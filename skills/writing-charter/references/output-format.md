# 输出格式参照

本文件定义 Charter 文档的最终输出格式。Step 6 Draft 时按此格式组织文档。

## 格式规则

1. 第一行是项目名称，第二行是 blockquote 元信息（`> 项目章程 | Owner: X | Sponsor: Y`）+ `---` 分隔线
2. "受益人" 表格列头：`受益人 | 需要什么 | 当前差距`
3. Why Now 用编号列表或短段落，不用两列表格
4. SMART Objective 用 "项目结束时：" + 编号列表
5. In Scope 用表格（`施工面 | 类型` 或 `受益人 | 施工面 | 类型`）
6. Out / Deferred 用列表
7. Stakeholder 分两个子节：`### Power / Interest`（2×2 矩阵）+ `### Resources`（角色/人/职责）
8. "执行计划" 是独立顶级章节，包含 Budget 表 + Schedule 表 + Risk Register 表 + Communication Plan 表 + 可选 Dependencies 表 + 可选 KPIs 表
9. Budget 用明细表（`项目 | 费用 | 说明`），不只写 ceiling
10. Schedule 用分阶段表（`阶段 | 内容 | 时间 | 主力`）
11. Solution 作为可选顶级章节出现在 Stakeholder 之后、执行计划之前

## Charter-only 输出格式

```markdown
# [项目名称]

> 项目章程 | Owner: [ProjM] | Sponsor: [Sponsor]
---

## Business Case

### 受益人与未满足需求

| 受益人 | 需要什么 | 当前差距 |
|--------|----------|----------|
| **[一类人 1]** | [desire or fear] | [具体观察，不是抽象结论] |
| **[一类人 2]** | [desire or fear] | [具体观察] |

### 为什么现在做

1. [恶化趋势 — 不做会发生什么]
2. [窗口 — 当前有什么条件使得现在适合做]

## SMART Objective

项目结束时：
1. **[Outcome 名称]** — [受益人可感知的变化描述]
2. **[Outcome 名称]** — [描述]

## High-Level Scope

**In**：

| 施工面 | 类型 |
|--------|------|
| [产物/变化 1] | 新增 |
| [产物/变化 2] | 变更 |

**Out**：
- [显式排除 1]
- [显式排除 2]

**Deferred**：
- [重要但不是这期 1]

## Stakeholder

### Power / Interest

|  | Low Interest | High Interest |
|--|--|--|
| **High Power** | — | [Sponsor、关键决策者] |
| **Low Power** | — | [受益人、潜在用户] |

### Resources

| 角色 | 人 | 职责 |
|------|-----|------|
| Owner | [姓名] | [职责] |
| Sponsor | [姓名] | [职责] |
| [其他] | [姓名] | [职责] |

## 执行计划

### Budget

| 项目 | 费用 | 说明 |
|------|------|------|
| [项目 1] | [金额或"工程时间"] | [补充] |
| [项目 2] | [金额] | [补充] |

### Schedule

| 阶段 | 内容 | 时间 | 主力 |
|------|------|------|------|
| **Phase 1** | [内容] | [时间] | [人] |
| **Phase 2** | [内容] | [时间] | [人] |

### Risk Register

| 风险 | 可能性 | 影响 | 应对 |
|------|--------|------|------|
| [风险 1] | 高/中/低 | 高/中/低 | [具体策略] |
| [风险 2] | 高/中/低 | 高/中/低 | [具体策略] |

### Communication Plan

| 时间点 | 对谁 | 沟通什么 | 方式 |
|--------|------|----------|------|
| [节点 1] | [对象] | [内容] | [渠道] |
| [节点 2] | [对象] | [内容] | [渠道] |

可选渠道：Slack 频道通知 / Slack DM / 1:1 会议 / 团队周会 / All-Hands / 飞书文档 / 书面报告 / PR Review
```

## Charter + Solution 输出格式

在 Stakeholder 和执行计划之间插入 Solution 章节：

```markdown
## Solution

### [组织维度：按技术层 / 按受益人 / 按架构分层]

[方案描述]

### Acceptance Criteria

1. [一句话验收条件 — 具体场景 + 预期结果]
2. [一句话验收条件]

### Dependencies

| 依赖 | 状态 | 说明 |
|------|------|------|
| [依赖 1] | ✅ 就绪 | [说明] |
| [依赖 2] | 🔄 并行 | [说明] |
| [依赖 3] | ⏳ 待定 | [说明] |
```

执行计划中可额外包含：

```markdown
### KPIs

| 指标 | 说明 |
|------|------|
| [指标 1] | [用途] |
| [指标 2] | [用途] |
```

## 多受益人 In Scope 变体

当受益人维度对范围理解至关重要时：

```markdown
| 受益人 | 施工面 | 类型 |
|--------|--------|------|
| [受益人 1] | [产物/变化] | 新增 |
| [受益人 2] | [产物/变化] | 变更 |
```

## 单受益人 Business Case 变体

当只有一个受益人时，可用四行声明替代表格：

```markdown
### 受益人与未满足需求

Customer class:   [一类人]
Desire or fear:   [desire | fear] — [描述]
Business outcome: [公司获得什么]
"Solved well":    [不含 solution 的验收标准]
```
