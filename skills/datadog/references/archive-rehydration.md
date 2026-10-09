# Datadog Archive Search 与再水化

当目标日志超出可搜索保留期时，使用此流程引导用户在 Datadog UI 中搜索 archive。默认先用 Archive Search 的 Search mode；只有需要完整平台能力或超过 24 小时保留结果时才进入 Search & Rehydration。

## 何时使用

- 目标时间窗口超过该服务的可搜索保留期。
- 用户或前置调查已明确日志已归档。
- 已确认时间、DQL 语法和已知过滤条件无误，但一次保留完整条件的精确 Flex 搜索仍为空，且调查仍依赖该时间窗口的数据。

如果时间范围仍在可搜索保留期内，先校验并补全已知查询条件，不要直接跳到 archive。发现明确查询错误时，只修正该错误后查询一次；不要重复相同参数或通过去掉已知条件扩大搜索。

## 保留期启发式

- 大多数服务默认：`15d`
- `moego-server-payment`：`3d` hot + `180d` flex
- `moego-svc-payment`：有 archive 定义，无特殊 searchable-retention override，按默认启发式处理。
- 以上为仓库默认值，非 Datadog 全局真理。用户提供更新信息时以用户为准。

## 模式与权限

| 模式 | 何时选择 | 权限 | 结果边界 |
|---|---|---|---|
| Archive Search — Search | 默认；只需在 Log Explorer 直接查看归档证据 | `logs_archive_search` + `logs_read_archives` | 搜索结果保留 24 小时；分析能力受限 |
| Archive Search — Search & Rehydration | 需要 monitors、dashboards、security rules 等完整平台能力，或结果需保留超过 24 小时 | `logs_write_historical_view` + `logs_read_archives` | 创建 Historical View，按配置保留 |

如果用户看不到 Archive Search 或相应模式，优先提示可能缺少权限，而非假定日志已丢失。

## Handoff 模板

需要人工搜索 archive 时，使用或改编以下消息：

```text
标准层和精确 Flex 查询都没有返回证据；这只说明当前可搜索层未命中，不能证明日志不存在或事件正常。

请在 Datadog UI 的 Log Explorer 中启动 Archive Search：
1. 默认选择 Search mode。
2. 选择覆盖目标事件的最窄时间范围和对应 archive。
3. 保留原始 service、env 与业务条件，不要为了命中而去掉已知过滤。
4. 如果 Search mode 的 24 小时结果保留或分析能力不够，再选择 Search & Rehydration。
5. 启动前检查预估扫描量；结果生成后，把 Archive Search 或 Historical View 链接发给我继续调查。

Search mode 需要 logs_archive_search + logs_read_archives；
Search & Rehydration 需要 logs_write_historical_view + logs_read_archives。
当前 Skill 与公开 Logs Archives API 不提供启动 Archive Search/Rehydration 的入口，因此这一步需要在 UI 中完成。
```

## 缩窄过滤建议

启动前推荐最窄的过滤条件：

- `service:<service>`
- `env:<env>`
- `@id:<request_id>`
- `trace_id:<trace_id>`
- `resource_name:<endpoint>`
- `status:error`
- 业务 ID、客户 ID、订单 ID 或其他已索引的实体键
- 可靠索引的短错误签名

除非没有更窄的切入点，否则避免搜索宽泛的全服务时间窗口。

## 注意事项

- 如果用户已有 Archive Search、Historical View 或再水化日志链接，直接使用，不要求重新创建。
- Public Logs Archives API 覆盖 archive 配置和读取者管理；不要声称当前 Skill 能通过该 API 启动 Archive Search 或再水化。
- 用户返回 Datadog 链接后，从该结果继续调查，保持原始搜索意图不变。
