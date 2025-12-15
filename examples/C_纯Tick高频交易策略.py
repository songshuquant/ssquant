"""
TICK流策略示例 - 简化版多空交替策略

支持三种运行模式:
1. 历史数据回测 - 使用K线数据模拟TICK流
2. SIMNOW模拟交易 - 使用实时TICK数据
3. 实盘CTP交易 - 使用实时TICK数据

策略规则：
1. 每10个TICK/K线交易一次
2. 第一次默认做多
3. 后续多空交替（多->空->多->空...）
4. 实盘使用市价单，回测使用下一根K线开盘价

支持的CTP回调函数（仅实盘/SIMNOW模式有效）：
1. on_trade      - 成交回调：订单成交时触发
2. on_order      - 报单回调：报单状态变化时触发
3. on_cancel     - 撤单回调：订单被撤销时触发
4. on_order_error - 报单错误回调：报单失败时触发
5. on_cancel_error - 撤单错误回调：撤单失败时触发
6. on_account    - 账户资金回调：资金变化时触发
7. on_position   - 持仓回调：持仓查询/变化时触发
"""

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode


# ========== 全局状态变量 ==========
g_tick_counter = 0         # TICK计数器
g_next_direction = 'long'  # 下次交易方向（'long' 或 'short'）
g_trade_count = 0          # 交易次数统计
g_pos = 0                  # 当前持仓


def initialize(api: StrategyAPI):
    """策略初始化函数"""
    global g_tick_counter, g_next_direction, g_trade_count, g_pos
    
    api.log("=" * 60)
    api.log("TICK流策略初始化 - 简化版")
    api.log("=" * 60)
    api.log("策略规则:")
    api.log("  1. 每10个TICK交易一次")
    api.log("  2. 第一次默认做多")
    api.log("  3. 之后多空交替")
    api.log("  4. 使用市价单")
    api.log("=" * 60)
    
    # 初始化全局状态
    g_tick_counter = 0
    g_next_direction = 'long'
    g_trade_count = 0
    g_pos = 0
    
    # 显示初始持仓
    initial_pos = api.get_pos()
    api.log(f"[初始持仓] 净持仓: {initial_pos}")
    
    # 显示预加载的历史TICK数据（SIMNOW/实盘模式）
    tick_count = api.get_ticks_count()
    if tick_count > 0:
        api.log(f"[历史TICK] 已预加载 {tick_count} 条历史TICK数据")
        # 示例：获取所有历史TICK用于计算指标
        # all_ticks = api.get_ticks(window=tick_count)
        # avg_price = all_ticks['LastPrice'].mean()
        # api.log(f"[历史TICK] 平均价格: {avg_price:.2f}")


# ==================== CTP回调函数 ====================
# 以下回调函数都是可选的，根据需要选择使用
# 只在实盘模式（SIMNOW/REAL_TRADING）下有效

def on_trade(data):
    """
    成交回调 - 订单成交时触发
    
    触发时机：每次有订单成交时
    
    data字段说明：
        InstrumentID  - 合约代码，如 'rb2601'
        Direction     - 方向，'0'=买, '1'=卖
        OffsetFlag    - 开平标志，'0'=开仓, '1'=平仓, '3'=平今, '4'=平昨
        Price         - 成交价格
        Volume        - 成交数量
        TradeTime     - 成交时间，如 '14:30:25'
        TradeID       - 成交编号
        TradeDate     - 成交日期
    """
    direction = '买' if data['Direction'] == '0' else '卖'
    offset_map = {'0': '开', '1': '平', '3': '平今', '4': '平昨'}
    offset = offset_map.get(data['OffsetFlag'], '未知')
    
    print(f"[成交] {data['InstrumentID']} {direction}{offset} "
          f"价格:{data['Price']:.2f} 数量:{data['Volume']} "
          f"时间:{data['TradeTime']}")


def on_order(data):
    """
    报单回调 - 报单状态变化时触发
    
    触发时机：报单提交后、部分成交、全部成交、撤单等状态变化时
    
    data字段说明：
        InstrumentID        - 合约代码
        Direction           - 方向，'0'=买, '1'=卖
        CombOffsetFlag      - 开平标志
        LimitPrice          - 限价
        VolumeTotalOriginal - 报单总数量
        VolumeTraded        - 已成交数量
        VolumeTotal         - 剩余数量
        OrderStatus         - 状态，'0'=全部成交, '1'=部分成交, '3'=未成交, '5'=撤单
        OrderSysID          - 报单编号
        InsertTime          - 报单时间
        StatusMsg           - 状态信息
    """
    status_map = {'0': '全部成交', '1': '部分成交', '3': '未成交', '5': '撤单'}
    status = status_map.get(data['OrderStatus'], f"状态{data['OrderStatus']}")
    direction = '买' if data.get('Direction') == '0' else '卖'
    
    print(f"[报单] {data['InstrumentID']} {direction} "
          f"价格:{data.get('LimitPrice', 0):.2f} 状态:{status}")


