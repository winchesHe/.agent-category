# Grooming Report 发送日志排查

Grooming Report 通知没有独立 Datadog service，主要走 `moego-server-message`。

## SMS 发送

- `targetType=151` 标识 Grooming Report SMS。
- 搜索关键词：`"Grooming Report"` + business id、business name 或 pet name。
- 示例 DQL：`service:moego-server-message "Grooming Report" businessId:122164`

## 邮件发送

- `sendEmailSendEvent`：系统发出，`direction=SEND`。
- `sendEmailReceiveEvent`：客户回复，`direction=RECEIVE`。
- 搜索关键词：`"Grooming Report"` + pet name 或 business id。

## 数据源注意

Redshift 镜像可能滞后，近期 Grooming Report 发送记录应优先从 Datadog 日志取证。
