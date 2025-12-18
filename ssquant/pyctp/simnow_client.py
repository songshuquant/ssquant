#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SIMNOW 自动交易客户端
提供完整的SIMNOW自动交易和行情接收功能
"""

import os
import time
import threading
from typing import List, Dict, Callable, Optional
from datetime import datetime

from .md_api import MdApi, MdSpi
from .trader_api import TraderApi, TraderSpi
from .simnow_config import SIMNOWConfig


class SIMNOWMdSpi(MdSpi):
    """SIMNOW行情回调"""
    
    def __init__(self, api, client):
        super().__init__(api)
        self.client = client
        self.connected = False
        self.logged_in = False
    
    def OnFrontConnected(self):
        """连接成功"""
        self.connected = True
        print(f"[{self._timestamp()}] [行情] 服务器已连接")
        
        # 自动登录
        if self.client.investor_id and self.client.password:
            self.api.login(
                self.client.broker_id,
                self.client.investor_id,
                self.client.password
            )
    
    def OnFrontDisconnected(self, nReason: int):
        """连接断开"""
        self.connected = False
        self.logged_in = False
        print(f"[{self._timestamp()}] [行情] 服务器断开连接，原因: {nReason:#x}")
        
        # 通知客户端
        if self.client.on_disconnected:
            self.client.on_disconnected('md', nReason)
    
    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID: int, bIsLast: bool):
        """登录响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[{self._timestamp()}] [行情] 登录失败: {full_msg}")
            return
        
        self.logged_in = True
        print(f"[{self._timestamp()}] [行情] 登录成功")
        if pRspUserLogin:
            print(f"[{self._timestamp()}] [行情] 交易日: {pRspUserLogin.TradingDay}")
        
        # 订阅行情
        if self.client.subscribe_list:
            instruments = [inst.decode() if isinstance(inst, bytes) else inst 
                          for inst in self.client.subscribe_list]
            print(f"[{self._timestamp()}] [行情] 订阅合约: {instruments}")
            self.api.subscribe_market_data(instruments)
        
        # 通知客户端
        if self.client.on_md_login:
            self.client.on_md_login()
    
    def OnRspSubMarketData(self, pSpecificInstrument, pRspInfo, nRequestID: int, bIsLast: bool):
        """订阅行情响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[{self._timestamp()}] [行情] 订阅失败: {full_msg}")
        else:
            if pSpecificInstrument:
                print(f"[{self._timestamp()}] [行情] 订阅成功: {pSpecificInstrument.InstrumentID}")
    
    def OnRtnDepthMarketData(self, pDepthMarketData):
        """行情数据"""
        if pDepthMarketData and self.client.on_market_data:
            # 转换为字典 - 基础字段
            data = {
                'InstrumentID': pDepthMarketData.InstrumentID,
                'TradingDay': pDepthMarketData.TradingDay,  # 交易日
                'ActionDay': pDepthMarketData.ActionDay,    # 自然日
                'UpdateTime': pDepthMarketData.UpdateTime,
                'UpdateMillisec': pDepthMarketData.UpdateMillisec,
                'LastPrice': pDepthMarketData.LastPrice,
                'Volume': pDepthMarketData.Volume,
                'OpenInterest': pDepthMarketData.OpenInterest,
                'UpperLimitPrice': pDepthMarketData.UpperLimitPrice,
                'LowerLimitPrice': pDepthMarketData.LowerLimitPrice,
            }
            
            # 自适应提取多档买卖盘数据（CTP支持1-5档）
            # SIMNOW通常只有1档，中金所等可能有5档
            for i in range(1, 6):
                bid_price_attr = f'BidPrice{i}'
                ask_price_attr = f'AskPrice{i}'
                bid_vol_attr = f'BidVolume{i}'
                ask_vol_attr = f'AskVolume{i}'
                
                # 检查属性是否存在且有效（非0或非最大浮点数）
                if hasattr(pDepthMarketData, bid_price_attr):
                    bid_price = getattr(pDepthMarketData, bid_price_attr)
                    # CTP用极大值表示无效价格
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
    
    def _timestamp(self):
        """获取时间戳"""
        return datetime.now().strftime('%H:%M:%S.%f')[:-3]


class SIMNOWTraderSpi(TraderSpi):
    """SIMNOW交易回调"""
    
    def __init__(self, api, client):
        super().__init__(api)
        self.client = client
        self.connected = False
        self.logged_in = False
        self.front_id = 0
        self.session_id = 0
        self.order_ref = 0
    
    def OnFrontConnected(self):
        """连接成功"""
        self.connected = True
        print(f"[{self._timestamp()}] [交易] 服务器已连接")
        
        # 如果需要认证
        if self.client.app_id and self.client.auth_code:
            print(f"[{self._timestamp()}] [交易] 开始认证...")
            self.api.authenticate(
                self.client.broker_id,
                self.client.investor_id,
                self.client.app_id,
                self.client.auth_code
            )
        else:
            # 直接登录
            self._login()
    
    def OnFrontDisconnected(self, nReason: int):
        """连接断开"""
        self.connected = False
        self.logged_in = False
        print(f"[{self._timestamp()}] [交易] 服务器断开连接，原因: {nReason:#x}")
        
        # 通知客户端
        if self.client.on_disconnected:
            self.client.on_disconnected('trader', nReason)
    
    def OnRspAuthenticate(self, pRspAuthenticateField, pRspInfo, nRequestID: int, bIsLast: bool):
        """认证响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[{self._timestamp()}] [交易] 认证失败: {full_msg}")
            return
        
        print(f"[{self._timestamp()}] [交易] 认证成功")
        self._login()
    
    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID: int, bIsLast: bool):
        """登录响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[{self._timestamp()}] [交易] 登录失败: {full_msg}")
            return
        
        self.logged_in = True
        print(f"[{self._timestamp()}] [交易] 登录成功")
        
        if pRspUserLogin:
            self.front_id = pRspUserLogin.FrontID
            self.session_id = pRspUserLogin.SessionID
            self.order_ref = int(pRspUserLogin.MaxOrderRef) if pRspUserLogin.MaxOrderRef else 0
            
            print(f"[{self._timestamp()}] [交易] 交易日: {pRspUserLogin.TradingDay}")
            print(f"[{self._timestamp()}] [交易] 前置编号: {self.front_id}")
            print(f"[{self._timestamp()}] [交易] 会话编号: {self.session_id}")
        
        # 确认结算单
        print(f"[{self._timestamp()}] [交易] 确认结算单...")
        self.api.settlement_info_confirm(self.client.broker_id, self.client.investor_id)
    
    def OnRspSettlementInfoConfirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID: int, bIsLast: bool):
        """结算单确认响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[{self._timestamp()}] [交易] 结算单确认失败: {full_msg}")
            return
        
        print(f"[{self._timestamp()}] [交易] 结算单确认成功")
        
        # 通知客户端
        if self.client.on_trader_ready:
            self.client.on_trader_ready()
    
    def OnRtnOrder(self, pOrder):
        """报单通知"""
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
                        'ExchangeID': pOrder.ExchangeID,
                        'InsertTime': pOrder.InsertTime,
                        'CancelTime': pOrder.CancelTime if hasattr(pOrder, 'CancelTime') else '',
                        'StatusMsg': status_msg,
                    }
                    self.client.on_cancel(cancel_data)
            
            # 报单回调
            if self.client.on_order:
                # 解码状态消息（可能是GBK编码）
                status_msg = self._decode_error_msg(pOrder.StatusMsg) if pOrder.StatusMsg else ""
                
                data = {
                    'InstrumentID': pOrder.InstrumentID,
                    'OrderRef': pOrder.OrderRef,
                    'Direction': pOrder.Direction,
                    'CombOffsetFlag': pOrder.CombOffsetFlag,
                    'LimitPrice': pOrder.LimitPrice,
                    'VolumeTotalOriginal': pOrder.VolumeTotalOriginal,
                    'VolumeTraded': pOrder.VolumeTraded,
                    'OrderStatus': pOrder.OrderStatus,
                    'OrderSysID': pOrder.OrderSysID,
                    'InsertTime': pOrder.InsertTime,
                    'ExchangeID': pOrder.ExchangeID,  # 交易所代码
                    'StatusMsg': status_msg,
                }
                self.client.on_order(data)
    
    def OnRtnTrade(self, pTrade):
        """成交通知"""
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
                    'TradeID': pTrade.TradeID,
                }
                self.client.on_trade(data)
            
            # 检查是否需要刷新持仓（平今→平昨重试后的成交）
            if hasattr(self.client, '_pending_position_refresh'):
                if instrument_id in self.client._pending_position_refresh:
                    self.client._pending_position_refresh.discard(instrument_id)
                    print(f"[{self._timestamp()}] [持仓刷新] 平昨成交，刷新 {instrument_id} 持仓...")
                    # 延迟一点再查询，确保成交处理完成
                    import threading
                    def refresh():
                        import time
                        time.sleep(0.5)  # 只需要短暂延迟
                        self.client.query_position(instrument_id)
                    threading.Thread(target=refresh, daemon=True).start()
    
    def OnRspOrderInsert(self, pInputOrder, pRspInfo, nRequestID: int, bIsLast: bool):
        """报单错误"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[{self._timestamp()}] [交易] 报单失败: {full_msg}")
            
            # 智能追单重试逻辑
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
                        print(f"[{self._timestamp()}] [交易] 平今失败，检测到昨仓{yd_pos}手，自动改为平昨重试...")
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
                        print(f"[{self._timestamp()}] [交易] 平今失败，但无昨仓可平，不重试")
            
            print(f"[{self._timestamp()}] [交易] 报单失败: {pRspInfo.ErrorID} - {full_msg}")
            if self.client.on_order_error:
                self.client.on_order_error(pRspInfo.ErrorID, full_msg)
    
    def OnRspOrderAction(self, pInputOrderAction, pRspInfo, nRequestID: int, bIsLast: bool):
        """撤单请求响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            print(f"[{self._timestamp()}] [交易] 撤单请求失败: {pRspInfo.ErrorID} - {error_msg}")
            if self.client.on_cancel_error:
                self.client.on_cancel_error(pRspInfo.ErrorID, error_msg)
        else:
            # 撤单请求已接受，等待报单状态变为'5'时才真正撤单成功
            print(f"[{self._timestamp()}] [交易] 撤单请求已接受，等待确认...")
    
    def OnRspQryTradingAccount(self, pTradingAccount, pRspInfo, nRequestID: int, bIsLast: bool):
        """查询资金账户响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[{self._timestamp()}] [交易] 查询资金失败: {full_msg}")
            return
        
        if pTradingAccount and self.client.on_account:
            data = {
                'AccountID': pTradingAccount.AccountID,
                'PreBalance': pTradingAccount.PreBalance,
                'Available': pTradingAccount.Available,
                'CurrMargin': pTradingAccount.CurrMargin,
                'Commission': pTradingAccount.Commission,
                'CloseProfit': pTradingAccount.CloseProfit,
                'PositionProfit': pTradingAccount.PositionProfit,
                'Balance': pTradingAccount.Balance,
                'Deposit': pTradingAccount.Deposit,
                'Withdraw': pTradingAccount.Withdraw,
            }
            print(f"[{self._timestamp()}] [资金] 可用资金: {data['Available']:.2f} | "
                  f"保证金: {data['CurrMargin']:.2f} | "
                  f"权益: {data['Balance']:.2f}")
            self.client.on_account(data)
    
    def OnRspQryInvestorPosition(self, pInvestorPosition, pRspInfo, nRequestID: int, bIsLast: bool):
        """查询持仓响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            print(f"[{self._timestamp()}] [交易] 查询持仓失败: {pRspInfo.ErrorID} - {error_msg}")
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
                    print(f"[{self._timestamp()}] [持仓] {data['InstrumentID']} {direction} "
                          f"总持仓: {position} (今:{today_pos} 昨:{yd_pos} - CTP数据同步延迟，实际已无持仓)")
                else:
                    print(f"[{self._timestamp()}] [持仓] {data['InstrumentID']} {direction} 无持仓")
            else:
                # 有持仓，正常显示
                print(f"[{self._timestamp()}] [持仓] {data['InstrumentID']} {direction} "
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
            print(f"[{self._timestamp()}] [持仓] 查询完成")
            self.client.on_position_complete()
    
    def OnRspQryOrder(self, pOrder, pRspInfo, nRequestID: int, bIsLast: bool):
        """查询报单响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            print(f"[{self._timestamp()}] [交易] 查询订单失败: {pRspInfo.ErrorID} - {error_msg}")
            return
        
        if pOrder and self.client.on_query_order:
            # 解码状态消息（可能是GBK编码）
            status_msg = self._decode_error_msg(pOrder.StatusMsg) if pOrder.StatusMsg else ""
            
            data = {
                'InstrumentID': pOrder.InstrumentID,
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
            print(f"[{self._timestamp()}] [订单] 查询完成")
            self.client.on_query_order_complete()
    
    def OnRspQryTrade(self, pTrade, pRspInfo, nRequestID: int, bIsLast: bool):
        """查询成交响应"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = self._decode_error_msg(pRspInfo.ErrorMsg)
            full_msg = self._get_error_desc(pRspInfo.ErrorID, error_msg)
            print(f"[{self._timestamp()}] [交易] 查询成交失败: {full_msg}")
            return
        
        if pTrade and self.client.on_query_trade:
            data = {
                'InstrumentID': pTrade.InstrumentID,
                'OrderRef': pTrade.OrderRef,
                'TradeID': pTrade.TradeID,
                'Direction': pTrade.Direction,
                'OffsetFlag': pTrade.OffsetFlag,
                'Price': pTrade.Price,
                'Volume': pTrade.Volume,
                'TradeDate': pTrade.TradeDate,
                'TradeTime': pTrade.TradeTime,
            }
            self.client.on_query_trade(data)
        
        if bIsLast and self.client.on_query_trade_complete:
            print(f"[{self._timestamp()}] [成交] 查询完成")
            self.client.on_query_trade_complete()
    
    def _login(self):
        """登录"""
        self.api.login(
            self.client.broker_id,
            self.client.investor_id,
            self.client.password
        )
    
    def _timestamp(self):
        """获取时间戳"""
        return datetime.now().strftime('%H:%M:%S.%f')[:-3]
    
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
    
    def get_next_order_ref(self):
        """获取下一个报单引用"""
        self.order_ref += 1
        return str(self.order_ref).zfill(12)


class SIMNOWClient:
    """SIMNOW自动交易客户端"""
    
    def __init__(self, investor_id: str, password: str, server_name: str = '24hour',
                 subscribe_list: Optional[List] = None, md_flow_path: str = "simnow_md_flow/",
                 td_flow_path: str = "simnow_td_flow/"):
        """
        初始化SIMNOW客户端
        :param investor_id: 投资者账号
        :param password: 密码
        :param server_name: 服务器名称（电信1, 电信2, 移动, TEST, N视界, 24hour）
        :param subscribe_list: 订阅合约列表
        :param md_flow_path: 行情流文件路径
        :param td_flow_path: 交易流文件路径
        """
        # 账号信息
        self.investor_id = investor_id
        self.password = password
        self.subscribe_list = subscribe_list or []
        
        # 获取服务器配置
        config = SIMNOWConfig()
        server = config.get_server(server_name)
        if not server:
            raise ValueError(f"未找到服务器配置: {server_name}")
        
        self.server = server
        self.broker_id = server.broker_id
        self.app_id = server.app_id
        self.auth_code = server.auth_code
        
        # 创建流文件目录
        if not os.path.exists(md_flow_path):
            os.makedirs(md_flow_path)
        if not os.path.exists(td_flow_path):
            os.makedirs(td_flow_path)
        
        # 创建API
        self.md_api = MdApi(flow_path=md_flow_path)
        self.trader_api = TraderApi(flow_path=td_flow_path)
        
        # 创建SPI
        self.md_spi = SIMNOWMdSpi(self.md_api, self)
        self.trader_spi = SIMNOWTraderSpi(self.trader_api, self)
        
        # 回调函数
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
        
        print(f"[初始化] SIMNOW客户端")
        print(f"[初始化] 服务器: {server.name} - {server.description}")
        print(f"[初始化] 账号: {investor_id}")
    
    def connect(self):
        """连接服务器"""
        print(f"\n{'=' * 80}")
        print(f"开始连接SIMNOW服务器...")
        print(f"{'=' * 80}\n")
        
        # 注册行情SPI和前置
        self.md_api.register_spi(self.md_spi)
        self.md_api.register_front(self.server.md_front)
        
        # 注册交易SPI和前置
        self.trader_api.register_spi(self.trader_spi)
        self.trader_api.subscribe_private_topic(2)
        self.trader_api.subscribe_public_topic(2)
        self.trader_api.register_front(self.server.trader_front)
        
        # 初始化
        self.md_api.init()
        self.trader_api.init()
        
        print(f"[连接] 行情前置: {self.server.md_front}")
        print(f"[连接] 交易前置: {self.server.trader_front}")
    
    def is_connected(self):
        """检查是否已连接"""
        return self.md_spi.connected and self.trader_spi.connected
    
    def is_ready(self):
        """检查是否就绪（已登录）"""
        return self.md_spi.logged_in and self.trader_spi.logged_in
    
    def wait_ready(self, timeout: int = 30):
        """等待就绪"""
        start_time = time.time()
        while not self.is_ready():
            if time.time() - start_time > timeout:
                raise TimeoutError("等待就绪超时")
            time.sleep(0.1)
        print(f"\n[就绪] 客户端已就绪，可以开始交易\n")
    
    def buy_open(self, instrument_id: str, price: float, volume: int):
        """买开"""
        return self._send_order(instrument_id, '0', '0', price, volume)
    
    def sell_close(self, instrument_id: str, price: float, volume: int, close_today: bool = True):
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
    
    def sell_open(self, instrument_id: str, price: float, volume: int):
        """卖开"""
        return self._send_order(instrument_id, '1', '0', price, volume)
    
    def buy_close(self, instrument_id: str, price: float, volume: int, close_today: bool = True):
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
                    price: float, volume: int):
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
        """
        撤单
        :param instrument_id: 合约代码
        :param order_sys_id: 交易所报单编号
        :param exchange_id: 交易所代码
        :return: None
        """
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
    
    def query_account(self):
        """查询账户资金"""
        print(f"[查询] 正在查询资金账户...")
        self.trader_api.qry_trading_account(self.broker_id, self.investor_id)
    
    def query_position(self, instrument_id: str = ""):
        """查询持仓"""
        print(f"[查询] 正在查询持仓{f': {instrument_id}' if instrument_id else '...'}")
        self.trader_api.qry_investor_position(self.broker_id, self.investor_id, instrument_id)
    
    def query_orders(self, instrument_id: str = ""):
        """
        查询报单
        :param instrument_id: 合约代码，为空则查询所有
        """
        print(f"[查询] 正在查询报单{f': {instrument_id}' if instrument_id else '...'}")
        self.trader_api.qry_order(self.broker_id, self.investor_id, instrument_id)
    
    def query_trades(self, instrument_id: str = ""):
        """
        查询成交
        :param instrument_id: 合约代码，为空则查询所有
        """
        print(f"[查询] 正在查询成交{f': {instrument_id}' if instrument_id else '...'}")
        self.trader_api.qry_trade(self.broker_id, self.investor_id, instrument_id)
    
    def subscribe(self, instruments: List[str]):
        """订阅行情"""
        self.md_api.subscribe_market_data(instruments)
    
    def unsubscribe(self, instruments: List[str]):
        """取消订阅"""
        self.md_api.unsubscribe_market_data(instruments)
    
    def release(self):
        """释放资源"""
        print(f"\n[退出] 正在释放资源...")
        self.md_api.release()
        self.trader_api.release()
        print(f"[退出] 已释放所有资源")

