# flow-brainstorm vs superpowers brainstorming 对比

> 本文档解释 `flow-brainstorm` 与 superpowers `brainstorming` skill 的核心差异。
> 配套 `SKILL.md`（执行入口）+ [`docs/specs/flow-brainstorm-skill.md`](../docs/specs/flow-brainstorm-skill.md)（设计依据）。

## 一句话定位

- **flow-brainstorm**：按需触发 + 已对齐可跳过 + 2 步轻量 + 默认对话不落盘。**"按需求强度调整深度"**
- **superpowers brainstorming**：spec-driven 信仰 + HARD-GATE 强制 + 7 步 fixed checklist + 必落盘 design doc。**"每个项目都要走"**

## 详细对比

| 维度 | flow-brainstorm | superpowers brainstorming |
|---|---|---|
| **强制度** | 软触发；已对齐可**跳过提问** | `<HARD-GATE>`：未 brainstorm + design approved 前**禁止**写任何代码 |
| **流程步数** | **2 步**（意图对齐 + 发散思维） | **7 步 fixed checklist** + DOT 流程图 |
| **问问题方式** | **≤ 2 问聚焦**，问完即收敛 | **one at a time** 深挖（"理解 purpose / constraints / success criteria"） |
| **提议方案数** | **条件强化**：用户问"怎么做 / 什么方案"时主动列 2-3 个；其他场景不强制 | **强制** 2-3 approaches + trade-offs + 推荐 |
| **设计落盘** | 默认主对话输出；不主动创建文件 | 必落 `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` + git commit |
| **分段 approval** | 整体 brainstorm 结束后用户决定下一步 | design 分段呈现 + **每段获用户批准** |
| **移交目标** | flow-spec / flow-impl / 对话继续（**可选**） | **强制** `writing-plans` skill |
| **额外能力** | 无 | visual companion（视觉问题独立 message 提供） |
| **anti-pattern 反对** | "every project needs a design"——刻意允许跳过 | "this is too simple to need a design"——明令反驳 |
| **失败模式** | 复杂任务挖得不够深 | 小项目过度仪式 / token 浪费 |

## 3 个核心理念差异

### 1. 「每次必走」 vs 「按需触发」

| | 方式 |
|---|---|
| **superpowers** | spec-driven 信仰——所有项目都要 design + approval。Anti-pattern 段明令反驳"too simple" |
| **flow-brainstorm** | 已对齐可跳过；信任用户对自己意图的判断；**承认"too simple"是合法的** |

### 2. 「分段 approval」 vs 「一次输出」

| | 方式 |
|---|---|
| **superpowers** | 渐进 + 每段获批准（防 big bang reveal） |
| **flow-brainstorm** | 一次性 2-3 条要点 + 用户决定下一步 |

### 3. 「必落盘 design doc」 vs 「默认对话」

| | 方式 |
|---|---|
| **superpowers** | design doc 是持久化产物，git commit 留底 |
| **flow-brainstorm** | brainstorm 默认是**对话产物**；用户明示才入 spec（移交给 `flow-spec`） |

## 借鉴 vs 没采用

| 来源 | 借鉴 | 没采用 |
|---|---|---|
| superpowers `brainstorming` | ✅ "brainstorm 在创作前先做"的核心理念 ✅ "提议多方案"思路（条件强化版） | ❌ HARD-GATE / ❌ 7 步 fixed checklist / ❌ 强制 2-3 approaches（改为条件强化） / ❌ 必落盘 design doc / ❌ 分段 approval / ❌ "too simple" anti-pattern 反驳 |

### 关于 7 步 fixed checklist

superpowers 的 7 步：
1. Explore project context
2. Visual companion
3. Ask clarifying questions（one at a time）
4. Propose 2-3 approaches
5. Present design sections（每段 approval）
6. Write design doc
7. Transition to writing-plans

**flow-brainstorm 不采用**——理由：

| superpowers 7 步 | 在 flow-* 里的归属 |
|---|---|
| 1. Explore project context | 已在 `flow-spec` step 2 explore（查 repo 代码） |
| 2. Visual companion | 暂未需要 |
| 3. one at a time 深挖 | **跟 flow-brainstorm "≤ 2 问聚焦" 哲学冲突** |
| 4. Propose 2-3 approaches | **条件加入**（用户问"怎么做"时） |
| 5. 分段 approval | 已在 `flow-spec` step 3-4（起草 + 用户明示对齐） |
| 6. Write design doc | 已在 `flow-spec` step 3（落 `docs/specs/<slug>.md`） |
| 7. Transition to writing-plans | 已在 `flow-spec` step 5（4 指标判定 plan） |

加进 flow-brainstorm 会导致 **5/7 步和 flow-spec 流程职责重叠**——违背抽离 brainstorm 的初衷。

### 关于"强制 2-3 approaches"的折中

**核心判断**：这条**真有价值**，但不能 fixed 强制。

| 场景 | flow-brainstorm 行为 |
|---|---|
| "帮我 brainstorm 下 X **怎么做**" | ✅ 列 2-3 方案 + trade-offs + 推荐 |
| "加个 toggle 控制" | ❌ 不强制（实现路径明确） |
| "**有什么风险**" | ❌ 不强制（不是问方案） |
| "**reframe 一下**需求" | ❌ 不强制（不是问方案） |

判定靠**用户语义**（"怎么做 / 什么方案 / 几种思路" 触发；其他场景照常发散思维不堆方案墙）。

## 适合 / 不适合

| | 适合 | 不适合 |
|---|---|---|
| **flow-brainstorm** | 个人快速迭代 / 单点发散思考 / 1 对 1 对话 / 想要"快速对齐就动手" | 多人协作的严格 design review |
| **superpowers brainstorming** | 团队中大型项目 / 正式 spec-driven 流程 / 有 PM/lead 把关 design / 需要审计 | 个人小任务（仪式过度，token 浪费） |

## 你为什么自建（痛点对照）

| 痛点 | superpowers 的对应 | flow-brainstorm 的对应 |
|---|---|---|
| 过度仪式 | HARD-GATE + 7 步 fixed checklist | 软触发 + 2 步 + 已对齐跳过提问 |
| 问问题太多太机械 | one at a time 深挖每个 question | ≤ 2 个聚焦问题，问完即收敛 |
| 不需要 design doc 落盘 | 必落 `docs/superpowers/specs/` + commit | 默认主对话输出，不主动创建文件 |
| 不需要每段 approval | 分段呈现 + 每段获批准 | 一次输出 2-3 条要点 |
| 多方案不强制但有价值 | 必须 2-3 approaches + trade-offs | **条件强化**（用户问"怎么做"时） |
| 移交不该强绑 writing-plans | 强制 → writing-plans | 可选 → flow-spec / flow-impl / 对话继续 |

**关键差**：superpowers 是 **"先 design 才能动手"** 的信仰；flow-brainstorm 是 **"对齐意图后就可以动手，发散思维是辅助而不是 gate"**。

## 关于 OpenSpec brainstorming

OpenSpec **没有独立的 brainstorming** —— 意图对齐内嵌在 `/opsx:propose` 阶段（自动生成 proposal / spec / design / tasks 4 份产物）。

OpenSpec 的 `/opsx:explore` 是 thinking partner mode 调研 codebase（≈ `flow-spec` 的 explore step），跟 brainstorm（跟人对话）**不是一回事**。

详见 [`flow-spec/README.md`](../flow-spec/README.md) flow-\* vs superpowers vs OpenSpec 全景对比。
