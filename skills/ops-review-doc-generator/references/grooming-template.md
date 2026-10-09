# Grooming Ops Review 模板

## 已确认来源

| 用途 | 标题 | Wiki token | 实际对象 |
|---|---|---|---|
| 立项依据 | Ops Review Agent 项目立项 | `XwYrwv65FiwcCGkNXyKcGnrqndz` | docx `KwkJdPXLKofMqHxU6ZAcjB9InSb` |
| Grooming 模板样例 | 2026.1.7 Grooming Ops review | `ZFaWwnbjgiJuVPk0qLYcnwOPnIf` | docx `X4FBdToYFoCOkFxcfQicTy4pnjb` |
| Feature Request Board | Feature Request Board | `M2q5wEFuTiI5uMkGQ80ceDnRnyf` | bitable `FIq7bTFLsa0nVSsjpBfcKMwbnvf`，表 `tbl6UXlgQZlotjEt` |
| QA Dashboard | Dashboard (QA) | `LspTwn0vYiM86Iklno8cQl8Xn1f` | bitable `LC6lbpSZrarwyisa0hmcQbXCnFe` |
| Bug review 样例 | ERP Bug 单分析（Week 34） | `Jp0Yw0WkGiEQNMkHVlXcPrFwnob` | docx `VZ6ZdxJ17oIFGHxRMMycuy4lnrd` |

所有 Wiki token 必须先用 `lark-cli wiki spaces get_node` 解析，不能直接当 file token。

## 固定章节

1. `Overall Summary`
2. `Growth`
3. `Retention`
4. `Onboarding`
5. `Product Usage`
6. `Customer Feedback & FR`
7. `Bug Tickets`
8. `CS Related`
9. `System Loading`
10. `Meeting Notes / Open Questions`
11. `Data Source & Traceability`

固定章节名可保留英文业务术语，但正文、summary、insight、risk、meeting notes 必须中文输出。

发布文档的 h2 标题必须包含上表固定英文 canonical name；可追加中文后缀，例如 `Overall Summary / 总览`、`Data Source & Traceability / 数据源与可追溯性`。不要只写中文标题，否则脚本或人工验收按固定章节名扫描时会漏检。

每个 h2 后必须紧跟且只跟一段灰色小字，简要说明该栏目的用途；说明与标题之间不得插入其它 block。Markdown 初稿用紧邻标题的引用行表达，DocxXML 使用 `<p><span text-color="gray">说明文字</span></p>`。固定说明如下：

| 二级标题 | 栏目说明 |
|---|---|
| Overall Summary / 总览 | 汇总本期最重要的业务变化、风险与需要团队决策的事项，帮助会议快速聚焦。 |
| Data Source & Traceability / 数据源与可追溯性 | 说明本期结论的数据来源、查询口径、拉取时间与责任人，确保结果可追溯。 |
| Growth / 增长 | 观察新注册、新订阅及转化变化，判断获客与新增增长是否健康。 |
| Retention / 留存 | 观察存量客户留存与流失情况，识别主要流失场景及可干预原因。 |
| Onboarding / 激活 | 观察新注册或新订阅商家从初始设置到首次获得业务价值的效率，定位激活过程中的阻塞环节。 |
| Product Usage / 产品使用 | 观察核心功能使用量与覆盖率变化，判断商家是否持续采用关键工作流。 |
| Customer Feedback & FR | 汇总本期用户反馈与功能诉求，识别高频问题、重复需求与优先关注的产品机会。 |
| Bug Tickets / 缺陷工单 | 跟踪本期缺陷数量、严重程度与处理状态，识别需要优先解决的质量风险。 |
| CS Related / 客服相关 | 观察客服工单量、活跃队列与重点问题分布，判断客户支持压力和反馈闭环效率。 |
| System Loading / 系统体验 | 观察关键服务错误率、页面加载与交互性能，识别影响用户体验的系统异常。 |
| Meeting Notes / Open Questions / 会议讨论与待开放问题 | 将本期异常、影响和建议动作转化为会议讨论、决策与后续责任人。 |

## 文档开头与总览

