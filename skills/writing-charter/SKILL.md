---
name: writing-charter
description: 撰写或完善项目章程、立项书与启动文档，并判断想法是否适合立项。
metadata:
  version: 1.2.0
---

# 项目立项写作

把立项文档写成一份可争取资源、可建立共识、可指导后续执行的文档，而不是只把背景和计划堆在一起。

## 先读什么

开始前先读这些 references，并以其中定义为准：

- [references/concepts.md](references/concepts.md)
- [references/project-initiation-checklist.md](references/project-initiation-checklist.md)
- [references/five-optimization-rules.md](references/five-optimization-rules.md)
- [references/output-format.md](references/output-format.md)

按需再读：

- Opportunity 不清楚：`references/opportunity-guide.md`
- 目标不清楚：`references/smart-objectives-guide.md`
- 范围不清楚：`references/scope-boundary-guide.md`
- 授权和沟通不清楚：`references/stakeholder-guide.md`
- 提问卡住：`references/clarification-prompts.md`

## 核心边界

- 先判断值不值得立项，再写文档。
- Charter 部分必须能独立成立——不依赖 Solution 才能理解 why、what、who。
- Solution 是可选补充：当方案已明确时可一并纳入，但不是 Charter 的必要组成。
- 目标写 Outcome，范围写 Output。
- 如果用户给的是已有文档，先诊断缺口，再重写，不做表面润色。

## 输出模式

| Mode | 适用场景 | 模板 |
|------|----------|------|
| Charter-only | 需要投资论证、方向确认、sponsor 初步 buy-in | [references/charter-template.md](references/charter-template.md) |
| Charter + Solution | 方案已明确，需要一步到位产出完整立项文档 | [references/charter-template.md](references/charter-template.md)（含 §6） |
| Full Initiation | 已明确要进入项目级推进，需补治理、节奏、验收、收尾口径 | [references/full-initiation-template.md](references/full-initiation-template.md) |

## 流程

### Step 1: Qualify

**输入**：用户需求、已有文档、背景材料。

**操作**：

1. 对照 `references/project-initiation-checklist.md` 判断这是否已经是项目级事项。
2. 判断输出模式：
   - 用户只有想法/问题 → `Charter-only`
   - 用户已有明确方案或技术选型 → `Charter + Solution`
   - 已经要进入正式治理 → `Full Initiation`
3. 如果还不到项目级，明确建议降级为轻量方案、PRD、执行计划或周会提案。
4. 判断受益人数量，决定使用四行声明还是受益人表格格式。

**输出**：文档级别判断 + 推荐输出模式 + 格式选择。

### Step 2: Gather

**输入**：已确认要写的项目。

**操作**：

1. 提取现有信息，标记已知、可推断、必须追问。
2. 优先追问根基性缺失：Opportunity、Why Now、边界、授权、验收。
3. 使用 `references/clarification-prompts.md`，一次只问最影响成文质量的一组问题。
4. 如果用户提供了方案/技术材料，标记为 Solution 素材，暂不混入 Charter 部分。

**输出**：已确认信息清单 + 待澄清问题。

### Step 3: Shape The Why

**输入**：Step 2 的信息。

**操作**：

1. 用 `references/opportunity-guide.md` 塑形成 Opportunity。
   - 多受益人：用表格（受益人/需要什么/当前差距），每行独立通过三要素测试。
   - 单受益人：用四行声明（customer class / desire or fear / business outcome / solved well）。
2. 补 Supporting Observations，确保引用的是观察，不是结论。
3. 强制拆开 `Why Doing` 和 `Why Now`。
4. 定义不含 solution 的验收画面。

**输出**：Business Case（Opportunity + Evidence + Why Now）。

### Step 4: Define Success And Boundaries

**输入**：Step 3 的结果。

**操作**：

1. 用 `references/smart-objectives-guide.md` 把验收画面变成 Outcome 声明（注意：Objective 只写 Outcome，不塞度量指标和 deadline）。
2. 用 `references/scope-boundary-guide.md` 写 Scope：
   - In Scope 用表格（受益人/施工面/类型）或列表。
   - Out 和 Deferred 用列表，每条可独立判定。
3. 若是 `Full Initiation`，继续补质量标准、RACI、里程碑、依赖、change control、final acceptance 和 closing 口径。

**输出**：目标、范围，以及所需的治理补充项。

### Step 5: Define Authority And Risk

**输入**：Step 3-4 的结果。

**操作**：

1. 用 `references/stakeholder-guide.md` 明确：
   - Power/Interest 矩阵
   - Resources 角色表（Sponsor、Owner/ProjM、关键角色）
   - Communication Plan（时间点/对谁/沟通什么/方式）
   - Budget ceiling、Timeline envelope
2. 区分 Risk 和 Uncertainty，并写出应对策略。
3. 若是 `Full Initiation`，补关键资源、依赖、验收、收尾责任。

**输出**：授权约束、沟通安排、风险与不确定性。

### Step 6: Draft

**输入**：Step 3-5 的全部结果。

**操作**：

1. 按 `references/output-format.md` 的格式规则组织文档（不编号顶级标题、执行计划打包、表格驱动等）。
2. 采用 `references/recommended-structure.md` 的阅读顺序。
3. 把 checklist 信息嵌入叙事，而不是写成术语堆砌。
4. **如果是 Charter + Solution 模式**：
   - Solution 章节放在 Stakeholder 之后、执行计划之前。
   - Solution 必须回应 Charter：方案解决 Business Case 的问题、覆盖 In Scope、支撑 Objective 的可度量性。
   - Dependencies 放在 Solution 内。
5. **如果用户提供了方案材料但选择 Charter-only**：在文末"下一步"中提示 Solution 待补。

**输出**：初稿。

### Step 7: Strengthen And Deliver

**输入**：初稿。

**操作**：

1. 用 `references/five-optimization-rules.md` 重写表达，提升 sponsor 可判断性和团队可执行性。
2. 用 charter-template.md 中的交付检查清单自检，缺口显式标注 `待确认`，不要脑补。
3. 交付最终文档，并列出仍需用户拍板的事项。
4. 如果文档用于 KO / sign-off，额外列出会上必须确认的事项。

**输出**：最终文档 + 待拍板项 + 下一步建议。

## 交付要求

- 如果只是 Charter-only，明确告诉用户：Solution 仍需后续补充——但 Charter 已经足以争取 sponsor 初步认可。
- 如果是 Charter + Solution，提示用户：如果技术复杂度高，建议转 `writing-spec` 进一步细化。
- 提醒用户设定 **Benefits Realization 检查点**：Outcome 通常在交付后数周才显现，需要提前约定"谁来度量、什么时候看、不达标怎么办"。

## 参考资料

- [references/concepts.md](references/concepts.md)
- [references/output-format.md](references/output-format.md)
- [references/opportunity-guide.md](references/opportunity-guide.md)
- [references/smart-objectives-guide.md](references/smart-objectives-guide.md)
- [references/scope-boundary-guide.md](references/scope-boundary-guide.md)
- [references/stakeholder-guide.md](references/stakeholder-guide.md)
- [references/project-initiation-checklist.md](references/project-initiation-checklist.md)
- [references/five-optimization-rules.md](references/five-optimization-rules.md)
- [references/clarification-prompts.md](references/clarification-prompts.md)
- [references/recommended-structure.md](references/recommended-structure.md)
- [references/charter-template.md](references/charter-template.md)
- [references/full-initiation-template.md](references/full-initiation-template.md)
