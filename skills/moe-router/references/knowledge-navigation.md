# 跨 skill 知识导航

保留当前任务入口，从当前操作和缺口选择知识归属。下表中的 skill 路径从实际 catalog 定位，再读其 SKILL.md 的对应条件、索引和相关正文；不依赖相邻安装，也不要求逐项预读。

| 自然语言线索 | 知识归属 | 为什么读这里 |
|---|---|---|
| T2 Pod 查询、日志或转发入口不明；Headlamp 可访问但裸 kubectl 查不到 context | `moe-t2-k8s`；RPC 目标、端口和协议核对再读 `moe-development-experience` 的 gRPC 经验 | T2 wrapper 负责 Host kubeconfig 选择与调用范围；从当前 catalog 解析入口，不凭裸命令失败认定无权限。缺少 skill 时说明依赖，不自动安装或造替代入口 |
| T2 PostgreSQL/MySQL 连接、凭据或 SQL 操作入口不明；想把通用 CLI 模板用于 T2 | `moe-t2-database`；业务落点、事务与测试隔离判断查 `moe-development-experience` 的数据库经验 | 专业 skill 维护 T2 连接与执行契约，原生客户端按其规则使用；数仓只读查询仍用 `redshift`，Redis 与非 T2 不套此入口 |
| 开发调试时想借已运行 iOS App 的身份查接口；只有 App 现场也要发 API；调试连接、产品客户端或异步结果回读不明 | `moe-acceptance` 的 iOS runtime API 指引 | 这份操作知识归属验收平台通道，开发入口明确也不能跳过。只借用当前需要的通道知识，不展开完整验收或重新准备健康 App |
| 已有 App/Web 身份与现场，想找以前用过的业务接口、核对数据或选请求通道 | `moe-acceptance` 的数据与 API 知识指引 | 已验证接口的发现、适用范围及现有通道选择由其维护；接口调查不等于另开浏览器或重做登录 |
| 调试、修复或续验时要保留即将消失的错误、前后变化、异步过程证据 | `moe-acceptance` 的证据与复验指引 | 证据需要在现场变化前保存；任务仍可由开发入口组织，读采证知识不要求先生成报告 |
| 已有 Go 应用重启后仍像旧逻辑；构建、启动或依赖落点不确定；知道有仓库操作经验但忘了位置 | `moe-development-experience`，开发任务继续由 `moe-development` 组织 | 原索引按仓库、操作与症状定位正文，区分已有应用运行与新增服务；这里只定位，不复制内部主题表 |
| 改了字段、Struct、proto 或 OpenAPI，犹豫是否生成、升级或发布 SDK；跨仓产物顺序不明 | `moe-development` 的协议与依赖判断 | 先判断实际契约和消费者需要，再进入相应经验；不能由“前后端都有改动”直接推出发包 |
| 记得某次历史取舍或客户原话，但不知道在哪条讨论；实现与决策似乎矛盾 | `moe-business-context` | 这是业务证据与来源关联问题，需要定位决策和实现证据，不应只在开发操作手册中找答案 |
| 开发中准备或切换 T2 商家 Web、Client Portal/Report Card、OBC 或 iOS/Android 现场；Host/API 分流、客户身份或原生环境切换不明 | `moe-acceptance` 的对应平台指引；凭据操作再沿其入口使用 `moe-mis` | 平台知识归属验收，不能将商家桥接、身份或 CSR 路径套到其他端；只借当前所需准备与恢复知识，不启动完整验收 |
| 本地页面能打开、HMR 有提示，却不确定实际消费了哪个 worktree、模块或构建 | `moe-acceptance` 的差异修复与局部复验指引 | 有实际消费入口与代码来源的核验方法；页面存活、静态 import 或源码中有模块只能提供部分证据，开发调试也需要这份判断 |
| 从日志 service 反查仓库，或把关联 PR/仓库名对应到 Grey 服务分支时名称不一致 | `datadog` 的服务到仓库映射；`moe-grey` 的 service ID 与 UI 仓库名映射 | 两套命名映射服务不同系统；按手中标识选择原表并核对当前对象，不能把日志 service、GitHub repo 和 Grey key 当成同名 |
| 客户说 Grooming Report / Report Card 短信或邮件没收到，想核对近期发送或回复证据 | `datadog` 的 Grooming Report 发送排查指引 | 通知来源和发送/回复线索不在报告页面验收知识内；按对应日志路径取证，区分系统发送与客户实际收到，不能由镜像缺记录直接判断未发送 |

未覆盖的线索先结合 catalog 中的能力描述选择候选，再按该 skill 的发现方式定向读取。候选不适用时补选，条件已覆盖时停止；没有可用知识则保留缺口，不把泛化猜测写成已有经验。
