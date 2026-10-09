# 周工作复盘产出契约

本契约定义 `weekly-work-review` 的期望产物。

## 周标识契约

从复盘周的本地周一计算归档标识。

```text
week_start = 周一本地日期
week_end = week_start + 6 天
workspace_week_dir = <YYYY-Www__YYYY-MM-DD--YYYY-MM-DD-周复盘>
digital_garden_week_dir = <YYYY>/<MM>/<日期范围>
```

例：

```text
2026-W23__2026-06-01--2026-06-07-周复盘
```

同一周的周三、周五上午、周五下午、周日运行必须更新同一个 digital-garden `<日期范围>/` 目录。

`workspace_week_dir` 仅用于理解旧 workspace 命名，不再作为默认产出目录。digital-garden 归档禁止再嵌套 `workspace_week_dir`。

禁止以运行日期或复盘结束日期作为目录标识。

## 固定默认契约

用户已确认以下默认，后续运行不得再反复询问：

- 目标路径有且仅有 Vault 归档：`<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/`。
- 目录结构按现有 2026/06 `<日期范围>` 到 `week-4` 的 flat package 结构永久执行；下个月、明年仍按 `<YYYY>/<MM>/<日期范围>/` 推导。
- 如果目标周目录不存在，证据范围为该周周一到当前运行时刻；如果目标周在过去，则采集完整周。
- 如果目标周目录已存在，按同周增量更新；无法可靠读取上次覆盖截止时，扫描整周并在 manifest 说明去重策略。
- 运行前先读取目标周上一周的 `evidence-manifest.md` / `evidence-manifest.json` 和 `迭代记录.md`；上一周缺 manifest 时只用 `迭代记录.md` 判断 legacy/gap，然后继续找最近一次成功归档。找不到 baseline 时记录原因后允许完整扫描。
- 复盘的主产品是 用户 自己阅读的个人全量周复盘。MoeGo 工作、写作/创作、知识系统和有明确产物的个人项目都属于默认范围。
- `Sprint Review` 只是从完整产出中选出的公司相关摘录；不得用 Sprint Review 受众反向裁剪个人复盘。
- 主线只决定概览、篇幅和顺序。所有有证据的实质产出必须进入 `本周产出总账`，不能因“没有改变主线”被排除。
- 如果用户明确指定具体周或日期范围，按用户输入执行；跨多个周一时才停下确认拆分方式。
- 会议模式永远是会议 + 转写：纳入飞书/Lark 会议，权限允许时归档完整 `会议转写.md`。
- 转写正文的首选来源是会议纪要 docx 底部 `文字记录` docx 链接；用 `lark-cli docs +fetch --doc <文字记录 docx> --doc-format markdown` 获取，不默认通过妙记/minutes 链接导出转写。
- 飞书/Lark 拉取到空正文、权限错误、明显过短占位或只有元数据时，必须标记 human check required，不能当作完整会议归档；用户 提供真实链接后按真实链接重建并同步索引/manifest。
- 原始证据 dump 必须放在 vault 外 scratch 目录，例如 `<scratch-root>/<YYYY>/<MM>/<日期范围>/`。禁止在 vault 内创建 `work/weekly-work-review`、`Work/weekly-work-review` 或 `outputs/`。

## 目录结构契约

创建或更新主 digital-garden 归档包：

```text
<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/
  <日期范围> 周复盘.md
  小时证据附录.md
  迭代记录.md
  evidence-manifest.json
  evidence-manifest.md
  validation-result.json
  meetings/
    会议索引.md              # 只索引，不复制会议正文
```

会议正文的权威位置在会议目录，与周报同样按年月分类，年月取会议日期：

```text
<vault>/工作/会议/<YYYY>/<MM>/<YYYY-MM-DD 标题>.md
```

带转写、PDF 或图片时升级为同名目录，主文件与目录同名以保持 wikilink 不变：

