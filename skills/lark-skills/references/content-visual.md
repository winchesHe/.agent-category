# content-visual：幻灯片 + 白板

合并 lark-cli 的 `lark-slides`（幻灯片，XML 协议）+ `lark-whiteboard`（画板，DSL / Mermaid / PlantUML / OpenAPI）。

> 鉴权 / 身份处理见 [`lark-shared.md`](./lark-shared.md)。
> Wiki 链接 / token 解析见 [`content-doc.md`](./content-doc.md)。
> ⚠️ **本领域绝大多数操作要求 `--as user`**——幻灯片是用户内容资源。

## 适用场景

- **幻灯片 / Slides**：创建演示文稿、读取 / 修改单页、添加图片、套用模板、块级替换
- **白板 / Whiteboard**：导出预览图 / 原始结构、用 Mermaid / PlantUML / DSL 创作或更新画板
- **可视化表达需求**：架构图、流程图、组织关系、时间线、因果、对比——即使用户没说"画板"也用本 reference

## 命中的 lark-cli skill

- `lark-slides`（slides 命令组，XML 协议 v1）
- `lark-whiteboard`（whiteboard 命令组）

---

# Part A：lark-slides（幻灯片）

## 关键约束

1. **XML 协议**：通过 `slides_xml_schema_definition.xml` 定义；生成任何 XML 前**必读** lark-cli `lark-slides/references/xml-schema-quick-ref.md`，**禁止凭记忆猜结构**。
2. **`<slide>` 直接子元素只允许** `<style>` / `<data>` / `<note>`；文本和图形必须放 `<data>` 内。
3. **文本通过 `<content>` 表达**：`<content><p>...</p></content>`，**不能**直接把文字写在 shape 内。
4. **`<img src>` 只能用上传到飞书 drive 的 `file_token`**——禁止 `http(s)` 外链 URL（飞书渲染端不代理外链，PPT 里通常不显示）。流程：本地存 → `+media-upload` → 写 `file_token` 进 src。**图片 ≤ 20 MB**（不支持分片）。
5. **演示文稿至少保留一页**——删除最后一页会失败。

## URL / Token

| URL 格式 | Token | 处理 |
|---|---|---|
| `/slides/<token>` | `xml_presentation_id` | 直接用 |
| `/wiki/<wiki_token>` | wiki_token | **必须** `wiki spaces get_node` 解析 → `obj_type=slides` → `obj_token` 即 `xml_presentation_id` |

`+replace-slide` 和 `+media-upload` 自动解析两种 URL；原生 API 仍需手动解析 wiki。

## 模板优先工作流

用户提到"模板 / 套用模板 / 风格 / 版式"，或需求落在常见场景（汇报 / 产品 / 商业计划 / 培训 / 晋升）时，**先做模板检索**：

```bash
# 1. 把用户原话整句放进 --query（不要只放短词）
python3 skills/lark-slides/scripts/template_tool.py search --query "<用户需求原文>" --limit 3
# → 默认给 2-3 个候选

# 2. 用户锁定模板后看页型摘要
python3 skills/lark-slides/scripts/template_tool.py summarize --template <id> --label <封面|目录|分节|内容|结尾>

# 3. 仅当需要复用布局骨架时
python3 skills/lark-slides/scripts/template_tool.py extract --template <id> --label <页型> --out /tmp/slice.xml

# 4. 生成本地 XML 后做布局风险检查
python3 skills/lark-slides/scripts/layout_lint.py --input /tmp/presentation.xml
```

> 这两个脚本路径基于 lark-cli 仓库布局；本仓库直接调相对 lark-cli 安装目录的脚本即可。

**规则**：
- 不直接读完整模板 XML 文件，太大；用 `summarize` / `extract`。
- 候选给 2-3 条（模板名 + 适用场景 + 风格/色调 + 推荐理由）；用户没要求看更多就别贴目录。
- 锁定后**复用 `<theme>` / 配色 / 页面流 / 布局骨架**，但**改写所有占位文案**为用户真实内容。
- `layout_lint.py` 有 error 先修 XML 再创建；warning 检查是否装饰/背景误报。

## Shortcut 速查表

