"""
期权交易示例 - SSQuant框架版
完整版：包含期权买卖测试流程

测试流程：
1. 买入看涨期权 → 卖出平仓
2. 买入看跌期权 → 卖出平仓
3. 卖出看涨期权 → 买入平仓
4. 卖出看跌期权 → 买入平仓

支持模式：SIMNOW模拟 / 实盘CTP
"""

import time
from datetime import datetime

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config


# ========== 期权配置 ==========
CALL_OPTION = 'au2602C650'      # 看涨期权
PUT_OPTION = 'au2602P640'       # 看跌期权
UNDERLYING = 'au2602'           # 标的期货

TRADE_VOLUME = 1                # 每次交易手数
INTERVAL = 3.0                  # 操作间隔（秒）

# ========== 测试状态（状态机） ==========
# g_phase: 当前测试阶段，可选值:
#   - 'wait_price':  等待行情数据就绪
#   - 'buy_call':    测试1 - 买入看涨期权
#   - 'close_call':  测试1 - 平仓看涨期权多头
#   - 'buy_put':     测试2 - 买入看跌期权
#   - 'close_put':   测试2 - 平仓看跌期权多头
#   - 'sell_call':   测试3 - 卖出看涨期权（做空）
#   - 'cover_call':  测试3 - 平仓看涨期权空头
#   - 'sell_put':    测试4 - 卖出看跌期权（做空）
#   - 'cover_put':   测试4 - 平仓看跌期权空头
#   - 'done':        测试完成
#   - 'finished':    已输出结果，等待退出
#
# 可以修改初始值跳过前面的测试，例如:
#   g_phase = 'sell_call'  # 直接从测试3开始
g_phase = 'buy_put'

# g_waiting: 订单等待标志，True=等待成交，False=可以下一步
g_waiting = False

# g_target: 当前操作的目标合约
g_target = None

# g_prices: 实时价格缓存
g_prices = {'call': 0, 'put': 0, 'underlying': 0}

# g_stats: 交易统计
g_stats = {'trades': 0, 'orders': 0}


def on_trade(data):
    """成交回调"""
    global g_waiting, g_stats
    g_waiting = False
    g_stats['trades'] += 1
    
    inst = data['InstrumentID']
    d = '买' if data['Direction'] == '0' else '卖'
    o = '开' if data['OffsetFlag'] == '0' else '平'
    
    opt_type = "看涨" if 'C' in inst else "看跌" if 'P' in inst else "期货"
    print(f"✅ [成交] {opt_type}期权 {inst} {d}{o} 价格:{data['Price']:.2f} 数量:{data['Volume']}")


def on_order(data):
    """报单回调"""
    global g_stats
    status = {'0': '成交', '3': '未成交', '5': '已撤'}
    d = '买' if data.get('Direction') == '0' else '卖'
    if data['OrderStatus'] == '3':
        g_stats['orders'] += 1
    print(f"📋 [报单] {data['InstrumentID']} {d} {status.get(data['OrderStatus'], '?')}")


def on_order_error(data):
    """报单错误"""
    global g_waiting
    g_waiting = False
    print(f"❌ [错误] {data['ErrorID']}: {data['ErrorMsg']}")


def on_position(data):
    """持仓回调"""
    inst = data['InstrumentID']
    pos = data.get('Position', 0)
    direction = {'2': '多', '3': '空'}.get(data.get('PosiDirection'), '')
    if pos > 0:
        print(f"📊 [持仓] {inst} {direction} {pos}手")


def initialize(api: StrategyAPI):
    """初始化"""
    print(f"\n{'='*60}")
    print(f"期权交易完整测试")
    print(f"{'='*60}")
    print(f"看涨期权: {CALL_OPTION}")
    print(f"看跌期权: {PUT_OPTION}")
    print(f"标的期货: {UNDERLYING}")
    print(f"{'='*60}")
    print(f"\n测试流程:")
    print(f"  1. 买入看涨期权 → 平仓")
    print(f"  2. 买入看跌期权 → 平仓")
    print(f"  3. 卖出看涨期权 → 平仓")
    print(f"  4. 卖出看跌期权 → 平仓")
    print(f"{'='*60}\n")


