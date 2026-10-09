---
name: datadog
description: >-
  通过唯一入口 scripts/datadog.py 只读查询 Datadog 日志、聚合、Trace、Span、
  APM 服务与依赖、Dashboard / Dashboard List、Metrics、Actions Datastore、慢 SQL 和 Monitor；
  支持关联日志、上下文、错误摘要、时段对比和日志模式分析。
  当用户提到 Datadog、DD、APM、x-request-id、trace、500、延迟、p99、
  error rate、Dashboard、Monitor、Actions Datastore、datastore、Intercom feedback、
  慢 SQL 或服务依赖时使用。
---

# Datadog Skill

用只读 Datadog API 拉取 MoeGo 后端日志、链路追踪、Span、APM 服务拓扑、Dashboard、Metrics、慢 SQL 和 Monitor 证据。

## 前置条件

| 项 | 说明 |
|---|---|
| Python | >= 3.9 |
| 依赖 | `pip install requests` |
| 配置 | 复制 `<SKILL_DIR>/.env.example` 为 `<SKILL_DIR>/.env`（`<SKILL_DIR>` = 本 SKILL.md 所在目录），填入 `DD_API_KEY` / `DD_APP_KEY` |

## 脚本位置

**唯一入口始终相对于本 SKILL.md 所在目录：**

```
<本 SKILL.md 所在目录>/scripts/datadog.py
```

> 解析规则：你是从某个绝对路径 `cat` / 读取到这份 SKILL.md 的，**那个目录就是 skill 根**，脚本必然在它的 `scripts/` 子目录下。**不要用 CWD 相对路径，始终用 SKILL_DIR 绝对路径。**

1. 已知本 SKILL.md 的绝对路径时（最常见，直接用读取它的路径）：
   ```bash
   SKILL_DIR="<本 SKILL.md 所在目录>"
   python3 "$SKILL_DIR/scripts/datadog.py" <subcommand> [flags]
   ```
2. 不确定 SKILL.md 在哪时，按文件名定位 skill 根：
   ```bash
   SKILL_DIR="$(dirname "$(find . -type f -path '*/datadog/SKILL.md' 2>/dev/null | head -n1)")"
   python3 "$SKILL_DIR/scripts/datadog.py" <subcommand> [flags]
   ```
3. 仍找不到则直接搜脚本入口，取其绝对路径调用：
   ```bash
   find . -type f -path '*/datadog/scripts/datadog.py' 2>/dev/null
   ```

`.env` 必须放在 `<SKILL_DIR>/`（与 `SKILL.md` 同目录），由脚本自动加载。

后续示例为简洁使用 `python3 scripts/datadog.py ...`；实际调用必须替换为 `$SKILL_DIR/scripts/datadog.py` 绝对路径。

不要直接调用 `scripts/dd/commands/*.py` 或 `scripts/dd_v3/commands/*.py`。
## 子命令速查表

