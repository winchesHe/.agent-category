# Slack Skill —— 人工 Quickstart

一个 Slack Web API 封装，对外是一个 Python CLI（`slack.py`）。读路径只读；写路径限定为 `files_upload`、`send`、`edit`、`delete`、`react`，必须经过明确确认后使用。普通 Markdown 消息交给 Slack 原生解析；需要结构化布局时用 --blocks-file 自动切换 Block Kit。

- 给 AI 读的 usage → [`SKILL.md`](./SKILL.md)
- 完整命令与行为参考 → [`references/command-reference.md`](references/command-reference.md)
- 本文件是**给人看的**上手文档。

## 能干什么

十五个子命令，全部返回结构化 JSON：

| 子命令 | 干啥 |
|---|---|
| `get` | 按 permalink / channel+ts 读单条消息 |
| `replies` | 按 permalink 读整个 thread（root + 所有回复） |
| `history` | 频道最近消息，支持条数或时间窗口（`--limit 1d`） |
| `search` | 全域搜索消息（`search.messages`，**要 xoxp**） |
| `files_download` | 按 file id / permalink 下载附件（自带 Bearer 认证） |
| `files_upload` | 上传本地文件到频道（可选评论 / 进 thread），导出产物后发 Slack 用 |
| `send` / `edit` / `delete` / `react` | Markdown/Block Kit 预览与发送、按原作者编辑或删除、添加或移除 reaction |
| `channels` / `users` / `resolve` | 从本地 cache 查 id / 名字 / 邮箱 |
| `cache_refresh` | 刷新本地 users / channels / subteams 字典 |
| `doctor` | 只读检查 Bot/User 身份、workspace、cache namespace 和频道可见性 |

三个读消息类命令（`get` / `replies` / `history`）都支持 `--download-files [--types ...]`，读消息同时把里面的附件一并下到本地。

**写口非常窄**：读路径走 `client.py` 的硬编码只读白名单；写路径走 `write_client.py` 的独立写白名单（`files.getUploadURLExternal` / `files.completeUploadExternal` / `chat.postMessage` / `chat.update` / `chat.delete` / `reactions.add` / `reactions.remove`），改一个不会影响另一个。

## 安装

需要：

- Python ≥ 3.9
- 一个 Slack token（见下）

运行时仅依赖 Python 标准库，无本地 Markdown 转换器或额外安装步骤。

配置 env：

```bash
cp .env.example .env
# 编辑 .env，至少填 SLACK_BOT_TOKEN
```

`<SKILL_DIR>/.env` 和当前工作目录 `.env` 都会自动加载；shell 里已 export 的同名变量会覆盖文件里的值。

## Token 和 scope

两种 token，按需配：

| 变量 | 格式 | 哪些命令需要 | 所需 scope |
|---|---|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-...` | Bot 身份读写 | `channels:history` `groups:history` `im:history` `mpim:history` `channels:read` `groups:read` `im:read` `mpim:read` `users:read` `users:read.email` `files:read`，写命令再加 `files:write` `chat:write` `reactions:write` |
| `SLACK_USER_TOKEN` | `xoxp-...` | 默认读取、`search`、User 身份写入 | 同一套 history/read；搜索加 `search:read`，写入加对应 write scope |

普通读取 `auto` 优先 User；发送/上传/添加 reaction 会先用 User 预检目标，不可达再在任何写请求前
选择 Bot。`edit/delete` 按原作者匹配。所有命令可用 `--as auto|bot|user`；显式身份不回退。
移除 reaction 使用 `react --remove --emoji <name> --url '<permalink>' --as user`（或 bot），
也可用 `SLACK_WRITE_ACTOR=bot|user` 固定身份；该模式拒绝 `auto`，只移除所选身份添加的表情。
`no_reaction` 按失败返回，需回读消息核对身份和表情是否存在，不能据此声称清理成功。
两个专用变量都没有时，`SLACK_TOKEN` 会先经 `auth.test` 分类。全部环境变量见
[`.env.example`](./.env.example)。

Token 来源：<https://api.slack.com/apps> → 你的 App → **OAuth & Permissions**。

## 使用

唯一入口是 `<SKILL_DIR>/scripts/slack.py`：

```bash
python3 scripts/slack.py --help
python3 scripts/slack.py <子命令> --help
```

常用示例：

```bash
# 读单条消息
python3 scripts/slack.py get --url "https://acme.slack.com/archives/C0.../p1712345678901234"

