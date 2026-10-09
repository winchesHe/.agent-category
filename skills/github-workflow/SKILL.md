---
name: github-workflow
description: >-
  访问 GitHub 仓库（org: MoeGolibrary / 个人: winchesHe）的入口，覆盖 PR/diff、CI/workflow、review thread、commit/push、clone、worktree 和源码搜索。读搜用 cache；改/测/提交/推送只在任务 worktree。代码 review/审查 PR 使用 `review-swarm` 只读审查；review comment 按真实性与修复安全判定，不自动调用 review-swarm；改动默认 commit → push，评论改动 push 后默认回复原 thread；写操作遵循授权。触发：查/创建/合并/审查 PR、处理/回复 review comment、代码 review、review-swarm、看 diff/CI/workflow、最近改动、bug 引入、clone/拉仓库、看实现/搜函数/查 commit。读取 MoeGolibrary/winchesHe 源码必先调用本 skill。
---

# GitHub Workflow

## Accounts / Access

- 公司 org：`MoeGolibrary`（私有仓库，需 VPN 访问，有 IP allowlist）。
- 个人账号：`winchesHe`。
- 认证：使用已配置的 `gh auth`；凭据能力不能替代用户授权。

## 核心工作区模型

固定使用 repo 根目录，并在每个 category 下放置该分类自己的 `worktrees/`；不从当前仓库、`pwd` 或 `git rev-parse` 推导：

```bash
REPOS_DIR=/Users/moego-winches/Desktop/Company/person/agent-workspace/repo
WORKTREES_DIR="$REPOS_DIR/$CATEGORY/worktrees"
```

目录继续按 `front-end / back-end / unclear / person` 分类：

```text
$REPOS_DIR/<category>/<repo>                  # 只读 cache
$REPOS_DIR/<category>/worktrees/<repo>/<branch> # 可写任务 worktree
```

必须遵守：

- repo cache 只用于 clone、fetch、读取、搜索、`git log`、`git diff` 和创建 worktree。
- 禁止在 repo cache 的主工作树修改业务文件、checkout 业务分支、测试、stage、commit 或 push；branch ref 只可随 `git worktree add` 创建到独立任务 worktree。
- 修改、测试、stage、commit 和 push 只在已验证的任务 worktree 内执行。
- 一个任务、一个仓库、一个分支对应一个 worktree；已有 worktree 只有在 cache、路径和 branch 全部一致时才能复用。
- 每次进入写任务都先执行 Acquire：精确 fetch 目标 ref，并把 worktree 分类为 equal、behind、ahead、diverged 或 dirty；只有 equal，或完成 fast-forward 后的 behind，才可声称基于最新远端继续。
- PR 仍 open 时默认保留 worktree，后续 review 调整继续 Acquire 同一 worktree；目录缺失时按 PR 的 `headRefName / headRefOid` 重建并验证精确 head。
- 用户明确要求合并 PR 且未要求保留 worktree 时，成功回读 `MERGED` 后默认对该 PR 的任务 worktree 执行安全 Release；PR closed / 明确放弃或其他结束场景仍需用户明确要求清理。dirty、含未 push commit、diverged、受保护 ignored 文件、状态不确定或仍有 open PR 时必须保留并报告原因。
- Release 只移除 worktree 并 prune 登记，不自动删除本地或远端 branch；不自动覆盖或重建有冲突的 cache / worktree。

需要 clone、fetch、本地搜索或 worktree 时，完整读取 `references/repository-operations.md`。

## 授权边界

先判断用户请求授权到哪一步。修改类任务在验证通过后默认以 `commit → push` 收尾，除非用户明确禁止或限定更窄终点；其他每一行仍是终点，不能自动扩展到下一行。

