# Slack 产品 / 设计 Owner 走查

## 显式与自动触发

用户点名发送产品/设计走查时立即执行，使用当前可得 PRD、设计、验收地址和证据；Delivery 未 finalized 或附件不完整只进入 Context/Limitations。

只有 Agent 准备自动发起走查时，才要求首次 Delivery finalized，即本次约定验收已结束、结果与交付物已核对；按 [delivery.md](../stages/delivery.md) 判断，不要求 owner Skill 提供 finalize 命令或 seal 状态。该自动时点不能阻止 Explicit Execute。

所有 Slack 操作使用 `SLACK_SKILL_TOKEN_MODE=user` 与 User Token；缺 token/权限/scope 属于真实外部拒绝，不尝试 Bot。

## 根消息

```text
<@DESIGN_REVIEWER_ID> <@PRODUCT_REVIEWER_ID> 麻烦走查一下：

【需求】<JIRA + 正式标题>
【PRD】<当前可用 PRD 链接>
【设计稿】<当前可用 Figma Node>
【验收地址】<显式地址；未提供时由 Web 前端分支推导 https://<branch-slug>-grey-go.t2.moego.dev>

【Mobile】<对应 Mobile 分支；适用时保留>
【白名单】<适用时保留>
```

不可用或不适用行直接删除，并在正文末尾简要说明当前缺失证据；不伪造链接。

## 验收地址与运行面

`【验收地址】` 是 Web 的唯一验收入口，同时覆盖 Legacy 与 Fulfillment；不得再输出单独的 `【Fulfillment】` 行。

1. 用户显式提供验收地址时直接使用，不再根据分支覆盖。
2. 未显式提供时，使用 `github-workflow` 回读当前 Web / 前端 PR 的唯一分支；去掉可选的 `refs/heads/`，再去掉一个开头的 `feature-`、`feature/`、`bugfix-` 或 `bugfix/`。
3. 将剩余内容转为小写，把 `/`、`_` 转为 `-`，合并连续 `-` 并移除首尾 `-`。结果只允许小写字母、数字和内部连字符，且拼接后的首个域名 label `<branch-slug>-grey-go` 必须非空且不超过 63 个字符；不合法时不得截断或猜测，删除 `【验收地址】` 行并说明限制。
4. 合法时生成 `https://<branch-slug>-grey-go.t2.moego.dev`。例如 Web 分支 `feature-grm-2310-snap` 生成 `https://grm-2310-snap-grey-go.t2.moego.dev`。

`【Mobile】` 只展示通过 `github-workflow` 回读的对应 Mobile 短分支名，不生成 Mobile 验收 URL；Mobile 不在范围内时删除整行。Web 或 Mobile 分支不能唯一确认时，不从 Jira Key、需求标题或历史分支反推。

## 本地 HTML 附件与位置

本地验收材料按 [本地 HTML 附件](slack-pr-review.md#本地-html-附件) 准备和上传完整 `.html` 文件。附件总数按实际 HTML 报告文件计算，报告内的图片不另计数或拆发。

- `1–4`：正文和全部 HTML 文件随根消息发送。
- `> 4`：根消息只发正文，全部 HTML 文件按顺序进入同一 thread。
- `0`：发送文本走查请求并说明暂无附件。

不混放根消息/thread。报告仍需完成脱敏，附件顺序与正文中的报告顺序一致。

## 写后回读与修正

回读 Reviewer、全部实际链接、root/thread identity、每个 HTML 的 File ID/文件名/类型/大小/任务与版本/顺序/位置。错传或漏传 HTML 在原 thread 补发并说明替代；删除重发根消息需要额外明确授权。
