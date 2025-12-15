"""
数据模块
~~~~~~~

提供期货数据的获取、处理和管理功能。

主要组件:
- api_data_fetcher: API数据获取模块，支持实时数据和历史数据
- local_data_loader: 本地数据处理模块，支持本地数据文件处理
- multi_data_fetcher: 多品种数据获取模块，支持批量数据处理
- data_source: 数据源管理模块，提供数据源和多数据源管理

功能特性:
1. API数据获取
   - 支持多种数据周期（分钟、小时、日、周、月）
   - 自动处理数据复权
   - 智能数据缓存
   - 时区自动转换

2. 本地数据处理
   - 灵活的数据格式支持
   - 自动日期解析
   - 数据范围筛选
   - 格式验证和检查

3. 多品种数据
   - 批量数据获取
   - 数据同步和对齐
   - 数据质量检查
   - 摘要统计分析

4. 数据源管理
   - 单一数据源管理
   - 多数据源管理
   - 数据对齐和填充
   - 交易接口

数据管理模块
- load_local_data: 本地行情数据加载
- DataSource: 单数据源管理
- MultiDataSource: 多数据源管理
"""

from .api_data_fetcher import (
    # API数据获取
    get_futures_data,
    fetch_data_from_api
)

from .local_data_loader import (
    # 本地数据处理
    load_local_data
)

from .multi_data_fetcher import (
    # 多品种数据
    fetch_multiple_data,
    get_data_summary,
    save_data_to_csv
)

from .data_source import (
    # 数据源管理
    DataSource,
    MultiDataSource
)

__all__ = [
    # API数据获取
    'get_futures_data',
    'fetch_data_from_api',
    
    # 本地数据处理
    'load_local_data',
    
    # 多品种数据
    'fetch_multiple_data',
    'get_data_summary',
    'save_data_to_csv',
    
    # 数据源管理
    'DataSource',
    'MultiDataSource'
] 