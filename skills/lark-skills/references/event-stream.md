# event-stream：实时事件订阅

对应 lark-cli 的 `lark-event`。把事件以 NDJSON 流式 push 到 stdout，专为 AI 子进程设计。

> 鉴权 / 身份 / Permission denied 处理见 [`lark-shared.md`](./lark-shared.md)。

## 适用场景

- 飞书 / Lark 机器人监听消息（`im.message.receive_v1`）
- 实时处理消息、表情回复、群成员变更
- 长时运行的订阅器、流式 webhook / push 处理
- AI 子进程作为事件消费者（NDJSON 输入 → 处理 → 业务）

## 命中的 lark-cli skill

- `lark-event`（event 命令组）

## 核心命令

| 命令 | 用途 |
|---|---|
| `lark-cli event list [--json]` | 列出所有可订阅的 EventKey |
| `lark-cli event schema <EventKey> [--json]` | 看某 EventKey 的 params 和输出 schema |
| `lark-cli event consume <EventKey> [flags]` | **阻塞消费**；事件以 NDJSON 写到 stdout |
| `lark-cli event status [--json] [--fail-on-orphan]` | 看本地 bus daemon 状态 |
| `lark-cli event stop [--all] [--force]` | 停 bus daemon |

## 通用 flag

| Flag | 说明 |
|---|---|
| `--param key=value` / `-p` | 业务参数（可重复；多值用逗号）。未知 key 报错并列出合法名 |
| `--jq <expr>` | jq 表达式过滤 / 转换每个事件；空输出跳过该事件 |
| `--max-events N` | N 个事件后退出。默认 0 = 不限 |
| `--timeout D` | D 后退出（如 `30s` / `2m`）。默认 0 = 不超时 |
| `--output-dir <dir>` | 每个事件落盘成文件（仅相对路径，防穿越） |
| `--quiet` | 抑制 stderr 诊断。**AI 不要用**——会屏蔽 ready marker |
| `--as user/bot/auto` | 身份 |

`--max-events` / `--timeout` 哪个先到都退出。

## 调用流程

1. `lark-cli event list --json` → 选合法 key
2. `lark-cli event schema <key> --json` → 读 `resolved_output_schema` + `jq_root_path` 确认字段路径
3. `lark-cli event consume <key> [--jq '<expr>']` → 消费

## 子进程契约（AI 调用必读）

### Ready marker（必看）

`event consume` 启动后会向 stderr 输出固定一行：

```
[event] ready event_key=<key>
```

**父进程必须在 stderr 等到这行后再读 stdout**。**不要 `sleep`**。

### stdin EOF = graceful shutdown

`event consume` 把 stdin 关闭当作关停信号（专为 AI 子进程设计）。`< /dev/null` / `nohup` / systemd 默认 `StandardInput=null` 会立刻 graceful 退出（stderr `reason: signal`）。

要持续运行：

```bash
# 喂一个永不 EOF 的源
lark-cli event consume <key> --as bot < <(tail -f /dev/null)

# 或带界限
lark-cli event consume <key> --max-events 100 --timeout 10m --as bot
```

### 退出码与 reason

退出时 stderr 最后一行：`[event] exited — received N event(s) in Xs (reason: ...)`。

| exit | reason | 触发 |
|---|---|---|
| 0 | `limit` | `--max-events` 到 |
| 0 | `timeout` | `--timeout` 到 |
| 0 | `signal` | Ctrl+C / SIGTERM / stdin EOF |
| 非 0 | `Error: ...`（无 `exited` 行） | 启动 / 运行时失败（权限 / 网络 / 参数 / 配置） |

编排器把 `limit/timeout/signal`（都是 exit 0）当"业务正常结束"；非 0 当失败。

### NEVER `kill -9`

EventKey 若有 PreConsume hook（用 OAPI 注册服务端订阅），`kill -9` 跳过 OAPI 反订阅，**会泄漏服务端订阅**——重启时报 "subscription already exists"，重复投递事件。

**要停**：用 SIGTERM 或关闭 stdin。

### 一个 consume 一个 EventKey

命令只接受一个 positional 参数；`k1,k2` 和通配符**不支持**。监听 N 个 key = N 个子进程，**这是有意设计**：

- 每进程 stdout 一种 shape，不需要 dispatcher
- 故障隔离（一个 key 出错不影响别的）
- 每个 key 独立的 `--as` / `--jq` / `--max-events` / `--timeout`

N 个 consumer 共用一个 bus daemon（UDS 本地 IPC），开销很小。

## 写 jq 看 schema 的 4 件事

`event schema <key> --json` 是写 `--jq` 的权威依据。

### (1) 字段从哪里开始 — `jq_root_path`

| 值 | 写法 |
|---|---|
| `"."` | 字段在顶层，写 `.chat_id` |
| `".event"` | 字段在 V2 envelope 内，写 `.event.chat_id` |

### (2) 字段列表 + 类型 — `resolved_output_schema.properties.<name>`

