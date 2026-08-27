# SSQuant v0.4.6 AI 策略开发指南

> **Version**: 0.4.6
> **Purpose**: 让任何 AI Agent 在阅读本文件后，能够理解 SSQuant 全貌，并安全编写、修改、运行期货策略（回测 / SIMNOW / CTP 实盘）。

---

## 0. AI 必读结论

SSQuant 是中国期货 CTP 专业量化交易框架，支持一套策略代码运行于：

- `RunMode.BACKTEST`：历史回测
- `RunMode.SIMNOW`：SIMNOW 仿真
- `RunMode.REAL_TRADING`：CTP 实盘

AI 编写策略时必须遵守：

1. 策略只通过 `StrategyAPI` 访问数据、下单、查询账户。
2. 不直接操作底层 CTP 接口。
3. 默认必须写 `initialize(api)`。
4. 默认必须在 `initialize(api)` 中用 `api.register_indicator()` 注册指标。
5. `strategy(api)` 中只做 O(1) 查询和交易判断。
6. 优先参考 `examples/*_高性能.py`，不要凭空发明框架接口。
7. TICK 回测必须使用 `data_source_mode='local'`。
8. 实盘/SIMNOW 策略应捕获关键异常，避免单根 K 线错误导致进程退出。

v0.4.6 特别重要：

> 复权连续合约采用价格双轨制：策略使用复权价格保持指标连续性，框架通过 `_adjust_factor` 映射真实价格，并用真实价格计算回测指标、持仓盯市、权益曲线和报告统计。

AI 不需要手动处理价格双轨制；按正常策略价写策略即可。

---

## 1. 项目全貌速览

| 主题 | AI 必须知道 |
|---|---|
| 框架定位 | 中国期货 CTP，回测/SIMNOW/实盘三模式 |
| 策略入口 | `StrategyAPI` 是唯一入口 |
| 运行入口 | `UnifiedStrategyRunner` + `RunMode` |
| 默认写法 | `initialize(api)` 注册指标，`strategy(api)` 查询指标 |
| 性能原则 | 不在每根 K 线重复 Pandas rolling |
| 数据模式 | `data_server` 远程数据，`local` 本地 SQLite |
| 连续合约 | `888` 主力连续，`777` 次主力连续 |
| 复权 | `adjust_type='0'` 不复权，`'1'` 后复权，`'2'` 前复权 |
| v0.4.6 | 价格双轨制，映射真实价格计算回测指标 |
| 示例保障 | `examples/` 覆盖约 80% 常见策略类型，AI 应优先参考 |
| AI Agent | `ai_agent/start_server.py` 是生产启动入口 |

---

## 2. 核心导入

每个策略通常需要：

```python
import pandas as pd
import numpy as np

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config
```

不要自己创建 `DataSource` 或直接操作 CTP API。策略运行时框架会注入 `api: StrategyAPI`。

---

## 3. StrategyAPI 是唯一接口

策略函数只和 `api` 交互。

### 3.1 交易接口

```python
api.buy(volume=1, reason="开多", order_type="next_bar_open")
api.sell(volume=1, reason="平多", order_type="next_bar_open")
api.sellshort(volume=1, reason="开空", order_type="next_bar_open")
api.buycover(volume=1, reason="平空", order_type="next_bar_open")
api.close_all(reason="全部平仓", order_type="next_bar_open")
```

多数据源时必须显式传 `index=i`：

```python
api.buy(volume=1, index=i)
api.sellshort(volume=1, index=i)
```

### 3.2 数据接口

```python
price = api.get_price()
close = api.get_close()
open_ = api.get_open()
high = api.get_high()
low = api.get_low()
volume = api.get_volume()
klines = api.get_klines()
refresh_sent = api.refresh_klines(index=0, preload=500)  # 仅 SIMNOW/实盘 data_server
idx = api.get_idx()
dt = api.get_datetime()
```

### 3.3 仓位和账户

```python
pos = api.get_pos()
long_pos = api.get_long_pos()
short_pos = api.get_short_pos()

account = api.get_account()
balance = api.get_balance()
available = api.get_available()
margin = api.get_margin()
commission = api.get_commission()
```

不要手动修改账户字典、仓位对象或成交列表。

---

## 4. 高性能指标系统

AI 默认应该使用 IndicatorCache v2。

### 4.1 推荐写法

```python
def initialize(api: StrategyAPI):
    api.register_indicator(
        "ma20",
        lambda c, o, h, l, v: pd.Series(c).rolling(20).mean().to_numpy(),
        window=20,
    )

def strategy(api: StrategyAPI):
    ma20 = api.get_indicator("ma20")
    price = api.get_price()
    if pd.isna(ma20):
        return
    if price > ma20 and api.get_pos() <= 0:
        api.buy(volume=1)
```

### 4.2 多数据源指标

注册和读取时使用 `index=i`：

