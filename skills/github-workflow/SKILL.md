---
name: github-workflow
description: >-
  访问 GitHub 仓库（org: MoeGolibrary / 个人: winchesHe）的唯一入口，覆盖 PR、diff、CI、workflow、
  review thread、commit、push、PR 创建、PR 合并、远端文件、代码搜索、clone、checkout 与 worktree，
  以及读源码、查函数、rg-grep 仓库和跨仓定位符号。优先复用用户已经置于上下文中的安全 checkout；
  只有并发、无关脏改动、branch 占用或精确 PR 隔离等风险出现时才创建可回收 worktree。GitHub 写操作
  遵循显式授权、写前校验和写后回读协议。任何读取或搜索 MoeGolibrary / winchesHe 仓库源码
  （包括配合 datadog、调试或排错查代码）必先调用本 skill。
---

# GitHub Workflow

## Accounts / Access

- 公司 org：`MoeGolibrary`（私有仓库，需 VPN 访问，有 IP allowlist）。
- 个人账号：`winchesHe`。
- 认证：使用已配置的 `gh auth`；凭据能力不能替代用户授权。
- 仓库归属影响远端治理的默认倾向，不决定本地目录模型。公司实验仓库可能允许直接写入，个人生产仓库也可能要求严格 PR；以仓库规则、协作状态和用户授权为准。

## 工作区选择

把工作目录分为三类：

- **用户 checkout**：用户明确给出的目录，或当前上下文中已经存在且 identity 匹配的普通 Git checkout。满足安全条件时优先复用。
- **只读 cache**：固定目录下供 clone、fetch、读取、搜索和创建 worktree 使用的共享仓库；一旦被识别为 cache，就不在其主工作树修改业务文件。
- **托管 worktree**：Skill 因隔离风险创建的临时可写目录；创建时必须同时确定释放条件。

选择顺序：

1. 用户明确指定目录时先验证该目录，不因为触发 Skill 就另建 checkout。
2. 未指定目录时，检查当前 Git checkout；identity、branch 和状态满足任务要求时直接复用。
3. 没有安全的 writable checkout 时，再复用固定只读 cache；需要修改则按风险触发规则创建 worktree。
4. 没有本地仓库时，才把仓库 clone 到固定 cache。

普通 checkout 可以写入的条件：

- `origin` 精确解析为目标 `owner/repo`；
- 当前 branch 与任务目标一致，或切换 branch 不会覆盖现有工作；
- 工作区 clean，或已有改动能够明确归属于同一任务；
- 没有证据表明另一个任务或用户正在并发使用该 checkout；
- 该目录未被明确标记为只读 cache。

只有出现下列任一条件才创建或要求使用 worktree：

- 同一仓库存在并发写任务；
- 当前 checkout 含无法安全归入本任务的脏改动；
- 目标 branch 已在其他工作目录使用；
- PR / review 必须锁定精确 `headRefOid`，现有 checkout 无法满足；
- 用户明确要求隔离；
- 只有只读 cache 可用。

worktree 不是按公司/个人仓库强制选择的默认制度。具体选择、checkout 校验、cache 路径、Acquire 和 Release 流程见 `references/repository-operations.md`。

## Acquire 与 Release

- 每次开始或恢复写任务，都对选中的 writable checkout 执行 Acquire：确认 identity、branch、dirty ownership，并把本地与远端关系分类为 `equal`、`behind`、`ahead`、`diverged` 或 `local-only`。
- `equal` 可继续；`behind` 只允许安全 fast-forward；`ahead`、`diverged` 或含无关 dirty 状态时保留现场并停止自动同步。
- PR / review 开始修改前，当前 `HEAD` 必须等于本轮读取的 `headRefOid`。
- Release 只适用于 Skill 创建的托管 worktree，不自动移除用户 checkout。
- 托管 worktree clean、没有未 push commit 且远端可精确恢复时，任务结束即可释放；open PR 本身不是保留目录的理由，后续可按精确 PR head 重建。
- dirty、ahead、diverged、远端状态不明或用户明确要求保留时不得释放。
- Release 默认只移除 worktree 并 prune 登记；删除本地或远端 branch 需要相应清理授权。

