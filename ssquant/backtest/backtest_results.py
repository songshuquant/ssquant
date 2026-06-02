import os
import pandas as pd
import numpy as np


class _EquityState:
    """权益曲线计算用的运行状态对象。

    用 __slots__ + 属性访问替代 dict[str]，让每根 K 线 + 每笔成交的状态读写
    走 C 层属性查找，避免 dict.get/__setitem__ 的字符串 hash 开销。
    所有字段语义与原 calculate_results 内的同名局部变量完全一致。
    """

    __slots__ = (
        'available_cash', 'total_margin',
        'cumulative_commission', 'cumulative_slippage',
        'long_pos', 'long_avg_price',
        'short_pos', 'short_avg_price',
    )

    def __init__(self, initial_capital):
        self.available_cash = float(initial_capital)
        self.total_margin = 0.0
        self.cumulative_commission = 0.0
        self.cumulative_slippage = 0.0
        self.long_pos = 0
        self.long_avg_price = 0.0
        self.short_pos = 0
        self.short_avg_price = 0.0


def _apply_trade_to_equity_state(state, trade, contract_multiplier, margin_rate):
    """把一笔成交应用到 _EquityState 上（in-place 修改）。

    与原 calculate_results 中权益曲线循环里 6 个动作分支（开多/平多/开空/平空/
    平多开空/平空开多）的语义、加减顺序、均价规则完全一致。
    """
    action = trade['action']

    if action == '开多':
        volume = trade['volume']
        price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
        position_cost = price * volume * contract_multiplier
        margin_required = position_cost * margin_rate
        commission = trade.get('commission', 0)
        state.available_cash -= (margin_required + commission)
        state.total_margin += margin_required
        state.cumulative_commission += commission
        state.cumulative_slippage += trade.get('slippage', 0)
        if state.long_pos > 0:
            state.long_avg_price = (state.long_pos * state.long_avg_price + volume * price) / (state.long_pos + volume)
        else:
            state.long_avg_price = price
        state.long_pos += volume

    elif action == '平多':
        volume = min(trade['volume'], state.long_pos)
        if volume <= 0:
            return
        price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
        commission = trade.get('commission', 0)
        position_value = state.long_avg_price * volume * contract_multiplier
        margin_released = position_value * margin_rate
        close_profit = (price - state.long_avg_price) * volume * contract_multiplier
        state.available_cash += (margin_released + close_profit - commission)
        state.total_margin -= margin_released
        state.cumulative_commission += commission
        state.cumulative_slippage += trade.get('slippage', 0)
        state.long_pos -= volume
        if state.long_pos <= 0:
            state.long_pos = 0
            state.long_avg_price = 0.0

    elif action == '开空':
        volume = trade['volume']
        price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
        position_cost = price * volume * contract_multiplier
        margin_required = position_cost * margin_rate
        commission = trade.get('commission', 0)
        state.available_cash -= (margin_required + commission)
        state.total_margin += margin_required
        state.cumulative_commission += commission
        state.cumulative_slippage += trade.get('slippage', 0)
        if state.short_pos > 0:
            state.short_avg_price = (state.short_pos * state.short_avg_price + volume * price) / (state.short_pos + volume)
        else:
            state.short_avg_price = price
        state.short_pos += volume

    elif action == '平空':
        volume = min(trade['volume'], state.short_pos)
        if volume <= 0:
            return
        price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
        commission = trade.get('commission', 0)
        position_value = state.short_avg_price * volume * contract_multiplier
        margin_released = position_value * margin_rate
        close_profit = (state.short_avg_price - price) * volume * contract_multiplier
        state.available_cash += (margin_released + close_profit - commission)
        state.total_margin -= margin_released
        state.cumulative_commission += commission
        state.cumulative_slippage += trade.get('slippage', 0)
        state.short_pos -= volume
        if state.short_pos <= 0:
            state.short_pos = 0
            state.short_avg_price = 0.0

    elif action == '平多开空':
        volume = trade['volume']
        price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
        commission = trade.get('commission', 0)
        slippage_cost = trade.get('slippage', 0)
        state.cumulative_commission += commission
        state.cumulative_slippage += slippage_cost
        close_vol = min(volume, state.long_pos)
        open_vol = close_vol
        if close_vol > 0:
            position_value = state.long_avg_price * close_vol * contract_multiplier
            margin_released = position_value * margin_rate
            close_profit = (price - state.long_avg_price) * close_vol * contract_multiplier
            state.available_cash += (margin_released + close_profit)
            state.total_margin -= margin_released
            state.long_pos -= close_vol
            if state.long_pos <= 0:
                state.long_pos = 0
                state.long_avg_price = 0.0
        state.available_cash -= commission
        if open_vol > 0:
            position_cost = price * open_vol * contract_multiplier
            margin_required = position_cost * margin_rate
            state.available_cash -= margin_required
            state.total_margin += margin_required
            if state.short_pos > 0:
                state.short_avg_price = (state.short_pos * state.short_avg_price + open_vol * price) / (state.short_pos + open_vol)
            else:
                state.short_avg_price = price
            state.short_pos += open_vol

    elif action == '平空开多':
        volume = trade['volume']
        price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
        commission = trade.get('commission', 0)
        slippage_cost = trade.get('slippage', 0)
        state.cumulative_commission += commission
        state.cumulative_slippage += slippage_cost
        close_vol = min(volume, state.short_pos)
        open_vol = close_vol
        if close_vol > 0:
            position_value = state.short_avg_price * close_vol * contract_multiplier
            margin_released = position_value * margin_rate
            close_profit = (state.short_avg_price - price) * close_vol * contract_multiplier
            state.available_cash += (margin_released + close_profit)
            state.total_margin -= margin_released
            state.short_pos -= close_vol
            if state.short_pos <= 0:
                state.short_pos = 0
                state.short_avg_price = 0.0
        state.available_cash -= commission
        if open_vol > 0:
            position_cost = price * open_vol * contract_multiplier
            margin_required = position_cost * margin_rate
            state.available_cash -= margin_required
            state.total_margin += margin_required
            if state.long_pos > 0:
                state.long_avg_price = (state.long_pos * state.long_avg_price + open_vol * price) / (state.long_pos + open_vol)
            else:
                state.long_avg_price = price
            state.long_pos += open_vol


