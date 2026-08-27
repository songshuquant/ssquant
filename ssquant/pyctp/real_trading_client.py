#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
实盘交易客户端
支持连接期货公司实盘环境
"""

import os
import time
import threading
from typing import List, Dict, Callable, Optional
from datetime import datetime

from .md_api import MdApi, MdSpi
from .trader_api import TraderApi, TraderSpi, close_comb_offset_flag


def _swig_safe(fn):
    """
    SWIG director callback 兜底装饰器。

    CTP 的 OnXxx 回调由 C++ 网络线程经 SWIG director 直接调用 Python。
    一旦 Python 端抛出未捕获异常，异常经 SWIG 反弹回 C++ 线程会导致进程被系统
    __fastfail 直接终止（Windows 下表现为 0xC0000409 / 静默退出，无 traceback）。

    本装饰器把所有异常压在 Python 层吞掉并打印，CTP 线程恢复原状继续运行。
    用户策略的 on_order / on_trade 等回调若有 bug，也不会把整个进程带走。

    阈值告警:同名回调异常累计达到 _SWIG_SAFE_PANIC_THRESHOLD 时,打印 CRITICAL
    并触发 client.on_callback_panic(callback_name, count, last_exc_text)(若已设置)。
    避免异常被无限静默吞掉、监控失明。
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            import traceback
            # key 以 Spi 类名限定,避免 MdSpi/TraderSpi 同名回调(如 OnFrontConnected)共享计数位被串台
            spi = args[0] if args else None
            spi_cls = type(spi).__name__ if spi is not None else '<unknown>'
            name = f"{spi_cls}.{fn.__name__}"
            # MD/TD 是两个 CTP 网络线程,并发写入同一 dict;GIL 只保 get/set 单步,不保 get+set 组合
            with _swig_safe_lock:
                _swig_safe_counters[name] = _swig_safe_counters.get(name, 0) + 1
                count = _swig_safe_counters[name]
            print(f"[回调兜底] {name} 异常已吞掉 (累计{count}次): {e}")
            traceback.print_exc()
            if count == _SWIG_SAFE_PANIC_THRESHOLD or (count > _SWIG_SAFE_PANIC_THRESHOLD and count % _SWIG_SAFE_PANIC_THRESHOLD == 0):
                exc_text = f"{type(e).__name__}: {e}"
                print(f"\n{'!'*60}\n[CRITICAL] 回调 {name} 异常累计 {count} 次,疑似真实 bug,请排查!\n{'!'*60}\n")
                try:
                    client = getattr(spi, 'client', None) if spi is not None else None
                    cb = getattr(client, 'on_callback_panic', None) if client is not None else None
                    if callable(cb):
                        cb(name, count, exc_text)
                except Exception as panic_exc:
                    print(f"[回调兜底] on_callback_panic 自身也异常: {panic_exc}")
            return None
    return wrapper


# @_swig_safe 全局异常计数 + 阈值(模块级,跨 Spi 共享) + 锁(MD/TD 并发 panic 下保计数不丢)
_swig_safe_counters = {}
_swig_safe_lock = threading.Lock()
_SWIG_SAFE_PANIC_THRESHOLD = 10