```python
def initialize(api: StrategyAPI):
    for i in range(api.get_data_sources_count()):
        api.register_indicator(
            "ma20",
            lambda c, o, h, l, v: pd.Series(c).rolling(20).mean().to_numpy(),
            window=20,
            index=i,
        )

def strategy(api: StrategyAPI):
    for i in range(api.get_data_sources_count()):
        ma20 = api.get_indicator("ma20", index=i)
        price = api.get_price(index=i)
```

### 4.3 什么时候允许 Pandas fallback

只有以下情况才在 `strategy(api)` 中临时用 Pandas：

- 动态窗口依赖实时状态，无法提前注册。
- 复杂跨品种状态机无法表达为单个滚动指标。
- 临时研究验证，性能不重要。

生产策略默认不要每根 K 线写：

```python
api.get_close().rolling(20).mean().iloc[-1]
```

---

## 5. 标准策略模板

AI 生成新策略时优先使用此模板。

```python
import pandas as pd
import numpy as np

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config


def initialize(api: StrategyAPI):
    api.log("策略初始化")
    api.register_indicator(
        "ma20",
        lambda c, o, h, l, v: pd.Series(c).rolling(20).mean().to_numpy(),
        window=20,
    )


def strategy(api: StrategyAPI):
    try:
        price = api.get_price()
        ma20 = api.get_indicator("ma20")

        if pd.isna(ma20):
            return

        pos = api.get_pos()
        if price > ma20 and pos <= 0:
            api.buy(volume=1, order_type="next_bar_open", reason="上穿 MA20")
        elif price < ma20 and pos > 0:
            api.sell(order_type="next_bar_open", reason="下穿 MA20")
    except Exception as e:
        api.log(f"策略运行异常: {e}")


if __name__ == "__main__":
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {}

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(
            RUN_MODE,
            symbol="rb888",
            kline_period="1h",
            start_date="2024-01-01",
            end_date="2025-01-01",
            adjust_type="1",
            data_source_mode="data_server",
            initial_capital=100000,
            lookback_bars=500,
        )
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(
            RUN_MODE,
            account="simnow_default",
            symbol="rb888",
            kline_period="5m",
            kline_source="local",
            lookback_bars=500,
        )
    elif RUN_MODE == RunMode.REAL_TRADING:
        config = get_config(
            RUN_MODE,
            account="real_default",
            symbol="rb888",
            kline_period="5m",
            kline_source="data_server",
            lookback_bars=500,
        )

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)
    runner.run(strategy=strategy, initialize=initialize, strategy_params=strategy_params)
```

---

## 6. 数据模式

AI 必须区分三类配置：俱乐部远程数据账号、本地数据模式、CTP 交易账户。它们用途不同，填写位置和是否必需也不同。详细见第 7 节。

### 6.1 远程数据：`data_source_mode='data_server'`

适合有 quant789 远程数据账号的用户。

特点：

- 远程服务器维护历史 K 线和实时 K 线。
- 回测和实盘预加载可直接拉取数据。
- 支持订单流和深度数据。

```python
config = get_config(
    RunMode.BACKTEST,
    symbol="rb888",
    kline_period="15m",
    data_source_mode="data_server",
)
```

### 6.2 本地数据：`data_source_mode='local'`

适合本地 SQLite、离线回测、私有数据和 Tick 回测。

```python
config = get_config(
    RunMode.BACKTEST,
    symbol="rb888",
    kline_period="15m",
    data_source_mode="local",
)
```

导入数据参考：

```bash
python examples/A_工具_导入数据库DB示例.py
```

### 6.3 Tick 回测

Tick 回测必须使用 local：

```python
config = get_config(
    RunMode.BACKTEST,
    symbol="rb888",
    kline_period="tick",
    data_source_mode="local",
)
```

不要让 AI 写 Tick 回测时使用 `data_server`。

---

## 7. 账户与配置填写位置

SSQuant 里最容易混淆的是“远程数据账号、本地数据、CTP 账户”。AI 必须先判断用户当前需要哪一种。

### 7.1 俱乐部远程数据账号

用途：

- `data_source_mode='data_server'` 的历史数据回测。
- `kline_source='data_server'` 的 SIMNOW/实盘 K 线。
- 订单流和深度数据。
- 远程 WebSocket K 线推送。

填写位置：

```text
ssquant/config/trading_config.py
```

典型字段：

```python
API_USERNAME = "你的俱乐部手机号或邮箱"
API_PASSWORD = "你的俱乐部密码"
```

AI 必须知道：

- 俱乐部账号不是 CTP 交易账户。
- 没有俱乐部账号时，可以使用 `data_source_mode='local'`。
- data_server 鉴权失败时，先检查 `API_USERNAME` / `API_PASSWORD`。
- 订单流和深度数据属于 data_server 能力，通常需要远程数据账号支持。

### 7.2 本地模式

用途：

- 本地 SQLite 历史数据。
- 离线回测。
- Tick 回测。
- 用户自己的 CSV/Excel/Parquet/Feather/Pickle 数据。