## 授权边界

先判断用户请求授权到哪一步。每一行都是终点，不能自动扩展到下一行。

| 用户请求 | 可以执行 | 不可以推断 |
|---|---|---|
| 查看 PR、diff、评论、check、run log、代码 | 只读 `git` / `gh` | 修改、commit、push、回复、resolve、rerun |
| 修改、修复、处理指定 review comment | 在安全 writable checkout 修改指定范围并验证 | commit、push、回复、resolve |
| commit | stage 当前任务文件并普通 commit | push、创建 PR |
| push | 普通 push 当前已确认的精确 branch；默认分支还需用户明确点名且仓库规则允许 | 创建 PR、force、rerun CI |
| 修改并推送到指定 branch | 完成当前改动、验证、commit，并普通 push 到用户点名的 branch | 创建 PR、force、merge |
| 提 PR、创建 PR | 完成当前改动、commit、普通 push、创建 PR | 回复评论、resolve、rerun、merge |
| 合并 PR | 对用户明确指定的 PR 执行合并门禁，并在全部通过后即时 merge | auto-merge、admin bypass、删除远端 branch，除非逐项明确要求 |
| 回复评论 | 回复指定 comment / thread | resolve、push、处理其他评论 |
| resolve thread | resolve 指定 thread | 回复、push、处理其他 thread |
| rerun CI | 重跑指定 run 或失败 job | 修改 workflow、push、merge |

用户明确要求创建 PR 即授权本次 `commit → push → gh pr create`。用户明确要求“修改并推送到某 branch”也授权完成该结果所必需的普通 commit 与 push。只有关键信息无法安全推导、存在多个合理目标或超出请求范围时才询问。

以下高风险动作默认不做，只有用户逐项精确授权、目标可验证且仓库治理允许时才执行：默认分支直推、`--force-with-lease`、历史改写、auto-merge、admin bypass、跳过 hook、删除 branch。裸 `--force` 和 `git worktree remove --force` 不使用；选择带精确 lease 或先检查再普通释放的可审计替代方式。

任何 commit、push、PR 创建、PR merge、评论回复、resolve 或 rerun 操作前，完整读取 `references/github-write-protocol.md`；创建或更新 PR 时还要读取目标仓库规则和可用模板，缺少可用模板时使用 `references/pr-template.md`。

## 场景决策树

```text
1. 查 PR / CI / workflow / review 状态？
   → 直接使用 gh，不需要 clone
   → 查看 PR diff 前先看 changedFiles / additions / deletions

2. 读代码 / 搜函数 / 查历史 / 深挖本地 diff？
   → 优先验证并复用用户指定或当前 checkout
   → 没有可用 checkout 时复用只读 cache；不存在才 clone

3. 修改代码或处理 review comment？
   → 对候选 checkout 执行 Acquire
   → 安全且无隔离风险：原地修改
   → 并发、无关 dirty、branch 占用或精确 PR 隔离：创建/复用托管 worktree
   → 到用户授权终点后停止

4. commit / push / 创建 PR？
   → 读取 github-write-protocol.md
   → 检查仓库规则、hook、diff、origin / push identity、目标 branch 与授权
   → 创建或更新 PR 时读取仓库模板；没有可用模板才用本 Skill fallback

5. 回复评论 / resolve thread / rerun CI？
   → 每项要求独立明确授权；写前定位 ID，写后按 ID 回读
   → 结果不明确时先检查，禁止盲目重试

6. 合并 PR 或执行高风险写操作？
   → 锁定精确 repo、branch / PR、head SHA 和本次授权
   → 普通 merge 走完整门禁；auto/admin/force-with-lease 等必须逐项明确授权
   → 写后按精确目标回读

7. 任务结束？
   → 用户 checkout：保留并报告状态
   → 托管 worktree：执行 Release 门禁
   → clean、fully pushed 且可从远端恢复时释放；open PR 不自动阻止释放
```

