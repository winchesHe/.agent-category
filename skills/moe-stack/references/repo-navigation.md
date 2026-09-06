# moego 仓库导航

新接 moego 项目时先看这张表，定位"我要改的代码在哪个仓库"。

## 1. 仓库角色矩阵

### 1.1 后端

| 仓库 | 角色 | 语言 / 构建 | 入口目录 |
|---|---|---|---|
| `moego-api-definitions` | gRPC proto SoT；发 `@moego/api-web` / `@moego/api-node` | protobuf + Node CI | `proto/` |
| `moegoapis` | 公司共享 proto buf 模块（`buf.build/moegoapis/moegoapis`），不发前端包 | protobuf + buf | 顶层 buf module |
| `moego-bff` | Node BFF（hono + zod-openapi）；发 `@moego/bff-openapi` / `@moego/bff-schemas` / `@moego/legacy-api` | TS + pnpm 10 + tsx + Vitest | `server/` + `packages/{openapi,schemas,legacy-api}/` |
| `moego-api-v3` | Java gRPC BFF（**商家端**） | Gradle + Spring Boot 3 + Java 17 | `src/main/java/com/moego/api/v3/<domain>/` |
| `moego-client-api-v1` | Java gRPC BFF（**C 端 / 消费者 App**） | Gradle + Spring Boot | `src/main/java/com/moego/client/api/v1/<domain>/` |
| `moego-svc-online-booking` | Online Booking 业务 svc（gRPC） | Gradle + Spring Boot + MyBatis | `src/main/java/com/moego/svc/online/booking/server/` |
| `moego-svc-appointment` | Appointment 业务 svc（gRPC） | 同上 | `.../svc/appointment/controller/` |
| `moego-svc-activity-log` | Activity Log 业务 svc（多模块：event/processor/server） | Gradle 多模块，JDK 17 | `moego-svc-activity-log-server/src/main/java/.../server/` |
| `moego-server-grooming` | **Grooming 旧 monolith（HTTP）**：预约主链路 / OB / Smart Scheduling / AI Scheduler | Gradle 多模块 + Spring Boot + MyBatis | `moego-server-grooming/src/main/java/com/moego/server/grooming/web/` |
| `moego-server-common` | 旧 monolith 共享代码库（dto/utils/enums/exception/...） | Gradle | `moego-server-common/src/main/java/com/moego/common/` |
| `moego-server-api` | 旧 monolith 业务契约层（DTO/VO/Param/API client） | Gradle 多模块 | `moego-server-api/src/main/java/com/moego/{server,api}/` |
| `moego-java-lib` | Java 共享库聚合仓（17 个子模块：activemq/aws/common/encryption/event-bus/feature-flag/post-hog/...） | Gradle 多模块 | `moego-lib-*/src/main/java/` |
| `moego-devops-console` | DevOps 控制台（详情 ⚠️ TODO，本次未深入） | ⚠️ TODO | ⚠️ TODO |
| `moego` | **Go monorepo（Bazel）**：所有 Go 微服务 + proto SoT + 部分前端 | Bazel + Makefile | `backend/app/<service>/`、`backend/proto/`、`frontend/` |
| `moego-open-api-v1` | Go 项目：对外 Open API gRPC | Go 1.24 + Makefile + wire + mockgen | `internal/{service,repo,logic,entity,wire,...}/` |

### 1.2 前端

| 仓库 | 角色 | 技术栈 | 状态管理 | 构建 |
|---|---|---|---|---|
| `Boarding_Desktop` | **商家 PC 端**（Boarding + Grooming 业务） | React 17 + TS 5.8 + antd 4 | **amos** + React Query v4 | **rsbuild**（rspack）+ pnpm 10 |
| `moego-mobile` | 商家 RN App | RN 0.77 + Expo 52 + TS 5.8 | **经典 Redux + thunk** + React Query v4 | Expo / Metro + pnpm 8 |
| `moego-online-booking-client-web` | **C 端 OB Web（新版，React 重写）** | React 18 + TS + 自研 SSR | **Jotai** + React Query v5 | Vite 4 + pnpm 8 |
| `OnlineBooking_Go_Web` | C 端 OB Web（**老版，Vue/Nuxt**），与上面并存 | **Vue 2 + Nuxt 2** + TS | Vuex 3 | Nuxt2 (webpack) + yarn |

