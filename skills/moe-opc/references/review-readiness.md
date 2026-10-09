# Technical Design Review Readiness

本文件只定义 Technical Design 正文应覆盖的设计证据。它把后续 Code Review 关心的正确性、工程风险、代码库适配与验证指标前置到方案编写中，但不是 Code Review 流程，不决定 reviewer 数量、finding、优先级或 verdict；Technical Design 运行时不得调用或依赖 `review-swarm`。

## 加载时机

用户显式点名 Technical Design 后立即进入阶段。开始组织方案正文时加载本文件，用其中的指标指导内容编写；判断方案是否达到 `Implementable` 时检查适用证据是否闭合。`Exploration` 直接在正文中记录未闭合证据与 Unknown/Open Question。加载发生在执行内部，不是 Preflight，也不影响阶段能否开始。

## `Implementable` 的证据标准

方案至少从三组视角给出可追溯结论：

开始编写技术方案、PRD 或接口文档前，先记录一个 `Technical Design Start Checkpoint`：目标仓库/模块、用户目标、参考实现、需要确认的已有能力、租户与权限边界、明确不在范围内的内容，以及计划使用的验证证据。这个 checkpoint 用来防止文档从抽象目标直接开始，遗漏仓库适配和已有能力。

在标记 `Implementable` 前，必须有一份可回读的“Repository Fit & Reuse Checkpoint”：列出核心能力对应的已有 symbol/文件、租户边界、复用或不复用决定、最小跨仓依赖闭包和验证命令。只有“计划复用”而没有具体 symbol、调用方式或不复用理由时，仍保持 `Exploration`。

技术文档完成后，再执行一次 `Technical Design Completion Checkpoint`，逐条检查文档是否已经回答目标、行为、边界、依赖、接口变化、验收场景和发布影响，并把每条结论绑定到可定位的代码入口、测试场景或验证步骤。文档未通过这次回读时，不能标记为 `Implementable`，也不能进入编码。

| 视角 | 必须说明 | 按风险适用 |
|---|---|---|
| 意图与正确性 | 授权范围、必须保持的业务规则、主路径、边界/失败、逐 AC 行为变化 | 无 |
| 工程风险 | 并发、顺序、幂等、重试、超时、未知结果、部分失败与补偿 | 性能、安全隐私、公开契约/schema、兼容迁移、发布回滚 |
| 代码库适配与验证 | 可复用 symbol、模块职责、复用或不复用理由、测试与可观测性 | 复杂业务逻辑无法由命名/结构表达时的中文意图注释 |

每个维度必须满足以下一种状态：

- 有已验证证据支持结论；
- 有明确来源的推断或假设，且它不会改变主要实现路径、风险或估时；
- `N/A + 原因`，说明为什么对当前变更不适用；
- 引用一个 Unknown/Open Question。若该未知会改变主要实现路径、风险或估时，成熟度保持 `Exploration`。

必须保持的业务规则使用以下字段表达，每条只描述一个不可再拆的业务约束：

```text
主体 + 动作 + 目标 + tenant/作用域 + 允许/禁止 + 例外 + 业务原因
```

来源包含多个约束或多个业务原因时分别保留，不把局部事实泛化为“始终、全部、必然”，也不编造来源未提供的理由。

## 编写边界

- Review Readiness 指标必须落实到技术方案对应章节，不另生成 Review 专用索引、YAML 或重复摘要。
- 后续真实 Review 由用户显式调用 Review Skill，并重新读取技术方案、实际 diff、目标仓库规则与可执行场景；技术方案不预判 reviewer、finding、优先级或 verdict。
- 技术方案中的预计文件、风险和验证方式只是设计证据，不能替代真实代码事实或 Review 结论。
- 不保存 token、临时 URL、凭据、客户原文或其它敏感数据。

## 生产者完成检查

标记 `Implementable` 前确认：

1. 三组视角的适用指标都已在正文对应章节说明；N/A 和 Unknown 均有原因。
2. 关键结论可追溯到已验证事实、推断或假设及其来源。
3. 会改变主要实现路径、风险或估时的 Unknown 已闭合；否则保持 `Exploration`。
4. 方案没有提前给出 reviewer 数量、finding、优先级或 verdict。
5. Technical Design 工具轨迹没有调用 `review-swarm`、Git diff 或 reviewer。
