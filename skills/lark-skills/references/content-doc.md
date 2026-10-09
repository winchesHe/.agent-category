# content-doc：云文档 + 云空间 + 知识库

合并 lark-cli 的 `lark-doc`（v2）+ `lark-drive` + `lark-wiki` 三个 skill。三者关联紧密：drive 是文件容器和资源发现入口、doc 是文档内容编辑器、wiki 是知识库节点层（包装文档/表格/Base 等）。

> 鉴权 / Permission denied 处理见 [`lark-shared.md`](./lark-shared.md)。

## 适用场景

- 创建 / 读取 / 编辑飞书云文档（DocxXML 协议或 Markdown 整段写入）
- 局部读取大文档（按目录、block id 区间、关键词、章节）
- 文档内插图 / 文件 / 媒体上传 / 下载
- 评论：全文评论、局部评论（划词评论）、回复、reaction 表情、统计
- 文档权限管理（含给当前 bot 自身授权）
- 云空间文件 / 文件夹的 CRUD：上传、下载、移动、复制、删除、改标题
- 资源发现：按名称 / 关键词 / 时间 / 创建者搜索文档、Wiki、电子表格、Base
- 把本地 `.md` / `.docx` / `.xlsx` / `.csv` / `.base` 导入为飞书在线文档 / 表格 / Base
- 知识库（Wiki）空间、节点、成员管理

## 命中的 lark-cli skill

- `lark-doc`（docs 命令组，v2 API）
- `lark-drive`（drive 命令组，资源发现 + 文件操作 + 评论 + 权限 + 导入导出）
- `lark-wiki`（wiki 命令组，空间 + 节点 + 成员）

## ⚠️ API 版本与全局规则

- **执行前以当前 CLI 的 `--help` 为准**；下文 docs 示例按 1.0.91 编写，不传已移除的版本 flag。命令表用于选操作，参数与响应结构查当前帮助。
- **资源发现统一走 `drive +search`**（按名称 / 关键词 / 时间 / 创建者过滤）；`docs +search` 已 deprecated 进入维护期，**不要在新流程里依赖**。
- **本地文件导入飞书在线文档**优先使用 `drive +import`，**不要**先切到 `lark-base` / `lark-sheets`：那些只负责"导入完成后"的内部操作。
  - `.md` / `.docx` / `.doc` / `.txt` / `.html` → `drive +import --type docx`
  - `.xlsx` / `.xls` / `.csv` → `drive +import --type sheet`
  - `.xlsx` / `.csv` / `.base` 想导成 Base → `drive +import --type bitable`

## 文档类型与 Token（关键！）

不同类型云对象的 URL / token 处理方式不同：

| URL 格式 | 示例 | Token 类型 | 处理方式 |
|---|---|---|---|
| `/docx/` | `.../docx/doxcnxxx` | `file_token` | URL 中 token 直接用 |
| `/doc/`（旧版） | `.../doc/doccnxxx` | `file_token` | URL 中 token 直接用 |
| `/sheets/` | `.../sheets/shtcnxxx` | `file_token` | URL 中 token 直接用 |
| `/wiki/` | `.../wiki/wikcnxxx` | `wiki_token` | ⚠️ **不能直接用**，需先解析 |
| `/drive/folder/` | `.../drive/folder/fldcnxxx` | `folder_token` | URL 中 token 即文件夹 token |

### Wiki 链接解析（必读）

`/wiki/<token>` 背后可能是 docx、sheet、bitable、slides 等任意类型，**不要假设 token 就是 file_token**。

```bash
lark-cli wiki spaces get_node --params '{"token":"<wiki_token>"}'
```

返回中提取：
- `node.obj_type`：实际类型（`docx` / `doc` / `sheet` / `bitable` / `slides` / `file` / `mindnote`）
- `node.obj_token`：**真实文档 token**，后续操作都用它
- `node.title`：标题

按 obj_type 切到对应 reference：

| obj_type | 后续路由 |
|---|---|
| `docx` / `doc` | 本 reference（doc 命令组） |
| `sheet` | [`content-data.md`](./content-data.md) |
| `bitable` | [`content-data.md`](./content-data.md) |
| `slides` | [`content-visual.md`](./content-visual.md) |
| `file` / `mindnote` | 本 reference（drive 命令组） |

### 文档内嵌资源标签 → 必须下钻

