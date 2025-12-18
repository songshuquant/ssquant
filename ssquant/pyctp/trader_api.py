#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CTP 交易API封装
提供更友好的Python接口用于期货交易
"""

import os
import sys
from typing import Optional

# 使用CTP动态加载器
try:
    from ..ctp.loader import thosttraderapi as traderapi, CTP_AVAILABLE
    if not CTP_AVAILABLE:
        raise ImportError("CTP模块不可用")
except ImportError as e:
    print("错误: 无法导入CTP模块")
    print(f"导入错误: {e}")
    print("提示:")
    print("  1. 回测功能仍然可用")
    print("  2. 如需实盘功能，请检查Python版本是否支持")
    print("  3. 访问 https://github.com/songshuquant/ssquant-ai 获取帮助")
    sys.exit(1)


def decode_ctp_error(error_msg):
    """解码CTP错误消息"""
    if isinstance(error_msg, bytes):
        try:
            return error_msg.decode('gbk')
        except:
            try:
                return error_msg.decode('utf-8')
            except:
                return str(error_msg)
    elif isinstance(error_msg, str):
        try:
            return error_msg.encode('latin1').decode('gbk')
        except:
            return error_msg
    return str(error_msg)


class TraderSpi(traderapi.CThostFtdcTraderSpi):
    """
    交易回调接口
    用户需要继承此类并重写相应的回调方法
    """

    def __init__(self, api):
        super().__init__()
        self.api = api

    def OnFrontConnected(self):
        """当客户端与交易后台建立起通信连接时（还未登录前），该方法被调用"""
        print("交易服务器已连接")

    def OnFrontDisconnected(self, nReason: int):
        """
        当客户端与交易后台通信连接断开时，该方法被调用
        :param nReason: 错误原因
        """
        print(f"交易服务器断开连接，原因: {nReason}")

    def OnHeartBeatWarning(self, nTimeLapse: int):
        """
        心跳超时警告
        :param nTimeLapse: 距离上次接收报文的时间
        """
        print(f"心跳超时警告: {nTimeLapse}秒")

    def OnRspAuthenticate(self, pRspAuthenticateField, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        客户端认证响应
        """
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = decode_ctp_error(pRspInfo.ErrorMsg)
            print(f"认证失败: {pRspInfo.ErrorID} - {error_msg}")
        else:
            print("认证成功")

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        登录请求响应
        """
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = decode_ctp_error(pRspInfo.ErrorMsg)
            print(f"登录失败: {pRspInfo.ErrorID} - {error_msg}")
        else:
            print("登录成功")
            if pRspUserLogin:
                print(f"交易日: {pRspUserLogin.TradingDay}")
                print(f"登录时间: {pRspUserLogin.LoginTime}")
                print(f"前置编号: {pRspUserLogin.FrontID}")
                print(f"会话编号: {pRspUserLogin.SessionID}")

    def OnRspUserLogout(self, pUserLogout, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        登出请求响应
        """
        print("已登出")

    def OnRspError(self, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        错误应答
        """
        if pRspInfo:
            error_msg = decode_ctp_error(pRspInfo.ErrorMsg)
            print(f"错误: {pRspInfo.ErrorID} - {error_msg}")

    def OnRspOrderInsert(self, pInputOrder, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        报单录入请求响应
        """
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = decode_ctp_error(pRspInfo.ErrorMsg)
            print(f"报单失败: {pRspInfo.ErrorID} - {error_msg}")

    def OnRspOrderAction(self, pInputOrderAction, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        报单操作请求响应
        """
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = decode_ctp_error(pRspInfo.ErrorMsg)
            print(f"撤单失败: {pRspInfo.ErrorID} - {error_msg}")
        else:
            print("撤单成功")

    def OnRtnOrder(self, pOrder):
        """
        报单通知
        """
        if pOrder:
            print(f"报单通知: {pOrder.InstrumentID} "
                  f"方向: {pOrder.Direction} "
                  f"价格: {pOrder.LimitPrice} "
                  f"数量: {pOrder.VolumeTotalOriginal} "
                  f"状态: {pOrder.OrderStatus}")

    def OnRtnTrade(self, pTrade):
        """
        成交通知
        """
        if pTrade:
            print(f"成交通知: {pTrade.InstrumentID} "
                  f"方向: {pTrade.Direction} "
                  f"价格: {pTrade.Price} "
                  f"数量: {pTrade.Volume}")

    def OnRspSettlementInfoConfirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        投资者结算结果确认响应
        """
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = decode_ctp_error(pRspInfo.ErrorMsg)
            print(f"结算单确认失败: {pRspInfo.ErrorID} - {error_msg}")
        else:
            print("结算单确认成功")

    def OnRspQryInvestorPosition(self, pInvestorPosition, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        请求查询投资者持仓响应
        """
        if pInvestorPosition:
            print(f"持仓: {pInvestorPosition.InstrumentID} "
                  f"方向: {pInvestorPosition.PosiDirection} "
                  f"数量: {pInvestorPosition.Position}")

    def OnRspQryTradingAccount(self, pTradingAccount, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        请求查询资金账户响应
        """
        if pTradingAccount:
            print(f"账户资金:")
            print(f"  可用资金: {pTradingAccount.Available}")
            print(f"  当前保证金: {pTradingAccount.CurrMargin}")
            print(f"  平仓盈亏: {pTradingAccount.CloseProfit}")

    def OnRspQryInstrument(self, pInstrument, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        请求查询合约响应
        """
        if pInstrument:
            print(f"合约: {pInstrument.InstrumentID} {pInstrument.InstrumentName}")


class TraderApi:
    """
    交易API封装类
    提供简化的交易接口
    """

    def __init__(self, flow_path: str = "flow/"):
        """
        初始化交易API
        :param flow_path: 流文件保存路径
        """
        # 创建流文件目录
        if not os.path.exists(flow_path):
            os.makedirs(flow_path)

        self.flow_path = flow_path
        self.request_id = 0
        self.api = traderapi.CThostFtdcTraderApi.CreateFtdcTraderApi(flow_path)
        self.spi = None

    def register_spi(self, spi: TraderSpi):
        """
        注册回调接口
        :param spi: 继承自TraderSpi的回调类实例
        """
        self.spi = spi
        self.api.RegisterSpi(spi)

    def register_front(self, front_address: str):
        """
        注册前置机地址
        :param front_address: 前置机地址，格式: tcp://ip:port
        """
        self.api.RegisterFront(front_address)

    def subscribe_private_topic(self, resume_type: int):
        """
        订阅私有流
        :param resume_type: 0:重传, 1:从最新开始, 2:快速重传
        """
        self.api.SubscribePrivateTopic(resume_type)

    def subscribe_public_topic(self, resume_type: int):
        """
        订阅公共流
        :param resume_type: 0:重传, 1:从最新开始, 2:快速重传
        """
        self.api.SubscribePublicTopic(resume_type)

    def init(self):
        """
        初始化API，开始连接
        """
        self.api.Init()

    def join(self):
        """
        等待API线程结束
        """
        return self.api.Join()

    def release(self):
        """
        释放API资源
        """
        self.api.Release()

    def get_trading_day(self) -> str:
        """
        获取当前交易日
        :return: 交易日字符串
        """
        return self.api.GetTradingDay()

    def get_api_version(self) -> str:
        """
        获取API版本
        :return: 版本号字符串
        """
        return traderapi.CThostFtdcTraderApi.GetApiVersion()

    def authenticate(self, broker_id: str, user_id: str, app_id: str, auth_code: str) -> int:
        """
        客户端认证请求
        :param broker_id: 经纪公司代码
        :param user_id: 用户代码
        :param app_id: 应用标识
        :param auth_code: 认证码
        :return: 请求ID
        """
        req = traderapi.CThostFtdcReqAuthenticateField()
        req.BrokerID = broker_id
        req.UserID = user_id
        req.AppID = app_id
        req.AuthCode = auth_code

        self.request_id += 1
        self.api.ReqAuthenticate(req, self.request_id)
        return self.request_id

    def login(self, broker_id: str, user_id: str, password: str) -> int:
        """
        用户登录请求
        :param broker_id: 经纪公司代码
        :param user_id: 用户代码
        :param password: 密码
        :return: 请求ID
        """
        req = traderapi.CThostFtdcReqUserLoginField()
        req.BrokerID = broker_id
        req.UserID = user_id
        req.Password = password

        self.request_id += 1
        self.api.ReqUserLogin(req, self.request_id)
        return self.request_id

    def logout(self, broker_id: str, user_id: str) -> int:
        """
        登出请求
        :param broker_id: 经纪公司代码
        :param user_id: 用户代码
        :return: 请求ID
        """
        req = traderapi.CThostFtdcUserLogoutField()
        req.BrokerID = broker_id
        req.UserID = user_id

        self.request_id += 1
        self.api.ReqUserLogout(req, self.request_id)
        return self.request_id

    def settlement_info_confirm(self, broker_id: str, investor_id: str) -> int:
        """
        投资者结算结果确认
        :param broker_id: 经纪公司代码
        :param investor_id: 投资者代码
        :return: 请求ID
        """
        req = traderapi.CThostFtdcSettlementInfoConfirmField()
        req.BrokerID = broker_id
        req.InvestorID = investor_id

        self.request_id += 1
        self.api.ReqSettlementInfoConfirm(req, self.request_id)
        return self.request_id

    def order_insert(self, broker_id: str, investor_id: str, instrument_id: str,
                     order_ref: str, direction: str, offset_flag: str, price: float, volume: int) -> int:
        """
        报单录入请求
        :param broker_id: 经纪公司代码
        :param investor_id: 投资者代码
        :param instrument_id: 合约代码
        :param order_ref: 报单引用
        :param direction: 买卖方向 '0':买, '1':卖
        :param offset_flag: 开平标志 '0':开仓, '1':平仓, '3':平今, '4':平今仓优先
        :param price: 价格
        :param volume: 数量
        :return: 请求ID
        """
        req = traderapi.CThostFtdcInputOrderField()
        req.BrokerID = broker_id
        req.InvestorID = investor_id
        req.InstrumentID = instrument_id
        req.OrderRef = order_ref
        req.Direction = direction
        req.LimitPrice = price
        req.VolumeTotalOriginal = volume
        req.OrderPriceType = '2'  # 限价
        req.ContingentCondition = '1'  # 立即
        req.TimeCondition = '3'  # 当日有效
        req.VolumeCondition = '1'  # 任何数量
        req.MinVolume = 1
        req.ForceCloseReason = '0'
        req.CombOffsetFlag = offset_flag  # 开平标志
        req.CombHedgeFlag = '1'  # 投机

        self.request_id += 1
        self.api.ReqOrderInsert(req, self.request_id)
        return self.request_id

    def order_action(self, broker_id: str, investor_id: str, order_sys_id: str,
                     exchange_id: str, front_id: int, session_id: int, order_ref: str) -> int:
        """
        报单操作请求（撤单）
        :param broker_id: 经纪公司代码
        :param investor_id: 投资者代码
        :param order_sys_id: 报单编号
        :param exchange_id: 交易所代码
        :param front_id: 前置编号
        :param session_id: 会话编号
        :param order_ref: 报单引用
        :return: 请求ID
        """
        req = traderapi.CThostFtdcInputOrderActionField()
        req.BrokerID = broker_id
        req.InvestorID = investor_id
        req.OrderSysID = order_sys_id
        req.ExchangeID = exchange_id
        req.FrontID = front_id
        req.SessionID = session_id
        req.OrderRef = order_ref
        req.ActionFlag = '0'  # 删除

        self.request_id += 1
        self.api.ReqOrderAction(req, self.request_id)
        return self.request_id

    def qry_investor_position(self, broker_id: str, investor_id: str, instrument_id: str = "") -> int:
        """
        请求查询投资者持仓
        :param broker_id: 经纪公司代码
        :param investor_id: 投资者代码
        :param instrument_id: 合约代码（可选）
        :return: 请求ID
        """
        req = traderapi.CThostFtdcQryInvestorPositionField()
        req.BrokerID = broker_id
        req.InvestorID = investor_id
        if instrument_id:
            req.InstrumentID = instrument_id

        self.request_id += 1
        self.api.ReqQryInvestorPosition(req, self.request_id)
        return self.request_id

    def qry_trading_account(self, broker_id: str, investor_id: str) -> int:
        """
        请求查询资金账户
        :param broker_id: 经纪公司代码
        :param investor_id: 投资者代码
        :return: 请求ID
        """
        req = traderapi.CThostFtdcQryTradingAccountField()
        req.BrokerID = broker_id
        req.InvestorID = investor_id

        self.request_id += 1
        self.api.ReqQryTradingAccount(req, self.request_id)
        return self.request_id

    def qry_instrument(self, instrument_id: str = "", exchange_id: str = "") -> int:
        """
        请求查询合约
        :param instrument_id: 合约代码（可选）
        :param exchange_id: 交易所代码（可选）
        :return: 请求ID
        """
        req = traderapi.CThostFtdcQryInstrumentField()
        if instrument_id:
            req.InstrumentID = instrument_id
        if exchange_id:
            req.ExchangeID = exchange_id

        self.request_id += 1
        self.api.ReqQryInstrument(req, self.request_id)
        return self.request_id

    def qry_order(self, broker_id: str, investor_id: str, instrument_id: str = "") -> int:
        """
        请求查询报单
        :param broker_id: 经纪公司代码
        :param investor_id: 投资者代码
        :param instrument_id: 合约代码（可选）
        :return: 请求ID
        """
        req = traderapi.CThostFtdcQryOrderField()
        req.BrokerID = broker_id
        req.InvestorID = investor_id
        if instrument_id:
            req.InstrumentID = instrument_id

        self.request_id += 1
        self.api.ReqQryOrder(req, self.request_id)
        return self.request_id

    def qry_trade(self, broker_id: str, investor_id: str, instrument_id: str = "") -> int:
        """
        请求查询成交
        :param broker_id: 经纪公司代码
        :param investor_id: 投资者代码
        :param instrument_id: 合约代码（可选）
        :return: 请求ID
        """
        req = traderapi.CThostFtdcQryTradeField()
        req.BrokerID = broker_id
        req.InvestorID = investor_id
        if instrument_id:
            req.InstrumentID = instrument_id

        self.request_id += 1
        self.api.ReqQryTrade(req, self.request_id)
        return self.request_id

