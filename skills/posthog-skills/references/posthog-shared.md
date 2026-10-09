# posthog-shared

跨场景共享：环境变量、CLI 调用契约、PostHog MCP 退化、出错排查。**仅在首次接入或排错时读这份**。

## 1. 环境变量

skill 根目录 `.env`（拷自 `.env.example`）：

| 变量 | 必填 | 用途 |
|---|---|---|
| `POSTHOG_PERSONAL_API_KEY` | ✅ | personal token（`phx_xxx`），所有 CLI 调用必备 |
| `POSTHOG_HOST` | ✅ | API endpoint，US / EU / 自部署 URL |
| `POSTHOG_PROJECT_ID` | 多 project 时建议 | 多 project 下的默认项目；不填会取 `/api/projects/` 第一个并提示 |
| `POSTHOG_DOTENV` | 可选 | 显式指定 `.env` 路径覆盖默认搜索 |

加载优先级：**进程环境 > `$POSTHOG_DOTENV` > `CWD/.env` > `scripts/.env` > skill 根目录 `.env`**。同名变量后者被前者覆盖，已存在的不重写。

`HOST` 取值：

- US Cloud：`https://us.i.posthog.com`
- EU Cloud：`https://eu.i.posthog.com`
- 自部署：`https://posthog.your-company.com`

`PERSONAL_API_KEY` 怎么拿：登录 PostHog → 头像 → **Personal API Keys** → Create personal API key。Scope 至少需要 `query:read`、`feature_flag:write`、`insight:write`、`dashboard:write`。

## 2. CLI 入口

**唯一入口**：

```bash
python3 scripts/posthog.py <subcommand> [--flags]
```

完整子命令列表：

```
# 探索 / 验证
whoami / list-orgs / list-projects [--org]
list-event-defs [--search]
list-property-defs --type event|person [--search] [--event-names a,b]

# HogQL
query --sql ... | --sql-file ... [--refresh] [--format raw|rows]

# Feature Flag CRUD
list-flags / get-flag / create-flag / update-flag

# Insight CRUD
list-insights / get-insight / create-insight / update-insight

# Dashboard CRUD + 关联
list-dashboards / get-dashboard / create-dashboard / update-dashboard
add-insight-to-dashboard [--replace]
```

每个端点在源码注释里标注了对应的 PostHog REST URL（与 PostHog 官方 MCP `typescript/src/api/client.ts` 对齐），grep `MCP:` 即可看到映射。

`-h` 看任一子命令的具体参数：`python3 scripts/posthog.py query -h`。

输出契约：

| 流 | 内容 |
|---|---|
| stdout | 命令结果 JSON（用 `jq` 过滤友好） |
| stderr | 提示 / 警告 / 错误，统一前缀 `[posthog]` |

退出码：

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 入参错（缺必填、互斥参数同时给等） |
| 3 | 鉴权 / 环境配置错（未设 token、`.env` 没读到） |
| 4 | PostHog 4xx（包括 401/403/404） |
| 5 | PostHog 5xx 或网络错 |

## 3. 与 PostHog MCP 的关系

本 skill **不依赖 MCP**：PostHog MCP 本身也是对 REST API 的封装层，本 CLI 直接抽取了它的端点映射（参考 `PostHog/mcp` 仓 `typescript/src/api/client.ts`），所以同样的查询 / 编辑 / 创建能力，用 CLI 一定能走通。

具体抽取了以下端点（脚本里 grep `MCP:` 可定位每段对应的源码位置）：

| 操作 | URL | 方法 |
|---|---|---|
| `whoami` | `/api/personal_api_keys/@current` | GET |
| `list-orgs` | `/api/organizations/` | GET |
| `list-projects --org X` | `/api/organizations/<org>/projects/` | GET |
| `list-projects` | `/api/projects/` | GET |
| `list-event-defs` | `/api/projects/<pid>/event_definitions/` | GET（自动分页） |
| `list-property-defs` | `/api/projects/<pid>/property_definitions/` | GET（自动分页） |
| `query` | `/api/environments/<pid>/query/` | POST |
| `list-flags` / `get-flag` | `/api/projects/<pid>/feature_flags/[<id>/]` | GET（list 走分页 + 客户端 filter，与 MCP `findByKey` 一致） |
| `create-flag` / `update-flag` | `/api/projects/<pid>/feature_flags/[<id>/]` | POST / PATCH |
| `list-insights` / `get-insight` | `/api/projects/<pid>/insights/[<id>/]`（short_id 走 `?short_id=`） | GET |
| `create-insight` / `update-insight` | `/api/projects/<pid>/insights/[<id>/]` | POST / PATCH |
| `list-dashboards` / `get-dashboard` | `/api/projects/<pid>/dashboards/[<id>/]` | GET |
| `create-dashboard` / `update-dashboard` | `/api/projects/<pid>/dashboards/[<id>/]` | POST / PATCH |
| `add-insight-to-dashboard` | `/api/projects/<pid>/insights/<insight_id>/` | PATCH（默认追加保留已挂；`--replace` 切回 MCP 的覆盖语义） |

> ⚠ **注意 query endpoint**：PostHog 内部正在把 events/query 类操作从 `/api/projects/` 迁到 `/api/environments/`。MCP 已经走 `/api/environments/<pid>/query/`，本 CLI 也对齐这个端点；用旧 `/api/projects/<pid>/query/` 在新版 PostHog 上可能 404 或行为不一致。