- 飞书页面标题承载报告名称和周期；正文直接从 `Overall Summary / 总览` 开始。
- 不在正文重复报告标题，不输出“目标”“生成时间”或“文档初稿”等生成过程说明块。
- `Overall Summary` 固定写 3–5 条结论式短句；先说变化、风险或决策结论，再给关键数字支撑，不复述 Data / Insight / Team attention 表格。
- `Overall Summary` 中的 Customer Feedback 结论必须总结最高频反馈主题、用户反复提到的具体功能/工作流，以及需要团队关注的分流或动作；不要用四源总数、来源占比或渠道分布代替反馈内容。来源计数和 coverage 留在 `Customer Feedback & FR` 的 Data 表。
- 每条只突出 1–2 个最重要的数字、变化或判断。使用 `emphasis` 显式配置颜色；负向变化/风险优先 `red` 或 `orange`，正向改善优先 `green`，中性重点优先 `blue`。不要整句着色。
- 兼容纯字符串总览；字符串以 `结论标签：正文` 开头时，渲染器自动把冒号前标签加粗并标蓝。新 evidence 优先使用结构化写法。

推荐 evidence：

```json
{
  "overall_summary": [
    {
      "conclusion": "新增注册较上一双周下降 9.3%，增长端承压。",
      "emphasis": [
        {"text": "下降 9.3%", "color": "red"},
        {"text": "增长端承压", "color": "orange"}
      ]
    }
  ]
}
```

## 模块固定写法

每个业务模块先给 `Data / Insight / Team attention`，再放详细指标、截图和风险。不要只罗列 dashboard 数字。

| 字段 | 写法 |
|---|---|
| Data | 已确认的数据事实，包含周期、分母/范围、来源口径 |
| Insight | 基于本期变化做出的业务解读、异常解释或趋势判断 |
| 客户原话 example（匿名） | 仅用于 Customer Feedback & FR、Bug Tickets；展示短的匿名原话或明确标注的匿名转述，并在案例下方附可点击出处 |
| Team attention | 建议团队讨论、决策、跟进或 owner 关注的动作 |

如果某项数据只是 PNG 展示或人工口径，直接在 Data 写清 `visual_only` / `manual`，不要把它放到最后的 Open Questions。

## 章节输入与输出

| 章节 | 主要输入 | 输出内容 |
|---|---|---|
| Overall Summary | 各模块已确认的关键变化 | 直接给出本期最重要的 3–5 个结论、风险或待决策点，并用颜色突出关键数字与判断 |
| Data Source & Traceability | 源文档 Data source 表、各系统链接、owner | 数据源清单、owner、取数方式、缺口 |
| Growth | Tableau Growth/Monthly/Weekly views | ARR、new logo、new signup、new upgrade、signup-to-upgrade 变化 |
| Retention | Tableau ChurnLogos / retention views | GRR/NRR、churn 分层、business type split、脱敏后的直接 churn reason 明细 |
| Onboarding | PostHog dashboard 546845 的 `dailyMetricsUpload` 或相关 insight | 优先展示 Days to first value、Go-live rate、关键功能首次使用率；仅当这些真实字段不可用且只剩 setup/churn/Jira 线索时标为 proxy-only |
| Product usage | PostHog dashboard/insight | 核心使用行为趋势，异常增长/下降；PostHog 金额字段只能作 telemetry proxy |
| Customer Feedback & FR | Community FR、Quick-win Canny、Intercom feedback、Jira Grooming CS（Jira 仅用于正式追踪和 owner/status 口径） | 先 Summary / Insight，再 Data；Insight 表独立展示匿名客户表达与出处链接；按主题合并四源信号，展示 source coverage |
| Bug tickets | Jira（默认 source of truth）、Bug review doc / QA Dashboard 历史参考 | Bug/CS 趋势、Bug Top、SLA breach、重点 issue；Insight 表独立展示匿名客户表达与出处链接 |
| CS related | Jira、业务目标、QA Dashboard / Feature Request Board 历史参考 | OB bug/FR 追踪目标与本期进展；NPS official 仅作人工项 |
| System loading | Datadog dashboard `bk2-7s3-xqq` | error/latency/loading 是否异常，证据与影响范围 |
| Meeting notes | 本期已确认指标、人工补充或上期 action items | 异常解读、建议动作、决策和 owner |

`Data Source & Traceability` 的发布表只展示 `标题`、`查询 / 过滤条件`、`拉取时间`、`Owner` 四列，并排除 `source_type=manual_policy` 的内部人工口径行。`拉取时间` 统一转换为北京时间并展示为 `YYYY-MM-DD HH:MM`。`source_id`、`source_type` 和 manual policy 继续保留在 evidence pack 中供指标关联与校验使用，但不在面向 PM 的文档里展示。

