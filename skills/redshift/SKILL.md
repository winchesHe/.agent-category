---
name: redshift
metadata:
  version: 2.2.1
license: Proprietary
description: "Use when a MoeGo task needs read-only Redshift/warehouse queries, MySQL/PostgreSQL replica verification, or Provisioned/Serverless Wire/Data API connection diagnostics. Supports discovery, live metadata, EXPLAIN, bounded export, and maintained recipes. Not for code search, logs, writes, or tasks without database intent."
---

# Redshift

这是 MoeGo 内部通用的只读数据访问 Skill。它可以被 Agent、SDK host 或工程师以
同一契约调用，不绑定某个产品或消息渠道。

调用前，直接复制 Host 本次加载的 `SKILL.md` location，并在同一条 command 中建立
入口。禁止根据 workspace、用户名或安装目录重新拼接。每个独立 shell tool call
都必须在同一条 command 中重新绑定。不要假设之前设置的 shell 变量仍然存在。

下列代码是调用模板。`<loaded SKILL.md location>` 必须替换为 Host 本次提供的原始
location，不能原样执行：

```bash
SKILL_FILE='<loaded SKILL.md location>'
SKILL_DIR="$(dirname "$SKILL_FILE")"
test -f "$SKILL_DIR/scripts/redshift.py" || {
  printf '%s\n' 'Redshift Skill entrypoint is unavailable' >&2
  exit 3
}
python3 "$SKILL_DIR/scripts/redshift.py" COMMAND ...
```

入口检查失败时，重新读取 Host 提供的 Skill location。禁止猜测或修改路径字符串后重试。
唯一公开入口是 `scripts/redshift.py`。

禁止直接 import 内部 `rs/` 模块，禁止绕过入口，禁止构造或建议任何数据库写操作。
本 Skill 没有 `--allow-write`，即使用户要求也不能执行 `INSERT`、`UPDATE`、
`DELETE`、DDL、`COPY`、`UNLOAD`、存储过程或多语句。需要改数据时，停止并说明
这里只能提供只读证据。

SQL guard 保证 statement shape 和已知 session-control function 的拒绝，不证明任意
用户自定义函数或 external function 没有外部副作用。运行此 Skill 的 Redshift role
必须遵循 least privilege：不得拥有未批准 UDF、Lambda UDF 或其他外部函数的
`EXECUTE` 权限。这个数据库权限边界不能由客户端 lexer 替代。

## 标准工作流

1. 先判断问题属于哪个 MoeGo 领域、要查当前状态还是历史聚合。
2. 涉及 account/customer/appointment、legacy grooming service/addon、membership/order/payment/package 或新旧系统
   选择时，读取 [domain-routing.md](references/domain-routing.md)。不要按数据库名猜业务含义。
3. 编写自定义 SQL、查询 system view、处理 metadata/permission 错误，或判断
   Provisioned/Serverless 差异时，读取
   [redshift-semantics.md](references/redshift-semantics.md)。不要套用 PostgreSQL 习惯。
4. 首次执行 live command 前，先用 `doctor --list-connections` 获取安全的 connection
   清单。按任务和 Operator 配置选择一个 name，再用
   `doctor --connection NAME --connect` 验证该 connection。不要从 endpoint、SQL 或错误猜 connection。
5. 对象不确定时先 `search`；database inventory 或 source 类型不确定时用
   `databases`。需要确认当前身份可见的 schema 或 table/view 时，分别使用
   `schemas` 和 `relations`。`search` 读本地 catalog，其他三个 discovery command
   读取当前 connection 的 live metadata。
6. 在写 SQL 前用 `describe` 获取 live metadata。[query-patterns.md](references/query-patterns.md)
   中标记 `verified` 的内容只是可复用起点；形成最终结论前仍要确认 live metadata。
7. Operator 配置多个 named connection 时，按明确任务上下文选择 `--connection`；
   清单中的 `default=true` 只表示 Operator 默认项，不表示它适合所有任务。不要按
   database、SQL、网络错误或对象名猜 transport。
   `--database` 只覆盖本次连接库，不做业务路由。SQL 继续使用完整的
   `database.schema.relation` 对象名。执行 live command 后检查
   `meta.connectionName`、`meta.transport` 和 `meta.connectionDatabase`。