是否需要账号：

- 不需要俱乐部远程数据账号。
- 不需要 CTP 交易账户。
- 但需要先导入本地数据，或通过 SIMNOW/实盘 CTP Tick 落盘积累数据。

数据位置：

```text
data_cache/backtest_data.db
```

导入工具：

```bash
python examples/A_工具_导入数据库DB示例.py
```

配置示例：

```python
config = get_config(
    RunMode.BACKTEST,
    symbol="rb888",
    kline_period="15m",
    data_source_mode="local",
)
```

AI 必须知道：

- Tick 回测必须使用 `data_source_mode='local'`。
- 本地模式回测无数据时，优先检查是否导入了对应合约、周期、日期范围。
- 如果只导入 1m K 线，框架可通过 `multi_period.py` 派生 5m/15m/1h 等周期。

### 7.3 SIMNOW CTP 账户

用途：

- SIMNOW 模拟交易。
- CTP 行情订阅。
- CTP 模拟下单。

填写位置：

```text
ssquant/config/trading_config.py
```

典型配置名：

```python
account = "simnow_default"
```

AI 应提醒用户在 `trading_config.py` 中填写或检查：

- broker_id
- investor_id
- password
- md_server
- td_server
- app_id
- auth_code
- user_product_info

配置示例：

```python
config = get_config(
    RunMode.SIMNOW,
    account="simnow_default",
    symbol="rb888",
    kline_period="5m",
    kline_source="local",
)
```

AI 必须知道：

- SIMNOW 账户不是俱乐部远程数据账号。
- `kline_source='local'` 表示 K 线由本地 CTP Tick 合成或从本地 SQLite 预加载。
- `kline_source='data_server'` 表示 K 线来自远程 data_server，此时还需要俱乐部远程数据账号。

### 7.4 实盘 CTP 账户

用途：

- 真实期货公司 CTP 实盘交易。
- 真实资金下单。

填写位置：

```text
ssquant/config/trading_config.py
```

典型配置名：

```python
account = "real_default"
```

AI 应提醒用户在 `trading_config.py` 中填写或检查：

- broker_id
- investor_id
- password
- md_server
- td_server
- app_id
- auth_code
- user_product_info

配置示例：

```python
config = get_config(
    RunMode.REAL_TRADING,
    account="real_default",
    symbol="rb888",
    kline_period="5m",
    kline_source="data_server",
)
```

AI 必须知道：

- 实盘 CTP 账户和俱乐部远程数据账号完全不同。
- 实盘前必须先跑通 SIMNOW。
- 实盘策略应捕获异常。
- 不确定账户字段时，打开 `ssquant/config/trading_config.py` 和 `ssquant/config/config_helpers.py`。

### 7.5 AI 判断规则

用户说“没有会员账号”：

- 推荐 `data_source_mode='local'`。
- 提醒先导入本地数据。

用户说“我要 SIMNOW/实盘”：

- 需要 CTP 账户配置。
- 如果 K 线来源选 `data_server`，还需要俱乐部远程数据账号。
- 如果 K 线来源选 `local`，不需要俱乐部账号，但本地要有历史 K 线或允许 CTP Tick 生成。

用户说“回测无数据”：

- 先检查 `data_source_mode`。
- `data_server` 检查 `API_USERNAME` / `API_PASSWORD`。
- `local` 检查 `data_cache/backtest_data.db` 和导入数据。

---

## 8. 连续合约与复权

连续合约约定：

| 后缀 | 含义 |
|---|---|
| `888` | 主力连续 |
| `777` | 次主力连续 |

复权类型：

| 参数 | 含义 |
|---|---|
| `adjust_type="0"` | 不复权 |
| `adjust_type="1"` | 后复权 |
| `adjust_type="2"` | 前复权 |

AI 不应写 `000` 指数连续；当前项目约定中没有 `000`。

---

## 9. v0.4.6 价格双轨制

v0.4.6 起，复权连续合约回测采用价格双轨制。

| 字段 | 含义 | 用途 |
|---|---|---|
| `price` / `current_price` | 策略价，通常是复权价 | 指标、信号、图表、限价触发 |
| `raw_price` / `current_raw_price` | 映射真实价格 | 回测指标、持仓盯市、权益曲线、报告统计 |

实现概念：

```text
raw = adjusted / _adjust_factor
```

AI 写策略时：

- 使用 `api.get_price()`、`api.get_close()`、`api.get_indicator()` 写策略信号。
- 不手动读取或计算 `_adjust_factor`。
- 不手动维护 `raw_price`。
- 不把 `raw_price` 当作策略指标输入。
- 回测指标由框架自动按映射真实价格计算。

复权回测的指标和 v0.4.5 不一致是预期修正。

---

## 10. 回测报告

回测会生成文本报告和 HTML 报告。

v0.4.6 HTML 报告增强：

