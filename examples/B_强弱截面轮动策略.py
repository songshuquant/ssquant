"""强弱截面轮动策略 - 统一运行版本

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易  
3. 实盘CTP交易

策略逻辑:
1. 计算多个品种的动量指标
2. 选择动量最强的品种做多
3. 选择动量最弱的品种做空
4. 定期调仓
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
    api.log("强弱轮动策略初始化...")
    api.log("所有交易将使用下一根K线开盘价执行 (order_type='next_bar_open')")
    api.log("本策略通过比较不同品种的相对强弱进行轮动交易")
    
    # 获取策略参数
    lookback_period = api.get_param('lookback_period', 20)  # 回溯期
    
    api.log(f"参数设置 - 回溯期: {lookback_period}")

def calculate_relative_strength(price_series_list, lookback_period=20):
    """
    计算相对强弱指标
    
    Args:
        price_series_list: 价格序列列表
        lookback_period: 回溯期
        
    Returns:
        相对强弱指标列表
    """
    # 计算每个品种的相对强弱
    rs_list = []
    
    # 首先计算每个品种的回报率
    returns_list = [price_series.pct_change(periods=lookback_period) for price_series in price_series_list]
    
    # 计算相对强弱值（归一化）
    for i in range(len(returns_list)):
        rs_list.append(returns_list[i])
    
    return rs_list

def rank_instruments(rs_list):
    """
    对品种进行排名
    
    Args:
        rs_list: 相对强弱指标列表
        
    Returns:
        排名结果，从强到弱排序的索引列表
    """
    # 获取当前的相对强弱值（使用相对索引-1表示最新）
    current_rs_values = [rs.iloc[-1] if not pd.isna(rs.iloc[-1]) else -np.inf for rs in rs_list]
    
    # 对索引按相对强弱值排序（从大到小）
    ranked_indices = np.argsort(current_rs_values)[::-1]
    
    return ranked_indices

def relative_strength_strategy(api: StrategyAPI):
    """
    强弱轮动策略
    
    该策略通过比较不同品种的相对强弱来选择交易品种。
    具体实现为：计算每个品种的相对强弱指标，
    选择最强的品种做多，最弱的品种做空。
    
    策略逻辑：
    1. 计算所有品种的相对强弱指标
    2. 根据相对强弱指标对品种进行排名
    3. 选择排名最强的品种做多
    4. 选择排名最弱的品种做空
    5. 定期重新评估排名并轮动持仓
    """
    # 确保至少有2个数据源
    if not api.require_data_sources(2):
        return
    
    # 获取策略参数
    lookback_period = api.get_param('lookback_period', 20)  # 回溯期
    rebalance_period = api.get_param('rebalance_period', 5)  # 再平衡周期（每隔多少个bar重新评估）
    
    # 获取当前索引和日期时间
    bar_idx = api.get_idx(0)
    bar_datetime = api.get_datetime(0)
    
    # 获取数据源数量
    data_sources_count = api.get_data_sources_count()
    
    # 【防止多次触发】确保所有数据源的K线索引一致（数据同步）
    all_indices = [api.get_idx(i) for i in range(data_sources_count)]
    if len(set(all_indices)) > 1:
        # 数据源索引不一致，说明还有品种的K线没完成，等待
        return
    
    # 【防止重复执行】记录上次执行的bar索引
    if not hasattr(api, '_last_exec_bar_idx_rs'):
        api._last_exec_bar_idx_rs = -1
    
    if bar_idx == api._last_exec_bar_idx_rs:
        # 这个bar已经执行过了，跳过（防止同一bar被多次回调触发）
        return
    
    # 打印当前处理的数据
    if bar_idx % 100 == 0:
        api.log(f"当前Bar索引: {bar_idx}, 日期时间: {bar_datetime}")
    
    # 确保有足够的数据
    if bar_idx < lookback_period:
        return
    
    # 只在再平衡周期调整仓位
    if bar_idx % rebalance_period != 0:
        return
    
    # 记录本次执行
    api._last_exec_bar_idx_rs = bar_idx
    
    # 获取所有价格序列
    price_series_list = []
    symbol_list = []
    
    for i in range(data_sources_count):
        klines = api.get_klines(i)
        price_series_list.append(klines['close'])
        
        # 获取品种名称
        data_source = api.get_data_source(i)
        symbol_list.append(f"{data_source.symbol}_{data_source.kline_period}")
    
    # 计算相对强弱指标
    rs_list = calculate_relative_strength(price_series_list, lookback_period)
    
    # 对品种进行排名（使用相对索引）
    ranked_indices = rank_instruments(rs_list)
    
    # 获取最强和最弱的品种索引
    strongest_idx = ranked_indices[0]
    weakest_idx = ranked_indices[-1]
    
    # 获取当前价格（使用相对索引）
    prices = [price_series_list[i].iloc[-1] for i in range(data_sources_count)]
    
    # 打印排名信息
    api.log(f"品种相对强弱排名:")
    for rank, idx in enumerate(ranked_indices):
        api.log(f"第{rank+1}名: {symbol_list[idx]}, 价格: {prices[idx]:.2f}, 强弱值: {rs_list[idx].iloc[-1]:.4f}")
    
    # 获取当前持仓
    positions = [api.get_pos(i) for i in range(data_sources_count)]
    
    # 交易单位
    unit = 1
    
    # 确定目标持仓：哪些品种应该持有，方向如何
    target_positions = [0] * data_sources_count  # 默认全部空仓
    
    # 做多最强品种
    target_positions[strongest_idx] = unit
    api.log(f"目标: 做多最强品种 {symbol_list[strongest_idx]}")
    
    # 做空最弱品种
    target_positions[weakest_idx] = -unit
    api.log(f"目标: 做空最弱品种 {symbol_list[weakest_idx]}")
    
    # 根据目标持仓调整实际持仓（智能调仓，避免不必要的平开）
    for i in range(data_sources_count):
        current_pos = positions[i]
        target_pos = target_positions[i]
        
        # 如果当前持仓与目标一致，跳过
        if current_pos == target_pos:
            api.log(f"{symbol_list[i]}: 持仓已符合目标({target_pos})，无需调整")
            continue
        
        # 需要调整持仓
        if current_pos != 0:
            # 先平掉当前持仓
            api.log(f"平仓 {symbol_list[i]}: {current_pos} → 0")
            api.close_all(order_type='next_bar_open', index=i)
        
        if target_pos > 0:
            # 需要做多
            api.log(f"开多 {symbol_list[i]}: 0 → {target_pos}")
            api.buy(volume=target_pos, order_type='next_bar_open', index=i)
        elif target_pos < 0:
            # 需要做空
            api.log(f"开空 {symbol_list[i]}: 0 → {target_pos}")
            api.sellshort(volume=abs(target_pos), order_type='next_bar_open', index=i)

def relative_strength_momentum_strategy(api: StrategyAPI):
    """
    强弱动量策略变种
    
    该策略基于相对强弱指标，但增加了动量判断：
    只有当最强品种具有正动量时做多，
    只有当最弱品种具有负动量时做空。
    
    策略逻辑：
    1. 计算所有品种的相对强弱指标和动量指标
    2. 根据相对强弱指标对品种进行排名
    3. 如果最强品种具有正动量，做多
    4. 如果最弱品种具有负动量，做空
    5. 定期重新评估并轮动持仓
    """
    # 确保至少有2个数据源
    if not api.require_data_sources(2):
        return
    
    # 获取策略参数
    lookback_period = api.get_param('lookback_period', 20)  # 回溯期
    rebalance_period = api.get_param('rebalance_period', 5)  # 再平衡周期
    
    # 获取当前索引和日期时间
    bar_idx = api.get_idx(0)
    bar_datetime = api.get_datetime(0)
    
    # 获取数据源数量
    data_sources_count = api.get_data_sources_count()
    
    # 【防止多次触发】确保所有数据源的K线索引一致（数据同步）
    all_indices = [api.get_idx(i) for i in range(data_sources_count)]
    if len(set(all_indices)) > 1:
        # 数据源索引不一致，说明还有品种的K线没完成，等待
        return
    
    # 【防止重复执行】记录上次执行的bar索引
    if not hasattr(api, '_last_exec_bar_idx'):
        api._last_exec_bar_idx = -1
    
    if bar_idx == api._last_exec_bar_idx:
        # 这个bar已经执行过了，跳过（防止同一bar被多次回调触发）
        return
    
    # 打印当前处理的数据
    if bar_idx % 100 == 0:
        api.log(f"当前Bar索引: {bar_idx}, 日期时间: {bar_datetime}")
    
    # 确保有足够的数据
    if bar_idx < lookback_period:
        return
    
    # 只在再平衡周期调整仓位
    if bar_idx % rebalance_period != 0:
        return
    
    # 记录本次执行
    api._last_exec_bar_idx = bar_idx
    
    # 获取所有价格序列
    price_series_list = []
    symbol_list = []
    
    for i in range(data_sources_count):
        klines = api.get_klines(i)
        price_series_list.append(klines['close'])
        
        # 获取品种名称
        data_source = api.get_data_source(i)
        symbol_list.append(f"{data_source.symbol}_{data_source.kline_period}")
    
    # 计算相对强弱指标
    rs_list = calculate_relative_strength(price_series_list, lookback_period)
    
    # 对品种进行排名（使用相对索引）
    ranked_indices = rank_instruments(rs_list)
    
    # 获取最强和最弱的品种索引
    strongest_idx = ranked_indices[0]
    weakest_idx = ranked_indices[-1]
    
    # 计算动量（这里简单用回报率表示动量，使用相对索引）
    momentum_list = [price_series.pct_change(periods=lookback_period).iloc[-1] for price_series in price_series_list]
    
    # 判断最强和最弱品种的动量方向
    strongest_momentum = momentum_list[strongest_idx]
    weakest_momentum = momentum_list[weakest_idx]
    
    # 获取当前价格（使用相对索引）
    prices = [price_series_list[i].iloc[-1] for i in range(data_sources_count)]
    
    # 打印排名和动量信息
    api.log(f"品种相对强弱排名和动量:")
    for rank, idx in enumerate(ranked_indices):
        api.log(f"第{rank+1}名: {symbol_list[idx]}, 价格: {prices[idx]:.2f}, " +
                f"强弱值: {rs_list[idx].iloc[-1]:.4f}, 动量: {momentum_list[idx]:.4f}")
    
    # 获取当前持仓
    positions = [api.get_pos(i) for i in range(data_sources_count)]
    
    # 交易单位
    unit = 1
    
    # 确定目标持仓：哪些品种应该持有，方向如何
    target_positions = [0] * data_sources_count  # 默认全部空仓
    
    # 做多最强品种（如果具有正动量）
    if strongest_momentum > 0:
        target_positions[strongest_idx] = unit
        api.log(f"目标: 做多最强品种 {symbol_list[strongest_idx]}，动量 {strongest_momentum:.4f}")
    else:
        api.log(f"最强品种 {symbol_list[strongest_idx]} 动量为负 {strongest_momentum:.4f}，不做多")
    
    # 做空最弱品种（如果具有负动量）
    if weakest_momentum < 0:
        target_positions[weakest_idx] = -unit
        api.log(f"目标: 做空最弱品种 {symbol_list[weakest_idx]}，动量 {weakest_momentum:.4f}")
    else:
        api.log(f"最弱品种 {symbol_list[weakest_idx]} 动量为正 {weakest_momentum:.4f}，不做空")
    
    # 根据目标持仓调整实际持仓（智能调仓，避免不必要的平开）
    for i in range(data_sources_count):
        current_pos = positions[i]
        target_pos = target_positions[i]
        
        # 如果当前持仓与目标一致，跳过
        if current_pos == target_pos:
            continue
        
        # 需要调整持仓
        if current_pos != 0:
            # 先平掉当前持仓
            api.log(f"平仓 {symbol_list[i]}: {current_pos} → 0")
            api.close_all(order_type='next_bar_open', index=i)
        
        if target_pos > 0:
            # 需要做多
            api.log(f"开多 {symbol_list[i]}: 0 → {target_pos}")
            api.buy(volume=target_pos, order_type='next_bar_open', index=i)
        elif target_pos < 0:
            # 需要做空
            api.log(f"开空 {symbol_list[i]}: 0 → {target_pos}")
            api.sellshort(volume=abs(target_pos), order_type='next_bar_open', index=i)

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config
    
    # ========== 选择运行模式 ==========
    RUN_MODE = RunMode.BACKTEST
    
    # ========== 策略参数 ==========
    strategy_params = {
        'momentum_period': 20,
        'rebalance_period': 5,
    }
    
    # ========== 获取基础配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 (强弱轮动 - 4个品种) ====================
        config = get_config(RUN_MODE,
            # -------- 基础配置 --------
            start_date='2025-12-01',          # 回测开始日期
            end_date='2026-01-31',            # 回测结束日期
            initial_capital=100000,           # 初始资金 (元)
            commission=0.0001,                # 手续费率 (万分之一)
            margin_rate=0.1,                  # 保证金率 (10%)
            
            # -------- 数据对齐配置 (多品种轮动必须开启) --------
            align_data=True,                  # 是否对齐多数据源的时间索引
            fill_method='ffill',              # 缺失值填充方法: 'ffill'向前填充, 'bfill'向后填充
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线回溯窗口 (0=不限制，策略get_klines返回的最大条数)
            
            # -------- 多品种数据源配置 (黑色系4品种) --------
            data_sources=[
                {   # 数据源0: 螺纹钢主力连续
                    'symbol': 'rb888',        # 合约代码 (888=主力连续)
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权类型: '0'不复权, '1'后复权
                    'price_tick': 1.0,        # 最小变动价位 (元)
                    'contract_multiplier': 10,# 合约乘数 (吨/手)
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源1: 热卷主力连续
                    'symbol': 'hc888',        # 合约代码
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权类型
                    'price_tick': 1.0,        # 最小变动价位
                    'contract_multiplier': 10,# 合约乘数
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源2: 铁矿石主力连续
                    'symbol': 'i888',         # 合约代码
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权类型
                    'price_tick': 0.5,        # 最小变动价位
                    'contract_multiplier': 100,# 合约乘数 (100吨/手)
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源3: 焦炭主力连续
                    'symbol': 'j888',         # 合约代码
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权类型
                    'price_tick': 0.5,        # 最小变动价位
                    'contract_multiplier': 100,# 合约乘数
                    'slippage_ticks': 1,      # 滑点跳数
                },
            ],
        )
    
    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置 (强弱轮动) ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='simnow_default',         # 账户名称
            server_name='电信1',              # 服务器: 电信1/电信2/移动/TEST(盘后测试)
            
            # -------- 多品种配置 --------
            data_sources=[
                {   # 数据源0: 螺纹钢
                    'symbol': 'rb2601',           # 合约代码 (具体月份)
                    'kline_period': '1m',         # K线周期
                    'price_tick': 1.0,            # 最小变动价位 (元)
                    'order_offset_ticks': 5,      # 下单偏移跳数 (挂单距离)
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 100, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型: '0'不复权, '1'后复权
                },
                {   # 数据源1: 热卷
                    'symbol': 'hc2601',           # 合约代码
                    'kline_period': '1m',         # K线周期
                    'price_tick': 1.0,            # 最小变动价位
                    'order_offset_ticks': 5,      # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 100, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型
                },
                {   # 数据源2: 铁矿石
                    'symbol': 'i2601',            # 合约代码
                    'kline_period': '1m',         # K线周期
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
                {   # 数据源3: 焦炭
                    'symbol': 'j2601',            # 合约代码
                    'kline_period': '1m',         # K线周期
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
        # ==================== 实盘配置 (强弱轮动) ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='real_default',           # 账户名称 (对应trading_config.py中的配置)
            
            # -------- 多品种配置 --------
            data_sources=[
                {   # 数据源0: 螺纹钢
                    'symbol': 'rb2601',           # 合约代码 (具体月份)
                    'kline_period': '1m',         # K线周期
                    'price_tick': 1.0,            # 最小变动价位 (元)
                    'order_offset_ticks': 5,      # 下单偏移跳数 (挂单距离)
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 是否预加载历史数据
                    'history_lookback_bars': 100, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型: '0'不复权, '1'后复权
                },
                {   # 数据源1: 热卷
                    'symbol': 'hc2601',           # 合约代码
                    'kline_period': '1m',         # K线周期
                    'price_tick': 1.0,            # 最小变动价位
                    'order_offset_ticks': 5,      # 下单偏移跳数
                    
                    'algo_trading': False,        # 智能交易开关
                    'order_timeout': 10,          # 超时时间
                    'retry_limit': 3,             # 重试次数
                    'retry_offset_ticks': 5,      # 重试偏移
                    
                    'preload_history': True,      # 预加载历史数据
                    'history_lookback_bars': 100, # 预加载K线数量
                    'adjust_type': '1',           # 复权类型
                },
                {   # 数据源2: 铁矿石
                    'symbol': 'i2601',            # 合约代码
                    'kline_period': '1m',         # K线周期
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
                {   # 数据源3: 焦炭
                    'symbol': 'j2601',            # 合约代码
                    'kline_period': '1m',         # K线周期
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
    print("强弱截面轮动策略 - 统一运行版本")
    print("="*80)
    print(f"运行模式: {RUN_MODE.value}")
    # 多数据源模式：打印所有品种
    if 'data_sources' in config:
        symbols = [ds['symbol'] for ds in config['data_sources']]
        print(f"交易品种: {', '.join(symbols)}")
    else:
        print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 动量周期={strategy_params['momentum_period']}, 调仓周期={strategy_params['rebalance_period']}")
    print("="*80 + "\n")
    
    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    
    # 设置配置
    runner.set_config(config)
    
    # 运行策略
    try:
        results = runner.run(
            strategy=relative_strength_momentum_strategy,
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