| 子命令 | 作用 | 必填 flag |
|---|---|---|
| `search-logs` | 搜索 Datadog 日志事件，支持标准层/Flex/归档层 | `--query` `--from` |
| `aggregate-logs` | 服务端日志聚合统计，适合 count、分组、p95 等 | `--query` `--from` |
| `search-spans` | 搜索 APM span，定位错误/慢请求 trace | `--query` `--from` |
| `get-trace` | 按 trace_id 展开 span 树（基于 v2 spans search） | `trace_id` |
| `get-dependencies` | 查询指定服务的上游/下游依赖 | `service` |
| `list-services` | 列出时间窗口内活跃 APM 服务 | 无 |
| `get-dashboard` | 获取 Dashboard 定义（含所有 widget 查询） | `dashboard_id` |
| `query-metrics` | 查询 Metrics 时序数据 | `--query` `--from` |
| `search-trace-logs` | 按 trace_id 查关联日志 | `trace_id` `--from` |
| `get-log-context` | 查询目标时间点前后的日志 | `--timestamp`，以及 `--query` / `--service` 至少一个 |
| `summarize-errors` | 汇总错误总量、服务、错误类型和消息样本 | `--from` |
| `compare-log-counts` | 比较相邻等长窗口的日志数量 | `--query` |
| `group-log-patterns` | 对有限日志样本做消息模式聚类 | `--query` `--from` |
| `list-log-services` | 按日志活动发现服务 | `--from` |
| `list-dashboards` | 分页列出 Dashboard 摘要 | 无 |
| `list-dashboard-lists` | 列出 Dashboard List | 无 |
| `get-dashboard-list` | 读取单个 Dashboard List | `list_id` |
| `list-dashboard-list-items` | 列出 Dashboard List 的成员 | `list_id` |
| `scan-slow-sql` | 扫描 DBM 慢 SQL | `--from` |
| `list-monitors` | 分页列出 Monitor | 无 |
| `search-monitors` | 搜索 Monitor | `--query` |
| `get-monitor` | 读取单个 Monitor | `monitor_id` |
| `list-datastores` | 列出当前组织的 Actions Datastore 摘要，用于发现 ID | 无 |
| `list-datastore-items` | 分页读取 Actions Datastore，可做服务端过滤和字段投影 | `datastore_id` |

## 通用 flag

| Flag | 说明 |
|---|---|
| `--format` | 原有 8 个命令支持 `json|human|summary`；新增 16 个只读命令支持 `json|summary`。默认均为 `json` |
| `--from` / `--to` | 时间范围。支持 `15m`、`1h`、`now-1h`、RFC3339、Unix timestamp |
| `--env` | APM 环境标签，默认 `DD_DEFAULT_ENV` 或 `ns-production` |
| `--storage indexes|online-archives|flex` | 日志存储层；`online` 是 `indexes` 兼容别名 |

`list-datastore-items` 使用独立分页参数：`--page-size 1..100`、`--offset`、
`--all-pages`、`--max-items 1..10000`、`--sort <field>`、
`--consistency-passes 1..3`；`--filter` 与 `--item-key` 互斥，`--field` 可重复用于
最小字段投影。完整分页必须二选一：指定稳定且唯一的 `--sort` 字段；或在服务端没有
可用排序字段时省略 `--sort` 并设置至少 2 次一致性扫描。

## 场景决策树