- K 线/Tick 交互图。
- 交易标记。
- 交易表格筛选和分页。
- 多数据源综合页。
- 手续费、滑点、交易盈亏、净利润。
- 复权价与映射真实价不一致时显示“实际价”。
- 综合最大回撤按综合权益曲线计算。

AI 分析报告时应优先看：

- 总收益率。
- 年化收益率。
- 最大回撤。
- 夏普比率。
- 交易次数。
- 手续费和滑点。
- 交易明细。
- 是否存在过拟合或交易过少。

---

## 11. examples 是策略保障

`examples/` 是 SSQuant 最重要的上手保障之一，覆盖约 80% 常见期货策略类型。新手必须先跑通示例策略；AI 写策略前必须优先参考最接近的示例。

### 11.1 示例覆盖类型

| 类型 | 示例 |
|---|---|
| 数据工具 | `A_工具_导入数据库DB示例.py` |
| 数据管理 | `A_工具_数据库管理_查看与删除.py` |
| CTP 连接 | `A_CTP连接状态监测测试_真实断网.py` |
| 撤单重发 | `A_撤单重发示例.py` |
| 穿透式测试 | `A_穿透式测试脚本.py` |
| 双均线 | `B_双均线策略_高性能.py` |
| 海龟/通道突破 | `B_海龟交易策略_高性能.py` |
| Aberration | `B_十大经典策略之Aberration_高性能.py` |
| 日内交易 | `B_日内交易策略.py` |
| 网格 | `B_网格交易策略.py` |
| 加仓 | `B_加仓策略_高性能.py` |
| 减仓 | `B_减仓策略_高性能.py` |
| 正反手 | `B_正反手策略_高性能.py` |
| 混合开平仓 | `B_正反手混合开平仓策略_高性能.py` |
| 多品种多周期 | `B_多品种多周期交易策略_高性能.py` |
| 参数优化 | `B_自动参数示例.py`、`B_多品种多周期交易策略_参数优化.py` |
| 自动换月 | `B_自动换月示例.py` |
| 跨周期过滤 | `B_跨周期过滤策略_高性能.py` |
| 跨品种套利 | `B_跨品种套利策略_高性能.py` |
| 跨期套利 | `B_跨期套利策略_高性能.py` |
| 截面轮动 | `B_强弱截面轮动策略_高性能.py` |
| 机器学习 | `B_机器学习策略_随机森林_高性能.py` |
| Tick 高频 | `C_纯Tick高频交易策略.py` |
| Tick 限价单 | `C_纯Tick限价单交易策略.py` |
| 期权 | `C_期权交易策略.py` |
| 期货期权组合 | `C_期货期权组合策略.py` |
| 订单流和深度数据 | `D_订单流与深度数据_data_server模式.py` |

### 11.2 新手推荐顺序

1. `A_工具_导入数据库DB示例.py`
2. `B_双均线策略_高性能.py`
3. `B_海龟交易策略_高性能.py`
4. `B_多品种多周期交易策略_高性能.py`
5. `B_自动参数示例.py`
6. 根据方向选择套利、Tick、期权、机器学习或订单流示例。

### 11.3 AI 使用 examples 的规则

AI 写策略前：

- 先找最接近的示例。
- 优先参考高性能版。
- 复用其导入、函数结构、Runner 配置。
- 不确定接口时打开示例，不要猜。
- 用户需求属于常见类型时，尽量从示例改造，而不是从零写。

---

## 12. 参数优化

参考：

- `examples/B_自动参数示例.py`
- `examples/B_多品种多周期交易策略_参数优化.py`

AI 写参数优化时要注意：

- 优化期间应减少日志和报告生成。
- 参数网格不要过大。
- 回测数据要足够长。
- 优化结果必须再用独立时间段验证。

---

## 13. SIMNOW / 实盘注意事项

### 13.1 SIMNOW

```python
config = get_config(
    RunMode.SIMNOW,
    account="simnow_default",
    symbol="rb888",
    kline_period="5m",
    kline_source="local",
)
```

### 13.2 实盘

```python
config = get_config(
    RunMode.REAL_TRADING,
    account="real_default",
    symbol="rb888",
    kline_period="5m",
    kline_source="data_server",
)
```

实盘策略必须注意：

- 捕获关键异常。
- 不要频繁撤单重发。
- 平今/平昨依赖交易所推导，未知品种应先补合约信息。
- 先 SIMNOW 跑通，再小资金实盘。

---

## 14. AI 任务流程

AI 接到用户任务时，应按任务类型执行固定流程。

### 14.1 用户要“写一个策略”

执行顺序：

1. 判断策略类型：趋势、均值回归、套利、网格、Tick、期权、订单流、机器学习等。
2. 在 `examples/` 中找最接近的示例。
3. 优先选择 `*_高性能.py` 示例作为模板。
4. 写 `initialize(api)` 注册指标。
5. 写 `strategy(api)` 做 O(1) 查询和交易判断。
6. 用 `get_config()` 配置回测。
7. 用 `UnifiedStrategyRunner` 运行。
8. 运行前做 `py_compile`。
9. 如果用户要求，实际运行回测并读取报告。

