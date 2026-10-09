---
name: flow-spec
description: "手动触发的产品设计工作流：仅当用户明确点名 flow-spec 时使用；通过 brainstorm、代码探索和评审，将新功能或重构整理为可执行、可验收的 spec。"
---

# flow-spec

## 关联 skill 调用协议

`flow-spec` 是 flow-* 工作流的入口和关联协议 source of truth。各 skill 均由用户手动触发，不根据 description 自动串联：

| 当前阶段 | 关联 skill | 处理 |
|---|---|---|
| spec 前需要梳理问题 | `flow-brainstorm` | 在 step 1 使用其方法；若用户已从该 skill 移交，跳过重复 brainstorm |
| spec 已落盘并经用户明示对齐 | `flow-impl` | 告知用户可点名 `flow-impl` 开始实现；未点名前停在当前阶段 |
| 实现与验证全部完成 | `flow-ship` | 告知用户可点名 `flow-ship` 收尾；未点名前不执行归档、合并或 release |

`flow-impl` / `flow-ship` 启动后仍须按各自入场 gate 检查文件状态，用户点名不代表可以跳过 gate。

## 何时使用

- ✅ 做新功能 / 重构 / 涉及不熟模块前，写**产品设计图**（架构 / 数据 / 接口 / 验收链路 / 后续实现顺序 / 改动范围）
- ✅ 多步骤 / 跨仓改动
- ✅ 想让 spec 跟代码一起 PR 留底
- ❌ 单文件 typo / 一次性脚本（直接改）
- ❌ 已有 spec 的继续实现（用 `flow-impl`）
- ❌ 纯调研 / 概念解释（直接对话回答）

## 流程

### 1. brainstorm（详见 `flow-brainstorm` SKILL.md）

按 `flow-brainstorm` 做意图对齐 + 发散思维。**若已从 flow-brainstorm 移交过来 → 跳过本步**。

最重要 2-3 条（风险 / 假设 / reframe）入 spec `§ 风险 / § 假设`。

### 2. explore（默认查 repo 代码 + 用户按需用业务上下文）

**默认范围**（Claude 主动调用）：

| 工具 | 用途 |
|---|---|
| `github-workflow` | 远端 grep / 读源码 / 跨仓搜索 |
| `Read` + `Grep` | 本地仓库文件读取 + 模式搜索 |
| `WebFetch` / `WebSearch` | 开源 / 第三方依赖文档 / RFC / issue |


**explore 结束自检**（内部判断，不写入 spec 正文）：

```
- feature flag: [Y/N]
- 跨 ≥ 2 仓库 / SDK: [Y/N]
- 有外部 caller: [Y/N]
- schema / proto / API 字段改动: [Y/N]
```

这组判断只用于后续 plan 4 指标判定，**不要**在 spec 中创建 `## 涉及矩阵` 章节，也不要把矩阵表落进 spec。

**跨仓 spec 落盘**：若探索发现跨 ≥ 2 仓库 → **明问用户**"主驱动仓库是前端还是后端？"（不要 agent 拍脑袋估"改动量最大"）

**停止条件**（任一即停）：

- 能回答 spec 核心字段 + 改动范围 + 验收链路 + plan 判定信息
- ≥ 3 个独立查询仍未拿到答案 → 标 ⚠ 假设 + 注明"已尝试 X / Y / Z"
- 工具失败 / 超时 → 标 ⚠ 假设 + 注明原因（**不假装已验证**）
- 假设 ≥ 3 条堆积 → 回 brainstorm 做 1 次澄清
- 用户主动说"够了"

### 3. 起草 spec（必须 `Read references/spec-template.md`）

**spec = 产品设计图 + 实现路径 + 验收 + 代码改动范围**（对标 superpowers spec 形态）。

必有章节：概述 / 目标 / 非目标 / 假设 / 风险 / 验收链路 / 后续实现顺序 / 参考。

按产品形态自由组织子章节：工作区结构 / 数据模型 / 接口设计 / 子系统 / 配置 / 安全策略 / 改动范围。

**允许写技术细节**：TypeScript types / SQL schema / TOML config / 接口签名 / CLI 命令 / 数据流图 / 数据库字段表。

**slug 规则**：

- kebab-case `[a-z0-9-]`，≤ 40 字符
- 任务名意译英文；如"OB 新客 birthday 提醒" → `ob-new-client-birthday-alert`
- 冲突追加 `-YYYYMMDD`，**不覆盖**
- 永远 lowercase
- **Write 前显式告诉用户 `slug = <slug>`**

**落盘位置**：按 `## 共享协议 § cwd 判定` 拿到当前业务仓库根 + `docs/specs/<slug>.md`。

**无 frontmatter**：spec 是普通 markdown。

