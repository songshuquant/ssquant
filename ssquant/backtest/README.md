# 回测框架

## 模块结构

回测框架被拆分为以下模块：

1. `backtest_core.py` - 核心回测类和方法
2. `backtest_data.py` - 数据获取和处理功能
3. `backtest_logger.py` - 日志记录功能
4. `backtest_results.py` - 结果计算功能
5. `backtest_report.py` - 性能报告生成功能
6. `backtest_visualization.py` - 可视化绘图功能
7. `multi_source_backtest.py` - 主入口文件，导入并导出核心功能

## 使用方法

### 1. 基本用法

```python
from backtest import MultiSourceBacktester

# 创建回测实例
backtester = MultiSourceBacktester()

# 配置回测参数
backtester.set_base_config({
    'use_cache': True,
    'save_data': True,
    'align_data': True,
    'debug': False
})

# 添加品种配置
backtester.add_symbol_config('rb888', {
    'periods': [
        {'kline_period': '1h', 'adjust_type': '1'},
        {'kline_period': 'D', 'adjust_type': '1'}
    ],
    'start_date': '2023-01-01',
    'end_date': '2023-12-31',
    'initial_capital': 100000.0
})

# 定义策略函数
def my_strategy(api):
    # 策略逻辑
    pass

# 定义初始化函数
def initialize(api):
    api.log("策略初始化")
    api.log(f"策略参数: {api.params}")

# 运行回测
results = backtester.run(my_strategy, initialize, {'param1': 100})

# 显示回测结果
backtester.show_results(results)
```

### 2. 策略函数示例

```python
def simple_strategy(api):
    # 获取多个数据源
    data1 = api.data[0]  # 第一个数据源
    data2 = api.data[1]  # 第二个数据源
    
    # 当前价格
    current_price = data1.current_price
    
    # 当前时间
    current_datetime = data1.current_datetime
    
    # 当前持仓
    position = data1.current_pos
    
    # 简单的移动平均线交叉策略
    if len(data1.data) > 20 and data1.current_idx >= 20:
        # 计算移动平均线
        ma5 = data1.data['close'].iloc[data1.current_idx-5:data1.current_idx].mean()
        ma20 = data1.data['close'].iloc[data1.current_idx-20:data1.current_idx].mean()
        
        # 金叉买入
        if ma5 > ma20 and position <= 0:
            api.log(f"{current_datetime} 金叉买入信号, MA5={ma5:.2f}, MA20={ma20:.2f}")
            api.buy(data1, 1, limit_price=None, reason="金叉买入")
        
        # 死叉卖出
        elif ma5 < ma20 and position > 0:
            api.log(f"{current_datetime} 死叉卖出信号, MA5={ma5:.2f}, MA20={ma20:.2f}")
            api.sell(data1, 1, limit_price=None, reason="死叉卖出")
```

## 更多示例

可以在`strategies/`目录下找到更多示例策略，包括：

1. 双均线策略
2. 跨品种套利策略
3. 跨周期过滤策略
4. 多品种多周期交易策略
5. 海龟交易策略
6. 机器学习策略
7. 强弱轮动策略

这些示例展示了如何使用回测框架的不同功能进行各种类型的策略回测。 