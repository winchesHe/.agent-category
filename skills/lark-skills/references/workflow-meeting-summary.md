# workflow-meeting-summary：会议纪要汇总报告

对应 lark-cli 的 `lark-workflow-meeting-summary`。这是一个**组合工作流**——编排 vc + drive + （可选）docs，把指定时间范围内的会议纪要汇总成结构化报告。

> 鉴权 / 身份处理见 [`lark-shared.md`](./lark-shared.md)。
> 单领域命令详见 [`collab-calendar.md`](./collab-calendar.md)（vc 部分）和 [`content-doc.md`](./content-doc.md)（drive / docs）。

## 适用场景

- "帮我整理这周的会议纪要" / "总结最近的会议" / "生成会议周报"
- "看看今天开了哪些会" / "回顾过去一周开了哪些会"
- "整理某个时间范围的会议产物"

## 前置条件

⚠️ **仅支持 user 身份**（`--as user`）。涉及的 scope 域：`vc`（搜索 + 取纪要）+ `drive`（取纪要文档元信息、创建汇总文档）。

## 工作流概览

```
{时间范围}
   │
   ▼
vc +search           ──► 会议列表（meeting_ids）
   │
   ▼
vc +notes            ──► 纪要 doc tokens（note_doc_token / verbatim_doc_token）
   │
   ▼
drive metas batch_query  ──► 文档名 + URL（≤10 个/次）
   │
   ▼
AI 整理结构化报告（用户要求时按 content-doc 的创建流程生成在线文档）
```

## Step 1：确定时间范围

默认 **过去 7 天**。常见推断：

| 用户说 | 解析 |
|---|---|
| "今天" | 当天 0:00 – 23:59 |
| "这周" | 本周一 – 现在 |
| "上周" | 上周一 – 上周日 |
| "这个月" | 本月 1 日 – 现在 |
| "最近一周" / 默认 | 过去 7 天 |

⚠️ **日期转换必须用系统命令**（如 `date`），**不要心算**。
时间格式按 CLI 实际要求，通常 `YYYY-MM-DD` 或 ISO 8601。

## Step 2：搜会议记录

```bash
lark-cli vc +search --start "<YYYY-MM-DD>" --end "<YYYY-MM-DD>" \
  --format json --page-size 30 --as user
```

约束：
- **`--end` 包含当天**（查"今天" → start 和 end 都填今天）
- **`--page-size` 最大 30**——超过得翻页（看 `page_token`）
- **单次时间范围最大 1 个月**——更长时间段必须**拆分**多次调用
- 收集所有结果的 `id` 字段（meeting-id）

## Step 3：取纪要 token

```bash
# 单次最多 50 个 meeting-id；超过分批
lark-cli vc +notes --meeting-ids "id1,id2,...,idN" --as user
```

返回中：
- `note_doc_token` — AI 智能纪要文档 token
- `verbatim_doc_token` — 逐字稿文档 token
- `meeting_notes` — 用户绑定的会议纪要文档（**仅 `--calendar-event-ids` 路径返回**，本工作流不一定有）

部分会议返回 `no notes available` → 在最终报告标注**"无纪要"**。

## Step 4：取纪要 / 逐字稿文档元信息

```bash
# 看用法
lark-cli schema drive.metas.batch_query

# 单次最多 10 个文档
lark-cli drive metas batch_query --as user \
  --data '{"request_docs":[{"doc_type":"docx","doc_token":"<doc_token>"}],"with_url":true}'
```

得到每个文档的 `name` + `url` 用于呈现。

## Step 5：生成结构化报告

按时间跨度选格式：

### 单日（"今天" / "昨天"）

```markdown
# 今日会议概览（YYYY-MM-DD）

## 会议 1：<会议主题>
- 时间：HH:mm – HH:mm
- 组织者：<姓名>
- 纪要：[<doc_name>](<url>)
- 逐字稿：[<doc_name>](<url>)

## 会议 2：...

## 小结
- 共 N 场会议
- 无纪要：M 场（标注列表）
```

### 多日 / 周报

```markdown
# 会议纪要周报（<start> ~ <end>）

## 概览
- 时间范围：YYYY-MM-DD ~ YYYY-MM-DD
- 共 N 场会议（含 M 场无纪要）

## 会议详情
（按时间倒序或正序列出，每场含主题、时间、纪要 / 逐字稿链接）
```

## Step 6（可选）：生成在线文档

用户要求生成在线文档时，读取 [`content-doc.md`](./content-doc.md) 的“创建文档（默认 Wiki）”与 [`content-doc-rich-text.md`](./content-doc-rich-text.md)，按统一流程选择位置、组织丰富文本并回读。Step 5 的 Markdown 仅为报告内容示意，不决定飞书写入格式。用户指定追加到已有文档时，按文档写入规则追加，不新建节点。

## NEVER 规则（领域特有）

- ❌ **不要用 calendar `events search` 当历史会议查询入口**——会缺即时会议，必须 `vc +search`。
- ❌ **不要心算日期 / 时区**——必用 `date` 等系统命令转换。
- ❌ **`vc +search` 单次范围超过 1 个月会失败**——拆分调用。
- ❌ **`vc +notes` 单次超过 50 个 ID 会失败**——分批。
- ❌ **`drive metas batch_query` 单次超过 10 个 doc 会失败**——分批。
- ❌ **不要替用户读纪要全文**——默认只给链接；除非用户明确要总结/章节内容才读 `note_doc_token` 内容。
- ❌ **不要静默忽略"无纪要"会议**——汇总里要标注，避免用户以为遗漏。

## 不在本 reference 范围

- 取纪要内容里的具体段落 / 总结 / 待办 / 章节 → [`collab-calendar.md`](./collab-calendar.md) 的 `vc +notes` 详细字段说明
- 给生成的汇总文档加权限 / 评论 → [`content-doc.md`](./content-doc.md)
- 把汇总结果发到群里 → [`collab-im.md`](./collab-im.md)

## 溯源

- lark-cli `skills/lark-workflow-meeting-summary/SKILL.md`（v1.0.0）
