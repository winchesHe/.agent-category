# Investigation Workflows

本文件定义需要两个以上 CLI 调用的只读调查路径。所有后续调用必须保留首个调用的窗口、环境、服务和业务过滤。命令已经回答问题时立即停止。

## Request ID 到 Trace

1. 使用 `search-logs --query "env:ns-production @id:<uuid>" --from <window>` 获取请求日志。
2. 只从结果的结构化字段读取完整 `trace_id`。无字段标签的 breadcrumb 数字不能作为 trace ID。
3. 用户要 span 链路时，对该原值调用 `get-trace`。窗口必须覆盖原事件。
4. 用户要同一 trace 的关联日志时，调用 `search-trace-logs <trace_id> --from <same-window>`。
5. 单请求链路已经回答问题后停止。不要自动扫描同服务的其他请求。

如果日志没有返回完整 `trace_id`，报告该缺口。禁止补零、转换进制或猜测高位。

## 已知 Trace ID

| 用户目标 | 首个调用 | 条件化后续 |
|---|---|---|
| 展开 span tree | `get-trace` | `meta.page.next_cursor` 存在时，只按 cursor 继续同一查询 |
| 查关联日志 | `search-trace-logs` | 只按 cursor 继续同一范围 |
| 同时需要 span 和日志 | 先调用与问题主语匹配的命令 | 只有首个结果不足时再调用另一个 |

Trace ID 必须按原值传递。Trace 查询窗口必须覆盖已知事件时间。`get-trace` 的 tree 只在当前 page 内计算；合并多页前必须保留 page 边界。

## 错误调查

### 错误样本

使用 `search-logs`。保留 `service`、`env`、状态、业务字段和窗口。样本足以回答后停止。

### 错误总量或分组

使用 `aggregate-logs --compute count`。按问题选择 `service`、`@http.status_code` 或 `@error.kind` 分组。不要用 `search-logs` 返回条数替代 count。

用户明确要求 5xx 时，query 使用 `@http.status_code:>=500` 或等价 500–599 范围。不能用更宽的 `status:error` 替代。

### 快速错误概览

使用 `summarize-errors`。`total`、`by_service` 和 `by_error_kind` 来自服务端聚合。`top_messages` 来自有限 sample。报告 `message_sample.sample_size`，不要把消息样本排序写成全量分布。

### 相邻窗口比较

使用 `compare-log-counts`。CLI 固定当前窗口和紧邻的等长前一窗口。必须报告两个实际窗口。前一窗口为零时只报告 absolute change 和 `baseline_zero=true`，不构造百分比。

### 消息模式

使用 `group-log-patterns`。模式来自有限日志 sample。报告 `sample_size` 和 `requested_sample_size`。不要声称模式覆盖完整窗口的全部日志。

## Log Context

1. 固定用户提供的事件 timestamp。
2. 使用最窄的 query 或 service。两者已知时同时保留。
3. 调用 `get-log-context`，默认读取前后各 5 分钟。
4. 分开解释 `before` 和 `after`。每侧达到 limit 时，说明该侧可能截断。

不要为了获得更多内容去掉 query 或 service。

## 慢请求和延迟

### 慢 span 样本

1. 使用 `search-spans --slow-ms <threshold>`，保留 service、env 和窗口。
2. 只对返回的完整 `trace_id` 调用 `get-trace`。
3. 报告最慢样本的 duration 和 trace ID。

样本不能代表总体 p95/p99。

### p95/p99 或总体延迟

使用 `aggregate-logs` 的 percentile compute，或使用用户指定的 Datadog metric 调用 `query-metrics`。不要用最慢样本或 `avg` 代替百分位。

### Error rate

Error count 和总请求 count 必须来自口径匹配的序列或聚合。没有分母时，只能报告 error count。`.as_count()` 不能单独证明 error rate。

## 服务发现

| 目标 | Command | 数据来源 |
|---|---|---|
| 哪些 service 有日志活动 | `list-log-services` | Logs 聚合 |
| 环境中有哪些 APM service | `list-services` | APM service inventory |
| 一个 APM service 的上下游 | `get-dependencies` | APM service map |

`list-log-services` 和 `list-services` 不能互换。前者按窗口聚合 Logs 活动；后者读取环境级 APM service 清单。来源不明确时先澄清。

## Dashboard URL

1. 从 `/dashboard/<id>` 取得短 ID，调用 `get-dashboard <id>`。
2. 保留 URL 中的 `from_ts`、`to_ts` 和 `tpl_var_*`。毫秒 timestamp 传给数据命令前转换为秒或等价 RFC3339。
3. 先读取 Dashboard 定义。只选择与用户问题相关的 widget。
4. 保留该 widget 的 template variables，并按 `data_source` 选择一次后续调用：
   - `logs`：`search-logs` 或 `aggregate-logs`
   - `spans`：`search-spans`
   - `metrics` / `apm_metrics`：`query-metrics`
5. 回答目标 widget 后停止。禁止自动扫描其他 widget。

用户只问 URL 固定窗口时，不自动追加前一窗口。只有用户明确要求同期/环比，或 widget 自带对照序列时才比较。

## Dashboard 发现

1. 不知道 Dashboard ID 时使用 `list-dashboards`，按 start/count 显式分页。
2. 明确目标后只调用一次 `get-dashboard`。
3. 用户问 Dashboard List 时先调用 `list-dashboard-lists`。
4. 已知 list ID 后，根据问题调用 `get-dashboard-list` 或 `list-dashboard-list-items`。

所有 Dashboard 和 Dashboard List 命令只读。禁止从发现流程转为创建、更新或删除。

Dashboard List API 没有分页参数。`completion=unknown` 或 warning 表示结果可能超过 CLI 的 1000 项输出上限，不能声称成员完整。

## 历史日志

1. 保留全部已知条件，先查询适用的标准层。
2. 当前证据已确认标准层为空或超出保留期时，执行一次相同范围的精确 Flex 查询。
3. Flex 仍空时停止 API 查询，转 Datadog UI Archive Search handoff。

空结果不能证明日志不存在。禁止去掉 service、env、业务条件或改查无关 APM 数据。

## Grooming Report 发送

先根据业务标识缩窄 message 服务日志。SMS 与 email 使用不同事件字段。不要把下游 provider 状态、内部发送状态和用户最终送达状态合并成一个结论。

## 通用停止条件

- 当前证据已经回答用户问题。
- 下一步需要猜测 ID、服务、窗口或业务过滤。
- 权限错误阻止当前路径。
- 同语义的一次降载后仍 timeout。
- 精确 Flex 为空，需要 UI handoff。
- 后续调用只会扩大范围，不会验证当前假设。
