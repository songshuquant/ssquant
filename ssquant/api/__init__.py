"""
策略API模块
- StrategyAPI: 策略开发的主要接口
- create_strategy_api: 策略API工厂方法
"""

from .strategy_api import StrategyAPI, create_strategy_api

__all__ = [
    "StrategyAPI",
    "create_strategy_api"
] 