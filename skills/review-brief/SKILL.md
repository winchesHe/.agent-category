---
name: review-brief
description: >-
  从真实 PR、branch、revision range 或 worktree diff 生成或更新统一中文 Review Brief，帮助 Reviewer 快速理解改动背景、主要行为变化、推荐阅读顺序、Review 重点与发布风险，复杂流程可生成技术图。用户要求 PR Description/PR Body、Reviewer Brief、改动导览、阅读顺序、帮助 Reviewer 理解变更，或把同一份 Brief 准备给 GitHub/Slack 时必须使用，即使用户没有点名 review-brief。只负责变更理解与内容渲染；找 bug、P0-P3、Approve/Request changes 使用 review-swarm，独立技术图使用 fireworks-tech-graph，代码实现与修复不触发。
---

# Review Brief

把真实改动转成面向人类 Reviewer 的阅读导览。文字是完整骨架，图只是跨组件关系确实难以用短文字讲清时的增强。

## 场景决策树

```text
用户目标
├─ 生成/更新 PR 描述、PR Body、Reviewer Brief、改动导览
│  └─ 进入 Review Brief 流程
├─ 解释一个变更应按什么顺序读、哪些位置重点看
│  └─ 进入 Review Brief 流程
├─ 把已生成 Brief 准备给 GitHub 或 Slack
│  └─ 先生成统一模型，再加载渠道合同；外部发布交给 owner Skill
├─ 找 bug、输出 finding、Approve 或 Request changes
│  └─ 使用 review-swarm，不生成 Brief
├─ 实现、修复或重构代码
│  └─ 使用实现工作流，不生成 Brief
├─ 只画与代码变更无关的技术图
│  └─ 使用 fireworks-tech-graph
└─ 解释静态文件当前做什么，没有变更来源
   └─ 普通代码理解，不生成 Brief
```

相邻路由请求应简短说明为什么不生成 Review Brief，并明确指出负责该任务的 owner Skill（例如 `review-swarm` 或 `fireworks-tech-graph`）；不要在当前 Skill 内继续模拟执行。

## 工作流

### 1. 锁定变化范围

只面向变化，不提供静态文件模式：

- GitHub PR：通过 `github-workflow` 获取 repo、base、head、PR 元数据和完整 diff。
- branch：使用用户指定 base、PR base 或仓库确认的集成分支，以 merge-base 计算增量。
- revision range：使用用户给出的明确 range，不把工作区改动混入。
- worktree：分别读取 staged、unstaged 与 untracked；不要用一个组合 diff 掩盖 index 和 worktree 的反向变化。

生成完整 PR Body 时必须覆盖完整目标 diff。路径过滤后的结果只能标为 scoped draft，不能替换完整 PR Description。没有 diff、base 不明确或目标身份不唯一时停止，说明缺失信息，不猜最近文件或分支。

### 2. 建立可信上下文

按以下顺序读取：

1. 目标路径适用的 `AGENTS.md` 与仓库工作流规则。
2. 已确认的需求、Issue、PR 描述、设计文档或当前对话决策。
3. 影响行为的 diff、关键调用方、契约及表达既有行为的测试。
4. 解释跨组件关系所需的直接依赖与消费方。

将“已确认意图”和“从 diff 可证明的行为”分开。缺少业务原因时，只陈述可观察变化；若发布内容会因此误导，发布前只问一个会改变结果的问题。不得把文件名、分支名或模型推断写成确认事实。

对可访问性、并发安全、幂等性等需要运行时或组合证据才能成立的性质，只说明 diff 中可见的属性、分支和数据流，不把单个属性存在推导成效果已经成立。图标题、节点和箭头也必须保留真实职责边界；一个入口同时负责持久化与排队时，不得概括为“只负责排队”。

### 3. 选择 Lite 或 Full

不要用纯行数或 changed files 数量决定模式；先排除生成物、格式化、快照与机械重命名。

使用 **Lite**，需同时满足：

- 只有一个自洽行为，入口明显；
- 不需要跨多个行为文件核对同一规则；
- 没有复杂状态迁移、异步交互或多系统数据流。

命中任一情况使用 **Full**：

- 同一能力跨至少两个行为文件、层或组件，需要按因果顺序阅读；
- 同时涉及入口、领域规则、状态/持久化、外部副作用或消费方中的多个环节；
- 涉及异步任务、事件、重试、补偿、兼容迁移或跨边界数据转换；
- 文件顺序会明显误导 Reviewer。