8. ODS/DWD、大表 JOIN、范围不明确或成本较高的查询先 `explain`，再执行有界
   `query`。空 `advisories` 不代表查询安全或高效。
9. 只依据 `ok`、稳定 error code、`retryClass` 和 `suggestion` 决定下一步。
   不要从错误文案猜类别。

## 领域入口

| 任务 | 起点 |
|---|---|
| 指标、趋势、报表、历史聚合 | Warehouse ADS/DWS/DIM；明细再到 DWD |
| ETL/原始同步排查 | Warehouse ODS/RAW |
| email/account → company/business | `recipe email-to-company` |
| 当前客户、联系方式、宠物 | `pg_moego_customer_prod`，按 domain reference 确认边界 |
| 当前预约状态时间线 | `recipe appointment-timeline`；其他履约问题再读 domain reference |
| Legacy grooming service/addon | `mysql_prod.moe_grooming`；读取 legacy grooming reference 后重新 metadata |
| 当前订单与行项 | `pg_moego_order_prod` |
| 当前退款来源 | `recipe refund-origin`；其他支付问题先区分 product generation |
| 当前会员/订阅/权益链路 | `recipe membership-entitlement`；不自动混合旧会员模型 |
| Package 核销 | 读取 domain reference；旧模板存在字段漂移，必须先 metadata |

新旧并存不等于总是“新版优先”。租户、时间范围、金额单位或产品代际会改变结论时，
先问用户一次。空结果本身不是切换到 legacy source 的证据。

## 命令契约

下表由 `CommandSpec` 生成；参数必须放在对应 leaf command 后面。把
`--database`、`--format` 等 leaf option 放在 root 会返回 `usage.option_scope`。

<!-- BEGIN GENERATED COMMAND MATRIX -->
| Command | Canonical grammar | Formats |
|---|---|---|
| `databases` | `redshift databases [--connection NAME] [--source-type TYPE] [--format json]` | `json` |
| `schemas` | `redshift schemas DATABASE [--connection NAME] [--include-system] [--limit LIMIT] [--format json]` | `json` |
| `relations` | `redshift relations DATABASE.SCHEMA [--connection NAME] [--kind table|view|all] [--limit LIMIT] [--format json]` | `json` |
| `search` | `redshift search [TEXT] [filters] [--format json]` | `json` |
| `describe` | `redshift describe DATABASE.SCHEMA.RELATION [--connection NAME] [--format json]` | `json` |
| `query` | `redshift query [--connection NAME] [--database DATABASE] (--sql SQL | --file PATH) [options]` | `json,csv,ndjson` |
| `explain` | `redshift explain [--connection NAME] [--database DATABASE] (--sql SQL | --file PATH) [options]` | `json` |
| `recipe` | `redshift recipe (list | email-to-company | appointment-timeline | refund-origin | membership-entitlement) [--connection NAME] [options]` | `json` |
| `doctor` | `redshift doctor [--connection NAME] [--connect | --list-connections] [--debug] [--format json]` | `json` |
<!-- END GENERATED COMMAND MATRIX -->

完整 leaf options 使用 `python3 "$SKILL_DIR/scripts/redshift.py" COMMAND --help`
查询。Help 是 plain text 且成功时 exit 0；正常 command outcome 才使用 typed JSON
envelope。不要读取内部 parser 或猜测省略的 `[filters]` / `[options]`。

### Connection 选择

```bash
python3 "$SKILL_DIR/scripts/redshift.py" doctor \
  --list-connections --format json

python3 "$SKILL_DIR/scripts/redshift.py" doctor \
  --connection "$CONNECTION_NAME" --connect --format json
```

`doctor --list-connections` 是离线、无网络的安全清单。它只返回 `name`、
`deployment`、`transport`、`database`、`authMode`、`default` 和 `catalog`。
它不会创建 Adapter，也不返回 endpoint、AWS account/profile、principal、SecretArn、
环境变量 key 或 credential。`--list-connections` 不能和 `--connect` 或
`--connection` 组合。

从清单选择 name 后，将 `CONNECTION_NAME` 设置为该原始 name。下列 live 示例都要求
已设置该 shell 变量。不要静默修改 name。

