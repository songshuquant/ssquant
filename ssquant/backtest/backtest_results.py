import pandas as pd
import numpy as np

class BacktestResultCalculator:
    """回测结果计算器，负责计算交易统计、盈亏和绩效指标等"""
    
    def __init__(self, logger=None):
        """初始化结果计算器
        
        Args:
            logger: 日志管理器实例
        """
        self.logger = logger
        self.results = {}
    
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
        max_drawdown = 0
        max_drawdown_pct = 0
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
                max_drawdown += result.get('max_drawdown', 0)
                max_drawdown_pct += result.get('max_drawdown_pct', 0)
                sharpe_ratio += result.get('sharpe_ratio', 0)
                win_rate += result.get('win_rate', 0) * 100  # 转换为百分比
                
                # 累加交易统计
                total_trades += result.get('total_trades', 0)
                winning_trades += result.get('win_trades', 0)
                losing_trades += result.get('loss_trades', 0)
                profit_factor += result.get('profit_factor', 0)
        
        # 计算平均值
        if count > 0:
            performance['total_return'] = total_return / count
            performance['annual_return'] = annual_return / count
            performance['max_drawdown'] = max_drawdown / count
            performance['max_drawdown_pct'] = max_drawdown_pct / count
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
        
        # 遍历所有数据源
        for i, ds in enumerate(multi_data_source.data_sources):
            # 获取交易记录
            trades = ds.trades
            
            if not trades:
                self.log(f"数据源 #{i} ({ds.symbol} {ds.kline_period}) 没有交易记录")
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
            initial_capital = symbol_config.get('initial_capital', 100000.0)
            
            # 计算交易统计
            total_trades = len(trades) // 2  # 修改为开平仓一组算一次交易
            
            # 计算每笔交易的盈亏
            for j, trade in enumerate(trades):
                if j % 2 == 0 and j+1 < len(trades):  # 开仓交易
                    open_price = trade['price']
                    close_price = trades[j+1]['price']
                    volume = trade['volume']
                    
                    # 计算点数盈亏
                    if trade['action'] == '开多':
                        points_profit = (close_price - open_price)
                    elif trade['action'] == '开空':
                        points_profit = (open_price - close_price)
                    else:
                        points_profit = 0
                    
                    # 计算金额盈亏（考虑合约乘数）
                    amount_profit = points_profit * volume * contract_multiplier
                    
                    # 计算手续费
                    open_commission = open_price * volume * contract_multiplier * commission_rate
                    close_commission = close_price * volume * contract_multiplier * commission_rate
                    total_commission = open_commission + close_commission
                    
                    # 计算净盈亏（扣除手续费）
                    net_profit = amount_profit - total_commission
                    
                    # 计算保证金占用
                    margin = max(open_price, close_price) * volume * contract_multiplier * margin_rate
                    
                    # 计算收益率
                    roi = net_profit / margin * 100 if margin > 0 else 0
                    
                    # 添加盈亏字段
                    trades[j]['points_profit'] = 0  # 开仓时点数盈亏为0
                    trades[j]['amount_profit'] = 0  # 开仓时金额盈亏为0
                    trades[j]['commission'] = open_commission  # 开仓手续费
                    trades[j]['margin'] = margin  # 保证金占用
                    
                    trades[j+1]['points_profit'] = points_profit  # 平仓时记录点数盈亏
                    trades[j+1]['amount_profit'] = amount_profit  # 平仓时记录金额盈亏
                    trades[j+1]['commission'] = close_commission  # 平仓手续费
                    trades[j+1]['net_profit'] = net_profit  # 净盈亏
                    trades[j+1]['roi'] = roi  # 收益率
                    trades[j+1]['profit'] = net_profit  # 兼容旧代码
            
            # 处理未配对的最后一笔开仓交易（如果有）
            if len(trades) % 2 != 0:
                last_trade = trades[-1]
                if last_trade['action'] in ['开多', '开空']:
                    # 计算开仓手续费
                    last_price = last_trade['price']
                    last_volume = last_trade['volume']
                    last_commission = last_price * last_volume * contract_multiplier * commission_rate
                    # 设置手续费
                    last_trade['commission'] = last_commission
                    # 设置其他字段为默认值
                    last_trade['points_profit'] = 0
                    last_trade['amount_profit'] = 0
                    last_trade['margin'] = last_price * last_volume * contract_multiplier * margin_rate
            
            # 重新计算统计数据
            # 只统计平仓交易的盈亏情况
            win_trades = sum(1 for t in trades if t.get('net_profit', 0) > 0 and t['action'] in ['平多', '平空'])
            loss_trades = sum(1 for t in trades if t.get('net_profit', 0) < 0 and t['action'] in ['平多', '平空'])
            win_rate = win_trades / (win_trades + loss_trades) if (win_trades + loss_trades) > 0 else 0
            
            # 计算总盈亏
            total_points_profit = sum(t.get('points_profit', 0) for t in trades)
            total_amount_profit = sum(t.get('amount_profit', 0) for t in trades)
            total_commission = sum(t.get('commission', 0) for t in trades)
            total_net_profit = sum(t.get('net_profit', 0) for t in trades)
            
            # 计算平均盈亏
            avg_win = sum(t.get('net_profit', 0) for t in trades if t.get('net_profit', 0) > 0) / win_trades if win_trades > 0 else 0
            avg_loss = sum(t.get('net_profit', 0) for t in trades if t.get('net_profit', 0) < 0) / loss_trades if loss_trades > 0 else 0
            
            # 修正盈亏比计算方式
            if avg_loss != 0:
                # 使用绝对值计算盈亏比，确保结果为正数
                profit_factor = abs(avg_win / avg_loss)
                # 如果总体亏损，盈亏比应小于1
                if total_net_profit < 0 and profit_factor > 1:
                    profit_factor = 1 / profit_factor
            else:
                profit_factor = float('inf') if avg_win > 0 else 0
            
            # 修改权益曲线计算方法，考虑持仓盈亏
            equity_curve = pd.Series(float(initial_capital), index=ds.data.index, dtype=float)
            available_cash = initial_capital  # 可用资金（未被占用的资金）
            total_margin = 0  # 总保证金占用
            total_equity = initial_capital  # 总权益（可用资金 + 保证金 + 浮动盈亏）
            
            # 持仓管理
            long_pos = 0  # 多头持仓量
            long_avg_price = 0  # 多头平均持仓价格
            short_pos = 0  # 空头持仓量
            short_avg_price = 0  # 空头平均持仓价格
            
            # 按时间排序交易记录并创建副本，避免修改原始数据
            sorted_trades = sorted(trades.copy(), key=lambda x: x['datetime'])
            
            # 遍历每个时间点
            for i, date in enumerate(ds.data.index):
                row = ds.data.iloc[i]
                # K线数据使用close，TICK数据使用LastPrice
                if 'close' in row:
                    current_price = row['close']
                elif 'LastPrice' in row:
                    current_price = row['LastPrice']
                elif 'BidPrice1' in row and 'AskPrice1' in row:
                    current_price = (row['BidPrice1'] + row['AskPrice1']) / 2
                else:
                    raise KeyError("数据中未找到价格字段（close/LastPrice/BidPrice1+AskPrice1）")
                
                # 处理当前日期的所有交易
                trades_to_process = [t for t in sorted_trades if t['datetime'] <= date]
                trades_to_remove = []  # 存储需要移除的交易索引
                
                for trade in trades_to_process:
                    if trade['action'] == '开多':
                        # 计算开仓成本和保证金
                        volume = trade['volume']
                        price = trade['price']
                        position_cost = price * volume * contract_multiplier
                        margin_required = position_cost * margin_rate
                        commission = trade.get('commission', 0)
                        
                        # 更新资金
                        available_cash -= (margin_required + commission)
                        total_margin += margin_required
                        
                        # 更新多头持仓和平均价格
                        if long_pos > 0:
                            # 计算新的加权平均持仓价格
                            long_avg_price = (long_pos * long_avg_price + volume * price) / (long_pos + volume)
                        else:
                            long_avg_price = price
                        long_pos += volume
                        
                    elif trade['action'] == '平多':
                        # 获取平仓数量和价格
                        volume = min(trade['volume'], long_pos)  # 确保不超过实际持仓
                        if volume <= 0:
                            continue  # 无多头持仓可平，跳过
                            
                        price = trade['price']
                        commission = trade.get('commission', 0)
                        
                        # 计算平仓后释放的保证金
                        position_value = long_avg_price * volume * contract_multiplier
                        margin_released = position_value * margin_rate
                        
                        # 计算平仓盈亏
                        close_profit = (price - long_avg_price) * volume * contract_multiplier
                        
                        # 更新资金
                        available_cash += (margin_released + close_profit - commission)
                        total_margin -= margin_released
                        
                        # 更新多头持仓
                        long_pos -= volume
                        # 如果完全平仓，重置平均价格
                        if long_pos <= 0:
                            long_pos = 0
                            long_avg_price = 0
                        
                    elif trade['action'] == '开空':
                        # 计算开仓成本和保证金
                        volume = trade['volume']
                        price = trade['price']
                        position_cost = price * volume * contract_multiplier
                        margin_required = position_cost * margin_rate
                        commission = trade.get('commission', 0)
                        
                        # 更新资金（空头开仓不增加现金，只收取保证金和手续费）
                        available_cash -= (margin_required + commission)
                        total_margin += margin_required
                        
                        # 更新空头持仓和平均价格
                        if short_pos > 0:
                            # 计算新的加权平均持仓价格
                            short_avg_price = (short_pos * short_avg_price + volume * price) / (short_pos + volume)
                        else:
                            short_avg_price = price
                        short_pos += volume
                        
                    elif trade['action'] == '平空':
                        # 获取平仓数量和价格
                        volume = min(trade['volume'], short_pos)  # 确保不超过实际持仓
                        if volume <= 0:
                            continue  # 无空头持仓可平，跳过
                            
                        price = trade['price']
                        commission = trade.get('commission', 0)
                        
                        # 计算平仓后释放的保证金
                        position_value = short_avg_price * volume * contract_multiplier
                        margin_released = position_value * margin_rate
                        
                        # 计算平仓盈亏
                        close_profit = (short_avg_price - price) * volume * contract_multiplier
                        
                        # 更新资金
                        available_cash += (margin_released + close_profit - commission)
                        total_margin -= margin_released
                        
                        # 更新空头持仓
                        short_pos -= volume
                        # 如果完全平仓，重置平均价格
                        if short_pos <= 0:
                            short_pos = 0
                            short_avg_price = 0
                    
                    # 标记交易为待移除，而不是直接移除
                    trades_to_remove.append(trade)
                
                # 在循环之外移除已处理的交易
                for trade in trades_to_remove:
                    if trade in sorted_trades:
                        sorted_trades.remove(trade)
                
                # 计算多头浮动盈亏
                long_floating_pnl = 0
                if long_pos > 0:
                    long_floating_pnl = (current_price - long_avg_price) * long_pos * contract_multiplier
                
                # 计算空头浮动盈亏
                short_floating_pnl = 0
                if short_pos > 0:
                    short_floating_pnl = (short_avg_price - current_price) * short_pos * contract_multiplier
                
                # 计算总浮动盈亏
                total_floating_pnl = long_floating_pnl + short_floating_pnl
                
                # 计算当前总权益
                total_equity = available_cash + total_margin + total_floating_pnl
                
                # 更新权益曲线
                equity_curve[date] = total_equity
            
            # 计算期末权益和净值
            final_equity = equity_curve.iloc[-1] if not equity_curve.empty else initial_capital
            
            # 确保期末权益不小于0.01（为了避免负净值）
            final_equity = max(0.01, final_equity)
            
            net_value = final_equity / initial_capital
            
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
            
            # 计算年化收益率（假设一年250个交易日）
            if not ds.data.empty:
                trading_days = (ds.data.index[-1] - ds.data.index[0]).days / 365
                if trading_days > 0:
                    annual_return = (total_net_profit / initial_capital) / trading_days * 100
                else:
                    annual_return = 0
            else:
                annual_return = 0
            
            # 计算夏普比率（假设无风险利率为3%）
            if not equity_curve.empty:
                daily_returns = equity_curve.diff().fillna(0)
                if daily_returns.std() > 0:
                    sharpe_ratio = (daily_returns.mean() - 0.03/250) / daily_returns.std() * np.sqrt(250)
                else:
                    sharpe_ratio = 0
            else:
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
                'data': ds.data,
                'equity_curve': equity_curve
            }
            
            # 添加到结果字典
            key = f"{ds.symbol}_{ds.kline_period}_{'不复权' if ds.adjust_type == '0' else '后复权'}"
            results[key] = ds_results
            
            # 打印结果摘要
            self.log(f"\n数据源 #{i} ({ds.symbol} {ds.kline_period}) 回测结果:")
            self.log(f"总交易次数: {total_trades}")
            self.log(f"盈利交易: {win_trades}, 亏损交易: {loss_trades}")
            self.log(f"胜率: {win_rate:.2%}")
            self.log(f"初始权益: {initial_capital:.2f}")
            self.log(f"期末权益: {final_equity:.2f}")
            self.log(f"净值: {net_value:.4f}")
            self.log(f"总点数盈亏: {total_points_profit:.2f}")
            self.log(f"总金额盈亏: {total_amount_profit:.2f}")
            self.log(f"总手续费: {total_commission:.2f}")
            self.log(f"总净盈亏: {total_net_profit:.2f}")
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
                price = trade['price']
                volume = trade['volume']
                points_profit = trade.get('points_profit', 0)
                amount_profit = trade.get('amount_profit', 0)
                commission = trade.get('commission', 0)
                net_profit = trade.get('net_profit', 0)
                roi = trade.get('roi', 0)
                reason = trade.get('reason', '')
                
                # 只打印平仓交易的盈亏
                if action in ['平多', '平空']:
                    profit_info = f" 点数盈亏:{points_profit:.2f} 金额盈亏:{amount_profit:.2f} 手续费:{commission:.2f} 净盈亏:{net_profit:.2f} ROI:{roi:.2f}%"
                else:
                    profit_info = f" 手续费:{commission:.2f}"
                
                self.log(f"{j+1}. {trade_time} {action} {volume}手 价格:{price:.2f}{profit_info}")
        
        self.results = results
        return results
    
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