# 读整个 thread，落盘避免吃 stdout
python3 scripts/slack.py replies --url "<permalink>" --output /tmp/thread.json

# 频道最近一天，带 thread 回复，所有附件一并下载
python3 scripts/slack.py history --channel '#eng' --limit 1d \
  --include-thread-replies --download-files --types all --output /tmp/today.json

# alice 是谁？（模糊查）
python3 scripts/slack.py users --query alice

# 全域搜（需 xoxp）
python3 scripts/slack.py search "deploy in:#eng from:@alice" --limit 50 \
  --output /tmp/hits.json

# 一键 id → 对象
python3 scripts/slack.py resolve "@alice"
python3 scripts/slack.py resolve "#eng-release"

# 把刚刚导出的报表发到频道（典型用法：导出 → 询问用户 → 上传）
python3 scripts/slack.py files_upload \
  --channel '#release-notes' --file ./out/report.pdf \
  --message '本周报告已生成 ✅'

# 标准 Markdown 先预览，确认 digest 后发送
python3 scripts/slack.py send --channel '#release-notes' \
  --format markdown --text-file ./out/release.md --dry-run

# 发送 Block Kit 消息；顶层 fallback 仍为必填
python3 scripts/slack.py send --channel '#release-notes' \
  --text-file /tmp/message-fallback.txt \
  --blocks-file /tmp/message-blocks.json --dry-run

# 更新同一条消息的 fallback 与 blocks
python3 scripts/slack.py edit --url '<permalink>' \
  --text-file /tmp/message-fallback.txt --blocks-file /tmp/message-blocks.json

