# business-process：审批 + 考勤 + OKR

合并 lark-cli 的 `lark-approval`（审批）+ `lark-attendance`（考勤打卡）+ `lark-okr`（OKR）。三者都是组织流程类、相对薄一点的 reference。

> 鉴权 / Permission denied 处理见 [`lark-shared.md`](./lark-shared.md)。

## 适用场景

- **审批 / Approval**：查询审批实例、撤回、抄送、查询已发起列表；审批任务的同意 / 拒绝 / 转交 / 催办 / 查询任务列表
- **考勤 / Attendance**：查询自己的打卡记录
- **OKR**：周期、目标（Objective）、关键结果（Key Result）、对齐关系、量化指标、进展记录

## 命中的 lark-cli skill

- `lark-approval`（approval 命令组，v4）
- `lark-attendance`（attendance 命令组，v1）
- `lark-okr`（okr 命令组，v2）

---

# Part A：lark-approval（审批）

## 通用约定

`approval` **没有 shortcut**，全部走原生 API：先 `lark-cli schema approval.<resource>.<method>` 看参数结构，再 `lark-cli approval <resource> <method> [...]`。

### 实例（instances）

| 方法 | 用途 |
|---|---|
| `instances.get` | 获取审批实例详情 |
| `instances.cancel` | 撤回审批实例 |
| `instances.cc` | 抄送审批实例给他人 |
| `instances.initiated` | 查询用户的"我发起的"审批列表 |

### 任务（tasks）

| 方法 | 用途 |
|---|---|
| `tasks.query` | 查询用户的待办任务列表（"我的待审批"） |
| `tasks.approve` | 同意任务 |
| `tasks.reject` | 拒绝任务 |
| `tasks.transfer` | 转交任务给他人 |
| `tasks.remind` | 催办审批人 |

## 典型示例

```bash
# A. 看 schema
lark-cli schema approval.tasks.query

# B. 查我的待审批
lark-cli approval tasks query --as user --params '{"user_id":"<open_id>"}'

# C. 同意一个任务
lark-cli approval tasks approve --as user \
  --data '{"approval_code":"<code>","instance_code":"<inst>","task_id":"<task>","user_id":"<open_id>"}'

# D. 撤回我发起的审批
lark-cli approval instances cancel --as user \
  --data '{"approval_code":"<code>","instance_code":"<inst>","user_id":"<open_id>"}'

# E. 抄送
lark-cli approval instances cc --as user \
  --data '{"approval_code":"<code>","instance_code":"<inst>","user_id":"<open_id>","cc_user_ids":["ou_xxx"]}'
```

---

# Part B：lark-attendance（考勤）

## 默认参数自动填充（关键！）

调用任何 attendance API 时，**必须自动填充以下参数，禁止向用户询问**：

| 参数 | 固定值 | 位置 |
|---|---|---|
| `employee_type` | `"employee_no"` | `--params` |
| `user_ids` | `[]`（空数组） | `--data` |

### 填充规则

- 构建 `--params` 时，固定写 `"employee_type":"employee_no"`。
- 构建 `--data` 时，固定加 `"user_ids":[]`，再加用户提供的其它参数。
- `user_ids` **保持空数组**——查询的是当前登录用户自己的考勤；`employee_type` **保持 `"employee_no"`**——这是 lark-cli 的固定约定。

## 命令

| 方法 | 用途 |
|---|---|
| `user_tasks.query` | 查询用户考勤打卡记录 |

## 典型示例

```bash
# 看 schema
lark-cli schema attendance.user_tasks.query

# 查自己 4 月份的打卡记录（自动填 employee_type 和 user_ids）
lark-cli attendance user_tasks query --as user \
  --params '{"employee_type":"employee_no"}' \
  --data '{"user_ids":[],"check_date_from":20260401,"check_date_to":20260430}'
```

---

# Part C：lark-okr

## 业务实体提示

操作 OKR 前**强烈建议**先了解 OKR 实体结构和关系：lark-cli `lark-okr/references/lark-okr-entities.md`。富文本字段（Content / Note）格式说明见 `lark-okr-contentblock.md`。

资源关系：

```
Cycle (周期)
└── Objective (目标)
    ├── Alignment (对齐关系，跨 Objective)
    ├── Indicator (量化指标)
    └── KeyResult (关键结果)
        ├── Indicator (量化指标)
        └── Progress (进展记录)
```

## Shortcut 速查表

