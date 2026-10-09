# Jira 采集与发布协议

## 数据源与团队配置

- 项目：`CS`。
- 团队字段：`cf[10089]`（Squad）。
- 运行实例只配置 `MFC_SQUAD`，例如 `MFC_SQUAD=Grooming`。
- 唯一数据通道：`<jira-skill>/scripts/jira.py search`；Collector 不直接请求 Jira
  HTTP，也不读取或复制 Jira 凭据。

`MFC_SQUAD` 同时供 Intercom 发布和 Jira 报表身份、范围强信号使用。没有旧变量兼容逻辑；环境、
CWD `.env`、skill `.env` 按键是否存在分层覆盖，显式空值会禁用依赖 Squad 的流程。

## 周期与查询

默认周期为上一个完整自然周，也可显式传入恰好 7 天：

```bash
uv run --script scripts/moe_feedback_collector.py collect \
  --source jira --mode period \
  --period-start 2026-08-17 --period-end 2026-08-23
```

Jira 裸日期按调用账号时区解释。Collector 将 JQL 窗口前后各扩一天，完整分页后再把
`created` 转为 `Asia/Shanghai`，按 `[周一 00:00, 下周一 00:00)` 精确过滤。这样既不
依赖 Jira 账号时区，也不会把扩窗数据写入 evidence。

请求字段固定为：

```text
summary, status, created, issuetype, issuelinks, components, customfield_10089
```

Collector 必须校验 Jira schema v1 envelope 的 `command / jql / fields` 与本次请求完全
一致。每页 100 条，沿 `next_page_token` 读取到 `is_last=true`；缺 token、token 循环、
重复 issue key、终页仍有 token 或超过 10000 条都使整次采集失败。

## 入选口径

先建立反馈候选：

```text
project = CS
AND 当周新建
AND (
  源工单 Issue Type = Feature Request
  OR 关联目标 project_key = DES 且 issue_type = Design Issue
)
```

不要在 JQL 中预先限定 Squad，否则 BD、Communication、FinTech 等公共域承接的
Grooming Customer 问题会在范围判定前丢失。

候选进入第二层 Grooming Customer 范围判定：

- 强证据：Squad 与 `MFC_SQUAD=Grooming` 忽略大小写精确匹配；或 Summary 明确出现
  `Grooming / groomer / groomers / groomer's`。任一命中即可确认纳入。
- 弱证据：Appointment、Booking、Calendar、Client/Pet/Leads、Communication、Payment、
  Payroll、Staff、Shift、Van 等公共 Component。只有弱证据时进入人工复核，不计入确认反馈。
- 排除：没有强证据且 Summary 明确属于 Daycare、Boarding、Kennel 或 Training；或者既无
  强证据也无公共 Component 弱证据。

范围判定与反馈候选门槛不可混用：Grooming 关键词不能把普通 Bug 自动变成反馈；Squad
或 Component 也不能替代 Feature Request / DES Design Issue 合同。

同一 CS 工单同时满足两类时只落一条 evidence，并在 `feedbackKinds` 同时记录
`feature_request / design_linked`。发布时可在两个分类章节分别出现，但概览的入选总数
按 CS key 去重。

不要使用 Summary 关键词、`link_count > 0` 或只判断 `issueLinkType=Defect`。DM、GRM
等项目也可能使用同一关联类型；目标项目和目标 Issue Type 必须同时匹配。

## Evidence 与隐私

确认纳入的 Jira evidence 只保留：

```text
sourceObjectId, sourceUrl, createdAt, title, squad, issueType, status,
components, feedbackKinds, scopeDecision, scopeReasons, businessCategory,
auxiliaryCategories, classificationConfidence, relatedTickets
```

每条确认项默认一个主分类，优先级为：van-staff-shift-management → payment →
communication → fulfillment → scheduling → management → others。同一条命中多个维度时，
最高优先级写入 `businessCategory`，其余写入 `auxiliaryCategories`；没有可靠分类信号时进入
`others` 且置信度为 low。分类词按完整英文词或短语匹配，禁止 `advance / context / multiple`
分别误命中 `van / text / tip`。范围为弱证据的候选保存在 `reportRows`，只出现在“待人工复核”
章节；明确排除的候选也保存在 `reportRows`，出现在“范围排除审计”章节。两者都不进入
evidence、总看板信号数或六类确认统计。若 Grooming Squad 或 Grooming/groomer 语义与
Daycare、Boarding 等明确非 Grooming 服务冲突，必须进入人工复核，不能自动纳入。

`relatedTickets` 只保留入选的 DES Design Issue 的 key、状态、关系方向、Link Type 和
URL。禁止请求或落盘 description、comments、attachments、reporter、客户邮箱和
Intercom 会话；Summary 中意外出现的邮箱统一替换为 `[EMAIL]`。

Jira 是周期快照，不创建 `state/jira.json`。Manifest 固定记录 Squad、精确 JQL、字段
投影、扩窗返回数、周期内数量、反馈候选、确认入选、人工复核、范围排除和规则版本
`jira-grooming-journey-v2`。发布时
当前 `MFC_SQUAD` 必须与 manifest Squad 一致，防止跨团队误发。

## 飞书发布

先执行 dry-run：

```bash
uv run --script scripts/moe_feedback_collector.py publish \
  --source jira --manifest <manifest.json> --dry-run
```

周报标题格式：

```text
2026-W34｜08.17–08.23｜Jira CS 反馈｜Grooming
```

正文包含本周概览、功能需求（Feature Request）、关联设计单反馈、待人工复核和范围排除审计。
概览同时展示确认入选、人工复核和范围排除计数。入选数据超过 50 条
时按分类拆为自动子文档；缩量重跑只把带 Collector 标记的旧子文档覆盖为失效提示，
不删除页面或修改人工文档。
