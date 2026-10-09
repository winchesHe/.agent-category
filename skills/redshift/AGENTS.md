# Redshift Skill 维护宪法

本文件面向维护此 Skill 的 Agent。它记录长期成立的设计原则、权衡和迭代方法，
不承担用户使用说明，不保存某个调用方、运行时、消息平台、账号或一次性调查记录。

## 定位与边界

- 将本 Skill 维护为 MoeGo 内部通用、只读、runtime-neutral 的 Redshift 数据访问能力。
- 保持 Agent、SDK host 和工程师使用同一 CLI contract；不得引入调用方专属分支。
- 只解决 Redshift 数据发现、live metadata、只读查询、EXPLAIN、受控导出和维护过的
  recipe。代码搜索、日志排查、写数据库和宿主 UI 不属于本 Skill。
- 此目录是实现真源。消费目录必须通过父仓库的 symlink 分发机制获得；不得修改派生副本。
- `.env` 和 `connections.json` 是 Skill-local、operator-managed 配置。两者位于 Skill
  根目录并由 Git ignore；它们不是源码、fixture、candidate 或报告资产。Git pull 会保留
  已有文件，Git clone 不会分发它们。新 host 必须从 example 单独 provision。

## 真相源

修改前按职责读取，不把同一事实维护两份：

| 内容 | 真相源 |
|---|---|
| Agent 触发条件、标准工作流、公开恢复方式 | `SKILL.md` |
| 命令、参数位置、格式和 canonical grammar | `scripts/rs/contract.py` |
| Named connection schema、组合和安全校验 | `scripts/rs/connectivity/registry.py` |
| Wire/Data API lifecycle 和 Adapter parity | `scripts/rs/connectivity/` |
| 分层、只读边界、输出和 artifact 语义 | `ARCHITECTURE.md` |
| 构建、live smoke、验证与发布维护流程 | `MAINTENANCE.md` |
| 业务 source 路由 | `references/domain-routing.md` |
| 已验证查询起点 | `references/query-patterns.md` |
| Redshift 方言、system view 与 Data API provider 语义 | `references/redshift-semantics.md` |
| 领域 enrichment | `references/moego-domain-map.json` |
| 可搜索 catalog | `references/catalog.jsonl`，只由 builder 生成 |

parser grammar 只能来自 `CommandSpec`。禁止在文档、测试或另一套 parser 中手工维护
平行命令定义。

## 核心设计原则

### 单一、稳定的公共契约

- 只保留一个入口 `scripts/redshift.py` 和九个公开 command。
- 不增加旧命令 alias、deprecated 双轨或隐藏 fallback。需要改变公开语义时，先确认外部
  contract 影响，再一次性更新代码、文档、fixtures 和测试。
- stdout 对 caught outcome 始终输出一个 schema-versioned JSON envelope。错误判断只依赖
  `category`、`code`、`retryClass`、稳定的 `suggestion` 和白名单 `details`。
- 面向 Agent 的友好性来自可执行 action code，而不是自然语言错误段落。不要在 CLI 内
  写死语言、产品名或交互文案。
- Application 只持有一个 `RedshiftConnectivity` dependency。Wire 和 Data API 是该
  Module 的内部 Adapter；禁止重新增加 query/explain/metadata 的平行注入路径。

### 只读是纵深防御

- 所有 SQL 必须经过同一 readonly guard；禁止提供 `allow-write` 逃生口。
- 普通查询使用 readonly session；server-side cursor 使用 readonly transaction 并 rollback。
- statement timeout、结果行数和 artifact 字节数必须有硬上限。
- lexer 只证明 statement shape，不能证明任意 UDF 没有外部副作用。数据库 role 必须作为
  第二道边界，拒绝未批准的外部函数执行权限。
