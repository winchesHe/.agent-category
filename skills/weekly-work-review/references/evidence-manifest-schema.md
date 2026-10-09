# Evidence Manifest Schema

`weekly-work-review` 每次生成或更新归档包时，必须写入：

- `evidence-manifest.json`：机器可读账本
- `evidence-manifest.md`：人类可读覆盖报告

Manifest 的目标是让“采集了什么、没采集什么、哪些证据进入正文、哪些被排除”可审计。它不是原始证据 dump。

当前 schema 为 `1.2`。

> **字段必填性、类型和枚举以 `references/evidence-manifest.schema.json` 为准。** 本文件解释语义和写作规则，不重复声明必填字段——避免两处漂移。validator 直接对该 JSON Schema 校验，违规报 `MANIFEST-001`。

1.2 相对 1.1 的变化：

| 字段 | 变化 |
|---|---|
| `iso_week` | 新增必填。机器元数据，形如 `2026-W32`，不进入目录名 |
| `week_label` | 新增必填。人可读日期范围，必须等于周目录名 |
| `report_path` | 新增必填。周目录内主报告文件名，形如 `<日期范围> 周复盘.md` |
| `archive_shape` | 由 `flat-week-dir` 改为 `date-range-week-dir` |
| `candidate_items[].agent` | 可选。session 候选记录来源 agent |
| `candidate_items[].meeting_note_link` | 可选。指向 `工作/会议` 权威归档 |
| `candidate_items[].transcript_status` | 可选。转写内容质量分类 |
| `coverage_summary.session_agents` | 可选。本周各 agent session 计数 |

## JSON 顶层字段

```json
{
  "schema_version": "1.2",
  "week_start": "2026-08-03",
  "week_end": "2026-08-09",
  "iso_week": "2026-W32",
  "week_label": "2026-08-03 至 08-09",
  "timezone": "Asia/Shanghai",
  "archive_dir": "<vault>/工作/周报/2026/08/2026-08-03 至 08-09",
  "archive_shape": "date-range-week-dir",
  "report_path": "2026-08-03 至 08-09 周复盘.md",
  "generated_at": "2026-08-09T12:00:00Z",
  "sources_scanned": {},
  "queries_run": [],
  "empty_results": [],
  "candidate_items": [],
  "output_items": [],
  "indexed_items": [],
  "used_in_report": [],
  "excluded_with_reason": [],
  "coverage_summary": {}
}
```

`archive_dir` 只按尾部 `<YYYY>/<MM>/<日期范围>` 三段校验，归档包可以整体移动或复制。

## Required Sources

`sources_scanned` 必须包含以下 key。没有执行也必须出现，并写明原因。

```json
{
  "sessions": {},
  "slack_outbound": {},
  "slack_inbound": {},
  "lark_vc": {},
  "lark_calendar": {},
  "lark_minutes_owner": {},
  "lark_minutes_participant": {},
  "shared_clip_link_extraction": {},
  "shared_clip_keyword_search": {},
  "lark_drive_docs": {},
  "local_vault_notes": {},
  "personal_outputs": {},
  "github_activity": {},
  "jira_linear_worklog": {}
}
```

每个 source object 必须包含：

```json
{
  "status": "scanned | zero_result | skipped_by_user | tool_unavailable | permission_denied | not_applicable | partial",
  "tool": "string",
  "query": "string",
  "artifact_path": "string",
  "raw_count": 0,
  "candidate_count": 0,
  "used_count": 0,
  "skipped_reason": "string"
}
```

规则：

- `status=scanned` 或 `partial` 时，`tool` 和 `query` 或 `artifact_path` 至少一个非空
- `status=zero_result` 时，必须在 `empty_results[]` 中记录查询
- `status=tool_unavailable`、`permission_denied`、`skipped_by_user` 时，`skipped_reason` 必须非空
- `raw_count > 0` 或 `candidate_count > 0` 但 `used_count = 0` 时，必须在 `excluded_with_reason[]` 中解释

## Candidate Item

`candidate_items[]` 记录所有高信号证据，不记录原始日志全文。

```json
{
  "id": "stable-id",
  "type": "session | meeting | shared-clip | shared-minute | slack-thread | doc | local-note | github | jira-linear",
  "title": "string",
  "date": "YYYY-MM-DD",
  "source_key": "one key from sources_scanned",
  "source": "sessions | slack | lark | local-vault | github | jira-linear",
  "source_path_or_token": "path/token/url",
  "discovery_method": "string",
  "evidence_ref": "string",
  "used_in": ["周复盘.md#主要推进"],
  "confidence": "high | medium | low",
  "sensitivity": "public | personal | internal | confidential | restricted",
  "note_doc_token": "optional docx token for meeting-note PDF export",
  "note_doc_url": "optional docx URL for meeting-note PDF export",
  "verbatim_doc_token": "optional docx token extracted from meeting-note bottom 文字记录 link",
  "verbatim_doc_url": "optional docx URL extracted from meeting-note bottom 文字记录 link",
  "pdf_export_path": "optional archive-relative path, e.g. meetings/<folder>/exports/飞书原始纪要.pdf",
  "pdf_unavailable_reason": "optional reason when note_doc_token/note_doc_url is unavailable"
}
```

Shared clips 的额外字段：

