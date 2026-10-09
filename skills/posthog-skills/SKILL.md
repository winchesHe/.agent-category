---
name: posthog-skills
description: >-
  通过 PostHog REST API 做 查询 / 编辑 / 创建 三类操作的语义索引 skill。
  统一入口 `scripts/posthog.py` 子命令，可选 PostHog MCP 兜底。
  覆盖 HogQL 查询，以及 Feature Flag / Insight / Dashboard 三类实体的 list /
  get / create / update。任何"查 PostHog 数据 / 改 Flag / 建 Insight /
  改 Dashboard 标题 / 挂图到 Dashboard"类请求都通过本 skill 路由。
---

# PostHog Skills（查询 / 编辑 / 创建）

仅服务三类场景：

| 场景 | 路由 |
|---|---|
| **查询**：跑 HogQL、看 events / persons / sessions、读 Flag / Insight / Dashboard 详情 | [`query-hogql.md`](references/query-hogql.md) |
| **创建**：建 Flag / 建 Insight（HogQL Insight）/ 建 Dashboard / 把 Insight 挂到 Dashboard | [`entity-crud.md`](references/entity-crud.md) |
| **编辑**：改 Flag 的 active / rollout / name；改 Insight 的 SQL / name；改 Dashboard 的 name / description | [`entity-crud.md`](references/entity-crud.md) |

不在本 skill 范围内的场景（埋点、SDK 接入、错误追踪、LLM trace、日志、排查工作流）走 PostHog 官方 docs 或 `external-references/posthog-skills/skills/...`。

## 执行底座

| 通道 | 何时用 |
|---|---|
| **`scripts/posthog.py`**（本仓自带，stdlib only） | **默认且唯一通道**。端点抽自 PostHog 官方 MCP（`PostHog/mcp` 仓 `typescript/src/api/client.ts`），打 PostHog REST API |
| **PostHog MCP（`posthog:*` 工具）** | 不依赖。本 skill 覆盖的查询 / 编辑 / 创建场景已全部用 CLI 实现；用户已连 MCP 并明确要求时再用 |

写 / 改之前都应能从 query / list / get 拿到当前状态再决策。

## 前置条件

1. **凭证**：复制 skill 根目录 `.env.example` 为 `.env`，填入 `POSTHOG_PERSONAL_API_KEY`（`phx_xxx`，写操作必备）、`POSTHOG_HOST`，多 project 时填 `POSTHOG_PROJECT_ID`。详见 [`posthog-shared.md`](references/posthog-shared.md) §1。
2. Python ≥ 3.9（stdlib 即可，无第三方依赖）。
3. **不要混淆两条凭证**：
   - `POSTHOG_API_KEY`（`phc_`，项目公钥）—— 客户端业务代码用，本 skill 的 CLI **不需要**。
   - `POSTHOG_PERSONAL_API_KEY`（`phx_`，个人 token）—— 调管理 API 用，本 skill 的 CLI 必需。

## 调用约定

| 约定 | 说明 |
|---|---|
| 入口 | `python3 scripts/posthog.py <subcommand> [--flags]`，子命令完整列表见下方决策树 |
| 输出契约 | stdout = 命令结果 JSON；stderr = 提示 / 警告 / 错误（前缀 `[posthog]`） |
| 退出码 | `0` 成功 / `2` 入参错 / `3` 鉴权或环境错 / `4` PostHog 4xx / `5` PostHog 5xx 或网络错 |
| 修改前先查 | 改 Flag / Insight / Dashboard 前先 `get-*` 拿当前状态，向用户展示再写 |
| Body 复杂时 | `--body-json '{...}'` 或 `--body-file path.json`（`-` 表 stdin），覆盖简化 flag |
| HogQL 时间窗 | 任何查询必须带时间过滤（`timestamp >= now() - INTERVAL N DAY`），见 [`query-hogql.md`](references/query-hogql.md) |
| Dashboard 上的 SQL Insight | SQL 里保留 `{filters}` 占位符让 Dashboard 控件参与过滤 |
| 多 project 切换 | `.env` 里只放最常用 project；切其它项目用 **单条命令前 inline 覆盖** —— `POSTHOG_PROJECT_ID=25329 python3 scripts/posthog.py ...`。**绝不**为了一次切换去改 `.env`（会忘改回来导致脏数据）。CLI 不接受 `--project` flag，只读 `POSTHOG_PROJECT_ID` 环境变量。详见 [`posthog-shared.md`](references/posthog-shared.md) §4 |
| Dashboard URL ≠ 事件落点 | URL `https://us.posthog.com/project/<pid>/dashboard/<id>` 里的 `<pid>` 只表示「dashboard 所在 project」；事件被写到哪个 project 由前端代码 / GTM 配置的 `phc_xxx` key 决定。建 insight 前先在目标 project 用 `list-event-defs --search` 或 `query` 验证事件存在，否则 insight 会查不到任何数据 |

## 场景决策树

