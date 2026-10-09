# Redshift Skill 维护指南

本文件面向 maintainer。公开行为写入 `SKILL.md`；parser grammar 只由
`scripts/rs/contract.py` 维护。

## 源码与配置

本目录是 Skill 实现真源。只维护一个 active command contract 和一个 catalog artifact。
不要增加 alias、deprecated 双轨或平行 dispatch path。

Active checkout 可以包含 Skill-local `.env` 和 `connections.json`。两者由 operator 管理并被
Git ignore。禁止把两者复制到源码包、fixture、eval input、report、archive 或 review digest。

测试会清除继承的 `REDSHIFT_*` 和 `RS_*`，避免缺失 fake 时访问 live database。经明确授权的
live 验证可以使用 Skill-local 配置或 host process env。`RS_DOTENV` 仅用于集中管理场景。

显式 `RS_DOTENV` 必须是绝对路径。文件必须归当前用户所有、mode `0600`、regular file、
不超过 256 KiB。Parent 必须由 root 或当前用户拥有，且不能 group/other writable；拒绝 symlink。
离线 `search` 和 `recipe list` 不读取 dotenv。

把 `connections.example.json` 复制为 Skill-root `connections.json`，mode 设为 `0600`。Skill 默认
读取该文件；`REDSHIFT_CONNECTIONS_FILE` 仅用于 host 显式 override。Registry 只保存非 secret
target 和 env key name。Password、SecretArn value、AWS key、SSO cache 与 CA content 不进 JSON。

新 connection 优先 IAM、temporary DbUser 或 Secrets Manager。Password mode 只用于明确配置的
named connection。Named Wire 必须使用私有 CA 和 `verify-full`。

Wire 需要 psycopg2。AWS-backed Wire 和 Data API 还需要
`requirements-data-api.txt` 中的 `boto3>=1.43.55,<2`。Boto3 1.43.55 对应的 botocore service
model 开始为 Execute/Describe/GetResult 提供 `WaitTimeSeconds`。不得降低该 floor。Skill 运行时
不安装依赖；host 负责安装，`doctor` 只报告可用性。

Data API IAM policy 必须用以下 condition 限制 statement 和 session ownership：

- `redshift-data:statement-owner-iam-userid=${aws:userid}`
- `redshift-data:session-owner-iam-userid=${aws:userid}`

成功 query 不能证明 deployed IAM policy 正确。Live acceptance 必须单独回读 policy。

## 本地确定性验证

从 Skill root 执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
python3 scripts/generate_contract_cases.py
python3 scripts/run_contract_replay.py \
  --candidate-dir <source-copy-without-operator-config> \
  --fixtures tests/fixtures/contract-cases.json
```

测试失败、新 skip 或 coverage 删除都必须解释。固定测试数量不能代替行为验证。

必要 fault matrix：

- parser attribution、leaf option scope、format/output 配对和 exit code；
- LF/CRLF/bare-CR guard、readonly doctor、parameter mismatch、limit+1 和 duplicate column；
- catalog malformed line、quoted identifier、enum、version/count/order/coverage/freshness；
- artifact write/fsync/link/unlink/directory-fsync、EEXIST、post-link failure 和 signal；
- 64 MiB UTF-8 cap、64-row fetch batch、禁止 artifact 主路径 `fetchall()`；
- stdout/stderr/diagnostic/report redaction；
- named registry schema、duplicate key、owner/mode/size、parent 与 final symlink；
- registry 必填、全部 V2 transport/auth 组合和无 fallback；
- connection inventory 不创建 Adapter 或网络请求；
- 64 KiB inline envelope、artifact separation 和稳定 action code；
- recipe 首条 SQL 前只读取一次 database inventory；
- Wire CA、IAM/secret resolution、expected AWS identity 和 transaction parity；
- Data API phase ordering、ClientToken、session identity、readonly proof、deadline、cancel/settlement、
  `HasResultSet`、pagination、重复 token、result-not-ready 和 value decoding；
- metadata source 的 N+1 bounded read、SHOW interactive truncation、Catalog overflow 和旧 snapshot 保留；
- 每个 Data API logical operation 只用一个 absolute deadline；
- HTTP 400 throttling 仍分类为 transient AWS condition。

## Error taxonomy 升级条件

只有同时满足以下条件，才能把未分类 database failure 升级为公共 typed error：

1. Driver 提供合法 SQLSTATE，不解析 raw message；
2. SQLSTATE 有权威语义；
3. 至少两个独立 live probe 稳定复现；安全缺陷除外；
4. 可以定义无歧义 retry class 和 recovery action；
5. 先补 public-seam failure test；
6. 用相同 live probe 验证修改前后，确认 public payload 不泄漏 SQLSTATE。

单样本保留为 `internal.unexpected`，细节只进 private diagnostics。Parser/planner probe 优先使用
live EXPLAIN，不为分类错误重放昂贵历史 query。

Wire 连接排查可以使用 `doctor --connection NAME --connect --debug`，不得换 connection、
TLS 模式或凭据来源。固定客户端短语信号只用于本机诊断，不新增公共错误类别；
测试需覆盖默认 stderr 静默、凭据内容不能触发信号、诊断跨 wrapper 传播和无 SQLSTATE 的失败。

## Catalog build

Builder 需要 live metadata 和可选 maintained enrichment，并且必须先确认完整 visible database
universe。标准命令：

```bash
python3 scripts/build_catalog.py \
  --output references/catalog.jsonl \
  --domain-map references/moego-domain-map.json