```json
{
  "minute_token": "obcn...",
  "shared_by": "string",
  "local_context_path": "Work/MoeGo/记录/...",
  "keyword_hits": ["Manager 101", "Delegation"],
  "token_unavailable_reason": ""
}
```

## Output Item

`output_items[]` 是个人复盘的完整产出账本。它记录实质结果，不记录所有活动或中间文件。

```json
{
  "id": "stable-output-id",
  "category": "company-delivery | engineering | operations | communication | writing-creation | knowledge-system | personal-project",
  "title": "string",
  "status": "published | completed | live | in-progress | blocked | paused",
  "evidence_refs": ["candidate-id"],
  "report_anchor": "string that appears in 周复盘.md",
  "used_in": ["周复盘.md#本周产出总账"],
  "sprint_review_selected": false
}
```

规则：

- 所有有证据的实质产出都必须进入 `output_items[]`
- 每项至少有一个 `evidence_refs`，引用现有 `candidate_items[].id`
- 每项 `used_in` 必须非空，并至少指向 `周复盘.md#本周产出总账`
- `report_anchor` 必须能在 `周复盘.md` 中回读
- `sprint_review_selected=false` 只表示不进入 Sprint Review，不得因此排除个人复盘
- 同一工作流的多个文件可以合并成一个产出；仅参会、重复同步、无产物探索和自动生成的中间文件不单列
- 每个 `candidate_items[]` 必须且只能二选一：进入正文/某个 `output_item.evidence_refs`，或进入 `excluded_with_reason`；禁止候选证据静默消失，也禁止同时 used 和 excluded
- `coverage_summary.total_candidates` / `total_used` 必须与 manifest 实际分类回读一致

## Indexed Item

`indexed_items[]` 记录已经写入归档索引的证据。

```json
{
  "candidate_id": "stable-id",
  "index_path": "meetings/会议索引.md",
  "row_key": "minute_token or meeting_id",
  "source_type": "vc | calendar | minutes-owner | minutes-participant | shared-minute | shared-clip | manual-link"
}
```

规则：

- `type=shared-clip` 或 `type=shared-minute` 的 candidate 必须有对应 indexed item
- `source_type=shared-clip` 的 indexed item 必须保留 `minute_token`，除非 candidate 写明 `token_unavailable_reason`

## Used In Report

`used_in_report[]` 记录进入 `周复盘.md` 的证据锚点。

```json
{
  "candidate_id": "stable-id",
  "report_section": "主要推进 / 协作与沟通 / 风险、遗留问题与下周建议",
  "anchor_text": "string",
  "claim_supported": "string"
}
```

规则：

- `主要推进` 每个小节至少有一个 used item
- `可直接贴到 Sprint Review 的内容` 每条至少有一个 used item；没有时该条必须标记 `待复核`
- 非空 source 至少 1 条进入正文，或写入排除理由

## Excluded With Reason

`excluded_with_reason[]` 记录已收集但未进入正文的证据。

```json
{
  "candidate_id": "stable-id",
  "reason": "background | duplicate | low-signal | sensitive | off-scope | superseded | already-covered",
  "detail": "string"
}
```

## Coverage Summary

```json
{
  "total_candidates": 0,
  "total_used": 0,
  "total_outputs": 0,
  "outputs_in_report": 0,
  "output_coverage_ratio": 1.0,
  "high_signal_candidates": 0,
  "high_signal_used": 0,
  "high_signal_usage_ratio": 0.0,
  "shared_clip_candidates": 0,
  "shared_clip_indexed": 0,
  "sources_missing": [],
  "low_usage_explanation": ""
}
```

Quality gate：

- `output_coverage_ratio` 必须为 `1.0`
- `high_signal_usage_ratio` 目标为 `>= 0.7`
- 未达到时，`coverage_summary.low_usage_explanation` 和 `evidence-manifest.md` 必须解释原因
- `shared_clip_candidates` 必须等于 `shared_clip_indexed`，除非候选项写明 `token_unavailable_reason`
- Lark meeting 若有 `note_doc_token` / `note_doc_url`，必须导出 `exports/飞书原始纪要.pdf`；若纪要文档 token 不可用，必须写 `pdf_unavailable_reason`。缺 PDF 且无原因时 validator 应失败。

## Markdown Report

`evidence-manifest.md` 必须包含这些标题：

```markdown
## Coverage Matrix
## Queries Run
## Empty Results
## Candidate Evidence
## Used In Report
## Excluded With Reason
## Shared Clip Discovery
## Validation Readback
```

`Validation Readback` 必须记录真实 validator 结果，包含 `passed` 或 `failed`。只记录执行命令不算 readback。

Slack collaboration summary 优先写入 `evidence-manifest.md`，只保留人类可读摘要：主要话题、关键决策/行动/handoff、links、低信号 chatter 排除口径。raw Slack JSON、thread detail 和 DM 明细只保留在 scratch。

Lark meeting candidate 可记录 `verbatim_doc_token` / `verbatim_doc_url`，来源应优先是会议纪要底部 `文字记录` docx 链接。转写正文归档应通过 `docs +fetch` 读取该 docx，而不是默认用妙记/minutes 链接导出。

禁止在 `evidence-manifest.md` 中粘贴完整 Slack 原文、完整 session prompt/tail、密钥、customer PII 或未脱敏工具输出。
