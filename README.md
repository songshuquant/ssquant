# SSQuant - 专业期货 CTP 量化交易框架

SSQuant（松鼠Quant）是面向中国期货市场的 Python 量化交易框架，支持一套策略代码在 **回测 / SIMNOW 仿真 / CTP 实盘** 三种环境中运行。

它不是只做历史回测的 toy project，而是围绕期货交易的真实工程问题设计：连续合约、复权、换月、保证金、手续费、滑点、CTP 下单、Tick/K 线数据、SIMNOW 验证、实盘运行和回测报告。

当前版本：v0.4.6
Python：3.9 - 3.14
License：MIT

- GitHub: https://github.com/songshuquant/ssquant
- Gitee: https://gitee.com/ssquant/ssquant
- 官网: https://quant789.com

---

## 一句话理解

SSQuant 的核心目标是：

> 让期货策略从研究、回测、仿真到实盘尽量使用同一套代码和同一套交易接口。

策略只和 `StrategyAPI` 交互：

```python
api.buy()
api.sell()
api.sellshort()
api.buycover()
api.close_all()
```

运行环境由 `RunMode` 决定：

```python
RunMode.BACKTEST       # 回测
RunMode.SIMNOW         # SIMNOW 仿真
RunMode.REAL_TRADING   # CTP 实盘
```

---

## 核心能力

| 能力 | 说明 |
|---|---|
| 一套代码三处运行 | 回测、SIMNOW、实盘共享策略主体 |
| StrategyAPI | 策略唯一数据和交易入口 |
| 高性能回测 | ndarray 缓存 + IndicatorCache v2 |
| 本地/远程数据 | 支持 `data_server` 和 `local` 两种模式 |
| 连续合约 | 支持 `888` 主力、`777` 次主力 |
| 复权处理 | 支持不复权、后复权、前复权 |
| 价格双轨制 | 复权策略价映射真实价格，用真实价格计算回测指标 |
| 自动移仓 | 支持主力换月平旧开新 |
| 交互式报告 | HTML K 线图、交易标记、综合绩效、费用统计 |
| AI Agent | 自然语言生成、修改、运行和迭代策略 |

---

## v0.4.6 最重要的变化

v0.4.6 的关键变化不是新增一个普通功能，而是建立价格双轨制：策略使用复权价格保持连续性，回测指标通过映射后的真实价格计算。

过去，策略使用后复权/前复权连续合约时，复权价格既用于指标，也可能进入成交、盯市和权益曲线计算。这样会让换月点附近的盈亏被复权因子污染。

v0.4.6 改为价格双轨体系：

| 价格 | 用途 |
|---|---|
| `price` / `current_price` | 策略看到的复权价，用于指标、信号、图表 |
| `raw_price` / `current_raw_price` | 由复权价映射回的真实价格，用于回测指标、持仓盯市、权益曲线 |

这意味着：

- 策略仍然可以用连续平滑的复权价格做技术指标。
- 回测指标通过映射后的真实价格计算。
- 后复权/前复权回测结果可能和 v0.4.5 不一致，这是预期修正。

详细更新见 [046.MD](046.MD)。

---

## 安装

正式安装请使用源码仓库。PyPI 只保留弃用提示包，不再作为真实安装入口。

### GitHub

```bash
git clone https://github.com/songshuquant/ssquant.git
cd ssquant
pip install -e .
```

### Gitee

```bash
git clone https://gitee.com/ssquant/ssquant.git
cd ssquant
pip install -e .
```

安装后，如果出现 `ModuleNotFoundError: No module named 'ssquant'`，通常是没有在项目根目录执行 editable install，或误装了 PyPI redirect 包：

```bash
pip uninstall ssquant
pip install -e .
```

---

## 数据模式

SSQuant 支持两种数据模式。

### 远程数据：`data_source_mode='data_server'`

适合 quant789 松鼠俱乐部会员使用。

特点：

- 远程服务器维护历史 K 线和实时 K 线。
- 回测、SIMNOW、实盘预加载可直接拉取数据。
- 支持多周期 K 线、订单流和盘口深度数据。
- 免去本地导入和维护数据的成本。

示例：

```python
config = get_config(
    RunMode.BACKTEST,
    symbol="rb888",
    kline_period="15m",
    data_source_mode="data_server",
)
```