在 `docs +fetch` 返回内容里看到这些标签，**不能只呈现标签**，必须提取 token 切到对应 skill：

| 标签 | 提取 | 切到 |
|---|---|---|
| `<sheet token="..." sheet-id="...">` | spreadsheet_token + sheet-id | [`content-data.md`](./content-data.md) |
| `<bitable token="..." table-id="...">` | app_token + table-id | [`content-data.md`](./content-data.md) |
| `<cite type="doc" file-type="sheets" ...>` | 同上 | [`content-data.md`](./content-data.md) |
| `<cite type="doc" file-type="bitable" ...>` | 同上 | [`content-data.md`](./content-data.md) |
| `<synced_reference src-token="..." src-block-id="...">` | doc_token + block_id | 用 `docs +fetch` 读取 src |

## Shortcut 速查表

### docs（云文档内容）

| Shortcut | 用途 | 必填 | 关键 flag |
|---|---|---|---|
| `+create` | 创建文档（XML / Markdown） | `--content` | `--doc-format xml/markdown` `--parent-token` / `--parent-position` |
| `+fetch` | 读取文档内容 | `--doc <URL或token>` | `--scope full/outline/range/keyword/section` `--detail simple/with-ids/full` |
| `+update` | 更新文档（八种指令） | `--doc` `--command`；其余按指令查帮助 | `command ∈ str_replace / block_insert_after / block_copy_insert_after / block_replace / block_delete / block_move_after / overwrite / append` |
| `+media-insert` | 插入本地图片 / 文件到文档末尾（4 步编排 + 自动回滚） | `--doc` | `--from-clipboard`（剪贴板优先）/ `--file <path>` |
| `+media-download` | 下载文档媒体 / 白板缩略图 | `--doc` `--block-id` 或 `--media-id` | `--type whiteboard` 仅适用于白板缩略图 |
| `+media-preview` | 预览文档里的图片 / 附件（不下载） | 同上 | — |

### drive（云空间文件 / 资源发现 / 评论 / 权限 / 导入导出）

| Shortcut | 用途 | 关键 flag |
|---|---|---|
| `+search` | **资源发现统一入口**：搜文档 / Wiki / sheet / Base / 文件 | `--query` `--mine` `--edited-since` `--doc-types docx,sheet,bitable` `--owner` |
| `+upload` | 上传本地文件到 Drive 文件夹 / Wiki 节点 | `--file` `--folder-token` 或 `--wiki-token` |
| `+create-folder` | 创建文件夹（可指定父文件夹） | `--name` `--parent-folder-token` |
| `+download` | 下载 Drive 文件 | `--file-token` `--output` |
| `+create-shortcut` | 在另一文件夹创建已有文件的快捷方式 | `--source-token` `--target-folder` |
| `+add-comment` | 添加文档评论（全文 / 局部） | `--doc` `--content` `--block-id`（局部） `--full-comment` |
| `+export` / `+export-download` | 把 docx/sheet/bitable 导出本地（轮询） | `--token` `--type pdf/docx/xlsx/csv` |
| `+import` | 把本地文件导入为 docx / sheet / bitable | `--file` `--type docx/sheet/bitable` `--folder-token` |
| `+move` / `+delete` | 移动 / 删除文件或文件夹（删除是高风险写） | `--token` `--target-folder` / `--yes` |
| `+task_result` | 轮询异步任务结果（导入 / 导出 / 移动 / 删除） | `--task-id` |
| `+apply-permission` | 申请文档查看 / 编辑权限（user-only，每文档每天 5 次） | `--doc` `--perm view/edit` |

### wiki（知识库）

| Shortcut | 用途 | 关键 flag |
|---|---|---|
| `+node-create` | 创建知识库节点（自动解析 space） | `--space-id` `--parent-node-token` `--title` `--obj-type` |
| `+move` | 移动 wiki 节点；或把 Drive 文档移入 Wiki | `--node-token` `--target-parent` |
| `+delete-space` | 删除知识空间（高风险，必须 `--yes`） | `--space-id` |

## 文档读写决策

### 读

