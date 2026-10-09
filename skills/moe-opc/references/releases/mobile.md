# Mobile Release｜online 分支

## 适用范围

用于 Mobile 的 `online` 分支发布。主分支名称以仓库事实为准，常见为 `production`；不得写死或从旧记录推断。JS Bundle 与原生包是不同发布目标，只有用户点名范围或仓库实际标准流程包含对应目标时才执行。

## 默认协议

1. 解析真实主分支和远程，拉取远程主分支，并把用于发布的主分支基线更新、绑定到最新远程 SHA。
2. 检查本地 `online`。存在时先记录其 SHA；未被其他 worktree 使用且没有无法恢复的未推送唯一 commit 时，删除本地 `online`，无需二次确认。存在未推送唯一 commit 或身份无法确认时，按不可恢复风险中断。
3. 从最新远程主分支 SHA 创建并切换到新的本地 `online`，回读本地 `online` 已精确指向绑定 SHA。
4. 检查远程 `online`。存在时先记录旧 SHA，再删除精确远程 `online` 并回读其已不存在；这是 Mobile Release 的标准动作，不要求二次确认，也不得扩大到其他分支。
5. 普通 push 新的本地 `online` 到远程，回读远程 `online` 已精确指向绑定主线 SHA。若绑定 SHA 已经生成 workflow/run，只按该 SHA 读取一次稳定 run 身份与当前状态并记录；随后立即以 `BRANCH_HANDOFF` 结束，不等待或推荐 CI/CD、approval、deployment、smoke、质量护栏、发布通知或 Observation。
6. 删除远程 `online` 后若新 push 失败或结果不明，先回读远程分支；保留旧 SHA 供恢复决策，不盲目重试。`BRANCH_HANDOFF` 只表示远程 `online` 已精确指向目标 SHA，不表示生产发布、部署或上线成功。没有已生成 workflow/run 时不主动 dispatch，也不轮询等待其出现。

每次调用 `$github-workflow` 时明确说明：用户点名 Mobile Release 已授权删除并重建精确 `online`；force、历史改写、删除其他分支和独立原生包发布仍不在授权内。
