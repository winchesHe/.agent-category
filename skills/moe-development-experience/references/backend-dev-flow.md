# Java 与 Node BFF 开发经验

- ID：`MDEV-BACKEND-DEV`
- 适用：Java 服务或 `moego-bff` 开发中，仓库规范入口、下游调用或特定工具失败的判断有缺口时。

## 仓库指南入口

遵循目标仓库及修改模块的 `AGENTS.md`、`README.md`；启动、测试、生成与格式化命令从实际构建配置确认，不由框架名称推断。

| 仓库 / 场景 | 按需读取 |
|---|---|
| Java RPC、业务实现与测试 | 本仓 README、当前接口实现和邻近测试；分层、鉴权、测试基类与事务机制按模块确认 |
| moego-svc-online-booking 的 Mapper 与数据库测试 | 本仓 README 已说明生成文件与可手改文件的边界、`MockStubs` 和测试回滚要求 |
| moego-bff 的 route、鉴权、环境和启动 | 本仓 README 的开发指南及 AGENTS.md 指向的相关文档；脚本与配置以当前版本为准 |

## moego-api-v3：Spotless 失败未必能自动修复

本仓 `build.gradle` 的自定义检查会拒绝 wildcard import 和直接 `new BizException(...)`：

- wildcard import 报错明确指出 `spotlessApply` 不能自动处理；手工替换成实际使用的 import，再运行对应检查。
- `new BizException(...)` 按本仓既有 `ExceptionUtil` 用法调整，保留原异常的业务语义。
- 这两项是本仓自定义规则；其他 Java 仓库报错时读其构建配置，不直接套用。

## Java gRPC 的定位入口

从当前 `@GrpcService` 实现和生成的 service 定义确定方法，再沿 `@GrpcClient`、实际加载的配置与调用方定位监听和下游。身份从拦截器及上下文填充逻辑核对，不能把某个仓库的 `AuthContext` 或请求头推广到全部服务。

实际调用读[本地 gRPC 调试](local-grpc-debugging.md)，复用协议、监听、metadata 与结果核对方法；本篇不再提供一套固定端口或鉴权头的调用模板。

## moego-bff：复用下游调用的上下文与错误处理

修改调用链时，先查看同模块现有调用及 `server/utils/invoke-svc-method.ts`、`server/middleware/svc-method-invoker.middleware.ts`：

- `invokeSvcMethod` 接收 client、方法和参数，使用 `withForwardContext` 传递调用上下文，并处理 trace 与错误转换。
- `invokeSvcMethodAutoThrow` 在同一调用结果上抛出错误；middleware 提供的 `c.callService` 是其别名。按模块已有用法选择，核对对应 middleware 确实挂载。
- import gRPC client 本身没有问题。README 也展示了直接调用 client 并显式传入 `withForwardContext(c)` 的方式；检查的是该路径是否保留所需上下文、trace 和错误语义，不能仅凭“直接调用”判错。
- 本地调用成功但经 BFF 命中错误分支时，对照下游实际收到的上下文；接口失败表现变化时，对照封装返回/抛出的错误与 route 的响应处理。

已有调用封装能够满足需求时优先复用。保留兼容路径或换一种调用方式，都要核对当前请求的实际行为，不为统一写法顺手改动其他接口。

## 生成、发布与排障的归属

| 当前缺口 | 按需读取 |
|---|---|
| api-node 等包的来源或 catalog / workspace 消费关系 | [npm 依赖](npm-dependencies.md) |
| BFF 导出 client/schema 变化，消费者需要新产物 | [BFF 包生成与发布](bff-openapi-publish-cheatsheet.md) |
| legacy runtime OpenAPI 生成内容不符 | [legacy codegen](legacy-svc-codegen.md) |
| 下游有字段、聚合结果缺失，或请求落错服务 | [联调与排障](debugging-and-observability.md)，按同一请求定位丢失环节 |
| 测试或构建通过，但目标版本未部署 | [Git 与 CI 排查](commit-and-review-conventions.md) |

仅改 handler 内部逻辑，不自动触发 SDK 升级或发包。测试采用当前模块的真实入口与已有设施，覆盖本次修改的行为；不由测试框架、注解名称或一次直接方法调用推断整条请求链已验证。
