# Release｜发布执行

## 标准动作

用户点名发布或上线时，立即执行目标仓库的标准发布协议；用户点名暂停或回滚时，立即执行对应的仓库标准流程。Release 的 GitHub 操作只使用 `$github-workflow`。

默认发布标准动作只覆盖目标发布分支的必要准备、普通 push 与远端精确 SHA 回读，也覆盖 [Web 默认发布协议](../releases/web.md) 中可安全恢复的本地 `release` 重建、用户选择后的精确 cherry-pick，以及 [Mobile 默认发布协议](../releases/mobile.md) 中精确 `online` 分支的删除重建。

精确仓库 `MoeGolibrary/moego` 使用 [MoeGo Monorepo 协议](../releases/moego-monorepo.md)，执行时加载其中的发布基线、已有固定发布分支的删除重建、环境选择、构建能力判断与结果合同。该例外不扩展到其它仓库。

除上述精确例外外，Release 不覆盖 PR merge、tag、workflow dispatch/approval、deployment、smoke、质量护栏、发布通知、Release Note、Release Handbook、force、历史改写、其它分支的删除重建、跨范围 cherry-pick、生产数据修改、真实客户消息或未知副作用。大仓的允许动作与等待范围以其 reference 为准。

## JIT 执行参数

在每个标准动作实际使用时回读真实默认分支/发布基线、目标发布分支、目标 SHA、祖先关系和分支占用。大仓协议还绑定 app、source/release SHA、App CI、Git tag、image tag、production workflow 输入与 run ID。把解析结果保存为执行绑定记录，不展示统一确认卡。

若基线、目标分支或 SHA 变化，重新解析：目标仍唯一、仍属于用户点名范围且分支准备策略仍是仓库标准流程时继续；变化引入新范围、新策略或非标准破坏性动作时才中断。

## 执行

1. 先精确解析仓库身份。命中 `MoeGolibrary/moego` 时加载 [moego-monorepo.md](../releases/moego-monorepo.md) 并按其终点执行，不再套用 Web 或 Mobile 默认协议。
2. 其它仓库再解析目标属于 Web、Mobile 还是仓库自定义发布面，不假设主线叫 `main`。Web 前端和后端加载 [web.md](../releases/web.md)，Mobile 加载 [mobile.md](../releases/mobile.md)；其它仓库使用其可回读的标准发布分支。跨发布面时分别绑定对象、分支、SHA 和结果。
3. 仓库存在更具体且可回读的发布分支约定时使用该约定；否则 Web 使用 `release`，Mobile 使用 `online`。参数发现发生在动作内，不让用户替代可验证事实判断。
4. 按 `$github-workflow` 完成目标发布分支的必要准备和普通 push，并按精确远端 ref 回读 SHA。调用 owner Skill 时明确传递本 reference 已定义的阶段授权和精确分支范围。
5. 默认协议只有在远端目标发布分支精确指向绑定 SHA 时记录 `BRANCH_HANDOFF`。该结果只表示分支交接完成，不得写成生产发布、部署或上线成功。
6. 默认协议若发现绑定 SHA 已经生成 workflow/run，只按精确 SHA 读取一次稳定 run 身份和当前状态，记录后立即结束；没有已生成 run 时不 dispatch、不轮询等待其出现。大仓例外按自身 reference 继续执行。
7. 默认协议不等待或推荐 CI/CD、tag、approval、deployment、smoke、质量护栏、发布通知或 Observation。大仓例外按自身 reference 的环境选择与等待范围执行。
8. Web 的 `release` 只在本地分支无未推送唯一 commit、无其它 worktree 占用且可安全恢复时重建，并且只做普通 push；non-fast-forward 拒绝是真实执行阻塞，不静默 force 或删除远程分支。Mobile 的精确 `online` 删除重建是已定义分支准备动作，不套用通用“删除重建需二次授权”。

## 失败与恢复

- 远端 ref 回读不等于绑定 SHA、外部系统拒绝、权限不足或目标无法唯一确定时，记录本轮真实 Blocked。
- push 结果不明时先回读精确远端 ref，不盲目重试。
- 大仓 workflow dispatch 结果不明时先按精确 workflow 输入与时间边界 reconcile，不盲目创建第二个 run。
- Mobile 已删除远端 `online` 但新 push 失败时保留旧 SHA 和已发生副作用，等待可验证的恢复决策。
- 不删除失败证据，不以本地 branch 名或“最新 run”代替绑定对象。

## 结果与回读

- 记录目标仓库、目标发布分支、绑定 SHA、远端 ref 回读 SHA 和 `BRANCH_HANDOFF` 结果。
- 大仓按其 reference 记录分支、制品、部署对象及真实终态或阻塞。
- 已生成 workflow/run 时记录其稳定身份、绑定 SHA 和当前状态；不把 run 存在或状态转换成部署结论。
- 默认 Release 在分支交接回读后结束；大仓按其 reference 的成功终点或真实阻塞交付结果。两者都不主动进入、安排或推荐 Observation。
