# ReviewBrief 输出合同

生成或渲染任何 Review Brief 时完整读取本文件。语义模型是唯一内容权威，Markdown 只是渠道视图。

## 统一模型

```yaml
review_brief:
  schema_version: 1
  target:
    kind: pr | branch | range | worktree
    identity: string
    base: string | null
    head: string | null
  mode: lite | full
  overview: string
  main_changes:
    - title: string
      description: string | omitted
      points:
        - title: string
          description: string
      code_refs: []
      attachments: []
  diagram: null | object
  reading_route: []
  review_focus: []
  risk_release: []
  related: []
  content_hash: string
artifacts:
  attachments:
    - alt_text: string
      local_path: absolute-path | omitted
      github_url: https-url | omitted
      github_file_hash: sha256 | omitted
      github_target_identity: string | omitted
      visual_review: passed | failed | skipped | omitted
      file_hash: sha256 | omitted
  diagram: null | object
```

`review_brief` 是唯一语义来源；`artifacts` 只保存本地路径、渠道标识和质量门禁等交付元数据。附件必须提供存在的本地绝对路径；需要进入 GitHub 时再附加已验证的 GitHub HTTPS 附件 URL，remote-only URL 不能形成可发布 artifact。`main_changes` 与 `artifacts.attachments` 必须按定位路径或 URL 一一对应，alt text 和重复出现的 URL 不得冲突；渠道 URL 与视觉状态以 artifact 记录为准。GitHub URL 存在时，`github_file_hash` 必须等于本地 `file_hash` / `png_hash`，该 hash 必须再次匹配当前本地文件快照，`github_target_identity` 必须等于当前 `target.identity`；这些字段只是一致性声明，不构成上传证明。Markdown 只渲染 `review_brief`，不得展示内部状态字段。

输入 JSON 最大 4 MiB、嵌套最大 32 层、节点最大 20,000 个；单个文本字段最大 20,000 字符，通用列表最大 200 项，主要变化最大 100 项，每条主要变化的子要点最大 20 项，语义附件与 artifact 各最大 200 项。上限用于阻止异常模型输出造成无界解析或校验成本，不改变正常 Brief 的内容建议。

## 字段合同

### `target`

- `identity` 使用稳定、可回读的目标身份，例如 PR 编号与 URL、branch 名、revision range 或 `worktree:<absolute-root>`。
- `base` 与 `head` 必须显式存在且为非空字符串或 `null`。PR、branch 与 range 尽量记录可回读 SHA；无法获得时使用 `null`，不得删除字段或猜测。
- 路径过滤后的内容在 `identity` 中明确标记 `scoped-draft`。

### `overview`

- 固定存在，用 2–4 句话说明可信背景、目标和最终行为结果。
- 句子保持简短；两个独立结果可以在同一字符串中用空行分段，渠道渲染器必须保留为安全段落。
- 面向不了解实现上下文的 Reviewer，不复述 commit 标题。
- 只写已确认事实或 diff 可证明的行为，不写计划、推测和未执行结果。
- 对可访问性、幂等性、并发安全等性质，不从单个属性或局部 diff 推导整体效果；只陈述可观察实现，并把需要人类确认的效果放进 `review_focus`。

### `main_changes`

- 固定存在，按用户行为、领域能力、模块职责或协议变化分组。
- 每项回答“实际行为改变了什么，以及它在整体改动中的职责”。
- 每项必须有非空 `description` 或非空 `points`；简单变化使用 `description`，存在多个从属行为时使用 `points`。
- `points` 是带标题的二级要点，按阅读顺序排列；通常使用 2–5 项，不把从属细节提升成一串同层级 `main_changes`。
- Lite 使用 `description` 且不使用 `points`；Full 可用 2–4 条主线配合 `points`，也可在变化天然同层级时继续使用描述式条目。
- 概括组件职责时保留同一组件承担的关键并列动作，不用“只负责”“完全交给”等绝对措辞抹掉 diff 中仍存在的职责。
- `code_refs` 只放理解该变化有帮助的文件或 symbol，不逐文件列清单。
- UI 截图、录屏或视觉附件放在所属变化项的 `attachments`，不单设验证或证据章节。
- 普通视觉附件只有对应 artifact 明确记录 `visual_review: passed` 时才可进入 GitHub 或 Slack；状态缺失、`failed` 或 `skipped` 的附件仍可留作本地产物，但不得外发。
- 本地渲染前将附件路径解析为可确认存在的绝对路径；相对路径按其来源文件或任务根目录解析。文件不存在时不生成破损的 Markdown 图片链接。

### `diagram`

未通过可视化门禁时为 `null`。存在时只保留会影响 Reviewer 理解的语义：

```yaml
diagram:
  type: sequence | state | data-flow | architecture
  alt_text: string
  source_hash: sha256
```