class RealTradingMdSpi(MdSpi):
    """实盘行情回调"""
    
    def __init__(self, client, api):
        super().__init__(api)
        self.client = client
        self.connected = False
        self.logged_in = False
    
    @_swig_safe
    def OnFrontConnected(self):
        """行情前置连接（首次连接或断线重连）"""
        was_disconnected = hasattr(self, '_was_connected') and self._was_connected
        self._was_connected = True
        self.connected = True
        self.client._bump_conn_epoch()

        if was_disconnected:
            print("[行情] ✅ 服务器重连成功！正在重新登录...")
        else:
            print("[行情] 已连接到服务器")

        # 登录
        self.client.md_api.login(
            self.client.broker_id,
            self.client.investor_id,
            self.client.password
        )

    @_swig_safe
    def OnFrontDisconnected(self, nReason: int):
        """行情连接断开 - CTP会自动重连"""
        self.connected = False
        self.logged_in = False
        self.client._md_ready = False
        self.client._ready_event.clear()
        self.client._bump_conn_epoch()
        
        reason_map = {
            0x1001: '网络读取失败',
            0x1002: '网络写入失败', 
            0x2001: '接收心跳超时',
            0x2002: '发送心跳超时',
            0x2003: '收到错误报文',
        }
        reason_desc = reason_map.get(nReason, '未知原因')
        print(f"[行情] ⚠️ 服务器断开: {reason_desc}，CTP会自动重连...")
        if self.client.on_disconnected:
            self.client.on_disconnected('md', nReason)
    
    @_swig_safe
    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        """行情登录响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            # helper 定义在 TraderSpi 上,MdSpi 内部没有 —— 跨 Spi 走 client.trader_spi
            error_msg = self.client.trader_spi._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client.trader_spi._format_error_output(pRspInfo.ErrorID, error_msg)
            print(f"[行情] 登录失败: {full_msg}")
            return
        
        self.logged_in = True
        print("[行情] 登录成功")

        # 订阅行情
        if self.client.subscribe_list:
            self.client.md_api.subscribe_market_data(self.client.subscribe_list)
            print(f"[行情] 已订阅 {len(self.client.subscribe_list)} 个合约")

        self.client._md_ready = True
        self.client._check_ready()

        if self.client.on_md_login:
            self.client.on_md_login()
    
    @_swig_safe
    def OnRspSubMarketData(self, pSpecificInstrument, pRspInfo, nRequestID, bIsLast):
        """订阅行情响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            # helper 定义在 TraderSpi 上,MdSpi 内部没有 —— 跨 Spi 走 client.trader_spi
            error_msg = self.client.trader_spi._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client.trader_spi._format_error_output(pRspInfo.ErrorID, error_msg)
            print(f"[行情] 订阅失败: {full_msg}")
        else:
            print(f"[行情] 订阅成功: {pSpecificInstrument.InstrumentID}")
    
    @_swig_safe
    def OnRtnDepthMarketData(self, pDepthMarketData):
        """行情推送"""
        if self.client.on_market_data:
            # 基础字段
            data = {
                'InstrumentID': pDepthMarketData.InstrumentID,
                'TradingDay': pDepthMarketData.TradingDay,
                'ActionDay': pDepthMarketData.ActionDay,
                'UpdateTime': pDepthMarketData.UpdateTime,
                'UpdateMillisec': pDepthMarketData.UpdateMillisec,
                'LastPrice': pDepthMarketData.LastPrice,
                'Volume': pDepthMarketData.Volume,
                'OpenInterest': pDepthMarketData.OpenInterest,
                'HighestPrice': pDepthMarketData.HighestPrice,
                'LowestPrice': pDepthMarketData.LowestPrice,
                'OpenPrice': pDepthMarketData.OpenPrice,
                'PreClosePrice': pDepthMarketData.PreClosePrice,
                'PreSettlementPrice': pDepthMarketData.PreSettlementPrice,
                'UpperLimitPrice': pDepthMarketData.UpperLimitPrice,
                'LowerLimitPrice': pDepthMarketData.LowerLimitPrice,
            }
            
            # 自适应提取多档买卖盘数据（CTP支持1-5档）
            # 不同交易所返回的档位数不同：
            # - 上期所/大商所/郑商所/能源中心：通常1档
            # - 中金所：可能有5档
            for i in range(1, 6):
                bid_price_attr = f'BidPrice{i}'
                ask_price_attr = f'AskPrice{i}'
                bid_vol_attr = f'BidVolume{i}'
                ask_vol_attr = f'AskVolume{i}'
                
                # 检查属性是否存在且有效（CTP用极大值表示无效价格）
                if hasattr(pDepthMarketData, bid_price_attr):
                    bid_price = getattr(pDepthMarketData, bid_price_attr)
                    if bid_price < 1e10:
                        data[bid_price_attr] = bid_price
                
                if hasattr(pDepthMarketData, ask_price_attr):
                    ask_price = getattr(pDepthMarketData, ask_price_attr)
                    if ask_price < 1e10:
                        data[ask_price_attr] = ask_price
                
                if hasattr(pDepthMarketData, bid_vol_attr):
                    data[bid_vol_attr] = getattr(pDepthMarketData, bid_vol_attr)
                
                if hasattr(pDepthMarketData, ask_vol_attr):
                    data[ask_vol_attr] = getattr(pDepthMarketData, ask_vol_attr)
            
            self.client.on_market_data(data)


