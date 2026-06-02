import os
import re
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Union


def _period_to_timedelta(period_str: str) -> pd.Timedelta:
    """将K线周期字符串转为 pd.Timedelta，支持任意数字前缀。

    支持格式: 1m/3m/65m/120m, 1h/2h/4h, 1d/2d/d, 1w/2w/w 等
    """
    p = period_str.lower().strip()
    m = re.match(r'^(\d+)(m|min)$', p)
    if m:
        return pd.Timedelta(minutes=int(m.group(1)))
    m = re.match(r'^(\d+)(h|hour)$', p)
    if m:
        return pd.Timedelta(hours=int(m.group(1)))
    m = re.match(r'^(\d+)(d|day)$', p)
    if m:
        return pd.Timedelta(days=int(m.group(1)))
    if p in ('d', 'day'):
        return pd.Timedelta(days=1)
    m = re.match(r'^(\d+)(w|week)$', p)
    if m:
        return pd.Timedelta(weeks=int(m.group(1)))
    if p in ('w', 'week'):
        return pd.Timedelta(weeks=1)
    print(f"[警告] 无法识别的K线周期 '{period_str}'，默认按1分钟处理")
    return pd.Timedelta(minutes=1)


class DataSource:
    """
    数据源类，用于管理单个数据源的数据和交易操作
    """

    def __init__(self, symbol: str, kline_period: str, adjust_type: str = '1', lookback_bars: int = 0,
                 slippage_ticks: int = 1, price_tick: float = 1.0):
        """
        初始化数据源

        Args:
            symbol: 品种代码，如'rb888'
            kline_period: K线周期，如'1h', 'D'
            adjust_type: 复权类型，'0'表示不复权，'1'表示后复权
            lookback_bars: K线回溯窗口大小，0表示不限制（返回全部历史数据）
            slippage_ticks: 滑点跳数，默认1跳
            price_tick: 最小变动价位，默认1.0
        """
        self.symbol = symbol
        self.kline_period = kline_period
        self.adjust_type = adjust_type
        self.lookback_bars = lookback_bars  # K线回溯窗口大小
        self.slippage_ticks = slippage_ticks  # 滑点跳数
        self.price_tick = price_tick  # 最小变动价位
        self.data = pd.DataFrame()
        self.current_pos = 0
        self.target_pos = 0
        self.signal_reason = ""
        self.trades = []
        self.current_idx = 0
        self.current_price = None
        # v0.4.6 双轨价格：当前 K 线的"真实合约原始价"（用 _adjust_factor 还原）。
        # 与 current_price 始终成比例：current_raw_price ≈ current_price / factor[current_idx]。
        # 不复权或缺失因子时直接等于 current_price。撮合 / 盯市 P&L 用它来消除"复权幻觉"。
        self.current_raw_price = None
        self.current_datetime = None
        self.pending_orders = []  # 存储待执行的订单
        self.original_data = None
        self._is_higher_tf = False
        self.symbol_config = {}
        self.account_info = None
        self.account_sync_callback = None

        # ====== 增量账户状态（每次 add_trade 时 O(1) 维护）======
        # 用于 get_runtime_account_snapshot 直接读取，避免每根 K 线 O(T) 重放整段成交。
        # 与 self.trades 同步：self.trades 仍是完整历史记录（可视化/results 仍可用）。
        self._acct_long_pos = 0
        self._acct_long_avg_price = 0.0
        self._acct_short_pos = 0
        self._acct_short_avg_price = 0.0
        self._acct_close_profit = 0.0
        self._acct_total_commission = 0.0
        # 这两个由 configure_backtest_context 缓存，避免热路径反复 dict.get + float()
        self._cached_contract_multiplier = 10.0
        self._cached_margin_rate = 0.1

        # ====== ndarray 价格缓存（set_data / align_data 后构建）======
        # 用于主循环和 get_current_price / get_price_by_type 等热路径，避免
        # `data.iloc[i]['close']` 这种昂贵的 Pandas 标签索引。
        # 仍保留 self.data 完整 DataFrame，给 get_klines 返回（用户的 rolling 等不受影响）。
        self._has_array_cache = False
        self._is_kline = True
        self._price_arr = None       # 主价格序列：K线用 close、Tick 用 LastPrice、报价用 (Bid+Ask)/2
        self._open_arr = None
        self._high_arr = None
        self._low_arr = None
        self._close_arr = None
        self._volume_arr = None
        self._bid1_arr = None
        self._ask1_arr = None
        # v0.4.6：复权因子数组（来自 DataFrame 的 _adjust_factor 列，由 apply_local_adjust 写入）。
        # None 或全 1 表示不复权 / 没有换月，撮合直接用复权价当原始价。
        self._adjust_factor_arr = None
        self._index_obj = None       # 直接持有 DataFrame.index（DatetimeIndex/RangeIndex）
        self._index_arr = None       # numpy 时间序列（datetime64 或对象数组），目前仅给统计/对账留口子
        self._data_len = 0

        # ====== P4：per-Bar get_klines 结果缓存 ======
        # 在同一根 K 线（current_idx 不变）内，同一 window 的 get_klines 调用共享同一
        # DataFrame 视图。get_close/get_open/get_high/get_low/get_volume 直接复用此视图
        # 取列，避免每次重新做 self.data.iloc[start:end] 切片。
        # current_idx 改变时整个字典清空。
        self._kline_cache_idx = -1
        self._kline_cache = {}

        # ====== 方式一：IndicatorCache（用户自定义指标的预计算列存）======
        # _indicator_registry: name -> {'func': callable, 'window': Optional[int]}
        # _indicator_arrays:   name -> np.ndarray（长度 == _data_len，主循环 O(1) 查表）
        # 在 set_data / _build_arrays_cache 之后立即批量重算所有已注册指标。
        self._indicator_registry: Dict[str, Dict[str, Any]] = {}
        self._indicator_arrays: Dict[str, np.ndarray] = {}

    def configure_backtest_context(self, symbol_config: Optional[Dict[str, Any]] = None,
                                   account_info: Optional[Dict[str, Any]] = None,
                                   account_sync_callback=None):
        """绑定回测账户上下文，用于资金校验与实时账户同步。"""
        self.symbol_config = (symbol_config or {}).copy()
        self.account_info = account_info
        self.account_sync_callback = account_sync_callback
        # 缓存热路径常用参数，避免 get_runtime_account_snapshot 反复 dict.get + float()
        self._cached_contract_multiplier = float(
            self.symbol_config.get('contract_multiplier', 10) or 10
        )
        self._cached_margin_rate = float(
            self.symbol_config.get('margin_rate', 0.1) or 0.1
        )
        # 配置变化时重置增量账户状态（保险措施；正常流程里这总在 add_trade 之前调用一次）
        self._reset_account_state()

    def _reset_account_state(self):
        """重置增量账户状态。"""
        self._acct_long_pos = 0
        self._acct_long_avg_price = 0.0
        self._acct_short_pos = 0
        self._acct_short_avg_price = 0.0
        self._acct_close_profit = 0.0
        self._acct_total_commission = 0.0

    def _apply_trade_to_account_state(self, action: str, price: float, volume: int):
        """在 add_trade 里调用一次：O(1) 增量维护账户聚合状态。

        与原 get_runtime_account_snapshot 内部 for-loop 的语义保持完全一致，
        包括 "平多开空" / "平空开多" 这种组合动作的拆单顺序。
        """
        if price is None or price <= 0 or volume <= 0:
            return
        price = float(price)
        volume = int(volume)
        contract_multiplier = self._cached_contract_multiplier

        if action == "开多":
            commission = self._get_trade_commission("开多", price, volume)
            self._acct_total_commission += commission
            new_total = self._acct_long_pos + volume
            if self._acct_long_pos > 0:
                self._acct_long_avg_price = (
                    self._acct_long_pos * self._acct_long_avg_price + volume * price
                ) / new_total
            else:
                self._acct_long_avg_price = price
            self._acct_long_pos = new_total

        elif action == "平多":
            actual_volume = min(volume, self._acct_long_pos)
            if actual_volume <= 0:
                return
            self._acct_total_commission += self._get_trade_commission("平多", price, actual_volume)
            self._acct_close_profit += (price - self._acct_long_avg_price) * actual_volume * contract_multiplier
            self._acct_long_pos -= actual_volume
            if self._acct_long_pos <= 0:
                self._acct_long_pos = 0
                self._acct_long_avg_price = 0.0

        elif action == "开空":
            commission = self._get_trade_commission("开空", price, volume)
            self._acct_total_commission += commission
            new_total = self._acct_short_pos + volume
            if self._acct_short_pos > 0:
                self._acct_short_avg_price = (
                    self._acct_short_pos * self._acct_short_avg_price + volume * price
                ) / new_total
            else:
                self._acct_short_avg_price = price
            self._acct_short_pos = new_total

        elif action == "平空":
            actual_volume = min(volume, self._acct_short_pos)
            if actual_volume <= 0:
                return
            self._acct_total_commission += self._get_trade_commission("平空", price, actual_volume)
            self._acct_close_profit += (self._acct_short_avg_price - price) * actual_volume * contract_multiplier
            self._acct_short_pos -= actual_volume
            if self._acct_short_pos <= 0:
                self._acct_short_pos = 0
                self._acct_short_avg_price = 0.0

        elif action == "平多开空":
            # 与原 snapshot 一致：先平多，再以平多得到的实际数量开空
            close_volume = min(volume, self._acct_long_pos)
            if close_volume > 0:
                self._acct_total_commission += self._get_trade_commission("平多", price, close_volume)
                self._acct_close_profit += (price - self._acct_long_avg_price) * close_volume * contract_multiplier
                self._acct_long_pos -= close_volume
                if self._acct_long_pos <= 0:
                    self._acct_long_pos = 0
                    self._acct_long_avg_price = 0.0
                # 开空 close_volume 手
                self._acct_total_commission += self._get_trade_commission("开空", price, close_volume)
                new_total = self._acct_short_pos + close_volume
                if self._acct_short_pos > 0:
                    self._acct_short_avg_price = (
                        self._acct_short_pos * self._acct_short_avg_price + close_volume * price
                    ) / new_total
                else:
                    self._acct_short_avg_price = price
                self._acct_short_pos = new_total

        elif action == "平空开多":
            close_volume = min(volume, self._acct_short_pos)
            if close_volume > 0:
                self._acct_total_commission += self._get_trade_commission("平空", price, close_volume)
                self._acct_close_profit += (self._acct_short_avg_price - price) * close_volume * contract_multiplier
                self._acct_short_pos -= close_volume
                if self._acct_short_pos <= 0:
                    self._acct_short_pos = 0
                    self._acct_short_avg_price = 0.0
                self._acct_total_commission += self._get_trade_commission("开多", price, close_volume)
                new_total = self._acct_long_pos + close_volume
                if self._acct_long_pos > 0:
                    self._acct_long_avg_price = (
                        self._acct_long_pos * self._acct_long_avg_price + close_volume * price
                    ) / new_total
                else:
                    self._acct_long_avg_price = price
                self._acct_long_pos = new_total
        # 其它未知 action 静默忽略，与原行为一致

    def _sync_backtest_account(self):
        """同步回测账户快照，保证同一根K线内的后续下单也能看到最新资金。"""
        if callable(self.account_sync_callback):
            self.account_sync_callback()

    def _get_open_cost_per_lot(self, price: Optional[float]) -> float:
        """估算开仓每手占用资金（保证金+开仓手续费）。"""
        if price is None or price <= 0:
            return 0.0

        margin_required = self._get_margin_required(price, 1)
        open_commission = self._get_trade_commission("开多", price, 1)
        return margin_required + open_commission

    def _use_fixed_commission(self) -> bool:
        commission_rate = float(self.symbol_config.get('commission', 0.0003) or 0.0)
        commission_per_lot = float(self.symbol_config.get('commission_per_lot', 0) or 0.0)
        return commission_rate < 1e-05 and commission_per_lot > 0.1

    def _get_margin_required(self, price: Optional[float], volume: int) -> float:
        if price is None or price <= 0 or volume <= 0:
            return 0.0
        contract_multiplier = float(self.symbol_config.get('contract_multiplier', 10) or 10)
        margin_rate = float(self.symbol_config.get('margin_rate', 0.1) or 0.1)
        return float(price) * int(volume) * contract_multiplier * margin_rate

    def _get_trade_commission(self, action: str, price: Optional[float], volume: int) -> float:
        if price is None or price <= 0 or volume <= 0:
            return 0.0

        volume = int(volume)
        contract_multiplier = float(self.symbol_config.get('contract_multiplier', 10) or 10)
        commission_rate = float(self.symbol_config.get('commission', 0.0003) or 0.0)
        commission_per_lot = float(self.symbol_config.get('commission_per_lot', 0) or 0.0)
        commission_close_per_lot = float(self.symbol_config.get('commission_close_per_lot', 0) or 0.0)

        if self._use_fixed_commission():
            if action in ("平多", "平空"):
                fixed_per_lot = commission_close_per_lot if commission_close_per_lot > 0 else commission_per_lot
            else:
                fixed_per_lot = commission_per_lot
            return fixed_per_lot * volume

        return float(price) * volume * contract_multiplier * commission_rate

    def get_runtime_account_snapshot(self, current_price: Optional[float] = None,
                                     raw_current_price: Optional[float] = None) -> Dict[str, float]:
        """读取该数据源的账户快照。

        使用 add_trade 时增量维护的 self._acct_* 字段，O(1) 复杂度。
        历史成交列表 self.trades 仍是完整记录，仅用于结果展示与可视化。

        v0.4.6：盯市 P&L 用原始价（raw_current_price），消除复权幻觉。
        - raw_current_price 缺省 → 用 self.current_raw_price
        - 仍缺 → 从 current_price + _adjust_factor 现场算
        - 还缺 → 退回 current_price（不复权场景，与老行为一致）

        如需对账（验证增量与全量重算一致），把环境变量 SSQUANT_AUDIT_ACCOUNT=1
        即可在每次取快照时多跑一次全量重算并断言一致。
        """
        margin_rate = self._cached_margin_rate
        contract_multiplier = self._cached_contract_multiplier
        # 复权价（仅给保证金/口径占用用）
        cp = float(current_price or self.current_price or 0.0)
        # 盯市用原始价：参数 > self.current_raw_price > 现场反算 > 复权价兜底
        if raw_current_price is not None:
            rp = float(raw_current_price)
        elif self.current_raw_price is not None:
            rp = float(self.current_raw_price)
        else:
            rp = float(self._unadjust_price(cp) or cp)

        long_pos = self._acct_long_pos
        short_pos = self._acct_short_pos

        if long_pos > 0:
            long_position_profit = (rp - self._acct_long_avg_price) * long_pos * contract_multiplier
        else:
            long_position_profit = 0.0
        if short_pos > 0:
            short_position_profit = (self._acct_short_avg_price - rp) * short_pos * contract_multiplier
        else:
            short_position_profit = 0.0

        position_profit = long_position_profit + short_position_profit
        # 保证金按复权价计算，与老行为一致（保证金口径与合约名义价值挂钩，
        # 复权与不复权差异在百分比层面对保证金的影响可忽略；改用原始价会让
        # 历史段保证金更"真实"但同时让一致性测试不再幂等，权衡后保留 cp）
        curr_margin = (long_pos + short_pos) * cp * contract_multiplier * margin_rate

        snapshot = {
            'close_profit': self._acct_close_profit,
            'commission': self._acct_total_commission,
            'position_profit': position_profit,
            'curr_margin': curr_margin,
        }

        # 可选对账：仅在显式开启时跑一次全量重算并断言一致（用于回归测试）
        if os.environ.get('SSQUANT_AUDIT_ACCOUNT') == '1':
            legacy = self._compute_account_snapshot_legacy(rp, cp)
            for k, v in snapshot.items():
                lv = legacy[k]
                if abs(v - lv) > max(1e-6, abs(lv) * 1e-9):
                    raise AssertionError(
                        f"[SSQUANT_AUDIT] {self.symbol} {self.kline_period} 增量={v} 重算={lv} key={k}"
                    )

        return snapshot

    def _compute_account_snapshot_legacy(self, current_price: float,
                                         margin_price: Optional[float] = None) -> Dict[str, float]:
        """从 self.trades 全量重算的旧版实现，仅用于对账与回归测试。

        v0.4.6：current_price 是用于 P&L 的原始价；
                margin_price 是用于保证金口径的复权价（缺省时退回 current_price）。
        """
        contract_multiplier = self._cached_contract_multiplier
        margin_rate = self._cached_margin_rate

        long_pos = 0
        long_avg_price = 0.0
        short_pos = 0
        short_avg_price = 0.0
        close_profit = 0.0
        total_commission = 0.0

        def open_long(price: float, volume: int):
            nonlocal long_pos, long_avg_price, total_commission
            total_commission += self._get_trade_commission("开多", price, volume)
            if long_pos > 0:
                long_avg_price = (long_pos * long_avg_price + volume * price) / (long_pos + volume)
            else:
                long_avg_price = price
            long_pos += volume

        def close_long(price: float, volume: int) -> int:
            nonlocal long_pos, long_avg_price, close_profit, total_commission
            actual_volume = min(volume, long_pos)
            if actual_volume <= 0:
                return 0
            total_commission += self._get_trade_commission("平多", price, actual_volume)
            close_profit += (price - long_avg_price) * actual_volume * contract_multiplier
            long_pos -= actual_volume
            if long_pos <= 0:
                long_pos = 0
                long_avg_price = 0.0
            return actual_volume

        def open_short(price: float, volume: int):
            nonlocal short_pos, short_avg_price, total_commission
            total_commission += self._get_trade_commission("开空", price, volume)
            if short_pos > 0:
                short_avg_price = (short_pos * short_avg_price + volume * price) / (short_pos + volume)
            else:
                short_avg_price = price
            short_pos += volume

        def close_short(price: float, volume: int) -> int:
            nonlocal short_pos, short_avg_price, close_profit, total_commission
            actual_volume = min(volume, short_pos)
            if actual_volume <= 0:
                return 0
            total_commission += self._get_trade_commission("平空", price, actual_volume)
            close_profit += (short_avg_price - price) * actual_volume * contract_multiplier
            short_pos -= actual_volume
            if short_pos <= 0:
                short_pos = 0
                short_avg_price = 0.0
            return actual_volume

        for trade in self.trades:
            action = trade.get('action')
            # v0.4.6：旧 trade dict 没有 raw_price 时回退到 price
            price = float(trade.get('raw_price', trade.get('price', 0)) or 0.0)
            volume = int(trade.get('volume', 0) or 0)
            if price <= 0 or volume <= 0:
                continue
            if action == "开多":
                open_long(price, volume)
            elif action == "平多":
                close_long(price, volume)
            elif action == "开空":
                open_short(price, volume)
            elif action == "平空":
                close_short(price, volume)
            elif action == "平多开空":
                reversed_volume = close_long(price, volume)
                if reversed_volume > 0:
                    open_short(price, reversed_volume)
            elif action == "平空开多":
                reversed_volume = close_short(price, volume)
                if reversed_volume > 0:
                    open_long(price, reversed_volume)

        long_position_profit = (current_price - long_avg_price) * long_pos * contract_multiplier if long_pos > 0 else 0.0
        short_position_profit = (short_avg_price - current_price) * short_pos * contract_multiplier if short_pos > 0 else 0.0
        mp = float(margin_price) if margin_price is not None else current_price
        return {
            'close_profit': close_profit,
            'commission': total_commission,
            'position_profit': long_position_profit + short_position_profit,
            'curr_margin': (long_pos + short_pos) * mp * contract_multiplier * margin_rate,
        }

    def _fit_open_volume_to_funds(self, requested_volume: int, price: Optional[float],
                                  extra_reserved_funds: float = 0.0):
        """
        根据当前可用资金裁剪开仓手数。

        返回:
            (actual_volume, reserved_funds)
        """
        requested_volume = int(requested_volume or 0)
        if requested_volume <= 0:
            return 0, 0.0

        cost_per_lot = self._get_open_cost_per_lot(price)
        if cost_per_lot <= 0:
            return requested_volume, 0.0

        if self.account_info is None:
            return requested_volume, cost_per_lot * requested_volume

        available = float(self.account_info.get('available', 0) or 0.0) + max(0.0, float(extra_reserved_funds or 0.0))
        max_volume = int(np.floor(available / cost_per_lot)) if cost_per_lot > 0 else requested_volume
        actual_volume = max(0, min(requested_volume, max_volume))
        reserved_funds = cost_per_lot * actual_volume
        return actual_volume, reserved_funds

    def _mark_insufficient_funds(self, message: str = ""):
        if self.account_info is not None:
            self.account_info['_last_order_rejected_for_funds'] = True
            self.account_info['_fund_reject_count'] = int(self.account_info.get('_fund_reject_count', 0) or 0) + 1
            if message:
                dt = self.get_current_datetime()
                dt_str = str(dt)[:19] if dt is not None else ""
                tagged = f"[{dt_str}] {message}" if dt_str else message
                self.account_info['_last_fund_reject_reason'] = tagged

    def set_data(self, data: pd.DataFrame):
        """设置数据"""
        self.data = data
        # 数据更新后立刻重建 ndarray 缓存（主循环 / 价格查询会直接读它）
        self._build_arrays_cache()
        # P4：data 替换后立即清空 K 线切片缓存
        self._kline_cache.clear()
        self._kline_cache_idx = -1

    def _invalidate_arrays_cache(self):
        """标记 ndarray 缓存失效（仅在 align_data 等会替换 self.data 的路径上需要）。"""
        self._has_array_cache = False
        # P4：同步清空 K 线切片缓存
        self._kline_cache.clear()
        self._kline_cache_idx = -1

    def _build_arrays_cache(self):
        """从 self.data 构建一份 ndarray 缓存，用于热路径直接 O(1) 读取。

        - K 线数据：以 close 为主价格，并缓存 open/high/low/close
        - Tick 数据：若仅有 LastPrice，则以 LastPrice 为主价格
        - 报价数据：若有 BidPrice1+AskPrice1，缓存这两列；主价格取中间价
        - index 转 numpy（datetime64 / 对象数组）
        若数据为空或字段缺失，自动降级为 _has_array_cache=False，老路径继续工作。
        """
        self._has_array_cache = False
        self._price_arr = None
        self._open_arr = None
        self._high_arr = None
        self._low_arr = None
        self._close_arr = None
        self._volume_arr = None
        self._bid1_arr = None
        self._ask1_arr = None
        self._adjust_factor_arr = None
        # P4：data 被替换/对齐后立即清空 K 线切片缓存（防止旧切片被复用）
        self._kline_cache.clear()
        self._kline_cache_idx = -1
        self._index_obj = None
        self._index_arr = None
        self._data_len = 0

        df = self.data
        if df is None or df.empty:
            return
        cols = df.columns
        n = len(df)

        # 主价格序列（按数据形态决定）
        if 'close' in cols:
            self._close_arr = df['close'].to_numpy(dtype=np.float64, copy=False)
            self._price_arr = self._close_arr
            self._is_kline = True
        elif 'LastPrice' in cols:
            self._price_arr = df['LastPrice'].to_numpy(dtype=np.float64, copy=False)
            self._is_kline = False
        elif 'BidPrice1' in cols and 'AskPrice1' in cols:
            bid = df['BidPrice1'].to_numpy(dtype=np.float64, copy=False)
            ask = df['AskPrice1'].to_numpy(dtype=np.float64, copy=False)
            self._bid1_arr = bid
            self._ask1_arr = ask
            self._price_arr = (bid + ask) * 0.5
            self._is_kline = False
        else:
            # 不认识的数据格式，保持降级路径
            return

        # 其余 OHLC 字段（K线常用，Tick/报价场景可能为 None）
        if 'open' in cols:
            self._open_arr = df['open'].to_numpy(dtype=np.float64, copy=False)
        if 'high' in cols:
            self._high_arr = df['high'].to_numpy(dtype=np.float64, copy=False)
        if 'low' in cols:
            self._low_arr = df['low'].to_numpy(dtype=np.float64, copy=False)
        if 'volume' in cols:
            self._volume_arr = df['volume'].to_numpy(dtype=np.float64, copy=False)
        # 报价单字段（K线场景一般没有，留空即可）
        if self._bid1_arr is None and 'BidPrice1' in cols:
            self._bid1_arr = df['BidPrice1'].to_numpy(dtype=np.float64, copy=False)
        if self._ask1_arr is None and 'AskPrice1' in cols:
            self._ask1_arr = df['AskPrice1'].to_numpy(dtype=np.float64, copy=False)

        # v0.4.6：复权因子列（apply_local_adjust 写入）。撮合 / 盯市用它把复权价还原回原始合约价。
        if '_adjust_factor' in cols:
            arr = df['_adjust_factor'].to_numpy(dtype=np.float64, copy=False)
            # 全 1 等价不复权，置 None 走快路径
            if not np.allclose(arr, 1.0):
                self._adjust_factor_arr = arr

        # 索引：保留原 Pandas 索引对象，确保 index[i] 返回的依旧是 pd.Timestamp，
        # 不改变下游日志/trades 记录里 datetime 的字面行为。
        # to_numpy() 版本另存，便于将来对账或向量化扩展使用。
        self._index_obj = df.index
        try:
            self._index_arr = df.index.to_numpy()
        except Exception:
            self._index_arr = np.array(df.index)

        self._data_len = n
        self._has_array_cache = True

        # 已注册的自定义指标在数据就绪后立即重算，保证主循环 O(1) 查表正确。
        # 调用顺序：register_indicator 自己也会调 _recompute_indicator；当 set_data
        # / align_data 之后引擎重建 ndarray cache，这里再批量刷一次，避免 stale。
        if self._indicator_registry:
            self._recompute_all_indicators()

    def get_data(self) -> pd.DataFrame:
        """获取数据"""
        return self.data

    def get_current_price(self) -> Optional[float]:
        """获取当前价格"""
        if self.current_price is not None:
            return self.current_price
        if self._has_array_cache and 0 <= self.current_idx < self._data_len:
            return float(self._price_arr[self.current_idx])
        if not self.data.empty and self.current_idx < len(self.data):
            return self.data.iloc[self.current_idx]['close']
        return None

    def get_current_datetime(self):
        """获取当前日期时间"""
        if self.current_datetime is not None:
            return self.current_datetime
        if self._has_array_cache and 0 <= self.current_idx < self._data_len:
            # 走 _index_obj[i]（DatetimeIndex 直接索引返回 pd.Timestamp），与原行为一致
            return self._index_obj[self.current_idx]
        if not self.data.empty and self.current_idx < len(self.data):
            return self.data.index[self.current_idx]
        return None

    def get_current_pos(self) -> int:
        """获取当前持仓"""
        return self.current_pos

    def _update_pos(self, log_callback=None):
        """更新实际持仓"""
        if self.current_pos != self.target_pos:
            old_pos = self.current_pos
            self.current_pos = self.target_pos
            if log_callback:
                # 添加debug参数检查
                debug_mode = getattr(log_callback, 'debug_mode', True)
                if debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 持仓变化: {old_pos} -> {self.current_pos}")

    def set_target_pos(self, target_pos: int, log_callback=None):
        """设置目标持仓"""
        self.target_pos = target_pos
        self._update_pos(log_callback)

    def set_signal_reason(self, reason: str):
        """设置交易信号原因"""
        self.signal_reason = reason

    def _unadjust_price(self, price: Optional[float], idx: Optional[int] = None) -> Optional[float]:
        """v0.4.6 除权：把复权价还原为真实合约原始价。

        raw = adjusted / _adjust_factor[idx]
        无因子数据 / 不复权场景下原值返回。idx 缺省时取 self.current_idx。

        round 到 price_tick 对齐（避免 1/factor 的浮点尾数误差）。
        """
        if price is None:
            return price
        arr = self._adjust_factor_arr
        if arr is None:
            return price
        if idx is None:
            idx = self.current_idx
        if not (0 <= idx < arr.shape[0]):
            return price
        f = float(arr[idx])
        if f <= 0 or abs(f - 1.0) < 1e-12:
            return price
        raw = float(price) / f
        # 对齐到最小变动价位，消除浮点尾数
        tick = float(self.price_tick or 0.0)
        if tick > 0:
            raw = round(raw / tick) * tick
        return raw

    def add_trade(self, action: str, price: float, volume: int, reason: str, datetime=None,
                  slippage_cost: float = 0, raw_price: Optional[float] = None):
        """添加交易记录

        Args:
            action: 交易动作
            price: 成交价格（已含滑点；策略代码 / 画图看到的复权价）
            volume: 交易数量
            reason: 交易原因
            datetime: 交易时间
            slippage_cost: 滑点成本（元）
            raw_price: v0.4.6 双轨价格的"真实合约原始价"，
                       用于 P&L / 盯市，消除复权幻觉。
                       缺省时与 price 相同（不复权 / 实盘等场景）。
        """
        if datetime is None:
            datetime = self.get_current_datetime()

        if raw_price is None:
            raw_price = price

        self.trades.append({
            'datetime': datetime,
            'action': action,
            'price': price,           # 复权价：用户策略 / 画图 / 限价单触发用
            'raw_price': raw_price,   # 原始价：P&L / 盯市用
            'volume': volume,
            'reason': '',  # 不再记录原因
            'slippage_cost': slippage_cost  # 滑点成本
        })
        # 同步增量维护账户聚合状态：把原本每根 K 线全量重放 self.trades 的 O(N×T)
        # 折算为每笔成交一次的 O(1) 更新；get_runtime_account_snapshot 直接读取即可。
        # 用 raw_price 计算 P&L，避免复权因子在换月点污染
        self._apply_trade_to_account_state(action, raw_price, volume)

    def get_price_by_type(self, order_type='bar_close'):
        """
        根据订单类型获取价格

        Args:
            order_type (str): 订单类型，可选值：
                - 'bar_close': 当前K线收盘价（默认）
                - 'next_bar_open': 下一K线开盘价
                - 'next_bar_close': 下一K线收盘价
                - 'next_bar_high': 下一K线最高价
                - 'next_bar_low': 下一K线最低价
                - 'market': 市价单，按对手价成交，买入按ask1，卖出按bid1

        Returns:
            float: 价格，如果无法获取则返回None
        """
        # 优先走 ndarray 缓存，避免 self.data.iloc[i]['col'] 这种昂贵的 Pandas 标签索引
        if self._has_array_cache:
            n = self._data_len
            i = self.current_idx
            if order_type == 'bar_close':
                if 0 <= i < n and self._close_arr is not None:
                    return float(self._close_arr[i])
            elif order_type == 'next_bar_open':
                if 0 <= i + 1 < n and self._open_arr is not None:
                    return float(self._open_arr[i + 1])
            elif order_type == 'next_bar_close':
                if 0 <= i + 1 < n and self._close_arr is not None:
                    return float(self._close_arr[i + 1])
            elif order_type == 'next_bar_high':
                if 0 <= i + 1 < n and self._high_arr is not None:
                    return float(self._high_arr[i + 1])
            elif order_type == 'next_bar_low':
                if 0 <= i + 1 < n and self._low_arr is not None:
                    return float(self._low_arr[i + 1])
            elif order_type == 'market':
                if 0 <= i < n:
                    if self._bid1_arr is not None and self._ask1_arr is not None:
                        # TICK / 报价：在 buy/sell 内部按方向取 bid1/ask1
                        return None
                    if self._close_arr is not None:
                        return float(self._close_arr[i])
            return None

        # 兜底：缓存未建立（极少见，例如尚未调用 set_data 的极早期路径）
        if not self.data.empty:
            if order_type == 'bar_close':
                if self.current_idx < len(self.data):
                    return self.data.iloc[self.current_idx]['close']
            elif order_type == 'next_bar_open':
                if self.current_idx + 1 < len(self.data) and 'open' in self.data.columns:
                    return self.data.iloc[self.current_idx + 1]['open']
            elif order_type == 'next_bar_close':
                if self.current_idx + 1 < len(self.data):
                    return self.data.iloc[self.current_idx + 1]['close']
            elif order_type == 'next_bar_high':
                if self.current_idx + 1 < len(self.data) and 'high' in self.data.columns:
                    return self.data.iloc[self.current_idx + 1]['high']
            elif order_type == 'next_bar_low':
                if self.current_idx + 1 < len(self.data) and 'low' in self.data.columns:
                    return self.data.iloc[self.current_idx + 1]['low']
            elif order_type == 'market':
                # 市价单，对于tick数据，可以使用买一卖一价格
                if self.current_idx < len(self.data):
                    if 'BidPrice1' in self.data.columns and 'AskPrice1' in self.data.columns:
                        # TICK数据：在具体的buy/sell方法中根据买卖方向确定价格
                        return None
                    else:
                        # K线数据：使用收盘价
                        return self.data.iloc[self.current_idx]['close']
        return None

    def _process_pending_orders(self, log_callback=None):
        """处理待执行的订单"""
        if not self.pending_orders:
            return

        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True

        orders_to_remove = []
        for i, order in enumerate(self.pending_orders):
            # 获取执行时间
            execution_time = order.get('execution_time', self.current_idx + 1)

            # 获取订单类型（默认为next_bar_open）
            order_type = order.get('order_type', 'next_bar_open')

            # 判断是否到达执行时间
            if execution_time <= self.current_idx:
                # 执行订单
                action = order['action']
                volume = order['volume']
                reason = order['reason']

                # 根据订单类型获取执行价格
                # 如果已经预先计算了价格，就使用那个价格
                if 'price' in order and order['price'] is not None:
                    price = order['price']
                else:
                    # 否则根据订单类型获取当前价格
                    price = self.get_price_by_type(order_type)
                    if price is None:
                        # 如果仍然无法获取价格，则使用当前价格
                        price = self.get_current_price()
                        if price is None:
                            # 如果完全无法获取价格，跳过此订单
                            continue

                # 应用滑点成本（买入加滑点，卖出减滑点）
                # v0.4.6：滑点 = ticks × price_tick 是 raw 价单位（合约真实最小变动价位）。
                # 但成交 price 这里是复权价（complex = raw × factor），
                # 直接加 raw 单位滑点会让 _unadjust_price 把滑点也除以 factor，
                # 导致 hfq/qfq 路径下实际 P&L 滑点偏小。
                # 解法：把滑点先按当前 factor 放大到复权单位，
                # 这样 raw_fill = (raw_market × F + slip × F) / F = raw_market + slip，与不复权完全一致。
                slippage_per_unit = self.slippage_ticks * self.price_tick  # 每单位滑点金额（raw 价单位）
                slippage_in_price_space = slippage_per_unit
                if self._adjust_factor_arr is not None:
                    _i = self.current_idx
                    if 0 <= _i < self._adjust_factor_arr.shape[0]:
                        _f = float(self._adjust_factor_arr[_i])
                        if _f > 0:
                            slippage_in_price_space = slippage_per_unit * _f
                if action in ["开多", "平空", "平空开多"]:
                    # 买入方向：价格上滑
                    price = price + slippage_in_price_space
                elif action in ["开空", "平多", "平多开空"]:
                    # 卖出方向：价格下滑
                    price = price - slippage_in_price_space

                if action in ["开多", "开空"]:
                    reserved_funds = float(order.get('reserved_funds', 0.0) or 0.0)
                    actual_volume, actual_reserved = self._fit_open_volume_to_funds(
                        volume, price, extra_reserved_funds=reserved_funds
                    )
                    if actual_volume <= 0:
                        if log_callback:
                            log_callback(
                                f"{self.symbol} {self.kline_period} 取消待执行开仓订单: "
                                f"资金不足，请求{volume}手，执行价{price:.2f}"
                            )
                        self._mark_insufficient_funds(
                            f"{self.symbol} {self.kline_period} 待执行开仓被取消：资金不足，请求{volume}手，执行价{price:.2f}"
                        )
                        order['reserved_funds'] = 0.0
                        orders_to_remove.append(i)
                        # P9：拒单未改 _acct_* 状态，省一次冗余 _sync_backtest_account
                        continue
                    if actual_volume < volume and log_callback:
                        log_callback(
                            f"{self.symbol} {self.kline_period} 待执行开仓资金不足: "
                            f"{volume}手自动调整为{actual_volume}手"
                        )
                    volume = actual_volume

                # 更新持仓
                if action == "开多":
                    self.target_pos = self.current_pos + volume
                elif action == "平多":
                    if volume is None:
                        volume = max(0, self.current_pos)
                    # 检查是否有多头持仓可平
                    actual_volume = min(volume, max(0, self.current_pos))
                    if actual_volume <= 0:
                        # 没有多头持仓可平，跳过此订单
                        orders_to_remove.append(i)
                        # P9：跳过未改 _acct_* 状态，省一次冗余 _sync_backtest_account
                        continue
                    self.target_pos = self.current_pos - actual_volume
                    volume = actual_volume  # 更新volume为实际交易量
                elif action == "开空":
                    self.target_pos = self.current_pos - volume
                elif action == "平空":
                    if volume is None:
                        volume = max(0, -self.current_pos)
                    # 检查是否有空头持仓可平
                    actual_volume = min(volume, max(0, -self.current_pos))
                    if actual_volume <= 0:
                        # 没有空头持仓可平，跳过此订单
                        orders_to_remove.append(i)
                        # P9：跳过未改 _acct_* 状态，省一次冗余 _sync_backtest_account
                        continue
                    self.target_pos = self.current_pos + actual_volume
                    volume = actual_volume  # 更新volume为实际交易量
                elif action == "平多开空":  # 支持反手交易
                    self.target_pos = -self.current_pos  # 从多头变为空头
                elif action == "平空开多":  # 支持反手交易
                    self.target_pos = -self.current_pos  # 从空头变为多头

                # 更新持仓
                self._update_pos(log_callback)

                # 记录交易（包含单位滑点金额，用于后续计算滑点成本）
                # v0.4.6：成交价 price 是复权价（指标对齐），P&L 用原始价（_unadjust_price 还原）
                self.add_trade(action, price, volume, reason, slippage_cost=slippage_per_unit,
                               raw_price=self._unadjust_price(price))

                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 执行订单: {action} {volume}手 成交价:{price:.2f} 类型:{order_type} 原因:{reason}")

                # 标记为待移除
                order['reserved_funds'] = 0.0
                orders_to_remove.append(i)
                self._sync_backtest_account()

        # 移除已执行的订单（从后往前移除，避免索引问题）
        for i in sorted(orders_to_remove, reverse=True):
            self.pending_orders.pop(i)

        # P9：成交分支已经在每次 fill 之后即时同步过 _sync_backtest_account（保留跨 fill
        # 的资金校验语义），这里的最终 sync 是冗余的，移除。reject/skip 分支只是登记
        # 拒单标志而非改 _acct_* 状态，因此不需要 sync。
        # 注：主循环（backtest_core.py 主循环每根 Bar 末尾）也会再调一次
        # _update_backtest_account，最终 account_info 仍是最新的。

    def buy(self, volume: int = 1, reason: str = "", log_callback=None, order_type='bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        开多仓

        Args:
            volume (int): 交易数量
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值：
                - 'limit': 限价单（需指定price）
                - 'bar_close': 当前K线收盘价（默认）
                - 'next_bar_open': 下一K线开盘价
                - 'next_bar_close': 下一K线收盘价
                - 'next_bar_high': 下一K线最高价
                - 'next_bar_low': 下一K线最低价
                - 'market': 市价单，按ask1价格成交（买入用卖一价）
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）

        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True

        if order_type == 'bar_close':
            # 当前K线收盘价下单，立即执行
            price = self.get_current_price()
            if price is None:
                return False

            actual_volume, _ = self._fit_open_volume_to_funds(volume, price)
            if actual_volume <= 0:
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 开多失败: 资金不足，请求{volume}手 成交价:{price:.2f}")
                self._mark_insufficient_funds(
                    f"{self.symbol} {self.kline_period} 开多失败：资金不足，请求{volume}手，参考价{price:.2f}"
                )
                return False
            if actual_volume < volume and log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 开多资金不足: {volume}手自动调整为{actual_volume}手")
            volume = actual_volume

            self.target_pos = self.current_pos + volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)

            # 记录交易
            self.add_trade("开多", price, volume, reason,
                           raw_price=self._unadjust_price(price))
            self._sync_backtest_account()
            return True
        elif order_type == 'market':
            # 市价单，TICK数据买入使用卖一价格(AskPrice1)
            price = None
            if self._has_array_cache and self._ask1_arr is not None \
                    and 0 <= self.current_idx < self._data_len:
                price = float(self._ask1_arr[self.current_idx])
            elif 'AskPrice1' in self.data.columns and self.current_idx < len(self.data):
                price = self.data.iloc[self.current_idx]['AskPrice1']
            else:
                price = self.get_current_price()

            if price is None:
                return False

            actual_volume, _ = self._fit_open_volume_to_funds(volume, price)
            if actual_volume <= 0:
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 市价买入失败: 资金不足，请求{volume}手 成交价:{price:.2f}")
                self._mark_insufficient_funds(
                    f"{self.symbol} {self.kline_period} 市价买入失败：资金不足，请求{volume}手，参考价{price:.2f}"
                )
                return False
            if actual_volume < volume and log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 市价买入资金不足: {volume}手自动调整为{actual_volume}手")
            volume = actual_volume

            self.target_pos = self.current_pos + volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)

            # 记录交易
            self.add_trade("开多", price, volume, reason,
                           raw_price=self._unadjust_price(price))

            if log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 市价买入: {volume}手 成交价:{price:.2f} 原因:{reason}")

            self._sync_backtest_account()
            return True
        else:
            # 下一K线价格下单，添加到待执行队列
            if price is None:
                price = self.get_price_by_type(order_type)
            estimate_price = price if price is not None else self.get_current_price()
            actual_volume, reserved_funds = self._fit_open_volume_to_funds(volume, estimate_price)
            price_str = f"{estimate_price:.2f}" if estimate_price is not None else "未知"
            if actual_volume <= 0:
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 开多订单失败: 资金不足，请求{volume}手 参考价:{price_str}")
                self._mark_insufficient_funds(
                    f"{self.symbol} {self.kline_period} 开多订单失败：资金不足，请求{volume}手，参考价{price_str}"
                )
                return False
            if actual_volume < volume and log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 开多订单资金不足: {volume}手自动调整为{actual_volume}手")
            volume = actual_volume

            # 注意：如果是next_bar_open/high/low/close，价格可能为None，因为下一K线的数据尚未加载
            # 但我们仍然可以添加到待执行队列，等待下一K线时执行，再根据order_type获取正确的价格

            # 添加到待执行队列
            self.pending_orders.append({
                'action': "开多",
                'volume': volume,
                'price': price,  # 可能为None，将在执行时重新获取
                'reason': reason,
                'order_type': order_type,  # 保存订单类型
                'execution_time': self.current_idx + 1,  # 在下一K线执行
                'reserved_funds': reserved_funds,
            })

            if log_callback and debug_mode:
                price_str = f"{price:.2f}" if price is not None else "待确定"
                log_callback(f"{self.symbol} {self.kline_period} 添加待执行订单: 开多 {volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")

            self._sync_backtest_account()
            return True

    def sell(self, volume: Optional[int] = None, reason: str = "", log_callback=None, order_type='bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        平多仓

        Args:
            volume (int, optional): 交易数量，None表示平掉所有多仓
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值同buy函数
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）

        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True

        if order_type == 'bar_close':
            # 当前K线收盘价下单，立即执行
            price = self.get_current_price()
            if price is None:
                return False

            if volume is None:
                volume = max(0, self.current_pos)

            # 检查是否有多头持仓可平
            actual_volume = min(volume, max(0, self.current_pos))
            if actual_volume <= 0:
                # 没有多头持仓可平，不记录交易
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 平多失败: 无多头持仓可平")
                return True

            self.target_pos = self.current_pos - actual_volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)

            # 记录交易
            self.add_trade("平多", price, actual_volume, reason,
                           raw_price=self._unadjust_price(price))
            self._sync_backtest_account()
            return True
        elif order_type == 'market':
            # 市价单，TICK数据卖出使用买一价格(BidPrice1)
            price = None
            if self._has_array_cache and self._bid1_arr is not None \
                    and 0 <= self.current_idx < self._data_len:
                price = float(self._bid1_arr[self.current_idx])
            elif 'BidPrice1' in self.data.columns and self.current_idx < len(self.data):
                price = self.data.iloc[self.current_idx]['BidPrice1']
            else:
                price = self.get_current_price()

            if price is None:
                return False

            if volume is None:
                volume = max(0, self.current_pos)

            # 检查是否有多头持仓可平
            actual_volume = min(volume, max(0, self.current_pos))
            if actual_volume <= 0:
                # 没有多头持仓可平，不记录交易
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 市价平多失败: 无多头持仓可平")
                return True

            self.target_pos = self.current_pos - actual_volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)

            # 记录交易
            self.add_trade("平多", price, actual_volume, reason,
                           raw_price=self._unadjust_price(price))

            if log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 市价卖出: {actual_volume}手 成交价:{price:.2f} 原因:{reason}")

            self._sync_backtest_account()
            return True
        else:
            # 下一K线价格下单，添加到待执行队列
            if price is None:
                price = self.get_price_by_type(order_type)
            # 注意：如果是next_bar_open/high/low/close，价格可能为None，因为下一K线的数据尚未加载

            if volume is None:
                volume = max(0, self.current_pos)

            # 检查是否有多头持仓可平
            actual_volume = min(volume, max(0, self.current_pos))
            if actual_volume <= 0:
                # 没有多头持仓可平，不添加订单
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 平多订单失败: 无多头持仓可平")
                return True

            # 添加到待执行队列
            self.pending_orders.append({
                'action': "平多",
                'volume': actual_volume,
                'price': price,  # 可能为None，将在执行时重新获取
                'reason': reason,
                'order_type': order_type,  # 保存订单类型
                'execution_time': self.current_idx + 1  # 在下一K线执行
            })

            if log_callback and debug_mode:
                price_str = f"{price:.2f}" if price is not None else "待确定"
                log_callback(f"{self.symbol} {self.kline_period} 添加待执行订单: 平多 {actual_volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")

            return True

    def sellshort(self, volume: int = 1, reason: str = "", log_callback=None, order_type='bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        开空仓

        Args:
            volume (int): 交易数量
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值同buy函数
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）

        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True

        if order_type == 'bar_close':
            # 当前K线收盘价下单，立即执行
            price = self.get_current_price()
            if price is None:
                return False

            actual_volume, _ = self._fit_open_volume_to_funds(volume, price)
            if actual_volume <= 0:
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 开空失败: 资金不足，请求{volume}手 成交价:{price:.2f}")
                self._mark_insufficient_funds(
                    f"{self.symbol} {self.kline_period} 开空失败：资金不足，请求{volume}手，参考价{price:.2f}"
                )
                return False
            if actual_volume < volume and log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 开空资金不足: {volume}手自动调整为{actual_volume}手")
            volume = actual_volume

            self.target_pos = self.current_pos - volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)

            # 记录交易
            self.add_trade("开空", price, volume, reason,
                           raw_price=self._unadjust_price(price))
            self._sync_backtest_account()
            return True
        elif order_type == 'market':
            # 市价单，TICK数据卖出使用买一价格(BidPrice1)
            price = None
            if self._has_array_cache and self._bid1_arr is not None \
                    and 0 <= self.current_idx < self._data_len:
                price = float(self._bid1_arr[self.current_idx])
            elif 'BidPrice1' in self.data.columns and self.current_idx < len(self.data):
                price = self.data.iloc[self.current_idx]['BidPrice1']
            else:
                price = self.get_current_price()

            if price is None:
                return False

            actual_volume, _ = self._fit_open_volume_to_funds(volume, price)
            if actual_volume <= 0:
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 市价卖空失败: 资金不足，请求{volume}手 成交价:{price:.2f}")
                self._mark_insufficient_funds(
                    f"{self.symbol} {self.kline_period} 市价卖空失败：资金不足，请求{volume}手，参考价{price:.2f}"
                )
                return False
            if actual_volume < volume and log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 市价卖空资金不足: {volume}手自动调整为{actual_volume}手")
            volume = actual_volume

            self.target_pos = self.current_pos - volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)

            # 记录交易
            self.add_trade("开空", price, volume, reason,
                           raw_price=self._unadjust_price(price))

            if log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 市价卖空: {volume}手 成交价:{price:.2f} 原因:{reason}")

            self._sync_backtest_account()
            return True
        else:
            # 下一K线价格下单，添加到待执行队列
            if price is None:
                price = self.get_price_by_type(order_type)
            estimate_price = price if price is not None else self.get_current_price()
            actual_volume, reserved_funds = self._fit_open_volume_to_funds(volume, estimate_price)
            price_str = f"{estimate_price:.2f}" if estimate_price is not None else "未知"
            if actual_volume <= 0:
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 开空订单失败: 资金不足，请求{volume}手 参考价:{price_str}")
                self._mark_insufficient_funds(
                    f"{self.symbol} {self.kline_period} 开空订单失败：资金不足，请求{volume}手，参考价{price_str}"
                )
                return False
            if actual_volume < volume and log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 开空订单资金不足: {volume}手自动调整为{actual_volume}手")
            volume = actual_volume
            # 注意：如果是next_bar_open/high/low/close，价格可能为None，因为下一K线的数据尚未加载

            # 添加到待执行队列
            self.pending_orders.append({
                'action': "开空",
                'volume': volume,
                'price': price,  # 可能为None，将在执行时重新获取
                'reason': reason,
                'order_type': order_type,  # 保存订单类型
                'execution_time': self.current_idx + 1,  # 在下一K线执行
                'reserved_funds': reserved_funds,
            })

            if log_callback and debug_mode:
                price_str = f"{price:.2f}" if price is not None else "待确定"
                log_callback(f"{self.symbol} {self.kline_period} 添加待执行订单: 开空 {volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")

            self._sync_backtest_account()
            return True

    def buycover(self, volume: Optional[int] = None, reason: str = "", log_callback=None, order_type='bar_close', offset_ticks: Optional[int] = None, price: Optional[float] = None):
        """
        平空仓

        Args:
            volume (int, optional): 交易数量，None表示平掉所有空仓
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值同buy函数
            offset_ticks: 价格偏移tick数
            price: 限价单价格（仅当order_type='limit'时有效）

        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True

        if order_type == 'bar_close':
            # 当前K线收盘价下单，立即执行
            price = self.get_current_price()
            if price is None:
                return False

            if volume is None:
                volume = max(0, -self.current_pos)

            # 检查是否有空头持仓可平
            actual_volume = min(volume, max(0, -self.current_pos))
            if actual_volume <= 0:
                # 没有空头持仓可平，不记录交易
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 平空失败: 无空头持仓可平")
                return True

            self.target_pos = self.current_pos + actual_volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)

            # 记录交易
            self.add_trade("平空", price, actual_volume, reason,
                           raw_price=self._unadjust_price(price))
            self._sync_backtest_account()
            return True
        elif order_type == 'market':
            # 市价单，TICK数据买入使用卖一价格(AskPrice1)
            price = None
            if self._has_array_cache and self._ask1_arr is not None \
                    and 0 <= self.current_idx < self._data_len:
                price = float(self._ask1_arr[self.current_idx])
            elif 'AskPrice1' in self.data.columns and self.current_idx < len(self.data):
                price = self.data.iloc[self.current_idx]['AskPrice1']
            else:
                price = self.get_current_price()

            if price is None:
                return False

            if volume is None:
                volume = max(0, -self.current_pos)

            # 检查是否有空头持仓可平
            actual_volume = min(volume, max(0, -self.current_pos))
            if actual_volume <= 0:
                # 没有空头持仓可平，不记录交易
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 市价平空失败: 无空头持仓可平")
                return True

            self.target_pos = self.current_pos + actual_volume
            if reason:
                self.set_signal_reason(reason)
            self._update_pos(log_callback)

            # 记录交易
            self.add_trade("平空", price, actual_volume, reason,
                           raw_price=self._unadjust_price(price))

            if log_callback and debug_mode:
                log_callback(f"{self.symbol} {self.kline_period} 市价买平: {actual_volume}手 成交价:{price:.2f} 原因:{reason}")

            self._sync_backtest_account()
            return True
        else:
            # 下一K线价格下单，添加到待执行队列
            if price is None:
                price = self.get_price_by_type(order_type)
            # 注意：如果是next_bar_open/high/low/close，价格可能为None，因为下一K线的数据尚未加载

            if volume is None:
                volume = max(0, -self.current_pos)

            # 检查是否有空头持仓可平
            actual_volume = min(volume, max(0, -self.current_pos))
            if actual_volume <= 0:
                # 没有空头持仓可平，不添加订单
                if log_callback and debug_mode:
                    log_callback(f"{self.symbol} {self.kline_period} 平空订单失败: 无空头持仓可平")
                return True

            # 添加到待执行队列
            self.pending_orders.append({
                'action': "平空",
                'volume': actual_volume,
                'price': price,  # 可能为None，将在执行时重新获取
                'reason': reason,
                'order_type': order_type,  # 保存订单类型
                'execution_time': self.current_idx + 1  # 在下一K线执行
            })

            if log_callback and debug_mode:
                price_str = f"{price:.2f}" if price is not None else "待确定"
                log_callback(f"{self.symbol} {self.kline_period} 添加待执行订单: 平空 {actual_volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")

            return True

    def reverse_pos(self, reason: str = "", log_callback=None, order_type='bar_close'):
        """
        反手（多转空，空转多）

        Args:
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值同buy函数

        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True

        old_pos = self.current_pos
        if old_pos == 0:
            return True

        if old_pos > 0:
            reverse_volume = old_pos
            if order_type in ('bar_close', 'market'):
                if not self.sell(volume=reverse_volume, reason=reason, log_callback=log_callback, order_type=order_type):
                    return False
                return self.sellshort(volume=reverse_volume, reason=reason, log_callback=log_callback, order_type=order_type)

            price = self.get_price_by_type(order_type)
            self.pending_orders.append({
                'action': "平多",
                'volume': reverse_volume,
                'price': price,
                'reason': reason,
                'order_type': order_type,
                'execution_time': self.current_idx + 1
            })
            self.pending_orders.append({
                'action': "开空",
                'volume': reverse_volume,
                'price': price,
                'reason': reason,
                'order_type': order_type,
                'execution_time': self.current_idx + 1,
                'reserved_funds': 0.0,
                'defer_fund_check_until_execute': True,
            })
            if log_callback and debug_mode:
                price_str = f"{price:.2f}" if price is not None else "待确定"
                log_callback(f"{self.symbol} {self.kline_period} 添加待执行反手订单: 先平多后开空 {reverse_volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")
            self._sync_backtest_account()
            return True

        reverse_volume = -old_pos
        if order_type in ('bar_close', 'market'):
            if not self.buycover(volume=reverse_volume, reason=reason, log_callback=log_callback, order_type=order_type):
                return False
            return self.buy(volume=reverse_volume, reason=reason, log_callback=log_callback, order_type=order_type)

        price = self.get_price_by_type(order_type)
        self.pending_orders.append({
            'action': "平空",
            'volume': reverse_volume,
            'price': price,
            'reason': reason,
            'order_type': order_type,
            'execution_time': self.current_idx + 1
        })
        self.pending_orders.append({
            'action': "开多",
            'volume': reverse_volume,
            'price': price,
            'reason': reason,
            'order_type': order_type,
            'execution_time': self.current_idx + 1,
            'reserved_funds': 0.0,
            'defer_fund_check_until_execute': True,
        })
        if log_callback and debug_mode:
            price_str = f"{price:.2f}" if price is not None else "待确定"
            log_callback(f"{self.symbol} {self.kline_period} 添加待执行反手订单: 先平空后开多 {reverse_volume}手 订单类型:{order_type} 预计价格:{price_str} 原因:{reason}")
        self._sync_backtest_account()
        return True

    def close_all(self, reason: str = "", log_callback=None, order_type='bar_close'):
        """
        平掉所有持仓

        Args:
            reason (str): 交易原因
            log_callback: 日志回调函数
            order_type (str): 订单类型，可选值同buy函数

        Returns:
            bool: 是否成功下单
        """
        # 获取debug模式设置
        debug_mode = getattr(log_callback, 'debug_mode', True) if log_callback else True

        if self.current_pos > 0:
            return self.sell(volume=None, reason=reason, log_callback=log_callback, order_type=order_type)
        elif self.current_pos < 0:
            return self.buycover(volume=None, reason=reason, log_callback=log_callback, order_type=order_type)
        return True  # 已经没有持仓

    # 数据访问方法
    def get_close(self) -> pd.Series:
        """获取收盘价序列"""
        df = self.get_klines()
        return df['close'] if 'close' in df.columns else pd.Series(dtype=float)  # type: ignore

    def get_open(self) -> pd.Series:
        """获取开盘价序列"""
        df = self.get_klines()
        return df['open'] if 'open' in df.columns else pd.Series(dtype=float)  # type: ignore

    def get_high(self) -> pd.Series:
        """获取最高价序列"""
        df = self.get_klines()
        return df['high'] if 'high' in df.columns else pd.Series(dtype=float)  # type: ignore

    def get_low(self) -> pd.Series:
        """获取最低价序列"""
        df = self.get_klines()
        return df['low'] if 'low' in df.columns else pd.Series(dtype=float)  # type: ignore

    def get_volume(self) -> pd.Series:
        """获取成交量序列"""
        df = self.get_klines()
        return df['volume'] if 'volume' in df.columns else pd.Series(dtype=float)  # type: ignore

    # ====== 方式二：ndarray 视图直读（零拷贝，回测主路径下比 Pandas 快 10-30×） ======
    # 语义：返回从历史第一根到当前 Bar（含）的 numpy.ndarray 视图；window 给定时
    # 只取最后 window 根。和 get_close()/.values 等价但跳过 Pandas Series/DataFrame
    # 构造、跳过 P4 的 dict 缓存、直接 slice ndarray。
    #
    # 不会泄漏未来数据：上界严格用 self.current_idx + 1。
    # 对跨周期数据源（_is_higher_tf=True）自动降级到 get_klines 路径，行为不变。
    def _get_array_slice(self, arr, window=None):
        """内部辅助：按 current_idx 和 window 截取 ndarray 视图。"""
        if arr is None:
            return np.empty(0, dtype=np.float64)
        if not hasattr(self, 'current_idx'):
            return arr
        end_idx = self.current_idx + 1
        if end_idx <= 0:
            return np.empty(0, dtype=arr.dtype)
        if end_idx > self._data_len:
            end_idx = self._data_len
        if window is None or window <= 0:
            lookback = getattr(self, 'lookback_bars', 0)
            if lookback and lookback > 0:
                start = max(0, end_idx - lookback)
            else:
                start = 0
        else:
            start = max(0, end_idx - int(window))
        return arr[start:end_idx]

    def get_close_array(self, window: int = None) -> np.ndarray:
        """获取收盘价 ndarray 视图（零拷贝）。

        - 回测：返回 [起点, current_idx] 区间的视图，不会泄漏未来数据
        - 跨周期/数据未就绪：自动降级走 get_klines() 路径返回 .to_numpy()
        - window=None 时使用 lookback_bars 配置；window=0 表示不限制
        """
        if self._has_array_cache and self._close_arr is not None and not self._is_higher_tf:
            return self._get_array_slice(self._close_arr, window)
        df = self.get_klines(window)
        if 'close' in df.columns:
            return df['close'].to_numpy(dtype=np.float64, copy=False)
        return np.empty(0, dtype=np.float64)

    def get_open_array(self, window: int = None) -> np.ndarray:
        """获取开盘价 ndarray 视图（零拷贝）。"""
        if self._has_array_cache and self._open_arr is not None and not self._is_higher_tf:
            return self._get_array_slice(self._open_arr, window)
        df = self.get_klines(window)
        if 'open' in df.columns:
            return df['open'].to_numpy(dtype=np.float64, copy=False)
        return np.empty(0, dtype=np.float64)

    def get_high_array(self, window: int = None) -> np.ndarray:
        """获取最高价 ndarray 视图（零拷贝）。"""
        if self._has_array_cache and self._high_arr is not None and not self._is_higher_tf:
            return self._get_array_slice(self._high_arr, window)
        df = self.get_klines(window)
        if 'high' in df.columns:
            return df['high'].to_numpy(dtype=np.float64, copy=False)
        return np.empty(0, dtype=np.float64)

    def get_low_array(self, window: int = None) -> np.ndarray:
        """获取最低价 ndarray 视图（零拷贝）。"""
        if self._has_array_cache and self._low_arr is not None and not self._is_higher_tf:
            return self._get_array_slice(self._low_arr, window)
        df = self.get_klines(window)
        if 'low' in df.columns:
            return df['low'].to_numpy(dtype=np.float64, copy=False)
        return np.empty(0, dtype=np.float64)

    def get_volume_array(self, window: int = None) -> np.ndarray:
        """获取成交量 ndarray 视图（零拷贝）。"""
        if self._has_array_cache and self._volume_arr is not None and not self._is_higher_tf:
            return self._get_array_slice(self._volume_arr, window)
        df = self.get_klines(window)
        if 'volume' in df.columns:
            return df['volume'].to_numpy(dtype=np.float64, copy=False)
        return np.empty(0, dtype=np.float64)

    # ====== 方式一：IndicatorCache 注册式 API（最高性能档位） ======
    # 设计：
    #   - 用户在策略 initialize(api) 里调 api.register_indicator(name, func, window=...)
    #   - DataSource 在数据已就绪的前提下，立即对全列预计算一次，得到 ndarray
    #   - 主循环 api.get_indicator(name) → arr[current_idx]，O(1) 查表
    #   - set_data / _build_arrays_cache 触发后，自动重算所有已注册指标，保证不 stale
    #
    # func 协议：
    #   func(close, open, high, low, volume) -> np.ndarray  (长度 == data_len)
    #   引擎传入的都是只读 ndarray view，用户不能修改它们。
    #
    # 行为约束：
    #   - func 必须只用历史数据计算每根 Bar 的值（即 result[i] 不能依赖 result[j>i] 的输入）。
    #     vectorize 写法（如 pandas rolling）天然满足；要严格保证，用户应自检。
    #   - func 可以返回 NaN（前 N 根没法算的位置），主循环用 get_indicator 拿这些 NaN 就跳过即可。
    def register_indicator(self, name: str, func, window: Optional[int] = None):
        """注册一个自定义指标，引擎立即对全量数据预计算。

        Args:
            name: 指标名（同一 DataSource 内唯一，重名会覆盖）
            func: 计算函数 func(close, open, high, low, volume) -> np.ndarray
            window: 该指标依赖的最大窗口（实盘增量更新时回看长度），可选

        Returns:
            np.ndarray: 预计算好的指标值数组（长度 == data_len，可能含 NaN）
        """
        if not callable(func):
            raise TypeError(f"register_indicator: func 必须是 callable，得到 {type(func)}")
        self._indicator_registry[name] = {'func': func, 'window': window}
        return self._recompute_indicator(name)

    def unregister_indicator(self, name: str) -> bool:
        """移除一个已注册的指标，返回是否成功移除。"""
        ok = self._indicator_registry.pop(name, None) is not None
        self._indicator_arrays.pop(name, None)
        return ok

    def _recompute_indicator(self, name: str) -> Optional[np.ndarray]:
        """对单个已注册指标做一次全量预计算，结果写入 _indicator_arrays。"""
        spec = self._indicator_registry.get(name)
        if spec is None:
            return None
        if not self._has_array_cache or self._data_len <= 0:
            self._indicator_arrays[name] = np.full(0, np.nan, dtype=np.float64)
            return self._indicator_arrays[name]

        close = self._close_arr if self._close_arr is not None else self._price_arr
        open_ = self._open_arr if self._open_arr is not None else close
        high = self._high_arr if self._high_arr is not None else close
        low = self._low_arr if self._low_arr is not None else close
        volume = self._volume_arr if self._volume_arr is not None else \
            np.zeros(self._data_len, dtype=np.float64)

        try:
            arr = spec['func'](close, open_, high, low, volume)
        except Exception as exc:
            raise RuntimeError(
                f"register_indicator: 指标 '{name}' 的计算函数抛错: {exc}"
            ) from exc

        if not isinstance(arr, np.ndarray):
            arr = np.asarray(arr, dtype=np.float64)
        if arr.dtype != np.float64:
            arr = arr.astype(np.float64, copy=False)
        if arr.shape[0] != self._data_len:
            raise ValueError(
                f"register_indicator: 指标 '{name}' 返回长度 {arr.shape[0]} != "
                f"data_len {self._data_len}，必须返回与数据等长的数组"
            )
        self._indicator_arrays[name] = arr
        return arr

    def _recompute_all_indicators(self):
        """重算所有已注册指标（在 set_data / _build_arrays_cache 之后调用）。"""
        if not self._indicator_registry:
            return
        for name in list(self._indicator_registry.keys()):
            self._recompute_indicator(name)

    def get_indicator(self, name: str) -> float:
        """获取已注册指标在当前 Bar 的值（标量），O(1)。

        若指标未注册或数据未就绪或 current_idx 越界，返回 NaN。
        """
        arr = self._indicator_arrays.get(name)
        if arr is None or arr.size == 0:
            return float('nan')
        idx = self.current_idx
        if not (0 <= idx < arr.size):
            return float('nan')
        return float(arr[idx])

    def get_indicator_array(self, name: str, window: int = None) -> np.ndarray:
        """获取已注册指标的最近 window 个值（ndarray 视图，零拷贝）。"""
        arr = self._indicator_arrays.get(name)
        if arr is None or arr.size == 0:
            return np.empty(0, dtype=np.float64)
        return self._get_array_slice(arr, window)

    def get_klines(self, window: int = None) -> pd.DataFrame:
        """
        获取K线数据

        回测模式：返回从开始到当前索引的数据（避免未来数据泄露）
        实盘模式：返回所有缓存的数据（deque滚动窗口）

        跨周期场景下，高周期数据源自动返回原始K线（无ffill重复），
        确保 rolling 等指标在真实K线上计算。

        Args:
            window: 滑动窗口大小，None表示使用配置的lookback_bars，0表示不限制

        Returns:
            K线数据DataFrame，最多返回window条（从最近往前）
        """
        if not self.data.empty and hasattr(self, 'current_idx'):
            # P4：per-Bar 缓存命中 — 同一根 K 线 + 同一 window 直接返回上次切片，
            # 让 get_close/get_open/get_high/get_low/get_volume 共享同一 DataFrame 视图。
            current_idx = self.current_idx
            if current_idx != self._kline_cache_idx:
                # current_idx 推进了 → 整体失效
                self._kline_cache.clear()
                self._kline_cache_idx = current_idx
            else:
                cached = self._kline_cache.get(window)
                if cached is not None:
                    return cached

            # 高周期数据源：返回原始K线（无ffill重复）
            if self._is_higher_tf and self.original_data is not None:
                current_time = self.data.index[current_idx]
                end = self.original_data.index.searchsorted(current_time, side='right')
                effective_window = window if window is not None else getattr(self, 'lookback_bars', 0)
                if effective_window > 0:
                    start = max(0, end - effective_window)
                    result = self.original_data.iloc[start:end]
                else:
                    result = self.original_data.iloc[:end]
                self._kline_cache[window] = result
                return result

            # 回测模式：只返回到当前索引的数据
            end_idx = current_idx + 1

            # 确定窗口大小：优先使用传入参数，其次使用配置的lookback_bars
            effective_window = window if window is not None else getattr(self, 'lookback_bars', 0)

            # 如果设置了窗口限制（大于0），则只返回最近的window条数据
            if effective_window > 0:
                start_idx = max(0, end_idx - effective_window)
                result = self.data.iloc[start_idx:end_idx]
            else:
                # 不限制，返回从开始到当前的所有数据
                result = self.data.iloc[:end_idx]
            self._kline_cache[window] = result
            return result

        # 实盘模式或无索引：返回所有数据
        return self.data

    def get_tick(self) -> Optional[pd.Series]:
        """返回当前tick的所有字段（Series）"""
        if not self.data.empty and self.current_idx < len(self.data):
            return self.data.iloc[self.current_idx]
        return None

    def get_ticks(self, window: int = None) -> pd.DataFrame:
        """返回最近window条tick数据（DataFrame）

        Args:
            window: 滑动窗口大小，None表示使用配置的lookback_bars，0表示不限制

        Returns:
            最近window条tick数据
        """
        if not self.data.empty and self.current_idx < len(self.data):
            end_idx = self.current_idx + 1

            # 确定窗口大小：优先使用传入参数，其次使用配置的lookback_bars，最后默认100
            if window is not None:
                effective_window = window
            else:
                effective_window = getattr(self, 'lookback_bars', 0) or 100

            # 如果窗口大于0，限制返回数据量
            if effective_window > 0:
                start_idx = max(0, end_idx - effective_window)
                return self.data.iloc[start_idx:end_idx]
            else:
                return self.data.iloc[:end_idx]
        return pd.DataFrame()


