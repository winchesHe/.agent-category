# Slack 搜索语法参考

按需加载——简单关键词搜索无需阅读本文件。当需要复杂搜索策略或搜索结果不理想时参考。

## Search Modifiers

直接嵌入 query 字符串使用：

| Modifier            | 示例                                   | 说明                     |
| ------------------- | -------------------------------------- | ------------------------ |
| `in:channel-name`   | `in:customer-support-issue-discussion` | 指定频道                 |
| `in:<#C01TT9K995M>` |                                        | 按频道 ID                |
| `from:<@U123456>`   |                                        | 指定用户（ID）           |
| `from:username`     | `from:rhea`                            | 指定用户（用户名）       |
| `before:YYYY-MM-DD` | `before:2026-03-15`                    | 日期之前                 |
| `after:YYYY-MM-DD`  | `after:2026-03-01`                     | 日期之后                 |
| `on:YYYY-MM-DD`     |                                        | 指定日期                 |
| `during:month`      | `during:march`                         | 指定月份                 |
| `is:thread`         |                                        | 仅 thread 消息           |
| `has:link`          |                                        | 含链接                   |
| `has:file`          |                                        | 含附件                   |
| `has::emoji:`       | `has::eyes:`                           | 含指定 reaction          |
| `"exact phrase"`    | `"debit card fee"`                     | 精确短语                 |
| `-word`             | `-resolved`                            | 排除词                   |
| `wild*`             | `inv*`                                 | 通配符（`*` 前至少 3 字符）|

## Common Pitfalls

- **无 boolean operators**：`AND`/`OR`/`NOT` 不支持。用空格（隐式 AND）和 `-` 排除
- **无括号分组**：`()` 无效
- **非实时**：最近几秒的消息可能搜不到；已知频道时改用 `scripts/slack.py history --channel <channel> --limit <短时间窗> --include-thread-replies`
- **必须使用 xoxp**：配置 `SLACK_USER_TOKEN`；也可用同为 xoxp 的 `SLACK_TOKEN` 作为兼容入口。Bot Token 不能调用 `search.messages`

## Multi-Search Pattern（CS 分析）

深度历史上下文搜索，分 4 步：

1. **按工单号**：`CS-12345` — 直接提及
2. **按关键词 + 频道**：`"debit card fee" in:<#C01TT9K995M>` — 相似讨论
3. **按组件/领域**：`"FinTech deposit"` — 领域相关 thread
4. **按用户**：搜索 QA assignee 的消息，找调查笔记

### 搜索策略

1. 先用简单关键词或工单号搜索
2. 结果太多 → 在原始 query 中加 `in:` 频道 modifier 或日期范围
3. 结果太少 → 换同义词、去掉过滤条件、用工单摘要关键词
