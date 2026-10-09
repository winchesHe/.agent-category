# 数据源 Playbook

## 统一原则

- 先发现真实对象 ID，再取数据；URL 文本不是数据源 ID。
- 优先结构化数据，其次 dashboard 导出 CSV，最后才使用图片。
- 每次查询都写入 evidence pack 的 `traceability`：`source_id`、`source_type`、`source_url`、`query_or_filter`、`retrieved_at`、`owner`。
- 取不到数据时先按补数 SOP 继续追真实来源；仍无法补齐时写入 `pre_generation_confirmations` 或 `open_questions`，不要继续生成看似完整的结论。
- 初稿仍有缺口或需要 PNG/权限/人工项兜底时，继续读 `references/supplemental-data-backfill.md`，按补数顺序处理；NPS official 这类已确认人工收集的指标不作为自动取数缺口阻塞。
- 补数过程可以在内部 evidence/debug 里保留失败探针；发布前的 `Data Source & Traceability` 只保留已使用的数据源、已接受的 manual policy 和必要口径，不保留被后续补齐或人工确认替代的 `_missing`、`gap_summary`、source search、permission denied 探针。
- Grooming 已确认默认口径见 [`pre-generation-confirmation-gate.md`](pre-generation-confirmation-gate.md)：PostHog dashboard weekly bucket 可用；GRR/NDR 可用 Tableau PNG 展示；Bug tickets、CS related、以及用户明确要求的 CS ticket / Jira-only 范围以 Jira 为 source of truth。
- Customer Feedback & FR 要合并 Community FR、Quick-win Canny、Intercom feedback、Jira Grooming CS 四源；Jira 仍是正式追踪和 owner/status 口径，其它来源用于补充诉求来源和影响面。完整 Ops Review 不允许把 `jira_only` 当作默认降级；四源没拉全时先补拉或进入生成前确认。
- 最终文档正文必须中文。英文只用于 source name、field name、product name、source_id 和少量固定业务术语。
- 双周报告引用月度指标时只当背景，evidence metric 必须 `context_only=true`；不要把月度 ARR/ARPU/NPS 写成双周 actual。

## Lark Wiki / Docx / Base / Sheet

使用 `$lark-skills`：

1. Wiki URL 先解析：
   ```bash
   lark-cli wiki spaces get_node --params '{"token":"<wiki_token>"}' --format json
   ```
2. Docx 读取：
   ```bash
   lark-cli docs +fetch --api-version v2 --doc <doc_token> --scope outline --format json
   lark-cli docs +fetch --api-version v2 --doc <doc_token> --scope full --detail simple --format json
   ```
3. Base 读取：
   ```bash
   lark-cli base +table-list --base-token <base_token> --format json
   lark-cli base +field-list --base-token <base_token> --table-id <table_id> --format json
   lark-cli base +record-list --base-token <base_token> --table-id <table_id> --field-id Summary --limit 50 --format json
   ```
4. 聚合优先用 `base +data-query`；但它不能用 formula/lookup/附件/系统字段作为维度或指标，失败时退回小范围 `record-list`。

关键 Base（用于模板追溯、历史参考或用户明确要求；Bug tickets / CS related 默认不以这些 Base 覆盖 Jira 结论；Customer Feedback & FR 仍需四源合并）：

| 名称 | base token | 表 |
|---|---|---|
| Feature Request Board | `FIq7bTFLsa0nVSsjpBfcKMwbnvf` | `tbl6UXlgQZlotjEt` |
| Dashboard (QA) | `LC6lbpSZrarwyisa0hmcQbXCnFe` | `tblruJHZLPYSeYAy`（2025-CS-BugReport）、`tblwGB5SkrbtZHLI`（2024-CS-BugReport）、`tblDjzvqwkZ9L252`（E2E data）、`tblHDCsDpglEUQF0`（FIN ALL） |

## Customer Feedback & FR 四源合并

输出顺序固定为 `Summary` → `Insight` → `Data`。先写跨来源主题结论和业务洞察，最后展示主题聚合表与 source coverage。

敏感字段边界：

