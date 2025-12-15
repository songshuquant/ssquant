"""
回测核心模块
- MultiSourceBacktester: 多品种多周期回测主类
- UnifiedStrategyRunner: 统一策略运行器（支持回测/SIMNOW/实盘）
- 其他回测相关工具
"""

from .backtest_core import MultiSourceBacktester
from .backtest_logger import BacktestLogger
from .backtest_data import BacktestDataManager
from .backtest_results import BacktestResultCalculator
from .backtest_report import BacktestReportGenerator
from .backtest_visualization import BacktestVisualizer
from .unified_runner import UnifiedStrategyRunner, RunMode
from .live_trading_adapter import LiveTradingAdapter, DataRecorder

__all__ = [
    "MultiSourceBacktester",
    "BacktestLogger",
    "BacktestDataManager",
    "BacktestResultCalculator",
    "BacktestReportGenerator",
    "BacktestVisualizer",
    "UnifiedStrategyRunner",
    "RunMode",
    "LiveTradingAdapter",
    "DataRecorder"
]

