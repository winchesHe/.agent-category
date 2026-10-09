# 数据库与 Redis 调试

- ID：`MDEV-DATABASE-DEBUGGING`
- 适用：MoeGo 开发与测试的数据连接、业务状态排查、集成测试和迁移验证。

## 按环境选择操作入口

| 当前目标 | 入口与适用范围 |
|---|---|
| T2 PostgreSQL/MySQL 连接、凭据或直接客户端操作 | 从当前 Host catalog 定位并读取 `moe-t2-database/SKILL.md`，再按其实际目录读取 `references/connections.yaml`；连接选择、推断值核对、凭据保护、命令形式、操作分级确认和写后回读均由该 skill 管理 |
| 数仓或同步只读副本查询 | 使用 `redshift`；不能替代 T2 业务库写入 |
| 非 T2 PostgreSQL/MySQL、Redis 或 ClickHouse 接入 | 按下方通用接入指引及目标环境规则处理 |
| 业务状态、事务、测试隔离或迁移结果判断 | 继续读取本文对应章节；实际数据库操作仍服从所属环境入口 |

T2 专业 skill 的安装位置不要求与本经验相邻，也不从历史 checkout 猜运行入口。缺少该 skill 时明确说明依赖，继续源码、映射与 SQL 意图等可独立核对；不自动安装、创建替代工具或回退本文模板。它使用原生 `psql` / `mysql`，不是另一个数据库 wrapper。

本文下方 PostgreSQL/MySQL 命令模板、命令前环境变量赋值、SQL 文件重定向及 Adminer 备选仅适用于非 T2。T2 必须按专业 skill 构造命令与保护身份信息，不能照搬这些模板或输出其中的账号字段；模板可用不代表获准执行。

## 非 T2 数据库与 Redis 接入

Agent 优先使用 `mysql`、`psql`、`redis-cli`，采用非交互命令和可解析输出，复用已有连接配置与凭据注入。缺客户端时先检查安装位置，只需客户端，不必启动本地数据库服务。