| 用户请求 | 可以执行 | 不可以推断 |
|---|---|---|
| 查看 PR、diff、评论、check、run log、代码 | 只读 `git` / `gh` | 修改、commit、push、回复、resolve、rerun |
| 代码 review / 审查 PR、branch、commit 或 diff | 先按 `review-swarm` 选择差异模式、解析范围和 reviewer 路由；主 agent 独立验证 finding | 修改、commit、push、回复、resolve、rerun |
| 修改、修复、处理指定 review comment | 先锁定 head / thread，加载评论真实性与修复安全判定并直接核对代码、调用链、契约、测试和业务不变量；在 worktree 修改并验证；未声明例外时默认 commit、push；由该评论触发的改动成功 push 后默认回复原 thread | PR 创建、resolve、rerun、merge，以及其他评论 |
| commit | worktree 内 stage 当前任务文件并普通 commit | push、创建 PR |
| push | 普通 push 当前已确认的非默认分支 | 创建 PR、rerun CI |
| 提 PR、创建 PR | 完成当前改动、commit、普通 push、创建 PR | 回复评论、resolve、rerun、merge |
| 合并 PR | 对用户明确指定的 PR 执行合并门禁；成功回读 `MERGED` 后默认安全 Release 对应任务 worktree，用户可明确要求保留 | auto-merge、admin bypass、删除本地或远端 branch、强制清理不安全 worktree |
| 回复评论 | 回复指定 comment / thread | resolve、push、处理其他评论 |
| resolve thread | resolve 指定 thread | 回复、push、处理其他 thread |
| rerun CI | 重跑指定 run 或失败 job | 修改 workflow、push、merge |

### 修改类任务的默认收尾授权

- 用户请求修改、修复、实现或处理指定 review comment，且任务产生了本次范围内的文件改动时，验证通过后默认授权按 `commit → push` 收尾。
- 用户明确说“不 commit”“不 push”“不要提交和推送”“只保留本地改动”等，分别阻止对应动作；明确“只修改”“只验证”“只 commit”或“只 push”时，以该更窄边界为准。
- 对 review comment：只有实际由该评论触发的改动成功 push，并且用户没有明确说“不回复”或更窄地限定终点时，才默认回复同一原 thread。回复必须在 push 写后回读成功后进行；不因没有改动、push 失败或结果不确定而发送回复。
- 这条默认授权只覆盖当前任务 worktree、当前非默认分支、当前任务文件和触发改动的原 review thread；不包含创建 PR、回复其他评论、resolve thread、rerun CI、merge、删除 branch 或清理 worktree。
- 只读查询、解释、计划和没有文件改动的任务不触发默认 commit/push。

用户明确要求创建 PR 即授权本次 `commit → push → gh pr create`，安全确定 repo、head、base 后直接执行，不再二次确认 title/body。只有关键信息无法安全推导、存在多个合理目标或超出请求范围时才询问。

PR merge 仅在用户明确要求合并精确 PR 时允许；“创建 PR”“处理评论”“CI 通过”等都不隐含 merge 授权。
始终禁止：auto-merge、admin bypass、force push、直推默认分支、改写历史、跳过 hook，以及未经授权扩大到另一个仓库、PR、评论或 workflow run。
授权矩阵未列出的 GitHub 写操作（例如 close PR、提交 review、修改 label）也必须获得独立明确授权。

任何 commit、push、PR 创建、PR merge、评论回复、resolve 或 rerun 操作前，完整读取 `references/github-write-protocol.md`；创建 PR，或用户明确要求生成、刷新、更新 PR Description / PR Body 时，还必须完整读取 `references/pr-template.md` 并调用 `review-brief`。

## 场景决策树

