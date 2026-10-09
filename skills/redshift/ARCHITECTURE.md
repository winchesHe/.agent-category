# Redshift Skill 架构

本 Skill 是 runtime-neutral 的 MoeGo Redshift 只读适配层。公共契约由九个命令和
schema version 1 JSON envelope 组成。业务知识、连接、SQL 校验和文件发布彼此分层。

## 分层

```text
Agent 指引与领域 reference
          ↓
CLI contract 与参数解析
          ↓
Typed application service
   ├── RedshiftConnectivity
   │     ├── WireAdapter
   │     └── DataApiAdapter
   ├── local catalog
   └── maintained recipes
```

- `scripts/rs/contract.py`：命令、参数位置、格式和 canonical usage 的唯一真源。
- `scripts/rs/cli.py`：解析请求、执行连接前校验、分发服务、输出唯一 envelope。
- `scripts/rs/query/`：参数计划、只读 SQL guard、有界执行和结果映射。
- `scripts/rs/connectivity/`：每次调用只解析一个 named connection，并封装 target、auth、
  AWS client、DB-API connection、session、pagination、cancel 和 cleanup。
- `scripts/rs/catalog/`：加载、校验、搜索和 enrichment 本地 snapshot，并提供 SHOW-first
  live metadata source。`search` 不扫描 live catalog；`schemas` 和 `relations` 不加载或修改
  snapshot。
- `scripts/rs/recipes/`：维护过的有界多阶段查询。Recipe 不是通用 query 的隐藏 fallback。
- `references/domain-routing.md`：选择业务 source。CLI 不从 SQL 或自然语言猜 database。

## 只读边界

所有用户 SQL 都经过同一个 guard，再进入 transport 专属只读路径：

1. Guard 将 LF、CRLF 和 bare CR 识别为行注释结束符；只允许一条只读 statement；拒绝已知
   session-control function；其余 SQL 保持原样。
2. Wire JSON、metadata、recipe 和 explain 使用 `readonly=True`、`autocommit=True`。
3. Wire CSV/NDJSON 使用 `readonly=True`、`autocommit=False`，因为 named cursor 不能在
   autocommit 中工作。调用结束始终尝试 close cursor、rollback 和 close connection。
4. Data API 固定一个已验证 AWS identity 和一个 Redshift session。它执行 `BEGIN READ ONLY`、
   设置 server-side timeout、验证 `transaction_read_only`、执行用户 SQL、等待明确终态，
   再以 keepalive zero rollback，最后读取已缓存 result page。

两种 transport 都必须使用正数 timeout。Cleanup error 不能覆盖原始 FETCH/writer error。
Artifact 已 durable publish 后，cleanup error 不能把已知成功改成 `output.publish_unknown`。

Data API 每个逻辑 phase 使用独立 `ClientToken`。只有 SDK 对同一 phase 和 payload 的 retry
可以复用 token。无法确认 provider 是否接受提交时返回 `query.submission_unknown`，禁止重提 SQL。
Execute、describe 和 result fetch 使用受总 deadline 约束的 `WaitTimeSeconds`。Result fetch 的
`ResourceNotFoundException` 在 deadline 内表示 not ready；保持相同 statement ID。只有
`HasResultSet=true` 才读取结果。重复 `NextToken` 直接失败，禁止循环或重复输出。

SQL guard 只证明 statement shape，不能证明任意 UDF 或 external function 没有副作用。
Redshift role 是第二道边界，必须拒绝未批准 UDF、Lambda UDF 和外部副作用函数的 `EXECUTE`。

`doctor --connect` 只有在连接成功且 `SHOW transaction_read_only` 为 true 时才报告可用。
可连接但可写的 session 必须返回 `capability.readonly_unavailable`。

`query --database` 与 `explain --database` 只选择本次连接 database。SQL 继续使用完整
`database.schema.relation`。命令不做业务路由，也不修改进程环境。

`--connection` 只选择一个显式 profile。Runtime 不根据 SQL、错误或网络状态切换 transport、
target、database auth 或 AWS credential source。离线 `search` 和 `recipe list` 不解析 connection。
Catalog V1 固定绑定一个 `catalogConnection`。

