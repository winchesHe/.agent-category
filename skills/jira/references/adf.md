# ADF

Jira Description 使用 Atlassian Document Format（ADF）。ADF 是 Skill 创建工单时的规范富文本格式；调用方已经持有 ADF，或需要标题、列表、表格、链接、mark、代码块等结构时，优先提交完整 ADF，不要先降级成 Markdown 再转换。

## 当前输入能力

- API create 的完整 ADF：优先使用 `--description-adf-file <path|->`。现有 `--additional-fields.description` 继续兼容，并执行相同的 ADF 与链接校验。
- API create 的 Markdown / 纯文本：通过 `--description` 或 `--description-file` 传入。Skill 按 `jira-md-v1` 转成 ADF，支持 ATX heading、单层 blockquote、单层 bullet/ordered list、无对齐 pipe table、fenced/inline code、link、strong、em、strike 和反斜杠转义。
- Automation create 的 description 当前作为 `PARAGRAPH` 字符串传给规则，不承诺接受完整 ADF。需要结构化 Description 时使用 API mode。

ADF、Markdown 参数和 `--additional-fields.description` 互斥。输入格式只由参数决定，不根据字符串内容自动猜测。未支持 Markdown、非法 ADF、敏感链接或转换残留会在 dry-run 写入前失败；禁止自动降级成字面量文本。

基础结构：

```json
{
  "type": "doc",
  "version": 1,
  "content": [
    {
      "type": "paragraph",
      "content": [{"type": "text", "text": "Content"}]
    }
  ]
}
```

API create 的 dry-run 会返回 `description_input_format`，Markdown 另返回 `markdown_profile=jira-md-v1`。执行后读取 ADF，并按结构、文本、mark 和稳定 attrs 的语义投影比较 postcondition。

## 能力边界

Markdown 兼容层不覆盖全部 ADF。panel、expand、media、mention、status、inlineCard
等原生结构应由调用方直接构造 ADF。完整 ADF 会避免 Markdown 转换损失，但本地只做
结构与安全校验；目标 Jira Cloud、字段配置和服务端 schema 仍决定节点是否可用。

`jira-md-v1` 明确拒绝嵌套或 task list、definition list、Setext heading、thematic
break、缩进代码块、对齐或畸形表格、image、reference link、autolink、footnote、raw
HTML、MDX、emoji shortcode、Jira wiki markup、波浪线 fence，以及未闭合或交叉的
inline delimiter。调用方确实要显示 Markdown 标点时应反斜杠转义，代码应使用受支持的
inline/fenced code。

转换器只使用 Python 标准库，并刻意限制在可穷举测试的 fail-closed 子集。若未来要求
完整 CommonMark/GFM、嵌套容器或复杂表格，应先重新评估成熟解析依赖，不继续叠加正则。

ADF 和 Markdown 链接只允许绝对 `https`、`http` 与 `mailto`。含控制字符、
userinfo 或 token、access_token、api_key、authorization、jwt、signature 等敏感
query key 的 URL 会被拒绝。Skill 不额外限制 ADF 文档大小；目标 Jira Cloud 的请求与
字段限制仍由服务端决定。

## 写前门禁与错误码

Markdown dry-run 依次执行有限解析、URL 校验、ADF 发射与结构校验，再用解析时
记录的结构节点/mark 账本检查转换结果；它不是对最终纯文本做宽泛正则扫描。ADF 输入
不做 Markdown 标记扫描，因为 `#`、`-`、`|` 可能是调用方有意提交的文本。

| 错误码 | 含义 |
|---|---|
| `adf_invalid` | JSON、根结构、节点、attrs、marks 或 content 非法 |
| `markdown_unsupported` | Markdown 使用未支持或有歧义的语法 |
| `markdown_residual` | 结构 token 未按解析账本转换 |
| `unsafe_link` | Markdown 或 ADF 含不安全、敏感链接 |
| `adf_unsupported_transport` | ADF 被用于 Automation 等未支持 transport |
| `adf_postcondition_failed` | Jira 已创建工单，但 Description 回读语义不一致；禁止自动重试 |

输入失败退出码为 2 或 4，错误码显示在 stderr 的 `[jira] <code>:` 前缀中。输入类
错误发生在写请求前；postcondition 失败会在消息中返回已经创建的 issue key。
