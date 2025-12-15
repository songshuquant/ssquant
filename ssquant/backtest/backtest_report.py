class BacktestReportGenerator:
    """回测报告生成器，负责生成和保存性能报告"""
    
    def __init__(self, logger=None):
        """初始化报告生成器
        
        Args:
            logger: 日志管理器实例
        """
        self.logger = logger
    
    def log(self, message):
        """记录日志
        
        Args:
            message: 日志消息
        """
        if self.logger:
            self.logger.log_message(message)
        else:
            print(message)
    
    def save_performance_report(self, results, performance_file):
        """保存综合绩效报告
        
        Args:
            results: 回测结果字典
            performance_file: 绩效报告文件路径
            
        Returns:
            report_path: 报告文件路径
        """
        # 过滤掉"performance"键的条目（不是真正的数据源）
        filtered_results = {k: v for k, v in results.items() if k != 'performance'}
        
        # 使用过滤后的结果
        results = filtered_results

        # 检查是否禁用可视化和报告
        import os
        if os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            self.log("报告生成已被禁用 (NO_VISUALIZATION=True)")
            return None
        
        # 检查是否禁用控制台日志    
        if os.environ.get('NO_CONSOLE_LOG', '').lower() == 'true':
            # 完全静默模式，不生成任何输出
            return None
            
        if not performance_file:
            self.log("没有指定绩效报告文件路径，无法保存报告")
            return None
            
        with open(performance_file, 'w', encoding='utf-8') as f:
            f.write(f"多数据源回测综合绩效报告\n")
            f.write("-" * 80 + "\n\n")
            
            # 检查是否为优化结果（结构不同）
            if 'best_params' in results and 'performance' in results:
                # 这是参数优化结果，使用不同的格式
                f.write(f"参数优化结果\n")
                f.write("-" * 80 + "\n\n")
                
                # 写入优化指标
                performance = results.get('performance', {})
                f.write(f"优化指标: {performance.get('optimization_metric', 'sharpe_ratio')}\n")
                f.write(f"最优值: {performance.get('best_value', 0)}\n")
                f.write(f"夏普比率: {performance.get('sharpe_ratio', 0):.4f}\n")
                f.write(f"总收益率: {performance.get('total_return', 0):.2f}%\n")
                f.write(f"最大回撤: {performance.get('max_drawdown', 0):.2f}%\n")
                f.write(f"胜率: {performance.get('win_rate', 0):.2f}%\n")
                
                # 如果有best_params，写入最优参数
                if 'best_params' in results:
                    f.write("\n最优参数:\n")
                    for param_name, param_value in results['best_params'].items():
                        f.write(f"{param_name}: {param_value}\n")
                
                # 结束报告
                f.write("\n优化完成\n")
                self.log(f"优化结果报告已保存到: {performance_file}")
                return performance_file
            
            # 遍历所有数据源的结果
            for i, (key, result) in enumerate(results.items()):
                # 安全获取symbol和kline_period，如果不存在则使用默认值
                symbol = result.get('symbol', f'数据源{i}')
                kline_period = result.get('kline_period', '')
                
                f.write(f"\n数据源 #{i} ({symbol} {kline_period}) 回测结果:\n")
                f.write(f"总交易次数: {result.get('total_trades', 0)}\n")
                f.write(f"盈利交易: {result.get('win_trades', 0)}, 亏损交易: {result.get('loss_trades', 0)}\n")
                f.write(f"胜率: {result.get('win_rate', 0):.2%}\n")
                f.write(f"初始权益: {result.get('initial_capital', 100000.0):.2f}\n")
                f.write(f"期末权益: {result.get('final_equity', 100000.0):.2f}\n")
                f.write(f"净值: {result.get('net_value', 1.0):.4f}\n")
                f.write(f"总点数盈亏: {result.get('total_points_profit', 0):.2f}\n")
                f.write(f"总金额盈亏: {result.get('total_amount_profit', 0):.2f}\n")
                f.write(f"总手续费: {result.get('total_commission', 0):.2f}\n")
                f.write(f"总净盈亏: {result.get('total_net_profit', 0):.2f}\n")
                f.write(f"平均盈利: {result.get('avg_win', 0):.2f}\n")
                f.write(f"平均亏损: {result.get('avg_loss', 0):.2f}\n")
                f.write(f"盈亏比: {result.get('profit_factor', 0):.2f}\n")
                f.write(f"最大回撤: {result.get('max_drawdown', 0):.2f} ({result.get('max_drawdown_pct', 0):.2f}%)\n")
                f.write(f"年化收益率: {result.get('annual_return', 0):.2f}%\n")
                f.write(f"夏普比率: {result.get('sharpe_ratio', 0):.2f}\n")
                
                # 写入交易明细
                trades = result.get('trades', [])
                if trades:
                    f.write("\n交易明细:\n")
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
                        
                        f.write(f"{j+1}. {trade_time} {action} {volume}手 价格:{price:.2f}{profit_info}\n")
                    
                    f.write("-" * 80 + "\n\n")
            
            # 写入综合绩效
            if len(results) >= 1:
                f.write("\n综合绩效:\n")
                total_net_profit = sum(result.get('total_net_profit', 0) for result in results.values())
                total_trades = sum(result.get('total_trades', 0) for result in results.values()) 
                win_trades = sum(result.get('win_trades', 0) for result in results.values())
                loss_trades = sum(result.get('loss_trades', 0) for result in results.values())
                win_rate = win_trades / total_trades if total_trades > 0 else 0
                
                # 计算综合初始权益和期末权益
                total_initial_capital = sum(result.get('initial_capital', 100000.0) for result in results.values())
                total_final_equity = sum(result.get('final_equity', 100000.0) for result in results.values())
                total_net_value = total_final_equity / total_initial_capital if total_initial_capital > 0 else 1.0
                
                # 计算综合金额盈亏和手续费
                total_amount_profit = sum(result.get('total_amount_profit', 0) for result in results.values())
                total_commission = sum(result.get('total_commission', 0) for result in results.values())
                
                # 计算综合平均盈利和平均亏损
                total_win_profit = sum(result.get('avg_win', 0) * result.get('win_trades', 0) for result in results.values())
                total_loss_profit = sum(result.get('avg_loss', 0) * result.get('loss_trades', 0) for result in results.values())
                
                avg_win = total_win_profit / win_trades if win_trades > 0 else 0
                avg_loss = total_loss_profit / loss_trades if loss_trades > 0 else 0
                
                # 计算综合盈亏比
                if avg_loss != 0:
                    profit_factor = abs(avg_win / avg_loss)
                    # 如果总体亏损，盈亏比应小于1
                    if total_net_profit < 0 and profit_factor > 1:
                        profit_factor = 1 / profit_factor
                else:
                    profit_factor = float('inf') if avg_win > 0 else 0
                
                # 改进的最大回撤计算 - 合并所有数据源的权益曲线
                import pandas as pd
                import numpy as np
                
                # 收集所有数据源的权益曲线
                all_equity_curves = []
                for result in results.values():
                    if 'equity_curve' in result and isinstance(result['equity_curve'], pd.Series):
                        all_equity_curves.append(result['equity_curve'])
                
                # 如果有可用的权益曲线，则计算综合最大回撤
                if all_equity_curves:
                    # 首先将所有权益曲线对齐到相同的日期索引
                    aligned_curves = []
                    all_indices = pd.Index([])
                    
                    # 收集所有日期索引
                    for curve in all_equity_curves:
                        all_indices = all_indices.union(curve.index)
                    
                    # 对齐所有曲线到相同的日期索引
                    for curve in all_equity_curves:
                        aligned_curve = curve.reindex(all_indices)
                        # 向前填充缺失值（使用最近的有效值）
                        aligned_curve = aligned_curve.ffill()
                        # 向后填充开头的缺失值（使用最早的有效值）
                        aligned_curve = aligned_curve.bfill()
                        aligned_curves.append(aligned_curve)
                    
                    # 将所有对齐后的权益曲线相加，得到综合权益曲线
                    if aligned_curves:
                        combined_equity = sum(aligned_curves)
                        
                        # 计算综合最大回撤
                        cummax = combined_equity.cummax()
                        drawdown = (combined_equity - cummax)
                        max_drawdown = drawdown.min()
                        max_drawdown_pct = (drawdown / cummax).min() * 100
                    else:
                        # 如果无法计算，则使用以前的方法
                        max_drawdown = max(result.get('max_drawdown', 0) for result in results.values())
                        max_drawdown_pct = max(result.get('max_drawdown_pct', 0) for result in results.values())
                else:
                    # 如果没有权益曲线，则使用以前的方法
                    max_drawdown = max(result.get('max_drawdown', 0) for result in results.values())
                    max_drawdown_pct = max(result.get('max_drawdown_pct', 0) for result in results.values())
                
                # 计算加权平均年化收益率和夏普比率
                weighted_annual_return = sum(result.get('annual_return', 0) * result.get('initial_capital', 100000.0) for result in results.values()) / total_initial_capital if total_initial_capital > 0 else 0
                weighted_sharpe_ratio = sum(result.get('sharpe_ratio', 0) * result.get('initial_capital', 100000.0) for result in results.values()) / total_initial_capital if total_initial_capital > 0 else 0
                
                f.write(f"总交易次数: {total_trades}\n")
                f.write(f"盈利交易: {win_trades}, 亏损交易: {loss_trades}\n")
                f.write(f"胜率: {win_rate:.2%}\n")
                f.write(f"初始权益: {total_initial_capital:.2f}\n")
                f.write(f"期末权益: {total_final_equity:.2f}\n")
                f.write(f"净值: {total_net_value:.4f}\n")
                f.write(f"总手续费: {total_commission:.2f}\n")
                f.write(f"总金额盈亏: {total_amount_profit:.2f}\n")
                f.write(f"总净盈亏: {total_net_profit:.2f}\n")
                f.write(f"平均盈利: {avg_win:.2f}\n")
                f.write(f"平均亏损: {avg_loss:.2f}\n")
                f.write(f"盈亏比: {profit_factor:.2f}\n")
                f.write(f"最大回撤: {max_drawdown:.2f} ({max_drawdown_pct:.2f}%)\n")
                f.write(f"年化收益率: {weighted_annual_return:.2f}%\n")
                f.write(f"夏普比率: {weighted_sharpe_ratio:.2f}\n")
                
            # 添加绩效指标计算公式说明
            f.write("\n\n")
            f.write("=" * 80 + "\n")
            f.write("绩效指标计算公式说明：\n")
            f.write("=" * 80 + "\n\n")
            f.write("1. 胜率 = 盈利交易次数 / 总交易次数\n")
            f.write("2. 净值 = 期末权益 / 初始权益\n")
            f.write("3. 总点数盈亏 = 所有交易的点数盈亏之和\n")
            f.write("4. 总金额盈亏 = 所有交易的金额盈亏之和（点数盈亏 × 合约乘数 × 交易量）\n")
            f.write("5. 总净盈亏 = 总金额盈亏 - 总手续费\n")
            f.write("6. 平均盈利 = 盈利交易的净盈亏之和 / 盈利交易次数\n")
            f.write("7. 平均亏损 = 亏损交易的净盈亏之和 / 亏损交易次数\n")
            f.write("8. 盈亏比 = |平均盈利 / 平均亏损|（如果总体亏损且比值>1，则取倒数）\n")
            f.write("9. 最大回撤 = 权益曲线中的最大下跌幅度（绝对值）\n")
            f.write("10. 最大回撤率 = 最大回撤 / 回撤前的最高权益 × 100%\n")
            f.write("11. 年化收益率 = (总净盈亏 / 初始权益) / 交易周期(年) × 100%\n")
            f.write("12. 夏普比率 = (策略收益率 - 无风险收益率) / 收益率标准差 × √250（假设一年250个交易日）\n")
            f.write("\n")
            f.write("注意事项：\n")
            f.write("- 交易次数统计方式：开平仓一组算作一次完整交易\n")
            f.write("- 手续费计算：手续费率 × 成交金额（价格 × 合约乘数 × 交易量）\n")
                
        self.log(f"综合绩效报告已保存到: {performance_file}")
        return performance_file 

    def generate_report(self, results):
        """生成回测报告
        
        Args:
            results: 回测结果字典
            
        Returns:
            report_path: 报告文件路径
        """
        # 检查是否禁用可视化和报告
        import os
        if os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            self.log("报告生成已被禁用 (NO_VISUALIZATION=True)")
            return None
            
        # 检查是否禁用控制台日志
        if os.environ.get('NO_CONSOLE_LOG', '').lower() == 'true':
            # 完全静默模式，不生成任何输出
            return None
            
        # 创建日志目录
        import os
        from datetime import datetime
        
        log_dir = "backtest_logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 第一个数据源的交易标的，用于文件名
        first_key = next(iter(results))
        symbol = results[first_key].get('symbol', 'unknown')
        
        # 创建绩效报告文件路径
        performance_file = os.path.join(log_dir, f"performance_{symbol}_{timestamp}.txt")
        
        # 保存综合绩效报告
        return self.save_performance_report(results, performance_file) 