def _extract_price_array(effective_data):
    """从 effective_data 提取主价格列为 np.float64 ndarray。
    K 线: close；Tick: LastPrice；报价: (Bid1+Ask1)/2。

    v0.4.6：若 K 线 DataFrame 带有 _adjust_factor 列，返回的是
    原始合约价（close / _adjust_factor），与 trades 里 raw_price 对齐，
    避免盯市 P&L 出现复权幻觉。
    """
    cols = effective_data.columns
    if 'close' in cols:
        arr = effective_data['close'].to_numpy(dtype=np.float64, copy=False)
        if '_adjust_factor' in cols:
            f = effective_data['_adjust_factor'].to_numpy(dtype=np.float64, copy=False)
            # 全 1 等价不复权，跳过除法保持位级一致
            if not np.allclose(f, 1.0):
                # 用 np.where 避免 factor=0 触发 RuntimeWarning（理论上不会发生）
                safe_f = np.where(f > 0, f, 1.0)
                return arr / safe_f
        return arr
    if 'LastPrice' in cols:
        return effective_data['LastPrice'].to_numpy(dtype=np.float64, copy=False)
    if 'BidPrice1' in cols and 'AskPrice1' in cols:
        bid = effective_data['BidPrice1'].to_numpy(dtype=np.float64, copy=False)
        ask = effective_data['AskPrice1'].to_numpy(dtype=np.float64, copy=False)
        return (bid + ask) * 0.5
    raise KeyError("数据中未找到价格字段（close/LastPrice/BidPrice1+AskPrice1）")