不能做：

- 不要从其他量化框架复制 API。
- 不要直接操作 CTP。
- 不要手动维护账户、仓位、成交列表。
- 不要手动处理价格双轨制。

### 14.2 用户要“跑回测”

执行顺序：

1. 确认策略文件或策略代码。
2. 确认 `RunMode.BACKTEST`。
3. 确认 `symbol`、`kline_period`、`start_date`、`end_date`。
4. 确认 `data_source_mode`。
5. 若 `data_server`，检查俱乐部账号配置。
6. 若 `local`，检查本地数据是否导入。
7. 运行回测。
8. 读取 HTML/文本报告。
9. 总结收益、回撤、交易次数、手续费、滑点、异常。

如果无数据：

- `data_server`：检查 `API_USERNAME` / `API_PASSWORD`。
- `local`：检查 `data_cache/backtest_data.db` 和导入范围。
- Tick：确认必须 `local`。

### 14.3 用户要“优化参数”

执行顺序：

1. 确认待优化参数和范围。
2. 控制网格大小，不要爆炸。
3. 优先参考 `examples/B_自动参数示例.py`。
4. 优化阶段减少报告和日志。
5. 记录最优参数。
6. 用独立时间段复验。
7. 不要只看收益，必须看最大回撤、交易次数、费用、滑点。

### 14.4 用户要“改成 SIMNOW”

执行顺序：

1. 保留 `initialize(api)` 和 `strategy(api)` 主体。
2. 将 `RUN_MODE` 改为 `RunMode.SIMNOW`。
3. 配置 `account="simnow_default"`。
4. 配置 `symbol`、`kline_period`。
5. 选择 `kline_source`：
   - `local`：使用本地 CTP Tick 合成/预加载。
   - `data_server`：使用远程 K 线，需要俱乐部账号。
6. 确认 `trading_config.py` 中 SIMNOW CTP 账户填写完整。
7. 增加异常保护。
8. 先小频率、低风险运行。

### 14.5 用户要“改成实盘”

执行顺序：

1. 确认用户明确要求实盘。
2. 确认策略已经回测和 SIMNOW 跑通过。
3. 将 `RUN_MODE` 改为 `RunMode.REAL_TRADING`。
4. 配置 `account="real_default"`。
5. 确认 `trading_config.py` 中实盘 CTP 账户完整。
6. 确认合约、交易所、乘数、最小变动价位。
7. 确认平今/平昨映射可用。
8. 增加异常保护和日志。
9. 降低下单频率，避免频繁撤单。
10. 提醒用户先小资金验证。

AI 不应在用户没有明确要求时主动改成实盘。

### 14.6 用户要“排查问题”

按问题类型打开文件：

| 问题 | 优先检查 |
|---|---|
| 策略接口报错 | `ssquant/api/strategy_api.py`、最接近的 `examples/` |
| 回测主循环异常 | `ssquant/backtest/backtest_core.py` |
| 指标/报告异常 | `ssquant/backtest/backtest_results.py`、`html_report.py` |
| 无数据 | `ssquant/data/api_data_fetcher.py`、`local_data_loader.py` |
| 复权/价格双轨 | `ssquant/data/local_adjust.py`、`data_source.py` |
| SIMNOW/实盘 | `live_trading_adapter.py`、`pyctp/` |
| CTP 加载失败 | `ssquant/ctp/loader.py` |

---

## 15. 回测到 SIMNOW/实盘迁移清单

### 15.1 回测策略迁移前检查

- [ ] 策略主体只使用 `StrategyAPI`。
- [ ] 指标已在 `initialize(api)` 注册。
- [ ] `strategy(api)` 中没有重计算大型 Pandas rolling。
- [ ] 策略没有直接读取或修改内部账户/仓位。
- [ ] 策略没有直接使用底层 CTP API。
- [ ] 策略有关键异常保护。
- [ ] 回测交易次数合理，不是靠极少交易偶然盈利。
- [ ] 手续费和滑点已设置。
- [ ] 最大回撤可接受。

### 15.2 迁移到 SIMNOW

配置清单：

- [ ] `RUN_MODE = RunMode.SIMNOW`
- [ ] `account="simnow_default"`
- [ ] `symbol` 使用 `rb888` 等连续合约或实际合约。
- [ ] `kline_period` 合理。
- [ ] `kline_source` 明确选择 `local` 或 `data_server`。
- [ ] `trading_config.py` 中 SIMNOW 账号字段完整。
- [ ] 如果 `kline_source='data_server'`，俱乐部账号也已配置。
- [ ] 如果 `kline_source='local'`，本地历史 K 线可预加载，或允许 CTP Tick 合成。

运行检查：

- [ ] 能登录行情。
- [ ] 能登录交易。
- [ ] 能订阅合约。
- [ ] 能收到 Tick/K 线。
- [ ] 能正常下单。
- [ ] 能正常撤单。
- [ ] 日志正常。