```text
用户提供 x-request-id / request id / @id？
  -> search-logs --query "@id:<uuid>" --from 4h --limit 20
  -> 从 logs[].trace_id 提取 trace_id
  -> get-trace <trace_id>

用户报告 500 / API 失败 / 后端报错？
  -> search-logs --query "service:<svc> status:error" --from 1h --limit 20
  -> aggregate-logs --query "service:<svc> status:error" --from 1h --compute count --group-by @http.status_code

用户报告接口慢 / latency spike / p99 飙升？
  -> search-spans --query "service:<svc>" --from 1h --slow-ms 3000
  -> get-trace <最慢 span 的 trace_id>

需要判断影响面 / 上游下游 / 依赖拓扑？
  -> get-dependencies <svc> --env ns-production --from 1h

不确定服务名？
  -> list-services --env ns-production --from 1h --filter "moego-*"
  -> 必要时读取 references/datadog-service-map.md

时间较早或标准层查不到？
  -> search-logs --query "<DQL>" --from 30d --storage flex
收到 Datadog dashboard 报告消息？
  -> 从消息 URL 提取 dashboard ID（路径段 /dashboard/<id>）
  -> 提取时间范围：from_ts / to_ts（毫秒 Unix timestamp）
  -> 提取 template variables：tpl_var_* 参数
  -> get-dashboard <id> 获取 widget 定义
  -> 扫描 widget 查询，识别异常指标（error rate 飙升、latency spike、5xx 占比上升）
  -> 对异常 widget 的底层查询用 search-logs / search-spans / query-metrics 获取具体数据
  -> 数据提取完成，产出：service name、error type、trace_id、时间窗口、影响规模

需要具体 metric 值或趋势数据？
  -> query-metrics --query "avg:trace.servlet.request.duration{service:<svc>}" --from 1h
  -> 分析时序点，判断是否有 spike 或持续劣化

已有 trace_id，需要关联日志？
  -> search-trace-logs <trace_id> --from <覆盖事件的窗口>

需要查看某条日志前后发生了什么？
  -> get-log-context --timestamp <事件时间> --service <svc>

需要快速看错误结构、相邻窗口变化或常见消息模式？
  -> summarize-errors --from 1h [--service <svc>]
  -> compare-log-counts --query "service:<svc> status:error" --period 1h
  -> group-log-patterns --query "service:<svc> status:error" --from 1h

不知道 Dashboard ID / Dashboard List 内容？
  -> list-dashboards --count 25
  -> list-dashboard-lists
  -> get-dashboard-list <list_id> 或 list-dashboard-list-items <list_id>

需要查询慢 SQL？
  -> scan-slow-sql --from 7d
  -> 详细口径读取 references/slow-sql-scan.md

需要查告警配置或状态？
  -> list-monitors / search-monitors / get-monitor
  -> 仅只读，不提供 mute、unmute、创建、更新或删除能力

需要读取 Actions Datastore / Intercom feedback datastore？
  -> 不知道 datastore ID：先用 list-datastores 发现当前组织的表
  -> 按精确 name 选择结果中的 id；没有命中或有重名时停止，不猜 ID
  -> 已知并确认 datastore ID：list-datastore-items <id> --page-size 20
  -> 先用 --filter 验证查询，再选择稳定唯一排序，或 --all-pages --consistency-passes 2
  -> 涉及客户数据时必须用重复 --field 做最小投影
```

## 领域知识

### `x-request-id` 与 `@id`

MoeGo HTTP 请求头里的 `x-request-id` 在 Datadog 中索引为 `@id`。搜索时必须写：

```bash
python3 scripts/datadog.py search-logs --query "@id:<uuid>" --from 4h
```

不要写 `x-request-id:<uuid>` 或 `x_request_id:<uuid>`。

### Trace 采样

不是每个请求都有完整 trace：

- 错误和慢请求通常更容易保留。
- 正常请求可能被采样丢弃。
- `search-spans` / `get-trace` 返回空不等于请求没有发生，应回到 logs 查证。

### 环境标签

| 环境 | env 标签 |
|---|---|
| 生产 | `ns-production` |
| 测试 | `ns-testing` |

### Dashboard URL 解析

Slack 中 Datadog 报告消息包含 dashboard URL：
- 格式：`https://us5.datadoghq.com/dashboard/<id>?from_ts=<ms>&to_ts=<ms>&tpl_var_*=...`
- `<id>` 是 dashboard 短 ID（如 `ian-th8-5fh`），直接传给 `get-dashboard`
- `from_ts` / `to_ts` 是毫秒级 Unix timestamp，转换为 `--from` / `--to` 时除以 1000
- `tpl_var_resource_realm[0]=timeslot` 等参数是 dashboard 的 template variable 过滤维度
- Dashboard 包含多个 widget，每个 widget 有独立查询（data_source 可以是 spans、logs、apm_metrics、events）

### Dashboard 报告分析

收到 Datadog dashboard 报告消息时，目标是判断指定时间范围内是否存在异常，并尽可能定位异常位置。

**异常定义**（以下任一即算异常）：
- HTTP 4xx / 5xx 响应
- APM span `status:error`
- 明确的 error log
- 异常 trace（超时、依赖调用失败）
- error rate 或 latency 相比前一周期显著上升