def on_cancel(data):
    """
    撤单回调 - 订单被撤销时触发
    
    触发时机：订单撤单成功时
    
    data字段说明：
        InstrumentID        - 合约代码
        Direction           - 方向
        CombOffsetFlag      - 开平标志
        LimitPrice          - 限价
        VolumeTotalOriginal - 报单总数量
        VolumeTraded        - 已成交数量（撤单前）
        OrderSysID          - 报单编号
        ExchangeID          - 交易所代码
        InsertTime          - 下单时间
        CancelTime          - 撤单时间
    """
    direction = '买' if data.get('Direction') == '0' else '卖'
    offset_map = {'0': '开', '1': '平', '3': '平今', '4': '平昨'}
    offset_flag = data.get('CombOffsetFlag', '0')
    offset = offset_map.get(offset_flag[0] if offset_flag else '0', '未知')
    
    total_vol = data.get('VolumeTotalOriginal', 0)
    traded_vol = data.get('VolumeTraded', 0)
    cancelled_vol = total_vol - traded_vol
    
    print(f"[撤单] {data['InstrumentID']} {direction}{offset} "
          f"价格:{data.get('LimitPrice', 0):.2f} "
          f"撤销:{cancelled_vol}手 已成交:{traded_vol}手")


def on_order_error(data):
    """
    报单错误回调 - 报单失败时触发
    
    触发时机：报单被CTP/交易所拒绝时
    
    data字段说明：
        ErrorID   - 错误码
        ErrorMsg  - 错误描述
    
    常见错误码：
        22  - 合约不存在或未订阅
        30  - 平仓数量超出持仓数量
        36  - 资金不足
        44  - 价格超出涨跌停板限制
        50  - 平今仓位不足，请改用平昨仓
        51  - 持仓不足或持仓方向错误
        68  - 每秒报单数超过限制
    """
    print(f"[报单错误] 错误码:{data['ErrorID']} - {data['ErrorMsg']}")


def on_cancel_error(data):
    """
    撤单错误回调 - 撤单失败时触发
    
    触发时机：撤单被CTP/交易所拒绝时
    
    data字段说明：
        ErrorID   - 错误码
        ErrorMsg  - 错误描述
    
    常见错误码：
        25  - 撤单报单已全成交
        26  - 撤单被拒绝：订单已成交
        77  - 没有可撤的单
    """
    print(f"[撤单错误] 错误码:{data['ErrorID']} - {data['ErrorMsg']}")


def on_account(data):
    """
    账户资金回调 - 资金变化时触发
    
    触发时机：账户查询或资金变化时
    
    data字段说明：
        Balance         - 账户权益
        Available       - 可用资金
        FrozenMargin    - 冻结保证金
        FrozenCommission- 冻结手续费
        PositionProfit  - 持仓盈亏
        CloseProfit     - 平仓盈亏
        Commission      - 手续费
        CurrMargin      - 当前保证金
        WithdrawQuota   - 可取资金
    """
    print(f"[账户] 权益:{data.get('Balance', 0):.2f} "
          f"可用:{data.get('Available', 0):.2f} "
          f"持仓盈亏:{data.get('PositionProfit', 0):.2f}")


def on_position(data):
    """
    持仓回调 - 持仓查询/变化时触发
    
    触发时机：持仓查询或持仓变化时
    
    data字段说明：
        InstrumentID    - 合约代码
        PosiDirection   - 持仓方向，'1'=净, '2'=多, '3'=空
        Position        - 总持仓量
        TodayPosition   - 今日持仓
        YdPosition      - 昨日持仓
        PositionProfit  - 持仓盈亏
        PositionCost    - 持仓成本
        OpenCost        - 开仓成本
        Available       - 可用仓位
    """
    direction_map = {'1': '净', '2': '多', '3': '空'}
    direction = direction_map.get(data.get('PosiDirection', ''), '未知')
    
    print(f"[持仓] {data['InstrumentID']} {direction} "
          f"总:{data.get('Position', 0)} "
          f"(今:{data.get('TodayPosition', 0)} 昨:{data.get('YdPosition', 0)})")


