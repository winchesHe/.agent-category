# MoeGo Redshift Skill

面向 AI Agent、SDK host 和工程师的只读 Amazon Redshift 数据访问 Skill。

它提供一个稳定的 Python CLI，统一支持 Provisioned cluster、Serverless workgroup、
PostgreSQL Wire protocol 和 Redshift Data API。调用方不需要为不同 transport 维护两套
命令、SQL 参数或输出解析逻辑。

> 当前目录是 MoeGo Redshift Skill V2 源码。代码实现不等于某个真实 connection 已通过
> 安全认证；每个 connection 都需要单独
> `doctor --connect` 和 owner acceptance。

- Agent 使用说明：[`SKILL.md`](./SKILL.md)
- 架构与安全边界：[`ARCHITECTURE.md`](./ARCHITECTURE.md)
- Operator 与发布维护：[`MAINTENANCE.md`](./MAINTENANCE.md)
- Connection 示例：[`connections.example.json`](./connections.example.json)
- Redshift 方言与诊断：[`references/redshift-semantics.md`](./references/redshift-semantics.md)

## 功能特性

- **一个入口、九个命令**：`databases`、`schemas`、`relations`、`search`、`describe`、
  `query`、`explain`、`recipe`、`doctor`。
- **双 transport**：同一契约覆盖 Wire 和 Data API。
- **双 deployment**：明确区分 Provisioned cluster 与 Serverless workgroup。
- **Named connections**：显式选择 target、transport、auth、database 和 AWS identity；
  不从 SQL 或错误文本猜连接。
- **多种认证**：password、IAM temporary credentials、Provisioned Data API DbUser、
  Secrets Manager SecretArn。
- **纵深只读**：SQL guard、readonly session/transaction、数据库 readonly role。
- **Agent-safe errors**：schema-versioned JSON、稳定 code、retryClass 和恢复 action。
- **数据发现**：离线 catalog search、live database/schema/table/view inventory、SHOW-first
  describe。
- **有界输出**：JSON 行数和字节上限；CSV/NDJSON 使用 streaming artifact。
- **原子 artifact**：私有目录、`0600`、绝不覆盖、hard-link 发布、directory fsync。
- **安全恢复**：无自动 transport fallback、无 credential fallback、无 SQL 自动改写。
- **Data API lifecycle**：ClientToken、readonly session、absolute deadline、long polling、
  cancel/settlement、分页去重和 result-not-ready 恢复。

## 明确不做什么

- 不执行 `INSERT`、`UPDATE`、`DELETE`、DDL、COPY、UNLOAD、存储过程或多语句。
- 不提供 `--allow-write`。
- 不自动从 Wire 切到 Data API，也不反向切换。
- 不根据 database、DNS、错误文本或自然语言推断 connection。
- 不把 catalog 当成当前 principal 的授权证明。
- 不在公共输出中返回 SQL、参数值、endpoint、credential、SecretArn 或 statement ID。

## 支持矩阵

下表表示代码已实现的组合，不表示任意 AWS account 或 target 已通过 live certification。

| Deployment | Transport | Authentication | 配置要求 |
|---|---|---|---|
| Provisioned | Wire | Password | host、port、username/password env、CA |
| Provisioned | Wire | IAM | cluster identifier、AWS identity、CA；可选 explicit host |
| Provisioned | Wire | SecretArn | SecretArn env、AWS identity、CA；explicit host 时无需 cluster identifier |
| Serverless | Wire | Password | workgroup endpoint、username/password env、CA |
| Serverless | Wire | IAM | workgroup name、AWS identity、CA；可选 explicit host |
| Serverless | Wire | SecretArn | SecretArn env、AWS identity、CA；explicit host 时无需 workgroup name |
| Provisioned | Data API | IAM | cluster identifier、AWS identity |
| Provisioned | Data API | DbUser | cluster identifier、database user、AWS identity |
| Provisioned | Data API | SecretArn | cluster identifier、SecretArn env、AWS identity |
| Serverless | Data API | IAM | workgroup name、AWS identity |
| Serverless | Data API | SecretArn | workgroup name、SecretArn env、AWS identity |

