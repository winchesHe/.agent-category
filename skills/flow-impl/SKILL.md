---
name: flow-impl
description: "手动触发的代码实现工作流：仅当用户明确点名 flow-impl 时使用；按已有 spec 或 plan 实现、逐步验证，并同步设计偏差与完成记录。"
---

# flow-impl

## 何时使用

- ✅ 承接 `flow-spec`：spec 已落 `docs/specs/<slug>.md`；按 spec `§ 后续实现顺序` 实现（有 plan 时按 plan 步骤节奏循环 + 活更新；无 plan 时按 spec 整体实现）
- ✅ 裸任务：简单单文件 / typo / 一次性脚本 / 小修
- ❌ 用户**未明示**"开始实现 / 按 spec 做 / 直接动手"（等用户 trigger）
- ❌ spec 还在 draft / review 阶段（回 `flow-spec`）
- ❌ 纯调研 / 文档 / 答疑（不进 implement）

## 流程

### 0. 拿到 slug + cwd

- **slug 回查**：按 `flow-spec/SKILL.md § 共享协议 § slug 回查协议`（git branch → 扫盘 → 用户路径）
- **cwd 判定**：按 `flow-spec/SKILL.md § 共享协议 § cwd 判定算法`

cwd 与 spec 物理位置不一致 → 提示用户切换 cwd，**不自动 cd**。

### 1. 入场 gate

| 场景 | 处理 |
|---|---|
| 无 spec 文件 | 仅当裸任务允许（单文件 / typo / 一次性脚本）；否则建议先 `flow-spec` |
| spec 存在 + 用户**未明示**"开始实现 / 直接动手" | **等待**（可能用户还在 review spec） |
| spec 存在 + **有 plan** + 用户明示 | **准入：按 plan 步骤节奏循环**（走 §2A） |
| spec 存在 + **无 plan** + 用户明示 | **准入：按 spec § 后续实现顺序整体实现 + verify**（走 §2B） |
| plan 步全 ✅ | 提示"全部步已完成，应进 `flow-ship`" |

判定逻辑：用户对话信号 + 文件状态（不依赖 status frontmatter）。

### 2A. 有 plan：步骤节奏循环

```
对每个 ⏳ 步：

1. 读 spec § 相关章节 + plan § 步骤节奏（该步）+ § 未确认假设
2. 写代码：内联注释非 obvious 的 why（不写 what / 不写 PR 号 / 不写设计史）
3. 跑 verify：用 plan 的"观察点 + 验证方式"命令；输出引用到对话
4. 偏差回流（如发现 spec 失真）：按 `flow-spec § 共享协议 § spec 偏差直接改原文`
   （直接改原文 + git commit 写清"调整 spec § X：<原因>"）
5. plan 活更新：
   - Read references/impl-records.md（Y/N 判定 checklist + Y 时模板）
   - 步骤节奏表当前行 ⏳ → ✅ + reviewed 列填 `YYYY-MM-DD`（**无论 Y/N**）
   - Y 时追加决策段
6. 进入下一步
```

**步粒度**：1-2 次会话内完成。超过 → 重切，不硬撑。

### 2B. 无 plan：按 spec § 后续实现顺序整体实现

按 spec `§ 后续实现顺序` 的步骤逐步实现（spec 已含高层路径 + 验收链路）。

- 每步完成跑 spec `§ 验收链路` 中对应命令 + 引用输出
- 实现中发现 spec 失真：**直接改 spec 原文** + git commit 写清"调整 spec § X：<原因>"
- 整体完成 → 输出完成 report 6 字段草稿（见 §4）

**何时建议升级到 plan**：实现中发现步骤多于预期 / 跨仓更复杂 / 不确定假设堆积 → 建议用户回 `flow-spec` 起 plan（4 指标可能现在命中 ≥ 2）。

### 3. verify 硬铁律

- claim 步完成**前**必须跑 verify 命令 + 引用输出到对话
- "跑测试" ≠ "verify"——是 **plan 的"观察点 + 验证方式"** 或 **spec `§ 验收链路`** 中预设的命令 / 断言 / UI 检查 / 数据查询
- verify 失败 → 不切步状态、不进下一步
- 连续 ≥ 3 次失败 → 回 step 2 重写代码 OR 走偏差回流改 spec 步骤定义，**不能调 verify 命令**

### 4. 全部完成 → 输出完成 report 6 字段草稿

`Read references/impl-records.md` → 按字段表输出对话回复（**不进独立文件**）。

模板 source of truth 在 `flow-ship/references/ship-release.md`；flow-impl 这里只产出**草稿**（缺完成日期 + PR/Commit，由 flow-ship 补）。

## 内联注释规则

| ✅ 写注释 | ❌ 不写注释 |
|---|---|
| 非 obvious 业务约束（如 `NBSP because flex collapses`） | 重复代码本身（"add 1 to x"） |
| 跨文件不变式（"must sync with X.Y"） | 重复方法名 / 类型 |
| workaround 标记 + 原因 | 任务编号 / 当前 PR 号（rot 风险） |
| 已知限制 + 后续计划 | 设计史 / 个人感想 |

## NEVER

- 不在用户**未明示**"开始实现 / 直接动手"前主动启动 implement
- verify 未跑 / 输出未引用 / verify 失败时不 claim "步完成"（不切 ⏳ → ✅）
- 不创建独立 `process.md` / `notes.md` 等过程文件
- **代码注释里不写任务编号 / 当前 PR 号 / 设计史**（rot 风险）
- **改 spec 原文时 git commit 必须写清"调整 spec § X：<原因>"**（按 flow-spec § 共享协议）
- 不跳过 plan `reviewed` 列填写（即使 N 也要标日期）+ Y 步必填决策段（仅有 plan 时适用）
- **步粒度超 1-2 会话时不硬撑**（应重切；无 plan 时建议升级到 plan）
- **plan 写描述性子模块设计**（行为 / 流程 / 状态机）；**不写代码 / 伪代码 / 接口签名**（接口签名在 spec `§ 接口设计` 已有）
- **纯调研 / 文档 / 答疑任务不进入 implement**

## References

- `references/impl-records.md` — 每步完成回填 plan 决策段（§2A.5）+ 任务完成时输出 report 草稿（§4）必读
