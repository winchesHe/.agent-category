---
name: moe-t2-database
metadata:
  version: 1.0.3
description: >
  Use when MoeGo engineers need T2 PostgreSQL or MySQL connection details, database
  names, table names, or direct psql/mysql command patterns for the main PostgreSQL
  instance, membership v2, grooming, message, or business databases.
compatibility: Requires psql and mysql clients plus host-managed credentials. PostgreSQL uses T2_DATABASE_USER with .pgpass or PGPASSWORD; MySQL uses T2_MYSQL_OPTION_FILE.
---

# T2 Database

查询 MoeGo T2 开发数据库连接信息，并构造直接的本地数据库客户端命令。

## 工作流

1. 执行数据库命令前，先读取 `references/connections.yaml`。
2. 按服务名和数据库引擎选择连接：
   - PostgreSQL：`pg_main`、`membership_v2`
   - `pg_main` 下的数据库：`membership_old`、`subscription`、`billing`、`account`
   - MySQL：`business`、`grooming`、`message`
3. 按“执行确认”分级处理 SQL。数据库凭据只决定技术权限，不能代替用户确认。
4. 执行写操作后，使用只读查询回读可观察结果。回读失败时报告“写入结果未验证”，不能声称完成。
5. 连接字段标记为 `inferred` 时，必须说明该字段是推断值。需要权威值时，先从对应仓库配置验证。

## 执行确认

| 级别 | 范围 | 执行条件 |
| --- | --- | --- |
| R0 | 单个 database 内的单条只读 SQL | 确认目标连接后可执行 |
| W1 | 单个 database 内的单条 `INSERT`、`UPDATE` 或 `DELETE` | 先只读核实范围；再用自然语言展示 database、table、筛选条件和预计影响，并等待本次操作的明确确认 |
| W2 | DDL、权限语句、多语句或跨 database 操作 | 初始请求不构成执行确认；拆成可独立审阅的操作，逐项展示 database、object、动作和不可逆影响，并逐项等待明确确认 |

- W1 和 W2 只能执行确认时展示的操作。SQL、目标或影响范围变化后，原确认失效。
- W2 不接受“全部确认”“按上面执行”等批量确认。每个操作必须单独确认。
- 无法完成只读核实、确认内容有歧义或用户未确认时，停止执行。
- 不建立通用权限策略。以上规则只约束本 Skill 的直接数据库客户端操作。

## 凭据

- 从宿主环境读取 `T2_DATABASE_USER`。
- PostgreSQL 密码由宿主的 `.pgpass` 或 `PGPASSWORD` 提供。
- MySQL 密码只能由宿主管理的 MySQL option file 提供。文件路径由 `T2_MYSQL_OPTION_FILE` 指定。
- MySQL option file 必须是当前用户拥有的普通文件，权限不得高于 `0600`。Skill 不读取或输出文件内容。
- 禁止输出用户名、密码或包含凭据的 DSN。
- 禁止把凭据放入命令参数。

## 命令规则

- PostgreSQL 命令必须直接以 `psql` 开头。
- MySQL 命令必须直接以 `mysql` 开头。
- `--defaults-extra-file` 必须是 MySQL 的第一个参数。缺少 `T2_MYSQL_OPTION_FILE` 时停止，不得回退到交互式 `-p`。
- 不要使用 shell wrapper、管道、heredoc、重定向或命令替换。
- 不要在命令前添加环境变量赋值。
- `<SQL>` 必须按当前 shell 安全引用。不能机械替换单引号模板。

PostgreSQL：

```bash
psql -h <host> -p <port> -U "$T2_DATABASE_USER" -d <database>
psql -h <host> -p <port> -U "$T2_DATABASE_USER" -d <database> -c <SQL>
```

MySQL：

```bash
mysql --defaults-extra-file="$T2_MYSQL_OPTION_FILE" -h <host> -P <port> -u "$T2_DATABASE_USER" <database>
mysql --defaults-extra-file="$T2_MYSQL_OPTION_FILE" -h <host> -P <port> -u "$T2_DATABASE_USER" <database> -e <SQL>
```

含 SQL 字符串字面量的直接命令示例：

```bash
psql -h postgres.t2.moego.dev -p 40132 -U "$T2_DATABASE_USER" -d moego_account -c "select id, email from public.account where email = 'owner@example.com';"
mysql --defaults-extra-file="$T2_MYSQL_OPTION_FILE" -h mysql.t2.moego.dev -P 40106 -u "$T2_DATABASE_USER" moe_business -e "select id, business_name from moe_business where business_name = 'Paws & Play';"
```

## 常用查询

按 owner email 查询 company 和 business：

1. 在 PostgreSQL `pg_main.databases.account` 中，按 `public.account.email` 查询 `public.account.id`。
2. 在 MySQL `business` 中，按 `moe_company.account_id = account.id` 查询 `moe_company`。
3. 在 MySQL `business` 中，按 `moe_business.company_id = moe_company.id` 查询 location 或 business。

```sql
-- PostgreSQL: moego_account
select id, email
from public.account
where email = '<owner_email>';
```

```sql
-- MySQL: moe_business
select
  mc.id as company_id,
  mc.name as company_name,
  mc.enterprise_id,
  mb.id as business_id,
  mb.business_name
from moe_company mc
left join moe_business mb on mb.company_id = mc.id
where mc.account_id = <account_id>;
```
