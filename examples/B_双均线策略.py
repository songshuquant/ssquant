"""
双均线交易策略 - 统一运行版本

支持三种运行模式:
1. 历史数据回测
2. SIMNOW模拟交易  
3. 实盘CTP交易

只需修改配置参数即可切换运行模式，策略代码保持不变
"""

import pandas as pd


# 导入必要模块
from ssquant.api.strategy_api import StrategyAPI


from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config


# 全局变量
g_tick_counter = 0

def initialize(api: StrategyAPI):
    """
    策略初始化函数
    
    Args:
        api: 策略API对象
    """
    api.log("双均线交叉策略初始化")
    fast_ma = api.get_param('fast_ma', 5)
    slow_ma = api.get_param('slow_ma', 10)
    api.log(f"参数设置 - 快线周期: {fast_ma}, 慢线周期: {slow_ma}")


def ma_cross_strategy(api: StrategyAPI):
    """
    双均线交叉策略
    
    策略逻辑:
    - 短期均线上穿长期均线: 买入信号
    - 短期均线下穿长期均线: 卖出信号
    
    运行模式:
    - 回测模式: 在K线完成时触发
    - 实盘模式: 启用TICK流双驱动，每个TICK都会触发，但交易仍使用K线数据
    
    说明:
    虽然实盘模式下每个TICK都会触发此函数，但由于使用 order_type='next_bar_open'，
    实际下单和成交都在K线级别进行，不影响策略逻辑。
    
    如需添加TICK级别功能（如实时止损），可以使用：
    tick = api.get_tick()  # 获取当前TICK数据
    if tick and api.get_pos() > 0:
        if tick['LastPrice'] < stop_loss_price:
            api.sell(order_type='market', reason='实时止损')
    
    Args:
        api: 策略API对象
    """
    global g_tick_counter  # 声明使用全局变量
    
    # 获取TICK数据（实盘模式）
    tick = api.get_tick()
    # print(f"💰 实时价格: {tick.get('LastPrice', 0):.2f} "
    #     f"| 卖一:{tick.get('AskPrice1', 0):.2f} "
    #     f"| 买一:{tick.get('BidPrice1', 0):.2f}")
            
    # 获取参数
    fast_ma = api.get_param('fast_ma', 5)
    slow_ma = api.get_param('slow_ma', 10)
    
    # 获取当前索引
    current_idx = api.get_idx()

    #print("current_idx:",current_idx)

    klines = api.get_klines()
    #print(len(klines))
    
    if current_idx < slow_ma:
        return
    
    # 获取收盘价和计算均线
    close = api.get_close()
    # 确保有足够的数据
    if len(close) < slow_ma:
        return
    
    fast_ma_values = close.rolling(fast_ma).mean()
    slow_ma_values = close.rolling(slow_ma).mean()
    # print(fast_ma_values)
    # print(slow_ma_values)
    # print("最新快线:",fast_ma_values.iloc[-1])
    # print("最新慢线:",slow_ma_values.iloc[-1])
    # print("前一个快线:",fast_ma_values.iloc[-2])
    # print("前一个慢线:",slow_ma_values.iloc[-2])

    
    # 获取当前持仓
    current_pos = api.get_pos()
    
    # 均线金叉：快线上穿慢线
    if fast_ma_values.iloc[-2] <= slow_ma_values.iloc[-2] and fast_ma_values.iloc[-1] > slow_ma_values.iloc[-1]:
        if current_pos <= 0:
            # 如果没有持仓或者空头持仓，先平空再买入开仓
            if current_pos < 0:
                api.buycover(volume=1, order_type='next_bar_open')
            api.buy(volume=1, order_type='next_bar_open')
            api.log(f"均线金叉：快线({fast_ma_values.iloc[-1]:.2f})上穿慢线({slow_ma_values.iloc[-1]:.2f})，买入")
    
    # 均线死叉：快线下穿慢线
    elif fast_ma_values.iloc[-2] >= slow_ma_values.iloc[-2] and fast_ma_values.iloc[-1] < slow_ma_values.iloc[-1]:
        if current_pos >= 0:
            # 如果没有持仓或者多头持仓，先平多再卖出开仓
            if current_pos > 0:
                api.sell(order_type='next_bar_open')
            api.sellshort(volume=1, order_type='next_bar_open')
            api.log(f"均线死叉：快线({fast_ma_values.iloc[-1]:.2f})下穿慢线({slow_ma_values.iloc[-1]:.2f})，卖出")
    
    # 记录当前价格和日期时间
    current_price = api.get_price()
    current_datetime = api.get_datetime()
    # print("current_datetime:",current_datetime)
    # print("current_price:",current_price)