- 不输出邮箱、客户名、conversation id、客户原话、raw feedback、quote、链接明细或长文本。
- 只保留主题、数量、来源覆盖、status/priority/decision/classification 这类聚合字段。
- 未归类信号只作为 triage backlog，不作为 headline。
- Quick-win Canny 不输出 `classification top: unknown N` 作为洞察；优先展示 PM Decision 和已明确的可行动分类，例如 accepted、needs_discovery、backlog、Quick win、Project candidate、Needs validation。
- Jira issue 先分流再聚合：Bug-only issue 进入 `Bug Tickets`；feedback/feature/support-like issue 才进入 `Customer Feedback & FR`。如果一个 issue 同时包含 bug 与需求信号，计入 Customer Feedback 时要按需求/痛点主题聚合，不能把 bug 计数重复当作反馈量。

四源取数：

| 来源 | 获取方式 | 过滤口径 | 用途 |
|---|---|---|---|
| Community FR | Google Sheet 优先 CSV；若 401，用 Composio Google Sheets `GOOGLESHEETS_BATCH_GET`，range `A1:Z1000` | 复盘月 `Date`；Grooming 取 `Business Type = GR/Both` | 社区长期诉求 |
| Quick-win Canny | 飞书 Base URL 先 `base +url-resolve`；再 `record-list` 指定 view 和字段 | 用户提供 view 是当前快赢池快照，不写成自然月计数 | 可快速交付 / accepted / needs-discovery / backlog |
| Intercom feedback | `$datadog` 的 `list-datastore-items` 只读分页，必须用 `--field` 最小投影 | 复盘月 `conversation_created_at`；`squad` 或 `domain` 包含 Grooming | 日常 support pain |
| Jira Grooming CS | `$jira` search 分页，JQL 用 `squad = Grooming`，不要用全文 `text ~ Grooming` 当主口径 | 复盘月 `created`；保留反馈/需求/support-like，Bug-only 放 `Bug Tickets` | 正式追踪 source of truth |

推荐 Jira JQL：

```bash
python3 /Users/moego-winches/Desktop/Company/person/skills/jira/scripts/jira.py search \
  'project = CS AND created >= "<YYYY-MM-01>" AND created < "<next-month-01>" AND squad = Grooming ORDER BY created DESC' \
  --limit 100 --format json
```

Intercom Datastore URL 形如：

```text
https://us5.datadoghq.com/actions/datastores/<datastore_id>
```

底层只读 REST 路径：

```text
GET https://api.us5.datadoghq.com/api/v2/actions-datastores/<datastore_id>/items?page[limit]=100&page[offset]=0
```

实际调用统一走 skill：

```bash
python3 /Users/moego-winches/Desktop/Company/person/skills/datadog/scripts/datadog.py \
  list-datastore-items a56cf9ac-2d2d-4e72-b19a-f9f0107868aa \
  --filter 'conversation_created_at:>=<start_ms> AND conversation_created_at:<end_ms> AND (squad:Grooming OR domain:Grooming)' \
  --all-pages --sort id --max-items 10000 \
  --field id --field conversation_created_at --field domain --field type \
  --field sentiment --field squad --field requirement --format json
```

分页由命令统一处理；只有 `meta.pagination.completion=complete` 才能作为全量。聚合时只读取结构化字段如 `domain`、`type`、`sentiment`、`squad`、`requirement`；不得投影或把 `email`、`conversation_id`、`quote` 写入 evidence pack 或文档。`requirement` 内嵌邮箱还需在消费层脱敏。

Quick-win Canny 读取字段建议：

```bash
lark-cli base +record-list \
  --base-token <base_token> --table-id <table_id> --view-id <view_id> \
  --field-id "Demand Theme" --field-id "Classification" --field-id "Priority" \
  --field-id "PM Decision" --field-id "Updated At" --field-id "Source Type" \
  --limit 200 --format json
```

聚合建议字段：

- `summary[]`：3-5 条本期主题结论。
- `insights[]`：洞察、数据支持、解读、团队关注。
- `theme_rows[]`：`theme`、`total_signals`、`community_fr`、`quick_win_canny`、`intercom_feedback`、`jira_grooming_cs`、`readout`。
- `source_coverage[]`：`source`、`signals_used`、`rows_scanned`、`window`。
- `source_mode`：完整 Ops Review 四源都已读取时写 `four_source`。`jira_only` 只用于用户明确要求“只看 CS ticket / Jira ticket”或任务本身就是 CS ticket-only 分析；Data 表只能展示 Jira-only 结果，并且摘要必须说明不是完整 Customer Feedback & FR 四源口径。
- `excludes_bug_only`：必须为 `true`，表示 bug-only issue 已从 Customer Feedback & FR 中排除。