注：`moego-mobile` 仓库名带 hyphen，跟 `Boarding_Desktop`、`OnlineBooking_Go_Web` 命名风格不一致——别看错。

## 2. 任务 → 入口仓库

| 任务 | 入口仓库 |
|---|---|
| "Boarding_Desktop 加客户标签字段" | 先看接口在哪定义：grpc → `moego-api-definitions` + `moego-api-v3`；node REST → `moego-bff`；老 svc REST → `moego-server-grooming`。详见 §3 决策树 |
| "moego-mobile 列表加一个状态" | 路径同上，前端入口换成 `moego-mobile/src/modules/<Module>/` |
| "C 端 OB 加新流程" | 新版用 `moego-online-booking-client-web`；老版用 `OnlineBooking_Go_Web`。问产品确定走新版还是老版 |
| "改 appointment 业务逻辑" | `moego-svc-appointment`（gRPC）+ `moego-api-v3`（聚合） |
| "改 grooming 列表 / 预约老逻辑" | `moego-server-grooming`（旧 monolith） |
| "改通知中心字段" | `moego-api-v3/.../notification/`（聚合 + enricher）+ 协议层（proto 或 dynamic Struct） |
| "改活动日志" | `moego-svc-activity-log` |
| "Go 服务改逻辑" | `moego/` monorepo `backend/app/<service>/` |
| "对外 Open API" | `moego-open-api-v1` |

## 3. 拿到 Jira ticket 后第一步

```
1. 看 ticket 标题 / 描述，判断业务域（grooming / booking / customer / fintech / notification / ...）
2. 用业务域反查仓库：
   - grooming 老业务（calendar / appointment / schedule） → moego-server-grooming + 可能 moego-api-v3
   - online booking 商家配置 → moego-svc-online-booking + moego-api-v3
   - appointment 数据（创建 / 状态 / 流转） → moego-svc-appointment + moego-api-v3
   - 通知 / 消息中心 → moego-api-v3/notification/ + 可能 moego-server-grooming
   - 财务 / 支付 / Finance → 详情 ⚠️ TODO（FIN- ticket 常涉及 finance-* 系列 npm 包）
   - C 端用户 / 注册 / 我的 / 预约 → moego-client-api-v1 + moego-online-booking-client-web 或 OnlineBooking_Go_Web
3. 用 ticket 前缀辅助（参考 commit-and-review-conventions.md §2 前缀表）
4. 前端入口由产品 / mock 截图判断 PC 端、Mobile、还是 C 端
```

## 4. 仓库本地缓存路径

按全局约定，所有 moego 仓库 clone 到固定目录：

```
/Users/moego-winches/Desktop/Company/person/agent-workspace/repo/back-end/
/Users/moego-winches/Desktop/Company/person/agent-workspace/repo/front-end/
```

复用前先 `ls` 看本地是否已有；已有则直接复用（不要重复 clone），需要最新代码时 `git fetch origin` + 用 `origin/<default-branch>` 而不是本地 main。

## 5. 几个易混点

| 易混点 | 澄清 |
|---|---|
| moego vs moego-api-v3 vs moego-api-definitions | **moego** = Go 大 monorepo（Bazel）；**moego-api-v3** = Java gRPC BFF（商家）；**moego-api-definitions** = 所有 gRPC proto SoT |
| moego-bff vs moego-api-v3 | **moego-bff** = Node BFF（hono + REST，前端维护）；**moego-api-v3** = Java BFF（gRPC，后端维护）。前端**两个都调** |
| moego-svc-* vs moego-server-* | **svc-*** = 新业务 gRPC 微服务（per-domain）；**server-*** = 旧 Java HTTP monolith（grooming/common/api） |
| moego-client-api-v1 vs moego-api-v3 | 都是 Java gRPC BFF，**v3** 给商家，**client-api-v1** 给 C 端消费者 App |
| moego-online-booking-client-web vs OnlineBooking_Go_Web | 同是 C 端 OB Web，**前者**新版（React + Vite），**后者**老版（Vue + Nuxt2），并存中 |
| moego-mobile 用 Redux 而 Boarding 用 amos | 状态管理范式不统一，新代码别盲目复制 |
