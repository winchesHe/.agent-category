# 报告整理与发布

只在登记已有证据、生成/更新 HTML、发布 Site 或报告产物收尾时加载。直接消费 AI 已形成的结论和已检查媒体，不为渲染重启环境或重做业务，也不要求重新读取采集流程。原始证据不足时单列交付缺口，仅在授权范围补验相关场景并注明新时间；不补造来源或 before。

报告呈现业务结论与交付缺口；验收过程中是否继续调查、等待或暂停，按[主文件的问题处理入口](../SKILL.md#验收途中遇到问题)判断。用户仅要求整理已有材料时，按该范围交付并注明缺口，不据此启动业务复验。

## 保存位置

新任务的正式交付目录固定为 `~/.config/moego/moe-acceptance/<任务ID>/`，任务 ID 在此根目录内保持唯一。同一任务补充 Case、复验或更新报告时复用原目录，不按轮次另建任务目录。此约定由调用方落实；现有 Python API 仍接收显式的 `task_dir`，不会自动推导或迁移目录。

```text
~/.config/moego/moe-acceptance/<任务ID>/
├── manifest.json       # 摘要、轮次与证据登记
├── assets/             # 已检查的正式媒体，HTML 与 Sites 共用的来源
├── report/index.html   # 原有 HTML 输出
└── sites/              # Sites 生成项目，按需导出
```

临时采集文件经检查后通过 `register_asset` 登记到 `assets/`；正式证据不以临时目录或 `agent-workspace` 作为新任务的默认保存位置。已有任务继续使用其已确认目录，本约定不自动搬迁或删除历史文件。

模板源码与每次验收的数据分开维护：原有 HTML 模板保留在 Skill 的 `scripts/report_ui/`；Sites 模板位于 `templates/sites/`，通过 `scripts/sites_report.py` 导出。两种模板随 `person/skills/moe-acceptance` 源码维护，任务证据不放进模板目录。

整理已有报告时直接使用原任务目录及素材，不为整理或发布复制整个任务。确需暂存时只复制本次需要的内容；将独有修改、必要证据与诊断保存到正式位置并核对引用后，再清理无接续用途的临时副本。

## 报告产物收尾

按[主文件的资源边界](../SKILL.md#并发与资源)处理长期报告目录。保留 Site 指保留正式证据与报告记录、HTML、Sites 源码与配置、Git、`.openai/hosting.json` 中的 Site ID，以及 `public/report/` 中供报告使用的数据和媒体；不要求长期保留所有生成产物。发布目录中的媒体副本用于报告独立运行，不能因与原资产内容相同就删除。

| 产物 | 处理条件与动作 |
| --- | --- |
| 项目内 Vite 预构建缓存，如 `.sites-runtime/node_modules/.vite/` | 任务结束且相关预览、构建已停止，无接续用途时清理已确认的缓存路径；不整目录删除 `.sites-runtime` 中未知运行状态 |
| `dist/` 与本次生成的部署压缩包 | 发布复验及交付已完成、不再需要本地预览或保留回滚包时清理；保留重建所需源码和配置。再次执行依赖 `dist/` 的 `npm start` 前先重新构建 |

## HTML 交付与更新规则

一个任务固定对应一个 `report/index.html`。任务内多轮验收和交付都更新这个文件，不按轮次或 case 生成多个 HTML。HTML 是可选呈现层，不创建新的验收状态；生成失败只影响呈现，不改写已经形成的业务结论。

默认不渲染 HTML；满足以下任一条件时再生成：

- 用户明确要求交付页、评审页或可下载材料；
- 已有集中交付需求，多个 case、前后对比或媒体需要统一阅读；
- 需要把限制、风险、代码版本和证据来源交给未参与执行的人。

脚本默认只保存 manifest 和资产，不自动生成 HTML；正式交付时显式开启报告渲染，后续更新继续写入同一个 `report/index.html`。资产登记可以附带 `case_id`、`page_ref`、`comparison_id`、`viewport`、`capture_mode`、`width`、`height` 等脱敏 metadata；同一 `comparison_id` 的 before/after 资产在对应 case 内成组展示。图片按原比例展示，可点击放大、切换原始尺寸，支持关闭、上一张/下一张、键盘方向键与焦点恢复；视频和音频保留原生 controls，GIF 以可放大的动图展示。新模型默认展示当前轮次摘要及 Case 明确采用的证据，按 case 优先展示 Claim、结论和实际观察；输入、操作与所有 UI 验收条目可展开查看，证据详情保留完整采集信息和替代关系。顶部选择框可切换历史快照，正文、场景三态计数、Case 索引和放大图集一起切换；历史明确标注“不代表当前结果”，旧模式升级快照另标“证据未复核”。切换不写 manifest、不更改当前轮次，重新打开仍默认当前。当前模板未单独展示 limitation、代码版本和运行 runId；不能声称这些 UI 已实现。更新说明仍在 history 和 HTML 注释中；完整历史报告保存在 rounds，也可通过只读 API 查看。页面不引用 CDN、绝对源路径、未登记文件或秘密。

区分缺业务观察与缺交付证据：缺关键业务观察的 Case 才按事实标为“信息不足”；已有充分业务观察、仅缺约定截图时，保留业务 verdict，另列证据缺口与交付未完成。不能为压低报告总状态而改写业务结论，也不能声称渲染器会自动判断图片是否充分。

生成或更新报告后、交付或发布前，逐个按 [Case 与截图一致性检查](evidence-capture.md#case-与截图一致性检查)核对使用截图举证的 Case。打开最终页面并查看实际图集，连同 Case 描述、观察、结论和图片说明一起核对；确认 `evidence_ids` 采用的图片在对应 Case、当前轮次和前后位置正确呈现。只检查原始文件、manifest 或图片能否加载，不能代替此步骤。内容与呈现关系均未变化且已有核对依据的部分可复用；补选已有有效图不新增验收轮次。发现错配就修正并重检受影响部分，证据缺口或画面冲突按该检查规则处理，不能把导出成功作为图文一致的依据。

## 渲染辅助模块调用合同

报告保持重点优先的多 Case 长页：顶部摘要、场景三态计数与轮次选择、固定横向 Case 索引、每 Case 的目标/结论/实际观察、可展开的操作与 UI 验收、证据与证明说明、前后对比。复用当前模板的桌面/手机响应式布局、离线图片放大与键盘切换、视频/音频原生 controls 和 GIF 展示，不退化为文件清单。样式与交互分别维护在 `scripts/report_ui/report.css`、`scripts/report_ui/report.js`，由生成器内联到 HTML；分发 Skill 时保留这些资源，生成后的报告不依赖资源源目录、前端框架或外部请求。新模型未采用的资产留在资产库与只读结果的 `unassigned_assets`，不进入当前正文或放大图集。未升级的旧模式仍保留原“未归类证据”展示行为，不能当作新模型已生效。

入口为 `moe-acceptance/scripts/delivery_artifacts.py`，作为 Python 模块调用，不是 CLI、业务判定器或 session 总控。需要生成或更新报告时先读本节，复用以下函数，不重复实现 manifest 或 HTML。

| 函数 | 输入与返回 | 写入语义 |
|---|---|---|
| `initialize(task_dir, task_id, manifest=None, *, render_report=False, report_round=None)` | 已存在且目录名等于 `task_id` 的真实目录；返回完整任务数据 | 默认兼容旧模式；显式 report_round 启用轮次模型；重复初始化报错，默认不生成 HTML |
| `register_asset(task_dir, task_id, source, kind, label="", note="", metadata=None, *, captured_at=None, supersedes=None, replacement_reason="")` | 已检查且符合交付范围的本地媒体；返回含 asset_id 的资产记录 | 图片自动读取宽高，手填尺寸冲突时提示并留痕更正；不可解码时拒绝登记。复制并追加登记；新模型随后 update 显式选择；旧模式仍按开关刷新 |
| `update_asset_metadata(task_dir, task_id, asset_id, metadata, *, reason)` | metadata 合并补丁和非空原因；返回资产记录 | null 删除字段，空补丁可补齐图片尺寸。保留 ID、文件、时间、来源轮次与业务结论；归属须兼容已有采用记录，历史引用共用更正后的元数据。history 记录前后值和原因。相同值不重复记账；输入尺寸被更正时仍记录更正前后值。已开启 HTML 时刷新同一页 |
| `update(task_dir, task_id, content, change="", *, report_round=None)` | 完整的新摘要与本次变化说明；返回完整任务数据 | **完整替换** manifest；新轮次归档前轮完整内容，同轮仅更新当前内容；保留资产、history、报告开关 |
| `read_report(task_dir, task_id, *, round_id=None)` | 默认当前轮次，可选择已存在历史 ID | 只读返回 task_id、round、rounds 目录、manifest、assets、unassigned_assets；不写文件、不改变当前结果 |
| `check_html_export(task_dir, task_id)` | 已初始化任务；返回统一诊断 | 只读检查，不生成页面、不改变报告开关 |
| `render(task_dir, task_id)` | 已初始化任务；返回 HTML 的 `Path` | 执行同一诊断，通过后开启后续自动刷新，写入固定 `report/index.html` |

摘要使用 `title`、`summary`、`cases` 与 `ui_acceptance`。每个 Case 提供 `id`、`title`、`claim`、`input`、`observed`、`verdict`；UI 条目提供 `case_id`、`criterion`、`observed`、`verdict`。同一 Case 的所有 UI 条目都会展示。`verdict` 由 AI 明确填写 `通过`、`不通过` 或 `信息不足`，解释放在观察字段；渲染器不从自然语言推测通过。摘要可保留 `excluded_cases` 列表，其中 `title`、`reason` 展示为本轮范围说明；它不改写历史 Case，也不表示原故障已修复。顶部显示 Case 的通过、不通过、信息不足计数，汇总状态仍只来自 Case 结论：有明确不通过则不通过，空 Case、缺失或非标准结论为信息不足，只有非空且全部明确通过才采用通过状态。这只反映现有汇总实现，不证明证据或交付完成；UI 业务观察参与 Case 判断，媒体是否齐备不能混入业务 verdict。当前模板不能独立汇总交付缺口，缺必要证据时应在摘要明确“业务观察通过，证据不足，交付未完成”，仅作为不完整草稿，不交付为已完成报告；不能编造未实现字段或自动门禁。

### 摘要与实际观察的写法

`summary` 面向未参与验收的读者，以以下标签分三段：

- **背景**：CS 单或需求中的使用场景、问题及影响。
- **用户预期**：用户希望完成的操作和看到的结果。
- **改动方案 InScope**：本次实际改法、覆盖入口与范围，用业务行为说明。

Case 的 `observed` 写清对象、操作和实际结果，按不同入口、前后差异等需要分段，一段说明一组相关事实。参数、URL、命令等排查细节放在 `input`，直接支撑判断时可留在观察中。未观察到的结果如实写缺口，不把预期当事实。

两个字段均使用纯文本，以空行分段；HTML 完整展示摘要并保留段内单换行。内部标识等追溯信息留在交接记录，报告需展示的版本与环境可补充到当前 `report_round.reason`（轮次说明），保留原原因。影响结论的限制与证据缺口仍在摘要或观察中明示。

### UI 走查数据与呈现

识别到 UI 改动且有对应 Figma 时，执行标准按 [UI 走查](ui-design-review.md)；报告只消费已观察结论。新增可选 Case 字段 `kind`（`functional` 或 `ui`，省略沿用功能 Case），UI Case 可提供 `ui_comparisons`：

```json
{
  "id": "UI-ADDRESS-IOS",
  "kind": "ui",
  "title": "iOS 区域外地址",
  "claim": "区域外图标与设计一致",
  "input": "真实页面、代码来源与操作",
  "observed": "填写实际对比观察，不能照抄示例为通过",
  "verdict": "信息不足",
  "evidence_ids": ["asset-1", "asset-2"],
  "ui_comparisons": [{
    "id": "outside-ios",
    "platform": "iOS",
    "design_url": "https://www.figma.com/design/example/demo?node-id=1-2",
    "design_asset_id": "asset-1",
    "implementation_asset_id": "asset-2"
  }]
}
```

示例仅说明形状。UI 对比要求 `schema_version=2` 的显式轮次；旧报告先通过 `update(..., report_round=...)` 升级，不能沿用旧图集的隐式采用关系。两侧图片通过原 `register_asset` 登记为 image/screenshot，必须显式包含在同一 Case 的 `evidence_ids` 中；缺图时对应 ID 可省略或为 null，诊断返回证据不齐备 warning，页面显示缺图占位，业务结论不被自动改写。节点链接仅接受 Figma HTTPS 链接；平台及节点来源由 AI 核实。配对 ID 在 Case 内唯一，一对不能引用同一个资产。设计未变化时可复用旧轮次原图；替换实现图仍用 `supersedes`，并在完整 update 中同时更新采用列表与配对引用。跨 Case 归属仍按既有约束，不复制或篡改实际采集事实。

`ui_acceptance` 复用原字段，新增 `ui_comparison_id` 将检查点关联到本 Case 的一组图片。`criterion` 写检查对象、设计预期及来源，`observed` 写实际生效值/画面观察、差异及确认依据；`verdict` 仍为三态，不另存一份 UI 汇总。例如：

```json
{
  "case_id": "UI-ADDRESS-IOS",
  "ui_comparison_id": "outside-ios",
  "criterion": "区域外图标：按关联 Figma 节点核对轮廓、尺寸和描边",
  "observed": "填写实际属性与原图对比观察；未执行时说明缺口",
  "verdict": "信息不足"
}
```

每组图片下展示对应检查点，未关联的旧条目仍保留在操作记录。当前轮次缺检查点、关联或预期/观察/结论时返回 warning 并显示走查记录未齐备，可整理草稿，不能声称交付完成。引用不存在的配对，或 Case 为通过而已有检查点未通过/未明确结论，导出返回 error；工具不自动修正业务 verdict。规则不追溯改写历史结论。诊断只验证已填记录的结构与显式矛盾，不能证明检查点覆盖充分或画面相符。`update` 先保存记录再自动渲染；导出失败保留上一次页面，应修正当前记录后重新导出，不能将旧页视为新结果。

存在 UI Case 时，HTML 和 Site 分为「功能验收」「UI 走查」，分别显示三态计数；每个 Case 仅计数一次。UI 栏目左侧设计、右侧实现，窄屏上下排列，支持原比例放大。设计/实现配对使用 `ui_comparisons`，修复前后仍使用资产的 `comparison_id + before/after`，两者不混用；配对图片不重复出现在同 Case 的普通图集。

没有新字段的旧报告保持原展示；轮次切换同时切换栏目、对比图和结论。模板只展示 AI 提供的 verdict，缺配对警告不能自动改写业务结论或被当作交付通过。Site 模板升级为 1.3.1；既有 Site 不会被静默改写源码，版本冲突仍先保留项目、核对自定义改动并明确升级后再导出，不能只改模板标记绕过升级。

### 轮次、证据与兼容

新建多轮报告时显式使用 `report_round`；已有任务用 `update(..., report_round=...)` 升级为 `schema_version=2`。轮次参数包含非空 `id`、`reason`，可含 `label`、带时区的 ISO `observed_at`；未知时间保留 null，不能拿登记时间代替。`legacy` 为升级快照保留 ID，不可指定为当前轮次。

- `current_round` 保存当前轮次元数据，`rounds` 保存此前完整摘要、UI 条目和当时资产 ID 范围，避免后续资产混入历史。当前及历史共用原媒体文件，不为轮次重复复制。
- 真实验收/补验由 AI 明确提供新 ID，才归档前轮。省略参数或使用当前 ID 时只更新当前轮；同 ID 可只传 `{"id": "R1"}`，其它元数据保留。重新渲染和纯文案修改不新增轮次，不能用旧 ID 覆写历史。
- 目标不变时复用 Case ID；每个 Case 显式填写 `evidence_ids`。空列表允许非视觉或待补证据，但不代表证据充分。仍由 AI 说明必要媒体缺口，不修改已有业务 verdict 来掩盖交付不足。
- `asset_id` 为任务内稳定标识；`round_id` 是登记时的当前来源轮次，采集事实由可空 `captured_at` 说明。新图应在相应轮次登记；确切时序未知时不能猜。`registered_at` 仅表示登记时间。
- 替代旧图时传 `supersedes=[旧asset_id, ...]` 和 `replacement_reason`。仅记录关系，不删除旧图、不自动选择新图、不自动改变业务结果。`evidence_ids` 是展示的唯一选择来源；有效旧图或跨轮 before/after 可以显式引用，保留原始来源和采集时间。
- 未归类旧图只有经实际检查并显式引用后才进入新模型正文；已有明确 Case 归属的图不能引用到其它 Case。重复、未知或跨 Case 引用、不安全路径和缺文件均拒绝，不静默跳过。
- `update` 仍是完整替换，不自动继承未复验 Case。只有已有观察仍有效时才显式保留，并说明复用，而不是将新轮次伪装成全量重验。

旧文件只读时在内存按资产原顺序补稳定 ID，不修改磁盘，不补造轮次和采集时间。显式升级保存当前已有内容为“旧报告快照（未复核）”，旧摘要及原更新记录保留；当前新摘要必须显式选择证据。更早 history 的截断摘要不能恢复完整轮次；有外部完整备份时先备份现状，在暂存目录恢复可信快照，再通过现有 API 升级、登记和选择证据，核验后替换原任务的同一报告。原备份保留，不手工拼造历史数据。

轮次页展示观察时间；证据展示采集时间、来源轮次和已记录的替代关系。未知值直接标为“未知”，观察收据时间不能冒充精确截图时间。历史文件缺失时，历史正文保留原业务结论并明确提示媒体缺失，不展示该轮图集；不因此阻断当前有效证据的呈现。当前引用缺文件仍严格报错，不降级为静默忽略。历史资源仍随报告保留，历史隔离是呈现语义而非访问控制，发布前必须按目标访问范围一并检查。

以下代码在仓库根目录运行，示例仅演示输入形状，不代表已经验收：

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("moe-acceptance/scripts").resolve()))
from delivery_artifacts import initialize, register_asset, update, read_report, render

task_id = "acceptance-example"
evidence_root = Path.home() / ".config" / "moego" / "moe-acceptance"
evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
task_dir = evidence_root / task_id
task_dir.mkdir(mode=0o700)
content = {
    "title": "列表筛选验收",
    "summary": "待执行",
    "cases": [{"id": "C1", "title": "筛选结果", "claim": "仅显示匹配项",
               "input": "筛选条件", "observed": "尚未执行", "verdict": "信息不足",
               "evidence_ids": []}],
    "ui_acceptance": [],
}
initialize(task_dir, task_id, content,
           report_round={"id": "R1", "reason": "首次验收", "observed_at": None})
# 执行验收后更新真实观察；每次传入要保留的全部 Case 和 UI 条目。
update(task_dir, task_id, content, change="建立待执行摘要")
report = render(task_dir, task_id)
# 有已检查的真实图片时再登记；宽高自动读取，viewport 和时间仅填已知事实。
# 前后两图经 Agent 核对后使用相同 comparison_id，独立补验不填：
# before = register_asset(task_dir, task_id, before_source, "before", "修复前列表",
#                         metadata={"case_id": "C1", "comparison_id": "list-result"})
# after = register_asset(task_dir, task_id, after_source, "after", "修复后列表",
#                        metadata={"case_id": "C1", "comparison_id": "list-result"})
# extra = register_asset(task_dir, task_id, supplement_source, "screenshot", "另一条件补验",
#                        metadata={"case_id": "C1"})
# content["cases"][0]["evidence_ids"] = [before["asset_id"], after["asset_id"], extra["asset_id"]]
# 补充真实观察和结论后，完整 update 采用证据：
# update(task_dir, task_id, content, change="前后列表配对，另一条件补验独立展示")

current = read_report(task_dir, task_id)
# 新一轮实际补验时，传完整摘要和新 report_round，再登记本轮媒体并显式采用。
# update(task_dir, task_id, new_content, report_round={"id": "R2", "reason": "补验受影响搜索"})
# previous = read_report(task_dir, task_id, round_id="R1")
```

`kind` 支持 `screenshot/image/video/gif/audio/before/after/comparison`；媒体必须是允许扩展名的普通文件、非 symlink、单文件不超过 100 MB。metadata 使用实际 `case_id`、`page_ref`、`comparison_id`、`viewport`、`capture_mode`、`width` 和 `height`，缺失的旧采集事实不填默认值。文本过滤不等于媒体脱敏，登记前仍由 AI 检查画面。

PNG、JPEG、WebP、GIF 宽高从文件解码取得；带 EXIF 方向时使用浏览器呈现后的像素轴。手填尺寸不一致时以文件为准，提示并记录更正，不中断登记，不把图片尺寸当作浏览器 viewport。视频／音频不通过图片解码器检查，时长等仍来自实际记录。

常见异常：`FileExistsError` 表示已初始化或资产目标已存在，不覆盖旧文件；`FileNotFoundError` 表示未初始化或所选证据缺失；`ValueError` 表示目录、schema、轮次、引用或 metadata 不合法；`OSError` 表示文件系统写入失败。错误引用在 update 写入前拒绝；登记 manifest 失败只回收本次新资产文件。原证据损坏时仍可登记替代图，再显式 update 修正引用，不需要重建任务。只读不更改磁盘；写入后纯渲染失败保留已存数据，修复呈现即可，不重跑业务或改写 verdict。

## 导出诊断与处理

HTML 的生成也是导出交付物。使用 `delivery_artifacts.check_html_export` 可先只读核对缺口；处理后调用原 `render` 生成页面。需要 Sites 时才调用 `check_sites_export` / `export_sites`。

围绕约定交付物检查：**内容能否让评审理解，证据能否访问并支持说明，元数据是否可信，展示是否保留必要信息，输出是否写入正确项目。** 配对只是展示关系的一种，不把检查限定为某个 Case、布局或固定问题清单。工具只能识别已实现的确定规则，未报告问题不等于没有缺口，仍由 Agent 对照 Claim、真实媒体和最终页面补充判断。

`delivery_artifacts.check_html_export(task_dir, task_id)` 与 `sites_report.check_sites_export(task_dir, task_id, *, presentation=None)` 共用诊断规则，分别检查 HTML 与 Sites 的实际输出合同。两者只读返回 `schema_version`、`task_id`、`can_export`、`requires_review`、按严重程度汇总的 `counts` 和 `diagnostics`。每条诊断沿用统一合同，后续新增规则不另建专项流程：

| 字段 | 含义 |
|---|---|
| `code` / `category` | 稳定问题代码与归类 |
| `severity` | `error` 确定错误、`warning` 需要上下文判断、`info` 已确认的处理或降级说明 |
| `round_id` / `case_id` / `asset_ids` / `field` | 受影响位置；不适用时为空 |
| `message` / `suggested_action` | 具体事实与下一步建议；建议不扩展任务授权 |

当前覆盖结构和引用、采用文件的路径／存在性／类型／大小、图片解码及尺寸、metadata 合法性、当前 Case 缺失内容或未识别结论、模板未展示的 Case 字段、媒体标题与展示关系，以及展示配置和输出目录冲突。历史媒体仍检查可访问性和元数据，历史缺文件保留文字并提示图集降级；当前内容与关系检查不套用旧快照。显式轮次中未采用的旧图不阻断生成，非视觉 Case 允许空媒体列表。HTML 继续支持旧模式及旧快照的全量图集：检查这些媒体，不补造轮次或采用关系；不安全路径等确定错误会明确报错并保留已有页面，不再静默跳过；Sites 沿用显式升级要求，旧快照仅展示文字。

按问题影响处理，不按某个错误代码固化操作链：

1. **文件中可确认的事实**由工具补齐：导出只在副本补缺失宽高并返回 `info`；需要写回时调用 `update_asset_metadata` 留痕。尺寸冲突同样在副本按文件更正并返回带前后值的 `info`，不阻断生成；登记与修订会将更正写入 history，未知采集事实不猜填。
2. **确定错误**先恢复文件、修正引用／元数据或输出冲突，再重检。必要证据无法恢复时保留缺口，不更改业务结论来伪装完成。
3. **需要判断的问题**由 Agent 核对上下文和真实媒体，补充内容、纠正采用／展示关系，或在同轮更新说明中记录保留方式及限制。不自动配对、不补造观察，也不机械转交用户确认。
4. 根据修改重检并目视检查最终页面；规则未覆盖但实际发现的问题也按同样方式处理。仍影响交付时，明确草稿与未完成项。

`render`（HTML 生成）与 `export_sites` 均返回路径，并在写入前自动执行对应的同一检查；HTML 无需额外执行 Sites 导出。确定错误抛出 `ExportValidationError`，`.diagnostics` 保留结构化结果；缺少当前媒体的异常也兼容 `FileNotFoundError`。待判断问题通过 `ExportDiagnosticsWarning` 的正文及 `.diagnostics` 提示，不静默吞掉或自动改写业务 verdict。`can_export=true` 仅表示可生成，`requires_review=false` 仅表示已有规则无待判断项，均不能证明证据充分或代表发布许可。复制、权限、磁盘等实际写入故障仍按 `OSError` 处理；只读检查不能保证后续写入成功，失败保留此前输出。

## Codex Sites

Codex Sites 是可选的远程呈现层。一个任务最多对应一个独立 Site，与本地 HTML 共用同一份已检查的交付内容；后续补充 case、截图、录屏或前后对比时更新同一 Site 和同一 HTML。仅在完成有意义的验收节点、用户明确要求更新或新增正式证据后更新，避免每次 HMR 都产生无用版本。

### 本地预览的共享依赖

所有任务的 `sites/node_modules` 都链接到固定的 `~/.config/moego/moe-acceptance/.shared-deps/node_modules`，本机只维护一份当前依赖，不按锁文件、Node ABI 或任务保留历史版本。模板沿用 `npm run install:ci`，Sites 安装工具也会调用这个入口：共享依赖不存在时安装一次，存在时直接连接，不因旧报告的锁文件不同而重新安装或降级。

模板依赖升级或切换 Node 后，先停止使用共享依赖的预览和构建，在已更新到当前模板的项目中执行 `npm run install:ci -- --refresh`，按该项目的 `package.json`、`package-lock.json` 和可选 `.npmrc` 统一刷新。“当前依赖”以当前模板的锁文件为准，不自动追逐 npm 上的最新包。刷新先在临时目录安装并校验，成功后替换固定目录并删除旧依赖；失败保留原依赖。安装锁只保护首次安装和刷新，冲突时等待正在执行的操作结束再重试。刷新后重启预览。

每个项目的 Vite 缓存位于自己的 `.sites-runtime/node_modules/.vite/`；这里只存预构建缓存，保留 `node_modules/.vite` 后缀是为了兼容当前 Vinext 的 CommonJS 转换器，不是另一份依赖安装。报告数据、源码、运行状态和 Site ID 仍各自保存；缓存与构建输出按上方报告产物收尾规则处理。导出本身仍不安装依赖，首次需要预览或构建时再沿 Sites 流程调用安装入口。仅查看 `report/index.html` 无需 Node 依赖。

首次迁入共享依赖时，补入模板的 `scripts/shared-deps.mjs`、更新 `scripts/install-ci.mjs`，并将 Vite 的 `cacheDir` 设为上述项目内缓存路径。停止该项目的预览后执行安装入口；原 `node_modules` 会保留为 `.sites-runtime/node_modules.previous`。预览与构建核对成功后清理这份迁移备份；失败可移除新链接并将备份移回。共享目录不随单个验收任务收尾删除。

旧报告需要继续使用时，先核对自定义修改并将预览代码、运行配置和依赖声明更新到当前模板，再复用当前共享依赖；保留报告证据、Git 和 Site ID，不为兼容旧预览恢复历史依赖。不要直接在共享链接上运行 `npm install`、`npm ci` 或修改包文件。调整模板依赖时先解除项目的 `node_modules` 链接，更新依赖与锁文件，再通过 `install:ci -- --refresh` 统一替换。已有 pnpm/yarn/bun、workspace 或本地文件依赖项目沿用其原安装方式，不强行改成 npm 共享安装。

复用 `scripts/sites_report.py` 的 `export_sites(task_dir, task_id, *, presentation=None) -> Path`。该模块通过现有 `read_report` 读取当前与历史内容，首次复制 `templates/sites/`，后续只刷新 `sites/public/report/` 中的报告 JSON 和被引用媒体。相同内容媒体按 SHA-256 复用，未采用资产不进入发布目录；源码、Git 和 `.openai/hosting.json` 中已登记的 Site ID 保留。导出不修改原 manifest、资产、HTML 或报告开关，不安装依赖，也不负责创建与部署 Site。

```python
# 沿用上文 skill scripts 的 sys.path 和已初始化任务。
from sites_report import check_sites_export, export_sites
assessment = check_sites_export(task_dir, task_id)
# 先按上文诊断规则处理 assessment，再生成并目视核对页面。
site_dir = export_sites(task_dir, task_id)
```

页面复用已确认的 MoeGo 主题、Manrope 与 shadcn，报告概况和全部案例共用文档滚动条，目录随阅读位置高亮并支持平滑定位；目录在屏幕空间充足时吸顶，过长时随页面滚动。截图为主要证据，录屏、前后对比、竖屏 App、GIF、音频和无媒体场景按实际记录展示。全部 Case、UI 条目、采集时间及来源关系从同一数据读取；未知事实不补默认值。可选目录短标题、主证据和媒体 metadata 的具体合同见 [Sites 模板说明](../templates/sites/README.md)。

新模型的当前引用必须有效，坏路径、非法配置或复制失败保留此前输出。历史缺媒体时保留原业务结论并提示缺失；旧模式先通过原 API 显式升级，未经复核的 legacy 快照只导出历史文字。模板版本冲突或目录属于其他任务时拒绝覆盖，需要检查并明确处理，不删除原始证据。模板内部不含任务素材或 Site ID。

通过本 Skill 新建并发布的 Site 默认公开，用户明确指定的访问范围优先。将公开要求传递给 Sites Skill：创建后将 `access_mode` 设为 `public`，发布后回读确认公开状态。已有 Site 更新时沿用 Sites Skill 的当前访问范围规则。

只上传已检查的截图、录屏、对比图和说明，不上传原始 JSONL、凭据或未检查媒体。Sites 更新失败时，本地 HTML 和本地证据仍然有效，但不能声称远程 Site 已更新。浏览器、Whistle、dev 和录制资源 cleanup 与 Site 生命周期分开，不能删除正式证据或远端 Site。Site 的创建、更新和部署使用 Sites Skill，不在这里复制发布管理器。
