"""跨期套利策略 - 统一运行版本

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易  
3. 实盘CTP交易

策略逻辑:
1. 计算主力合约与次主力合约的价差
2. 当价差偏离均值时开仓（正向套利或反向套利）
3. 当价差回归均值时平仓

特点:
- 同品种不同月份合约，对冲比率为1:1
- 价差具有均值回归特性
- 风险相对较低
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
    api.log("=" * 60)
    api.log("跨期套利策略初始化...")
    api.log("本策略利用同一品种主力合约与次主力合约之间的价差进行套利")
    api.log("回测数据: XXX888(主力连续) vs XXX777(次主力连续)")
    api.log("实盘数据: 具体月份合约，如rb2601 vs rb2605")
    api.log("对冲比率: 1:1 (同品种不同月份)")
    api.log("=" * 60)

def calculate_spread(price_near, price_far):
    """
    计算近月与远月合约的价差
    
    Args:
        price_near: 近月合约（主力）价格序列
        price_far: 远月合约（次主力）价格序列
    
    Returns:
        价差序列 = 近月 - 远月
    """
    return price_near - price_far

def calculate_zscore(spread, window=20):
    """
    计算价差的Z分数
    
    Args:
        spread: 价差序列
        window: 窗口大小
    
    Returns:
        Z分数序列
    """
    mean = spread.rolling(window=window).mean()
    std = spread.rolling(window=window).std()
    # 避免除以0
    std = std.replace(0, np.nan)
    zscore = (spread - mean) / std
    return zscore

def calendar_spread_strategy(api: StrategyAPI):
    """
    跨期套利策略主函数
    
    交易逻辑:
    - 当价差Z分数 > 阈值：做空价差（卖近月买远月）
    - 当价差Z分数 < -阈值：做多价差（买近月卖远月）
    - 当Z分数回归到0附近：平仓
    
    注意：
    - index=0 为近月合约（主力）
    - index=1 为远月合约（次主力）
    """
    # 检查是否有2个数据源
    if not api.require_data_sources(2):
        return
    
    # 获取策略参数
    min_samples = api.get_param('min_samples', 100)        # 最小样本数
    zscore_threshold = api.get_param('zscore_threshold', 2.0)  # 开仓阈值
    zscore_close = api.get_param('zscore_close', 0.5)      # 平仓阈值
    rolling_window = api.get_param('rolling_window', 20)   # 滚动窗口
    trade_volume = api.get_param('trade_volume', 1)        # 交易手数
    
    # 获取当前K线索引
    bar_idx = api.get_idx(0)
    bar_datetime = api.get_datetime(0)
    
    # 获取两个合约的K线数据
    near_klines = api.get_klines(0)   # 近月（主力）
    far_klines = api.get_klines(1)    # 远月（次主力）
    
    # 检查数据量
    if len(near_klines) < min_samples or len(far_klines) < min_samples:
        if bar_idx % 100 == 0:
            api.log(f"数据不足: 近月{len(near_klines)}条, 远月{len(far_klines)}条, 需要{min_samples}条")
        return
    
    # 提取收盘价
    near_close = near_klines['close']
    far_close = far_klines['close']
    
    # 计算价差
    spread = calculate_spread(near_close, far_close)
    
    # 检查滚动窗口
    if bar_idx < rolling_window:
        return
    
    # 计算Z分数
    zscore = calculate_zscore(spread, window=rolling_window)
    current_zscore = zscore.iloc[-1]
    current_spread = spread.iloc[-1]
    
    if pd.isna(current_zscore):
        return
    
    # 获取当前持仓
    near_pos = api.get_pos(0)   # 近月持仓
    far_pos = api.get_pos(1)    # 远月持仓
    
    # 获取当前价格
    near_price = api.get_price(0)
    far_price = api.get_price(1)
    
    # 每20个bar打印一次状态
    if bar_idx % 20 == 0:
        api.log(f"[{bar_datetime}] 价差:{current_spread:.2f} Z分数:{current_zscore:.2f} | 近月持仓:{near_pos} 远月持仓:{far_pos}")
    
    # ========== 交易逻辑 ==========
    
    # 无持仓时，判断是否开仓
    if near_pos == 0 and far_pos == 0:
        if current_zscore > zscore_threshold:
            # Z分数过高：价差偏大，预期回归
            # 做空价差 = 卖近月 + 买远月
            api.log(f"📉 开仓做空价差 | Z={current_zscore:.2f} > {zscore_threshold}")
            api.log(f"   卖出近月@{near_price:.2f}, 买入远月@{far_price:.2f}")
            api.sellshort(volume=trade_volume, order_type='next_bar_open', index=0)  # 卖近月
            api.buy(volume=trade_volume, order_type='next_bar_open', index=1)        # 买远月
            
        elif current_zscore < -zscore_threshold:
            # Z分数过低：价差偏小，预期回归
            # 做多价差 = 买近月 + 卖远月
            api.log(f"📈 开仓做多价差 | Z={current_zscore:.2f} < {-zscore_threshold}")
            api.log(f"   买入近月@{near_price:.2f}, 卖出远月@{far_price:.2f}")
            api.buy(volume=trade_volume, order_type='next_bar_open', index=0)        # 买近月
            api.sellshort(volume=trade_volume, order_type='next_bar_open', index=1)  # 卖远月
    
    # 持有做空价差（空近月 + 多远月）
    elif near_pos < 0 and far_pos > 0:
        if current_zscore < zscore_close:
            # Z分数回归，平仓
            api.log(f"✅ 平仓做空价差 | Z={current_zscore:.2f} < {zscore_close}")
            api.buycover(order_type='next_bar_open', index=0)  # 平空近月
            api.sell(order_type='next_bar_open', index=1)      # 平多远月
    
    # 持有做多价差（多近月 + 空远月）
    elif near_pos > 0 and far_pos < 0:
        if current_zscore > -zscore_close:
            # Z分数回归，平仓
            api.log(f"✅ 平仓做多价差 | Z={current_zscore:.2f} > {-zscore_close}")
            api.sell(order_type='next_bar_open', index=0)       # 平多近月
            api.buycover(order_type='next_bar_open', index=1)   # 平空远月


if __name__ == "__main__":
    from ssquant.config.trading_config import get_config
    
    # ========== 选择运行模式 ==========
    RUN_MODE = RunMode.BACKTEST
    
    # ========== 策略参数 ==========
    strategy_params = {
        'min_samples': 100,        # 最小样本数
        'zscore_threshold': 2.0,   # 开仓Z分数阈值
        'zscore_close': 0.5,       # 平仓Z分数阈值
        'rolling_window': 20,      # 滚动窗口
        'trade_volume': 1,         # 交易手数
    }
    
    # ========== 获取基础配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 (跨期套利 - 主力vs次主力) ====================
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
            
            # -------- 跨期套利数据源配置 (同品种不同月份) --------
            # 888=主力连续, 777=次主力连续
            data_sources=[
                {   # 数据源0: 近月合约 (主力连续)
                    'symbol': 'rb888',        # 合约代码 (888=主力连续)
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权类型: '0'不复权, '1'后复权
                    'price_tick': 1,          # 最小变动价位 (元)
                    'contract_multiplier': 10,# 合约乘数 (吨/手)
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源1: 远月合约 (次主力连续)
                    'symbol': 'rb777',        # 合约代码 (777=次主力连续)
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权类型
                    'price_tick': 1,          # 最小变动价位
                    'contract_multiplier': 10,# 合约乘数
                    'slippage_ticks': 1,      # 滑点跳数
                },
            ]
        )
    
    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置 (跨期套利) ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='simnow_default',         # 账户名称
            server_name='电信1',              # 服务器: 电信1/电信2/移动/TEST(盘后测试)
            
            # -------- 跨期套利配置 --------
            # ⭐ 关键：使用 history_symbol 指定历史数据来源
            # 近月用主力数据(rb888)，远月用次主力数据(rb777)
            data_sources=[
                {   # 数据源0: 近月合约（主力）
                    'symbol': 'rb2601',           # 合约代码 (近月合约)
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
                    'history_symbol': 'rb888',    # 历史数据来源 (主力连续)
                },
                {   # 数据源1: 远月合约（次主力）
                    'symbol': 'rb2605',           # 合约代码 (远月合约)
                    'kline_period': '1m',         # K线周期
                    'price_tick': 1,              # 最小变动价位
                    'order_offset_ticks': 5,      # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 200, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型
                    'history_symbol': 'rb777',    # 历史数据来源 (次主力连续)
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
        # ==================== 实盘配置 (跨期套利) ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='real_default',           # 账户名称 (对应trading_config.py中的配置)
            
            # -------- 跨期套利配置 --------
            # ⭐ 关键：使用 history_symbol 指定历史数据来源
            data_sources=[
                {   # 数据源0: 近月合约（主力）
                    'symbol': 'rb2601',           # 合约代码 (近月合约)
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
                    'history_symbol': 'rb888',    # 历史数据来源 (主力连续)
                },
                {   # 数据源1: 远月合约（次主力）
                    'symbol': 'rb2605',           # 合约代码 (远月合约)
                    'kline_period': '1m',         # K线周期
                    'price_tick': 1,              # 最小变动价位
                    'order_offset_ticks': 5,      # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 200, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型
                    'history_symbol': 'rb777',    # 历史数据来源 (次主力连续)
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
    
    # ========== 打印策略信息 ==========
    print("\n" + "=" * 80)
    print("跨期套利策略 - 主力 vs 次主力")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    
    if 'data_sources' in config:
        symbols = [ds['symbol'] for ds in config['data_sources']]
        print(f"套利对: {symbols[0]} (近月) vs {symbols[1]} (远月)")
    
    print(f"策略参数:")
    print(f"  - 开仓阈值: Z > {strategy_params['zscore_threshold']} 或 Z < {-strategy_params['zscore_threshold']}")
    print(f"  - 平仓阈值: |Z| < {strategy_params['zscore_close']}")
    print(f"  - 滚动窗口: {strategy_params['rolling_window']}")
    print(f"  - 交易手数: {strategy_params['trade_volume']}")
    print("=" * 80 + "\n")
    
    # ========== 创建运行器并执行 ==========
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)
    
    try:
        results = runner.run(
            strategy=calendar_spread_strategy,
            initialize=initialize,
            strategy_params=strategy_params
        )
        
        # 回测模式打印结果
        if RUN_MODE == RunMode.BACKTEST and results:
            print("\n" + "=" * 80)
            print("回测结果汇总")
            print("=" * 80)
            
    except KeyboardInterrupt:
        print("\n用户中断")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()

