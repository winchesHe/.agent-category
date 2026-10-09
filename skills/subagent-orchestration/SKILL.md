---
name: subagent-orchestration
description: 手动触发的 Codex 子 Agent 编排规范，用于任务拆分、调度与结果验收。
---

# Subagent Orchestration

## 前置条件

- 当前运行环境支持 Codex 原生子 Agent 调度。
- 已读取目标仓库从根目录到目标路径的 `AGENTS.md` 和相关 Skill 规则。
- `.env.example` 是供主 Agent 读取的配置约定；本 Skill 不提供运行时加载器，主 Agent 按配置优先级整理每个子 Agent 的自然语言配置说明。
- 只有独立 worktree 才允许并行写入；共享 worktree 的写入任务串行执行。

## 场景决策树

1. 小范围、单文件、强上下文依赖或需要频繁往返的任务：主 Agent 直接完成。
2. 需要大量探索、独立验证、多个专业视角或可拆分实现的任务：先进入 `plan` 模式，再进入 `execute` 模式。
3. 只读任务或独立 worktree 任务：可并行，数量受 `CODEX_SUBAGENT_MAX_CONCURRENCY` 限制；主 Agent 维护运行中任务集合，超出上限的任务排队，依赖未满足的任务不占用槽位。
4. 共享 worktree、同一文件、同一状态或有前后依赖的写入任务：串行执行。
5. 子 Agent 返回后，主 Agent 必须独立检查 diff、测试、范围和验收证据，不能把自报完成当作最终结论。

## 模式

### `plan` 模式

只读分析，不启动子 Agent，不修改代码。输出一份待确认的 Plan，至少包含：

- 明确的任务目标和非目标；
- 最终可验收的效果：可观察的行为或输出，以及对应的验收条件；
- 工作包列表、允许路径和依赖图；
- 每个工作包的读写边界、并行条件和推荐模型配置；
- 任务合同、验收命令和失败处理；
- 预计需要的复核层级。

Plan 必须能独立交给用户审阅。只有用户明确表示“确认执行”或等价意思后，才能进入执行阶段；模糊表示不算确认。

### `execute` 模式

只消费已确认的 Plan。主 Agent 按 Plan 调度 Codex 子 Agent，执行过程中不能静默扩大范围；如果发现 Plan 不完整或依赖发生变化，应暂停受影响工作包并更新 Plan。

## 主 Agent 工作流

### 1. 建立任务图

先确认需求边界、当前 worktree 状态、适用规则、已有实现和最终验收标准。将任务拆成有明确输入和输出的工作包，标记：

- 文件或目录范围；
- 依赖和冲突；
- 只读或写入；
- 是否需要独立 worktree；
- 验证命令和通过条件。

没有独立边界的任务不要为了并行而拆分。

### 2. 生成任务合同

每个子 Agent 都必须收到：

- 目标和背景；
- 精确允许范围；
- 必须保持的业务不变量；
- 已知输入和相关文件；
- 禁止事项：不得扩大范围、不得再次委派、不得提交或推送；
- 输出格式：改动摘要、测试结果、证据、未完成项、风险；
- 明确的结束条件。

子 Agent 只接收完成任务所需的上下文，不传完整主会话。

### 3. 调度与执行

主 Agent 为每个工作包用自然语言说明要使用的子 Agent 职责、模型、推理档位和任务合同，由 Codex 根据当前运行环境选择原生子 Agent 能力完成调度。本 Skill 不绑定具体工具名、调用参数或创建接口，也不额外封装 CLI runner。

任务合同必须写明已确认的工作目录绝对路径；并行写入前先创建或确认各自独立的 worktree。timeout、sandbox、approval 沿用主 Agent 当前运行配置。

只读调研可以并行。写入任务只有在各自 worktree 独立、文件冲突已排除且主 Agent 能够合并时才并行；否则逐个执行。

子 Agent 返回后，主 Agent 负责审阅 diff、合并或复制经过验证的改动，并在确认不再需要时清理临时 worktree。子 Agent 不提交、不推送。

### 4. 任务复核

每个实现工作包完成后，主 Agent 做一次轻量复核：

1. diff 是否只落在允许范围；
2. 是否满足任务合同和业务不变量；
3. 定向测试或验证命令是否通过；
4. 子 Agent 的证据是否能被主 Agent 独立复现；
5. 是否需要返工、拆分或标记阻塞。

### 5. 整体复核

所有工作包完成后，主 Agent 重新检查跨包接口、依赖顺序、测试覆盖、范围漂移、合并冲突和最终验收。整体复核通过后才向用户报告完成。

## 子 Agent 输出合同

子 Agent 必须返回以下信息：

```text
status: succeeded | failed | blocked
changed_paths: [...]
summary: ...
validation: [{command, result, evidence}]
open_items: [...]
risks: [...]
```

`status=succeeded` 只表示子 Agent 认为工作包已完成，不等于整体任务通过。

状态处理：`succeeded` 进入独立复核；`failed` 由主 Agent 根据证据决定返工或接管；`blocked` 记录阻塞原因，涉及需求或范围决策时暂停并询问用户；超时或失联按失败处理，未验证的产物不得合并。

## 配置

读取 [`.env.example`](.env.example) 中的：

- `CODEX_SUBAGENT_MODEL_VERSION`：子 Agent 模型版本；
- `CODEX_SUBAGENT_REASONING_EFFORT`：推理档位；
- `CODEX_SUBAGENT_MAX_CONCURRENCY`：独立任务并发上限。

配置优先级固定为：用户 prompt 中对当前任务的明确指定 > `.env` 环境变量 > Skill 默认值。用户只覆盖自己明确指定的字段，其余字段继续沿用环境变量或默认值。用户 prompt 没有指定时，主 Agent 不得臆测临时配置。

主 Agent 将解析后的配置与工作包一起用自然语言交给 Codex，例如：“使用一个只读证据核查子 Agent，模型为 `gpt-5.6-sol`，推理档位为 high；本次任务同时运行的子 Agent 最多 3 个。”示例值只有在用户明确指定或配置解析得到时才采用；Prompt 覆盖只对当前任务生效，不修改 `.env`。

配置是否可用以当前运行时能力与实际反馈为准，不在 Skill 中维护模型白名单，也不因工具说明未列出某模型或参数就预判不可用。运行时明确拒绝配置或无法应用指定要求时，停止受影响的调度并说明原因，不静默更换模型或推理档位；未确认生效的配置不得声称已生效。

timeout、sandbox、approval 必须继承主 Agent，不在子 Agent 配置中覆盖。

## NEVER 规则

- 不为简单任务强行启动子 Agent。
- 不把完整会话、无关工具输出或未经核对的结论传给子 Agent。
- 不在共享 worktree 中并行执行写入任务。
- 不允许子 Agent 自行递归委派、改变范围、提交或推送。
- 不把子 Agent 的自报状态当作主 Agent 的验收结论。
- 不为子 Agent 单独设置 timeout、sandbox 或 approval。

## 验证

修改本 Skill 或配置合同后运行：

```bash
python3 /Users/moego-winches/.codex/skills/.system/skill-creator/scripts/quick_validate.py subagent-orchestration
git diff --check -- docs/specs/subagent-orchestration-skill.md subagent-orchestration
```

## References

- `../docs/specs/subagent-orchestration-skill.md`：调整工作流、配置合同或阶段边界时读取。
