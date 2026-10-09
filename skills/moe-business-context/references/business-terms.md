# MoeGo 术语检索线索

需要把业务说法转换成搜索关键词时读取。以下内容来自既有业务调查，仅作为历史线索；字段、枚举、实体范围和单接口口径必须按当前问题核验，不能推广为全产品现行定义。

## 业务实体

| 用户说法 | 搜索线索 | 核对重点 |
|---|---|---|
| 客户 / 顾客 | `customer` / `client`（Boarding_Desktop 偏向 client，后端表多用 customer） | business/company 作用域、身份来源和关联方式 |
| 宠物 | `pet`、`petTypeId` | 当前类型枚举及写入值，不沿用历史数字映射 |
| 员工 / 美容师 / Groomer | `staff` / `groomer` | 通用员工实体与 grooming 角色的关系 |
| 预约 / 工单 | `appointment` / `grooming` / `ticket`、`MoeGroomingAppointment` | 产品对象与后端实现是否对应同一预约生命周期 |
| 预约状态 | `status`、SUBMITTED / CONFIRMED / IN_PROGRESS / CANCELLED / FINISHED | 当前枚举及实际 SQL 过滤；名称不能替代口径 |
| 服务项目 | `service`、`serviceItemType`、GROOMING / BOARDING / DAYCARE / EVALUATION / DOG_WALKING / GROUP_CLASS | 所属产品线与当前服务类型定义 |
| 套餐 / 会员 | `package` / `membership` / `subscription` | 购买、权益、订阅和消耗记录不因名称相近而等价 |
| 评价 | `review` / `evaluation` | evaluation 也可能是评估服务，先确认产品入口 |
| 商户 | `business` / `company` | 当前实体层级、租户范围及关联 ID |

## 流程与场景

| 用户说法 | 系统术语 |
|---|---|
| OB / OB-C / OB-B | `online_booking`；OB-C = customer 端（`moego-online-booking-client-web`），OB-B = 商户端 |
| B&D / B/D / 寄养 | Boarding + Daycare 联合上下文（`Boarding_Desktop`） |
| 美容 | Grooming |
| Check-in / Check-out | 入住 / 退住 |
| Auto Accept | OB 自动接单逻辑 |
| Waitlist | 候补；OB 在没有可用 slot 时进入 |
| Preferred groomer | 从 `preferredGroomerId` 查定义、setter 和消费者；历史线索是 `customer.preferredGroomerId`，目标入口的 customer/pet/business 归属仍需核验。长期偏好或单次建议由写入时机、覆盖和消费规则判断，不能仅凭存储实体确定 |
| New client / New customer | 历史 OB list 线索是「该 customer 在该 business 无 FINISHED 预约」；目标接口另核对身份来源、历史、时间与状态，不能仅凭名称等同于首次来店或请求未带 customerId |
| Last APPT groomer | 核对“最近”的时间字段、状态、排序与并列处理，以及额外查询或聚合；派生的最近预约美容师不等于 preferred groomer 配置 |
| 通知 / Notification | `MoeGoNotification` enum（OB_REQUEST / OB_REQUEST_CANCEL / OB_RESCHEDULED / ...） |
| 客户分群 | `lifeCycle` / `customerType`（LEAD / CUSTOMER）/ tags |
| Intake form | C 端提交的客户 / 宠物信息表单 |

## 缩写陷阱

| 缩写 | 容易误解为 | 实际 |
|---|---|---|
| OB | OnBoarding | **O**nline **B**ooking |
| B/D | Build / Develop | **B**oarding & **D**aycare |
| APPT | Appointment | Appointment |
| TZ | TimeZone | TimeZone；核对 business 时区设置，并区分业务、查询和展示时区 |
| ADF | Application Data Format | Atlassian Document Format（Jira 评论体） |
| CS | Customer Service ticket | Jira 项目 key（CS-*） |
| GRM | Groom 项目 | Jira Grooming squad（GRM-*） |
| IFRFE | （前端项目）| Jira 前端 Issue 项目（IFRFE-*） |
