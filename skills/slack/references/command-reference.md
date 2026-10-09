# Slack CLI 命令参考

需要精确参数、环境配置、缓存行为、文件类型或错误码时读取本文。统一入口始终是：

```bash
python3 "$SKILL_DIR/scripts/slack.py" <subcommand> [flags]
```

`$SKILL_DIR` 是 `SKILL.md` 所在目录。禁止绕过入口或直接导入内部 `sk` 包。

## 子命令

| 子命令 | 作用 | 典型入参 |
|---|---|---|
| `get` | 读单条消息 | `--url <permalink>` |
| `replies` | 读完整 thread | `--url <任一消息 permalink>` |
| `history` | 浏览频道消息 | `--channel <#name\|C...> --limit <n\|1d\|2h>` |
| `search` | 全域搜索，xoxp 专属 | `<query>`、`--sort`、`--sort-dir` |
| `files_download` | 下载附件 | `--file-id F...` 或 `--url <permalink>` |
| `files_upload` | 上传本地文件 | `--channel`、`--thread-ts`、`--file`、`--sha256`、`--message` |
| `channels` | 搜索/列出频道 | `--query <name>`、`--type public` |
| `users` | 按 ID/email/name 查人 | `--id`、`--email`、`--query` |
| `resolve` | 字符串解析为对象 | `@user`、`#channel`、`^subteam`、ID/email |
| `cache_refresh` | 刷新 users/channels/subteams cache | `--output <file>` |
| `doctor` | 聚合诊断 Bot/User 身份与频道可见性 | 可选 `--channel` |
| `send` | Markdown/Block Kit 预览与发送 | `--channel`、`--text`/`--text-file`、`--blocks-file`、`--format`、`--dry-run` |
| `edit` | 按原作者身份编辑文本或 Block Kit | `--url` 或 `--channel + --ts [--thread-ts]`，以及 fallback 文本、可选 `--blocks-file` |
| `delete` | 按原作者身份删除消息 | `--url` 或 `--channel + --ts [--thread-ts]` |
| `react` | 添加或移除 emoji reaction | `--emoji <name>` 加 permalink 或 channel/ts；移除加 `--remove` 并固定 actor |

每个子命令都支持 `--help`；除聚合诊断全部身份的 `doctor` 外，业务命令支持
`--as auto|bot|user`。大输出使用 `--output <file>`；stdout 只返回 `saved: <path>`。
显式 Bot/User 永不 fallback。

## Setup、Token 与 Cache

- Python ≥ 3.9，无第三方依赖。
- 复制 `$SKILL_DIR/.env.example` 为 `$SKILL_DIR/.env`。
- 普通读取 `auto`：User → Bot；只在主事务未产生结果前遇到明确访问错误才切换。
- `search`：User only，必须是 xoxp。
- send/files_upload/react 添加的 `auto`：User → Bot；每个候选用自己的 cache/client 做写前目标预检。
- `react --remove`：使用 `--as bot|user` 或 `SLACK_WRITE_ACTOR=bot|user` 固定原添加者身份；`auto` 在认证和写入前被拒绝。
- edit/delete `auto`：读取原消息并匹配 Bot/User 作者。
- Bot/User 执行写操作都需要对应 token 上的 `chat:write`、`files:write` 或 `reactions:write`。
- 所有写操作还受 `SLACK_SKILL_ALLOWED_CHANNELS` 约束。

每个 token 都通过 `auth.test` 分类。`SLACK_BOT_TOKEN`/`SLACK_USER_TOKEN` 的声明类型必须与
返回身份一致；`SLACK_TOKEN` 只作迁移兼容。同类型槽位对应不同身份、或 `auto` 候选跨
workspace 时直接报配置错误。

`channels`、`users --query`、`resolve "#name|@handle|^handle"` 会在 cache 缺失或过期时自动刷新。单条 ID/email lookup 走 live API；消息类命令不会触发全量刷新。

相关环境变量：

- `SLACK_SKILL_CACHE_TTL`：默认 3 天。
- `SLACK_SKILL_CACHE_NO_AUTO=1`：关闭自动刷新。
- `SLACK_READ_ACTOR` / `SLACK_WRITE_ACTOR`：默认 `auto`。
- `SLACK_SKILL_CACHE_DIR`：覆盖 cache root；实际按 team/actor namespace 隔离。
- `SLACK_SKILL_FILES_DIR`：覆盖附件 root；实际按 team/actor namespace 隔离。
- `SLACK_SKILL_DOWNLOAD_TYPES`：默认下载类型。
- `SLACK_SKILL_WRITE_RETRY_BUDGET`：429 可等待的累计秒数，默认 30。

## 输出形状

