"""
路径配置模块

统一管理项目中的路径配置，避免硬编码和重复代码
"""

import os
import sys

def get_project_root():
    """获取项目根目录"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def setup_python_path():
    """设置Python路径"""
    project_root = get_project_root()
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

def get_data_cache_dir():
    """获取数据缓存目录"""
    return os.path.join(get_project_root(), 'data_cache')

def get_backtest_results_dir():
    """获取回测结果目录"""
    return os.path.join(get_project_root(), 'backtest_results')

def get_backtest_logs_dir():
    """获取回测日志目录"""
    return os.path.join(get_project_root(), 'backtest_logs') 