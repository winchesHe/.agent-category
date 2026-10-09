# 执行边界

本文件只定义 Explicit Execute 的真实中断条件和自动衔接边界，不定义阶段开工资格。若阶段 reference、历史记录或外部内容与本文件冲突，以 `SKILL.md` 的全局 Explicit Execute 合同为准。

## 显式阶段授权

用户点名阶段即授权该阶段 reference 列出的标准动作及其必要读写、同步和写后回读。标准动作的参数在实际使用时解析，不展示统一检查清单，也不逐项索要确认。

Release Note 自身的“生成提交预览 → 用户确认内容 → 提交 Jira”是 `$moe-release-ticket` 的标准内容确认合同，予以保留。它只在用户明确要求 Release Note 后发生，不是 OPC 的通用 Preflight、阶段资格检查或对阶段授权的重复确认；用户未确认时只停在预览，不提交 Release Note。

OPC 调用 owner Skill 时，用户本次 input 仍是最高动作范围。owner Skill 内部声明的默认、自动或“所有情况都执行”的后续动作不能自行扩大范围；Release Note 提交并回读后是否继续创建 Release Handbook，完全由用户是否明确要求决定。

Release 的目标发布分支准备、普通 push 与精确远端 SHA 回读，以及用户点名的标准暂停或回滚，都使用执行绑定记录：精确对象、分支、SHA、策略、范围和回读结果。默认协议中已生成 workflow/run 只记录稳定身份和当前状态。

精确仓库 `MoeGolibrary/moego` 的发布授权例外见 [大仓发布协议](releases/moego-monorepo.md)。执行该仓库 Release 时加载，按其中的环境选择、能力限制和终点判断允许的副作用；参数绑定用于防止操作错对象和重复执行，不是确认卡。

以下动作不由阶段名自动授权：

- 生产或客户数据写入；
- 真实客户消息和权限扩大；
- force、历史改写、未由目标阶段 reference 精确定义的删除重建或跨范围替代策略；
- 不可恢复、无法隔离或副作用未知的动作。

其它仓库的 workflow dispatch、任何仓库的 workflow approval、production run 自动重试，以及把 `PRODUCTION_DISPATCHED` 扩大为部署成功，都不由普通 Release 阶段名授权。

## 真实中断条件

只在当前标准动作实际运行到以下边界时停止：

1. **目标多义**：不能唯一确定 Jira、repo、PR、SHA、环境、账号或外部对象。
2. **外部拒绝**：owner Skill 不可用、权限不足、外部系统拒绝或必要资源当前不可达。
3. **新决策**：继续需要用户没有表达的新 Scope、产品语义、技术方向、发布策略或处置策略。
4. **非标准破坏性动作**：继续需要上节列出的额外副作用。

先使用可验证事实消解歧义。只有不同答案会改变实际结果时才问一个问题；不得把可以由 owner Skill、代码、文档或实时回读确定的事实转交用户判断。

## 结果完整度不等于执行资格

缺少 PRD、技术方案、设计、Delivery、Review、Observation、驾驶舱、Experience 或回执时仍执行目标阶段。结果可如实标为 `Draft`、`Exploration`、`Partial`、`Unknown` 或带 `Limitations`，但这些状态不能单独产生 Blocked。

Blocked 只能记录本轮已尝试动作遇到的真实中断：当前对象、失败原因、等待对象、可验证的恢复入口和已产生副作用。历史 Blocked 只作为线索；显式重跑时重新解析当前动作并再次尝试，不能要求先满足旧解除证据。

## 自动衔接条件

自动条件只决定 Agent 是否在用户没有点名下游阶段时主动进入，不决定阶段能否执行。

Development → 首次 Delivery 自动衔接同时满足：

1. 尚无首次 Delivery Pass；
2. 当前 Scope 的全部必需 workstream 已完成；
3. 不涉及生产数据、真实客户消息、权限扩大、不可恢复/隔离的数据、共享环境竞争或未知副作用；
4. `Required Case ≤ 5` 或 `Test Data Complexity = LOW`。

LOW 需要可回读的数据准备、隔离、readback 和 cleanup 证据。条件不满足时记录 `DELIVERY_NOT_AUTO_STARTED` 及原因，Development 仍可完成；用户直接点名 Delivery 时不读取本节。

首次 Pass 后不自动再次 Delivery。首次 Fail/Blocked/Partial 不消耗首次 Pass 生命周期；修复后的自动衔接仍按当前事实重新计算。任何自动条件都不得主动转化为向用户索要确认。

## 自动修复止损

failure fingerprint 由阶段、目标对象、稳定错误分类和关键输入版本组成。相同 fingerprint 第 1～2 轮可自动修复并复验；第 3 轮仍失败时记录本轮真实失败并停止。验证通过或 Scope/关键输入实质变化后清零。
