# 生成前确认门禁

用于 Ops Review evidence 已经采集完、准备渲染表格或发布飞书文档之前。目标是把“数据能不能用、口径要不要补、fallback 是否接受”这类问题前置问用户或继续补数，不让它们进入最终文档的 `Meeting Notes / Open Questions`、各章节 `Highlights` 或 `Risks / Watchouts`。

## 总原则

- 最终文档只写两类内容：
  - 已确认口径下的指标、趋势、风险、建议动作。
  - Data Source & Traceability 中的来源、查询条件、更新时间和必要限制。
- 生成前确认项不写进业务正文。凡是会影响“这个数字能不能当正式 review 指标”的问题，都放进 `pre_generation_confirmations[]`，先问用户或继续补数。
- 如果用户确认“这是人工收集项”，例如 NPS official，则标记为 manual policy；不要继续作为自动补数缺口，也不要在 Meeting Notes 里反复写“待补 official”。
- 如果用户确认某个 fallback 可用于本期，则文档正文可以写该 fallback 产生的业务指标；不要写“fallback 是否可用 / 等待 owner 确认”。

## 已确认默认口径（Grooming Ops Review）

以下口径已由用户确认，可作为 Grooming Ops Review 生成的默认处理。除非用户在本次任务里明确要求更严格口径，否则不要再把这些项放入 `pre_generation_confirmations[]`：

| 场景 | 默认处理 | 文档写法 |
|---|---|---|
| PostHog 月度指标来自 dashboard weekly bucket | 接受周期口径，可使用完整周桶指标 | 在 Data Source & Traceability 写清楚具体日期范围，例如 `2026-05-03 to 2026-05-30 full weekly buckets`；业务正文可写指标，但不要声称为自然月 exact |
| Tableau GRR / NDR 只有 PNG 可见 | 可直接用高分辨率 PNG 展示 | PNG 写入 section `visuals[]`；读数用 `confidence=manual` 或 `visual_only`；正文可作为图表/展示指标，不把“需要底层 sheet/crosstab”写成会议问题 |
| Feature Request Board / QA Base 断流或无当月数据 | Jira 是 Bug tickets、CS related、以及用户明确要求的 CS ticket / Jira-only 范围的 source of truth | 使用 JQL 聚合，Data Source 写明 Jira 查询范围；正文只写 Jira 聚合结论；不适用于完整 Customer Feedback & FR 四源合并 |
| Customer Feedback & FR 四源合并 | 必须合并 Community FR、Quick-win Canny、Intercom feedback、Jira Grooming CS；Jira 只承载正式追踪和 owner/status 口径 | Community/Intercom/Jira 按复盘月和 Grooming 过滤；Quick-win Canny 写成当前视图快照；正文按 Summary → Insight → Data 输出 |
| NPS official | 人工收集，不属于自动补数缺口 | 可在 traceability 标记 `manual_nps_collection_policy`；正文不反复写 NPS 待补 |
| 已补齐或已人工确认的数据缺口 | 删除旧 missing/gap/probe traceability，只保留成功来源或 manual policy | RUM 补齐后不保留 `datadog_rum_missing`；NPS manual 后不保留 NPS source search / permission probe / gap summary |
| 双周报告使用月度指标 | 可作为背景参考 | metric 写 `context_only=true`，正文写“月度背景”；不要放进双周 headline |

## 必须前置确认的场景

| 场景 | 归入 `pre_generation_confirmations` 的问题 | 不要写进最终文档的话 |
|---|---|---|
| 时间窗口不一致 | 周桶、完整周、自然月 exact、财务月、cohort 月是否作为本期口径 | “是否接受周桶口径”“要不要补 5/1-5/31 exact”“正式版需 exact” |
| 官方源断流后使用 fallback | Feature Request Board / QA Dashboard / Base 为 0 或停止更新后，是否接受 Jira / IM / 人工汇总替代 | “Jira fallback 是否可作为本期口径”“是否把 Jira 升级为 source of truth” |
| Tableau PNG / 视觉兜底 | PNG 读数、dashboard `view/data` 只吐部分 sheet、无法拿底层 sheet/crosstab 是否可作为本期指标 | “请 Tableau owner 暴露底层 sheet/crosstab”“PNG 视觉兜底能否当正式口径” |
| 异常值可信度 | 极端 NDR/GRR、缺 denominator、缺 cohort size、疑似低基数或 outlier | “MGP-only NDR 5978% 不适合 headline，需要补 denominator/outlier 说明” |
| 人工指标 | NPS official、人工整理 actual、owner 尚未提供的最终值 | “PM/CS 会前补 official actual、样本范围、分层口径” |
| 权限或来源限制 | Redshift/Salesforce/Tableau permission denied，只能证明当前账号拿不到 | “因为权限不足需要数据 owner 给数据”“permission denied 所以正式值待确认” |
| 文档卫生 / 安全提示 | 不输出客户明细、邮箱、行级文本、PAT 等 | “正式文档只保留聚合”“不得输出客户明细”作为业务风险 |
| Onboarding 只有 proxy 信号 | churn/setup/Jira 线索不能替代真实 funnel | 不写成 “Go-live / first value actual”；只写 proxy signal |
| Onboarding 已有 `dailyMetricsUpload` 真实字段 | `days_to_first_value`、`days_to_go_live`、关键功能 `*_count_1d` 可按公司聚合 | 不再使用 proxy-only；展示 Days to first value、Go-live rate、关键功能首次使用率及分母/窗口 |
| PostHog 金额字段 | PostHog sales/revenue/net sales/GMV/ARR 来自埋点 | 不写成 finance actual 或 ARR headline；只写 telemetry/usage proxy |

