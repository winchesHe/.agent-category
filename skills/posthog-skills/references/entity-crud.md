# entity-crud

**用于**：Feature Flag / Insight / Dashboard 三类实体的 list / get / create / update。统一通过 `scripts/posthog.py`：

```bash
python3 scripts/posthog.py <subcommand> [args]
```

读操作（list / get）写 stdout 即可；改 / 创操作前 agent 应先 `get-*` / `list-*` 把当前状态展示给用户，确认后再调写命令。

## 触发关键词

- "PostHog 里有没有 / 有哪些 ..." → `list-*`
- "看 ... 的详情 / 配置" → `get-*`
- "建一个 / 创建 ..." → `create-*`
- "改 ... 的 ... / 把 ... 关掉 / 改名" → `update-*`
- "把 insight 挂到 dashboard 上" → `add-insight-to-dashboard`

## 通用约定

- 简单字段用对应 flag（`--name` / `--rollout` / `--active` / `--description` / `--sql-file` …），复杂场景用 `--body-json '{...}'` 或 `--body-file path.json`（`-` 表 stdin）传完整 PostHog API payload，覆盖简化逻辑。
- 改之前**先查**：`get-flag` / `get-insight` / `get-dashboard` 把当前 JSON 给用户，diff 出待变更字段，确认后再 update。
- 同一个动作不要重复创建：先 `list-* --search <keyword>` 确认是否已有同名实体，存在就 update。

---

## Feature Flag

### list-flags

```bash
python3 scripts/posthog.py list-flags
python3 scripts/posthog.py list-flags --active true                    # 仅启用
python3 scripts/posthog.py list-flags --active STALE                   # PostHog 标记的"久未命中"
python3 scripts/posthog.py list-flags --search checkout --limit 50
```

### get-flag

```bash
python3 scripts/posthog.py get-flag new-checkout-flow      # 按 key
python3 scripts/posthog.py get-flag 12345                  # 按 id
```

返回字段里关注：`active` / `filters.groups[*].rollout_percentage` / `filters.multivariate` / `experiment_set`（非空说明被实验占用，改之前要慎重）。

### create-flag

最常见：建一个 0% rollout 的布尔 Flag，等代码上线再灰度：

```bash
python3 scripts/posthog.py create-flag --key new-checkout-flow --name "New checkout flow" --rollout 0
```

带 `--rollout` 直接全员某百分比：

```bash
python3 scripts/posthog.py create-flag --key kill-legacy-import --name "Kill legacy import" --rollout 100
```

需要复杂条件（按 plan / email / group）时走完整 payload：

```bash
python3 scripts/posthog.py create-flag --body-json '{
  "key": "enterprise-only-export",
  "name": "Enterprise only export",
  "active": true,
  "filters": {
    "groups": [
      {
        "properties": [
          {"key": "plan", "value": "enterprise", "operator": "exact", "type": "person"}
        ],
        "rollout_percentage": 100
      }
    ]
  }
}'
```

Multivariate（A/B/C）：

```bash
python3 scripts/posthog.py create-flag --body-json '{
  "key": "exp-checkout-v2",
  "name": "Checkout v2 experiment",
  "active": true,
  "filters": {
    "multivariate": {
      "variants": [
        {"key": "control",   "rollout_percentage": 50},
        {"key": "variant_a", "rollout_percentage": 25},
        {"key": "variant_b", "rollout_percentage": 25}
      ]
    },
    "groups": [{"properties": [], "rollout_percentage": 100}]
  }
}'
```

### update-flag

> 改 rollout 等同于一次部署。**先 `get-flag` 给用户看当前值**，确认后再 update。

```bash
# 关掉
python3 scripts/posthog.py update-flag new-checkout-flow --active false

# 推到 50%
python3 scripts/posthog.py update-flag new-checkout-flow --rollout 50

# 改名
python3 scripts/posthog.py update-flag new-checkout-flow --name "Checkout v2 (GA)"

# 复杂条件改写整个 filters
python3 scripts/posthog.py update-flag new-checkout-flow --body-json '{"filters": {...}}'
```

`--rollout` 是简化路径，会把 `filters.groups` 替换成单一全员百分比规则；要保留多组条件用 `--body-json`。

`update-flag --active false` 是软关闭（可逆），优先于硬删除——本 CLI 不提供 delete-flag。

---

## Insight

### list-insights

```bash
python3 scripts/posthog.py list-insights
python3 scripts/posthog.py list-insights --search "checkout funnel"
python3 scripts/posthog.py list-insights --saved-only --limit 100
```

### get-insight

```bash
python3 scripts/posthog.py get-insight 12345         # 数字 id
python3 scripts/posthog.py get-insight a1b2c3d4      # short_id（PostHog URL 上的那串）
```