```text
<vault>/工作/会议/<YYYY>/<MM>/<YYYY-MM-DD 标题>/
  <YYYY-MM-DD 标题>.md
  会议转写.md
  exports/
    飞书原始纪要.pdf
  assets/
    whiteboards/
    images/
```

周报包内 `meetings/<folder>/` 是过渡形态：validator 仍会校验已存在的会议子目录（MEETING-002/003 等），但新归档不应再往周报包内写会议正文，避免同一场会议在多个周报包重复存储。

规则：

- 最终产物是文件夹包，不是单个 markdown 替代品
- 写入前必须按固定默认计算具体归档路径
- digital-garden 路径为唯一交付物
- 禁止创建 `outputs/<workspace_week_dir>/` 或 vault 内临时 evidence dump
- `<日期范围>/` 本身就是 digital-garden 最终包目录；禁止创建 `<vault>/.../<日期范围>/<YYYY-Www__YYYY-MM-DD--YYYY-MM-DD-周复盘>/`
- 默认包含 `小时证据附录.md`；如果没有小时/session 证据，文件中写明 `zero_result` 或 `not_applicable`
- 同周重跑时包含 `迭代记录.md`；追加运行时间戳、覆盖范围和主要变更
- 默认包含 `meetings/会议索引.md`；如果没有会议命中，索引中写明 `zero_result`
- 禁止创建同周重复目录
- 禁止删除已有周目录中的未知文件或手动笔记

## 自动范围契约

固定默认不需要 preflight。仅在以下情况通过环境对应的交互问答工具确认：

- Claude Code：使用 `AskUserQuestion`
- Codex：使用 `functions.request_user_input`

触发条件：

- 用户指定日期范围跨多个周一。
- 同一周存在多个候选归档目录。
- 用户要求与固定默认冲突，例如非 Vault 路径、workspace-only、session-only、不包含会议转写。
- 危险操作或外部副作用触发全局 SAFETY。

工具不可用时，在关键决策前停下并报告。

目标路径自动解析为：

```text
<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/
```

## Digital-Garden 契约

发布精编包到：

```text
<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/
```

确认 `<vault>` 路径：

1. `<vault-root>`

写入前读取：

- `<vault>/CLAUDE.md`
- `<vault>/Work/MoeGo/README.md`

vault 路径由 `week_start` 推导：

- `YYYY` 和 `MM` 为 `week_start` 的年和月
- `N` 为该月中以周一起始的序数周号，从 1 开始
- `week_start=2026-06-01` → 发布到 `工作/周报/2026/06/<日期范围>/`
- 具体日期范围写入 frontmatter `date_range: YYYY-MM-DD-YYYY-MM-DD`
- 不在 vault 目录名中编码完整日期范围

默认归档内容：

- `周复盘.md`
- `小时证据附录.md`
- `迭代记录.md`
- `evidence-manifest.json`
- `evidence-manifest.md`
- `meetings/会议索引.md`（只索引；会议正文归 `工作/会议/<YYYY>/<MM>/`）
- `validation-result.json`（validator 生成，绑定 manifest hash）

会议归档内容（写入 `工作/会议/<YYYY>/<MM>/`，不写进周报包）：

- 每会议主文件 `<YYYY-MM-DD 标题>.md`
- 当 transcript/verbatim 文本可用时，每会议完整 `会议转写.md`
- 当会议纪要/转写不可用、为空或权限不足时，会议文件必须明确读取状态和 human-check 缺口，不能用占位正文替代真实内容
- 当 `note_doc_token` 或 `note_doc_url` 可用时，每会议 `exports/飞书原始纪要.pdf`；不可用时写明 `pdf_unavailable_reason`
- 每会议本地 `assets/whiteboards/` 和 `assets/images/`，从主文件用相对链接嵌入

