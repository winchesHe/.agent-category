# OPC Active 经验索引

Experience 是按需增强，不是 Explicit Execute 的依赖。只有当前动作明确命中 Trigger 时才读详细文件；没有命中直接执行基础阶段合同。

| ID@Version | Stages / Scope | Tags | Status | Trigger 摘要 | 详细文件 |
|---|---|---|---|---|---|
| `OPC-ORCH-001@2.0.0` | 全阶段 / Explicit Execute | `routing,compatibility` | Active | 用户点名阶段 | [opc-orchestration.md](opc-orchestration.md) |
| `OPC-ORCH-002@1.0.0` | Query / 并行 workstream | `query,parallel` | Active | 查询跨仓库或生命周期事实 | [opc-orchestration.md](opc-orchestration.md) |
| `OPC-ORCH-003@1.0.0` | 外部写入 / 重入 | `idempotency,reconcile` | Active | 可能重复对象或写结果未知 | [opc-orchestration.md](opc-orchestration.md) |
| `OPC-ORCH-004@1.0.0` | Requirement discovery | `migration,index` | Active | Navigate 使用 Transitional 索引 | [opc-orchestration.md](opc-orchestration.md) |

Deprecated 条目只保留审计信息，不进入运行指令。