### 15.3 迁移到实盘

实盘前必须：

- [ ] 已完成回测。
- [ ] 已完成 SIMNOW。
- [ ] 已运行穿透式测试。
- [ ] 用户明确确认进入实盘。
- [ ] 实盘账户配置完整。
- [ ] 合约信息、交易所、乘数、price_tick 正确。
- [ ] 平今/平昨偏移位可推导。
- [ ] 策略有异常保护。
- [ ] 下单频率受控。
- [ ] 风险资金和手数足够小。

实盘配置：

```python
config = get_config(
    RunMode.REAL_TRADING,
    account="real_default",
    symbol="rb888",
    kline_period="5m",
    kline_source="data_server",
)
```

AI 必须提醒：

- 实盘 CTP 账户不是俱乐部远程数据账号。
- `data_server` 只解决行情/K 线，不代表 CTP 交易账户已配置。
- 实盘有真实资金风险，不能只凭回测收益上线。

---

## 16. AI 自测验证流程

AI 写完策略后，应至少做以下验证。

### 16.1 静态检查

检查项：

- [ ] 是否导入 `StrategyAPI`。
- [ ] 是否导入 `UnifiedStrategyRunner` 和 `RunMode`。
- [ ] 是否导入 `get_config`。
- [ ] 是否存在 `initialize(api)`。
- [ ] 是否存在 `strategy(api)`。
- [ ] 是否使用 `api.register_indicator()`。
- [ ] 是否交易只用 `StrategyAPI`。
- [ ] 是否没有 `000` 连续合约。
- [ ] 是否没有直接操作 `DataSource` 内部字段。
- [ ] 是否没有直接操作 CTP API。
- [ ] Tick 回测是否 local。

### 16.2 语法检查

对生成策略文件运行：

```bash
python -m py_compile path/to/strategy.py
```

失败时先修语法，不要直接运行回测。

### 16.3 小样本回测检查

先用较短时间段运行：

- 数据能否加载。
- 指标是否 NaN 过久。
- 是否有交易。
- 是否报错。
- 报告能否生成。

### 16.4 报告检查

检查：

- 总收益率。
- 最大回撤。
- 交易次数。
- 手续费。
- 滑点。
- 每笔交易是否合理。
- 复权场景下报告指标是否按映射真实价计算。

### 16.5 AI 生成策略验收标准

合格策略至少满足：

- 能 `py_compile`。
- 能跑通回测。
- 有 HTML 报告。
- 不使用不存在的接口。
- 不绕过 `StrategyAPI`。
- 不手动处理价格双轨制。
- 能解释策略逻辑、参数、风险。

---

## 17. AI Agent

AI Agent 位于 `ai_agent/`。

v0.4.6 推荐启动：

```powershell
cd ai_agent
pip install -r requirements.txt
python start_server.py
```

访问：

```text
http://localhost:5000
```

说明：

- `start_server.py` 使用 waitress，适合 Windows 长时间运行。
- 不建议长期用 Flask 开发服务器。
- 支持 OpenAI 兼容模型和 Claude。
- 支持思考模型、附件上传、自动运行、自动调试、自动迭代。
- `settings.json`、`history.json`、`workspaces/`、`strategies/` 是运行数据，升级时不要无脑覆盖。

---

## 18. ssquant 源码职责地图

AI 不需要每次都读完整源码，但必须知道遇到问题该打开哪个文件。

### 18.1 顶层与 API

| 文件 | 职责 | AI 使用建议 |
|---|---|---|
| `ssquant/__init__.py` | 包版本、CTP 可用性检测 | 查版本和 CTP 状态 |
| `ssquant/api/strategy_api.py` | 策略唯一入口，封装数据、指标、交易、账户查询 | 写策略前优先查这里 |
| `ssquant/api/debug_utils.py` | 调试辅助工具 | 排查策略行为时参考 |
| `ssquant/api/__init__.py` | API 包初始化 | 通常不用改 |

### 18.2 回测与三模式运行

