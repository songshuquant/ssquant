import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Union, Callable
import pandas as pd
import os

from ..api.strategy_api import create_strategy_api
from .backtest_logger import BacktestLogger
from .backtest_data import BacktestDataManager
from .backtest_results import BacktestResultCalculator
from .backtest_report import BacktestReportGenerator
from .html_report import HTMLReportGenerator

class MultiSourceBacktester:
    """
    多数据源回测器
    
    支持多品种、多周期回测，可以通过data[0]等方式访问不同的数据源
    """
    
    def __init__(self, base_config=None):
        """
        初始化多数据源回测器
        
        Args:
            base_config (dict, optional): 基础配置，包含所有品种共享的参数
        """
        # 默认基础配置
        self.default_base_config = {
            # API数据参数
            'use_api_data': True,
            'use_cache': True,
            'save_data': True,
            
            # 是否获取多个品种和周期的数据
            'fetch_multiple': True,
            
            # 是否对齐数据
            'align_data': True,
            'fill_method': 'ffill',
            
            # 调试模式
            'debug': False
        }
        
        # 使用传入的基础配置或默认配置
        self.base_config = base_config or self.default_base_config.copy()
        
        # 默认品种配置
        self.default_symbol_config = {
            'initial_capital': 100000.0,
            'commission': 0.0003,
            'margin_rate': 0.1,
            'contract_multiplier': 10
        }
        
        # 品种特定配置字典
        self.symbol_configs = {}
        
        # 品种和周期列表
        self.symbols_and_periods = []
        
        # 回测结果
        self.results = {}
        
        # 日志管理器
        debug_mode = self.base_config.get('debug', False)
        self.logger = BacktestLogger(debug_mode=debug_mode)
        
        # 数据管理器
        self.data_manager = BacktestDataManager(self.logger)
        
        # 结果计算器
        self.result_calculator = BacktestResultCalculator(self.logger)
        
        # 文本报告生成器
        self.report_generator = BacktestReportGenerator(self.logger)
        
        # HTML 报告生成器（替代 matplotlib 可视化）
        self.html_report_generator = HTMLReportGenerator(self.logger)
        
        # 参数优化模式标志
        self._in_optimization_mode = False
        
    def set_base_config(self, config):
        """
        设置基础配置
        
        Args:
            config (dict): 基础配置字典
        """
        self.base_config.update(config)
        # 更新日志管理器的debug_mode
        debug_mode = self.base_config.get('debug', False)
        self.logger.set_debug_mode(debug_mode)
        return self
        
    def add_symbol_config(self, symbol, config):
        """
        添加品种特定配置和周期
        
        Args:
            symbol (str): 品种代码，如'rb888'
            config (dict): 品种特定配置，可以包含以下额外参数：
                - periods (list): 周期配置列表，每个元素是一个字典，包含 'kline_period' 和 'adjust_type'
                  例如：[{'kline_period': '1h', 'adjust_type': '1'}, {'kline_period': 'D', 'adjust_type': '0'}]
                - kline_period (str): 单个K线周期，如'1h', 'D'（如果不提供periods）
                - adjust_type (str): 单个复权类型，'0'表示不复权，'1'表示后复权（如果不提供periods）
        """
        # 保存品种配置
        self.symbol_configs[symbol] = config.copy()
        
        # 处理周期信息
        if 'periods' in config:
            # 如果提供了多个周期配置
            for period_config in config['periods']:
                self.symbols_and_periods.append({
                    "symbol": symbol,
                    "kline_period": period_config['kline_period'],
                    "adjust_type": period_config.get('adjust_type', '1')
                })
        elif 'kline_period' in config:
            # 如果只提供了单个周期
            self.symbols_and_periods.append({
                "symbol": symbol,
                "kline_period": config['kline_period'],
                "adjust_type": config.get('adjust_type', '1')
            })
        
        return self
    
    def set_optimization_mode(self, enable=True):
        """设置是否处于参数优化模式
        
        Args:
            enable (bool): 是否启用优化模式
        
        Returns:
            self: 支持链式调用
        """
        self._in_optimization_mode = enable
        return self
    
    def run_backtest(self, strategy_func, strategy_params=None):
        """
        运行回测逻辑
        
        Args:
            strategy_func: 策略函数
            strategy_params: 策略参数，可选
        
        Returns:
            回测结果字典
        """
        # 确保日志管理器debug_mode与base_config一致
        debug_mode = self.base_config.get('debug', False)
        self.logger.set_debug_mode(debug_mode)
        
        # 检查是否跳过模块检查
        if not self.base_config.get('skip_module_check', False):
            # 添加调试代码，检查模块加载情况
            try:
                from ..api.debug_utils import print_debug_info
                self.logger.log_message("\n=== 检查模块加载情况 ===")
                print_debug_info()
                self.logger.log_message("=== 模块检查完成 ===\n")
            except ImportError as e:
                self.logger.log_message(f"导入调试模块出错: {str(e)}")
        
        # 检查是否有配置
        if not self.symbol_configs:
            self.logger.log_message("错误：没有指定任何品种配置，请先调用add_symbol_config添加配置")
            return {}
            
        # 准备日志文件
        self.logger.prepare_log_file(self.symbols_and_periods)
        
        # 记录回测开始
        self.logger.log_message("\n===================== 多数据源回测开始 =====================")
        
        # 检查是否已经预加载了数据
        if hasattr(self, '_data_preloaded') and self._data_preloaded:
            self.logger.log_message("使用预加载的数据进行回测...")
            data_dict = self._preloaded_data
            multi_data_source = self._preloaded_multi_data_source
        else:
            # 没有预加载数据，正常获取数据
            self.logger.log_message("获取回测数据...")
            # 获取数据
            data_dict = self.data_manager.fetch_data(self.symbols_and_periods, self.symbol_configs, self.base_config)
            
            # 创建多数据源（传入lookback_bars参数）
            lookback_bars = self.base_config.get('lookback_bars', 0)
            multi_data_source = self.data_manager.create_data_sources(
                self.symbols_and_periods, data_dict, lookback_bars=lookback_bars
            )
            
            # 对齐数据
            multi_data_source = self.data_manager.align_data(
                align=self.base_config.get('align_data', True),
                fill_method=self.base_config.get('fill_method', 'ffill')
            )
        
        # 运行回测
        self.logger.log_message("\n开始回测...")
        
        # 根据是否对齐数据决定遍历长度
        data_lengths = [len(ds.data) for ds in multi_data_source.data_sources if not ds.data.empty]
        is_aligned = self.base_config.get('align_data', True)
        
        if is_aligned:
            # 对齐模式：所有数据源长度相同，用min获取
            total_length = min(data_lengths)
            self.logger.log_message(f"回测数据长度: {total_length}条K线 (数据已对齐)")
        else:
            # 非对齐模式：使用最大长度，确保所有数据源都被完整遍历
            total_length = max(data_lengths)
            self.logger.log_message(f"回测数据长度: {total_length}条K线 (独立模式，各数据源: {data_lengths})")
        
        # 记录回测开始时间
        start_time = time.time()
        
        # 创建策略上下文
        context = {
            'data': multi_data_source,
            'log': self.logger.log_message,
            'params': strategy_params or {}
        }
        
        # 创建策略API
        api = create_strategy_api(context)
        
        # 运行策略初始化
        if hasattr(strategy_func, 'initialize'):
            self.logger.log_message("运行策略初始化...")
            strategy_func.initialize(api)
        
        # 创建进度条相关变量
        progress_last_update = time.time()
        progress_update_interval = 0.5  # 每0.5秒更新一次进度条
        progress_bar_length = 50  # 进度条长度
        
        # 逐条数据运行策略
        for i in range(total_length):
            # 更新所有数据源的当前索引
            for ds in multi_data_source.data_sources:
                if not ds.data.empty and i < len(ds.data):
                    ds.current_idx = i
                    row = ds.data.iloc[i]
                    # K线数据使用close，TICK数据使用LastPrice
                    if 'close' in row:
                        ds.current_price = row['close']
                    elif 'LastPrice' in row:
                        ds.current_price = row['LastPrice']
                    elif 'BidPrice1' in row and 'AskPrice1' in row:
                        ds.current_price = (row['BidPrice1'] + row['AskPrice1']) / 2
                    else:
                        raise KeyError("数据中未找到价格字段（close/LastPrice/BidPrice1+AskPrice1）")
                    ds.current_datetime = ds.data.index[i]
                    
                    # 处理待执行的订单
                    ds._process_pending_orders(log_callback=self.logger.log_message)
                # 非对齐模式下，数据源遍历完后保持最后状态（不更新current_idx）
            
            # 显示进度条（仅在非优化模式下显示）
            if not self._in_optimization_mode:
                current_time = time.time()
                if current_time - progress_last_update >= progress_update_interval:
                    progress_last_update = current_time
                    progress = float(i + 1) / total_length
                    filled_length = int(progress_bar_length * progress)
                    bar = '█' * filled_length + '-' * (progress_bar_length - filled_length)
                    
                    # 添加每分钟处理的K线数
                    elapsed = current_time - start_time
                    if elapsed > 0:
                        bars_per_minute = (i + 1) / elapsed * 60
                        estimated_time = (total_length - i - 1) * elapsed / (i + 1)
                        
                        # 清空当前行并显示进度条
                        print(f"\r回测进度: |{bar}| {progress*100:.1f}% ({i+1}/{total_length}) [{bars_per_minute:.0f}K线/分钟] [剩余: {estimated_time:.1f}秒]", end='', flush=True)
            
            # 调试信息（仅在debug=True时显示详细日志）
            if debug_mode and i % 100 == 0:
                self.logger.log_message(f"处理第 {i}/{total_length} 条数据")
                for j, ds in enumerate(multi_data_source.data_sources):
                    if not ds.data.empty and i < len(ds.data):
                        self.logger.log_message(f"数据源 #{j}: 时间={ds.current_datetime}, 价格={ds.current_price:.2f}, 持仓={ds.current_pos}")
            
            # 运行策略
            strategy_func(api)
        
        # 完成进度条（仅在非优化模式下显示）
        if not self._in_optimization_mode:
            print(f"\r回测进度: |{'█' * progress_bar_length}| 100.0% ({total_length}/{total_length}) [完成]", flush=True)
            print()  # 添加一个换行
        
        # 记录回测结束时间
        end_time = time.time()
        elapsed_time = end_time - start_time
        self.logger.log_message(f"回测完成，耗时: {elapsed_time:.2f}秒")
        
        # 计算回测结果
        results = self.result_calculator.calculate_results(multi_data_source, self.symbol_configs)
        self.results = results
        
        # 将multi_data_source保存到结果中，以便后续使用
        self._last_multi_data_source = multi_data_source
        
        return results
    
    def run(self, strategy, initialize=None, strategy_params=None, silent_mode=False):
        """
        运行回测
        
        Args:
            strategy: 策略函数
            initialize: 初始化函数，可选
            strategy_params: 策略参数，可选
            silent_mode: 是否静默模式（不生成图表和报告），用于参数优化
            
        Returns:
            回测结果字典
        """
        # 检查环境变量是否禁用可视化和日志输出
        no_visualization = os.environ.get('NO_VISUALIZATION', '').lower() == 'true'
        no_console_log = os.environ.get('NO_CONSOLE_LOG', '').lower() == 'true'
        
        # 如果设置了环境变量或者是静默模式，则设置为优化模式
        if no_visualization or no_console_log or silent_mode:
            self._in_optimization_mode = True
        else:
            self._in_optimization_mode = False
        
        # 运行回测逻辑
        results = self.run_backtest(strategy, strategy_params)
        
        # 计算结果指标
        self.result_calculator.calculate_performance(results)
        
        # 获取multi_data_source，用于绘制图表
        multi_data_source = getattr(self, '_last_multi_data_source', None)
        
        # 所有需要显示的文件路径
        chart_paths = []
        report_path = ""
        performance_file = None
        
        # 只有在非优化模式下，才生成图表和报告
        if not self._in_optimization_mode:
            # 获取性能报告文件路径
            performance_file = self.logger.get_performance_file()
            
            # 保存文本绩效报告
            if performance_file:
                self.report_generator.save_performance_report(results, performance_file)
                report_path = performance_file
                results['report_path'] = report_path
            
            # 生成 HTML 交互式报告 - 只有在未禁用可视化时
            if not no_visualization:
                html_report_path = self.html_report_generator.generate_report(
                    results, multi_data_source
                )
                results['html_report_path'] = html_report_path
                results['chart_paths'] = [html_report_path] if html_report_path else []
            else:
                results['chart_paths'] = []
                results['html_report_path'] = None
            
            # 显示结果摘要 - 只有在未禁用控制台日志时
            if not no_console_log:
                self.show_summary(results)
                
            # 即使在静默模式下也显示文件保存位置
            if performance_file:
                print(f"文本报告已保存至: {os.path.abspath(performance_file)}")
            
            if results.get('html_report_path'):
                print(f"HTML报告已保存至: {os.path.abspath(results['html_report_path'])}")
        else:
            # 在优化模式下，不输出任何图表或报告
            results['chart_paths'] = []
            results['report_path'] = ""
        
        return results
        
    def show_summary(self, results):
        """
        显示回测结果摘要
        
        Args:
            results: 回测结果字典
        """
        performance = results.get('performance', {})
        
        # 输出摘要信息
        self.logger.log_message("\n-------- 回测结果摘要 --------")
        if performance:
            self.logger.log_message(f"总收益率: {performance.get('total_return', 0):.2f}%")
            self.logger.log_message(f"年化收益率: {performance.get('annual_return', 0):.2f}%")
            self.logger.log_message(f"最大回撤: {performance.get('max_drawdown', 0):.2f}")
            self.logger.log_message(f"夏普比率: {performance.get('sharpe_ratio', 0):.2f}")
            self.logger.log_message(f"胜率: {performance.get('win_rate', 0):.2f}%")
            
            # 交易统计
            trade_stats = performance.get('trade_stats', {})
            if trade_stats:
                self.logger.log_message(f"总交易次数: {trade_stats.get('total_trades', 0)}")
                self.logger.log_message(f"盈利交易: {trade_stats.get('winning_trades', 0)}")
                self.logger.log_message(f"亏损交易: {trade_stats.get('losing_trades', 0)}")
                
        self.logger.log_message("----------------------------")
    
    def show_results(self, results, multi_data_source=None):
        """
        显示回测结果并生成图表
        
        Args:
            results: 回测结果字典
            multi_data_source: 多数据源实例（用于生成报告）
        
        Returns:
            回测结果字典(可能包含新生成的图表路径)
        """
        # 检查环境变量是否禁用可视化和日志输出
        no_visualization = os.environ.get('NO_VISUALIZATION', '').lower() == 'true'
        no_console_log = os.environ.get('NO_CONSOLE_LOG', '').lower() == 'true'
        
        # 计算结果指标(如果尚未计算)
        if 'performance' not in results:
            self.result_calculator.calculate_performance(results)
        
        # 只有在NO_VISUALIZATION不为True时，才生成 HTML 报告
        if not no_visualization:
            # 生成 HTML 交互式报告
            html_report_path = self.html_report_generator.generate_report(results, multi_data_source)
            results['html_report_path'] = html_report_path
            results['chart_paths'] = [html_report_path] if html_report_path else []
        else:
            results['chart_paths'] = []
            results['html_report_path'] = None
        
        # 只有在NO_CONSOLE_LOG不为True时，才生成报告
        if not no_console_log:
            # 生成回测报告
            report_path = self.report_generator.generate_report(results)
            results['report_path'] = report_path
            
            # 显示结果摘要
            self.show_summary(results)
        else:
            results['report_path'] = ""
            
        return results
    
    def get_results(self):
        """获取回测结果"""
        return self.results
    
    def get_summary(self):
        """获取回测结果摘要"""
        return self.result_calculator.get_summary(self.results)
    
    def preload_data(self):
        """
        预加载所有数据，避免在参数优化过程中重复加载
        
        Returns:
            预加载的数据字典和多数据源对象
        """
        # 如果已经预加载过，直接返回
        if hasattr(self, '_preloaded_data') and self._preloaded_data:
            self.logger.log_message("使用已预加载的数据...")
            return self._preloaded_data, self._preloaded_multi_data_source
            
        # 记录预加载开始
        self.logger.log_message("\n===================== 预加载数据开始 =====================")
        
        # 检查是否跳过模块检查
        if self.base_config.get('skip_module_check', False):
            self.logger.log_message("跳过模块检查...")
        else:
            # 添加调试代码，检查模块加载情况
            try:
                from ..api.debug_utils import print_debug_info
                self.logger.log_message("\n=== 检查模块加载情况 ===")
                print_debug_info()
                self.logger.log_message("=== 模块检查完成 ===\n")
            except ImportError as e:
                self.logger.log_message(f"导入调试模块出错: {str(e)}")
        
        # 检查是否有配置
        if not self.symbol_configs:
            self.logger.log_message("错误：没有指定任何品种配置，请先调用add_symbol_config添加配置")
            return None, None
            
        # 准备日志文件
        self.logger.prepare_log_file(self.symbols_and_periods)
        
        # 记录数据预加载开始
        self.logger.log_message("开始预加载数据...")
        
        # 获取数据
        data_dict = self.data_manager.fetch_data(self.symbols_and_periods, self.symbol_configs, self.base_config)
        
        # 创建多数据源（传入lookback_bars参数）
        lookback_bars = self.base_config.get('lookback_bars', 0)
        multi_data_source = self.data_manager.create_data_sources(
            self.symbols_and_periods, data_dict, lookback_bars=lookback_bars
        )
        
        # 对齐数据
        multi_data_source = self.data_manager.align_data(
            align=self.base_config.get('align_data', True),
            fill_method=self.base_config.get('fill_method', 'ffill')
        )
        
        # 如果没有数据源，无法预加载
        if len(multi_data_source) == 0:
            self.logger.log_message("没有获取到任何数据，无法预加载")
            return None, None
        
        # 根据是否对齐数据决定遍历长度
        data_lengths = [len(ds.data) for ds in multi_data_source.data_sources if not ds.data.empty]
        is_aligned = self.base_config.get('align_data', True)
        
        if is_aligned:
            total_length = min(data_lengths)
            self.logger.log_message(f"预加载数据长度: {total_length}条K线 (数据已对齐)")
        else:
            total_length = max(data_lengths)
            self.logger.log_message(f"预加载数据长度: {total_length}条K线 (独立模式，各数据源: {data_lengths})")
        
        # 保存预加载的数据
        self._preloaded_data = data_dict
        self._preloaded_multi_data_source = multi_data_source
        self._data_preloaded = True
        
        self.logger.log_message("数据预加载完成！后续优化将直接使用预加载数据，大幅提高效率")
        self.logger.log_message("===================== 预加载数据完成 =====================\n")
        
        return data_dict, multi_data_source
    
    def optimize_parameters(self, strategy, param_grid, method='grid', initialize=None, 
                          optimization_metric='sharpe_ratio', higher_is_better=True, strategy_name=None, 
                          reuse_data=True, **kwargs):
        """运行参数优化
        
        Args:
            strategy: 策略函数
            param_grid: 参数网格或参数空间
            method: 优化方法，支持'grid'(网格搜索), 'random'(随机搜索), 'bayesian'(贝叶斯优化)
            initialize: 初始化函数
            optimization_metric: 优化指标，如'sharpe_ratio', 'total_return'等
            higher_is_better: 是否越高越好
            strategy_name: 策略名称，用于保存结果
            reuse_data: 是否复用预加载的数据，大幅提高优化效率
            **kwargs: 其他参数，将传递给具体的优化方法
            
        Returns:
            (最优参数, 最优参数的回测结果)
        """
        try:
            # 动态导入优化器模块
            from .parameter_optimizer import ParameterOptimizer
        except ImportError:
            self.logger.log_message("错误: 参数优化模块未安装。请确保backtest/parameter_optimizer.py文件存在。")
            return None, None
        
        # 如果启用数据复用，先预加载数据
        if reuse_data:
            self.logger.log_message("启用数据复用，开始预加载数据...")
            self.preload_data()
            
        # 创建优化器
        optimizer = ParameterOptimizer(
            backtester=self,
            strategy=strategy,
            initialize=initialize,
            logger=self.logger.log_message,
            strategy_name=strategy_name
        )
        
        # 设置优化指标
        optimizer.set_optimization_metric(optimization_metric, higher_is_better)
        
        # 根据方法运行优化
        if method == 'grid':
            return optimizer.grid_search(param_grid, **kwargs)
        elif method == 'random':
            return optimizer.random_search(param_grid, **kwargs)
        elif method == 'bayesian':
            return optimizer.bayesian_optimization(param_grid, **kwargs)
        else:
            self.logger.log_message(f"错误: 不支持的优化方法 '{method}'。支持的方法: grid, random, bayesian")
            return None, None
