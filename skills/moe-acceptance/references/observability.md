# 准备与清理日志

仅在定位准备耗时、失败组件或重试原因时加载。已有 case 正常续跑不要求读取日志或生成新 run；日志不是业务验收状态机。

## 当前实现

`scripts/observability.py` 的 `EventLogger` 每个实例生成独立 `runId`，namespace/session 哈希为 `sessionKey`。事件按该 run 的 `seq` 写入：

`/tmp/moe-acceptance/<namespace>/runs/<runId>.jsonl`

实际字段为 `runId`、`sessionKey`、`seq`、`ts`、`phase`、`action`、`status`、`attempt`、`trigger`、`retryable`、`errorClass`、`nextAction`、`durationMs`，有详情时追加 `details`。durationMs 由 monotonic clock 计算，未计时事件为 null；attempt/trigger/retryable 默认 1/initial/false，不代表发生过重试。

登录 bridge 顺序处理 dev、Whistle、浏览器、Host、MIS、跳转和身份读取。具体事件以实际 JSONL 为准，不要求每阶段都有同形 started/terminal 配对。例如 Host 成功和 MIS skipped 是单事件，`_timed` 包装动作才记录耗时。`run.started` 的 details 包含 browserMode，成功摘要不含模式或阶段耗时汇总。

stdout 成功 JSON 包含 `ok/runId/logFile/session/target/identity/actions`；actions 中可见 MIS 是否调用、dev/Whistle 是否复用。cleanup 是独立 run，摘要包含 `ok/runId/logFile/cleanup`。业务 case 的三态结果由 AI 的观察形成，不由这些日志决定。

## 如何定位

1. 从故障返回取得已有 runId/logFile，读取对应末尾事件，再定位该 run 内最早的组件失败。
2. 用组件 phase/action 和 errorClass 看失败位置；`run.failed` 是总体失败，不能只看它就认定唯一组件。
3. 比较有记录的 durationMs、reused/skipped 与 actions，判断时间是否花在实际准备、等待或重复登录。
4. nextAction 目前可能是顺序流程中的下一个阶段或 inspect-log，不保证是完整的局部修复处方。AI 结合当前故障判断最小动作，不机械执行字段。
5. 明确修复假设、等待上限和再次尝试原因；无新证据就停止重复。不把重跑 bridge 当默认修复。

## 脱敏与保留

details 对含 token/cookie/password/authorization/secret/query/body 的键做脱敏，字符串截断为 240 字符。sessionKey 哈希不代表其它账号、路径、URL 或自由文本都已脱敏；不要把完整页面、认证 URL 或秘密塞进普通字段，也不要直接发布未检查日志。

任务结束精确清理自有运行资源，JSONL 保留。并行 session 各用独立 run 和日志；当前同一 bridge 的准备链顺序执行，不声称已并行 dev/Whistle。共享 worktree 编辑/重启串行。

## 未实现边界

当前没有 parentRunId 自动关联、failedPhase 字段、parallelGroup、waitMs/processStartMs/browserCommandMs/misMs 细分或最终 phase 耗时汇总，也没有每个 AI 业务动作的自动埋点。上述不是调用方必须补齐的 gate；不为读取日志重启 session 或新增持久化状态。

已知 URL 摘要与服务归属校验的范围限制以 T2 桥接合同为准，日志不能替代来源和身份的实际观察。
