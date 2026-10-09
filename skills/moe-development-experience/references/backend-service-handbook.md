# Go 大仓应用运行与新增服务

- ID：`MDEV-NEW-SERVICE`
- 适用：`moego` Go 大仓；已有应用构建与本地运行、新增 RPC 服务或独立应用，以及注册、部署与 Grey 服务发现。

## 已有应用：构建与本地运行

已有应用修改后准备启动时，先读目标仓库及应用的 AGENTS.md、README，按当前 Makefile 核对以下条件：

| 待确认条件 | 经验与完成判断 |
|---|---|
| 启动的是本次源码产物 | `make run app=<app> local=1` 的 run 入口复制已有 Bazel 产物启动。先核对当前 recipe 使用的目标与路径，确认已按当前源码重新构建；运行成功不能证明包含本次修改 |
| local 的实际依赖落点 | `local=1` 选择 local 配置，但其中仍可能连接 testing 数据库、Kafka 或其他远端服务。沿实际加载配置核对本次运行会用到的依赖目标，不凭文件名判断环境 |
| 验证覆盖本次行为 | Go 测试通过不能代替应用使用的 Bazel 构建；选当前应用/包的测试与构建目标，再用原请求验证本次修改。依赖缺失而跳过的测试不算集成验证通过 |

这些条件已确认时继续本次运行验证。检查范围随改动和症状扩展：注册、监听、Secret 或部署发生变化或出现对应故障时，才读取下方相应章节。

## 先确定改动入口

| 需求 | 必要改动 |
|---|---|
| 已有 RPC 服务增加方法 | 核对协议、实现与生成产物；服务名和监听不变时，不为新方法复制一份服务配置 |
| 在已有应用新增 RPC 服务 | `backend/proto/<app>/`、实现与注册入口、各环境服务配置；沿用应用部署 |
| 新增独立应用 | 应用骨架、proto、BUILD、独立配置与 metadata，以及对应部署资源 |

先读仓库及目标应用的 AGENTS.md、README；Go 大仓协议从 `backend/proto/` 查起。消费方是否需要新 SDK，取决于实际使用的接口；确认需要时读[协议包发布](api-web-publish-cheatsheet.md)。

## 从脚手架补齐应用

先对齐 `go.mod`、`.bazelversion` 与仓库工具要求，避免把本机工具链不兼容误判为业务错误。独立应用使用仓库已有入口：

```bash
# example_service 替换为实际应用名。
make create service=example_service
```

入口由 `Makefile` 路由到 `scripts/.create_app.sh`。执行前读脚本，检查模板、错误码分配与 CODEOWNERS 更新。脚本的缺参数、目录已存在等分支可能以 0 退出，且过程中会修改协议、错误码与应用目录；以实际文件完整性判断结果，失败后先查已生成内容，不直接重跑或手工复制半套骨架。

| 位置 | 生成后检查 |
|---|---|
| `backend/app/<app>/main.go`、`service/` | 依赖装配、RPC 实现与注册 |
| `backend/proto/<app>/`、`backend/proto/error_codes.yaml` | 正式协议、错误码冲突与生成产物 |
| `backend/app/<app>/config/` | 各部署环境的监听、依赖与 Secret；移除未使用的模板配置 |
| `backend/app/<app>/metadata.yaml` | 部署名称；需要自动 CD 时检查 `cd: true` |
| `BUILD.bazel`、CODEOWNERS | 生成器输出与实际依赖、归属一致 |

## RPC 注册与配置要成对检查

代码注册的 `ServiceDesc.ServiceName` 必须与配置 `server.service[].name` 一致；配置中的 filter 也需要对应实现注册。逐环境对照注册入口与 YAML，重点检查每个服务自己的 `ip/port/protocol/timeout`，不能只判断 YAML 能否解析。

| 现象 | 检查与判断 |
|---|---|
| 注册阶段 nil panic | 注册名是否存在于所加载的环境配置；缺项应在启动检查时明确报错 |
| 新 RPC 加入后原端口失效 | YAML 字段是否挂错列表项，端口是否变成 0 |
| 配置正确但无监听 | 按各地址组检查服务分配与监听逻辑，多地址不能只按全局服务数判断 |
| Pod Running 但调用失败 | 核对实际配置、容器与监听端口，再发真实 RPC；Pod 状态不能证明 RPC 可用 |

## 依赖、Secret 与数据库落点

客户端使用的代理名要与配置 `callee` 一致。Secret 需要同时核对**名称、注入前缀、字段键**；只写 `${...}` 不会自动加载所引用的 Secret。解析后检查必填项，报错时不输出凭据或完整 DSN。

本地启动使用[已有应用：构建与本地运行](#已有应用构建与本地运行)核对产物与依赖环境。

数据库连接成功后，还要确认实例、库名与所需 schema。部署新镜像不会自动补齐数据库迁移，按应用的迁移机制执行；具体检查见[数据库与 Redis 调试](database-debugging.md)。

## 生成与构建

生成、构建与测试命令按仓库 README 和当前 Makefile 选择。当前 `make proto` 会重建协议生成文件；执行后检查语义差异及范围，不能只看目标文件。`build` 若已依赖 Gazelle，无需重复执行。

新增 import 引发 Bazel strict deps 错误时，检查 Gazelle 与 BUILD 输出。构建、测试与运行的验证边界见[已有应用：构建与本地运行](#已有应用构建与本地运行)。

## 部署和 Grey 分开定位

独立应用按“CI 识别应用 → 构建镜像 → CD 更新 GitOps → ArgoCD 同步 → 实际资源”检查。入口包括 `.github/workflows/app-ci.yaml`、`app-deploy.yml` 和 `scripts/.get_changed_apps.sh`，分支匹配与 changed apps 以目标版本为准。

| 现象 | 下一步 |
|---|---|
| CI 没构建新应用 | 查应用路径匹配与 changed apps，确认构建目标 |
| 有镜像但没有 Pod | 查 metadata 的 CD 开关、Deploy job、GitOps 中的应用发现配置与同步结果 |
| namespace 正确但连错环境 | 查镜像启动命令、`MOEGO_ENVIRONMENT` 与容器实际选择的配置 |
| feature Pod 正常但 Grey 无分支 | 查基础版本与 feature 的 Service、标签、selector、端口，再查 watcher 发现条件 |
| Grey 可见但默认调用失败 | 查基础 Service 的 EndpointSlice；有 Service 不代表有可用后端 |
| BFF 调到了旧版 | 分别核对 BFF 和后端部署版本、每一跳的路由信息与客户端产物 |

在依赖基础版本的 watcher 路径中，只有 feature Pod 不足以完成服务发现；先确认基础资源真实可用。不要靠空 Service 或创建业务 Grey 规则掩盖部署缺项。`version: production` 可能表示基础版本标签，环境仍由 namespace 与实际配置决定。

Grey 查询通过 `moe-grey`，service 使用部署服务名；Git、CI 操作通过 `github-workflow`。服务发现成功与业务选择哪个版本是两步，分别验证。

最小可用结果是：目标镜像运行、配置和依赖正确、准确版本能处理真实 RPC。转发和协议核对见[本地 gRPC 调试](local-grpc-debugging.md)；包含异步业务时继续验证最终结果。
