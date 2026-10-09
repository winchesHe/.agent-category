# 输出质量与 Evidence Pack 契约

## Evidence Pack Schema

基础结构：

```json
{
  "report": {
    "title": "Grooming Ops Review",
    "period": "2026-01",
    "period_granularity": "monthly",
    "language": "zh-CN",
    "generated_at": "2026-06-26T10:00:00Z",
    "target_business": "Grooming only"
  },
  "overall_summary": [
    {
      "conclusion": "新增注册较上一双周下降 9.3%，增长端承压。",
      "emphasis": [
        {"text": "下降 9.3%", "color": "red"},
        {"text": "增长端承压", "color": "orange"}
      ]
    }
  ],
  "sections": {
    "growth": {"insights": [], "highlights": [], "metrics": [], "visuals": [], "risks": [], "source_ids": []},
    "retention": {"insights": [], "highlights": [], "metrics": [], "visuals": [], "risks": [], "churn_reason_details": [], "source_ids": []},
    "onboarding": {"insights": [], "highlights": [], "metrics": [], "visuals": [], "risks": [], "proxy_only": false, "source_ids": []},
    "product_usage": {"insights": [], "highlights": [], "metrics": [], "visuals": [], "risks": [], "source_ids": []},
    "customer_feedback": {"source_mode": "four_source", "excludes_bug_only": true, "summary": [], "insights": [], "theme_rows": [], "source_coverage": [], "highlights": [], "metrics": [], "visuals": [], "risks": [], "source_ids": []},
    "bug_tickets": {"insights": [], "highlights": [], "metrics": [], "visuals": [], "risks": [], "source_ids": []},
    "cs_related": {"insights": [], "highlights": [], "metrics": [], "visuals": [], "risks": [], "source_ids": []},
    "system_loading": {"insights": [], "highlights": [], "metrics": [], "visuals": [], "risks": [], "source_ids": []}
  },
  "traceability": [],
  "pre_generation_confirmations": [],
  "meeting_notes": [],
  "open_questions": []
}
```

`report.language` 固定为 `zh-CN`。最终飞书文档的业务正文、summary、insight、risk、meeting notes 必须中文；source name、metric id、产品名、Jira/Tableau/PostHog 等专有名词可保留英文。

`overall_summary[]` 固定为 3–5 条结论式短句。优先使用 `conclusion` + `emphasis[]` 结构；`emphasis[].text` 必须是结论原文中的短语，`color` 可用 `red`、`orange`、`yellow`、`green`、`blue`、`purple`、`gray`。每条只突出 1–2 处关键数字、变化或判断，不整句着色。兼容纯字符串；字符串中冒号前的结论标签会自动加粗标蓝。

Customer Feedback 出现在 `overall_summary[]` 时，结论必须回答三件事：本期反馈主要集中在哪些主题、用户反复反馈了哪些具体功能/工作流、团队需要优先关注或分流什么。不要把“四源共 N 条、各来源分别 N 条”写成总览结论；来源数量与 coverage 只放在 `sections.customer_feedback.summary[]` 和 Data 表中。

`report.period_granularity` 用于区分 `monthly`、`biweekly` 等周期。双周报告如果引用月度 ARR、ARPU、NPS、GRR/NDR 或其它月度指标，必须在 metric 上写 `context_only: true`，并在正文里标明“月度背景/参考”，不能作为本期双周 headline。

`traceability[]` 项：

```json
{
  "source_id": "tableau_growth_monthly",
  "source_type": "tableau_view",
  "title": "MonthlyOpsReviw",
  "source_url": "https://...",
  "query_or_filter": "Business=Grooming only; period=2026-01",
  "retrieved_at": "2026-06-26T10:00:00Z",
  "owner": "Jenny"
}
```

最终文档的 `Data Source & Traceability` 只保留本次正文实际使用的数据源和必要口径说明。`source_type=manual_policy` 的内部人工口径继续留在 evidence 供关联校验，但不进入发布版 traceability。补数过程中的失败探针也只能留在内部 debug/evidence；尤其不要保留：

发布表固定展示 `标题`、`查询 / 过滤条件`、`拉取时间`、`Owner` 四列，不展示内部字段 `Source ID` 和 `类型`；`拉取时间` 将 evidence 中的 ISO 时间转换为北京时间 `YYYY-MM-DD HH:MM`。evidence 中仍必须保留原始 `retrieved_at`、`source_id`、`source_type`，并继续执行 section/metric/visual 到 source_id 的关联校验。

