---
name: tech-doc-architect
description: "仅在用户显式调用 $tech-doc-architect 时使用：设计、重构、更新或评审技术架构文档。"
---

# 技术文档架构师

把技术事实整理成读者可以逐层建立心智模型、工程师可以定位实现、评审者可以检查边界的文档。重点不是堆章节或润色措辞，而是让抽象层级、系统边界、状态权威、生命周期、失败语义和验证证据彼此一致。

专业性的可观察结果是：领导能在 Overview 中复述系统边界和核心所有权；新成员能沿专题理解机制；工程师能追到代码与测试；运维人员能判断失败如何收敛。不要用更多章节、更多术语或更复杂的图制造“看起来专业”。

## 前置条件

- 确定性校验需要 Python 3.9+，只使用标准库，不需要认证或环境变量。
- 运行脚本前先把本 `SKILL.md` 所在目录解析为 `SKILL_ROOT`，不要假设当前目录是 Skill 根目录。
- 飞书、Obsidian、画图或代码仓库的读写能力按当前环境可用工具决定；没有外部写授权时只生成可审阅草稿。

## 脚本位置

唯一入口为 `$SKILL_ROOT/scripts/tech_doc_architect.py`。它只负责结构、链接、资源与跨载体语义校验，不替代事实审查和目标载体视觉验收。

## 子命令速查表

| 子命令 | 作用 | 必填参数 |
|---|---|---|
| `validate-content-model` | 校验平台无关内容模型 | `path` |
| `validate-docset` | 校验 Markdown / Obsidian 链接、资源与平台语法 | `--document-format`、`--root` |
| `validate-semantic-checksum` | 检查多个载体是否保留同一组规范化结论 | `path` |

## 通用 flag

每个子命令都支持 `--format json|human|summary`，默认 `json`。JSON 结果写入 stdout；人类可读与摘要结果写入 stderr。

## 场景决策树

区分四种工作：

- **新建**：从代码、设计资料和运行证据构建新文档或文档集。
- **重构**：保留仍然有效的事实，重建信息架构、图表和表达层级。
- **更新**：围绕已变化的事实直接改写对应内容，不把历史结论继续留在正文里。
- **评审**：检查现有文档的事实、抽象层级、边界、失败闭环、图文分工和目标载体可读性；只在用户同时要求修改时改写正文。

明确主要读者、他们读完要能回答的问题、范围边界和输出目标。优先从对话、现有文档和仓库中推断，只有会改变文档拓扑或外部写入范围的缺口才向用户提问。用户未指定载体时，以通用 Markdown 作为可审阅草稿；没有明确授权时，不发布或覆盖外部文档。

## 错误处理

| 退出码 | 含义 | 处理 |
|---|---|---|
| `0` | 校验通过 | 继续事实与视觉验收 |
| `2` | 输入文件缺失、不可读或 JSON 无法解析 | 修正输入后重试 |
| `4` | 内容模型、文档集或语义校验失败 | 根据 `errors` 修正文档，不绕过门禁 |

## 示例

```bash
python "$SKILL_ROOT/scripts/tech_doc_architect.py" validate-content-model \
  path/to/document-model.json

python "$SKILL_ROOT/scripts/tech_doc_architect.py" validate-docset \
  --document-format markdown \
  --root path/to/docs \
  --format summary

python "$SKILL_ROOT/scripts/tech_doc_architect.py" validate-semantic-checksum \
  path/to/semantic-checksum.json
```

## 交付物合同

按任务规模交付以下产物的必要子集，而不是机械生成全部文件：

- **证据账本**：关键断言、可信状态、证据来源和受影响章节。
- **内容模型**：平台无关的系统定义、边界、术语、不变量、专题问题与验证证据。
- **文档拓扑**：单页或 Overview + 专题，说明每页只回答什么问题。
- **图表计划与图稿**：每张图的问题、图型、节点、箭头语义和正文分工。
- **目标载体文档**：飞书、Obsidian、Markdown 中的一种或多种。
- **验收记录**：事实、链接、图表、缩放、主题和跨载体一致性结果。