class RealTradingTraderSpi(TraderSpi):
    """实盘交易回调"""
    
    def __init__(self, client, api):
        super().__init__(api)
        self.client = client
        self.connected = False
        self.logged_in = False
        self.front_id = 0
        self.session_id = 0
        self.order_ref = 0
    
    def get_next_order_ref(self) -> str:
        """获取下一个报单引用"""
        self.order_ref += 1
        return str(self.order_ref).zfill(12)
    
    @_swig_safe
    def OnFrontConnected(self):
        """交易前置连接（首次连接或断线重连）"""
        was_disconnected = hasattr(self, '_was_connected') and self._was_connected
        self._was_connected = True
        self.connected = True
        self.client._bump_conn_epoch()

        if was_disconnected:
            print(f"\n{'='*60}")
            print("[交易] ✅ 服务器重连成功！正在重新认证...")
            print(f"{'='*60}\n")
        else:
            print("[交易] 已连接到服务器")

        # 产品认证
        self.client.trader_api.authenticate(
            self.client.broker_id,
            self.client.investor_id,
            self.client.app_id,
            self.client.auth_code
        )

    @_swig_safe
    def OnFrontDisconnected(self, nReason: int):
        """交易连接断开 - CTP会自动重连"""
        self.connected = False
        self.logged_in = False
        # 重连后从 3s 起重新退避,避免沿用上一次会话的高次数延迟
        self._auth_retry_count = 0
        self.client._trader_ready = False
        self.client._ready_event.clear()
        self.client._bump_conn_epoch()
        
        reason_map = {
            0x1001: '网络读取失败',
            0x1002: '网络写入失败', 
            0x2001: '接收心跳超时',
            0x2002: '发送心跳超时',
            0x2003: '收到错误报文',
        }
        reason_desc = reason_map.get(nReason, '未知原因')
        print(f"\n{'!'*60}")
        print(f"[交易] ⚠️ 服务器断开连接！")
        print(f"[交易] 原因码: {nReason:#x} ({nReason}) - {reason_desc}")
        print(f"[交易] 🔄 CTP会自动重连，请等待...")
        print(f"{'!'*60}\n")
        if self.client.on_disconnected:
            self.client.on_disconnected('trader', nReason)
    
    @_swig_safe
    def OnRspAuthenticate(self, pRspAuthenticateField, pRspInfo, nRequestID, bIsLast):
        """认证响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._format_error_output(pRspInfo.ErrorID, error_msg)
            print(f"[交易] 认证失败: {full_msg}")

            # 认证失败后持续重试（服务器可能还未完全就绪，如收盘后CTP自动重连）
            retry_count = getattr(self, '_auth_retry_count', 0)
            self._auth_retry_count = retry_count + 1
            delay = min(3 * (retry_count + 1), 30)  # 3s, 6s, 9s, ... 最长30s
            print(f"[交易] {delay}秒后重试认证 (第{self._auth_retry_count}次)...")
            # 捕获当前连接纪元,Timer 醒来后会比对;若纪元已变(被新连接或断线取代),_retry_authenticate 自动作废。
            # 读单个 int 在 CPython 下原子,无需持 _conn_epoch_lock (锁只保护 _bump_conn_epoch 的 read-modify-write)
            scheduled_epoch = self.client._conn_epoch
            threading.Timer(delay, self._retry_authenticate, args=[scheduled_epoch]).start()
            return

        self._auth_retry_count = 0  # 认证成功，重置计数器
        print("[交易] 认证成功")
        self._login()

    def _login(self):
        """向柜台发起登录请求。提取为方法便于与 simnow_client 对齐及重试复用。"""
        self.client.trader_api.login(
            self.client.broker_id,
            self.client.investor_id,
            self.client.password
        )

    def _retry_authenticate(self, scheduled_epoch: int = -1):
        """重试交易认证。scheduled_epoch 是排队时刻的连接纪元,若已变化说明连接状态已前进,作废。"""
        # 纪元校验:任何一次新连接或断线都会让 epoch 递增,这里一比对就知道排队时刻的"那次连接"是否还在。
        # 与 scheduled_epoch 捕获点一样,读 int 在 CPython 下原子,不需持锁。
        if scheduled_epoch != -1 and scheduled_epoch != self.client._conn_epoch:
            print(f"[交易] 重试认证作废(排队时纪元={scheduled_epoch}, 当前={self.client._conn_epoch}): 连接状态已变化")
            return
        if not self.connected:
            print("[交易] 连接已断开，取消认证重试")
            return
        if self.logged_in:
            return

        print("[交易] 正在重试认证...")
        try:
            self.client.trader_api.authenticate(
                self.client.broker_id,
                self.client.investor_id,
                self.client.app_id,
                self.client.auth_code
            )
        except Exception as e:
            print(f"[交易] 重试认证异常: {e}")
    
    @_swig_safe
    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        """交易登录响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[交易] 登录失败: {full_msg}")
            return
        
        self.logged_in = True
        print("[交易] 登录成功")
        print(f"[交易] 交易日: {pRspUserLogin.TradingDay}")
        
        # 保存前置编号和会话编号（撤单需要）
        if pRspUserLogin:
            self.front_id = pRspUserLogin.FrontID
            self.session_id = pRspUserLogin.SessionID
            # 从柜台返回的 MaxOrderRef 续号，避免同交易日重启后 OrderRef 与已有订单冲突被拒
            # 非空但非数值 = 协议异常,必须响亮报错 + 用时间戳种子保证新编号不会与旧的撞车
            raw_max = pRspUserLogin.MaxOrderRef
            if not raw_max:
                self.order_ref = 0
            else:
                try:
                    self.order_ref = int(raw_max)
                except (ValueError, TypeError):
                    safe_seed = int(time.time() * 1000) % 1_000_000_000
                    # 计入 _swig_safe_counters,让阈值告警机制能跨多次登录累计,避免被视作孤立事件
                    with _swig_safe_lock:
                        _swig_safe_counters['__MaxOrderRef_parse__'] = _swig_safe_counters.get('__MaxOrderRef_parse__', 0) + 1
                        count = _swig_safe_counters['__MaxOrderRef_parse__']
                    print(f"\n{'!'*60}")
                    print(f"[CRITICAL] MaxOrderRef 无法解析为数值: {raw_max!r} (累计{count}次)")
                    print(f"[CRITICAL] 使用时间戳种子 {safe_seed} 作为起始引用,避免静默撞号")
                    print(f"{'!'*60}\n")
                    self.order_ref = safe_seed
                    if self.client.on_callback_panic:
                        try:
                            self.client.on_callback_panic(
                                'MaxOrderRef_parse',
                                count,
                                f"non-numeric MaxOrderRef={raw_max!r}, seeded={safe_seed}"
                            )
                        except Exception:
                            pass
            print(f"[交易] 前置编号: {self.front_id}")
            print(f"[交易] 会话编号: {self.session_id}")
            print(f"[交易] 起始报单引用: {self.order_ref}")
        
        # 确认结算单
        self.client.trader_api.settlement_info_confirm(
            self.client.broker_id,
            self.client.investor_id
        )
    
    @_swig_safe
    def OnRspSettlementInfoConfirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID, bIsLast):
        """结算单确认响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[交易] 结算单确认失败: {full_msg}")
            return
        
        print("[交易] 结算单确认成功")
        
        self.client._trader_ready = True
        self.client._check_ready()
        
        if self.client.on_trader_ready:
            self.client.on_trader_ready()
    
    @_swig_safe
    def OnRtnOrder(self, pOrder):
        """报单回报"""
        if pOrder:
            # 检查是否是撤单成功
            if pOrder.OrderStatus == '5':
                # 旧版简单回调（向后兼容）
                if self.client.on_cancel_success:
                    self.client.on_cancel_success()
                
                # 新版详细撤单回调
                if self.client.on_cancel:
                    status_msg = self._clean_exchange_text(self._decode_error_msg(pOrder.StatusMsg)) if pOrder.StatusMsg else ""
                    cancel_data = {
                        'InstrumentID': pOrder.InstrumentID,
                        'OrderRef': pOrder.OrderRef,
                        'OrderSysID': pOrder.OrderSysID,
                        'FrontID': getattr(pOrder, 'FrontID', None),
                        'SessionID': getattr(pOrder, 'SessionID', None),
                        'Direction': pOrder.Direction,
                        'CombOffsetFlag': pOrder.CombOffsetFlag,
                        'LimitPrice': pOrder.LimitPrice,
                        'VolumeTotalOriginal': pOrder.VolumeTotalOriginal,
                        'VolumeTraded': pOrder.VolumeTraded,
                        'VolumeTotal': pOrder.VolumeTotal,
                        'ExchangeID': pOrder.ExchangeID,
                        'InsertTime': pOrder.InsertTime if hasattr(pOrder, 'InsertTime') else '',
                        'CancelTime': pOrder.CancelTime if hasattr(pOrder, 'CancelTime') else '',
                        'StatusMsg': status_msg,
                    }
                    self.client.on_cancel(cancel_data)
            
            # 报单回调
            if self.client.on_order:
                # 解码状态消息（可能是GBK编码）
                status_msg = self._clean_exchange_text(self._decode_error_msg(pOrder.StatusMsg)) if pOrder.StatusMsg else ""
                
                data = {
                    'OrderRef': pOrder.OrderRef,
                    'OrderSysID': pOrder.OrderSysID,
                    'FrontID': getattr(pOrder, 'FrontID', None),
                    'SessionID': getattr(pOrder, 'SessionID', None),
                    'InstrumentID': pOrder.InstrumentID,
                    'Direction': pOrder.Direction,
                    'CombOffsetFlag': pOrder.CombOffsetFlag,
                    'LimitPrice': pOrder.LimitPrice,
                    'VolumeTotalOriginal': pOrder.VolumeTotalOriginal,
                    'VolumeTraded': pOrder.VolumeTraded,
                    'VolumeTotal': pOrder.VolumeTotal,
                    'OrderStatus': pOrder.OrderStatus,
                    'ExchangeID': pOrder.ExchangeID,  # 交易所代码
                    'InsertTime': pOrder.InsertTime if hasattr(pOrder, 'InsertTime') else '',
                    'StatusMsg': status_msg,
                }
                self.client.on_order(data)
    
    @_swig_safe
    def OnRtnTrade(self, pTrade):
        """成交回报"""
        if pTrade:
            instrument_id = pTrade.InstrumentID
            
            # 触发用户回调
            if self.client.on_trade:
                data = {
                    'InstrumentID': instrument_id,
                    'OrderRef': pTrade.OrderRef,
                    'Direction': pTrade.Direction,
                    'OffsetFlag': pTrade.OffsetFlag,
                    'Price': pTrade.Price,
                    'Volume': pTrade.Volume,
                    'TradeTime': pTrade.TradeTime,
                    'TradeDate': pTrade.TradeDate,
                    'TradeID': pTrade.TradeID,
                }
                self.client.on_trade(data)
            
            # 检查是否需要刷新持仓（平今→平昨重试后的成交）
            if hasattr(self.client, '_pending_position_refresh'):
                if instrument_id in self.client._pending_position_refresh:
                    self.client._pending_position_refresh.discard(instrument_id)
                    print(f"[持仓刷新] 平昨成交，刷新 {instrument_id} 持仓...")
                    # 延迟一点再查询，确保成交处理完成
                    def refresh():
                        time.sleep(0.5)  # 只需要短暂延迟
                        self.client.query_position(instrument_id)
                    threading.Thread(target=refresh, daemon=True).start()
    
    @_swig_safe
    def OnRspOrderInsert(self, pInputOrder, pRspInfo, nRequestID, bIsLast):
        """报单错误"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._format_error_output(pRspInfo.ErrorID, error_msg)
            
            # 错误50：平今仓位不足 - 智能重试平昨（先检查是否有昨仓）
            if pRspInfo.ErrorID == 50 and pInputOrder:
                offset_flag = pInputOrder.CombOffsetFlag[0] if pInputOrder.CombOffsetFlag else ''
                if offset_flag == '3':  # 平今仓失败
                    instrument_id = pInputOrder.InstrumentID
                    direction = pInputOrder.Direction  # '0'=买, '1'=卖
                    
                    # 检查持仓缓存，判断是否有昨仓可平
                    pos_cache = self.client._position_cache.get(instrument_id, {})
                    # 买平 → 平空头, 卖平 → 平多头
                    yd_pos = pos_cache.get('short_yd', 0) if direction == '0' else pos_cache.get('long_yd', 0)
                    
                    if yd_pos > 0:
                        # 有昨仓，可以重试平昨
                        print(f"[交易] 平今失败，检测到昨仓{yd_pos}手，自动改为平昨重试...")
                        # 标记该品种需要在成交后刷新持仓
                        if not hasattr(self.client, '_pending_position_refresh'):
                            self.client._pending_position_refresh = set()
                        self.client._pending_position_refresh.add(instrument_id)
                        # 重新发送平昨订单
                        self.client._send_order(
                            instrument_id,
                            direction,
                            '4',  # 改为平昨
                            pInputOrder.LimitPrice,
                            pInputOrder.VolumeTotalOriginal
                        )
                        return  # 不触发错误回调，等待重试结果
                    else:
                        # 没有昨仓，不重试，直接报错
                        print(f"[交易] 平今失败，但无昨仓可平，不重试")
            
            # 获取品种信息
            instrument_id = pInputOrder.InstrumentID if pInputOrder else "未知品种"
            print(f"[交易] 报单失败: {instrument_id} - {full_msg}")
            if self.client.on_order_error:
                self.client.on_order_error(pRspInfo.ErrorID, full_msg, instrument_id)
    
    @_swig_safe
    def OnRspOrderAction(self, pInputOrderAction, pRspInfo, nRequestID, bIsLast):
        """撤单请求响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._format_error_output(pRspInfo.ErrorID, error_msg)
            print(f"[撤单] 请求失败: {full_msg}")
            if self.client.on_cancel_error:
                self.client.on_cancel_error(pRspInfo.ErrorID, full_msg)
        else:
            # 撤单请求已接受，等待报单状态变为'5'时才真正撤单成功
            print(f"[撤单] 请求已接受，等待确认...")
    
    @_swig_safe
    def OnRspQryTradingAccount(self, pTradingAccount, pRspInfo, nRequestID, bIsLast):
        """资金查询响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._format_error_output(pRspInfo.ErrorID, error_msg)
            print(f"[查询] 资金查询失败: {full_msg}")
            return
        
        if pTradingAccount and self.client.on_account:
            data = {
                'AccountID': pTradingAccount.AccountID,
                'PreBalance': pTradingAccount.PreBalance,
                'Balance': pTradingAccount.Balance,
                'Available': pTradingAccount.Available,
                'CurrMargin': pTradingAccount.CurrMargin,
                'Commission': pTradingAccount.Commission,
                'CloseProfit': pTradingAccount.CloseProfit,
                'PositionProfit': pTradingAccount.PositionProfit,
                'Deposit': pTradingAccount.Deposit,
                'Withdraw': pTradingAccount.Withdraw,
            }
            self.client.on_account(data)
    
    @_swig_safe
    def OnRspQryInvestorPosition(self, pInvestorPosition, pRspInfo, nRequestID, bIsLast):
        """持仓查询响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._format_error_output(pRspInfo.ErrorID, error_msg)
            print(f"[持仓] 查询失败: {full_msg}")
            return
        
        if pInvestorPosition and self.client.on_position:
            data = {
                'InstrumentID': pInvestorPosition.InstrumentID,
                'PosiDirection': pInvestorPosition.PosiDirection,
                'Position': pInvestorPosition.Position,
                'TodayPosition': pInvestorPosition.TodayPosition,
                'YdPosition': pInvestorPosition.YdPosition,
                'OpenVolume': pInvestorPosition.OpenVolume,
                'CloseVolume': pInvestorPosition.CloseVolume,
                'PositionCost': pInvestorPosition.PositionCost,
                'PositionProfit': pInvestorPosition.PositionProfit,
                'UseMargin': pInvestorPosition.UseMargin,
                'OpenCost': pInvestorPosition.OpenCost,
            }
            direction_map = {'1': '净', '2': '多', '3': '空'}
            direction = direction_map.get(data['PosiDirection'], '未知')
            
            # 判断持仓状态并给出清晰的日志
            position = data['Position']
            today_pos = data['TodayPosition']
            yd_pos = data['YdPosition']
            
            # 持仓状态由用户回调自行处理，框架保持安静
            
            # 更新内部持仓缓存（用于智能重试判断）
            # 【关键修复】使用累加模式，因为CTP可能对同一品种分多次回调（今仓/昨仓分开）
            instrument_id = data['InstrumentID']
            if instrument_id not in self.client._position_cache:
                self.client._position_cache[instrument_id] = {
                    'long_yd': 0, 'short_yd': 0, 'long_today': 0, 'short_today': 0
                }
            
            # 【关键修复】上海期货交易所(SHFE)和能源交易中心(INE)的YdPosition字段不可靠
            # 正确的昨仓计算方式：昨仓 = 总持仓 - 今仓
            # 这样无论哪个交易所都能正确计算昨仓
            calculated_yd_pos = position - today_pos
            
            # 【累加模式】同一品种可能有多条持仓记录，需要累加
            if data['PosiDirection'] == '2':  # 多头
                self.client._position_cache[instrument_id]['long_today'] += today_pos
                self.client._position_cache[instrument_id]['long_yd'] += calculated_yd_pos
            elif data['PosiDirection'] == '3':  # 空头
                self.client._position_cache[instrument_id]['short_today'] += today_pos
                self.client._position_cache[instrument_id]['short_yd'] += calculated_yd_pos
            
            self.client.on_position(data)
        
        if bIsLast and self.client.on_position_complete:
            self.client.on_position_complete()
    
    @_swig_safe
    def OnRspQryOrder(self, pOrder, pRspInfo, nRequestID, bIsLast):
        """订单查询响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._format_error_output(pRspInfo.ErrorID, error_msg)
            print(f"[查询] 订单查询失败: {full_msg}")
            return
        
        if pOrder and self.client.on_query_order:
            status_msg = self._clean_exchange_text(self._decode_error_msg(pOrder.StatusMsg)) if pOrder.StatusMsg else ""
            data = {
                'InstrumentID': pOrder.InstrumentID,
                'ExchangeID': pOrder.ExchangeID,
                'OrderRef': pOrder.OrderRef,
                'OrderSysID': pOrder.OrderSysID,
                'Direction': pOrder.Direction,
                'CombOffsetFlag': pOrder.CombOffsetFlag,
                'LimitPrice': pOrder.LimitPrice,
                'VolumeTotalOriginal': pOrder.VolumeTotalOriginal,
                'VolumeTraded': pOrder.VolumeTraded,
                'VolumeTotal': pOrder.VolumeTotal,
                'OrderStatus': pOrder.OrderStatus,
                'InsertDate': pOrder.InsertDate,
                'InsertTime': pOrder.InsertTime,
                'StatusMsg': status_msg,
            }
            self.client.on_query_order(data)
        
        if bIsLast and self.client.on_query_order_complete:
            self.client.on_query_order_complete()
    
    @_swig_safe
    def OnRspQryTrade(self, pTrade, pRspInfo, nRequestID, bIsLast):
        """成交查询响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._format_error_output(pRspInfo.ErrorID, error_msg)
            print(f"[查询] 成交查询失败: {full_msg}")
            return
        
        if pTrade and self.client.on_query_trade:
            data = {
                'TradeID': pTrade.TradeID,
                'OrderRef': pTrade.OrderRef,
                'InstrumentID': pTrade.InstrumentID,
                'Direction': pTrade.Direction,
                'OffsetFlag': pTrade.OffsetFlag,
                'Price': pTrade.Price,
                'Volume': pTrade.Volume,
                'TradeDate': pTrade.TradeDate,
                'TradeTime': pTrade.TradeTime,
            }
            self.client.on_query_trade(data)
        
        if bIsLast and self.client.on_query_trade_complete:
            self.client.on_query_trade_complete()
    
    def _decode_error_msg(self, error_msg):
        """解码错误消息（处理GBK编码）"""
        if isinstance(error_msg, bytes):
            try:
                return error_msg.decode('gb18030')
            except:
                try:
                    return error_msg.decode('gbk')
                except:
                    try:
                        return error_msg.decode('utf-8')
                    except:
                        # 最后的手段：返回Hex，方便排查
                        return f"RawBytes({error_msg.hex()})"
        elif isinstance(error_msg, str):
            # 检查是否包含乱码字符
            if any(ord(c) == 0xFFFD for c in error_msg): # replacement character
                 return "解码失败(含替换符)"
            try:
                return error_msg.encode('latin1').decode('gb18030')
            except:
                pass
        return str(error_msg)

    def _is_garbled_text(self, text: str) -> bool:
        """粗略判断文本是否已乱码。"""
        if not text:
            return False
        if text.startswith("RawBytes(") or text == "解码失败(含替换符)":
            return True
        suspicious = 0
        for ch in text[:40]:
            code = ord(ch)
            if 127 < code < 256:
                suspicious += 1
        return suspicious >= 3

    def _clean_exchange_text(self, text: str) -> str:
        """清理交易所原始文本，明显乱码时直接隐藏。"""
        text = str(text or "").strip()
        if not text or self._is_garbled_text(text):
            return ""
        return text
    
    def _get_error_desc(self, error_id: int, error_msg: str) -> str:
        """获取错误描述（添加常见错误的中文说明）"""
        error_descriptions = {
            1: "CTP:综合交易平台:不在交易时段",
            2: "CTP:综合交易平台:未授权",
            3: "CTP:综合交易平台:不合法的登录",
            22: "合约不存在或未订阅",
            23: "报单价格不合法",
            30: "平仓数量超出持仓数量",
            31: "报单超过最大下单量",
            36: "资金不足",
            42: "成交价格不合法",
            44: "价格超出涨跌停板限制",
            50: "平今仓位不足，请改用平昨仓",
            51: "持仓不足或持仓方向错误",
            58: "报单已撤销",
            63: "重复报单",
            68: "每秒报单数超过限制",
            76: "撤单已提交到交易所，请稍后",
            81: "风控原因拒绝报单",
            85: "非法报单，CTP拒绝",
            90: "休眠时间不允许报单",
            91: "错误的开仓标志",
            95: "CTP不支持的价格类型（限价单/市价单）",
        }
        
        # 如果有预定义描述，直接使用（避免乱码）
        desc = error_descriptions.get(error_id, "")
        if desc:
            return desc
        
        # 否则尝试解码原始消息
        if error_msg:
            # 尝试清理乱码
            try:
                # 如果消息看起来是乱码，就不显示
                if any(ord(c) > 127 and ord(c) < 256 for c in error_msg[:20]):
                    return f"未知错误（错误码: {error_id}）"
            except:
                pass
            return error_msg
        return f"未知错误（错误码: {error_id}）"

    def _format_error_output(self, error_id: int, error_msg: str) -> str:
        """统一输出：错误码 + 中文解释，原始消息仅在可读时附带。"""
        clean_msg = self._clean_exchange_text(error_msg)
        desc = self._get_error_desc(error_id, clean_msg)
        if clean_msg and clean_msg != desc and clean_msg not in desc:
            return f"错误码={error_id} - {desc} | 原始消息: {clean_msg}"
        return f"错误码={error_id} - {desc}"


class RealTradingClient:
    """
    实盘交易客户端
    用于连接期货公司实盘环境
    """
    
    def __init__(
        self,
        broker_id: str,
        investor_id: str,
        password: str,
        md_server: str,
        td_server: str,
        app_id: str,
        auth_code: str,
        subscribe_list: Optional[List[str]] = None,
        md_flow_path: str = "./real_md_flow",
        td_flow_path: str = "./real_td_flow",
        resume_mode: int = 2,
    ):
        """
        初始化实盘客户端

        Args:
            broker_id: 期货公司BrokerID
            investor_id: 投资者账号
            password: 密码
            md_server: 行情服务器地址 (格式: "tcp://ip:port")
            td_server: 交易服务器地址 (格式: "tcp://ip:port")
            app_id: 产品认证AppID
            auth_code: 产品认证授权码
            subscribe_list: 订阅合约列表
            md_flow_path: 行情流文件路径
            td_flow_path: 交易流文件路径
            resume_mode: 私有/公共流续传模式,传给 SubscribePrivate/PublicTopic
                0=RESTART(重播当日全部), 1=RESUME(断点续传),
                2=QUICK(仅收新消息,默认), 3=NONE(不接收)
        """
        self.broker_id = broker_id
        self.investor_id = investor_id
        self.password = password
        self.md_server = md_server
        self.td_server = td_server
        self.app_id = app_id
        self.auth_code = auth_code
        self.subscribe_list = subscribe_list or []
        self._resume_mode = resume_mode
        
        # 创建流文件目录
        os.makedirs(md_flow_path, exist_ok=True)
        os.makedirs(td_flow_path, exist_ok=True)
        
        # 创建 API
        self.md_api = MdApi(md_flow_path)
        self.trader_api = TraderApi(td_flow_path)
        
        # 创建 Spi
        self.md_spi = RealTradingMdSpi(self, self.md_api)
        self.trader_spi = RealTradingTraderSpi(self, self.trader_api)

        # 注册回调
        self.md_api.register_spi(self.md_spi)
        self.trader_api.register_spi(self.trader_spi)
        
        # 就绪标志
        self._md_ready = False
        self._trader_ready = False
        self._ready_event = threading.Event()
        
        # 用户回调
        self.on_market_data: Optional[Callable] = None
        self.on_order: Optional[Callable] = None
        self.on_trade: Optional[Callable] = None
        self.on_cancel: Optional[Callable] = None  # 撤单回调（新增，包含详细信息）
        self.on_order_error: Optional[Callable] = None
        self.on_cancel_success: Optional[Callable] = None  # 保留向后兼容
        self.on_cancel_error: Optional[Callable] = None
        self.on_account: Optional[Callable] = None
        self.on_position: Optional[Callable] = None
        self.on_position_complete: Optional[Callable] = None
        self.on_query_order: Optional[Callable] = None
        self.on_query_order_complete: Optional[Callable] = None
        self.on_query_trade: Optional[Callable] = None
        self.on_query_trade_complete: Optional[Callable] = None
        self.on_md_login: Optional[Callable] = None
        self.on_trader_ready: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None
        
        # 内部持仓缓存（用于智能重试判断）
        # 格式: {instrument_id: {'long_yd': 0, 'short_yd': 0, 'long_today': 0, 'short_today': 0}}
        self._position_cache = {}

        # 查询流控：CTP 规定查询类请求 1 秒最多 1 次，相邻调用间隔不够时补齐
        self._last_query_ts = 0.0
        self._query_lock = threading.Lock()

        # 连接纪元号:每次 OnFrontConnected / OnFrontDisconnected 递增,
        # 用于让 _retry_authenticate 的 threading.Timer 能识别出"我排队的时候
        # 的那次连接"是不是已经过期(被新连接或新断线取代),避免重连后重复认证。
        self._conn_epoch = 0
        self._conn_epoch_lock = threading.Lock()

        # 回调兜底阈值触发的 panic 回调:on_callback_panic(name, count, exc_text)
        self.on_callback_panic: Optional[Callable] = None

    def _throttle_query(self, min_interval: float = 1.0):
        """CTP 查询流控：仅补齐距上次查询不足的时间，避免每次无条件 sleep 阻塞策略线程"""
        with self._query_lock:
            now = time.time()
            gap = now - self._last_query_ts
            if gap < min_interval:
                time.sleep(min_interval - gap)
            self._last_query_ts = time.time()

    def _bump_conn_epoch(self) -> int:
        """递增连接纪元号并返回新值。任何 OnFrontConnected / OnFrontDisconnected 必须调用,
        这样前一批 threading.Timer 排队的 _retry_authenticate 醒来后可以自检作废。"""
        with self._conn_epoch_lock:
            self._conn_epoch += 1
            return self._conn_epoch
    
    def is_connected(self):
        """检查是否已连接"""
        return self.md_spi.connected and self.trader_spi.connected
    
    def is_ready(self):
        """检查是否就绪（行情+交易均已登录）"""
        return (
            self._md_ready
            and self._trader_ready
            and self.md_spi.connected
            and self.md_spi.logged_in
            and self.trader_spi.connected
            and self.trader_spi.logged_in
        )
    
    def _check_ready(self):
        """检查是否就绪"""
        if self._md_ready and self._trader_ready:
            self._ready_event.set()
            print("\n" + "=" * 80)
            print("实盘系统已就绪！")
            print("=" * 80 + "\n")
    
    def connect(self):
        """连接服务器"""
        print("=" * 80)
        print("正在连接实盘服务器...")
        print(f"期货公司: {self.broker_id}")
        print(f"账号: {self.investor_id}")
        print(f"行情服务器: {self.md_server}")
        print(f"交易服务器: {self.td_server}")
        print("=" * 80 + "\n")
        
        # 注册前置
        self.md_api.register_front(self.md_server)
        self.trader_api.register_front(self.td_server)

        # CTP 要求 Init() 之前必须订阅私有/公共流，否则部分柜台会触发栈破坏崩溃（0xC0000409）
        # resume_mode: 0=RESTART 1=RESUME 2=QUICK 3=NONE(默认 2,仅收新消息)
        self.trader_api.subscribe_private_topic(self._resume_mode)
        self.trader_api.subscribe_public_topic(self._resume_mode)

        # 初始化
        self.md_api.init()
        self.trader_api.init()
    
    def wait_ready(self, timeout: int = 30):
        """等待系统就绪"""
        if not self._ready_event.wait(timeout):
            raise TimeoutError("连接超时")
    
    def release(self):
        """释放资源"""
        self.md_api.release()
        self.trader_api.release()
    
    # ========== 交易方法 ==========
    
    def buy_open(self, instrument_id: str, price: float, volume: int) -> str:
        """买入开仓"""
        return self._send_order(instrument_id, '0', '0', price, volume)
    
    def sell_close(self, instrument_id: str, price: float, volume: int, close_today: bool = True) -> str:
        """
        卖平
        
        Args:
            instrument_id: 合约代码
            price: 价格
            volume: 数量
            close_today: True=平今仓('3'), False=平昨仓('4')
        """
        offset_flag = close_comb_offset_flag(close_today, instrument_id)
        return self._send_order(instrument_id, '1', offset_flag, price, volume)
    
    def sell_open(self, instrument_id: str, price: float, volume: int) -> str:
        """卖出开仓"""
        return self._send_order(instrument_id, '1', '0', price, volume)
    
    def buy_close(self, instrument_id: str, price: float, volume: int, close_today: bool = True) -> str:
        """
        买平
        
        Args:
            instrument_id: 合约代码
            price: 价格
            volume: 数量
            close_today: True=平今仓('3'), False=平昨仓('4')
        """
        offset_flag = close_comb_offset_flag(close_today, instrument_id)
        return self._send_order(instrument_id, '0', offset_flag, price, volume)
    
    def _send_order(self, instrument_id: str, direction: str, offset_flag: str,
                    price: float, volume: int) -> Optional[str]:
        """发送报单"""
        # 【关键修复】发送订单前检查连接状态
        if not self.is_ready():
            reason = (
                f"CTP客户端未就绪 - "
                f"md连接={self.md_spi.connected}/登录={self.md_spi.logged_in}, "
                f"trader连接={self.trader_spi.connected}/登录={self.trader_spi.logged_in}"
            )
            print(f"❌ [下单失败] {reason}")
            print(f"   - 合约: {instrument_id}, 价格: {price}, 数量: {volume}")
            # 走 on_order_error 回调让策略监控通道能感知,不再仅 stdout 可见
            # 使用自定义错误码 -1 区别于 CTP 柜台错误
            if self.on_order_error:
                try:
                    self.on_order_error(-1, reason, instrument_id)
                except Exception as cb_exc:
                    print(f"[下单失败] on_order_error 回调自身异常: {cb_exc}")
            return None
        
        order_ref = self.trader_spi.get_next_order_ref()
        self.trader_api.order_insert(
            broker_id=self.broker_id,
            investor_id=self.investor_id,
            instrument_id=instrument_id,
            order_ref=order_ref,
            direction=direction,
            offset_flag=offset_flag,
            price=price,
            volume=volume
        )
        return order_ref
    
    def cancel_order(self, instrument_id: str, order_sys_id: str, exchange_id: str = ""):
        """
        撤单
        :param instrument_id: 合约代码
        :param order_sys_id: 交易所报单编号
        :param exchange_id: 交易所代码（不传则根据合约自动推导）
        """
        # 如果未指定交易所代码，自动推导
        if not exchange_id:
            from .trader_api import _get_exchange_id
            exchange_id = _get_exchange_id(instrument_id) or 'SHFE'
        
        order_ref = self.trader_spi.get_next_order_ref()
        self.trader_api.order_action(
            broker_id=self.broker_id,
            investor_id=self.investor_id,
            order_sys_id=order_sys_id,
            exchange_id=exchange_id,
            front_id=self.trader_spi.front_id,
            session_id=self.trader_spi.session_id,
            order_ref=order_ref
        )
        print(f"[撤单] 合约: {instrument_id}, 系统编号: {order_sys_id}")
    
    # ========== 查询方法 ==========
    
    def query_account(self):
        """查询资金"""
        self._throttle_query()
        self.trader_api.qry_trading_account(self.broker_id, self.investor_id)
    
    def query_position(self, instrument_id: str = ""):
        """查询持仓"""
        # 查询前清空缓存（因为回调使用累加模式）
        if instrument_id:
            # 查询特定品种，只清空该品种的缓存
            if instrument_id in self._position_cache:
                self._position_cache[instrument_id] = {
                    'long_yd': 0, 'short_yd': 0, 'long_today': 0, 'short_today': 0
                }
        else:
            # 查询全部，清空所有缓存
            self._position_cache.clear()
        self._throttle_query()
        self.trader_api.qry_investor_position(
            self.broker_id, self.investor_id, instrument_id
        )

    def query_orders(self, instrument_id: str = ""):
        """查询订单"""
        self._throttle_query()
        self.trader_api.qry_order(
            self.broker_id, self.investor_id, instrument_id
        )
    
    def query_trades(self, instrument_id: str = ""):
        """查询成交"""
        self._throttle_query()
        self.trader_api.qry_trade(
            self.broker_id, self.investor_id, instrument_id
        )

    # ========== 行情订阅（运行时动态订阅/退订） ==========

    def subscribe(self, instruments: List[str]):
        """动态订阅行情（需在行情登录后调用）"""
        if not self._md_ready:
            raise RuntimeError("行情尚未登录，无法订阅")
        self.md_api.subscribe_market_data(instruments)

    def unsubscribe(self, instruments: List[str]):
        """取消订阅行情"""
        if not self._md_ready:
            raise RuntimeError("行情尚未登录，无法退订")
        self.md_api.unsubscribe_market_data(instruments)

