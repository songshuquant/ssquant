# SSQuant — AI Agent 项目上下文

> **Version**: 0.4.6
> **License**: MIT
> **Language**: Python 3.9-3.14

---

## 项目定位

SSQuant（松鼠Quant）是中国期货 CTP 专业量化交易与回测框架，支持**一套代码三处运行**：回测 / SIMNOW 仿真 / 实盘。

**v0.4.6 核心变化**：
- 价格双轨制：复权策略价映射真实价格，用真实价格计算回测指标
- 本地数据复权与连续合约映射修复，提升专业期货回测可信度
- 回测报告增强：复权信息、真实成交价、回测配置和关键指标更清晰
- AI Agent 后端更新为 `backend.py` + `start_server.py`，支持工作区、历史、报告元数据管理
- README / SKILL 已重写，面向用户和 AI Agent 解释完整框架

---

## 目录结构

```
ssquant/
├── api/
│   └── strategy_api.py          # StrategyAPI（策略唯一入口）
├── backtest/
│   ├── backtest_core.py         # 回测引擎主循环
│   ├── unified_runner.py        # BACKTEST / SIMNOW / REAL_TRADING 统一入口
│   ├── live_trading_adapter.py  # 实盘/SIMNOW 桥接
│   ├── backtest_results.py      # 回测结果与权益曲线
│   ├── backtest_report.py       # 文本/结构化报告
│   ├── html_report.py           # HTML 报告
│   └── rollover_engine.py       # 自动移仓
├── config/
│   ├── trading_config.py        # 俱乐部数据账号、本地/CTP/SIMNOW/实盘账户配置
│   ├── config_helpers.py        # get_config() 等配置生成逻辑
│   └── _server_config.py        # data_server 连接配置
├── data/
│   ├── data_source.py           # 数据源、缓存、真实价格映射
│   ├── api_data_fetcher.py      # REST API + SQLite 缓存
│   ├── local_data_loader.py     # 本地 SQLite 导入/加载
│   ├── local_adjust.py          # 前复权/后复权
│   └── contract_mapper.py       # 888/777 连续合约映射
├── ctp/py39~py314/              # CTP 二进制
├── pyctp/                       # CTP 客户端封装
└── indicators/

examples/                        # 策略示例，新手必须先跑通
ai_agent/                        # AI 策略助手
046.MD                           # v0.4.6 更新文档
README.md                        # 项目介绍和使用说明
SKILL.md                         # 面向 Codex / Claude Code 的完整框架指南
```

---

## 关键约定

1. **策略唯一入口**：所有交易操作必须通过 `StrategyAPI`。
2. **连续合约**：当前约定只有 `888`（主力）和 `777`（次主力），不要写 `000`。
3. **复权类型**：`adjust_type='0'` 不复权 / `'1'` 后复权 / `'2'` 前复权。
4. **价格双轨制**：策略用复权价格产生信号，框架映射真实价格计算成交、盈亏、权益、回撤等回测指标。
5. **数据模式**：
   - `data_source_mode='data_server'`：远程数据，需俱乐部账号。
   - `data_source_mode='local'`：本地 SQLite，免会员；TICK 回测必须使用本地模式。
6. **默认高性能写法**：在 `initialize(api)` 中用 `api.register_indicator()` 注册指标，`strategy()` 中 O(1) 查表。
7. **examples 是重要保障**：覆盖约 80% 常见期货策略类型，新手和 AI 写策略前都应先参考并跑通示例。

---

## 账户配置位置

| 场景 | 配置位置 | 说明 |
|------|----------|------|
| 俱乐部远程数据账号 | `ssquant/config/trading_config.py` 的 `API_USERNAME` / `API_PASSWORD` | 仅 `data_server` 模式需要 |
| 本地数据模式 | `data_cache/backtest_data.db` | 不需要账号，先运行 `examples/A_工具_导入数据库DB示例.py` 导入数据 |
| SIMNOW 账户 | `ssquant/config/trading_config.py` 的 `ACCOUNTS['simnow_default']` | 填 broker_id / investor_id / password / 前置地址等 |
| 实盘 CTP 账户 | `ssquant/config/trading_config.py` 的 `ACCOUNTS['real_default']` | 填真实柜台账户、AppID、AuthCode 和前置地址 |

---

## 常见陷阱

| 问题 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: No module named 'ssquant'` | 未在项目根目录安装源码包，或误装旧包 | 在仓库根目录执行 `pip install -e .` |
| 回测无数据 | 远程鉴权失败或本地库无数据 | 检查 `data_source_mode`；本地模式先导入 SQLite |
| TICK 回测报错 | TICK 历史数据不走远程模式 | 设置 `data_source_mode='local'` |
| 复权回测与 v0.4.5 不一致 | v0.4.6 改为真实价格口径计算指标 | 这是预期修正，重点检查连续合约复权场景 |
| 策略速度慢 | 策略内重复 Pandas rolling/ewm/iloc | 改为 `initialize()` 注册指标，策略内查缓存 |
| 多品种数据错位 | `align_data=True` 误截断不同周期 | 多品种多周期通常设为 `align_data=False` |

---

## 关键文件速查

| 需求 | 文件 |
|------|------|
| v0.4.6 更新详情 | `046.MD` |
| 框架完整指南 | `SKILL.md` |
| 项目 README | `README.md` |
| AI Agent 上下文 | `AGENTS.md` |
| 策略 API | `ssquant/api/strategy_api.py` |
| 回测引擎 | `ssquant/backtest/backtest_core.py` |
| 三模式统一入口 | `ssquant/backtest/unified_runner.py` |
| 数据源/缓存/真实价格映射 | `ssquant/data/data_source.py` |
| 配置生成 | `ssquant/config/config_helpers.py` |
| 账户配置 | `ssquant/config/trading_config.py` |
| 合约映射 | `ssquant/data/contract_mapper.py` |