- `databases`、`describe`、`query`、`explain`、执行型 `recipe` 和 `doctor`
  接受 leaf option `--connection NAME`。
- `search` 始终离线，不接受 `--connection`。
- `recipe list` 始终离线，和 `--connection` 组合会返回 `usage.invalid_combination`。
- 未传 `--connection` 时使用 operator 配置的 `defaultConnection`。
- Wire 与 Data API 是同一 Skill 的内部 transport。失败后禁止自动切换 transport、
  credential source、target 或 connection。
- AWS client 不使用 ambient endpoint override；Wire `target.host` 只接受单个网络 hostname、IPv4
  或 IPv6 literal，port 使用独立字段。
- Named connection 的用户配置按 [README.md](README.md) Quickstart 执行；维护、live smoke
  和发布流程再读取 `MAINTENANCE.md`。

### 探索与 metadata

```bash
python3 "$SKILL_DIR/scripts/redshift.py" databases \
  --connection "$CONNECTION_NAME" --source-type postgres --format json

python3 "$SKILL_DIR/scripts/redshift.py" schemas \
  pg_moego_order_prod --connection "$CONNECTION_NAME" --format json

python3 "$SKILL_DIR/scripts/redshift.py" relations \
  pg_moego_order_prod.public --connection "$CONNECTION_NAME" \
  --kind all --format json

python3 "$SKILL_DIR/scripts/redshift.py" search payment \
  --source-type warehouse --domain payment --limit 20 --format json

python3 "$SKILL_DIR/scripts/redshift.py" describe \
  pg_moego_order_prod.public.order \
  --connection "$CONNECTION_NAME" --format json
```

`schemas` 和 `relations` 的结果只对本次 connection、principal 和请求时间成立。
两个 command 使用 Redshift `SHOW`，不会读取或修改本地 Catalog。默认隐藏系统 schema；
使用 `schemas --include-system` 才显示 `information_schema`、`pg_catalog` 和
`pg_internal`。`relations --kind` 支持 `table`、`view` 和 `all`。两个 command 默认
返回最多 200 行，最大 10,000 行；`truncated=true` 表示结果超过 caller limit。
空结果是当前 principal 可见对象为空，不代表其他 principal 也不可见。

Catalog build 使用更高的内部上限：SHOW database/schema 为 10,000 行，SVV relation/column
为 100,000 行，并读取一行确认是否超限。relation/column 超限会记录
`metadata.limit_exceeded`，对应 database 的 coverage 变为 incomplete；SHOW DATABASES 超限
会停止发布并保留旧 Catalog。

Catalog 的 `fresh` / `stale` 每次请求动态计算。`search` 返回
`catalog.coverage_incomplete` 时，零匹配不能解释为“全集没有”；查看 coverage，
再对相关 database 做 `schemas`、`relations` 或 `describe`。`describe` 的 permission、warning、incomplete
和 timeout 都不是 `metadata.not_found`。

`databases` 中 enrichment 与 freshness 是两个独立维度：`sourceType: null` 表示
没有 enrichment，不表示已分类为 unknown；`objectCount: null` 表示当前不能给出
完整数量；`enrichmentStatus` 描述补充信息是否 complete / incomplete / missing，
`catalogFreshness` 只描述 catalog 是 fresh / stale。新 catalog 会持久化已完整扫描但
没有 relation 的 database 身份；旧 catalog 缺少该字段时不会按数量猜测，相关 live
database 保持 `missing`，需要 operator 重建 catalog。

### Query 与参数

```bash
python3 "$SKILL_DIR/scripts/redshift.py" query \
  --connection "$CONNECTION_NAME" \
  --database pg_moego_order_prod \
  --sql 'SELECT id, create_time FROM pg_moego_order_prod.public."order" WHERE id = %(order_id)s' \
  --params '{"order_id":123456}' \
  --limit 20 --format json
```

- `--sql` / `--file` 二选一；`--params` / `--params-file` 二选一。
- 参数必须是 JSON object，SQL 使用 psycopg named placeholder `%(name)s`。
- 参数值只接受 JSON scalar 或由 scalar 组成的 array；nested object（包括 array 内的
  object）会在连接前返回 `query.invalid_parameters`。
