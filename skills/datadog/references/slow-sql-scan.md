# Slow SQL Scan

`scan-slow-sql` 查询指定时间范围内的生产环境慢 SQL，并返回结构化结果。命令只读 Datadog Query Metrics 和 Query Samples，不执行 SQL、Explain Plan 或数据库变更。

## 默认口径

- Scope：`database_instance:prod*`
- Database type：MySQL 与 PostgreSQL
- Avg Duration：严格大于 5 秒
- Count：严格大于 100
- 排序：Avg Duration 降序
- 时间：必须显式传入 `--from`；用户未给出口径时使用 `--from 7d`

调用方已经给出窗口时，原样使用该窗口。用户未提供时间口径或要求查询最新数据时，skill 必须在命令中补充 `--from 7d`；`--to` 省略时默认为当前时间。`--from` 和 `--to` 的相对时间都以同一个命令执行时刻为基准，不相互嵌套计算。解析后的 UTC 和毫秒边界位于 `target.window`，调用方不需要自行推算实际窗口。

## 工作流

### 1. 发现候选

**Input**：数据库类型、解析后的查询窗口、scope、Avg Duration 阈值和 Top N。

**Operation**：一次 scalar 请求同时读取总执行时间和执行次数，服务端按 `total_time / count / 1e9` 降序返回 Top N Query Signature。MySQL 使用 `mysql.queries.time/count`，PostgreSQL 使用 `postgresql.queries.time/count`。

**Output**：Avg Duration 高于阈值的候选 Signature，以及 Top N 边界覆盖信息。

只有返回少于 N 条，或末位有效 Avg Duration 已小于等于阈值，才算覆盖完整。否则命令对该数据库类型失败关闭，避免把截断结果误当全量。

### 2. 精确筛选

**Input**：候选 Signature。

**Operation**：用 `query_signature IN (...)` 批量读取精确 Total Duration 和 Count，在本地重新计算 Avg Duration，并应用两个严格阈值。每批最多 100 个 Signature。

**Output**：最终符合 `Avg Duration > threshold AND Count > threshold` 的 SQL 指标。

这一步不逐条调用指标 API，也不使用 Query Samples 估算 Count。

### 3. 补全上下文

**Input**：最终 Signature。

**Operation**：批量按 Signature、Instance、Cluster、Database 和 Table 分组读取 query count metric。该请求只提取上下文集合，不再次累计 Count。

**Output**：`database_instances`、`db_cluster_identifiers`、`databases` 和 `tables`。

`_other` 是 Datadog 聚合占位值，输出时会丢弃。

### 4. 读取 SQL 文本

**Input**：每条最终 Signature、数据库类型、scope 和相同时间窗口。

**Operation**：每条 Signature 调用一次 DBM Query Samples endpoint，限制 `limit=1` 并取最新记录。

**Output**：Normalized SQL；sample 中的 Table metadata 会合并到 metrics 上下文，避免丢失任一来源识别到的 Table。

Sample 缺失或单条读取失败时仍保留指标记录，通过 `sample_status` 标记；不会追加 Explain Plan 请求。Query Sample 首次返回认证/权限错误后，不再继续请求同一 endpoint，其余记录标记为 `error`。

## API 调用模型

单个数据库类型的固定开销为：

1. 1 次候选发现；
2. 每 100 个候选 1 次精确指标请求；
3. 每 100 个最终命中 1 次上下文请求；
4. 每条最终命中至多 1 次 Query Sample 请求；首次认证/权限错误后停止后续 Sample 请求。

在通常候选少于 100 的情况下，总逻辑请求数上限是 `3 + 最终命中数`。没有候选时只发 1 次请求。MySQL 和 PostgreSQL 独立执行：任一失败时，成功一侧仍会输出，顶层状态为 `partial_success`。

## 使用方式

```bash
SKILL_DIR="<本 SKILL.md 所在目录>"
uv run "$SKILL_DIR/scripts/datadog.py" scan-slow-sql \
  --from 2026-07-24T00:00:00+08:00 \
  --to 2026-07-31T00:00:00+08:00 \
  --database-type all \
  --scope "database_instance:prod*" \
  --min-avg-seconds 5 \
  --min-count 100 \
  --top 400 \
  --format json
```

## 输出字段

| 字段 | 说明 |
|---|---|
| `result.status` | `success`、`partial_success` 或 `failed` |
| `target.window` | UTC 格式和毫秒格式的实际查询窗口 |
| `meta.criteria` | scope、严格阈值和 Top N |
| `result.sources` | 各数据库类型的状态、覆盖边界、候选数、命中数和请求数 |
| `result.sources.*.rows_returned` | 候选发现实际返回的行数 |
| `result.sources.*.null_avg_count` | 因 Avg 为空或 Signature 无效而丢弃的行数 |
| `result.sources.*.minimum_returned_avg_seconds` | Top N 中最低有效 Avg，用于证明阈值覆盖 |
| `result.sources.*.coverage_complete` | 是否已证明阈值以上候选覆盖完整 |
| `result.sources.*.avg_candidates` | Avg Duration 严格高于阈值的候选数 |
| `result.sources.*.qualified_count` | 再应用 Count 阈值后的最终命中数 |
| `result.sources.*.sample_errors` | 实际发出的 Query Sample 逻辑请求中发生错误的数量；无最终命中时可能省略 |
| `result.sources.*.sample_skipped` | 首次认证/权限错误后跳过的 Query Sample 数量；无最终命中时可能省略 |
| `result.sources.*.logical_request_count` | 该数据库类型发起的逻辑 API 操作数；429 等底层重试不重复计数 |
| `result.queries[].query_signature` | Datadog Query Signature |
| `result.queries[].avg_duration_seconds` | 查询窗口内总时间除以 Count |
| `result.queries[].count` | 查询窗口内执行次数 |
| `result.queries[].total_duration_seconds` | 查询窗口内总执行时间 |
| `result.queries[].database_instances` | 完整 Instance identifier 集合 |
| `result.queries[].db_cluster_identifiers` | Datadog `dbclusteridentifier` 集合，不猜测映射 |
| `result.queries[].databases` / `result.queries[].tables` | 查询涉及的 Database 与 Table 集合 |
| `result.queries[].normalized_sql` | 最新 Query Sample 中的归一化 SQL，可能为空 |
| `result.queries[].sample_status` | `found`、`not_found` 或 `error` |
| `result.queries[].datadog_query_url` | 实际查询窗口对应的 Datadog Queries 页面链接 |
| `result.query_count` | 两类数据库最终命中总数 |

`result.queries` 始终按 Avg Duration 降序排列。数据库来源失败或任一 Query Sample 请求错误时，`result.status=partial_success` 且退出码为 0；Sample `not_found` 不视为错误。调用方应同时检查 `result.status` 和 `result.sources`。全部失败时，单一失败类型沿用通用退出码（认证/权限为 3、API/查询为 4、超时为 5）；多个来源失败类型不同时返回 4。

## 准确性检查

- Count 与 Total Duration 必须只按 Query Signature 聚合，不能按 Table 展开后重复求和。
- 平均秒数必须使用 `total_time_ns / count / 1e9`。
- `count = 0`、空 Signature、非有限指标和 `_other` 均不得成为候选。
- Query Sample 只负责 SQL 文本和 metadata，不代表窗口执行总量。
- 定时查询应保存具体窗口，不使用会随执行时间变化的相对时间描述查询结果。
