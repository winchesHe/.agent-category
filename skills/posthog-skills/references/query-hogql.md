# query-hogql

**用于**：跑 HogQL（PostHog 的 SQL 方言）查 events / persons / sessions / 其他系统表。

实际请求端点（PostHog MCP 同款，已迁到 environments）：

```
POST /api/environments/<project_id>/query/
body: {"query": {"kind": "HogQLQuery", "query": "<SQL>"}, "refresh": "blocking"?}
```

CLI 用法：

```bash
python3 scripts/posthog.py query --sql '<HogQL>'
python3 scripts/posthog.py query --sql-file path.sql              # 从文件
echo "SELECT 1" | python3 scripts/posthog.py query --sql-file -   # 从 stdin
python3 scripts/posthog.py query --sql '...' --refresh            # 强制刷新（refresh=blocking）
python3 scripts/posthog.py query --sql '...' --format raw         # 返回原始 PostHog 响应（含 hogql/clickhouse 元信息）
```

默认 `--format rows` 输出 `{columns, row_count, rows}`，便于 `jq` 处理。

## 写 SQL 之前 —— 用 discovery 命令快速摸清 schema

不知道事件叫什么 / property 拼写：

```bash
# 列工程里所有上报过的事件（自动分页）
python3 scripts/posthog.py list-event-defs --search checkout --limit 20

# 列 events 表里所有 property（含 sample 值数量）
python3 scripts/posthog.py list-property-defs --type event --search amount

# 仅看某些事件用过的 property（join：在 list 端点服务端做，效率高）
python3 scripts/posthog.py list-property-defs --type event --event-names checkout_started,checkout_completed

# person 维度的 property
python3 scripts/posthog.py list-property-defs --type person --search plan
```

这两个端点用法等同 MCP 的 `posthog:eventDefinitions` / `posthog:propertyDefinitions`，对写 HogQL 时确认事件名 / property 拼写非常有用——拼错 property 是 PostHog SQL 报错最常见的来源。

## 触发关键词

- "用 HogQL 查 ..." / "events 表里 ..."
- "上周 DAU / 漏斗 / 留存的具体数字"
- "PostHog 里搜某个事件 / 某个 property 的分布"

## 决策步骤

### 1. 先看是否能用既有 Insight

用户问"上周转化率"且已有同名 Insight → `list-insights --search` 找到，再 `get-insight <id>` 看历史 query，复用比新写更稳。

只有以下情形才写新 SQL：

- 既有 Insight 表达不了的复杂逻辑
- 临时一次性核数
- 准备落成新 Insight（参考 [`entity-crud.md`](entity-crud.md) 的 `create-insight`）

### 2. 必带时间窗口

events 是大表。任何 SQL 至少要带一个时间过滤，否则会撞超时或配额：

```sql
SELECT count() FROM events
WHERE event = 'subscription_created'
  AND timestamp >= now() - INTERVAL 7 DAY
```

要落成 Dashboard 的 SQL 必须保留 `{filters}` 占位符让 UI 控件参与：

```sql
SELECT dateTrunc('day', timestamp) AS day, count() AS c
FROM events
WHERE event = '$pageview' AND {filters}
GROUP BY day ORDER BY day
```

### 3. 核心表 schema

| 表 | 含义 | 关键列 |
|---|---|---|
| `events` | 所有埋点事件 | `event`, `timestamp`, `distinct_id`, `person_id`, `properties`, `session_id` |
| `persons` | 用户主表 | `id`, `created_at`, `properties` |
| `sessions` | 会话聚合 | `session_id`, `start_timestamp`, `end_timestamp`, `pageview_count`, `event_count`, `entry_url` |
| `groups` | B2B group 维度 | `group_type_index`, `group_key`, `properties` |
| `cohort_people` | 分群成员 | `cohort_id`, `person_id` |

属性访问：