所有结果顶层包含 `actor`。消息对象包含 `ts`、`thread_ts`、`author`、`text_raw`、
`text_rendered`、`blocks_rendered`、`files`、`reactions` 与 `raw`。二次提取使用 `text_raw`；
给 AI 或人阅读使用 `text_rendered`。

`replies --limit` 计算回复数，root 总会返回。`history --limit` 的纯数字表示条数；`<n>{m|h|d|w}` 表示时间窗口。

## Identity 与 Resolve

```bash
python3 scripts/slack.py cache_refresh --output /tmp/slack-cache-refresh.json
python3 scripts/slack.py channels --query release --output /tmp/slack-channels.json
python3 scripts/slack.py users --query alice --output /tmp/slack-users-query.json
python3 scripts/slack.py users --email alice@example.com --output /tmp/slack-user-email.json
python3 scripts/slack.py users --id U06GM8PAFEX --output /tmp/slack-user-id.json
python3 scripts/slack.py resolve "@alice" --output /tmp/slack-resolve-user.json
python3 scripts/slack.py resolve "#eng-release" --output /tmp/slack-resolve-channel.json
python3 scripts/slack.py resolve "^oncall" --output /tmp/slack-resolve-subteam.json
python3 scripts/slack.py doctor --channel '#eng-release'
```

`resolve` 返回 `kind`、`resolved`、可选 `candidates` 与 `cache_refresh`。解析出 channel id 后再交给 `history`。

## 文件下载细节

```bash
python3 scripts/slack.py get --url "<permalink>" --download-files --types image,pdf
python3 scripts/slack.py files_download --file-id F012ABC --types all --out /tmp/f/
```

Slack `url_private` 需要 token 授权，不能当公网 URL。下载结果会填入 `local_path`、`download_category`、`download_status`，顶层含 `downloads` 汇总。

类型包括 `text`、`image`、`video`、`audio`、`pdf`、`archive`、`other`、`all`。文件名按 file id 幂等保存；已存在时标记 `skipped:already_exists`。

## 文件上传细节

```bash
python3 scripts/slack.py files_upload \
  --channel '#release-notes' --file ./out/report.pdf \
  --message '本周报告已生成'

python3 scripts/slack.py files_upload \
  --channel C0123456 --thread-ts 1700000000.000200 \
  --file ./out/report.pdf --message '已生成，见附件'

python3 scripts/slack.py files_upload \
  --channel C0123456 --thread-ts 1700000000.000200 \
  --file ./out/review.png --sha256 '<64位小写SHA-256>' \
  --message 'Review Brief，见附件'
```

- `--file` 可重复；`--filename` 只适用于单文件。
- `--sha256` 可选；使用时必须与每个 `--file` 按顺序一一对应。命令在任何 Slack API
  调用前核对单链接普通文件的 hash，并把同一份已核对字节交给上传请求；该模式拒绝
  symlink、hardlink、FIFO 等特殊节点，每次最多 20 个文件、单文件 25 MiB、总计 100 MiB。
- `--message` 复用通知门禁；全频道与 usergroup 通知分别需要
  `--allow-broadcast`、`--allow-usergroup-mention`。
- thread 上传必须传 root `--thread-ts`，否则文件会落到频道顶层。
- 上传使用 `files.getUploadURLExternal` → 上传字节 → `files.completeUploadExternal`。
- 不要把 `uploaded[].permalink` 放进回复或 initial comment，避免 Slack 再次 unfurl 同一文件。
- 成功后一句“已上传到当前 thread”即可。

## 写操作参数

```bash
python3 scripts/slack.py send --channel '#eng' --format markdown \
  --text-file /tmp/deploy.md --dry-run
python3 scripts/slack.py send --channel '#eng' --format markdown \
  --text-file /tmp/deploy.md --confirm-preview 'sha256:...'
python3 scripts/slack.py send --channel C0123456 --thread-ts 1700000000.000200 \
  --format markdown --text 'Thread reply'
python3 scripts/slack.py send --channel C0123456 --format markdown \
  --text-file /tmp/message-fallback.txt --blocks-file /tmp/message-blocks.json --dry-run
python3 scripts/slack.py edit --url '<permalink>' --format markdown \
  --text '**Updated content**' --dry-run --as auto
python3 scripts/slack.py edit --url '<permalink>' --format markdown \
  --text '**Updated content**' --confirm-preview 'sha256:...' --as auto
python3 scripts/slack.py edit --url '<permalink>' \
  --text-file /tmp/message-fallback.txt --blocks-file /tmp/message-blocks.json --as auto
python3 scripts/slack.py delete --url '<permalink>' --as auto
python3 scripts/slack.py react --emoji white_check_mark --url '<permalink>' --as user
python3 scripts/slack.py react --remove --emoji lark_onesecond --url '<permalink>' --as user
```

