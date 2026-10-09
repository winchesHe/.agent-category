# content-data：多维表格 + 电子表格

合并 lark-cli 的 `lark-base`（多维表格 / Bitable，v1.2）+ `lark-sheets`（电子表格，v3）。

> 鉴权 / 身份处理见 [`lark-shared.md`](./lark-shared.md)。
> Wiki 链接 / token 解析、本地文件导入 → 见 [`content-doc.md`](./content-doc.md)。

## 适用场景

- **多维表格 / Bitable / Base**：建表、字段管理、记录读写、视图、公式 / lookup 字段、跨表计算、临时聚合分析、workflow、dashboard、表单、角色权限
- **电子表格 / Sheets**：创建、读写单元格、追加行、查找、合并 / 拆分单元格、风格、维度（增删插入移动行/列）、筛选视图、下拉列表、浮动图片、导出

## 命中的 lark-cli skill

- `lark-base`（base 命令组，v1.2）
- `lark-sheets`（sheets 命令组，v3）

## 全局规则

1. **资源发现统一走 `drive +search`**（[`content-doc.md`](./content-doc.md)）；多维表格 `--filter '{"doc_types":["BITABLE"]}'`、电子表格 `--filter '{"doc_types":["SHEET"]}'`。
2. **本地文件导入** → 先 `drive +import --type bitable / sheet`（**不要先切到 base / sheets**）；导入完成才进本 reference 做内部操作。
3. **Wiki 链接**：先 `wiki spaces get_node` 解析 → `obj_type=bitable/sheet` 后再切对应命令。
4. **Base 业务命令仅用 `lark-cli base +...` shortcut 形式**——不要改走 `lark-cli api /open-apis/bitable/v1/...`。
5. **执行任何 `base +` 命令前**先看对应命令的 `--help`（lark-cli 强约束）。

---

# Part A：lark-base（多维表格 / Bitable）

## 模块地图

| 大模块 | 处理什么 | 子模块 / 能力 |
|---|---|---|
| Base 模块 | Base 本体 | `+base-create / +base-get / +base-copy` |
| 表与数据 | Base 内部结构 + 日常数据 | `+table-* / +field-* / +record-* / +view-*` |
| 公式 / Lookup | 派生字段、跨表计算 | `+field-create/update`（`type=formula/lookup`） |
| 数据分析 | 临时聚合 | `+data-query` |
| Workflow | 自动化 | `+workflow-list/get/create/update/enable/disable` |
| Dashboard | 仪表盘 | `+dashboard-* / +dashboard-block-*` |
| 表单 | 表单 + 题目 | `+form-* / +form-questions-*` |
| 权限角色 | 高级权限 + 自定义角色 | `+advperm-* / +role-*` |

## Base 模块

| 命令 | 用途 | 说明 |
|---|---|---|
| `drive +search --filter '{"doc_types":["BITABLE"]}'` | 按名称找 Base | 资源发现入口 |
| `+base-create` | 建 Base | 写入；`--folder-token` `--time-zone` 可选 |
| `+base-get` | 取 Base 元信息 | 不替代字段 / 表结构读取 |
| `+base-copy` | 复制 Base | 写入；成功后返回新 Base 标识 |

## Table（数据表）

| 命令 | 用途 |
|---|---|
| `+table-list` / `+table-get` | 列表 / 详情。`+table-list` **只能串行执行** |
| `+table-create` / `+table-update` / `+table-delete` | 增删改。删除明确目标可直接 `--yes` |

## Field（字段）

| 命令 | 用途 | 注意 |
|---|---|---|
| `+field-list` / `+field-get` | 看字段结构。`+field-list` 只能串行；写记录前常先看 | — |
| `+field-create` / `+field-update` / `+field-delete` | 普通字段增删改 | 写字段前看 `lark-base-shortcut-field-properties.md` |
| `+field-search-options` | 查单选 / 多选字段的可选项 | 选项型字段专用 |

字段类型 `formula` / `lookup` 见下文"公式 / Lookup"模块。

## Record（记录）

统计、汇总、全量导出或完整比较需要覆盖目标范围，自动按响应分页至完成，无需用户额外说“翻页”。预览或明确要求前 N 条时才限量，并说明截断。当前 CLI 普通输出单页最多 200 条，NDJSON 最多 2000 条；分析优先 `--format ndjson --output <相对路径>` 配合字段投影和过滤，用本地工具处理数据，避免为节省上下文缩小用户要求的范围。先查 `base +record-list --help`，依实际分页信息核对完整性；请求失败或未取完时只报告部分结果。

