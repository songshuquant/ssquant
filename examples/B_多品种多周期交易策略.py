"""多品种多周期交易策略 - 统一运行版本

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易  
3. 实盘CTP交易

展示如何在一个策略中:
1. 同时交易多个品种
2. 使用不同周期的K线数据
3. 根据不同品种的特点设置不同的参数
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np

def initialize(api: StrategyAPI):
    """
    策略初始化函数
    
    Args:
        api: 策略API对象
    """
    api.log("多数据源策略初始化...")
    api.log("所有交易将使用下一根K线开盘价执行 (order_type='next_bar_open')")
    api.log("本版本使用自定义函数计算指标，不依赖API提供的指标计算功能")

# 自定义指标函数
def calculate_ma(price_series, period):
    """计算移动平均线"""
    return price_series.rolling(period).mean()

def is_crossover(fast_ma, slow_ma, idx):
    """判断上穿"""
    if idx < 1:
        return False
    return (fast_ma.iloc[idx-1] <= slow_ma.iloc[idx-1] and 
            fast_ma.iloc[idx] > slow_ma.iloc[idx])

def is_crossunder(fast_ma, slow_ma, idx):
    """判断下穿"""
    if idx < 1:
        return False
    return (fast_ma.iloc[idx-1] >= slow_ma.iloc[idx-1] and 
            fast_ma.iloc[idx] < slow_ma.iloc[idx])

def multi_source_strategy(api: StrategyAPI):
    """
    多数据源策略示例（无指标API版）
    
    使用多个数据源：
    - 数据源0: j888 5分钟K线
    - 数据源1: j888 15分钟K线
    - 数据源2: jm888 5分钟K线
    - 数据源3: jm888 15分钟K线
    
    策略逻辑：
    1. 每个数据源都单独交易，根据自身的均线交叉产生信号
    2. 5分钟和15分钟周期各自独立交易，不互相影响
    3. 当短期均线上穿长期均线时，开多仓
    4. 当短期均线下穿长期均线时，开空仓
    
    参数:
        fast_ma: 短期均线周期，默认5
        slow_ma: 长期均线周期，默认20
    
    注意：本版本使用自定义函数计算指标，不依赖API提供的指标计算功能
    """
    # 获取参数，如果未提供则使用默认值
    fast_ma = api.get_param('fast_ma', 5)  # 短期均线周期
    slow_ma = api.get_param('slow_ma', 20) # 长期均线周期
    
    # 确保至少有4个数据源
    if not api.require_data_sources(4):
        return
    
    # 获取当前索引和日期时间
    bar_idx = api.get_idx(0)
    bar_datetime = api.get_datetime(0)
    
    # 打印各数据源的信息
    if bar_idx % 100 == 0:  # 每处理100条数据打印一次信息
        api.log(f"当前Bar索引: {bar_idx}, 日期时间: {bar_datetime}")
        api.log(f"策略参数 - 快线周期: {fast_ma}, 慢线周期: {slow_ma}")
        for i in range(4):
            ds = api.get_data_source(i)
            if ds:
                api.log(f"数据源{i}: {ds.symbol}_{ds.kline_period}, 当前价格: {ds.current_price}, 持仓: {ds.current_pos}")
    
    # 获取K线数据
    j888_5m_klines = api.get_klines(0)    # j888 5分钟K线
    j888_15m_klines = api.get_klines(1)   # j888 15分钟K线
    jm888_5m_klines = api.get_klines(2)   # jm888 5分钟K线
    jm888_15m_klines = api.get_klines(3)  # jm888 15分钟K线
    
    # 确保有足够的数据
    min_data_len = max(fast_ma, slow_ma) + 5  # 需要的最小数据长度
    if (len(j888_5m_klines) < min_data_len or len(j888_15m_klines) < min_data_len or 
        len(jm888_5m_klines) < min_data_len or len(jm888_15m_klines) < min_data_len):
        return
    
    # 获取收盘价
    j888_5m_close = j888_5m_klines['close']
    j888_15m_close = j888_15m_klines['close']
    jm888_5m_close = jm888_5m_klines['close']
    jm888_15m_close = jm888_15m_klines['close']
    
    # 计算均线 - 使用自定义函数和参数化的均线周期
    j888_5m_ma_fast = calculate_ma(j888_5m_close, fast_ma)
    j888_5m_ma_slow = calculate_ma(j888_5m_close, slow_ma)
    j888_15m_ma_fast = calculate_ma(j888_15m_close, fast_ma)
    j888_15m_ma_slow = calculate_ma(j888_15m_close, slow_ma)
    jm888_5m_ma_fast = calculate_ma(jm888_5m_close, fast_ma)
    jm888_5m_ma_slow = calculate_ma(jm888_5m_close, slow_ma)
    jm888_15m_ma_fast = calculate_ma(jm888_15m_close, fast_ma)
    jm888_15m_ma_slow = calculate_ma(jm888_15m_close, slow_ma)
    
    # 如果数据不足，直接返回（使用相对索引）
    if (pd.isna(j888_5m_ma_slow.iloc[-1]) or pd.isna(j888_15m_ma_slow.iloc[-1]) or
        pd.isna(jm888_5m_ma_slow.iloc[-1]) or pd.isna(jm888_15m_ma_slow.iloc[-1])):
        return
    
    # 获取当前持仓
    j888_5m_pos = api.get_pos(0)   # 数据源0持仓
    j888_15m_pos = api.get_pos(1)  # 数据源1持仓
    jm888_5m_pos = api.get_pos(2)  # 数据源2持仓
    jm888_15m_pos = api.get_pos(3) # 数据源3持仓
    
    # 获取当前价格（使用相对索引）
    j888_5m_price = j888_5m_close.iloc[-1]
    jm888_5m_price = jm888_5m_close.iloc[-1]
    j888_15m_price = j888_15m_close.iloc[-1]
    jm888_15m_price = jm888_15m_close.iloc[-1]
    
    # 计算交易信号 - 使用自定义函数和相对索引
    if len(j888_5m_ma_fast) < 2:
        return
        
    # 判断均线交叉（使用相对索引-1表示当前，-2表示前一个）
    j888_5m_long_signal = (j888_5m_ma_fast.iloc[-2] <= j888_5m_ma_slow.iloc[-2] and j888_5m_ma_fast.iloc[-1] > j888_5m_ma_slow.iloc[-1])
    j888_5m_short_signal = (j888_5m_ma_fast.iloc[-2] >= j888_5m_ma_slow.iloc[-2] and j888_5m_ma_fast.iloc[-1] < j888_5m_ma_slow.iloc[-1])
    j888_15m_long_signal = (j888_15m_ma_fast.iloc[-2] <= j888_15m_ma_slow.iloc[-2] and j888_15m_ma_fast.iloc[-1] > j888_15m_ma_slow.iloc[-1])
    j888_15m_short_signal = (j888_15m_ma_fast.iloc[-2] >= j888_15m_ma_slow.iloc[-2] and j888_15m_ma_fast.iloc[-1] < j888_15m_ma_slow.iloc[-1])
    jm888_5m_long_signal = (jm888_5m_ma_fast.iloc[-2] <= jm888_5m_ma_slow.iloc[-2] and jm888_5m_ma_fast.iloc[-1] > jm888_5m_ma_slow.iloc[-1])
    jm888_5m_short_signal = (jm888_5m_ma_fast.iloc[-2] >= jm888_5m_ma_slow.iloc[-2] and jm888_5m_ma_fast.iloc[-1] < jm888_5m_ma_slow.iloc[-1])
    jm888_15m_long_signal = (jm888_15m_ma_fast.iloc[-2] <= jm888_15m_ma_slow.iloc[-2] and jm888_15m_ma_fast.iloc[-1] > jm888_15m_ma_slow.iloc[-1])
    jm888_15m_short_signal = (jm888_15m_ma_fast.iloc[-2] >= jm888_15m_ma_slow.iloc[-2] and jm888_15m_ma_fast.iloc[-1] < jm888_15m_ma_slow.iloc[-1])
    
    # 交易单位
    unit = 1
    
    # 数据源0: j888 5分钟K线交易逻辑
    if j888_5m_pos > 0:  # 当前持多仓
        if j888_5m_short_signal:  # 平多信号
            api.log(f"J888 5分钟K线短期均线下穿长期均线，平多仓，价格：{j888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.sell(volume=unit, order_type='next_bar_open', index=0)
            
            # 同时开空
            api.log(f"J888 5分钟K线短期均线下穿长期均线，开空仓，价格：{j888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.sellshort(volume=unit, order_type='next_bar_open', index=0)
            
    elif j888_5m_pos < 0:  # 当前持空仓
        if j888_5m_long_signal:  # 平空信号
            api.log(f"J888 5分钟K线短期均线上穿长期均线，平空仓，价格：{j888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.buycover(volume=unit, order_type='next_bar_open', index=0)
            
            # 同时开多
            api.log(f"J888 5分钟K线短期均线上穿长期均线，开多仓，价格：{j888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.buy(volume=unit, order_type='next_bar_open', index=0)
            
    else:  # 当前无持仓
        if j888_5m_long_signal:  # 开多信号
            api.log(f"J888 5分钟K线短期均线上穿长期均线，开多仓，价格：{j888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.buy(volume=unit, order_type='next_bar_open', index=0)
        elif j888_5m_short_signal:  # 开空信号
            api.log(f"J888 5分钟K线短期均线下穿长期均线，开空仓，价格：{j888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.sellshort(volume=unit, order_type='next_bar_open', index=0)
    
    # 数据源1: j888 15分钟K线交易逻辑
    if j888_15m_pos > 0:  # 当前持多仓
        if j888_15m_short_signal:  # 平多信号
            api.log(f"J888 15分钟K线短期均线下穿长期均线，平多仓，价格：{j888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.sell(volume=unit, order_type='next_bar_open', index=1)
            
            # 同时开空
            api.log(f"J888 15分钟K线短期均线下穿长期均线，开空仓，价格：{j888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.sellshort(volume=unit, order_type='next_bar_open', index=1)
            
    elif j888_15m_pos < 0:  # 当前持空仓
        if j888_15m_long_signal:  # 平空信号
            api.log(f"J888 15分钟K线短期均线上穿长期均线，平空仓，价格：{j888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.buycover(volume=unit, order_type='next_bar_open', index=1)
            
            # 同时开多
            api.log(f"J888 15分钟K线短期均线上穿长期均线，开多仓，价格：{j888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.buy(volume=unit, order_type='next_bar_open', index=1)
            
    else:  # 当前无持仓
        if j888_15m_long_signal:  # 开多信号
            api.log(f"J888 15分钟K线短期均线上穿长期均线，开多仓，价格：{j888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.buy(volume=unit, order_type='next_bar_open', index=1)
        elif j888_15m_short_signal:  # 开空信号
            api.log(f"J888 15分钟K线短期均线下穿长期均线，开空仓，价格：{j888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.sellshort(volume=unit, order_type='next_bar_open', index=1)
    
    # 数据源2: jm888 5分钟K线交易逻辑
    if jm888_5m_pos > 0:  # 当前持多仓
        if jm888_5m_short_signal:  # 平多信号
            api.log(f"JM888 5分钟K线短期均线下穿长期均线，平多仓，价格：{jm888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.sell(volume=unit, order_type='next_bar_open', index=2)
            
            # 同时开空
            api.log(f"JM888 5分钟K线短期均线下穿长期均线，开空仓，价格：{jm888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.sellshort(volume=unit, order_type='next_bar_open', index=2)
            
    elif jm888_5m_pos < 0:  # 当前持空仓
        if jm888_5m_long_signal:  # 平空信号
            api.log(f"JM888 5分钟K线短期均线上穿长期均线，平空仓，价格：{jm888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.buycover(volume=unit, order_type='next_bar_open', index=2)
            
            # 同时开多
            api.log(f"JM888 5分钟K线短期均线上穿长期均线，开多仓，价格：{jm888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.buy(volume=unit, order_type='next_bar_open', index=2)
            
    else:  # 当前无持仓
        if jm888_5m_long_signal:  # 开多信号
            api.log(f"JM888 5分钟K线短期均线上穿长期均线，开多仓，价格：{jm888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.buy(volume=unit, order_type='next_bar_open', index=2)
        elif jm888_5m_short_signal:  # 开空信号
            api.log(f"JM888 5分钟K线短期均线下穿长期均线，开空仓，价格：{jm888_5m_price:.2f}，将在下一根K线开盘价执行")
            api.sellshort(volume=unit, order_type='next_bar_open', index=2)
    
    # 数据源3: jm888 15分钟K线交易逻辑
    if jm888_15m_pos > 0:  # 当前持多仓
        if jm888_15m_short_signal:  # 平多信号
            api.log(f"JM888 15分钟K线短期均线下穿长期均线，平多仓，价格：{jm888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.sell(volume=unit, order_type='next_bar_open', index=3)
            
            # 同时开空
            api.log(f"JM888 15分钟K线短期均线下穿长期均线，开空仓，价格：{jm888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.sellshort(volume=unit, order_type='next_bar_open', index=3)
            
    elif jm888_15m_pos < 0:  # 当前持空仓
        if jm888_15m_long_signal:  # 平空信号
            api.log(f"JM888 15分钟K线短期均线上穿长期均线，平空仓，价格：{jm888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.buycover(volume=unit, order_type='next_bar_open', index=3)
            
            # 同时开多
            api.log(f"JM888 15分钟K线短期均线上穿长期均线，开多仓，价格：{jm888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.buy(volume=unit, order_type='next_bar_open', index=3)
            
    else:  # 当前无持仓
        if jm888_15m_long_signal:  # 开多信号
            api.log(f"JM888 15分钟K线短期均线上穿长期均线，开多仓，价格：{jm888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.buy(volume=unit, order_type='next_bar_open', index=3)
        elif jm888_15m_short_signal:  # 开空信号
            api.log(f"JM888 15分钟K线短期均线下穿长期均线，开空仓，价格：{jm888_15m_price:.2f}，将在下一根K线开盘价执行")
            api.sellshort(volume=unit, order_type='next_bar_open', index=3)

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config
    

    ###注意，这是4个独立运行的策略案例，不要对齐数据，否则会出错。

    # ========== 选择运行模式 ==========
    RUN_MODE = RunMode.BACKTEST
    
    # ========== 策略参数 ==========
    strategy_params = {
        'fast_ma': 5,
        'slow_ma': 20,
    }
    
    # ========== 获取基础配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 (多品种多周期 - 2品种×2周期=4数据源) ====================
        config = get_config(RUN_MODE,
            # -------- 基础配置 --------
            start_date='2025-12-01',          # 回测开始日期
            end_date='2026-01-31',            # 回测结束日期
            initial_capital=100000,           # 初始资金 (元)
            commission=0.0001,                # 手续费率 (万分之一)
            margin_rate=0.1,                  # 保证金率 (10%)
            
            # -------- 数据对齐配置 (独立策略不需要对齐) --------
            align_data=False,                  # 多个独立策略不需要对齐数据
            fill_method='ffill',              # 缺失值填充方法: 'ffill'向前填充, 'bfill'向后填充
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线回溯窗口 (0=不限制，策略get_klines返回的最大条数)
            
            # -------- 多品种多周期数据源配置 (焦炭+焦煤, 各2个周期) --------
            data_sources=[
                {   # 数据源0: 焦炭 1分钟
                    'symbol': 'j888',         # 合约代码 (888=主力连续)
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权类型: '0'不复权, '1'后复权
                    'price_tick': 0.5,        # 最小变动价位 (元)
                    'contract_multiplier': 100,# 合约乘数 (吨/手)
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源1: 焦炭 5分钟
                    'symbol': 'j888',         # 合约代码
                    'kline_period': '5m',     # K线周期
                    'adjust_type': '1',       # 复权类型
                    'price_tick': 0.5,        # 最小变动价位
                    'contract_multiplier': 100,# 合约乘数
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源2: 焦煤 1分钟
                    'symbol': 'jm888',        # 合约代码
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权类型
                    'price_tick': 0.5,        # 最小变动价位
                    'contract_multiplier': 60,# 合约乘数 (60吨/手)
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源3: 焦煤 5分钟
                    'symbol': 'jm888',        # 合约代码
                    'kline_period': '5m',     # K线周期
                    'adjust_type': '1',       # 复权类型
                    'price_tick': 0.5,        # 最小变动价位
                    'contract_multiplier': 60,# 合约乘数
                    'slippage_ticks': 1,      # 滑点跳数
                },
            ]
        )
    
    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置 (多品种多周期) ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='simnow_default',         # 账户名称
            server_name='电信1',              # 服务器: 电信1/电信2/移动/TEST(盘后测试)
            
            # -------- 多品种多周期数据源配置 --------
            data_sources=[
                {   # 数据源0: 焦炭 1分钟
                    'symbol': 'j2601',            # 合约代码 (具体月份)
                    'kline_period': '1m',         # K线周期
                    'price_tick': 0.5,            # 最小变动价位 (元)
                    'order_offset_ticks': 10,     # 下单偏移跳数 (挂单距离)
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 150, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型: '0'不复权, '1'后复权
                },
                {   # 数据源1: 焦炭 5分钟
                    'symbol': 'j2601',            # 合约代码
                    'kline_period': '5m',         # K线周期
                    'price_tick': 0.5,            # 最小变动价位
                    'order_offset_ticks': 10,     # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 100, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型
                },
                {   # 数据源2: 焦煤 1分钟
                    'symbol': 'jm2601',           # 合约代码
                    'kline_period': '1m',         # K线周期
                    'price_tick': 0.5,            # 最小变动价位
                    'order_offset_ticks': 10,     # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 150, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型
                },
                {   # 数据源3: 焦煤 5分钟
                    'symbol': 'jm2601',           # 合约代码
                    'kline_period': '5m',         # K线周期
                    'price_tick': 0.5,            # 最小变动价位
                    'order_offset_ticks': 10,     # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 100, # 预加载K线数量
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
        # ==================== 实盘配置 (多品种多周期) ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='real_default',           # 账户名称 (对应trading_config.py中的配置)
            
            # -------- 多品种多周期数据源配置 --------
            data_sources=[
                {   # 数据源0: 焦炭 1分钟
                    'symbol': 'j2601',            # 合约代码 (具体月份)
                    'kline_period': '1m',         # K线周期
                    'price_tick': 0.5,            # 最小变动价位 (元)
                    'order_offset_ticks': 10,     # 下单偏移跳数 (挂单距离)
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 150, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型: '0'不复权, '1'后复权
                },
                {   # 数据源1: 焦炭 5分钟
                    'symbol': 'j2601',            # 合约代码
                    'kline_period': '5m',         # K线周期
                    'price_tick': 0.5,            # 最小变动价位
                    'order_offset_ticks': 10,     # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 100, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型
                },
                {   # 数据源2: 焦煤 1分钟
                    'symbol': 'jm2601',           # 合约代码
                    'kline_period': '1m',         # K线周期
                    'price_tick': 0.5,            # 最小变动价位
                    'order_offset_ticks': 10,     # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 150, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型
                },
                {   # 数据源3: 焦煤 5分钟
                    'symbol': 'jm2601',           # 合约代码
                    'kline_period': '5m',         # K线周期
                    'price_tick': 0.5,            # 最小变动价位
                    'order_offset_ticks': 10,     # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 100, # 预加载K线数量
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
    print("多品种多周期交易策略 - 统一运行版本")
    print("="*80)
    print(f"运行模式: {RUN_MODE.value}")
    # 多数据源模式：打印所有数据源
    if 'data_sources' in config:
        data_sources_info = [f"{ds['symbol']}_{ds['kline_period']}" for ds in config['data_sources']]
        print(f"数据源: {', '.join(data_sources_info)}")
    else:
        print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 快线={strategy_params['fast_ma']}, 慢线={strategy_params['slow_ma']}")
    print("="*80 + "\n")
    
    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    
    # 设置配置
    runner.set_config(config)
    
    # 运行策略
    try:
        results = runner.run(
            strategy=multi_source_strategy,
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

