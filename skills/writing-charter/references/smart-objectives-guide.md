# Objective 编写指南

## 章节职责

Objective 章节的唯一职责是**声明 Outcome**——"项目结束时世界变成什么样了"。

它不承载度量指标、不承载目标值、不承载截止时间。这些信息由其他章节分担。

## SMART 是分布式实现的

SMART 是检验目标质量的技术手段，不是要求每条目标都塞满五个维度的格式模板。

| SMART 要素 | 由哪个章节/结构承担 | 不应该出现在 |
|------------|---------------------|-------------|
| S — Specific | Opportunity 的 "Solved well" / 受益人表的"当前差距" | — |
| M — Measurable | 执行计划中的 KPIs 表 | Objective 正文 |
| A — Achievable | Budget & Timeline 隐含 | Objective 正文 |
| R — Relevant | Opportunity 的 Business outcome | — |
| T — Time-bound | "项目结束时：" 开头 + Timeline envelope | Objective 每条后面 |

## 写法

```markdown
## SMART Objective

项目结束时：
1. **[Outcome 名称]** — [用受益人能感受到的话描述变化]
2. **[Outcome 名称]** — [描述]
3. **[Outcome 名称]** — [描述]
```

每条 Objective 回答一个问题："项目成功后，谁的什么行为/体验/状态发生了什么变化？"

## Output vs Outcome

| 概念 | 定义 | 特征 | 示例 |
|------|------|------|------|
| Output | 项目直接交付的产物 | 我们能完全控制 | "部署翻译管理平台" |
| Outcome | 产出物带来的业务结果 | 我们只能试图引发 | "非英语客户的激活率不因语言折损" |

**规则**：Objective 写 Outcome，Scope 写 Output。

## 好的 Objective 示例

✅ 正确：

```
项目结束时：
1. **试点需求全程无翻译环节** — 各角色直接表达意图并看到结果落地，不再有"做完交给别人重做"的环节
2. **需求交付效率显著提升** — Mobile UI 组件从意图到代码合入的周期大幅缩短
3. **流程自然被采纳且可复制** — 参与者因为"更容易"而使用新流程，非试点团队能独立采用
```

✅ 正确：

```
项目结束时：
1. **EPD 每个人有 state of the art AI for coding with enough quota**
2. **每个 Agent 有稳定的程序化 token 通道，与个人解耦，成本可归因**
3. **上线首月，月度总成本预期 $8,000–13,000 且有明确 Owner 负责渠道稳定运行**
```

## 常见错误

### 错误 1：把 KPI 当 Objective

❌

| 目标 | Metric | Target | Deadline |
|------|--------|--------|----------|
| 返工率下降 | 返工次数 | ≤0.5 次/需求 | T+8 周 |

这是 KPI 表，不是 Objective。度量指标和目标值属于执行计划中的 KPIs 章节。

### 错误 2：在 Objective 里塞"追踪/衡量"

❌ "试点需求全程无翻译环节 — ...追踪：跨角色翻译交接次数"

"追踪什么指标"是 KPIs 的职责，不是 Objective 的职责。

### 错误 3：在每条后面重复写 Deadline

❌ "需求交付效率显著提升（T+8 周）"

"项目结束时：" 这句话本身就是 deadline。Timeline envelope 在 Budget & Timeline 中已经声明。不需要每条重复。

### 错误 4：写 Output 而非 Outcome

❌ "部署 Sub2API 网关" — 这是交付物（Output），属于 Scope

✅ "每个 Agent 有稳定的程序化 token 通道" — 这是交付后的状态变化（Outcome）

## Objective 与 KPIs 的关系

| | Objective | KPIs |
|--|-----------|------|
| 回答什么 | 世界变成什么样了 | 怎么证明变成了那样 |
| 位置 | 顶级章节 | 执行计划内 |
| 格式 | 编号列表，每条一句话 | 表格（指标/说明/Leading or Lagging） |
| 数字 | 通常不需要（除非数字本身就是 Outcome 描述的自然组成部分） | 必须有 |

Objective 先写。KPIs 从 Objective 推导——"要证明这个 Outcome 发生了，需要看什么数字？"

## 多个 Objective 的关系

一个 Charter 可以有多个 Objective，但它们必须：
1. 全部追溯到同一个 Opportunity（同一群受益人的同一个问题）
2. 彼此不矛盾
3. 共同描绘 "solved well" 的完整画面

如果 Objective 追溯到不同的 Opportunity → 拆成两个项目。

## 何时可以在 Objective 中出现数字

当数字本身就是 Outcome 描述的自然组成部分时，可以出现：

- ✅ "月度总成本预期 $8,000–13,000" — 成本控制本身就是 Outcome
- ✅ "≥3 个 agent 成功 adopt" — adopt 数量就是 Outcome 的定义
- ❌ "返工次数 ≤0.5 次/需求" — 这是 KPI 的度量格式，不是 Outcome 声明
