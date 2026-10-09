# Block Kit 使用参考

需要结构化布局或原生格式时加载；普通回复优先 [Markdown 默认路径](message-formatting.md)。
本文件按官方文档和截至 2026-09-09 已获授权的测试整理。所有示例内容与数值均为虚构，
仅提供结构，不代表执行成功、真实指标或新的发送授权。

## 什么时候用

| 用户意图 | 选择 | 不要做 |
|---|---|---|
| 一两段回复、摘要、链接、代码 | 默认 Markdown，无 blocks-file | 为普通短句堆砌 blocks |
| 状态通知、少量字段、来源脚注 | header + section/fields + context | 把所有信息塞进一块长文 |
| 单个对象的图片与摘要 | card | 用卡片承载大段报告 |
| 多个候选对象逐个浏览 | carousel 内放 card | 把互不相关的长段落硬拆卡片 |
| 先给结论，证据可展开 | section + container | 只给折叠证据而没有摘要 |
| 趋势或构成 | data_visualization | 没有口径、单位或来源就造图 |
| 多行明细、分页浏览 | data_table | 用空格排表格 |
| 已实际执行的步骤与状态 | plan，或单独 task_card | 把展示面板当执行器或后台任务 |
| 原生 mention、严格字面文本 | rich_text 的 user/usergroup 或无样式 text | 把 literal 当作阻断所有通知 |

轮播、折叠、表格翻页属于客户端原生交互，不需要业务回调。
提交表单、审批、重试、点赞等按钮需要已部署并验证的 handler；本 skill 不提供回调服务，
不能仅凭支持 actions 就造出无响应控件。即使只是 URL button，也不要假设免除交互回执要求；
普通导航优先正文链接。

## 语法模型

- **block**：消息布局单元，例如 section、context、card、plan。
- **element**：放在某个 block 允许位置的组件，例如 image、button；不能任意作为顶层 block。
- **text object**：`{"type":"plain_text","text":"摘要"}` 或 `{"type":"mrkdwn","text":"*摘要*"}`。
  它不是完整 block。各字段只接受规定类型，例如 header.text 必须 plain_text。
- **markdown block**：`{"type":"markdown","text":"**摘要**"}` 是完整 block，不是 mrkdwn text object。
  由 Slack 转换，可能返回多个 blocks；不要对它添加 verbatim。
- **rich_text block**：elements 里再放 rich_text_section/list/quote/preformatted，
  其中 text/link/user 等元素使用结构化字段，不解析星号。

按展示目的与组件 schema 选择：

| 场景 | 文本类型与写法 |
|---|---|
| 普通回复或现有标准 Markdown 内容 | 默认 `markdown_text`；组合布局中可用独立 `markdown` block |
| 结构化正文、列表、精确样式或原生 mention | 优先独立 `rich_text` block；列表用 `rich_text_list`，加粗用 `style.bold`，链接用 `link`，表情用 `emoji`，mention 用 `user/usergroup/channel` |
| Footer、来源与统计的小字样式 | `context` 中使用 `mrkdwn` 文本对象表达链接、表情和行内代码；纯文本用 `plain_text` |
| `section.text` / `section.fields` 等支持格式化文本对象的字段 | 可用 `mrkdwn`；按该字段 schema 核对，不能嵌入完整的 `rich_text` / `markdown` block |
| 按钮标签、header 等只接受纯文本的字段 | `plain_text`，不塞格式标记 |

`mrkdwn` 使用 `*粗体*`、`<URL|标签>`、`:emoji:` 和反引号；标准 Markdown 使用 `**粗体**`、`[标签](URL)`。`rich_text` 的 text 元素不解析这些标记，需用对应原生元素和样式；切换格式不能只替换外层 type。普通文字按所属语法转义，真实 URL 保持不变。

mrkdwn 的 `verbatim` 原样保留；需要关闭 Slack 自动解析名称时可设为 `true`，手写链接、格式和 `<@ID>` 等控制串仍生效。CLI 的 `mention-mode=resolve` 仍会按缓存解析名称；`literal` 只保留名称原文，不绕过广播与用户组门禁。