class BacktestResultCalculator:
    """回测结果计算器，负责计算交易统计、盈亏和绩效指标等"""

    def __init__(self, logger=None):
        """初始化结果计算器

        Args:
            logger: 日志管理器实例
        """
        self.logger = logger
        self.results = {}

    def _get_combined_equity_curve(self, results):
        """获取综合权益曲线（所有数据源权益相加）"""
        all_equity_curves = []

        for key, result in results.items():
            if isinstance(result, dict) and 'equity_curve' in result and isinstance(result['equity_curve'], pd.Series):
                all_equity_curves.append(result['equity_curve'])

        if not all_equity_curves:
            return pd.Series(dtype=float)

        if len(all_equity_curves) == 1:
            return all_equity_curves[0]

        # 使用交集：只保留所有数据源都有数据的时间点
        common_indices = all_equity_curves[0].index
        for curve in all_equity_curves[1:]:
            common_indices = common_indices.intersection(curve.index)

        if len(common_indices) == 0:
            base_curve = max(all_equity_curves, key=len)
            combined = base_curve.copy()
            for curve in all_equity_curves:
                if curve is not base_curve:
                    aligned = curve.reindex(base_curve.index)
                    combined = combined + aligned.fillna(method='ffill').fillna(method='bfill')
            return combined
        else:
            combined = pd.Series(0.0, index=common_indices)
            for curve in all_equity_curves:
                combined = combined + curve.reindex(common_indices)
            return combined

    def calculate_performance(self, results):
        """计算回测性能指标

        Args:
            results: 回测结果字典

        Returns:
            包含性能指标的字典
        """
        if not results:
            return {}

        # 提取关键绩效指标
        performance = {}

        # 如果存在多个数据源，则计算平均指标
        total_return = 0
        annual_return = 0
        sharpe_ratio = 0
        win_rate = 0
        total_trades = 0
        winning_trades = 0
        losing_trades = 0
        profit_factor = 0

        # 计数器
        count = 0

        # 遍历所有结果
        for key, result in results.items():
            if isinstance(result, dict) and 'net_value' in result:
                count += 1

                # 确保净值不小于0.0001（防止出现负净值）
                net_value = max(0.0001, result.get('net_value', 1.0))
                result['net_value'] = net_value  # 修正结果中的净值

                # 累加绩效指标
                total_return += (net_value - 1.0) * 100  # 转换为百分比
                annual_return += result.get('annual_return', 0)
                sharpe_ratio += result.get('sharpe_ratio', 0)
                win_rate += result.get('win_rate', 0) * 100  # 转换为百分比

                # 累加交易统计
                total_trades += result.get('total_trades', 0)
                winning_trades += result.get('win_trades', 0)
                losing_trades += result.get('loss_trades', 0)
                profit_factor += result.get('profit_factor', 0)

        # 基于综合权益曲线计算最大回撤（而非单品种平均）
        combined_equity = self._get_combined_equity_curve(results)
        if not combined_equity.empty and combined_equity.max() > 0:
            combined_equity = combined_equity.clip(lower=0.01)
            cummax = combined_equity.cummax()
            drawdown = cummax - combined_equity
            performance['max_drawdown'] = drawdown.max()
            performance['max_drawdown_pct'] = (drawdown / cummax).max() * 100
        else:
            performance['max_drawdown'] = 0
            performance['max_drawdown_pct'] = 0

        # 计算平均值
        if count > 0:
            performance['total_return'] = total_return / count
            performance['annual_return'] = annual_return / count
            performance['sharpe_ratio'] = sharpe_ratio / count
            performance['win_rate'] = win_rate / count

            # 交易统计
            trade_stats = {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'profit_factor': profit_factor / count if count > 0 else 0
            }
            performance['trade_stats'] = trade_stats

        # 添加性能指标到结果中
        results['performance'] = performance

        return performance

    def log(self, message):
        """记录日志

        Args:
            message: 日志消息
        """
        if self.logger:
            self.logger.log_message(message)
        else:
            print(message)

    def calculate_results(self, multi_data_source, symbol_configs):
        """计算回测结果

        Args:
            multi_data_source: 多数据源实例
            symbol_configs: 品种配置字典

        Returns:
            results: 回测结果字典
        """
        results = {}

        # 资金分配：统计每个品种的 initial_capital 和对应的数据源数量
        num_data_sources = len(multi_data_source.data_sources)
        _symbol_ds_info = {}
        for ds in multi_data_source.data_sources:
            sc = symbol_configs.get(ds.symbol, {})
            cap = sc.get('initial_capital', 100000.0)
            if ds.symbol not in _symbol_ds_info:
                _symbol_ds_info[ds.symbol] = {'capital': cap, 'count': 0}
            _symbol_ds_info[ds.symbol]['count'] += 1
        # 判断分配模式：所有品种 initial_capital 相同 → 共享总资金均分；不同 → 按品种独立分配
        _unique_capitals = set(v['capital'] for v in _symbol_ds_info.values())
        _shared_capital_mode = len(_unique_capitals) == 1 and num_data_sources > 1

        # 遍历所有数据源
        for ds_idx, ds in enumerate(multi_data_source.data_sources):
            # 获取交易记录
            trades = ds.trades
            result_end_idx = int(getattr(ds, 'result_end_idx', len(ds.data)) or 0)
            result_end_idx = max(0, min(result_end_idx, len(ds.data)))
            effective_data = ds.data.iloc[:result_end_idx] if result_end_idx > 0 else ds.data.iloc[0:0]

            if not trades:
                self.log(f"数据源 #{ds_idx} ({ds.symbol} {ds.kline_period}) 没有交易记录")
                continue
            if effective_data.empty:
                self.log(f"数据源 #{ds_idx} ({ds.symbol} {ds.kline_period}) 没有可用于生成报告的回测区间")
                continue

            # 获取品种配置
            symbol_config = symbol_configs.get(ds.symbol, {
                'commission': 0.0003,  # 手续费率
                'margin_rate': 0.1,  # 保证金率
                'contract_multiplier': 10,  # 合约乘数
                'initial_capital': 100000.0  # 初始资金
            })
            commission_rate = symbol_config.get('commission', 0.0003)
            margin_rate = symbol_config.get('margin_rate', 0.1)
            contract_multiplier = symbol_config.get('contract_multiplier', 10)
            _ds_allocated = getattr(ds, '_allocated_capital', None)
            if _ds_allocated is not None:
                initial_capital = _ds_allocated
            else:
                raw_capital = symbol_config.get('initial_capital', 100000.0)
                if _shared_capital_mode:
                    initial_capital = raw_capital / num_data_sources
                elif num_data_sources > 1:
                    initial_capital = raw_capital / _symbol_ds_info[ds.symbol]['count']
                else:
                    initial_capital = raw_capital

            # 获取固定金额手续费（元/手）
            commission_per_lot = symbol_config.get('commission_per_lot', 0)
            commission_close_per_lot = symbol_config.get('commission_close_per_lot', 0)
            commission_close_today_per_lot = symbol_config.get('commission_close_today_per_lot', 0)

            # 判断手续费计算方式：
            # - 如果费率 > 1e-05（有意义的费率），则使用费率计算（如螺纹钢 0.000101）
            # - 如果费率 ≈ 1e-06（无意义占位符）且固定金额 > 0，则使用固定金额（如黄金 10元/手）
            use_fixed_commission = commission_rate < 1e-05 and commission_per_lot > 0.1

            # ===== 基于均价跟踪计算每笔交易的盈亏（支持加仓/部分平仓/复合反手） =====
            _long_pos = 0
            _long_avg_price = 0.0
            _short_pos = 0
            _short_avg_price = 0.0

            def _calc_trade_commission(action, price, vol):
                """根据动作类型（开仓/平仓）计算手续费"""
                is_close = action in ('平多', '平空')
                if use_fixed_commission:
                    per_lot = commission_close_per_lot if is_close else commission_per_lot
                    return per_lot * vol
                return price * vol * contract_multiplier * commission_rate

            for trade in trades:
                action = trade['action']
                price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
                volume = trade['volume']
                _slippage_per_unit = trade.get('slippage_cost', 0)

                if action == '开多':
                    trade['slippage'] = _slippage_per_unit * volume * contract_multiplier
                    comm = _calc_trade_commission(action, price, volume)
                    trade['commission'] = comm
                    trade['points_profit'] = 0
                    trade['amount_profit'] = 0
                    trade['margin'] = price * volume * contract_multiplier * margin_rate
                    if _long_pos > 0:
                        _long_avg_price = (_long_pos * _long_avg_price + volume * price) / (_long_pos + volume)
                    else:
                        _long_avg_price = price
                    _long_pos += volume

                elif action == '平多':
                    actual_vol = min(volume, _long_pos)
                    if actual_vol <= 0:
                        trade['commission'] = 0
                        trade['points_profit'] = 0
                        trade['amount_profit'] = 0
                        trade['net_profit'] = 0
                        trade['roi'] = 0
                        trade['profit'] = 0
                        trade['slippage'] = 0
                        trade['margin'] = 0
                        continue
                    trade['slippage'] = _slippage_per_unit * actual_vol * contract_multiplier
                    comm = _calc_trade_commission(action, price, actual_vol)
                    pts = price - _long_avg_price
                    amt = pts * actual_vol * contract_multiplier
                    net = amt - comm
                    mgn = max(_long_avg_price, price) * actual_vol * contract_multiplier * margin_rate
                    trade['commission'] = comm
                    trade['points_profit'] = pts
                    trade['amount_profit'] = amt
                    trade['net_profit'] = net
                    trade['roi'] = net / mgn * 100 if mgn > 0 else 0
                    trade['profit'] = net
                    trade['margin'] = mgn
                    _long_pos -= actual_vol
                    if _long_pos <= 0:
                        _long_pos = 0
                        _long_avg_price = 0.0

                elif action == '开空':
                    trade['slippage'] = _slippage_per_unit * volume * contract_multiplier
                    comm = _calc_trade_commission(action, price, volume)
                    trade['commission'] = comm
                    trade['points_profit'] = 0
                    trade['amount_profit'] = 0
                    trade['margin'] = price * volume * contract_multiplier * margin_rate
                    if _short_pos > 0:
                        _short_avg_price = (_short_pos * _short_avg_price + volume * price) / (_short_pos + volume)
                    else:
                        _short_avg_price = price
                    _short_pos += volume

                elif action == '平空':
                    actual_vol = min(volume, _short_pos)
                    if actual_vol <= 0:
                        trade['commission'] = 0
                        trade['points_profit'] = 0
                        trade['amount_profit'] = 0
                        trade['net_profit'] = 0
                        trade['roi'] = 0
                        trade['profit'] = 0
                        trade['slippage'] = 0
                        trade['margin'] = 0
                        continue
                    trade['slippage'] = _slippage_per_unit * actual_vol * contract_multiplier
                    comm = _calc_trade_commission(action, price, actual_vol)
                    pts = _short_avg_price - price
                    amt = pts * actual_vol * contract_multiplier
                    net = amt - comm
                    mgn = max(_short_avg_price, price) * actual_vol * contract_multiplier * margin_rate
                    trade['commission'] = comm
                    trade['points_profit'] = pts
                    trade['amount_profit'] = amt
                    trade['net_profit'] = net
                    trade['roi'] = net / mgn * 100 if mgn > 0 else 0
                    trade['profit'] = net
                    trade['margin'] = mgn
                    _short_pos -= actual_vol
                    if _short_pos <= 0:
                        _short_pos = 0
                        _short_avg_price = 0.0

                elif action == '平多开空':
                    close_vol = min(volume, _long_pos)
                    open_vol = close_vol
                    close_comm = 0
                    pts = 0
                    amt = 0
                    if close_vol > 0:
                        close_comm = _calc_trade_commission('平多', price, close_vol)
                        pts = price - _long_avg_price
                        amt = pts * close_vol * contract_multiplier
                        _long_pos -= close_vol
                        if _long_pos <= 0:
                            _long_pos = 0
                            _long_avg_price = 0.0
                    open_comm = _calc_trade_commission('开空', price, open_vol) if open_vol > 0 else 0
                    if open_vol > 0:
                        if _short_pos > 0:
                            _short_avg_price = (_short_pos * _short_avg_price + open_vol * price) / (_short_pos + open_vol)
                        else:
                            _short_avg_price = price
                        _short_pos += open_vol
                    total_comm = close_comm + open_comm
                    net = amt - total_comm if close_vol > 0 else 0
                    mgn = price * open_vol * contract_multiplier * margin_rate if open_vol > 0 else 0
                    trade['slippage'] = trade.get('slippage_cost', 0) * (close_vol + open_vol) * contract_multiplier
                    trade['commission'] = total_comm
                    trade['points_profit'] = pts
                    trade['amount_profit'] = amt
                    trade['net_profit'] = net
                    trade['roi'] = net / mgn * 100 if mgn > 0 and close_vol > 0 else 0
                    trade['profit'] = net
                    trade['margin'] = mgn

                elif action == '平空开多':
                    close_vol = min(volume, _short_pos)
                    open_vol = close_vol
                    close_comm = 0
                    pts = 0
                    amt = 0
                    if close_vol > 0:
                        close_comm = _calc_trade_commission('平空', price, close_vol)
                        pts = _short_avg_price - price
                        amt = pts * close_vol * contract_multiplier
                        _short_pos -= close_vol
                        if _short_pos <= 0:
                            _short_pos = 0
                            _short_avg_price = 0.0
                    open_comm = _calc_trade_commission('开多', price, open_vol) if open_vol > 0 else 0
                    if open_vol > 0:
                        if _long_pos > 0:
                            _long_avg_price = (_long_pos * _long_avg_price + open_vol * price) / (_long_pos + open_vol)
                        else:
                            _long_avg_price = price
                        _long_pos += open_vol
                    total_comm = close_comm + open_comm
                    net = amt - total_comm if close_vol > 0 else 0
                    mgn = price * open_vol * contract_multiplier * margin_rate if open_vol > 0 else 0
                    trade['slippage'] = trade.get('slippage_cost', 0) * (close_vol + open_vol) * contract_multiplier
                    trade['commission'] = total_comm
                    trade['points_profit'] = pts
                    trade['amount_profit'] = amt
                    trade['net_profit'] = net
                    trade['roi'] = net / mgn * 100 if mgn > 0 and close_vol > 0 else 0
                    trade['profit'] = net
                    trade['margin'] = mgn

                else:
                    trade.setdefault('commission', 0)
                    trade.setdefault('points_profit', 0)
                    trade.setdefault('amount_profit', 0)
                    trade.setdefault('slippage', 0)
                    trade.setdefault('margin', 0)

            # ===== 统计交易数据（包含复合反手动作） =====
            _close_actions = ('平多', '平空', '平多开空', '平空开多')
            total_trades = sum(1 for t in trades if t['action'] in _close_actions)
            win_trades = sum(1 for t in trades if t.get('net_profit', 0) > 0 and t['action'] in _close_actions)
            loss_trades = sum(1 for t in trades if t.get('net_profit', 0) < 0 and t['action'] in _close_actions)
            win_rate = win_trades / (win_trades + loss_trades) if (win_trades + loss_trades) > 0 else 0

            total_points_profit = sum(t.get('points_profit', 0) for t in trades)
            total_amount_profit = sum(t.get('amount_profit', 0) for t in trades)
            total_commission = sum(t.get('commission', 0) for t in trades)
            total_slippage = sum(t.get('slippage', 0) for t in trades)
            total_net_profit = sum(t.get('net_profit', 0) for t in trades)

            _total_win_pnl = sum(t.get('net_profit', 0) for t in trades if t.get('net_profit', 0) > 0 and t['action'] in _close_actions)
            _total_loss_pnl = abs(sum(t.get('net_profit', 0) for t in trades if t.get('net_profit', 0) < 0 and t['action'] in _close_actions))
            avg_win = _total_win_pnl / win_trades if win_trades > 0 else 0
            avg_loss = -(_total_loss_pnl / loss_trades) if loss_trades > 0 else 0

            if _total_loss_pnl > 0:
                profit_factor = _total_win_pnl / _total_loss_pnl
            else:
                profit_factor = float('inf') if _total_win_pnl > 0 else 0

            # ===== P10：双指针 + ndarray 增量推进权益曲线（O(B+T)，原 O(B×T²)） =====
            equity_arr, gross_equity_arr = self._calc_equity_curve_fast(
                effective_data, trades, initial_capital,
                contract_multiplier, margin_rate
            )

            # 审计通道：SSQUANT_AUDIT_RESULTS=1 时同步跑老 O(B×T²) 算法逐位对账，
            # 任何差异立即抛 AssertionError，作为后续优化的安全网。
            if os.environ.get('SSQUANT_AUDIT_RESULTS') == '1':
                legacy_eq, legacy_gross = self._calc_equity_curve_legacy(
                    effective_data, trades, initial_capital,
                    contract_multiplier, margin_rate
                )
                if not np.allclose(equity_arr, legacy_eq, rtol=1e-9, atol=1e-6, equal_nan=True):
                    diff = np.abs(equity_arr - legacy_eq)
                    idx = int(np.argmax(diff))
                    raise AssertionError(
                        f"[SSQUANT_AUDIT_RESULTS] equity_curve 不一致 "
                        f"ds={ds.symbol} {ds.kline_period} idx={idx} "
                        f"fast={equity_arr[idx]} legacy={legacy_eq[idx]} "
                        f"max_diff={diff.max()}"
                    )
                if not np.allclose(gross_equity_arr, legacy_gross, rtol=1e-9, atol=1e-6, equal_nan=True):
                    diff = np.abs(gross_equity_arr - legacy_gross)
                    idx = int(np.argmax(diff))
                    raise AssertionError(
                        f"[SSQUANT_AUDIT_RESULTS] gross_equity_curve 不一致 "
                        f"ds={ds.symbol} {ds.kline_period} idx={idx} "
                        f"fast={gross_equity_arr[idx]} legacy={legacy_gross[idx]} "
                        f"max_diff={diff.max()}"
                    )

            equity_curve = pd.Series(equity_arr, index=effective_data.index, dtype=float)
            gross_equity_curve = pd.Series(gross_equity_arr, index=effective_data.index, dtype=float)

            # 计算期末权益和净值
            final_equity = equity_curve.iloc[-1] if not equity_curve.empty else initial_capital
            gross_final_equity = gross_equity_curve.iloc[-1] if not gross_equity_curve.empty else initial_capital

            # 确保期末权益不小于0.01（为了避免负净值）
            final_equity = max(0.01, final_equity)
            gross_final_equity = max(0.01, gross_final_equity)

            net_value = final_equity / initial_capital

            # 重新计算利润指标，确保与权益曲线一致
            # 净利润 = 期末权益 - 初始资金（基于 equity_curve，已扣除手续费和滑点）
            total_net_profit = final_equity - initial_capital
            # 毛利润 = 净利润 + 手续费 + 滑点（完全不含任何成本的原始盈亏）
            total_amount_profit = total_net_profit + total_commission + total_slippage

            # 计算最大回撤（使用修改后的权益曲线）
            if not equity_curve.empty and equity_curve.max() > 0:
                # 对权益曲线进行修正，不允许出现负值
                equity_curve = equity_curve.clip(lower=0.01)

                cummax = equity_curve.cummax()
                drawdown = (cummax - equity_curve)
                max_drawdown = drawdown.max()
                max_drawdown_pct = (drawdown / cummax).max() * 100
            else:
                max_drawdown = 0
                max_drawdown_pct = 0

            # 计算年化收益率和夏普比率
            # 先将权益曲线按日聚合，避免不同K线周期导致的计算偏差
            annual_return = 0
            sharpe_ratio = 0

            if not equity_curve.empty and len(equity_curve) > 1:
                # 将权益曲线按日聚合（取每日最后一个值）
                equity_with_date = pd.Series(equity_curve.values, index=effective_data.index[:len(equity_curve)])
                daily_equity = equity_with_date.resample('D').last().dropna()

                if len(daily_equity) > 1:
                    # 计算日收益率（百分比形式）
                    daily_returns = daily_equity.pct_change().dropna()

                    # 计算实际交易天数
                    actual_trading_days = len(daily_equity)

                    # 年化收益率：(期末/期初)^(250/交易天数) - 1
                    if actual_trading_days > 0 and daily_equity.iloc[0] > 0:
                        total_return = (daily_equity.iloc[-1] / daily_equity.iloc[0]) - 1
                        # 简单年化：总收益率 / 年数
                        years = actual_trading_days / 250
                        if years > 0:
                            annual_return = (total_return / years) * 100

                    # 夏普比率：(日收益率均值 - 无风险日利率) / 日收益率标准差 * √250
                    # 假设无风险年利率为3%
                    risk_free_daily = 0.03 / 250

                    if len(daily_returns) > 0 and daily_returns.std() > 0:
                        excess_return = daily_returns.mean() - risk_free_daily
                        sharpe_ratio = excess_return / daily_returns.std() * np.sqrt(250)
                else:
                    # 只有一天数据，无法计算
                    annual_return = 0
                    sharpe_ratio = 0

            # 保存结果
            ds_results = {
                'symbol': ds.symbol,
                'kline_period': ds.kline_period,
                'adjust_type': ds.adjust_type,
                'contract_multiplier': contract_multiplier,  # 添加合约乘数到结果
                'total_trades': total_trades,
                'win_trades': win_trades,
                'loss_trades': loss_trades,
                'win_rate': win_rate,
                'total_points_profit': total_points_profit,
                'total_amount_profit': total_amount_profit,
                'total_commission': total_commission,
                'total_slippage': total_slippage,  # 总滑点成本
                'total_net_profit': total_net_profit,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': profit_factor,
                'initial_capital': initial_capital,
                'final_equity': final_equity,
                'net_value': net_value,
                'max_drawdown': max_drawdown,
                'max_drawdown_pct': max_drawdown_pct,
                'annual_return': annual_return,
                'sharpe_ratio': sharpe_ratio,
                'trades': trades,
                'data': effective_data,
                'equity_curve': equity_curve,
                'gross_equity_curve': gross_equity_curve  # 毛利润曲线（不扣除成本）
            }

            # 添加到结果字典
            key = f"{ds.symbol}_{ds.kline_period}_{'不复权' if ds.adjust_type == '0' else '后复权'}"
            results[key] = ds_results

            # 打印结果摘要
            self.log(f"\n数据源 #{ds_idx} ({ds.symbol} {ds.kline_period}) 回测结果:")
            self.log(f"总交易次数: {total_trades}")
            self.log(f"盈利交易: {win_trades}, 亏损交易: {loss_trades}")
            self.log(f"胜率: {win_rate:.2%}")
            self.log(f"初始权益: {initial_capital:.2f}")
            self.log(f"期末权益: {final_equity:.2f}")
            self.log(f"净值: {net_value:.4f}")
            self.log(f"总点数盈亏: {total_points_profit:.2f}")
            self.log(f"毛利润(不含成本): {total_amount_profit:.2f}")
            self.log(f"总手续费: {total_commission:.2f}")
            self.log(f"总滑点成本: {total_slippage:.2f}")
            self.log(f"净利润(扣除成本): {total_net_profit:.2f}")
            self.log(f"平均盈利: {avg_win:.2f}")
            self.log(f"平均亏损: {avg_loss:.2f}")
            self.log(f"盈亏比: {profit_factor:.2f}")
            self.log(f"最大回撤: {max_drawdown:.2f} ({max_drawdown_pct:.2f})")
            self.log(f"年化收益率: {annual_return:.2f}%")
            self.log(f"夏普比率: {sharpe_ratio:.2f}")

            # 打印交易明细
            self.log("\n交易明细:")
            for j, trade in enumerate(trades):
                trade_time = trade['datetime']
                action = trade['action']
                price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
                volume = trade['volume']
                points_profit = trade.get('points_profit', 0)
                amount_profit = trade.get('amount_profit', 0)
                commission = trade.get('commission', 0)
                net_profit = trade.get('net_profit', 0)
                roi = trade.get('roi', 0)
                reason = trade.get('reason', '')

                # 只打印平仓交易的盈亏
                if action in ['平多', '平空', '平多开空', '平空开多']:
                    profit_info = f" 点数盈亏:{points_profit:.2f} 金额盈亏:{amount_profit:.2f} 手续费:{commission:.2f} 净盈亏:{net_profit:.2f} ROI:{roi:.2f}%"
                else:
                    profit_info = f" 手续费:{commission:.2f}"

                self.log(f"{j+1}. {trade_time} {action} {volume}手 价格:{price:.2f}{profit_info}")

        self.results = results
        return results

    # =========================================================================
    # P10：权益曲线计算 - fast 路径（双指针 + ndarray，O(B+T)）
    # =========================================================================
    def _calc_equity_curve_fast(self, effective_data, trades, initial_capital,
                                 contract_multiplier, margin_rate):
        """O(B+T) 双指针权益曲线计算。

        替代原 calculate_results 中 393-596 行的 O(B×T²) 实现：
        - 价格走 ndarray（一次 to_numpy，无 iloc/__getitem__）
        - 成交按时间排序后用一个游标推进，每根 Bar 仅处理新到期的成交
        - 权益结果直接写 ndarray，最后一次性构造 pd.Series（避免 B 次标签写入）

        Args:
            effective_data: 已截到 result_end_idx 的 DataFrame（视图，无需 copy）
            trades: 该数据源的全部成交列表（不会被修改）
            initial_capital: 初始资金
            contract_multiplier: 合约乘数
            margin_rate: 保证金率

        Returns:
            (equity_arr, gross_equity_arr): 两个 np.float64 ndarray，
            长度均等于 len(effective_data)
        """
        n_bars = len(effective_data)
        equity_arr = np.empty(n_bars, dtype=np.float64)
        gross_equity_arr = np.empty(n_bars, dtype=np.float64)
        if n_bars == 0:
            return equity_arr, gross_equity_arr

        price_arr = _extract_price_array(effective_data)
        bar_dates = effective_data.index

        # 稳定排序：相同 datetime 的成交保留原始相对顺序，与 legacy 实现一致
        sorted_trades = sorted(trades, key=lambda x: x['datetime'])
        T = len(sorted_trades)
        trade_idx = 0

        state = _EquityState(initial_capital)

        for i in range(n_bars):
            date = bar_dates[i]
            current_price = price_arr[i]

            # 双指针：把所有 datetime <= date 的成交批量应用
            while trade_idx < T and sorted_trades[trade_idx]['datetime'] <= date:
                _apply_trade_to_equity_state(
                    state, sorted_trades[trade_idx],
                    contract_multiplier, margin_rate,
                )
                trade_idx += 1

            if state.long_pos > 0:
                long_floating_pnl = (current_price - state.long_avg_price) * state.long_pos * contract_multiplier
            else:
                long_floating_pnl = 0.0
            if state.short_pos > 0:
                short_floating_pnl = (state.short_avg_price - current_price) * state.short_pos * contract_multiplier
            else:
                short_floating_pnl = 0.0
            total_floating_pnl = long_floating_pnl + short_floating_pnl

            total_equity = state.available_cash + state.total_margin + total_floating_pnl
            gross_total_equity = total_equity + state.cumulative_commission + state.cumulative_slippage

            equity_arr[i] = total_equity
            gross_equity_arr[i] = gross_total_equity

        return equity_arr, gross_equity_arr

    # =========================================================================
    # P10：权益曲线计算 - legacy 路径（O(B×T²)，仅供 SSQUANT_AUDIT_RESULTS=1 对账）
    # =========================================================================
    def _calc_equity_curve_legacy(self, effective_data, trades, initial_capital,
                                   contract_multiplier, margin_rate):
        """旧版 O(B×T²) 实现，仅供审计对账。

        与原 calculate_results 内的权益曲线循环行为完全一致：
        - 每根 Bar 用列表推导式过滤未到期成交
        - 用 list.remove 摘除已处理成交
        - 用 effective_data.iloc[i] 取价
        - 用 equity_curve[date] = ... 写 Pandas Series

        返回 ndarray 而非 Series，方便和 fast 版本逐位对比。
        """
        n_bars = len(effective_data)
        equity_arr = np.empty(n_bars, dtype=np.float64)
        gross_equity_arr = np.empty(n_bars, dtype=np.float64)
        if n_bars == 0:
            return equity_arr, gross_equity_arr

        available_cash = float(initial_capital)
        total_margin = 0.0
        cumulative_commission = 0.0
        cumulative_slippage = 0.0
        long_pos = 0
        long_avg_price = 0.0
        short_pos = 0
        short_avg_price = 0.0

        sorted_trades = sorted(list(trades), key=lambda x: x['datetime'])

        for i, date in enumerate(effective_data.index):
            row = effective_data.iloc[i]
            if 'close' in row:
                current_price = row['close']
                # v0.4.6：盯市 P&L 用原始合约价
                if '_adjust_factor' in row:
                    f = float(row['_adjust_factor']) if pd.notna(row['_adjust_factor']) else 1.0
                    if f > 0 and abs(f - 1.0) > 1e-12:
                        current_price = current_price / f
            elif 'LastPrice' in row:
                current_price = row['LastPrice']
            elif 'BidPrice1' in row and 'AskPrice1' in row:
                current_price = (row['BidPrice1'] + row['AskPrice1']) / 2
            else:
                raise KeyError("数据中未找到价格字段（close/LastPrice/BidPrice1+AskPrice1）")

            trades_to_process = [t for t in sorted_trades if t['datetime'] <= date]
            trades_to_remove = []

            for trade in trades_to_process:
                action = trade['action']
                if action == '开多':
                    volume = trade['volume']
                    price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
                    position_cost = price * volume * contract_multiplier
                    margin_required = position_cost * margin_rate
                    commission = trade.get('commission', 0)
                    available_cash -= (margin_required + commission)
                    total_margin += margin_required
                    cumulative_commission += commission
                    cumulative_slippage += trade.get('slippage', 0)
                    if long_pos > 0:
                        long_avg_price = (long_pos * long_avg_price + volume * price) / (long_pos + volume)
                    else:
                        long_avg_price = price
                    long_pos += volume

                elif action == '平多':
                    volume = min(trade['volume'], long_pos)
                    if volume <= 0:
                        trades_to_remove.append(trade)
                        continue
                    price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
                    commission = trade.get('commission', 0)
                    position_value = long_avg_price * volume * contract_multiplier
                    margin_released = position_value * margin_rate
                    close_profit = (price - long_avg_price) * volume * contract_multiplier
                    available_cash += (margin_released + close_profit - commission)
                    total_margin -= margin_released
                    cumulative_commission += commission
                    cumulative_slippage += trade.get('slippage', 0)
                    long_pos -= volume
                    if long_pos <= 0:
                        long_pos = 0
                        long_avg_price = 0.0

                elif action == '开空':
                    volume = trade['volume']
                    price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
                    position_cost = price * volume * contract_multiplier
                    margin_required = position_cost * margin_rate
                    commission = trade.get('commission', 0)
                    available_cash -= (margin_required + commission)
                    total_margin += margin_required
                    cumulative_commission += commission
                    cumulative_slippage += trade.get('slippage', 0)
                    if short_pos > 0:
                        short_avg_price = (short_pos * short_avg_price + volume * price) / (short_pos + volume)
                    else:
                        short_avg_price = price
                    short_pos += volume

                elif action == '平空':
                    volume = min(trade['volume'], short_pos)
                    if volume <= 0:
                        trades_to_remove.append(trade)
                        continue
                    price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
                    commission = trade.get('commission', 0)
                    position_value = short_avg_price * volume * contract_multiplier
                    margin_released = position_value * margin_rate
                    close_profit = (short_avg_price - price) * volume * contract_multiplier
                    available_cash += (margin_released + close_profit - commission)
                    total_margin -= margin_released
                    cumulative_commission += commission
                    cumulative_slippage += trade.get('slippage', 0)
                    short_pos -= volume
                    if short_pos <= 0:
                        short_pos = 0
                        short_avg_price = 0.0

                elif action == '平多开空':
                    volume = trade['volume']
                    price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
                    commission = trade.get('commission', 0)
                    slippage_cost = trade.get('slippage', 0)
                    cumulative_commission += commission
                    cumulative_slippage += slippage_cost
                    close_vol = min(volume, long_pos)
                    open_vol = close_vol
                    if close_vol > 0:
                        position_value = long_avg_price * close_vol * contract_multiplier
                        margin_released = position_value * margin_rate
                        close_profit = (price - long_avg_price) * close_vol * contract_multiplier
                        available_cash += (margin_released + close_profit)
                        total_margin -= margin_released
                        long_pos -= close_vol
                        if long_pos <= 0:
                            long_pos = 0
                            long_avg_price = 0.0
                    available_cash -= commission
                    if open_vol > 0:
                        position_cost = price * open_vol * contract_multiplier
                        margin_required = position_cost * margin_rate
                        available_cash -= margin_required
                        total_margin += margin_required
                        if short_pos > 0:
                            short_avg_price = (short_pos * short_avg_price + open_vol * price) / (short_pos + open_vol)
                        else:
                            short_avg_price = price
                        short_pos += open_vol

                elif action == '平空开多':
                    volume = trade['volume']
                    price = trade.get('raw_price', trade['price'])  # v0.4.6: P&L 用真实合约原始价
                    commission = trade.get('commission', 0)
                    slippage_cost = trade.get('slippage', 0)
                    cumulative_commission += commission
                    cumulative_slippage += slippage_cost
                    close_vol = min(volume, short_pos)
                    open_vol = close_vol
                    if close_vol > 0:
                        position_value = short_avg_price * close_vol * contract_multiplier
                        margin_released = position_value * margin_rate
                        close_profit = (short_avg_price - price) * close_vol * contract_multiplier
                        available_cash += (margin_released + close_profit)
                        total_margin -= margin_released
                        short_pos -= close_vol
                        if short_pos <= 0:
                            short_pos = 0
                            short_avg_price = 0.0
                    available_cash -= commission
                    if open_vol > 0:
                        position_cost = price * open_vol * contract_multiplier
                        margin_required = position_cost * margin_rate
                        available_cash -= margin_required
                        total_margin += margin_required
                        if long_pos > 0:
                            long_avg_price = (long_pos * long_avg_price + open_vol * price) / (long_pos + open_vol)
                        else:
                            long_avg_price = price
                        long_pos += open_vol

                trades_to_remove.append(trade)

            for trade in trades_to_remove:
                if trade in sorted_trades:
                    sorted_trades.remove(trade)

            if long_pos > 0:
                long_floating_pnl = (current_price - long_avg_price) * long_pos * contract_multiplier
            else:
                long_floating_pnl = 0.0
            if short_pos > 0:
                short_floating_pnl = (short_avg_price - current_price) * short_pos * contract_multiplier
            else:
                short_floating_pnl = 0.0
            total_floating_pnl = long_floating_pnl + short_floating_pnl

            total_equity = available_cash + total_margin + total_floating_pnl
            gross_total_equity = total_equity + cumulative_commission + cumulative_slippage

            equity_arr[i] = total_equity
            gross_equity_arr[i] = gross_total_equity

        return equity_arr, gross_equity_arr

    def get_summary(self, results=None):
        """获取回测结果摘要

        Args:
            results: 回测结果字典，如果为None则使用内部结果

        Returns:
            summary: 回测结果摘要DataFrame
        """
        if results is None:
            results = self.results

        if not results:
            return None

        summary_data = []
        for key, result in results.items():
            if not isinstance(result, dict) or 'symbol' not in result:
                continue
            summary_data.append({
                '数据集': key,
                '品种': result['symbol'],
                '周期': result['kline_period'],
                '复权类型': '不复权' if result['adjust_type'] == '0' else '后复权',
                '总交易次数': result['total_trades'],
                '盈利交易': result['win_trades'],
                '亏损交易': result['loss_trades'],
                '胜率': result['win_rate'],
                '初始权益': result.get('initial_capital', 100000.0),
                '期末权益': result.get('final_equity', 100000.0),
                '净值': result.get('net_value', 1.0),
                '总点数盈亏': result.get('total_points_profit', 0),
                '总金额盈亏': result.get('total_amount_profit', 0),
                '总手续费': result.get('total_commission', 0),
                '总净盈亏': result.get('total_net_profit', 0),
                '最大回撤': result.get('max_drawdown', 0),
                '最大回撤率': result.get('max_drawdown_pct', 0),
                '年化收益率': result.get('annual_return', 0),
                '夏普比率': result.get('sharpe_ratio', 0)
            })

        return pd.DataFrame(summary_data)

    def get_results(self):
        """获取回测结果字典

        Returns:
            results: 回测结果字典
        """
        return self.results 