Data API 不接受 raw database password。Serverless Data API 不接受 caller-specified
DbUser。无效组合会在网络访问前返回 `config.invalid_combination`。

## 如何选择 connection

选择分为配置和运行时两步：

1. Operator 在 `connections.json` 中定义 named connection。每个 connection 固定自己的
   deployment、transport、authentication、target 和 database。
2. Agent 或其他调用方在运行时只通过 `--connection NAME` 选择一个 named connection，
   不直接传 `--transport` 或 `--auth`。未传 `--connection` 时使用
   `defaultConnection`；它只是默认项，不是失败后的 fallback。

选择 transport 时使用以下规则：

- Host 无法访问 Redshift 5439，或希望使用 AWS IAM 且没有 Wire 专属需求时，优先配置
  Data API。
- Host 已有稳定的 Wire endpoint 或 gateway，并需要完整驱动参数语义、server-side cursor
  或 streaming artifact 时，配置 Wire。
- Data API 不接收 raw database password；调用方使用 IAM、DbUser 或 SecretArn。只有明确配置的
  Wire password connection 才从环境变量读取 raw username/password。
- 同一个 target 可以同时定义 Wire 和 Data API 两个 named connection。调用方必须选择其中
  一个；任一 connection 失败后，Skill 不会自动切换 transport、target 或 credential。

Provisioned / Serverless 不决定 transport。两种 deployment 都可以按实际网络、认证和查询
能力选择 Wire 或 Data API。

## 前置要求

先设置 Skill 的绝对路径。后续安装和 Quickstart 命令都使用该变量：

```bash
export SKILL_DIR="/absolute/path/to/redshift"
```

- Python 3.10 或更高版本。
- 所有 connection 使用只读数据库身份。
- Wire 需要 `psycopg2`。
- AWS-backed Wire 和 Data API 需要 `boto3>=1.43.55,<2`。
- Named Wire connection 需要 CA 文件，并强制 `sslmode=verify-full`。
- Artifact export 需要调用方创建任务私有 `0700` 目录。

推荐为 Skill 创建独立 venv。以下命令不修改 Homebrew 或系统 Python：

```bash
python3 -m venv "$SKILL_DIR/.venv"
source "$SKILL_DIR/.venv/bin/activate"
python -m pip install -r "$SKILL_DIR/requirements-data-api.txt"
```

Wire 还需要在同一 venv 安装 psycopg2：

```bash
python -m pip install psycopg2-binary
```

直接调用时先 activate 该 venv。长期运行的 Agent、SDK 或 process manager 必须把
`$SKILL_DIR/.venv/bin` 放在 process `PATH` 前面，确保后续 `python3` 使用同一 interpreter。
生产 host 也可以提供自己的 Python environment 和 `psycopg2` 构建。Skill 不在运行时安装依赖。

## 推荐配置结构

每个 Skill checkout 在根目录维护自己的 operator config：

```text
redshift/
├── .env                        # 0600；credential、CA/output 路径；Git ignored
├── connections.json            # 0600；target、transport、auth；Git ignored
├── .env.example                # 可提交模板
└── connections.example.json    # 可提交模板
```

`.gitignore` 必须同时忽略 `.env` 和 `connections.json`。Git pull 会保留已存在的 ignored
文件，但 Git clone 不会下载它们。新 host 首次 clone 后，operator 必须从两个 example
文件创建本机配置。禁止通过 Git 提交或分发真实配置。

默认情况下，Skill 自动读取根目录 `.env`，host 不需要设置 `RS_DOTENV`。只有 host 必须
集中管理 dotenv 时，才使用 `RS_DOTENV` 覆盖 Skill-local `.env`：

| Host | 可选的 `RS_DOTENV` 配置入口 |
|---|---|
| 单次 CLI | 放在本次命令前，例如 `RS_DOTENV=/absolute/path/redshift.env python3 ...` |
| macOS 用户 shell | `~/.zshenv`；修改后启动新 shell |
| Agent workspace runtime | workspace 的 host-local env 文件；重启 runtime 后生效 |
| launchd | plist 的 `EnvironmentVariables` |
| Container / SDK host | workload 的 environment 或 secret injection 配置 |