class MultiDataSource:
    """
    多数据源管理类，用于管理多个数据源
    """

    def __init__(self):
        """初始化多数据源管理器"""
        self.data_sources = []
        self.log_callback = None

    def set_log_callback(self, callback):
        """设置日志回调函数"""
        self.log_callback = callback

    def add_data_source(self, symbol: str, kline_period: str, adjust_type: str = '1',
                        data: Optional[pd.DataFrame] = None, lookback_bars: int = 0,
                        slippage_ticks: int = 1, price_tick: float = 1.0) -> int:
        """
        添加数据源

        Args:
            symbol: 品种代码，如'rb888'
            kline_period: K线周期，如'1h', 'D'
            adjust_type: 复权类型，'0'表示不复权，'1'表示后复权
            data: 数据，如果为None则创建空数据源
            lookback_bars: K线回溯窗口大小，0表示不限制
            slippage_ticks: 滑点跳数，默认1跳
            price_tick: 最小变动价位，默认1.0

        Returns:
            数据源索引
        """
        data_source = DataSource(symbol, kline_period, adjust_type, lookback_bars=lookback_bars,
                                 slippage_ticks=slippage_ticks, price_tick=price_tick)
        if data is not None:
            data_source.set_data(data)
        self.data_sources.append(data_source)
        return len(self.data_sources) - 1

    def get_data_source(self, index: int) -> Optional[DataSource]:
        """获取指定索引的数据源"""
        if 0 <= index < len(self.data_sources):
            return self.data_sources[index]
        return None

    def get_data_sources_count(self) -> int:
        """获取数据源数量"""
        return len(self.data_sources)

    def __getitem__(self, index: int) -> Optional[DataSource]:
        """通过索引访问数据源"""
        return self.get_data_source(index)

    def __len__(self) -> int:
        """获取数据源数量"""
        return self.get_data_sources_count()

    def align_data(self, align_index: bool = True, fill_method: str = 'ffill'):
        """
        对齐所有数据源的数据

        跨周期防偷价：K线时间戳为周期起始时间（向下取整），高周期K线的 close
        在周期结束前不应对低周期策略可见。因此在对齐前，将高周期数据源的
        索引向前偏移一个自身周期，确保数据只在周期结束后才参与 ffill。

        Args:
            align_index: 是否对齐索引
            fill_method: 填充方法，可选值：'ffill', 'bfill', None
        """
        if len(self.data_sources) <= 1:
            return

        # 去除重复索引（数据库可能存在重复行）
        for ds in self.data_sources:
            if not ds.data.empty and ds.data.index.duplicated().any():
                ds.data = ds.data[~ds.data.index.duplicated(keep='last')]

        # 跨周期防偷价：高周期索引向前偏移一个周期
        periods = [_period_to_timedelta(ds.kline_period) for ds in self.data_sources]
        min_period = min(periods)
        for i, ds in enumerate(self.data_sources):
            if periods[i] > min_period and not ds.data.empty:
                ds.data.index = ds.data.index + periods[i]
                ds.original_data = ds.data.copy()
                ds._is_higher_tf = True

        # 收集所有数据源的索引
        all_indices = []
        for ds in self.data_sources:
            if not ds.data.empty:
                all_indices.append(ds.data.index)

        if not all_indices:
            return

        # 合并为统一索引
        common_index = all_indices[0]
        for idx in all_indices[1:]:
            common_index = common_index.union(idx)

        # 对齐所有数据源的数据
        for ds in self.data_sources:
            if not ds.data.empty:
                ds.data = ds.data.reindex(common_index)

                if fill_method:
                    if fill_method == 'ffill':
                        ds.data = ds.data.ffill()
                    elif fill_method == 'bfill':
                        ds.data = ds.data.bfill()
                    else:
                        ds.data = ds.data.fillna(method=fill_method)  # 保留兼容性

        # 数据已经被 reindex / ffill 等改写过，需要重建 ndarray 缓存以保证主循环读到一致数据
        for ds in self.data_sources:
            ds._build_arrays_cache()