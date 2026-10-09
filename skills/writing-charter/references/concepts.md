# 核心概念定义

写作和评审都以本文件为准，避免同一个词在不同文档里代表不同意思。

## Opportunity

**定义**：一类 customer 的 desire 或 fear，如果被解决，会带来业务 outcome。

**要求**：必须是 problem-shaped，只描述问题空间，不预设解决方案。

**三要素**：
1. Customer class：一类人，具体到能想象出一个人。
2. Desire or fear：一个需求或一个痛点，命名为一个。
3. Business outcome：如果解决，公司获得什么。

**Solved well bar**：不含 solution、客户可验证的证明标准。即使不知道方案，也能判断问题是否被解决。

## Output vs Outcome

**Output**：项目直接交付的产物或变化，团队能完全控制。

- 示例：文档发布、平台接入、工作流建立。
- 判定：团队做完，这个东西就一定存在吗？是则为 Output。

**Outcome**：Output 引发的业务变化，团队只能试图引发，不能完全控制。

- 示例：答疑成本下降、激活率提升、上手时间缩短。
- 判定：交付 Output 后，这个结果一定发生吗？不一定则为 Outcome。

**在立项文档中**：Objectives 写 Outcome，Scope 写 Output。

## Risk vs Uncertainty

**Risk**：能枚举具体失败模式，能评估概率和影响。

- 应对：列出失败模式，写概率、影响、缓解动作。

**Uncertainty**：无法枚举具体失败模式，只知道有未知。

- 应对：控制爆炸半径、保留回退路径、加速学习。

**判定**：能列出具体会怎么失败，是 Risk；列不出来，是 Uncertainty。

**Pre-Mortem**：在填 Risk Register 之前做——假设项目 3 个月后失败了，"什么导致了失败？"。反转正面规划的乐观偏差，暴露团队不愿主动提出的风险。

## Quality Standards（验收标准）

**定义**：对 Scope 中每个 Output，"做对了"长什么样。

- 在 Charter 中定义验收标准，而非事后再补。
- Quality Standards 关注的是 Output 的正确性，与 Objective 关注的 Outcome 是不同层面。
- Charter-only 模式下可以简要描述；Full Initiation 模式下需要结构化的验收标准表。

## Stakeholder vs 项目成员 vs 受益人

| 概念 | 定义 | 管理方式 |
|------|------|----------|
| 项目成员 | 做事的人 | RACI、任务分配 |
| Stakeholder | 项目外能影响或被影响的人 | Communication Plan |
| 受益人 | 从成果中获益的人 | 目标和验收视角 |

**关键点**：Stakeholder 的关键子集是能阻止项目的人，他们不一定是受益人。

## Product Scope vs Project Scope

| 类型 | 回答什么 | 在哪里定义 |
|------|----------|------------|
| Product scope | 最终交付什么结果面 | Charter / Initiation |
| Project scope | 需要做哪些工作 | Planning / WBS |

Charter 中应写 product scope。若写成任务清单，说明把 scope 写成了 plan。

## SMART

检验目标质量的技术手段，**分布式实现在多个章节中**，不是要求每条 Objective 都塞满五个维度：

| 字母 | 含义 | 由哪个章节承担 |
|------|------|----------------|
| S | Specific | Opportunity 的 "Solved well" / 受益人表 |
| M | Measurable | 执行计划中的 KPIs 表 |
| A | Achievable | Budget & Timeline 隐含 |
| R | Relevant | Opportunity 的 Business outcome |
| T | Time-bound | "项目结束时：" + Timeline envelope |

Objective 章节本身只需声明 Outcome（项目结束时世界变成什么样）。

## Why Now

Why Now 回答的是“为什么现在不能等”，不是“为什么这件事重要”。

必须同时回答：
1. 现在不做会发生什么恶化或损失。
2. 现在做有什么窗口、锚点或成本优势。

## Charter-only vs Full Initiation

| 模式 | 用途 | 必备内容 |
|------|------|----------|
| Charter-only | 投资论证、方向确认 | Why、目标、边界、授权、风险 |
| Charter + Solution | 方案已明确，一步到位产出完整立项文档 | Charter-only 全部内容 + Solution 章节（方案概述、Dependencies） |
| Full Initiation | 可直接进入项目治理 | 在 Charter（± Solution）基础上补里程碑、RACI、依赖、change control、acceptance、closing 口径 |

## Charter → Solution → SPEC 的关系

| 文档 | 回答什么 | 粒度 |
|------|----------|------|
| Charter | 值不值得做 | 投资论证 |
| Solution | 怎么解决 | 方案概述 + 选型 |
| SPEC | 怎么实现 | 详细技术设计 |

Solution 是 Charter 的可选补充——当方案已明确时可一并纳入（Charter + Solution 模式），但 Charter 部分必须能独立成立，不依赖 Solution 才能理解 why、what、who。