路径与校验状态放进同一 JSON 的内部元数据：

```yaml
artifacts:
  diagram:
    svg_path: absolute-path
    png_path: absolute-path
    png_hash: sha256
    visual_review: passed | failed | skipped
    github_url: https-url | omitted
    github_file_hash: sha256 | omitted
    github_target_identity: string | omitted
```

只有实际加载本地 PNG 并检查后才能在内部记录 `passed`，并同时把检查时的 PNG SHA-256 记录到普通附件 `file_hash` 或技术图 `png_hash`。`finalize` 不根据历史 `passed` 自动补 hash；缺失时必须重新视觉回看并由检查动作同时记录 hash。`finalize`、`check` 和双渠道渲染在 hash/PNG 深度读取前对全部唯一的本地产物执行共享门禁：单文件不超过 25 MiB、总文件字节不超过 100 MiB、PNG 头声明的单图与累计解压预算不超过 64 MiB、单行不超过 8 MiB、scanline 不超过 10 万、总 chunk 不超过 8192、IDAT chunk 不超过 4096，并拒绝 symlink/hardlink；任何标记为 `visual_review: passed` 的 `.png` 普通附件也必须通过完整 PNG 结构门禁，不能留到渠道渲染时静默跳过。每个唯一文件只通过同一 fd 稳定读取一次，后续 hash、PNG 校验与渲染复用不可变字节及缓存结果；重复 locator 会按冻结的 realpath 身份去重，读后发生路径替换也不能改变本次命令使用的快照。图片被替换后必须重新视觉检查。凡 artifact 携带 GitHub URL，无论视觉状态是 `passed` 还是 `skipped`，都必须以当前本地快照核对候选 hash；remote-only URL 或两个相等的伪 hash 不能代替本地证据。GitHub 匿名附件上传完成后，可信 `github-workflow` owner 必须重新读取远端字节，并在候选产物目录之外生成独立绑定清单；`render-github --github-bindings <path>` 先拒绝最终 symlink、冻结 realpath，再从该规范路径用同一 fd 的单链接 inode 快照读取清单，同时核对清单目标、URL、SHA-256、候选声明与本地当前字节，并拒绝 `--output` 覆盖清单。该清单是 owner 可信输入，不是渲染器自行联网验证，也不防御拥有同一系统用户权限的恶意调用者；来源或远端回读结果不明时不得传入。渲染器不接受 raw 分支链接、仅凭域名可信的 URL，或候选 JSON/同目录文件的自证明。最终可校验 bundle 中，非空 `diagram` 必须对应 `visual_review: passed`；`failed` 或 `skipped` 只表示生成过程的临时状态，必须先移除 diagram 才能 finalize，也不向 Reviewer 展示。

### `reading_route`

- Lite 必须为空；Full 必须包含 3–7 步。
- 按运行时或因果顺序组织，每步给出具体文件/symbol，以及该位置回答的问题。
- 生成物、快照、机械重命名可标为略读，不展开冗长清单。

### `review_focus`

- 只放非直观设计、关键边界、跨组件契约或需要人类判断的内容。
- 不预判缺陷，不包含 finding、优先级或 verdict。
- 可以用“确认/核对……是否……”表达开放式检查项；不得把它写成已确认问题、修复要求或合并条件。
- 没有有效内容时为空并删除章节。

### `risk_release`

只在兼容、迁移、配置、权限、外部依赖、回滚或特殊发布步骤存在时填写。不要用“无”“不适用”占位。

### `related`

只保留已确认且直接帮助理解或追踪本次改动的 Issue、PR、设计文档或讨论链接，不猜 Jira key 或关联 PR。

## 禁止的用户可见内容

- 任何非目标、Out of scope 或同义说明，无论位于独立章节还是其他正文位置。
- 测试、CI、技术图或其他产物的执行状态、命令列表、通过/失败结论或其他验证结果，包括 `visual_review`。
- Review 工作量、预计分钟数、复杂度评分。
- Findings、P0–P3、Approve、Request changes 或其他 merge verdict。

测试、CI、契约和历史可以作为内部证据。测试代码本身若是本次实际行为改动，可以在主要变化中说明其职责，但不得顺带报告执行结果。