| 命令 | 用途 | 关键约束 |
|---|---|---|
| `+record-list` | 分页读记录（默认） | 按目标决定范围；完整性与分页见下文，不以首屏代替全量 |
| `+record-search` | **关键词检索**（用户给了关键词才用） | 默认优先 `+record-list` |
| `+record-get` | 单条详情 | — |
| `+record-upsert` | 写单条（创建或更新） | 写前先 `+field-list`；只写存储字段 |
| `+record-batch-create` / `+record-batch-update` | 批量增 / 改 | 单批 ≤ 200 条；`batch-update` 是**同值更新**（同一 patch 应用到多条） |
| `+record-upload-attachment` | 给已有记录加附件 | 附件**专用链路**——不要用 `+record-upsert` / `+record-batch-*` 伪造附件值 |
| `+record-delete` | 删记录（明确目标可 `--yes`） | — |
| `+record-history-list` | 单条变更历史 | 按 `table-id` + `record-id`，不支持整表扫描；只能串行 |
| `+record-share-link-create` | 单条 / 多条记录分享链接 | 单次 ≤ 100；自动去重 |

**Base 附件下载**：从 `+record-get` 返回的附件字段拿 `file_token`，用 `lark-cli docs +media-download`，**不要用 `lark-cli drive +download`**（对 Base 附件返 403）。

## View（视图）

| 命令 | 用途 |
|---|---|
| `+view-list` / `+view-get` | 列表 / 详情。`+view-list` 只能串行 |
| `+view-create` / `+view-delete` / `+view-rename` | 增删改 |
| `+view-get/set-filter` | 视图筛选条件，常配 `+record-list` |
| `+view-get/set-sort` | 排序——字段名必须来自真实结构 |
| `+view-get/set-group` | 分组——同上 |
| `+view-get/set-visible-fields` | 控制可见字段顺序 |
| `+view-get/set-card` | 卡片视图 |
| `+view-get/set-timebar` | 时间轴视图 |

## 公式 / Lookup

默认优先 `formula`（常规计算、条件、文本、日期差、跨表聚合，长期沉淀的派生指标）；只有用户明确要 `lookup`，或场景天然符合 `from / select / where / aggregate` 的固定查找建模，才用 `lookup`。

| 命令 | 何时 |
|---|---|
| `+field-create --type formula` | 创建公式字段。**先读 `formula-field-guide.md`**（lark-cli reference），不要直接写 |
| `+field-update --type formula` | 更新公式 |
| `+field-create --type lookup` | 创建 lookup 字段。先读 `lookup-field-guide.md` |
| `+field-update --type lookup` | 更新 lookup；跨表时还要拿目标表结构 |

## 数据分析（`+data-query`）

| 命令 | 用途 |
|---|---|
| `+data-query` | 分组、SUM/AVG/COUNT/MAX/MIN、过滤后聚合 |

**前置约束**：
- 调用者必须是目标 Base 的**管理员（FA 权限）**，否则权限错误
- 只支持白名单字段类型作为 `dimensions / measures / filters / sort`：`formula` / `lookup` / 附件 / 系统字段 / 关联字段**不能用**
- 字段名必须**精确匹配**真实字段名
- **不返回原始记录**——要原始数据走 `+record-list`，不要用 `+data-query` 拉一次再手算
- 不要用 `+record-list` / `+record-search` 拉全量再手算聚合——用 `+data-query`

## Workflow

执行任何 workflow 命令前**必须**先读对应文档和 `lark-cli schema`。

| 命令 | 用途 |
|---|---|
| `+workflow-list` / `+workflow-get` | 列表（只摘要，串行） / 完整结构 |
| `+workflow-create` / `+workflow-update` | 增 / 改。**先读 schema**；禁止凭自然语言猜 `type`；先确认真实表名字段名 |
| `+workflow-enable` / `+workflow-disable` | 启 / 停；`workflow_id` 与 `table_id` **按前缀区分** |

## Dashboard

| 命令 | 用途 |
|---|---|
| `+dashboard-list` / `+dashboard-get` | 列表 / 详情 |
| `+dashboard-create / update / delete` | CRUD |
| `+dashboard-block-list / get` | 看图表组件 |
| `+dashboard-block-create / update / delete` | 增删改图表组件；涉及 `data_config` 必读 lark-cli `dashboard-block-data-config.md` |

## 表单

| 命令 | 用途 |
|---|---|
| `+form-list / get` | 列表（可拿 `form-id`）/ 详情 |
| `+form-create / update / delete` | CRUD |
| `+form-questions-list` | 列题目（依赖 `form-id`） |
| `+form-questions-create / update / delete` | 增删改题目 |

## 权限与角色

涉及 `+advperm-* / +role-*` 时操作用户必须是 Base **管理员**。

| 命令 | 用途 |
|---|---|
| `+advperm-enable / disable` | 启 / 停高级权限。**停用是高风险**（已有自定义角色失效） |
| `+role-list / get` | 列表（串行）/ 详情。详细配置见 `role-config.md` |
| `+role-create / update / delete` | CRUD 自定义角色 |

---