数值对齐规则：

- `theme_rows[].total_signals` 必须等于该行四源列之和。
- `theme_rows[]` 各来源列的合计必须等于 `source_coverage[].signals_used` 对应来源的数值。
- 如果 source coverage 里有信号没有进入 headline 主题，必须用 `Other / Triage backlog` 或同义行承接；不要只在摘要写总数，导致主题表和来源覆盖对不上。

## Tableau MCP

优先使用 MCP/REST，而不是手工截图。需要先判断“飞书文档里用到的 Tableau 数据哪些能拉下来”时，先读 `references/tableau-extraction-audit.md`，按其中的三表输出格式完成审计。

发现路径：

1. 用 `mcp__tableau.search_content` 搜 `Dashboard`、`MonthlyOpsReviw`、`WeeklyOpsReviw`、`ChurnLogos`，过滤 `contentTypes: ["view","workbook"]`。
2. 或用 `mcp__tableau.list_views`，按 `workbookName` / `viewUrlname` / `contentUrl` 过滤。
3. 拿到 view LUID 后：
   - `mcp__tableau.get_view` 获取 workbook、datasource、owner、usage。
   - `mcp__tableau.get_view_data` 获取 CSV。
   - 只有需要入文图表时才用 `mcp__tableau.get_view_image`。
4. 需要字段定义时，用 `mcp__tableau.get_datasource_metadata`。

认证与 URL：

- 从 Tableau URL 解析 `server`、`site contentUrl`、`workbook contentUrl`、`view urlName`。
- 如果 Tableau MCP/REST 返回 401，不要立刻判定 PAT 缺失；先检查 URL 里的 `/site/<contentUrl>/` 是否和 MCP/环境变量配置的 `SITE_NAME` 一致。
- 只输出 HTTP 状态和 Tableau error code，不输出 PAT、账号密码、邮箱明细或客户敏感文本。
- Dashboard 自身的 `view/data` 不等于完整 dashboard 数据；必须枚举 workbook 下的 views/sheets，逐个判断 CSV/XLSX/PNG 可用性。

Grooming 初始搜索词：

- `Dashboard`
- `MonthlyOpsReviw`
- `WeeklyOpsReviw`
- `ChurnLogos`
- `Grooming`

必须记录 view filter，例如 `Business=Grooming only`、日期范围、tier 过滤。

## PostHog

使用 `$posthog-skills` 的 `scripts/posthog.py`。

默认 dashboard：

- host: `https://us.posthog.com`
- project: `21084`
- dashboard id: `546845`

步骤：

1. 先查已有 dashboard/insight：
   ```bash
   python3 /Users/moego-winches/Desktop/Company/person/skills/posthog-skills/scripts/posthog.py get-dashboard 546845
   ```
2. 若需要新 HogQL，先 discovery：
   ```bash
   python3 /Users/moego-winches/Desktop/Company/person/skills/posthog-skills/scripts/posthog.py list-event-defs --search onboarding --limit 20
   python3 /Users/moego-winches/Desktop/Company/person/skills/posthog-skills/scripts/posthog.py list-property-defs --type event --search planVersion
   ```
3. 所有 HogQL 必须带时间窗口：
   ```sql
   WHERE timestamp >= now() - INTERVAL 50 DAY
   ```
4. Dashboard SQL 保留 `{filters}`；一次性核数不用。

输出到 evidence pack 时保留 SQL 或 insight id。

Grooming 月度复盘默认接受 dashboard weekly bucket 作为周期口径。使用这类指标时：

- `period` 仍写复盘月，例如 `2026-05`。
- `traceability.query_or_filter` 必须写清真实时间窗，例如 `2026-05-03 to 2026-05-30 full weekly buckets`。
- 业务正文可以写 signup、upgrade、onboarding、usage 等指标，但不要写成自然月 exact。
- 只有用户明确要求自然月 exact 时，才补 `2026-05-01 <= timestamp < 2026-06-01` 的 HogQL。