| Shortcut | 用途 | 关键 flag |
|---|---|---|
| `+create` | 创建 PPT（可选 `--slides '[xml1,xml2,...]'` 一步建多页；支持 `<img src="@./local.png">` 占位符自动上传） | `--title` `--slides` |
| `+media-upload` | 上传本地图片到指定演示文稿 → `file_token`（≤ 20 MB） | `--file ./local.png` `--presentation $PID` |
| `+replace-slide` | 已有页面**块级替换 / 插入**（`block_replace` / `block_insert`），不动页序 | `--whiteboard-token` `--parts` |

## 创建方式选择

| 场景 | 推荐 |
|---|---|
| 1-3 页、结构简单、特殊字符少 | `slides +create --slides '[...]'` 一步 |
| 多页、含中文 / 大段文本 / 复杂布局 / 嵌套引号 / 较多特殊字符 / 超 10 页 | **两步法**：先 `+create` 空白 → `xml_presentation.slide.create` 逐页加 |
| 已有 PPT 追加 | `xml_presentation.slide.create`，必要时 `before_slide_id` |

> ⚠️ **`+create --slides` 不是原子操作**——中途某页失败会保留前面已成功的页。失败后先记录 `xml_presentation_id`，回读确认现状，再决定修复或追加。

## 已有 PPT 编辑：优先块级替换

| 场景 | 方法 |
|---|---|
| 改单个 shape / img / 文字 / 颜色 | `+replace-slide` 的 `block_replace` |
| 给某页加图（不动其它元素） | ① `+media-upload` 拿 `file_token` ② `+replace-slide` 的 `block_insert` 插入 `<img src="<file_token>" .../>` |
| 整页结构要重做 | `slide.delete` 旧页 + `slide.create` 新页 |

详见 lark-cli `lark-slides-edit-workflows.md`（action 决策树 + 完整读-改-写流程）。

## 创建后验证（**必做**）

`+create` 成功 ≠ 内容正确。完成后**必须**回读 XML 校验：

```bash
lark-cli slides xml_presentations get --as user \
  --params '{"xml_presentation_id":"<id>"}'
```

逐项检查：
- [ ] 页数与预期一致
- [ ] 每页 `<data>` 含所有预期 `<shape>` / `<img>` 等
- [ ] 文本未被 shell / JSON 截断或转义损坏
- [ ] 关键布局（封面、内容区、结尾页）实际生成
- [ ] 坐标 / 尺寸合理，无堆叠 / 越界
- [ ] 配色统一、字号层级合理

发现问题先读问题页 XML 判断是生成问题还是传参损坏；再 `+replace-slide` 局部修，复杂页面改两步法。

## XML 自检 4 项

生成 XML 真正调用前：

- [ ] **特殊字符转义**：文本节点和属性值里的裸 `&` → `&amp;`；文本里的 `<` → `&lt;`、`>` → `&gt;`。例：`Q&A` → `Q&amp;A`，URL 属性 `a=1&b=2` → `a=1&amp;b=2`。
- [ ] **属性引号安全**：XML 属性、shell 引号、JSON 字符串包装互不打断。
- [ ] **结构合法**：`<slide>` 下只 `<style>` `<data>` `<note>`，文字都在 `<content>` 内。
- [ ] **路径正确**：`<img src="@...">` 只在 `+create --slides` 链路替换；直接调 `xml_presentation.slide.create` **必须**先 `+media-upload` 拿 `file_token`。

## 渐变背景陷阱

渐变**必须** `rgba()` 格式 + 百分比停靠点：
```
linear-gradient(135deg,rgba(15,23,42,1) 0%,rgba(56,97,140,1) 100%)
```
用 `rgb()` 或省略停靠点 → 服务端回退**白色**。

## 风格 / 配色快速建议

| 主题 | 风格 | 背景 | 主色 | 文字 |
|---|---|---|---|---|
| 科技 / AI / 产品 | 深色科技风 | 深蓝渐变 | 蓝 `rgb(59,130,246)` | 白 |
| 商务 / 季度总结 | 浅色商务风 | 浅灰 `rgb(248,250,252)` | 深蓝 `rgb(30,60,114)` | 深灰 |
| 教育 / 培训 | 清新明亮风 | 白 | 绿 `rgb(34,197,94)` | 深灰 |
| 创意 / 设计 | 渐变活力风 | 紫粉渐变 | 粉紫 | 白 |
| 周报 / 日常 | 简约专业风 | 浅灰 + 顶部彩色渐变条 | 蓝 | 深 |
| 用户未指定 | 默认简约专业风 | 同上 | 同上 | 同上 |

## 常见错误

