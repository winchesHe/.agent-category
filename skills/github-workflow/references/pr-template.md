# Review Brief 接入与 PR 发布契约

创建 PR，或用户明确要求生成、刷新、更新 PR Description / PR Body 时完整读取本文件。PR 正文的字段、顺序、删减和图片规则只由 `review-brief` 定义；本文件不维护第二套 Body 模板。

## 标题

默认使用带 scope 的 Conventional Commit：

```text
<type>(<scope>): <subject>
```

先检查目标仓库的 `AGENTS.md`、commitlint 配置和最近提交；仓库标题规则优先。标题不属于 Review Brief marker，普通标题更新不触发 Body 重算。

## 何时生成或刷新 Body

必须调用 `review-brief`：

- 创建新 PR。
- 用户明确要求生成或刷新 Review Brief。
- 用户明确要求更新 PR Description / PR Body。

不得自动调用：

- 只执行普通 push。
- 只修改标题、label、reviewer 或 base。
- 只编辑 Review Brief marker 外的人工正文。
- 只执行代码审查、回复评论、resolve thread 或 rerun CI。

`review-brief` 只生成内容，不启动 `review-swarm`；创建或更新 PR Body 也不等于执行代码审查。

## 正文生成

1. 锁定目标 repo、base、head 和完整真实 diff，并读取已确认上下文。
2. 完整加载已安装 `review-brief/SKILL.md` 及其要求的输出合同、渠道合同。
3. 生成 `review-brief.json`，执行 `finalize` 后再执行 `check`。
4. 使用确定性入口生成 UTF-8 Body 文件：

```bash
node <review-brief-root>/scripts/review-brief.mjs render-github \
  <review-brief.json> \
  --github-bindings <owner-verified-bindings.json> \
  --output <temporary-body.md>
```

更新现有 Body 时，先把回读正文保存到 worktree 外的临时文件，再传入 `--existing-body`。已有非空 Body 没有 marker 时必须显式选择 `--adopt append|replace`；没有用户或既有流程支持时停止，不静默覆盖。

## Marker 与图片

- 自动区域使用 `<!-- review-brief:start schema=1 content=<content_hash> render=<render_hash> -->` 和 `<!-- review-brief:end -->`。
- 更新只替换唯一且完整、schema/hash 元数据符合固定格式的 marker block，逐字保留 marker 外正文；残缺、重复或非规范 marker 时停止。
- GitHub 没有供 `gh pr create/edit` 自动上传 PR 附件的公开接口。只嵌入网页上传返回的 `github.com/user-attachments/assets/<UUID>` 匿名附件 URL。
- 本 Skill 是 `github-bindings.json` 的可信 owner。网页上传后必须重新读取远端 URL 的实际字节，确认 SHA-256 与本地 hash 一致，再在 worktree 外、且不属于候选 ReviewBrief 产物目录的位置生成独立临时清单：`{"schema_version":1,"target_identity":"<当前目标>","assets":[{"url":"<附件 URL>","sha256":"<本地 hash>"}]}`。调用 `render-github` 时传入 `--github-bindings`；不能只相信 `review-brief.json` 内的 `github_file_hash` 与 `github_target_identity` 自声明，也不能把候选 JSON 自身、同 inode/硬链接或同目录文件当作 owner 清单。清单是本 owner workflow 的可信输入，不是 `render-github` 自行联网验证；无法确认来源或远端回读结果时不得传入。输出文件也不得与清单为同一路径或同一 inode。
- 没有满足独立绑定门禁的 URL 时使用文字 Brief；临时清单用后删除，不提交到产品分支。
- 用户明确要求任意图片必须出现在 PR Body 时使用 `--require-image`；明确要求技术图时才使用 `--require-diagram`。对应类型缺少通过视觉、字节 hash 与 URL 门禁的附件时停止写入。
- 禁止使用未文档化 endpoint、公共图床、Release Asset、Actions Artifact 或业务分支 commit 绕过附件能力缺口。

## 写入与回读

- 多行 Body 只通过 `--body-file` 发送。
- 创建或编辑后按同一 PR 回读 body、base、head 和 checks。
- 除 GitHub 对单个结尾换行的规范化外，回读 body 必须与本地渲染文件一致。
- 只有渲染器返回 `action: noop` 时才跳过 Body 写入；不能只比较 `content_hash`。
- 普通 push 不自动刷新 Body，也不自动执行 `review-swarm`。
