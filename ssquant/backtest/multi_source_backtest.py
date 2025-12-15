import pandas as pd
import numpy as np

# 导入拆分后的模块
from .backtest_core import MultiSourceBacktester

# 保持向后兼容性，直接导出 MultiSourceBacktester 类
__all__ = ['MultiSourceBacktester']