需要显式落盘内容模型时，从 [assets/document-model.template.json](assets/document-model.template.json) 复制；需要快速建立页面骨架时复用 [assets/overview.template.md](assets/overview.template.md) 与 [assets/topic.template.md](assets/topic.template.md)，删除不适用段落，不要留下空模板。

## 核心工作模型

1. **建立证据底座**：检查代码、schema、测试、配置、运行记录和已有文档。把关键断言标为已验证、合理推断或待确认假设；不把命名、注释或旧文档单独当成事实。冲突事实先解决或标注，不用流畅文字掩盖。
2. **提炼架构模型**：按任务需要识别参与者、边界、组件职责、所有权、生命周期、状态权威、不变量、失败与恢复、验证方式和代码入口。不要为了模板完整而制造无关章节。
3. **设计认知顺序**：写正文前先按 [文档拓扑](references/document-structure.md) 确定阅读主线、专题的前置关系和分支位置。Overview 建立全局心智模型，专题逐步展开；用“读完本页能回答什么、下一步去哪”检验页面边界与承接。
4. **设计表达介质**：图负责拓扑、顺序、状态变化和所有权；正文负责原因、约束、例外和失败语义；表格负责精确映射和对比。三者不要重复同一句话。
5. **先做代表性切片**：大型文档先完成可独立验收的 Overview 与一个最能暴露架构边界的专题。切片按目标载体呈现，包含拟复用的图、表、提示块和导航；按 [质量门禁](references/quality-gates.md) 检查实际页面后再扩展。仅 Markdown 草稿或单张图通过，不代表飞书切片通过；缺外部写授权时保留为草稿，不宣称载体验收完成。
6. **扩展并按载体渲染**：先保持一份平台无关的内容模型，再转换为飞书、Obsidian 或 Markdown。多目标输出共享同一语义校验和事实来源，不能维护三份不同结论。
7. **在目标载体验收**：同时检查事实、链接、图表、层级、缩放可读性和目标平台的真实显示效果。API 成功、文件存在或本地大图可读都不等于交付完成。

需要理解完整方法时读 [references/methodology.md](references/methodology.md)；需要决定单页还是文档集、Overview 与专题如何拆分时读 [references/document-structure.md](references/document-structure.md)；准备交付或跨载体输出时读 [references/quality-gates.md](references/quality-gates.md)。

## 专业性约束

- 一个段落先给结论，再解释原因；删除不能帮助理解、执行或验收的过程性叙述。
- 同一张图只回答一个问题，箭头必须有稳定语义，跨图复用同一术语。
- 明确区分“执行完成”“用户可见”“实际交付”等不同事实面，避免把相邻概念合并成一个模糊状态。
- 先确定图的阅读问题和语义合同，再决定视觉风格；图不能依赖正文替它纠正错误箭头。
- 代码入口、测试或运行证据只在能帮助追溯时出现；不要把文件清单伪装成架构说明。
- Owner、文档状态、最后校验日期、架构驱动力或决策记录均为可选内容，只在读者确实需要时加入。
- 不使用 MVP、临时方案或历史阶段标签描述当前架构，除非它们仍是有效边界或用户明确要求保留。
- 文档正文只呈现当前有效结论；历史决策仍有解释价值时放入 ADR 或附录，而不是和当前架构并排。

## 图表策略

优先选择最能回答问题的图型：

- 总工作流：从输入到结果的阶段流程图；突出主线、核心循环与按需支路，避免画成能力或组件清单。
- 系统边界与外部依赖：C4 Context / Container。
- 请求、事件和恢复顺序：Sequence / Swimlane。
- 状态权威与终态：State model / Data lifecycle。
- 能力发现与策略：Pipeline。
- 部署所有权与故障域：Deployment。
- E2E 如何证明不变量：Test architecture。