```

Builder 在内存中完成构建与校验，再同目录写 temp、flush、fsync、replace 和 parent fsync。
Replace 前失败不能影响旧 catalog。验证以下 invariant：

- 第一行是唯一 meta，schema version 为 1，`generatedAt` 是 UTC；
- relation object 唯一并确定性排序；
- relation/column/database count 一致；
- coverage universe 与有 relation database、complete-empty database 和失败项一致；
- expected live 的 domain map entry 均存在或有说明；
- freshness 由 loader 动态计算，不写入 artifact。

## Live smoke

Live smoke 必须得到明确授权，并且只走公共 CLI。使用新写、无个人信息、有界 SQL。覆盖 warehouse、
MySQL/PostgreSQL replica、metadata 和 artifact export。Artifact case 应超过 64 行，验证真实 fetch batch。

V2 Core 的每种已声明组合都需要独立 live evidence：Provisioned/Serverless、Wire/Data API、
password/IAM/secret、Provisioned DbUser、named AWS profile、blocked Wire、expired credential、
permission denial、cancel/timeout、pagination、metadata 和 artifact parity。

Data API 还必须证明：用户 statement 完成并 rollback session 后，result 仍可读取。该 probe 失败时，
不得为 query 或 artifact 启用 Data API。

Statement/session ID 和 provider result page 是敏感数据。CloudTrail 只记录 API call；完整 SQL audit
依赖 Redshift audit logging。验证记录只保存 typed outcome，不保存 SQL、参数、结果、raw error、
credential、endpoint 或 host task metadata。

## Query pattern 升级与降级

Pattern 初始状态为 `needs_review`。只有满足以下条件才可改为 `verified`：

- 所有对象和列通过当前 live metadata；
- 有界 SQL 在选定 connection database 通过 Redshift EXPLAIN；
- status、soft-delete、namespace、amount unit 和 generation 语义有维护来源或授权 live 证据；
- 文档记录 `lastVerifiedAt` 与最小证据。

Metadata drift 时立即降级或删除 pattern。旧 guide 中已证实错误的
`package_service.service_name` 与 order `created_at` 禁止恢复，除非出现新证据。

## Query artifact 运维

Host 创建 mode `0700` 的任务私有 output directory。CLI 只创建 caller 指定的 `0600` 文件，
绝不覆盖。Caller 消费后删除 artifact。Skill 不提供 TTL、后台 cleanup 或 cleanup command。

CSV/NDJSON 使用 readonly transaction 和 named server-side cursor。Client streaming 与 64 MiB cap
不能降低 Redshift leader node 的查询成本。宽表和复杂 JOIN 仍需缩小列、加外层 limit 并先 EXPLAIN。
`UNLOAD` 不属于本只读契约。

Operator-managed Redshift role 必须拒绝未批准 UDF、Lambda UDF 和外部函数的 `EXECUTE`。
`output.publish_unknown` 表示 final 可能存在，禁止自动重复导出。

## 仓库级验证

Skill-local gate 通过后，在个人 skills 仓库根目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider redshift/tests
python3 redshift/scripts/generate_contract_cases.py
python3 redshift/scripts/run_contract_replay.py \
  --candidate-dir /absolute/path/to/clean-redshift-candidate \
  --fixtures redshift/tests/fixtures/contract-cases.json
git diff --check
```

提交前检查完整 diff、Skill semver、根 Skill 路径、Skill-local catalog 和 ignored operator config。未经明确授权，
不 commit、不 push、不创建 PR。
