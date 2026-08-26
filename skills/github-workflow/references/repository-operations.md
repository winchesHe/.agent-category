# Repository Operations

本文件负责 GitHub 只读查询、本地 checkout / repo cache，以及风险触发的托管 worktree。授权边界与安全不变量以 `SKILL.md` 为准。

## Contents

- [工作区类型与选择顺序](#工作区类型与选择顺序)
- [确定仓库身份](#确定仓库身份)
- [验证现有 checkout](#验证现有-checkout)
- [复用或 clone cache](#复用或-clone-cache)
- [只读查询](#只读查询)
- [Acquire：验证 writable checkout](#acquire验证-writable-checkout)
- [风险触发的 worktree](#风险触发的-worktree)
- [Release：回收托管 worktree](#release回收托管-worktree)
- [分支规则](#分支规则)
- [Local vs Remote](#local-vs-remote)

## 工作区类型与选择顺序

固定 cache 根目录仍作为没有可用 checkout 时的后备来源：

```bash
REPOS_DIR=/Users/moego-winches/Desktop/Company/person/agent-workspace/repo
CACHE="$REPOS_DIR/$CATEGORY/$REPO"
WORKTREES_DIR="$REPOS_DIR/$CATEGORY/worktrees"
```

分类规则：

| 仓库 | `CATEGORY` |
|---|---|
| 公司前端项目 | `front-end` |
| 公司后端项目 | `back-end` |
| 暂时无法分类的公司项目 | `unclear` |
| `winchesHe` 个人项目 | `person` |

本地目录按以下顺序选择：

1. 用户明确指定的 checkout；
2. 当前目录或当前任务上下文中的 identity 匹配 checkout；
3. 已存在的其他安全 checkout；
4. 固定只读 cache；
5. clone 到固定 cache。

不要因为仓库属于 `MoeGolibrary` 就自动创建 worktree，也不要因为属于 `winchesHe` 就降低检查。是否隔离由并发、dirty ownership、branch 占用和 PR head 精确性决定。

## 确定仓库身份

公司仓库 owner 是 `MoeGolibrary`；个人仓库 owner 是 `winchesHe`。用户给出 URL、当前 remote 或完整 `owner/repo` 时，以解析结果为准；无法安全确认时先询问，禁止猜测。

```bash
REPO_INPUT='<owner/repo-or-url>'
NAME_WITH_OWNER=$(gh repo view "$REPO_INPUT" --json nameWithOwner --jq .nameWithOwner)
OWNER=${NAME_WITH_OWNER%%/*}
REPO=${NAME_WITH_OWNER#*/}
DEFAULT_BRANCH=$(gh repo view "$NAME_WITH_OWNER" --json defaultBranchRef --jq .defaultBranchRef.name)
```

验证任何本地候选目录时，都解析其 fetch 与全部 push URL；它们必须精确指向目标仓库：

```bash
CHECKOUT='<candidate-path>'
git -C "$CHECKOUT" rev-parse --show-toplevel
ORIGIN_URL=$(git -C "$CHECKOUT" remote get-url origin)
CHECKOUT_NAME_WITH_OWNER=$(gh repo view "$ORIGIN_URL" --json nameWithOwner --jq .nameWithOwner)
test "$CHECKOUT_NAME_WITH_OWNER" = "$OWNER/$REPO"
git -C "$CHECKOUT" remote get-url --push --all origin
```

identity 不匹配时停止，不修改 remote 来掩盖 mismatch。

## 验证现有 checkout

读取候选目录的 branch、状态和 worktree 登记：

```bash
git -C "$CHECKOUT" status --short --branch
BRANCH=$(git -C "$CHECKOUT" symbolic-ref --quiet --short HEAD)
git -C "$CHECKOUT" worktree list --porcelain
```

现有 checkout 可直接用于写任务，需要同时满足：

- identity 精确匹配；
- branch 是用户指定或可从任务安全推导的目标 branch；
- 工作区 clean，或所有已有改动都能明确归属于当前任务；
- 没有另一个任务或用户正在并发写入该目录；
- 该目录不是固定 cache，也未被用户声明为只读。

dirty 改动无法区分归属时停止。不要为了获得 clean 状态而 stash、reset、checkout 文件或复制改动。branch 不匹配且目录 dirty 时不自动切换；目录 clean 时也只切换到已确认的任务 branch。

## 复用或 clone cache

只有没有合适现有 checkout 时才进入固定 cache 流程。cache 主工作树只用于 clone、fetch、读取、搜索、历史和创建 worktree，不用于修改、测试、stage、commit 或 push。

```bash
CACHE="$REPOS_DIR/$CATEGORY/$REPO"

if [ -e "$CACHE" ]; then
  git -C "$CACHE" rev-parse --git-dir >/dev/null 2>&1 || {
    echo "cache path is not a Git repository: $CACHE" >&2
    exit 1
  }
else
  mkdir -p "$(dirname "$CACHE")"
  gh repo clone "$OWNER/$REPO" "$CACHE"
fi
```

复用前按“确定仓库身份”校验 cache origin。命中 cache 时不删除重建。只有以下情况才精确 fetch 所需 ref：

- 用户明确要求最新代码；
- 目标 commit、PR ref 或 branch 本地不存在；
- 开始或恢复写任务，需要判断本地与远端关系；
- cache 明显过期且任务依赖近期变化。

浅 clone 不是通用硬禁止，但共享 cache 默认保留完整历史；只有用户明确需要临时、受限的只读探测时才采用浅 clone，并且不能冒充完整 cache。

## 只读查询

### PR、CI 与 workflow

```bash
gh pr list --repo "$OWNER/$REPO" --search '<keyword>' --state all \
  --json number,title,state,url

gh pr view '<number>' --repo "$OWNER/$REPO" \
  --json number,title,body,state,mergedAt,reviewDecision,changedFiles,additions,deletions,url,statusCheckRollup

gh pr diff '<number>' --repo "$OWNER/$REPO" --name-only
gh pr diff '<number>' --repo "$OWNER/$REPO"
gh pr checks '<number>' --repo "$OWNER/$REPO"
gh run view '<run-id>' --repo "$OWNER/$REPO" --log-failed
```

查看 PR diff 前先读取 `changedFiles / additions / deletions`；`changedFiles >= 20` 时先看文件名，再按相关文件深入。

### Commit、代码与远端文件

```bash
gh api "repos/$OWNER/$REPO/commits?per_page=10" \
  --jq '.[] | "\(.sha[0:7]) \(.commit.message | split("\n")[0])"'

gh search code '<name>' --owner "$OWNER" --json path,repository

gh api "repos/$OWNER/$REPO/contents/<path>" \
  -H 'Accept: application/vnd.github.raw'
```

本地已有 identity 匹配 checkout 时，代码搜索优先使用 `rg`，历史追踪优先使用 `git log` / `git blame`。远端 search / contents 只作快速探测。

## Acquire：验证 writable checkout

每次开始或恢复写任务，都对最终选中的 writable checkout 执行 Acquire。Acquire 不是 worktree 专属流程。

若任务来自已有 PR，先锁定精确 head：

```bash
PR_HEAD_NAME=$(gh pr view "$PR_NUMBER" --repo "$OWNER/$REPO" \
  --json headRefName --jq .headRefName)
PR_HEAD_OID=$(gh pr view "$PR_NUMBER" --repo "$OWNER/$REPO" \
  --json headRefOid --jq .headRefOid)
BRANCH="$PR_HEAD_NAME"
```

精确判断远端 branch 是否存在。只有状态码 `2` 表示不存在，其他非零结果都停止：

```bash
REMOTE_BRANCH_STATUS=0
git -C "$CHECKOUT" ls-remote --exit-code --heads origin "refs/heads/$BRANCH" >/dev/null \
  || REMOTE_BRANCH_STATUS=$?

if [ "$REMOTE_BRANCH_STATUS" -eq 0 ]; then
  git -C "$CHECKOUT" fetch origin \
    "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
elif [ "$REMOTE_BRANCH_STATUS" -ne 2 ]; then
  echo "cannot inspect remote branch: origin/$BRANCH" >&2
  exit "$REMOTE_BRANCH_STATUS"
fi
```

先读取 dirty 状态并确认 ownership，再判断关系。远端 branch 不存在时直接分类为 `local-only`，不要引用不存在的 remote-tracking ref：

```bash
git -C "$CHECKOUT" status --short --branch

if [ "$REMOTE_BRANCH_STATUS" -eq 0 ]; then
  set -- $(git -C "$CHECKOUT" rev-list --left-right --count \
    "HEAD...origin/$BRANCH")
  AHEAD=$1
  BEHIND=$2
else
  ACQUIRE_STATE=local-only
fi
```

处理原则：

| 状态 | 处理 |
|---|---|
| `equal` | 直接继续；存在 task-owned dirty 改动时报告但不覆盖 |
| `behind` | 仅在 clean 时 `merge --ff-only`；dirty 时停止 |
| `ahead` | 保留并报告未 push commit，不自动丢弃或改写 |
| `diverged` | 保留并停止，不自动 rebase、merge、reset 或 force push |
| `local-only` | 仅用于已确认的新 branch；恢复 PR 时远端缺失必须停止 |
| dirty ownership 不明 | 保留并停止 |

PR / review 开始修改前还必须验证：

```bash
CURRENT_HEAD=$(git -C "$CHECKOUT" rev-parse HEAD)
test "$CURRENT_HEAD" = "$PR_HEAD_OID"
```

## 风险触发的 worktree

仅在下列情况创建或复用托管 worktree：并发写任务、无关 dirty 状态、branch 被其他目录占用、精确 PR 隔离、用户明确要求，或只有只读 cache 可用。

托管路径保持可预测：

```bash
WORKTREE="$WORKTREES_DIR/$REPO/$BRANCH"
```

创建前确认 branch 是否已挂载，禁止复制同一 branch 或覆盖已有目录：

```bash
BRANCH_WORKTREE=$(git -C "$CACHE" worktree list --porcelain | awk -v ref="refs/heads/$BRANCH" '
  /^worktree / { path = substr($0, 10) }
  $0 == "branch " ref { print path; exit }
')

if [ -n "$BRANCH_WORKTREE" ]; then
  echo "branch is already checked out at: $BRANCH_WORKTREE" >&2
  exit 1
fi

mkdir -p "$(dirname "$WORKTREE")"
if git -C "$CACHE" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git -C "$CACHE" worktree add "$WORKTREE" "$BRANCH"
elif [ "$REMOTE_BRANCH_STATUS" -eq 0 ]; then
  git -C "$CACHE" worktree add --track -b "$BRANCH" \
    "$WORKTREE" "origin/$BRANCH"
else
  git -C "$CACHE" fetch origin \
    "refs/heads/$DEFAULT_BRANCH:refs/remotes/origin/$DEFAULT_BRANCH"
  git -C "$CACHE" worktree add -b "$BRANCH" \
    "$WORKTREE" "origin/$DEFAULT_BRANCH"
fi
```

创建后立即执行 Acquire，并在汇报中说明哪项风险触发了隔离以及预期何时 Release。PR worktree 已被安全释放时，可从精确 `origin/$BRANCH` 重建；重建后仍需验证 `HEAD == PR_HEAD_OID`。

## Release：回收托管 worktree

Release 只处理 Skill 创建的托管 worktree。用户 checkout 永远不因任务结束而自动移除。

满足以下条件时，托管 worktree 可以在任务结束后释放：

1. cache identity、worktree 注册路径和 branch 都精确匹配；
2. `git status --porcelain` 为空；
3. 远端查询结果明确；
4. 远端 branch 存在时 `ahead == 0`，因此提交可以从远端恢复；
5. open PR 存在时，当前 `HEAD` 等于本轮确认的 PR `headRefOid`；
6. 用户没有明确要求保留。

open PR 不是保留物理目录的充分理由。只要 clean、fully pushed 且精确 head 可从远端恢复，就可以释放；后续 review 重新 Acquire 或重建。

```bash
test -z "$(git -C "$WORKTREE" status --porcelain)" || {
  echo "Release skipped: worktree is dirty" >&2
  exit 1
}

if [ "$REMOTE_BRANCH_STATUS" -eq 0 ]; then
  set -- $(git -C "$WORKTREE" rev-list --left-right --count \
    "HEAD...origin/$BRANCH")
  AHEAD=$1
  test "$AHEAD" -eq 0 || {
    echo "Release skipped: worktree has $AHEAD unpushed commit(s)" >&2
    exit 1
  }
fi

git -C "$CACHE" worktree remove "$WORKTREE"
git -C "$CACHE" worktree prune
test ! -e "$WORKTREE"
```

dirty、ahead、diverged、远端状态不明或 PR head 不一致时保留并报告。不要使用 `git worktree remove --force`。

Release 默认保留本地和远端 branch。用户明确要求完整清理时，可在确认没有 worktree、没有未 push commit、远端可恢复或任务已明确终结后删除本地 branch；删除远端 branch 需要单独精确授权。

## 分支规则

创建新 branch 前读取目标仓库规则和已有 branch 命名。若存在 `git-branch-is`，按仓库配置校验。没有明确规则时沿用最近 branch 风格，不臆造 Jira key。

MoeGo 部署仓库必须保证 `<repo>-<branch>` 不超过 63 字符：

```bash
test $((${#REPO} + 1 + ${#BRANCH})) -le 63
```

## Local vs Remote

| 操作 | 优先方式 |
|---|---|
| PR / CI / workflow metadata | `gh` |
| 代码阅读与搜索 | identity 匹配的现有 checkout；其次只读 cache |
| 历史、blame、本地 diff | 现有 checkout / cache 中的 `git` |
| 修改、测试、commit、push | Acquire 通过的 writable checkout |
| 并发、无关 dirty 或精确 PR 隔离 | 托管 worktree |
| 远端单文件 | `gh api contents` |
| 跨仓代码探测 | 本地优先，其次 `gh search code` |