def strategy(api: StrategyAPI):
    """期权交易策略"""
    global g_phase, g_waiting, g_target, g_prices
    
    tick = api.get_tick()
    if tick is None:
        return
    
    inst = tick.get('InstrumentID', '')
    price = tick.get('LastPrice', 0)
    
    if inst == CALL_OPTION:
        g_prices['call'] = price
    elif inst == PUT_OPTION:
        g_prices['put'] = price
    elif inst == UNDERLYING:
        g_prices['underlying'] = price
    
    if g_waiting:
        return
    
    pos = api.get_pos()
    
    if g_phase == 'wait_price':
        if g_prices['call'] > 0 and g_prices['put'] > 0:
            print(f"\n>>> 价格就绪，开始期权交易测试")
            g_phase = 'buy_call'
            time.sleep(1)
        return
    
    if g_phase == 'buy_call':
        print(f"\n{'='*40}\n[测试1] 买入看涨期权\n{'='*40}")
        api.buy(volume=TRADE_VOLUME, order_type='market', reason='买入看涨期权')
        g_phase, g_target, g_waiting = 'close_call', CALL_OPTION, True
        time.sleep(INTERVAL)
        return
    
    if g_phase == 'close_call' and pos > 0:
        print(f">>> 平仓看涨期权多头")
        api.sell(order_type='market', reason='平仓看涨期权')
        g_phase, g_waiting = 'buy_put', True
        time.sleep(INTERVAL)
        return
    
    if g_phase == 'buy_put' and pos == 0:
        print(f"\n{'='*40}\n[测试2] 买入看跌期权\n{'='*40}")
        api.buy(volume=TRADE_VOLUME, order_type='market', reason='买入看跌期权', index=1)
        g_phase, g_target, g_waiting = 'close_put', PUT_OPTION, True
        time.sleep(INTERVAL)
        return
    
    if g_phase == 'close_put':
        put_pos = api.get_pos(index=1)
        if put_pos > 0:
            print(f">>> 平仓看跌期权多头")
            api.sell(order_type='market', reason='平仓看跌期权', index=1)
            g_phase, g_waiting = 'sell_call', True
            time.sleep(INTERVAL)
        return
    
    if g_phase == 'sell_call':
        call_pos = api.get_pos(index=0)
        if call_pos == 0:
            # 检查期权价格是否足够高（避免卖出时委托价变成负数）
            if g_prices['call'] < 0.10:
                print(f"⚠️ 看涨期权价格过低({g_prices['call']:.2f})，跳过卖出测试")
                g_phase = 'sell_put'
                return
            print(f"\n{'='*40}\n[测试3] 卖出看涨期权（做空）\n{'='*40}")
            api.sellshort(volume=TRADE_VOLUME, order_type='market', reason='卖出看涨期权', index=0)
            g_phase, g_target, g_waiting = 'cover_call', CALL_OPTION, True
            time.sleep(INTERVAL)
        return
    
    if g_phase == 'cover_call':
        call_pos = api.get_pos(index=0)
        if call_pos < 0:
            print(f">>> 平仓看涨期权空头")
            api.buycover(order_type='market', reason='平仓看涨期权空头', index=0)
            g_phase, g_waiting = 'sell_put', True
            time.sleep(INTERVAL)
        return
    
    if g_phase == 'sell_put':
        call_pos = api.get_pos(index=0)
        if call_pos == 0:
            # 检查期权价格是否足够高（避免卖出时委托价变成负数）
            if g_prices['put'] < 0.10:
                print(f"⚠️ 看跌期权价格过低({g_prices['put']:.2f})，跳过卖出测试")
                g_phase = 'done'
                return
            print(f"\n{'='*40}\n[测试4] 卖出看跌期权（做空）\n{'='*40}")
            api.sellshort(volume=TRADE_VOLUME, order_type='market', reason='卖出看跌期权', index=1)
            g_phase, g_target, g_waiting = 'cover_put', PUT_OPTION, True
            time.sleep(INTERVAL)
        return
    
    if g_phase == 'cover_put':
        put_pos = api.get_pos(index=1)
        if put_pos < 0:
            print(f">>> 平仓看跌期权空头")
            api.buycover(order_type='market', reason='平仓看跌期权空头', index=1)
            g_phase, g_waiting = 'done', True
            time.sleep(INTERVAL)
        return
    
    if g_phase == 'done':
        print(f"\n{'='*60}")
        print(f"期权交易测试完成 - {datetime.now().strftime('%H:%M:%S')}")
        print(f"总报单: {g_stats['orders']}笔 | 总成交: {g_stats['trades']}笔")
        print(f"{'='*60}")
        print(f"\n按 Ctrl+C 退出\n")
        g_phase = 'finished'