`finalize` 与所有渠道渲染都会对以上禁止内容执行生产门禁；命中时直接拒绝 bundle，不能只依赖评测器或提示词自律。门禁按语义角色区分“修复/关联已有缺陷”等完整完成态改动说明与 Reviewer finding：前者允许展示，但完成态缺陷或工单引用后的句号、逗号、冒号、长/短连字符或连接词不能再追加断言；完成态遮罩只覆盖第一个完整片段，不跨越尾随 finding。渠道 Markdown 会分别还原标题与描述的角色，Slack 斜体标题是完整完成态、描述只是中性行为说明时可以通过。后者以及验证进度、技术图生成/检查状态等内部交付信息必须拦截；“测试失败重试能力/机制/次数/策略”和失败测试的诊断日志职责不属于执行结果，但其后由标点或“且/并且/并/同时/之后”连接的真实测试状态仍会被拦截。“通过环境变量注入/通过 webhook 发送/通过事件总线同步”中的“通过”是介词，不作为验证结论；带 `已/已经/全部/均` 完成态前缀的“通过质量门禁后发布”仍按真实结果拦截，但“通过后端接口/后台任务发送”中的“后端/后台”是渠道名词。无完成态标记的“CI 通过后发布产物”按条件行为描述处理。`null` / `undefined` 返回值、参数错误、规范错误码和错误处理分支可以作为正常接口契约展示，契约遮罩不得跨过数据丢失等缺陷信号；只有存在缺陷断言或危害因果时才按 finding 拦截。灰度、回滚、兼容等发布语境只豁免兼容事实自身；任何用户可见字段中，其后由标点或常见连接词引出的“其他流程”或具名接口、业务、调用方、路径的“不受影响/不调整”仍属于非目标说明。

## `content_hash`

使用 `node scripts/review-brief.mjs finalize <review-brief.json>` 生成 SHA-256，不手写哈希。脚本只规范化 `review_brief`，忽略顶层 `artifacts`，并遵循：

1. 对象键按字典序排列，数组保持展示顺序。
2. 统一换行为 `\n`，去除字符串首尾空白，不改写正文内部空格。
3. 保留语义上的 `null` 与空数组，排除临时绝对路径、上传 URL、file id、运行时间和 `visual_review`。
4. 图只纳入 `type`、`alt_text` 与 SVG 内容 SHA-256，不纳入本地路径和渠道 URL。
5. 对规范化 UTF-8 JSON 计算 SHA-256，输出 64 位小写十六进制。

相同目标、head 和语义内容必须得到相同 hash；head 或语义字段变化后必须重新计算。

需要保存本地产物、生成技术图或交给渠道 Skill 时，`review-brief.json` 是必交付物。下游渲染前必须执行 `check`；校验失败时回到语义模型修正，不从已有 Markdown 反向重建。
渠道渲染的 `--output` 不得与输入 JSON、普通附件或技术图 SVG/PNG 指向同一真实文件，避免覆盖唯一语义来源或待发布产物。

`finalize` 是读改写操作：读取时冻结输入 JSON 的 inode、链接数、大小、时间戳和内容 hash，原子替换前再次核对同一路径仍是该版本；中途被其他进程修改时失败，避免用旧快照覆盖新内容。

## 渠道渲染身份

`content_hash` 只标识语义内容，不能单独判断渠道输出是否需要更新。确定性渲染器另行计算 `render_hash`：

- GitHub：覆盖 marker 内最终 Markdown，包括已验证的 GitHub 图片 URL。
- Slack：覆盖精简 fallback、原生 blocks 以及待上传本地 PNG 的稳定文件名与内容 hash；不包含临时绝对路径。
- `render_hash` 不写回语义模型；GitHub marker 同时记录 `content_hash` 与 `render_hash`。
- 相同语义从文字 fallback 升级为含图片版本时，`content_hash` 保持不变，`render_hash` 必须变化。

## Markdown 顺序与删减

固定顺序：

1. 概要
2. 主要变化
3. 技术图（放在所解释的主要变化后；解释全局时放在主要变化末尾）
4. 推荐阅读路线
5. Review 重点
6. 风险与发布
7. 关联资料

只有“概要”和“主要变化”固定出现。其余字段为空时删除整个章节，不输出“无”“不适用”、空列表或图片占位。

### Lite 示例

```md
## 概要

设置页现在会在用户清空可选备注时发送明确的空值，使服务端能够移除旧值，而不是继续保留历史内容。

## 主要变化

- **清空备注语义**：表单提交层将空字符串规范化为 `null`，与现有更新接口的删除语义保持一致。
```

### Full 骨架

```md
## 概要

第一条简短结论。

第二条简短结论。

## 主要变化

### 1. 第一条主线

- **第一个要点**：说明行为与职责。
- **第二个要点**：说明行为与职责。

### 2. 第二条主线

- **第一个要点**：说明交接或消费关系。
- **第二个要点**：说明边界。

![能够独立说明参与者与流程的替代文本](<local-or-channel-image>)

## 推荐阅读路线

1. `path/file.ts:symbol` — 先理解入口约束。
2. `path/service.ts:symbol` — 再理解核心规则与状态变化。
3. `path/worker.ts:symbol` — 最后确认异步副作用与结果回写。

## Review 重点

- ...

## 风险与发布

- ...

## 关联资料

- ...
```
