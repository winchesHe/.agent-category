# MoeGo 查询模式

适用：已经选定 source 与产品 generation，需要使用已验证 recipe、查询起点或升级 pattern。

先读 [domain-routing.md](domain-routing.md)。`verified` 表示对象和字段已通过 live metadata，且有界 SQL
在记录日期通过 Redshift EXPLAIN。`needs_review` 只是发现起点，不是可信模板。

下列命令都使用 `SKILL.md` 建立的 `SKILL_DIR`。SQL 使用完整三段式对象名、named parameter 和
正数 limit。Catalog 与 live metadata 冲突时，重新 `describe`。

## Identity：email 到 company/business

- 状态：`verified`
- 最近验证：`2026-08-20`
- 证据：两个阶段均通过 live metadata 与有界 EXPLAIN；safe no-match canary 通过。

只使用维护过的 recipe，不复制内部 identity filter：

```bash
python3 "$SKILL_DIR/scripts/redshift.py" recipe email-to-company \
  --email person@example.invalid --format json
```

Recipe 不 fallback 到 legacy account table 或 staff profile email。

## 按 company/business 查询 customer 与 contact

- 状态：`needs_review`
- 最近审查：`2026-07-14`
- 范围：当前 customer service 模型。

先验证三个 relation：

```bash
python3 "$SKILL_DIR/scripts/redshift.py" describe pg_moego_customer_prod.public.customer
python3 "$SKILL_DIR/scripts/redshift.py" describe pg_moego_customer_prod.public.customer_related_data
python3 "$SKILL_DIR/scripts/redshift.py" describe pg_moego_customer_prod.public.contact
```

验证后使用以下有界 EXPLAIN 起点：

```bash
python3 "$SKILL_DIR/scripts/redshift.py" explain \
  --database pg_moego_customer_prod \
  --sql "SELECT c.id, c.given_name, c.family_name, ct.email, ct.phone
         FROM pg_moego_customer_prod.public.customer AS c
         JOIN pg_moego_customer_prod.public.customer_related_data AS crd
           ON crd.customer_id = c.id AND crd.deleted_time IS NULL
         LEFT JOIN pg_moego_customer_prod.public.contact AS ct
           ON ct.customer_id = c.id
          AND lower(ct.is_self) = 'true'
          AND ct.deleted_time IS NULL
         WHERE c.organization_type = 'COMPANY'
           AND c.organization_id = %(company_id)s
           AND c.deleted_time IS NULL
           AND crd.company_id = %(company_id)s
           AND crd.business_id = %(business_id)s" \
  --params '{"company_id":100,"business_id":200}' --format json
```

Pattern 未升级为 `verified` 前，禁止当作可信 query 执行。Company/business 与 soft-delete filter
会改变业务含义。

## 按 customer 查询 pet

- 状态：`needs_review`
- 最近审查：`2026-07-14`
- 范围：当前 customer-service pet 模型。

```bash
python3 "$SKILL_DIR/scripts/redshift.py" search pet \
  --database pg_moego_customer_prod --domain customer --limit 20
```

用 `describe` 确认 customer link、active 和 delete 字段。旧 guide 中的 `account_id` 与
`status=1` 不再视为已验证事实。

## 当前 appointment

- 状态：`verified`
- 最近验证：`2026-08-20`
- 范围：一个当前 fulfillment appointment 及其 status history。
- 证据：两个阶段均通过 live metadata 和有界 EXPLAIN。

```bash
python3 "$SKILL_DIR/scripts/redshift.py" recipe appointment-timeline \
  --appointment-id 123456 --format json
```

输出分开保存当前 snapshot 与有序 status history。History 证明状态变化，不是 schedule、assignment
或其他字段的字段级审计日志。只有明确 legacy 请求或已验证 current-model coverage gap 时，才使用
`mysql_prod.moe_grooming`。

## Legacy grooming service/addon 与 appointment detail

- 状态：query shape 为 `verified`
- 最近验证：`2026-08-21`
- 证据：三个对象通过 live metadata；以下低基数 aggregation 与 Join shape 已通过有界 EXPLAIN。
- 语义：[legacy-grooming.md](legacy-grooming.md)

按 company/business 和 offering 属性汇总有效 service/addon：

```bash
python3 "$SKILL_DIR/scripts/redshift.py" explain \
  --database mysql_prod \
  --sql 'SELECT company_id, business_id, type, service_item_type,
                require_dedicated_staff, COUNT(*) AS offering_count
         FROM mysql_prod.moe_grooming.moe_grooming_service
         WHERE status = 1 AND inactive = 0
         GROUP BY company_id, business_id, type, service_item_type,
                  require_dedicated_staff' \
  --format json
```

从 legacy appointment 连接当前有效 pet detail：

```bash
python3 "$SKILL_DIR/scripts/redshift.py" explain \
  --database mysql_prod \
  --sql 'SELECT apt.id, apt.company_id, apt.business_id, apt.status,
                pd.pet_id, pd.staff_id, pd.service_id, pd.service_type,
                pd.service_item_type, pd.total_price
         FROM mysql_prod.moe_grooming.moe_grooming_appointment AS apt
         JOIN mysql_prod.moe_grooming.moe_grooming_pet_detail AS pd
           ON pd.grooming_id = apt.id AND pd.status = 1
         WHERE apt.id = %(appointment_id)s
           AND apt.is_deprecate = 0' \
  --params '{"appointment_id":123456}' --format json
```

不要默认添加 appointment status filter。由问题明确选择 UNCONFIRMED、CONFIRMED、FINISHED、
CANCELED、READY 或 CHECK_IN；遇到历史 raw/unknown 值时保留原值，不自动归入 canceled 或
finished。跨 location 汇总时保留 business grain；没有用户确认时，不按 offering name 去重，
也不按 company name 排除 tenant。

