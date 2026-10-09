---
name: ops-review-doc-generator
description: 完整生成可追溯的 Ops Review 飞书文档 Markdown 初稿，特别是 Grooming Ops Review；按模板从 Tableau、PostHog、Jira、Datadog、Lark 和四源反馈取数，补齐 evidence pack，经过口径门禁、Markdown 渲染和发布验收。
---

# Ops Review Doc Generator

本 skill 把 Ops Review Agent 第一阶段落成可执行的完整文档生成链路：从多源证据采集、缺口回填、口径确认、evidence pack 归一化，到 Markdown 初稿渲染和飞书发布验收。第一版模板固定服务 Grooming Ops Review；后续可以把同一 evidence pack 契约扩展到其它 Ops Review。

## Agent 要完成的事

- 交付一篇 PM 可审阅的飞书文档初稿。
- 将关键数字写入 evidence pack，并在文档里保留来源链接、查询口径或截图来源。
- 对账号、密码、PAT、API key、鉴权 token、cookie、Authorization header 做隔离和脱敏；文档、日志、reference、evidence pack 只保留低敏来源信息。
- 数据可靠性不足时，写入 `pre_generation_confirmations` 或 `open_questions`，并标明“待确认 / 数据缺口”。
- 飞书文档正文使用中文；Tableau/PostHog/Jira、字段名、source_id、产品名和少量固定业务术语可保留英文。
- 业务目标如“NPS 回到 80”“OB bug 降到 5/month”以复盘追踪目标呈现。
- 默认跑完整 Ops Review 文档链路：多源采集、缺口回填、口径门禁、evidence pack、Markdown 初稿渲染和发布验收。
- 完整 Grooming Ops Review 的 Customer Feedback & FR 合并 Community FR、Quick-win Canny、Intercom feedback 和 Jira Grooming CS 四源；Jira-only 作为用户明确要求的 CS ticket / Jira ticket 范围。
- `Customer Feedback & FR` 与 `Bug Tickets` 的每条洞察必须在“洞察”和“团队关注”之间单独展示 `客户原话 example（匿名）` 列，不得把案例塞进“洞察”列；每条案例都要有至少一个可点击的 Jira、Slack、Canny、Intercom 或原始记录链接。
- 案例优先使用已脱敏的短原话；无法安全直接引用时，必须明确标为“匿名转述”。禁止补造案例，也禁止输出客户名、邮箱、conversation id 或可识别客户身份的长文本。

## 默认任务入口

| 任务入口 | 执行范围 | 必须验收 |
|---|---|---|
| 生成 Grooming Ops Review | 跑完整链路：确认范围 → 读模板 → 采集多源数据 → 补数 → 口径门禁 → evidence pack → 渲染 Markdown 初稿 → 发布/验收 | `--check` 通过；若发布飞书，fetch 回查标题、章节、表格、traceability 和敏感信息 |
| 审计已有初稿或飞书文档 | 读取 `references/output-quality.md` 和 `references/pre-generation-confirmation-gate.md`，检查正文、traceability、Meeting Notes、敏感信息和禁用词 | 输出具体问题清单和建议修正路径 |
| 只补某个数据缺口 | 读取对应数据源 reference 和 `references/supplemental-data-backfill.md`，补齐后回写 evidence 口径 | 成功来源进入发布版 traceability；失败探针只留内部 debug |
| 内部重渲染 / 校验已生成 evidence | 仅用于维护、调试或 agent 已经在本地生成 evidence 的场景；先读 `references/output-quality.md`，校验后再渲染 Markdown | `--check` 通过；Markdown 直接以 `## Overall Summary / 总览` 开头且包含固定 canonical 章节 |

## 必读 References

按任务需要加载：

| 文件 | 何时读 |
|---|---|
| `references/grooming-template.md` | 任何 Grooming Ops Review 文档生成任务，先读 |
| `references/data-source-playbook.md` | 需要从 Tableau/PostHog/Jira/Datadog/Lark 取数时读 |
| `references/supplemental-data-backfill.md` | 初稿 evidence 有缺口、PNG 兜底、权限不足或需要补拉 Datadog RUM / Tableau GRR-NDR / NPS 等边缘数据时读 |
| `references/pre-generation-confirmation-gate.md` | 渲染表格或发布文档前，判断哪些口径/fallback/权限/人工数据问题必须先问用户 |
| `references/tableau-extraction-audit.md` | 需要判断飞书文档里的 Tableau 数据哪些能通过 MCP/REST 拉取时读 |
| `references/output-quality.md` | 生成、发布或验收飞书文档前读 |

同时按需加载并遵守这些已有 skills：