# Part B：lark-sheets（电子表格）

## 单元格数据类型（关键！）

二维数组写入（`+write/+append/+create --values/--data`）的每个单元格值：

| 类型 | 写入格式 | 示例 |
|---|---|---|
| 字符串 | `"文本"` | `"hello"` |
| 数字 | 数字 | `123` / `3.14` |
| 日期 | 数字（自 1899-12-30 起天数；先设单元格日期格式） | `42101` |
| 链接（纯 URL） | `"URL"` | `"https://x.com"` |
| 链接（带文本） | `{"type":"url","text":"…","link":"…"}` | — |
| 邮箱 | `"x@y.com"` | — |
| **公式** | `{"type":"formula","text":"=…"}` | `{"type":"formula","text":"=SUM(A1:A10)"}` |
| @人 | `{"type":"mention","text":"标识","textType":"email/openId/unionId","notify":false}` | `notify` 默认 false，仅用户明确要求才 true |
| @文档 | `{"type":"mention","textType":"fileToken","text":"token","objType":"sheet/docx/..."}` | — |
| 下拉列表 | `{"type":"multipleValue","values":[…]}` | 必须**先配置下拉选项** |

⚠️ **公式 / @人 / @文档 / 下拉必须用对象格式**——直接传字符串会被当纯文本存。

**限制**：
- 公式支持 IMPORTRANGE 跨表（最多 5 层嵌套，每工作表 ≤ 100 引用）
- @人仅同租户用户，单次 ≤ 50 人
- 下拉列表先 `+set-dropdown` 配置选项，否则 `multipleValue` 写入变纯文本；值字符串**不能含逗号**

## Shortcut 速查表

### 基础读写

| Shortcut | 用途 |
|---|---|
| `+create` | 建电子表格（可同时写表头 + 初始数据） |
| `+info` | 看电子表格 + sheet 元信息 |
| `+read` | 读单元格值 |
| `+write` | 写单元格（覆盖模式） |
| `+write-image` | 把图片写入单元格 |
| `+append` | 追加行 |
| `+find` | 查找单元格 |
| `+replace` | 查找替换 |
| `+export` | 导出电子表格（异步轮询 + 可选下载） |

### 单元格 / 维度 / 样式

| Shortcut | 用途 |
|---|---|
| `+merge-cells` / `+unmerge-cells` | 合并 / 拆分 |
| `+set-style` / `+batch-set-style` | 单 / 多区域样式 |
| `+add-dimension` / `+insert-dimension` | 末尾加 / 指定位置插入行/列 |
| `+update-dimension` | 改行/列属性（可见、尺寸） |
| `+move-dimension` / `+delete-dimension` | 移动 / 删除行/列 |

### 筛选视图

| Shortcut | 用途 |
|---|---|
| `+create-filter-view / +update-filter-view / +delete-filter-view` | CRUD 筛选视图 |
| `+list-filter-views / +get-filter-view` | 列表 / 详情 |
| `+create/update/list/get/delete-filter-view-condition` | 筛选条件 CRUD |

### 下拉列表

| Shortcut | 用途 |
|---|---|
| `+set-dropdown` | 设置下拉（`multipleValue` 写入的**前置**） |
| `+update-dropdown / +get-dropdown / +delete-dropdown` | 改 / 查 / 删 |

### 浮动图片

| Shortcut | 用途 |
|---|---|
| `+media-upload` | 上传本地图片→`file_token`（>20MB 自动分片） |
| `+create-float-image / +update-float-image / +delete-float-image` | CRUD |
| `+get-float-image / +list-float-images` | 详情 / 列表 |

> 浮动图片读接口只返**元数据**（含 `float_image_token`）。要图片字节，用 `lark-cli docs +media-preview --token "<float_image_token>" --output ./image.png`。

## 工作表筛选（spreadsheet.sheet.filters）

工作表级筛选（不是 filter view）的操作流程：

1. **create**：首次创建。`range` 必须**覆盖所有**要筛选的列（如 `B1:E200`）；已有筛选会被覆盖
2. **update**：在已有筛选上加 / 改某列条件——只指定 `col` + `condition`，**不需要 range**
3. **delete** / **get**：删除 / 查询

```bash
# 多列筛选（B 列 + E 列）
# 1. 删旧
lark-cli sheets spreadsheet.sheet.filters delete \
  --params '{"spreadsheet_token":"<t>","sheet_id":"<id>"}'
# 2. 创建（range 覆盖 B-E）
lark-cli sheets spreadsheet.sheet.filters create \
  --params '{"spreadsheet_token":"<t>","sheet_id":"<id>"}' \
  --data '{"col":"B","condition":{"expected":["xx"],"filter_type":"multiValue"},"range":"<id>!B1:E200"}'
# 3. 加第二个条件
lark-cli sheets spreadsheet.sheet.filters update \
  --params '{"spreadsheet_token":"<t>","sheet_id":"<id>"}' \
  --data '{"col":"E","condition":{"expected":["xx"],"filter_type":"multiValue"}}'
```