## Membership

- 状态：当前 V2 identifier trace 为 `verified`
- 最近验证：`2026-08-20`
- 证据：membership、subscription、price、benefit-config、benefit 和 event 阶段均通过 live
  metadata 与有界 EXPLAIN。

必须且只能提供一个当前 V2 identifier：

```bash
python3 "$SKILL_DIR/scripts/redshift.py" recipe membership-entitlement \
  --membership-id 123456 --format json

python3 "$SKILL_DIR/scripts/redshift.py" recipe membership-entitlement \
  --subscription-id 123456 --format json
```

输出将 membership definition、subscription instance、price、benefit configuration、issued
benefit 和 event 分开。Recipe 不读取 event payload，也不查询或合并旧 generation。

### 指定日期的 active subscription

- 状态：`needs_review`
- 最近审查：`2026-07-15`

禁止复用通用 `state = 'ACTIVE'`。先定义 timezone、scheduled cancellation 是否仍 active、
soft deletion 规则，以及 cancellation 后保留 benefit 是否算 entitlement。先用 verified recipe 收集
lifecycle facts，再应用用户确认的解释。

## Order 与 line item

- 状态：`needs_review`
- 最近审查：`2026-07-14`
- 证据：live metadata 已将旧 `created_at` 修正为 `create_time`；完整模式仍需当前 EXPLAIN。

```bash
python3 "$SKILL_DIR/scripts/redshift.py" describe pg_moego_order_prod.public.order
python3 "$SKILL_DIR/scripts/redshift.py" describe pg_moego_order_prod.public.order_line_item

python3 "$SKILL_DIR/scripts/redshift.py" explain \
  --database pg_moego_order_prod \
  --sql 'SELECT id, business_id, customer_id, payment_status,
                fulfillment_status, total_amount, paid_amount,
                complete_time, create_time
         FROM pg_moego_order_prod.public."order"
         WHERE id = %(order_id)s' \
  --params '{"order_id":123456}' --format json
```

没有新 metadata 证据时，禁止恢复 `created_at`。

## Payment 路由与金额语义

- 状态：`needs_review`
- 最近审查：`2026-07-14`
- 范围：从 domain reference 精确选择一个路径。

```bash
python3 "$SKILL_DIR/scripts/redshift.py" describe pg_moego_payment_prod.public.payment
python3 "$SKILL_DIR/scripts/redshift.py" describe pg_moego_order_prod.public.order_payment
python3 "$SKILL_DIR/scripts/redshift.py" describe mysql_prod.moe_payment.payment
```

汇总金额前确认 type、unit 和 entity linkage。当前 service payment、order payment 与 legacy
payment 不能因为 relation 都叫 `payment` 就互换。

## 当前 refund origin

- 状态：`verified`
- 最近验证：`2026-08-20`
- 范围：一个当前 payment-service refund identifier。
- 证据：refund、payment 和 order-payment 阶段均通过 live metadata 与有界 EXPLAIN。

```bash
python3 "$SKILL_DIR/scripts/redshift.py" recipe refund-origin \
  --refund-id 123456 --format json
```

结果分开保存 refund、当前 payment 和匹配的 order-payment。Recipe 不 fallback 到 legacy。
Order-payment 不匹配不能证明 refund 缺失。当前 service amount 是 minor units；order-payment
numeric amount 在比较前必须明确单位。

## 有界日期范围指标

- 状态：query shape 为 `needs_review`；每个 metric 仍依赖具体 source。
- 最近审查：`2026-07-15`

选择 ADS/DWS/DIM，明确 metric 与 timezone，并使用半开区间：
`event_time >= start AND event_time < end`。每个大 fact branch 都保留 time predicate，使用 named
parameter，并在 DWD/ODS 前执行 EXPLAIN。不要把 date range 加 `COUNT(*)` 变成通用 recipe。

## Package redemption

- 状态：`needs_review`
- 最近审查：`2026-07-14`
- 证据：live metadata 已证明旧字段 `moe_grooming_package_service.service_name` 不存在。

```bash
python3 "$SKILL_DIR/scripts/redshift.py" search package \
  --database mysql_prod --domain fulfillment --limit 30 --format json
python3 "$SKILL_DIR/scripts/redshift.py" describe \
  mysql_prod.moe_grooming.moe_grooming_package_service
```

根据实际 package、package-service、history 和 invoice-apply 字段重建关系，再 EXPLAIN。
确认 status/delete 语义前，count difference 不能解释为 missing redemption。

## Warehouse metric 与 detail fact

- 状态：路由为 `verified`；具体 SQL 仍依赖 pattern。
- 最近验证：`2026-07-14`

```bash
python3 "$SKILL_DIR/scripts/redshift.py" search payment \
  --source-type warehouse --layer ads --limit 20 --format json
python3 "$SKILL_DIR/scripts/redshift.py" search payment \
  --source-type warehouse --layer dws --limit 20 --format json
```

ADS/DWS/DIM 用于维护过的 metric，DWD 用于 detail fact。ODS/RAW 用于 ingestion 或 ETL 调查。
有界 limit 只限制返回行数，不限制 scan data；大 JOIN 与 ODS/DWD query 必须先 EXPLAIN。

## Pattern 升级与降级

只有当前 `describe`、有界 Redshift EXPLAIN 和业务语义证据全部通过时，才将 pattern 从
`needs_review` 改为 `verified`，并记录日期和证据。Object/column drift、相关 catalog coverage
不完整或路由变化时立即降级。Template 失败不能成为发明 fallback 的理由。