| 文件 | 职责 | AI 使用建议 |
|---|---|---|
| `ssquant/backtest/unified_runner.py` | 回测/SIMNOW/实盘三模式统一入口 | 查运行流程和 Runner 用法 |
| `ssquant/backtest/backtest_core.py` | 回测主循环，多数据源推进、账户汇总、报告生成 | 回测行为异常时查这里 |
| `ssquant/backtest/backtest_data.py` | 回测数据加载辅助 | 数据加载问题时参考 |
| `ssquant/backtest/backtest_results.py` | 权益曲线、绩效指标、交易统计 | 指标、回撤、收益计算问题查这里 |
| `ssquant/backtest/backtest_report.py` | 文本绩效报告生成 | 文本报告口径问题查这里 |
| `ssquant/backtest/html_report.py` | HTML 交互式报告 | 图表、交易表格、综合页问题查这里 |
| `ssquant/backtest/backtest_visualization.py` | 静态图、信号全景图、水印 | PNG 图或信号图问题查这里 |
| `ssquant/backtest/backtest_logger.py` | 回测日志和绩效文件路径管理 | 日志文件问题查这里 |
| `ssquant/backtest/function_api.py` | 函数式 API 辅助封装 | 兼容旧写法时参考 |
| `ssquant/backtest/multi_source_backtest.py` | 多数据源回测封装 | 多品种多周期回测问题查这里 |
| `ssquant/backtest/parameter_optimizer.py` | 参数优化 | 网格优化、优化报告问题查这里 |
| `ssquant/backtest/live_trading_adapter.py` | SIMNOW/实盘桥接，K 线/Tick、下单适配 | 实盘/SIMNOW 行为查这里 |
| `ssquant/backtest/rollover_engine.py` | 自动移仓引擎 | 主力换月逻辑查这里 |
| `ssquant/backtest/rollover_audit.py` | 移仓复盘日志 | 移仓审计和复盘查这里 |
| `ssquant/backtest/__init__.py` | backtest 包初始化 | 通常不用改 |

### 18.3 配置

| 文件 | 职责 | AI 使用建议 |
|---|---|---|
| `ssquant/config/trading_config.py` | 默认参数、账号配置、常量 | 用户账号/默认值问题查这里 |
| `ssquant/config/config_helpers.py` | `get_config()`、连续合约解析等配置逻辑 | 配置生成和三模式参数查这里 |
| `ssquant/config/_server_config.py` | data_server 连接配置 | 远程服务器地址和超时查这里 |
| `ssquant/config/path_config.py` | 路径配置 | 数据目录、缓存路径查这里 |
| `ssquant/config/__init__.py` | config 包初始化 | 通常不用改 |

### 18.4 数据层

| 文件 | 职责 | AI 使用建议 |
|---|---|---|
| `ssquant/data/data_source.py` | 回测数据源、撮合、账户状态、价格双轨映射 | 交易执行、`raw_price`、持仓盯市问题查这里 |
| `ssquant/data/api_data_fetcher.py` | 远程数据获取、SQLite 缓存、本地复权出口 | data_server 数据和缓存问题查这里 |
| `ssquant/data/local_data_loader.py` | 本地 CSV/Excel/Parquet 等导入 SQLite | local 模式导入问题查这里 |
| `ssquant/data/local_adjust.py` | 本地复权、`_adjust_factor` | 复权和价格双轨映射查这里 |
| `ssquant/data/contract_mapper.py` | 连续合约映射，`888/777` 检测 | 合约映射问题查这里 |
| `ssquant/data/contract_info.py` | 合约信息、交易所、乘数等 | 实盘合约信息和平今平昨问题查这里 |
| `ssquant/data/auth_manager.py` | 远程数据认证 | data_server 登录问题查这里 |
| `ssquant/data/historical_preloader.py` | 实盘/SIMNOW 历史数据预加载 | 启动预加载问题查这里 |
| `ssquant/data/multi_period.py` | 本地 K 线周期聚合 | 1m 派生 5m/15m/1h 问题查这里 |
| `ssquant/data/multi_data_fetcher.py` | 多品种多周期批量获取 | 批量数据获取问题查这里 |
| `ssquant/data/ws_kline_client.py` | WebSocket K 线推送客户端 | data_server 实时 K 线问题查这里 |
| `ssquant/data/__init__.py` | data 包初始化 | 通常不用改 |

### 18.5 CTP 与 pyctp

| 文件 | 职责 | AI 使用建议 |
|---|---|---|
| `ssquant/pyctp/trader_api.py` | CTP 交易 API 封装、平今/平昨偏移位 | 真实下单、撤单、偏移位问题查这里 |
| `ssquant/pyctp/md_api.py` | CTP 行情 API 封装 | Tick/行情订阅问题查这里 |
| `ssquant/pyctp/simnow_client.py` | SIMNOW 客户端 | SIMNOW 登录、交易、行情问题查这里 |
| `ssquant/pyctp/real_trading_client.py` | 实盘客户端 | 实盘登录、交易、行情问题查这里 |
| `ssquant/pyctp/simnow_config.py` | SIMNOW 服务器配置 | SIMNOW 地址和账户配置查这里 |
| `ssquant/pyctp/__init__.py` | pyctp 包初始化 | 通常不用改 |
| `ssquant/ctp/loader.py` | 按 Python 版本加载 CTP 二进制模块 | CTP_AVAILABLE 或加载失败查这里 |
| `ssquant/ctp/py39~py314/` | CTP SWIG 包装和 DLL/SO 适配 | 生成/二进制层，策略 AI 通常不要改 |
| `ssquant/ctp/__init__.py` | ctp 包初始化 | 通常不用改 |

### 18.6 指标与资源