**常见错误**：
- `Wrong Filter Value` → 筛选已存在，先 delete 再 create
- `Excess Limit` → update 时重复加同列条件

---

## 典型示例（综合）

```bash
# A. 找一个 Base
lark-cli drive +search --query "项目跟踪" --filter '{"doc_types":["BITABLE"]}' --as user

# B. 看 Base 表结构
lark-cli base +table-list --url "<base_url>"

# C. 写一条记录（先看字段定义）
lark-cli base +field-list --url "<base_url>" --table-id <tbl_id>
lark-cli base +record-upsert --url "<base_url>" --table-id <tbl_id> \
  --fields '{"标题":"修复登录","负责人":"ou_xxx","状态":"进行中"}'

# D. 批量更新 50 条记录到同一状态
lark-cli base +record-batch-update --url "<base_url>" --table-id <tbl_id> \
  --record-ids <r1>,<r2>,... --fields '{"状态":"已完成"}'

# E. 数据分析：按负责人统计
lark-cli base +data-query --url "<base_url>" --table-id <tbl_id> \
  --dimensions '["负责人"]' --measures '[{"field":"工时","aggregate":"sum"}]'

# F. 创建电子表格 + 表头 + 初始数据
lark-cli sheets +create --title "周报" --header '["项目","进度","负责人"]' \
  --data '[["A","30%","张三"],["B","60%","李四"]]'

# G. 写公式
lark-cli sheets +write --url "<sheet_url>" --sheet-id <id> --range "C6" \
  --values '[[{"type":"formula","text":"=SUM(C2:C5)"}]]'

# H. 在 sheet 里查找单元格
lark-cli sheets +find --url "<sheet_url>" --sheet-id <id> --query "未完成"

# I. 配下拉再写下拉值
lark-cli sheets +set-dropdown --url "<sheet_url>" --sheet-id <id> --range "B2:B100" \
  --options '["待办","进行中","已完成"]'
lark-cli sheets +write --url "<sheet_url>" --sheet-id <id> --range "B2" \
  --values '[[{"type":"multipleValue","values":["进行中"]}]]'
```

## NEVER 规则（领域特有）

### Base

- ❌ **不要 `lark-cli api /open-apis/bitable/v1/...`** ——Base 业务一律 `lark-cli base +...`。
- ❌ **附件不要走 `+record-upsert` / `+record-batch-*`**——专用 `+record-upload-attachment`。
- ❌ **Base 附件下载不要用 `drive +download`**——会 403；必须 `docs +media-download` + 从 `+record-get` 拿 `file_token`。
- ❌ **`+data-query` 不返原始记录**——要原始数据用 `+record-list`，不要用聚合命令绕。
- ❌ **不要用 `+record-list/search` 拉全量再手算聚合**——用 `+data-query`。
- ❌ **`+data-query` 不能用 `formula`/`lookup`/附件/系统字段/关联字段**作为 dim/measure/filter/sort——会失败。
- ❌ **写记录 / 字段前不先 `+field-list`**——会写到错的字段或类型。
- ❌ **`workflow create/update` 不读 schema 直接猜**——禁止凭自然语言推 `type`。
- ❌ **`advperm-disable` 是高风险**——会让已有自定义角色失效，确认后再做。

### Sheets

- ❌ **公式 / @人 / @文档 / 下拉值不要传字符串**——必须对象格式，否则被当纯文本。
- ❌ **下拉 `multipleValue` 写入前不先 `+set-dropdown`**——会失败或被当纯文本。
- ❌ **筛选已存在不要直接 `create`**——会覆盖整个筛选，先 `delete`；增量改条件用 `update`。
- ❌ **浮动图片读接口当图片下载接口用**——只有元数据；用 `docs +media-preview` 下字节。
- ❌ **下拉值字符串不要含逗号**——会被解析错误。
- ❌ **@人不要跨租户**——只同租户，单次 ≤ 50。

## 不在本 reference 范围

- 资源发现（按名称找 Base / Sheet）→ [`content-doc.md`](./content-doc.md) 的 `drive +search`
- 本地文件导入为 Base / Sheet → [`content-doc.md`](./content-doc.md) 的 `drive +import`
- Wiki 链接解析 → [`content-doc.md`](./content-doc.md)
- Base / Sheet 文件级权限、评论 → [`content-doc.md`](./content-doc.md)（drive 命令组）
- Base 事件订阅 → [`event-stream.md`](./event-stream.md)

## 溯源

- lark-cli `skills/lark-base/SKILL.md`（v1.2.0）
- lark-cli `skills/lark-sheets/SKILL.md`（v1.1.0，sheets v3）