Full 必须给出 3–7 步推荐阅读路线。进入 Full 不等于必须画图。

### 4. 生成统一语义模型

生成或渲染 Brief 时，完整读取 [output-contract.md](references/output-contract.md)。先形成 ReviewBrief 语义对象，再渲染 Markdown；不要在 GitHub、Slack 或其他 Skill 中另造字段和删减规则。

只要需要保存本地产物、生成技术图或把内容交给 GitHub/Slack，必须同时生成 `review-brief.json`：先写入统一模型与内部产物元数据，再执行 `node scripts/review-brief.mjs finalize <path>` 写入 `content_hash`，随后执行 `check`。下游只能消费通过校验的 JSON，不能从 Markdown 反向猜字段。

概要与主要变化固定存在。推荐阅读路线、技术图、Review 重点、风险与发布、关联资料只在有有效内容时出现，空章节直接删除。

面向人类组织内容时优先保证层级清楚：

- 概要使用 2–4 个短句；存在两个独立结果时用空行分成短段，不把入口、实现、验证和风险压成一个长段落。
- Lite 的主要变化直接渲染为简短列表。
- Full 先识别 2–4 条同层级主线；一条主线包含多个从属行为时使用 `points`，通常保留 2–5 个有标题的要点，不把每个细节都提升为同层级标题。
- `description` 与 `points` 至少存在一种。简单变化只写 `description`；分组变化可以只写 `points`，避免标题后再重复一段同义概述。

### 5. 判断并生成技术图

只有图能明显降低理解成本时才调用 `fireworks-tech-graph`：

- 3 个及以上参与者存在有顺序的调用、事件或异步交互：时序图；
- 状态、重试、补偿或部分失败决定行为：状态图；
- 数据跨层、跨服务或跨协议转换：数据流图；
- 架构归属或模块依赖本身是 Review 决策重点：同一抽象层的架构图。

单函数、普通 CRUD、局部校验或短文字足以说明时不画图。通过门禁后：

1. 显式加载并遵循 `fireworks-tech-graph` 的完整工作流。
2. 默认使用白底 Style 1；只有明确领域证据才使用 C4、cloud、event 或 ops style。
3. 生成 SVG 源文件和约 1920px 宽 PNG，写入调用方安全目录或临时目录，不提交业务分支。
4. 完成 SVG 校验、PNG 导出和视觉回看；只有实际检查本地 PNG 后才能在 `review-brief.json` 的内部产物元数据中记录 `visual_review: passed`，并记录检查时的普通附件 `file_hash` 或技术图 `png_hash`；remote-only URL 不能作为视觉或字节证据。
5. 写出能够独立说明主要参与者与流程的 alt text；正文在图片不可见时仍须可理解。

Fireworks 失败最多按其恢复协议修正；仍失败则退回文字 Brief。PNG 未通过视觉检查时不得发布或声称可用。

### 6. 渲染与交付

默认返回完整 Markdown。若生成图，在对应主要变化后嵌入 PNG；SVG/PNG 绝对路径、文件哈希和视觉检查状态保留在 `review-brief.json` 的内部产物元数据中，不写入 Reviewer 可见正文。只有用户询问产物位置或发布受阻原因时，才在 Brief 之外单独说明。

本地 Markdown 中的截图、录屏和技术图都使用可确认存在的绝对路径。相对附件路径先按其来源文件或任务根目录解析；文件不存在时保留已确认的附件定位信息并报告缺口，不输出破损图片链接。

用户要求 GitHub 或 Slack 渲染、发布或上传时，完整读取 [channel-rendering.md](references/channel-rendering.md)。本 Skill 只准备同源内容、本地图产物和确定性渠道文件：

- GitHub 的读取、授权、已验证附件 URL 获取、正文更新与写后回读由 `github-workflow` 负责。
- Slack 的频道/thread 解析、授权、文件上传与消息发布由 `slack` 负责。
- Slack 只上传与 `review-brief.json` 同一产物目录树内、通过 PNG 结构与 scanline 门禁、拥有 `visual_review: passed` 且文件 hash 仍匹配的 artifact，并且属于精简正文所展示变化；GitHub 只嵌入同样通过视觉/字节门禁、候选声明一致且由可信 `github-workflow` 在回读远端字节后生成独立 `github-bindings.json` 的匿名附件 URL。该清单是 owner 可信输入，不是渲染器自行联网验证，也不得由来源不明的调用者伪装；两端不交叉复用需要另一端登录态的私有 URL。

