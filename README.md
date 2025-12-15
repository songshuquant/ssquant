# SSQuant - 期货量化交易框架

<div align="center">

🐿️ **松鼠量化** | 专业的期货CTP量化交易框架

[![PyPI](https://img.shields.io/pypi/v/ssquant.svg)](https://pypi.org/project/ssquant/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Non--Commercial-red.svg)](LICENSE)

**一次编写，三处运行** - 回测 / SIMNOW模拟 / 实盘CTP

</div>

---

## 🎯 核心特性

### ✅ 统一的策略框架

- **一套代码三处运行** - 同一份策略代码可在回测、SIMNOW模拟、实盘CTP三种环境下运行
- **完整的数据支持** - K线数据（1m/5m/15m/30m/1h/4h/1d）+ TICK逐笔数据
- **多品种多周期** - 同时交易多个品种，使用不同周期数据

### ✅ 强大的交易功能

- **自动开平仓管理** - 智能识别开平仓、今昨仓
- **智能算法交易** - 支持限价单排队、超时撤单、追价重发等高级逻辑
- **实时回调系统** - on_trade/on_order/on_cancel 实时通知
- **TICK流双驱动** - K线驱动 + TICK驱动两种模式

### ✅ 丰富的策略示例

- 19个完整策略示例
- 涵盖趋势、套利、轮动、期权、机器学习等类型
- 从入门到高级，循序渐进

---

## ⚡ 快速开始

### 1. 安装

```bash
pip install ssquant
```

### 2. 编写策略

```python
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

def my_strategy(api: StrategyAPI):
    """双均线策略"""
    close = api.get_close()
    
    if len(close) < 20:
        return
    
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    pos = api.get_pos()
    
    # 金叉做多
    if ma5.iloc[-2] <= ma20.iloc[-2] and ma5.iloc[-1] > ma20.iloc[-1]:
        if pos <= 0:
            if pos < 0:
                api.buycover(order_type='next_bar_open')
            api.buy(volume=1, order_type='next_bar_open')
    
    # 死叉做空
    elif ma5.iloc[-2] >= ma20.iloc[-2] and ma5.iloc[-1] < ma20.iloc[-1]:
        if pos >= 0:
            if pos > 0:
                api.sell(order_type='next_bar_open')
            api.sellshort(volume=1, order_type='next_bar_open')

if __name__ == "__main__":
    # 回测配置
    config = get_config(
        mode=RunMode.BACKTEST,
        symbol='rb888',
        start_date='2025-01-01',
        end_date='2025-11-30',
        kline_period='1h',
        price_tick=1.0,
        contract_multiplier=10,
    )
    
    # 运行
    runner = UnifiedStrategyRunner(mode=RunMode.BACKTEST)
    runner.set_config(config)
    results = runner.run(strategy=my_strategy)
```

### 3. 切换模式只需改配置

```python
# ===== 回测模式 =====
config = get_config(
    mode=RunMode.BACKTEST,
    symbol='rb888',
    start_date='2025-01-01',
    end_date='2025-11-30',
    kline_period='1h',
)

# ===== SIMNOW模拟 =====
config = get_config(
    mode=RunMode.SIMNOW,
    account='simnow_default',      # 使用预配置的账户
    symbol='rb2601',               # 具体合约月份
    kline_period='1m',
)

# ===== 实盘交易 =====
config = get_config(
    mode=RunMode.REAL_TRADING,
    account='real_default',        # 使用预配置的账户
    symbol='rb2601',
    kline_period='1m',
)
```

**策略代码完全不用改！**

---

## 📚 文档导航

| 文档 | 说明 | 适合 |
|------|------|------|
| [用户手册.md](用户手册.md) | 📖 完整使用教程 | 新手必读 |
| [API参考手册.md](API参考手册.md) | 📚 详细API说明 | 开发查询 |
| [文档导航.md](文档导航.md) | 📑 所有文档索引 | 查找文档 |

### 专题指南

| 文档 | 说明 |
|------|------|
| [数据管理指南.md](数据管理指南.md) | 数据获取、导入、落盘 |
| [回测教程.md](回测教程.md) | 历史回测配置和优化 |
| [SIMNOW使用指南.md](SIMNOW使用指南.md) | 模拟盘配置和测试 |
| [实盘部署指南.md](实盘部署指南.md) | 实盘配置和风险管理 |

---

## 🎓 示例策略

所有示例在 `examples/` 目录（共19个）：

### 工具类 (A_开头)

| 文件 | 说明 |
|------|------|
| `A_工具_导入数据库DB示例.py` | 数据导入数据库 |
| `A_工具_数据库管理_查看与删除.py` | 数据库管理 |
| `A_撤单重发示例.py` | 订单撤单重发机制 |
| `A_穿透式测试脚本.py` | CTP穿透式认证测试 |

### 策略类 (B_开头)

| 文件 | 说明 |
|------|------|
| `B_双均线策略.py` | ⭐ 经典均线交叉，入门推荐 |
| `B_海龟交易策略.py` | 唐奇安通道突破 |
| `B_十大经典策略之Aberration.py` | 布林带突破 |
| `B_日内交易策略.py` | 日内交易 |
| `B_网格交易策略.py` | 网格交易 |
| `B_强弱截面轮动策略.py` | 多品种强弱轮动 |
| `B_跨周期过滤策略.py` | 多周期信号过滤 |
| `B_跨品种套利策略.py` | 品种间价差套利 |
| `B_跨期套利策略.py` | 同品种跨期套利 |
| `B_多品种多周期交易策略.py` | 多品种多周期 |
| `B_多品种多周期交易策略_参数优化.py` | 参数优化示例 |
| `B_机器学习策略_随机森林.py` | ML机器学习预测 |

### 高级类 (C_开头)

| 文件 | 说明 |
|------|------|
| `C_期权交易策略.py` | 期权交易 |
| `C_期货期权组合策略.py` | 期货期权组合 |
| `C_纯Tick高频交易策略.py` | TICK流高频交易 |

---

## 🏗️ 项目结构

```
ssquant/
├── api/                    # 策略API
│   └── strategy_api.py     # 核心API类
├── backtest/               # 回测引擎
│   ├── unified_runner.py   # 统一运行器
│   ├── backtest_core.py    # 回测核心
│   └── live_trading_adapter.py  # 实盘适配器
├── config/                 # 配置管理
│   └── trading_config.py   # 配置生成（账户配置在此）
├── data/                   # 数据管理
│   ├── api_data_fetcher.py # API数据获取
│   └── local_data_loader.py # 本地数据加载
├── ctp/                    # CTP二进制文件
│   ├── py39/ ~ py314/      # 各Python版本的CTP文件
│   └── loader.py           # CTP加载器
├── pyctp/                  # CTP封装
│   ├── simnow_client.py    # SIMNOW客户端
│   └── real_trading_client.py  # 实盘客户端
└── indicators/             # 技术指标
    └── tech_indicators.py
```

---

## 💡 核心API

### 数据获取

```python
api.get_close()      # 收盘价序列
api.get_open()       # 开盘价序列
api.get_high()       # 最高价序列
api.get_low()        # 最低价序列
api.get_volume()     # 成交量序列
api.get_klines()     # 完整K线DataFrame
api.get_tick()       # 当前TICK数据（实盘）
```

### 持仓查询

```python
api.get_pos()        # 净持仓（正=多，负=空）
api.get_long_pos()   # 多头持仓
api.get_short_pos()  # 空头持仓
api.get_position_detail()  # 详细持仓（今昨仓）
```

### 交易操作

```python
api.buy(volume=1)         # 买入开仓
api.sell()                # 卖出平仓
api.sellshort(volume=1)   # 卖出开仓
api.buycover()            # 买入平仓
api.close_all()           # 全部平仓
api.reverse_pos()         # 反手
```

### 多数据源

```python
# 访问第2个数据源（index=1）
close = api.get_close(index=1)
api.buy(volume=1, index=1)
```

详见 [API参考手册.md](API参考手册.md)

---

## 🔧 系统要求

- **Python**: 3.9 ~ 3.14
- **系统**: Windows 10+ (CTP仅支持Windows)
- **内存**: 4GB+
- **网络**: 稳定连接（实盘/SIMNOW）

### CTP版本支持

框架内置 CTP 6.7.x 版本，位于 `ssquant/ctp/pyXXX/` 目录：

| Python版本 | 目录 | 状态 |
|-----------|------|------|
| 3.9 | `py39/` | ✅ 已包含 |
| 3.10 | `py310/` | ✅ 已包含 |
| 3.11 | `py311/` | ✅ 已包含 |
| 3.12 | `py312/` | ✅ 已包含 |
| 3.13 | `py313/` | ✅ 已包含 |
| 3.14 | `py314/` | ✅ 已包含 |

---

## ⚙️ 账户配置

编辑 `ssquant/config/trading_config.py`：

```python
# SIMNOW账户
ACCOUNTS = {
    'simnow_default': {
        'investor_id': '你的SIMNOW账号',
        'password': '你的密码',
        'server_name': '电信1',  # 电信1/电信2/移动/TEST
        # ...
    },
    
    # 实盘账户
    'real_default': {
        'broker_id': '期货公司代码',
        'investor_id': '资金账号',
        'password': '密码',
        'md_server': 'tcp://xxx:port',
        'td_server': 'tcp://xxx:port',
        'app_id': 'AppID',
        'auth_code': '授权码',
        # ...
    },
}
```

---

## ⚠️ 风险提示

本框架仅供学习和研究使用。期货交易有风险，入市需谨慎。

- ⚠️ 请先在SIMNOW充分测试（至少1周）
- ⚠️ 实盘前用小资金验证
- ⚠️ 做好风险管理和止损
- ⚠️ 不要使用高杠杆

---

## 📖 快速链接

- [PyPI 主页](https://pypi.org/project/ssquant/) - 安装和版本信息
- [GitHub 仓库](https://github.com/songshuquant/ssquant) - 源码和问题反馈
- [用户手册](用户手册.md) - 完整使用教程
- [API参考](API参考手册.md) - 所有API详解

### 专题指南

| 文档 | 说明 |
|------|------|
| 数据获取与管理 | 数据获取、导入、落盘 |
| 回测配置与优化 | 历史回测配置和优化 |
| SIMNOW模拟指南 | 模拟盘配置和测试 |
| 实盘部署指南 | 实盘配置和风险管理 |

---

## 📝 更新日志

### v0.3.0 (2025-12)

- ✅ 完整的TICK流双驱动模式
- ✅ 多品种多周期支持
- ✅ 订单撤单重发机制
- ✅ 实时回调系统（on_trade/on_order/on_cancel）
- ✅ 动态price_tick和offset_ticks
- ✅ 统一的API接口
- ✅ 19个策略示例

---

**开始你的量化交易之旅！** 🚀

查看 [用户手册.md](用户手册.md) 了解详细使用方法。
