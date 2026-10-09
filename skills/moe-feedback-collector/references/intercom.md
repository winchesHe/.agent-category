# Intercom 采集与发布协议

## 数据源

- 存储：Datadog Actions Datastore。
- Datastore ID：`a56cf9ac-2d2d-4e72-b19a-f9f0107868aa`。
- 传输入口：`<datadog-skill>/scripts/datadog.py list-datastore-items`。
- Collector 不读取 Datadog `.env`，也不直接构造 Datadog HTTP 请求；凭据、host
  校验、重试和错误 envelope 全由 `datadog` skill 负责。

## 周期

默认周期是上一个完整自然周。显式周期必须恰好 7 天：

```bash
uv run --script scripts/moe_feedback_collector.py collect \
  --source intercom --mode period \
  --period-start 2026-08-17 --period-end 2026-08-23
```

起止日按 `Asia/Shanghai` 转成毫秒 Unix timestamp。查询是半开区间：

```text
conversation_created_at:>=<start_ms> AND conversation_created_at:<end_exclusive_ms>
```

返回行的 `conversation_created_at` 会再次在 Collector 内校验；越界或类型错误使整次
采集失败。

## 分页与完整性

- 正式模式只启动一次 Datadog CLI，显式传入
  `--all-pages --consistency-passes 2 --max-items 10000`。Datadog 在同一进程和 API
  client 内完成两轮全量扫描；Collector 不跨进程拼接分页结果。
- 只有 `meta.pagination.completion=complete`，且
  `verification.mode=converged-read / passes>=2 / matched=true` 时才能保存 run 和
  manifest。验证覆盖总数、schema、item ID 集合和每条完整内容，而不只比较计数。
- 达到安全上限、扫描内容变化、空页但 `hasMore=true`、终页总数不闭合或 response
  shape 异常都失败，整次重试。
- `probe` 只读首批 20 条，允许 `completion=partial`，用于验证权限和 schema。
- Collector 还会校验 schema v2、`command=list-datastore-items`、原始 Datadog
  envelope，以及 target 中的 datastore、周期 filter、无 sort 和字段投影；任何一项
  不符都视为错表或错查询。

## 字段合同

允许从 Datadog 投影：

```text
id, business_type, conversation_created_at, conversation_updated_at,
domain, enterprise, jira, leads_business_type, requirement, role,
sentiment, squad, stripe_plan, tier, type
```

其中 `requirement` 和 `conversation_created_at` 必须有效；其它分类字段允许为空。
落盘时转换为稳定 camelCase evidence。Datadog item id 只参与 SHA-256 稳定标识计算，
原值不进入 evidence、run、manifest 或 stdout。

## 隐私边界

以下字段禁止请求和落盘：

```text
email, conversation_id, quote
```

Datadog 即使意外返回其中任一字段，Collector 也必须失败，不能尝试清洗后继续。
Intercom evidence 允许保存结构化 `requirement`，但不得把它描述为客户原话；其中
意外嵌入的邮箱地址统一替换为 `[EMAIL]`。

## 状态与错误

Intercom 是周期快照，不创建 `state/intercom.json`。每次成功运行写入独立
`runs/intercom/`、`evidence/intercom/` 和 `manifests/`；失败不写 manifest。

发布读取时，外层 manifest 必须与 run artifact 内嵌 manifest 一致，运行状态必须为
`succeeded`，并且 `fetchedCount` 与 evidence 实际条数相等。

Datadog 子进程退出码保持统一映射：2=配置，3=认证/权限，4=API/业务，5=超时。
错误回复不转发 Datadog stderr，避免带出底层响应内容。

## 团队发布

运行实例通过 `.env` 配置团队，不在代码中写死团队名称：

```dotenv
MFC_SQUAD=Grooming
```

进程环境、CWD `.env`、skill `.env` 按由高到低优先级且以“键存在”为覆盖条件；显式
空值用于禁用当前实例的 Intercom 发布，不得回退到低优先级残留团队值。

发布时对 evidence 的 `squad` 做去除首尾空白、忽略大小写的精确匹配。`domain`
仍作为业务子域展示，不承担团队筛选；这样 Grooming Calendar、Service、Online Booking
等子域不会因为字段值不同而被漏掉。其它团队只需修改运行环境变量，不需要修改 Skill。

团队内只发布以下两类：

```text
feature_feedback → 功能反馈
feature_request  → 功能需求
```

先执行 dry-run：

```bash
uv run --script scripts/moe_feedback_collector.py publish \
  --source intercom --manifest <manifest.json> --dry-run
```

dry-run 输出必须记录采集总数、Squad 命中数、两类入选数、排除数和规则版本
`intercom-squad-features-v1`。只有 `mode=period` 且发布周期与 manifest 周期完全一致时
才能发布；`probe`、跨周期和缺少 Squad 配置都失败。数据超过 50 条时，周报保留两类
摘要，并按类型拆分只读源数据子文档。周报和自动子文档标题都包含 Squad，作为同一
周期的稳定团队身份；缩量重跑时，不再被主周报引用且带自动生成标记的旧子文档会被
覆盖为失效提示，不删除页面，也不修改未带标记的文档。