```text
1. 查 PR / CI / workflow / review 状态？
   → 直接使用 gh，不需要 clone
   → 查看 PR diff 前先看 changedFiles / additions / deletions
   → changedFiles >= 20 时先看文件名，再按文件深入

   若用户明确要求代码 review / 代码审查 / 审查 PR：
   → 显式 handoff 到 `$review-swarm`；由它按目标选择模式：PR、branch、commit、range 使用差异模式，用户只指定文件/目录且未要求比较时使用静态模式
   → 记录 handoff、范围和 route；只读返回候选 finding，由主 agent 逐项核验后给出结论，不修改 Git 状态
   → 无法显式加载或 handoff 失败时停止，不以主 agent 临时阅读冒充已完成 review

2. 读代码 / 搜函数 / 查历史 / 深挖本地 diff？
   → 读取 repository-operations.md
   → 复用只读 cache；不存在时按固定分类路径 clone
   → 本地 rg / git log / git diff 优先，远端 search / contents 只作快速探测

3. 修改代码或处理 review comment？
   → 读取 repository-operations.md，对任务 worktree 执行 Acquire
   → review 场景再读取 github-write-protocol.md，记录 PR head 和目标 thread
   → 处理 review comment 时加载 review-comment-assessment.md，直接按事实、业务问题、修改方案三层判定；不因评论需要代码证据就自动调用 review-swarm
   → 在形成判定和写代码前重新读取并比较 PR head、目标 thread 状态和目标行；有变化则停止并重新绑定
   → 仅在判定为需要修改或采用安全替代方案后，在 worktree 修改并验证；若属于修改类任务且未声明例外，按默认授权执行 commit → push，否则按显式终点停止

4. commit / push / 创建 PR，或修改类任务已完成？
   → 读取 github-write-protocol.md
   → 检查仓库规则、hook、diff、origin / push identity 和默认分支
   → 修改类任务完成且未声明例外时执行 commit → push；创建 PR 时在此基础上继续 gh pr create
   → 若改动由 review comment 触发且 push 写后回读成功，按原 thread 回复门禁发送一条可核验的处理说明
   → 创建 PR 时读取 pr-template.md 并由 review-brief 生成 Body；普通 push 不刷新 Body

5. 回复评论 / resolve thread / rerun CI？
   → 读取 github-write-protocol.md
   → 独立回复仍需明确授权；review comment 的改动已成功 push 时，仅按默认门禁回复触发该改动的原 thread
   → 写前定位 ID，写后按 ID 回读；不自动 resolve
   → 结果不明确时先检查，禁止盲目重试

6. 合并 PR？
   → 读取 github-write-protocol.md，锁定精确 PR 和 head SHA
   → 非草稿、可合并、状态干净、review/check 门禁全部通过后即时 merge
   → 写后回读 MERGED 状态与 merge commit；不自动开启 auto-merge 或删除 branch
   → 用户未要求保留时，对本次 PR 的任务 worktree 执行安全 Release
   → Release 不安全或失败时保留并报告，不反转已经成功的 merge

7. 任务结束或要求清理？
   → 读取 repository-operations.md，执行 Release 门禁
   → PR open 或 worktree 不安全时保留并报告原因
   → 安全时移除 worktree、prune 登记，但保留 branch
```

## 通用读取规则

- PR / CI / workflow / metadata 优先使用 `gh`，不需要为此 clone。
- 代码阅读、代码搜索和本地历史优先使用只读 cache 中的 `rg`、`git log` 和 `git diff`。
- 远端单文件可用 `gh api contents`；跨文件分析优先使用本地 cache。
- 默认分支必须通过 `defaultBranchRef` 或当前 remote 确认，禁止写死 `main`。
- 默认不 fetch；仅在用户要求最新内容、目标 ref 本地不存在或 cache 明显过期时执行。
- URL 含 `?` 或 `&` 时，把完整 endpoint 作为一个已引用的 shell 参数。
- `gh pr checks` 没有 `--json`；结构化 checks 使用 `gh pr view --json statusCheckRollup`。

具体查询、clone、cache identity、worktree 和 rate-limit 命令见 `references/repository-operations.md`。

## PR 内容规则