- 读全文 → `docs +fetch --doc <URL> --scope full`
- 看大纲（标题 + block id 树）→ `--scope outline`
- 拉某段 block id 区间 → `--scope range --start-block-id ... --end-block-id ...`
- 按关键词找上下文 → `--scope keyword --keyword "..."`
- 按章节标题自动成节 → `--scope section --start-block-id <标题block_id>`（先从 outline 定位标题）
- `--detail simple/with-ids/full` 控制 block 详细度（`with-ids` 是局部精修必须的）

> 大文档慎用 `scope=full`，优先 outline → 定位 block_id → range/keyword/section 拉局部，省 context。

### 创建文档（默认 Wiki）

一般“创建飞书文档”默认创建 **Wiki 节点承载的 docx**，交付 Wiki 链接。用户明确指定 Drive 文件夹、云空间或独立 docx 时遵从指定；编辑已有文档时保持原位置。

1. 先读 [`content-doc-rich-text.md`](./content-doc-rich-text.md)，按默认丰富文本展示规则准备正文。
2. 优先使用用户指定或当前任务已确定的知识空间 / 父节点。给了 Wiki URL 时，先解析 `space_id` 与节点 token；不要把 docx 的 `obj_token` 当父节点 token。位置有歧义时先检索，仍无法确定再询问。
3. 未指定位置且使用 user 身份时，默认个人知识库 `my_library`；bot 身份不套用个人库默认值，需要可用的目标空间或父节点。
4. `wiki +node-create --title "标题" --obj-type docx --space-id my_library --as user` 创建节点；指定父节点时用真实 `--parent-node-token`，需要时同时传对应 `--space-id`，替换个人库目标。
5. 从创建响应取得节点 token、`obj_type` 和 `obj_token`；响应不足时用 `wiki spaces get_node` 回查。向解析出的 docx 写入正文，不再调用 `docs +create` 另建一份。创建已成功而正文写入失败时，保留并复用该节点继续处理，避免重复创建。
6. 回读确认节点归属、节点标题与正文标题一致，内容和样式按丰富文本 reference 验证。返回实际 Wiki 链接，不编造租户域名。

### 写

- **创建 / 整段写入**：默认按 [`content-doc-rich-text.md`](./content-doc-rich-text.md) 使用 XML 丰富文本展示。用户给 `.md` 文件或明确要求导入 Markdown / 纯文本时遵从原要求。
- **精准编辑**：优先 XML，按当前 `docs +update --help` 选择 `str_replace` 或 `block_*`；涉及样式时加载丰富文本 reference，不为局部文字修改重排全文。
- **整篇覆盖**：只在确需替换全文时使用 `overwrite`；XML 以 `<title>文档标题</title>` 开头，避免正文标题变成 Untitled（Wiki 节点标题不会随之自动修复）。

编辑前必读 `lark-cli docs +update --help`；XML / Markdown 协议通过帮助中列出的 `lark-cli skills read` 入口按需查询。

## 评论

### 模式

- **全文评论**：未传 `--block-id` 时默认；支持 `docx`、旧版 `doc` URL、解析为 doc/docx 的 wiki URL。
- **局部评论（划词评论）**：传 `--block-id` 时启用；仅 `docx`，以及解析为 docx 的 wiki URL。block id 用 `docs +fetch --detail with-ids` 拿。
- **slides 评论**：必须显式传 `--block-id <slide-block-type>!<xml-id>`，CLI 自动拆分；不支持 `--selection-with-ellipsis` 与 `--full-comment`。

### 内容转义

- 评论文本**不能直接含 `<` / `>`**，必须转义：`<` → `&lt;`，`>` → `&gt;`。
- `drive +add-comment` 的 `--content` 接 `reply_elements` JSON 数组：`'[{"type":"text","text":"正文"}]'`。
- `drive +add-comment` 对 `type=text` 自动转义；底层 `drive file.comments create_v2` / `replys create` / `replys update` 需自行转义。

### 列表 / 统计口径（关键！）

- 用户要求“所有评论”或统计全部评论时，分别查询 `is_solved:false` 与 `is_solved:true`，各自翻完分页并按 comment_id 去重合并；当前接口省略该参数默认 false，不能靠省略取得全部。只看待处理反馈时查询 false；未限定状态的普通评论查询也默认包含两类。预览可限量，但必须说明状态范围与截断情况。
- 返回的 `items` 是**评论卡片**列表（一张卡片 = UI 上的一条评论）。
- 第一条 reply 在用户视角下是这张卡片的"评论本身"。
- 统计：
  - 评论数 / 卡片数 = `items` 长度（全量分页累加）
  - 回复数 = `Σ item.reply_list.replies` − `len(items)`
  - 总互动数 = `Σ item.reply_list.replies`
