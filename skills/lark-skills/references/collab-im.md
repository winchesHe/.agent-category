# collab-im：即时通讯 + 通讯录

合并 lark-cli 的 `lark-im` 和 `lark-contact` 两个 skill。

> 鉴权 / 身份 / Permission denied 处理见 [`lark-shared.md`](./lark-shared.md)。

## 适用场景

- 发消息 / 回复消息（包括线程回复）/ 撤回消息
- 群聊管理：创建群、查群、改群名、列群成员、加 / 移群成员
- 聊天搜索：按关键词搜消息（user 身份），按群名搜 chat_id
- 表情回复（reactions）增删查
- 消息 Pin
- 上传 / 下载消息中的图片、文件、音视频（大文件分片）
- **姓名 / 邮箱 ↔ open_id 互转**（contact 部分）

## 命中的 lark-cli skill

- `lark-im`（消息、群、表情、Pin、资源上传下载）
- `lark-contact`（按姓名 / 邮箱搜员工、按 open_id 取资料）

## 核心概念

```
Chat (oc_xxx)                ← 群聊或 P2P 会话
├── Message (om_xxx)         ← 单条消息
│   ├── Thread (om_/omt_xxx) ← 回复线程
│   ├── Reaction             ← 表情回复
│   └── Resource             ← 图片 / 文件 / 音视频
└── Member (user / bot)
```

| 实体 | ID 前缀 | 解析方式 |
|---|---|---|
| 群聊 / P2P chat | `oc_xxx` | `+chat-search` 按群名 |
| 消息 | `om_xxx` | 由 message-list / send 返回 |
| 用户 | `ou_xxx`（open_id）/ union_id / user_id | `contact +search-user` 按姓名 / 邮箱 |

## Shortcut 速查表（推荐优先用）

### 消息 / 群聊（lark-im）

| Shortcut | 用途 | 身份 | 关键 flag |
|---|---|---|---|
| `+chat-create` | 创建群 | user/bot | `--name` `--users` `--bots` `--mode private/public` |
| `+chat-search` | 按群名 / 成员搜可见群 → chat_id | user/bot | `--query` 或 `--member-ids` |
| `+chat-update` | 改群名 / 群描述 | user/bot | `--chat-id` `--name` `--description` |
| `+chat-messages-list` | 列出群或 P2P 的消息 | user/bot | `--chat-id` 或 `--user-id`（自动解析 P2P） |
| `+messages-send` | 发消息（chat 或 DM） | user/bot | `--chat-id` 或 `--user-id` + `--text/--markdown/--post/--media` |
| `+messages-reply` | 回复消息（含线程） | user/bot | `--message-id` `--text/...` `--reply-in-thread` |
| `+messages-mget` | 批量取消息（≤50 条 om_id） | user/bot | `--message-ids` |
| `+messages-search` | 跨群搜索消息 | **user only** | `--keyword` `--chat-id` `--from-id` `--start` `--end` `--page-all` |
| `+messages-resources-download` | 下载消息中的图/文件/音视频 | user/bot | `--message-id` `--file-key`；大文件自动分片 |
| `+threads-messages-list` | 列出线程内的回复 | user/bot | `--message-id`（om_/omt_） |

### 通讯录（lark-contact）

| Shortcut | 用途 | 身份 | 关键 flag |
|---|---|---|---|
| `+search-user` | 按姓名 / 邮箱搜员工拿 open_id | **user only** | `--query "<姓名或邮箱>"` `--has-chatted`（仅曾联系过的） |
| `+get-user` | 已知 open_id 取详细资料 | user/bot | `--user-id <id>` `--user-id-type open_id/union_id/user_id` |

### 选哪个命令（contact 决策）

| 想做什么 | user 身份 | bot 身份 |
|---|---|---|
| 按姓名 / 邮箱搜员工 → open_id | `+search-user` | **不支持**（bot 没有用户级搜索） |
| 已知 open_id 取他人资料 | `+search-user --user-ids <id>` | `+get-user --user-id <id>` |
| 查自己 | `+get-user` 或 `+search-user --user-ids me` | 不支持 |

