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
from .trader_api import TraderApi, TraderSpi


class RealTradingMdSpi(MdSpi):
    """实盘行情回调"""
    
    def __init__(self, client, api):
        super().__init__(api)
        self.client = client
    
    def OnFrontConnected(self):
        """行情前置连接"""
        print("[行情] 已连接到服务器")
        # 登录
        self.client.md_api.login(
            self.client.broker_id,
            self.client.investor_id,
            self.client.password
        )
    
    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        """行情登录响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self.client._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[行情] 登录失败: {full_msg}")
            return
        
        print("[行情] 登录成功")
        
        # 订阅行情
        if self.client.subscribe_list:
            self.client.md_api.subscribe_market_data(self.client.subscribe_list)
            print(f"[行情] 已订阅 {len(self.client.subscribe_list)} 个合约")
        
        self.client._md_ready = True
        self.client._check_ready()
    
    def OnRspSubMarketData(self, pSpecificInstrument, pRspInfo, nRequestID, bIsLast):
        """订阅行情响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self.client._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[行情] 订阅失败: {full_msg}")
        else:
            print(f"[行情] 订阅成功: {pSpecificInstrument.InstrumentID}")
    
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
        self.front_id = 0
        self.session_id = 0
        self.order_ref = 0
    
    def get_next_order_ref(self) -> str:
        """获取下一个报单引用"""
        self.order_ref += 1
        return str(self.order_ref)
    
    def OnFrontConnected(self):
        """交易前置连接"""
        print("[交易] 已连接到服务器")
        # 产品认证
        self.client.trader_api.authenticate(
            self.client.broker_id,
            self.client.investor_id,
            self.client.app_id,
            self.client.auth_code
        )
    
    def OnRspAuthenticate(self, pRspAuthenticateField, pRspInfo, nRequestID, bIsLast):
        """认证响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[交易] 认证失败: {full_msg}")
            return
        
        print("[交易] 认证成功")
        
        # 登录
        self.client.trader_api.login(
            self.client.broker_id,
            self.client.investor_id,
            self.client.password
        )
    
    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        """交易登录响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[交易] 登录失败: {full_msg}")
            return
        
        print("[交易] 登录成功")
        print(f"[交易] 交易日: {pRspUserLogin.TradingDay}")
        
        # 保存前置编号和会话编号（撤单需要）
        if pRspUserLogin:
            self.front_id = pRspUserLogin.FrontID
            self.session_id = pRspUserLogin.SessionID
            print(f"[交易] 前置编号: {self.front_id}")
            print(f"[交易] 会话编号: {self.session_id}")
        
        # 确认结算单
        self.client.trader_api.settlement_info_confirm(
            self.client.broker_id,
            self.client.investor_id
        )
    
    def OnRspSettlementInfoConfirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID, bIsLast):
        """结算单确认响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[交易] 结算单确认失败: {full_msg}")
            return
        
        print("[交易] 结算单确认成功")
        
        self.client._trader_ready = True
        self.client._check_ready()
        
        if self.client.on_trader_ready:
            self.client.on_trader_ready()
    
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
                    status_msg = self._decode_error_msg(pOrder.StatusMsg) if pOrder.StatusMsg else ""
                    cancel_data = {
                        'InstrumentID': pOrder.InstrumentID,
                        'OrderRef': pOrder.OrderRef,
                        'OrderSysID': pOrder.OrderSysID,
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
                status_msg = self._decode_error_msg(pOrder.StatusMsg) if pOrder.StatusMsg else ""
                
                data = {
                    'OrderRef': pOrder.OrderRef,
                    'OrderSysID': pOrder.OrderSysID,
                    'InstrumentID': pOrder.InstrumentID,
                    'Direction': pOrder.Direction,
                    'CombOffsetFlag': pOrder.CombOffsetFlag,
                    'LimitPrice': pOrder.LimitPrice,
                    'VolumeTotalOriginal': pOrder.VolumeTotalOriginal,
                    'VolumeTraded': pOrder.VolumeTraded,
                    'VolumeTotal': pOrder.VolumeTotal,
                    'OrderStatus': pOrder.OrderStatus,
                    'ExchangeID': pOrder.ExchangeID,  # 交易所代码
                    'StatusMsg': status_msg,
                }
                self.client.on_order(data)
    
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
                    import threading
                    def refresh():
                        import time
                        time.sleep(0.5)  # 只需要短暂延迟
                        self.client.query_position(instrument_id)
                    threading.Thread(target=refresh, daemon=True).start()
    
    def OnRspOrderInsert(self, pInputOrder, pRspInfo, nRequestID, bIsLast):
        """报单错误"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            
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
            
            print(f"[交易] 报单失败: {pRspInfo.ErrorID} - {full_msg}")
            if self.client.on_order_error:
                self.client.on_order_error(pRspInfo.ErrorID, full_msg)
    
    def OnRspOrderAction(self, pInputOrderAction, pRspInfo, nRequestID, bIsLast):
        """撤单请求响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            print(f"[撤单] 请求失败: {pRspInfo.ErrorID} - {error_msg}")
            if self.client.on_cancel_error:
                self.client.on_cancel_error(pRspInfo.ErrorID, error_msg)
        else:
            # 撤单请求已接受，等待报单状态变为'5'时才真正撤单成功
            print(f"[撤单] 请求已接受，等待确认...")
    
    def OnRspQryTradingAccount(self, pTradingAccount, pRspInfo, nRequestID, bIsLast):
        """资金查询响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client._get_error_desc(pRspInfo.ErrorID, error_msg)
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
    
    def OnRspQryInvestorPosition(self, pInvestorPosition, pRspInfo, nRequestID, bIsLast):
        """持仓查询响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client._get_error_desc(pRspInfo.ErrorID, error_msg)
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
            
            if position == 0:
                # 总持仓为0，说明无持仓
                if today_pos > 0 or yd_pos > 0:
                    # 如果今昨仓不为0，说明CTP系统数据未完全同步
                    print(f"[持仓] {data['InstrumentID']} {direction} "
                          f"总持仓: {position} (今:{today_pos} 昨:{yd_pos} - CTP数据同步延迟，实际已无持仓)")
                else:
                    print(f"[持仓] {data['InstrumentID']} {direction} 无持仓")
            else:
                # 有持仓，正常显示
                print(f"[持仓] {data['InstrumentID']} {direction} "
                      f"总持仓: {position} (今:{today_pos} 昨:{yd_pos})")
            
            # 更新内部持仓缓存（用于智能重试判断）
            instrument_id = data['InstrumentID']
            if instrument_id not in self.client._position_cache:
                self.client._position_cache[instrument_id] = {
                    'long_yd': 0, 'short_yd': 0, 'long_today': 0, 'short_today': 0
                }
            
            if data['PosiDirection'] == '2':  # 多头
                self.client._position_cache[instrument_id]['long_today'] = today_pos
                self.client._position_cache[instrument_id]['long_yd'] = yd_pos
            elif data['PosiDirection'] == '3':  # 空头
                self.client._position_cache[instrument_id]['short_today'] = today_pos
                self.client._position_cache[instrument_id]['short_yd'] = yd_pos
            
            self.client.on_position(data)
        
        if bIsLast and self.client.on_position_complete:
            print(f"[持仓] 查询完成")
            self.client.on_position_complete()
    
    def OnRspQryOrder(self, pOrder, pRspInfo, nRequestID, bIsLast):
        """订单查询响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[查询] 订单查询失败: {full_msg}")
            return
        
        if pOrder and self.client.on_query_order:
            data = {
                'InstrumentID': pOrder.InstrumentID,
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
            }
            self.client.on_query_order(data)
        
        if bIsLast and self.client.on_query_order_complete:
            self.client.on_query_order_complete()
    
    def OnRspQryTrade(self, pTrade, pRspInfo, nRequestID, bIsLast):
        """成交查询响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self.client._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[查询] 成交查询失败: {full_msg}")
            return
        
        if pTrade and self.client.on_query_trade:
            data = {
                'TradeID': pTrade.TradeID,
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
        """
        self.broker_id = broker_id
        self.investor_id = investor_id
        self.password = password
        self.md_server = md_server
        self.td_server = td_server
        self.app_id = app_id
        self.auth_code = auth_code
        self.subscribe_list = subscribe_list or []
        
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
        self.on_trader_ready: Optional[Callable] = None
        
        # 内部持仓缓存（用于智能重试判断）
        # 格式: {instrument_id: {'long_yd': 0, 'short_yd': 0, 'long_today': 0, 'short_today': 0}}
        self._position_cache = {}
    
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
        # 上期所需要明确区分平今/平昨，默认平今
        offset_flag = '3' if close_today else '4'
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
        # 上期所需要明确区分平今/平昨，默认平今
        offset_flag = '3' if close_today else '4'
        return self._send_order(instrument_id, '0', offset_flag, price, volume)
    
    def _send_order(self, instrument_id: str, direction: str, offset_flag: str,
                    price: float, volume: int) -> str:
        """发送报单"""
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
    
    def cancel_order(self, instrument_id: str, order_sys_id: str, exchange_id: str = "SHFE"):
        """撤单"""
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
        time.sleep(1)  # 查询间隔
        self.trader_api.qry_trading_account(self.broker_id, self.investor_id)
    
    def query_position(self, instrument_id: str = ""):
        """查询持仓"""
        time.sleep(1)  # 查询间隔
        self.trader_api.qry_investor_position(
            self.broker_id, self.investor_id, instrument_id
        )
    
    def query_orders(self, instrument_id: str = ""):
        """查询订单"""
        time.sleep(1)  # 查询间隔
        self.trader_api.qry_order(
            self.broker_id, self.investor_id, instrument_id
        )
    
    def query_trades(self, instrument_id: str = ""):
        """查询成交"""
        time.sleep(1)  # 查询间隔
        self.trader_api.qry_trade(
            self.broker_id, self.investor_id, instrument_id
        )

