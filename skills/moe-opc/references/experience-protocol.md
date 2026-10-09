# Experience 协议

Experience 用于提升动作质量，不是阶段开工依赖。缺少 Experience、历史 workspace 或远端 Experience Center 时，Explicit Execute 仍按目标阶段运行。

## 所有权

- OPC 自有的 Active/Deprecated 经验源位于 `references/experiences/`。
- Jira、Slack、Delivery、GitHub、观测等领域经验归对应 owner Skill；OPC 不复制其运行状态机。
- Observed/Pending 候选保存在需求复盘或 Experience Center；远端页面只是可读镜像。

## 生命周期

`Observed → Pending → Active → Deprecated`

只有触发、动作、验证、适用边界和稳定 ID 完整，并进入 owner Skill 版本控制后，才是 Active。Data/Security/Release 类经验从 Pending 升级 Active 前，需要用户批准具体 `ID@Version`。运行中不得自动改写已安装 Skill 或把单次教训提升为 Active。

## 按需应用

执行当前动作时，如果 `experiences/index.md` 中有明确命中的 Active 条目，可以加载最小集合；找不到、不可访问或无法判断命中时直接按基础阶段合同继续。

Experience 不得：

- 要求补齐前序阶段或运行产物；
- 在标准动作前强制写入摘要或回执；
- 覆盖当前用户范围、owner Skill 安全边界或全局 Explicit Execute 合同；
- 把 Pending、历史记录或其它需求经验当作 Active 指令。

动作结束后，可在已有结果记录中写 `ID@Version`、命中原因、实际动作和验证。记录失败不影响已回读的外部结果。

## 经验条目 Schema

| 字段 | 要求 |
|---|---|
| ID / Version / Status | 稳定 ID、语义版本；Active 或 Deprecated |
| Stages / Scope | 适用阶段、workstream、repo/需求类型边界 |
| Tags / Risk | 检索标签与误用风险 |
| Trigger | 可从当前动作观察的条件 |
| Action | 命中后影响的编排动作 |
| Validation | Yes/No 可判断的结果 |
| Not applicable | 防止错误套用的边界 |
| Last validated / Supersedes | 最近验证日期/版本；被替代条目 |
| Priority | 冲突时的相对优先级 |
| Source | 审计标识；不得成为运行依赖 |

冲突优先级：公司/Workspace/目标仓库硬规则 > 当前用户范围与已确认决策 > owner Skill 合同 > OPC Active 经验 > Pending/历史记录。低优先级经验只能被忽略，不能单独制造 Blocked。
