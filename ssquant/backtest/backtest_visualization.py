import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from datetime import datetime
from PIL import Image
import matplotlib.image as mpimg
from scipy.interpolate import make_interp_spline, interp1d

from .trade_position import format_position, resolve_trade_positions

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
            logger: 日志记录器，可以是BacktestLogger或logging.Logger
        """
        self.logger = logger

        # 加载Logo水印
        self.logo_path = self._find_logo_path()
        if self.logo_path:
            self.log(f"找到Logo文件: {self.logo_path}")
        else:
            self.log("未找到Logo文件，将不使用水印")

    def log(self, message, level='INFO'):
        """记录日志"""
        if self.logger:
            if hasattr(self.logger, 'log'):
                self.logger.log(message, level=level)
            elif hasattr(self.logger, 'log_message'):
                self.logger.log_message(message)
            elif hasattr(self.logger, 'info'):
                self.logger.info(message)
            else:
                print(f"[{level}] {message}")
        else:
            print(f"[{level}] {message}")

    def _find_logo_path(self):
        """查找Logo文件路径"""
        # 尝试多个可能的路径
        possible_paths = [
            'ssquant/assets/squirrel_quant_logo.png',
            '../assets/squirrel_quant_logo.png',
            '../../assets/squirrel_quant_logo.png',
            'assets/squirrel_quant_logo.png',
            os.path.join(os.path.dirname(__file__), '..', 'assets', 'squirrel_quant_logo.png'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets', 'squirrel_quant_logo.png'),
        ]

        # 获取当前文件所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(current_dir))
        possible_paths.append(os.path.join(project_root, 'ssquant', 'assets', 'squirrel_quant_logo.png'))

        # 尝试使用pkg_resources查找
        try:
            import pkg_resources
            resource_path = pkg_resources.resource_filename('ssquant', 'assets/squirrel_quant_logo.png')
            possible_paths.append(resource_path)
        except:
            pass

        # 尝试使用importlib查找（Python 3.9+）
        try:
            from importlib import resources
            with resources.path('ssquant.assets', 'squirrel_quant_logo.png') as path:
                possible_paths.append(str(path))
        except:
            pass

        # 尝试使用importlib.util查找模块路径
        try:
            import importlib.util
            spec = importlib.util.find_spec('ssquant')
            if spec and spec.origin:
                ssquant_dir = os.path.dirname(spec.origin)
                possible_paths.append(os.path.join(ssquant_dir, 'assets', 'squirrel_quant_logo.png'))
        except:
            pass

        # 查找可能的Logo文件
        for path in possible_paths:
            if os.path.exists(path):
                return path

        # 如果都找不到，尝试glob查找
        try:
            import glob
            patterns = [
                '**/squirrel_quant_logo.png',
                '**/*logo*.png'
            ]
            for pattern in patterns:
                matches = glob.glob(pattern, recursive=True)
                if matches:
                    return matches[0]
        except:
            pass

        return None

    def _add_logo_watermark(self, ax):
        """在指定 axes 的右上角添加 Logo 水印，不占用额外子图空间。"""
        if not self.logo_path or not os.path.exists(self.logo_path):
            return
        try:
            from matplotlib.offsetbox import OffsetImage, AnnotationBbox
            img = mpimg.imread(self.logo_path)
            imagebox = OffsetImage(img, zoom=0.08)
            ab = AnnotationBbox(imagebox, (0.98, 0.98), xycoords='axes fraction',
                                frameon=False, pad=0, boxcoords="axes fraction",
                                box_alignment=(1, 1), zorder=10)
            ax.add_artist(ab)
        except Exception as e:
            self.log(f"添加Logo水印时出错: {str(e)}", level='WARNING')

    def visualize_backtest(self, result, output_dir='.', show=False):
        """生成回测结果可视化图表

        Args:
            result: 回测结果字典，包含equity_curve、trades等
            output_dir: 输出目录
            show: 是否显示图表（在服务器环境中通常设置为False）

        Returns:
            dict: 包含生成的图表路径
        """
        charts = {}

        try:
            # 创建输出目录
            os.makedirs(output_dir, exist_ok=True)

            # 生成权益曲线图
            equity_chart_path = os.path.join(output_dir, f"equity_curve_{result.get('symbol', 'unknown')}.png")
            if self._generate_equity_curve(result, equity_chart_path):
                charts['equity_curve'] = equity_chart_path

            # 生成回撤图
            drawdown_chart_path = os.path.join(output_dir, f"drawdown_{result.get('symbol', 'unknown')}.png")
            if self._generate_drawdown_chart(result, drawdown_chart_path):
                charts['drawdown'] = drawdown_chart_path

            # 生成价格与交易图
            price_chart_path = os.path.join(output_dir, f"price_chart_{result.get('symbol', 'unknown')}.png")
            if self._generate_price_chart(result, price_chart_path):
                charts['price_chart'] = price_chart_path

            return charts

        except Exception as e:
            self.log(f"可视化过程中出错: {str(e)}", level='ERROR')
            return charts

    def _generate_equity_curve(self, result, chart_path):
        """生成权益曲线图

        Args:
            result: 回测结果字典
            chart_path: 图表保存路径

        Returns:
            True: 图表成功生成并保存
            False: 图表生成失败
        """
        try:
            # 获取权益曲线数据
            equity_curve = result.get('equity_curve', [])

            if not equity_curve or len(equity_curve) < 2:
                self.log("权益曲线数据不足，无法生成图表")
                return False

            # 创建图表
            fig = plt.figure(figsize=(16, 10))

            # 创建网格布局
            gs = fig.add_gridspec(2, 1, height_ratios=[2, 2])

            # 转换为numpy数组以便处理
            equity_array = np.array(equity_curve)

            # 如果数据包含时间戳，分离时间和权益值
            if isinstance(equity_curve[0], (list, tuple)) and len(equity_curve[0]) >= 2:
                # 数据格式为[(time1, value1), (time2, value2), ...]
                times = np.array([item[0] for item in equity_curve])
                values = np.array([item[1] for item in equity_curve])
            else:
                # 数据格式为[value1, value2, ...]，使用时间索引
                times = np.arange(len(equity_curve))
                values = equity_array

            # 创建权益曲线子图
            ax_equity = fig.add_subplot(gs[0])

            # 添加Logo水印
            self._add_logo_watermark(ax_equity)

            # 计算初始资金和最终权益
            initial_capital = result.get('initial_capital', values[0] if len(values) > 0 else 100000)
            final_equity = values[-1] if len(values) > 0 else initial_capital

            # 判断整体盈亏，决定曲线颜色
            if final_equity >= initial_capital:
                curve_color = '#FF4500'  # 橙红色（盈利）
            else:
                curve_color = '#32CD32'  # 绿色（亏损）

            # 绘制权益曲线
            ax_equity.plot(times, values, color=curve_color, linewidth=2, label='权益曲线')

            # 填充盈亏区域
            ax_equity.fill_between(times, values, initial_capital,
                                   where=(values >= initial_capital),
                                   alpha=0.3, color='red', label='盈利区域')
            ax_equity.fill_between(times, values, initial_capital,
                                   where=(values < initial_capital),
                                   alpha=0.3, color='green', label='亏损区域')

            # 添加初始资金水平线
            ax_equity.axhline(y=initial_capital, color='gray', linestyle='--', linewidth=1, alpha=0.7, label=f'初始资金: {initial_capital:.2f}')

            # 添加标注
            total_return = result.get('total_return', 0)
            if total_return > 0:
                return_text = f"+{total_return:.2f}%"
                return_color = 'red'
            else:
                return_text = f"{total_return:.2f}%"
                return_color = 'green'

            # 标注最终权益
            ax_equity.annotate(f'最终权益: {final_equity:.2f}\n总收益率: {return_text}',
                              xy=(times[-1], final_equity),
                              xytext=(times[-1], final_equity + (max(values) - min(values)) * 0.1),
                              arrowprops=dict(arrowstyle='->', color=return_color),
                              fontsize=12, color=return_color, fontweight='bold')

            # 标注最大回撤点
            max_dd_info = result.get('max_drawdown_info', {})
            if max_dd_info and 'start_idx' in max_dd_info and 'end_idx' in max_dd_info:
                try:
                    start_idx = max_dd_info['start_idx']
                    end_idx = max_dd_info['end_idx']
                    if start_idx < len(times) and end_idx < len(times):
                        start_time = times[start_idx]
                        end_time = times[end_idx]
                        start_value = values[start_idx]
                        end_value = values[end_idx]

                        # 绘制最大回撤区间
                        ax_equity.plot([start_time, end_time], [start_value, end_value],
                                      'b--', linewidth=2, label=f'最大回撤: {result.get("max_drawdown", 0):.2f}%')

                        # 标注回撤开始和结束点
                        ax_equity.plot(start_time, start_value, 'bo', markersize=8)
                        ax_equity.plot(end_time, end_value, 'bs', markersize=8)

                        # 添加回撤标注文字
                        mid_time = (start_time + end_time) / 2
                        mid_value = (start_value + end_value) / 2
                        ax_equity.text(mid_time, mid_value, f'最大回撤: {result.get("max_drawdown", 0):.2f}%',
                                      fontsize=10, color='blue', ha='center')
                except Exception as e:
                    self.log(f"标注最大回撤点时出错: {str(e)}")

            # 设置标题和标签
            symbol = result.get('symbol', '未知品种')
            strategy_name = result.get('strategy_name', '未知策略')
            ax_equity.set_title(f'{symbol} - {strategy_name} 权益曲线', fontsize=16)
            ax_equity.set_xlabel('时间', fontsize=12)
            ax_equity.set_ylabel('权益（元）', fontsize=12)
            ax_equity.legend(loc='upper left')
            ax_equity.grid(True, alpha=0.3)

            # 格式化Y轴为货币格式
            ax_equity.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:,.0f}'))

            # 创建收益分布子图
            ax_returns = fig.add_subplot(gs[1])

            # 获取每笔交易的收益
            trades = result.get('trades', [])
            if trades and len(trades) > 0:
                # 提取交易收益
                trade_returns = []
                for trade in trades:
                    if isinstance(trade, dict) and 'net_profit' in trade:
                        trade_returns.append(trade['net_profit'])
                    elif isinstance(trade, (list, tuple)) and len(trade) >= 6:
                        trade_returns.append(trade[5] if trade[5] is not None else 0)

                if trade_returns:
                    # 分离盈利和亏损
                    profits = [r for r in trade_returns if r > 0]
                    losses = [r for r in trade_returns if r < 0]

                    # 绘制收益分布直方图
                    bins = max(10, min(50, len(trade_returns) // 5))

                    if profits:
                        ax_returns.hist(profits, bins=bins, alpha=0.7, color='red', label=f'盈利交易 ({len(profits)}笔)')
                    if losses:
                        ax_returns.hist(losses, bins=bins, alpha=0.7, color='green', label=f'亏损交易 ({len(losses)}笔)')

                    ax_returns.axvline(x=0, color='black', linestyle='-', linewidth=1)

                    # 添加统计信息
                    avg_profit = np.mean(profits) if profits else 0
                    avg_loss = np.mean(losses) if losses else 0
                    win_rate = result.get('win_rate', 0)

                    stats_text = (
                        f"总交易: {len(trade_returns)}笔\n"
                        f"胜率: {win_rate:.2%}\n"
                        f"平均盈利: {avg_profit:.2f}元\n"
                        f"平均亏损: {avg_loss:.2f}元\n"
                        f"盈亏比: {abs(avg_profit/avg_loss):.2f}" if avg_loss != 0 else "盈亏比: N/A"
                    )

                    ax_returns.text(0.98, 0.95, stats_text, transform=ax_returns.transAxes,
                                   fontsize=11, verticalalignment='top', horizontalalignment='right',
                                   bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

                    ax_returns.set_title('交易收益分布', fontsize=14)
                    ax_returns.set_xlabel('收益（元）', fontsize=12)
                    ax_returns.set_ylabel('交易次数', fontsize=12)
                    ax_returns.legend()
                    ax_returns.grid(True, alpha=0.3)
            else:
                ax_returns.text(0.5, 0.5, '无交易记录', transform=ax_returns.transAxes,
                              fontsize=14, ha='center', va='center')
                ax_returns.set_title('交易收益分布', fontsize=14)

            # 添加整体统计信息
            stats = {
                '初始资金': f"{initial_capital:,.2f}",
                '最终权益': f"{final_equity:,.2f}",
                '总收益率': f"{total_return:.2f}%",
                '最大回撤': f"{result.get('max_drawdown', 0):.2f}%",
                '胜率': f"{result.get('win_rate', 0):.2%}",
                '夏普比率': f"{result.get('sharpe_ratio', 0):.4f}",
            }

            stats_text = '\n'.join([f"{k}: {v}" for k, v in stats.items()])

            # 在权益曲线图上添加统计信息框
            ax_equity.text(0.02, 0.98, stats_text, transform=ax_equity.transAxes,
                          fontsize=10, verticalalignment='top',
                          bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

            # 调整布局并保存
            plt.tight_layout()
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close(fig)

            self.log(f"权益曲线图已保存到: {chart_path}")
            return True

        except Exception as e:
            self.log(f"生成权益曲线图时出错: {str(e)}")
            plt.close('all')
            return False

    def _generate_drawdown_chart(self, result, chart_path):
        """生成回撤分析图

        Args:
            result: 回测结果字典
            chart_path: 图表保存路径

        Returns:
            True: 图表成功生成并保存
            False: 图表生成失败
        """
        try:
            # 获取权益曲线数据
            equity_curve = result.get('equity_curve', [])

            if not equity_curve or len(equity_curve) < 2:
                self.log("权益曲线数据不足，无法生成回撤图")
                return False

            # 提取权益值
            if isinstance(equity_curve[0], (list, tuple)) and len(equity_curve[0]) >= 2:
                values = np.array([item[1] for item in equity_curve])
            else:
                values = np.array(equity_curve)

            # 计算回撤
            peak = np.maximum.accumulate(values)
            drawdown = (peak - values) / peak * 100  # 百分比回撤

            # 创建图表
            fig, ax = plt.subplots(figsize=(16, 8))

            # 添加Logo水印
            self._add_logo_watermark(ax)

            # 绘制回撤曲线
            ax.fill_between(range(len(drawdown)), drawdown, 0, alpha=0.5, color='green', label='回撤')
            ax.plot(range(len(drawdown)), drawdown, color='green', linewidth=1)

            # 标记最大回撤点
            max_dd_idx = np.argmax(drawdown)
            max_dd_value = drawdown[max_dd_idx]

            ax.plot(max_dd_idx, max_dd_value, 'rv', markersize=10)
            ax.annotate(f'最大回撤: {max_dd_value:.2f}%',
                       xy=(max_dd_idx, max_dd_value),
                       xytext=(max_dd_idx, max_dd_value + 2),
                       arrowprops=dict(arrowstyle='->', color='red'),
                       fontsize=12, color='red', fontweight='bold')

            # 设置标题和标签
            symbol = result.get('symbol', '未知品种')
            ax.set_title(f'{symbol} 回撤分析', fontsize=16)
            ax.set_xlabel('时间', fontsize=12)
            ax.set_ylabel('回撤 (%)', fontsize=12)
            ax.legend()
            ax.grid(True, alpha=0.3)

            # 添加统计信息
            avg_drawdown = np.mean(drawdown)
            stats_text = (
                f"最大回撤: {max_dd_value:.2f}%\n"
                f"平均回撤: {avg_drawdown:.2f}%\n"
                f"回撤持续时间: {max_dd_idx} 周期"
            )

            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
                   fontsize=11, verticalalignment='top',
                   bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

            # 保存图表
            plt.tight_layout()
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            plt.close(fig)

            self.log(f"回撤图已保存到: {chart_path}")
            return True

        except Exception as e:
            self.log(f"生成回撤图时出错: {str(e)}")
            plt.close('all')
            return False

    def _generate_price_chart(self, result, chart_path):
        """生成K线（蜡烛图）和交易信号图，使用整数索引作为x轴以避免非交易时段连线问题。

        Args:
            result: 单个回测结果字典，需包含 klines (DataFrame 含 datetime/open/high/low/close)
                    和 trades (列表含 datetime/price/action 等)
            chart_path: 图表保存路径

        Returns:
            bool: True 表示成功生成并保存，False 表示失败
        """
        try:
            # ---------- 1. 数据提取与校验 ----------
            symbol = result.get('symbol', '未知品种')
            kline_period = result.get('kline_period', '未知周期')
            trades = result.get('trades', [])
            klines = result.get('klines', pd.DataFrame())

            if klines.empty:
                self.log(f"K线数据为空，无法生成 {symbol}_{kline_period} 的图表")
                return False

            if not isinstance(klines, pd.DataFrame):
                if isinstance(klines, list) and len(klines) > 0 and isinstance(klines[0], dict):
                    klines = pd.DataFrame(klines)
                else:
                    self.log(f"K线数据格式错误，无法生成图表")
                    return False

            required_cols = {'datetime', 'open', 'high', 'low', 'close'}
            if not required_cols.issubset(klines.columns):
                self.log(f"K线数据缺少必要列 {required_cols - set(klines.columns)}，无法生成图表")
                return False

            # ---------- 2. 预处理 ----------
            n = len(klines)
            dates = pd.to_datetime(klines['datetime'])
            opens = klines['open'].astype(float).values
            highs = klines['high'].astype(float).values
            lows = klines['low'].astype(float).values
            closes = klines['close'].astype(float).values

            # 整数索引映射：x=0..n-1
            x = np.arange(n)

            # 建立 datetime -> 最近K线索引的映射（用于交易信号定位）
            # 使用 numpy searchsorted 进行高效二分查找
            kline_ts = dates.to_numpy(dtype='datetime64[ns]').astype(np.int64, copy=False)

            # ---------- 3. 创建画布 ----------
            fig, ax = plt.subplots(figsize=(16, 9))
            self._add_logo_watermark(ax)

            # ---------- 4. 向量化绘制蜡烛图 ----------
            up_color = '#e74c3c'      # 涨：红色（A股习惯）
            down_color = '#2ecc71'    # 跌：绿色
            body_width = 0.75

            colors = np.where(closes >= opens, up_color, down_color)
            body_bottoms = np.minimum(opens, closes)
            body_heights = np.abs(closes - opens)

            from matplotlib.collections import LineCollection

            # 影线：一次性 LineCollection（比逐根 ax.plot 快 10~50 倍）
            segments = np.empty((n, 2, 2))
            segments[:, 0, 0] = x
            segments[:, 0, 1] = lows
            segments[:, 1, 0] = x
            segments[:, 1, 1] = highs
            lc = LineCollection(segments, colors=colors, linewidths=0.8, capstyle='butt')
            ax.add_collection(lc)

            # 实体：向量化粗竖线 LineCollection（替代 ax.bar，避免 10 万+ Patch 对象开销）
            nonzero = body_heights >= 1e-9
            if np.any(nonzero):
                body_segments = np.empty((int(np.count_nonzero(nonzero)), 2, 2))
                body_segments[:, 0, 0] = x[nonzero]
                body_segments[:, 0, 1] = body_bottoms[nonzero]
                body_segments[:, 1, 0] = x[nonzero]
                body_segments[:, 1, 1] = body_bottoms[nonzero] + body_heights[nonzero]
                body_lc = LineCollection(body_segments, colors=colors[nonzero],
                                         linewidths=3.5, capstyle='butt', antialiaseds=True)
                ax.add_collection(body_lc)
            # 十字星横线
            zmask = ~nonzero
            if np.any(zmask):
                zidx = np.where(zmask)[0]
                zseg = np.empty((len(zidx), 2, 2))
                zseg[:, 0, 0] = x[zidx] - body_width / 2
                zseg[:, 0, 1] = opens[zidx]
                zseg[:, 1, 0] = x[zidx] + body_width / 2
                zseg[:, 1, 1] = opens[zidx]
                lc_zero = LineCollection(zseg, colors=colors[zmask], linewidths=2.0)
                ax.add_collection(lc_zero)

            # ---------- 5. 标记最高/最低点 ----------
            highest_idx = int(np.argmax(highs))
            lowest_idx = int(np.argmin(lows))
            ax.plot(x[highest_idx], highs[highest_idx], 'r^', markersize=10, zorder=5)
            ax.text(x[highest_idx], highs[highest_idx], f" 最高: {highs[highest_idx]:.2f}",
                    verticalalignment='bottom', fontsize=9, color='darkred')
            ax.plot(x[lowest_idx], lows[lowest_idx], 'gv', markersize=10, zorder=5)
            ax.text(x[lowest_idx], lows[lowest_idx], f" 最低: {lows[lowest_idx]:.2f}",
                    verticalalignment='top', fontsize=9, color='darkgreen')

            # ---------- 6. 绘制交易信号（向量化） ----------
            action_style = {
                '开多': ('^', up_color),
                '买多': ('^', up_color),
                '开空': ('v', down_color),
                '卖空': ('v', down_color),
                '平多': ('o', down_color),
                '卖多': ('o', down_color),
                '平空': ('o', up_color),
                '买空': ('o', up_color),
                '平空开多': ('^', '#c0392b'),
                '平多开空': ('v', '#27ae60'),
            }

            # 按 marker 分组，批量 scatter
            trade_groups = {}   # marker -> list of (x, y, color)
            profit_texts = []   # (x, y, text, color, va)
            position_texts = [] # (x, y, text, color, va, y_offset_points)
            hl_range = max(highs) - min(lows)
            trade_positions = resolve_trade_positions(trades)

            # reverse_pos 会在同一时刻生成“先平仓、再反向开仓”两笔记录。
            # 静态图保留两枚成交图标和第一腿盈亏，但只在第二腿显示最终仓位，
            # 避免“空仓”和最终反向仓位文字重叠。
            reverse_close_indices = set()
            order_by_time = sorted(
                range(len(trades)),
                key=lambda i: (pd.to_datetime(trades[i].get('datetime'), errors='coerce'), i),
            )
            pair_idx = 0
            reverse_pairs = {('平多', '开空'), ('平空', '开多')}
            while pair_idx < len(order_by_time) - 1:
                first_idx = order_by_time[pair_idx]
                second_idx = order_by_time[pair_idx + 1]
                first_trade = trades[first_idx]
                second_trade = trades[second_idx]
                first_time = pd.to_datetime(first_trade.get('datetime'), errors='coerce')
                second_time = pd.to_datetime(second_trade.get('datetime'), errors='coerce')
                actions = (
                    str(first_trade.get('action', '') or '').strip(),
                    str(second_trade.get('action', '') or '').strip(),
                )
                if first_time == second_time and actions in reverse_pairs:
                    reverse_close_indices.add(first_idx)
                    pair_idx += 2
                else:
                    pair_idx += 1

            for trade_idx, trade in enumerate(trades):
                if not all(k in trade for k in ('datetime', 'price', 'action')):
                    continue
                trade_dt = pd.to_datetime(trade['datetime'])
                trade_ts = trade_dt.value
                price = float(trade['price'])
                action = trade['action']

                idx = int(np.searchsorted(kline_ts, trade_ts, side='left'))
                if idx >= n:
                    idx = n - 1
                elif idx > 0 and abs(kline_ts[idx] - trade_ts) > abs(kline_ts[idx - 1] - trade_ts):
                    idx -= 1

                marker, color = action_style.get(action, (None, None))
                if marker is None:
                    continue

                # 多头开仓/空头平仓置于K线下方；其余信号置于上方。
                below_actions = {'开多', '买多', '平空', '买空', '平空开多'}
                offset_dir = -1 if action in below_actions else 1
                local_range = float(highs[idx] - lows[idx])
                offset_size = abs(local_range) * 0.15
                if offset_size < 1e-9:
                    offset_size = max(abs(float(hl_range)) * 0.0005, 1e-9)
                if offset_dir < 0:
                    y_pos = min(price, float(lows[idx])) - offset_size
                else:
                    y_pos = max(price, float(highs[idx])) + offset_size

                trade_groups.setdefault(marker, []).append((float(x[idx]), float(y_pos), color))

                if '平' in action and 'net_profit' in trade:
                    net_profit = float(trade['net_profit'])
                    profit_text = f"+{net_profit:.2f}" if net_profit > 0 else f"{net_profit:.2f}"
                    text_color = up_color if net_profit > 0 else down_color
                    va = 'top' if offset_dir < 0 else 'bottom'
                    profit_texts.append((float(x[idx]), float(y_pos), profit_text, text_color, va))
                position_text = '' if trade_idx in reverse_close_indices else format_position(
                    trade_positions[trade_idx], compact=True
                )
                if position_text:
                    va = 'top' if offset_dir < 0 else 'bottom'
                    y_offset_points = -12 if offset_dir < 0 else 12
                    position_texts.append((
                        float(x[idx]), float(y_pos), position_text, color, va, y_offset_points
                    ))

            for marker, pts in trade_groups.items():
                xs, ys, cs = zip(*pts)
                ax.scatter(xs, ys, marker=marker, s=80, c=cs,
                           edgecolors='black', linewidths=0.5, zorder=6)

            for tx, ty, txt, tc, va in profit_texts:
                ax.text(tx, ty, txt, color=tc, fontsize=8,
                        verticalalignment=va, horizontalalignment='center')

            for tx, ty, txt, tc, va, y_offset_points in position_texts:
                ax.annotate(
                    txt, (tx, ty), xytext=(0, y_offset_points), textcoords='offset points',
                    color=tc, fontsize=8, verticalalignment=va,
                    horizontalalignment='center'
                )

            # ---------- 7. X轴标签 ----------
            target_ticks = 10
            step = max(1, n // target_ticks)
            tick_positions = list(range(0, n, step))
            if (n - 1) not in tick_positions:
                tick_positions.append(n - 1)

            tick_labels = []
            kp_str = str(kline_period).lower()
            fmt = '%m-%d %H:%M' if ('min' in kp_str or '分钟' in kp_str) else '%Y-%m-%d'
            for pos in tick_positions:
                tick_labels.append(dates.iloc[pos].strftime(fmt))

            ax.set_xticks(tick_positions)
            ax.set_xticklabels(tick_labels, rotation=30, ha='right', fontsize=9)

            # ---------- 8. 图表格式 ----------
            ax.set_title(f"{symbol} {kline_period} K线与交易记录", fontsize=16)
            ax.set_xlabel('K线索引（按时间顺序）', fontsize=12)
            ax.set_ylabel('价格', fontsize=12)
            ax.grid(True, alpha=0.2, linestyle='--')
            ax.set_xlim(-0.5, n - 0.5)

            net_profit = result.get('total_net_profit', 0)
            win_rate = result.get('win_rate', 0)
            max_drawdown = result.get('max_drawdown_pct', 0)
            initial_capital = result.get('initial_capital', 100000.0)
            total_return_pct = (net_profit / initial_capital * 100) if initial_capital else 0
            info_text = (
                f"总收益: {net_profit:.2f} 元 ({total_return_pct:.2f}%)\n"
                f"胜率: {win_rate:.2%}\n"
                f"最大回撤: {max_drawdown:.2f}%"
            )
            ax.text(0.02, 0.98, info_text, transform=ax.transAxes, fontsize=11,
                    verticalalignment='top',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.4))

            from matplotlib.lines import Line2D
            ax.legend(handles=[
                Line2D([0], [0], marker='^', color='w', markerfacecolor=up_color,
                       markeredgecolor='black', markersize=8, label='开多/平空开多'),
                Line2D([0], [0], marker='v', color='w', markerfacecolor=down_color,
                       markeredgecolor='black', markersize=8, label='开空/平多开空'),
                Line2D([0], [0], marker='o', color='w', markerfacecolor=down_color,
                       markeredgecolor='black', markersize=8, label='平多'),
                Line2D([0], [0], marker='o', color='w', markerfacecolor=up_color,
                       markeredgecolor='black', markersize=8, label='平空'),
            ], loc='lower right', fontsize=9, framealpha=0.7)

            # 手动边距 + 低 dpi，跳过 tight_layout / bbox_inches='tight' 的二次重算
            fig.subplots_adjust(left=0.06, right=0.98, top=0.93, bottom=0.12)
            fig.savefig(chart_path, dpi=100)
            plt.close(fig)

            if hasattr(chart_path, 'getvalue'):
                self.log("K线和交易图已写入内存缓冲区")
            else:
                self.log(f"K线和交易图已保存到: {chart_path}")
            return True

        except Exception as e:
            self.log(f"生成价格图表时出错: {str(e)}")
            plt.close('all')
            return False