`RS_DOTENV` 必须是绝对路径。被指向的 dotenv 不能通过自身设置 `RS_DOTENV`。dotenv
value 不执行 shell expansion，不能用 `~` 或 `$HOME` 代替绝对路径。

加载优先级是 process environment → `RS_DOTENV` 指定文件 → Skill 根目录 `.env`。
已有 process environment 不会被 dotenv 覆盖。Skill 不读取调用方当前目录的 `.env`。

Skill 根目录 `.env` 和 `RS_DOTENV` 指定文件都必须是当前用户拥有的普通 `0600`
文件，不能是 symlink。文件路径必须是绝对路径；各级父目录只能归 root 或当前用户
所有，且不能允许 group/other 写入。任一条件不满足时，Skill 返回 `config.invalid`。

CA 文件可以由 host 或操作系统统一维护，不要求放进 Skill。输出目录也不放进 Skill；
host 应创建独立的 `0700` 任务目录或用户私有目录。

## Quickstart

### 1. 验证入口

```bash
python3 "$SKILL_DIR/scripts/redshift.py" --help
```

兼容 Agent Skills 的 host 应把整个目录注册为名为 `redshift` 的 Skill。直接调用 CLI
不依赖某个 Agent runtime。

### 2. 创建 Skill-local operator config

从模板创建两个 ignored 文件：

```bash
cp "$SKILL_DIR/connections.example.json" \
  "$SKILL_DIR/connections.json"
cp "$SKILL_DIR/.env.example" \
  "$SKILL_DIR/.env"
chmod 600 \
  "$SKILL_DIR/connections.json" \
  "$SKILL_DIR/.env"
```

使用本地编辑器填写两个文件。不要在 shell history 中输入 password 或 SecretArn。
`.env` 只设置 connections.json 实际引用的 credential 和可选 output path：

```dotenv
# 只填写 connections.json 实际引用的 credential env key：
WAREHOUSE_USER=
WAREHOUSE_PASSWORD=

# Named Wire 才需要：
WAREHOUSE_CA=/absolute/path/to/ca-bundle.pem

# 仅 CSV/NDJSON artifact export 需要：
REDSHIFT_OUTPUT_DIR=/absolute/path/to/private-output-directory
```

上述变量与 `connections.example.json` 一一对应。使用其他 authentication mode 时，
按实际 registry 中的 `*Env` 引用向本机 `.env` 增加同名变量。不要把未引用的 secret
占位符复制进 `.env`。

完成后直接验证。Skill 会自动读取根目录 `.env`：

```bash
python3 "$SKILL_DIR/scripts/redshift.py" doctor \
  --list-connections --format json
```

一个最小的 Serverless Data API IAM connection：

```json
{
  "schemaVersion": 1,
  "defaultConnection": "analytics-api",
  "connections": {
    "analytics-api": {
      "deployment": "serverless",
      "transport": "data_api",
      "database": "dev",
      "target": {
        "region": "us-west-2",
        "workgroupName": "example-workgroup"
      },
      "authentication": {
        "mode": "iam"
      },
      "awsCredentials": {
        "source": "profile",
        "profile": "example-readonly",
        "expectedAccountId": "123456789012"
      }
    }
  }
}
```

Registry 只能保存 target 和环境变量名称，不能保存 password、SecretArn value、AWS key、
token 或 CA 内容。文件必须是当前用户拥有的普通 `0600` 文件；symlink、不安全 parent、
错误 owner/mode 和超大文件都会被拒绝。

### 3. 检查连接

先离线列出配置，不创建 Adapter，也不访问网络：

```bash
python3 "$SKILL_DIR/scripts/redshift.py" doctor \
  --list-connections --format json
```

选择 connection 后执行 live readonly preflight：

```bash
export CONNECTION_NAME="analytics-api"
python3 "$SKILL_DIR/scripts/redshift.py" doctor \
  --connection "$CONNECTION_NAME" --connect --format json
```

只有 `skillAvailable=true` 且 readonly check 通过，才能把该 connection 用于查询。

