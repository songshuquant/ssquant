# SSQuant AI Agent

> 版本：v0.4.6
> 协议：MIT

SSQuant AI Agent 是 SSQuant 的本地策略开发助手。它用浏览器界面连接大模型，帮助用户生成策略、修改策略、运行回测、查看报告、分析错误，并围绕工作区保存一次策略开发过程。

它不是独立量化框架，所有策略运行、回测指标、数据源、复权和交易接口都以仓库根目录的 SSQuant v0.4.6 为准。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| 策略生成 | 根据中文需求生成 SSQuant 策略代码 |
| 示例优先 | 系统提示词要求 AI 优先参考 `examples/` 高性能示例 |
| 回测执行 | 后端保存临时策略文件并用子进程运行回测 |
| 实时日志 | 使用 SSE 推送回测状态和运行日志 |
| 报告管理 | 自动发现 `backtest_results/` 下的 HTML 报告 |
| 报告分析 | 将回测报告交给 AI 分析并生成改进建议 |
| 自动流程 | 支持自动运行、自动调试、自动迭代 |
| 工作区 | 按工作区保存聊天、策略、报告关联关系 |
| 多模型 | 支持 OpenAI 兼容接口和 Claude 原生 API |
| 思考模式 | 支持 DeepSeek R1 / QwQ 文本思考流，也支持 Claude thinking 参数注入 |

---

## v0.4.6 重点

- 系统提示词已升级到 SSQuant v0.4.6。
- 策略生成必须围绕 `StrategyAPI`，优先使用 `initialize(api)` + `api.register_indicator()`。
- 连续合约只写 `888` 主力、`777` 次主力，不写 `000`。
- 复权说明统一为价格双轨制：复权策略价映射真实价格，用真实价格计算回测指标。
- `examples/` 是新手和 AI 的第一参考，覆盖约 80% 常见期货策略类型。
- 后端入口从旧 `app.py` 切换为 `backend.py`，启动脚本为 `start_server.py`。
- 运行时状态不提交仓库：`settings.json`、`history.json`、`report_metadata.json`、`strategies/`、`workspaces/` 会在启动或使用时自动生成。

---

## 目录结构

```text
ai_agent/
├── backend.py             # Flask 后端主程序
├── start_server.py        # waitress 启动脚本
├── prompt.py              # SSQuant v0.4.6 系统提示词
├── requirements.txt       # AI Agent 依赖
├── README.md              # 本文档
├── templates/
│   └── index.html         # 前端单页界面
└── static/
    └── node_modules/      # 前端依赖资源
```

运行后会自动生成：

```text
ai_agent/
├── settings.json          # 本机模型和回测参数设置
├── history.json           # 策略历史记录
├── report_metadata.json   # 报告与工作区映射
├── strategies/            # AI 生成或回测用的策略文件
└── workspaces/            # 工作区 JSON 文件
```

这些运行时文件已在 `.gitignore` 中忽略。

---

## 安装与启动

在仓库根目录先安装 SSQuant：

```powershell
pip install -e .
```

安装 AI Agent 依赖：

```powershell
cd ai_agent
pip install -r requirements.txt
```

启动服务：

```powershell
python start_server.py
```

浏览器访问：

```text
http://localhost:5000
```

---

## 模型配置

打开页面右上角设置，填写：

| 配置项 | 说明 |
|--------|------|
| Provider | DeepSeek / OpenAI / Claude / Qwen / Moonshot / Zhipu / Custom |
| API 接口地址 | OpenAI 兼容接口或 Claude 原生接口 |
| 模型名称 | 如 `deepseek-chat`、`gpt-4o`、`claude-3-7-sonnet-20250219` |
| API Key | 模型服务商密钥，只保存在本机 `settings.json` |
| Temperature | 生成随机性 |
| 额外参数 | 透传给模型 API 的 JSON 参数 |
| 思考模式 | 允许显示/处理模型思考内容，并延长超时时间 |
| 思考链期望长度 | Claude 模式会映射为 `thinking.budget_tokens` |
| 回复最大长度 | 透传 `max_tokens` |

