# collab-calendar：日历 + 视频会议 + 妙记

合并 lark-cli 的 `lark-calendar`（日历日程）+ `lark-vc`（视频会议记录）+ `lark-minutes`（妙记）三个 skill。三者的边界由"未来 vs 已结束"和"会议本身 vs 录像产物"自然划分。

> 鉴权 / Permission denied 处理见 [`lark-shared.md`](./lark-shared.md)。

## 适用场景

- 日历 / 日程：查询 / 创建 / 更新日程，邀请参会人，忙闲查询，推荐空闲时段，会议室预定，RSVP 回复
- 视频会议：搜索已结束的历史会议记录、查询会议详情和参会人
- 会议纪要：AI 智能纪要、用户绑定纪要、逐字稿、共享文档
- 妙记：搜索妙记、获取妙记基础元数据、下载音视频媒体文件

## 命中的 lark-cli skill

- `lark-calendar`（calendar 命令组，v4 API）— 日历 / 日程
- `lark-vc`（vc 命令组，v1 API）— 已结束会议记录、纪要产物
- `lark-minutes`（minutes 命令组，v1 API）— 妙记元信息、媒体下载

## ⚠️ 三者的路由边界（决策树）

| 用户说 | 路由 |
|---|---|
| 未来日程 / agenda / 待开的会 / 今天还要开的会 / 帮我约个会 | `lark-calendar`（`+agenda`、`+create`、`+update`） |
| 已结束的会 / 昨天的会 / 上周的会 / 今天开过的会 | `lark-vc +search`（**不是 calendar `events search`**） |
| "今天有哪些会议" | **同时**用 `vc +search`（已开）+ `calendar +agenda`（未开）合并 |
| 妙记列表 / 我的妙记 / 某关键词妙记 | `minutes +search` |
| 妙记的标题 / 时长 / 封面 / 链接 | `minutes minutes get` |
| 妙记的视频 / 音频 / 下载 | `minutes +download` |
| 会议的纪要 / 逐字稿 / AI 总结 / 待办 / 章节 | `vc +notes`（**不是 minutes**） |
| 同时提到"会议"和"妙记" | 优先 `vc +search` 定位会议 → `vc +recording` 拿 minute_token |

## 核心概念

### Calendar / Event

- **Calendar 日历**：日程容器；每用户有一个主日历（primary calendar），可创建/订阅共享日历。
- **Event 日程**：日历单条日程；含起止时间、地点、标题、参与人；遵循 RFC5545 iCalendar；支持单次和重复。
- **All-day Event 全天日程**：只占日期，结束日期**包含**在日程内。
- **Instance 日程实例**：日程的具体时间实例（重复性日程会展开为 N 个 instance）；按时间段查询时返回 instance 视图。
- **Rrule 重复规则**：如 `FREQ=DAILY;UNTIL=20230307T155959Z;INTERVAL=14`（每 14 天一次）。
- **Exception 例外日程**：重复性日程中与原规则不一致的日程。
- **Attendee 参会人**：用户、群、会议室资源、外部邮箱地址；每个有独立 RSVP 状态。
- **FreeBusy 忙闲**：指定时间段的忙闲状态。
- **Room 会议室**：作为 resource attendee 加入日程，**不能脱离日程单独存在或单独预定**。
- **时间块（Time Slot）**：明确的连续时间段（如 14:00~15:00），与"时间范围"（"今天下午"）有严格区别。

### VC / Note / Minutes

```
Meeting (视频会议，meeting_id)
├── Note (会议纪要)
│   ├── MainDoc           (AI 智能纪要 → note_doc_token)
│   ├── MeetingNotes       (用户绑定纪要 → meeting_notes，仅 --calendar-event-ids 路径返回)
│   ├── VerbatimDoc       (逐字稿 → verbatim_doc_token)
│   └── SharedDoc         (会中共享文档)
└── Minutes (妙记，minute_token，+recording 从 meeting_id 拿)
    ├── Transcript / Summary / Todos / Chapters  → vc +notes
    └── MediaFile (音视频)                        → minutes +download
```

| 用户意图 | 用哪个 token |
|---|---|
| AI 总结 + 待办 + 章节 | `note_doc_token` |
| 用户主动绑定的纪要 | `meeting_notes`（仅 `--calendar-event-ids` 路径返回） |
| 逐字稿 / 完整记录 / 谁说了什么 | `verbatim_doc_token` |
| "纪要 / 总结 / 纪要内容" | 同时返回 `note_doc_token` 和 `meeting_notes`（如有） |

意图不明时**不要替用户决定**——展示所有可用文档链接让用户选。

## Shortcut 速查表

### lark-calendar

