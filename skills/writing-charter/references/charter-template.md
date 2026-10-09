# Charter 文档模板

## 模板结构

以下是 Charter 的标准章节结构。支持单受益人（四行声明）和多受益人（表格）两种形态。

---

```markdown
# [项目名称]

> Owner: [ProjM] | Sponsor: [Sponsor 姓名]
> 状态：草案 / 待审批 / 已批准
> 创建日期：YYYY-MM-DD

## Business Case（为什么要做）

### 受益人与未满足需求

<!-- 多受益人时用表格（推荐）-->

| 受益人 | 需要什么 | 当前差距 |
|--------|----------|----------|
| [一类人 1] | [desire or fear] | [现状与期望的距离] |
| [一类人 2] | [desire or fear] | [现状与期望的距离] |

<!-- 单受益人时可用四行声明 -->

Customer class:   [一类人]
Desire or fear:   [desire | fear] — [描述]
Business outcome: [公司获得什么]
"Solved well":    [不含 solution 的验收标准]

### Supporting Observations（证据）

什么证据让这个需求从"假设"变为"已验证"？引用具体观察，不只是结论。

- [证据 1：数据 / 客户反馈 / 事故记录 / 竞品动态]
- [证据 2]

### Why Now?（为什么是现在）

<!-- 用简短段落或列表，回答两个子问题 -->

1. 现在不做会发生什么？（恶化趋势）
2. 现在做的窗口是什么？（为什么当前适合做）

## SMART Objective（做到什么程度算成功）

项目结束时：
1. [Outcome 声明 1 — 受益人可感知的变化]
2. [Outcome 声明 2 — 受益人可感知的变化]

## High-Level Scope（做什么和不做什么）

### In Scope

<!-- 推荐表格格式，按受益人维度组织 -->

| 受益人 | 施工面 | 类型 |
|--------|--------|------|
| [一类人 1] | [产物/变化描述] | 新增 / 变更 |
| [一类人 2] | [产物/变化描述] | 新增 / 变更 |

<!-- 单一受益人或施工面少时，列表也可以 -->

### Out of Scope（显式排除）

- [不是我们的问题 1]
- [不是我们的问题 2]

### Deferred（重要但不是这期）

- [承认重要但不是现在 1]
- [承认重要但不是现在 2]

## Stakeholder & Authorization（谁参与、谁决定）

### Power / Interest 矩阵

|  | Low Interest | High Interest |
|--|--|--|
| **High Power** | — | [Sponsor、关键决策者] |
| **Low Power** | — | [受益人、潜在用户] |

### Resources（项目角色）

| 角色 | 人选 | 职责 |
|------|------|------|
| Sponsor | [姓名] | 审批预算、优先级背书、关键取舍拍板 |
| Owner / ProjM | [姓名] | 对目标、范围、节奏、交付质量负责 |
| [其他关键角色] | [姓名] | [职责] |

### Budget & Timeline

- **Budget ceiling**: [Sponsor 授权的资源上限]
- **Timeline envelope**: [大致时间边界，如 "Q3" 或 "6 周"]

### Communication Plan

| 时间点 | 对谁 | 沟通什么 | 方式 |
|--------|------|----------|------|
| [节点 1] | [对象] | [内容] | [渠道] |
| [节点 2] | [对象] | [内容] | [渠道] |

<!-- 公司可用沟通渠道参考：
- Slack 频道通知（#team-xxx / #engineering）
- Slack DM / 小群
- 1:1 会议（同步，适合需要拍板的对话）
- 团队周会 / All-Hands（适合广播式通知）
- 飞书文档（异步，适合需要留痕的进展同步）
- 书面报告（适合向 Sponsor 汇报数据和结论）
- PR Review / GitHub Discussion（适合技术决策同步）
-->

## Risk & Uncertainty（主要风险）

<!-- 推荐先思考 Pre-Mortem：假设项目 3 个月后失败了，"是什么导致了失败？"——用于暴露乐观偏差隐藏的风险 -->

| 风险 | 可能性 | 影响 | 应对策略 |
|------|--------|------|----------|
| [风险 1] | 高/中/低 | 高/中/低 | [策略] |
| [风险 2] | 高/中/低 | 高/中/低 | [策略] |

不确定性（无法枚举的未知）：
- [如何控制爆炸半径]
- [如何加速学习]

## Solution（可选 — 方案已明确时纳入）

<!-- 此章节可选。当方案方向已确定时纳入，否则留待 Charter 通过后再补。 -->
<!-- 如果纳入，Solution 必须回应 Charter：方案解决的是 Business Case 声明的问题，覆盖 In Scope，且上线后能验证 Objective。 -->

### 技术选型 / 方案概述

[方案描述]

### Acceptance Criteria（怎么证明东西做对了）

<!-- 用编号列表，每条一句话，直接可判定。不用表格。 -->

1. [一句话验收条件 — 具体场景 + 预期结果]
2. [一句话验收条件]
3. [一句话验收条件]

### Dependencies（依赖）

| 依赖 | 状态 | 说明 |
|------|------|------|
| [依赖 1] | ✅ 就绪 / 🔄 并行 / ⏳ 待定 | [说明] |
```