完整会议转写随周复盘归档一起发布。不因普通内部会议敏感性而阻止。
会议转写正文优先从纪要底部 `文字记录` docx 链接读取并归档；不要把妙记/minutes 链接当成转写正文导出的默认路径。
飞书/Lark 会议纪要 PDF 必须使用 `drive +export` 原样导出，不做脱敏、摘要化、截图替代或二次转换。
`会议纪要.md` / `会议转写.md` 是会议正文归档，不是对外摘要；保持飞书正文语义、说话人和原文表达。除凭证/密钥形状字符串触发安全门禁外，不主动替换姓名、用户 ID、客户名或原文句子。

除非明确要求，不将原始 session JSONL、完整工具输出、完整 Lark 元数据 dump 或 prompt 日志发布到 vault；默认也不在 vault 内保存这些原始 dump。

禁止将此包写入 `Research/wiki/`。如有持久教训浮现，提议单独 wiki 候选项并等待批准。

## Evidence Manifest 契约

每次生成或更新周复盘，必须同步写入：

- `evidence-manifest.json`：机器可读的证据账本
- `evidence-manifest.md`：人类可读的证据覆盖报告

Manifest schema 见 `references/evidence-manifest-schema.md`。

最低要求：

- `archive_shape` 必须是 `date-range-week-dir`
- `archive_dir` 必须指向 `<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/`
- `sources_scanned` 必须覆盖 AI sessions、Slack outbound/inbound、Lark VC、calendar fallback、minutes owner/participant、shared clip link extraction、shared clip keyword search、Lark Drive docs、本地 vault notes、GitHub/code activity、Jira/Linear/worklog
- `sources_scanned` 还必须覆盖 `personal_outputs`：本周写作、内容资产、知识系统和有明确产物的个人项目
- 每个 source 必须记录 `status`、查询或 artifact、`raw_count`、`candidate_count`、`used_count`、`skipped_reason`
- `candidate_items[]` 必须记录 `id`、`type`、`title`、`date`、`source_key`、`source`、`source_path_or_token`、`discovery_method`、`evidence_ref`、`used_in`、`confidence`、`sensitivity`
- `output_items[]` 必须记录全部实质产出及其 `category`、`status`、`evidence_refs`、`report_anchor`、`used_in` 和 `sprint_review_selected`
- 对 raw/candidate 非 0 但未进入正文的证据，必须写 `excluded_with_reason`
- 命中的 shared clip 必须同时进入 `candidate_items`、`indexed_items` 和 `meetings/会议索引.md`
- `evidence-manifest.md` 优先保存 Slack collaboration summary，覆盖主要话题、关键决策/行动/handoff、低信号 chatter 排除口径；`周复盘.md` 只保留 3-5 条最高信号协作结论
- `evidence-manifest.md` 的 `Validation Readback` 必须包含真实 validator pass/fail 结果；只有命令本身不算 readback

`evidence-manifest.md` 必须包含：

```markdown
## Coverage Matrix
## Queries Run
## Empty Results
## Candidate Evidence
## Used In Report
## Excluded With Reason
## Shared Clip Discovery
## Validation Readback
```

## 主报告契约

`周复盘.md` 应可独立归档阅读，无需原始证据附录。

推荐结构：

```markdown
# <YYYY-MM-DD> ~ <YYYY-MM-DD> 周复盘

## 本周概览

## 本周一句话判断

## 本周产出总账

## 可直接贴到 Sprint Review 的内容

## 主要推进

## 每天在做什么

### <日期>

**上午**

**下午**

**晚上**

## 协作与沟通

### 会议

### 异步协作（Slack）

## 个人复盘

## 风险、遗留问题与下周建议

## 证据口径
```

顺序重要，禁止将证据口径放在顶部。

`协作与沟通` 含两个子节：

- `### 会议` — 来自飞书/Lark 会议证据
- `### 异步协作（Slack）` — 来自 Slack 协作摘要：参与的主要话题、关键决策/行动/handoff、links、被排除的低信号 chatter；仅引用用户自己的话，每 thread 最多 2 句

