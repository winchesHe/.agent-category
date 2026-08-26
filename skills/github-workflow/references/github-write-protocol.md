# GitHub Write Protocol

本文件负责 review comment、commit、push、PR 创建、PR merge、回复、resolve 和 workflow rerun。先服从 `SKILL.md` 的授权矩阵；只有用户请求到达对应终点时才执行该写操作。

## Contents

- [写操作前置契约](#写操作前置契约)
- [Review 证据与 stale head](#review-证据与-stale-head)
- [GitHub Markdown 与正文传输](#github-markdown-与正文传输)
- [Commit](#commit)
- [Push](#push)
- [高风险分支写入](#高风险分支写入)
- [创建 PR](#创建-pr)
- [合并 PR](#合并-pr)
- [回复、resolve 与 rerun](#回复resolve-与-rerun)
- [不确定结果与跨仓任务](#不确定结果与跨仓任务)

## 写操作前置契约

任何写操作前都必须：

1. 确认精确的 `owner/repo`、默认分支、当前 branch 和用户授权终点。
2. 完整读取目标仓库 `AGENTS.md`；缺失时读取 `CLAUDE.md`；随后完整读取存在的 `CONTEXT.md`。
3. 确认当前目录是 `references/repository-operations.md` 完成 Acquire 的 writable checkout，而不是只读 cache。
4. 读取 `git status --short --branch`、remote 和 worktree 列表，保留所有无关改动。
5. 只 stage、commit、push 当前任务范围；发现无法区分的已有改动时停止并报告。

用户凭据拥有的权限不能扩展请求授权。默认分支直推、`--force-with-lease`、历史改写、auto-merge、admin bypass、跳过 hook 和删除 branch 都属于高风险动作，只有用户逐项点名精确目标且仓库治理允许时才执行。裸 `--force` 和 `git worktree remove --force` 不使用。

## Review 证据与 stale head

处理 review comment 前读取 PR metadata，并保存开始时的 `headRefOid`：

```bash
PR_NUMBER='<number>'

gh pr view "$PR_NUMBER" --repo "$OWNER/$REPO" \
  --json number,title,url,state,baseRefName,headRefName,headRefOid,reviewDecision,changedFiles,additions,deletions,statusCheckRollup
```

随后用 `headRefName` Acquire 安全 writable checkout。开始修改前必须满足 `git rev-parse HEAD == headRefOid`；现有 checkout 无法满足或需要并发隔离时，才创建或重建托管 worktree，并验证同一等式。dirty ownership 不明、ahead 或 diverged 的目录必须保留并停止，不能覆盖或假装已同步。

区分并读取四类讨论证据：

```bash
# conversation comments
gh api --paginate "repos/$OWNER/$REPO/issues/$PR_NUMBER/comments?per_page=100"

# review submissions
gh api --paginate "repos/$OWNER/$REPO/pulls/$PR_NUMBER/reviews?per_page=100"

# inline review comments
gh api --paginate "repos/$OWNER/$REPO/pulls/$PR_NUMBER/comments?per_page=100"
```

REST API 不提供完整 thread 状态。需要 thread ID、`isResolved` 或 `isOutdated` 时使用 GraphQL 分页，并按 ID 去重：

```bash
REVIEW_TMP_DIR=$(mktemp -d)

gh api graphql --paginate --slurp \
  -F owner="$OWNER" \
  -F name="$REPO" \
  -F number="$PR_NUMBER" \
  -f query='query($owner:String!, $name:String!, $number:Int!, $endCursor:String) {
    repository(owner:$owner, name:$name) {
      pullRequest(number:$number) {
        reviewThreads(first:100, after:$endCursor) {
          nodes {
            id isResolved isOutdated path line
            comments(first:100) {
              nodes { id body createdAt updatedAt url author { login } }
            }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
  }' > "$REVIEW_TMP_DIR/review-thread-pages.json"

jq '[.[].data.repository.pullRequest.reviewThreads.nodes[]]
    | unique_by(.id)
    | sort_by(.path, (.line // 0), .id)' \
  "$REVIEW_TMP_DIR/review-thread-pages.json"
```

把 comment / thread 快照放在 writable checkout 外的临时目录，不提交这些文件。

用户指定评论时，用 thread ID、comment ID、文件和行号锁定目标，不扩展到其他意见。修改并验证后重新读取 PR 的 `headRefOid` 和目标 thread：

- head 未变化且目标仍有效：可以继续到用户已授权的下一步；
- head 已变化、thread 已 outdated，或目标状态无法确认：报告 stale 状态并停止远端写入；
- “处理评论”本身只授权安全 writable checkout 内修改和验证，不授权 commit、push、回复或 resolve。

## GitHub Markdown 与正文传输

本节适用于 PR body、issue / PR comment、review reply 和 review body。格式正确需要同时满足：Markdown 源文正确、API 收到真实字符、写后回读与源文一致。

### 强制传输流程

1. 先把完整正文写入 writable checkout 外的临时 UTF-8 `.md` 文件；在 Codex 中使用 `apply_patch`，不要用 shell 拼接正文。
2. 多行正文必须包含真实 LF 换行。禁止把单引号字符串里的 `\n`、`\r\n`、`\t` 当作换行或缩进；它们会被 GitHub 原样显示。
3. 发送前完整读取源文件，确认段落、列表、围栏和空行；复杂表格、折叠块或代码围栏先调用 GitHub Markdown API 预渲染。
4. 用文件参数发送，不把多行正文内联进命令。PR 使用 `--body-file`；`gh api` 的 `-F key=@file` 会读取文件内容。
5. 写后按 PR、comment 或 thread ID 回读 `body`，与源文件比较；除单个结尾换行外必须一致。发现字面量 `\n`、断裂围栏、空列表或错误表格时，报告失败，不把写入视为完成，也不盲目重试。

预渲染复杂正文：

```bash
BODY_FILE='<absolute-temp-markdown-file>'

gh api markdown \
  -F "text=@$BODY_FILE" \
  -f mode=gfm \
  -f context="$OWNER/$REPO"
```

文件传输示例：

```bash
# REST comment body
gh api "repos/$OWNER/$REPO/issues/$PR_NUMBER/comments" \
  -F "body=@$BODY_FILE"

# GraphQL body variable
gh api graphql \
  -F threadId="$THREAD_ID" \
  -F "body=@$BODY_FILE" \
  -f query='<mutation>'

# PR body
gh pr create --repo "$OWNER/$REPO" \
  --base "$BASE_BRANCH" --head "$BRANCH" \
  --title '<title>' --body-file "$BODY_FILE"
```

### 常用 GitHub Flavored Markdown

| 目的 | 正确源文 | 约束 |
|---|---|---|
| 段落 | 两段之间留一个空行 | 不用字面量 `\n\n` |
| 标题 | `## 标题` | `#` 后留空格；评论通常从 `##` 开始 |
| 粗体 / 斜体 / 删除线 | `**粗体**`、`_斜体_`、`~~删除~~` | 定界符成对，不跨无关段落 |
| 行内代码 | `` `pnpm test` `` | 内容含反引号时改用双反引号或代码块 |
| 引用 | `> 原评论` | 每个引用段落行都以 `>` 开头 |
| 无序列表 | `- 项目` | 正文与列表之间留空行；每项使用真实新行 |
| 有序列表 | `1. 第一步` | 每项独占一行；嵌套项保持一致缩进 |
| 任务列表 | `- [ ] 待办`、`- [x] 完成` | 方括号和状态字符格式固定 |
| 链接 | `[说明](https://example.com)` | URL 含空格或括号时先编码；不要破坏右括号 |
| 图片 | `![替代文本](https://example.com/a.png)` | 必须提供有意义的替代文本 |
| Issue / PR 引用 | `#123`、`owner/repo#123` | 先确认目标；不要引用错误仓库 |
| 用户 / 团队提及 | `@user`、`@org/team` | 会通知对方，只在明确需要时使用 |
| 转义 Markdown | `\*不是斜体\*` | 只转义需要显示的语法字符 |

列表嵌套时用真实空格缩进，并在父项下保持同一层级：

```markdown
- 已处理
  - `openpyxl`：增加 import guard
  - FinTech：改用 GitHub `main` ref

1. 运行定向测试
2. 检查 CI
```

代码块的围栏必须独占一行并标注语言；正文代码中若包含三个反引号，外层改用四个或更长围栏：

````markdown
```bash
pnpm run validate
```
````

表格前后留空行，必须有表头分隔行；单元格里的 `|` 写成 `\|`，需要单元格内换行时使用 `<br>`：

```markdown
| 检查 | 结果 |
|---|---|
| `pnpm run validate` | 通过 |
| CI \| Plugin Integrity | 通过 |
```

### 按需使用的高级格式

- 折叠内容：使用 `<details>` / `<summary>`，`</summary>` 后留空行，确保内部 Markdown 被渲染。
- GitHub Alert：使用 `> [!NOTE]`、`> [!TIP]`、`> [!IMPORTANT]`、`> [!WARNING]` 或 `> [!CAUTION]`，下一行继续 `>`。
- 脚注：正文使用 `[^1]`，文末使用 `[^1]: 说明`。
- Mermaid：使用语言为 `mermaid` 的围栏代码块；只有图比文字更清楚时才使用。
- 数学表达式：行内使用 `$...$`，块级使用 `$$...$$`；普通工程评论不主动使用。
- HTML 注释：`<!-- hidden -->` 只用于不希望渲染的维护信息，不隐藏重要结论。

### 动态内容与语义防护

- 把文件路径、命令、branch、SHA、错误文本等动态值视为不可信 Markdown；优先放入行内代码或代码块，不直接拼进链接、表格分隔符或 HTML。
- 动态值含反引号时，选择更长的行内定界符或围栏；含 `|` 时先转义；多行日志放入围栏代码块。
- 不使用 Markdown 修复错误的数据。链接、PR 编号、SHA、测试结论和提及对象必须先确认真实值。
- `Closes #123`、`Fixes #123`、`Resolves #123` 可能触发 issue 关闭语义，只在用户明确要求关联关闭时使用；普通引用只写 `#123`。
- 发送前检查字面量 `\n` / `\t` 命中；只有明确展示转义字符的代码片段允许保留，普通 prose、列表和表格中出现即停止。

官方语法基线：

- [Basic writing and formatting syntax](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax)
- [Working with advanced formatting](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting)
- [GitHub CLI `gh api`](https://cli.github.com/manual/gh_api)，其中 `-F key=@filename` 从文件读取字段值

## Commit

提交前检查仓库规则、实际 hook 和 diff：

```bash
git status --short --branch
git remote -v
git config --get core.hooksPath || true
git rev-parse --git-path hooks
ls commitlint.config.* .commitlintrc* package.json 2>/dev/null
git diff --check
git diff
git diff --cached
```

执行要求：

- 检查有效的 `pre-commit`、`commit-msg`、`pre-push` hook 和 hook manager 配置，不只看 sample hook。
- commit message 遵守目标仓库规则；若 commitlint 使用 MoeGo `issuePrefixes` 规则，使用占位 key `IFRFE-0`，其他情况不猜或追加 Jira key。
- 只 stage 当前任务文件；提交前复核 staged diff。
- 默认使用普通 `git commit` 并修复 hook 失败原因。只有用户在看到具体 hook 失败和影响后仍明确授权跳过，且仓库规则允许时，才可对本次精确 commit 使用 `--no-verify`；写后必须报告被跳过的 hook。
- commit 后回读 `git status --short --branch` 和 `git rev-parse HEAD`。

## Push

push 前确认用户授权的精确目标 branch，并校验 origin 的全部 push URL：

```bash
test "$BRANCH" != "$DEFAULT_BRANCH"

PUSH_URL_COUNT=0
while IFS= read -r PUSH_URL; do
  [ -n "$PUSH_URL" ] || continue
  PUSH_URL_COUNT=$((PUSH_URL_COUNT + 1))
  PUSH_NAME_WITH_OWNER=$(gh repo view "$PUSH_URL" --json nameWithOwner --jq .nameWithOwner 2>/dev/null) || {
    echo "cannot resolve origin push URL #$PUSH_URL_COUNT" >&2
    exit 1
  }
  if [ "$PUSH_NAME_WITH_OWNER" != "$OWNER/$REPO" ]; then
    echo "origin push URL mismatch: expected $OWNER/$REPO, got $PUSH_NAME_WITH_OWNER" >&2
    exit 1
  fi
done < <(git remote get-url --push --all origin)

if [ "$PUSH_URL_COUNT" -eq 0 ]; then
  echo "origin has no push URL" >&2
  exit 1
fi
```

默认执行普通 push。当前 branch 与目标 branch 相同时：

```bash
git push -u origin "$BRANCH"

LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git ls-remote origin "refs/heads/$BRANCH" | awk '{print $1}')
test "$LOCAL_SHA" = "$REMOTE_SHA"
```

用户明确要求把当前提交推到另一个精确 branch（包括明确点名默认分支）时，先确认仓库规则允许，再执行普通 fast-forward push：

```bash
TARGET_BRANCH='<explicit-target-branch>'
git fetch origin "refs/heads/$TARGET_BRANCH:refs/remotes/origin/$TARGET_BRANCH"
git merge-base --is-ancestor "origin/$TARGET_BRANCH" HEAD
git push origin "HEAD:refs/heads/$TARGET_BRANCH"

LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git ls-remote origin "refs/heads/$TARGET_BRANCH" | awk '{print $1}')
test "$LOCAL_SHA" = "$REMOTE_SHA"
```

默认分支不能从宽泛的“push”“发布”或“收尾”推断，必须由用户明确点名。普通 push 因远端前进而失败时停止并重新 Acquire，不自动 merge、rebase、force 或盲目重试。禁止修改 remote 来通过 identity 校验。

## 高风险分支写入

### `--force-with-lease` 与历史改写

只有用户明确要求改写精确的非默认分支历史时才允许。先保存本轮读取的远端 SHA，确认 branch 不受他人共享，并使用带精确预期值的 lease：

```bash
test "$BRANCH" != "$DEFAULT_BRANCH"
EXPECTED_REMOTE_SHA=$(git ls-remote origin "refs/heads/$BRANCH" | awk '{print $1}')
test -n "$EXPECTED_REMOTE_SHA"

# 完成用户明确授权的 amend / rebase 后再次确认目标，再执行：
git push --force-with-lease="refs/heads/$BRANCH:$EXPECTED_REMOTE_SHA" origin \
  "HEAD:refs/heads/$BRANCH"
```

lease 失败时停止。不要退化为裸 `--force`，也不要自动扩大到默认分支。

### 默认分支、hook 与治理绕过

- 默认分支直推只接受用户明确点名的 `owner/repo` 和 branch；仓库规则要求 PR 时停止，不使用 admin 权限绕过。
- `--no-verify` 只按 Commit 节的 break-glass 条件用于一次精确 commit / push，并报告跳过内容。
- admin bypass 只有用户明确点名目标 PR、当前被阻断的门禁和 `--admin` 意图时才允许；写前回读全部门禁，写后按 PR head 回读。
- 删除本地或远端 branch 必须明确区分目标。删除远端 branch 前确认 PR / 任务终态和远端 SHA，不把 `--delete-branch` 隐含在 merge 中。

## 创建 PR

“提 PR / 创建 PR”明确授权当前改动的 commit、普通 push 和 `gh pr create`，不需要再次确认 title/body；它不授权回复 review、resolve、rerun、merge 或修改其他仓库。

创建前：

1. 读取并遵守目标仓库 `AGENTS.md`、`CLAUDE.md`、贡献指南和仓库原生 PR 模板；没有可用模板时才读取 `references/pr-template.md`。
2. 根据真实 diff 和已确认上下文填写正文，可选章节没有有效信息时直接删除。
3. 检查同一 head branch 是否已有 open PR；存在时回读并汇报，不重复创建。
4. 确认 base 是已验证的默认分支或用户明确指定的 base，head 是当前 writable checkout branch。

```bash
gh pr list --repo "$OWNER/$REPO" --head "$BRANCH" --state open \
  --json number,url,state,baseRefName,headRefName,headRefOid

gh pr create --repo "$OWNER/$REPO" \
  --base "$BASE_BRANCH" \
  --head "$BRANCH" \
  --title '<repository-compliant-title>' \
  --body-file '<temporary-body-file>'
```

创建后回读：

```bash
gh pr list --repo "$OWNER/$REPO" --head "$BRANCH" --state open \
  --json number,url,state,baseRefName,headRefName,headRefOid,statusCheckRollup
```

再读取 PR body，确认模板正文、base/head 和 checks 没有丢失。

PR 创建成功后，用户 checkout 保留。托管 worktree 若 clean、fully pushed 且当前 `HEAD` 等于已回读的 PR `headRefOid`，即可按 `repository-operations.md` 的 Release 门禁释放；open PR 不要求物理目录常驻，后续评论调整按精确 head 重新 Acquire 或重建。

## 合并 PR

“合并 PR / merge PR”只授权即时合并用户明确指定的目标 PR。auto-merge、管理员绕过、删除远端 branch 和清理托管 worktree需要分别点名；若同一请求明确包含清理，先确认写后回读为 `MERGED`，再执行 Release 门禁。

合并前锁定当前快照：

```bash
gh pr view "$PR_NUMBER" --repo "$OWNER/$REPO" \
  --json number,title,url,state,isDraft,baseRefName,headRefName,headRefOid,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup
```

只有以下条件全部满足才可即时合并：

1. `state == OPEN` 且 `isDraft == false`。
2. `baseRefName` 与已确认目标分支一致，`headRefOid` 已保存为本次 `PR_HEAD_OID`。
3. `mergeable == MERGEABLE` 且 `mergeStateStatus == CLEAN`；`UNKNOWN`、`BLOCKED`、`BEHIND`、`DIRTY` 等状态均停止。
4. `reviewDecision != CHANGES_REQUESTED`；仓库要求审批但尚未满足时，`mergeStateStatus` 不会是 `CLEAN`，同样停止。
5. `statusCheckRollup` 为空，或所有已返回检查都已结束且 conclusion 为 `SUCCESS`、`NEUTRAL` 或 `SKIPPED`。存在 queued / in_progress，或 failure / cancelled / timed_out / action_required / stale 等结论时停止；不要从普通 merge 请求推断 rerun、auto-merge 或 admin bypass。

合并方式以用户明确指定为准，只允许 `merge`、`squash`、`rebase`。用户未指定时，先读取仓库设置；若多种方式可用，默认顺序为 `squash` → `merge` → `rebase`，选择第一个允许项：

```bash
gh api "repos/$OWNER/$REPO" \
  --jq '{allow_merge_commit,allow_squash_merge,allow_rebase_merge}'

gh pr merge "$PR_NUMBER" --repo "$OWNER/$REPO" \
  "$MERGE_FLAG" --match-head-commit "$PR_HEAD_OID"
```

`MERGE_FLAG` 只能是 `--merge`、`--squash` 或 `--rebase`。`--auto`、`--admin` 和 `--delete-branch` 只有用户逐项明确授权并满足各自门禁时才可添加；普通“合并”不包含这些动作。若仓库规则要求手工输入 merge commit 标题或正文，停止并报告，不猜测内容。

用户明确要求 auto-merge 时，仍需锁定 `PR_HEAD_OID`、确认 PR 非 draft、没有 `CHANGES_REQUESTED`、仓库允许所选 merge 方式，并使用 `--match-head-commit`。queued / in_progress checks 可以等待；已失败或需要人工处理的门禁必须报告，不能伪装成可自动完成。用户明确要求 admin bypass 时，在命令中显式使用 `--admin`，并报告被绕过的具体门禁。

命令返回后必须按同一 PR 回读，不以命令退出码单独判定成功：

```bash
gh pr view "$PR_NUMBER" --repo "$OWNER/$REPO" \
  --json number,url,state,headRefOid,mergedAt,mergedBy,mergeCommit
```

只有 `state == MERGED`、`mergedAt` 非空且 `headRefOid == PR_HEAD_OID` 时才报告合并成功，并记录 `mergeCommit.oid`。若命令超时或结果不明确，先执行这次回读，禁止盲目重试。

## 回复、resolve 与 rerun

回复评论和 resolve thread 是两个独立写操作，必须分别获得明确授权。

回复指定 review thread：

```bash
BODY_FILE='<absolute-temp-markdown-file>'

gh api graphql \
  -F threadId='<thread-id>' \
  -F "body=@$BODY_FILE" \
  -f query='mutation($threadId:ID!, $body:String!) {
    addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId, body:$body}) {
      comment { id url body }
    }
  }'
```

resolve 指定 thread：

```bash
gh api graphql \
  -F threadId='<thread-id>' \
  -f query='mutation($threadId:ID!) {
    resolveReviewThread(input:{threadId:$threadId}) {
      thread { id isResolved }
    }
  }'
```

workflow rerun 也需要独立授权：

```bash
gh run view '<run-id>' --repo "$OWNER/$REPO" \
  --json name,workflowName,status,conclusion,url,event,headBranch,headSha

gh run rerun '<run-id>' --repo "$OWNER/$REPO" --failed
```

每次写入前确认精确 ID 和当前状态；正文先通过本文件的 Markdown 与传输门禁，写后按同一 ID 回读 `body` 和状态。普通“处理评论”“修 CI”或“创建 PR”不自动授权回复、resolve 或 rerun。

## 不确定结果与跨仓任务

GitHub 写命令超时或返回不明确时，操作可能已经成功。禁止直接重试：

- commit：检查本地 HEAD 和 status；
- push：比较本地与远端 SHA；
- PR：按 head branch 查询现有 PR；
- merge：按 PR number 回读 `state`、`mergedAt`、`headRefOid` 和 `mergeCommit`；
- 回复 / resolve：按 comment / thread ID 回读；
- rerun：读取 run attempt 和状态。

跨仓任务为每个仓库分别选择并 Acquire 安全 writable checkout；只有出现隔离风险时才建立独立 worktree。分别记录授权、branch、commit、PR 和验证状态；一个仓库的授权不能扩展到另一个仓库，一个 PR 的评论授权不能扩展到另一个 PR。