需要在 `ssquant/config/trading_config.py` 中配置远程数据账号：

```python
API_USERNAME = "你的账号"
API_PASSWORD = "你的密码"
```

### 本地数据：`data_source_mode='local'`

本地模式不需要会员账号，适合离线回测、私有数据和 Tick 回测。

特点：

- 数据保存在本地 SQLite。
- 支持 CSV、Excel、JSON、Parquet、Feather、Pickle 导入。
- Tick 回测必须使用本地模式。
- 导入 1 分钟 K 线后可派生 5m、15m、1h、1d 等周期。
- SIMNOW/实盘可通过 CTP Tick 落盘，逐步积累自己的本地行情库。

示例：

```python
config = get_config(
    RunMode.BACKTEST,
    symbol="rb888",
    kline_period="15m",
    data_source_mode="local",
)
```

导入本地数据：

```bash
python examples/A_工具_导入数据库DB示例.py
```

---

## 第一个策略

下面是一个最小高性能双均线思路示例。它使用 `initialize(api)` 注册指标，在 `strategy(api)` 中 O(1) 查询。

```python
import pandas as pd
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config


def initialize(api: StrategyAPI):
    api.register_indicator(
        "ma20",
        lambda c, o, h, l, v: pd.Series(c).rolling(20).mean().to_numpy(),
        window=20,
    )


def strategy(api: StrategyAPI):
    price = api.get_price()
    ma20 = api.get_indicator("ma20")

    if pd.isna(ma20):
        return

    if price > ma20 and api.get_pos() <= 0:
        api.buy(volume=1, order_type="next_bar_open", reason="上穿 MA20")
    elif price < ma20 and api.get_pos() > 0:
        api.sell(order_type="next_bar_open", reason="下穿 MA20")


if __name__ == "__main__":
    config = get_config(
        RunMode.BACKTEST,
        symbol="rb888",
        kline_period="1h",
        start_date="2024-01-01",
        end_date="2025-01-01",
        adjust_type="1",
        data_source_mode="data_server",
        initial_capital=100000,
    )

    runner = UnifiedStrategyRunner(mode=RunMode.BACKTEST)
    runner.set_config(config)
    runner.run(strategy=strategy, initialize=initialize)
```

---

## 三模式切换

策略函数不需要因为运行环境变化而重写。通常只切换 `RunMode` 和配置。

```python
# 回测
config = get_config(
    RunMode.BACKTEST,
    symbol="rb888",
    kline_period="1h",
    start_date="2024-01-01",
    end_date="2025-01-01",
)

# SIMNOW 仿真
config = get_config(
    RunMode.SIMNOW,
    account="simnow_default",
    symbol="rb888",
    kline_period="5m",
)

# CTP 实盘
config = get_config(
    RunMode.REAL_TRADING,
    account="real_default",
    symbol="rb888",
    kline_period="5m",
)
```

实盘策略建议捕获关键异常，避免单根 K 线错误导致整个交易进程退出。

---

## StrategyAPI 约定

策略必须通过 `StrategyAPI` 交易。不要在策略里直接操作底层 CTP 接口。

### 交易接口

```python
api.buy(volume=1)        # 开多
api.sell(volume=1)       # 平多
api.sellshort(volume=1)  # 开空
api.buycover(volume=1)   # 平空
api.close_all()          # 全部平仓
```

SIMNOW/实盘模式还支持委托查询和撤单：

```python
api.query_orders()                 # 异步查询当日全部委托
api.query_orders("rb2601")        # 查询指定合约委托
api.cancel_order(order_sys_id)     # 按 OrderSysID 撤销单笔活动委托
api.cancel_all_orders()            # 撤销当前数据源的全部活动委托
```

`query_orders()` 的结果通过 `runner.run(on_query_order=..., on_query_order_complete=...)`
逐条返回。`OrderSysID` 可从 `on_order` 或 `on_query_order` 回调中取得。

### 数据接口

```python
api.get_price()
api.get_open()
api.get_high()
api.get_low()
api.get_close()
api.get_volume()
api.get_pos()
api.get_balance()
```

### 高性能指标接口

```python
api.register_indicator(name, func, window=None, index=0)
api.get_indicator(name, index=0)
api.get_indicator_array(name, window=None, index=0)
api.get_close_array(window=None, index=0)
```