当某子节无数据时，省略该子节而非写空标题。

正文生成前必须做综合前置：

1. 从全部 source 构建 `output_items[]`，先闭合本周产出总账，再讨论叙事主线
2. 基于 `evidence-manifest.json` 生成 3 个候选主线：`thesis / supporting_evidence / contradicted_by / best_audience`
3. 写 `周复盘.md` 前做一次 human checkpoint：向用户 确认哪些主线值得重点展开、漏掉的重点、Slack/会议取舍、敏感项和 Sprint Review 选材；默认等待 90 秒，`request_user_input` 不可用或超时则记录 assumptions 后继续，不进行第二轮追问
4. 选择 1–3 个重点主线写入 `本周概览` 和 `本周一句话判断`
5. 未选择的实质产出仍必须写入 `本周产出总账`；主线选择不得成为排除理由
6. 证据数量统计不放首段，只放 `证据口径` 或 `evidence-manifest.md`

## 本周产出总账契约

`本周产出总账` 是个人复盘的完整索引，不是 Sprint Review 的长版本。

- 按工作流聚合，不按文件逐条堆砌
- 至少区分 `已发布 / 已完成 / live / 进行中 / blocked / 暂停`
- 覆盖 MoeGo 交付、工程与运维、协作与管理、写作与创作、知识系统和有明确产物的个人项目
- 敏感 1v1 可以只写“完成准备/对齐”及非敏感主题，不复制私密内容
- 仅参会、重复同步、无产物探索和自动生成的中间文件不算独立产出
- manifest 中每个 `output_item.report_anchor` 必须能在正文回读
- 发现被旧版主线逻辑排除的真实产出时，必须恢复进总账，并在 `迭代记录.md > Skill 运行复盘` 说明根因
- 每个 candidate 必须明确进入正文/产出证据，或进入 `excluded_with_reason`；不得因为不够“主线”而静默消失

`主要推进` 每个小节必须有 evidence anchor。允许的 anchor 包括：会议标题、minute token、doc title、repo/PR/commit、版本号、验证命令、readback、session id、本地笔记路径。没有 anchor 的小节不得写成完成项。

## 文风契约

以用户视角写作，但省略显式第一人称。

推荐：

- `本周完成了...`
- `推进了...`
- `梳理了...`
- `确认了...`
- `沉淀了...`

禁止：

- `我做了...`
- `我完成了...`
- `我去...`
- agent 过程叙述如 `我通过 session 分析发现...`
- 自说自话、开篇铺垫、审计日志腔

文档应感觉像用户可以存入个人知识库的东西。

## Sprint Review 摘录契约

`可直接贴到 Sprint Review 的内容` 部分应从 `本周产出总账` 二次筛选，最多 6 条。用户 可以只复制其中一部分，因此这一节不承担完整记录职责。

- 交付物或决策在前
- 影响或状态在后
- 每条必须包含 `交付物/判断`、`影响/状态`、`下一步/请求`
- 每条必须有 evidence anchor；没有 anchor 时标为 `待复核`
- 除非必要不引用原始证据
- 不含私密转写摘录
- 不含密钥、token 名或凭证路径

## 每日契约

每天一个 section。每天内使用：

- `上午`
- `下午`
- `晚上`

如果某时段无证据，省略或写一句中性短句。禁止捏造活动。

`周复盘.md` 中禁止小时级分解；小时细节放 `小时证据附录.md`。

## 会议契约

`meetings/会议索引.md` 应包含：

- 日期/时间
- 会议标题
- `source_type`：`vc`、`calendar`、`minutes-owner`、`minutes-participant`、`shared-minute`、`shared-clip`、`manual-link`
- `discovery_method`：例如 `vc +search`、`minutes owner search`、`slack link extraction`、`local vault link extraction`、`keyword minutes search`
- `minute_token/meeting_id`
- 可用的笔记/转写文件
- 安全时附 source doc/minutes token 或链接
- 一句话说明与周复盘的关联