**查询策略**：
- 首轮查询不限 service——先用 `aggregate-logs` 或 dashboard widget 的全局查询扫描，不要先入为主假设哪个服务有问题
- Dashboard 的 template variables（`tpl_var_*`）指示了报告关注的维度（如 `resource_realm=timeslot`），查询时带上这些过滤条件
- Widget 的 `data_source` 决定用哪个子命令：`spans` -> `search-spans`，`logs` -> `search-logs/aggregate-logs`，`apm_metrics` -> `query-metrics`

**命中异常后提取**：
- timestamp、service、endpoint / resource / operation
- trace_id、span_id、request_id
- http.status_code、error.message
- stack trace 摘要（如有）
- 下游依赖线索（外部 API、DB、消息队列）
- 影响规模（count / 采样数——没有总量时注明"仅有样本证据"）

命中异常后，提取的证据（service、error、trace_id、时间窗口）是后续深入调查的输入，不是最终结论。

只有查询充分且确认无异常时，才可以产出"正常"结论。查询不足时说明已查了什么、未覆盖什么、为什么覆盖不足，不硬说"正常"。

### MoeGo 服务名映射

完整的 Datadog service -> GitHub repo -> 本地目录映射见 `references/datadog-service-map.md`（82 条，含 direct/monorepo/alias 三类）。`references/dql-syntax.md` 只列了 5 个高频示例。

服务名不确定时，先查 `references/datadog-service-map.md` 定位服务对应的代码仓库。

### Actions Datastore

`list-datastores` 调用只读 `GET /api/v2/actions-datastores`，用于发现当前组织可见的
datastore。输出只包含 `id / name / description / primary_column_name /
primary_key_generation_strategy / created_at / modified_at`，不传播 `org_id` 或 creator
标识。该 API 不提供分页参数；CLI 最多输出 1000 张表，超过时返回
`completion=unknown` 和 `datastores_truncated` warning。

`list-datastore-items` 调用只读
`GET /api/v2/actions-datastores/<id>/items`。Datadog 每页最多 100 条；返回
`totalFilteredCount / hasMore`。`--all-pages` 只有在调用方明确需要完整结果，并提供
稳定唯一排序字段，或执行至少 2 次无排序全量扫描时使用；达到 `--max-items` 后仍有下一页会返回
`completion=truncated`。只有 `hasMore=false` 且返回条数与
`totalFilteredCount - offset` 一致时才标记 `completion=complete`；查询过程中数据
发生变化导致总数不闭合时失败，不能把漂移后的分页拼接伪装成全量。

无排序全量模式在同一个 CLI 进程和 API client 内重复完整扫描，只有各次扫描的
`totalFilteredCount`、字段 schema、item ID 集合和每条完整内容都一致时才成功，并在
顶层 `verification` 标记 `mode=converged-read`、实际 passes 与
`matched=true`。任一内容变化都返回 `pagination_changed`，调用方必须整次重试。

过滤语法沿用 Datadog search syntax。数值时间范围使用比较表达式，例如：

```text
conversation_created_at:>=1786896000000 AND conversation_created_at:<1787500800000
```

MoeGo Intercom feedback datastore ID 为
`a56cf9ac-2d2d-4e72-b19a-f9f0107868aa`。其数据含客户隐私字段；自动采集只能投影
业务所需字段，禁止请求或传播 `email / conversation_id / quote`。

## NEVER 规则