`--blocks-file` 文件本身是非空数组，不是 `{"blocks":[...]}` API envelope。
所有顶层项必须有 type。复制官方 envelope 时只取 blocks 数组，JSON 不支持注释、尾逗号或省略号。
每个下面的 JSON 都可独立作为文件，也可取其中的 block 合并到同一数组；不要拼成数组套数组。
嵌套字段名由 schema 决定：carousel.elements、container.child_blocks、plan.tasks 不能互换。

顶层 `--text/--text-file` 必填，写独立可读的通知/无障碍摘要，包含关键结论和必要来源链接。
它不经标准 Markdown 渲染，使用简单文本或原生 mrkdwn；不要仅写“见卡片”。
有 blocks-file 时自动发送 blocks + text，不与 markdown_text 同时提交。
fallback、blocks 内容、actor 和目标都进入 preview digest。

```bash
python3 "$SKILL_DIR/scripts/slack.py" send --channel '<channel_id>' \
  --text-file /tmp/slack-fallback.txt --blocks-file /tmp/slack-blocks.json --dry-run

python3 "$SKILL_DIR/scripts/slack.py" edit --url '<permalink>' \
  --text-file /tmp/slack-fallback.txt --blocks-file /tmp/slack-blocks.json --dry-run
```

正式写入仍需具体授权，edit 还需 get、diff、原作者比对和最终确认。

## 基础状态通知

```json
[
  {"type":"header","text":{"type":"plain_text","text":"演示状态"}},
  {"type":"rich_text","elements":[{"type":"rich_text_section","elements":[
    {"type":"text","text":"摘要","style":{"bold":true}},
    {"type":"text","text":"：示例检查完成。"}
  ]}]},
  {"type":"section","fields":[
    {"type":"plain_text","text":"环境：演示环境"},
    {"type":"plain_text","text":"结果：虚构数据"}
  ]},
  {"type":"divider"},
  {"type":"context","elements":[
    {"type":"plain_text","text":"示例来源，不对应真实执行"}
  ]}
]
```

### Footer 与来源链接

正文搭配小字 Footer，编号自身可点击；通知/无障碍 fallback 另保留必要 URL。

```json
[
  {"type":"rich_text","elements":[{"type":"rich_text_section","elements":[
    {"type":"text","text":"示例处理完成，详情见 Footer。"}
  ]}]},
  {"type":"context","elements":[
    {"type":"mrkdwn","text":":stopwatch: 2分10秒 · `feature/example` · <https://github.com/example/app/pull/123|PR #123>","verbatim":true}
  ]}
]
```

### 原生列表

以下是完整 blocks 文件；每个列表项由一个 section 组成，自动保留换行缩进：

```json
[
  {"type":"rich_text","elements":[
    {"type":"rich_text_list","style":"bullet","elements":[
      {"type":"rich_text_section","elements":[
        {"type":"text","text":"主要变化","style":{"bold":true}},
        {"type":"text","text":"：说明修复后的行为。"},
        {"type":"link","url":"https://example.com/report","text":"查看报告"}
      ]}
    ]}
  ]}
]
```

需要 mention 时在列表项的 elements 中加入 `{"type":"user","user_id":"U…"}` 或 `{"type":"usergroup","usergroup_id":"S…"}`，先解析真实 ID，用户组仍需 `--allow-usergroup-mention`。

### 中文标点与加粗边界

中文标点紧贴 `mrkdwn` 加粗标记时，例如 `*Approve*；` 或 `：*Approve*`，
使用独立 `rich_text` block：加粗内容放入 `style.bold = true` 的 text 元素，
标点放入相邻的普通 text 元素，保留原标点与间距。以下示例可作为 `--blocks-file`：

```json
[
  {
    "type": "rich_text",
    "elements": [
      {
        "type": "rich_text_section",
        "elements": [
          {"type": "text", "text": "示例：已提交 "},
          {"type": "text", "text": "Approve", "style": {"bold": true}},
          {"type": "text", "text": "；此前问题已修复。"}
        ]
      }
    ]
  }
]
```

`rich_text` 是完整 block，不能直接替换 `section.text`、`context.elements` 等
只接受 text object 的字段；该段正文使用独立 block，链接和原生元素按其 schema 表达。
它也不能直接用于 `files_upload --message`。

## 图文对象与候选轮播

