# Facebook Community 采集

## 数据入口

- Slack 频道：`#community-pending-posts`，默认 ID `C0BEL8Y0Y74`。
- 唯一调用链：`moe-feedback-collector` → `slack/scripts/slack.py resolve/search`。
- 不直接调用 Slack Web API，不登录或抓取 Facebook 页面。

## 周期口径

`period` 默认采集上一个完整自然周，也可以同时传入
`--period-start / --period-end` 指定恰好 7 天。Slack 搜索条件向周期外各放宽一天，
collector 再按 Asia/Shanghai 对消息 `ts` 精确过滤。

`probe` 最多返回 20 条，允许只看小样本；正式 `period` 必须满足 Slack 返回的
`returned == total`，否则停止，不保存不完整 run。

## 消息分类

### Group 新帖

同时满足以下条件才归一化为 `group_post`：

1. Slack 消息包含 email file；
2. 发件地址域名为 `facebookmail.com`；
3. subject 或 `plain_text` 包含 `needs approval`。

只从 `plain_text` 提取帖子正文、Group 名和 Group ref。Facebook 邮件的收件人、
发件人、HTML preview、退订链接和全部追踪参数不进入 evidence。

### 留言总结

只有消息正文以明确前缀开头才采集：

- `Campaign comment summary:` / `Campaign feedback summary:` →
  `campaign_comment_summary`
- `Facebook comment summary:` / `Facebook feedback summary:` →
  `group_comment_summary`
- `Customer replied:` / `He replied:` / `She replied:` →
  `group_comment_summary`

其它 thread 回复属于内部协作噪声，必须跳过。新增前缀时同步修改解析器、fixture、
测试和本参考文档，不能用宽泛的 `comment` 关键词匹配。

## 隐私与覆盖声明

- 正文中的邮箱替换为 `[EMAIL]`。
- 不保存 Facebook 邮件 envelope 或个人收件信息。
- Facebook URL 只保留 scheme、host、path；query 和 fragment 全部移除。
- 所有 evidence 与 manifest 标记 `coverage=channel-summary`，不得描述成 Facebook
  全量原始数据。

## 排障

- `Slack 数据源配置不可用`：确认已安装 `slack` skill，且其 `.env` 存在 user token。
- `Slack 鉴权或搜索权限不足`：`search` 需要 xoxp user token 及可见频道权限。
- `Slack Facebook 搜索结果不完整`：缩短周期或排查 Slack 搜索分页，不允许忽略。
- accepted 为 0：先用 `probe` 查看当周是否只有内部 thread 回复，或 Facebook 邮件
  格式是否发生变化。