实例地址、代理端口、TLS 和认证方式统一读取[DB/Redis 接入说明](https://mengshikeji.feishu.cn/wiki/PG03wrSsqi75IOkL8vScaAdtnnc)，再从目标应用配置确认库名与账号。已有准确连接信息时直接复用；这里不维护第二份端点表。

- 本机代理地址与 Pod 内 datasource 地址不能直接互换；同一 host 的不同端口可能对应不同实例。
- Web SSO、数据库账号、网络可达和库权限分别核对；SELECT 权限不等于建库或迁移权限。
- CLI 条件不具备或用户需要页面操作时，可用 [Adminer](https://adminer.devops.moego.pet) 查询同一目标，仍需确认实例、数据库和账号。ClickHouse 按接入说明选择其客户端协议，不套 MySQL/Postgres 命令。

## 非 T2 SQL 连接后确认身份与落点

MySQL 使用已有受保护配置文件，`--defaults-extra-file` 放在首个选项；host/port/database 来自已确认目标：

```bash
mysql --defaults-extra-file='<客户端配置文件>' \
  --protocol=TCP --host='<host>' --port='<port>' \
  --database='<目标库>' --connect-timeout=10 --batch \
  --execute='SELECT DATABASE(), @@hostname, @@port, VERSION(), CURRENT_USER(), @@session.time_zone, UTC_TIMESTAMP(3);'
```

Postgres 复用密码文件或进程凭据。`--no-password` 避免缺少凭据时卡在交互提示，`-X` 避免用户启动文件改变查询行为：

```bash
PGCONNECT_TIMEOUT=10 psql -X --no-password \
  --host='<host>' --port='<port>' \
  --username='<数据库账号>' --dbname='<目标库>' \
  --csv --set=ON_ERROR_STOP=1 \
  --command='SELECT current_database(), current_user, inet_server_addr(), inet_server_port(), version();'
```

TLS/CA 按实例要求配置，口令不写进命令或文档。服务端内部端口可能不同于本机代理端口，不能仅凭端口不同认定连错。

先检查退出状态再解析 stdout。MySQL `--batch` 使用带转义的制表符输出，psql `--csv` 使用 CSV；执行 SQL 文件时沿用连接参数，分别以输入重定向或 `--file` 替换单条查询，psql 保留 `ON_ERROR_STOP`。完整选项按本机帮助或 [mysql](https://dev.mysql.com/doc/refman/8.4/en/mysql-command-options.html)、[psql](https://www.postgresql.org/docs/current/app-psql.html)说明读取。

超时查网络与代理地址，认证失败查账号和实例授权，TLS 错误查证书与配置；浏览器能登录不代表这些条件成立。

## 从实际结构与同一业务对象查询

表名、字段、关联键和租户条件从当前 ORM/Repository、正式迁移与数据库结构核对。MySQL 可读 `SHOW CREATE TABLE` / 索引，Postgres 可用 psql 的 `\d+`；不从历史案例复制业务 SQL 或假定所有异步服务都有相同表结构。

按准确对象、时间窗口、稳定排序与适量 LIMIT 查询必要字段。拿到任务标识后再追关联记录；旧成功记录不能证明本次成功。

| 现象 | 检查 |
|---|---|
| 表不存在 | 先确认实例与库，再查正式迁移 |
| 表存在但应用拒绝启动 | 对照列、索引、CHECK、生成列和会话要求；不能只数表 |
| 异步状态不推进 | 数据库时间、下次执行时间、租约和执行范围；结合[Kafka](kafka-debugging.md)与[日志](business-chain-logging.md) |
| 状态成功但读取结果不符 | 关联对象、租户、业务版本和实际读取条件 |
| 不断查询仍是旧值 | 检查是否处于早先的可重复读事务快照 |

核对租约与重试时间时使用数据库时间并明确时区。持续观察进度采用能取得新状态的查询方式；需要一致性快照时，明确其不能代表后续实时变化。

## Redis 的逻辑 DB、Key 与 TTL

先确认准确实例、逻辑 DB、Key 前缀和缓存策略，复用 `REDISCLI_AUTH` 或已有凭据配置；ACL 用户和 CA 按实例要求提供。以下模板适用于已确认启用 TLS 的目标：

```bash
redis-cli -h '<host>' -p '<port>' --tls -n '<逻辑DB>' PING
redis-cli -h '<host>' -p '<port>' --tls -n '<逻辑DB>' SCAN 0 MATCH '<业务Key前缀>*' COUNT 100
redis-cli -h '<host>' -p '<port>' --tls -n '<逻辑DB>' TYPE '<准确Key>'
redis-cli -h '<host>' -p '<port>' --tls -n '<逻辑DB>' TTL '<准确Key>'
```

PONG 只证明连接与该命令可用。SCAN 按返回游标继续到 0，单页为空不代表不存在，COUNT 也不是精确返回数；需要统计时还要考虑重复元素及扫描期间的数据变化，见 [SCAN 说明](https://redis.io/docs/latest/commands/scan/)。

TTL 非负表示剩余秒数，-1 表示无过期时间，-2 表示 Key 不存在。查不到 Key 时先核对实例、DB、前缀、对象和过期时间；通过原业务入口验证变化，不清空共享库来验证缓存。

## 集成测试与迁移

先读目标模块的测试说明，确认隔离、连接权限和中断清理机制。若需直接在 T2 PostgreSQL/MySQL 执行写入、DDL 或多语句，先沿 `moe-t2-database` 完成对应分级确认和写后回读；不能用“迁移验证”绕过其执行规则。本地隔离测试按本仓机制处理，不因数据库引擎相同就改连 T2。已有事务回滚或测试容器方案时按本仓方法核验，不套另一服务的测试基类或独立库脚本。需要真实锁、DDL 或写入失败测试时，使用能隔离这些影响的测试库/环境；权限不足不能改成在共享业务表随意造数。

普通测试 PASS 可能包含因缺少连接而 SKIP 的集成用例，检查相关用例确实执行。远端时序测试以可观察的锁等待和数据库时间同步，避免依赖本机毫秒级 sleep；只清理本次创建的确切资源。

迁移验证覆盖本次需要的空库初始化或已有结构升级，再回读结构与应用结果：

- SQL 含 `库名.表名` 限定名时，改变 CLI 的 `--database` 不会重定向语句，先确认实际落点。
- `IF NOT EXISTS` 不能修正已有表结构差异，使用正式增量迁移。
- MySQL 部分 DDL 会隐式提交，不能承诺外层事务撤销整份迁移；以[隐式提交说明](https://dev.mysql.com/doc/refman/8.4/en/implicit-commit.html)和实际语句为准。
- 新镜像、迁移和业务结果分别验证；一个环境的成功不代表其他环境已完成。
