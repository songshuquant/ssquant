"""
自动参数策略示例 - 演示合约参数自动获取功能
Auto Parameters Strategy Demo

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易  
3. 实盘CTP交易

特性：
1. 无需手动填写 contract_multiplier、price_tick、margin_rate、commission
2. 支持主力连续合约（如 au888）自动解析为当前主力合约
3. 支持多品种回测，每个品种自动获取对应参数
4. 手动指定的参数会覆盖自动获取的参数

使用说明：
    只需填写合约代码，其他参数自动从远程服务器获取
    首次运行会从 kanpan789.com 拉取合约信息并缓存到本地
"""

import pandas as pd
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config


def initialize(api: StrategyAPI):
    """
    策略初始化函数
    
    Args:
        api: 策略API对象
    """
    api.log("=" * 50)
    api.log("自动参数策略示例 - 初始化")
    api.log("=" * 50)
    
    # 获取参数
    fast_ma = api.get_param('fast_ma', 5)
    slow_ma = api.get_param('slow_ma', 20)
    api.log(f"参数设置 - 快线周期: {fast_ma}, 慢线周期: {slow_ma}")


def ma_cross_strategy(api: StrategyAPI):
    """
    双均线交叉策略
    
    策略逻辑:
    - 短期均线上穿长期均线: 买入信号
    - 短期均线下穿长期均线: 卖出信号
    
    Args:
        api: 策略API对象
    """
    # 获取参数
    fast_ma = api.get_param('fast_ma', 5)
    slow_ma = api.get_param('slow_ma', 20)
    
    # 获取当前索引
    current_idx = api.get_idx()
    
    if current_idx < slow_ma:
        return
    
    # 获取收盘价和计算均线
    close = api.get_close()
    if len(close) < slow_ma:
        return
    
    fast_ma_values = close.rolling(fast_ma).mean()
    slow_ma_values = close.rolling(slow_ma).mean()
    
    # 获取当前持仓
    current_pos = api.get_pos()
    
    # 均线金叉：快线上穿慢线
    if fast_ma_values.iloc[-2] <= slow_ma_values.iloc[-2] and fast_ma_values.iloc[-1] > slow_ma_values.iloc[-1]:
        if current_pos <= 0:
            if current_pos < 0:
                api.buycover(volume=1, order_type='next_bar_open')
            api.buy(volume=1, order_type='next_bar_open')
            api.log(f"均线金叉：快线({fast_ma_values.iloc[-1]:.2f})上穿慢线({slow_ma_values.iloc[-1]:.2f})，买入")
    
    # 均线死叉：快线下穿慢线
    elif fast_ma_values.iloc[-2] >= slow_ma_values.iloc[-2] and fast_ma_values.iloc[-1] < slow_ma_values.iloc[-1]:
        if current_pos >= 0:
            if current_pos > 0:
                api.sell(order_type='next_bar_open')
            api.sellshort(volume=1, order_type='next_bar_open')
            api.log(f"均线死叉：快线({fast_ma_values.iloc[-1]:.2f})下穿慢线({slow_ma_values.iloc[-1]:.2f})，卖出")


# =====================================================================
# 配置区
# =====================================================================