- 任何便利性都不能通过降低 readonly、扩大权限或绕过 guard 获得。
- Wire 普通查询保留 readonly autocommit session；artifact 使用 readonly transaction。
- Data API 必须先建立同一 provider session 的 readonly transaction、timeout 和 readonly probe，
  再提交用户 SQL。用户 SQL 未到确定终态时禁止 rollback 或重提。

### 明确路由，不猜数据库

- `--database` 只选择本次连接库，不做业务路由，也不修改进程环境。
- SQL 使用完整三段式对象名。不得从 SQL 或自然语言自动推断 connection database。
- `search` 用于离线发现，`databases`、`schemas`、`relations` 和 `describe` 用于 live
  metadata。catalog enrichment 不能冒充 live schema；不完整 coverage 必须显式传播。
- 新旧业务模型的选择写入 domain reference 或显式 recipe，不藏在通用 query fallback 中。
- `--connection` / `defaultConnection` 是唯一 transport 和 target 选择入口。禁止根据 SQL、
  database、DNS、异常或网络状态切换 connection、transport 或 credential source。
- Offline `search` 和 `recipe list` 不解析 connection；Catalog V1 只属于
  `catalogConnection`。

### 有界资源与原子 artifact

- JSON 结果保持 eager、可重复访问且严格有界；artifact 使用独立 streaming 路径，不把
  `QueryResult.records` 改成通用 iterable 或 union。
- server-side cursor 降低客户端结果复制，不代表 Redshift leader node 不会物化结果。
  大表、宽列或复杂 JOIN 仍应先 EXPLAIN。
- artifact 发布坚持私有目录、0600 文件、绝不覆盖、同文件系统 hard link 和 directory
  fsync。平台不支持时明确失败，不做非原子 fallback。
- final link 创建后绝不删除 final；durability 不确定时返回 `output.publish_unknown`。

### 公共错误与私有诊断分离

- 公共 envelope 禁止包含原始异常、SQL、参数值、endpoint、credential 或可能含 PII 的文本。
- `details` 只接受经过类型、长度和控制字符校验的结构化字段。
- SQLSTATE 只进入显式 `--debug` 的 allowlisted diagnostic，不进入公共 error payload。
- error wrapper 必须保留私有 diagnostics；新增 wrapper 时同时补端到端传播测试。
- 不从异常 message 正则解析表名、列名、SQLSTATE 或修复建议。驱动没有提供结构化字段时，
  保持缺失，不猜测。

### Recipe 是显式产品化查询

- 只有高频、边界稳定、可有界执行、能清楚说明 source generation 的流程才进入 recipe。
- recipe 的每个阶段都必须使用共享 readonly executor，保留 stage failure 和 truncation。
- 不自动跨产品代际 fallback，不把空结果解释为应切换数据源。
- 新 recipe 必须同步 domain routing、query pattern、registry、CLI contract 和测试。

## 关键权衡

- 选择轻量 lexer 而不是完整 SQL parser：降低复杂度并保留原 SQL，但接受语义安全仍依赖
  readonly role。不要在没有真实失败证据时扩建 parser。
- 选择 typed error 而不是原始数据库文案：牺牲部分即时细节，换取隐私、稳定性和跨 host
  一致性；细节只进入受控 telemetry。
- 选择显式 action code 而不是自动改 SQL：避免错误修复、重复昂贵查询和静默改变用户意图。
- 选择 live `schemas`、`relations`、`describe` 加离线 `search`：兼顾 metadata 正确性与发现
  效率，不让 snapshot freshness 伪装成 live truth。
- 选择 POSIX 原子发布而不是跨平台 best-effort：第一版优先保证完整文件可见和绝不覆盖。
- 选择 EXPLAIN 做历史 SQL 的错误探针：验证真实 parser/planner 与错误映射，同时避免重放
  数据扫描。只有明确需要执行期证据且成本有界时才运行 query。

## Error taxonomy 迭代规则

新增 typed database error 前必须满足：

