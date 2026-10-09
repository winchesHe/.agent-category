# Slack 消息格式参考

用于 `send/edit` 正文与 `files_upload --message`。示例是虚构文本，不代表已授权发送。

## 场景决策树

撰写前主动选择消息结构，不将 Block Kit 仅作为 Markdown 失败后的兜底；
无需先尝试 Markdown 或证明它不适用，也不在发送失败后自动换格式重发。

- 用户明确指定 Block Kit：直接加载 [Block Kit 参考](block-kit.md)，提供 `--blocks-file`。
- 普通回复、摘要、标题、列表、链接与代码：直接写标准 Markdown；`send/edit` 默认 `--format markdown`。
- 内容、原生 Slack 语义、布局或交互需求适合结构化消息：加载 [Block Kit 参考](block-kit.md)，提供 `--blocks-file`。图片、轮播、图表、任务状态、原生 mention 和动态日期只是示例，不限制使用范围。
- 要求逐字纯文本：Block Kit 的 `plain_text` text object，或 `rich_text` 的无样式 text 元素；不要把源文中的星号当格式。
- 附件说明：`files_upload --message` 仍是简短原生 mrkdwn，不接受相同的 blocks payload。

Block Kit 的文本类型与写法见[语法模型](block-kit.md#语法模型)。
未指定结构且没有其它需求的普通短回复优先 Markdown。

## Markdown 默认路径

CLI 仅处理换行、mention 和通知门禁，正文以 `markdown_text` 交给 Slack 解析；
不会本地转成 mrkdwn/rich_text，不猜测语法，不在失败时改格式重发。
`send/edit` 的 `markdown_text` 不能同时带 `text` 或 `blocks`，上限为 12,000 字符。
[发送字段](https://docs.slack.dev/reference/methods/chat.postMessage/)、
[编辑字段](https://docs.slack.dev/reference/methods/chat.update/)。

| 表达 | 标准 Markdown 写法 |
|---|---|
| 粗体 / 斜体 / 删除线 | `**验证通过**`、`*补充*`、`~~旧方案~~` |
| 标题 | `## 验证结果` |
| 链接 | `[查看报告](https://example.com/report?q=1#detail)` |
| 列表 | `- 项目`、`1. 步骤` |
| 引用 | `> 原话` |
| 行内代码 | 反引号包围代码 |
| 多行代码 | 独占行的 backtick fence，可带语言标签 |
| 段落 | 使用真实空行，不是字面量 `\n` |

不要混入原生 `*粗体*`、`<URL|标题>`：前者在 Markdown 中是斜体。
普通代码与链接目标不能为了排版被改写。不要把整条消息放进代码块。
Slack 决定实际支持和渲染结果；CLI 不再因本地转换器不支持表格、图片或嵌套结构而拒绝。
需要稳定的表格、图片或任务结构时，主动选 Block Kit，不能把 API 接受当作所有客户端正确显示的证据。

## 通知边界

没有通知意图时使用普通姓名。send 默认 `mention-mode=resolve`，edit 默认 `literal`；
resolve 把代码和链接目标以外的 `@name`、`@{email}`、`#channel` 唯一匹配为 Slack 控制串。
零匹配或多匹配会停止。literal 不解析人类姓名，但**不屏蔽显式原生 mention**，也不绕过广播门禁。
链接标签属于可见正文；需要字面名称时使用 literal，不假定标签受到保护。
当前保护范围是反引号行内代码、backtick/tilde fence 和链接目标，不是完整 Markdown AST；
用 fenced code 表达示例，不依赖缩进代码或 HTML 转义绕过通知检查。

`@here/@channel/@everyone`、`<!here>/<!channel>/<!everyone>` 需 `--allow-broadcast`；
用户组控制串需 `--allow-usergroup-mention`。可解析控制串进入预览清单，
但 Slack 未单独保证 Markdown 控制串的实际通知行为。需要明确通知时使用 Block Kit
的 rich_text user/usergroup 元素，并保留授权检查。
代码中的控制串应保持代码，不通过 fallback 另发通知。

## Block Kit 与附件说明

`--blocks-file` 自动切换为 `blocks + text`，顶层文本是独立、可阅读的 fallback，
不是另一份 Markdown 正文。语法、完整场景 JSON、原生交互限制见 [Block Kit 参考](block-kit.md)。

附件说明仍使用原生 mrkdwn：`*粗体*`、`_斜体_`、`~删除线~` 和 `<URL|标题>`。
`files_upload --message` 按 literal 处理，但频道和用户组广播仍需各自 allow flag；
该限制不能由 Markdown 正文的默认行为推导或覆盖。

## 预览与验收

多行正文使用 UTF-8 文件。以下只执行只读预检：

```bash
python3 "$SKILL_DIR/scripts/slack.py" send --channel '<channel_id>' \
  --thread-ts '<root_thread_ts>' --text-file /tmp/slack-message.md --dry-run

python3 "$SKILL_DIR/scripts/slack.py" edit --url '<permalink>' \
  --text-file /tmp/slack-message.md --dry-run
```

检查最终 `markdown_text` 或 `blocks + text`、完整链接、代码和通知清单。
正式执行可用 `--confirm-preview <digest>` 绑定预览；edit 还绑定原消息 text/blocks/edited，
但不是服务端原子 compare-and-swap，也不能替代 get、diff 和最终授权。

dry-run 不是客户端视觉预览。写后核对实际返回与独立回读，格式敏感时查看客户端。
不向真实频道发送未经授权的测试消息；结果未知先回读，禁止因渲染不对而盲目重发。