连接失败时可给同一条 doctor 命令加 `--debug`。stderr 只输出白名单诊断：
失败阶段、驱动类型、驱动明确提供的 SQLSTATE 和固定连接错误短语的布尔匹配信号；
stdout 保持原有能力报告。不输出原始异常、端点或凭据；未匹配到密码拒绝信号不证明密码正确。

### 4. 执行第一条查询

```bash
python3 "$SKILL_DIR/scripts/redshift.py" query \
  --connection "$CONNECTION_NAME" \
  --sql 'SELECT 1 AS smoke_value' \
  --limit 1 --format json
```

## 配置

### Named connection registry

顶层字段：

| 字段 | 含义 |
|---|---|
| `schemaVersion` | 当前固定为 `1` |
| `defaultConnection` | 未传 `--connection` 时使用的 name |
| `catalogConnection` | 可选；拥有 Catalog V1 enrichment 的 connection |
| `connections` | connection name 到 profile 的映射 |

每个 profile 显式声明：

- `deployment`: `provisioned` 或 `serverless`
- `transport`: `wire` 或 `data_api`
- `database`
- `target`
- `authentication`
- AWS-backed 模式使用 `awsCredentials`
- Wire 使用 `tls`
- 可选 timeout/keepalive 设置

常用组合：

| Transport | Deployment | `authentication.mode` | 必填 target / 配置 |
|---|---|---|---|
| Data API | Provisioned | `iam` | `region`、`clusterIdentifier`、`awsCredentials` |
| Data API | Provisioned | `iam_db_user` | 上述字段，加 `dbUser` |
| Data API | Provisioned / Serverless | `secret` | cluster/workgroup target、`awsCredentials`、`secretArnEnv` |
| Data API | Serverless | `iam` | `region`、`workgroupName`、`awsCredentials` |
| Wire | Provisioned / Serverless | `password` | 显式 `host`、username/password env、`tls`；不配置 `awsCredentials` |
| Wire | Provisioned / Serverless | `iam` | cluster/workgroup target、`awsCredentials`、`tls` |
| Wire | Provisioned / Serverless | `secret` | 显式 host 或 cluster/workgroup target、`awsCredentials`、`secretArnEnv`、`tls` |

`iam_db_user` 只适用于 Provisioned Data API。Data API 禁止 `host` 和 `tls`；所有 Wire
connection 都必须配置 `tls`。完整基础示例见
[`connections.example.json`](./connections.example.json)。Skill 默认读取根目录
`connections.json`。只有集中管理配置的 host 才设置 `REDSHIFT_CONNECTIONS_FILE`
覆盖默认路径。Live command 找不到最终 registry 时返回 `config.missing`。

### AWS identity

AWS-backed connection 支持：

```json
{
  "source": "default",
  "expectedAccountId": "123456789012"
}
```

或 named profile：

```json
{
  "source": "profile",
  "profile": "example-readonly",
  "expectedAccountId": "123456789012"
}
```

`expectedAccountId` 是必填的 identity guard。还可以配置精确的
`expectedPrincipalArn`。Identity 不匹配时，Skill 在访问 target 或 secret 前失败。

### Provisioned Data API + IAM DbUser

将以下 profile 放入 `connections.json` 的 `connections` object：

```json
{
  "deployment": "provisioned",
  "transport": "data_api",
  "database": "dev",
  "target": {
    "region": "us-west-2",
    "clusterIdentifier": "example-cluster"
  },
  "authentication": {
    "mode": "iam_db_user",
    "dbUser": "readonly_user"
  },
  "awsCredentials": {
    "source": "profile",
    "profile": "example-readonly",
    "expectedAccountId": "123456789012"
  }
}
```

### Provisioned Wire + IAM

```json
{
  "deployment": "provisioned",
  "transport": "wire",
  "database": "dev",
  "target": {
    "region": "us-west-2",
    "clusterIdentifier": "example-cluster"
  },
  "authentication": {
    "mode": "iam"
  },
  "awsCredentials": {
    "source": "profile",
    "profile": "example-readonly",
    "expectedAccountId": "123456789012"
  },
  "tls": {
    "mode": "verify-full",
    "trust": {
      "source": "file",
      "pathEnv": "WAREHOUSE_CA"
    }
  }
}
```