单卡片：公开可访问的图片 URL，alt_text 说明内容。示例图与真实业务无关；
实际使用应换成获授权且已检查的图片，不能假定 Slack 私有附件 URL 可充当公网图源。

```json
[
  {
    "type":"card",
    "hero_image":{"type":"image","image_url":"https://picsum.photos/400/300","alt_text":"公网演示配图"},
    "title":{"type":"plain_text","text":"示例资料"},
    "body":{"type":"plain_text","text":"一份虚构资料的简短摘要。"},
    "subtext":{"type":"plain_text","text":"示例来源：https://example.com/report"}
  }
]
```

多个卡片放入 carousel.elements，原生左右浏览，无自制翻页按钮：

```json
[
  {"type":"carousel","elements":[
    {"type":"card","title":{"type":"plain_text","text":"方案 A"},"body":{"type":"plain_text","text":"虚构方案：范围小，准备快。"}},
    {"type":"card","title":{"type":"plain_text","text":"方案 B"},"body":{"type":"plain_text","text":"虚构方案：内容多，准备较久。"}}
  ]}
]
```

## 结论与折叠证据

```json
[
  {"type":"rich_text","elements":[{"type":"rich_text_section","elements":[
    {"type":"text","text":"虚构结论","style":{"bold":true}},
    {"type":"text","text":"：等待上游耗时较长。"}
  ]}]},
  {
    "type":"container",
    "title":{"type":"plain_text","text":"演示证据"},
    "is_collapsible":true,
    "default_collapsed":true,
    "child_blocks":[
      {"type":"section","text":{"type":"plain_text","text":"观察：示例等待耗时 1800 ms。"}},
      {"type":"context","elements":[{"type":"plain_text","text":"来源：手工演示数据，未查询真实日志"}]}
    ]
  }
]
```

container 是证据布局，不是权限隔离；折叠不隐藏数据的实际可见性。

## 趋势图

```json
[
  {
    "type":"data_visualization",
    "title":"虚构任务趋势",
    "chart":{
      "type":"line",
      "series":[{"name":"完成量","data":[{"label":"周一","value":10},{"label":"周二","value":15}]}],
      "axis_config":{"categories":["周一","周二"],"x_label":"演示工作日","y_label":"任务数"}
    }
  }
]
```

line/bar/area 使用 series 与 axis_config；每个 series 的 label 必须完整匹配 categories。
pie 使用 segments 而非上述轴结构，不要只改 type。官方还支持 bar/area/pie，
本次桌面实测只覆盖 line，不推断所有图型都已验证。

## 分页明细

```json
[
  {
    "type":"data_table",
    "caption":"虚构任务工时",
    "page_size":1,
    "rows":[
      [{"type":"raw_text","text":"任务"},{"type":"raw_text","text":"工时"}],
      [{"type":"raw_text","text":"示例 A"},{"type":"raw_number","value":2,"text":"2"}],
      [{"type":"raw_text","text":"示例 B"},{"type":"raw_number","value":1,"text":"1"}]
    ]
  }
]
```

首行是表头，所有行列数一致；数值用 raw_number，不将数值伪装成带单位字符串。
page_size 控制原生分页，不需要在消息里加“下一页”业务按钮。
data_table 与 table 是不同块，不能照搬字段或把两者能力混为一谈。

## 任务进度

```json
[
  {
    "type":"plan",
    "title":"虚构研究进度",
    "tasks":[
      {
        "task_id":"demo_read",
        "title":"整理资料",
        "status":"complete",
        "sources":[{"type":"url","url":"https://example.com/report","text":"演示来源"}],
        "output":{"type":"rich_text","elements":[
          {"type":"rich_text_section","elements":[{"type":"text","text":"仅为虚构完成状态。"}]}
        ]}
      },
      {"task_id":"demo_compare","title":"比较方案","status":"in_progress"}
    ]
  }
]
```

plan.tasks 中的 task 对象不带 type，task_id 在同一 plan 中唯一。
单任务可另用 task_card；首次使用先查其 schema，不从 plan 反猜必填字段。
**同一条消息不能同时放 plan 与独立 task_card**：实测 API 返回 invalid_blocks，
原因是 “Plan block and task blocks are mutually exclusive”。需要来源时放进 plan 任务的 sources。
状态只展示已知进度，不会真的启动任务，也不会自行更新；持续编辑需要独立授权。

