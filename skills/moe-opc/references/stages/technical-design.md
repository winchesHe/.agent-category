# Technical Design｜技术方案

## 直接进入与最小输入

用户点名技术方案时立即执行。最小输入是“技术方案意图 + 一个可唯一发现的需求线索”：Jira/DES key、已验证标题、当前会话唯一需求，或用户直接给出的范围、代码入口、repo 线索。PRD、设计稿、Resource Context、驾驶舱、Process Root、repo 列表、估时和 Task 结构都不是开始条件。

只有目标仍多义且继续可能作用于错误对象时，才问一个定位问题。不得检查前序阶段，不得把 JIT 包装成 Preflight，也不得因缺少既有产物写成 Blocked。

## JIT 最小充分证据

在实际消费事实时按需收集：

1. 使用当前用户指令、当前 Jira 对象和已有 PRD/Design/Resource Context/已确认决策；以 Jira/DES 为入口时通过 `$jira` 回读当前对象和 revision。
2. 产品语义、用户路径或业务边界仍有缺口时，通过 `$moe-business-context` 补业务事实。
3. 当前行为、复用点、影响模块或调用链仍有缺口时，通过 `$github-workflow` 读取代码、仓库规则、repo/head 和相关历史。
4. 开发相关判断统一交给 `$moe-development`，传入当前方案目标、已知代码与约束，由其决定开发路径和所需资料。
5. 技术方案调查不自动授权代码修改、发包或经验写入。
6. 开始组织方案正文时读取 `../review-readiness.md`，用其中的正确性、工程风险、代码库适配与验证指标指导编写；判断是否达到 `Implementable` 时再检查适用证据是否闭合。`Exploration` 把未闭合项直接写入正文的 Unknown/Open Question。加载发生在执行内部，不是 Preflight，也不调用 `review-swarm`。

已有来源闭合某类事实时跳过对应查询。满足以下任一条件就停止搜索：证据足以支持当前成熟度和关键决策；权威来源已查尽且剩余内容只能标为 Unknown/Limitations；继续查询不会改变方案、风险、估时或物化判断。不得为了“资料完整”穷举 Jira、业务系统或仓库。

分析与当前 Scope 相关的真实端到端链路：

```text
用户入口 → 前端状态/请求 → API/BFF → 下层服务
→ Legacy/新流程数据 → 输出模型 → 各端/下游消费
```

## 产品与技术歧义

- 可验证事实继续查 owner Skill、代码、文档或当前对象，不转交用户猜测。
- 不改变关键方向的缺口记录为假设、Unknown 或 Limitation，继续产出。
- 会改变 Scope、技术方向、发布策略或实质风险时，只形成一个决策卡：已确认事实、选项、推荐项和影响；只讨论一个真实选择。
- 用户已经给出选择时直接使用并记录来源，不重复询问。
- 等待选择时保存 `Exploration`，只暂停依赖该选择的物化或任务，独立结论继续。

Technical Design 不自动调用 `$grilling`；只有用户明确要求压力测试或点名 grilling 时才使用。

## 四个正交状态

- 执行结果：`Completed / Partial / Blocked`。`Partial` 表示方案已形成，但一个或多个授权动作尚未完成；`Blocked` 只来自本轮真实中断。
- 成熟度：`Exploration / Implementable`。关键 Unknown 会改变实现路径、风险或估时时保持 `Exploration`；适用 Review Readiness 已回答且逐 AC 可执行时才标记 `Implementable`。
- 有效性：`Current / Stale / Superseded`。绑定变化时只标记受影响段落、workstream 和投影，不清空无关历史。
- 载体同步：本地、Lark、Jira requirement、Jira Tasks 分别记录 `current / stale / failed / deferred / skipped / unknown`。`deferred` 表示授权动作只因上游输出未就绪而暂停，必须同时记录 `blocked_by`、`retryable` 和恢复入口；`skipped` 只用于用户明确排除或矩阵不适用。

不要使用 `Draft / Approved` 表示成熟度。真实人工批准单独记录 `decision_status / accepted_by / accepted_at / source`。

## 执行与内容

1. 建立产品语义卡和必须保持的业务规则；每条规则只表达一个主体、动作、目标与作用域约束，并区分已验证事实、推断、假设、Unknown/Limitations。
2. 分开描述当前能力与拟议改动，闭合调用链并记录真实可复用 symbol、复用或不复用理由。
3. 按 `assets/templates/technical-design.md` 形成推荐方案、关键决策、工程风险、发布回滚、逐 AC 实现/测试/Delivery/观测责任及失败回路；用 `../review-readiness.md` 检查这些指标是否已在正文中清楚表达，不另生成 Review 专用索引。
4. 计算稳定 `design_identity` 与规范化 `content_fingerprint`，记录 Jira revision、Design version、repo/head、API/data/release 边界等 `source_bindings`。canonical payload 计算规则以 `../requirement-workspace.md` 为准；运行元数据、同步回执和回读时间不参与指纹。
5. 按条件物化矩阵执行本地、Lark、Jira requirement 与 Jira Tasks；用户明确的正向或负向范围优先。

方案正文只呈现帮助读者理解、实现和评审的内容。标题后保留紧凑的关联 Resources：需求文档、设计链接、相关 Jira/代码/API 与发布方式；没有可用项时如实写“无”或“待确认”，不得编造链接。不在标题下或文末重复展示 `source_authority`、成熟度、有效性、同步状态、`design_identity`、`content_fingerprint`、执行结果等运行元数据；这些信息由阶段回执、驾驶舱或外部载体字段承载。