def tick_flow_strategy(api: StrategyAPI):
    """
    TICK流策略 - 简化版多空交替
    
    策略逻辑：
    1. 每10个TICK/K线交易一次
    2. 第一次做多，之后多空交替
    3. 实盘使用市价单，回测使用下一根K线开盘价
    
    兼容模式：
    - 实盘/SIMNOW：使用TICK数据驱动
    - 回测：使用K线数据驱动（每根K线相当于一个TICK）
    """
    global g_tick_counter, g_next_direction, g_trade_count, g_pos
    
    # 计数器（TICK或K线）
    g_tick_counter += 1
    
    # 获取当前价格（兼容回测和实盘）
    current_tick = api.get_tick()
    if current_tick is not None:
        # 实盘模式：使用TICK数据
        last_price = current_tick.get('LastPrice', 0)
    else:
        # 回测模式：使用K线收盘价
        last_price = api.get_price()
        if last_price is None or last_price == 0:
            return
    
    # 每10个tick/K线打印一次状态
    if g_tick_counter % 10 == 0:
        api.log(f"[#{g_tick_counter}] 价格:{last_price:.2f} "
                f"持仓:{g_pos} 下次:{g_next_direction} 已交易:{g_trade_count}次")
    
    # 每10个TICK/K线交易一次
    if g_tick_counter % 10 == 0:
        g_trade_count += 1
        
        api.log(f"\n[第{g_trade_count}次交易] 方向: {g_next_direction}")
        
        # 下单方式：TICK数据（实盘或回测）都使用market
        order_type = 'market'
        
        if g_next_direction == 'long':
            # 有空仓先平空
            if g_pos < 0:
                api.buycover(order_type=order_type)
                api.log("✓ 平空仓")
                g_pos = 0
            
            # 开多仓
            api.buy(volume=1, order_type=order_type)
            api.log("✓ 开多仓 1手")
            g_pos = 1
            g_next_direction = 'short'
            
        else:  # short
            # 有多仓先平多
            if g_pos > 0:
                api.sell(order_type=order_type)
                api.log("✓ 平多仓")
                g_pos = 0
            
            # 开空仓
            api.sellshort(volume=1, order_type=order_type)
            api.log("✓ 开空仓 1手")
            g_pos = -1
            g_next_direction = 'long'


