#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
交易配置文件
"""

from ..backtest.unified_runner import RunMode


# ========== 数据API认证 (quant789.com) ==========
API_USERNAME = ""
API_PASSWORD = ""

# ========== 回测默认配置 ==========
BACKTEST_DEFAULTS = {
    'initial_capital': 20000,
    'commission': 0.0001,
    'margin_rate': 0.1,
    'contract_multiplier': 10,
    'price_tick': 1.0,
    'slippage_ticks': 1,
    'adjust_type': '1',
    'use_cache': True,
    'save_data': True,
    'debug': False,
}


# ========== 账户配置 ==========
# 在此定义所有账户，策略中通过 account='账户名' 使用
ACCOUNTS = {
    
    # -------------------- SIMNOW 模拟账户 --------------------
    'simnow_default': {
        # 账户认证 (必填)
        'investor_id': '',                # SIMNOW账号 (在 simnow.com.cn 注册)
        'password': '',                   # SIMNOW密码
        'server_name': '电信1',            # 服务器: '电信1', '电信2', '移动', 'TEST', '24hour'
        
        # 交易参数
        'kline_period': '1m',             # K线周期: '1m', '5m', '15m', '30m', '1h', '1d'
        'price_tick': 1.0,                # 最小变动价位 (螺纹钢=1, 黄金=0.02)
        'order_offset_ticks': 5,          # 委托价格偏移跳数 (超价下单，确保成交)
        
        # 智能算法交易配置
        'algo_trading': False,             # 是否启用算法交易
        'order_timeout': 10,              # 订单超时时间(秒)，0表示不启用
        'retry_limit': 3,                 # 最大重试次数
        'retry_offset_ticks': 5,          # 重试时的超价跳数 (相对于对手价)
        
        # 数据配置
        'preload_history': True,          # 是否预加载历史K线
        'history_lookback_bars': 100,     # 预加载K线数量
        'adjust_type': '1',               # 复权类型: '0'不复权, '1'后复权
        # 'history_symbol': 'rb888',      # 自定义历史数据源 (默认自动推导为主力XXX888)
                                          # 跨期套利时可指定: 主力用'rb888', 次主力用'rb777'
        
        # 回调配置
        'enable_tick_callback': False,     # 是否启用TICK回调 (实时行情推送)
        
        # 数据保存配置 (默认全部关闭)
        'save_kline_csv': True,          # 是否保存K线到CSV文件
        'save_kline_db': True,           # 是否保存K线到数据库
        'save_tick_csv': True,           # 是否保存TICK到CSV文件
        'save_tick_db': True,            # 是否保存TICK到数据库
        'data_save_path': './live_data',  # CSV文件保存路径
        'db_path': 'data_cache/backtest_data.db',  # 数据库路径
    },
    
    # -------------------- 实盘账户 --------------------
    'real_default': {
        # 账户认证 (必填，向期货公司获取)
        'broker_id': '',                  # 期货公司代码 (如: '9999')
        'investor_id': '',                # 资金账号
        'password': '',                   # 交易密码
        'md_server': '',                  # 行情服务器地址 (如: 'tcp://180.168.146.187:10211')
        'td_server': '',                  # 交易服务器地址 (如: 'tcp://180.168.146.187:10201')
        'app_id': '',                     # 应用ID (向期货公司申请)
        'auth_code': '',                  # 授权码 (向期货公司申请)
        
        # 交易参数
        'kline_period': '1d',             # K线周期: '1m', '5m', '15m', '30m', '1h', '1d'
        'price_tick': 1.0,                # 最小变动价位 (螺纹钢=1, 黄金=0.02)
        'order_offset_ticks': 5,          # 委托价格偏移跳数 (超价下单，确保成交)
        
        # 智能算法交易配置
        'algo_trading': False,             # 是否启用算法交易
        'order_timeout': 10,              # 订单超时时间(秒)，0表示不启用
        'retry_limit': 3,                 # 最大重试次数
        'retry_offset_ticks': 5,          # 重试时的超价跳数 (相对于对手价)
        
        # 数据配置
        'preload_history': True,          # 是否预加载历史K线
        'history_lookback_bars': 100,     # 预加载K线数量
        'adjust_type': '1',               # 复权类型: '0'不复权, '1'后复权
        # 'history_symbol': 'rb888',      # 自定义历史数据源 (默认自动推导为主力XXX888)
                                          # 跨期套利时可指定: 主力用'rb888', 次主力用'rb777'
        
        # 回调配置
        'enable_tick_callback': False,     # 是否启用TICK回调 (实时行情推送)
        
        # 数据保存配置 (默认全部关闭)
        'save_kline_csv': False,          # 是否保存K线到CSV文件
        'save_kline_db': False,           # 是否保存K线到数据库
        'save_tick_csv': False,           # 是否保存TICK到CSV文件
        'save_tick_db': False,            # 是否保存TICK到数据库
        'data_save_path': './live_data',  # CSV文件保存路径
        'db_path': 'data_cache/backtest_data.db',  # 数据库路径
    },
}




def get_config(mode: RunMode, account: str = None, **overrides):
    """
    获取配置
    
    Args:
        mode: 运行模式
        account: 账户名 (SIMNOW/实盘必填，从 ACCOUNTS 中选择)
        **overrides: 覆盖参数 (如 symbol='rb2601')
    
    常用覆盖参数:
        symbol: 合约代码
        kline_period: K线周期
        preload_history: 是否预加载历史数据
        history_lookback_bars: 预加载K线数量
        history_symbol: 自定义历史数据源 (跨期套利用)
                       - 不指定: 自动推导为主力连续(XXX888)
                       - 'rb888': 主力连续
                       - 'rb777': 次主力连续
    
    示例:
        # 回测
        config = get_config(RunMode.BACKTEST, symbol='rb888', start_date='2025-01-01')
        
        # SIMNOW
        config = get_config(RunMode.SIMNOW, account='simnow_default', symbol='rb2601')
        
        # 实盘
        config = get_config(RunMode.REAL_TRADING, account='real_default', symbol='rb2601')
        
        # 跨期套利 (指定历史数据源)
        config = get_config(RunMode.SIMNOW, account='simnow_default',
            data_sources=[
                {'symbol': 'rb2601', 'history_symbol': 'rb888', ...},  # 近月用主力数据
                {'symbol': 'rb2605', 'history_symbol': 'rb777', ...},  # 远月用次主力数据
            ])
    """
    if mode == RunMode.BACKTEST:
        config = BACKTEST_DEFAULTS.copy()
    elif mode in (RunMode.SIMNOW, RunMode.REAL_TRADING):
        if not account:
            raise ValueError(f"运行模式 {mode.value} 必须指定 account 参数")
        if account not in ACCOUNTS:
            available = ', '.join(ACCOUNTS.keys())
            raise ValueError(f"账户 '{account}' 不存在，可用: {available}")
        config = ACCOUNTS[account].copy()
    else:
        raise ValueError(f"不支持的运行模式: {mode}")
    
    config.update(overrides)
    return config


def get_api_auth():
    """获取数据API认证"""
    return API_USERNAME, API_PASSWORD


def set_api_auth(username: str, password: str):
    """设置数据API认证"""
    global API_USERNAME, API_PASSWORD
    API_USERNAME = username
    API_PASSWORD = password


def add_account(name: str, **config):
    """添加账户"""
    ACCOUNTS[name] = config


def list_accounts():
    """列出所有账户"""
    return list(ACCOUNTS.keys())