| 文件 | 职责 | AI 使用建议 |
|---|---|---|
| `ssquant/indicators/tech_indicators.py` | 技术指标函数 | 需要通用指标时参考 |
| `ssquant/indicators/__init__.py` | indicators 包初始化 | 通常不用改 |
| `ssquant/assets/__init__.py` | assets 包初始化 | 通常不用改 |
| `ssquant/assets/plotly.min.js` | HTML 报告 Plotly 资源 | 报告资源加载问题参考 |
| `ssquant/assets/squirrel_quant_logo.png` | 报告水印 Logo | 图表水印资源 |

### 18.7 AI 修改源码时的原则

- 策略问题优先改策略，不要动框架源码。
- 数据问题优先查 `data/`，不要绕过数据层。
- 回测指标问题优先查 `backtest_results.py` 和 `html_report.py`。
- 实盘交易问题优先查 `live_trading_adapter.py` 和 `pyctp/`。
- 不要修改 `ssquant/ctp/py39~py314/` 这类生成/二进制适配文件，除非用户明确要求修 CTP 绑定。
- 不要在策略里复制 `DataSource`、`BacktestCore` 的内部逻辑。

---

## 19. 常见错误

### 19.1 `ModuleNotFoundError: No module named 'ssquant'`

在项目根目录执行：

```bash
pip install -e .
```

### 19.2 回测无数据

检查：

- `data_source_mode` 是否正确。
- 远程模式账号是否配置。
- 本地模式是否导入数据。
- 合约、周期、日期范围是否存在数据。

### 19.3 Tick 回测失败

必须使用：

```python
data_source_mode="local"
```

### 19.4 复权回测和 v0.4.5 不同

v0.4.6 使用价格双轨制映射真实价格计算回测指标，这是预期修正。

### 19.5 策略很慢

通常是 `strategy(api)` 中每根 K 线重复 Pandas rolling。

修复：

- 移到 `initialize(api)`。
- 用 `api.register_indicator()`。
- 用 `api.get_indicator()` 或 `api.get_indicator_array()`。

### 19.6 AI 生成了不存在的接口

处理：

- 打开 `ssquant/api/strategy_api.py`。
- 打开最接近的 `examples/*_高性能.py`。
- 不要凭经验猜其他框架接口。

---

## 20. 关键文件速查

| 需求 | 文件 |
|---|---|
| 策略 API | `ssquant/api/strategy_api.py` |
| 回测主循环 | `ssquant/backtest/backtest_core.py` |
| 三模式统一入口 | `ssquant/backtest/unified_runner.py` |
| 实盘/SIMNOW 桥接 | `ssquant/backtest/live_trading_adapter.py` |
| 权益和绩效 | `ssquant/backtest/backtest_results.py` |
| HTML 报告 | `ssquant/backtest/html_report.py` |
| 数据源 | `ssquant/data/data_source.py` |
| 远程数据和缓存 | `ssquant/data/api_data_fetcher.py` |
| 本地数据导入 | `ssquant/data/local_data_loader.py` |
| 本地复权 | `ssquant/data/local_adjust.py` |
| 连续合约映射 | `ssquant/data/contract_mapper.py` |
| 配置生成 | `ssquant/config/config_helpers.py` |
| 默认配置 | `ssquant/config/trading_config.py` |
| CTP 交易 API | `ssquant/pyctp/trader_api.py` |
| 示例策略 | `examples/` |
| AI Agent 后端 | `ai_agent/backend.py` |
| AI Agent 启动 | `ai_agent/start_server.py` |
| v0.4.6 更新日志 | `046.MD` |

---

## 21. AI 写策略最终检查清单

生成或修改策略前，AI 必须确认：

- [ ] 是否先查看了最接近的 `examples/` 示例。
- [ ] 是否导入 `StrategyAPI`、`UnifiedStrategyRunner`、`RunMode`、`get_config`。
- [ ] 是否有 `initialize(api)`。
- [ ] 是否在 `initialize(api)` 中注册指标。
- [ ] `strategy(api)` 中是否避免重复 Pandas rolling。
- [ ] 交易是否只通过 `StrategyAPI`。
- [ ] 多数据源是否显式传 `index=i`。
- [ ] TICK 回测是否使用 `data_source_mode='local'`。
- [ ] 复权策略是否没有手动处理 `_adjust_factor` 或 `raw_price`。
- [ ] SIMNOW/实盘是否有异常保护。
- [ ] 是否没有使用 `000` 连续合约。
- [ ] 是否没有直接操作底层 CTP。
- [ ] 是否没有修改账户/仓位内部对象。

---

## 22. 最重要原则

AI 不要把 SSQuant 当成通用回测库。

它是专业期货 CTP 框架。策略代码要尊重框架边界：

- 用 `StrategyAPI`。
- 用 examples。
- 用 IndicatorCache。
- 用 `get_config()`。
- 用 `UnifiedStrategyRunner`。
- 让框架处理数据、复权、价格双轨、账户、成交、报告和 CTP。
