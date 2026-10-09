# DQL 搜索语法参考

## 基础语法

| 语法 | 含义 | 示例 |
|------|------|------|
| `key:value` | 精确匹配 | `service:moego-api-v3` |
| `@attr:value` | 自定义属性匹配 | `@id:550e8400-e29b-41d4-a716-446655440000` |
| `@attr:>N` | 数值比较（`>`/`>=`/`<`/`<=`） | `@http.status_code:>=500` |
| `"exact phrase"` | 精确短语 | `"connection refused"` |
| `key:val*` | 通配符 | `service:moego-svc-*` |
| `-key:value` | 否定 | `-status:info` |
| `AND` / `OR` / `NOT` | 布尔运算符（隐式为 AND） | `service:moego-api-v3 AND status:error` |
| `(A OR B) AND C` | 分组 | `(status:error OR status:critical) service:moego-api-v3` |

## 日志常用 Facet

| Facet | 说明 |
|-------|------|
| `status` | 日志级别：`info` / `warn` / `error` / `critical` |
| `service` | 服务名 |
| `host` | 主机名 |
| `source` | 日志来源 |
| `@id` | x-request-id（MoeGo 自定义索引，见下方说明） |
| `@http.status_code` | HTTP 状态码 |
| `@http.method` | HTTP 方法 |
| `@http.url_details.path` | 请求路径 |
| `trace_id` | 关联的 Trace ID |

## APM / Trace 查询语法

| Facet | 说明 |
|-------|------|
| `service:<name>` | 服务名 |
| `resource_name:<path>` | 资源名（通常是 endpoint 路径） |
| `operation_name:<op>` | 操作名 |
| `status:error` | 错误 span |
| `@duration:>5000000000` | 持续时间（纳秒！5s = 5000000000） |
| `env:<env>` | 环境标签 |

## MoeGo 服务名映射

| 业务域 | Datadog service 名 | 常见查询场景 |
|--------|-------------------|-------------|
| 主 API | `moego-api-v3` | HTTP 接口错误、业务逻辑异常 |
| 支付 | `moego-svc-payment` | 扣款失败、退款异常 |
| 消息 | `moego-svc-message` | 通知未送达、短信发送失败 |
| 预约 | `moego-svc-appointment` | 预约冲突、日历同步问题 |
| 账号 | `moego-svc-account` | 登录失败、权限问题 |

服务名通配：`service:moego-svc-*` 匹配所有微服务。

## @id 与 x-request-id

MoeGo 后端在 HTTP 请求头中传递 `x-request-id`，Datadog 将其索引为 `@id`。

- 搜索时用 `@id:<uuid>`，不要用 `x-request-id`
- CS 工单和 QA 报告中通常以 `x-request-id` 形式出现
- 格式：标准 UUID（`550e8400-e29b-41d4-a716-446655440000`）

## 时间范围格式

`--from` / `--to` 参数支持：

| 格式 | 示例 |
|------|------|
| 相对简写 | `5s`, `30m`, `1h`, `4h`, `1d`, `7d`, `30d` |
| 相对全称 | `5min`, `2hours`, `3days` |
| RFC3339 | `2024-01-01T00:00:00Z` |
| Unix 毫秒时间戳 | `1704067200000` |
| 组合范围 | `--from=7d --to=1d`（7 天前到 1 天前） |

默认值：`--from=1h --to=now`。归档查询用 `--from=30d --storage=flex`。

## 环境标识

| 环境 | env 标签 | 用途 |
|------|---------|------|
| 生产 | `ns-production` | 线上真实流量 |
| 测试 | `ns-testing` | 测试环境 |

命令中通过 `--env=ns-production` 或查询中 `env:ns-production` 指定。

## 常用查询模板

```bash
# 按 x-request-id 查日志
python3 scripts/datadog.py search-logs --query "@id:<uuid>" --from 4h

# 某服务最近 1 小时的错误日志
python3 scripts/datadog.py search-logs --query "service:moego-api-v3 status:error" --from 1h

# 统计各服务错误数量
python3 scripts/datadog.py aggregate-logs --query "status:error" --from 1h --compute count --group-by service

# 查历史归档日志（超过 15 天）
python3 scripts/datadog.py search-logs --query "@id:<uuid>" --from 30d --storage flex

# 查找某服务的错误 trace
python3 scripts/datadog.py search-spans --query "service:moego-svc-payment status:error" --from 1h

# 查看服务依赖拓扑
python3 scripts/datadog.py get-dependencies moego-api-v3

# HTTP 5xx 错误
python3 scripts/datadog.py search-logs --query "service:moego-api-v3 @http.status_code:>=500" --from 1h

# 慢请求（>5s）
python3 scripts/datadog.py search-spans --query "service:moego-api-v3 @duration:>5000000000" --from 1h
```

## URL 构造

生成 Datadog UI 链接时使用以下参数：

- **Base URL**: `https://us5.datadoghq.com/logs`
- **Required Params**:
  - `storage=flex_tier`（Flex 日志）
  - `viz=stream`（Stream 视图）
  - `messageDisplay=inline`（紧凑行）
  - `refresh_mode=sliding` & `live=true`（Live tail）
  - `cols=host,service`（自定义列）