- Wire 与 Data API 都会把完整 `IN %(name)s` / `NOT IN %(name)s` 右侧的非空 flat
  array 安全展开为逐元素 placeholder。Wire 在 `ANY(%(name)s)` 等非 IN 场景保留 V2
  array 语义；Data API 对这些没有等价语义的形状返回
  `capability.parameter_shape_unavailable`，不会改写或猜测。
- 禁止 positional `%s`；literal percent 写成 `%%`。missing、extra 或重复 JSON key
  都会返回 `query.invalid_parameters`。
- `--limit` 只接受正整数。JSON 默认且最多 200；CSV/NDJSON 最多 100000，
  且最终 artifact 的 UTF-8 编码大小最多 64 MiB。
- JSON query 的完整 stdout envelope 最多 64 KiB。超过时返回
  `output.inline_size_limit_exceeded` 和 `suggestion=use_artifact`；Skill 不会自动改成导出。
- 结果是 object records；重复输出列名返回 `query.duplicate_output_column`，应显式 alias。
- timeout 后收窄时间、对象或 JOIN，再重试；Skill 不自动重试，也不切到 writable session。

### Explain

```bash
python3 "$SKILL_DIR/scripts/redshift.py" explain \
  --connection "$CONNECTION_NAME" \
  --database dbt_dw --file /private/task/query.sql --format json
```

`plan` 是 Redshift 返回的硬结果；`advisories` 只是 best-effort 的本地提示。第一版
只发布能从确定证据产生的 advisory，例如 `query.select_star`。不能把没有 advisory
解释为已做完整性能或安全分析。

### Recipe

```bash
python3 "$SKILL_DIR/scripts/redshift.py" recipe list --format json
python3 "$SKILL_DIR/scripts/redshift.py" recipe email-to-company \
  --connection "$CONNECTION_NAME" \
  --email person@example.invalid --format json

python3 "$SKILL_DIR/scripts/redshift.py" recipe appointment-timeline \
  --connection "$CONNECTION_NAME" \
  --appointment-id 123456 --format json

python3 "$SKILL_DIR/scripts/redshift.py" recipe refund-origin \
  --connection "$CONNECTION_NAME" \
  --refund-id 123456 --format json

python3 "$SKILL_DIR/scripts/redshift.py" recipe membership-entitlement \
  --connection "$CONNECTION_NAME" \
  --subscription-id 123456 --format json
```

`email-to-company` 是显式的两段有界只读计划：先查有效 MOEGO account IDs，只有
非空时才查 company/business membership。它不会隐藏跨库 fallback；任一阶段失败
都会保留 typed error，不会伪装成“查无结果”。不要手写或复制其 identity filter。

`appointment-timeline` 只查询当前 fulfillment 模型，返回 appointment snapshot 和
有序 status transitions；它不是所有字段变更的 audit log，也不自动回退 legacy grooming。

`refund-origin` 只从当前 payment-service refund 出发，读取对应 payment，再查询
匹配的 order-payment。没有 order-payment match 不会触发 legacy fallback。

`membership-entitlement` 必须且只能提供 `--membership-id` 或
`--subscription-id` 之一。它分别返回 membership、subscription、price、benefit
configuration、issued benefit 和 event，不读取 event payload，也不混合旧会员模型。

执行型 recipe 会先从所选 connection 读取一次 live database inventory。任一所需
database 不可见时，Skill 在执行首条 recipe SQL 前返回
`capability.recipe_source_unavailable` 和 `suggestion=select_connection`。它不会切换
connection 或 transport。该 preflight 只证明 database 可见；实际对象仍由 readonly query 验证。

## Artifact export

JSON query 不需要 `REDSHIFT_OUTPUT_DIR`。CSV/NDJSON 必须同时提供格式、单个 final
name 和由 host 设置的私有目录：

```bash
python3 "$SKILL_DIR/scripts/redshift.py" query \
  --connection "$CONNECTION_NAME" \
  --database dbt_dw --file /private/task/query.sql \
  --format ndjson --output payment-results.ndjson
```

成功 stdout 只返回相对 `outputRef`，其值就是经过校验但未被修改的 final name，
只在本次 `REDSHIFT_OUTPUT_DIR` 上下文中有意义。禁止路径、`.`、`..` 和隐藏名；
不会覆盖已有文件。`output.publish_unknown` 表示 final 可能已存在，`retryClass=never`，
不能自动重复同一导出。caller 消费完敏感 artifact 后负责删除。

