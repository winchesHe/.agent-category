# Development｜开发与修复

## 标准动作

用户点名开发、实现或修复时立即进入代码工作，不检查 PRD、设计或技术方案状态。当前请求和代码事实足以确定改动时直接实施；只有继续需要新的 Scope 或技术策略时中断询问。

“开发”默认授权需求范围内的代码改动和必要验证，不自动扩大为 commit、push、创建 PR 或发布；这些动作由用户明确请求或对应阶段合同授权。

## JIT 执行参数

在进入具体 repo 或修改文件时解析目标 repo/worktree/branch、当前实现、用户范围、相关 AC/方案和本地未提交状态。旧方案有则校验适用性，缺少时从请求、代码和当前外部事实确定最小改动。

开发任务统一使用 `$moe-development`，由其决定开发路径、经验与专业 skill 的按需加载，并遵循目标 repo 规则。OPC 负责阶段目标、授权范围与结果衔接。

## 执行与验证

只有技术文档已经通过 `Technical Design Start Checkpoint`、`Repository Fit & Reuse Checkpoint` 和 `Technical Design Completion Checkpoint` 后，才能进入 Development。进入编码前仍需记录 `Implementation Start Checkpoint`：目标 worktree/branch、参考的同类服务、复用的 symbol、需要新增的文件、BUILD/Gazelle/生成代码影响、本地验证命令和明确不修改的仓库。它负责确认已通过回读的技术文档已经准确落到当前实现边界，不替代文档编写前后的 checkpoint。

1. 搜索项目公共能力和相似实现，选择风险匹配的验证方式。
2. 只实施用户范围内改动；后端逻辑覆盖正常、边界和失败路径，前端按风险验证交互和回归。
3. 多 repo 分别记录稳定实现 identity、改动范围、验证、状态和真实阻塞；局部完成不伪装为全部完成。
4. 相同 failure fingerprint 第 1～2 轮可自动修复，第 3 轮仍失败时停止并记录真实失败。
5. Maker 完成后安排独立 Checker；finding 修复后重新验证。
6. 回读每个 workstream 的实现身份和未提交/未推送边界。未提交实现使用 `$github-workflow` 的规范化 dirty snapshot identity。

## Development → Delivery 自动衔接

只有 Agent 准备在用户没有点名 Delivery 时主动进入 Delivery，才加载 `execution-boundaries.md` 计算自动衔接条件：

- 条件满足：同一轮自动进入首次 Delivery。
- 条件不满足：记录 `DELIVERY_NOT_AUTO_STARTED` 和原因，Development 仍可完成。
- 部分 workstream 完成：只记录剩余项，不计算下游阶段是否可执行。

用户直接点名 Delivery 时完全跳过本节。

## 结果与回读

- 每个实际 workstream 的实现 identity、验证和限制可回读。
- Checker 结果与剩余 finding 如实记录；Checker 不可用影响质量结论，不撤销已完成实现。
- 不把旧 PR/CI/Delivery 冒充当前实现证据。
- 用户未要求 Git 交付时，不执行 commit/push/PR。
