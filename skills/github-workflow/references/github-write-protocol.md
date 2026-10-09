# GitHub Write Protocol

本文件负责 review comment、commit、push、PR 创建、PR merge、回复、resolve 和 workflow rerun。先服从 `SKILL.md` 的授权矩阵；修改类任务完成且未声明例外时，按默认授权执行 `commit → push`；若改动由 review comment 触发，push 成功并回读后默认回复同一原 thread。其他写操作只有用户请求到达对应终点时才执行。

## Contents

- [写操作前置契约](#写操作前置契约)
- [Review 证据与 stale head](#review-证据与-stale-head)
- [GitHub Markdown 与正文传输](#github-markdown-与正文传输)
- [Commit](#commit)
- [Push](#push)
- [创建 PR 与更新 Body](#创建-pr-与更新-body)
- [提交 Review](#提交-review)
- [合并 PR](#合并-pr)
- [回复、resolve 与 rerun](#回复resolve-与-rerun)
- [不确定结果与跨仓任务](#不确定结果与跨仓任务)

## 写操作前置契约

任何写操作前都必须：

1. 确认精确的 `owner/repo`、默认分支、当前 branch 和用户授权终点；若是修改类任务，记录是否触发默认 `commit → push`，若是由 review comment 触发还要记录原 thread 和是否有“不回复”等显式例外。
2. 完整读取目标仓库 `AGENTS.md`；缺失时读取 `CLAUDE.md`；随后完整读取存在的 `CONTEXT.md`。
3. 确认当前目录是 `references/repository-operations.md` 完成 Acquire 的任务 worktree，而不是 repo cache。
4. 读取 `git status --short --branch`、remote 和 worktree 列表，保留所有无关改动。
5. 只 stage、commit、push 当前任务范围；发现无法区分的已有改动时停止并报告。

用户凭据拥有的权限不能扩展请求授权。PR merge 只允许在用户明确指定目标 PR 并要求合并时执行；auto-merge、admin bypass、force push、默认分支直推、历史改写和跳过 hook 始终禁止。

## Review 证据与 stale head

处理 review comment 前读取 PR metadata，并保存开始时的 `headRefOid`：

```bash
PR_NUMBER='<number>'

gh pr view "$PR_NUMBER" --repo "$OWNER/$REPO" \
  --json number,title,url,state,baseRefName,headRefName,headRefOid,reviewDecision,changedFiles,additions,deletions,statusCheckRollup
```

随后用 `headRefName` Acquire 对应 worktree。开始修改前必须满足 `git rev-parse HEAD == headRefOid`；若旧 worktree 不存在，可从精确 fetch 的 PR head branch 重建，但仍要验证该等式。dirty、ahead 或 diverged 的旧 worktree必须保留并停止，不能覆盖或假装已同步。

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

把 comment / thread 快照放在 worktree 外的临时目录，不提交这些文件。

用户指定评论时，用 thread ID、comment ID、文件和行号锁定目标，不扩展到其他意见；然后加载 `references/review-comment-assessment.md`。直接收集与评论相关的代码、调用链、业务契约、差异、测试和业务不变量证据，完成事实、业务问题和修改方案三层判定；处理单条 review comment 不自动调用 `review-swarm`。若用户另行明确要求完整代码 review / PR review，才切换到 `SKILL.md` 的 `review-swarm` 路由。

评论改动采用分阶段 stale-head 门禁：

1. **写代码前**：重新读取 PR `headRefOid` 和目标 thread。head 必须仍等于开始快照，目标 ID 必须存在且没有无法解释的状态变化；否则报告 stale 并停止。
2. **形成判定前**：完成三层判定后重新读取并比较 PR head、目标 thread 的 ID、`isResolved`、最新回复和目标行状态；任何变化都停止并重新绑定，不得沿用旧结论。
3. **写代码前**：只有 `需要修改` 或安全替代方案且上下文仍新鲜时才改代码。
4. **commit/push 前**：验证已覆盖评论触发条件、原本合法路径和适用边界；若无显式更窄终点，按默认授权执行普通 `commit → push`。
5. **push 后**：先按 push 协议回读远端 branch SHA，确认等于本地提交；再读取 PR head 和同一目标 thread。
6. **回复前**：若远端 head 是本次刚推送的 SHA、thread ID 仍存在且没有并发状态变化，则按“回复门禁”回复原 thread。由本次自身改动造成的 `isOutdated=true` 不单独阻止回复；目标消失、被他人 resolve、head 出现额外推进或状态无法确认时，不回复并报告。

“处理评论”不自动 resolve；默认回复只覆盖触发本次改动的同一原 thread，不覆盖其他评论。没有代码改动、push 失败或结果不确定时，不触发默认回复。

## GitHub Markdown 与正文传输

本节适用于 PR body、issue / PR comment、review reply 和 review body。格式正确需要同时满足：Markdown 源文正确、API 收到真实字符、写后回读与源文一致。

### 强制传输流程

1. 先把完整正文写入 worktree 外的临时 UTF-8 `.md` 文件；在 Codex 中使用 `apply_patch`，不要用 shell 拼接正文。
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

修改、修复、实现或处理指定 review comment 的任务在验证通过且产生本次范围内文件改动时，默认授权执行 `commit → push`。由 review comment 触发的改动在 push 成功并回读确认后，默认继续回复同一原 thread。以下显式指令覆盖默认行为：不 commit / 不 push / 不要提交和推送、只修改或只验证、只 commit、只 push、不要回复。默认授权不包含 PR 创建、回复其他评论、resolve、rerun、merge 或删除操作。

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
- 使用普通 `git commit`，禁止 `--no-verify`；hook 失败时修复原因，不绕过 hook。
- commit 后回读 `git status --short --branch` 和 `git rev-parse HEAD`。

## Push

push 前确认当前 branch 不是已验证的默认分支，并校验 origin 的全部 push URL：

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

只执行普通 push：

```bash
git push -u origin "$BRANCH"

LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git ls-remote origin "refs/heads/$BRANCH" | awk '{print $1}')
test "$LOCAL_SHA" = "$REMOTE_SHA"
```

对于由 review comment 触发的改动，push 回读成功后不得直接结束：必须按下方回复门禁重新读取 PR head 和原 thread；确认没有并发变化后再回复。禁止在 push 前回复，禁止 `--force`、`--force-with-lease`、`--no-verify`，禁止修改 remote 来通过校验。

## 创建 PR 与更新 Body

“提 PR / 创建 PR”明确授权当前改动的 commit、普通 push 和 `gh pr create`，不需要再次确认 title/body；它不授权回复 review、resolve、rerun、merge 或修改其他仓库。

创建前：

1. 完整读取 `references/pr-template.md`，忽略且不读取仓库原生 PR 模板。
2. 锁定 repo、base、head 与完整 diff；调用 `review-brief` 生成并校验 `review-brief.json`，再通过 `render-github` 生成临时 UTF-8 Body 文件。
3. 检查同一 head branch 是否已有 open PR；存在时回读并汇报，不重复创建。
4. 确认 base 是已验证的默认分支或用户明确指定的 base，head 是当前 worktree branch。

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

再读取 PR body，确认回读正文与本地渲染文件一致，且 base/head 和 checks 没有丢失。

PR 创建成功后 worktree 仍处于活跃 review 周期，默认保留。后续评论调整重新读取 PR `headRefOid` 并 Acquire 同一 worktree；用户之后明确要求合并该 PR 时，成功回读 `MERGED` 后默认按 `repository-operations.md` 尝试安全 Release，除非用户明确要求保留。PR closed / 明确放弃或其他结束场景仍需用户明确要求清理。

### 更新已有 PR Body

只有用户明确要求生成、刷新或更新 PR Description / PR Body 时执行；普通 push、标题/label/reviewer/base 更新、marker 外人工正文编辑都不授权 Body 更新。

1. 回读目标 PR 的 body、base、head 与 head SHA，并确认 Review Brief 覆盖当前完整 diff。
2. 将现有 body 保存到 worktree 外的临时 UTF-8 文件。
3. 用 `render-github --existing-body <file>` 生成候选 Body。现有非空 Body 无 marker 时，只有用户或既有流程明确选择后才传 `--adopt append|replace`。
4. 无论渲染器返回 `noop` 还是其他 action，都再次回读 body 与 head SHA，并与步骤 1 的原始快照逐字比较，同时确认 `review_brief.target.head` 等于当前 `headRefOid`；任一变化都停止本轮，回到步骤 1 重新读取完整 diff 和渲染，不能把旧候选当成当前 head 的导览。
5. 写前快照仍一致时，`noop` 才能确认为无需写入；其他 action 使用 `gh pr edit --body-file` 更新。
6. 写后回读 body 与 head SHA；除单个结尾换行外，body 必须与候选文件一致，head 也必须仍为开始时锁定值。

marker 残缺、重复、顺序错误，或用户要求图片必须出现但缺少已验证 GitHub 附件 URL 时，在任何 PR 编辑前停止。不得用 Release Asset、Actions Artifact、公共图床、业务分支 commit 或未文档化 endpoint 绕过。

创建或更新 PR Body 只生成 Reviewer 导览，不调用 `review-swarm`，也不产生 finding 或 merge verdict；明确代码审查/审查 PR 时，另按 `SKILL.md` 的显式 handoff 只读流程调用它。处理单条 review comment 不因需要核对代码而触发该流程。

## 提交 Review

此节只用于用户明确授权提交 GitHub review 的场景。普通代码审查只生成本地结论，
创建 PR 也不授权提交 review；不要因为已生成总结就自动写入 GitHub。

- 具体、可定位的问题使用通过 finding 门禁的 inline comments；顶层 review body
  使用 `review-swarm` 产出的整体分析，保留关键路径、领域规则、依赖方向、边界与取舍。
  不能将其压缩成“检查 N 个文件，发现 P2 × N，详见 inline”，也不在顶层逐条复制 inline。
- `review-swarm` 是整体总结的内容权威。依据其“整体 Review 总结”参考区分本次必改、
  非阻断建议和可以保留的设计；不要把总结交给 `review-brief`，其禁止 finding/verdict
  的规则只约束 PR Description，不用于删掉 review body 的分析。
- 发布前重新核对 PR head、审查范围、finding 与总结的一致性；总结出现新的具体缺陷时，
  先交回审查流程核实。不能只在总结中增加一个没有证据的阻断要求。
- Review event 与审查结论一致：完整覆盖且无未决问题时，`Request changes` 对应
  `REQUEST_CHANGES`，`Approve` 和 `Approve with non-blocking comments` 对应 `APPROVE`。
  `Approve with non-blocking comments` 不是 API event；P3 或一般建议不单独触发请求修改。
  局部覆盖或影响结论的 open question 只用 `COMMENT`，不能给全 PR 审批结论。
  GitHub 权限或自审限制导致 event 不可用时明确报告，不伪称提交成功或自动改换身份。
- body 按本协议通过 UTF-8 文件传输，inline 绑定已核实的文件、diff 行和 head SHA。
  写后按返回的 review ID 回读正文、state、commit_id，并回读关联 inline comments；
  核对正文与源文件一致、head 未漂移、comments 无遗漏。结果未知先回读，不重复提交。
- Slack 仅作已获授权的简短回执，链接到 GitHub review 或 PR；频道摘要不替代 GitHub
  上的整体分析，也不因提交 review 自动获得发 Slack 的权限。

## 合并 PR

“合并 PR / merge PR”授权合并用户明确指定的目标 PR，并在成功回读 `MERGED` 后默认对该 PR 的任务 worktree 执行安全 Release；用户明确说“保留 worktree”时跳过 Release。该授权不包含 auto-merge、管理员绕过或删除本地 / 远端 branch，也不允许强制清理未通过 Release 门禁的 worktree。

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
5. `statusCheckRollup` 为空，或所有已返回检查都已结束且 conclusion 为 `SUCCESS`、`NEUTRAL` 或 `SKIPPED`。存在 queued / in_progress，或 failure / cancelled / timed_out / action_required / stale 等结论时停止；不要自动 rerun 或开启 auto-merge。

合并方式以用户明确指定为准，只允许 `merge`、`squash`、`rebase`。用户未指定时，先读取仓库设置；若多种方式可用，默认顺序为 `squash` → `merge` → `rebase`，选择第一个允许项：

```bash
gh api "repos/$OWNER/$REPO" \
  --jq '{allow_merge_commit,allow_squash_merge,allow_rebase_merge}'

gh pr merge "$PR_NUMBER" --repo "$OWNER/$REPO" \
  "$MERGE_FLAG" --match-head-commit "$PR_HEAD_OID"
```

`MERGE_FLAG` 只能是 `--merge`、`--squash` 或 `--rebase`。禁止传 `--auto`、`--admin` 或 `--delete-branch`。若仓库规则要求手工输入 merge commit 标题或正文，停止并报告，不猜测内容。

命令返回后必须按同一 PR 回读，不以命令退出码单独判定成功：

```bash
gh pr view "$PR_NUMBER" --repo "$OWNER/$REPO" \
  --json number,url,state,headRefOid,mergedAt,mergedBy,mergeCommit
```

只有 `state == MERGED`、`mergedAt` 非空且 `headRefOid == PR_HEAD_OID` 时才报告合并成功，并记录 `mergeCommit.oid`。若命令超时或结果不明确，先执行这次回读，禁止盲目重试。

确认 merge 成功后按以下顺序收尾：

1. 若用户明确要求保留 worktree，记录 `retained: user requested`，不进入 Release。
2. 若本次任务没有对应 worktree，记录 `release: not applicable`，不得猜测或清理其他 worktree。
3. 其余情况立即执行 `repository-operations.md` 的 Release 门禁；全部通过后移除 worktree 并 prune，任一条件不满足则保留并报告精确原因，不再为确定性结果向用户二次确认。
4. Release 是 merge 后的 best-effort 收尾。清理失败不得把已经回读确认的 `MERGED` 重新报告成合并失败，也不得使用 `--force` 补救。

## 回复、resolve 与 rerun

独立的“回复评论”请求仍需明确授权。处理 review comment 且该评论实际触发了改动时，用户已通过本流程预先授权：在普通 push 成功并回读确认后，回复同一原 review thread；这是仅限该 thread 的默认例外，不扩展到其他评论。用户明确说“不要回复”“只修改/只提交/只推送”时跳过回复。

自动回复默认只适用于可由 `thread_id` 唯一定位的 inline review thread。普通 PR conversation comment 或 review body 没有原生线程回复关系时，不猜测关联对象，也不自动新发顶层评论；需要时按用户明确指定的回复方式执行。

### 回复门禁

回复前必须同时满足：

1. 本次代码改动能对应到该评论的判定结论或安全替代方案。
2. 普通 push 已成功，远端 branch SHA 已回读并等于本次提交。
3. PR head 没有在本次 push 之外继续变化。
4. 原 thread ID 仍存在且可唯一定位；若本次改动使它变成 `isOutdated`，不能仅凭该字段阻止回复。
5. thread 未被他人 resolve，且没有无法解释的并发状态变化。

回复正文要说明事实判断、是否接受原建议、采用的实际方案、验证结果和 commit SHA。不要声称未执行的测试，不要使用 `Closes` / `Fixes` / `Resolves` 等会改变 issue 状态的关键词，不要自动 resolve。

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

每次写入前确认精确 ID 和当前状态；正文先通过本文件的 Markdown 与传输门禁，写后按同一 ID 回读新增 reply 的 `id`、`body` 和 thread 状态。普通“处理评论”“修 CI”或“创建 PR”不自动回复，除非是本流程中已成功 push 的同一 review thread；resolve 和 rerun 始终需要独立授权。

## 不确定结果与跨仓任务

GitHub 写命令超时或返回不明确时，操作可能已经成功。禁止直接重试：

- commit：检查本地 HEAD 和 status；
- push：比较本地与远端 SHA；
- PR：按 head branch 查询现有 PR；
- merge：按 PR number 回读 `state`、`mergedAt`、`headRefOid` 和 `mergeCommit`；
- 回复 / resolve：按 comment / thread ID 回读；若 push 已成功但回复结果不确定，报告“代码已推送、评论回复待处理”，先回读再决定，不盲目重试；
- rerun：读取 run attempt 和状态。

跨仓任务为每个仓库建立独立 worktree，并分别记录授权、branch、commit、PR 和验证状态。一个仓库的授权不能扩展到另一个仓库，一个 PR 的评论授权不能扩展到另一个 PR。