| Code / 现象 | 含义 / 处理 |
|---|---|
| 400 XML 格式错 | 检查标签闭合、转义 |
| 创建成功但页面空白 / 内容丢失 | shell 转义或长参数问题 → 改两步法 + 创建后立即回读 |
| 404 演示文稿 / 幻灯片不存在 | 检查 `xml_presentation_id` / `slide_id` |
| 1061002 媒体上传 params error | 必须 `+media-upload`（不要手拼 `medias/upload_all`）；slides 唯一 `parent_type` 是 `slide_file` |
| 1061004 forbidden 编辑无权限 | 当前身份没编辑权（bot 多见）→ 授权或 `+create --as bot` 自创 |
| 3350001 XML non-well-formed / replace 失败 | 优先查未转义 `&` `<` `>`；`layout_lint.py` 定位行；replace 场景查 `block_id` 和 `<content/>` |
| 3350002 revision_id 大于当前版本 | 用 `-1` 取当前，或 `xml_presentations.get` 重读最新 |
| validation: unsafe file path | `--file` 必须是 CWD 内相对路径；先 `cd` 到素材目录 |

---

# Part B：lark-whiteboard（白板）

## 何时用

用户要可视化表达：架构、流程、组织关系、时间线、因果、对比——**即使没说"画板"**。

## Shortcut

| Shortcut | 用途 |
|---|---|
| `+query` | 查画板。`--output_as image/code/raw`：图片预览 / Mermaid/PlantUML 代码 / 原始节点 JSON |
| `+update` | 更新画板。`--input_format mermaid/plantuml/raw`；`--source -` 从 stdin 读，`--source <file>` 从文件读 |

⚠️ **数据来自本地文件时必须用 `--source - --input_format <格式>`**：
```bash
cat chart.mmd | lark-cli whiteboard +update <token> --source - --input_format mermaid --as user
```

## 决策矩阵

| 用户需求 | 路径 |
|---|---|
| 看画板 / 导出图 | `+query --output_as image` |
| 取 Mermaid / PlantUML 代码 | `+query --output_as code` |
| 改文字 / 颜色（小改） | `+query --output_as raw` → 改 JSON → `+update --input_format raw` |
| 用户给了代码或指定 Mermaid/PlantUML | `+update --input_format mermaid/plantuml` |
| 复杂图表（架构 / 流程 / 组织） | 走"创作 workflow"：先 query 看现状 / 选模板 → 渲染 SVG 或 DSL → `+update` 写入 |
| 修改/重绘已有复杂画板 | 走"修改 workflow"：先 `+query --output_as code` 看是否有源代码 → 改源代码或重绘 |

## 获取 board_token

| 用户给的 | 怎么拿 |
|---|---|
| `wbcnXXX` 直接给 | 直接用 |
| 文档 URL（已有画板）| `lark-cli docs +fetch --doc <URL> --as user` → 从 `<whiteboard token="xxx"/>` 提取 |
| 文档 URL（要新建画板）| `lark-cli docs +update --api-version v2 --doc <doc_id> --command append --content '<whiteboard type="blank"></whiteboard>' --as user` → 从 `data.new_blocks[0].block_token` 取 |

## 写入前强制 dry-run

```bash
# Step 1：dry-run 探测会删除多少节点
npx -y @larksuite/whiteboard-cli@^0.2.10 -i <文件> --to openapi --format json \
  | lark-cli whiteboard +update --whiteboard-token <token> \
    --source - --input_format raw \
    --idempotent-token <≥10 字符唯一串> \
    --overwrite --dry-run --as user
# 输出 "XX whiteboard nodes will be deleted" → 必须向用户确认

# Step 2：用户确认后真正写入（去掉 --dry-run）
```

> `--idempotent-token` ≥ 10 字符，建议时间戳+标识拼接（`1744800000-board-1`），避免重试重复写。

## 渲染路径选择

按图表类型 + AI 身份选路径：
- 思维导图、时序图、类图、饼图、甘特图 → Mermaid 路径（任意身份）
- 其它图表，身份是 Claude / Gemini / GPT / GLM → SVG 路径
- 其它图表，身份是 Doubao / Seed / Other → DSL 路径

详细规则、模板、各路径完整工作流见 lark-cli `lark-whiteboard/routes/`：`mermaid.md` / `svg.md` / `dsl.md`。