---

## 选择格式的指引

| 项目特征 | Opportunity 格式 | Scope 格式 |
|----------|-----------------|------------|
| 单一受益人、聚焦型 | 四行声明 | 列表 |
| 多受益人、平台型 | 受益人表格 | 表格（受益人/施工面/类型） |
| 不确定 | 默认用表格——更容易扩展 | 默认用表格 |

## 交付检查清单

Charter 完成后，逐项确认：

- [ ] Opportunity 通过三要素测试（customer class + desire/fear + business outcome）
- [ ] "Solved well" bar 或"当前差距"不含 solution
- [ ] Supporting Observations 引用了具体证据（非空洞结论）
- [ ] Why Now 回答了"不做会恶化"和"现在的窗口"
- [ ] Objectives 是 Outcome 声明（受益人可感知的变化），不是 KPI 表
- [ ] 明确区分了 Output（交付物）和 Outcome（业务结果）
- [ ] Scope 有 In / Out / Deferred 三部分
- [ ] Out 和 Deferred 比 In 更能防止争议
- [ ] 有明确的 Sponsor 和 Owner/ProjM
- [ ] Stakeholder 用 Power/Interest 矩阵覆盖了"项目之外能影响成败的人"
- [ ] 有 Budget ceiling 和 Timeline envelope
- [ ] Communication Plan 覆盖关键节点
- [ ] Risk 至少识别了 3 个主要风险并有应对策略
- [ ] 如含 Solution：方案回应了 Opportunity、对齐了 Scope、指标可追踪

## 章节写作要点

### Business Case 章节

- 多受益人时用表格，每行一个受益人类型
- "当前差距"列要写具体观察，不写抽象结论
- 如果你发现自己在描述技术方案 → 停，那是 Solution 不是 Business Case

### Scope 章节

- Out of Scope 和 Deferred 比 In Scope 更重要——它们防止的争议远多于 In Scope
- Scope 是 product scope（交付什么产物），不是 project scope（做哪些工作）
- In Scope 的"类型"列（新增/变更）帮助读者快速理解影响面

### Objectives 章节

- Objective 的唯一职责是声明 Outcome——"项目结束时世界变成什么样了"
- 不塞度量指标（那是 KPIs 的事）、不塞 deadline（"项目结束时："已经是 deadline）
- 写"受益人能感受到的变化"，而非"系统完成了什么部署"
- 数字只在它本身就是 Outcome 描述的自然组成部分时出现（如"月成本 ≤$13,000"）

### Stakeholder 章节

- Stakeholder ≠ 项目成员。项目成员通过 Resources 表管理，Stakeholder 通过 Communication Plan 管理
- 按 Power × Interest 分象限：Manage Closely / Keep Satisfied / Keep Informed / Monitor

### Solution 章节（可选）

- 不是独立的技术文档——必须回应 Charter 前 5 章
- 如果技术复杂度高，建议转 moe-writing-spec 进一步细化
- Dependencies 帮助 sponsor 判断外部阻塞风险
