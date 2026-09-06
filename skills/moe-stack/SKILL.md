---
name: moe-stack
description: >-
  MoeGo 跨栈协议与交付路由。用于任务实际跨越协议定义、后端、前端、SDK/代码生成、联调或发布中的至少两层，
  或首次处理 MoeGo 任务且无法判断仓库归属；按需路由 proto、Node BFF OpenAPI、legacy runtime OpenAPI、
  dynamic Struct、@moego/api-web/@moego/bff-openapi 和跨仓验证。单仓纯 Java/TypeScript/UI/CLI 修改不触发。
---

# MoeGo Stack：跨栈边界与交付路由

本 skill 只负责三件事：判断是否跨栈、确认协议/产物边界、给出可验证的跨仓顺序。仓库命令、框架细节、调试与发布规约按场景加载 References，不在主文档重复。

## 0. 路由门禁

先分类，再读 reference。不要因为消息里出现“前端”“proto”“SDK”等单个词就加载整套流程。

### 使用

满足任一条件时使用：

1. 当前任务实际跨越以下至少两层：协议定义、业务服务、BFF、前端、SDK/codegen、部署联调。
2. 需要判断字段属于显式 gRPC proto、Node BFF OpenAPI、legacy Java runtime OpenAPI，还是已有 dynamic Struct 中的 key。
3. 前端需要消费尚未发布的 `@moego/api-web`、`@moego/api-node`、`@moego/bff-openapi` 或 in-tree OpenAPI 生成代码。
4. 跨仓 PR review、改动面评估、依赖/合并顺序或 testing 联调。
5. 首次处理 MoeGo 任务，尚不知道目标能力位于哪个仓库。此时只加载 `references/repo-navigation.md`，定位后重新过门禁。

### 不使用

以下情况只遵循目标仓库的 AGENTS/README 和定向验证，不加载本 skill 的其他 reference：

- 单仓纯 Java、TypeScript、UI、CLI、文案或样式修改。
- 单仓 bug 已确认不改变接口、协议、SDK、代码生成、其他仓库或发布链路。
- 只查一个 PR、Jira、日志或数据源，且不需要判断跨仓影响。
- 历史转录、周报、skill 正文里偶然出现跨栈术语；当前任务本身并不跨边界。

### 拿不准时

只做一次轻量侦察：

1. 写出当前目标仓库、接口入口和消费者。
2. 检查是否存在跨仓依赖或生成产物变化。
3. 若仍是单仓，停止加载本 skill；若确认跨层，再进入下面流程。

## 1. 固定工作流

每个跨栈任务都按以下顺序推进，并在答案或计划里显式写出结果。

### Step 1：画真实依赖图

至少列出：

```text
协议 SoT → 字段生产者 → 聚合/BFF → 消费者 → 发布或部署产物
```

不要按仓库列表机械排序。开发可以并行，但端到端验证必须服从真实调用依赖：通常先协议产物，再字段生产者，再聚合/BFF，最后消费者。

### Step 2：判定协议类型与是否产生新产物

回答四个问题：

1. 字段是否改变显式 proto / OpenAPI schema？
2. 哪个仓库是唯一 SoT？
3. 消费者拿类型的方式是 npm SDK、in-tree codegen，还是已有 `Struct` 基础类型？
4. 消费者是否确实需要一个尚未发布的 feature 产物？

只有第 4 题为“是”，才进入 feature 包发布。不能从历史案例直接推导需要发包。

### Step 3：只加载相关 reference

- 找仓库：只读 `repo-navigation.md`
- gRPC SDK 发包：只读 `api-web-publish-cheatsheet.md`
- Node BFF 包：只读 `bff-openapi-publish-cheatsheet.md`
- legacy Java OpenAPI：只读 `legacy-svc-codegen.md`
- 正式跨仓实施：再读 `cross-repo-branch-checklist.md`
- 具体编码、调试或提交：按 References 表继续选一份，不要全读

### Step 4：设置 checkpoint

每跨过一层都要有可观察证据：

| 层 | 最小证据 |
|---|---|
| 协议 | schema/codegen diff、字段兼容性与字段号 |
| npm 产物 | CI publish step + registry 中真实 version |
| 业务服务 | 定向测试 + testing 响应 |
| 聚合/BFF | mapper/enricher/route 测试 + 端到端响应 |
| legacy codegen | 目标环境 OpenAPI JSON + 消费仓生成 diff |
| 前端 | lockfile、typecheck/定向测试、缺失值降级、真实页面/请求 |
| 合并 | PR 依赖关系、主线产物已存在、消费者不再错误锁定临时版本 |