- `item.has_more=true` 时需 `drive file.comment.replys list` 拉全后再统计。

### 评论排序与回复限制

- 排序：仅当用户提"最新 / 最后 / 最早评论"时按 `create_time` 排（**必须先拉全分页再排**）；说"第一条评论"直接用 list 返回的第一条。
- 全文评论（`is_whole=true`）**不能回复**——遇到时只提示，不要替用户找其它可回复的评论。
- 已解决评论（`is_solved=true`）**不能回复**——同上。

## 知识库（Wiki）要点

### 用户给 wiki URL 但要查/管成员

```bash
# 1. 解析 space_id
lark-cli wiki spaces get_node --params '{"token":"<wiki_token>"}'
# → data.node.space_id
# 2. 用 space_id 调成员接口
```

### 删除知识空间

只给名称或 URL **不能直接传给 `--space-id`**，必须先解析：

- URL：`wiki spaces get_node` 拿 `space_id`。
- 仅名称：`wiki spaces list` 翻页 + 精确匹配 `name`；首次精确命中即停页。全部翻完仍无精确则用宽松匹配（trim、大小写不敏感、子串包含）。
- **无论命中 1 条还是多条，发起删除前都必须把候选（name + space_id + description + space_type）列给用户，由用户明确选定**——不要因为"只命中一条"就自动删。
- 命中 0 条 → 问用户是名字拼错还是无权限，**不要**自行改名重试。
- 用户选定后：`lark-cli wiki +delete-space --space-id <ID> --yes`（高风险写，必须 `--yes`）。

### 添加成员（先解析 ID 再调用）

| 目标类型 | `member_type` | ID 解析方式 |
|---|---|---|
| 用户 | `openid` | `lark-cli contact +search-user --query "<姓名/邮箱>"` 拿 open_id |
| 群 | `openchat` | `lark-cli im +chat-search --query "<群名>"` 拿 chat_id |
| 部门 | `opendepartmentid` | `lark-cli api POST /open-apis/contact/v3/departments/search --as user --params '{"department_id_type":"open_department_id"}' --data '{"query":"<部门名>"}'` |

> ⚠️ **`--as bot` 不能用 `opendepartmentid` 加成员**（官方限制）。遇到"部门 + bot"必须停下提示，要求 `--as user` 或明确告知不可行。

### 语义识别：个人知识库 vs Drive 根目录

- "我的文档库" / "My Document Library" / "我的知识库" / "个人知识库" / `my_library` → **Wiki personal library**（不是 Drive 根目录）。先解析 `my_library` 对应 space_id，再走 `wiki +move` / `wiki +node-create`。
- 用户明确说"Drive 文件夹 / 云空间根目录 / 我的空间" → 才进 drive 域。

## 给当前应用（bot）授权访问文档

```bash
# 1. 取 bot 自己的 open_id
lark-cli api GET /open-apis/bot/v3/info --as bot
# → bot.open_id

# 2. 授权
lark-cli drive permission.members create \
  --params '{"token":"<doc_token>","type":"<resource_type>"}' \
  --data '{"member_type":"openid","member_id":"<bot_open_id>","perm":"view","type":"user"}'
```

`<resource_type>` ∈ `doc / docx / sheet / bitable / file / folder / wiki / slides`。

## 典型示例