关注 `query` 字段（HogQL 类型在 `query.source.query`）和 `dashboards`（被哪些 dashboard 引用）。

### create-insight

默认创建 HogQL Insight：

```bash
python3 scripts/posthog.py create-insight \
    --name "Weekly checkout funnel by variant" \
    --sql-file q.sql

# 创建后直接挂到指定 dashboard
python3 scripts/posthog.py create-insight \
    --name "Daily signups" \
    --sql 'SELECT dateTrunc(...) FROM events WHERE event = ... AND {filters}' \
    --dashboard-id 42
```

要 Insight 出现在 Dashboard 时**必须**在 SQL 里保留 `{filters}`，否则 dashboard 控件失效。

要建非 SQL 类型（Trends / Funnels / Retention 等）走完整 payload：

```bash
python3 scripts/posthog.py create-insight --body-json '{
  "name": "Weekly DAU",
  "saved": true,
  "query": {
    "kind": "TrendsQuery",
    "series": [{"event": "$pageview", "math": "dau"}],
    "interval": "week"
  }
}'
```

PostHog 各 Insight 类型的 query schema 见官方 docs；本 CLI 不限制 schema。

### update-insight

```bash
# 改名
python3 scripts/posthog.py update-insight 12345 --name "Daily signups (US only)"

# 改 SQL
python3 scripts/posthog.py update-insight 12345 --sql-file q.sql

# 同时改多字段或非 SQL 类型
python3 scripts/posthog.py update-insight 12345 --body-json '{...}'
```

> Update 不返回 diff——改 SQL 前**务必** `get-insight 12345 > backup.json`，万一覆盖错了能从 backup 还原。

---

## Dashboard

### list-dashboards / get-dashboard

```bash
python3 scripts/posthog.py list-dashboards --search "growth"
python3 scripts/posthog.py get-dashboard 42
```

### create-dashboard

```bash
python3 scripts/posthog.py create-dashboard --name "Growth weekly" --description "Sign-up & activation"
```

create 完成后用 `add-insight-to-dashboard` 逐个挂 Insight。

### update-dashboard

```bash
python3 scripts/posthog.py update-dashboard 42 --name "Growth weekly (US)"
python3 scripts/posthog.py update-dashboard 42 --description "Sign-up funnel + activation cohort"
```

### add-insight-to-dashboard

```bash
python3 scripts/posthog.py add-insight-to-dashboard 42 12345                # dashboard_id, insight_id
python3 scripts/posthog.py add-insight-to-dashboard 42 12345 --replace      # 走 MCP 行为：覆盖
```

底层是 `PATCH /api/projects/<pid>/insights/<insight_id>/ {"dashboards": [...]}`。

| 模式 | 行为 | 何时用 |
|---|---|---|
| 默认 | 先 `get-insight` 拿当前 `dashboards` 列表 → append → PATCH，**追加而不覆盖**；已挂的跳过 | 几乎所有场景 |
| `--replace` | 直接 PATCH `dashboards: [<id>]`，**摘掉 insight 与其他 dashboard 的所有关联**。这与 PostHog 官方 MCP 的行为一致 | 明确要把 insight 从其他 dashboard 上摘下来时 |

⚠ MCP 的默认就是 `--replace` 那种行为，本 CLI 改为更安全的追加；这是与 MCP 唯一的语义差异。

---

## 常见组合操作

### 把一段 HogQL 落成 Dashboard

```bash
# 1. 先在 query 里跑通
python3 scripts/posthog.py query --sql-file q.sql

# 2. 建 Dashboard（如果还没有）
python3 scripts/posthog.py create-dashboard --name "Checkout monitoring"
# → 拿到 id，比如 99

# 3. 建 Insight 并直接挂上
python3 scripts/posthog.py create-insight \
    --name "Checkout funnel by variant" \
    --sql-file q.sql \
    --dashboard-id 99
```

### 灰度推进

```bash
# 看现状
python3 scripts/posthog.py get-flag new-checkout-flow

# 用户确认后推进
python3 scripts/posthog.py update-flag new-checkout-flow --rollout 25
# 几小时后再到 50 / 100
```

## NEVER

- ❌ Update Flag rollout / Insight SQL **不向用户展示当前状态**就直接写 → 等同闭眼修改线上。
- ❌ 同名实体重复创建 → 先 `list-* --search` 去重，存在就 update。
- ❌ `--rollout` 简化路径**覆盖**已有的多组复杂条件后没告知用户 → 用 `--body-json` 完整改写或先备份原 filters。
- ❌ 创建 Dashboard 用 SQL Insight 时 SQL 里漏 `{filters}` → 控件全部失效，等于做了一张静态截图。
- ❌ 改 Insight SQL 不先 `get-insight > backup.json` → patch 覆盖原 query 后只能从 PostHog activity log 找，效率极低。
