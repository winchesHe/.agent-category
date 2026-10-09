---
name: slack
metadata:
  version: 2.1.1
description: >
  Use when requests involve Slack permalinks or threads, search/history/files,
  Bot/User actor selection, or proposing or performing Markdown/Block Kit Slack
  send/edit/delete/react/upload actions with preview and confirmation gating.
  Not for Slack app development, generic message drafting, or Jira/PR work
  without Slack links.
---

# Slack Skill

Slack Web API 的统一入口是 `scripts/slack.py`。读路径走只读白名单；`files_upload`、
`send`、`edit`、`delete`、`react` 走独立写白名单。精确参数、配置、缓存、输出形状和
错误码见 [命令参考](references/command-reference.md)。

## 凭据契约

`skill-metadata.json` 不把任何单个 token 设为全局必填。原因是不同操作使用不同 token，
不是 Slack 不需要凭据。运行时会在缺少当前操作所需 token 时明确返回错误。

| 操作路径 | Token 路由 | 说明 |
|---|---|---|
| 普通读取 | User → Bot | `auto` 先用 User；只有主读取事务在任何结果产生前遇到明确访问错误才回退 Bot |
| 全域 `search` | User only | 必须是 xoxp user token；Bot token 不能调用 `search.messages` |
| `send`、`files_upload`、`react` 添加 | User → Bot 写前预检 | 每个候选用自己的身份解析目标；User 不可达、Bot 可达时写前选择 Bot |
| `react --remove` | 固定 Bot 或 User | 按原添加者使用 `--as bot\|user` 或固定 `SLACK_WRITE_ACTOR`，拒绝 `auto` |
| `edit`、`delete` | 原消息作者 | Bot 消息只能由匹配 Bot actor 操作；User 消息只能由匹配 User actor 操作 |

除聚合诊断全部身份的 `doctor` 外，业务命令支持 `--as auto|bot|user`。显式 actor 永不
fallback；只有 `auto` 能在任何写请求前选择另一个身份。运行时先用 `auth.test` 验证 token 声明、取得 team/user/bot identity，
并要求 `auto` 候选属于同一 workspace。`SLACK_TOKEN` 只用于兼容且必须先分类；同类型变量
解析成不同身份时直接报配置冲突。若显式 actor 只有写 scope、缺少频道元数据读取 scope，
传入明确 channel ID 时允许以 `reachable=unknown` 附 warning 继续；`auto` 不使用未知候选。
User token 写出的消息即使同时带 App `bot_id`，edit/delete 所有权仍以认证 `user_id` 匹配。

## Execution Boundary

- 只有宿主实际暴露终端或 Slack 工具时才执行；文档里的命令不代表工具可用。
- 没有工具时，明确说明尚未取得 Slack 数据或完成写入，给出当前阶段可安全运行的完整
  `scripts/slack.py` 命令及后续读取/交付步骤。`edit` / `delete` 当前阶段只给 `get`
  预检命令，写命令须等真实预检结果和最终确认。不得伪造工具标记、结果或只留命令。
- 明确授权指用户已清楚指定当前操作、目标和内容，不要求机械出现“确认”二字。
  `把 /tmp/a.pdf 发到当前 thread` 是授权；`可能发到 #ops`、`帮我处理`、`发出去`
  不是。
- 单项 `send` / `react` / `files_upload` 已获完整直接授权时，直接进入工具权限确认并
  执行，不再追加自然语言确认。直接意图只缺目标或内容时仅追问缺失字段；补齐即完成
  授权，不得承诺“补齐后再确认”。
- `edit` / `delete` 必须先执行只读 `get` 预检，展示原文或 diff，再请求该项最终
  确认。确认中写出返回的 author id/name；仅当最终 actor identity 与原作者精确匹配时
  才能继续，不能只凭 `is_bot` 或名称判断。
- 多项写操作优先于单项规则：在当前响应中一次列全所有写入，每项都提供独立的
  同意/拒绝入口，不串行隐藏后续项，也不提供笼统的“全部确认”。不得先执行其中参数
  完整的 send/react/upload；edit/delete 的最终确认须等各自预检完成。没有工具时也
  立即给出 edit/delete 各自的 `get` 预检命令，但不编造预检结果。
- 宿主权限卡只保护最终执行，不能替代缺失的用户意图。

多项写操作在无工具时使用以下交付契约：

1. 先说明所有写操作均未执行，再把每项请求按编号一次列全。
2. `send` / `react` / `files_upload` 分别展示目标、内容和命令，并各自提供“同意此项 / 拒绝此项”入口。
3. `edit` / `delete` 当前只展示各自的 `get` 预检命令；明确取得真实结果后的展示清单：
   `edit` 展示 author id/name、与候选 Bot/User identity 的匹配结论及原文到新文本的 diff；
   `delete` 展示 author id/name、与候选 identity 的匹配结论及待删原文。完成展示后，
   再分别请求“同意编辑 / 拒绝编辑”或“同意删除 / 拒绝删除”的最终确认。