`doctor --list-connections` 只读取 registry，不创建 Adapter，也不访问网络。公共结果只返回
profile name、deployment、transport、database、auth mode 和 default/catalog 标记。

Recipe 在第一条用户 SQL 前读取一次 live database inventory。缺少必需 database 时返回
`capability.recipe_source_unavailable`。该检查只证明 database visibility，不证明对象存在或 SQL 成功。

## Connection 配置

Skill 默认从根目录读取严格 JSON registry `connections.json`。Host 可以用
`REDSHIFT_CONNECTIONS_FILE` 显式覆盖路径。Registry 只保存 env key 引用、target、transport/auth
union、expected AWS account、database 和有界 lifecycle 设置，不保存 secret value。

Loader 使用 directory fd 打开绝对路径的每个组件，并拒绝：

- symlink traversal；
- group/other writable parent；
- 非当前用户拥有的 final file；
- 非 `0600` regular file；
- 超过文件大小上限的 registry。

Registry 是所有 live command 的必填配置。Named Wire 强制 `verify-full` 和显式 CA。
Data API 需要可选 boto3 依赖。离线 `search` 和 `recipe list` 不加载 registry。
AWS client 忽略 ambient `AWS_ENDPOINT_URL*` 和 profile endpoint override；Wire explicit host
只接受单个 hostname、IPv4 或 IPv6 literal，port 必须单独配置。

## 公共结果

所有 caught outcome 输出一个 schema version 1 JSON envelope。只有尚未识别 root command 时，
`command` 才为 null。稳定契约是 `category`、`code`、`retryClass`、白名单 `details` 和
`suggestion` action code。

公共输出禁止包含 exception text、endpoint、credential、SecretArn、statement/session ID、
SQL parameter value 或可能含 PII 的完整 SQL。合法 SQLSTATE 只能进入显式 debug telemetry。

CommandResult 的 diagnostics 为内部非公开通道，Wire doctor 到 Connectivity 再到 CLI
必须保留该通道；仅显式 `--debug` 输出白名单字段。连接错误在丢失 SQLSTATE 时仍保持
原公共 error code，另提供固定客户端短语的布尔匹配信号。匹配前剔除已知凭据及目标值，
不保留异常正文、不由消息推导 SQLSTATE、不将这些信号作为自动恢复或新 error taxonomy。

Data API result 最多由 provider 保留 24 小时。CloudTrail 记录 Data API 调用，不记录完整 SQL；
完整 SQL 审计由 Redshift audit logging 负责。

JSON query 返回唯一列名的 object records。完整 inline envelope 在写 stdout 前序列化，最大 64 KiB。
超限返回 `output.inline_size_limit_exceeded`，不会自动切换 artifact。

JSON、NDJSON、CSV 和 recipe 共用显式 recursive encoder：

| 输入值 | 稳定编码 |
|---|---|
| `None`、string、boolean、integer、finite float | 相同 JSON scalar |
| `Decimal` | 不损失精度的 decimal string |
| `date`、`time`、`datetime` | `isoformat()`；naive value 不添加 timezone 或 `Z` |
| `bytes`、`bytearray`、`memoryview` | 小写 hexadecimal string |
| `NaN`、正无穷、负无穷 | `"NaN"`、`"Infinity"`、`"-Infinity"` |
| list 或 tuple | recursive JSON array |
| string key mapping | recursive JSON object |
| 不支持的 nested value 或非 string key | `output.unsupported_value_type` |

CSV 为避免 spreadsheet formula execution，会给以 `=`、`+`、`-`、`@`、tab、CR、LF 或对应
全角前缀开头的 string header/value 添加 apostrophe。NDJSON 不应用该规则。下游 spreadsheet
重新保存产生的转换不属于本 Skill 的可信 sanitization 边界。

## Catalog artifact

Catalog 是可替换 snapshot，不是 query result：

```text
SHOW DATABASES 确认 visible universe
→ 有界采集每个 database metadata
→ 可选 maintained enrichment
→ 内存中构建并校验全部 records
→ 同目录写唯一 temp
→ flush + fsync temp
→ os.replace(temp, catalog.jsonl)
→ fsync parent directory
```

