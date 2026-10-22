# ssquantdata 0.1.3 使用说明

[PyPI 0.1.3](https://pypi.org/project/ssquantdata/0.1.3/) 于 2026-10-21 发布。本页补充该版本的能力和限制；PyPI 历史页面保留上传时的 README。

## 安装与升级

需要 Python 3.9 及以上。保留 0.1.3 的环境可执行：

```bash
python -m pip install "ssquantdata==0.1.3"
```

新环境推荐 [0.1.4](ssquantdata-0.1.4.md)。框架本体从 [SSQuant 源码仓库](https://github.com/songshuquant/ssquant) 安装，不能用 PyPI 上的旧 `ssquant` 提示包替代。

## 数据与鉴权

- 俱乐部账号鉴权、HTTP Bearer 自动续期、历史 K 线、批量任务和实时 K 线通过同一个 SDK 客户端。
- `SSQUANTDATA_USERNAME`、`SSQUANTDATA_PASSWORD` 可由环境变量提供。不要把账号和 Token 写入项目或日志。
- 返回原始价量、成交额、持仓变化、订单流及服务端覆盖字段。字段未知保留未知，不把 NULL 补成零；复权由框架或调用方完成。
- 0.1.3 增加周/月线名称和自定义周期参数的接受能力。是否能查询仍取决于服务端；SDK 不在本地重聚合。

标准周期是 `1M/5M/15M/30M/1H/1D`，具体支持情况以当前服务端能力和实际响应为准。`W` 规范化为 `1W`，`60M` 规范化为 `1H`。2026-10-21 月线旧名称 `1Y` 的生产请求返回 500，因此月线仍未通过验收，不应反复尝试别名。

```python
from ssquantdata import SSQuantDataClient

with SSQuantDataClient.from_env() as client:
    result = client.futures.history("rb888", "1M", limit=10)
    print(result.count)
    print(result.records[-1] if result.records else None)
```

## 实时连接的限制

HTTP 自动续期不等于已经建立的 WS 自动续鉴权。0.1.3 在连接中断或发现实时序号缺口后，先交付有效前缀和 `GapEvent`，随后抛出 `RealtimeGapError` 并停止。该版本没有自动重连补齐保证。

历史预加载、连接成功或队列为空不能证明断线期间 K 线完整。发生缺口后应核对并重建业务状态，不能直接继续用旧缓存交易。0.1.4 的配套方案见[新版说明](ssquantdata-0.1.4.md)。