设计、重绘或选择图稿风格前，读取 [技术图设计原则与样式偏好](references/diagram-design.md)，按阅读问题收敛内容，再决定构图、图标和视觉层级。没有当次指定风格时，优先从 **Style 1、5、8、10、11、12** 中选择；这是用户的默认候选集，不是排名，也不覆盖图型的语义要求。

若环境中有 `fireworks-tech-graph`，用它生成专业技术图，读取所选样式的当前 reference，并执行几何与视觉验证；不要把换色当成完整的样式实现。图稿必须在最终载体的实际宽度和主题下可读，而不是只在本地大图中成立。

## 输出路由

只读取当前目标对应的说明；多目标输出时逐个读取，但始终复用同一内容模型。

- **飞书 / Lark**：读 [references/output-feishu.md](references/output-feishu.md)。若 `lark-skills` 可用，通过它创建、更新和回读文档；外部写入仍需遵守用户授权边界。
- **Obsidian**：读 [references/output-obsidian.md](references/output-obsidian.md)。若 `obsidian-markdown` 可用，用它遵循现有 Vault 的链接、附件和属性约定。
- **Markdown**：读 [references/output-markdown.md](references/output-markdown.md)。输出可移植的 CommonMark / GFM，不混入平台专属语法。

多目标输出时先冻结以下“语义校验和”：一句话定义、系统内外边界、稳定术语、关键所有权、不变量、专题问题、终态和失败恢复语义。转换后逐项对照；允许排版不同，不允许技术结论漂移。

## 确定性检查

如果内容模型已落盘，运行：

```bash
python "$SKILL_ROOT/scripts/tech_doc_architect.py" validate-content-model \
  path/to/document-model.json
```

Markdown 或 Obsidian 文档集落盘后运行：

```bash
python "$SKILL_ROOT/scripts/tech_doc_architect.py" validate-docset \
  --document-format markdown --root path/to/docs
python "$SKILL_ROOT/scripts/tech_doc_architect.py" validate-docset \
  --document-format obsidian --root path/to/vault/subdir
```

同时输出多个载体时，把必须一致的规范化结论和各载体导出文本写入 checksum 文件，再运行：

```bash
python "$SKILL_ROOT/scripts/tech_doc_architect.py" validate-semantic-checksum \
  path/to/semantic-checksum.json
```

这些脚本只验证结构、链接、资源和平台语法，不替代事实审查与目标载体视觉验收。飞书验收必须按输出说明执行在线回读和实际页面检查。

## 完成标准

交付前逐项确认：

- 核心结论均有当前证据支持，推断和假设没有伪装成事实。
- Overview 能回答系统是什么、边界在哪里、内部如何分层、关键不变量是什么、专题从哪里继续读。
- 每个专题只围绕一个稳定问题展开，并覆盖相关的正常路径、失败/恢复和验证证据。
- 图、表、正文和代码入口使用同一术语，箭头方向与文字关系一致。
- 所有内部链接、图片、白板或嵌入资源可解析。
- 已在目标载体回读或渲染；多目标版本的技术结论一致。
- 最终交付明确说明已验证项、仍为推断的内容和任何无法完成的载体验收；不要用“已生成”替代“已可用”。

## References

| 文件 | 加载时机 |
|---|---|
| [references/methodology.md](references/methodology.md) | 需要建立事实模型、认知顺序或区分新建/重构/更新时 |
| [references/document-structure.md](references/document-structure.md) | 写正文前确定单页或文档集、阅读主线、专题承接及图文分工时 |
| [references/diagram-design.md](references/diagram-design.md) | 设计、重绘、选择或比较技术图风格时；包含总流程构图、图标与视觉层级、默认样式偏好及迭代方法 |
| [references/quality-gates.md](references/quality-gates.md) | 代表性切片完成后及最终交付前 |
| [references/output-feishu.md](references/output-feishu.md) | 飞书 / Lark 首稿设计富文本、制作代表性切片及更新文档时 |
| [references/output-obsidian.md](references/output-obsidian.md) | 输出到 Obsidian Vault 时 |
| [references/output-markdown.md](references/output-markdown.md) | 输出通用 Markdown 或仓库文档时 |