CSV/NDJSON 在客户端分批读取并直接写临时文件，不会先把最多 100000 行全部构建为
records。64 MiB 上限按实际 UTF-8 输出计算，包含 CSV header、引号、分隔符、中文和
换行；超过时返回 `output.size_limit_exceeded`，不发布部分文件。这个契约限制客户端
累计结果和 artifact 大小，不代表单个 fetch batch 或单行拥有绝对进程内存上限。

CSV 对 spreadsheet formula prefix 做防护：字符串 header 或 value 以 ASCII
`=`、`+`、`-`、`@`、tab、CR、LF 或对应全角字符开头时，会添加一个前导
apostrophe。非字符串和普通字符串保持编码结果不变。需要避免 CSV apostrophe
改写、保持 JSON encoder 输出语义的消费者应使用 NDJSON；NDJSON 不应用 CSV
规则。Spreadsheet 保存并重新打开时可能重写 cell，不能把外部转换后的文件继续
视为已完成可信 sanitization。

## 输出与恢复

所有 caught command 结果写一条 schema version 1 JSON envelope 到 stdout：

```json
{"schemaVersion":1,"ok":false,"command":"query","error":{"category":"query","code":"timeout","retryClass":"transient"}}
```

| Error / retryClass | 下一步 |
|---|---|
| `usage.*` / `after_change` | 按 canonical grammar 修正 command/option/参数位置 |
| `config.*` / `after_change` | 报告缺失 key，由 operator 修复；不要猜值 |
| `catalog.unavailable|invalid` | 不把 search 当全集；operator 重建 catalog |
| `metadata.not_found` / `suggestion=search_object` | 用 `details.object` 重新 search 或核对完整对象名 |
| `query.permission_denied|metadata.permission_denied` / `suggestion=request_data_access` | 保留不确定性；请 Data Team 核对 database user、object grant 和可见范围 |
| `metadata.failed` / `suggestion=inspect_provider_failure` | Provider 只确认 metadata statement 失败；停止重试，由 Operator 检查私有诊断，不从错误文本猜权限或对象 |
| `metadata.limit_exceeded` / `after_change` | 缩小 metadata 范围或由 Operator 分 database 重建 Catalog；不要把结果当成完整 inventory |
| `query.timeout` / `transient` | 收窄查询后重试，不原样循环 |
| `query.undefined_table` / `suggestion=search_object` | 用安全诊断字段缩小范围后重新 search |
| `query.undefined_column` / `suggestion=describe_object` | 对目标对象重新 describe，再修改列名 |
| `query.syntax_error` / `suggestion=inspect_sql_position` | 检查 `details.position` 附近的 SQL；缺失时不要猜位置 |
| `query.cannot_coerce` / `suggestion=inspect_types` | describe 相关对象并核对 cast 两侧的数据类型 |
| `query.undefined_function` / `suggestion=inspect_function_signature` | 核对函数名、参数类型和 Redshift 支持情况 |
| `config.connection_not_found` / `suggestion=list_connections` | 重新读取安全清单并选择已有 name |
| `capability.readonly_unavailable` / `suggestion=fix_readonly_role` | 当前 live session 未确认只读；停止查询并由 Operator 修复连接配置 |
| `capability.cross_database_read_unavailable` / `suggestion=use_single_database_or_recipe` | 改成单库查询或已有显式 recipe，不降低只读 |
| `capability.parameter_shape_unavailable` / `suggestion=simplify_parameters` | 当前 transport 无等价参数语义；改用 scalar 或完整 IN-list |
| `capability.recipe_source_unavailable` / `suggestion=select_connection` | 所选 connection 看不到 recipe 所需 database；从安全清单重新选择 |
| `connection.auth_interaction_required` / `suggestion=refresh_aws_auth` | AWS profile 需要人工续期；Operator 在进程外重新登录 |
| `connection.aws_credentials_unavailable` / `suggestion=configure_aws_credentials` | Operator 修复 AWS credential，不切换身份 |
| `connection.permission_denied` / `suggestion=request_platform_access` | 请 SRE 核对 AWS IAM、Secret、target 和网络权限；不切换身份 |
| `query.submission_unknown` / `never` | Data API 是否接受 SQL 无法确认；禁止自动重提 |
| `query.failed` / `never` | 依据 `details.stage` 缩小范围；禁止从原始 provider 文案猜原因 |
| `output.already_exists` | 使用新的 caller-approved final name |
| `output.size_limit_exceeded` / `after_change` | 减少列、行或时间范围后使用新文件名重试 |
| `output.inline_size_limit_exceeded` / `suggestion=use_artifact` | 明确选择 CSV/NDJSON、私有目录和新 final name 后重试 |
| `output.publish_unknown` / `never` | final 可能存在；检查私有目录，禁止自动重试 |
| `control.interrupted` / `never` | 任务已中断；只有用户新指示才重新执行 |