### SecretArn

Registry 只保存 SecretArn 所在的环境变量名称：

```json
{
  "authentication": {
    "mode": "secret",
    "secretArnEnv": "WAREHOUSE_SECRET_ARN"
  }
}
```

实际 ARN 由 SRE 或 host secret store 在启动进程时注入。README、shell history 和
connection registry 都不负责保存该值。启动前只检查变量是否存在：

```bash
: "${WAREHOUSE_SECRET_ARN:?host must inject WAREHOUSE_SECRET_ARN}"
```

不要把 secret value 写入 registry、`.env.example`、命令参数、日志或报告。Wire secret
通过 Secrets Manager 取得 username/password；Data API 把 SecretArn 交给 AWS 服务。

### Serverless Data API + SecretArn

将以下 profile 放入 `connections.json` 的 `connections` object：

```json
{
  "deployment": "serverless",
  "transport": "data_api",
  "database": "dev",
  "target": {
    "region": "us-west-2",
    "workgroupName": "example-workgroup"
  },
  "authentication": {
    "mode": "secret",
    "secretArnEnv": "WAREHOUSE_SECRET_ARN"
  },
  "awsCredentials": {
    "source": "profile",
    "profile": "example-readonly",
    "expectedAccountId": "123456789012"
  }
}
```

只有 registry 引用该 key 时，才在本机 `.env` 增加 `WAREHOUSE_SECRET_ARN`。Wire
SecretArn 使用相同 authentication block，同时增加 Wire target 和 `tls`。

### Wire TLS

Named Wire connection 只接受：

```json
{
  "tls": {
    "mode": "verify-full",
    "trust": {
      "source": "file",
      "pathEnv": "WAREHOUSE_CA"
    }
  }
}
```

CA 文件路径通过环境变量注入。文件及父目录必须满足 owner、mode、regular file、大小和
no-symlink 规则。Skill 不提供降低 TLS 校验的 fallback。

macOS 直接使用系统 CA bundle，不需要复制文件：

```dotenv
WAREHOUSE_CA=/etc/ssl/cert.pem
```

macOS 的 `/etc` 是系统 symlink。Skill 只对 Apple 提供的这个精确 CA 路径使用 canonical
file；其他 symlink 路径仍然拒绝。其他操作系统应配置该 host 维护的可信 CA bundle
canonical path；不需要为 Skill 创建副本，也禁止从不明 URL 下载证书。配置后先运行
离线 doctor，再运行 `doctor --connection NAME --connect`。

代理合成 DNS、gateway 或 split-tunnel 环境必须独立验证连接地址和证书 hostname。
TCP 可达不能替代 `verify-full` 成功。

### Artifact output directory

JSON query 不需要 output directory。CSV/NDJSON 需要调用方先创建私有目录：

```bash
install -d -m 700 "$HOME/.local/share/moego-redshift/task-output"
export REDSHIFT_OUTPUT_DIR="$HOME/.local/share/moego-redshift/task-output"
```

Skill 只返回相对 `outputRef`。调用方消费完成后负责删除敏感 artifact。

## 使用

### 数据库与对象发现

```bash
# Live database inventory
python3 "$SKILL_DIR/scripts/redshift.py" databases \
  --connection "$CONNECTION_NAME" --format json

# Offline catalog search
python3 "$SKILL_DIR/scripts/redshift.py" search payment \
  --domain payment --limit 20 --format json

# Live metadata
python3 "$SKILL_DIR/scripts/redshift.py" schemas \
  example_db --connection "$CONNECTION_NAME" --format json

python3 "$SKILL_DIR/scripts/redshift.py" relations \
  example_db.public --connection "$CONNECTION_NAME" \
  --kind all --format json

python3 "$SKILL_DIR/scripts/redshift.py" describe \
  example_db.public.example_table \
  --connection "$CONNECTION_NAME" --format json
```