推荐表头固定为：

```markdown
| 时间 | 标题 | source_type | discovery_method | minute_token/meeting_id | 本地材料 | 复盘相关性 |
```

共享妙记 / clip 也纳入 `meetings/会议索引.md`，来源标记为 `shared-minute` 或 `shared-clip`。这类条目可能没有 `meeting_id` 或 calendar event，但必须保留 `minute_token`，并尽量归档完整 transcript。

发现共享妙记 / clip 的最低搜索链路：

1. 本周 Slack outbound/inbound 中抽取 `minutes/<minute_token>` 链接。
2. 本地 vault `Work/MoeGo/记录/`、`Work/MoeGo/思考/` 中抽取 `minutes/<minute_token>` 链接，尤其是 `1v1/`、`复盘/`、`会议/`。
3. 从 Slack/vault 命中片段生成关键词，逐个执行 `lark-cli minutes +search --query "<keyword>" --start <week_start> --end <week_end>`。
4. 合并 `owner-ids me`、`participant-ids me`、关键词搜索和显式 token，按 `minute_token` 去重。
5. 对候选 token 执行 `lark-cli vc +notes --minute-tokens` 获取总结、章节、待办和纪要文档线索；不要把它当成转写正文的默认导出路径。
6. 转写正文优先从纪要底部 `文字记录` docx 链接用 `lark-cli docs +fetch --doc <docx> --doc-format markdown` 获取。

不要把 `owner-ids me` / `participant-ids me` 的结果当作共享 clip 的完整集合。别人通过 Slack 分享给 用户 的妙记可能不在这两类结果里，只能通过 token 抽取或关键词搜索命中。

每个会议文件夹应包含：

- `会议纪要.md`：从飞书笔记文档获取的正文归档；只做 Markdown 格式整理和本地资产链接持久化，不做内容摘要、改写或普通脱敏
- `会议转写.md`：归档包中权限允许时的完整 transcript/verbatim 文本；优先从会议纪要底部 `文字记录` docx 链接通过 `docs +fetch --doc-format markdown` 获取；不可用时写明原因和已尝试的来源
- `exports/飞书原始纪要.pdf`：飞书笔记文档的 `drive +export` PDF，用作保真降级；用 `scripts/export-meeting-pdfs.mjs <week_dir>` 批量导出，该 helper 只导出纪要 PDF，不导出转写
- `assets/whiteboards/<NN>-<name>.<ext>`：用 `whiteboard +query --output_as image` 导出的白板图片；使用实际保存的扩展名
- `assets/images/<NN>-<name>.<ext>`：笔记文档含 `<img>` 资源时下载的图片

如果转写正文获取失败：

- 先检查 `会议纪要.md` / 原始纪要 docx 底部是否有 `文字记录` docx 链接，并用 `lark-cli docs +fetch --doc <docx> --doc-format markdown` 读取
- 若已有 `verbatim_doc_token` / `verbatim_doc_url`，直接用 `lark-cli docs +fetch` 读取
- 仍不可用则创建 `会议转写.md` 写明不可用原因和已尝试的来源

转写文本不进入 `周复盘.md`；仅摘要相关决策和上下文。

对飞书 AI 会议笔记，不要将 `vc +notes` 产物当作完整笔记文档。用 `note_doc_token` / `note_doc_url` 获取并导出实际 docx；从纪要底部 `文字记录` docx 链接获取转写正文，不默认用妙记/minutes 链接导出转写。如果文档含 `<whiteboard token="...">`，在 `会议纪要.md` 中嵌入导出的本地图片并在相邻 HTML 注释中保留 token。禁止依赖 `internal-api-drive-stream.feishu.cn` URL 作为持久归档资产。

## 证据口径契约

`证据口径` 部分应简要说明：