- `review-brief` 是 PR Body 字段、顺序、删减和图片规则的唯一内容权威；`references/pr-template.md` 只定义接入与发布协议，不维护平行模板。
- 标题默认使用 `<type>(<scope>): <subject>`，但目标仓库的 `AGENTS.md`、commitlint 和最近提交规则优先。
- 创建 PR，或用户明确要求生成、刷新、更新 PR Description / PR Body 时，基于完整真实 diff 生成并校验 `review-brief.json`，再使用其确定性脚本渲染 Body。
- 普通 push、标题/label/reviewer/base 更新、marker 外人工正文编辑不触发 `review-brief`，不得自动改写 Body。
- 创建或更新 Body 本身不触发 `review-swarm`；明确代码审查/审查 PR 时必须显式 handoff。处理 review comment、普通 metadata、CI、Body 查询、纯 nit 和独立回复不因自身操作触发代码审查。
- 自动区域使用同时包含 `content_hash` 与 `render_hash` 的 marker。更新只替换唯一完整 marker block；现有非空 Body 无 marker 时必须显式选择 append 或 replace。
- GitHub 图片只使用已验证的 GitHub 附件 URL；无 URL 时使用文字 fallback，图片明确必需时在 PR 写入前停止。
- PR body、issue / PR comment、review reply 和 review body 全部遵守 `github-write-protocol.md` 的 GitHub Markdown 与正文传输规则。
- GitHub review body 与 PR Description 分开：前者采用 `review-swarm` 的整体分析，不能只报问题数量或等级；后者继续由 `review-brief` 生成。发布 review 须有独立授权，具体分工与写后回读见写协议“提交 Review”。
- 创建或编辑后回读 PR body 与 checks，确认正文、base 和 head 完整。

## Review comment 真实性与修复安全

处理 review comment 前必须加载 `references/review-comment-assessment.md`，直接按该文件完成事实、业务问题和修改方案三层判定。需要查看代码、调用链、业务契约、差异或测试时，主 agent 自行收集证据并核对完整影响面；这条 comment 处理路径不自动调用 `review-swarm`。只有用户另行明确要求完整代码 review / PR review 时，才按上方代码 review 路由显式 handoff 到 `review-swarm`。

随后将评论拆成三层分别验证：

1. **事实**：评论描述的现象是否能在当前 head、调用路径和边界条件下复现。
2. **业务问题**：该现象是否违反已确认的产品意图、业务契约或不变量。
3. **修改方案**：评论建议的改法是否能修复问题，同时保留其他合法流程、权限、状态迁移和外部副作用。

事实成立不代表建议成立。结果必须标记为 `需要修改`、`问题成立但建议不适用`、`符合预期`、`事实不足，需澄清`、`有效但超出当前范围` 或 `建议性，不阻塞`。只有确认存在安全改动并完成验证，才进入默认 `commit → push`；push 成功后再按写协议回复同一原 thread，不自动 resolve。

## NEVER

