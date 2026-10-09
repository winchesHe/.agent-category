# JQL Patterns

CS 项目常用 JQL 查询模式。

## Similar Ticket Search

```jql
project = CS AND summary ~ "debit card" ORDER BY created DESC
project = CS AND summary ~ "invoice" AND cf[10089] = FinTech ORDER BY created DESC
project = CS AND summary ~ "deposit" AND status = Closed ORDER BY created DESC
project = CS AND text ~ "processing fee" ORDER BY created DESC
```

## Filtering

```jql
project = CS AND cf[10089] = FinTech ORDER BY created DESC
project = CS AND cf[11580] = Payment ORDER BY created DESC
project = CS AND cf[10049] = "P1-Critical" ORDER BY created DESC
project = CS AND component = "Payments" ORDER BY created DESC
project = CS AND created >= -30d ORDER BY created DESC
```

## Combined Queries

```jql
project = CS AND cf[10089] = FinTech AND cf[10049] IN ("P0-Block", "P1-Critical") AND cf[10084] IS NOT EMPTY ORDER BY created DESC
project = CS AND issue in linkedIssues("FIN-6100") ORDER BY created DESC
```

## Weekly Squad Feedback

```jql
project = CS AND created >= "2026-08-16" AND created < "2026-08-25" AND cf[10089] = "Grooming" ORDER BY created DESC
```

Jira 裸日期按调用账号时区解释。需要按 `Asia/Shanghai` 生成自然周时，应把 JQL
查询窗口前后各扩一天，完整分页后再用返回的 `created` 做本地半开区间精确过滤。
Feature Request 使用源工单 `issue_type` 判断；设计反馈必须检查关联目标的
`project_key=DES` 且 `issue_type=Design Issue`，不能用标题关键词或 `link_count > 0`。

## Intercom for Jira

Intercom for Jira exposes app JQL fields for linked conversation IDs and link count:

```jql
project = CS AND linkedIntercomConversationId IS NOT EMPTY ORDER BY updated DESC
project = CS AND linkedIntercomConversationId = 123456
project = CS AND linkedIntercomConversationId IN (123456, 234567)
project = CS AND linkedIntercomConversationCount > 0 ORDER BY linkedIntercomConversationCount DESC
```

## Common Pitfalls

- `summary ~` 通常比 `text ~` 精准；先用 summary 缩小候选。
- 特殊字符需要转义，尤其是引号、括号和斜杠。
- Squad 是 `cf[10089]`，Feature Domains 是 `cf[11580]`，Cause and Solution 是 `cf[10084]`。
- Intercom for Jira 的 JQL 字段只保存 conversation ID/count；客户原文仍需用 conversation ID 调 Intercom for Jira GraphQL。
- 搜索必须用 POST `/rest/api/3/search/jql`，不要使用 GET `/rest/api/3/search`。
- `issueLinkType` 或 `link_count` 不能单独证明目标是 Design Issue；DM、GRM 等项目也可能使用同一 Link Type。
