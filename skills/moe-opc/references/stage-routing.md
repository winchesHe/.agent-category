# 阶段路由

## 先判入口，再判阶段

只读动词始终优先：查看、汇总、检查、状态、到哪了、结果怎样。“下一步做什么/是什么/应该做什么”也是 Query，只推荐不执行。

| 用户意图 | 目标阶段 | 加载文件 |
|---|---|---|
| 建立需求、收集背景/Resources、从 Title/Jira 创建或更新 PRD、按 OPC 创建或更新 Release Note | PRD | `stages/prd.md` |
| Design Ticket、设计协调、设计复核 | Design Coordination | `stages/design-coordination.md` |
| 技术调研、技术方案、估时 | Technical Design | `stages/technical-design.md` |
| 开发、实现、修复 | Development | `stages/development.md` |
| Delivery、联调验收、重新验收 | Delivery | `stages/delivery.md` |
| 创建 PR、看 CI、处理 finding、请求 review | PR Review | `stages/pr-review.md` |
| 发布、上线、暂停、回滚 | Release | `stages/release.md` |
| 上线观察、指标、反馈、错误 | Observation | `stages/observation.md` |
| 关闭、完成、取消、归档 | Closure | `stages/closure.md` |

## Explicit Execute

用户点名上表任一阶段时，加载目标 reference 后立即执行，不读取前序阶段完整度，也不先跑驾驶舱、Experience、回执或自动衔接条件。

显式 requirement key、DES key、完整 PR identity、repo/branch 或用户提供的稳定对象足以唯一定位当前动作时直接使用。Process Root 和驾驶舱只在需要恢复更多上下文或记录结果时发现。

阶段 reference 只能定义标准动作、JIT 参数、结果和写后回读；其中的质量标准不能倒推为阶段开工资格。

## Navigate

只有用户没有点名阶段而说“继续/开始下一步/推进下一步”时：

1. 使用当前会话唯一需求；否则验证索引 focus。
2. 必要时合并 Complete/Transitional 候选。
3. 候选唯一后比较当前 workstream，选择最能推进目标的动作。
4. 自动进入下游阶段时读取该衔接的自动条件。
5. 需求或动作仍不唯一时只问一个问题。

推荐顺序只服务导航，不是硬性流程。

## 直接阶段示例

- 直接 PRD：Title 就是最小输入；阶段内部完成 Resources 收集、需求目录与用户本次要求的产物、Jira 映射和回读。飞书只在用户明确要求时同步；Release Note 也只在用户明确要求时作为 PRD 子动作执行。同轮要求 PRD 与 Release Note 时先完成本轮 PRD 回读；单独要求 Release Note 时只读绑定既有版本并跳过 PRD/Resources 工作区预写，没有既有 PRD 时记录限制后继续。
- 直接技术方案：从 Jira、业务 Context、代码和当前设计收集所需事实；缺 PRD 不拒绝开始。
- 直接开发：从用户请求、当前实现和可用方案确定改动；缺阶段产物不补演流程。
- 直接 Delivery：立即生成当前可用 handoff 并调用 owner Skill；不计算自动衔接条件。
- 直接 Review：创建/更新 PR、处理 finding 或发送请求；Delivery 状态只作为上下文。
- 直接 Release：JIT 解析仓库身份、目标发布分支与标准分支准备策略。默认协议在普通 push 并回读远端精确 SHA 后结束；精确仓库 `MoeGolibrary/moego` 继续按大仓 reference 自动 dispatch production workflow，并在唯一 run 回读后结束。不展示统一确认卡，也不创建或更新 Release Note、Release Handbook。
- 直接 Observation：从真实部署事实定位观察对象；缺 Release 回执不拒绝。
- 直接 Closure：同步用户点名终态；缺 Delivery/Observation 只记录为限制或遗留。

## Query 输出

按 Product、Technical、各 repo、Delivery、Review、Release、Observation 分别报告当前事实、来源、有效性和真实阻塞，最后给一个推荐动作。Query 不更新驾驶舱或外部系统。