`Data Source & Traceability` 固定放在全文最后，位于 `Meeting Notes / Open Questions` 之后，作为审计与复核附录，不打断业务数据、洞察和行动讨论的主阅读路径。

## Retention / Churn Reason 写法

Churn reason 是直接展示脱敏 reason，不再把重点写成 reason 分类质量判断。

推荐表格：

| Date | Segment / Business Type | Tier | Churn reason |
|---|---|---|---|
| 2026-06-xx | Mobile / Salon / Other | T1-T4 或 unknown | 脱敏后的简短 reason 文本 |

要求：

- 可展示 direct churn reason，但不得包含邮箱、客户名、公司名、Company ID、Intercom 原文长文本或其它可识别客户身份的信息。
- reason 原文过长时，压缩成短句；保留业务含义，不补造分类。
- 死亡、疾病、家庭变故等个人敏感事件改写成低敏业务原因，不展示原文。
- 不输出 reason 分类质量、缺失比例或采集质量作为正文结论。
- 若确实没有 reason，只在对应行写 `No reason captured` 或中文等价描述，不把它扩展成数据质量 headline。

## Customer Feedback & FR 写法

本章节不是 Jira feedback 的补充说明，而是把四个反馈/FR 来源合并成一个栏目：

| 来源 | 作用 |
|---|---|
| Jira Grooming CS | 正式追踪来源，用于 owner/status/priority 和正式需求归档 |
| Community FR | 社区长期诉求，用日期和 Business Type 过滤到本期 Grooming/Both |
| Quick-win Canny | 当前快赢池快照，用于判断可快速交付、accepted、needs-discovery、backlog |
| Intercom feedback | 日常 support pain，用 Grooming squad/domain 过滤，不展示 raw quote |

固定输出顺序：

1. `Summary`：3-5 条已确认的主题结论。
2. `Insight`：固定五列表格 `主题 / 数据 / 洞察 / 客户原话 example（匿名） / 团队关注`；案例不能写进“洞察”单元格。
3. `Data`：主题聚合表和 source coverage，放在本章节最后。

要求：

- 不展示邮箱、客户名、conversation id、未脱敏原始长文本或其它可识别客户身份的信息。
- 每条 Insight 至少提供一个 `customer_examples[]` 案例。优先使用脱敏后的短原话；无法安全直接引用时用 `anonymized_paraphrase` 并在正文标记“匿名转述”。每个案例至少带一个原始 Jira、Slack、Canny、Intercom 或其它记录链接，不得补造案例或出处。
- 不把 Quick-win Canny 写成自然月计数；它是当前视图快照。
- 未归类信号只作为 triage backlog，不作为 headline。
- Bug-only 细节留在 `Bug Tickets`，Customer Feedback & FR 只承接反馈、需求和 support pain 聚合。
- 四源未全部拉到时不要发布完整 Customer Feedback & FR；先补拉或进入生成前确认。只有用户明确要求只看 CS ticket / Jira-only 范围时，才按 Jira-only 表输出，并在 source coverage 写明本次覆盖不是完整四源口径。
- 主题表必须数值自洽：每行 `总信号数 = Community FR + Quick-win Canny + Intercom feedback + Jira Grooming CS`；各来源列合计必须等于 source coverage 的使用信号数；未归入 headline 的低量信号用 `Other / Triage backlog` 行承接，不要让摘要总数、主题表总数和来源覆盖互相打架。

## 默认业务目标呈现方式

- `Grooming only NPS back to 80`：作为 CS related 的业务追踪目标。
- `OB: bug 20/month -> 5/month in 2026 H1`：作为 Bug/CS 质量目标。
- `Solve Team management / Service FR in 2026 H2`：作为 Feature Request 目标。

这些目标不能写成 Agent 已经达成；只能写“本期进展 / 风险 / 待确认”。

## 必须保留的边界

- 不做开放式 BI 问答。
- 不替代 Tableau/PostHog/Datadog dashboard。
- 不自动 root cause 或自动分派 owner。
- 不用截图中的数字替代可查询的结构化数据；截图只作为展示或辅助证据。
- 不把第二篇源文档中的账号密码复制到任何输出。
