# <Requirement>｜Delivery 交接与结果

## 当前可用输入

- 业务目标：
- AC / 可观察结果：<当前可用内容、稳定链接或 Unknown>
- 实现 identity / repo / 范围：<当前可回读内容或 Unknown>
- 目标 Surface：CLI/API / Web / Electron / iOS / Unknown
- 环境意图：
- 已知限制：
- 允许副作用：0 / <用户范围内对象、清理>
- Owner Review 边界：
- 交付物约定：验收摘要 / HTML / 已有 Site 更新 / 其它明确要求

> 字段在 owner Skill 实际消费时解析。Unknown 不阻止 Explicit Delivery；owner Skill 若真实无法执行，应返回精确拒绝原因。

## Delivery 结果

| 项目 | 结果 |
|---|---|
| 实现 / 验收上下文 |  |
| Surface / Case 三态结论 | 通过 / 不通过 / 信息不足；分别列出依据 |
| 覆盖范围 / 未验范围 |  |
| 必要证据 / 约定交付物 | 分别说明是否充分、是否完成 |
| 已有报告定位（如有） | task_id / 报告路径 / 已有 report_round；无报告则不填 |
| Blocked / Skipped / Limitations |  |
| Side effects | 0 / 去敏摘要 |
| 用户评审 | 待验收 / accept / reject / comment |

## OPC 下一步

- 只写生命周期动作；环境、证据和修复细节留在 owner Skill。