if __name__ == "__main__":
    
    # ========== 运行模式 ==========
    RUN_MODE = RunMode.BACKTEST  # 可选: BACKTEST, SIMNOW, REAL_TRADING
    
    # ========== 策略参数 ==========
    strategy_params = {'fast_ma': 5, 'slow_ma': 20}
    
    # ========== 配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置（自动参数）====================
        # 
        # 【重点】只需填写合约代码，以下参数自动获取：
        #   - contract_multiplier (合约乘数)
        #   - price_tick (最小变动价位)
        #   - margin_rate (保证金率)
        #   - commission (手续费率)
        #
        config = get_config(RUN_MODE,
            # -------- 基础配置 --------
            symbol='au888',                   # 合约代码 (主力连续，自动解析为当前主力)
            start_date='2025-12-01',          # 回测开始日期
            end_date='2026-01-31',            # 回测结束日期
            kline_period='15m',               # K线周期: '1m','5m','15m','30m','1h','4h','1d'
            adjust_type='1',                  # 复权类型: '0'不复权, '1'后复权
            debug= False,
            
            # -------- 以下参数自动获取，无需手动填写 --------
            # price_tick=0.02,                # 自动：黄金=0.02
            # contract_multiplier=1000,       # 自动：黄金=1000克/手
            # margin_rate=0.17,               # 自动：约17%
            # commission=0.000001,            # 自动：万分之0.1
            
            # -------- 资金配置 --------
            initial_capital=500000,           # 初始资金 (元)
            slippage_ticks=1,                 # 滑点跳数 (回测模拟成交时的滑点)
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线回溯窗口 (0=不限制)
        )
        
        # ==================== 多品种回测配置示例（自动参数）====================
        # 取消下面的注释可以运行多品种回测
        """
        config = get_config(RUN_MODE,
            # -------- 基础配置 --------
            start_date='2025-12-01',
            end_date='2026-01-31',
            initial_capital=1000000,
            
            # -------- 数据对齐配置 --------
            align_data=False,                 # 独立策略不需要对齐
            
            # -------- 多品种数据源配置（每个品种参数自动获取）--------
            data_sources=[
                {   # 数据源0: 黄金主力
                    'symbol': 'au888',
                    'kline_period': '15m',
                    'adjust_type': '1',
                    'slippage_ticks': 1,
                    # price_tick, contract_multiplier 自动获取
                },
                {   # 数据源1: 螺纹钢主力
                    'symbol': 'rb888',
                    'kline_period': '15m',
                    'adjust_type': '1',
                    'slippage_ticks': 1,
                    # price_tick, contract_multiplier 自动获取
                },
                {   # 数据源2: 原油主力
                    'symbol': 'sc888',
                    'kline_period': '15m',
                    'adjust_type': '1',
                    'slippage_ticks': 1,
                    # price_tick, contract_multiplier 自动获取
                },
            ],
            
            lookback_bars=500,
        )
        """
    
    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置（自动参数）====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='simnow_default',         # 账户名称 (在trading_config.py的ACCOUNTS中定义)
            server_name='电信1',              # 服务器: '电信1','电信2','移动','TEST'(盘后测试)
            
            # -------- 合约配置 --------
            symbol='au2602',                  # 交易合约代码 (具体月份合约)
            kline_period='1m',                # K线周期
            
            # -------- 以下参数自动获取 --------
            # price_tick=0.02,                # 自动获取
            # contract_multiplier=1000,       # 自动获取
            
            # -------- 交易参数 --------
            order_offset_ticks=-5,            # 委托偏移跳数 (超价下单确保成交)
            
            # -------- 智能算法交易配置 --------
            algo_trading=False,               # 启用算法交易
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,                    # 撤单后最大重试次数
            retry_offset_ticks=5,             # 重试时的超价跳数
            
            # -------- 历史数据配置 --------
            preload_history=True,             # 是否预加载历史K线
            history_lookback_bars=100,        # 预加载K线数量
            adjust_type='1',                  # 复权类型
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线回溯窗口
            
            # -------- 回调模式配置 --------
            enable_tick_callback=False,       # TICK回调: True=每个TICK触发
            
            # -------- 数据保存配置 --------
            save_kline_csv=True,              # 保存K线到CSV
            save_kline_db=True,               # 保存K线到数据库
            save_tick_csv=False,              # 保存TICK到CSV
            save_tick_db=False,               # 保存TICK到数据库
        )
    
    elif RUN_MODE == RunMode.REAL_TRADING:
        # ==================== 实盘配置（自动参数）====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='real_default',           # 账户名称 (在trading_config.py的ACCOUNTS中定义)
            
            # -------- 合约配置 --------
            symbol='au2602',                  # 交易合约代码
            kline_period='1m',                # K线周期
            
            # -------- 以下参数自动获取 --------
            # price_tick=0.02,                # 自动获取
            # contract_multiplier=1000,       # 自动获取
            
            # -------- 交易参数 --------
            order_offset_ticks=-10,           # 委托偏移跳数
            
            # -------- 智能算法交易配置 --------
            algo_trading=True,                # 启用算法交易
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,                    # 最大重试次数
            retry_offset_ticks=5,             # 重试时的超价跳数
            
            # -------- 历史数据配置 --------
            preload_history=True,             # 是否预加载历史K线
            history_lookback_bars=100,        # 预加载K线数量
            adjust_type='1',                  # 复权类型
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线回溯窗口
            
            # -------- 回调模式配置 --------
            enable_tick_callback=False,       # TICK回调模式
            
            # -------- 数据保存配置 --------
            save_kline_csv=False,             # 保存K线到CSV
            save_kline_db=False,              # 保存K线到数据库
            save_tick_csv=False,              # 保存TICK到CSV
            save_tick_db=False,               # 保存TICK到数据库
        )
    
    # ========== 创建运行器并执行 ==========
    print("\n" + "=" * 80)
    print("自动参数策略示例 (Auto Parameters Demo)")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    
    # 打印合约信息
    if 'data_sources' in config:
        data_sources_info = [f"{ds['symbol']}_{ds['kline_period']}" for ds in config['data_sources']]
        print(f"数据源: {', '.join(data_sources_info)}")
    else:
        print(f"合约代码: {config['symbol']}")
    
    print(f"策略参数: 快线={strategy_params['fast_ma']}, 慢线={strategy_params['slow_ma']}")
    
    # 打印自动获取的参数
    print("-" * 40)
    print("自动获取的合约参数:")
    print(f"  合约乘数: {config.get('contract_multiplier', '未设置')}")
    print(f"  最小跳动: {config.get('price_tick', '未设置')}")
    print(f"  保证金率: {config.get('margin_rate', '未设置')}")
    print(f"  手续费率: {config.get('commission', '未设置')}")
    print("=" * 80 + "\n")
    
    # 创建运行器
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    
    # 设置配置
    runner.set_config(config)
    
    # 运行策略
    try:
        results = runner.run(
            strategy=ma_cross_strategy,
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