- 已被真实来源替代的 `*_missing`、`missing_source`、`gap_summary`、source search / metadata search。
- 用户已确认人工收集后的 NPS source search、permission probe、gap search。
- 已补齐后的旧缺口行，例如 RUM missing、NPS missing。
- `permission denied`、`owner 确认`、`底层 sheet` 这类会被读成待确认的问题。

`metrics[]` 项：

```json
{
  "name": "Monthly new logo",
  "value": "117",
  "delta": "-24% MoM",
  "period": "2025-11",
  "source_id": "tableau_growth_monthly",
  "confidence": "verified",
  "context_only": false
}
```

PostHog dashboard/HogQL 里的 sales、revenue、net sales、GMV、ARR 等金额字段，只能在 evidence 中作为 `metric_type: "telemetry"` 或 `metric_type: "usage_proxy"` 使用，并在 `delta` 或 `query_or_filter` 写清它来自行为埋点/事件属性；除非另有财务或 Tableau actual source 交叉验证，不得标成 `confidence=verified` 或写成财务实际值。

`insights[]` 项用于每个模块固定输出 `Data / Insight / Team attention`：

```json
{
  "topic": "Retention / Churn",
  "data": "6 月 all-segment churn logos 30，其中 Mobile 16、Salon 14；GRR/NDR 使用 Tableau PNG 展示。",
  "insight": "本期 churn 压力主要集中在 Mobile 与 Salon 的存量流失，GRR/NDR 适合作为视觉趋势参考，不单独作为可复算 headline。",
  "team_attention": "会议中优先讨论 Mobile/Salon 的前 3 类流失场景，以及是否需要对应 owner 制定降 churn 动作。"
}
```

`sections.customer_feedback.insights[]` 与 `sections.bug_tickets.insights[]` 额外必填 `customer_examples[]`，渲染为“洞察”和“团队关注”之间的独立列；不得把案例拼进 `insight`。每条案例至少有一个可点击出处：

```json
{
  "topic": "Online Booking / Scheduling",
  "data": "本期跨来源重复出现预约返回与服务选择问题。",
  "insight": "问题集中在端到端预约流程，不是单一入口的局部体验。",
  "customer_examples": [
    {
      "text": "在线预约返回上一步后，之前选好的服务会被清空，只能重新开始。",
      "representation": "anonymized_paraphrase",
      "sources": [
        {
          "label": "CS-46790（客户工单）",
          "url": "https://moego.atlassian.net/browse/CS-46790"
        }
      ]
    }
  ],
  "team_attention": "按预约创建到日历呈现的完整链路排查。"
}
```

`representation` 只允许：

- `direct_anonymized`：已确认可安全展示的短原话，正文使用引号展示。
- `anonymized_paraphrase`：为去除身份或敏感上下文而做的忠实转述，正文必须明确显示“匿名转述”。

每个 `customer_examples[]` 项的 `text` 不超过 280 个字符；`sources[]` 非空，每个 source 必须有非空 `label` 和 `http(s)` `url`。不得补造客户表达或链接。

`sections.customer_feedback` 额外支持 `source_mode`、`excludes_bug_only`、`summary[]`、`theme_rows[]` 和 `source_coverage[]`，用于渲染 `Customer Feedback & FR` 的固定顺序：`Summary` → `Insight` → `Data`。

```json
{
  "source_mode": "four_source",
  "excludes_bug_only": true,
  "summary": [
    "本期最高频可行动主题是 Online Booking / Scheduling，其次是 Staff / Operations。"
  ],
  "theme_rows": [
    {
      "theme": "Online Booking / Scheduling",
      "total_signals": 135,
      "community_fr": 3,
      "quick_win_canny": 13,
      "intercom_feedback": 80,
      "jira_grooming_cs": 39,
      "readout": "跨来源优先看"
    }
  ],
  "source_coverage": [
    {
      "source": "Intercom feedback",
      "signals_used": 105,
      "rows_scanned": 5928,
      "window": "2026-05 by conversation_created_at; squad/domain contains Grooming"
    }
  ]
}
```

`source_mode` 取值：

- `four_source`：已合并 Community FR、Quick-win Canny、Intercom feedback、Jira Grooming CS。`source_coverage[]` 必须包含四个来源；`theme_rows[]` 必须能按四源列展示。
- `jira_only`：只用于用户明确要求“只看 CS ticket / Jira ticket”，或任务本身是 CS ticket-only 分析。正文必须标明这是 Jira-only / CS ticket 口径，不得当作完整 Customer Feedback & FR 发布口径；Data 只能展示 Jira-only 表，不得渲染 Community / Quick-win / Intercom 三列为 0 来假装四源已拉。

