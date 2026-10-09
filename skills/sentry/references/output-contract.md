# Output Contract

Default target is `json`. Schema version: `2`.

字段分为两类：`issue`、`events`、`exceptions`、`breadcrumbs` 主要承载 API 观测；`analysis`、`root_cause_candidates`、`backend_correlation`、`repo_candidates` 和 `summary` 包含工具推断。顶层 `exceptions` / `breadcrumbs` 可以跨样本聚合，而 `exception_chain`、route context 与 `backend_correlation` 只基于 `selected_event`。消费者必须保留这些差异，不能跨 event 拼接因果，也不能把 confidence 或 recommended fix 当成代码层已验证结论。

## Top-level required fields

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | `int` | Always `2` |
| `ok` | `bool` | Overall success/failure |
| `input` | `object` | Echo of input parameters (url, mode, events, target) |
| `issue` | `object` | Normalized issue metadata |
| `selected_event` | `object` | Primary event used for analysis |
| `events` | `array` | All fetched events (normalized) |
| `exceptions` | `array` | Extracted exception entries with frames |
| `breadcrumbs` | `array` | Merged breadcrumb timeline |
| `analysis` | `object` | Semantic analysis (exception_chain, route_context, fix_boundary); fix boundary 仅是待源码验证的调查位置 |
| `root_cause_candidates` | `array` | Ranked root cause hypotheses with confidence |
| `backend_correlation` | `object` | Datadog correlation status, observed failing requests and queries; service 过滤仅来自显式 breadcrumb 字段 |
| `repo_candidates` | `array` | Candidate repos with confidence scores |
| `summary` | `object` | Human-readable summaries for rendering |
| `warnings` | `array<string>` | Non-fatal issues during processing |
| `errors` | `array<string>` | Fatal issues (when `ok` is `false`) |

`analysis.fix_boundary.upstream_repo` 表示异常时间链里的前置触发候选，`downstream_repo` 表示直接崩溃候选；两者不是包依赖方向。`recommended_first_fix` 与 `recommended_followup_fix` 是调查顺序，不是已确认的代码修改。`backend_correlation.requests` 保留观测到的 method、URL、status、timestamp 与可选 service；没有 service 证据时，`datadog_queries` 不得自行补 service 条件。

## Error semantics

- `ok: true` + empty `errors`: normal success
- `ok: true` + non-empty `warnings`: success with degraded analysis
- `ok: false` + non-empty `errors`: pipeline failure, raw data may still be present