- `$lark-skills`：解析 Wiki、读取/创建 Docx、读取 Base/Sheet、发布飞书文档。
- `$posthog-skills`：查询 PostHog dashboard/事件/漏斗/留存数据。
- `$jira`：读取 Jira issue、JQL 搜索、CS-* linked Intercom conversation。
- `$datadog`：读取 Datadog dashboard、metrics、logs、spans。
- Tableau MCP：优先用 `mcp__tableau.search_content/list_views/get_view/get_view_data/get_view_image` 发现和读取 Tableau view。

## 完整端到端流程

1. **确认范围与验收**
   - 默认目标：生成 Grooming Ops Review 文档初稿。
   - 默认源文档：`2026.1.7 Grooming Ops review` Wiki；默认立项依据：`Ops Review Agent 项目立项` Wiki。
   - 需要确认：复盘周期、输出位置（本地 Markdown / 新飞书文档 / 覆盖已有文档）、是否允许创建或更新飞书文档。
   - 默认执行完整链路；审计已有文档、只补特定数据缺口、内部重渲染/校验已生成 evidence 时，按对应任务入口收窄范围。

2. **读取模板与 reference**
   - 用 Lark Wiki 解析源文档 token，读取大纲和 Data source 段。
   - 下钻文档内的 `<cite>` / `<bitable>` / `<sheet>` 引用，拿真实 Base/Sheet token 和 table id。
   - 用 `references/grooming-template.md` 对齐固定章节、标题和模块写法。

3. **采集数据**
   - Tableau：先按 `references/tableau-extraction-audit.md` 分析 URL/site/workbook/view 和可拉取性，再用 `search_content` 或 `list_views` 找 workbook/view LUID；CSV 优先，Grooming GRR/NDR 可用 PNG 展示并写入 `visuals[]`，置信度标为 `manual` 或 `visual_only`；ChurnLogos 要补 exact period 的 all-segment 明细和脱敏 churn reason。
   - PostHog：先复用 dashboard/insight；需要新查询时用 HogQL 且带时间窗口。Onboarding 在 `dailyMetricsUpload` 可用时优先展示 Days to first value、Go-live rate 和 appointment / Online Booking / Grooming Report 关键功能首次使用率，不再使用 proxy-only；金额类 sales/revenue/net sales/GMV/ARR 仍标为 telemetry/usage proxy。
   - Lark Base/Sheet：读取模板、历史 Board/Base 和引用对象用于 traceability；Grooming Bug tickets / CS related 使用 Jira 结论做当前追踪口径。
   - Customer Feedback & FR：完整 Ops Review 合并 Community FR、Quick-win Canny、Intercom feedback 和 Jira Grooming CS 四源；Jira 承载正式追踪和 owner/status 口径，其它来源补充社区诉求、快赢池和 support pain。采集主题信号时同步保留可安全发布的匿名客户表达及原始记录链接。四源未齐时先补拉或进入生成前确认。
   - Jira：Bug tickets、CS related、以及用户明确要求的 CS ticket / Jira-only 范围使用 Jira 作为默认 source of truth；用 JQL 聚合，读完整 issue 后写根因，并为 Bug Tickets 洞察保留匿名客户表达与对应 CS/修复单链接。`source_mode=jira_only` 对应这类 CS ticket-only 范围。
   - Datadog：先读 dashboard 定义，再只对异常 widget 或关注维度查询 logs/spans/metrics；Intercom feedback 的 Datadog Actions Datastore 按 `references/data-source-playbook.md` 读取。
   - 初稿还有缺口时，进入 `references/supplemental-data-backfill.md` 的补数顺序；人工收集项（如 NPS official）标记为 `manual`。
   - 每个固定章节都写入可追溯来源；完整 Customer Feedback & FR 先尝试四源合并。

4. **数据口径门禁**
   - 先读 `references/pre-generation-confirmation-gate.md`，按里面的分类表扫描所有 metrics、highlights、risks 和 `meeting_notes` 候选项。
   - 渲染表格或发布飞书文档前，先套用 `references/pre-generation-confirmation-gate.md` 的 Grooming 已确认默认口径。
   - 再扫描所有指标和 `meeting_notes` 候选项，把默认口径之外的“是否接受周桶/自然月 exact”“是否使用其它 fallback”“PNG 视觉兜底能否作为正式口径”“是否需要 Tableau owner 暴露底层 sheet/crosstab”“人工值是否已提供”等问题归入 `pre_generation_confirmations`。
   - `pre_generation_confirmations` 非空时，先集中问用户确认或继续补数。
   - `meeting_notes` 只写基于已确认数据提出的业务异常、解释假设、建议动作和 owner；数据源健康、权限、fallback 合法性、自然月 exact 等内容留在 traceability 或生成前确认。
   - 门禁通过后进入发布态；用户明确要预览时，只输出已确认内容并标明预览状态。