当 `source_mode=four_source` 时，`theme_rows[]` 必须和 `source_coverage[]` 数值对齐：每行 `total_signals` 等于四源列之和；四源列合计等于对应 source coverage 的 `signals_used`；如果 coverage 中有未进入 headline 主题的信号，必须新增 `Other / Triage backlog` 行承接，不得让摘要总数、主题表和来源覆盖出现不一致。

`excludes_bug_only=true` 表示 Customer Feedback & FR 已排除 bug-only issue。Bug-only issue 只进入 `bug_tickets`；同一个 Jira ticket 只有在同时含反馈/需求信号时才可进入 Customer Feedback，并且要在聚合逻辑里说明。

Customer Feedback & FR 不输出邮箱、客户名、conversation id、未脱敏原始长文本或其它可识别客户身份的信息。允许在独立的“客户原话 example（匿名）”列展示已脱敏短原话，或明确标注为“匿名转述”的忠实改写；每条案例必须附原始记录链接。

Quick-win Canny 的空/未知分类只保留在内部计数，不作为正文洞察或 headline。正文优先展示 PM Decision 与可行动分类分布，例如 accepted、needs_discovery、backlog、Quick win、Project candidate、Needs validation。

`sections.retention.churn_reason_details[]` 项用于展示脱敏后的直接 churn reason：

```json
{
  "date": "2026-06-12",
  "segment": "Mobile",
  "tier": "T4",
  "reason": "Business closed / stopped using the product"
}
```

要求：

- 只放简短 reason，不放邮箱、客户名、公司名、Company ID、Intercom 原文长文本或其它可识别客户身份的信息。
- 不把 direct reason 改写成 reason 分类质量判断。
- 死亡、疾病、家庭变故、个人身份或其它敏感事件必须改写成低敏业务原因，例如 `Business closed / stopped operation`、`Owner personal reason`；不要输出 `passed away`、`died`、具体病名或家庭细节。
- 无 reason 时只在单行 reason 写 `No reason captured` 或中文等价描述，不扩展为正文 headline。

`confidence` 取值：

- `verified`：结构化查询或 owner 确认。
- `derived`：由结构化数据计算得出。
- `manual`：人工输入、会议记录或截图。
- `visual_only`：PNG/图片可展示，但没有结构化底层数据可复算。
- `missing`：缺数据，仅作为待确认问题出现。

`visuals[]` 项用于把 Tableau PNG 或其它图片证据渲染进文档。发布前必须提供可直接显示的 `href`（HTTPS 图片 URL）或 `src`（已上传的飞书图片 token）；只有本地路径时，先上传或替换成可显示地址，再运行 `--check`。

```json
{
  "title": "GRR / NDR dashboard PNG",
  "href": "https://example.com/grooming-grr-ndr.png",
  "caption": "GRR / NDR visual-only dashboard, May 2026",
  "width": 960,
  "source_id": "tableau_retention_grr_ndr_png",
  "confidence": "visual_only"
}
```

`pre_generation_confirmations[]` 项用于生成表格/发布文档前向用户确认，不能出现在最终文档的最后一节。详细规则见 [`pre-generation-confirmation-gate.md`](pre-generation-confirmation-gate.md)。凡是影响核心数字是否能作为正式口径的问题，都必须进入这里：

```json
{
  "area": "Growth",
  "question": "PostHog signup/upgrade 当前是 5/3-5/30 完整周桶，是否接受为本期口径，还是要补 5/1-5/31 exact？",
  "impact_if_unconfirmed": "若不确认，文档不能把 signup/upgrade 当作自然月增长归因。",
  "default_action": "先补 exact；或经用户确认后标注 dashboard weekly 口径。"
}
```

Grooming Ops Review 的已确认默认口径：

- PostHog dashboard weekly bucket 可作为本期周期口径；在 `traceability.query_or_filter` 写清日期范围，不要把指标描述成自然月 exact。
- 双周报告可以使用月度指标作背景，但 metric 必须 `context_only=true`；正文不可把月度 ARR/ARPU/NPS 等写成本期双周结果。
- Tableau GRR / NDR 可用高分辨率 PNG 展示；`confidence` 用 `manual` 或 `visual_only`，不要写成结构化 `verified`。
- Bug tickets、CS related、以及用户明确要求的 CS ticket / Jira-only 反馈分析使用 Jira 作为 source of truth；Feature Request Board / QA Base 断流不再阻塞这些 ticket 追踪章节。完整 Customer Feedback & FR 仍必须补齐四源或进入生成前确认。
- NPS official 是人工收集项，不作为自动补数缺口。

必须前置确认的典型场景：

