# 联调与可观测：moego 调试入口

适用于：用户报 bug、线上异常、联调失败时定位问题。

## 1. 环境概览

| 环境 | 用途 | 域名规律（前端推断 / OnlineBooking_Go_Web 配置） |
|---|---|---|
| local | 本地起的 dev server | `localhost:<port>` / 走 `MOE_RPC_HOST` 代理 |
| testing (t2) | feature 分支默认 deploy 环境 | `*.t2.moego.dev`（例：`api.t2.moego.dev`） |
| staging | 预上线 | ⚠️ TODO：t1 / staging 域名未在本次调研中确认 |
| canary (grey) | 灰度 | `*-grey-booking.*.moego.dev` |
| production | 生产 | `*.moego.pet`（例：`moego.pet`、`api.moego.pet`、`cdn.moego.pet`） |
| devops | DevOps 工具环境（白名单 app：`devops-console / gemini_mcp_client / aistudio / cs_page_watcher / devops-auth`） | ⚠️ TODO |

各前端仓库的 host 推断逻辑：

- `OnlineBooking_Go_Web/config/host.ts` 按 booking host 名判断环境（local / t2 / grey / prod）
- `Boarding_Desktop`：⚠️ TODO 应在 `src/config/host/` 或 middleware 内（具体文件未读到）
- `moego-mobile`：⚠️ TODO 应在 `src/api/` 或 `app.config.ts` 内（未读到具体逻辑）

## 2. 日志：Datadog

公司主日志栈是 Datadog。已有 `datadog` skill：

```
skill: datadog
入口: scripts/datadog.py
子命令: search-logs / aggregate-logs / get-trace / search-spans / get-dependencies / list-services
```

什么时候用：

| 场景 | 子命令 |
|---|---|
| 查某个 request 的全链路 trace | `get-trace --trace-id <id>` |
| 查 `x-request-id` / `@id` 关联日志 | `search-logs "@id:<value>"` |
| 查某接口 5xx / latency p99 | `aggregate-logs` + 服务名 |
| 查上下游依赖拓扑 | `get-dependencies --service <name>` |
| 查 API 超时 / canary 异常 | `search-logs` 过滤 service / env / status |

服务名约定：每个仓库部署后 service 名通常跟仓库名一致（如 `moego-api-v3`、`moego-svc-online-booking`、`moego-server-grooming`、`moego-bff`），具体看 deploy 配置。

## 3. 错误：Sentry

已有 `sentry` skill：

```
skill: sentry
入口: scripts/sentry.py
子命令: get-issue / fetch-event / list-issues / list-issue-events / tag-values / list-projects
```

什么时候用：用户报 crash / 前端白屏 / RN 闪退 / 后端异常被 Sentry 捕获时。

已知项目：

- `OnlineBooking_Go_Web` Sentry project: `online-booking-go-web`（`https://moego-ey.sentry.io/projects/online-booking-go-web`，README L27）
- 其他项目 ⚠️ TODO：未在本次调研中逐项核实

## 4. 业务数据：Redshift

已有 `redshift` skill（只读 Redshift 数仓）：

```
skill: redshift
入口: scripts/redshift.py
子命令: databases / schemas / relations / search / describe / query / explain / recipe / doctor
```

首次 live 查询先运行 `doctor --list-connections`，选择明确 connection 后再运行
`doctor --connection <name> --connect`。邮箱反查使用
`recipe email-to-company --connection <name> --email <value>`；不要继续调用 V1 的
`email-to-company` 顶层命令，也不要从 SQL、数据库名或连接错误猜 transport。

什么时候用：

- 查某个商家 / 客户的业务数据
- 用户邮箱反查 `company_id` + `business_id`（`email-to-company`）
- 对账 / 复盘历史数据

注意：是数仓快照，不是实时数据；想看实时业务表用对应 svc 的 DB 直连（⚠️ TODO：moego-svc-* 的实时 DB 入口未知，本次调研外）。

## 5. Jira 工单

已有 `jira` skill：

```
skill: jira
入口: scripts/jira.py
子命令: read / intercom / search / download-attachment / create / update
```

什么时候用：

- 读 ticket 详情 / 评论 / 附件截图：`read <issue-key>`
- 看 CS- 工单关联的 Intercom conversations：`intercom`
- 搜索 ticket：`search --jql`
- 创建 / 更新工单字段