| 用户意图 | 子命令 | reference |
|---|---|---|
| "我现在登录的是谁 / token 还有效吗" | `whoami` | [`posthog-shared.md`](references/posthog-shared.md) |
| "PostHog 里有哪些 organization / project" | `list-orgs` / `list-projects [--org X]` | [`posthog-shared.md`](references/posthog-shared.md) |
| "工程里都上报了哪些事件 / 这个事件叫什么" | `list-event-defs [--search keyword]` | [`query-hogql.md`](references/query-hogql.md) |
| "events 上有哪些 property / person 上有哪些字段" | `list-property-defs --type event\|person [--search] [--event-names a,b]` | [`query-hogql.md`](references/query-hogql.md) |
| "用 HogQL 查 ..." / "events 表里 ..." / "上周 DAU" | `query --sql '...'` 或 `query --sql-file q.sql` | [`query-hogql.md`](references/query-hogql.md) |
| "PostHog 里有哪些 flag" / "搜某个 flag" | `list-flags [--active true\|false\|STALE] [--search keyword]` | [`entity-crud.md`](references/entity-crud.md) |
| "看 flag X 的详情" | `get-flag <key 或 id>` | [`entity-crud.md`](references/entity-crud.md) |
| "建一个 flag" | `create-flag --key X --name X [--rollout 10] [--active true]` | [`entity-crud.md`](references/entity-crud.md) |
| "把 flag X 关掉 / 改 rollout / 改名" | `update-flag <key> [--active false] [--rollout 50] [--name '新名']` | [`entity-crud.md`](references/entity-crud.md) |
| "看有哪些 insight" / "找叫 X 的 insight" | `list-insights [--search X] [--saved-only]` | [`entity-crud.md`](references/entity-crud.md) |
| "看 insight X" | `get-insight <id 或 short_id>` | [`entity-crud.md`](references/entity-crud.md) |
| "把这段 SQL 存成 insight" | `create-insight --name X --sql-file q.sql [--dashboard-id D]` | [`entity-crud.md`](references/entity-crud.md) |
| "改 insight 的 SQL / 改名" | `update-insight <id> [--sql-file q.sql] [--name '新名']` | [`entity-crud.md`](references/entity-crud.md) |
| "看有哪些 dashboard" | `list-dashboards [--search X]` | [`entity-crud.md`](references/entity-crud.md) |
| "看 dashboard X 的所有 tile" | `get-dashboard <id>` | [`entity-crud.md`](references/entity-crud.md) |
| "建 dashboard" | `create-dashboard --name X [--description '...']` | [`entity-crud.md`](references/entity-crud.md) |
| "改 dashboard 名 / 描述" | `update-dashboard <id> [--name X] [--description '...']` | [`entity-crud.md`](references/entity-crud.md) |
| "把 insight Y 挂到 dashboard X 上" | `add-insight-to-dashboard <dashboard_id> <insight_id>` | [`entity-crud.md`](references/entity-crud.md) |
| "API key / host / project / 自部署 / 报错排查" | —— | [`posthog-shared.md`](references/posthog-shared.md) |

## NEVER 规则

- ❌ **`POSTHOG_PERSONAL_API_KEY` 不入 git、不进任何被打包发布的工程**。**Why**：personal token 是 admin 级，泄露后整个 PostHog 项目可被改写。**如何应用**：只放 skill 根目录 `.env`（已在 `.gitignore` 覆盖）或 CI secrets；不要 cp 到业务工程的 `.env`，业务工程要的是项目公钥 `phc_`，与本 CLI 无关。
- ❌ **不要在 HogQL 里写无时间窗的 `SELECT * FROM events`**。**Why**：events 是巨表，无时间窗会撞超时或配额。**如何应用**：必须 `WHERE timestamp >= now() - INTERVAL N DAY`，Dashboard 上的 SQL 还要保留 `{filters}` 占位符。
- ❌ **`update-flag` 改 rollout 不向用户确认**。**Why**：Flag 是线上灰度开关，把 10% 改成 100% 的影响等同于一次部署。**如何应用**：先 `get-flag <key>` 给用户看当前 `rollout_percentage` 与 `experiment_set`，确认后再 update。
- ❌ **改 Insight 的 SQL 不先 `get-insight` 备份原 query**。**Why**：PostHog API patch 不返回 diff，原 query 覆盖后只能从 activity log 恢复。**如何应用**：update 前 `get-insight <id> > backup.json`，用户看完旧 SQL 再改。
- ❌ **同名 flag / insight 重复创建**。**Why**：PostHog 不强约束唯一名，两个同名 dashboard tile 会让维护者无从判断哪个是真源。**如何应用**：create 前先 `list-flags --search` / `list-insights --search`；存在就 update 而不是 create。

## References 加载时机

| Reference | 触发 | 是否首次必读 |
|---|---|---|
| [`posthog-shared.md`](references/posthog-shared.md) | API key / host / project / 自部署 / CLI 报错 | 仅首次或不确定环境时 |
| [`query-hogql.md`](references/query-hogql.md) | 任何 HogQL 查询；表 schema / 函数 / 时间窗口 | 否 |
| [`entity-crud.md`](references/entity-crud.md) | Flag / Insight / Dashboard 的 list / get / create / update | 否 |

按需加载——命中决策树后只读一份。
