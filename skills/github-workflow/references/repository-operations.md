# Repository Operations

本文件负责 GitHub 只读查询、本地 repo cache 和任务 worktree。授权边界与硬性禁止事项以 `SKILL.md` 为准。

## Contents

- [固定目录与分类](#固定目录与分类)
- [确定仓库身份](#确定仓库身份)
- [复用或 clone cache](#复用或-clone-cache)
- [只读查询](#只读查询)
- [Acquire：创建、同步或复用 worktree](#acquire创建同步或复用-worktree)
- [Release：安全释放 worktree](#release安全释放-worktree)
- [分支规则](#分支规则)
- [Local vs Remote](#local-vs-remote)

## 固定目录与分类

```bash
REPOS_DIR=/Users/moego-winches/Desktop/Company/person/agent-workspace/repo
WORKTREES_DIR="$REPOS_DIR/$CATEGORY/worktrees"
```

分类规则：

| 仓库 | `CATEGORY` |
|---|---|
| 公司前端项目 | `front-end` |
| 公司后端项目 | `back-end` |
| 暂时无法分类的公司项目 | `unclear` |
| `winchesHe` 个人项目 | `person` |

repo cache 位于 `$REPOS_DIR/$CATEGORY/$REPO`；每个 category 的 worktree 根位于 `$REPOS_DIR/$CATEGORY/worktrees`，任务 worktree 位于 `$WORKTREES_DIR/$REPO/$BRANCH`。

## 确定仓库身份

公司仓库 owner 是 `MoeGolibrary`；个人仓库 owner 是 `winchesHe`。用户给出 URL、当前 remote 或完整 `owner/repo` 时，以解析结果为准；无法安全确认时先询问，禁止猜测。

```bash
REPO_INPUT='<owner/repo-or-url>'
NAME_WITH_OWNER=$(gh repo view "$REPO_INPUT" --json nameWithOwner --jq .nameWithOwner)
OWNER=${NAME_WITH_OWNER%%/*}
REPO=${NAME_WITH_OWNER#*/}
DEFAULT_BRANCH=$(gh repo view "$NAME_WITH_OWNER" --json defaultBranchRef --jq .defaultBranchRef.name)
```

当前本地仓库没有显式输入时，可从当前 remote 解析：

```bash
NAME_WITH_OWNER=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
OWNER=${NAME_WITH_OWNER%%/*}
REPO=${NAME_WITH_OWNER#*/}
```

## 复用或 clone cache

任何 clone 前都执行下面的检查。已有路径必须是 Git 仓库，并且 `origin` 必须精确解析为目标 `$OWNER/$REPO`。

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

ORIGIN_URL=$(git -C "$CACHE" remote get-url origin) || {
  echo "cache has no readable origin: $CACHE" >&2
  exit 1
}
CACHE_NAME_WITH_OWNER=$(gh repo view "$ORIGIN_URL" --json nameWithOwner --jq .nameWithOwner) || {
  echo "cannot resolve cache origin: $CACHE" >&2
  exit 1
}
if [ "$CACHE_NAME_WITH_OWNER" != "$OWNER/$REPO" ]; then
  echo "cache origin mismatch: expected $OWNER/$REPO, got $CACHE_NAME_WITH_OWNER" >&2
  exit 1
fi

git -C "$CACHE" status --short --branch
```

命中本地 cache 时直接复用，禁止删除重建。不要使用 `--depth`。只有以下情况才 fetch：

- 用户明确要求最新代码；
- 目标 commit、PR ref 或 branch 本地不存在；
- 任务依赖近期变化，而 cache 明显过期。

尽量精确 fetch 所需 ref，不无条件更新全部 remote refs。

## 只读查询

### PR 与 diff

```bash
gh pr list --repo "$OWNER/$REPO" --search '<keyword>' --state all \
  --json number,title,state,url

gh search prs '<keyword>' --owner MoeGolibrary \
  --json number,title,repository,url

gh pr view '<number>' --repo "$OWNER/$REPO" \
  --json number,title,body,state,mergedAt,reviewDecision,changedFiles,additions,deletions,url,statusCheckRollup

gh pr diff '<number>' --repo "$OWNER/$REPO" --name-only
gh pr diff '<number>' --repo "$OWNER/$REPO"
```

先读取 `changedFiles / additions / deletions`。`changedFiles >= 20` 时先看 `--name-only`，再按相关文件深入。

### CI 与 workflow

```bash
gh pr checks '<number>' --repo "$OWNER/$REPO"
gh pr view '<number>' --repo "$OWNER/$REPO" --json statusCheckRollup
gh run list --repo "$OWNER/$REPO" --limit 10
gh run view '<run-id>' --repo "$OWNER/$REPO" --log-failed
```

### Commit、代码与远端文件

```bash
gh pr list --repo "$OWNER/$REPO" --state merged --limit 10 \
  --json number,title,mergedAt,url

gh api "repos/$OWNER/$REPO/commits?per_page=10" \
  --jq '.[] | "\(.sha[0:7]) \(.commit.message | split("\n")[0])"'

gh search code '<name>' --owner MoeGolibrary --json path,repository

gh api "repos/$OWNER/$REPO/contents/<path>" \
  -H 'Accept: application/vnd.github.raw'

gh api "repos/$OWNER/$REPO/compare/<base>...<head>" \
  --jq '{commits: (.commits | length), files: [.files[].filename]}'
```

本地已有 cache 时，代码搜索优先使用 `rg`，历史追踪优先使用 `git log` / `git blame`。`gh search code` 只在本地没有仓库或快速跨仓探测时使用。

### Rate limit

```bash
gh api rate_limit --jq '{core: .resources.core.remaining, search: .resources.search.remaining}'
```

Search API 和 Code Search 限流较严；同一轮避免重复搜索。

## Acquire：创建、同步或复用 worktree

每次开始或恢复写任务都执行 Acquire。它不是“目录存在就继续”，而是先精确更新目标 remote-tracking ref，再根据真实 Git 状态决定复用、fast-forward、保留或停止。创建 worktree 前必须已经通过 cache identity 校验，并确认默认分支；新建 branch 时还要先完成下方“分支规则”检查。

若任务来自已有 PR，先锁定 PR head。`BRANCH` 必须取 `headRefName`，开始修改前 worktree HEAD 必须等于本轮读取的 `headRefOid`：

```bash
PR_HEAD_NAME=$(gh pr view "$PR_NUMBER" --repo "$OWNER/$REPO" \
  --json headRefName --jq .headRefName)
PR_HEAD_OID=$(gh pr view "$PR_NUMBER" --repo "$OWNER/$REPO" \
  --json headRefOid --jq .headRefOid)
BRANCH="$PR_HEAD_NAME"
```

先精确判断远端 branch 是否存在。只有状态码 `2` 表示不存在，其他非零值都必须停止：

```bash
REMOTE_BRANCH_STATUS=0
git -C "$CACHE" ls-remote --exit-code --heads origin "refs/heads/$BRANCH" >/dev/null \
  || REMOTE_BRANCH_STATUS=$?

if [ "$REMOTE_BRANCH_STATUS" -eq 0 ]; then
  git -C "$CACHE" fetch origin \
    "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
elif [ "$REMOTE_BRANCH_STATUS" -ne 2 ]; then
  echo "cannot inspect remote branch: origin/$BRANCH" >&2
  exit "$REMOTE_BRANCH_STATUS"
fi
```

然后创建或验证 worktree。cache 主工作树只作为 source，不 checkout 业务分支、不修改文件；`git worktree add -b` 创建的 branch ref 必须直接挂到目标任务 worktree：

```bash
BRANCH='<feature-or-bugfix-branch>'
WORKTREES_DIR="$REPOS_DIR/$CATEGORY/worktrees"
WORKTREE="$WORKTREES_DIR/$REPO/$BRANCH"

BRANCH_WORKTREE=$(git -C "$CACHE" worktree list --porcelain | awk -v ref="refs/heads/$BRANCH" '
  /^worktree / { path = substr($0, 10) }
  $0 == "branch " ref { print path; exit }
')

if [ -e "$WORKTREE" ]; then
  REGISTERED_WORKTREE=$(git -C "$CACHE" worktree list --porcelain | awk -v target="$WORKTREE" '
    /^worktree / { path = substr($0, 10) }
    path == target { print path; exit }
  ')
  if [ "$REGISTERED_WORKTREE" != "$WORKTREE" ]; then
    echo "target path is not a registered worktree: $WORKTREE" >&2
    exit 1
  fi
  if [ -n "$BRANCH_WORKTREE" ] && [ "$BRANCH_WORKTREE" != "$WORKTREE" ]; then
    echo "branch is already checked out at: $BRANCH_WORKTREE" >&2
    exit 1
  fi
  WORKTREE_BRANCH=$(git -C "$WORKTREE" symbolic-ref --quiet --short HEAD) || {
    echo "target worktree is detached: $WORKTREE" >&2
    exit 1
  }
  if [ "$WORKTREE_BRANCH" != "$BRANCH" ]; then
    echo "worktree branch mismatch: expected $BRANCH, got $WORKTREE_BRANCH" >&2
    exit 1
  fi
else
  if [ -n "$BRANCH_WORKTREE" ]; then
    echo "branch is already checked out at: $BRANCH_WORKTREE" >&2
    exit 1
  fi

  mkdir -p "$(dirname "$WORKTREE")"
  if git -C "$CACHE" show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git -C "$CACHE" worktree add "$WORKTREE" "$BRANCH"
  else
    if [ "$REMOTE_BRANCH_STATUS" -eq 0 ]; then
      git -C "$CACHE" worktree add --track -b "$BRANCH" \
        "$WORKTREE" "origin/$BRANCH"
    elif [ "$REMOTE_BRANCH_STATUS" -eq 2 ]; then
      git -C "$CACHE" fetch origin \
        "refs/heads/$DEFAULT_BRANCH:refs/remotes/origin/$DEFAULT_BRANCH"
      git -C "$CACHE" worktree add -b "$BRANCH" \
        "$WORKTREE" "origin/$DEFAULT_BRANCH"
    else
      echo "cannot inspect remote branch: origin/$BRANCH" >&2
      exit "$REMOTE_BRANCH_STATUS"
    fi
  fi
fi
```

worktree 就绪后先检查脏状态，再分类本地与远端关系：

```bash
git -C "$WORKTREE" status --short --branch

if [ -n "$(git -C "$WORKTREE" status --porcelain)" ]; then
  echo "Acquire retained dirty worktree; automatic sync stopped: $WORKTREE" >&2
  exit 1
fi

if [ "$REMOTE_BRANCH_STATUS" -eq 0 ]; then
  set -- $(git -C "$WORKTREE" rev-list --left-right --count \
    "HEAD...origin/$BRANCH")
  AHEAD=$1
  BEHIND=$2

  if [ "$AHEAD" -eq 0 ] && [ "$BEHIND" -eq 0 ]; then
    ACQUIRE_STATE=equal
  elif [ "$AHEAD" -eq 0 ]; then
    git -C "$WORKTREE" merge --ff-only "origin/$BRANCH"
    ACQUIRE_STATE=fast-forwarded
  elif [ "$BEHIND" -eq 0 ]; then
    echo "Acquire retained worktree with $AHEAD unpushed commit(s)" >&2
    exit 1
  else
    echo "Acquire stopped: local and origin/$BRANCH diverged ($AHEAD ahead, $BEHIND behind)" >&2
    exit 1
  fi
else
  ACQUIRE_STATE=local-only
fi

CURRENT_HEAD=$(git -C "$WORKTREE" rev-parse HEAD)
if [ -n "${PR_HEAD_OID:-}" ] && [ "$CURRENT_HEAD" != "$PR_HEAD_OID" ]; then
  echo "Acquire stopped: expected PR head $PR_HEAD_OID, got $CURRENT_HEAD" >&2
  exit 1
fi

echo "Acquire: $ACQUIRE_STATE $WORKTREE @ $CURRENT_HEAD" >&2
```

分类处理原则：

| 状态 | 处理 |
|---|---|
| `equal` | 直接复用 |
| `behind` | 只允许 `merge --ff-only`，成功后继续 |
| `ahead` | 保留并报告未 push commit；不得把它说成最新 PR head，也不得自动丢弃 |
| `diverged` | 保留并停止；不得自动 rebase、merge、reset 或 force push |
| `dirty` | 保留并停止自动同步；不得覆盖已有改动 |
| `local-only` | 只用于确认的新 branch；恢复 PR 时远端 branch 缺失必须停止 |

如果 PR 的 worktree 目录已经被清理，只要 branch 没有挂载在其他 worktree，就按上述流程从精确 fetch 的 `origin/$BRANCH` 重建；重建后必须验证 `HEAD == PR_HEAD_OID`。这使后续 review 调整既能复用现有 worktree，也能安全恢复，不依赖旧目录一直存在。

## Release：安全释放 worktree

创建 PR 不是 Release 时机。只要同一 branch 仍有 open PR，worktree 默认保留，后续调整重新执行 Acquire：

```bash
OPEN_PRS=$(gh pr list --repo "$OWNER/$REPO" --head "$BRANCH" --state open \
  --json number,url,headRefName,headRefOid)
if [ "$(printf '%s' "$OPEN_PRS" | jq 'length')" -gt 0 ]; then
  echo "Release skipped: PR is still open; retain $WORKTREE" >&2
  exit 0
fi
```

Release 有两种触发方式：

- **自动 Release**：用户明确要求合并 PR、未要求保留 worktree，且写后回读确认同一 `headRefOid` 已 `MERGED`。merge 本身即授权清理该 PR 对应的任务 worktree，不再二次询问。
- **显式 Release**：PR closed / 明确放弃，或其他任务结束场景中，用户明确要求结束或清理。

PR 仍 open、merge 回读不确定或用户明确要求保留时不得自动 Release。Release 只针对本次 PR / task 已锁定的精确 worktree；没有对应 worktree 时返回 `not applicable`，不得选择同仓其他目录代替。

### Release 门禁

按顺序执行，任一步不满足都保留 worktree 并报告精确原因：

1. **终态与开放 PR**：自动 Release 必须满足 `state == MERGED`、`mergedAt` 非空、`headRefOid == PR_HEAD_OID`；同一 branch 不得存在其他 open PR。
2. **路径与身份**：规范化后的 `WORKTREE` 必须位于精确的 `$WORKTREES_DIR/$REPO/` 下，不能等于 repo cache、主 checkout、`$WORKTREES_DIR` 或其他宽泛目录。重新校验 `owner/repo`、branch 与 worktree 登记关系。
3. **registry**：优先使用标准 `$CACHE` 的 worktree registry。为兼容历史 worktree，若标准 cache 未登记但目标目录自身可解析 `git-common-dir`，只在该 registry 的 origin 仍精确等于 `$OWNER/$REPO`、目标路径已登记且 branch 完全匹配时继续；否则保留，禁止跨 registry 猜测。
4. **工作区内容**：`git status --porcelain --untracked-files=all` 必须为空。再用 `git ls-files --others --ignored --exclude-standard` 检查 ignored 文件；`.env` / `.env.*`（已跟踪的 `.env.example` 除外）、认证文件、session、journal、checkpoint、下载证据及任何未知 ignored 文件都视为受保护内容并阻断 Release。只有明确可重建的 `.venv/`、`node_modules/`、`__pycache__/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、`dist/`、`build/`、`coverage/` 与 `.coverage` 可作为 disposable cache 忽略。
5. **提交关系**：精确查询并 fetch 远端 branch。远端存在时 `ahead` 必须为 `0`，diverged 或查询不确定时保留；behind-only 不阻断 Release。远端已不存在时，只能在任务终态确定、worktree `HEAD == PR_HEAD_OID` 且对应本地 branch 仍存在时继续。
6. **删除方式**：只执行普通 `git worktree remove`，禁止 `--force`。命令拒绝、超时或结果不明确时先回读路径和登记状态，不盲目重试。

### Release 执行与回读

`WORKTREE_REGISTRY` 是完成上述 registry 校验后的真实 common git dir；标准 worktree 使用 `$CACHE` 的 registry，历史 worktree 使用已验证的 `git-common-dir`：

```bash
test -z "$(git -C "$WORKTREE" status --porcelain --untracked-files=all)" || {
  echo "Release skipped: worktree is dirty" >&2
  exit 1
}

# 在执行前按门禁分类检查 ignored 文件；受保护或未知项必须使 Release 停止。
git -C "$WORKTREE" ls-files --others --ignored --exclude-standard

if [ "$REMOTE_BRANCH_STATUS" -eq 0 ]; then
  set -- $(git -C "$WORKTREE" rev-list --left-right --count \
    "HEAD...origin/$BRANCH")
  AHEAD=$1
  BEHIND=$2
  if [ "$AHEAD" -ne 0 ]; then
    echo "Release skipped: worktree has $AHEAD unpushed commit(s)" >&2
    exit 1
  fi
fi

git --git-dir="$WORKTREE_REGISTRY" worktree remove "$WORKTREE"
git --git-dir="$WORKTREE_REGISTRY" worktree prune

test ! -e "$WORKTREE"
git --git-dir="$WORKTREE_REGISTRY" show-ref --verify --quiet "refs/heads/$BRANCH"
```

最后必须回读 worktree 路径已消失、registry 已 prune、本地 branch 仍存在；远端 branch 在执行前存在时还要确认它仍存在。Release 只回收工作目录和过期登记，不删除本地或远端 branch。自动 Release 失败是 merge 后的 best-effort 收尾失败：报告 `MERGED + retained` 和阻断原因，不把已经成功的 merge 反转为失败。

## 分支规则

创建新 branch 前读取目标仓库规则和已有 branch 命名。若存在 `git-branch-is`，按仓库配置校验；当前 MoeGo 通用校验可使用：

```bash
./node_modules/.bin/git-branch-is -r "^(feature|bugfix)-([0-9a-z.-]+)|main$|staging$|release$|^release-[0-9]{6}$"
```

没有明确规则时沿用最近 branch 风格，不臆造 Jira key。

MoeGo 部署仓库必须保证 `<repo>-<branch>` 不超过 63 字符：

```bash
test $((${#REPO} + 1 + ${#BRANCH})) -le 63
```

检查失败时缩短 branch 后再创建，不在 push 后补救。

## Local vs Remote

| 操作 | 优先方式 |
|---|---|
| PR / CI / workflow metadata | `gh` |
| 代码阅读与搜索 | repo cache 中的 `rg` |
| 历史、blame、本地 diff | repo cache 中的 `git` |
| 修改、测试、commit、push | 任务 worktree 中的 `git` |
| 远端单文件 | `gh api contents` |
| 跨仓代码探测 | 本地 cache 优先，其次 `gh search code` |
