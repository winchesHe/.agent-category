# MoeGo 仓库与模块定位

- ID：`MDEV-REPO-NAVIGATION`
- 适用：目标仓库、应用、接口实现或依赖包源码尚不明确。

已有代码、请求和配置足以确定改动入口时，直接继续开发。这里提供候选位置和确认方法；仓库名、业务名与协议类型都不能单独证明当前请求由谁处理。

## 从已有线索找入口

| 已有线索 | 下一步与确认依据 |
|---|---|
| 页面、客户端或具体 URL | 找本端路由与组件，再沿实际 query/hook、客户端封装核对请求 host、path 和响应。只有确实需要后端变化时才继续追服务 |
| HTTP 路径、RPC 方法或 trace | 从真实调用代码、网关/代理配置、部署服务与 trace 定位实现；同为 gRPC 或 REST 也可能走不同入口，不据此固定选择某个 BFF |
| 业务概念、字段或 Jira 描述 | 用业务词和已知 symbol 缩小候选，核对实际读写方与调用方；语义不清时用 `moe-business-context`。ticket 前缀只能辅助检索 |
| Go 应用或部署服务名 | 从大仓 `backend/app/` 找候选，再用注册入口、配置和 metadata 确认；应用目录名、协议 service 名与部署名分别核对 |
| npm 包、import 或生成类型 | 按[npm 依赖](npm-dependencies.md#从实际消费入口反查)从消费仓反查包、workspace 或生成源 |
| 已知入口不存在或仓库不在下表 | 通过 `github-workflow` 按仓库名、描述及实际 symbol 定向发现；发现仓库内有改名或迁移说明时沿当前实现继续，不为套表而扩大改动范围 |

## 仓库候选与职责

下表用于缩小搜索范围，不是必须修改的仓库清单。分支、文件和实际消费关系仍需从当前任务核对。

| 仓库 | 定位线索 |
|---|---|
| `moego` | Go 大仓及部分前端/Node 应用；后端从 `backend/app/`、协议从 `backend/proto/`、前端/Node 从 `frontend/app/` 查起 |
| `moego-api-definitions` | api-web/api-node SDK 链路的 proto 与发布源候选；查 `proto/` 和生成/发布配置，不当作所有 MoeGo 协议的唯一来源 |
| `moegoapis` | 共享 Buf proto 模块；沿消费仓的 Buf 依赖确认使用关系 |
| `moego-api-v3` / `moego-client-api-v1` | Java gRPC BFF；分别是商家端、C 端/消费者 App 的入口候选，按实际客户端与路由确认 |
| `moego-bff` | Node BFF；`server/routes/`、`server/services/` 与 `packages/{openapi,schemas,legacy-api}/`。与 Java BFF 分开定位 |
| `moego-svc-online-booking` / `moego-svc-appointment` | OB、预约领域服务候选；从 RPC 实现和实际数据调用确认，不因业务同名就认定当前链路经过它们 |
| `moego-svc-activity-log` | 活动日志的 event/processor/server 模块候选；按事件入口与处理链定位 |
| `moego-server-grooming` | legacy HTTP 业务入口候选；从 Controller、实际路由和下游调用确定领域实现 |
| `moego-server-common` / `moego-server-api` | legacy 共享代码与业务契约；从依赖和使用位置确认，不把契约定义当作运行服务 |
| `moego-java-lib` | Java 公共库；从 import、Gradle 依赖和对应子模块找实现 |
| `moego-open-api-v1` | 对外 Open API 的 Go 仓库候选；`internal/` 下沿 service、logic、repo 与装配入口定位，不套用 legacy Java codegen |
| `Boarding_Desktop` | 商家 PC；从 `src/router/`、`src/container/` 与 `src/query/` 等实际调用位置定位 |
| `moego-mobile` | 商家 App；从 `src/modules/`、入口路由和本模块 API 定位 |
| `moego-online-booking-client-web` | React OB Web；从 `src/routes.ts`、页面与客户端封装定位 |
| `OnlineBooking_Go_Web` | Vue/Nuxt OB Web；从页面路由与 `config/host.ts` 等请求配置定位。与 React OB 的选择以实际页面和部署为准 |
| [moego-client-portal](https://github.com/MoeGolibrary/moego-client-portal) | Client Portal 与 Report Card 页面入口；按实际页面和请求区分 OB Web、消费者 App 与本仓实现 |
| [moego-ui](https://github.com/MoeGolibrary/moego-ui) | Web 基础组件与设计 Tokens；查 `@moego/ui`、`@moego/design-tokens` 的定义与导出。查询现有组件能力时可按仓库说明使用 `@moego/ui-cli` |
| [moego-client-libs](https://github.com/MoeGolibrary/moego-client-libs) | OB Web 与 Client Portal 的共享前端能力；从消费仓 import 反查对应包，跨仓本地联动方法读本仓 README |
| [moego-finance-kit](https://github.com/MoeGolibrary/moego-finance-kit) | 跨端支付逻辑、订单能力与 Web/RN 金融组件；先核对消费端使用的入口包，再定位共享实现 |
| [moego-admin-web-v3](https://github.com/MoeGolibrary/moego-admin-web-v3) / [moego-admin-api-v3](https://github.com/MoeGolibrary/moego-admin-api-v3) / [moego-admin-svc-v3](https://github.com/MoeGolibrary/moego-admin-svc-v3) | MIS 前端、Admin API Gateway、Admin Service Gateway 的候选入口；开发 MIS 功能时沿页面请求确认实际调用关系 |
| [moego-agent](https://github.com/MoeGolibrary/moego-agent) | Slack Agent 运行时、会话、消息渲染与 MCP 接入；运行时行为从本仓定位，插件内容从实际加载来源确认 |
| [moego-ai-plugin](https://github.com/MoeGolibrary/moego-ai-plugin) | 公司共享 Agent 插件与 skills 的开发、分发入口；与个人 skills 仓库区分，按安装来源确认要修改的版本与归属 |
| [moego-actions-tool](https://github.com/MoeGolibrary/moego-actions-tool) | 共享 GitHub Actions workflows 与 CLI；业务仓 workflow 引用了公共能力时，继续沿调用与版本定位本仓实现 |
| [moego-k8s-apps](https://github.com/MoeGolibrary/moego-k8s-apps) | 应用 Kubernetes 配置；部署配置不在业务仓时，按实际应用、环境和部署引用查找 |
| [moego-devops-console](https://github.com/MoeGolibrary/moego-devops-console) | 通过 PR 提交数据库、MQ、缓存等环境资源变更的请求、schema 与执行流程；与 `moego/frontend/app/devops-console/` 页面入口分别定位，具体关系按实际调用确认 |

前端开发先遵循消费仓 AGENTS.md 与指南；组件、状态复用或页面验证有缺口时见[前端开发](frontend-dev-flow.md)，包来源与升级见[npm 依赖](npm-dependencies.md)。

## Go 大仓内继续定位

先读取目标应用范围内的仓库规则、说明与相似实现，再按问题选择位置：

| 目标 | 查找位置与用途 |
|---|---|
| 后端入口与业务实现 | `backend/app/<app>/` 的 `main.go`、注册/装配入口与实际业务模块；沿调用找到 Reader/Repo/代理，区分本地实现与下游数据来源 |
| 共享后端能力 | 从已有 import 追到 `backend/common/` 或真实依赖包；公共能力所在位置不决定业务数据归属 |
| 协议与生成源 | 从实际方法与生成文件追到 proto，结合 `buf.yaml`、生成配置和构建依赖确认；协议在本仓不意味着消费者无需生成或更新产物 |
| 前端/Node 应用 | `frontend/app/<app>/package.json` 与入口文件；例如 `frontend/app/devops-console/`。各应用脚本可能不同，不能用根目录 package.json 代替应用配置 |
| 前端共享能力 | 从应用 import 追到 `frontend/common/` 或实际 workspace/依赖包，核对导出入口和构建关系 |
| 构建与部署对应关系 | 当前应用 BUILD、配置、metadata 与仓库 CI；用它们确认目标应用，不在导航阶段展开部署流程 |

新增独立应用或 RPC 服务时，按[新增服务](backend-service-handbook.md)检查注册与配置；已有服务仅新增方法或修改内部逻辑，不需要默认加载该手册。

## 定位到哪里就够了

能用当前文件、调用或配置说明“本次改哪个仓库/模块、从哪里进入、为何属于这里”，即可回到开发。只在改动涉及外部调用或产物时补足对应依赖；保留会改变实施范围的未知项，不继续枚举无关仓库。

本地 cache、任务 worktree 与源码搜索操作由 `github-workflow` 提供；本文件不维护安装路径或另一套 Git 操作。
