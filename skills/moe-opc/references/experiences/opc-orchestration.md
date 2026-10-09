# OPC 编排经验

## Active

### OPC-ORCH-001@2.0.0｜显式阶段直接执行

- Status / Scope：Active；全部阶段；Explicit Execute。
- Trigger：用户点名阶段或阶段内标准动作。
- Action：立即进入目标阶段；前序产物仅作可选上下文；参数在当前动作使用时解析。
- Validation：目标阶段发生标准动作及写后回读，没有前序完整性判断、门禁卡或二次确认。
- Not applicable：用户请求是 Query 或未点名阶段的 Navigate。
- Last validated / Priority：2026-08-28；OPC Active。

### OPC-ORCH-002@1.0.0｜并行事实查询

- Status / Scope：Active；Query；跨 workstream 或仓库。
- Trigger：只读查询多个 workstream。
- Action：分别回读并报告，不压缩成单一阶段；只给推荐动作。
- Validation：每个 workstream 有来源、有效性和真实阻塞，调用全为只读。
- Not applicable：用户明确执行某一动作。
- Last validated / Priority：2026-08-28；OPC Active。

### OPC-ORCH-003@1.0.0｜重入幂等

- Status / Scope：Active；所有外部写入；稳定对象可查询。
- Trigger：阶段重入或写结果未知。
- Action：用稳定身份/查询键回读，再选择 create/update/skip/reconcile；写后按同一身份回读。
- Validation：没有重复对象，结果包含最新回读。
- Not applicable：用户明确创建身份不同的新对象。
- Last validated / Priority：2026-08-28；OPC Active。

### OPC-ORCH-004@1.0.0｜Transitional 导航

- Status / Scope：Active；Navigate；旧 `requirements/` 兼容期。
- Trigger：Navigate 使用 Transitional 索引定位需求。
- Action：浅层扫描旧驾驶舱并合并候选后判断唯一性。
- Validation：未登记的旧 Active 需求仍出现在候选集。
- Not applicable：Explicit Execute 已有唯一稳定目标，或 Coverage 已验证为 Complete。
- Last validated / Priority：2026-08-28；OPC Active。

## Deprecated

| ID | 原规则 | 原因 | 替代 |
|---|---|---|---|
| `OPC-ORCH-D01` | 必须按单一状态机依次前进 | 阻止阶段独立运行 | `OPC-ORCH-001@2.0.0` |
| `OPC-ORCH-001@1.0.0` | 前序不完整时直接发现事实，但仍允许通用开工记录 | 没有彻底分开 Explicit Execute 与自动衔接 | `OPC-ORCH-001@2.0.0` |