PostHog 金额类字段边界：

- `dailyMetricsUpload` 或其它事件属性里的 sales、revenue、net sales、GMV、ARR 只能作为行为埋点或 usage proxy，不是财务 actual。
- 写入 evidence 时用 `metric_type=telemetry` 或 `usage_proxy`，`confidence` 用 `derived` / `manual`，并在 `delta` 写明“PostHog telemetry，不作为 finance actual”。
- 若要作为正式收入 headline，必须用 Tableau/finance/warehouse source 交叉验证后改用对应 source_id。

Onboarding 边界：

- `dailyMetricsUpload` 持续更新且字段可用时，优先使用 `days_to_first_value`、`days_to_go_live` 和关键功能每日计数，按公司去重后展示 Days to first value、Go-live rate、关键功能首次使用率；不得继续用 proxy signal 替代。
- Days to first value 与首次使用率以新订阅公司为 cohort，明确 cohort size、达到人数和观察窗口；Go-live rate 沿用 dashboard 定义，以全量 Grooming 商家为分母，并写清 Go-live 业务定义。
- 关键功能首次使用率默认至少覆盖 appointment、Online Booking、Grooming Report；按窗口内任一日对应 `*_count_1d > 0` 的公司数 / 新订阅 cohort 公司数计算。
- 如果只能从 churn reason、setup friction、单个 Jira issue 推断 onboarding 问题，`sections.onboarding.proxy_only=true`，正文写“proxy signal / 线索”，不得写成 onboarding funnel actual。

## Jira

使用 `$jira` 的唯一入口：

```bash
python3 /Users/moego-winches/Desktop/Company/person/skills/jira/scripts/jira.py search '<JQL>' --limit 50 --format json
python3 /Users/moego-winches/Desktop/Company/person/skills/jira/scripts/jira.py read CS-12345 --format json
```

用途：

- 从 Jira issue key 读取详情、评论、附件、linked issue。
- 对 CS-* 读取 linked Intercom conversations。
- 对 Base 聚合结果中的重点 issue 做深读。
- Bug tickets、CS related、以及用户明确要求的 CS ticket / Jira-only 反馈分析默认以 Jira 为 source of truth；优先 JQL 聚合，再按需要深读重点 issue。完整 Customer Feedback & FR 仍需补齐 Community FR、Quick-win Canny、Intercom feedback 和 Jira Grooming CS 四源。
- 对 Bug tickets、CS related、以及用户明确要求的 CS ticket / Jira-only 范围，Feature Request Board / QA Dashboard 当月断流或为 0 时不再阻塞生成，也不要把“是否接受 Jira fallback”写进文档正文；完整 Customer Feedback & FR 仍需四源合并，不能因此默认降级。

不要从 `search` 摘要直接写 root cause；根因必须读完整 issue 或明确标为“推测”。

## Datadog

使用 `$datadog` 的唯一入口：

```bash
python3 /Users/moego-winches/Desktop/Company/person/skills/datadog/scripts/datadog.py get-dashboard bk2-7s3-xqq --format json
python3 /Users/moego-winches/Desktop/Company/person/skills/datadog/scripts/datadog.py query-metrics --query '<metric query>' --from 7d --format json
python3 /Users/moego-winches/Desktop/Company/person/skills/datadog/scripts/datadog.py aggregate-logs --query '<DQL>' --from 7d --compute count --format json
```

步骤：

1. 先读取 dashboard 定义，识别 widget 查询。
2. 只对异常或 Grooming 相关 widget 做底层查询。
3. latency / error rate / 5xx / status:error / slow span 任一异常都进入 `system_loading.alerts`。
4. 查询不足时写“覆盖不足”，不要写“系统正常”。

## Evidence Pack 完整要求

采集完成后必须能回答：

- 每个章节的数据来自哪里？
- 取数的时间窗口是什么？
- 哪些数字是结构化查询得来，哪些只是人工输入或截图？
- 哪些问题仍需 owner 确认？
- 完整 Customer Feedback & FR 是否已经合并四源；如果没有，为什么不能发布为完整口径？
- 发布版 traceability 是否只保留正文实际使用的数据源和已接受的 manual policy？
