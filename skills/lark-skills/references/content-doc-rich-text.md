# content-doc-rich-text：文档丰富文本展示

创建飞书文档、生成飞书报告或调整文档排版时读取；纯读取、评论、权限管理无需加载。文档位置、Wiki 节点与正文写入流程见 [`content-doc.md`](./content-doc.md)。

## 默认展示与场景选择

创建文档默认采用 **XML 丰富文本展示**，主动根据内容使用标题层级、加粗、列表、表格、callout 和语义颜色，不等用户额外要求“美化”。丰富性服务于阅读，不要求每篇凑齐全部组件；短文可以只用段落与重点加粗。用户明确要求纯文本、Markdown 导入或指定模板时遵从其要求。

| 内容 / 意图 | 展示方式 |
|---|---|
| 正文层次 | 完整文档以唯一 `<title>` 开头，正文标题层级连续；段落说明因果，列表呈现并列事项或步骤 |
| 核心结论 / 关键决策 | 重点短语加粗，适合独立强调时使用浅蓝 callout |
| 风险 / 待确认 | 橙色或浅黄色 callout，写明风险或待确认事项；颜色不替代状态文字 |
| 已完成 / 推荐 / 正面结果 | 绿色强调状态词或关键数字 |
| 字段比较 / 方案对照 / 责任分工 | 表格，表头优先浅灰底；单元格保留完整含义，避免整表铺色 |
| 代码 / 公式 | 行内 `<code>`、独立 `<pre><code>` 或 `<latex>`，不以截图替代可编辑文字 |
| 流程 / 关系确需图示 | 按当前 XML 指南选择白板嵌入方式；白板内部编辑另读 [`content-visual.md`](./content-visual.md) |
| 已有文档局部加样式 | 保留原文，取得 block id 后 `block_replace`，不覆盖整篇 |

全文保持同一套颜色语义；通常以不超过三种文字颜色为起点，callout 只用于需要突出的位置，随内容长度调整。不要每段着色或把所有段落放入 callout。

## 语法与配色

写入前读取当前 CLI 随附协议：

```bash
lark-cli docs +update --help
lark-cli skills read lark-doc/references/lark-doc-xml.md
```

下列是常用写法；当前 CLI 指南是标签、属性和嵌套限制的依据。遇到高级块先查帮助指向的扩展协议，不沿用旧版本“全部不支持”的结论，也不猜 raw API schema。

| 用途 | 标签 / 属性 | 取值 |
|---|---|---|
| 文字颜色 | `<span text-color="X">` | `gray` / `red` / `orange` / `yellow` / `green` / `blue` / `purple` |
| 文字背景 | `<span background-color="X">` | 基础色、`light-{色}`、`medium-gray` |
| callout 字色 / 边框 | `text-color` / `border-color` | 基础色 |
| callout 填充 | `background-color` | `gray`、`light-{色}`、`medium-{色}`；默认浅色背景 |
| 表头 / 单元格背景 | `<th/td background-color="X">` | 同文字背景；表头优先 `light-gray` |

```xml
<title>项目进展</title>
<h1>当前结论</h1>
<callout emoji="🎯" background-color="light-blue" border-color="blue">
  <p><b>核心流程已完成</b>，下一步验证边界场景。</p>
</callout>
<p>验收状态：<span text-color="green">已通过正常流程</span>；<span text-color="orange">边界场景待验证</span>。</p>
<h1>行动安排</h1>
<table>
  <thead><tr><th background-color="light-gray"><p>事项</p></th><th background-color="light-gray"><p>完成条件</p></th></tr></thead>
  <tbody><tr><td><p>边界验证</p></td><td><p>覆盖空输入与失败恢复</p></td></tr></tbody>
</table>
```

行内代码强调与公式：

```xml
<p>检查 <code><span text-color="red">addon_ids</span></code> 的空值处理。</p>
<p>算法复杂度为 <latex>O(n \log n)</latex>。</p>
<pre lang="go" caption="字段示例"><code>repeated int64 addon_ids = 5;</code></pre>
```

## 容易导致展示失效的写法

- 文字颜色使用 `<span text-color="...">`，不要使用 `<font color>`、`<text color>` 或 `<span style="color:...">`；这些 HTML 写法可能被剥离或转义。
- `str_replace` 用于文字替换，不能用于插入样式结构；新增颜色、callout 或表格背景使用 `block_replace`。
- callout 的正文使用 `<p>`、列表或待办容器，不放裸文字。当前 XML 指南限制其子块，标题、表格、代码块、图片和白板放在 callout 外；不要依赖多层 callout 嵌套。
- 只转义标签内部文本：`&` → `&amp;`、`<` → `&lt;`、`>` → `&gt;`。不要把整个 XML 标签转义。
- 删除线、待办、引用、分割线、代码块分别使用 `<del>`、`<checkbox done="false">`、`<blockquote>`、`<hr/>`、`<pre><code>`；不猜同义标签。上标或下标公式使用 `<latex>`。
- 某些 emoji 可能被规范化为 💡；需要警告标识时优先使用 🚨 或 🔥，并保留文字含义。

## 写入与验证

1. 创建时随正文一次写入样式；修改已有文档时先用 `docs +fetch --detail with-ids` 配合章节或范围定位，取得真实 block id 和原内容。
2. 按 `docs +update --help` 构造 XML；局部加样式使用 `--command block_replace --block-id <真实block_id> --doc-format xml`。结构改变后重新取得 block id。
3. 写入后使用 `docs +fetch --detail full` 回读目标内容；不要依赖默认 `simple` 或关键词搜索的简化 fragment 判断颜色。大文档按章节或范围读取，必要时再读全文。
4. 核对正文无遗漏、标题层级和重点位置正确，并检查 callout、表格背景与 inline 样式。命名色回读为 `rgb(...)` 是正常落库形式，不是样式失效。
5. 用户要求视觉验收或实际布局仍有疑问时再查看 UI；仅有 API 回读时说明核对的是内容与样式结构，不声称完成视觉验证。

## 相关资料

- [`content-doc.md`](./content-doc.md)：创建位置、Wiki 解析、正文读写、资源与权限操作。
- [`content-visual.md`](./content-visual.md)：需要操作白板内容时读取。
- [`lark-shared.md`](./lark-shared.md)：身份、权限报错或高风险确认时读取；展示需求不改变写入授权。
- `lark-cli skills read lark-doc/references/lark-doc-xml.md`：编写 XML 前读取当前协议；高级块使用该指南指向的对应资料。
