# Closure｜关闭、取消与归档

## 标准动作

用户点名关闭、完成、取消或归档时立即执行对应终态同步。Delivery、Release、Observation、驾驶舱或其它阶段是否完整不构成关闭资格；可用事实用于生成遗留清单和结果说明。

## JIT 执行参数

在写入终态时解析唯一 requirement、当前 Jira/Lark/台账对象、用户点名的 Closed/Cancelled 语义、未完成项和已知副作用。外部对象多义时中断；缺某份前序产物时记录 Unknown，不停止。

## Closed

1. 回读当前外部终态对象和已知遗留。
2. 通过 `$jira`/`$lark-skills` 同步用户点名的 Closed 并写后回读。
3. 某个外部系统真实拒绝时，保留其它已回读成功动作，记录失败对象和恢复入口。
4. 存在 workspace 时按 `requirement-workspace.md` 对账驾驶舱和索引；本地记录失败不反转外部关闭结果。
5. 将缺失观察、未完成项和副作用作为 Closure Limitations/遗留记录，而不是前序门禁。

## Cancelled

用户明确取消时记录原因、已完成资产、当前外部状态、副作用和可恢复入口，随后同步 Cancelled 并回读。Cancelled 不因 Navigate 自动重开。

## 重开

Closed/Cancelled 重开需要用户明确意图。使用当前稳定对象执行恢复，不覆盖原终态历史；历史解除证据不构成重新执行的资格。

## 结果与回读

- 每个实际外部对象的终态和回读结果分别列出。
- 外部拒绝、权限问题或目标多义才记录真实 Blocked。
- 缺前序阶段、观察窗口未完成或驾驶舱不存在只进入 Limitations/遗留。
- Experience 候选可在结果后按需提炼，不影响终态同步。
