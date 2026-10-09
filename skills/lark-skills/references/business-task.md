# business-task：飞书任务

对应 lark-cli 的 `lark-task`（v2 API）。

> 鉴权 / Permission denied 处理见 [`lark-shared.md`](./lark-shared.md)。

## 适用场景

- 创建 / 更新 / 删除任务，含截止时间 / 提醒 / 重复规则 / 起始时间
- 任务状态变更：完成 / 重开 / 评论
- 任务成员（assignee）和关注者（follower）管理
- 子任务（subtask）拆分
- 自定义分组（section）管理
- 任务清单（tasklist）CRUD + 清单成员
- 列表 / 搜索：按"分给我的"、"与我相关的"、关键词搜任务，搜清单
- 自定义字段（custom field）与字段选项

## 命中的 lark-cli skill

- `lark-task`（task 命令组）

## ⚠️ 全局关键规则

- **`task` 命令组使用 v2 API**——以 `lark-cli task --help` 实时输出为准。
- **跨租户加任务成员**：使用 `tenant_access_token`（`--as bot`）时**不能**跨租户加成员。需要跨租户必须 `--as user`。
- **创建/更新约束**：
  1. 只有设置了 `due`（截止时间）才能设 `repeat_rule`（重复规则）和 `reminder`（提醒）。
  2. 同时设了 `start` 和 `due` 时，`start ≤ due`。
- **任务 GUID ≠ 任务编号**：操作任务时 `guid` 是全局唯一标识（GUID），**不是** UI 上的 `t104121` / `suite_entity_num` 等编号。
- **任务 applink** 形如 `.../client/todo/task?guid=...` 时，URL query 里的 `guid` 就是 task guid。

## Shortcut 速查表

### 任务

| Shortcut | 用途 | 关键 flag |
|---|---|---|
| `+create` | 创建任务 | `--summary` `--description` `--due` `--start` `--reminder` `--repeat-rule` `--assignees` `--tasklist-guid` `--section-guid` |
| `+update` | 更新任务 | `--guid` 必填；可改 `--summary` `--due` `--description` 等 |
| `+complete` | 标记完成 | `--guid` |
| `+reopen` | 重开任务 | `--guid` |
| `+comment` | 加任务评论 | `--guid` `--content` |
| `+assign` | 加 / 删 任务成员 | `--guid` `--add ou_xxx,ou_yyy` `--remove ou_xxx` |
| `+followers` | 加 / 删 任务关注者 | `--guid` `--add` `--remove` |
| `+reminder` | 任务提醒增删（前提：已设 due） | `--guid` `--add <relative>` `--remove <id>` |
| `+set-ancestor` | 设/清祖任务（建立任务树） | `--guid` `--ancestor` 或 `--clear` |
| `+subscribe-event` | 订阅任务事件 | 见 [`event-stream.md`](./event-stream.md) |

### 列表 / 搜索（决策很重要）

| Shortcut | 用途 | 何时用 |
|---|---|---|
| `+get-my-tasks` | 列出**分给我**的任务 | 用户说"我负责的 / 分配给我的" |
| `+get-related-tasks` | 列出**与我相关**的任务（创建、关注、协作） | 用户说"与我相关 / 我关注的 / 由我创建" |
| `+search` | 关键词搜索任务 | 用户**特地说要搜索**或**给了查询关键字** |
| `+tasklist-search` | 关键词搜清单 | 同上但目标是清单 |

### 任务清单 / 自定义分组

| Shortcut | 用途 | 关键 flag |
|---|---|---|
| `+tasklist-create` | 建清单（可批量添加任务） | `--name` `--tasks <guid1,guid2>` |
| `+tasklist-task-add` | 把已有任务加进清单 | `--tasklist-guid` `--task-guids` |
| `+tasklist-members` | 管理清单成员 | `--tasklist-guid` `--add` `--remove` `--role member/admin` |

> 自定义分组（sections）目前没有 shortcut，用原生 API：`task sections create/list/patch/delete/tasks`。

## 列表 vs 搜索决策（重要）

> 这是 lark-task 的核心判断点，决定是否走错路。

| 用户表达 | 优先用 |
|---|---|
| "搜索带关键字 X 的任务" / 明确说要搜索 + 给关键字 | `+search` |
| "今年以来 / 已完成 / 由我创建 / 我关注的" 等**只有范围条件、无关键字** | `+get-related-tasks`（与我相关 / 我关注 / 由我创建） |
| "我负责的 / 分配给我的" 范围条件 | `+get-my-tasks` |
| "搜索带关键字 X 的清单" | `+tasklist-search` |
| "由我创建 / 今年以来创建的清单"（**仅范围条件**） | 原生 `tasklists.list` + 本地按 `creator` / `created_at` 筛选 |