## 表情 / Pin / 原生 API

- 表情回复：`reactions.batch_query / create / delete / list`（必读 `lark-cli im reactions --help`）
- Pin 消息：`pins.create / delete / list`
- 其它原生 API：`lark-cli schema im.<resource>.<method>` 看参数 → `lark-cli im <resource> <method> [...]`

## 身份与权限要点

- `--as user` 用 `user_access_token`，权限受用户 + scope 双重约束。
- `--as bot` 用 `tenant_access_token`，权限受 app 可见范围 + bot 是否在群 + bot scope 影响。
- **同一 API 在两种身份下的成功条件不同**——失败时先确认身份是否合理（详见 [`lark-shared.md`](./lark-shared.md) §3）。
- 用 bot 身份拉消息时，**发件人姓名可能解析不出来**（显示 open_id），原因是 bot app 的可见范围未覆盖发件人。解决：调整 app 可见范围或换 user 身份。
- 卡片消息（`interactive`）在事件订阅里**未支持紧凑转换**，会返回原始 event 数据并 stderr 提示。

## 典型示例

```bash
# 1. 给某人发消息（不知道 open_id）—— 先 search 后 send
lark-cli contact +search-user --query "张三" --has-chatted --as user
# → 拿到 ou_xxx 后
lark-cli im +messages-send --user-id ou_xxx --text "Hi!" --as user

# 2. 找一个群（不知道 chat_id）—— 按群名搜
lark-cli im +chat-search --query "项目周会" --as user

# 3. 给群发 markdown 消息
lark-cli im +messages-send --chat-id oc_xxx --markdown "**今日重点**：...\n- A\n- B" --as user

# 4. 回复某条消息（线程内）
lark-cli im +messages-reply --message-id om_xxx --text "ack" --reply-in-thread --as user

# 5. 跨群搜索消息（仅 user 身份）
lark-cli im +messages-search --keyword "故障" --start "2026-04-01" --end "2026-04-30" --page-all --as user

# 6. 下载消息中的图片 / 文件
lark-cli im +messages-resources-download --message-id om_xxx --file-key file_xxx --output ./tmp/ --as user

# 7. 在群里加表情
lark-cli im reactions create --message-id om_xxx --emoji-type "THUMBSUP" --as user
```

## NEVER 规则（领域特有）

- ❌ **不要凭空造 chat_id / open_id**。用户提"群"或"某人"时，先用 `+chat-search` / `+search-user` 解析。
  **Why**：编造的 ID 会调用错对象（错群发消息不可逆）。
  **如何应用**：search 命中多条且后续操作有副作用（发消息、邀请等）时，把候选列给用户挑，不要默认选第一条。

- ❌ **不要让 bot 身份去搜员工**。`contact +search-user` 仅 user 身份可用。
  **Why**：bot 没有用户级搜索权限。
  **如何应用**：用 user 身份做名字解析后，可以再用 bot 身份发消息（如果业务需要 bot 名义）。

- ❌ **跨租户用户的业务字段多数为空**（`is_cross_tenant=true`）。
  **Why**：飞书可见性规则。
  **如何应用**：下游做空值兜底，不要把空字段当作"用户不存在"。

- ❌ **bot 身份发的消息以 app 名义发送**，不是替用户发。需要"以用户名义"必须 `--as user`。

## 不在本 reference 范围

- 部门树遍历 / 按部门列员工 / 组织架构图 → [`openapi-explorer.md`](./openapi-explorer.md) 找原生 API。
- 实时接收消息（长连接订阅）→ [`event-stream.md`](./event-stream.md)。

## 溯源

- lark-cli `skills/lark-im/SKILL.md`（v1.0.0）
- lark-cli `skills/lark-contact/SKILL.md`（v1.0.0）