- 时间窗口不一致：周桶、完整周、自然月 exact、财务月或 cohort 月混用；Grooming 默认接受 PostHog dashboard weekly bucket 的情况除外。
- 数据源兜底：官方 Board/Base/Dashboard 断流后改用 Jira、IM、人工汇总或截图；Bug tickets、CS related、CS ticket-only 分析默认使用 Jira 的情况除外。Customer Feedback & FR 四源没拉全不是普通兜底场景，不能直接降级为 `jira_only` 发布。
- Tableau 视觉兜底：PNG 视觉读取、dashboard `view/data` 只吐部分 sheet、需要 owner 暴露底层 sheet/crosstab；Grooming GRR/NDR 默认用 PNG 展示的情况除外。
- 异常值可信度：极端 NDR/GRR、低基数、缺 denominator、缺 cohort size、疑似 outlier。
- 人工指标：NPS official、人工整理的目标/actual、owner 尚未提供的最终值。
- 权限或来源限制：Salesforce/Redshift/Tableau permission denied 只能证明“当前拿不到”，不能替代正式 actual。
- `dailyMetricsUpload` onboarding 字段可用时，Onboarding 必须 `proxy_only=false`，并优先包含 Days to first value、Go-live rate、关键功能首次使用率；指标必须写清 cohort/分母、达到人数、观察窗口和公司级去重口径。
- Onboarding 没有真实 funnel/dashboard 或 `dailyMetricsUpload` onboarding 字段时只能写 proxy-only insight，`sections.onboarding.proxy_only=true`，不要把 churn/setup friction 或单个 Jira issue 当作 onboarding funnel actual。

`meeting_notes[]` 项用于最后的 `Meeting Notes / Open Questions`，必须基于本次已生成指标做 review 讨论分析，而不是把数据补拉缺口原样贴进去。推荐结构：

```json
{
  "topic": "Retention / Churn",
  "observation": "6 月 all-segment churn logos 30，其中 Mobile 16、Salon 14；直接 churn reason 集中在 business close、paper/manual process、setup/data migration 和 product gap 等场景。",
  "impact": "流失不是单一 funnel 问题，更像不同 business type 的经营状态、迁移成本和产品覆盖差异叠加。",
  "suggested_action": "会议中确认 Mobile/Salon 前 3 个可干预流失场景，以及哪些需要 PM、CS 或 Data 分别推进。",
  "owner": "PM / CS / Data"
}
```

`open_questions[]` 仍可保留数据缺口或口径待确认项；渲染文档时若存在 `meeting_notes[]`，最后一节优先展示 `meeting_notes[]`，`open_questions[]` 不应替代业务复盘讨论。

`meeting_notes[]` 禁止出现这类生成前确认语句：

- “是否接受 / 是否需要 / 要不要补 exact / 需要 owner 暴露底层 sheet / crosstab”
- “fallback 是否可作为本期口径 / source of truth 是否切换”
- “NPS official 待补 / 样本范围待确认 / 分层口径待确认”
- “因为权限不足所以需要数据 owner 给数据”
- “正式版需 exact / 仍缺 / 仍未定位 / permission denied 导致无法确认”

同样的禁止规则也适用于各 section 的 `highlights` 和 `risks`：这些字段只能写业务观察和业务风险，不能承载数据口径确认项。

## 文档质量门禁

生成前：