4. 要求用户按编号逐项回复，并明确不接受“全部确认 / 全部同意”等批量授权；不能把
   “确认作者后执行 edit/delete”合并成一个步骤。

## 何时使用

涉及 Slack permalink/thread、频道消息、全域搜索、用户/频道/用户组解析、Slack
附件，或 Slack send/edit/delete/react/upload 时使用。Jira/PR 中的 Slack permalink
也先用本 skill 取讨论上下文。不要用于 Slack app 开发、普通文案起草，或没有 Slack
链接的 Jira/PR 工作。

## 统一调用与回答契约

宿主提供的 `SKILL.md` 来源路径之父目录就是 `$SKILL_DIR`：

```bash
python3 "$SKILL_DIR/scripts/slack.py" <subcommand> [flags]
```

不要递归 `find` 脚本、绕过入口或导入内部 `sk` 包。所有子命令支持 `--help`。常用
读命令为 `get`、`replies`、`history`、`search`、`files_download`、`channels`、
`users`、`resolve`、`cache_refresh`、`doctor`；用户给足条件时直接读取，不再询问确认。

输出顶层 `actor` 说明 requested/selected/source_env/team_id/user_id/bot_id 与 fallback_reason。
users/channels/subteams 和附件目录按 workspace + actor 隔离；一次操作锁定 ActorContext 后，
频道解析、mention、cache、附件下载、permalink 和写请求不得重新选择 token。

大 thread、频道历史和搜索结果用 `--output <file>` 落盘；命令完成后必须读取该文件，
再基于真实结果总结。未读取前不能声称已总结。消息二次提取用保留 Slack token 的
`text_raw`，面向人或 AI 阅读用 `text_rendered`。大结果不得用 `cat`、`less` 或
`json.dumps` 整份刷到 stdout；应使用 Python / `jq` 按结构筛选、计数或分段读取，
再交付汇总。

没有执行工具时，仍给出同样的准确命令，点名输出路径并说明下一步如何读取、总结或
交付；同时明确当前未拿到真实结果。参数校验失败时复述子命令、非法入参和 stderr
原因；例如非法 file id 要说明 `files_download` 未执行且 Slack file id 必须以 `F`
开头。

## 核心读路径

### 消息、thread 与频道历史

```bash
python3 scripts/slack.py get --url "<permalink>"
python3 scripts/slack.py replies --url "<permalink>" --output /tmp/slack-thread.json
python3 scripts/slack.py history --channel "#eng" --limit 1d \
  --include-thread-replies --output /tmp/slack-history.json
```

完整 thread 用 `replies`；其 `--limit` 计算回复数，root 总会返回。`history --limit`
纯数字表示条数，`<n>{m|h|d|w}` 表示时间窗口。频道全景必须先读取输出文件，再整理
消息与 thread replies。

### 搜索

复杂语法按需读取 [搜索语法](references/search-syntax.md)。查询字符串原样保留
Slack 原生 `in:`、`from:`、`after:`、`before:` 等 modifier：

```bash
python3 scripts/slack.py search \
  '"payment stuck" in:#support from:@mia after:2026-06-01 before:2026-06-20' \
  --limit 200 --sort timestamp --sort-dir asc --output /tmp/slack-search.json
```

`search` 必须走 `SLACK_USER_TOKEN`/xoxp，bot token 不可替代。给出可执行命令方案或
无工具降级时，必须在命令附近显式说明这条 token 路径，并点名命令完成后读取同一
`--output` 文件，按 `matches` 结构筛选、计数或分段整理。不得用 `cat`、`less`、
`json.tool` 或整份 `json.dumps` 把搜索结果刷到 stdout；未读取前不能声称取得结果。

### 身份解析与私有附件

频道、用户、邮箱、用户 ID、用户组和 cache 场景分别使用 `channels`、`users`、
`resolve`、`cache_refresh`；精确组合见[命令参考](references/command-reference.md)。

Slack `url_private` 不是公网 URL，必须由 `slack.py` 使用已配置 token 下载；不得向
用户索取 token 或 Authorization header。先读消息确认 file id，再下载并读取本地文件：
`--types` 接受 `text`、`image`、`video`、`audio`、`pdf`、`archive`、`other`、`all`
类别，不接受扩展名或 MIME；CSV、日志和源码都属于 `text`。

```bash
python3 scripts/slack.py get --url "<permalink>"
python3 scripts/slack.py files_download --file-id F012ABC --types text --out /tmp/slack-files/
```