if __name__ == "__main__":
    from ssquant.config.trading_config import get_config
    
    # ==================== 用户配置区域 ====================
    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘)
    RUN_MODE = RunMode.SIMNOW
    
    # 交易合约（SIMNOW/实盘用具体合约，回测用主连）
    SYMBOL = 'au2602'
    
    # ==================== 获取配置 ====================
    if RUN_MODE == RunMode.BACKTEST:
        # TICK回测配置
        # ⚠️ TICK数据只能从本地数据库获取，远程服务器不提供
        # 数据库表名格式: {symbol}_tick，如 rb888_tick, au888_tick
        config = get_config(RUN_MODE,
            # -------- 合约配置 --------
            symbol='au888',                # 回测合约（主力连续用888后缀）
            start_date='2025-12-11',       # 回测开始日期（需有对应TICK数据）
            end_date='2025-12-11',         # 回测结束日期
            kline_period='tick',           # ⭐ 数据周期: tick=使用TICK数据回测
            
            # -------- 回测成本参数 --------
            price_tick=0.02,               # 最小变动价位（黄金=0.02, 白银=1, 螺纹=1）
            contract_multiplier=1000,      # 合约乘数（黄金=1000, 白银=15, 螺纹=10）
            slippage_ticks=1,              # 滑点跳数（模拟成交时的滑点）
        )
    
    elif RUN_MODE == RunMode.SIMNOW:
        # SIMNOW模拟盘配置
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='simnow_default',      # 账户名（在trading_config.py的ACCOUNTS中定义）
            server_name='电信1',           # SIMNOW服务器: 电信1/电信2/移动/TEST(盘后测试)
            
            # -------- 合约配置 --------
            symbol=SYMBOL,                 # 交易合约代码（需用具体月份合约如rb2601）
            kline_period='tick',           # 数据周期: tick/1m/5m/15m/30m/1h/1d
            enable_tick_callback=True,    # True=每个TICK触发策略, False=每根K线触发

            # -------- 历史TICK数据预加载 --------
            # ⭐ TICK模式下支持从数据库预加载历史TICK数据
            # 前提：数据库中需有对应的TICK表（通过save_tick_db=True采集）
            # TICK表名格式：{主连符号}_tick，如 au888_tick
            preload_history=True,          # 是否预加载历史TICK数据
            history_lookback_bars=1000,    # 预加载TICK条数（TICK模式下建议1000+）
            # history_symbol='au888',      # 可选：自定义历史数据源（默认自动推导为主连）
            # 获取历史TICK: tick_count = api.get_ticks_count()
            #              all_ticks = api.get_ticks(window=tick_count)
            
            # -------- 交易参数 --------
            price_tick=0.02,               # 最小变动价位（螺纹=1, 黄金=0.02）
            order_offset_ticks=5,         # 超价跳数（确保成交，10跳=0.2元偏移）
            
            # -------- 智能算法交易配置 (新增) --------
            algo_trading=False,             # 启用算法交易
            order_timeout=5,               # 订单超时时间(秒) - 高频策略超时要短
            retry_limit=3,                 # 最大重试次数
            retry_offset_ticks=5,          # 重试时的超价跳数
            
            # -------- 数据保存 --------
            save_kline_csv=False,          # 保存K线到CSV文件
            save_kline_db=False,           # 保存K线到数据库
            save_tick_csv=False,           # 保存TICK到CSV文件
            save_tick_db=False,            # 保存TICK到数据库（用于后续预加载）
            data_save_path='./live_data',  # CSV文件保存路径
            db_path='./data_cache/backtest_data.db',  # 数据库文件路径
        )
    
    elif RUN_MODE == RunMode.REAL_TRADING:
        # 实盘CTP配置
        config = get_config(RUN_MODE,
            # -------- 账户配置 --------
            account='real_default',        # 账户名（在trading_config.py的ACCOUNTS中定义）
            # 实盘账户需要配置: broker_id, investor_id, password,
            #                  md_server, td_server, app_id, auth_code
            
            # -------- 合约配置 --------
            symbol=SYMBOL,                 # 交易合约代码
            kline_period='tick',           # TICK模式（高频策略）
            
            # -------- 回调模式 --------
            enable_tick_callback=True,    # True=每个TICK触发策略, False=每根K线触发
            
            # -------- 历史TICK数据预加载 --------
            # ⭐ TICK模式下支持从数据库预加载历史TICK数据
            # TICK表名格式：{主连符号}_tick，如 au888_tick
            preload_history=True,          # 是否预加载历史TICK
            history_lookback_bars=1000,    # 预加载TICK条数
            # history_symbol='au888',      # 可选：自定义历史数据源（默认自动推导为主连）
            
            # -------- 交易参数 --------
            price_tick=0.02,               # 最小变动价位（黄金=0.02）
            order_offset_ticks=5,          # 超价跳数
            
            # -------- 智能算法交易配置 (新增) --------
            algo_trading=False,             # 启用算法交易
            order_timeout=5,               # 订单超时时间(秒) - 高频策略超时要短
            retry_limit=3,                 # 最大重试次数
            retry_offset_ticks=5,          # 重试时的超价跳数
            
            # -------- 数据保存 --------
            save_kline_csv=False,          # 保存K线到CSV
            save_kline_db=False,           # 保存K线到数据库
            save_tick_csv=False,           # 保存TICK到CSV
            save_tick_db=False,            # 保存TICK到数据库（用于后续预加载）
            data_save_path='./live_data',  # CSV文件保存路径
            db_path='./data_cache/backtest_data.db',  # 数据库文件路径
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")
    
    # ==================== 运行策略 ====================
    print("\n" + "=" * 60)
    print("TICK流策略 - 简化版多空交替")
    print("=" * 60)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {config['symbol']}")
    print(f"数据周期: {config.get('kline_period', 'tick')}")
    if RUN_MODE == RunMode.BACKTEST:
        print(f"回测区间: {config.get('start_date')} 至 {config.get('end_date')}")
    print(f"策略规则: 每10个TICK交易一次，多空交替")
    print("=" * 60 + "\n")
    
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)
    
    try:
        results = runner.run(
            strategy=tick_flow_strategy,
            initialize=initialize,
            # CTP回调函数（可选，按需启用）
            on_trade=on_trade,           # 成交回调
            on_order=on_order,           # 报单回调
            on_cancel=on_cancel,         # 撤单回调
            on_order_error=on_order_error,   # 报单错误回调
            on_cancel_error=on_cancel_error, # 撤单错误回调
            on_account=on_account,       # 账户资金回调
            on_position=on_position,     # 持仓回调
        )
    except KeyboardInterrupt:
        print("\n用户中断")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()