```bash
# A. 资源发现：找最近自己编辑过的文档
lark-cli drive +search --query "周报" --mine --edited-since 7d --doc-types docx,sheet --as user

# B. 默认在个人知识库创建 Wiki 文档，再写入丰富文本
lark-cli wiki +node-create --space-id my_library \
  --title "2026 Q2 计划" --obj-type docx --as user
# 从创建响应取得真实 obj_token；必要时用 get_node 回查
lark-cli docs +update --doc "<obj_token>" --command overwrite --doc-format xml \
  --content '<title>2026 Q2 计划</title><h1>季度目标</h1><callout emoji="🎯" background-color="light-blue" border-color="blue"><p><b>优先完成核心交付。</b></p></callout><p>具体安排见后续章节。</p>' \
  --as user
# 指定知识库父节点时，以 --parent-node-token <真实节点token> 替换个人库目标；
# 用户明确要 Drive 文档时，才使用 docs +create --parent-token <真实文件夹token>。

# C. 读取大文档的章节
lark-cli docs +fetch --doc "https://xxx.feishu.cn/docx/doxcnXXX" \
  --scope section --start-block-id "<标题block_id>" --detail with-ids

# D. 局部精修：在某 block 后插一段
lark-cli docs +update --doc "<doc_url>" \
  --command block_insert_after --block-id "<真实block_id>" \
  --content '<p>新增段落</p>'

# E. 批量字符串替换
lark-cli docs +update --doc "<doc_url>" \
  --command str_replace --pattern "旧" --content "新"

# F. 在文档末尾插剪贴板里的截图
lark-cli docs +media-insert --doc "<doc_url>" --from-clipboard

# G. 把本地 Markdown 导入为 docx
lark-cli drive +import --file ./report.md --type docx --folder-token fldcnxxx

# H. 给文档加全文评论
lark-cli drive +add-comment --doc "<doc_url>" \
  --content '[{"type":"text","text":"请 review 第二节"}]'

# I. 解析 wiki 节点
lark-cli wiki spaces get_node --params '{"token":"wikcnxxx"}'

# J. 给知识库加用户成员
lark-cli contact +search-user --query "李四" --as user      # 拿 open_id
lark-cli wiki members create --params '{"space_id":"<id>"}' \
  --data '{"member_type":"openid","member_id":"ou_xxx","member_role":"member"}'
```

## NEVER 规则（领域特有）

- ❌ **不要把 wiki URL 的 token 当 file_token 用**。先 `wiki spaces get_node` 解析出 `obj_type` + `obj_token`。
  **Why**：wiki token ≠ file_token，会报 `not exist`。
  **如何应用**：见上文 "Wiki 链接解析"。

- ❌ **不要让 `--as bot` 给 wiki 加部门成员**（官方限制）。
  **Why**：tenant_access_token 不允许 `opendepartmentid` 加成员。
  **如何应用**：识别"部门 + bot"组合后，停下提示用户 `--as user`，不要先调用试错。

- ❌ **不要在新流程里用 `docs +search`**——已 deprecated。
  **Why**：会下线。
  **如何应用**：资源发现一律走 `drive +search`，flat flag 友好（`--mine`、`--edited-since` 等）。

- ❌ **不要用 Markdown 做精准编辑**。
  **Why**：Markdown 在 `str_replace`/`block_*` 指令下表达 block 结构不稳定。
  **如何应用**：精修一律 `--doc-format xml`（默认）。

- ❌ **删除 wiki space 不可"自动选最匹配项"**。
  **Why**：误删不可逆。
  **如何应用**：必须列候选给用户选定后再 `--yes` 执行。

- 评论查询范围与分页完成条件统一见上文“列表 / 统计口径”，不要把预览结果当全量统计。

- ❌ **评论文本不要漏转义 `<` `>`**——底层 API（`drive file.comments create_v2` 等）不会自动兜底。
  **Why**：会破坏 XML 解析。

- ❌ **本地文件导入 Base / Sheets，不要先切到 `lark-base` / `lark-sheets`**。
  **Why**：`lark-base` / `lark-sheets` 只做导入完成后的内部操作。
  **如何应用**：第一步统一 `drive +import --type bitable/sheet/docx`。

## 不在本 reference 范围

- 文档丰富文本展示、样式语法与落库验证 → [`content-doc-rich-text.md`](./content-doc-rich-text.md)（创建文档或调整排版时读取）

- 多维表格 / 电子表格内部操作（字段、记录、视图、公式）→ [`content-data.md`](./content-data.md)
- 幻灯片 / 白板内部操作 → [`content-visual.md`](./content-visual.md)
- 评论变更事件订阅 → [`event-stream.md`](./event-stream.md)（drive 只提供事件订阅入口，但订阅协议本身在那里）
- 部门树遍历 / 组织架构 → [`openapi-explorer.md`](./openapi-explorer.md)

## 溯源

- lark-cli `skills/lark-doc/SKILL.md`（v2.0.0）
- lark-cli `skills/lark-drive/SKILL.md`（v1.0.0）
- lark-cli `skills/lark-wiki/SKILL.md`（v1.0.0）