token/频道可见性排障使用只读 doctor；它不会证明写 scope：

```bash
python3 scripts/slack.py doctor
python3 scripts/slack.py doctor --channel '#release-ops'
```

## 核心写路径

### 消息撰写与格式

撰写 `send/edit` 正文或附件说明前，加载[消息格式参考](references/message-formatting.md)。
普通消息默认标准 Markdown，由 Slack 原生解析；不使用本地转换器、不猜格式。
撰写前根据内容、原生 Slack 语义、布局和交互需求判断是否使用 Block Kit；
用户明确指定时直接采用，无需先尝试 Markdown 或证明它不适用。
选择 Block Kit 时加载[参考](references/block-kit.md)，根据内容选择合适的组件。图文卡片、轮播、
折叠、图表、明细表和任务进度只是常见示例，不构成使用范围限制。
用 `--blocks-file` 自动切换，无需指定其它 format。
Block Kit 按组件 schema 选择文本类型：结构化正文优先 `rich_text`，`context` 等需要格式化文本对象的位置可用 `mrkdwn`。
选型、语法与中文标点边界见[Block Kit 参考](references/block-kit.md#语法模型)。
不在发送失败后自动切换格式重发；附件说明仍是简短原生 mrkdwn。
格式整理不得改变事实、代码、链接目标或增加未经授权的通知；写入授权仍遵循 Execution Boundary。

### 上传附件

- 用户只要求生成本地产物，或说“可能/考虑发到某处”时，不执行上传；询问是否把
  **具体文件**上传到**具体频道/thread**，并说明确认后使用 `files_upload`。
- 用户已明确要求将具体文件发到具体频道/thread，即已授权当前单项上传，不重复询问。
- Slack `@mention` 上下文中“发到这里”若已提供文件、`channel_id` 和 root
  `thread_ts`，直接上传到该 thread。`thread_ts` 优先取 mention 的 `thread_ts`；
  mention 本身是 root 时才用其 `ts`，绝不使用最新回复 ts。缺字段时只追问缺失项。
- thread 上传必须传 root `--thread-ts`，否则文件会落到频道顶层。完成后只简短说明
  已上传；不要把 `uploaded[].permalink` 放进回复或 initial comment，避免重复 unfurl。

```bash
python3 scripts/slack.py files_upload \
  --channel C0123456 --thread-ts 1700000000.000200 \
  --file ./out/report.pdf --message '已生成，见附件'

# Review Brief 等已绑定视觉检查字节的产物：每个文件同时传入预期 hash
python3 scripts/slack.py files_upload \
  --channel C0123456 --thread-ts 1700000000.000200 \
  --file ./out/review.png --sha256 '<64位小写SHA-256>' \
  --message 'Review Brief，见附件'

# 多文件一起发
python3 scripts/slack.py files_upload --channel C0123456 \
  --thread-ts 1700000000.000200 \
  --file ./a.csv --file ./b.csv
```

`--message` 按 Slack mrkdwn literal 处理，并复用 `send` 的 code-aware 通知门禁；其中
全频道和 usergroup 通知同样必须分别显式传 `--allow-broadcast` 与
`--allow-usergroup-mention`。

**约束**：
- `--file` 可重复传多个；`--filename` 仅在单文件时生效（覆盖 Slack 里展示的文件名）
- `--sha256` 可选；一旦使用，必须与每个 `--file` 按顺序一一对应。命令会以非阻塞方式打开单链接普通文件，在分配下一份缓冲区前检查剩余总预算，在任何 Slack API 调用前核对 hash，并把同一份已核对的内存字节交给上传请求；该模式拒绝 symlink、hardlink、FIFO 等特殊节点，每次最多 20 个文件、单文件不超过 25 MiB、总计不超过 100 MiB。
- 空文件会被拒（避免 Slack 端报错）
- 上传走 v2 流程：`files.getUploadURLExternal` → POST 字节 → `files.completeUploadExternal`
- `SLACK_SKILL_ALLOWED_CHANNELS` 同样对上传生效
- **场景 B 必须传 `--thread-ts`**，否则文件会发到频道顶层而不是 thread 里，等同于"@当前频道所有人"

### 发送、编辑、删除与 reaction

执行前应用 Execution Boundary：

```bash
python3 scripts/slack.py send --channel '#eng' --format markdown \
  --text '**部署状态**：验证通过' --dry-run
python3 scripts/slack.py send --channel '#eng' --format markdown \
  --text '**部署状态**：验证通过'
python3 scripts/slack.py send --channel '#eng' \
  --text-file /tmp/message-fallback.txt --blocks-file /tmp/message-blocks.json --dry-run
python3 scripts/slack.py edit --url '<permalink>' --format markdown \
  --text '**更新内容**' --dry-run --as auto
python3 scripts/slack.py edit --url '<permalink>' \
  --text-file /tmp/message-fallback.txt --blocks-file /tmp/message-blocks.json --as auto
python3 scripts/slack.py delete --url '<permalink>' --as auto
python3 scripts/slack.py react --emoji white_check_mark --url '<permalink>' --as auto
python3 scripts/slack.py react --remove --emoji lark_onesecond --url '<permalink>' --as user
```

`react` 默认添加；`--remove` 调用 `reactions.remove`，只移除当前认证身份添加的指定表情。
沿用单项 reaction 的授权规则；完整授权后直接执行。先确认原添加者身份与目标消息，
再固定 Bot/User actor；移除后用 `get/replies` 回读同一消息确认该身份的表情已不存在。
`no_reaction` 可能表示表情不存在或当前身份不是原添加者，按失败返回，不能直接当作清理成功，
也不切换身份重试。成功返回 `result: removed`；结果不明按现有 unknown 规则处理。

`send/edit` 均默认 `--format markdown`，也可显式传入；公开选项不再提供 mrkdwn/plain。
无 `--blocks-file` 时正文只使用 `markdown_text`；有 blocks 时改为 `blocks + text fallback`，
二者不混用。Markdown 超过 12,000 字符拒绝；不截断、自动拆条或降级重发。

`--blocks-file` 接受非空 JSON block 数组，`--text/--text-file` 仍必填，提供通知与无障碍 fallback。
CLI 先校验文件与基础结构，完整 schema 由 Slack 校验。具体语法、限制和场景见 Block Kit 参考。

长内容、mention、广播或代码块优先 dry-run；预览返回最终请求、通知清单及 `preview_digest`。
正式执行可用 `--confirm-preview <digest>` 防止内容、身份或目标变化。
`send` 默认 mention-mode=resolve，`edit` 默认 literal；代码与链接目标不参与名称解析。
全频道及用户组通知分别需要 `--allow-broadcast`、`--allow-usergroup-mention`；
顶层正文、嵌套 markdown/mrkdwn 和 rich_text 通知元素都经过门禁。
Markdown 控制串的通知效果未获单独保证，需要明确通知时使用 Block Kit 显式 mention 并检查预览。
显式 actor 缺 thread 只读 scope 时，合法 thread_ts 以 unknown warning 继续；auto 仍拒绝无法验证的 thread。

`edit/delete` 只操作与已配置 Bot/User 匹配的原作者消息，未知或不匹配时不得写入。
`edit --dry-run` 不写入；摘要同时绑定原消息 text/blocks/edited，变化时拒写。
编辑会提交完整的新 Markdown 或 blocks 正文，不拼接原 blocks；Slack 拒绝格式切换时
报告错误，不补发、不自动清空后重写。预览摘要不是服务端原子锁，也不能替代 get、展示 diff 和最终授权。
reply 使用 `channel + ts` 时还要传 root `--thread-ts`，permalink 自带 root 信息时除外。
`edit` 预检要展示原文到新文本的 diff。`react --emoji` 不带冒号。一次请求含多项写入
时，即使用户在一条消息里列出了全部操作，也必须逐项授权。

## 不可违反

- 不在缺少当前具体授权时执行任何写操作，也不自动发送、reaction 或 mark-read。
- 不把候选表述当上传授权，不把含糊的“发出去”当成目标和内容完整。
- 不批量确认多项写操作；不跳过 edit/delete 的预检、归属比对和最终确认。
- 不把 token 放进 argv、日志或回答；使用 `.env` 或 shell env。
- 不对大结果直接刷 stdout；使用 `--output` 并实际读取。
- 不用 `text_rendered` 做结构化提取，不编辑或删除非匹配 actor 自己的消息。
- 写请求出现 HTTP 5xx、超时、断连、派发期间任务取消、invalid JSON、`fatal_error` 或 `internal_error` 时，
  结果是 `unknown`；禁止自动重试、换 actor 或因 permalink 失败而重发。
- 已锁定 actor 的权限/参数类写失败必须输出结构化 `failed` JSON 和 actor；文件上传 unknown
  必须保留阶段、已取得 file_id 与已完成字节上传列表，不能整链重做。

## References

- [消息格式参考](references/message-formatting.md)：撰写发送、编辑正文或附件说明前加载；包含原生 Markdown、附件说明的语法边界与验收方法。
- [Block Kit 参考](references/block-kit.md)：需要结构化布局、原生格式或中文标点紧贴加粗标记时加载；含选型、语法、场景 JSON 和实测边界。
- [命令参考](references/command-reference.md)：需要精确子命令、flag、输出、错误码或身份矩阵时加载。
- [搜索语法](references/search-syntax.md)：使用 `search` 的 modifier、时间范围或复杂组合时加载。