- 不要用 `search-logs` 数数量；它最多返回 `--limit` 条。计数必须用 `aggregate-logs --compute count`。
- 不要省略 `--from`；排查必须有明确时间窗口。
- 不要首次查询就设置超大 `--limit`；先用 20 验证条件，再逐步放大。
- 不要把 APM duration 当毫秒写进查询；Datadog APM duration 是纳秒，5 秒是 `5000000000`。
- 不要对 401/403 盲目重试；这是认证或权限问题，检查 `DD_API_KEY` / `DD_APP_KEY`。
- 不要直接输出 `.env` 或 token；只确认变量是否存在。
- `get-trace` 的 `trace_id` 必须是 **32 位十六进制**（即 `attributes.trace_id`），而不是看起来像数字的 `span_id`；底层走 `POST /api/v2/spans/events/search`，所以传入的 `--from`/`--to` 必须覆盖该 trace 的发生时间，否则结果为空。
- 不要把 Datadog APM UI 面包屑 `<resource> > <数字>` 里的**十进制数字**当 `trace_id` 直接传给 `get-trace`。该数字是 trace_id 低 64 位的十进制表示（如 `4810075767859515357` = hex `42c0d26d0dfb0fdd`），必须左侧零填充或加上高 64 位补齐到 32 位 hex（如 `69eca0540000000042c0d26d0dfb0fdd`）才能命中。要拿真正的 32-hex trace_id：从 UI 的 `View Trace in APM` 链接 URL（`?traceID=…`）或右侧 Span Attributes 面板的 `trace_id` 字段读取。
- 不要对整个 dashboard 的每个 widget 都执行底层查询——先扫描 widget 定义，只对异常指标或用户关注的维度执行查询；一个 dashboard 可能有 10+ widget，全部查询会超时。
- 不要用 `summarize-errors` 的 `top_messages` 或 `group-log-patterns` 推断全量分布；它们来自有限样本，必须同时报告 sample size。
- 不要把 `list-log-services` 当成 APM 服务清单；它按日志活动聚合，APM 服务发现仍用 `list-services`。
- 不要尝试 mute / unmute Monitor，也不要创建、更新或删除 Monitor；本 skill 只暴露 `list-monitors`、`search-monitors`、`get-monitor`。
- 不知道 datastore ID 时不要从文档、历史输出或相似名称猜测；必须先调用 `list-datastores`，再按精确 name 选择 ID。没有命中或有重名时停止。
- 不要对含客户数据的 Datastore 省略 `--field`；先明确消费合同并只投影必要字段。
- 不要在既没有稳定唯一 `--sort`、又没有至少 2 次 `--consistency-passes` 的情况下使用 `--all-pages`；跨页顺序不稳定会产生漏行或重复行。
- 不要把 `list-datastore-items` 的 `partial` 或 `truncated` 结果当成全量；完整采集必须检查 `meta.pagination.completion=complete`，无排序模式还必须检查 `verification.mode=converged-read` 且 `matched=true`。
- 读取 Intercom feedback datastore 时不要投影、输出或落盘 `email`、`conversation_id`、`quote`。

## 错误处理

| 退出码 | 原因 | 处理 |
|---|---|---|
| 0 | 成功 | 解析 stdout JSON |
| 2 | 缺少必填配置或配置格式错误 | 检查 `<SKILL_DIR>/.env` 或进程环境变量 |
| 3 | 401/403 认证或权限错误 | 检查 key 是否过期、scope 是否覆盖目标 API |
| 4 | Datadog API/查询语法/业务错误 | 看 stderr；`pagination_changed` 表示本轮扫描不一致，应整次重试，其它错误修正 DQL、endpoint 或参数 |
| 5 | 请求超时 | 缩小时间范围、降低 limit，Flex 查询天然更慢 |

## 示例