# =====================================================================
# 配置区
# =====================================================================

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config
    
    # ========== 运行模式 ==========
    RUN_MODE = RunMode.BACKTEST  # 可选: BACKTEST, SIMNOW, REAL_TRADING
    
    # ========== 策略参数 ==========
    strategy_params = {'fast_ma': 5, 'slow_ma': 20}
    
    # ========== 配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测配置 ====================
        config = get_config(RUN_MODE,
            # -------- 基础配置 --------
            symbol='au888',                   # 合约代码 (连续合约用888后缀)
            start_date='2025-12-01',          # 回测开始日期
            end_date='2026-01-31',            # 回测结束日期
            kline_period='1m',                # K线周期: '1m','5m','15m','30m','1h','4h','1d'
            adjust_type='1',                  # 复权类型: '0'不复权, '1'后复权
            
            # -------- 合约参数 --------
            price_tick=0.02,                  # 最小变动价位 (黄金=0.02, 螺纹钢=1)
            contract_multiplier=1000,         # 合约乘数 (黄金=1000克/手, 螺纹钢=10吨/手)
            slippage_ticks=1,                 # 滑点跳数 (回测模拟成交时的滑点)
            
            # -------- 资金配置 --------
            initial_capital=100000,           # 初始资金 (元)
            commission=0.0001,                # 手续费率 (万分之一)
            margin_rate=0.1,                  # 保证金率 (10%)
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线回溯窗口 (0=不限制，策略get_klines返回的最大条数)
        )
    
    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW模拟配置 ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='simnow_default',         # 账户名称 (在trading_config.py的ACCOUNTS中定义)
            server_name='电信1',              # 服务器: '电信1','电信2','移动','TEST'(盘后测试)
            
            # -------- 合约配置 --------
            symbol='au2602',                  # 交易合约代码 (具体月份合约)
            kline_period='1m',                # K线周期: '1m','5m','15m','30m','1h','1d'
            
            # -------- 交易参数 --------
            price_tick=0.02,                  # 最小变动价位 (黄金=0.02)
            order_offset_ticks=-5,            # 委托偏移跳数 (超价下单确保成交, 10跳=0.2元)
            
            # -------- 智能算法交易配置 (新增) --------
            algo_trading=False,                # 启用算法交易
            order_timeout=10,                 # 订单超时时间(秒), 10秒未成交自动撤单
            retry_limit=3,                    # 撤单后最大重试次数
            retry_offset_ticks=5,             # 重试时的超价跳数 (更激进的价格)
            
            # -------- 历史数据配置 --------
            preload_history=True,             # 是否预加载历史K线 (策略需要历史数据计算指标)
            history_lookback_bars=100,        # 预加载K线数量 (根据策略指标周期设置)
            adjust_type='1',                  # 复权类型: '0'不复权, '1'后复权
            # history_symbol='au888',         # 自定义历史数据源 (默认自动推导, 跨期套利时指定)
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线/TICK回溯窗口 (0=不限制，策略get_klines返回的最大条数)
            
            # -------- 回调模式配置 --------
            enable_tick_callback=True,       # TICK回调: True=每个TICK触发, False=每根K线触发
            
            # -------- 数据保存配置 --------
            save_kline_csv=True,             # 保存K线到CSV (路径: ./live_data/)
            save_kline_db=True,              # 保存K线到数据库 (路径: data_cache/backtest_data.db)
            save_tick_csv=True,              # 保存TICK到CSV
            save_tick_db=True,               # 保存TICK到数据库
        )
    
    elif RUN_MODE == RunMode.REAL_TRADING:
        # ==================== 实盘配置 ====================
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='real_default',           # 账户名称 (在trading_config.py的ACCOUNTS中定义)
            
            # -------- 合约配置 --------
            symbol='au2602',                  # 交易合约代码
            kline_period='1m',                # K线周期
            
            # -------- 交易参数 --------
            price_tick=0.02,                  # 最小变动价位
            order_offset_ticks=-10,            # 委托偏移跳数
            
            # -------- 智能算法交易配置 (新增) --------
            algo_trading=True,                # 启用算法交易
            order_timeout=10,                 # 订单超时时间(秒)
            retry_limit=3,                    # 最大重试次数
            retry_offset_ticks=5,             # 重试时的超价跳数
            
            # -------- 历史数据配置 --------
            preload_history=True,             # 是否预加载历史K线
            history_lookback_bars=100,        # 预加载K线数量
            adjust_type='1',                  # 复权类型
            
            # -------- 数据窗口配置 --------
            lookback_bars=500,                # K线/TICK回溯窗口 (0=不限制，策略get_klines返回的最大条数)
            
            # -------- 回调模式配置 --------
            enable_tick_callback=False,       # TICK回调模式
            
            # -------- 数据保存配置 --------
            save_kline_csv=False,             # 保存K线到CSV
            save_kline_db=False,              # 保存K线到数据库
            save_tick_csv=False,              # 保存TICK到CSV
            save_tick_db=False,               # 保存TICK到数据库
        )
    
    # ========== 创建运行器并执行 ==========
    print("\n" + "="*80)
    print("双均线策略 - 统一运行版本")
    print("="*80)
    print(f"运行模式: {RUN_MODE.value}")
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

