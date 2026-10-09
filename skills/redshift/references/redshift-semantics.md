# Redshift 语义与诊断

适用：编写自定义 SQL、查询系统视图、处理 metadata/permission 错误，或分析
Provisioned 与 Serverless 差异。

最近官方复核：`2026-08-20`。

## 先确定 deployment

- Provisioned 使用 cluster；Data API 使用 `ClusterIdentifier`。
- Serverless 使用 workgroup/namespace；Data API 使用 `WorkgroupName`。
- `SELECT version()` 不能可靠判断 deployment。应读取 connection profile 或 AWS live metadata。

## Redshift 不是 PostgreSQL

Redshift 支持 PostgreSQL wire protocol，但不能继承 PostgreSQL 的全部语义。生成 SQL
前检查这些高频差异：

- 不使用 `CREATE INDEX`、sequence、`SERIAL`、`RETURNING` 或 `LATERAL`。
- 聚合字符串使用 Redshift `LISTAGG`，不要默认使用 PostgreSQL `string_agg`。
- 字符串截取使用 AWS 文档列出的 `SUBSTRING`。不根据 PostgreSQL alias 猜支持范围。
- `DATEADD` / `DATEDIFF` 把时间单位放在第一个参数。
- `PRIMARY KEY`、`FOREIGN KEY`、`UNIQUE` 只为 optimizer 提供 hint，不强制数据约束。
- `text` 不表示 PostgreSQL 的无限文本类型。读取 live metadata 后再决定 cast。
- 默认使用完整 `database.schema.relation`；external/datashare object 不依赖
  `search_path`。

本 Skill 始终只读。即使 Redshift 支持 COPY、UNLOAD、MERGE 或 datashare write，也
不能通过本 Skill 执行或建议绕过只读边界。

## Metadata 与系统视图

- 对象发现优先使用 `SHOW DATABASES/SCHEMAS/TABLES/COLUMNS`。
- `SHOW` list command 最多返回 10,000 行。大范围 catalog 不能把该上限当作完整结果。
- `SVV_ALL_TABLES` / `SVV_ALL_COLUMNS` 用于批量读取 local、external 和 datashare metadata。
- 查询运行历史和性能时优先使用 `SYS_*`。
- `STL_*`、`STV_*`、`SVL_*`、`SVCS_*` 属于 Provisioned-only 监控视图。Provisioned 与
  Serverless 的通用监控优先使用对应 `SYS_*` view。
- Serverless 只支持部分 `SVV_*`。不能根据视图族名称猜某个视图可用。

遇到 `relation does not exist`：

1. 用 `search` 找候选对象；catalog coverage incomplete 时保留不确定性。
2. 用 `describe` 获取 live metadata。
3. 核对 connection、database 和完整三段式对象名。
4. 若目标是系统视图，先核对 deployment 支持矩阵。

遇到 permission error：保留 typed error。`query.permission_denied` 和
`metadata.permission_denied` 使用 `request_data_access`，由 Data Team 核对 database
user、object grant 和 metadata 可见范围。`connection.permission_denied` 使用
`request_platform_access`，由 SRE 核对 AWS IAM、Secret、target 和网络权限。不要自动
更换 AWS identity、database user、connection 或 transport，也不要生成 GRANT。

## Data API

- Data API 默认异步。`WaitTimeSeconds` 是 1–30 秒的 long poll，不能替代总 deadline。
- Provisioned 与 Serverless 的 target 参数不同；auth 选择与 deployment 选择正交。
- V2 live acceptance 已观察到：statement 已完成但 result 尚不可读取时，`GetStatementResult`
  可能暂时返回 `ResourceNotFoundException`。该行为作为有界 compatibility recovery 处理，
  不是 AWS API 的通用语义保证。保持同一 statement ID，在 result-fetch deadline 内继续；
  禁止重提 SQL。
- 检查 `HasResultSet` 后再获取结果。
- Data API throttle 可能使用 HTTP 400。按 AWS error code 分类，不能只按 HTTP 429 判断。
- Data API result 最多保留 24 小时。statement ID 和 result 都视为敏感数据。
- CloudTrail 记录 `redshift-data:*` API 调用，但不记录完整 SQL。需要 SQL 审计时由
  Operator 配置 Redshift audit logging。

新 connection 优先使用 IAM、临时 `DbUser` 或 `SecretArn`。Password mode 只用于 operator
明确配置的 Wire target。Secret value、statement ID、SQL 和 result 禁止进入
公共 error、日志或报告。

## AWS 官方来源

- [Using the Amazon Redshift Data API](https://docs.aws.amazon.com/redshift/latest/mgmt/data-api.html)：
  Data API 异步模型、Provisioned/Serverless 支持、24 小时 query/result 上限。
- [ExecuteStatement API](https://docs.aws.amazon.com/redshift-data/latest/APIReference/API_ExecuteStatement.html)：
  target、IAM/DbUser/SecretArn 参数组合和 session keepalive。
- [GetStatementResult API](https://docs.aws.amazon.com/redshift-data/latest/APIReference/API_GetStatementResult.html)：
  result page 与 `NextToken` 契约。
- [SYS monitoring views](https://docs.aws.amazon.com/redshift/latest/dg/serverless_views-monitoring.html)：
  Provisioned 与 Serverless 的通用 SYS 视图。
- [System tables and views reference](https://docs.aws.amazon.com/redshift/latest/dg/cm_chap_system-tables.html)：
  Provisioned-only 视图与 SYS migration 边界。
- [Table constraints](https://docs.aws.amazon.com/redshift/latest/dg/t_Defining_constraints.html)：
  PK/FK/UNIQUE 为 informational constraint，`NOT NULL` 仍会强制执行。
- [Amazon Redshift and PostgreSQL](https://docs.aws.amazon.com/redshift/latest/dg/c_redshift-and-postgres-sql.html)
  与 [Unsupported PostgreSQL functions](https://docs.aws.amazon.com/redshift/latest/dg/c_unsupported-postgresql-functions.html)：
  Redshift 与 PostgreSQL 差异及不支持函数。