`react` 默认调用 `reactions.add`；`--remove` 调用 `reactions.remove`，只移除固定 actor
在指定消息上添加的表情。两者均支持 permalink 或 `--channel + --ts`，使用目标消息本身的
时间戳；目标是 reply 时不改成 root `thread_ts`。Bot/User 均需 `reactions:write`。
移除成功输出 `operation_status: succeeded`、`result: removed`、channel/ts/emoji/reachable
和 actor；调用方使用 `get/replies` 回读目标消息，按 actor.user_id 核对 reactions。
`no_reaction` 返回 `status: failed`、`reason: no_reaction` 和非零退出码，不转换为成功，
也不换身份重试。添加仍返回 `result: reacted` 和 `already_reacted`。

`send/edit` 默认 `--format markdown`，公开 format 只有 markdown。
无自定义 blocks 时以 `markdown_text` 交给 Slack 解析，不发送 text/blocks，不使用本地渲染依赖。
超过 12,000 字符拒绝，不截断、自动拆条或降级。语法边界见[消息格式参考](message-formatting.md)。
`--text` 与 `--text-file` 严格二选一；send 默认 mention-mode=resolve，edit 默认 literal。

`--blocks-file` 自动切换为 `blocks + text fallback`，无需更改 format。
顶层文本仍必填；fallback 超过 4,000 字符 warning、40,000 拒绝。
文件需 UTF-8、标准 JSON、非空 block 对象数组，每项有非空 type，最多 50 项；
4 MiB 文件、64 层嵌套、20,000 节点在凭据/网络前校验。完整 schema 由 Slack 校验。
嵌套 markdown/mrkdwn 和 rich_text 通知元素都经过门禁。
Block Kit 请求设置 parse=none、link_names=false，mrkdwn 的 verbatim 字段原样保留；选型与字段语义见 [Block Kit 参考](block-kit.md)。
仍使用 chat.postMessage/chat.update 与 chat:write，不增加 scope。

`--dry-run` 返回最终字段、通知和 `preview_digest`，不调用写 API；
`--confirm-preview <digest>` 不匹配时停止。edit 的摘要还绑定原消息 text/blocks/edited。
编辑发送完整新正文；Markdown 与 Block Kit 不混字段、不拼接旧 blocks。预览不是原子锁，
仍必须按作者预检、展示 diff 并取得最终授权。若 Slack 拒绝切换，报告错误而非补发。

人类写法与原生控制串都受通知门禁：广播需 `--allow-broadcast`，用户组需
`--allow-usergroup-mention`。Markdown 的通知效果未获单独保证，需要明确通知时使用
Block Kit 的显式 mention。thread ts 必须是 root 且格式为秒.6位微秒；reply_broadcast 固定 false。

## 常见错误

| Slack error | 处理 |
|---|---|
| `channel_not_found` | 用 `channels --query` 找正确 ID |
| `not_in_channel` | `auto` 写前按 User → Bot 选择可达身份；显式身份需加入频道或改用可达的 `--as user` 或 `--as bot` |
| `user_not_found` | 用 `users --query` 或完整用户 ID |
| `not_allowed_token_type` | `search` 改用 xoxp user token |
| `missing_scope` | 按 `.env.example` 补 scope 并重新安装应用 |
| `invalid_auth` / `not_authed` | 检查 token 与 SSO 状态 |
| `ratelimited` | 只在完整 Retry-After 不超等待预算时重试；绝不截短等待 |
| `message_not_found` | thread reply permalink 应含 root `thread_ts` |
| `file_not_found` | 使用 `get/replies` 返回的 F 开头 file id |
| `invalid_blocks` | 核对对应组件 schema 与组合限制，不猜字段重试；plan 与独立 task_card 不共存 |
| `block_mismatch` | Slack 拒绝格式替换；回读原消息并报告，不自动清空或另发 |
| `cant_update_message` | 当前 token 不是作者；不编辑，改为让原作者处理 |
| `cant_delete_message` | 当前 token 不是作者；不删除，改为保留并说明 |
| `already_reacted` | 无需重复操作 |
| `no_reaction` | 表情不存在或 actor 不是原添加者；回读目标消息并核对身份，不能直接声称清理成功或换身份重试 |

退出码：`2` 为 token/actor 配置错误，`3` 为只读白名单拦截，`4` 为参数、预检或允许频道
错误，`5` 为写结果不确定，`1` 为其它错误。HTTP 5xx、超时、断连、invalid JSON、
`fatal_error`/`internal_error` 返回 `unknown`，禁止自动重试或换 actor。凭证不会出现在输出。
