"""跨品种套利策略 - 统一运行版本

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易  
3. 实盘CTP交易

策略逻辑:
1. 计算两个品种的价差
2. 当价差偏离均值时开仓
3. 当价差回归均值时平仓
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np
import statsmodels.api as sm

def initialize(api: StrategyAPI):
    """
    策略初始化函数
    此函数用于初始化策略并输出日志信息。
    
    Args:
        api: 策略API对象，用于访问策略参数和日志功能
    """
    api.log("跨品种套利策略初始化...")  # 输出初始化日志
    api.log("本策略利用焦炭(J)和焦煤(JM)之间的价差关系进行套利")  # 描述策略的核心逻辑

def calculate_spread(price1, price2, hedge_ratio=None):
    """
    计算两个价格序列之间的价差
    如果提供hedge_ratio，则使用该比率调整价差计算；否则直接相减。
    
    Args:
        price1: 第一个品种的价格序列（例如焦炭）
        price2: 第二个品种的价格序列（例如焦煤）
        hedge_ratio: 套期保值比率，如果为None则不使用
    
    Returns:
        价差序列，表示两个价格序列的差值
    """
    if hedge_ratio is None:
        return price1 - price2  # 如果没有hedge_ratio，直接计算差值
    else:
        return price1 - price2 * hedge_ratio  # 使用hedge_ratio调整后计算价差

def calculate_hedge_ratio(price1, price2, window=60, current_idx=None):
    """
    计算套期保值比率（基于OLS回归）
    使用指定窗口的历史数据进行线性回归，获取动态对冲比率。
    
    Args:
        price1: 第一个品种的价格序列
        price2: 第二个品种的价格序列
        window: 滚动窗口大小，用于选取历史数据
        current_idx: 当前位置索引，如果为None则使用序列末尾
    
    Returns:
        当前位置的对冲比率
    """
    if current_idx is None:
        current_idx = len(price1) - 1  # 默认使用序列末尾作为当前索引
    if current_idx < window - 1:
        return np.nan  # 如果数据不足，返回NaN
    start_idx = max(0, current_idx - window + 1)  # 计算窗口起始索引
    
    # 选取窗口数据
    y = price1.iloc[start_idx:current_idx+1]  # 选取y变量数据
    X_series = price2.iloc[start_idx:current_idx+1]  # 选取X变量数据
    
    # 重置索引以确保对齐（关键修复）
    y = y.reset_index(drop=True)
    X_series = X_series.reset_index(drop=True)
    
    # 添加常数项
    X = sm.add_constant(X_series)  # 添加常数项以包含截距
    
    try:
        model = sm.OLS(y, X)  # 创建OLS模型
        results = model.fit()  # 拟合模型
        hedge_ratio = results.params.iloc[1]  # 获取斜率系数作为对冲比率（修复 FutureWarning）
        return hedge_ratio
    except Exception as e:
        # 如果回归失败，返回NaN
        return np.nan

def calculate_zscore(spread, window=20):
    """
    计算价差的Z分数
    Z分数用于衡量价差偏离均值的程度，基于移动窗口计算。
    
    Args:
        spread: 价差序列
        window: 窗口大小，用于计算移动均值和标准差
    
    Returns:
        Z分数序列
    """
    mean = spread.rolling(window=window).mean()  # 计算移动平均值
    std = spread.rolling(window=window).std()  # 计算移动标准差
    zscore = (spread - mean) / std  # 计算Z分数
    return zscore

def pairs_trading_strategy(api: StrategyAPI):
    """
    跨品种套利策略主函数
    基于价差的Z分数进行交易决策，包括开仓和平仓逻辑。
    """
    if not api.require_data_sources(2):  # 检查是否至少有2个数据源
        return  # 如果不足，返回
    
    min_samples = api.get_param('min_samples', 200)  # 获取最小样本数参数
    zscore_threshold = api.get_param('zscore_threshold', 2.0)  # 获取Z分数阈值
    rolling_window = api.get_param('rolling_window', 20)  # 获取滚动窗口大小
    hedge_ratio_window = api.get_param('hedge_ratio_window', 30)  # 获取对冲比率窗口
    use_dynamic_hedge_ratio = api.get_param('use_dynamic_hedge_ratio', True)  # 是否使用动态对冲比率
    
    bar_idx = api.get_idx(0)  # 获取当前K线索引
    j_klines = api.get_klines(0)  # 获取焦炭K线数据
    jm_klines = api.get_klines(1)  # 获取焦煤K线数据
    
    if len(j_klines) < min_samples or len(jm_klines) < min_samples:  # 检查数据量是否足够
        return  # 如果不足，返回
    
    j_close = j_klines['close']  # 提取焦炭收盘价
    jm_close = jm_klines['close']  # 提取焦煤收盘价
    
    hedge_ratio = None
    if use_dynamic_hedge_ratio:  # 如果使用动态对冲比率
        if bar_idx >= hedge_ratio_window:
            hedge_ratio = calculate_hedge_ratio(j_close, jm_close, window=hedge_ratio_window, current_idx=bar_idx)
        if pd.isna(hedge_ratio):  # 如果计算结果为NaN
            hedge_ratio = 1.5  # 使用默认值
    else:
        hedge_ratio = 1.5  # 使用静态对冲比率
    
    spread = calculate_spread(j_close, jm_close, hedge_ratio)  # 计算价差
    if bar_idx < rolling_window:  # 如果数据不足以计算Z分数
        return
    
    zscore = calculate_zscore(spread, window=rolling_window)  # 计算Z分数序列
    current_zscore = zscore.iloc[-1]  # 获取当前Z分数（使用相对索引）
    if pd.isna(current_zscore):  # 如果Z分数为NaN
        return
    
    j_pos = api.get_pos(0)  # 获取焦炭持仓
    jm_pos = api.get_pos(1)  # 获取焦煤持仓
    j_unit = 1  # 焦炭交易单位
    jm_unit = max(1, round(j_unit * hedge_ratio))  # 计算焦煤交易单位
    
    if j_pos == 0 and jm_pos == 0:  # 无持仓情况
        if current_zscore > zscore_threshold:  # Z分数过高，做空价差
            api.sellshort(volume=j_unit, order_type='next_bar_open', index=0)
            api.buy(volume=jm_unit, order_type='next_bar_open', index=1)
        elif current_zscore < -zscore_threshold:  # Z分数过低，做多价差
            api.buy(volume=j_unit, order_type='next_bar_open', index=0)
            api.sellshort(volume=jm_unit, order_type='next_bar_open', index=1)
    elif j_pos < 0 and jm_pos > 0:  # 持有空焦炭多焦煤
        if current_zscore < 0.5:  # Z分数回归，平仓
            api.buycover(order_type='next_bar_open', index=0)
            api.sell(order_type='next_bar_open', index=1)
    elif j_pos > 0 and jm_pos < 0:  # 持有多焦炭空焦煤
        if current_zscore > -0.5:  # Z分数回归，平仓
            api.sell(order_type='next_bar_open', index=0)
            api.buycover(order_type='next_bar_open', index=1)

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config
    
    # ========== 选择运行模式 ==========
    RUN_MODE = RunMode.BACKTEST
    
    # ========== 策略参数 ==========
    strategy_params = {
        'lookback': 20,
        'threshold': 2.0,
    }
    
    # ========== 获取基础配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 (跨品种套利 - 螺纹钢vs铁矿石) ====================
        config = get_config(RUN_MODE,
            # -------- 基础配置 --------
            start_date='2025-12-01',          # 回测开始日期
            end_date='2026-01-31',            # 回测结束日期
            initial_capital=100000,           # 初始资金 (元)
            commission=0.0001,                # 手续费率 (万分之一)
            margin_rate=0.1,                  # 保证金率 (10%)
            
            # -------- 数据对齐配置 (套利策略必须开启) --------
            align_data=True,                  # 是否对齐多数据源的时间索引
            fill_method='ffill',              # 缺失值填充方法: 'ffill'向前填充, 'bfill'向后填充
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线回溯窗口 (0=不限制，策略get_klines返回的最大条数)
            
            # -------- 跨品种套利数据源配置 (产业链相关品种) --------
            # 螺纹钢与铁矿石存在产业链上下游关系
            data_sources=[
                {   # 数据源0: 螺纹钢主力连续
                    'symbol': 'rb888',        # 合约代码 (888=主力连续)
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权类型: '0'不复权, '1'后复权
                    'price_tick': 1,          # 最小变动价位 (元)
                    'contract_multiplier': 10,# 合约乘数 (吨/手)
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源1: 铁矿石主力连续
                    'symbol': 'i888',         # 合约代码
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权类型
                    'price_tick': 0.5,        # 最小变动价位
                    'contract_multiplier': 100,# 合约乘数 (100吨/手)
                    'slippage_ticks': 1,      # 滑点跳数
                },
            ]
        )
    
    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置 (跨品种套利) ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='simnow_default',         # 账户名称
            server_name='电信1',              # 服务器: 电信1/电信2/移动/TEST(盘后测试)
            
            # -------- 套利品种配置 --------
            data_sources=[
                {   # 数据源0: 螺纹钢
                    'symbol': 'rb2601',           # 合约代码 (具体月份)
                    'kline_period': '1m',         # K线周期
                    'price_tick': 1,              # 最小变动价位 (元)
                    'order_offset_ticks': 5,      # 下单偏移跳数 (挂单距离)
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 200, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型: '0'不复权, '1'后复权
                },
                {   # 数据源1: 铁矿石
                    'symbol': 'i2601',            # 合约代码
                    'kline_period': '1m',         # K线周期
                    'price_tick': 0.5,            # 最小变动价位
                    'order_offset_ticks': 10,     # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 200, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型
                },
            ],
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线回溯窗口 (0=不限制，策略get_klines返回的最大条数)
            
            # -------- 回调模式配置 --------
            enable_tick_callback=False,       # TICK回调: False=K线驱动, True=TICK驱动
            
            # -------- 数据保存配置 --------
            save_kline_csv=False,             # 保存K线到CSV文件
            save_kline_db=False,              # 保存K线到SQLite数据库
            save_tick_csv=False,              # 保存TICK到CSV文件
            save_tick_db=False,               # 保存TICK到SQLite数据库
        )
    
    elif RUN_MODE == RunMode.REAL_TRADING:
        # ==================== 实盘配置 (跨品种套利) ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='real_default',           # 账户名称 (对应trading_config.py中的配置)
            
            # -------- 套利品种配置 --------
            data_sources=[
                {   # 数据源0: 螺纹钢
                    'symbol': 'rb2601',           # 合约代码 (具体月份)
                    'kline_period': '1m',         # K线周期
                    'price_tick': 1,              # 最小变动价位 (元)
                    'order_offset_ticks': 5,      # 下单偏移跳数 (挂单距离)
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 200, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型: '0'不复权, '1'后复权
                },
                {   # 数据源1: 铁矿石
                    'symbol': 'i2601',            # 合约代码
                    'kline_period': '1m',         # K线周期
                    'price_tick': 0.5,            # 最小变动价位
                    'order_offset_ticks': 10,     # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 200, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型
                },
            ],
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线回溯窗口 (0=不限制，策略get_klines返回的最大条数)
            
            # -------- 回调模式配置 --------
            enable_tick_callback=False,       # TICK回调: False=K线驱动, True=TICK驱动
            
            # -------- 数据保存配置 --------
            save_kline_csv=False,             # 保存K线到CSV文件
            save_kline_db=False,              # 保存K线到SQLite数据库
            save_tick_csv=False,              # 保存TICK到CSV文件
            save_tick_db=False,               # 保存TICK到SQLite数据库
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")
    
    # ========== 创建运行器并执行 ==========
    print("\n" + "="*80)
    print("跨品种套利策略 - 统一运行版本")
    print("="*80)
    print(f"运行模式: {RUN_MODE.value}")
    # 多数据源模式：打印所有品种
    if 'data_sources' in config:
        symbols = [ds['symbol'] for ds in config['data_sources']]
        print(f"套利对: {' vs '.join(symbols)}")
    else:
        print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 回溯周期={strategy_params['lookback']}, 阈值={strategy_params['threshold']}")
    print("="*80 + "\n")
    
    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    
    # 设置配置
    runner.set_config(config)
    
    # 运行策略
    try:
        results = runner.run(
            strategy=pairs_trading_strategy,
            initialize=initialize,
            strategy_params=strategy_params
        )
    
    except KeyboardInterrupt:
        print("\n用户中断")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()