⚠️ **SVG 路径失败回退**：渲染命令崩溃 / 两轮改写仍 `--check text-overflow` error / PNG 视觉严重错乱（文字大面积溢出 / 元素重叠 / 布局崩溃）→ **丢弃 SVG，改 DSL 从零重画**，不要逐行修补。

## 产物目录

`./diagrams/YYYY-MM-DDTHHMMSS/`（本地时间，不含冒号 / 时区）

```
diagram.svg           ← SVG 源
diagram.mmd           ← Mermaid 源
diagram.json          ← DSL 源 / OpenAPI JSON
diagram.gen.cjs       ← 坐标计算（DSL 脚本构建方式）
diagram.png           ← 渲染结果
```

---

## 典型示例

```bash
# A. 创建简单 PPT（一步法）
lark-cli slides +create --as user --title "Demo" --slides '["<slide xmlns=\"http://www.larkoffice.com/sml/2.0\"><style><fill><fillColor color=\"rgb(248,250,252)\"/></fill></style><data><shape type=\"text\" topLeftX=\"80\" topLeftY=\"80\" width=\"800\" height=\"100\"><content textType=\"title\"><p>标题</p></content></shape></data></slide>"]'

# B. 给已有 PPT 加一页（两步法 + jq 安全包装）
lark-cli slides xml_presentation.slide create --as user \
  --params '{"xml_presentation_id":"<id>"}' \
  --data "$(jq -n --arg content '<slide ...>...</slide>' '{slide:{content:$content}}')"

# C. 给某页换个文字（块级替换）
lark-cli slides +replace-slide --as user \
  --whiteboard-token <id> --slide-id <slide_id> \
  --parts '[{"action":"block_replace","block_id":"shape_xxx","content":"<shape ...><content><p>新文字</p></content></shape>"}]'

# D. 用 Mermaid 创作画板
cat > /tmp/flow.mmd <<'EOF'
graph TD
  A[需求] --> B[设计]
  B --> C[实现]
  C --> D[上线]
EOF
cat /tmp/flow.mmd | lark-cli whiteboard +update <board_token> \
  --source - --input_format mermaid --as user

# E. 取画板的 Mermaid 代码
lark-cli whiteboard +query --whiteboard-token <token> --output_as code --as user
```

## NEVER 规则（领域特有）

### Slides

- ❌ **`<img src>` 不要用 `http(s)` 外链 URL**——必须 `file_token`，否则不显示。
- ❌ **不要凭记忆猜 XML 结构**——必读 lark-cli `xml-schema-quick-ref.md`。
- ❌ **`<slide>` 直接子元素不要放别的**——只 `<style>` / `<data>` / `<note>`，文字必须 `<content>` 内。
- ❌ **复杂内容 / 中文 / >10 页不要 `+create --slides '[...]'` 一步**——shell 截断风险，改两步法。
- ❌ **创建后不要假设成功就内容正确**——必须 `xml_presentations get` 回读校验。
- ❌ **渐变背景不要用 `rgb()`** ——服务端会回退白色，必须 `rgba()` + 百分比停靠点。
- ❌ **直接调 `slide.create` 时不要写 `<img src="@./local.png">`** ——`@` 占位符**只在 `+create --slides` 链路替换**；其它链路必须 `+media-upload` 拿 `file_token` 写 src。
- ❌ **`--file` 不要给绝对路径或上层路径**——必须 CWD 内相对路径，先 `cd` 到素材目录。
- ❌ **改单元素不要整页重建**——优先 `+replace-slide` 块级替换。

### Whiteboard

- ❌ **`+update` 写入已有内容画板不要跳过 `--dry-run`**——必须先探测删除规模。
- ❌ **本地文件不要 `--source <file>`**——必须 `--source - --input_format <格式>`（stdin 模式）。
- ❌ **SVG 渲染严重失败不要逐行修补**——直接换 DSL 从零重画。
- ❌ **`--idempotent-token` 不要用短串**——≥ 10 字符，避免重试重复写。

## 不在本 reference 范围

- 文档块里嵌入画板 / `<whiteboard>` 标签 → [`content-doc.md`](./content-doc.md)（lark-doc 调度多画板）
- 妙记封面（也是 whiteboard）下载 → [`collab-calendar.md`](./collab-calendar.md)
- 资源发现 → [`content-doc.md`](./content-doc.md) 的 `drive +search`

## 溯源

- lark-cli `skills/lark-slides/SKILL.md`（v1.0.0，slides v1）
- lark-cli `skills/lark-whiteboard/SKILL.md`（v1.0.0）
