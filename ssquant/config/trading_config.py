#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
交易配置文件

支持自动获取合约参数（合约乘数、最小跳动、保证金率、手续费率）
"""

from ..backtest.unified_runner import RunMode

# 延迟导入合约信息服务（避免循环导入）
_contract_service = None

def _get_contract_params(symbol: str) -> dict:
    """获取合约交易参数"""
    global _contract_service
    if _contract_service is None:
        try:
            from ..data.contract_info import get_trading_params
            _contract_service = get_trading_params
        except ImportError:
            print("[配置] 警告：合约信息服务不可用，使用默认参数")
            return {}
    return _contract_service(symbol)


# ========== 数据API认证 (quant789.com) ==========
# 默认使用松鼠Quant俱乐部远程数据服务器
# 如需修改服务器地址，请编辑 ssquant/data/api_data_fetcher.py 第667行的 base_url
API_USERNAME = ""              # 数据API账号 (您的俱乐部手机号或邮箱)
API_PASSWORD = ""            # 数据API密码 (密码)

# ========== 云端数据开关 ==========
# 控制是否从云服务器请求数据（当本地缓存不存在或不完整时）
# True: 本地无数据时自动从云端获取（默认）
# False: 仅使用本地缓存，不请求云端
ENABLE_CLOUD_DATA = True

# ========== 远程数据复权设置 ==========
# 【重要】远程数据服务器升级中，暂不支持后复权数据
# 当此开关为 False 时，无论配置 adjust_type 为何值，实际请求都会使用 '0'（不复权）
# 
# 控制位置: ssquant/data/api_data_fetcher.py 的 get_futures_data() 和 fetch_data_from_api() 函数
# 
# 服务器恢复后启用后复权，只需将下方开关改为 True 即可
ENABLE_REMOTE_ADJUST = False  # 是否启用远程后复权请求（服务器升级中，暂时关闭）

# ========== 回测默认配置 ==========
BACKTEST_DEFAULTS = {
    # -------- 资金配置 --------
    'initial_capital': 20000,       # 初始资金 (元)
    'commission': 0.0001,           # 手续费率 (万分之一)
    'margin_rate': 0.1,             # 保证金率 (10%)
    
    # -------- 合约参数 --------
    'contract_multiplier': 10,      # 合约乘数 (吨/手)
    'price_tick': 1.0,              # 最小变动价位 (元)
    'slippage_ticks': 1,            # 滑点跳数
    'adjust_type': '1',             # 复权类型: '0'不复权, '1'后复权
    
    # -------- 数据对齐配置 (多数据源时使用) --------
    'align_data': False,            # 默认不开启，是否对齐多数据源的时间索引 (跨周期过滤策略需开启)
    'fill_method': 'ffill',         # 缺失值填充方法: 'ffill'向前填充, 'bfill'向后填充
    
    # -------- 数据窗口配置 --------
    'lookback_bars': 0,           # K线回溯窗口大小，0表示不限制（返回全部历史数据），建议设置500-2000
    
    # -------- 缓存与调试 --------
    'use_cache': True,              # 是否使用本地缓存数据
    'save_data': True,              # 是否保存数据到本地缓存
    'debug': False,                 # 是否开启调试模式
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
        'lookback_bars': 0,               # K线/TICK缓存窗口大小，0表示使用默认值(1000条)，建议设置500-2000
        'adjust_type': '1',               # 复权类型: '0'不复权, '1'后复权
        # 'history_symbol': 'rb888',      # 自定义历史数据源 (默认自动推导为主力XXX888)
                                         # 跨期套利时可指定: 主力用'rb888', 次主力用'rb777'
        
        # 回调配置
        'enable_tick_callback': False,     # 是否启用TICK回调 (实时行情推送)
        
        # 数据保存配置 (默认全部关闭)
        'save_kline_csv': True,           # 是否保存K线到CSV文件
        'save_kline_db': True,            # 是否保存K线到数据库
        'save_tick_csv': True,            # 是否保存TICK到CSV文件
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
        'lookback_bars': 0,               # K线/TICK缓存窗口大小，0表示使用默认值(1000条)，建议设置500-2000
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




def get_config(mode: RunMode, account: str = None, auto_params: bool = True, **overrides):
    """
    获取配置（支持自动获取合约参数）
    
    Args:
        mode: 运行模式
        account: 账户名 (SIMNOW/实盘必填，从 ACCOUNTS 中选择)
        auto_params: 是否自动获取合约参数（默认 True）
                    自动获取: contract_multiplier, price_tick, margin_rate, commission
        **overrides: 覆盖参数 (如 symbol='rb2601')
    
    常用覆盖参数:
        symbol: 合约代码（支持 au2602, au888, au 等格式）
        kline_period: K线周期
        preload_history: 是否预加载历史数据
        history_lookback_bars: 预加载K线数量
        history_symbol: 自定义历史数据源 (跨期套利用)
                       - 不指定: 自动推导为主力连续(XXX888)
                       - 'rb888': 主力连续
                       - 'rb777': 次主力连续
    
    示例:
        # 回测 - 自动获取 au 合约参数
        config = get_config(RunMode.BACKTEST, symbol='au888', start_date='2025-01-01')
        # 自动设置: contract_multiplier=1000, price_tick=0.02, margin_rate=0.08
        
        # SIMNOW - 自动获取参数
        config = get_config(RunMode.SIMNOW, account='simnow_default', symbol='au2602')
        
        # 手动指定参数（覆盖自动获取）
        config = get_config(RunMode.BACKTEST, symbol='au888', 
                           price_tick=0.05,  # 手动覆盖
                           start_date='2025-01-01')
        
        # 禁用自动参数
        config = get_config(RunMode.BACKTEST, auto_params=False, symbol='au888', ...)
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
    
    # 应用用户覆盖参数
    config.update(overrides)
    
    # 自动获取合约参数
    if auto_params:
        symbol = config.get('symbol', '')
        if symbol:
            contract_params = _get_contract_params(symbol)
            if contract_params:
                # 需要自动填充的参数列表（包括固定金额手续费）
                auto_keys = [
                    'contract_multiplier', 'price_tick', 'margin_rate', 'commission',
                    'commission_per_lot', 'commission_close_per_lot', 'commission_close_today_per_lot'
                ]
                
                # 只填充用户未手动指定的参数
                auto_filled = []
                for key in auto_keys:
                    if key not in overrides:  # 用户未手动指定
                        if key in contract_params:
                            config[key] = contract_params[key]
                            # 只显示主要参数，不显示手续费细节
                            if key in ['contract_multiplier', 'price_tick', 'margin_rate']:
                                auto_filled.append(f"{key}={contract_params[key]}")
                
                # 显示手续费类型
                comm_per_lot = contract_params.get('commission_per_lot', 0)
                if comm_per_lot > 0:
                    auto_filled.append(f"手续费={comm_per_lot}元/手")
                elif contract_params.get('commission', 0) > 0:
                    auto_filled.append(f"手续费率={contract_params.get('commission', 0)}")
                
                if auto_filled:
                    variety_name = contract_params.get('variety_name', '')
                    actual_symbol = contract_params.get('actual_symbol', symbol)
                    name_info = f"({variety_name})" if variety_name else ""
                    print(f"[自动参数] {symbol}{name_info} -> {', '.join(auto_filled)}")
                    
                    # 如果是主力连续，提示实际合约
                    if '888' in symbol or '777' in symbol:
                        print(f"[自动参数] {symbol} 当前主力合约: {actual_symbol}")
    
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