任一 checkpoint 未通过就停在该层，不把“分支已推”“CI 绿色”或“页面能打开”当成链路闭环。

## 2. 仓库与调用链速查

| 层 | 仓库 | 职责 / 产物 |
|---|---|---|
| gRPC 协议 SoT | `moego-api-definitions` | protobuf；发布 `@moego/api-web` / `@moego/api-node` |
| 共享 proto 模块 | `moegoapis` | buf 共享模块；不直接发前端包 |
| Java gRPC BFF | `moego-api-v3` | 聚合/转换/透传；不发布 api-web |
| 业务服务 | `moego-svc-*` | 字段生产与领域逻辑；不发布前端 npm 包 |
| Node REST BFF / OpenAPI SoT | `moego-bff` | hono/zod-openapi；发布 bff-openapi/schemas/legacy-api |
| legacy Java REST | `moego-server-*`、`moego-open-api-v1` | runtime OpenAPI；消费仓 codegen 后提交生成 TS |
| 前端 | Boarding_Desktop、moego-mobile、OB Web | 消费 SDK 或 in-tree 生成代码 |

```text
Boarding_Desktop / mobile / OB Web
  ├─ @moego/api-web → moego-api-v3 → moego-svc-* / legacy service
  └─ @moego/bff-openapi → moego-bff → legacy REST 或 gRPC
```

首次定位或存在例外时，以源码、依赖文件和 CI 脚本为准，不把本表当作运行时事实的替代。

## 3. 协议决策树

```text
消费者需要字段 X
  ├─ 显式 gRPC proto 字段
  │    → moego-api-definitions 改 schema
  │    → 发布并核验所需 SDK
  │    → svc / api-v3 按真实依赖实现
  │    → 前端升级真实 version
  │
  ├─ 已有 google.protobuf.Struct 中新增 key
  │    → 通常只改字段生产/聚合与消费逻辑
  │    → 先用当前 SDK 验证 extra.fields 可编译、可运行
  │    → 只有另有未发布 proto 变化或消费者确需 feature SDK 时才发包
  │
  ├─ Node BFF OpenAPI schema
  │    → moego-bff route/zod schema 是 SoT
  │    → CI 发布并核验 bff-openapi 实物
  │    → 前端升级具体 version
  │
  └─ legacy Java REST OpenAPI
       → server-* Controller/DTO 是 runtime SoT
       → 部署到目标环境并确认 /v3/api-docs
       → 消费仓对准该环境运行 codegen
       → 审查并提交生成 diff
```

### 3.1 Dynamic Struct 的硬边界

新增 `Struct` key 不会改变 proto schema，也不会生成新的 Java/TypeScript 字段。默认结论是：

- 不需要为这个 key 修改 `moego-api-definitions`。
- 不需要仅为“同名联调分支”推空 commit。
- 不需要升级 `@moego/api-web`，前提是当前版本已经提供 `Struct/Value` 基础访问能力。

只有以下任一事实被验证后，才允许进入 feature SDK 发布：

- 同一任务还有显式 proto 变化。
- 当前消费者 SDK 缺少所需基础能力。
- 消费者构建或联调明确依赖一个尚未发布的 feature dist-tag 产物。

历史 GRM-1728 的空分支是“消费者选择锁定同名 feature SDK”时的发布手段，不是 dynamic Struct 的协议要求。References 中“无 proto 改动时触发发包”的步骤只在上述发布门禁通过后适用。

### 3.2 Legacy OpenAPI 的硬边界

legacy Java service 不发布独立前端 npm 包。必须先确认：

1. 真实 runtime OpenAPI endpoint 和目标环境。
2. 新字段已出现在该环境的 OpenAPI JSON。
3. codegen 使用的 source URL 指向同一环境。
4. 生成代码进入哪个消费仓并被提交。

codegen 无 diff 时先查部署与 source URL，不要改手写 TS 类型伪造成功。

## 4. Feature 包发布门禁

只有消费者确需未发布产物时才执行本节。

### 4.1 分支与 dist-tag

当前已知规则：

- `moego-api-definitions` 和 `moego-bff` 的非主线发布只匹配 `feature-*` / `bugfix-*`。
- `feature/<topic>`、`feat-*`、`fix-*` 等其他形式可能直接 skip。
- `main` 发 `latest`；`production` 是否支持由目标仓库 CI 脚本确认，不能跨仓类推。
- topic 通常使用小写连字符并包含 Jira key。