Claude 原生 API 需要安装 `anthropic`，已写入 `requirements.txt`。

---

## 回测参数

右侧设置区会写入回测参数，包括：

| 参数 | 说明 |
|------|------|
| 合约代码 | 常用 `rb888`、`au888`；连续合约只用 `888/777` |
| K线周期 | 如 `1m`、`5m`、`15m`、`1h`、`1d` |
| 日期范围 | `start_date` / `end_date` |
| 复权类型 | `0` 不复权、`1` 后复权、`2` 前复权 |
| 初始资金 | `initial_capital` |
| 手续费率 | `commission` |
| 保证金率 | `margin_rate` |
| 合约乘数 | `contract_multiplier` |
| 最小变动价位 | `price_tick` |
| 滑点跳数 | `slippage_ticks` |
| 回溯窗口 | `lookback_bars` |

TICK 回测必须使用本地数据模式。实际数据账号、本地模式、SIMNOW 和实盘 CTP 账户配置位置，请以根目录 `README.md` 和 `SKILL.md` 为准。

---

## 自动流程

页面右下角有三个自动化开关：

| 开关 | 作用 |
|------|------|
| 自动运行 | AI 生成策略后自动启动回测 |
| 自动调试 | 回测报错后把错误交给 AI 修复 |
| 自动迭代 | 回测成功后分析报告并继续优化 |

典型流程：

```text
用户描述策略
  -> AI 生成策略代码
  -> 保存到 ai_agent/strategies/
  -> 子进程运行回测
  -> 生成 backtest_results/*.html
  -> 前端展示报告
  -> AI 分析报告并继续优化
```

---

## 后端接口速查

| 接口 | 作用 |
|------|------|
| `GET /` | 打开前端页面 |
| `POST /api/chat/stream` | 流式 AI 对话 |
| `POST /api/chat/stop` | 停止 AI 输出 |
| `GET/POST /api/strategy` | 获取或更新当前策略 |
| `POST /api/backtest/start` | 启动回测 |
| `GET /api/backtest/status` | 轮询回测状态 |
| `POST /api/backtest/stop` | 停止回测 |
| `GET /api/reports` | 列出回测报告 |
| `GET /api/report/<filename>` | 查看报告 |
| `DELETE /api/report/<filename>` | 删除报告 |
| `GET/POST /api/settings` | 读取或保存设置 |
| `GET /api/history` | 查看策略历史 |
| `POST /api/history/save` | 保存策略历史 |
| `GET /api/examples` | 列出示例策略 |
| `GET /api/example/<filename>` | 读取示例策略 |
| `GET /api/workspaces` | 列出工作区 |
| `POST /api/workspace` | 创建工作区 |
| `GET/PUT/DELETE /api/workspace/<id>` | 读取、更新、删除工作区 |

---

## 常见问题

### 启动后没有 `settings.json`

正常。首次启动 `backend.py` 会自动创建默认设置文件。

### `strategies/` 和 `workspaces/` 不存在

正常。启动后会自动创建，使用过程中会写入策略和工作区文件。

### Claude 报 `No module named anthropic`

重新安装依赖：

```powershell
cd ai_agent
pip install -r requirements.txt
```

### 回测没有数据

先确认根目录 SSQuant 数据源配置。本地模式需要先导入 SQLite 数据；远程 `data_server` 模式需要俱乐部数据账号。

### 生成的策略质量不稳定

先让 AI 读取并参考 `examples/` 中最接近的高性能示例，再生成策略。新手也应该先手动跑通示例策略。

---

## 发布注意

提交 GitHub 时应包含产品代码和文档：

```text
ai_agent/backend.py
ai_agent/start_server.py
ai_agent/prompt.py
ai_agent/templates/index.html
ai_agent/requirements.txt
ai_agent/README.md
```

不应提交本机运行状态：

```text
ai_agent/settings.json
ai_agent/history.json
ai_agent/report_metadata.json
ai_agent/strategies/
ai_agent/workspaces/
```

期货交易具有高风险，历史回测业绩不代表未来表现。
