# flow-\* vs superpowers vs OpenSpec 对比

> 本文档解释 `flow-spec / flow-impl / flow-ship` 三个 skill 与社区现有 spec-driven workflow 的核心差异。
> 配套 `SKILL.md`（执行入口）+ `references/`（模板）+ [`docs/specs/flow-spec-skill.md`](../docs/specs/flow-spec-skill.md)（设计依据）。

## 一句话定位

- **flow-\***：spec = 产品设计图 + 实现路径 + 验收 + 改动范围（**同 superpowers spec 形态**）；plan = 执行节奏（独立可选）；用户对话信号 + 文件状态驱动
- **superpowers**：硬强制 skill 触发；spec + plan 一并落盘到 `docs/superpowers/specs/`；偏团队严格工程纪律
- **OpenSpec**：命令 + 状态机驱动；spec 是**演进的契约**走 propose-apply-archive；偏团队协作 + 审计

## 详细对比

| 维度 | flow-\* | superpowers | OpenSpec |
|---|---|---|---|
| **触发模式** | description 关键词 + 用户对话信号 | "1% 也必须调用"硬强制 | 显式命令 `/opsx:propose` 等 |
| **流程强制度** | brainstorm 永远做但已对齐可跳过提问；plan 4 指标命中 ≥ 2 才建议 | brainstorm/plan/TDD/verify 全 MUST | propose → apply → archive 阶段命令 |
| **spec 形态** | **产品设计图 + 实现路径 + 验收 + 改动范围**（架构 / 数据 / 接口 / 子系统 / 验收链路 / 后续实现顺序）；含技术细节 | 同等形态：含 schema / 接口 / 验收 / 后续实现顺序 | spec.md + design.md + tasks.md（多产物） |
| **plan 颗粒度** | **子模块级描述性设计 + Chunk 化执行节奏**（行为 / 流程 / 状态机 + Chunk 划分 + Observability Checkpoint + 步骤节奏表 + 验收 + reviewed + Y-only 决策）；**不嵌代码 / 接口签名 / 测试代码**（接口签名在 spec） | 跟 spec 混合（一份 doc）；含完整代码 + tests + step 级 commit | tasks.md（checklist） |
| **决策冻结风险** | 低（spec 偏差直接改原文 + git diff 留底；plan Y-only 活更新） | 高（plan 写完锁定，不鼓励 inline 调整） | 中（fluid not rigid 口号，但 4 份产物心理权威） |
| **产物数** | spec（必）+ 可选 plan（执行节奏）+ 完成 report 入 spec | spec + plan 一份 / 散落 memory | 每 change 4 份（proposal / spec / design / tasks） |
| **状态机** | **无**（靠用户对话信号 + 文件状态） | 隐式（skill 调用顺序） | 显式（status / archive 等） |
| **brainstorm 含义** | 意图对齐 + 发散思维（风险 / 可行性 / reframe） | 5 问 checklist 挖意图 | 内嵌 propose 无独立 |
| **explore 含义** | 查 repo 代码作证据 + 业务上下文用户主动调用 | 无独立 explore | `/opsx:explore` codebase 调研模式 |
| **NEVER 数量** | 每 SKILL 5-7 条（精简过） | 每 skill 都有 NEVER + 硬强制段 | 不显式 |

## 3 个核心向量

### 1. spec 形态：**flow-\* ≈ superpowers spec**

| | spec 长什么样 |
|---|---|
| **flow-\*** | 产品设计图（含架构 / 数据 / 接口 / 子系统 / 配置 / 安全 / 改动范围 / 验收链路 / 后续实现顺序）；允许写技术细节 |
| superpowers | 同等形态：含 schema / 接口 / 验收 / 后续实现顺序 |
| OpenSpec | spec.md（要求）+ design.md（技术方案）+ tasks.md（checklist）—— 拆 4 份 |

→ flow-\* 学习 superpowers spec 形态；但**把"执行节奏"剥离到 plan**，关注点分离

### 2. 防决策冻结的处理

| | 方式 |
|---|---|
| **flow-\*** | spec 偏差**直接改原文** + git diff 留底；plan **Y-only 活更新**（只在影响后续步时写决策段） |
| superpowers | plan 写完锁定，鼓励"按 plan 实现"，不鼓励 inline 调整 |
| OpenSpec | fluid 口号但 4 份产物已落盘，心理上"权威化"；要改要 propose 新 change |

