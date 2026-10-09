# Legacy grooming offering 与 appointment

适用：问题明确涉及 legacy grooming service/addon 配置、旧 appointment，或当前 fulfillment
模型存在已验证 coverage gap。当前 appointment snapshot 和 status history 仍优先使用
`recipe appointment-timeline`。

本参考的对象和关键字段已在 2026-08-21 通过 live metadata 验证。低基数枚举查询经过
有界 EXPLAIN；代码枚举来自 `moego-server-common`、`moego-server-api` 和
`moego-server-grooming`。执行具体业务查询前仍要重新 `describe` 和 `explain`。

## 对象与 grain

| 对象 | Grain | 主要用途 |
|---|---|---|
| `mysql_prod.moe_grooming.moe_grooming_service` | 一个 business/location 下的一条 offering 配置 | Service/addon 配置与启用状态 |
| `mysql_prod.moe_grooming.moe_grooming_appointment` | 一条 legacy appointment header | Legacy appointment 生命周期与 tenant link |
| `mysql_prod.moe_grooming.moe_grooming_pet_detail` | 一个 appointment pet 下的一条已选 service/addon | Staff、service、价格和明细状态 |

`company_id` 是 company 粒度，`business_id` 是 location 粒度。按 company 汇总会合并多个
location 的配置记录；这不等于多个 location 共享同一条 offering。

## Service / addon 语义

`moe_grooming_service` 同时保存主服务和 addon：

| 字段 | 已验证语义 |
|---|---|
| `type` | `1` = service，`2` = addon |
| `require_dedicated_staff` | boolean；`true/1` 表示需要指定 staff |
| `inactive` | `0` = enabled，`1` = inactive |
| `service_item_type` | `0` = unspecified/legacy，`1` = GROOMING，`2` = BOARDING，`3` = DAYCARE，`4` = EVALUATION，`5` = DOG_WALKING，`6` = GROUP_CLASS |

筛选当前有效 offering 使用 `status = 1 AND inactive = 0`。代码注释只定义了部分历史
`status`，live replica 存在其他值；除 `status = 1` 外，不要为未定义值猜业务含义。

不要用 offering name 做跨 location 静默去重。若任务需要“独立 offering”口径，先让用户
确认是按记录、business、service ID，还是另一个业务定义统计。

## Legacy appointment 语义

`moe_grooming_appointment.status` 的代码枚举为：

| 值 | 含义 |
|---|---|
| `0` | UNKNOWN |
| `1` | UNCONFIRMED |
| `2` | CONFIRMED |
| `3` | FINISHED |
| `4` | CANCELED |
| `5` | READY |
| `6` | CHECK_IN |

即：`READY = 5`，`CHECK_IN = 6`。Legacy replica 可能含代码枚举外的历史值；保留 raw
value 并标记 unknown，不要自动归入 canceled 或 finished。

`is_deprecate = 0` 表示未因 repeat 规则迁移而弃用。是否排除 deprecated row 取决于任务：
当前有效 legacy appointment 通常排除，历史迁移调查则可能需要保留。

## Pet detail 语义

`moe_grooming_pet_detail` 使用 `grooming_id = appointment.id` 连接 appointment：

| 字段 | 已验证语义 |
|---|---|
| `service_type` | `1` = service，`2` = addon；其他值按 unknown 处理 |
| `status` | `1` = active，`2` = deleted，`3` = removed by appointment edit |
| `service_item_type` | 与 offering 相同：GROOMING = 1，BOARDING = 2，DAYCARE = 3，EVALUATION = 4，DOG_WALKING = 5，GROUP_CLASS = 6 |
| `total_price` | 该 selected service 的总价；不能与单价或不同货币/单位直接混用 |

查询当前有效 detail 时使用 `pd.status = 1`。Appointment status 集合必须按问题显式选择；
不要默认只保留 CONFIRMED 和 FINISHED，因为 READY 和 CHECK_IN 也是有效生命周期状态。

## 统计边界

- Company 汇总与 business/location 汇总是不同口径，必须在结果中说明 grain。
- `GROUP BY` 只包含有匹配记录的 company。计算“全部 company 平均值”时，需要先定义完整
  company population，再 `LEFT JOIN` 聚合结果。
- 不按 company name 猜 Demo/Test 数据。排除内部 tenant 必须使用用户提供或已验证的
  company/business identity 集合。
- Enum 与本参考不一致时，返回 raw value，并回到代码和 live metadata 重新验证。