特别注意"**搜索**今年以来我关注的任务"这类带"搜索"字样但**没真正关键字**的表达——本质是范围限定，应优先走 `+get-related-tasks`，**不要**把"今年以来"当作 `query` 字符串送去搜索。

> **用户提"我"时**：在 user 身份下默认获取当前登录用户的 `open_id` 作为参数。
> **用户提 "todo / 待办"**：思考是否指 task，优先用本 reference 命令处理。

## 输出建议

- 输出任务 / 清单结果时**带上 `url` 字段**（任务/清单链接），方便用户点击跳转。
- 渲染 `assignee` / `creator` / `owner` / `member` 等人员字段时，**除了 id 还要查真实姓名**——通过 [`collab-im.md`](./collab-im.md)（`contact +get-user` / `contact +search-user`）解析 open_id → 姓名。
- 时间字段（创建时间、截止时间）用**本地时区**渲染，格式 `2006-01-02 15:04:05`。

## 自定义字段

```bash
# 创建字段（在某资源类型上，如清单）
lark-cli task custom_fields create --params '{"resource_type":"tasklist","resource_id":"<id>"}' \
  --data '{"name":"优先级","type":"single_select"}'

# 增加字段选项
lark-cli task custom_field_options create --params '{"custom_field_guid":"<guid>"}' \
  --data '{"name":"高","color":1}'

# 把字段挂到资源
lark-cli task custom_fields add --params '{"custom_field_guid":"<guid>"}' \
  --data '{"resource_type":"tasklist","resource_id":"<id>"}'
```

## 典型示例

```bash
# A. 创建一个有截止时间和提醒的任务
lark-cli task +create --summary "写设计文档" \
  --due "2026-05-05T18:00:00+08:00" \
  --reminder "1d" --reminder "1h" \
  --description "/specs 下" --as user

# B. 给任务加成员（同租户）
lark-cli contact +search-user --query "王五" --as user      # 拿 ou_xxx
lark-cli task +assign --guid <task_guid> --add ou_xxx --as user

# C. 列我的待办（分给我的）
lark-cli task +get-my-tasks --completed false --as user

# D. 搜关键字
lark-cli task +search --query "release v2" --as user

# E. 加子任务
lark-cli task subtasks create --params '{"task_guid":"<parent_guid>"}' \
  --data '{"summary":"先调研"}'

# F. 创建清单并把已有任务加进去
lark-cli task +tasklist-create --name "Q2 路线图" \
  --tasks <guid1>,<guid2> --as user

# G. 完成任务
lark-cli task +complete --guid <task_guid> --as user
```

## NEVER 规则（领域特有）

- ❌ **不要把 UI 编号（`t104121` / `suite_entity_num`）当 task guid 用**。
  **Why**：API 只认 GUID。
  **如何应用**：从 applink `?guid=...` 提取，或用搜索/列表返回的 `guid` 字段。

- ❌ **不要在没设 `due` 的情况下设 `repeat_rule` / `reminder`**。
  **Why**：API 强制约束。
  **如何应用**：先确保任务有 `--due`，再加重复 / 提醒。

- ❌ **不要用 `--as bot`（tenant_access_token）跨租户加任务成员**。
  **Why**：API 不允许。
  **如何应用**：跨租户场景必须 `--as user`。

- ❌ **不要把"今年以来 / 已完成"当作搜索关键字**。
  **Why**：会走错命令、返回不相关结果。
  **如何应用**：纯范围条件用 `+get-my-tasks` / `+get-related-tasks`；有真关键字才 `+search`。

- ❌ **输出任务详情时不要只展示 open_id**。
  **Why**：用户难辨识。
  **如何应用**：解析为真实姓名（走 [`collab-im.md`](./collab-im.md) 的 contact）。

## 不在本 reference 范围

- 任务事件订阅的具体监听协议 → [`event-stream.md`](./event-stream.md)（这里只指出 `+subscribe-event` 入口）
- 把任务输出在群里"通知" → 配合 [`collab-im.md`](./collab-im.md)
- 把任务关联到日历日程 → 配合 [`collab-calendar.md`](./collab-calendar.md)（不是直接 API）

## 溯源

- lark-cli `skills/lark-task/SKILL.md`（v1.0.0，task v2 API）