Shell exit code 只做粗分：2 usage、3 config、4 safety、5 connection/capability、
6 catalog/metadata、7 query、8 output/internal、130 SIGINT、143 SIGTERM。

`query.failed` 的 `details.stage` 只定位 lifecycle 阶段，不提供根因。没有新的 typed
evidence 时，将根因保持为 unknown；禁止把 IAM、readonly、database visibility、
cross-database、SQL 或 provider 状态列为“可能原因”。需要继续时，只运行能产生新
typed evidence 的显式 `doctor`、`databases` 或其他有界 probe。

`error.suggestion` 是稳定的恢复动作 code，不是面向用户的自然语言文案。
`error.details` 对上述 SQL 错误最多包含驱动明确提供且通过白名单校验的
`schema`、`table`、`column`、`position`；字段缺失时不得从原始异常或 SQL 猜测。
SQLSTATE 只允许进入显式 `--debug` 的 allowlisted diagnostic，不进入 public error。

## 信息与数据安全

- 不输出 credential、token、endpoint、环境变量值、原始异常、SQL parameter value、
  含 PII 的完整 SQL、artifact 内容或绝对 output path。
- `--debug` 只允许 command、source/database、SQL hash、参数名和类型、elapsed、
  row count、SQLSTATE、metadata fallback source，以及文末定义的连接阶段、驱动类型和固定布尔信号；
  不得打印 SQL、参数值或原始异常。
- 查询 PII 时只取完成任务所需的最少列和最小范围。不要在解释或错误里复述邮箱、
  电话、客户详情等查询参数。
- Redshift 是只读副本，但查询仍可能昂贵。始终 bounded；遇到大表、DWD/ODS、
  大 JOIN 或无明确时间范围时先 EXPLAIN。

## 按需 reference

- [domain-routing.md](references/domain-routing.md)：选择 MoeGo source、版本和 fallback 边界。
- [query-patterns.md](references/query-patterns.md)：选定领域后的 verified JOIN/过滤/解释。
- [legacy-grooming.md](references/legacy-grooming.md)：legacy service/addon/appointment 的 grain、枚举、Join 和统计边界。
- [redshift-semantics.md](references/redshift-semantics.md)：Redshift 方言、deployment、
  metadata/system view、Data API 和 permission 诊断边界。
- `catalog.jsonl`：只通过 `search`/loader 使用，不手工 grep，不直接塞进上下文。

`doctor --list-connections` 用于 Agent 离线选择 connection。
`doctor --connection NAME --connect --debug` 在 stderr 输出独立的安全诊断，
普通 stdout 不包含诊断字段。Wire 连接失败可报告 `connectionStage`、
`driverErrorType`、驱动明确提供的 `sqlState`，以及 `connectTimedOut`、
`passwordRejected`、`tlsVerificationFailed` 三个固定客户端短语匹配标记。
匹配前移除已知连接凭据和目标值，不保留或输出异常正文。这些标记不改变公共
error code，不生成 SQLSTATE，也不是自动重试、改配置或切换连接的依据；
`false` 只表示未匹配，不证明密码、网络或 TLS 正确。
`doctor [--connection NAME] [--connect]` 用于 Operator 诊断配置、catalog、connectivity、
readonly/cross-database 和 artifact capability；不会安装依赖、改配置或修复环境。
缺少 output directory 只表示 artifact export unavailable，不影响 JSON query 或整个 Skill。
显式 `doctor --connect` 只有在连接成功且 live session 确认 readonly 时才报告
Skill/query available。