每个字段有 `type` / `description`，部分有 `format`。例（`im.message.receive_v1`）：

```json
{
  "chat_id":     {"type":"string","format":"chat_id","description":"Chat ID, prefixed with oc_"},
  "sender_id":   {"type":"string","format":"open_id","description":"Sender open_id, prefixed with ou_"},
  "create_time": {"type":"string","format":"timestamp_ms","description":"Send time as ms-epoch string"}
}
```

### (3) 字段语义 — `format` 标签

Lark 自定义语义（**不是** JSON Schema 标准 `format`）。常见：`open_id` / `chat_id` / `message_id` / `timestamp_ms` / `email`。用于区分"同 string 类型不同含义"，方便反查 API / 转格式。

### (4) 解码状态 — 看 `description`

`event consume` 跑 Process hook 可能**预解码**部分字段（V2 envelope 拍平、`.content` 渲染成纯文本等）——和裸 OAPI 行为不同。**写 jq 前先读 `description`**，特别是通用字段名 `content` / `data` / `body` / `payload`。

⚠️ 盲目对已解码字段 `fromjson`，jq 会在每个事件都报错并**静默丢弃**——consumer 看着活着但不发任何输出，stderr 只有一行 WARN。这是通用行为：jq runtime error 都会跳过事件 + 一行 WARN，循环不会中止。

> **不要短路 schema**：用 jq 投影 `event schema --json` 时**别去掉 `.description`**——它告诉你字段是否已解码。dump 完整 property 对象，不要只 dump key 名。

> **附**：`--param` 合法值也在 schema 里——`params` section 列 `name` / `type` / `required` / `enum` / `default` / `description`；**section 缺失 = 该 key 不接受 `--param`**。

## 典型示例

```bash
# A. 看可用的 EventKey
lark-cli event list

# B. 看 im.message.receive_v1 的 schema
lark-cli event schema im.message.receive_v1 --json | jq '.jq_root_path, .resolved_output_schema.properties'

# C. 默认：流式监听全部消息
lark-cli event consume im.message.receive_v1 --as bot

# D. 抓一条样本看结构
lark-cli event consume im.message.receive_v1 --max-events 1 --timeout 30s --as bot

# E. 跑 10 分钟自动退出
lark-cli event consume im.message.receive_v1 --timeout 10m --as bot

# F. 多 key 并发（一个 shape 一个进程）
lark-cli event consume im.message.receive_v1          --as bot > receive.ndjson &
lark-cli event consume im.message.reaction.created_v1 --as bot > reaction.ndjson &
wait

# G. 仅监听某 chat 的文本消息（jq 过滤）
lark-cli event consume im.message.receive_v1 \
  --jq 'select(.chat_id=="oc_xxx" and .message_type=="text") | {sender_id,content,create_time}' \
  --as bot

# H. 长跑：用 tail 永不 EOF 的 stdin
lark-cli event consume im.message.receive_v1 --as bot < <(tail -f /dev/null) > events.ndjson
```

## 主题索引（lark-cli 仓库内的细化文档）

| 主题 | 路径 |
|---|---|
| IM 11 个 EventKey 目录 + V2/Flat shape 笔记 + `im.message.receive_v1` 字段陷阱（`sender_id` 仅 open_id；`.content` 已渲染成纯文本——`interactive` 卡片除外）+ 常用 jq 配方（按 chat_type / message_type / sender 过滤） | lark-cli `lark-event/references/lark-event-im.md` |

## NEVER 规则（领域特有）

- ❌ **不要 `kill -9` consume 进程**——会泄漏服务端订阅；用 SIGTERM 或关 stdin。
- ❌ **AI 父进程不要 `--quiet`**——会屏蔽 ready marker，导致父进程没法判断什么时候开始读 stdout。
- ❌ **不要用 `sleep` 等启动**——必须 block 到 stderr 出现 `[event] ready event_key=<key>`。
- ❌ **不要在 stdin 给 `< /dev/null`** ——`event consume` 会立刻 graceful 退出。要持续：`< <(tail -f /dev/null)` 或 `--max-events`/`--timeout`。
- ❌ **不要对已解码字段 `fromjson`**——会静默丢全部事件，consumer 看似活着但不发输出。先看 schema 的 `description`。
- ❌ **不要凭一个 consume 监听多 key**——只接受一个 positional 参数，`k1,k2` / 通配符不支持；并发请用多进程。
- ❌ **`--output-dir` 不要传绝对 / 上层路径**——会被拒。
- ❌ **不要把非 0 退出当业务结束**——只有 `reason: limit/timeout/signal`（exit 0）算业务正常结束。

## 不在本 reference 范围

- 取/查 IM 历史消息 → [`collab-im.md`](./collab-im.md) 的 `+chat-messages-list` / `+messages-search`
- 邮件事件单独走 `mail +watch`（WebSocket）→ [`collab-mail.md`](./collab-mail.md)（与 event 命令组解耦）

## 溯源

- lark-cli `skills/lark-event/SKILL.md`（v1.0.0）
