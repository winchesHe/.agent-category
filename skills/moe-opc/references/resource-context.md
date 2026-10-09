# Resource Context｜PRD 定向资料收集

Resource Context 是填写 PRD 的证据输入，不是独立阶段或门禁。PRD 在执行中按用户本次 input 收集所需资料，并只继续执行该 input 包含的后续动作。

## 搜索目标

从用户给出的 Title、Jira 或当前需求身份出发，逐项补齐现有 PRD 模板需要的事实。先判断哪个模板字段缺证据，再定向查找；不要为了“资料完整”横向穷举所有系统。

达到以下任一条件即可停止当前主题的搜索：已有足够证据支持可执行结论；权威来源已经查尽；继续搜索不会改变 PRD 内容。没有找到的内容标记 Unknown，不因为 Resources 不全拒绝建立 PRD。

## 按事实类型选择权威来源

不存在适用于所有事实的固定来源优先级。按问题类型选择来源，并记录来源时间与有效性：

| 事实类型 | 优先来源 |
|---|---|
| 客户痛点、用户场景、workaround | Jira/CS、Intercom、用户反馈和可追溯的一手记录 |
| 产品决策、范围和历史约定 | 用户明确结论、Jira 决策记录、飞书正式文档、Slack 决策上下文 |
| 当前产品与实现行为 | 当前代码、配置、Feature Flag、可验证产品行为；历史文档只作对照 |
| 线上状态、错误与质量 | Datadog、Sentry、GrowthBook 和对应环境的可回读事实 |
| 使用规模、分布和影响 | Redshift、PostHog 或其它有明确口径的数据来源 |
| Jira 对象、字段、`updated` 与当前可见 schema | `$jira` |
| repo、代码、PR 与历史实现 | `$github-workflow` |

业务术语翻译和跨来源检索优先交给 `$moe-business-context` 编排。来源冲突时不套用“代码 > Jira > 文档 > 讨论”的通用排序；说明冲突属于哪类事实、各自时间和为何选择当前结论。

## 输出要求

按 `assets/templates/resource-context.md` 组织结果：

- 已验证事实必须带可回读来源；敏感客户内容只保留去敏摘要。
- 推断必须标明依据，不能写成事实。
- 当前行为单独成节；无法确认时明确写 Unknown。
- 冲突与未知项单独列出，不用缺省值掩盖。
- 最后把证据映射回 PRD 模板字段，避免 PRD 与 Jira 分别重新解释资料。

Resource Context 不负责替用户决定 Goal、Scope、Solution 或 AC。只有需求/搜索目标本身无法唯一确定时可以中断；产品选择由 PRD 阶段在执行中处理。