`schemas` 和 `relations` 使用选定 connection 的当前 principal 执行 Redshift `SHOW`，结果
只对本次 invocation 成立。`schemas` 默认隐藏 `information_schema`、`pg_catalog` 和
`pg_internal`，加 `--include-system` 才显示。`relations --kind` 支持 `table`、`view`
和 `all`。两个 command 默认最多返回 200 行，最大 10,000 行；`truncated=true` 表示
结果超过 caller limit。空结果表示当前 principal 没有可见对象，不表示其他 principal
也没有对象。

Catalog builder 按 database 采集 metadata。SHOW database/schema 的上限是 10,000 行，SVV
relation/column 的上限是 100,000 行。Builder 会读取第 N+1 行确认是否超限；超限的 database
记录 `metadata.limit_exceeded` 并标记 coverage incomplete。SHOW DATABASES 超限时不会发布
不完整的新 Catalog，旧文件保持不变。

Offline catalog 是 discovery artifact，不是 live authorization。Data Team 必须批准 catalog
的 relation/column audience；最终结论使用 live `schemas`、`relations`、`describe` 或
`query` 验证。Live metadata 不读取或修改本地 Catalog。

### 参数化查询

```bash
python3 "$SKILL_DIR/scripts/redshift.py" query \
  --connection "$CONNECTION_NAME" \
  --database example_db \
  --sql 'SELECT id, status FROM example_db.public.example_table WHERE id = %(id)s' \
  --params '{"id":123}' \
  --limit 20 --format json
```

参数必须是 JSON object。SQL 使用 psycopg named placeholder：`%(name)s`。

Wire 与 Data API 都支持完整 `IN/NOT IN` RHS：

```sql
WHERE id IN %(ids)s
```

```json
{"ids":[1,2,3]}
```

Wire 继续支持已有的 array 语义，例如 `id = ANY(%(ids)s)`。Data API 对没有等价语义的
array context 返回 `capability.parameter_shape_unavailable`。

### EXPLAIN

```bash
python3 "$SKILL_DIR/scripts/redshift.py" explain \
  --connection "$CONNECTION_NAME" \
  --database example_db \
  --file /absolute/private/path/query.sql \
  --format json
```

`plan` 是 Redshift 返回值。`advisories` 只是本地辅助提示；空 advisories 不表示查询一定
安全或高效。

### CSV/NDJSON export

```bash
python3 "$SKILL_DIR/scripts/redshift.py" query \
  --connection "$CONNECTION_NAME" \
  --sql 'SELECT id FROM example_db.public.example_table ORDER BY id' \
  --limit 1000 \
  --format ndjson \
  --output example-results.ndjson
```

- JSON：最多 200 行，完整 stdout envelope 最多 64 KiB。
- CSV/NDJSON：最多 100,000 行，artifact 最多 64 MiB。
- Artifact filename 必须是一个非隐藏 final name，不能含路径。
- 已存在的 final 不会被覆盖。

### Maintained recipes

```bash
python3 "$SKILL_DIR/scripts/redshift.py" recipe list --format json
```

执行 recipe 时，Skill 先检查所选 connection 是否能看到 recipe 所需 database。不可见时
返回 `capability.recipe_source_unavailable`，不会切换 connection 或伪装成空结果。

## 输出契约

所有 caught outcome 都在 stdout 输出一条 schema version 1 JSON。

成功：

```json
{
  "schemaVersion": 1,
  "ok": true,
  "command": "query",
  "data": {},
  "meta": {}
}
```

失败：

```json
{
  "schemaVersion": 1,
  "ok": false,
  "command": "query",
  "error": {
    "category": "query",
    "code": "permission_denied",
    "retryClass": "never",
    "suggestion": "request_data_access"
  }
}
```

常见恢复 owner：

| Error | Action | Owner |
|---|---|---|
| `query.permission_denied` / `metadata.permission_denied` | `request_data_access` | Data Team |
| `metadata.failed` | `inspect_provider_failure` | Operator / SRE |
| `connection.permission_denied` | `request_platform_access` | SRE |
| `connection.auth_interaction_required` | `refresh_aws_auth` | Operator/SRE |
| `capability.recipe_source_unavailable` | `select_connection` | Operator/Data Team |
| `output.inline_size_limit_exceeded` | `use_artifact` | Caller |
| `query.submission_unknown` | 不自动重提 | Operator/SRE |