## 限制与通知

- 本地门禁：UTF-8、标准 JSON、非空数组、type、最多 50 个顶层 blocks、文件 4 MiB、
  嵌套 64 层、20,000 JSON 节点；完整字段及组合约束仍由 Slack 校验。
- card 至少提供 hero_image/title/actions/body 之一；carousel 为 1–10 张卡片。
- data_visualization 每条消息最多 2 个；标题不超过 50 字符。
- data_table 需 caption/rows；至少表头加一行，最多 201 行、20 列；所有表格单元格合计不超过
  20,000 字符。page_size 为 1–100。
- plan 最多 50 tasks；所有 markdown blocks 合计最多 12,000 字符。不要以顶层 50 blocks 门禁代替各组件限制。
- 不确定字段、类型、枚举、资源 ID 或组合时，先查官方页与现有实测，再构造 payload；
  API 拒绝时回读错误，不盲试新字段，不自动截断或拆成额外消息。
- 嵌套 markdown/mrkdwn，以及 rich_text user/channel/broadcast/usergroup 都进入通知预览与门禁。
  plain_text/raw_text 是字面展示，不做名称解析。literal 不等于禁止显式原生通知。
- 不新增未经授权的 mention。全频道和用户组通知仍需要各自 allow flag；格式正确不是写入授权。
- 编辑传完整新布局；若自带 block_id，每次编辑使用新 block_id。不要误以为更新一个嵌套字段就会与旧 blocks 合并。
- Block Kit 不增加本 skill 的 OAuth scope；复杂业务按钮仍需要真实的回调实现与验证。

## 证据与验收

必须区分：**官方文档列出**、**API 接受并回读**、**客户端实际显示/交互**。
Builder 或 dry-run 通过不能替代后两项；一个 workspace/桌面端通过不能外推所有部署及移动端。

2026-09-08 已获授权的测试频道展示中，card 图片、carousel 左右浏览、container 折叠、
line 图、data_table 翻页、plan 展开与状态均通过 API 回读及桌面 UI 操作检查。
中文标点紧贴 mrkdwn 加粗标记时，按[中文标点与加粗边界](#中文标点与加粗边界)使用显式样式。
card 等组件的其他强调现象仍未逐一复验，不宣称其所有样式完全通过。
本文缩小后的 JSON 示例做离线结构检查，不能冒称每个字节都已独立实发。

写前核对摘要、链接、来源、数字单位、通知、交互处理能力；写后独立 get 并查看所需交互。
检查失败应报告精确层次，结果 unknown 先回读，绝不因视觉问题盲目重发。

## 官方资料

- [Block Kit 概览](https://docs.slack.dev/reference/block-kit/)：首次选型及通用布局限制。
- [Text object](https://docs.slack.dev/reference/block-kit/composition-objects/text-object/)、
  [消息格式](https://docs.slack.dev/messaging/formatting-message-text/)：文本语法、verbatim、转义与通知。
- [Section](https://docs.slack.dev/reference/block-kit/blocks/section-block/)、
  [Context](https://docs.slack.dev/reference/block-kit/blocks/context-block/)：字段排布、脚注。
- [Card](https://docs.slack.dev/reference/block-kit/blocks/card-block/)、
  [Carousel](https://docs.slack.dev/reference/block-kit/blocks/carousel-block/)：图文对象及轮播。
- [Container](https://docs.slack.dev/reference/block-kit/blocks/container-block/)：折叠及 child_blocks。
- [Data visualization](https://docs.slack.dev/reference/block-kit/blocks/data-visualization-block/)：图表类型、轴与数值 schema。
- [Data table](https://docs.slack.dev/reference/block-kit/blocks/data-table-block/)：单元格、分页及表格限制。
- [Plan](https://docs.slack.dev/reference/block-kit/blocks/plan-block/)、
  [Task card](https://docs.slack.dev/reference/block-kit/blocks/task-card-block/)：任务状态及 sources。
- [Markdown](https://docs.slack.dev/reference/block-kit/blocks/markdown-block/)、
  [Rich text](https://docs.slack.dev/reference/block-kit/blocks/rich-text-block/)：标准文本与结构化内容的区别。
