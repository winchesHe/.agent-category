# Crash 分析模式

## 错误分类决策树

| 信号 | 判断 | 下一步 |
|---|---|---|
| Exception type 是 `TypeError` / `NullPointerException` | 客户端代码路径候选 | 查 `(in_app)` 帧、共同 stack 和触发输入；未读代码前不确认根因 |
| Exception message 含 `timeout` / `connection refused` | 网络或依赖异常候选 | 查失败请求 breadcrumb；有服务端标识时交给 Datadog 取证 |
| Exception message 含 `permission denied` | 权限相关候选 | 区分 Sentry API 鉴权失败与被观测业务的权限错误 |
| Breadcrumbs 最后几条是 HTTP 4xx/5xx | 后端关联候选 | 保留 path/status/time，去 Datadog 用 request ID 或 trace ID 验证 |
| Exception 含 `OutOfMemory` / `StackOverflow` | 资源耗尽候选 | 检查设备、OS、版本分布和重复样本 |
| Exception 含 `ConcurrentModification` | 并发/竞态候选 | 检查 breadcrumbs 时间间隔和共同操作序列 |
| Exception message 含 JSON parse/decode error | 数据格式候选 | 检查响应证据；不能仅凭异常文本断言后端返回值错误 |

## Breadcrumbs 分析模式

崩溃前的最后操作序列，按 category 分类：

| Category | 含义 | 分析价值 |
|---|---|---|
| `http` | 网络请求 | status >= 400 形成跨系统线索，不等于已确认后端根因 |
| `ui.click` / `navigation` | 用户交互 | 重建用户操作路径，帮助复现 |
| `console` | 控制台日志 | 可能包含业务逻辑错误信息 |
| `app.lifecycle` | 应用生命周期 | 判断是否在前后台切换时崩溃 |
| `xhr` / `fetch` | 异步请求 | 与 `http` 类似，注意请求时序 |

重建崩溃前操作路径时，从最后一条 breadcrumb 往前读，找到触发链。关注时间间隔：连续快速操作可能是竞态条件。

`analyze` 取 selected event 中首个 error/fatal 级别或 exception/error 类别线索之前的最后一次 navigation；普通 console 日志不截断路径。该边界只是定位线索，不等于已确认的根因时刻。

## 堆栈帧优先级

1. `(in_app)` 帧：MoeGo 自有代码，最高优先级。
2. 框架帧中的回调：可能是 MoeGo 注册的 handler。
3. 纯第三方/系统帧：通常不是根因，但提供崩溃上下文。

当所有帧都不是 `(in_app)` 时，只能说明当前 stack 未标出自有代码帧；回到 breadcrumbs 查最后的业务操作，并检查 sourcemap/符号化是否完整，不能直接判为第三方根因。

异常来源分类和直接崩溃仓库共用帧选择顺序：最后一个 `in_app` 帧 → 最后一个应用 bundle 帧 → 最后一个可用帧。选中帧无仓库映射时保留未知，不能借用前面的调用方仓库。

## 与 Datadog 联动

当 breadcrumbs 显示 HTTP 请求失败时：

1. 从 breadcrumbs 提取失败 URL path、status code 和 crash 时间。
2. 如果 breadcrumbs 有 `x-request-id`，优先用 Datadog 查 `@id:<uuid>`。
3. 没有 request id 时，用 path 和 status 搜：`@http.url:*<path>* status:error`；只有 breadcrumb 明确提供 service 字段时才添加 `service:<name>`，不得从 URL 或业务印象猜服务名。
4. 从日志提取 trace_id，再用 Datadog 展开完整调用链。
5. 只有 Datadog 日志或 trace 证实后端失败与该 event 的时间、请求和调用链对应时，才能把前端 crash 描述为后端问题的症状；否则保留为待验证关联。

## 采样率注意事项

- Sentry issue 的 event count 受客户端采样率影响，不等于实际发生次数。
- 同一 issue 短时间大量 event 可能是循环崩溃，不代表大量用户受影响。
- 评估影响面优先看 `userCount` 和 `tag-values --tag user` / release / environment 分布。

## 多 Event 对比

- `analyze` 的异常链、route 和后端关联只基于 selected event；顶层聚合 exceptions/breadcrumbs 只用于发现待比较候选，不能跨 event 组成时间链。
- 不要只看 latest event：它可能是边缘样本。
- 如果 issue 有多个 event，对比共同点：
  - 相同堆栈帧 -> 稳定崩溃位置线索，不自动等于根因。
  - 相同 breadcrumb 模式 -> 重复触发路径线索。
  - 相同 tags（release、os.name、browser.name）-> 集中度线索，需结合分母判断。
- 共同点提高候选置信度，差异点提示触发条件变体；有限样本不代表完整总体。

## 版本回归判断

当 tags 中 `release` 集中在某个版本时：

1. 对比该版本发布时间和 issue 首次出现时间。
2. 如果高度吻合，把该版本列为回归候选，再查部署时间、变更记录与对照版本。
3. 建议查该版本 changelog 或 PR 列表，定位引入变更。
4. 如果 issue 跨多个版本存在，只能排除“仅该版本出现”；仍需检查版本占比、首次出现时间和符号化差异。

## 平台特定崩溃

| 信号 | 判断 |
|---|---|
| 仅 iOS | 检查 iOS 版本、设备与 release 分布，再验证 API 行为候选 |
| 仅 Android | 检查设备、内存信号、OS 与 release 分布 |
| 仅特定浏览器 | 检查浏览器版本、Web API 支持和 sourcemap |
| 跨平台均有 | 平台特异性降低，但仍不能只凭分布确认业务逻辑根因 |

## 报告输出要点

分析完成后，报告中应包含：

- 直接崩溃表现：exception type + message + 可用的 stack 位置。
- 崩溃触发路径：breadcrumbs 重建的操作序列。
- 影响范围：平台、版本、用户数。
- 根因候选及证据强度：客户端代码、后端关联、权限/环境或未知。
- 如果 Datadog 已验证后端关联，附查询范围和 trace/log 证据；未验证时只给 handoff。