AI 生成策略时，默认应该：

- 写 `initialize(api)`。
- 在 `initialize(api)` 中注册指标。
- 在 `strategy(api)` 中只做 O(1) 查询。
- 仅当指标逻辑无法预注册时，才回退到 Pandas 普通写法。

---

## 连续合约与复权

SSQuant 常用连续合约约定：

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

v0.4.6 起，复权只影响策略看到的价格连续性，不再污染真实盈亏统计。报告中如果复权价和真实价不同，交易表格会显示实际成交价，方便对账。

---

## 回测报告

回测结束后，框架会输出文本报告和 HTML 交互式报告。

HTML 报告包含：

- 资金曲线和利润曲线。
- 回撤曲线。
- K 线/Tick 图。
- 交易标记。
- 手续费、滑点、交易盈亏、净利润。
- 多数据源综合页。
- 交易记录筛选和分页。
- 复权价与真实价对照显示。

v0.4.6 的综合最大回撤基于综合权益曲线计算，而不是简单取单品种平均。

---

## AI Agent

`ai_agent/` 是 SSQuant 的 AI 策略助手，可以通过自然语言生成、修改、运行和分析策略。

安装依赖：

```powershell
cd ai_agent
pip install -r requirements.txt
```

启动：

```powershell
python start_server.py
```

访问：

```text
http://localhost:5000
```

v0.4.6 起，AI Agent 使用 waitress 生产服务器启动，不建议长期使用 Flask 开发服务器。

主要能力：

- OpenAI 兼容模型。
- Claude 原生 API。
- DeepSeek-R1 / Claude thinking 思考内容展示。
- 图片和文本附件上传。
- 自动运行、自动调试、自动迭代。
- 强制停止运行中的策略进程。
- 工作区、报告和策略历史管理。

升级 AI Agent 时请注意：`settings.json`、`history.json`、`workspaces/`、`strategies/` 是运行数据，不建议直接覆盖。

---

## 推荐示例

`examples/` 是 SSQuant 最重要的上手保障之一。

新手不要一开始就让 AI 从零写复杂策略。正确顺序是：

1. 先安装框架。
2. 先导入或配置好数据。
3. 先跑通 `examples/` 中最接近自己需求的示例策略。
4. 再在示例基础上改参数、改信号、改仓位管理。
5. 最后再让 AI 帮你扩展成自己的策略。

这些示例不是装饰文件，而是框架能力的可运行样板。它们覆盖了期货市场中大约 80% 常见策略类型：趋势跟踪、均值回归、网格、套利、跨周期过滤、截面轮动、机器学习、加减仓、正反手、Tick 高频、期权组合、订单流、自动换月和数据工具。

对新手来说，跑通示例有三个作用：

- 验证安装、数据、账号、报告生成是否正常。
- 学会 SSQuant 的标准策略结构和 `StrategyAPI` 用法。
- 给 AI 一个可靠模板，避免生成不符合框架约定的代码。

### 示例分类

| 示例 | 用途 |
|---|---|
| `examples/A_工具_导入数据库DB示例.py` | 本地数据导入，local 模式第一步 |
| `examples/A_工具_数据库管理_查看与删除.py` | 查看和清理本地 SQLite 数据 |
| `examples/A_CTP连接状态监测测试_真实断网.py` | CTP 连接状态和断网恢复测试 |
| `examples/A_撤单重发示例.py` | 撤单、重发、追单链路示例 |
| `examples/A_穿透式测试脚本.py` | CTP 穿透式监管相关测试 |
| `examples/B_双均线策略_高性能.py` | 高性能策略入门 |
| `examples/B_海龟交易策略_高性能.py` | 唐奇安通道策略 |
| `examples/B_十大经典策略之Aberration_高性能.py` | 经典通道突破策略 |
| `examples/B_日内交易策略.py` | 日内交易模板 |
| `examples/B_网格交易策略.py` | 网格交易 |
| `examples/B_加仓策略_高性能.py` | 趋势加仓 |
| `examples/B_减仓策略_高性能.py` | 分批减仓 |
| `examples/B_正反手策略_高性能.py` | 多空反转 |
| `examples/B_正反手混合开平仓策略_高性能.py` | 正反手与混合开平仓 |
| `examples/B_多品种多周期交易策略_高性能.py` | 多品种、多周期 |
| `examples/B_自动参数示例.py` | 参数优化 |
| `examples/B_多品种多周期交易策略_参数优化.py` | 多品种多周期参数优化 |
| `examples/B_自动换月示例.py` | 主力连续合约自动换月 |
| `examples/B_跨周期过滤策略_高性能.py` | 大周期过滤小周期交易 |
| `examples/B_跨品种套利策略_高性能.py` | 跨品种套利 |
| `examples/B_跨期套利策略_高性能.py` | 跨期套利 |
| `examples/B_强弱截面轮动策略_高性能.py` | 截面强弱轮动 |
| `examples/B_机器学习策略_随机森林_高性能.py` | 机器学习策略 |
| `examples/C_纯Tick高频交易策略.py` | Tick 回测 |
| `examples/C_纯Tick限价单交易策略.py` | Tick 限价单交易 |
| `examples/C_期权交易策略.py` | 期权交易 |
| `examples/C_期货期权组合策略.py` | 期货期权组合 |
| `examples/D_订单流与深度数据_data_server模式.py` | 订单流和深度数据 |