1. 从驱动取得合法 SQLSTATE，不解析原始 message；
2. 有标准 SQLSTATE 语义；
3. 至少两个独立 live probe 稳定复现，除非它是必须立即封堵的安全或公共 contract 缺陷；
4. 能定义明确、不会误导的 retry class 和恢复 action；
5. 先写 public-seam 失败测试，再实现 mapping；
6. 用相同 live probe 验证改前、改后，并确认 public payload 没有泄漏 SQLSTATE。

单样本 SQLSTATE 保持 `internal.unexpected`，只进入 private diagnostics。不要为了降低
`internal.unexpected` 数量而创造含义模糊的 error code。

## 修改方法

1. 先复现并建立证据链：报错点、上游参数形状、typed outcome、相关配置和 live 能力。
2. 区分 CLI contract bug、数据库 capability、metadata drift、业务路由错误和模型 SQL 错误。
3. 把测试写在公共 seam：CLI stdout/stderr、application result、filesystem artifact 或数据库
   adapter contract。避免直接测试私有 helper，除非 helper 本身就是稳定模块边界。
4. 按 red → green 做垂直切片；不要先批量编写假想测试。
5. 只做解决已证实问题的最小改动。新增依赖、公共抽象或跨模块 contract 前先说明理由。
6. 同步受影响的 `SKILL.md`、`ARCHITECTURE.md`、`MAINTENANCE.md` 和 generated report。
7. 检查完整 diff，保留父仓库中不属于本任务的用户改动。未经明确要求不 commit、不 push。

涉及 Data API 时，每个 vertical slice 还要验证 ClientToken、provider session identity、terminal state、
cancel/rollback ordering、NextToken 去重和 public redaction。Mock 只证明实现；没有 live
readback 的组合不能标记 supported。

## Live 验证纪律

- live 操作只使用 public CLI 和 readonly role；先运行 `doctor --connect` 确认 readonly。
- 使用新写、无个人信息、严格有界的 smoke SQL；需要重放 caller-owned 私有历史时，只在
  内存中处理，输出 hash 和 typed outcome，不保存 SQL、参数、结果或原始异常。
- parser/planner 错误优先用同 SQL 的 EXPLAIN；不要批量原样重跑可能昂贵的历史 query。
- 查询返回成功时也不得打印 records 作为验证日志，只记录 row count、truncated 和稳定 meta。
- live catalog rebuild、artifact 写入或其他外部状态操作需要单独确认范围和回滚方式。

## 验证门禁

从 Skill 根目录依次运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
python3 scripts/generate_contract_cases.py
python3 scripts/run_contract_replay.py \
  --candidate-dir <source-copy-without-operator-config> \
  --fixtures tests/fixtures/contract-cases.json \
  --output /tmp/moe-redshift-v2-contract.json
```

candidate 必须排除 `.env`、`connections.json`、cache 和 artifact。所有 Python 稳定后重新生成 contract report，
并核对 `candidateSha256` 等于当前源码 digest。

Skill-local 门禁通过后，在个人 skills 仓库根目录执行 `git diff --check`，并按
`MAINTENANCE.md` 记录当前离线测试与 contract replay 结果。本仓库没有公共插件仓库的
pnpm workspace，不调用其 catalog、validate 或网站测试命令。

测试数量是动态事实，不写入本文件。交付时报告实际结果、未执行的 live 层和剩余风险。

## 禁止事项

- 禁止把具体 Agent、SDK host、消息平台、用户历史或私有评测数据放进本 Skill。
- 禁止把 credential、`.env`、真实 SQL、参数、结果行或原始异常写入测试、报告和文档。
- 禁止手改 generated catalog、contract fixture 或 report 来迎合测试。
- 禁止用 `default=str`、静默字段规范化、自动数据库推断或不透明 fallback 掩盖不确定性。
- 禁止把 secret value 写进 connection JSON；只保存 env key 引用。Live command 必须通过
  named registry 解析 connection。
- 禁止因单个失败样本引入策略框架、自动修复器、通用审批流或新的抽象层。
