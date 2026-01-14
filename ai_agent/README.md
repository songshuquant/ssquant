# SSQuant AI Agent

🚀 **驱动式AI量化策略编写智能体**

> ⚠️ **重要提示**：`ai_agent` 目录必须位于 `ssquant-main` 项目根目录下，不可单独移动到其他位置。
> 
> AI Agent 依赖 SSQuant 框架的回测引擎、数据接口和配置文件，目录结构如下：
> ```
> ssquant-main/           # 项目根目录
> ├── ai_agent/           # AI Agent（本目录）
> ├── ssquant/            # SSQuant 核心框架（必需）
> ├── backtest_results/   # 回测报告输出目录
> ├── backtest_logs/      # 回测日志目录
> └── examples/           # 示例策略
> ```

## 功能特性

### 三栏式布局
- **左侧 - 策略代码编辑器**: 基于Monaco Editor，支持语法高亮、差异对比（红绿色显示代码变化）
- **中间 - AI助手对话**: 支持自然语言交互，自动提取代码
- **右侧 - 回测报告与设置**: 查看报告、历史版本、配置参数

### 核心功能
1. **AI驱动策略生成**: 用自然语言描述需求，AI自动生成完整策略代码
2. **一键回测**: 直接运行策略，实时查看回测输出
3. **智能分析**: AI自动分析回测报告，给出改进建议
4. **自动迭代**: 开启AUTO模式，AI自动优化策略直到达到目标

### AUTO模式
- **自动回测**: 生成策略后自动运行回测
- **自动调试**: 回测完成后自动分析报告
- **自动迭代**: 根据分析结果自动优化策略（可设置迭代次数）

## 快速开始

### 0. 前置条件

**确保目录结构正确**：`ai_agent` 必须位于 `ssquant-main` 根目录下

```bash
# 正确的目录结构
ssquant-main/
├── ai_agent/        ← 你现在在这里
├── ssquant/         ← 必需：SSQuant 核心框架
├── data_cache/      ← 数据缓存目录
└── ...
```

**配置俱乐部账号**：在 `ssquant/config/trading_config.py` 中填写：
```python
API_USERNAME = "你的俱乐部账号"
API_PASSWORD = "你的俱乐部密码"
```

### 1. 安装依赖

```bash
# 进入 ai_agent 目录
cd ssquant-main/ai_agent

# 安装依赖（国内推荐使用镜像加速）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 配置 AI 模型 API Key

启动应用后，点击右上角 ⚙️ 设置按钮，配置：
- **API 接口地址**: 大模型服务的 API 地址（支持 OpenAI 兼容格式）
- **API Key**: 你的 API 密钥
- **模型**: deepseek-chat / gpt-4 / claude-3-opus 等
- **Temperature**: 控制生成的随机性 (0-2)

**支持的 AI 服务商**：
- DeepSeek（推荐，性价比高）
- OpenAI（ChatGPT、GPT-4）
- 智谱AI（GLM-4）
- 月之暗面（Moonshot/Kimi）
- 通义千问（Qwen）
- 其他兼容 OpenAI API 格式的服务

### 3. 启动应用

```bash
# 确保在 ai_agent 目录下
cd ssquant-main/ai_agent

# 启动服务
python app.py
```

访问 http://localhost:5000

## 使用流程

### 生成策略
1. 在中间对话框输入策略需求，例如：
   - "给我写一个双均线策略"
   - "生成一个海龟突破策略，使用20日突破入场"
   - "写一个MACD+RSI组合策略"

2. AI返回策略代码后，代码自动显示在左侧编辑器

### 运行回测
1. 在右侧"参数"标签配置回测参数
2. 点击左下角"▶️ 运行回测"
3. 在运行日志中查看实时输出
4. 回测完成后自动显示报告

### 优化迭代
1. 点击报告下方"让AI分析"
2. AI会分析报告并给出改进建议
3. 如果有建议代码，点击"应用代码"
4. 继续运行回测验证效果

### 版本管理
- 点击右侧"历史"标签查看所有版本
- 每次运行回测会自动保存版本
- 可以加载历史版本代码或查看对应报告

## 目录结构

```
ssquant-main/                    # 项目根目录
├── ai_agent/                    # AI Agent 目录
│   ├── app.py                   # Flask 后端主程序
│   ├── requirements.txt         # Python 依赖
│   ├── settings.json            # 用户设置（自动生成）
│   ├── history.json             # 历史记录（自动生成）
│   ├── templates/
│   │   └── index.html           # 前端页面
│   ├── strategies/              # AI 生成的策略保存目录
│   └── workspaces/              # 工作区数据目录
│
├── ssquant/                     # SSQuant 核心框架（必需）
│   ├── backtest/                # 回测引擎
│   ├── config/                  # 配置文件（含 trading_config.py）
│   └── ...
│
├── backtest_results/            # 回测报告输出目录
├── backtest_logs/               # 回测日志目录
├── data_cache/                  # 数据缓存目录
└── examples/                    # 示例策略
```

## 技术栈

- **后端**: Flask + Threading (非阻塞)
- **前端**: HTML5 + CSS3 + JavaScript
- **代码编辑器**: Monaco Editor
- **Markdown渲染**: Marked.js
- **AI接口**: 支持DeepSeek/OpenAI/Claude

## 配置说明

### LLM设置
| 参数 | 说明 | 默认值 |
|------|------|--------|
| Provider | AI提供商 | DeepSeek |
| Model | 模型名称 | deepseek-chat |
| Temperature | 生成随机性 | 0.7 |

### 优化目标
| 参数 | 说明 | 默认值 |
|------|------|--------|
| 最小交易次数 | 策略有效性验证 | 10 |
| 目标夏普比率 | 风险调整收益 | 1.5 |
| 目标胜率 | 盈利交易比例 | 45% |
| 最大回撤限制 | 风险控制 | 20% |

### 回测参数
| 参数 | 说明 | 默认值 |
|------|------|--------|
| 初始资金 | 回测起始资金 | 1,000,000 |
| 手续费率 | 交易成本 | 0.0001 |
| 保证金率 | 期货保证金 | 10% |
| 合约乘数 | 合约价值倍数 | 10 |
| 最小变动价位 | 价格精度 | 1 |
| 滑点跳数 | 成交滑点 | 1 |

## 常见问题

### Q: 提示"俱乐部鉴权失败"？
1. 检查 `ssquant/config/trading_config.py` 中的 `API_USERNAME` 和 `API_PASSWORD` 是否正确
2. 确保账号已开通 AI 助手权限
3. 重启 AI Agent 服务

### Q: 提示找不到 ssquant 模块？
**确保 `ai_agent` 目录位于 `ssquant-main` 根目录下**，不能单独复制到其他位置使用。
```bash
# 正确结构
ssquant-main/
├── ai_agent/     ← AI Agent
└── ssquant/      ← 必须存在
```

### Q: 回测没有输出？
1. 检查策略代码是否完整，确保包含 `if __name__ == "__main__":` 和运行器配置
2. 检查控制台是否有错误信息

### Q: AI无法响应？
1. 检查 API Key 是否正确
2. 检查 API 接口地址是否正确
3. 检查网络连接
4. 查看控制台错误信息

### Q: 报告无法显示？
确保 `backtest_results` 目录存在且有生成的 HTML 报告。

## 更新日志

### v1.0.0 (2026-01-10)
- 🎉 首次发布
- ✨ 三栏式布局
- ✨ Monaco代码编辑器+差异对比
- ✨ AI对话+自动回测+自动迭代
- ✨ 版本历史管理