### 3. 与状态机的关系

| | 衔接方式 |
|---|---|
| **flow-\*** | 用户对话信号 + 文件存在性 + plan 完整性 |
| superpowers | skill description 内嵌触发条件 + skill 之间调用 |
| OpenSpec | 显式状态字段 + 命令切换（propose / apply / archive） |

→ flow-\* 是**最轻量**（无状态字段、无命令、靠对话）

## 适合 / 不适合

| | 适合 | 不适合 |
|---|---|---|
| **flow-\*** | 个人快速迭代 + 想要"产品设计图同形态 superpowers spec"+ 关注点分离 plan / 防过度仪式 | 多人审计场景 / 严格状态机要求 |
| superpowers | 强工程纪律团队 / 严格 TDD / 大型复杂任务 | 个人小任务（过度仪式） |
| OpenSpec | 团队协作 + spec 审计 + 跨会话 handoff + 需求频繁 pivot | 单人快速 prototype |

## 你为什么自建（核心痛点对照）

| 痛点（基于 sessions 调研） | superpowers 的对应 | flow-\* 的对应 |
|---|---|---|
| token 多、过度仪式 | 强制 5 问 + 强制 plan | 已对齐跳过提问；plan 4 指标可选 |
| plan 锁实现节奏 | plan 写完锁定 | spec **可改**（直改原文 + git diff）；plan **Y-only 活更新** |
| 决策冻结，实现僵化 | 无法 inline 调整 | 偏差直改 spec 原文 + plan reviewed 列 + Y 时决策段 |
| 三步固定模式（合入 → main → release-script） | 无专门 ship | flow-ship 完整覆盖 + 询问代跑 |
| 反对独立 process.md | 每个 skill 各自生产文档 | **明令禁止**独立过程文件 |
| brainstorm 太薄 / 太机械 | 5 问 checklist | 意图对齐 + 发散思维（风险 / 可行性 / reframe） |
| explore 业务调研过重 | 无 explore 概念 | 默认查 repo 代码 + 业务上下文用户主动调用 |
| status frontmatter 状态机复杂 | 无（但 skill 间调用复杂） | 删 status，靠用户对话信号 + 文件状态 |

## 借鉴 vs 没采用

| 来源 | 借鉴的点 | 没采用的点 |
|---|---|---|
| superpowers `brainstorming` | brainstorm 在写代码前必做 | 5 问 checklist / 机械流程 |
| superpowers `writing-plans` | spec 含验收 + 后续实现顺序；切片要有验证点 | 强制触发 / plan 锁死 / spec + plan 混一份 |
| superpowers spec 形态 | **产品设计图 + 实现路径 + 验收 + 改动范围**（直接对标） | 不分 spec / plan（flow-\* 拆开） |
| superpowers `verification-before-completion` | verify 硬铁律（claim 完成前必跑命令引用输出） | 其他繁重 checklist |
| OpenSpec `tasks.md` | spec / plan 一组、可归档 | 独立 tasks.md / propose 阶段一次写完 |
| OpenSpec `/opsx:explore` | explore 是 codebase 调研、不是 user 问答 | 独立命令 / 强 thinking partner mode |
| OpenSpec "fluid not rigid" | spec 直接改原文反映当前真相 | 4 份产物落盘 / archive 流程 |
| Cursor Plan Mode | 实现中 inline 调整 | UI 锁死视图 |
| 用户 `CLAUDE.md` | 步设计"能跑 / 能观察 / 能验证" + 端到端最小骨架 | —— |

## flow-\* 的核心存在意义

不是替换 superpowers / OpenSpec，而是为**特定场景**（个人 / 小团队快速迭代 + 想要产品设计图同形态 + plan 关注点分离 + 防过度仪式）造的轻量版。

如果你做：
- 团队 spec review + 严格审计 → 用 OpenSpec
- 强 TDD + 团队工程纪律 → 用 superpowers
- 个人 / 小团队快速迭代 + spec 跟代码 PR 留底 + plan 关注点分离 → 用 flow-\*
