import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from datetime import datetime
from PIL import Image
import matplotlib.image as mpimg
from scipy.interpolate import make_interp_spline, interp1d

# 设置matplotlib支持中文显示
matplotlib.use('Agg')  # 使用Agg后端
# 设置中文字体
import platform
system = platform.system()
if system == 'Windows':
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS']  # 中文字体设置
elif system == 'Linux':
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'WenQuanYi Micro Hei', 'DejaVu Sans', 'Arial Unicode MS']
elif system == 'Darwin':  # macOS
    plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'STHeiti', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False  # 解决保存图像负号'-'显示为方块的问题
plt.rcParams['font.family'] = 'sans-serif'  # 使用上面设置的sans-serif字体

class BacktestVisualizer:
    """回测可视化工具，负责绘制各种回测图表"""
    
    def __init__(self, logger=None):
        """初始化可视化工具
        
        Args:
            logger: 日志管理器实例
        """
        self.logger = logger
        self.logo_array = self._load_logo()
    
    def log(self, message):
        """记录日志
        
        Args:
            message: 日志消息
        """
        if self.logger:
            self.logger.log_message(message)
        else:
            print(message)
    
    def _load_logo(self):
        """加载Logo图片"""
        logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "squirrel_quant_logo.png")
        if os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path)
                # 调整Logo大小，增加宽度，保持原始比例
                logo_width = 400  # 缩小宽度
                logo_height = 200  # 缩小高度
                # 使用 LANCZOS 重采样（PIL 10.0.0+ 使用 Resampling.LANCZOS）
                try:
                    from PIL.Image import Resampling
                    logo_img = logo_img.resize((logo_width, logo_height), Resampling.LANCZOS)
                except (ImportError, AttributeError):
                    # 兼容旧版本 PIL
                    try:
                        logo_img = logo_img.resize((logo_width, logo_height), 3)  # 3 = LANCZOS/ANTIALIAS
                    except:
                        logo_img = logo_img.resize((logo_width, logo_height))
                logo_array = np.array(logo_img)
                self.log("成功加载Logo图片")
                return logo_array
            except Exception as e:
                self.log(f"加载Logo图片失败: {e}")
                return None
        else:
            self.log(f"Logo图片不存在: {logo_path}")
            return None
    
    def _add_logo_watermark(self, fig, gs):
        if self.logo_array is not None:
            try:
                logo_ax = fig.add_subplot(gs[0])  
                logo_ax.imshow(self.logo_array)
                logo_ax.axis('off')  
            except Exception as e:
                self.log(f"lg: {e}")
    
    def generate_charts(self, results):
        """生成回测图表
        
        Args:
            results: 回测结果字典
            
        Returns:
            image_paths: 图表文件路径列表
        """
        # 检查是否禁用可视化
        if os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            self.log("图表生成已被禁用 (NO_VISUALIZATION=True)")
            return []
            
        # 检查是否禁用控制台日志
        if os.environ.get('NO_CONSOLE_LOG', '').lower() == 'true':
            # 完全静默模式，不生成任何输出
            return []
            
        # 检查是否有结果可以可视化
        if not results:
            self.log("没有可用的回测结果，无法生成图表")
            return []
            
        # 创建结果目录
        result_dir = "backtest_results"
        if not os.path.exists(result_dir):
            os.makedirs(result_dir)
            
        # 当前时间戳，用于文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 记录图表路径
        chart_paths = []
        
        try:
            # 生成单个标的的K线和交易图
            for key, result in results.items():
                if not isinstance(result, dict) or 'trades' not in result or not result['trades']:
                    continue
                    
                # 创建图表文件名
                chart_filename = f"{key}_chart_{timestamp}.png"
                chart_path = os.path.join(result_dir, chart_filename)
                
                # 生成K线和交易图
                self._generate_price_chart(result, chart_path)
                chart_paths.append(chart_path)
                
            # 注释掉组合权益曲线图生成逻辑，避免调用不存在的方法
            # if any('equity_curve' in result for result in results.values() if isinstance(result, dict)):
            #     equity_chart_filename = f"combined_equity_chart_{timestamp}.png"
            #     equity_chart_path = os.path.join(result_dir, equity_chart_filename)
            #     
            #     self._generate_combined_equity_chart(results, equity_chart_path)
            #     chart_paths.append(equity_chart_path)
                
            # 注释掉回撤图生成逻辑，避免调用不存在的方法
            # drawdown_chart_filename = f"drawdown_chart_{timestamp}.png"
            # drawdown_chart_path = os.path.join(result_dir, drawdown_chart_filename)
            # 
            # self._generate_drawdown_chart(results, drawdown_chart_path)
            # chart_paths.append(drawdown_chart_path)
                
        except Exception as e:
            self.log(f"生成图表时出错: {str(e)}")
            
        return chart_paths
        
    def plot_results(self, multi_data_source, results):
        """绘制回测结果图表
        
        Args:
            multi_data_source: 多数据源实例
            results: 回测结果字典
            
        Returns:
            image_paths: 图表文件路径列表
        """
        # 检查是否禁用可视化
        if os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            self.log("图表生成已被禁用 (NO_VISUALIZATION=True)")
            return []
        
        # 检查是否禁用控制台日志
        if os.environ.get('NO_CONSOLE_LOG', '').lower() == 'true':
            # 完全静默模式，不生成任何输出
            return []
            
        # 创建结果目录
        result_dir = "backtest_results"
        if not os.path.exists(result_dir):
            os.makedirs(result_dir)
        
        # 添加调试信息，跟踪进度
        self.log("\n=== 开始绘制回测图表 ===")
        
        image_paths = []
        
        # 遍历所有数据源，绘制单个品种的回测结果图表
        for i, ds in enumerate(multi_data_source.data_sources):
            # 获取交易记录
            trades = ds.trades
            
            if not trades:
                self.log(f"数据源 #{i} ({ds.symbol} {ds.kline_period}) 没有交易记录")
                continue
            
            self.log(f"绘制数据源 #{i} ({ds.symbol} {ds.kline_period}) 的回测图表")
            
            # 创建图表 - 现在有3个子图：价格图、收益曲线图和回撤图
            # 增加整体高度为24，宽度为22，为顶部LOGO留出足够空间
            fig = plt.figure(figsize=(22, 24))
            
            # 创建网格布局，为顶部LOGO留出空间
            gs = fig.add_gridspec(4, 1, height_ratios=[0.8, 3.5, 2.5, 1.2])
            
            # 创建三个子图，保持原有比例
            ax1 = fig.add_subplot(gs[1])  # 价格图
            ax2 = fig.add_subplot(gs[2])  # 收益曲线图
            ax3 = fig.add_subplot(gs[3])  # 回撤图
            
            # 获取实际有数据的交易日期和价格
            df = ds.data.copy()
            
            # 获取所有实际交易日期
            trading_dates = df.index.tolist()
            
            # 创建X轴位置（使用整数索引而不是日期）
            x_positions = list(range(len(trading_dates)))
            
            # 判断是K线数据还是TICK数据
            is_kline_data = all(col in df.columns for col in ['open', 'high', 'low', 'close'])
            
            if is_kline_data:
                # ========== K线数据：绘制蜡烛图 ==========
                opens = df['open'].values
                highs = df['high'].values
                lows = df['low'].values
                closes = df['close'].values
                prices = closes  # 用于后续Y轴范围计算
                
                # 绘制K线（蜡烛图）
                width = 0.6  # K线宽度
                width2 = 0.1  # 影线宽度
                
                for i in range(len(x_positions)):
                    x = x_positions[i]
                    o, h, l, c = opens[i], highs[i], lows[i], closes[i]
                    
                    # 根据涨跌确定颜色（中国习惯：涨红跌绿）
                    if c >= o:
                        color = 'red'
                        body_bottom = o
                        body_height = c - o
                    else:
                        color = 'green'
                        body_bottom = c
                        body_height = o - c
                    
                    # 绘制影线（上下影线）
                    ax1.plot([x, x], [l, h], color=color, linewidth=width2 * 10, zorder=1)
                    
                    # 绘制实体
                    if body_height > 0:
                        rect = plt.Rectangle((x - width/2, body_bottom), width, body_height,
                                           facecolor=color, edgecolor=color, zorder=2)
                        ax1.add_patch(rect)
                    else:
                        # 十字星：开盘=收盘
                        ax1.plot([x - width/2, x + width/2], [o, o], color=color, linewidth=1, zorder=2)
            else:
                # ========== TICK数据：绘制价格曲线 ==========
                if 'close' in df.columns:
                    prices = df['close'].values
                elif 'LastPrice' in df.columns:
                    prices = df['LastPrice'].values
                elif 'BidPrice1' in df.columns and 'AskPrice1' in df.columns:
                    prices = ((df['BidPrice1'] + df['AskPrice1']) / 2).values
                else:
                    raise KeyError("数据中未找到价格字段（close/LastPrice/BidPrice1+AskPrice1）")
                
                # 绘制价格曲线
                if len(x_positions) > 3:
                    try:
                        x_smooth = np.linspace(min(x_positions), max(x_positions), len(x_positions) * 3)
                        if len(x_positions) > 10:
                            spline = make_interp_spline(x_positions, prices, k=3)
                            prices_smooth = spline(x_smooth)
                        else:
                            interp_func = interp1d(x_positions, prices, kind='linear')
                            prices_smooth = interp_func(x_smooth)
                        ax1.plot(x_smooth, prices_smooth, label='价格', color='black', linewidth=1, alpha=0.8, zorder=1)
                    except Exception as e:
                        self.log(f"价格曲线平滑处理失败，使用原始绘图: {e}")
                        ax1.plot(x_positions, prices, label='价格', color='black', linewidth=1, alpha=0.8, zorder=1)
                else:
                    ax1.plot(x_positions, prices, label='价格', color='black', linewidth=1, alpha=0.8, zorder=1)
            
            # 绘制交易点，设置较高的zorder值，确保它们显示在价格曲线之上
            for trade in trades:
                # 找到交易日期在trading_dates中的位置
                try:
                    date_idx = trading_dates.index(trade['datetime'])
                    
                    if trade['action'] == '开多':
                        ax1.scatter(date_idx, trade['price'], color='red', marker='^', s=100, zorder=5)
                    elif trade['action'] == '平多':
                        ax1.scatter(date_idx, trade['price'], color='blue', marker='v', s=100, zorder=5)
                    elif trade['action'] == '开空':
                        ax1.scatter(date_idx, trade['price'], color='green', marker='v', s=100, zorder=5)
                    elif trade['action'] == '平空':
                        ax1.scatter(date_idx, trade['price'], color='purple', marker='^', s=100, zorder=5)
                except ValueError:
                    # 如果交易日期不在trading_dates中，则跳过
                    continue
            
            # 添加图例
            from matplotlib.lines import Line2D
            custom_lines = [
                Line2D([0], [0], marker='^', color='red', markersize=10, linestyle=''),
                Line2D([0], [0], marker='v', color='blue', markersize=10, linestyle=''),
                Line2D([0], [0], marker='v', color='green', markersize=10, linestyle=''),
                Line2D([0], [0], marker='^', color='purple', markersize=10, linestyle='')
            ]
            ax1.legend(custom_lines, ['开多', '平多', '开空', '平空'], loc='upper right')
            
            # 设置标题
            ax1.set_title(f"{ds.symbol} {ds.kline_period} {'不复权' if ds.adjust_type == '0' else '后复权'} 回测结果", fontsize=16, fontproperties=plt.rcParams['font.sans-serif'][0])
            ax1.grid(True)
            
            # 动态调整价格图的Y轴范围
            if is_kline_data:
                # K线图使用最高价和最低价
                min_price = min(lows)
                max_price = max(highs)
            else:
                min_price = min(prices)
                max_price = max(prices)
            
            if max_price > min_price:
                price_range = max_price - min_price
                # 添加边距使图表更美观
                padding = price_range * 0.05  # 5%的边距
                ax1.set_ylim(min_price - padding, max_price + padding)
            
            # 获取计算好的权益曲线
            if 'equity_curve' in results.get(f"{ds.symbol}_{ds.kline_period}_{'不复权' if ds.adjust_type == '0' else '后复权'}", {}):
                equity_curve = results[f"{ds.symbol}_{ds.kline_period}_{'不复权' if ds.adjust_type == '0' else '后复权'}"]["equity_curve"]
            else:
                # 如果没有计算好的权益曲线，则重新计算
                equity_curve = pd.Series(0.0, index=ds.data.index)
                for trade in trades:
                    if 'net_profit' in trade and trade['net_profit'] != 0:
                        equity_curve[trade['datetime']] += trade['net_profit']
                
                # 累积求和并添加初始资金
                initial_capital = results.get(f"{ds.symbol}_{ds.kline_period}_{'不复权' if ds.adjust_type == '0' else '后复权'}", {}).get('initial_capital', 100000.0)
                equity_curve = initial_capital + equity_curve.cumsum()
            
            # 绘制收益曲线（使用整数索引）
            equity_values = [equity_curve[date] for date in trading_dates]
            
            # 应用曲线平滑处理，使曲线更加平滑
            if len(x_positions) > 3:  # 确保有足够的点进行插值
                try:
                    # 创建更多插值点以获得更平滑的曲线
                    x_smooth = np.linspace(min(x_positions), max(x_positions), len(x_positions) * 3)
                    
                    # 使用三次样条插值（适合数据量较多的曲线）
                    if len(x_positions) > 10:
                        spline = make_interp_spline(x_positions, equity_values, k=3)
                        equity_smooth = spline(x_smooth)
                    else:
                        # 对于数据点较少的情况，使用线性插值
                        interp_func = interp1d(x_positions, equity_values, kind='linear')
                        equity_smooth = interp_func(x_smooth)
                    
                    # 绘制平滑后的曲线
                    ax2.plot(x_smooth, equity_smooth, label='收益曲线', color='blue', linewidth=2)
                except Exception as e:
                    # 如果插值失败，回退到原始绘图方式
                    self.log(f"曲线平滑处理失败，使用原始绘图: {e}")
                    ax2.plot(x_positions, equity_values, label='收益曲线', color='blue', linewidth=2)
            else:
                # 数据点太少，使用原始绘图
                ax2.plot(x_positions, equity_values, label='收益曲线', color='blue', linewidth=2)
            
            ax2.set_title('收益曲线', fontsize=16, fontproperties=plt.rcParams['font.sans-serif'][0])
            ax2.legend(fontsize=12, prop={'family': plt.rcParams['font.sans-serif'][0]})
            ax2.grid(True)
            
            # 动态调整收益曲线图的Y轴范围
            if equity_values:
                min_equity = min(equity_values)
                max_equity = max(equity_values)
                equity_range = max_equity - min_equity
                
                # 使用相对范围，避免小范围时图形过度放大
                min_range_pct = 0.02  # 最小范围为2%
                relative_range = equity_range / max_equity if max_equity > 0 else 0
                
                if relative_range < min_range_pct:
                    # 如果实际范围小于最小范围，则使用中心点扩展
                    center = (min_equity + max_equity) / 2
                    min_equity = center * (1 - min_range_pct / 2)
                    max_equity = center * (1 + min_range_pct / 2)
                else:
                    # 添加边距使图表更美观
                    padding = equity_range * 0.1  # 10%的边距
                    min_equity = min_equity - padding
                    max_equity = max_equity + padding
                
                ax2.set_ylim(min_equity, max_equity)
            
            # 计算并绘制回撤曲线
            if equity_values:
                # 计算累计最大值
                cummax_values = []
                max_value = float('-inf')
                
                # 正确计算累计最大值
                for value in equity_values:
                    if value > max_value:
                        max_value = value
                    cummax_values.append(max_value)
                
                # 计算回撤
                drawdown = []
                drawdown_pct = []
                
                for i in range(len(equity_values)):
                    # 避免除以零或负数
                    if cummax_values[i] > 0:
                        dd = cummax_values[i] - equity_values[i]
                        dd_pct = (dd / cummax_values[i]) * 100
                        drawdown.append(dd)
                        drawdown_pct.append(dd_pct)
                    else:
                        drawdown.append(0)
                        drawdown_pct.append(0)
                
                # 绘制回撤曲线
                ax3.fill_between(x_positions, 0, drawdown_pct, color='red', alpha=0.3)
                ax3.set_title('回撤百分比', fontsize=16, fontproperties=plt.rcParams['font.sans-serif'][0])
                ax3.set_ylabel('回撤 (%)', fontsize=14, fontproperties=plt.rcParams['font.sans-serif'][0])
                ax3.grid(True)
                
                # 设置回撤图的Y轴范围，确保0点在图表顶部
                max_drawdown = max(drawdown_pct) if drawdown_pct else 0
                # 添加一些边距
                padding = max(max_drawdown * 0.1, 1)  # 至少1%的边距
                ax3.set_ylim(max_drawdown + padding, 0)
            
            # 设置X轴，只显示部分日期标签，避免拥挤
            # 计算适当的刻度间隔，使标签不会过度拥挤
            num_dates = len(trading_dates)
            if num_dates <= 10:
                tick_step = 1
            elif num_dates <= 20:
                tick_step = 2
            elif num_dates <= 50:
                tick_step = 5
            elif num_dates <= 100:
                tick_step = 10
            else:
                tick_step = num_dates // 10  # 大约10个刻度
            
            # 创建刻度位置列表
            tick_indices = list(range(0, num_dates, tick_step))
            if num_dates - 1 not in tick_indices:
                tick_indices.append(num_dates - 1)  # 确保最后一个日期也显示
            
            ax1.set_xticks(tick_indices)
            ax1.set_xticklabels([trading_dates[i].strftime('%Y-%m-%d') for i in tick_indices], rotation=45, fontsize=12)
            ax1.tick_params(axis='y', labelsize=12)
            ax2.set_xticks(tick_indices)
            ax2.set_xticklabels([trading_dates[i].strftime('%Y-%m-%d') for i in tick_indices], rotation=45, fontsize=12)
            ax2.tick_params(axis='y', labelsize=12)
            ax3.set_xticks(tick_indices)
            ax3.set_xticklabels([trading_dates[i].strftime('%Y-%m-%d') for i in tick_indices], rotation=45, fontsize=12)
            ax3.tick_params(axis='y', labelsize=12)
            
            # 在每个子图左下角添加网站标记
            ax1.text(0.01, 0.02, 'by quant789.com', transform=ax1.transAxes, fontsize=20, color='gray')
            ax2.text(0.01, 0.02, 'by quant789.com', transform=ax2.transAxes, fontsize=20, color='gray')
            ax3.text(0.01, 0.02, 'by quant789.com', transform=ax3.transAxes, fontsize=20, color='gray')
            
            # 调整布局
            plt.tight_layout()
            
            # 添加Logo水印
            self._add_logo_watermark(fig, gs)
            
            # 保存图表
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = os.path.join(result_dir, f"{ds.symbol}_{ds.kline_period}_{'不复权' if ds.adjust_type == '0' else '后复权'}_backtest_chart_{timestamp}.png")
            plt.savefig(image_path)
            plt.close()
            
            image_paths.append(image_path)
            self.log(f"回测图表已保存到: {image_path}")
        
        # 创建综合收益图表
        self.log("\n=== 开始创建综合收益图表 ===")
        
        # 获取所有数据源的收益曲线
        all_equity_curves = []
        all_symbols = []
        
        for i, ds in enumerate(multi_data_source.data_sources):
            key = f"{ds.symbol}_{ds.kline_period}_{'不复权' if ds.adjust_type == '0' else '后复权'}"
            if key in results and 'equity_curve' in results[key]:
                all_equity_curves.append(results[key]['equity_curve'])
                all_symbols.append(f"{ds.symbol}_{ds.kline_period}")
                self.log(f"添加数据源 #{i} 的权益曲线，长度: {len(results[key]['equity_curve'])}")
        
        self.log(f"共找到 {len(all_equity_curves)} 个权益曲线")
        
        # 绘制综合收益图表（即使只有一个数据源）
        if all_equity_curves:
            try:
                # 找到共同的日期范围
                # 如果只有一个数据源，直接使用它的所有日期
                if len(all_equity_curves) == 1:
                    common_dates = list(all_equity_curves[0].index)
                    self.log(f"只有一个数据源，使用其所有日期: {len(common_dates)} 个日期")
                else:
                    # 找到多个数据源的共同日期
                    common_dates = set(all_equity_curves[0].index)
                    for curve in all_equity_curves[1:]:
                        common_dates = common_dates.intersection(set(curve.index))
                    common_dates = sorted(list(common_dates))
                    self.log(f"多个数据源的共同日期: {len(common_dates)} 个日期")
                
                if not common_dates:
                    self.log("没有找到共同日期，使用第一个权益曲线的全部日期")
                    common_dates = sorted(list(all_equity_curves[0].index))
                
                self.log(f"共同日期范围: {common_dates[0]} 到 {common_dates[-1]}, 共 {len(common_dates)} 个日期")
                
                # 创建综合收益图表
                self.log("创建综合收益图表...")
                fig = plt.figure(figsize=(22, 22))
                
                # 创建网格布局，为顶部LOGO留出空间
                gs = fig.add_gridspec(3, 1, height_ratios=[0.8, 3.5, 1.2])
                
                # 创建两个子图
                ax1 = fig.add_subplot(gs[1])  # 收益曲线图
                ax2 = fig.add_subplot(gs[2])  # 回撤图
                
                # 添加Logo水印
                self._add_logo_watermark(fig, gs)
                
                # 创建X轴位置
                x_positions = list(range(len(common_dates)))
                
                # 获取各品种的初始资金
                initial_capitals = {}
                for i, ds in enumerate(multi_data_source.data_sources):
                    key = f"{ds.symbol}_{ds.kline_period}_{'不复权' if ds.adjust_type == '0' else '后复权'}"
                    if key in results:
                        initial_capitals[ds.symbol] = results[key].get('initial_capital', 100000.0)
                
                # 计算总初始资金
                total_initial_capital = sum(initial_capitals.values())
                
                # 绘制各个品种的收益曲线
                for i, equity_curve in enumerate(all_equity_curves):
                    symbol = all_symbols[i].split('_')[0]
                    initial_capital = initial_capitals.get(symbol, 100000.0)
                    
                    # 计算每个日期的净值
                    equity_values = []
                    for date in common_dates:
                        if date in equity_curve.index:
                            equity_values.append(equity_curve[date] / initial_capital)
                        else:
                            equity_values.append(1.0)
                    
                    # 应用曲线平滑处理
                    if len(x_positions) > 3:
                        try:
                            x_smooth = np.linspace(min(x_positions), max(x_positions), len(x_positions) * 3)
                            if len(x_positions) > 10:
                                spline = make_interp_spline(x_positions, equity_values, k=3)
                                equity_smooth = spline(x_smooth)
                            else:
                                interp_func = interp1d(x_positions, equity_values, kind='linear')
                                equity_smooth = interp_func(x_smooth)
                            ax1.plot(x_smooth, equity_smooth, label=all_symbols[i])
                        except Exception as e:
                            self.log(f"{all_symbols[i]}曲线平滑处理失败: {e}")
                            ax1.plot(x_positions, equity_values, label=all_symbols[i])
                    else:
                        ax1.plot(x_positions, equity_values, label=all_symbols[i])
                
                # 计算综合收益曲线
                combined_equity = []
                for date in common_dates:
                    curve_net_values = []
                    for j, curve in enumerate(all_equity_curves):
                        symbol = all_symbols[j].split('_')[0]
                        initial_capital = initial_capitals.get(symbol, 100000.0)
                        if date in curve.index:
                            curve_net_values.append(curve[date] / initial_capital)
                        else:
                            curve_net_values.append(1.0)
                    
                    # 计算所有曲线的平均净值
                    if curve_net_values:
                        avg_net_value = sum(curve_net_values) / len(curve_net_values)
                    else:
                        avg_net_value = 1.0
                    
                    combined_equity.append(avg_net_value)
                
                # 绘制综合收益曲线
                label = '综合净值' if len(all_equity_curves) > 1 else '策略净值'
                
                # 应用曲线平滑处理
                if len(x_positions) > 3:
                    try:
                        x_smooth = np.linspace(min(x_positions), max(x_positions), len(x_positions) * 3)
                        if len(x_positions) > 10:
                            spline = make_interp_spline(x_positions, combined_equity, k=3)
                            equity_smooth = spline(x_smooth)
                        else:
                            interp_func = interp1d(x_positions, combined_equity, kind='linear')
                            equity_smooth = interp_func(x_smooth)
                        ax1.plot(x_smooth, equity_smooth, label=label, linewidth=2, color='black')
                    except Exception as e:
                        self.log(f"综合收益曲线平滑处理失败: {e}")
                        ax1.plot(x_positions, combined_equity, label=label, linewidth=2, color='black')
                else:
                    ax1.plot(x_positions, combined_equity, label=label, linewidth=2, color='black')
                
                ax1.set_title('综合收益图表', fontsize=16, fontproperties=plt.rcParams['font.sans-serif'][0])
                ax1.set_ylabel('净值', fontsize=14, fontproperties=plt.rcParams['font.sans-serif'][0])
                ax1.legend(fontsize=12, prop={'family': plt.rcParams['font.sans-serif'][0]})
                ax1.grid(True)
                
                # 在收益曲线图左下角添加网站标记
                ax1.text(0.01, 0.02, 'by quant789.com', transform=ax1.transAxes, fontsize=20, color='gray')
                
                # 计算并绘制回撤曲线
                if combined_equity:
                    # 计算累计最大值
                    cummax_values = []
                    max_value = float('-inf')
                    
                    for value in combined_equity:
                        if value > max_value:
                            max_value = value
                        cummax_values.append(max_value)
                    
                    # 计算回撤
                    drawdown_pct = []
                    for i in range(len(combined_equity)):
                        if cummax_values[i] > 0:
                            dd_pct = ((cummax_values[i] - combined_equity[i]) / cummax_values[i]) * 100
                            drawdown_pct.append(dd_pct)
                        else:
                            drawdown_pct.append(0)
                    
                    # 绘制回撤曲线
                    ax2.fill_between(x_positions, 0, drawdown_pct, color='red', alpha=0.3)
                    ax2.set_title('综合回撤百分比', fontsize=16, fontproperties=plt.rcParams['font.sans-serif'][0])
                    ax2.set_ylabel('回撤 (%)', fontsize=14, fontproperties=plt.rcParams['font.sans-serif'][0])
                    ax2.grid(True)
                    
                    # 设置回撤图的Y轴范围
                    max_drawdown = max(drawdown_pct) if drawdown_pct else 0
                    padding = max(max_drawdown * 0.1, 1)
                    ax2.set_ylim(max_drawdown + padding, 0)
                
                # 在回撤图左下角添加网站标记
                ax2.text(0.01, 0.02, 'by quant789.com', transform=ax2.transAxes, fontsize=20, color='gray')
                
                # 设置X轴刻度
                num_dates = len(common_dates)
                tick_step = max(1, num_dates // 10)
                tick_indices = list(range(0, num_dates, tick_step))
                if num_dates - 1 not in tick_indices:
                    tick_indices.append(num_dates - 1)
                
                ax1.set_xticks(tick_indices)
                ax1.set_xticklabels([common_dates[i].strftime('%Y-%m-%d') for i in tick_indices], rotation=45, fontsize=12)
                ax2.set_xticks(tick_indices)
                ax2.set_xticklabels([common_dates[i].strftime('%Y-%m-%d') for i in tick_indices], rotation=45, fontsize=12)
                
                # 调整布局
                plt.tight_layout()
                
                # 保存综合收益图表
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                combined_image_path = os.path.join(result_dir, f"combined_equity_chart_{timestamp}.png")
                plt.savefig(combined_image_path)
                plt.close()
                
                image_paths.append(combined_image_path)
                self.log(f"综合收益图表已保存到: {combined_image_path}")
            except Exception as e:
                self.log(f"创建综合收益图表时出错: {str(e)}")
                import traceback
                self.log(traceback.format_exc())
        else:
            self.log("没有找到任何权益曲线，无法创建综合收益图表")
        
        self.log("=== 绘制回测图表完成 ===\n")
        return image_paths 

    def _generate_price_chart(self, result, chart_path):
        """生成K线和交易图
        
        Args:
            result: 单个回测结果字典
            chart_path: 图表保存路径
            
        Returns:
            True: 图表成功生成并保存
            False: 图表生成失败
        """
        try:
            # 获取数据
            symbol = result.get('symbol', '未知品种')
            kline_period = result.get('kline_period', '未知周期')
            trades = result.get('trades', [])
            klines = result.get('klines', pd.DataFrame())
            
            # 检查数据可用性
            if not trades or klines.empty:
                self.log(f"无足够数据生成 {symbol}_{kline_period} 的图表")
                return False
                
            # 如果klines不是DataFrame，尝试转换
            if not isinstance(klines, pd.DataFrame):
                self.log(f"K线数据格式错误，尝试进行转换")
                # 尝试将字典列表转换为DataFrame
                if isinstance(klines, list) and len(klines) > 0 and isinstance(klines[0], dict):
                    klines = pd.DataFrame(klines)
                else:
                    self.log(f"无法转换K线数据为DataFrame，无法生成图表")
                    return False
            
            # 创建图表 - 现在只有1个子图：价格图
            fig = plt.figure(figsize=(16, 10))
            
            # 创建网格布局，为顶部LOGO留出空间
            gs = fig.add_gridspec(2, 1, height_ratios=[0.8, 4.5])
            
            # 添加Logo水印
            self._add_logo_watermark(fig, gs)
            
            # 创建价格图
            ax = fig.add_subplot(gs[1])
            
            # 绘制K线图
            if 'datetime' in klines.columns and 'open' in klines.columns and 'high' in klines.columns and 'low' in klines.columns and 'close' in klines.columns:
                dates = pd.to_datetime(klines['datetime'])
                opens = klines['open']
                highs = klines['high']
                lows = klines['low']
                closes = klines['close']
                
                # 绘制收盘价折线图
                ax.plot(dates, closes, color='blue', linewidth=1, label='收盘价')
                
                # 标出最高价和最低价
                highest_idx = highs.idxmax()
                lowest_idx = lows.idxmin()
                
                # 获取具体的日期和价格值（处理pandas Series）
                import numpy as np
                high_date = dates.loc[highest_idx]
                high_price = highs.loc[highest_idx]
                low_date = dates.loc[lowest_idx]
                low_price = lows.loc[lowest_idx]
                
                # 如果是timestamp对象，转换为datetime
                if hasattr(high_date, 'to_pydatetime'):
                    high_date = high_date.to_pydatetime()
                if hasattr(low_date, 'to_pydatetime'):
                    low_date = low_date.to_pydatetime()
                
                ax.plot(high_date, float(high_price), 'r^', markersize=10)
                ax.text(high_date, float(high_price), 
                        f" 最高: {float(high_price):.2f}", verticalalignment='bottom')
                
                ax.plot(low_date, float(low_price), 'gv', markersize=10)
                ax.text(low_date, float(low_price), 
                        f" 最低: {float(low_price):.2f}", verticalalignment='top')
                
                # 绘制交易点
                for trade in trades:
                    if 'datetime' in trade and 'price' in trade and 'action' in trade:
                        trade_time = pd.to_datetime(trade['datetime'])
                        price = trade['price']
                        action = trade['action']
                        
                        if action in ['开多', '买多']:
                            marker = '^'  # 上三角
                            color = 'r'
                            label = '买入'
                        elif action in ['开空', '卖空']:
                            marker = 'v'  # 下三角
                            color = 'g'
                            label = '卖出'
                        elif action in ['平多', '卖多']:
                            marker = 'o'  # 圆圈
                            color = 'g'
                            label = '平多'
                        elif action in ['平空', '买空']:
                            marker = 'o'  # 圆圈
                            color = 'r'
                            label = '平空'
                        else:
                            continue
                            
                        ax.plot(trade_time, price, marker=marker, markersize=8, color=color)
                        
                        # 显示盈亏信息
                        if action in ['平多', '卖多', '平空', '买空'] and 'net_profit' in trade:
                            net_profit = trade.get('net_profit', 0)
                            if net_profit > 0:
                                profit_text = f"+{net_profit:.2f}"
                                text_color = 'red'
                            else:
                                profit_text = f"{net_profit:.2f}"
                                text_color = 'green'
                                
                            ax.text(trade_time, price, profit_text, color=text_color, fontsize=9, verticalalignment='top')
                
                # 设置图表格式
                ax.set_title(f"{symbol} {kline_period} K线与交易记录", fontsize=16)
                ax.set_xlabel('日期', fontsize=12)
                ax.set_ylabel('价格', fontsize=12)
                ax.grid(True, alpha=0.3)
                
                # 格式化横轴日期
                plt.gcf().autofmt_xdate()
                
                # 添加收益信息
                net_profit = result.get('total_net_profit', 0)
                win_rate = result.get('win_rate', 0)
                max_drawdown = result.get('max_drawdown_pct', 0)
                
                info_text = (
                    f"总收益: {net_profit:.2f} 元 ({(net_profit / result.get('initial_capital', 100000.0) * 100):.2f}%)\n"
                    f"胜率: {win_rate:.2%}\n"
                    f"最大回撤: {max_drawdown:.2f}"
                )
                
                # 在图表右上角添加文本框
                props = dict(boxstyle='round', facecolor='wheat', alpha=0.3)
                ax.text(0.02, 0.98, info_text, transform=ax.transAxes, fontsize=11, 
                        verticalalignment='top', bbox=props)
                
                # 保存图表
                plt.tight_layout()
                plt.savefig(chart_path, dpi=100)
                plt.close(fig)
                
                self.log(f"K线和交易图已保存到: {chart_path}")
                return True
            else:
                self.log(f"K线数据缺少必要列，无法生成图表")
                return False
                
        except Exception as e:
            self.log(f"生成价格图表时出错: {str(e)}")
            plt.close('all')  # 确保关闭所有图表
            return False 