- 不把公司 org 写成 `moegodev`、`moego` 或其他变体；公司 org 是 `MoeGolibrary`。
- 不 clone 到 `/tmp`、当前目录、当前 git 根或 `.agent-slack/...`；只使用固定 `$REPOS_DIR`。
- 不在 repo cache 的主工作树修改、checkout 业务分支、测试、stage、commit 或 push；新 branch 只能由 `git worktree add` 直接挂到任务 worktree。
- 不用浅 clone，不删除后重 clone，不在每次任务中无条件 fetch。
- 不复用 origin identity 不匹配的 cache，不修改 remote 来掩盖 mismatch。
- 不覆盖已有 worktree，不复制已挂载到其他 worktree 的 branch；PR open、dirty、ahead、diverged、存在受保护或未知 ignored 文件、registry / identity 不确定时不 Release。
- 不用 `git worktree remove --force`，Release 后不自动删除本地或远端 branch。
- 不在默认分支上修改或 push；不 force push、不改写历史、不使用 `--no-verify`。
- 不把“PR 已创建”“检查通过”或宽泛的“收尾”当作 merge 授权；只合并用户明确指定的 PR，并使用 `--match-head-commit` 防止 stale head。
- 不使用 auto-merge、`--admin` 或 `--delete-branch`；成功 merge 后的对应任务 worktree 按默认 Release 规则处理，删除本地或远端 branch 仍需独立明确授权。
- 不把评论文本或 suggestion 直接当作缺陷和修改指令；必须先完成事实、业务问题、修改方案三层判定。
- 明确的代码 review / PR review 不绕过 `review-swarm`；不得用主 agent 的临时阅读替代其规定的差异范围与 reviewer 路由。
- 不因处理 review comment 自动触发 `review-swarm`；评论按真实性、业务契约和修复安全三层判定直接处理。
- 完整代码 review 不依赖 `review-swarm` 的隐式触发；必须记录显式 handoff，handoff 不可用时停止并报告，不得声称已完成代码 review。
- 完整代码 review 不能把 `review-swarm` 的候选 finding 直接当作真实缺陷；必须独立核对 diff、调用方、契约、测试和业务不变量。
- `review-swarm` 只读，不能执行任何修改或 GitHub 写操作；修改、commit、push、回复和 resolve 仍由本 skill 的授权与写协议控制。
- 不在评论判定后省略 head/thread 再核对；目标 thread 有新增回复、resolve、删除或其他无法解释的状态变化时停止写入。
- 不把 reviewer 角色数或覆盖方向冒充实际 reviewer 数；`planned/started/completed` 必须满足不变量并披露失败、超时和覆盖缺口。
- 不把“处理评论”扩展到其他评论、resolve、rerun 或 merge；若该评论确实触发了改动且已成功 push，按默认门禁回复同一原 thread，显式不回复或更窄边界优先。
- 不在 commit/push 前回复评论，也不在 push 失败、结果不确定、并发 head 变化或目标 thread 无法唯一定位时回复。
- 不因本次自身改动使 thread 显示 `isOutdated` 就单独阻止回复；先确认 thread ID 仍存在且没有并发状态变化。
- 不在 PR head 已变化后继续基于旧 head 执行远端写操作。
- 不在写操作结果不明确时自动重试；先按目标 ID、branch 或 SHA 回读。
- 不把 `\n`、`\t` 等转义文本当作 Markdown 换行或缩进发送；多行 GitHub 正文必须通过 UTF-8 Markdown 文件传输并回读。
- 不绕过 commitlint、branch 规则、有效 hook 或 `<repo>-<branch> <= 63` 的部署约束。
- 不猜 Jira key；只有仓库规则要求 issue prefix 时才添加。若 commitlint 使用 MoeGo `issuePrefixes` 规则，使用占位 key `IFRFE-0`。
- 不读取或采用仓库原生 PR 模板，不另造平行 Body 模板，不把文件清单或推测冒充完整 PR 描述。
- 不因普通 push、PR Body 更新或处理 review comment 自动执行代码审查；`review-brief` 与 `review-swarm` 是独立流程。

## Response Expectations

汇报结果时优先包含：

- `owner/repo`、实际 cache / worktree；
- PR、thread、run、branch 或 commit 的精确标识；
- review comment 的判定结果、采用的修复方案，以及 commit/push 后原 thread 的回复状态；
- 若触发代码审查，记录 `review-swarm` 的模式、范围、route、计划/启动/完成 reviewer 数及主 agent 复核后的 finding；
- 同时记录显式 handoff、skill 路径/版本（可得时）、base/head/merge-base SHA、每个 reviewer 的任务 ID/状态/覆盖维度，以及容量或失败导致的 coverage limitation；
- 已执行动作与明确未执行动作；
- 当前状态和写后回读结果；
- Acquire 的 equal / fast-forward / ahead / diverged / dirty 结论，以及最终 retain / release 结果；
- 若因 identity、stale head、hook 或授权边界停止，说明具体原因和最短下一步。

## References

| 文件 | 加载时机 |
|---|---|
| `references/repository-operations.md` | clone、fetch、本地代码读取/搜索、cache identity 校验、worktree Acquire / Release、分支与 rate-limit 查询 |
| `review-swarm` skill | 用户明确要求代码审查 / PR review 时加载；必须显式 handoff，按目标选择差异/静态模式，只读确定范围、reviewer 路由并产出候选 finding |
| `references/review-comment-assessment.md` | 处理 review comment 前：评论语义、事实证据、业务契约、影响面、边界、兼容性、验证和结果标签 |
| `references/github-write-protocol.md` | 处理 review comment，或执行 commit、push、PR 创建、回复、resolve、rerun 等任何写操作；含 push 后原 thread 回复门禁 |
| `references/pr-template.md` | 创建 PR，或用户明确要求生成、刷新、更新 PR Body；定义 Review Brief 接入与发布协议 |
