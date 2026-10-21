"""订单流与深度数据交易策略 - data_server K线推送模式

本策略充分利用 data_server 提供的**订单流分析**和**盘口深度**数据，
这些数据是 ssquant 本地聚合模式所没有的，只有 data_server 模式才能获取。

data_server K线包含的完整字段:
=================================
| 字段分类     | 字段名              | 说明                          |
|------------|--------------------|-----------------------------|
| 基础OHLCV   | datetime           | K线时间                       |
|            | symbol             | 合约代码                       |
|            | open/high/low/close| 开高低收                       |
|            | volume             | 成交量                         |
|            | amount             | 成交额                         |
| 持仓量      | openint            | 持仓量变化（当根K线内增减）         |
|            | cumulative_openint | 累计持仓量（绝对值）              |
| 深度数据    | open_bidp          | K线开盘时的买一价                |
|            | open_askp          | K线开盘时的卖一价                |
|            | close_bidp         | K线收盘时的买一价                |
|            | close_askp         | K线收盘时的卖一价                |
| 订单流      | 开仓               | 开仓成交量                      |
|            | 平仓               | 平仓成交量                      |
|            | 多开               | 多头主动开仓（价>=卖一 且 OI↑）    |
|            | 空开               | 空头主动开仓（价<=买一 且 OI↑）    |
|            | 多平               | 多头被动平仓（价<=买一 且 OI↓）    |
|            | 空平               | 空头被动平仓（价>=卖一 且 OI↓）    |
|            | 双开               | 中性开仓（OI↑但方向不明）          |
|            | 双平               | 中性平仓（OI↓但方向不明）          |
|            | 双换               | 换手（OI不变，方向中性）           |
|            | B                  | 主动买入成交量（价>=卖一价）        |
|            | S                  | 主动卖出成交量（价<=买一价）        |
|            | 未知               | 无法归类的成交量                  |

策略逻辑（多因子评分体系）:
=================================
1. 【订单流动量因子】多开净量 = 多开 - 空开
   - 多开持续大于空开 → 多头正在积极建仓，看涨
   - 空开持续大于多开 → 空头正在积极建仓，看跌

2. 【主动买卖因子】净主动量 = B - S
   - B > S → 市场主动买入占优，看涨
   - S > B → 市场主动卖出占优，看跌

3. 【资金流向因子】资金流向 = 开仓 - 平仓
   - 开仓 > 平仓 → 新资金入场（趋势可能延续）
   - 平仓 > 开仓 → 资金离场（趋势可能减弱）

4. 【盘口压力因子】盘口变化 = (close_bidp - open_bidp) - (close_askp - open_askp)
   - 买一抬升 + 卖一不动 → 买压增强
   - 卖一下移 + 买一不动 → 卖压增强

5. 各因子净差比×125放大评分，超过阈值时开仓，反向超过缓冲线时平仓

使用前提:
=================================
1. 已安装框架依赖，其中远程行情统一通过 ssquantdata>=0.1.3 获取。
2. 已配置有效的 SDK 环境变量账号，或 trading_config.py 中的俱乐部账号。
3. 数据源提供对应的订单流和深度字段；未知值不应当作真实零。
4. SDK 报告实时缺口后策略会停止，需要核验数据并重建状态后重新启动。
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config
import pandas as pd
import numpy as np

def initialize(api: StrategyAPI):
    """策略初始化"""
    api.log("=" * 60)
    api.log("订单流与深度数据策略 初始化")
    api.log("=" * 60)
    api.log("本策略利用 data_server 的订单流+盘口深度数据")
    api.log("多因子评分: 订单流动量 + 主动买卖 + 资金流向 + 盘口压力")
    api.log("=" * 60)

# ========== 辅助函数 ==========

def safe_rolling_sum(series, window):
    """安全的滚动求和，处理NaN"""
    return series.rolling(window, min_periods=1).sum()

def safe_rolling_mean(series, window):
    """安全的滚动均值，处理NaN"""
    return series.rolling(window, min_periods=1).mean()

def order_flow_strategy(api: StrategyAPI):
    """
    订单流与深度数据策略

    参数:
        lookback: 订单流统计回看窗口（K线根数）
        score_threshold: 开仓评分阈值（满分100）
        ma_period: 趋势过滤均线周期
        exit_ratio: 平仓反向阈值比例（评分反向达到 score_threshold * exit_ratio 时平仓）
        min_hold: 最小持仓周期（开仓后至少持有N根K线才允许平仓/反手）
    """
    # 获取参数
    lookback = api.get_param('lookback', 15)          # 回看15根K线的订单流（平滑噪声）
    score_threshold = api.get_param('score_threshold', 40)  # 40分以上才开仓（需多因子共振）
    ma_period = api.get_param('ma_period', 60)        # 60周期均线做趋势过滤（3m×60=3小时趋势）
    exit_ratio = api.get_param('exit_ratio', 0.6)     # 平仓缓冲：评分反向达阈值60%才平仓
    min_hold = api.get_param('min_hold', 20)          # 开仓后至少持有20根K线（3m×20=1小时）

    # 确保有数据源
    if not api.require_data_sources(1):
        return

    # 获取K线数据
    klines = api.get_klines(0)
    if klines is None or len(klines) < max(lookback, ma_period) + 5:
        return

    bar_datetime = api.get_datetime(0)
    bar_idx = api.get_idx(0)
    close = klines['close']
    current_pos = api.get_pos(0)
    current_price = close.iloc[-1]
    # 打印当前处理的数据
    if bar_idx % 1 == 0:
        api.log(f"当前Bar索引: {bar_idx}, 日期时间: {bar_datetime},K线:{klines}")

    if not hasattr(order_flow_strategy, '_entry_bar'):
        order_flow_strategy._entry_bar = 0
    bars_since_entry = bar_idx - order_flow_strategy._entry_bar

    # ========== 首次触发：打印字段信息 ==========
    if bar_idx <= 1:
        print(f"\n{'='*80}")
        print(f"[数据检查] K线列名: {list(klines.columns)}")
        print(f"[数据检查] 最后一条K线完整数据:")
        last_row = klines.iloc[-1]
        for col in klines.columns:
            print(f"  {col}: {last_row[col]}")
        print(f"{'='*80}\n")

    # ========== 检查订单流字段是否可用 ==========
    has_order_flow = '多开' in klines.columns and '空开' in klines.columns
    has_depth = 'open_bidp' in klines.columns and 'close_bidp' in klines.columns

    if not has_order_flow and not has_depth:
        # 没有订单流和深度数据，仅用基础OHLCV
        api.log(f"[警告] 未检测到订单流/深度字段，请确认使用 data_server 模式")
        return

    # ========== 计算各因子评分（满分各25分，总分100） ==========
    total_score = 0       # 正数看多，负数看空
    factor_details = {}   # 记录每个因子的详细信息

    # ------ 因子1: 订单流动量（25分）------
    # 多开 - 空开: 多头净建仓量
    factor1_score = 0
    if has_order_flow:
        duo_kai = klines['多开']
        kong_kai = klines['空开']

        # 最近N根K线的多开/空开累计
        recent_duo_kai = safe_rolling_sum(duo_kai, lookback).iloc[-1]
        recent_kong_kai = safe_rolling_sum(kong_kai, lookback).iloc[-1]

        total_open = recent_duo_kai + recent_kong_kai
        if total_open > 0:
            net_ratio = (recent_duo_kai - recent_kong_kai) / total_open
            factor1_score = max(-25, min(25, net_ratio * 125))

        factor_details['订单流动量'] = (
            f"多开:{recent_duo_kai:.0f} 空开:{recent_kong_kai:.0f} "
            f"净比:{(recent_duo_kai-recent_kong_kai)/max(total_open,1)*100:+.1f}% "
            f"得分:{factor1_score:+.1f}"
        )

    total_score += factor1_score

    # ------ 因子2: 主动买卖（25分）------
    # B - S: 净主动买入量
    factor2_score = 0
    if has_order_flow and 'B' in klines.columns:
        buy_vol = klines['B']
        sell_vol = klines['S']

        recent_buy = safe_rolling_sum(buy_vol, lookback).iloc[-1]
        recent_sell = safe_rolling_sum(sell_vol, lookback).iloc[-1]

        total_bs = recent_buy + recent_sell
        if total_bs > 0:
            net_ratio = (recent_buy - recent_sell) / total_bs
            factor2_score = max(-25, min(25, net_ratio * 125))

        factor_details['主动买卖'] = (
            f"B:{recent_buy:.0f} S:{recent_sell:.0f} "
            f"净比:{(recent_buy-recent_sell)/max(total_bs,1)*100:+.1f}% "
            f"得分:{factor2_score:+.1f}"
        )

    total_score += factor2_score

    # ------ 因子3: 资金流向（25分）------
    # 开仓 - 平仓: 资金净流入
    factor3_score = 0
    if has_order_flow:
        kai_cang = klines['开仓']
        ping_cang = klines['平仓']

        recent_kai = safe_rolling_sum(kai_cang, lookback).iloc[-1]
        recent_ping = safe_rolling_sum(ping_cang, lookback).iloc[-1]

        total_kp = recent_kai + recent_ping
        if total_kp > 0:
            net_ratio = (recent_kai - recent_ping) / total_kp
            price_direction = 1 if close.iloc[-1] > close.iloc[-lookback] else -1
            factor3_score = max(-25, min(25, net_ratio * 125 * price_direction))

        factor_details['资金流向'] = (
            f"开仓:{recent_kai:.0f} 平仓:{recent_ping:.0f} "
            f"净比:{(recent_kai-recent_ping)/max(total_kp,1)*100:+.1f}% "
            f"得分:{factor3_score:+.1f}"
        )

    total_score += factor3_score

    # ------ 因子4: 盘口压力（25分）------
    # 买一价抬升 vs 卖一价抬升
    factor4_score = 0
    if has_depth:
        open_bid = klines['open_bidp']
        close_bid = klines['close_bidp']
        open_ask = klines['open_askp']
        close_ask = klines['close_askp']

        # 每根K线内的盘口变化
        bid_change = close_bid - open_bid   # 买一抬升为正
        ask_change = close_ask - open_ask   # 卖一抬升为正

        # 盘口压力 = 买压 - 卖压
        # 买一持续抬升（bid_change > 0）且卖一不动 → 买压强
        depth_pressure = bid_change - ask_change

        recent_pressure = safe_rolling_sum(depth_pressure, lookback).iloc[-1]

        # 用价格归一化
        if current_price > 0:
            normalized_pressure = recent_pressure / current_price * 1000
            factor4_score = max(-25, min(25, normalized_pressure * 5))

        # 额外指标：K线内价差变化
        spread_open = open_ask - open_bid    # 开盘时的买卖价差
        spread_close = close_ask - close_bid  # 收盘时的买卖价差
        avg_spread = safe_rolling_mean(spread_close, lookback).iloc[-1]

        factor_details['盘口压力'] = (
            f"买压:{safe_rolling_sum(bid_change, lookback).iloc[-1]:+.2f} "
            f"卖压:{safe_rolling_sum(ask_change, lookback).iloc[-1]:+.2f} "
            f"均价差:{avg_spread:.2f} "
            f"得分:{factor4_score:+.1f}"
        )

    total_score += factor4_score
    # ========== 输出分析信息 ==========

    # ========== 趋势过滤 ==========
    ma = close.rolling(ma_period).mean()
    if pd.isna(ma.iloc[-1]):
        return

    trend_up = current_price > ma.iloc[-1]
    trend_down = current_price < ma.iloc[-1]

    for name, detail in factor_details.items():
        print(f"  [{name}] {detail}")

    # ========== 持仓量变化信息 ==========
    if 'openint' in klines.columns:
        oi_change = klines['openint'].iloc[-1]
        cum_oi = klines['cumulative_openint'].iloc[-1] if 'cumulative_openint' in klines.columns else 0
        print(f"  [持仓量] 变化:{oi_change:+.0f} 累计:{cum_oi:.0f}")

    # ========== 交易决策 ==========
    unit = 1
    exit_line = score_threshold * exit_ratio
    can_exit = (current_pos == 0) or (bars_since_entry >= min_hold)

    # 开多条件: 评分超过阈值 + 趋势向上
    if total_score >= score_threshold and trend_up:
        if current_pos < 0 and can_exit:
            api.log(f"⚡ 评分{total_score:+.1f}≥{score_threshold}，趋势↑，平空反多 "
                    f"价格:{current_price:.2f}")
            api.buycover(volume=unit, order_type='next_bar_open', index=0)
            api.buy(volume=unit, order_type='next_bar_open', index=0)
            order_flow_strategy._entry_bar = bar_idx
        elif current_pos == 0:
            api.log(f"⚡ 评分{total_score:+.1f}≥{score_threshold}，趋势↑，开多 "
                    f"价格:{current_price:.2f}")
            api.buy(volume=unit, order_type='next_bar_open', index=0)
            order_flow_strategy._entry_bar = bar_idx

    # 开空条件: 评分低于负阈值 + 趋势向下
    elif total_score <= -score_threshold and trend_down:
        if current_pos > 0 and can_exit:
            api.log(f"⚡ 评分{total_score:+.1f}≤{-score_threshold}，趋势↓，平多反空 "
                    f"价格:{current_price:.2f}")
            api.sell(volume=unit, order_type='next_bar_open', index=0)
            api.sellshort(volume=unit, order_type='next_bar_open', index=0)
            order_flow_strategy._entry_bar = bar_idx
        elif current_pos == 0:
            api.log(f"⚡ 评分{total_score:+.1f}≤{-score_threshold}，趋势↓，开空 "
                    f"价格:{current_price:.2f}")
            api.sellshort(volume=unit, order_type='next_bar_open', index=0)
            order_flow_strategy._entry_bar = bar_idx

    # 平仓条件: 评分明显反向 + 已过最小持仓周期
    elif current_pos > 0 and total_score < -exit_line and can_exit:
        api.log(f"📤 多头评分反转({total_score:+.1f}<{-exit_line:.0f})，持仓{bars_since_entry}根，平多 价格:{current_price:.2f}")
        api.sell(volume=unit, order_type='next_bar_open', index=0)

    elif current_pos < 0 and total_score > exit_line and can_exit:
        api.log(f"📤 空头评分反转({total_score:+.1f}>{exit_line:.0f})，持仓{bars_since_entry}根，平空 价格:{current_price:.2f}")
        api.buycover(volume=unit, order_type='next_bar_open', index=0)

if __name__ == "__main__":

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.SIMNOW

    # ========== 策略参数 ==========
    strategy_params = {
        'lookback': 5,              # 订单流回看窗口（根数）
        'score_threshold': 25,      # 开仓评分阈值（4因子各25分，满分±100）
        'ma_period': 20,            # 趋势过滤均线
        'exit_ratio': 0.4,          # 平仓缓冲：评分反向达阈值40%才平仓
    }

    # ========== 选择交易品种 ==========
    # 建议选择活跃品种（成交量大、订单流数据丰富）
    SYMBOL = 'sc2605'       # 螺纹钢（活跃品种，订单流数据质量好）
    PERIOD = '1m'           # 3分钟K线（订单流在短周期更有意义）

    # ========== 获取配置 ==========
    if RUN_MODE == RunMode.BACKTEST:
        # ==================== 回测模式（data_server 有订单流数据时同样可用） ====================
        config = get_config(RUN_MODE,
            start_date='2026-3-04', # 回测开始日期
            end_date='2026-03-31',  # 回测结束日期
            initial_capital=100000, # 初始资金（元）
            lookback_bars=500,      # 回溯K线窗口（IndicatorCache预热用）
            data_sources=[{
                'symbol': 'SH888',  # 回测用888
                'kline_period': PERIOD,
                'adjust_type': '1',
                'slippage_ticks': 1,
            }],
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )

    elif RUN_MODE == RunMode.SIMNOW:
        # ==================== SIMNOW + data_server（完整订单流+深度数据） ====================
        config = get_config(RUN_MODE,
            account='simnow_default', # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',      # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour

            kline_source='data_server', # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            data_sources=[{
                'symbol': SYMBOL,
                'kline_period': PERIOD,
                'order_offset_ticks': 5,

                'algo_trading': False,
                'order_timeout': 10,
                'retry_limit': 3,
                'retry_offset_ticks': 5,

                'preload_history': False,
            }],

            lookback_bars=500,      # 回溯K线窗口（IndicatorCache预热用）
            enable_tick_callback=False, # 是否启用逐Tick回调（高CPU占用）

            save_kline_csv=False,   # 是否保存K线到CSV文件
            save_kline_db=False,    # 是否保存K线到SQLite数据库
            save_tick_csv=False,    # 是否保存Tick到CSV文件
            save_tick_db=False,     # 是否保存Tick到SQLite数据库
        )

    elif RUN_MODE == RunMode.REAL_TRADING:
        # ==================== 实盘 + data_server ====================
        config = get_config(RUN_MODE,
            account='real_default', # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）

            kline_source='data_server', # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            data_sources=[{
                'symbol': SYMBOL,
                'kline_period': PERIOD,
                'order_offset_ticks': 5,

                'algo_trading': True,
                'order_timeout': 10,
                'retry_limit': 3,
                'retry_offset_ticks': 5,

                'preload_history': False,
            }],

            lookback_bars=500,      # 回溯窗口（IndicatorCache重算范围）
            enable_tick_callback=False, # Tick回调

            save_kline_csv=False,   # 保存K线CSV
            save_kline_db=True,     # 保存K线DB
            save_tick_csv=False,    # 保存Tick CSV
            save_tick_db=False,     # 保存Tick DB
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")

    # ========== 打印配置 ==========
    print("\n" + "=" * 80)
    print("订单流与深度数据交易策略 - data_server 专属模式")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"K线数据源: {config.get('kline_source', 'local')}")
    print(f"交易品种: {SYMBOL} {PERIOD}")
    ds_config = config.get('data_server', {})
    if ds_config:
        print(f"data_server: {ds_config.get('ws_url', 'N/A')}")
    print(f"策略参数:")
    for k, v in strategy_params.items():
        print(f"  {k}: {v}")
    print("=" * 80)
    print()
    print("data_server 特有字段说明:")
    print("  订单流: 多开/空开/多平/空平/双开/双平/双换/B/S")
    print("  深度:   open_bidp/open_askp/close_bidp/close_askp")
    print("  持仓:   openint(变化量)/cumulative_openint(绝对值)")
    print()
    print("多因子评分体系 (满分±100):")
    print("  [25分] 订单流动量 = (多开-空开)/(多开+空开) × 125")
    print("  [25分] 主动买卖   = (B-S)/(B+S) × 125")
    print("  [25分] 资金流向   = (开仓-平仓)/(开仓+平仓) × 125 × 价格方向")
    print("  [25分] 盘口压力   = 买一抬升 vs 卖一抬升")
    print("=" * 80 + "\n")

    # ========== 运行策略 ==========
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=order_flow_strategy,
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
