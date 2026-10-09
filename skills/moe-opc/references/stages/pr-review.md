# PR Review｜PR、CI 与 Finding

## 模式与标准动作

- “看 PR/CI/Review/Delivery 结果”：Query，只读回读。
- “创建 PR/处理 finding/请求 review”：Explicit Execute，立即执行对应标准动作。

GitHub 只使用 `$github-workflow`。PR Body 与 Slack Review 的改动导览只使用 `$review-brief` 基于真实 diff 生成的同源内容。Delivery Pass、例外批准、PRD 或阶段回执都不是创建 PR、处理 finding 或发送 Review 请求的资格，也不注入 Review Brief。

## JIT 执行参数

在当前动作使用时解析 repo、base/head、精确 SHA、PR identity/body 和真实 diff。处理 finding 或用户查询时再解析 CI、review threads、mergeability 与测试；发送 Slack Review 时只额外解析 Reviewer、频道、Review Brief 视觉附件和验收附件，不为正文查询或拼装 CI、测试、Delivery 状态、非目标或风险摘要。

## 执行

1. 根据用户点名动作锁定 repo、branch/PR、head SHA 和改动范围。
2. 创建或更新 PR 前按稳定 branch/PR URL 查询；写结果未知先回读，禁止重复 PR。
3. 处理 finding 时按行为回归、安全/隐私、性能、可维护性和有效性分类；修复后重跑受影响验证。
4. 回读 PR body、head/base、CI、review threads 和 mergeability；基线失败与本 PR 失败分开。
5. head SHA 改变时旧 CI/Review 证据失效，但不自动触发 Delivery。
6. 用户要求 Slack Review 时加载 `communications/slack-pr-review.md`，按当前 repo/PR/base/head 复用 PR Body 已绑定且校验通过的 `review-brief.json`；不存在时只生成一次。用同一 JSON 渲染 Slack 正文并对账 `content_hash`，把其图片/技术图作为额外附件，再按通知合同发送验收材料；全部写后回读。

## 结果与回读

- PR URL、head/base、精确 SHA、CI/Review 状态和限制来自实时回读。
- Delivery 的 Pass/Fail/Unknown 不改变 Review 执行结果，也不进入 Review Brief。
- finding 清零、剩余 finding、外部等待或真实权限失败分别记录。
- merge 不属于 PR Review 或 Release 的默认标准动作；只有用户明确要求合并指定 PR 时，才按 `$github-workflow` 的独立授权执行。