- 日期范围和时区
- week key 和周目录
- digital-garden 路径
- 证据覆盖截止时间（尤其是周五上午/下午的部分运行）
- 扫描的 session 来源
- Slack 证据：collaboration summary 已采集，或 `unavailable` / `partial` / `zero_result`（含原因）
- 纳入/排除的来源类别
- 当天是否为部分日
- 纳入的会议来源
- 已知缺失数据或权限缺口
- 完整会议转写是否已发布到 vault
- 原始 session/工具证据是否有意未纳入

详细来源统计和小时证据放 `小时证据附录.md`。

## Skill 运行学习契约

每次运行都在 `迭代记录.md` 追加 `## Skill 运行复盘`，至少包含：

- `initial_miss`
- `user_correction`
- `root_cause`
- `durable_change`
- `verification`

下次运行读取最近三次记录，将重复遗漏加入 rescan checklist。若问题重复出现，或直接违反 用户已确认的固定默认，必须同步更新 skill contract、eval 和 validator；不得只改当周正文。

## Source Coverage 契约

每个来源类别都必须在 `evidence-manifest.json` 中闭合：

| 来源 | 最低动作 | 正文使用规则 |
|---|---|---|
| AI sessions | 扫描 Codex/Claude session，抽取生产 work sessions | 支撑工程推进、验证命令、风险判断；原始 JSONL 不进 vault |
| Slack outbound/inbound | 搜索发出和被提及消息，拉取高信号 thread context，形成 Slack collaboration summary | `evidence-manifest.md` 优先保留协作摘要；正文只写 3-5 个协作结论；Top channel stats 和 raw dump 禁止进 vault |
| Lark VC/calendar | `vc +search` + calendar fallback | 会议索引和会议小节必须说明 discovery method |
| Lark minutes | owner/participant 分别查，按 token 去重 | 不把 owner/participant 当成 shared clip 全量覆盖 |
| Shared clips | Slack link、本地 vault link、关键词 minutes search | 命中 token 必须进入会议索引和 manifest |
| Lark Drive docs | opened/edited/commented/recent | 分 `used/background/irrelevant/sensitive-excluded`，正文只引用 used |
| Local vault notes | 扫 `Work/MoeGo/记录/`、`Work/MoeGo/思考/` | 用于补 1v1、管理辅导、会前/会后复盘线索 |
| Personal outputs | 扫 `Writing/`、活跃 `Projects/`、本周知识编译报告和明确的个人产物 | 所有实质产出进入总账；Sprint Review 可不选 |
| GitHub/code activity | 只读查 PR/commit/review/release/CI 或本地 git evidence | session 不能替代代码 source，只能解释上下文 |
| Jira/Linear/worklog | 若工具可用，查 assigned/updated/commented/resolved/worklog | 不可用时 manifest 标 `tool_unavailable` |

Coverage gate：

- 非空来源至少有 1 条进入主报告，或写入 `excluded_with_reason`
- 高信号 candidate 的使用率目标为 70%；不足时必须在 `evidence-manifest.md` 解释
- 所有 `output_items[]` 必须进入 `本周产出总账`，产出覆盖率必须为 100%
- 所有 `candidate_items[]` 必须完成 used / excluded 二选一分类，且 coverage 计数与实际数组一致
- Slack、shared clip、calendar fallback、Drive docs 不得静默缺席
- 命中的 shared clip 数量必须等于 `meetings/会议索引.md` 中 `source_type=shared-clip` 的行数，除非 manifest 记录 `token_unavailable_reason`

## 隐私契约

发布到 digital-garden 前对内容分级：

- `public`：可安全引用
- `personal`：适合个人笔记（review 后）
- `internal`：摘要即可，不 dump 原始文本
- `confidential`：除非明确授权不进 vault
- `restricted`：禁止发布

当非会议正文的 generated markdown 包含以下内容时阻止或要求人工审查。`会议纪要.md` / `会议转写.md` 作为原始会议归档，不因姓名、用户 ID、客户名、说话人或普通业务原文自动脱敏；但凭证/密钥形状字符串仍触发安全门禁：

