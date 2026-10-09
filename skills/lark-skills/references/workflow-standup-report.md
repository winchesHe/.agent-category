# workflow-standup-report：日程 + 待办摘要（站会 / 日报）

对应 lark-cli 的 `lark-workflow-standup-report`。**组合工作流**——编排 calendar + task，生成指定日期的日程 + 未完成待办摘要。

> 鉴权 / 身份处理见 [`lark-shared.md`](./lark-shared.md)。
> 单领域命令详见 [`collab-calendar.md`](./collab-calendar.md)（calendar）和 [`business-task.md`](./business-task.md)（task）。

## 适用场景

- "今天有什么安排" / "今天的日程和待办"
- "明天有什么会" / "明日日程与未完成任务"
- "帮我看看今天要做什么" / "早报摘要" / "开工摘要" / "standup report"
- "这周还有哪些安排"

## 前置条件

⚠️ **仅支持 user 身份**（`--as user`）。涉及的 scope 域：`calendar` + `task`。

## 工作流概览

```
{date}
  ├─► calendar +agenda [--start/--end] ──► 日程列表（会议 / 事件）
  └─► task +get-my-tasks [--due-end]   ──► 未完成待办列表
                │
                ▼
          AI 汇总（时间转换 + 冲突检测 + 排序）──► 摘要
```

## Step 1：取日程

```bash
# 今天（默认，无需参数）
lark-cli calendar +agenda --as user

# 指定日期范围（**必须 ISO 8601**，不支持 "tomorrow" 等自然语言）
lark-cli calendar +agenda --as user \
  --start "2026-04-30T00:00:00+08:00" --end "2026-04-30T23:59:59+08:00"
```

⚠️ `--start` / `--end` 仅支持 **ISO 8601** 或 Unix timestamp，**不支持** `"tomorrow"` / `"next monday"` 等自然语言。AI 必须基于当前日期自行计算目标日期。

返回字段含：`event_id` / `summary` / `start_time`（含 timestamp + timezone）/ `end_time` / `free_busy_status` / `self_rsvp_status`。

## Step 2：取未完成待办

```bash
# 默认：分配给我的未完成（最多 20 条）
lark-cli task +get-my-tasks --as user

# 推荐：仅看目标日期前到期的（减少数据量）
lark-cli task +get-my-tasks --as user --due-end "2026-04-30T23:59:59+08:00"

# 全部（>20 条时）
lark-cli task +get-my-tasks --as user --page-all
```

⚠️ 不带过滤可能返回大量历史待办（实测 30+ 条 / 100KB+），容易爆 context。

**摘要场景建议**：

- 用 `--due-end` 限制目标日期前到期
- 如果也需要无截止日期的任务，可不加 due-end，但 AI 汇总时**只展示近 30 天内创建的**，其余折叠为"其他 N 项历史待办"

## Step 3：AI 汇总输出

整合 Step 1 和 Step 2，按以下结构：

```markdown
## {日期}摘要（YYYY-MM-DD 星期X）

### 日程安排
| 时间 | 事件 | 组织者 | 状态 |
|---|---|---|---|
| 09:00-10:00 | 产品需求评审 | 张三 | 已接受 |
| 14:00-15:00 | 技术方案讨论 | 李四 | 待确认 |

### 待办事项
- [ ] {task_summary}（截止：{due_date}）
- [ ] {task_summary}

### 小结
- 共 {n} 场会议，{m} 项待办
- 冲突提醒：{列出时间重叠的日程}
- 空闲时段：{free_slots}（根据日程推算）
```

## 数据处理规则

### 1. 时间转换

- API 返回 Unix timestamp + timezone（通常 `Asia/Shanghai`）
- 转换为 `HH:mm` 格式渲染
- **必须用系统命令转换**，不要心算

### 2. RSVP 状态映射

| API 值 | 显示 |
|---|---|
| `accept` | 已接受 |
| `decline` | 已拒绝 |
| `needs_action` | 待确认 |
| `tentative` | 暂定 |

### 3. 日程排序

按 `start_time` 升序。

### 4. 冲突检测

先排除已拒绝日程，按开始时间升序扫描。维护当前组的最大结束时间；下一项开始时间小于该值时加入该组，并更新最大结束时间，否则结束当前组并另起一组。只报告含两项以上的冲突组，首尾相接不算重叠。组内不保证任意两项都冲突；需要列出具体冲突对时，将新日程与仍未结束的活动日程逐一比较。

例如 A 09:00–12:00、B 10:00–11:00、C 11:00–11:30：三者属同一冲突组，实际冲突对为 A–B、A–C；只比较相邻项会漏掉 A–C。

### 5. 已拒绝日程

标注"已拒绝"，但**不计入**忙碌时段和冲突检测。

### 6. 待办排序

- 按截止时间升序
- 已过期标注**"已过期"**
- 无截止时间排在最后

### 7. 空闲时段（可选）

工作日按 9:00-18:00 推算，扣除已接受 / 待确认的日程时间。

## 典型示例

```bash
# A. 今天的摘要（最简）
lark-cli calendar +agenda --as user
lark-cli task +get-my-tasks --as user --due-end "$(date -v+0d +%Y-%m-%dT23:59:59+08:00)"

# B. 明天的摘要
lark-cli calendar +agenda --as user \
  --start "$(date -v+1d +%Y-%m-%dT00:00:00+08:00)" \
  --end   "$(date -v+1d +%Y-%m-%dT23:59:59+08:00)"
lark-cli task +get-my-tasks --as user \
  --due-end "$(date -v+1d +%Y-%m-%dT23:59:59+08:00)"

# C. 这周剩余安排
lark-cli calendar +agenda --as user \
  --start "$(date +%Y-%m-%dT00:00:00+08:00)" \
  --end   "$(date -v+sun +%Y-%m-%dT23:59:59+08:00)"
lark-cli task +get-my-tasks --as user --page-all
```

> macOS `date` 用 `-v+1d`；Linux 用 `date -d 'tomorrow'`——按用户系统调整。

## NEVER 规则（领域特有）

- ❌ **不要给 `+agenda --start "tomorrow"`**——CLI 不识别自然语言；AI 必须计算 ISO 时间。
- ❌ **不要无过滤拉 `+get-my-tasks`** ——爆 context。优先 `--due-end`。
- ❌ **不要心算 / 心做时区转换**——用 `date` 等系统命令。
- ❌ **不要把"已拒绝"日程算进忙碌时段 / 冲突**——它们是空闲。
- ❌ **不要给"无截止时间"任务排在前面**——按截止升序，无截止排末尾。
- 冲突检测按上文“冲突检测”流程处理嵌套区间，不能只比相邻两项。

## 不在本 reference 范围

- 把摘要发到群 / 自己的 IM → [`collab-im.md`](./collab-im.md)
- 把摘要写成飞书文档 → [`content-doc.md`](./content-doc.md) 的“创建文档（默认 Wiki）”流程，并加载 [`content-doc-rich-text.md`](./content-doc-rich-text.md)
- 历史会议（已开过）汇总 → [`workflow-meeting-summary.md`](./workflow-meeting-summary.md)（这是另一个 workflow）

## 溯源

- lark-cli `skills/lark-workflow-standup-report/SKILL.md`（v1.0.0）