### 4. 用户 review → 明示对齐

落盘后等用户**明示**"OK / approved / 可以"。**模糊回复不算确认**。

### 5. plan 4 指标判定（实现路径细化到执行节奏）

spec 的 `## 后续实现顺序` 是**高层路径**。是否需要展开为**执行节奏**（步骤节奏表 + 观察点 + 验证方式 + reviewed + Y-only 决策记录）？

| # | 指标 | 判定方式 |
|---|---|---|
| 1 | spec `§ 后续实现顺序` 步骤 ≥ 5 行 | 数 spec 文件 |
| 2 | 跨 ≥ 2 个仓库 / 子项目 | = explore 内部判断第 2 项 |
| 3 | 涉及 schema / 数据迁移 / 协议改动 | = explore 内部判断第 4 项 |
| 4 | 用户**明问**"你熟这个模块吗" → N | 必问用户 |

输出 4 项 Y/N + 命中数。

- 命中 ≥ 2 → `Read references/plan-template.md` → 起草 `docs/plans/<slug>.md`（slug 与 spec 一致）
- 命中 < 2 → 只 spec，flow-impl 按 spec `§ 后续实现顺序` 整体实现 + verify

## 共享协议（flow-* single source of truth）

### § slug 回查协议

flow-impl / flow-ship 启动时拿 slug 的优先级：

| 优先级 | 来源 | 方法 |
|---|---|---|
| 1 | git branch | `git branch --show-current` 反查；约定分支名 `<type>/<slug>` 或 `<slug>` |
| 2 | docs/specs/ 扫盘 | 列最近修改的 spec 让用户选 |
| 3 | 用户复述 | 要求粘贴 spec **路径**（不是 slug 字面值，避免 typo） |

### § cwd 判定算法

判定"当前业务仓库根目录"：

| 场景 | 方法 |
|---|---|
| 默认 | `git rev-parse --show-toplevel` |
| worktree | worktree 内 |
| monorepo（pnpm workspace / nx / turborepo） | workspace root（`pnpm-workspace.yaml` / `package.json` `workspaces`） |
| 跨 ≥ 2 仓库 | **明问用户主驱动仓库**；fallback：前后端各半优先后端 |

cwd 与 spec 物理位置不一致 → 提示用户切换 cwd，**不自动 cd**。

### § spec 偏差直接改原文

implement 中发现 spec 失真：

- **直接改 spec 原文**（修改原章节）
- **不创建 `## 调整记录` 章节**
- git commit 必须写清 `调整 spec § X：<原因>` → git diff 即留底

### § 阶段衔接（无 status frontmatter）

3 个 skill 衔接靠**用户对话信号 + 文件状态**：

| 阶段判定 | 信号 |
|---|---|
| spec 起草完成 | spec 文件已 Write + 用户**明示**对齐 |
| 可进 flow-impl | 用户**明示**"开始实现 / 按 spec 做 / 直接动手" |
| flow-impl 进行中 | plan 步骤节奏表有 ⏳ 行（有 plan）/ spec 文件存在（无 plan 走整体实现） |
| 可进 flow-ship | 用户**明示**"发版 / 收尾 / ship"；如有 plan 则步全 ✅ |

## NEVER

- 默认 explore **不主动调用业务上下文 skill** —— 等用户 trigger
- explore 失败 / 拿不到数据时**不静默继续**——标 ⚠ 假设 + 注明原因
- 不在 explore 结束未完成内部影响判断时落 spec
- **不在 spec 中写 `## 涉及矩阵` 章节，也不把内部判断矩阵表落盘**；矩阵只服务 plan 判定
- **不在 spec / plan 隐藏假设**（必须 ⚠ 标明）
- **不把 spec 和 plan 写在同一个文件**（关注点分离：spec = 设计图，plan = 执行节奏）
- 不自创 `process.md` / `notes.md` 等过程文件
- slug 冲突时不覆盖已有文件（追加 `-YYYYMMDD`）
- **不在用户未确认 slug 时落盘 spec**
- **不跳过 brainstorm 的发散思维**（风险 / 假设至少各 2-3 条入 spec）
- 实际涉及 feature flag / 跨仓 · SDK / 外部 caller / schema 时，按业务需要补充灰度 / 依赖 / 回归点等正文信息，但不要以矩阵形式记录
- **plan 写描述性子模块设计**（行为 / 流程 / 状态机 / 命令链）；**不写代码 / 伪代码 / 接口签名**（接口签名在 spec `§ 接口设计` 已有）；spec 写全局产品设计图

## References

- `references/spec-template.md` — 起草 spec 文件前必读（step 3）
- `references/plan-template.md` — 4 指标命中 ≥ 2 时必读（step 5）
