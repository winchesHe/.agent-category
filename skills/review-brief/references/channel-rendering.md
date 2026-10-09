# Review Brief 渠道渲染合同

用户要求 GitHub/Slack 预览、发布、上传或更新时完整读取本文件。所有渠道只从通过 `scripts/review-brief.mjs check` 的 `review-brief.json` 渲染，不复制、重算语义字段，也不从 Markdown 反向解析。

## 本地与对话输出

这是默认模式，不需要外部写授权：

- 返回完整 Markdown。
- 若有技术图，在对应变化后嵌入已通过内部门禁的 PNG；路径、文件 hash 和视觉检查状态留在 `review-brief.json`。
- 本地图片使用可确认存在的绝对路径；未通过视觉检查时不嵌入，只在 Brief 之外报告受阻原因。
- 不在 Brief 中展示 `visual_review`、校验命令或通过/失败结论。

## GitHub PR Description

GitHub 使用 `render-github` 生成完整渲染：

```md
<!-- review-brief:start schema=1 content=<content_hash> render=<render_hash> -->
## 概要

第一条简短结论。

第二条简短结论。

## 主要变化

### 1. 第一条主线

- **第一个要点**：说明行为与职责。
- **第二个要点**：说明行为与职责。

![能够独立说明流程的替代文本](<verified-github-attachment-url>)

## 推荐阅读路线

- `file:symbol` — ...

## Review 重点

- ...

## 风险与发布

- ...

## 关联资料

- ...
<!-- review-brief:end -->
```

规则：

- 只有概要与主要变化固定存在；Lite 删除阅读路线；其他空章节删除。
- 概要中的空行渲染为安全段落；Lite 的主要变化使用加粗标题列表，Full 的分组变化使用主线标题和 `points` 列表。
- 行内代码必须由真实 Markdown 代码定界符渲染；不能把反引号转成实体后让 Reviewer 看到语法字符。其他动态文本继续按纯文本转义，不能借行内格式逃逸受控结构。
- marker 只包围自动生成区域。更新时逐字替换 marker block；首次 append 也只在末尾补充分隔，marker 外的作者正文保持逐字不变。
- marker 同时记录语义 `content_hash` 与渠道 `render_hash`；只有预期 block 与现有 block 完全一致才是 no-op。
- 现有非空 Body 没有 marker 时，默认停止；调用方必须明确选择 `--adopt append` 或 `--adopt replace`，不能静默覆盖作者正文。
- marker 残缺、重复、顺序错误，或 start marker 的 schema/hash 元数据不符合当前固定格式时停止，不猜测受控范围；即使调用方传入 adopt 策略也不能覆盖。
- `github-workflow` 负责 repo/base/head、标题、授权、正文传输、已验证附件 URL 获取、创建/编辑和写后回读。
- 普通 push、标题/label/reviewer/base 更新或 marker 外人工正文编辑不触发 Brief 重算，也不得自动改写 Body。

命令：

```bash
node scripts/review-brief.mjs render-github review-brief.json \
  --github-bindings github-bindings.json \
  --output github-body.md

node scripts/review-brief.mjs render-github review-brief.json \
  --existing-body current-body.md \
  --output updated-body.md
```

用户要求任意图片必须出现时传 `--require-image`；只有明确要求技术图时才传 `--require-diagram`。两者都在 GitHub 写入前检查实际可渲染结果。

### GitHub 图片门禁

GitHub 官方公开能力允许用户在网页编辑框拖拽、选择或粘贴附件，但公开的 `gh pr create/edit` 只负责 Body，官方 REST 二进制上传端点属于 Release Asset。本 Skill 不把 Release Asset 或未文档化 endpoint 冒充 PR 附件上传能力。

- 只接受 GitHub 网页上传返回的 `https://github.com/user-attachments/assets/<UUID>` 匿名附件 URL；拒绝 raw 分支链接、任意 `githubusercontent.com`、非默认端口、credentials、query 与 fragment。
- `github-workflow` 作为可信 owner 必须在上传后重新读取远端字节，核对其 SHA-256 与本地 `file_hash` / `png_hash` 一致，再在候选 ReviewBrief 产物目录之外生成独立的 `github-bindings.json` 并通过 `--github-bindings` 交给渲染器。清单包含 `schema_version: 1`、当前 `target_identity`，以及 `assets: [{url, sha256}]`；它不属于候选 ReviewBrief，不能由候选 JSON 的自声明替代。渲染器机械拒绝同一路径、同一 inode、硬链接或候选产物目录内的清单，也拒绝用 `--output` 覆盖清单。
- `github-bindings.json` 是 owner workflow 的可信输入，不是渲染器自行联网得到的证明，也不防御拥有同一操作系统用户权限的恶意调用者。调用者不是 `github-workflow`、无法证明已经回读远端字节，或清单来源不明时，不得传入 `--github-bindings`，只能生成纯文字 Brief。
- `github_file_hash` 与 `github_target_identity` 仍记录候选产物声称的绑定，只有候选声明、本地当前字节和 owner 清单三者一致时才嵌图。缺少独立清单时自动退回纯文字。
- 不使用公共图床承载私有代码关系图。
- 不把生成图提交到产品分支，不创建 release、Actions Artifact 或额外 commit 绕过附件能力缺口。
- 不把 Slack 私有 URL 嵌入 GitHub。

