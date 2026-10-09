# Grooming Quick Win 来源规则

只有需求可精确定位到 `Grooming - Product Roadmap` 的 Quick Win 表格行时加载本规则。普通 Owner 候选、其它 Grooming 来源和一般小改动均不匹配。

## JIT 执行参数

在读取或写回来源时解析唯一 Sheet/Row、Owner、目标指标、约束和 Quick Win 适用范围。来源行是当前动作参数，不是阶段开工资格；没有该来源只表示不使用 Quick Win 特例。

## 标准动作

1. 通过 `$jira` 用需求语义和来源 identity 查重，已有 Story 优先 update/skip/reconcile。
2. 按当前用户范围形成或更新 Jira PRD；执行中若出现无法由来源确定、且会改变 Scope/Solution/权限/平台/发布策略的新选择，只问一个问题。其它未知项如实记录。
3. Jira 写入保留原生 ADF 的标题、列表、引用、表格、链接和行内样式，并做结构化与真实渲染回读。
4. 有截图时通过 `$jira` 上传，保存稳定 attachment identity 和尺寸映射，不保存临时 URL。
5. 通过 `$lark-skills` 精确回写 Roadmap 原行的 Ticket、Module、Dependencies、Status、Note 并逐格回读。
6. Context/PRD 保留来源，但仍以真实用户问题、当前实现和 AC 为准。
7. 来源失效或需求范围扩大时停止使用 Quick Win 标签；不因此阻止当前显式阶段。

## 结果与回读

- 稳定 source URL、Sheet/Row 和同步时间可回读。
- Jira Story 唯一，ADF/附件/渲染正确；Roadmap 五类单元格与预期一致。
- 普通候选不会因为规模小而误用本规则。
