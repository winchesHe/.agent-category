# Intercom Linked Conversations

`read` 对 `CS-*` 工单默认启用 Intercom linked conversations 读取；`intercom --issue <issue>` 可只测试 Intercom 链路。两者都会先从 Intercom for Jira 暴露的 Jira app 字段、Jira API 返回的字段、评论、issue links 和 remote links 中发现 Browse linked conversations；发现 conversation ID 后，使用 Intercom for Jira GraphQL 读取详情。

GraphQL 认证优先使用 `JIRA_INTERCOM_JWT` 环境变量；长期使用建议配置 `JIRA_INTERCOM_JWT_COMMAND`，让命令在运行时从浏览器/Jira iframe 自动输出新的 runtime JWT。不要把 JWT 写进命令行、文档或代码。

`JIRA_INTERCOM_JWT_COMMAND` 约定：

- 用 `shlex.split()` 拆分执行，不走 shell。
- stdout 第一行必须是 JWT（可带或不带 `JWT ` 前缀）。
- 命令会收到环境变量：`JIRA_ISSUE_KEY`、`JIRA_ISSUE_ID`、`JIRA_PROJECT_KEY`、`JIRA_BASE_URL`。

如果已经拿到 conversation id 但没有 runtime JWT，`read` / `intercom` 会调用 Jira Connect servlet：

```text
POST /plugins/servlet/ac/io.toolsplus.atlassian.connect.jira.intercom/conversation-details-dialog
```

请求体包含 `plugin-key`、`product-context`、`key=conversation-details-dialog`、`classifier=json` 和 `ac.selectedConversationId=<conversation_id>`。返回的 `contextJwt` 用作 Intercom GraphQL 的 `Authorization: JWT ...`。

## Discovery Sources

conversation ID 从以下 Jira 内容中提取：

1. Intercom for Jira app 字段 `Linked Intercom conversation IDs`，字段值是 comma-separated conversation ID 字符串。
2. Summary、Description、Issue Description、Bug Description、Reproduce Steps、Story Description、Cause and Solution。
3. Jira comments。
4. Jira issue links 和 remote links 的 title / url / relationship。
5. 附件文件名中明显的 conversation ID。

## Supported Link Shapes

```text
https://app.intercom.com/a/inbox/<workspace>/inbox/conversation/<conversation_id>
https://app.intercom.com/a/inbox/<workspace>/conversations/<conversation_id>
intercom conversation <conversation_id>
conversation_id=<conversation_id>
```

## Output Shape

`read` 返回：

```json
{
  "intercom": {
    "enabled": true,
    "linked_conversations": [
      {
        "id": "123",
        "url": "https://app.intercom.com/a/inbox/.../conversation/123",
        "title": "Browse linked conversation",
        "relationship": "relates to",
        "source": "remote_link",
        "details": {
          "state": "open",
          "source": {"body_text": "..."},
          "contacts": [],
          "conversation_parts": []
        }
      }
    ],
    "warnings": []
  }
}
```

`intercom` 返回同一组 conversation details，但顶层是：

```json
{
  "command": "intercom",
  "issue": {"key": "CS-12345"},
  "linked_conversations": [],
  "warnings": []
}
```

## Failure Handling

- 未发现链接：`warnings[]` 包含 `no_intercom_linked_conversations_found`。
- 缺少 runtime JWT 且无法通过 Connect servlet 获取 `contextJwt`：`warnings[]` 包含 `runtime JWT unavailable` 或 `intercom_dialog:<id>:<error>`。
- 单个 conversation 拉取失败：保留其它结果，并在 `warnings[]` 写 `intercom:<id>:<error>`。
- 不要把 Jira token、Intercom JWT 或 Authorization header 输出到 stdout/stderr。