图是可选增强且没有可用 URL 时，`render-github` 生成不含图片的完整文字 Brief。`--require-image` 可由普通附件或技术图满足；`--require-diagram` 只能由技术图满足。缺少可读取本地 PNG、通过视觉检查、字节 hash 仍匹配且可用于 GitHub 的 URL 时必须在 PR 写入前停止。图片 URL 与 alt text 写入 Markdown 前必须编码结构字符；概要只保留空行分隔的安全段落，段内换行折叠，标题、描述、导览、风险与关联资料按单行纯文本安全渲染。行首列表、序号和 thematic break 字符同样编码，不能通过换行、Setext、列表、图片、HTML、mention 或 issue-closing 语义改写结构。

## Slack

Slack 使用 `render-slack` 生成同源精简消息、原生 `blocks` 和待上传文件列表：

1. Review Brief 标题；不重复展示仓库、分支或目标链接行，PR 链接由发送方放在根消息。
2. 概要。
3. 精简后的主要变化，最多 3 条。
4. 最重要的推荐阅读路线或 Review 重点，合计最多 3 条。
5. 若返回技术图，正文增加该图的 alt text 说明。
6. 通过视觉门禁的本地 PNG，由 Slack 原生文件消息展示。

```bash
node scripts/review-brief.mjs render-slack review-brief.json \
  --target-url https://github.com/owner/repo/pull/123 \
  --output slack-message.md
```

规则：

- 命令的 stdout JSON 返回 `blocks`：直接写入 JSON 数组文件并交给 Slack `--blocks-file`；`--output` 文件作为 `--text-file` fallback。整份 Brief 使用 `context` block 内的 `mrkdwn` 文本对象（`verbatim: true`），链接显式使用 `<URL|标签>`。渲染器从同源语义字段生成文本，并按完整行拆成每个文本对象最多 3000 字符的 context blocks，不截断链接或格式标记；不能将 `rich_text` 嵌入 context。`render_hash` 同时覆盖 fallback、blocks 与附件 hash。
- 命令的 stdout JSON 返回 `files: [{path, sha256}]`；由 `slack` Skill 的 `files_upload` 按每个 `--file <path> --sha256 <hash>` 上传同一份已核对字节，Review Brief 自身不执行外部写入。校验上传每次最多 20 个文件、单文件 25 MiB、总计 100 MiB。
- Slack Skill 负责 token、scope、频道和 thread 解析；Slack 写操作必须有明确授权。
- `--target-url` 仅用于目标校验，不输出目标身份或链接行；PR 链接必须与 `owner/repo#number` 或 GitHub PR URL 形式的目标身份一致。所有来自 Brief 的文本折叠为单行纯文本并中和 Slack mrkdwn 控制符，链接标签中的 `|` 改为全角字符，不能注入段落、格式、`<!channel>`、`<!here>` 或用户标记。
- 渠道按固定字段预算确定性截短长文本，最终消息不得超过 4,000 字符；`render_hash` 覆盖实际精简后的消息，避免发布端截断后与渲染身份不一致。
- 默认只返回扩展名、PNG chunk/CRC、scanline filter、indexed palette 容量与实际像素索引都有效，且不超过 25 MiB 文件、4000 万像素、64 MiB 单图与累计解压预算、8 MiB 单行、10 万 scanline、8192 个总 chunk 及 4096 个 IDAT chunk 的 PNG；解码时每个 layout 复用两份行缓冲。所有校验和渲染命令在任何 hash/PNG 深度读取前，对全部本地 artifact 做单文件 25 MiB、总文件 100 MiB 与累计 PNG 解压 64 MiB 的共享资源门禁。`render-slack` 额外执行 realpath 目录和候选批次数量/总量门禁，并按冻结的真实文件身份去重；预算只读取预检快照，不重新访问实时路径。Slack 校验上传按“实际文件大小、剩余总预算、25 MiB 单文件上限”中的最小值分配读取缓冲，不为小文件额外申请 25 MiB。普通附件必须有一一对应、`visual_review: passed` 且检查时 `file_hash` 仍匹配的 artifact，位于 `review-brief.json` 所在产物目录树内，并且只来自精简正文实际展示的前三项变化。技术图同样要求 `png_hash` 匹配。SVG 仅在用户明确需要下载源文件时由调用方作为第二附件处理。
- `render-github` 与 `render-slack` 的输出路径不得覆盖输入 `review-brief.json` 或任何本地 artifact。
- 不把上传结果中的 permalink 再写进消息，避免重复 unfurl。
- GitHub 只嵌入其已验证附件 URL；Slack 直接上传本地 PNG。两端不交叉复用私有 URL。

## 发布失败语义

| 失败 | 处理 |
|---|---|
| GitHub 附件 URL 不可用 | 可选图退回文字；显式必需图则停止 PR 更新 |
| 现有 Body 无 marker | 要求调用方明确选择 append 或 replace |
| marker 残缺或重复 | 停止，不编辑 PR |
| Slack token/scope/channel/thread 不可用 | 不猜目标或改发其他频道，报告精确缺口 |
| PNG 未通过视觉检查 | 不上传，不声称图片可用 |
| GitHub/Slack 写结果不明确 | 先按 PR、message 或 file id 回读，不自动重复发布 |

外部发布是独立动作。本地生成 Brief、生成 SVG/PNG 或准备渠道 payload 都不构成 GitHub/Slack 写授权。失败原因属于调用方操作反馈，不写进 marker 内的 Review Brief 正文。
