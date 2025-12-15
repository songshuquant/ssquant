# API参考手册

> 完整的API函数参考

## 📖 目录

1. [数据查询API](#数据查询api)
2. [持仓查询API](#持仓查询api)
3. [交易操作API](#交易操作api)
4. [TICK数据API](#tick数据api)
5. [多数据源API](#多数据源api)
6. [参数和日志API](#参数和日志api)
7. [实盘专用API](#实盘专用api)
8. [回调函数](#回调函数)

---

## 数据查询API

### api.get_close(index=0)

获取收盘价序列。

**参数：**
- `index` (int): 数据源索引，默认0

**返回：**
- `pd.Series`: 收盘价序列

**示例：**

```python
close = api.get_close()
ma20 = close.rolling(20).mean()
current_price = close.iloc[-1]
```

---

### api.get_open(index=0)

获取开盘价序列。

**参数：**
- `index` (int): 数据源索引

**返回：**
- `pd.Series`: 开盘价序列

---

### api.get_high(index=0)

获取最高价序列。

---

### api.get_low(index=0)

获取最低价序列。

---

### api.get_volume(index=0)

获取成交量序列。

---

### api.get_klines(index=0)

获取完整的K线数据。

**返回：**
- `pd.DataFrame`: 包含以下列
  - `datetime`: 时间
  - `open`: 开盘价
  - `high`: 最高价
  - `low`: 最低价
  - `close`: 收盘价
  - `volume`: 成交量

**示例：**

```python
klines = api.get_klines()
print(klines.columns)
# ['datetime', 'open', 'high', 'low', 'close', 'volume']

# 获取最新K线数据
latest = klines.iloc[-1]
print(f"最新价: {latest['close']}")
```

---

### api.get_price(index=0)

获取当前价格（最新收盘价）。

**返回：**
- `float`: 当前价格

---

### api.get_datetime(index=0)

获取当前K线时间。

**返回：**
- `pd.Timestamp`: 当前K线的时间

---

### api.get_idx(index=0)

获取当前K线索引（从0开始）。

**返回：**
- `int`: 当前索引

**用途：** 判断数据是否足够、防止策略在数据不足时执行

```python
current_idx = api.get_idx()
if current_idx < 20:
    return  # 数据不足，跳过
```

---

## 持仓查询API

### api.get_pos(index=0)

获取净持仓。

**返回：**
- `int`: 持仓数量
  - 正数：多头持仓
  - 负数：空头持仓
  - 0：无持仓

**示例：**

```python
pos = api.get_pos()

if pos > 0:
    print(f"持有{pos}手多仓")
elif pos < 0:
    print(f"持有{-pos}手空仓")
else:
    print("无持仓")
```

---

### api.get_long_pos(index=0)

获取多头持仓数量。

**返回：**
- `int`: 多头持仓（非负数）

---

### api.get_short_pos(index=0)

获取空头持仓数量。

**返回：**
- `int`: 空头持仓（非负数）

---

### api.get_position_detail(index=0)

获取详细持仓信息（包含今昨仓）。

**返回：**
- `dict`: 包含以下字段

| 字段 | 说明 |
|------|------|
| `net_pos` | 净持仓 |
| `long_pos` | 多头持仓 |
| `short_pos` | 空头持仓 |
| `today_pos` | 今仓（净） |
| `yd_pos` | 昨仓（净） |
| `long_today` | 多头今仓 |
| `short_today` | 空头今仓 |
| `long_yd` | 多头昨仓 |
| `short_yd` | 空头昨仓 |

**示例：**

```python
detail = api.get_position_detail()
print(f"多头: {detail['long_pos']} (今:{detail['long_today']} 昨:{detail['long_yd']})")
print(f"空头: {detail['short_pos']} (今:{detail['short_today']} 昨:{detail['short_yd']})")
print(f"净持仓: {detail['net_pos']}")
```

---

## 交易操作API

### api.buy()

买入开仓（做多）。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `volume` | int | 1 | 手数 |
| `reason` | str | "" | 交易原因 |
| `order_type` | str | 'bar_close' | 订单类型 |
| `index` | int | 0 | 数据源索引 |
| `offset_ticks` | int/None | None | 价格偏移 |

**order_type 选项：**

| 值 | 回测成交价 | 实盘委托 |
|----|----------|---------|
| `'bar_close'` | 当前K线收盘价 | 当前价 |
| `'next_bar_open'` | 下一K线开盘价 | 等下一根K线 |
| `'next_bar_close'` | 下一K线收盘价 | 等下一根K线 |
| `'next_bar_high'` | 下一K线最高价 | 条件单 |
| `'next_bar_low'` | 下一K线最低价 | 条件单 |
| `'market'` | 对价成交 | 市价/超价委托 |
| `'limit'` | (不支持) | 限价单 |

**注意：**
- 当 `order_type='limit'` 时，必须提供 `price` 参数。
- 也可以不指定 `order_type`，直接提供 `price` 参数，框架会自动识别为限价单。

**示例：**

```python
# 基础用法
api.buy(volume=1, order_type='next_bar_open')

# 带原因
api.buy(volume=1, reason='金叉信号', order_type='next_bar_open')

# 实盘超价委托 (市价单)
api.buy(volume=1, order_type='market', offset_ticks=10)

# 限价单 (Limit Order) - 挂单排队
api.buy(volume=1, price=3500.0)
# 或者
api.buy(volume=1, order_type='limit', price=3500.0)

# 多数据源
api.buy(volume=1, order_type='next_bar_open', index=1)
```

---

### api.sell()

卖出平仓（平多）。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `volume` | int/None | None | 手数，None=平所有多仓 |
| `reason` | str | "" | 交易原因 |
| `order_type` | str | 'bar_close' | 订单类型 |
| `index` | int | 0 | 数据源索引 |
| `offset_ticks` | int/None | None | 价格偏移 |
| `price` | float/None | None | 限价单价格 |

**示例：**

```python
# 平所有多仓
api.sell(order_type='next_bar_open')

# 平指定手数
api.sell(volume=2, order_type='next_bar_open')

# 限价平仓
api.sell(volume=1, price=3600.0)

# 带止损原因
api.sell(order_type='next_bar_open', reason='止损')
```

---

### api.sellshort()

卖出开仓（做空）。

**参数：** 同 `api.buy()`

**示例：**

```python
api.sellshort(volume=1, order_type='next_bar_open')
```

---

### api.buycover()

买入平仓（平空）。

**参数：** 同 `api.sell()`

**示例：**

```python
# 平所有空仓
api.buycover(order_type='next_bar_open')
```

---

### api.buytocover()

同 `api.buycover()`，别名。

---

### api.close_all()

平掉所有持仓（多头和空头）。

**参数：**
- `reason` (str): 交易原因
- `order_type` (str): 订单类型
- `index` (int): 数据源索引

**示例：**

```python
api.close_all(order_type='next_bar_open', reason='收盘平仓')
```

---

### api.reverse_pos()

反手（多转空，空转多）。

**示例：**

```python
# 如果当前持多仓，会平多开空
# 如果当前持空仓，会平空开多
api.reverse_pos(order_type='next_bar_open')
```

---

## TICK数据API

> ⚠️ TICK数据仅在 SIMNOW/实盘 模式下可用，回测模式返回None

### api.get_tick(index=0)

获取当前TICK数据。

**返回：**
- `dict/None`: TICK数据字典，回测模式返回None

**常用字段：**

| 字段 | 说明 |
|------|------|
| `LastPrice` | 最新价 |
| `OpenPrice` | 开盘价 |
| `HighestPrice` | 最高价 |
| `LowestPrice` | 最低价 |
| `AskPrice1` | 卖一价 |
| `BidPrice1` | 买一价 |
| `AskVolume1` | 卖一量 |
| `BidVolume1` | 买一量 |
| `Volume` | 累计成交量 |
| `OpenInterest` | 持仓量 |
| `TradingDay` | 交易日 |
| `UpdateTime` | 时间(HH:MM:SS) |
| `UpdateMillisec` | 毫秒 |

**示例：**

```python
tick = api.get_tick()
if tick:
    print(f"最新价: {tick.get('LastPrice', 0):.2f}")
    print(f"卖一: {tick.get('AskPrice1', 0):.2f}")
    print(f"买一: {tick.get('BidPrice1', 0):.2f}")
```

---

### api.get_ticks(window=100, index=0)

获取最近N个TICK数据。

**参数：**
- `window` (int): 窗口大小，默认100
- `index` (int): 数据源索引

**返回：**
- `pd.DataFrame`: TICK数据表

**示例：**

```python
ticks = api.get_ticks(window=50)
print(f"最近50个TICK的平均价: {ticks['LastPrice'].mean():.2f}")
```

---

### api.get_ticks_count(index=0)

获取当前缓存的TICK数据总数。

**返回：**
- `int`: TICK数据条数

**示例：**

```python
tick_count = api.get_ticks_count()
all_ticks = api.get_ticks(window=tick_count)
```

---

## 多数据源API

### api.get_data_sources_count()

获取数据源数量。

**返回：**
- `int`: 数据源数量

---

### api.get_data_source(index)

获取指定数据源对象。

**返回：**
- `DataSource`: 数据源对象

**示例：**

```python
ds = api.get_data_source(0)
print(ds.symbol)        # 品种代码
print(ds.kline_period)  # K线周期
```

---

### api.require_data_sources(count)

确保至少有指定数量的数据源。

**参数：**
- `count` (int): 最少数量

**返回：**
- `bool`: 是否满足要求

**示例：**

```python
def multi_symbol_strategy(api):
    # 确保至少有2个数据源
    if not api.require_data_sources(2):
        return
    
    # 继续策略逻辑...
```

---

### 访问不同数据源

所有数据和交易API都支持 `index` 参数：

```python
# 配置多数据源
config = get_config(
    mode=RunMode.BACKTEST,
    data_sources=[
        {'symbol': 'rb888', 'kline_period': '1h'},
        {'symbol': 'i888', 'kline_period': '1h'},
    ],
)

# 策略中访问
def multi_strategy(api):
    # 第一个品种（rb）index=0
    close_rb = api.get_close(index=0)
    pos_rb = api.get_pos(index=0)
    api.buy(volume=1, index=0)
    
    # 第二个品种（i）index=1
    close_i = api.get_close(index=1)
    pos_i = api.get_pos(index=1)
    api.buy(volume=1, index=1)
```

---

## 参数和日志API

### api.get_param(key, default=None)

获取策略参数。

**参数：**
- `key` (str): 参数名
- `default`: 默认值

**示例：**

```python
# 运行时传入参数
runner.run(
    strategy=my_strategy,
    strategy_params={'ma_period': 20, 'stop_loss': 0.05}
)

# 策略中获取
ma_period = api.get_param('ma_period', 20)
stop_loss = api.get_param('stop_loss', 0.05)
```

---

### api.get_params()

获取所有参数。

**返回：**
- `dict`: 参数字典

---

### api.log(message)

记录日志。

**参数：**
- `message` (str): 日志消息

**示例：**

```python
api.log("策略开始执行")
api.log(f"当前价格: {price:.2f}, 持仓: {pos}")
```

---

## 实盘专用API

### api.cancel_all_orders(index=0)

撤销所有未成交订单。

**注意：**
- 仅实盘/SIMNOW有效
- 回测模式无效果

**示例：**

```python
# 撤销所有订单
api.cancel_all_orders()

# 等待撤单完成
import time
time.sleep(0.3)

# 重新下单
api.buy(volume=1, order_type='market')
```

---

### offset_ticks 参数

在下单时临时指定价格偏移，覆盖配置中的 `order_offset_ticks`。

**委托价格计算：**

```
买入委托价 = 卖一价 + offset_ticks × price_tick
卖出委托价 = 买一价 - offset_ticks × price_tick
```

**示例：**

```python
# 使用配置中的order_offset_ticks
api.buy(volume=1, order_type='market')

# 临时超价委托（快速成交）
api.buy(volume=1, order_type='market', offset_ticks=10)

# 临时限价委托（降低成本）
api.buy(volume=1, order_type='market', offset_ticks=-5)
```

---

## 回调函数

> 回调函数仅在 SIMNOW/实盘 模式下有效

### on_trade(data)

成交回调，当订单成交时触发。

**参数 data 字段：**

| 字段 | 说明 | 类型 |
|------|------|------|
| TradeID | 成交编号 | str |
| InstrumentID | 合约代码 | str |
| Direction | 方向('0'=买,'1'=卖) | str |
| OffsetFlag | 开平('0'=开,'1'=平,'3'=平今,'4'=平昨) | str |
| Price | 成交价格 | float |
| Volume | 成交数量 | int |
| TradeTime | 成交时间 | str |
| TradeDate | 成交日期 | str |

**示例：**

```python
def on_trade(data):
    direction = '买' if data['Direction'] == '0' else '卖'
    offset = '开' if data['OffsetFlag'] == '0' else '平'
    print(f"成交: {data['InstrumentID']} {direction}{offset} "
          f"{data['Volume']}手 @{data['Price']:.2f}")

runner.run(
    strategy=my_strategy,
    on_trade=on_trade
)
```

---

### on_order(data)

报单回调，当报单状态变化时触发。

**参数 data 字段：**

| 字段 | 说明 |
|------|------|
| OrderSysID | 订单编号 |
| InstrumentID | 合约代码 |
| Direction | 方向 |
| OrderStatus | 状态 |
| LimitPrice | 委托价格 |
| VolumeTotalOriginal | 委托数量 |
| VolumeTraded | 已成交数量 |
| StatusMsg | 状态消息 |

**OrderStatus 值：**
- `'0'`: 全部成交
- `'1'`: 部分成交
- `'3'`: 未成交
- `'5'`: 撤单

---

### on_cancel(data)

撤单回调，当订单被撤销时触发。

**示例：**

```python
def on_cancel(data):
    symbol = data['InstrumentID']
    print(f"撤单: {symbol}")
    
    # 可以在这里重新下单（追价）
    # api.buy(volume=1, order_type='market', offset_ticks=10)
```

---

### on_order_error(data)

报单错误回调，当报单失败时触发。

---

### on_cancel_error(data)

撤单错误回调，当撤单失败时触发。

---

### on_account(data)

账户资金回调，资金变化时触发。

---

### on_position(data)

持仓回调，持仓变化时触发。

---

### 注册回调

```python
runner.run(
    strategy=my_strategy,
    on_trade=on_trade,
    on_order=on_order,
    on_cancel=on_cancel,
    on_order_error=on_order_error,
    on_cancel_error=on_cancel_error,
    on_account=on_account,
    on_position=on_position,
)
```

---

## 完整示例

### 双均线策略（带止损）

```python
from ssquant.api.strategy_api import StrategyAPI

# 全局变量
g_entry_price = 0
g_stop_loss_pct = 0.05  # 5%止损

def my_ma_strategy(api: StrategyAPI):
    """双均线策略 + 止损"""
    global g_entry_price
    
    close = api.get_close()
    
    if len(close) < 20:
        return
    
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    pos = api.get_pos()
    current_price = close.iloc[-1]
    
    # 止损逻辑
    if pos > 0 and g_entry_price > 0:
        if current_price < g_entry_price * (1 - g_stop_loss_pct):
            api.sell(order_type='next_bar_open', reason='止损')
            api.log(f"止损: {current_price:.2f} < {g_entry_price * 0.95:.2f}")
            g_entry_price = 0
            return
    
    # 金叉
    if ma5.iloc[-2] <= ma20.iloc[-2] and ma5.iloc[-1] > ma20.iloc[-1]:
        if pos <= 0:
            if pos < 0:
                api.buycover(order_type='next_bar_open')
            api.buy(volume=1, order_type='next_bar_open')
            g_entry_price = current_price
            api.log(f"金叉开多 @{current_price:.2f}")
    
    # 死叉
    elif ma5.iloc[-2] >= ma20.iloc[-2] and ma5.iloc[-1] < ma20.iloc[-1]:
        if pos >= 0:
            if pos > 0:
                api.sell(order_type='next_bar_open')
            api.sellshort(volume=1, order_type='next_bar_open')
            g_entry_price = current_price
            api.log(f"死叉开空 @{current_price:.2f}")
```

### 多品种策略

```python
def multi_symbol_strategy(api: StrategyAPI):
    """多品种策略"""
    if not api.require_data_sources(2):
        return
    
    for i in range(api.get_data_sources_count()):
        close = api.get_close(index=i)
        
        if len(close) < 20:
            continue
        
        ma20 = close.rolling(20).mean()
        pos = api.get_pos(index=i)
        
        if close.iloc[-1] > ma20.iloc[-1] and pos <= 0:
            if pos < 0:
                api.buycover(order_type='next_bar_open', index=i)
            api.buy(volume=1, order_type='next_bar_open', index=i)
        
        elif close.iloc[-1] < ma20.iloc[-1] and pos >= 0:
            if pos > 0:
                api.sell(order_type='next_bar_open', index=i)
            api.sellshort(volume=1, order_type='next_bar_open', index=i)
```

---

## 最佳实践

### 1. 数据验证

```python
def my_strategy(api):
    # 检查索引
    if api.get_idx() < 20:
        return
    
    close = api.get_close()
    
    # 检查长度
    if len(close) < 20:
        return
    
    # 继续策略逻辑...
```

### 2. 安全的持仓操作

```python
def safe_strategy(api):
    pos = api.get_pos()
    
    # 开仓前先平掉反向持仓
    if buy_signal and pos <= 0:
        if pos < 0:
            api.buycover(order_type='next_bar_open')
        api.buy(volume=1, order_type='next_bar_open')
```

### 3. 日志调试

```python
def debug_strategy(api):
    close = api.get_close()
    pos = api.get_pos()
    idx = api.get_idx()
    
    # 定期打印状态
    if idx % 100 == 0:
        api.log(f"Bar {idx}: 价格={close.iloc[-1]:.2f}, 持仓={pos}")
```

---

查看更多示例：`examples/` 目录