完整恢复表见 [`SKILL.md`](./SKILL.md)。

## 安全模型

- 所有 SQL 经过共享 readonly guard。
- Wire 使用 readonly session；streaming artifact 使用 readonly transaction 并 rollback。
- Data API 在同一 session 内执行 `BEGIN READ ONLY`、timeout 设置和 readonly probe。
- Data API 每个 phase 使用独立 ClientToken；未知提交状态不重提 SQL。
- Execute、Describe、Cancel settlement 和所有 result page 使用有界 deadline。
- Data API result 可以在 provider 保留最多 24 小时；statement ID 和 result 都是敏感数据。
- CloudTrail 记录 Data API 调用，不记录完整 SQL；SQL 审计由 SRE 配置 Redshift audit
  logging。
- Catalog audience、database user 和 object grants 由 Data Team 管理。
- IAM、Secrets Manager、network/TLS、owner policy 和 audit destination 由 SRE 管理。

功能 smoke 只验证当前请求路径。安全与权限验证由对应的 SRE、Data Team 和 Operator
流程负责，不改变 Skill 的 capability contract。

## 已知边界

- Serverless/T2 Wire 在代理 DNS 或 gateway 环境中必须逐 target 验证 `verify-full`。
- Skill 当前不自动分离 connect address 与 certificate hostname。
- SecretArn 代码实现需要 Operator 提供专用只读 secret 才能完成 live certification。
- Serverless recipe 是否可用取决于目标 workgroup 能看到哪些 database。
- 离线 catalog 可能保留权限撤销前的 metadata；分发范围必须由 Data Team 批准。
- Candidate、unit test 或 mock 只能证明实现，不能替代真实 IAM、network 和 DB grants。

## 架构

```text
Agent / SDK host / engineer
          |
          v
scripts/redshift.py
          |
          v
CLI contract -> Application -> RedshiftConnectivity
                                |              |
                                v              v
                           WireAdapter    DataApiAdapter
                                |
          +---------------------+--------------------+
          |                     |                    |
          v                     v                    v
     live metadata         local catalog       maintained recipes
```

`scripts/rs/contract.py` 是命令 grammar 的唯一事实来源。Connection schema 由
`scripts/rs/connectivity/registry.py` 维护。设计详情见 [`ARCHITECTURE.md`](./ARCHITECTURE.md)。

## 开发与验证

```bash
python3 -m pip install pytest
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
python3 scripts/generate_contract_cases.py
python3 scripts/run_contract_replay.py \
  --candidate-dir <source-copy-without-operator-config> \
  --fixtures tests/fixtures/contract-cases.json \
  --output /tmp/moe-redshift-v2-contract.json
```

验证层级：

- Unit/contract tests：parser、guard、registry、Wire/Data API lifecycle、artifact、安全失败。
- Contract replay：CLI exit code 和 typed envelope；不访问网络。
- Live acceptance：每个 exact connection、auth、network 和 principal 单独认证。

修改前先读 [`AGENTS.md`](./AGENTS.md)。发布、catalog build、live smoke 和固定点流程见
[`MAINTENANCE.md`](./MAINTENANCE.md)。

## 目录结构

```text
redshift/
├── SKILL.md                    # Agent instructions
├── README.md                   # Human quickstart
├── ARCHITECTURE.md             # Design and invariants
├── MAINTENANCE.md              # Operator and release workflow
├── connections.example.json    # Named connection example
├── requirements-data-api.txt   # Optional Data API dependency
├── agents/openai.yaml          # OpenAI/Codex metadata
├── scripts/
│   ├── redshift.py             # Public CLI
│   ├── build_catalog.py        # Catalog builder
│   └── rs/                     # Internal modules
├── references/                 # Domain, catalog and Redshift knowledge
├── tests/                      # Unit and contract tests
└── evals/                      # Deterministic CLI replay
```