> ⚠ **PostHog 上某些 list 端点 server-side 不支持 `?search=`**（典型如 feature_flags），MCP 的做法是分页拉全量后客户端 filter，本 CLI 同款行为；项目里 Flag 数量上千时 `list-flags` 会比较慢，必要时用 `get-flag <key>` 直查。

## 4. 多 project 处理

### 4.1 解析顺序

CLI 只读 `POSTHOG_PROJECT_ID` 环境变量，**没有 `--project` 这种 CLI flag**。未设值时调 `/api/projects/` 取第一个并把选择写到 stderr：

```
[posthog] 未设置 POSTHOG_PROJECT_ID，自动选择 project_id=12345 (production)
```

多项目用户**必须**显式设 `POSTHOG_PROJECT_ID`，否则脏数据风险（在 dev 项目里建出 prod dashboard 之类）。

### 4.2 推荐用法：inline 覆盖

`.env` 里只放**最常用项目**做默认值；切到其它 project 时**单条命令前 inline 覆盖**，不要去改 `.env`（容易忘改回来）：

```bash
# 默认 project（来自 .env）
python3 scripts/posthog.py list-dashboards

# 临时切到 MoeGo_Client (25329) 查这个 project 的 dashboard
POSTHOG_PROJECT_ID=25329 python3 scripts/posthog.py list-dashboards --search Grooming

# 临时切到 MoeGo_Business (21084) 看这个 project 的 dashboard 详情
POSTHOG_PROJECT_ID=21084 python3 scripts/posthog.py get-dashboard 451229
```

每条命令独立绑定 project，命令结束 shell 状态不变，不会污染下一次调用。

### 4.3 公司 project 速查表

| project_id | 名称 | 典型来源 |
|---|---|---|
| 21084 | MoeGo_Business | salon SaaS（PC / 商家端） |
| 25329 | MoeGo_Client | 客户端 H5 / OB（`moego-online-booking-client-web` 等） |
| 41936 | MoeGo_Petparent | 宠物主 App（iOS/Android） |
| 23530 | Test | 测试环境 |
| 147253 | MoeGo_Website | 官网 |

随时刷新这张表：`python3 scripts/posthog.py list-projects | jq -r '.results[] | "\(.id) \(.name)"'`。

### 4.4 ⚠ Dashboard 所在 project ≠ 事件落点 project

PostHog URL `https://us.posthog.com/project/<pid>/dashboard/<id>` 里的 `<pid>` 只表示「这个 dashboard 所在的 project」，**与事件被写到哪个 project 是两码事**：

- **dashboard / insight 的 project**：URL 里的 `<pid>`，由你建 dashboard 时所在的 PostHog project 决定。
- **事件落到哪个 project**：由前端代码 / GTM 后台配置的项目公钥 `phc_xxx` 决定。

PostHog 的 insight 是 **`team_id` 维度隔离**的：A project 的 dashboard 上挂一张查 B project 事件的 insight，结果永远是 0。

**建 insight 前必须验证事件确实存在于目标 project**：

```bash
# 用 event def
POSTHOG_PROJECT_ID=<dashboard 所在 project> python3 scripts/posthog.py list-event-defs --search <事件名>

# 或直接查 events 表（更可靠，event def 注册有延迟）
POSTHOG_PROJECT_ID=<dashboard 所在 project> python3 scripts/posthog.py query --sql "SELECT count() FROM events WHERE event = '<事件名>' AND timestamp >= now() - INTERVAL 7 DAY"
```

返回 0 时停下来和用户对齐：是建在错的 project（应换 dashboard），还是事件根本没接入到这个 project（应让前端 / GTM 双发）。**不要硬建空 insight**。

## 5. 出错排查 checklist

| 现象 | 排查 |
|---|---|
| `[posthog] 环境变量 POSTHOG_PERSONAL_API_KEY 未设置` | 没拷 `.env.example` 为 `.env`，或 `.env` 路径不在加载顺序里。试 `python3 scripts/posthog.py list-flags --limit 1` 验证 |
| `HTTP 401 ... Invalid API key` | token 拼成了项目公钥 `phc_`；要 personal `phx_` |
| `HTTP 403 ... Permission denied` | personal token scope 不够，去 PostHog 重新生成带 `*:read` / `*:write` 的 |
| `HTTP 404 /api/projects/<id>/...` | `POSTHOG_PROJECT_ID` 错；`list-flags` 试一下看自动选中的是哪个 |
| `HTTP 4xx` 但消息说 `"detail":"Not found"` | 用 EU 项目接了 US host（或反之）。`POSTHOG_HOST` 改对 |
| `HTTP 5xx` / `URLError` | 自部署网络不通，或 PostHog cloud 偶发；先重试，再看 status.posthog.com |
| 输出空 `{"results":[]}` | 项目里确实没有该实体，或 `--search` 参数与 PostHog 的 server-side 搜索口径不一致（试更宽松关键词） |

## 6. 安全约定

- `POSTHOG_PERSONAL_API_KEY` 是 admin 级凭证：**不进 git、不进客户端、不进业务工程的 `.env`**。skill 根目录的 `.env` 已被仓库 `.gitignore` 覆盖（确认一下你 fork 的 `.gitignore` 含 `.env`）。
- CLI **没有 dry-run / 确认门禁**：写接口（POST/PATCH）调出去就生效。
- 这条由 agent 来兜：写之前先调 `get-*` / `list-*` 把当前状态打给用户，让用户看完再调 `create-*` / `update-*`。
- 备份套路：改 Insight SQL 前 `get-insight <id> > /tmp/backup.json`，万一覆盖错了能从 backup 还原。