- `report.title`、`report.period`、`report.target_business` 非空。
- 默认生成任务完成完整链路：多源采集、缺口回填、口径门禁、evidence pack 归一化、Markdown 渲染检查；审计已有文档、只补特定缺口、内部重渲染/校验按对应入口收窄范围。
- `report.language` 必须为 `zh-CN`，业务正文必须包含中文表达。
- `report.period_granularity` 必须说明周期类型；双周报告引用月度 metric 时必须 `context_only=true`。
- 固定 8 个业务 section 都存在。
- Markdown h2 必须包含固定英文 canonical section name：`Overall Summary`、`Data Source & Traceability`、`Growth`、`Retention`、`Onboarding`、`Product Usage`、`Customer Feedback & FR`、`Bug Tickets`、`CS Related`、`System Loading`、`Meeting Notes / Open Questions`；可追加中文后缀。
- `Data Source & Traceability` 必须是最后一个 h2，紧跟在 `Meeting Notes / Open Questions` 之后，作为审计与复核附录。
- 每个 section 至少有 `highlights`、`metrics`、`risks`、`source_ids`，`source_ids` 非空且能在 `traceability` 中找到。
- 每个 section 应优先有 `insights[]`，并能表达 `Data / Insight / Team attention`；若暂时没有，正文也必须保持这个结构。
- `customer_feedback.insights[]` 与 `bug_tickets.insights[]` 的每条洞察必须有非空 `customer_examples[]`；每条案例都满足长度、匿名表达类型和来源链接校验。
- `customer_feedback` 应优先填 `source_mode`、`excludes_bug_only`、`summary[]`、`insights[]`、`theme_rows[]`、`source_coverage[]`；正文顺序必须是 Summary、Insight、Data。完整 Ops Review 应使用 `source_mode=four_source` 且必须有四源 coverage；`source_mode=jira_only` 只允许用于用户明确的 CS ticket / Jira-only 范围，且不得渲染成四源表。`theme_rows` 与 `source_coverage` 的信号数必须自洽。
- `onboarding` 如果没有 PostHog onboarding/funnel source，必须 `proxy_only=true` 并在正文写成 proxy，不得写成真实 onboarding funnel。
- PostHog 金额类 metric 必须标 `metric_type=telemetry` 或 `usage_proxy`，且不得伪装为财务 actual。
- 发布版 `traceability` 不得包含已被补齐或人工确认替代的 `_missing`、`gap_summary`、source search、permission denied 探针。
- Retention 如果有 churn reason 数据，写入 `churn_reason_details[]` 并脱敏展示 direct reason。
- 每个非空 metric 的 `source_id` 能在 `traceability` 中找到。
- 每个 visual 的 `source_id` 能在 `traceability` 中找到，且至少有 `href`、`src`、`image_url` 或 `url` 之一。
- `open_questions` 覆盖所有缺失数据源或不确定口径。
- `meeting_notes` 把关键异常、解释假设、建议动作和 owner 汇总为会议讨论项；不要只列“还缺什么数据”。
- 如果 `pre_generation_confirmations` 非空，先集中问用户或继续补数，不发布最终文档。
- 收窄范围来自用户明确要求，并在正文口径中说明；完整 Ops Review 使用完整数据源和正式口径。

生成后：

- 飞书页面标题包含报告名称和复盘周期；正文直接从 `Overall Summary / 总览` 开始，不重复报告标题，不展示“目标”“生成时间”或“文档初稿”等生成过程说明。
- Markdown 初稿直接以 `## Overall Summary / 总览` 开头；飞书 DocxXML 保留 `<title>`，但正文不再渲染重复 `<h1>`。
- 包含 Overall Summary、Data Source & Traceability 和所有固定章节；中文标题必须作为后缀或并列名出现，不能替代固定英文 canonical name。
- 11 个固定 h2 后均紧跟且只跟一段栏目用途说明；Markdown 使用引用行，DocxXML 使用灰色小字 `<p><span text-color="gray">...</span></p>`，说明文案与 `grooming-template.md` 完全一致。
- Overall Summary 直接给出 3–5 条结论，并在飞书中用加粗彩色文字突出关键数字与判断；Markdown 用加粗表达同一重点。
- 关键判断使用引用块、表格或短列表突出；风险层级保持简洁。
- 不出现账号、密码、PAT、API key、鉴权 token、Authorization、cookie。
- 不出现 PAT、账号密码、邮箱明细、conversation id、客户身份字段、未脱敏原始长文本或客户敏感长文本；允许按 `customer_examples[]` 契约展示脱敏短原话或明确标注的匿名转述，且必须带出处链接；脱敏后的短 churn reason 可展示。
- 不出现 `classification top: unknown`、`*_missing`、`gap_summary`、NPS permission/source search 这类会被读成待确认或数据质量问题的历史探针。
- 不出现用 reason 分类质量、缺失比例或采集质量替代 direct reason 的描述。
- 不出现死亡、疾病、家庭变故等个人敏感 churn reason 原文。
- 不出现“AI 自动分析了所有问题”这类无法证明的表述。

发布到飞书后：

```bash
lark-cli docs +fetch --api-version v2 --doc <doc_token> --scope full --detail full --format json
```

验收：

- 标题正确。
- 章节顺序正确。
- 关键数字旁有来源或 Data Source 表可追溯。
- Markdown 表格、链接、图片和引用块可见。
- Customer Feedback & FR、Bug Tickets 的洞察表均有独立的“客户原话 example（匿名）”列；每条案例显示出处，链接可点击，案例没有混入“洞察”列。
- PM 能从“审阅和补充”开始，而不是从零重写。

## Done 标准

第一阶段 Done 同时满足：

- 文档结构符合 Grooming Ops Review 使用习惯。
- 核心数字准确率目标为 `>= 95%`，无法验证的数字不得伪装为已验证。
- 文档生成成功率目标为 `>= 90%`。
- 单次准备时间相较人工流程目标下降 `>= 50%`。
- 至少一次真实业务试运行被明确判断为“可用于下一次 Ops Review”。