if __name__ == "__main__":
    
    # ==================== 运行模式选择 ====================
    RUN_MODE = RunMode.SIMNOW      # SIMNOW 或 REAL_TRADING
    
    # ==================== 配置 ====================
    if RUN_MODE == RunMode.SIMNOW:
        # SIMNOW模拟盘配置
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='simnow_default',      # 账户名（在trading_config.py的ACCOUNTS中定义）
            server_name='电信1',           # SIMNOW服务器: 电信1/电信2/移动/TEST(盘后测试)
            
            # -------- 多数据源配置 --------
            # 每个数据源对应一个index: 0=看涨期权, 1=看跌期权, 2=标的期货
            data_sources=[
                {'symbol': CALL_OPTION, 'kline_period': 'tick', 'price_tick': 0.02},  # index=0
                {'symbol': PUT_OPTION, 'kline_period': 'tick', 'price_tick': 0.02},   # index=1
                {'symbol': UNDERLYING, 'kline_period': 'tick', 'price_tick': 0.02},   # index=2
            ],
            
            # -------- 交易参数 --------
            order_offset_ticks=2,         # 期权需要正向偏移确保委托价>0
            
            # -------- 智能算法交易配置 (新增) --------
            algo_trading=True,            # 启用算法交易
            order_timeout=10,             # 订单超时时间(秒)
            retry_limit=3,                # 最大重试次数
            retry_offset_ticks=2,         # 重试时的超价跳数
            
            # -------- 回调模式 --------
            enable_tick_callback=True,     # 期权策略需要TICK驱动
            preload_history=False,         # 是否预加载历史K线
            
            # -------- 数据保存 --------
            save_kline_csv=False,          # 保存K线到CSV文件
            save_kline_db=False,           # 保存K线到数据库
            save_tick_csv=False,           # 保存TICK到CSV文件
            save_tick_db=False,            # 保存TICK到数据库
        )
    
    elif RUN_MODE == RunMode.REAL_TRADING:
        # 实盘CTP配置
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='real_default',        # 账户名（在trading_config.py的ACCOUNTS中定义）
            # 实盘账户需要配置: broker_id, investor_id, password,
            #                  md_server, td_server, app_id, auth_code
            
            # -------- 多数据源配置 --------
            data_sources=[
                {'symbol': CALL_OPTION, 'kline_period': '1m', 'price_tick': 0.02},  # index=0
                {'symbol': PUT_OPTION, 'kline_period': '1m', 'price_tick': 0.02},   # index=1
                {'symbol': UNDERLYING, 'kline_period': '1m', 'price_tick': 0.02},   # index=2
            ],
            
            # -------- 交易参数 --------
            order_offset_ticks=10,         # 期权需要正向偏移确保委托价>0
            
            # -------- 智能算法交易配置 (新增) --------
            algo_trading=True,            # 启用算法交易
            order_timeout=10,             # 订单超时时间(秒)
            retry_limit=3,                # 最大重试次数
            retry_offset_ticks=5,         # 重试时的超价跳数
            
            # -------- 回调模式 --------
            enable_tick_callback=True,     # 期权策略需要TICK驱动
            preload_history=False,         # 预加载历史K线
            
            # -------- 数据保存 --------
            save_kline_csv=False,          # 保存K线到CSV
            save_kline_db=False,           # 保存K线到数据库
            save_tick_csv=False,           # 保存TICK到CSV
            save_tick_db=False,            # 保存TICK到数据库
        )
    
    # ==================== 运行 ====================
    print(f"\n运行模式: {RUN_MODE.value}")
    
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)
    
    try:
        runner.run(
            strategy=strategy,
            initialize=initialize,
            on_trade=on_trade,
            on_order=on_order,
            on_order_error=on_order_error,
            on_position=on_position,
        )
    except KeyboardInterrupt:
        print(f"\n{'='*40}")
        print(f"【最终行情】")
        print(f"  {UNDERLYING}: {g_prices['underlying']:.2f}")
        print(f"  {CALL_OPTION}: {g_prices['call']:.2f}")
        print(f"  {PUT_OPTION}: {g_prices['put']:.2f}")
        print(f"{'='*40}")
        runner.stop()