## Source Authority 与本地路径

- 有可写 Process Root 时，写入或更新 `requirements/<key-or-slug>/03-technical-design/01-technical-design.md`，并记录 `source_authority=local`。不为目录完整性创建空 PRD、Resource Context 或驾驶舱。
- 没有可写 Process Root 但按矩阵正式发布 Lark 时，记录 `source_authority=lark`，后续重入先回读该文档。
- 两者都没有时在响应中交付完整方案，但不得声称存在可恢复的持久源。
- Jira requirement 是摘要/链接投影，Jira Tasks 是 workstream 投影，不承载完整正文。

权威源迁移或外部人工编辑时先回读、比较规范化内容，再决定合并或形成一个真实决策；禁止最后写入者静默覆盖。

## 条件物化矩阵

| 结果 | 本地源 | Lark | Jira requirement | Jira Tasks |
|---|---|---|---|---|
| `Exploration` | 有 Process Root 时创建/更新 | 默认不新建；用户明确分享时同步并标明限制 | 默认不写正式方案；用户明确同步探索状态时才写 | 默认不创建依赖未决策的实现任务；用户明确时可建独立 Exploration Task |
| `Implementable` 单仓/单 Owner | 有 Process Root 时创建/更新 | 已有正式上下文、需跨角色评审或用户明确要求时创建/更新 | 已有 Jira identity 时回填状态、源/正式链接和必要摘要 | 有持久 source authority 且存在需独立跟踪的稳定 workstream 时创建/更新 |
| `Implementable` 跨仓/多 Owner | 有 Process Root 时创建/更新 | 默认创建/更新；无本地源时成为持久源 | 回填状态、正式链接和内容版本 | 持久 source authority 建立后，默认按稳定 workstream 创建/更新并闭合关系 |

补充约束：

- 用户禁止某载体或矩阵明确不适用时记为 `skipped`，不二次确认；依赖上游结果而暂停的授权动作记为 `deferred`，不得复用 `skipped`。
- 不为满足矩阵静默创建新的根 Jira requirement。
- 只有响应、没有持久源时默认不创建实现 Task；用户明确要求时先建立其允许的持久方案载体，否则只交付任务拆分。
- Task 代表独立可跟踪 workstream，不按文件、函数或模板行机械拆分。
- 已发布旧方案变为 `Stale` 或 `Exploration` 时，按稳定对象纠正成熟度/有效性并回读；不自动改变 Jira Task workflow。

## Jira、Lark 与关系幂等

每个任务使用 `task_identity = design_identity + workstream_id`。`workstream_id` 由业务责任、repo/模块和交付边界决定，不使用可变标题。identity 同时保存在权威源和 Jira 可见稳定载体：优先专用字段/label，否则在 ADF/Description 写入 `OPC Task Identity`。

对每个外部对象执行：

1. 读取当前 schema、稳定 identity 和候选；Jira 同时回读 parent/hierarchy 与可用 Issue Link type/direction。
2. 内容一致则 `skip`，同一对象变化则完整 `update`，不存在才 `create`。
3. 写后回读 key/token、可见字段、ADF、fingerprint、parent/hierarchy、link type/direction 和依赖。
4. 写结果未知时按稳定 identity `search/read/reconcile`，禁止立即再次 create。

真实依赖才使用当前实例支持的 `blocks/is blocked by`。优先用项目支持的 parent/hierarchy 表达归属；没有合适 link type 时保留根需求/方案引用并记录限制，禁止用 `blocks` 或 `relates to` 冒充。只有用户明确要求必须建立该关系且当前 schema 确实无法表达时，才形成真实阻塞。

schema 无法持久化稳定 task identity 时不自动创建不可幂等恢复的新 Task，结果记为 `Partial` 和 capability limitation；只有多个既有候选会改变实际目标时才问一个定位问题。

Lark 按 `design_identity` 定位，在稳定元信息中保存 `design_identity`、`source_authority`、`content_fingerprint`。标题只能辅助定位。写结果未知时先按 token、稳定目录和 identity 回读。

## 依赖感知的写入与恢复

跨仓 `Implementable` 的首选顺序是：本地源 → Lark 写入/回读 → Jira requirement patch/回读 → Tasks 写入/回读 → hierarchy/links reconcile/回读 → 本地或驾驶舱同步摘要。

这只是依赖顺序，不是事务或门禁。一个载体失败只暂停依赖其输出的动作；与该输出无关、目标仍唯一且安全的授权动作继续。保留已经成功的对象和回读事实。恢复时只重试 `failed / deferred / unknown / stale` 中仍获授权的动作；`skipped` 不进入恢复队列，不从起点重放，也不回滚成功对象。

## 完成标准与结果

本轮响应或阶段回执至少报告：执行结果、成熟度、有效性、source authority、`design_identity`、`content_fingerprint`、source bindings、各载体同步状态、Unknown/Open Questions、真实阻塞和下一步；这些运行信息不要求重复写入技术方案正文。

- `Completed`：请求范围内标准动作完成；`Exploration` 也可以是 Completed。
- `Partial`：方案已形成，但某个授权载体或关系未完成，且有恢复入口。
- `Blocked`：真实中断使请求的必要结果无法继续；缺 PRD、设计、驾驶舱、Process Root 或 Review 不是 Blocked。

## Explicit Execute 与自动衔接

本阶段不新增 PRD/Design → Technical Design 自动衔接。用户显式点名时始终按本文件直接运行，Review Readiness 只决定成熟度。未来自动路径若存在，也必须复用同一执行、模板、物化和回读合同；自动条件不得用于限制显式执行。
