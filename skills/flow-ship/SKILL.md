---
name: flow-ship
description: "手动触发的交付收尾工作流：仅当用户明确点名 flow-ship 时使用；在实现完成后整理完成报告、归档 plan、完成 Git 收尾并处理 release。"
---

# flow-ship

## 何时使用

- ✅ 实现完成（所有步 ✅）+ 用户明示"发版 / 收尾 / ship"
- ✅ 裸任务完成（无 spec）+ 用户明示要 ship
- ❌ 还在改代码 / plan 步未全 ✅
- ❌ 用户**未明示**发版意图

## 流程

### 0. 拿到 slug + cwd

- **slug 回查**：按 `flow-spec/SKILL.md § 共享协议 § slug 回查协议`
- **cwd 判定**：按 `flow-spec/SKILL.md § 共享协议 § cwd 判定算法`

### 1. 入场 gate

| 场景 | 处理 |
|---|---|
| 用户**未明示**"发版 / 收尾" | **不主动启动**（等用户对话信号） |
| 无 spec（裸任务）+ 用户明示 | **进入裸任务路径**：跳过 step 1（report 入 spec）+ step 2（归档 plan），直接 step 3-4 |
| spec 存在 + 用户明示 | **准入**正常流程 |
| plan 存在但步未全 ✅ | **拒绝**："还有步未完成，应回 `flow-impl` 补完" |

**plan 完整性校验**（如有 plan，**4 项全过**才准入）：

| 检查项 | 通过条件 |
|---|---|
| 步骤节奏表 | 全 ✅，无 ⏳ |
| `reviewed` 列 | 每行非空 |
| 决策记录段 | Y 步对应 ✅ 行有决策段（N 步不需要） |
| 未确认假设 | spec `§ 假设` 已直接修订（确认事实或保留为 ⚠） |

任一不满足 → **拒绝归档**，列出缺失项让用户回 `flow-impl` 补完。

**git 状态警告**：有未提交修改 / untracked 文件 → 让用户确认是否一起 commit。

### 2. 收尾 4 步流程

#### Step 1：整理 report 入 spec（裸任务跳过）

`Read references/ship-release.md`（含完成 report 6 字段模板，**single source of truth**）→ 在 spec 末尾追加 / 更新 `## 完成 report`：

- **内容来源**：copy `flow-impl` 输出的 6 字段草稿 + 补 `完成日期` + `PR/Commit`
- git add `docs/specs/<slug>.md` + commit："docs: <slug> shipped"

#### Step 2：归档 plan（裸任务 / 无 plan 时跳过）

```bash
mv docs/plans/<slug>.md docs/plans/done/<slug>.md
git add -A && git commit -m "plan: archive <slug>"
```

#### Step 3：git 收尾

- 先读取目标仓库默认分支和仓库级规则，不把 `main` 当成所有项目的固定主线。
- 通用项目：检查当前 branch，切到真实主线并拉取最新代码；按用户偏好（merge / rebase / squash）合入并 push。
- `moego-mobile`：PR 合入主线后的正式发布以 `production` 为主线，不在本步骤再次合并 feature；进入 Step 4 的 Mobile `online` 发布路径。

#### Step 4：release 询问

`Read references/ship-release.md`（含 release-script 调用约定 + 代跑风险）→ 给用户 3 个选项：

- **Mobile 专用路径**：目标仓库是 `moego-mobile` 且用户已明确要求发布时，不调用通用 `release-script`；按 reference 的“`moego-mobile` 发布”流程，从最新 `production` 重建并推送 `online`。
- **a. 终端跑（默认）**：输出命令 `release-script`，结束
- **b. 代跑**：先给**风险提示**得用户确认 → Bash 启动 + 预喂 `y/n` + 监控
- **c. 跳过**：提示"下次 release 命令"后结束

## NEVER

- 不在用户**未明示**"发版 / 收尾"前主动启动 ship
- **裸任务（无 spec）按裸任务路径进入**——不要因为"没 spec"就拒绝
- plan 完整性 4 项任一不满足时不归档（步全 ✅ / reviewed 每行非空 / Y 步有决策段 / spec § 假设 已修订）
- **不跳过 step 1 report 整理**（spec 不完整就 ship = 丢决策记录）
- **不在归档 commit 失败时进入 step 3 git 收尾**（链路要顺序）
- 不在用户没说"代跑"时自动跑 release-script
- **不在用户当前不在项目真实主线时盲目执行 `release-script`**（先确认默认分支与仓库规则，再切主线并 pull）
- **不删除远端分支**；唯一例外是用户明确授权执行 `moego-mobile` 发布时删除远程 `online`，且必须用删除前回读的 SHA 做 `--force-with-lease` 保护。
- 不破坏 git 历史（`push --force` / `rebase --interactive` / `commit --amend`），除非用户明示
- 代跑 release-script 中途异常时不强行继续

## References

- `references/ship-release.md` — step 1（整理 report 入 spec）+ step 4（release 询问）时必读