- `Authorization`、`Bearer`、`access_token`、`refresh_token`、`client_secret`、`api_key`、`password`、`private_key`
- `.env`、`credentials.json`、service account JSON、webhook URL
- 长 API-key 形状字符串如 `sk-...`
- `op://.../credential`
- 原始邮箱、手机号、客户识别信息、1v1 绩效内容、薪资、招聘评估、健康数据

对 `周复盘.md` 和非会议证据，保留结论而非原始日志。周复盘归档中保留完整会议转写（转写可用时），会议纪要正文和纪要 PDF 按飞书原始内容归档，不做普通内容脱敏。此完整会议归档规则仅适用于会议纪要、会议转写和纪要 PDF，不适用于原始 session JSONL、工具日志、Lark 元数据 dump、Slack 原文或 prompt 日志。

### Slack 专属隐私规则

- **他人逐字消息**：禁止归档到 vault 文件。仅摘要话题和结论。
- **用户 自己的消息**：关键决策表述可引用（每 thread 最多 2 句），出现在 `周复盘.md` 的 `协作与沟通 > 异步协作（Slack）` 下。
- **Channel 名称和话题摘要**：可安全写入 — 这是 用户 的活动记录。
- **原始 Slack 证据**（`slack-events.json`、raw thread context、tool JSON）：仅保留在 vault 外 `<scratch-dir>/slack-evidence/`。禁止发布到 digital-garden。
- **Slack collaboration summary**：优先写入 `evidence-manifest.md`。进入 `周复盘.md` 的只保留 3-5 条最高信号协作结论。
- **DM 内容**：视为 `personal` 分级。只摘要主题和结论；不引用对方的话，不默认写对方姓名/身份，除非该身份是复盘上下文必要锚点且非敏感。
- **客户识别信息、HR/绩效内容、薪资**：如在 Slack 消息中遇到，输出前必须脱敏。

## 质量检查清单

交付前执行：

```bash
test -f '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/周复盘.md'
test -f '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/meetings/会议索引.md'
test -f '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/evidence-manifest.json'
test -f '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/evidence-manifest.md'
test ! -e '<vault>/Work/weekly-work-review'
test ! -e '<vault>/work/weekly-work-review'
test ! -e '<vault>/outputs'
find '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/meetings' -name '会议纪要.md' -o -name '会议转写.md'
node '<skill-dir>/scripts/export-meeting-pdfs.mjs' '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>'
find '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/meetings' -path '*/exports/飞书原始纪要.pdf' -print
find '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/meetings' -path '*/assets/whiteboards/*' -print
rg -n 'internal-api-drive-stream\.feishu\.cn|api3-eeft-drive\.feishu\.cn' '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/meetings' -g '会议纪要.md'
rg -n '我做了|我完成了' '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/周复盘.md'
rg -n '^## 本周产出总账$|^## 可直接贴到 Sprint Review 的内容$|^## Skill 运行复盘$' '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/'{周复盘.md,迭代记录.md}
rg -n 'Slack范围|PROMPT:|TAIL:|[UC][0-9][0-9A-Z]{7,}|\"(text|user|ts|blocks)\"\\s*:|source_package: Codex workspace outputs' '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>' -g '*.md' -g '!**/meetings/**/会议纪要.md' -g '!**/meetings/**/会议转写.md'
rg -n 'ANTHROPIC_AUTH_TOKEN|Authorization|Bearer |access_token|refresh_token|client_secret|api_key|password|private_key|sk-[A-Za-z0-9_-]{20,}|op://.*/credential' '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>'
node '<skill-dir>/scripts/validate-package.mjs' '<vault>/工作/周报/<YYYY>/<MM>/<日期范围>'
```

第一人称风格检查针对 `周复盘.md`，不针对原始转写。密钥检查针对整个包。