| Shortcut | 用途 | 关键 flag |
|---|---|---|
| `+agenda` | 看日程（默认今天） | `--start` `--end` `--user` |
| `+create` | 创建日程 + 邀请参会人 + 预定会议室 | `--summary` `--start` `--end` `--attendees` `--rooms` |
| `+update` | 更新既有日程 / 增删参会人 / 增删会议室 | `--event-id` 必填；`--add-attendees`/`--remove-attendees`/`--add-rooms`/`--remove-rooms` |
| `+freebusy` | 查主日历忙闲 + RSVP | `--user-ids` `--start` `--end` |
| `+room-find` | 给**确定时间块**找可用会议室 | `--start` `--end` `--building` |
| `+suggestion` | 给**模糊时间**推荐多个候选时间块 | `--range-start` `--range-end` `--duration` |
| `+rsvp` | 回复日程（接受 / 拒绝 / 待定） | `--event-id` `--reply accept/decline/tentative` |

### lark-vc

| Shortcut | 用途 | 关键 flag |
|---|---|---|
| `+search` | 搜历史会议记录 | 至少一个过滤条件：`--keyword` / `--start` / `--end` / `--organizer` / `--participant` / `--room` |
| `+notes` | 取纪要产物 | `--meeting-ids` 或 `--minute-tokens` 或 `--calendar-event-ids` |
| `+recording` | 由 meeting_id / event_id 拿 minute_token | `--meeting-ids` 或 `--calendar-event-ids` |

### lark-minutes

| Shortcut | 用途 | 关键 flag |
|---|---|---|
| `+search` | 搜妙记 | `--keyword` `--owners` `--participants` `--start` `--end` |
| `+download` | 下载妙记音视频 | `--minute-token` `--url-only`（仅取下载链接，1 天有效） |

## 预约日程 / 会议室——必看流程

涉及**预约日程 / 会议**或**查询/搜索可用会议室**时，**必须**遵循以下流程（这是 lark-cli 反复强调的强约束）：

1. **判断任务类型**：新建日程 vs 编辑已有日程
   - **编辑信号**：用户提到具体日程锚点（标题、时间段、"这个日程"、"这场会"）+ 修改动作（"添加""移除""改到""换会议室""调整时间"）。
   - **编辑前置**：MUST 先定位目标日程或具体实例的 `event_id`（重复性日程必须找到具体实例 ID，不能用原系列的 event_id）。
   - **新建**：仅当用户明确"新约 / 新建 / 安排一次"且没指向既有日程时。

2. **补默认值**：能补全的默认值先补；只有时间冲突 / 结果不唯一 / 时间语义歧义时才追问。做"智能助理"，不是"表单填写机"。

3. **判断时间是否明确**：
   - **明确时间** + 需要会议室 → 先 `+room-find`（基于已确定时间块），再按需 `+freebusy`。
   - **模糊时间 / 无时间** → 先 `+suggestion` 拿候选时间块；如需会议室再批量 `+room-find` 把候选时间块带入。
   - **编辑既有日程不改时间，仅加会议室** → 用已定位日程的**原始时间**做 `+room-find`。

4. **会议室增删语义**：
   - "添加会议室" / "再加一个会议室" → **增量添加**，保留已有。
   - "更换会议室" / "把原会议室换掉" / "移除会议室" → 才删除原会议室。

5. **候选方案必须给用户确认**：模糊时间、需要选会议室方案时，必须先展示候选给用户、等用户明确选择，**禁止擅自决定**。

6. **会议室≠房间**：用户说"房间"、"room"也按"会议室"理解。

7. **"查会议室"语义**：用户说"查会议室 / 找会议室 / 搜可用会议室 / 推荐常用会议室" 默认是查可用性，不是查资源名录，**严禁**拉历史日程做统计分析。

8. **没有明确时间不能直接 `+room-find`**：必须先 `+suggestion` 拿时间块再传给 `+room-find`。

## 时间与日期推断规范

- **星期定义**：周一 = 一周第一天，周日 = 最后一天。计算"下周一"基于真实当前日期。
- **"明天 / 今天"** = 整天范围；**不要**自缩范围（避免漏掉晚上）。
- **历史时间**：不能预约已完全过去的时间。例外：跨越当前时刻的日程（开始过去、结束未来）。
- **时间字符串 ↔ 时间戳转换**：必须调用系统命令 / 脚本工具，**不要**心算（这条是 calendar 文档明确强调的硬约束）。

## 修改 / 删除后的同步延迟

涉及 `events delete` / `events patch` / 加删参会人或会议室后，若需要二次查询验证，**必须等待至少 2 秒再查**——否则可能拉到旧数据。**不要向用户提及"等了 2 秒"**。

## 妙记内容下钻：第一个 `<whiteboard>` 是封面

读取 AI 智能纪要（`note_doc_token`）时，文档**第一个** `<whiteboard>` 标签是 AI 总结的可视化封面图，应同时下载展示给用户：