| Shortcut | 用途 |
|---|---|
| `+cycle-list` | 取某用户的 OKR 周期列表（可按时间筛选） |
| `+cycle-detail` | 取某 OKR 周期下所有目标和关键结果 |
| `+progress-list` | 列某 Objective 或 KR 的所有进展记录 |
| `+progress-get` | 单条进展记录详情 |
| `+progress-create` | 给 Objective 或 KR 创建进展记录 |
| `+progress-update` | 更新某条进展 |
| `+progress-delete` | 删除某条进展（**不可恢复**） |
| `+upload-image` | 上传图片，用于进展记录富文本内容 |

## 原生 API（无 shortcut 时）

| 资源 | 方法 |
|---|---|
| `cycles` | `list`（用户周期列表）、`objectives_position`（**全量**改周期下目标位置，不能重叠）、`objectives_weight`（**全量**改权重，和必须 = 1） |
| `cycle.objectives` | `create` / `list` |
| `objectives` | `get` / `patch` / `delete` / `key_results_position`（**全量**改 KR 位置）/ `key_results_weight`（**全量** KR 权重，和 = 1） |
| `objective.key_results` | `create` / `list` |
| `objective.alignments` | `create`（不可对齐自己；周期时间必须有重叠）/ `list` |
| `objective.indicators` | `list` |
| `key_results` | `get` / `patch` / `delete` |
| `key_result.indicators` | `list` |
| `indicators` | `patch` |
| `alignments` | `get` / `delete` |
| `categories` | `list`（批量取分类） |

## 关键约束（参数校验易错点）

- **`cycles.objectives_position` / `cycles.objectives_weight`**：必须同时修改**对应周期下全部目标**的位置 / 权重；位置不允许重叠；权重之和必须 = 1。
- **`objectives.key_results_position` / `objectives.key_results_weight`**：必须同时修改**对应目标下全部 KR**的位置 / 权重；位置不允许重叠；权重之和必须 = 1。
- **`objective.alignments.create`**：不允许对齐自己的目标；发起对齐和被对齐的目标所在周期时间上**必须有重叠**。
- **`+progress-delete`**：不可恢复，删除前必须用户明确确认。

## 典型示例

```bash
# A. 看我有哪些周期
lark-cli okr +cycle-list --user-id me --as user

# B. 取某周期下所有 O + KR
lark-cli okr +cycle-detail --cycle-id <cycle_id> --user-id me --as user

# C. 给某 KR 加一条进展
lark-cli okr +progress-create --target-id <kr_id> --target-type kr \
  --content '<contentblock 富文本>' --as user

# D. 全量重排某周期下目标（必须给所有目标新位置且不重叠）
lark-cli schema okr.cycles.objectives_position
lark-cli okr cycles objectives_position --as user \
  --params '{"user_id":"<open_id>","period_id":"<cycle_id>"}' \
  --data '{"objective_ids":["<o1>","<o2>","<o3>"]}'   # 顺序即位置
```

---

## NEVER 规则（领域特有）

### Approval

- ❌ **不要凭自然语言猜 `approval_code` / `instance_code` / `task_id`**——必须从查询结果取。
- ❌ **`tasks.transfer` 不要默认转给"任意可用人"**——必须用户明确指定接收人。
- ❌ **撤回 / 拒绝 / 同意属于写操作**，遵循 [`lark-shared.md`](./lark-shared.md) 写操作确认规则。

### Attendance

- ❌ **不要询问用户 `employee_type` / `user_ids`**——固定填 `"employee_no"` / `[]`。
- ❌ **`user_ids` 不要填实际 ID 想"查别人"**——本 skill 只查自己；查别人需走原生 API + 管理员权限，不在本 skill 范围。

### OKR

- ❌ **`*_position` / `*_weight` 不要做增量更新**——必须**全量**重新提交所有目标 / KR 的位置或权重；位置不重叠、权重和 = 1。
- ❌ **`alignments.create` 不要对齐自己的目标**——必失败。
- ❌ **`+progress-delete` 不要默认确认**——不可恢复，必须用户明确同意。
- ❌ **不要跳过 `lark-okr-entities.md` 直接动 OKR 写操作**——实体关系不熟容易写错字段。

## 不在本 reference 范围

- 把 OKR / 审批结果通知到 IM → 配合 [`collab-im.md`](./collab-im.md)
- 部门 / 组织树查询 → [`openapi-explorer.md`](./openapi-explorer.md)
- 审批 / 考勤 / OKR 的事件订阅 → [`event-stream.md`](./event-stream.md)

## 溯源

- lark-cli `skills/lark-approval/SKILL.md`（v1.0.0，approval v4）
- lark-cli `skills/lark-attendance/SKILL.md`（v1.0.0，attendance v1）
- lark-cli `skills/lark-okr/SKILL.md`（v1.0.0，okr v2）
