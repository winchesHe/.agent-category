# Web Release｜前端与后端

## 适用范围

用于 Web 范围内的前端和后端仓库。仓库已有更具体且可回读的发布约定时以仓库约定为准；否则执行本默认协议。所有分支名、远程、主线 SHA、目标 commit 和当天边界都在动作内 JIT 解析。

## 默认协议

1. 解析真实主分支和远程，拉取远程主分支，并把用于发布的主分支基线更新、绑定到最新远程 SHA。不得用旧本地主分支或旧会话记录代替。
2. 解析本次需要发布的精确 commit；目标不唯一时才中断询问。
3. 检查远程 `release` 是否存在，并按本次执行时区检查其历史中是否包含提交日期为当天的 commit；同时解析本地 `release` 的当前 SHA、未推送唯一 commit 和 worktree 占用。任何需要创建或重建本地 `release` 的路径，都只在没有未推送唯一 commit、未被其它 worktree 占用且可从已记录 SHA 恢复时继续。
4. 若远程 `release` 存在且包含当天 commit，只问一个发布策略问题：是否需要采用 cherry-pick 发布。列出已发现的当天 commit、当前 `release` SHA 和待发布 commit，不展示通用门禁卡。
   - 用户选择 cherry-pick：从当前远程 `release` 建立本地发布分支，只 cherry-pick 已绑定的待发布 commit，普通 push 后回读。
   - 用户不选择 cherry-pick：继续执行下一步的主线直推协议。
5. 其他全部情况，包括远程 `release` 不存在、存在但没有当天 commit，或用户明确不采用 cherry-pick：满足上一步本地分支安全条件时，基于最新远程主分支 SHA 创建或重建本地 `release`，普通 push 到远程 `release`；否则按真实不可恢复或共享工作区风险中断，不删除、重置或覆盖该分支。
6. 回读远程 `release` 的精确 SHA 和祖先关系。若绑定 SHA 已经生成 workflow/run，只按该 SHA 读取一次稳定 run 身份与当前状态并记录；随后立即以 `BRANCH_HANDOFF` 结束，不等待或推荐 CI/CD、approval、deployment、smoke、质量护栏、发布通知或 Observation。普通 push 被 non-fast-forward 拒绝时记录真实 Blocked；不得改用 force、静默删除远程 `release` 或扩大 cherry-pick 范围。

`BRANCH_HANDOFF` 只表示远程 `release` 已精确指向目标 SHA，不表示生产发布、部署或上线成功。没有已生成 workflow/run 时不主动 dispatch，也不轮询等待其出现。

“是否 cherry-pick”是发现当天 `release` 已在使用后的真实策略分叉，不是发布前置检查；未命中该条件时不得询问。
