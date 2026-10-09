# MoeGo 数据领域路由

适用：任务涉及 account、customer、appointment、legacy grooming service/addon、membership、order、payment、package
或数仓指标，需要先选择 source 与产品 generation。

本文件决定从哪个 source 开始，不提供自动 fallback。

状态含义：

- `verified`：对象和关键字段已通过 live metadata；对应 SQL 已通过有界 EXPLAIN。
- `needs_review`：仅用于发现；执行前必须重新 `describe` 和 `explain`。

## Source 选择顺序

1. 先确认任务要查当前业务状态、历史聚合还是 ingestion/ETL。
2. 当前状态优先选择拥有该事实的 service replica。
3. 指标和趋势优先选择 ADS/DWS/DIM；明细再下钻 DWD。
4. ODS/RAW 只用于 ingestion 或 ETL 诊断。
5. 产品 generation、时间范围、tenant 或金额单位会改变结论时，先问用户一次。
6. 空结果不能证明应该切换到 legacy source。

## 领域路由

### Identity：email/account 到 company/business

- 状态：`verified`
- 最近验证：`2026-08-20`
- 起点：`recipe email-to-company`
- 路径：有效 MoeGo account → company/business membership。
- 边界：不读取 staff profile email，不自动查询 legacy account table。

### Customer、contact 与 pet

- 状态：customer/contact 为 `needs_review`；pet 路径为 `needs_review`。
- 最近审查：`2026-07-14`
- 起点：`pg_moego_customer_prod`。
- Customer 与 contact 先确认 organization link、company/business filter、soft-delete 和 self-contact。
- Pet 先用 `search` 与 `describe` 找当前 customer link、active 和 delete 字段。
- 禁止沿用旧 guide 的 `account_id` 或 `status=1`，除非 live metadata 与业务语义重新验证。

重复、merge 或 lead conversion 调查必须有 shared identifier、维护过的 relationship 或 event evidence。
名称、邮箱或电话相同不能单独证明 lineage。

### Appointment 与 fulfillment

- 状态：当前 appointment timeline 为 `verified`；其他 booking/fulfillment join 为 `needs_review`。
- 最近验证：`2026-08-20`
- 起点：`pg_moego_fulfillment_prod`。
- 单个当前 appointment 使用 `recipe appointment-timeline`。
- Recipe 返回当前 snapshot 和按时间排序的 status record。
- Status record 证明 status transition 与 revert，不是 schedule、assignment 或内容字段的完整 audit log。
- 只有请求明确属于 legacy，或当前模型存在已验证 coverage gap 时，才使用
  `mysql_prod.moe_grooming`。

### Legacy grooming offering 与 appointment

- 状态：对象、关键字段和低基数枚举为 `verified`；具体业务指标仍按任务重新 EXPLAIN。
- 最近验证：`2026-08-21`
- 起点：`mysql_prod.moe_grooming`。
- Service/addon 配置从 `moe_grooming_service` 开始；legacy appointment 与已选服务明细使用
  `moe_grooming_appointment` 和 `moe_grooming_pet_detail`。
- 先读 [legacy-grooming.md](legacy-grooming.md) 确认 generation、grain、枚举和 Join，再使用
  [query-patterns.md](query-patterns.md) 的有界起点。
- 当前 appointment 查询仍使用 fulfillment recipe。Legacy 表不能因为对象名相似就替代当前模型。

### Membership

- 状态：当前 V2 identifier trace 为 `verified`；跨 generation 比较为 `needs_review`。
- 最近验证：`2026-08-20`
- 起点：`recipe membership-entitlement`。
- 固定模型：membership definition → subscription instance → price/benefit configuration →
  issued benefit → lifecycle event。
- Benefit configuration 与 issued benefit 是不同事实。
- 只有请求明确指定旧产品 generation 或历史范围时，才读取旧 membership source。
- 不自动合并新旧 generation，也不根据记忆猜 relation 的单复数名称。

### Order 与 line item

- 状态：`needs_review`
- 最近审查：`2026-07-14`
- 起点：`pg_moego_order_prod`。
- 当前 order 创建字段是 `create_time`。旧模板中的 `created_at` 已失效。
- Legacy invoice/package source 只用于明确的旧流程。

### Payment、refund、dispute 与 payout

- 状态：当前 refund origin trace 为 `verified`；其他路径为 `needs_review`。
- 最近验证：`2026-08-20`

| 路径 | 起点 | 关键区别 | 适用范围 |
|---|---|---|---|
| 当前 payment service | `pg_moego_payment_prod` | 金额可能是 integer minor units；payer 为 polymorphic link | 当前 payment/refund/dispute/payout lifecycle |
| Order payment | `pg_moego_order_prod` | Order-bound record 与 order-facing method | 与 order 对账 |
| Legacy payment | `mysql_prod.moe_payment` | Legacy numeric amount 与直接 company link | 明确 legacy 场景 |

给定当前 payment-service refund ID 时，使用 `recipe refund-origin`。Recipe 从 refund 的
`payment_id` 找当前 payment，再查 order-payment match。Order-payment 不匹配不能抹掉已经确认的
refund/payment，也不能触发 legacy fallback。

当前 payment-service amount 使用 integer minor units。Order-payment amount 是 numeric
order-facing value。没有明确单位转换和业务理由时，禁止相加或直接比较。

### Package redemption

- 状态：`needs_review`
- 最近审查：`2026-07-14`
- 当前仍在旧模型的流程从 `mysql_prod` 的 grooming/package relation 开始。
- 旧模板引用了不存在的 `package_service.service_name`。查询前必须重新发现字段并 EXPLAIN。

### Warehouse analytics

- 状态：路由为 `verified`
- 最近验证：`2026-07-14`
- 指标优先 ADS/DWS/DIM；明细使用 DWD。
- ODS/RAW 只用于 ingestion 或 ETL 诊断。
- ODS/DWD scan、大 JOIN 或时间范围不明确时先 `explain`。空 advisory 不代表 query 安全或高效。

## 决策规则

- 产品 generation 明确时，当前状态问题可以直接进入事实 owner source。
- Generation、amount unit、tenant、timezone 或历史范围会改变解释时，先问一次。
- Legacy fallback 必须有明确 scope 和证据。空结果本身不是证据。
- Metadata warning、incomplete catalog、permission error 和 timeout 都不是 “not found”。
- 文档 pattern 与 live metadata 冲突时，停止使用并降级为 `needs_review`。
- Bare record ID 不能决定领域；先确定 domain，必要时问一次。
- “某日仍 active”必须先定义 timezone、scheduled cancellation、soft deletion 和 benefit retention。
