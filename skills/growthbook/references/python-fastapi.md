# Python Async 与 FastAPI

官方入口：[GrowthBook Python SDK](https://docs.growthbook.io/lib/python)。

收到的 Python 参考只提供通用设计线索。不要复制其中的 endpoint、client key 或版本声明。

## 版本门禁

1. 读取 `pyproject.toml`、`uv.lock`、`poetry.lock` 或 `requirements*.txt`。
2. 查找现有 `GrowthBookClient` wrapper 和 FastAPI lifespan。
3. 用安装版本源码或类型信息确认 `Options`、`UserContext` 和 method 签名。
4. 当前官方文档只用于核对最新能力。目标仓库 lockfile 决定可用 API。

## FastAPI lifecycle

长驻 async app 使用一个 `GrowthBookClient`。在 lifespan startup 初始化，在 shutdown 关闭：

```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from growthbook import GrowthBookClient, Options


def create_client(settings) -> GrowthBookClient:
    return GrowthBookClient(
        Options(
            api_host=settings.growthbook_api_host,
            client_key=settings.growthbook_client_key,
        )
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = create_client(app.state.settings)
    try:
        initialized = await asyncio.wait_for(
            client.initialize(),
            timeout=app.state.settings.growthbook_init_timeout_seconds,
        )
    except asyncio.TimeoutError:
        initialized = False
    app.state.growthbook = client if initialized else None
    try:
        yield
    finally:
        await client.close()
```

目标仓库已有 dependency injection 或 wrapper 时，复用现有结构。

## 请求隔离

`GrowthBookClient` 可以进程级复用。`UserContext` 必须每次请求或 job 新建：

```python
from growthbook import UserContext


async def is_enabled(client, feature_key: str, company_id: str) -> bool:
    user = UserContext(attributes={"company": company_id})
    return await client.is_on(feature_key, user)
```

- 不要在共享 client 上保存当前用户 attributes。
- background job 也要新建 `UserContext`。
- attributes 使用 JSON-compatible 值，并遵循 GrowthBook 配置的类型。
- 不要跨 request 复用 mutable dict 或 `UserContext`。

## Fallback

- 初始化失败、client 未配置、feature 缺失和 evaluation exception 要分开处理。
- fallback 必须由业务 owner 定义。不要默认 fail open。
- fallback 与 feature value 类型一致。
- 日志记录 feature key 和错误类别。不要记录完整 attributes 或 secret。

## Tracking

- 通过目标版本支持的 callback 或 plugin 接入现有 analytics。
- callback 要快速。慢 I/O 交给现有 queue 或 background worker。
- tracking 失败不能改变 evaluation 结果。
- 使用 evaluation 对应的 `UserContext` 取稳定主体 ID。

## Tests

- 注入 fake wrapper，不访问真实 GrowthBook。
- 覆盖 initialized、disabled、missing、exception 和目标 attributes。
- 并发测试使用两个独立 `UserContext`。
- 测试 lifespan 会关闭 client。
- 不在单元测试写真实 endpoint 或 client key。

## Review 清单

- [ ] 已读 Python lockfile 和现有 wrapper。
- [ ] `GrowthBookClient` 跟随 FastAPI lifespan。
- [ ] 每个 request 或 job 新建 `UserContext`。
- [ ] fallback 由业务语义决定。
- [ ] tracking 不阻塞 event loop。
- [ ] 配置来自 settings 或 secret provider。
