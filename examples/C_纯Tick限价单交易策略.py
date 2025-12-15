"""
TICK流限价单交易策略示例 - 展示如何使用限价单(Limit Order)进行交易

演示功能:
1. 如何使用 api.buy(price=...) 发送限价单
2. 结合智能追单功能(algo_trading)，实现"限价不成交自动追单"的高级逻辑
3. 在高频TICK数据流中捕捉买一/卖一价差进行套利或做市尝试

策略逻辑:
1. 在盘口中间价挂限价单（Maker策略）
2. 如果一定时间内未成交，触发超时撤单
3. 撤单后通过智能追单以更激进价格重发（Taker策略）
"""

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

# ========== 全局变量 ==========
g_tick_counter = 0
g_pos = 0
g_target_pos = 0

def initialize(api: StrategyAPI):
    """策略初始化"""
    api.log("=" * 60)
    api.log("TICK限价单策略启动")
    api.log("=" * 60)
    api.log("演示特性:")
    api.log("  1. 使用 price 参数发送限价单")
    api.log("  2. 挂单在买一/卖一价之间 (排队)")
    api.log("  3. 配合 order_timeout=5秒 自动撤单")
    api.log("  4. 配合 retry_offset_ticks=5 撤单后追价成交")
    api.log("=" * 60)

def on_trade(data):
    """成交回调"""
    print(f"✅ [成交回报] {data['InstrumentID']} {data['Direction']} {data['OffsetFlag']} 价格:{data['Price']} 数量:{data['Volume']}")

def on_order(data):
    """报单回调"""
    status_map = {'0': '全部成交', '1': '部分成交', '3': '未成交', '5': '撤单', 'a': '未知'}
    status = status_map.get(data['OrderStatus'], data['OrderStatus'])
    print(f"📋 [报单回报] 价格:{data['LimitPrice']} 状态:{status} 信息:{data['StatusMsg']}")

def strategy(api: StrategyAPI):
    """TICK驱动策略"""
    global g_tick_counter, g_pos, g_target_pos
    
    tick = api.get_tick()
    if not tick:
        return
        
    g_tick_counter += 1
    
    # 每50个TICK尝试一次交易 (降低频率方便观察)
    if g_tick_counter % 50 != 0:
        return
        
    # 获取盘口数据
    bid_price = tick.get('BidPrice1', 0)
    ask_price = tick.get('AskPrice1', 0)
    last_price = tick.get('LastPrice', 0)
    
    if bid_price <= 0 or ask_price <= 0:
        return
        
    api.log(f"\n[TICK #{g_tick_counter}] 最新:{last_price} 买一:{bid_price} 卖一:{ask_price}")
    
    # 获取当前持仓
    current_pos = api.get_pos()
    
    # 简单的多空交替逻辑
    if current_pos == 0:
        # 计划做多
        # 挂单策略: 挂在买一价上 (排队等待成交)
        # 这是一个典型的Limit Order，不一定能立即成交
        target_price = bid_price
        api.log(f">>> 尝试开多仓 (限价单)")
        api.log(f"    目标价格: {target_price} (当前买一价)")
        
        # 【核心演示】发送限价单
        # 注意: 这里显式指定了 price，且没有指定 offset_ticks
        # 框架会识别为限价单
        api.buy(volume=1, price=target_price, reason="限价排队做多")
        
    elif current_pos > 0:
        # 计划平多
        # 挂单策略: 挂在卖一价上 (排队等待成交)
        target_price = ask_price
        api.log(f">>> 尝试平多仓 (限价单)")
        api.log(f"    目标价格: {target_price} (当前卖一价)")
        
        # 发送限价单
        api.sell(volume=1, price=target_price, reason="限价排队平多")


if __name__ == "__main__":
    # ==================== 配置区域 ====================
    RUN_MODE = RunMode.SIMNOW  # 建议使用SIMNOW观察限价单效果
    SYMBOL = 'au2602'          # 活跃合约
    
    if RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default',
            server_name='电信1',
            symbol=SYMBOL,
            kline_period='tick',           # TICK模式
            enable_tick_callback=True,     # 开启TICK回调
            
            # -------- 智能算法交易配置 --------
            # 这里是本示例的核心:
            # 1. 我们先发限价单去排队 (Maker)
            # 2. 如果5秒没成交，触发超时 (order_timeout)
            # 3. 撤单后，立即用超价单追单 (retry_offset_ticks)，确保成交 (Taker)
            algo_trading=True,             # 开启智能交易
            order_timeout=5,               # 5秒未成交自动撤单
            retry_limit=3,                 # 撤单后重试3次
            retry_offset_ticks=5,          # 重试时: 对手价 + 5跳 (激进追单)
            
            # -------- 常规配置 --------
            price_tick=0.02,
            order_offset_ticks=0,          # 默认偏移 (限价单模式下此参数被忽略)
            preload_history=False,
        )
    
    elif RUN_MODE == RunMode.REAL_TRADING:
        config = get_config(RUN_MODE,
            account='real_default',
            symbol=SYMBOL,
            kline_period='tick',
            enable_tick_callback=True,
            
            # 实盘配置 (更保守一点)
            algo_trading=True,
            order_timeout=10,              # 10秒超时
            retry_limit=3,
            retry_offset_ticks=5,          # 追单5跳
            
            price_tick=0.02,
            order_offset_ticks=0,
            preload_history=False,
        )
        
    else:
        # 回测模式暂不演示限价单排队逻辑 (回测引擎通常假设立即成交)
        print("本示例建议在 SIMNOW 或 REAL_TRADING 模式下运行")
        exit()

    # ==================== 运行 ====================
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)
    
    try:
        runner.run(
            strategy=strategy,
            initialize=initialize,
            on_trade=on_trade,
            on_order=on_order
        )
    except KeyboardInterrupt:
        runner.stop()