## 用户可见内容边界

- 不以章节、条目、概要补充或主要变化补充等任何形式输出非目标、Out of scope 或同义说明。
- 不报告测试、CI、技术图或其他产物的执行状态与验证结果，包括命令清单、`visual_review` 和通过/失败结论。测试代码若是实际改动，可以说明其行为职责。
- 不输出 Review 工作量、预计分钟数或复杂度评分。
- 不输出 `review-swarm` Findings、P0–P3 或 merge verdict。
- 不逐文件复述 diff，不把机械变更和生成物包装成主要变化。

## 权限与安全

- 读取本地 diff、生成 Brief 和本地 SVG/PNG 不授权任何外部写入。
- 编辑 PR、获取或使用 GitHub 附件 URL、向 Slack 发消息或上传文件必须满足 owner Skill 的独立授权门禁。
- 不把 token、secret、原始客户数据、完整请求载荷或不必要的内部标识写进正文、图或 alt text。
- GitHub 渠道把所有语义字段按纯文本安全渲染；不允许 diff 或模型生成内容注入图片、HTML、mention 或 issue-closing 语义。
- 输入 JSON、文本、集合与本地产物都受确定性资源上限约束；不得为异常模型输出关闭上限或在目录/大小门禁前读取外部字节。
- 私有仓库的 Brief 与图不得上传到公共匿名图床。
- 外部写结果不明确时先回读，不盲目重试。

## NEVER

- 不在找 bug、finding 或 verdict 请求中抢占 `review-swarm`。
- 不在没有真实 diff 或明确 base 时生成看似完整的 Brief。
- 不把 scoped draft 写成完整 PR Description。
- 不因进入 Full 就固定画图，也不让图片替代必要文字。
- 不伪造 Fireworks 校验或 `visual_review: passed`。
- 不用未文档化 GitHub 上传 endpoint、公共图床或业务分支 commit 绕过 asset uploader 缺口。
- 不把 Slack 私有文件 URL 嵌入 GitHub，也不把 GitHub 私有附件 URL 当 Slack 上传结果。
- 不因生成本地 Brief 自动创建、编辑或发布 PR/Slack 消息。

## 确定性脚本

唯一入口为 `scripts/review-brief.mjs`：

- `node scripts/review-brief.mjs finalize <review-brief.json>`：按规范化规则计算、写入 `content_hash` 并原子保存。
- `node scripts/review-brief.mjs check <review-brief.json>`：校验必选字段、Lite/Full 阅读路线和内容哈希。
- `node scripts/review-brief.mjs hash <review-brief.json>`：只计算规范化语义哈希，不修改文件。
- `node scripts/review-brief.mjs render-github <review-brief.json> --output <body.md> [--existing-body <body.md>] [--adopt append|replace] [--require-image] [--require-diagram]`：生成完整 GitHub Body，以双 hash marker 安全创建或更新受控区域；任意图片与技术图分别使用独立必需门禁。
- `node scripts/review-brief.mjs render-slack <review-brief.json> --output <message.md> [--target-url <https-url>]`：生成不超过 4000 字符的 Slack 精简消息，并在 JSON 结果中返回原生 `blocks`（交给 Slack `--blocks-file`，整份 Brief 使用 `context` 小字，不输出目标身份或链接行；`--target-url` 仅校验目标）和待上传 PNG 的 `{path, sha256}` 列表；owner 必须把 hash 交给 `slack files_upload --sha256` 做上传前复核。

不要手写或猜测 `content_hash` / `render_hash`。脚本将本地路径、渠道 URL/file id、时间和 `visual_review` 视为交付元数据并排除在语义哈希之外；`render_hash` 单独覆盖渠道最终正文以及实际图片 URL，Slack 则覆盖稳定文件名与文件内容，不纳入临时绝对路径。
运行前先把入口解析为本 `SKILL.md` 所在目录下的绝对路径；不要假设当前工作目录就是 Skill 根目录。

## References

| 文件 | 加载时机 |
|---|---|
| [output-contract.md](references/output-contract.md) | 每次生成或渲染 Review Brief；包含统一字段、顺序、删减和哈希规则 |
| [channel-rendering.md](references/channel-rendering.md) | 用户要求 GitHub/Slack 预览、发布、上传或更新时 |