5. **归一化 evidence pack**
   - 按 `references/output-quality.md` 的 schema 填入 `report`、`sections`、`traceability`、`pre_generation_confirmations`、`meeting_notes`、`open_questions`。
   - 每个 section 的 `source_ids` 必须非空并能在 `traceability` 找到；缺数据另外写入 `open_questions`。
   - 指标要区分 `value`、`delta`、`period`、`source_id`、`confidence`；双周报告引用月度指标时必须标为 `context_only=true`，只能作背景，不做本期 headline。
   - 每个 section 优先填 `insights[]`，固定表达 `Data / Insight / Team attention`；Retention 额外填 `churn_reason_details[]`，只保留脱敏后的直接 reason，并把死亡、疾病、家庭变故等个人敏感事件改写成低敏业务原因。
   - `customer_feedback.insights[]` 与 `bug_tickets.insights[]` 额外必填 `customer_examples[]`。每项包含 `text`、`representation`（`direct_anonymized` 或 `anonymized_paraphrase`）和非空 `sources[]`；每个 source 必须有 `label` 与 `http(s)` `url`。

6. **生成文档初稿**
   - 使用脚本渲染本地 Markdown：
     ```bash
     python3 /Users/moego-winches/Desktop/Company/person/skills/ops-review-doc-generator/scripts/render_grooming_ops_review.py \
       --input evidence.json \
       --output /tmp/grooming-ops-review.md \
       --check
     ```
   - 如需发布到飞书，先读 `$lark-skills` 的 `content-doc.md`，确认 Markdown 到飞书文档的创建或覆盖方式；若发布工具需要 DocxXML，再显式使用 `--format xml` 生成发布载体。
   - `--check` 失败时修 evidence，再重新渲染。

7. **验收**
   - 本地：脚本 `--check` 通过，Markdown 直接以 `## Overall Summary / 总览` 开头，包含所有必需章节。
   - 数据：关键数字都有 `traceability`；数据缺口进入 `open_questions`。
   - 飞书：创建/更新后用 `docs +fetch --detail full` 验证标题、章节、引用块、表格和关键来源可见；同时回查 Customer Feedback & FR、Bug Tickets 洞察表均有独立的“客户原话 example（匿名）”列，每条案例的出处链接可点击。
   - 发布态：完成敏感信息、历史探针和生成前确认语句扫描。

## 输出口径

生成文档应包含：

- 飞书页面标题包含报告名称与复盘周期；正文不重复标题，不展示目标或生成时间说明块。
- 章节标题包含固定英文 canonical name；可追加中文后缀，例如 `Overall Summary / 总览`。
- 每个固定二级标题后紧跟一段灰色小字说明栏目用途；说明文案固定使用 `references/grooming-template.md` 的定义，不插入其它 block，不重复添加。
- Overall Summary：直接给出本期最重要的 3–5 个结论、风险或待决策点，并用加粗彩色文字突出关键数字与判断。
- Data Source & Traceability：发布表只展示数据源标题/链接、查询/过滤条件、拉取时间和 Owner，拉取时间统一为北京时间 `YYYY-MM-DD HH:MM`，并排除 `source_type=manual_policy` 的内部人工口径行；内部 `source_id/source_type` 和 manual policy 不展示但继续用于 evidence 校验。
- Data Source & Traceability 固定放在全文最后、位于 Meeting Notes / Open Questions 之后，作为审计与复核附录，避免打断业务讨论主线。
- 正文中文输出。
- Growth、Retention、Onboarding、Product Usage：每个模块固定包含 `Data / Insight / Team attention`。
- Customer Feedback & FR：先写 Summary 和 Insight，最后写 Data；Data 合并四源主题表和 source coverage；主题表每行 total 等于四源列之和，主题表列合计等于 source coverage 的 signals_used，未归入 headline 的信号用 Other / Triage 行承接。
- Customer Feedback & FR、Bug Tickets：洞察表固定为 `主题 / 数据 / 洞察 / 客户原话 example（匿名） / 团队关注` 五列；案例列不得并入洞察列，每条案例下方必须展示可点击出处。
- Customer Feedback & FR 与 Bug Tickets 分流：bug-only issue 进入 Bug Tickets。
- Bug Tickets / CS Related。
- System Loading。
- Retention 的 churn reason 直接展示脱敏后的 reason 明细。
- Meeting Notes / Open Questions：基于本期已生成指标提出异常、解释假设、建议动作和 owner。

最终文档应像 PM 可直接拿去 review 的业务材料。