规则可能变化。动作前必须读目标仓库当前 CI 脚本；不能只凭本 skill 或旧 workflow 记忆。

### 4.2 产物验证

不要在 `package.json` 写自造的 dist-tag/version 组合。按顺序验证：

1. 目标 feature 分支存在。
2. publish job 实际执行而非被 skip。
3. 私有 registry 的 dist-tag 能解析到具体 version。
4. package.json 与 lockfile 锁定该具体 version。
5. 安装后的包实物包含预期客户端、schema 或类型。

包管理器和更新脚本以消费仓 `package.json` / AGENTS 为准；不要把其他仓库的 npm/pnpm 命令复制过来。

## 5. 常见失败：先查什么

| 现象 | 首查 | 失败后的正确动作 |
|---|---|---|
| feature SDK 404 | 分支前缀、publish step、registry 配置 | 不推进消费者；修正发布链后重新查实物 |
| 后端已部署但前端仍无字段 | 实际 response、消费者包版本、mapper/route | 沿依赖图逐层定位，禁止盲目重发所有仓 |
| dynamic key 可运行但提示要空分支 | 是否真的存在 SDK delta | 无 delta 就沿用当前 SDK |
| legacy codegen 无变化 | 部署环境与 codegen source URL | 对准环境后重跑，审查生成 diff |
| 前后端都改了仍联调失败 | flag、版本、请求、响应、缓存与数据源 | 按 debugging reference 收集同一请求链证据 |
| PR 顺序争议 | 谁生产字段、谁消费产物 | 按依赖拓扑设置 blocked-by，不按固定仓库名单 |

## 6. NEVER 规则

- 不因单个跨栈关键词触发；先确认当前任务实际跨边界。
- 不为判断“单仓无需跨栈”而先加载全部 reference。
- 不假设 api-v3、svc-* 或 legacy server push 会发布 `@moego/api-web`。
- 不把 dynamic Struct key 等同于 proto schema 变化、空分支或 SDK 升级。
- 不在未确认消费者需要新产物时创建空 commit、发布包或修改依赖。
- 不把 CI 绿色等同于 publish step 已执行；必须查 registry/package 实物。
- 不猜 schema、字段号、资源 ID、版本号、source URL、分支规则或目标环境；先查后用。
- 不手改生成代码来绕过 proto/OpenAPI codegen。
- 不跨过失败 checkpoint；失败层未闭环前不宣称联调或交付完成。
- 不把一个 case study 提升为全局规则；新结论至少由当前源码/CI/产物证据支持。

## 7. 输出模板

处理跨栈问题时，答案至少包含：

```text
路由：为什么触发 / 为什么不触发 moe-stack
依赖图：协议 SoT → 生产者 → 聚合/BFF → 消费者
产物判断：schema 是否变化；是否真的需要新 SDK/codegen
实施顺序：按依赖拓扑，不按固定仓库名单
Checkpoints：每层如何证明完成
失败与回退：停在哪层，先查什么
按需 References：本次实际读取哪些
```

## 8. References

| 文件 | 仅在以下场景加载 |
|---|---|
| `references/repo-navigation.md` | 首次接 MoeGo 任务、不知道目标仓库或调用入口 |
| `references/api-web-publish-cheatsheet.md` | 已确认需要 api-web/api-node feature 产物，或排查 registry/CI |
| `references/bff-openapi-publish-cheatsheet.md` | 已确认需要 bff-openapi/schemas/legacy-api feature 产物 |
| `references/legacy-svc-codegen.md` | legacy Java Controller/DTO 字段需要进入消费仓生成类型 |
| `references/cross-repo-branch-checklist.md` | 依赖图已确认，正式推进多仓分支、验证与合并 |
| `references/backend-dev-flow.md` | 需要 Java、svc-*、server-* 或 moego-bff 的具体编码/测试约定 |
| `references/backend-service-handbook.md` | 在 `moego` 大仓新增后端服务或 Fulfillment 类服务，需要复用仓库骨架、确认 BUILD/Gazelle/工具链、建立复用矩阵或核对完成证据 |
| `references/frontend-dev-flow.md` | 需要 Desktop/Mobile/OB Web 的具体编码、升包或本地联调约定 |
| `references/npm-packages-glossary.md` | 不确定某个 `@moego/*` 包的来源、用途或成组升级关系 |
| `references/debugging-and-observability.md` | 线上异常或联调失败，需要 Datadog/Sentry/Redshift/flag 证据 |
| `references/commit-and-review-conventions.md` | commit、Jira 前缀、CODEOWNERS、PR、canary 或 release 问题 |