### 推荐阅读顺序

如果你是第一次使用 SSQuant，建议按这个顺序：

1. `A_工具_导入数据库DB示例.py`
2. `B_双均线策略_高性能.py`
3. `B_海龟交易策略_高性能.py`
4. `B_多品种多周期交易策略_高性能.py`
5. `B_自动参数示例.py`
6. 再根据自己的方向选择套利、Tick、期权、机器学习或订单流示例。

所有生产策略建议优先参考 `*_高性能.py` 写法。

AI 生成策略时，也应该优先模仿这些示例的结构：`initialize(api)` 注册指标，`strategy(api)` 中 O(1) 查询，交易只通过 `StrategyAPI` 完成。

---

## 关键文件

| 需求 | 文件 |
|---|---|
| 策略 API | `ssquant/api/strategy_api.py` |
| 回测主循环 | `ssquant/backtest/backtest_core.py` |
| 三模式统一入口 | `ssquant/backtest/unified_runner.py` |
| 实盘/SIMNOW 桥接 | `ssquant/backtest/live_trading_adapter.py` |
| 数据源 | `ssquant/data/data_source.py` |
| 远程数据和缓存 | `ssquant/data/api_data_fetcher.py` |
| 本地复权 | `ssquant/data/local_adjust.py` |
| 配置生成 | `ssquant/config/config_helpers.py` |
| 默认配置 | `ssquant/config/trading_config.py` |
| AI Agent | `ai_agent/` |
| v0.4.6 更新日志 | `046.MD` |

---

## 升级到 v0.4.6

建议分阶段升级：

1. 先替换 `ssquant/`。
2. 跑不复权回测，确认结果基本稳定。
3. 跑后复权/前复权连续合约回测，确认报告中有 `raw_price` 映射真实价。
4. 再替换 AI Agent 代码。
5. 备份并合并 `ai_agent/settings.json`、`history.json`、`workspaces/`、`strategies/`。

重点验证：

- 不复权回测。
- 复权连续合约回测。
- 多品种多周期回测。
- HTML 报告。
- SIMNOW/实盘平今平昨。
- AI Agent `python start_server.py`。

---

## 常见问题

### 回测没有数据

检查：

- `data_source_mode` 是否正确。
- 远程模式账号是否配置。
- 本地模式是否已经导入数据。
- 合约、周期、日期范围是否存在数据。

### Tick 回测为什么报错

Tick 回测必须使用：

```python
data_source_mode="local"
```

### 复权回测结果为什么和 v0.4.5 不一样

v0.4.6 通过价格双轨制把复权价映射回真实价格，并用真实价格计算回测指标，这是预期修正。

### AI Agent 为什么要用 `start_server.py`

`start_server.py` 使用 waitress，能改善 Windows 下长时间运行、后台切换和 SSE 连接不稳定的问题。

---

## 许可证与风险提示

SSQuant 使用 MIT License。

期货交易具有高风险。SSQuant 是研究和工程框架，不构成投资建议。实盘前请充分回测和 SIMNOW 验证，并从小资金开始。