```bash
# 1. 读取纪要内容
lark-cli docs +fetch --api-version v2 --doc <note_doc_token> --doc-format markdown
# 2. 从 markdown 提取第一个 <whiteboard token="xxx"/> 的 token
# 3. 下载封面到聚合目录
lark-cli docs +media-download --type whiteboard --token <whiteboard_token> \
  --output ./minutes/<minute_token>/cover
```

并非所有纪要都有封面，没有 `<whiteboard>` 标签时跳过即可。

## 产物目录规范

同一会议的所有下载产物（录像、逐字稿、封面图等）统一放到 `./minutes/{minute_token}/`。这与 `minutes +download` 和 `vc +notes --minute-tokens` 默认落点一致，便于 Agent 聚合。显式路径（如封面图）需手动对齐到同一目录。

## 整理纪要的建议默认行为

1. 默认只给纪要文档和逐字稿**链接**，不读全文（除非用户明确要）。
2. 用户明确要总结 / 待办 / 章节时再 `docs +fetch` 读 `note_doc_token` 内容。
3. 取纪要文档基本信息（名 + URL）：`drive metas batch_query --data '{"request_docs":[{"doc_type":"docx","doc_token":"<doc_token>"}],"with_url":true}'`（一次最多 10 个）。

## 妙记 token 提取

妙记 URL：`http(s)://<host>/minutes/<minute-token>` → `minute-token` 是路径最后一段。如有 `?xxx` 等 query，截取路径末段。

## 典型示例

```bash
# A. 看今天日程
lark-cli calendar +agenda --as user

# B. 查未来一周某人忙闲
lark-cli calendar +freebusy --user-ids ou_xxx --start "2026-05-01T00:00:00+08:00" --end "2026-05-08T00:00:00+08:00" --as user

# C. 给"明天下午"找候选时间块（90 分钟会）
lark-cli calendar +suggestion --range-start "2026-05-01T13:00:00+08:00" --range-end "2026-05-01T18:00:00+08:00" --duration 90 --as user
# 拿到候选 → 用户确认 → 用确定时间块走 +room-find → +create

# D. 按会议室找：先有时间块再找会议室
lark-cli calendar +room-find --start "2026-05-01T14:00:00+08:00" --end "2026-05-01T15:30:00+08:00" --building "B 楼" --as user

# E. 给已有日程加 1 个会议室（保留已有）
lark-cli calendar +update --event-id <event_id> --add-rooms <room_id> --as user

# F. 搜昨天的历史会议
lark-cli vc +search --start "2026-04-29T00:00:00+08:00" --end "2026-04-29T23:59:59+08:00" --as user

# G. 取某会议的纪要（AI 总结 + 逐字稿）
lark-cli vc +notes --meeting-ids <meeting_id> --as user

# H. 由 calendar event 反查 minute_token
lark-cli vc +recording --calendar-event-ids <event_id> --as user

# I. 下载妙记视频
lark-cli minutes +download --minute-token <minute_token> --as user
```

## NEVER 规则（领域特有）

- ❌ **历史会议查询不要走 `calendar events search`**——只能查日程，缺即时会议。
  **如何应用**：历史一律 `vc +search`。

- ❌ **没有明确时间不要直接 `+room-find`**。
  **Why**：会拿到错误的"可用会议室"。
  **如何应用**：先 `+suggestion` 拿时间块。

- ❌ **不要把口语"日历"映射成日历容器操作**。
  **Why**：用户说"约个日历""查今天的日历"通常是要操作 Event。
  **如何应用**：默认按 Event 处理（`+create` / `+agenda`）。

- ❌ **重复性日程的实例操作不要传原系列 event_id**。
  **Why**：会改整条系列。
  **如何应用**：先 `events search_event` 或 `+agenda` 定位到具体实例的 `event_id`，再操作。

- ❌ **修改 / 删除后立刻验证不要直接查**——等至少 2 秒。**不要告诉用户你等了**。

- ❌ **加会议室不要默认替换原会议室**——除非用户明确说"换 / 移除"。

- ❌ **时间块 ≠ 时间范围**——预定 / 查会议室必须用确定时间块，不要把"今天下午"当时间块传。

- ❌ **`minutes +download` 不要用来取逐字稿**——它只下载音视频媒体；逐字稿走 `vc +notes`。

- ❌ **候选时间块 / 会议室方案不要替用户选**——展示候选 + 用户明确确认后再写。

## 不在本 reference 范围

- 文档 / 表格 / Base 的内容编辑 → [`content-doc.md`](./content-doc.md) / [`content-data.md`](./content-data.md)
- 在群里通知会议结果 → [`collab-im.md`](./collab-im.md)
- 把会议产物批量整理成报告 → [`workflow-meeting-summary.md`](./workflow-meeting-summary.md)

## 溯源

- lark-cli `skills/lark-calendar/SKILL.md`（v1.0.0，calendar v4）
- lark-cli `skills/lark-vc/SKILL.md`（v1.0.0，vc v1）
- lark-cli `skills/lark-minutes/SKILL.md`（v1.0.0，minutes v1）
