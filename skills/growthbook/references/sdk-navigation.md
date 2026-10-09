# GrowthBook 官方 SDK 导航

来源：[GrowthBook SDK Overview](https://docs.growthbook.io/lib/)。

使用本导航前，先读目标仓库 lockfile。版本、runtime 要求和 API 名称以目标仓库与当前官方文档为准。

## 通用安全规则

- Client SDK 会把可用的 feature payload 交给客户端。敏感规则应改用 Server SDK 或经过架构确认的 Remote Evaluation。
- SDK API host、client key、decryption key 和 secure attribute salt 必须来自目标环境配置。
- 每次 evaluation 都要传稳定且类型正确的 attributes。不要记录敏感 attributes。
- feature 缺失、初始化失败和 timeout 必须返回业务定义的 fallback。
- 实验必须接 tracking callback。tracking 失败不能破坏业务请求。
- 不要手写规则 evaluator。使用目标仓库安装的官方 SDK 或现有内部 wrapper。

## Client SDK

| SDK | 用途 | 最低安全规则 | 官方入口 |
|---|---|---|---|
| HTML Script Tag | 普通网页和低代码页面 | 只放可公开的 client payload；遵守 consent | [文档](https://docs.growthbook.io/lib/script-tag) |
| JavaScript | Browser、Vanilla JS、TypeScript | 初始化前确认缓存、attributes 和 tracking | [文档](https://docs.growthbook.io/lib/js) |
| React | React hooks、Provider、SSR | 单例只用于同一用户域；SSR 必须保持 hydration 一致 | [文档](https://docs.growthbook.io/lib/react) |
| Next.js React 示例 | App Router、Pages Router、SSR | 按请求隔离 attributes；客户端复用相同 payload | [示例](https://github.com/growthbook/examples/tree/main/next-js) |
| Vue | Vue 3、Nuxt | 在 app lifecycle 初始化；SSR 保持 payload 和 attributes 一致 | [文档](https://docs.growthbook.io/lib/vue) |
| Kotlin Android | 原生 Android | client key 来自 app 配置；不要把敏感 targeting 暴露到设备 | [文档](https://docs.growthbook.io/lib/kotlin) |
| Flutter | Flutter 移动端 | 持久化稳定 ID；明确离线 fallback | [文档](https://docs.growthbook.io/lib/flutter) |
| Swift iOS | 原生 iOS | client key 来自 app 配置；明确缓存和离线 fallback | [文档](https://docs.growthbook.io/lib/swift) |
| React Native | React Native | 配置 storage/SSE polyfill 前先核对版本；清理订阅 | [文档](https://docs.growthbook.io/lib/react-native) |
| Roku | Roku channel | 只使用设备可公开的 payload；明确网络失败 fallback | [文档](https://docs.growthbook.io/lib/roku) |

## Server SDK

| SDK | 用途 | 最低安全规则 | 官方入口 |
|---|---|---|---|
| Node.js | Node Server、Express、Fastify、Hono | 复用 process client；每个请求创建独立 user context | [文档](https://docs.growthbook.io/lib/node) |
| Vercel Flags | Vercel Flags SDK、Edge Config | 不与 React SSR 示例混用；先确认部署平台 | [文档](https://docs.growthbook.io/lib/nextjs) |
| PHP | Laravel、Symfony、PHP | 按请求隔离 attributes；不要跨请求保留用户状态 | [文档](https://docs.growthbook.io/lib/php) |
| Ruby | Rails、Ruby | 按请求隔离 attributes；后台刷新不能阻塞请求 | [文档](https://docs.growthbook.io/lib/ruby) |
| Python | Async、FastAPI、Django、Flask | Async client 进程级复用；`UserContext` 请求级新建 | [文档](https://docs.growthbook.io/lib/python) |
| Java | Java、Spring | MoeGo 项目优先内部 wrapper；核对 JitPack 和锁定版本 | [文档](https://docs.growthbook.io/lib/java) |
| Kotlin JVM | Kotlin Server、Ktor | 不与 Android SDK 混用；按请求隔离 context | [文档](https://docs.growthbook.io/lib/kotlin-jvm) |
| C# | .NET、ASP.NET | client 生命周期跟随 host；请求 attributes 不进单例 | [文档](https://docs.growthbook.io/lib/csharp) |
| Go | Go service | 进程 client 复用并关闭；请求 attributes 用 child client | [文档](https://docs.growthbook.io/lib/go) |
| Rust | Actix、Axum、Rocket | 共享只读 client；请求 context 独立 | [文档](https://docs.growthbook.io/lib/rust) |
| Elixir | Phoenix、Elixir | client lifecycle 交给 supervision tree；请求 context 独立 | [文档](https://docs.growthbook.io/lib/elixir) |

## Edge 与协议层

| 入口 | 用途 | 最低安全规则 | 官方入口 |
|---|---|---|---|
| Cloudflare Workers | Worker 内评估和 redirect | 控制 CPU、缓存和 payload 大小 | [文档](https://docs.growthbook.io/lib/edge/cloudflare) |
| Fastly Compute | Fastly Edge、Wasm | 明确缓存新鲜度和资源上限 | [文档](https://docs.growthbook.io/lib/edge/fastly) |
| Lambda@Edge | CloudFront request/response | 控制冷启动、区域复制和 timeout | [文档](https://docs.growthbook.io/lib/edge/lambda) |
| Other Edge | 其他 edge runtime | 先验证 Web API 和持久缓存支持 | [文档](https://docs.growthbook.io/lib/edge/other) |
| OpenFeature Provider | 已采用 OpenFeature 的服务 | 保留 provider error、reason 和 context 语义 | [文档](https://docs.growthbook.io/lib/openfeature) |
| Build Your Own | 无官方 SDK 的 runtime | 必须通过官方 test cases；不要简化 hashing 或条件语义 | [文档](https://docs.growthbook.io/lib/build-your-own) |
