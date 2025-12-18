#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CTP 行情API封装
提供更友好的Python接口用于接收市场行情数据
"""

import os
import sys
from typing import List, Optional

# 使用CTP动态加载器
try:
    from ..ctp.loader import thostmduserapi as mdapi, CTP_AVAILABLE
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


class MdSpi(mdapi.CThostFtdcMdSpi):
    """
    行情回调接口
    用户需要继承此类并重写相应的回调方法
    """

    def __init__(self, api):
        super().__init__()
        self.api = api

    def OnFrontConnected(self):
        """当客户端与交易后台建立起通信连接时（还未登录前），该方法被调用"""
        print("行情服务器已连接")

    def OnFrontDisconnected(self, nReason: int):
        """
        当客户端与交易后台通信连接断开时，该方法被调用
        :param nReason: 错误原因
        """
        print(f"行情服务器断开连接，原因: {nReason}")

    def OnHeartBeatWarning(self, nTimeLapse: int):
        """
        心跳超时警告
        :param nTimeLapse: 距离上次接收报文的时间
        """
        print(f"心跳超时警告: {nTimeLapse}秒")

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        登录请求响应
        :param pRspUserLogin: 用户登录应答
        :param pRspInfo: 响应信息
        :param nRequestID: 请求ID
        :param bIsLast: 是否最后一条
        """
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = decode_ctp_error(pRspInfo.ErrorMsg)
            print(f"登录失败: {pRspInfo.ErrorID} - {error_msg}")
        else:
            print("登录成功")

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

    def OnRspSubMarketData(self, pSpecificInstrument, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        订阅行情应答
        """
        if pRspInfo and pRspInfo.ErrorID != 0:
            error_msg = decode_ctp_error(pRspInfo.ErrorMsg)
            print(f"订阅行情失败: {pRspInfo.ErrorID} - {error_msg}")
        else:
            if pSpecificInstrument:
                print(f"订阅行情成功: {pSpecificInstrument.InstrumentID}")

    def OnRspUnSubMarketData(self, pSpecificInstrument, pRspInfo, nRequestID: int, bIsLast: bool):
        """
        取消订阅行情应答
        """
        if pSpecificInstrument:
            print(f"取消订阅行情: {pSpecificInstrument.InstrumentID}")

    def OnRtnDepthMarketData(self, pDepthMarketData):
        """
        深度行情通知
        :param pDepthMarketData: 深度行情数据
        """
        if pDepthMarketData:
            print(f"行情: {pDepthMarketData.InstrumentID} "
                  f"最新价: {pDepthMarketData.LastPrice} "
                  f"成交量: {pDepthMarketData.Volume}")


class MdApi:
    """
    行情API封装类
    提供简化的行情接口
    """

    def __init__(self, flow_path: str = "flow/", use_udp: bool = False, multicast: bool = False):
        """
        初始化行情API
        :param flow_path: 流文件保存路径
        :param use_udp: 是否使用UDP协议
        :param multicast: 是否使用组播
        """
        # 创建流文件目录
        if not os.path.exists(flow_path):
            os.makedirs(flow_path)

        self.flow_path = flow_path
        self.request_id = 0
        self.api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi(flow_path, use_udp, multicast)
        self.spi = None

    def register_spi(self, spi: MdSpi):
        """
        注册回调接口
        :param spi: 继承自MdSpi的回调类实例
        """
        self.spi = spi
        self.api.RegisterSpi(spi)

    def register_front(self, front_address: str):
        """
        注册前置机地址
        :param front_address: 前置机地址，格式: tcp://ip:port
        """
        self.api.RegisterFront(front_address)

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
        return mdapi.CThostFtdcMdApi.GetApiVersion()

    def login(self, broker_id: str, user_id: str, password: str) -> int:
        """
        用户登录请求
        :param broker_id: 经纪公司代码
        :param user_id: 用户代码
        :param password: 密码
        :return: 请求ID
        """
        req = mdapi.CThostFtdcReqUserLoginField()
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
        req = mdapi.CThostFtdcUserLogoutField()
        req.BrokerID = broker_id
        req.UserID = user_id

        self.request_id += 1
        self.api.ReqUserLogout(req, self.request_id)
        return self.request_id

    def subscribe_market_data(self, instrument_ids: List[str]) -> int:
        """
        订阅行情
        :param instrument_ids: 合约代码列表
        :return: 0表示成功
        """
        count = len(instrument_ids)
        arr = mdapi.new_string_array(count)
        for i, instrument_id in enumerate(instrument_ids):
            mdapi.string_array_setitem(arr, i, instrument_id)

        ret = self.api.SubscribeMarketData(arr, count)
        mdapi.delete_string_array(arr)
        return ret

    def unsubscribe_market_data(self, instrument_ids: List[str]) -> int:
        """
        取消订阅行情
        :param instrument_ids: 合约代码列表
        :return: 0表示成功
        """
        count = len(instrument_ids)
        arr = mdapi.new_string_array(count)
        for i, instrument_id in enumerate(instrument_ids):
            mdapi.string_array_setitem(arr, i, instrument_id)

        ret = self.api.UnSubscribeMarketData(arr, count)
        mdapi.delete_string_array(arr)
        return ret