## 这次 5 月 Grooming 的反例

这些内容曾经被错误放进 final review 文档，后续生成时必须前置处理：

- Growth / Acquisition：`PostHog signup 118、upgrade 62 来自 5/3-5/30 完整周桶，不是自然月 exact；会议中确认是否接受周桶口径`
  - 处理：Grooming 默认已接受 dashboard weekly 口径；写清楚日期范围即可。只有用户要求自然月 exact 时才补 exact query。
- GRR / NDR reliability：`GRR Month12 视觉兜底 78%；MGP-only NDR 5978%；请 Tableau owner 暴露底层 sheet/crosstab`
  - 处理：Grooming 默认允许 PNG/视觉读数展示；极端值可展示为 visual/manual 指标，但不要放大成未解释的 headline。
- Bug / CS ticket：`Feature Request Board / Dashboard QA 断流，Jira fallback 是否可作为本期口径`
  - 处理：Bug tickets、CS related、以及用户明确要求的 CS ticket / Jira-only 范围默认 Jira 是 source of truth；正文只写 Jira 聚合出的业务指标。
- Customer Feedback 四源没拉全却渲染成四源表：`Community FR=0、Quick-win=0、Intercom=0、Jira=58`
  - 处理：完整 Ops Review 先补拉四源；仍拿不到则进入生成前确认或 open question，不直接发布 Jira-only 表。只有用户明确把本次范围收窄为 CS ticket / Jira-only，才使用 `source_mode=jira_only`。
- Customer Feedback 与 Bug Tickets 重复计数：`所有 Jira CS issue 同时进入反馈和 bug`
  - 处理：先按 issue cause / type 分流；bug-only 留在 Bug Tickets，Customer Feedback 只聚合需求、反馈和 support pain。
- Biweekly 中直接放月度 ARR/ARPU：`6 月 Total ARR / ARPU 被写成本期双周结论`
  - 处理：月度指标可作为背景，metric 必须 `context_only=true`，正文写“月度背景”。
- Onboarding 用 churn/setup friction 替代 funnel：`只有 churn reason 和 1 个 Self-Onboarding issue`
  - 处理：标 `proxy_only=true`，正文写 onboarding proxy signal，不写真实 onboarding funnel。
- PostHog 金额字段误读：`PostHog net sales USD 看起来像正式收入`
  - 处理：标 `metric_type=telemetry` 或 `usage_proxy`，不要作为财务 headline。
- NPS interpretation：`NPS official 待 PM/CS 补 official actual、样本范围和分层口径`
  - 处理：用户已确认 NPS official 是人工收集项；正文不要把它当自动补数缺口或会议 action。
- System loading：`RUM 数据已补齐后仍残留“RUM loading/PV/JS error 需要补齐”`
  - 处理：补齐后删除旧缺口提示，只保留真实系统体验风险。

## 允许进入 Meeting Notes 的内容

`meeting_notes[]` 只能包含基于已确认数据的业务讨论项，建议结构：

```json
{
  "topic": "Retention / Churn",
  "observation": "6 月 all-segment churn logos 30，其中 Mobile 16、Salon 14；脱敏后的 direct churn reason 显示 business close、paper/manual process、setup/data migration 和 product gap 等场景。",
  "impact": "流失原因分散在经营状态、迁移成本和产品覆盖差异上，Retention 复盘需要按 business type 拆动作。",
  "suggested_action": "Review Mobile/Salon 的前 3 个可干预流失场景，并决定 PM、CS、Data 各自推进的动作。",
  "owner": "PM / CS / Data"
}
```

可进入 Meeting Notes 的例子：

- Retention / Churn：按 business type 展示 direct churn reason，讨论可干预流失场景。
- Onboarding / Product adoption：go-live、first value、OB/report adoption 偏弱。
- Roadmap signal concentration：OB bug 达标但 feature/feedback 仍集中在 OB 和 Service Settings。
- System loading / Frontend quality：API 月度 error rate 低，但单日 spike、LCP、JS error views 暴露体验风险。

## 生成前提问格式

如果 `pre_generation_confirmations[]` 非空，先用简表问用户：

| Area | 当前发现 | 影响 | 建议默认动作 |
|---|---|---|---|
| Growth | 默认口径之外的时间窗口混用 | 可能误读增长归因 | 先补 exact，或经用户确认后标注真实窗口 |
| Retention | 默认 GRR/NDR 以外的视觉-only 指标 | 不适合当正式 headline | 补底层数据，或降级为参考并写入 `visuals[]` |

用户确认前，不发布最终飞书文档；如果用户明确要求先出草稿，文档正文只保留已确认业务指标，未确认项不要出现在 Meeting Notes 或 Risks。

## 发布前自检

用 `docs +fetch --scope keyword`、本地 Markdown 初稿，或显式生成的 XML 发布载体搜索这些词，确认它们没有出现在业务正文或最后一节：

- `是否接受`
- `是否需要`
- `要不要补`
- `自然月 exact`
- `正式版需`
- `owner 暴露`
- `底层 sheet`
- `crosstab`
- `source of truth`
- `official actual`
- `待确认`
- `仍缺`
- `仍未`
- `permission denied`
- `_missing`
- `gap_summary`
- `classification top: unknown`

命中不一定都是错误；如果只在 Data Source & Traceability 里作为来源证据或 query limitation 出现，可以保留。若命中在 `Highlights`、`Risks / Watchouts`、`Meeting Notes / Open Questions`，必须移出正文或改成已确认业务洞察。

发布版例外更严格：`_missing`、`gap_summary`、NPS source search / permission probe、`classification top: unknown` 不应出现在 Data Source、业务正文或最后一节。