## 通用读取规则

- PR / CI / workflow / metadata 优先使用 `gh`，不需要为此 clone。
- 代码阅读、代码搜索和本地历史优先复用 identity 匹配的现有 checkout；没有时再用只读 cache。
- 远端单文件可用 `gh api contents`；跨文件分析优先使用本地 `rg`、`git log` 和 `git diff`。
- 默认分支必须通过 `defaultBranchRef` 或当前 remote 确认，禁止写死 `main`。
- 默认不 fetch；仅在用户要求最新内容、目标 ref 本地不存在、恢复写任务或 cache 明显过期时精确 fetch。
- URL 含 `?` 或 `&` 时，把完整 endpoint 作为一个已引用的 shell 参数。
- `gh pr checks` 没有 `--json`；结构化 checks 使用 `gh pr view --json statusCheckRollup`。

## PR 内容规则

- 先遵守目标仓库 `AGENTS.md`、`CLAUDE.md`、贡献指南和仓库原生 PR 模板；没有可用模板时使用本 Skill 的中文 `references/pr-template.md`。
- 标题默认使用 `<type>(<scope>): <subject>`，但目标仓库的 commitlint 和最近提交规则优先。
- Body 必须基于真实 diff 和已确认上下文填写；未确认和推测不得写成已经发生的事实。
- 可选章节没有有效信息时直接删除，不用文件清单冒充完整 PR 描述。
- PR body、issue / PR comment、review reply 和 review body 全部遵守 `github-write-protocol.md` 的 Markdown 与正文传输规则。
- 创建或编辑后回读 PR body 与 checks，确认正文、base 和 head 完整。

## 安全不变量

- 不复用 identity 不匹配的 checkout / cache，也不修改 remote 来掩盖 mismatch。
- 不覆盖、reset、丢弃或自动同步无法明确归属的 dirty、ahead、diverged 状态。
- 不把一个仓库、PR、branch、评论或 workflow run 的授权扩大到另一个目标。
- 不在 PR head 已变化后继续基于旧 head 执行远端写操作。
- 不在写操作结果不明确时自动重试；先按目标 ID、branch 或 SHA 回读。
- 不在未获精确授权时直推默认分支、改写历史、auto-merge、admin bypass、跳过 hook 或删除 branch。
- 不使用裸 `--force` 或 `git worktree remove --force`；不得以清理为名丢失本地工作。
- 不把“PR 已创建”“检查通过”或宽泛的“收尾”当作 merge 授权。
- 不把“处理评论”扩展为 commit、push、回复或 resolve。
- 不绕过仓库 branch 规则、有效 hook、required checks 或 `<repo>-<branch> <= 63` 等部署约束；只有用户明确授权对应 break-glass 动作时，按写入协议记录并执行。
- 不猜 Jira key；只有仓库规则要求 issue prefix 时才添加。若 commitlint 使用 MoeGo `issuePrefixes` 规则，使用占位 key `IFRFE-0`。
- 多行 GitHub 正文必须通过 UTF-8 Markdown 文件传输并回读，不把 `\n`、`\t` 等转义文本当作真实排版。

## Response Expectations

汇报结果时优先包含：

- `owner/repo`、实际使用的 checkout / cache / worktree；
- 为什么复用现有 checkout，或哪项风险触发了 worktree；
- PR、thread、run、branch 或 commit 的精确标识；
- 已执行动作与明确未执行动作；
- Acquire 状态、写后回读结果，以及托管 worktree 的 retain / release 结论；
- 若因 identity、stale head、hook、仓库治理或授权边界停止，说明具体原因和最短下一步。

## References

| 文件 | 加载时机 |
|---|---|
| `references/repository-operations.md` | clone、fetch、本地读取/搜索、checkout 选择与校验、worktree Acquire / Release |
| `references/github-write-protocol.md` | 处理 review comment，或执行 commit、push、PR 创建、回复、resolve、rerun 等任何写操作 |
| `references/pr-template.md` | 目标仓库没有可用 PR 模板时，作为 PR Body fallback |