无法确认 database universe 时禁止发布。若部分 database 失败且边界可精确证明，可以发布
`coverage.status=incomplete` 的 snapshot，并记录 database、stage 和稳定 code。任意 malformed line
或 invariant 失败都会使整个 artifact 无效。Fresh/stale 每次根据 `generatedAt` 和 `maxAgeDays`
动态计算，不写入 snapshot。

Object 使用可 round-trip 的 canonical identifier。普通小写名称保持三段式；包含 dot、quote 或
case-sensitive text 的部分使用 SQL quote。未知 relation type 或 nullable value 返回
`metadata.incomplete`，不猜默认值。

`databases` 从 live `SHOW DATABASES` 开始，再 left join snapshot enrichment。`schemas` 使用
`SHOW SCHEMAS FROM DATABASE`，`relations` 使用 `SHOW TABLES FROM SCHEMA`；两者只返回当前
connection/principal 的有界 live 结果，不读取或修改 snapshot。`search` 完全离线，coverage
不完整时必须返回 warning。`describe` 优先 live SHOW，仅在 SHOW 不支持时使用精确过滤的
system-view fallback。

Catalog builder 对每个 metadata stage 读取第 N+1 行确认是否超限：SHOW database/schema 的 N 为
10,000，SVV relation/column 的 N 为 100,000。relation/column 超限记录
`metadata.limit_exceeded` 并发布 `coverage.status=incomplete`；SHOW DATABASES 超限表示 visible
universe 不完整，整个 build 失败并保留旧 snapshot。Interactive SHOW 可以在 10,000 行处停止，
并在 public result 返回 `truncated=true`。

Live metadata 的 public result 包含 `authoritative=true`、`rowCount`、`truncated` 和稳定
connection meta。authority 只对当前 invocation、connection、principal 和请求时间成立。
系统 schema 默认隐藏，`schemas --include-system` 才显示；`relations --kind` 在 transport
边界统一 `table`、`view` 和 `all`。SHOW 不可用、permission、warning、timeout 和 malformed
row 保持不同 typed outcome，不自动 fallback 到 Catalog、SVV 或另一个 connection。

## Query artifact

CSV/NDJSON 要求当前用户拥有、mode `0700` 的本地 POSIX output directory、合法单文件名、
hard-link 支持和 directory fsync 支持。

```text
readonly transaction
→ named server-side cursor
→ 每批最多 fetch 64 行
→ 编码并写入当前批次
→ 直到 limit+1 或结束
→ close cursor + rollback + close connection
```

JSON/recipe 使用 eager `QueryResult.records`。Artifact 使用单次 `StreamingQuery`，主路径不构建
100000 行 dictionary tuple，也不调用 `fetchall()`。

```text
temp_created
→ 写入并 fsync 隐藏 0600 temp
→ hard link 到不存在的 final name
→ final_link_created
→ unlink temp + fsync output directory
→ durable_published
```

Final name 永不覆盖。Link 前失败只 best-effort 清理 temp。Link 后 final 永不删除；非 signal 失败
返回 `output.publish_unknown`，禁止自动重试。只有 `durable_published` 可以返回相对 `outputRef`。

Artifact 最大 64 MiB，按实际 UTF-8 bytes 计算，包含 CSV header、quote、delimiter 和 newline。
超限返回 `output.size_limit_exceeded`，不发布 partial final。Client memory 与当前 fetch batch 和
row width 成正比；单行仍可能很宽，所以这不是绝对进程内存上限。

## Process control 与文件归属

Signal handler 不输出也不清理，只抛专用 control exception。顶层 handler 负责关闭资源并在 stdout
可用时输出 `control.interrupted`。SIGINT exit 130，SIGTERM exit 143。

Signal 在 hard-link/state update 和 directory-fsync/durable-state update 临界区被 mask。Link 后、
durable publish 前中断时保留 final，并报告 `artifactState=may_exist`；durable publish 后报告
`artifactState=published` 和相对 `outputRef`。SIGKILL、进程崩溃或 broken stdout 不保证 envelope。

Durable publish 后，CLI 不再拥有 final。Caller 必须提供任务私有 output directory，并在消费后删除
敏感 artifact。Skill 不提供 TTL、cleanup daemon、registry 或 cleanup command。