```sql
properties.$browser                   -- 标准属性
properties.amount_usd                 -- 业务属性
properties['$feature/new-checkout']   -- 含特殊字符
person.properties.email               -- person 属性（注意 mode）
```

### 4. 常用函数

| 场景 | 用 |
|---|---|
| 唯一计数 | `uniq(distinct_id)`（**不要** `count(distinct ...)`，效率差） |
| 按天 / 周 / 月 | `dateTrunc('day' / 'week' / 'month', timestamp)` |
| 漏斗 | `windowFunnel(<window_seconds>)(timestamp, cond1, cond2, ...)` |
| 序列匹配 | `sequenceMatch('(?1)(?2)')(timestamp, cond1, cond2)` |
| Cohort 过滤 | `person_id IN COHORT '<cohort_name>'` |
| Action 匹配 | `matchesAction('action_name')` |

完整函数表：`external-references/posthog-skills/skills/omnibus/querying-posthog-data/references/available-functions.md`（很长，grep 用）。

### 5. person property modes

`person.properties.*` 有两种取值时机：

- **event-time**：事件发生时 person 的当时快照（写到 events 表里）
- **query-time**：查询执行时 person 的最新值

PostHog 默认很多查询用 **event-time**。当问"现在 plan=enterprise 的人做过什么"应该用 **query-time**——具体语法看 `external-references/posthog-skills/skills/omnibus/querying-posthog-data/references/person-property-modes.md`。

### 6. 调试套路

- 先 `SELECT * FROM events WHERE ... LIMIT 10`，验字段拼对（property 名拼错最常见）。
- `SELECT DISTINCT event FROM events WHERE timestamp >= now() - INTERVAL 1 DAY` 验事件名是否真在上报。
- 慢 query：缩短时间窗口、加 `LIMIT`、`count(distinct)` → `uniq()`。
- CLI 报 `HTTP 4xx` 看 stderr 的错误体，PostHog 会指明具体 column / function 错误位置。

## 常用模板

漏斗 + variant 拆分：

```sql
SELECT
  properties['$feature/exp-checkout-v2'] AS variant,
  windowFunnel(86400)(timestamp,
    event = 'checkout_started',
    event = 'checkout_completed'
  ) AS step
FROM events
WHERE timestamp >= now() - INTERVAL 14 DAY
  AND event IN ('checkout_started', 'checkout_completed')
GROUP BY person_id, variant
HAVING step > 0
```

按渠道留存：

```sql
SELECT
  dateTrunc('week', persons.created_at) AS cohort_week,
  persons.properties.signup_source AS source,
  uniq(events.person_id) AS retained_users
FROM events JOIN persons ON events.person_id = persons.id
WHERE events.event = '$pageview'
  AND events.timestamp >= persons.created_at + INTERVAL 7 DAY
  AND persons.created_at >= now() - INTERVAL 90 DAY
GROUP BY cohort_week, source
```

更多模板：`external-references/posthog-skills/skills/omnibus/querying-posthog-data/references/example-*.md`。

## 跑完之后

如果这次 query 用户后续还会反复用，问要不要落成 Insight：

```bash
python3 scripts/posthog.py create-insight --name "Weekly checkout funnel by variant" \
    --sql-file q.sql --dashboard-id 42
```

→ 转 [`entity-crud.md`](entity-crud.md) 的 create-insight 流程。

## NEVER

- ❌ `SELECT * FROM events`（无 WHERE） → 必撞超时。
- ❌ Dashboard 用的 SQL 不带 `{filters}` → UI 控件失效，过滤等于摆设。
- ❌ `count(distinct distinct_id)` → 用 `uniq(distinct_id)`，CH 在 PostHog 量级下效率差几倍。
- ❌ 把 `properties.email` 当 person email → email 大概率在 `person.properties.email`，事件级别只在 `$identify` 那条。
- ❌ 在 SQL 里 hardcode 用户 ID 然后给 Dashboard 用 → 用 `{variables.user_id}` 让 Dashboard 配置时参数化。