## 6. Slack 沟通

已有 `slack` skill。Slack 主要用于：

- @ 同事问问题（产品 / 后端 / 设计）
- 上传调研结果 / 截图 / 报表（`files_upload`）
- 查频道历史消息

**约定**：当本次会话由 Slack 里 @mention agent 触发，"上传 / 发到 Slack / 这里 / thread" 默认就是触发本次会话的那个 thread——用 mention 上下文取 `channel_id` 和 `thread_ts`。

## 7. GrowthBook（feature flag）

已有 `growthbook` skill：

```
skill: growthbook
入口: scripts/growthbook.py
能力: 环境 / 项目 / Feature Flag / 实验 / 属性 / 指标
鉴权: GB_TOKEN
```

什么时候用：

- 灰度 / 实验开关查询
- 用户反馈 "我没看到 X 功能"——可能是 flag 没开

别名：`gw` / `GW` / `GB` / 白名单 / 开关 / 灰度开关 = feature flag。

## 8. 前端埋点

| 仓库 | 埋点工具 |
|---|---|
| Boarding_Desktop | `src/telemetry/`、`@moego/reporting`、`utils/tracker` 的 `reportData` / `reportGTMOnly`（在 SignIn 示例里见到） |
| moego-mobile | ⚠️ TODO 具体埋点 SDK 未抽样 |
| OB-client-web | ⚠️ TODO 未抽样 |

⚠️ 已知 memory 规则：埋点辅助函数等待异步依赖的延迟 / 守门逻辑必须写在 `reportXxx` 函数内部，调用点保持单行（来自 user feedback memory）。

## 9. 联调失败排查决策树

```
"前端拉不到字段 / 接口报错"
              │
              ▼
┌──────────────────────────────────┐
│ 1. 浏览器 DevTools Network        │
│    - 接口请求路径 / 方法 / 参数对吗？│
│    - 返回码 200/4xx/5xx？         │
│    - 返回 body 里有目标字段吗？     │
└──────────────────────────────────┘
              │
       ┌──────┴──────┐
       │             │
   有字段           没字段
       │             │
       ▼             ▼
   前端没渲染     后端没返
       │             │
       ▼             ▼
┌──────────┐  ┌────────────────┐
│ React    │  │ 走哪个 BFF？     │
│ DevTools │  │ - grpc → api-v3 │
│ Redux    │  │ - rest → bff    │
│ state    │  │ - rest → 老 svc │
│ 字段在吗？│  └────────────────┘
│ selector │           │
│ 写对了？  │           ▼
└──────────┘  ┌────────────────────────┐
              │ 1. Datadog trace by id │
              │    看哪一层丢了字段      │
              │ 2. Datadog logs 看异常  │
              │ 3. svc 的代码 → 走过 enricher / converter 吗？ │
              │ 4. Sentry 看后端有没有 exception              │
              └────────────────────────┘
```

## 10. 常见排查 case

| 现象 | 第一步查 | 第二步 |
|---|---|---|
| 前端报 `@moego/<X>@<tag>` 404 | nexus `npm view`（详见 api-web-publish-cheatsheet.md） | 看 api-definitions / moego-bff 分支 + CI |
| 前端字段缺失 | DevTools Network 看 response | 缺字段 → Datadog trace 后端聚合层 |
| 接口 500 | Sentry list-issues / Datadog search-logs | trace 定位异常栈 |
| 灰度环境字段缺失 | 看 grey forward context | 看 GrowthBook flag 是否开 |
| 老 svc 改了 Controller 但前端没生效 | 看前端 `src/openApi/*` git diff | `pnpm openapi` 是否真的拉到新 schema（默认 endpoint 配置） |
| dispute / 退款流程 bug | Jira ticket + Datadog 查相关 svc 日志 | Redshift 查商家近期 dispute 数据 |

## 11. NEVER 规则

- **不要光看前端代码就下结论字段缺失**——先看 Network response 体里有没有，再看后端
- **不要在 production 直接抓 user-level 日志而不脱敏**——Datadog / Redshift 查询都按只读最小权限
- **不要跳过 GrowthBook 检查就断言"功能没生效"**——可能是 flag 没对该用户 / company 开启
- **不要假设 staging 跟 production 数据一致**——staging 是预上线，数据可能脱钩