# 诊断 Bot/User 为什么看不到同一个频道（只读）
python3 scripts/slack.py doctor --channel '#release-notes'
```

需要保证上传字节与上游视觉检查结果一致时，为每个文件按顺序补充 `--sha256 <64位小写hash>`。命令会以非阻塞方式打开单链接普通文件，在分配下一份缓冲区前检查剩余总预算，在外部调用前校验，并上传同一份已校验缓冲区；symlink、hardlink、FIFO 等特殊节点会被拒绝。该模式每次最多 20 个文件、单文件上限 25 MiB、总计上限 100 MiB。

### 大结果请 `--output <文件>`

所有可能返回多条消息的命令都支持 `--output <path>`。指定后 stdout 只剩一行 `saved: /path/to.json`。被 AI 调用时特别重要 —— stdout 会直接进 AI 的 context window，动辄塞爆。

### 本地 cache

`channels` / `users --query` / `resolve` 从 actor namespace cache 读取，默认路径为
`<SKILL_DIR>/cache/<team>/<actor-principal>/`（根目录可用 `SLACK_SKILL_CACHE_DIR` 修改）。
首次使用自动拉全量，之后每 3 天自动刷新一次。

每次响应里都带 `cache_refresh: {...}` 段，告诉你这次有没有触发刷新。

### 报错

出错时 stderr 会有一行 `error: <code>`；已知的 Slack 错误码会紧跟一行 `hint: ...` 直接给下一步。退出码：

- `2` —— token 缺失 / argparse 参数错
- `3` —— 触发只读白名单（正常情况下不会发生）
- `4` —— 参数非法（例如格式错、channel 不在 `SLACK_SKILL_ALLOWED_CHANNELS` 白名单）
- `5` —— 写请求结果不确定；可能已成功，禁止自动重试或换身份
- `1` —— 其他（含 Slack API 返回的业务错误）

完整错误码 → 建议操作映射见 [`SKILL.md`](./SKILL.md) §8。

### Thread 回复 permalink 的坑

Slack UI 复制 thread 内某条回复的链接时，天然带 `?thread_ts=<root_ts>`。如果你是**自己从 ts 拼的** permalink，**一定要保留 `thread_ts` 这个 query param**，否则 Slack 查不到 reply，你会收到 `message_not_found`。

## 目录结构

```
slack/
├── SKILL.md           # 给 AI 的 usage（frontmatter + recipes）
├── README.md          # 本文件
├── .env.example       # 全部 env 变量，带完整注释
└── scripts/
    ├── slack.py       # sys.path shim → sk.cli.main
    └── sk/            # 按关注点拆分的 package
        ├── cli.py            # argparse + 错误 hint 映射
        ├── identity.py       # auth.test 身份分类
        ├── actor.py          # ActorContext + Bot/User 选择与预检
        ├── client.py         # urllib HTTP 客户端 + 只读白名单（GET 类）
        ├── write_client.py   # 写入路径（POST + 文件流），独立写白名单
        ├── config.py         # .env 加载 + token 路由
        ├── errors.py         # 自定义异常 + token 打码
        ├── cache.py          # 本地 JSON cache（users / channels / subteams）
        ├── channels.py       # 频道解析（#name → id）
        ├── files.py          # 附件下载（原子写 + 类别分类）
        ├── lookups.py        # 构造 id → 名字 的解析器
        ├── mentions.py       # <@U> 收集 + users.info 批量预取
        ├── block_kit.py      # Block Kit 文件校验与 mrkdwn 通知门禁
        ├── send_content.py   # Markdown/mrkdwn/plain 编译与通知门禁
        ├── message.py        # normalise_message() 统一消息形状
        ├── output.py         # emit()：stdout vs --output 文件
        ├── render.py         # Block Kit + markdown 渲染
        ├── shared.py         # --download-files 公共入口
        ├── timex.py          # --limit '1d' / '30m' 解析
        ├── urls.py           # permalink 解析
        └── cmd_*.py          # 每个子命令一个
```

## 开发须知

- 运行时仅依赖标准库，没有 build 步骤。
- `ast.parse` + `--help` 可以对每个模块做零网络调用的烟雾测试。
- 代码风格：stdlib typing、`from __future__ import annotations`、公共 helper 写 docstring。没配 lint，保持现有代码风格即可。
- **新增只读 Slack API 方法**必须加到 `client.py` 的 `READ_ONLY_METHODS` 白名单 —— 这是放宽读能力的唯一口子，顺便 review 一下确实是只读。
- **新增写方法**（不推荐，目前只允许 `files_upload` 这一条写路径）必须加到 `write_client.py` 的 `WRITE_METHODS`，并要求改动经过明确评审。

### 消息格式与离线验证

`send/edit` 均默认 Markdown，正文只发 `markdown_text`；
带 `--blocks-file` 时自动发送 `blocks + text fallback`，无需其它 format。
公开格式选项仅保留 markdown。
已有原生文本应迁入对应 Block Kit text object，不能只删除旧 format 参数而不检查语法。

[消息格式参考](references/message-formatting.md) 说明普通 Markdown，
[Block Kit 参考](references/block-kit.md) 提供选型与场景 JSON。

在仓库根目录执行：

```bash
python3 -m unittest discover -s slack/tests -p 'test_*.py'
python3 slack/scripts/slack.py send --help
python3 slack/scripts/slack.py edit --help
```

离线测试验证请求互斥、通知、作者与预览门禁，不证明客户端显示。
真实消息测试需具体授权；版本变更不代表已合入 main 或已同步安装环境。

## 使用范围

MoeGo 内部工具，不对外 license。