```bash
# 按 x-request-id 查日志
python3 scripts/datadog.py search-logs --query "@id:26c6d5d6-79cb-4ff8-80c8-be840bfaff99" --from 4h

# 查某服务错误日志
python3 scripts/datadog.py search-logs --query "service:moego-api-v3 status:error" --from 1h --limit 20

# 查历史/Flex 日志
python3 scripts/datadog.py search-logs --query "@id:<uuid>" --from 30d --storage flex --limit 20

# 统计状态码错误数
python3 scripts/datadog.py aggregate-logs --query "service:moego-api-v3 status:error" --from 1h --compute count --group-by @http.status_code

# 统计 p95 duration
python3 scripts/datadog.py aggregate-logs --query "service:moego-api-v3" --from 1h --compute "percentile(@duration, 95)" --group-by service

# 搜索慢 span
python3 scripts/datadog.py search-spans --query "service:moego-svc-payment" --from 1h --slow-ms 3000

# 展开 trace
python3 scripts/datadog.py get-trace <trace_id> --format human

# 查服务依赖
python3 scripts/datadog.py get-dependencies moego-svc-payment --env ns-production --from 1h

# 列出活跃服务
python3 scripts/datadog.py list-services --env ns-production --from 1h --filter "moego-svc-*"

# 获取 dashboard 定义
python3 scripts/datadog.py get-dashboard ian-th8-5fh

# 查询 metrics 时序数据
python3 scripts/datadog.py query-metrics --query "avg:trace.servlet.request.duration{service:moego-api-v3}" --from 1h

# 按 trace_id 查关联日志
python3 scripts/datadog.py search-trace-logs <trace_id> --from 1h

# 查看目标时间点前后各 5 分钟的服务日志
python3 scripts/datadog.py get-log-context --timestamp 2026-08-21T10:00:00+08:00 --service moego-api-v3

# 汇总一小时内的错误
python3 scripts/datadog.py summarize-errors --from 1h --service moego-api-v3

# 比较当前一小时与前一小时的错误数
python3 scripts/datadog.py compare-log-counts --query "service:moego-api-v3 status:error" --period 1h

# 对错误日志样本做消息模式聚类
python3 scripts/datadog.py group-log-patterns --query "service:moego-api-v3 status:error" --from 1h --top 20

# 按日志活动列出服务
python3 scripts/datadog.py list-log-services --from 1h --limit 100

# 列出 Dashboard
python3 scripts/datadog.py list-dashboards --count 25 --start 0

# 列出 Dashboard List
python3 scripts/datadog.py list-dashboard-lists

# 读取 Dashboard List 定义和成员
python3 scripts/datadog.py get-dashboard-list 12345
python3 scripts/datadog.py list-dashboard-list-items 12345

# 扫描最近七天慢 SQL
python3 scripts/datadog.py scan-slow-sql --from 7d --database-type all

# 列出、搜索和读取 Monitor（均只读）
python3 scripts/datadog.py list-monitors --page-size 20
python3 scripts/datadog.py search-monitors --query "service:moego-api-v3"
python3 scripts/datadog.py get-monitor 12345678

# 先发现当前组织的 Datastore，再使用结果中的精确 ID
python3 scripts/datadog.py list-datastores

# 小样本读取 Datastore，只投影必要字段
python3 scripts/datadog.py list-datastore-items \
  a56cf9ac-2d2d-4e72-b19a-f9f0107868aa \
  --filter 'conversation_created_at:>=1786896000000 AND conversation_created_at:<1787500800000' \
  --page-size 20 --field id --field conversation_created_at --field domain

# 服务端无排序能力时，通过两次一致性扫描完成全量读取（达到 10000 条会标记 truncated）
python3 scripts/datadog.py list-datastore-items <datastore_id> \
  --filter 'domain:Grooming' --all-pages --consistency-passes 2 --max-items 10000 \
  --field id --field domain --field requirement
```

## References

| 文件 | 加载时机 |
|---|---|
| `references/dql-syntax.md` | 构造复杂 DQL、确认 facet、duration 单位、时间格式时 |
| `references/datadog-service-map.md` | 不确定 Datadog service 名、需要定位 GitHub repo 或 monorepo path 时 |
| `references/grooming-report-debugging.md` | 工单涉及 Grooming Report 短信/邮件发送、发送失败或发送证据时 |
| `references/investigation-workflows.md` | 需要两个以上命令串联调查、选择停止条件或理解 sample / pagination 边界时 |
| `references/slow-sql-scan.md` | 使用 `scan-slow-sql`、解释 DBM 数据口径或检查结果完整性时 |
| `references/archive-rehydration.md` | 标准层和 Flex 均无结果，需要判断 Archive Search / rehydration handoff 时 |
