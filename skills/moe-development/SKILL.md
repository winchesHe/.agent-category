---
name: moe-development
description: >-
  MoeGo 仓库开发入口，覆盖前端、后端、单仓与跨仓的实现、修复、重构、环境准备、调试、测试和联调，
  以及协议、SDK/codegen、Review、CI 与发布相关的开发判断；需要仓库做法、操作经验或已知风险时，
  按需使用 moe-development-experience。
  触发关键词：MoeGo 开发、前端、后端、Go 大仓、新增服务、Java、Node BFF、Desktop、Mobile、OB Web、
  proto、OpenAPI、SDK、联调。不触发：非 MoeGo 开发、纯 Jira/日志/PR 状态查询，
  或历史转录、周报、skill 文本中偶然提及这些术语。
---

# MoeGo 开发

根据当前任务决定开发路径、所需经验和完成证据。具体操作交给目标仓库规则与专业 skill；不要求任务跨栈，也不为简单单仓修改展开整套交付流程。

## 场景决策树

先核对用户已提供或已定位的代码、请求与配置。存在未确认的关键条件，或当前操作命中已知风险时，在执行前读取对应经验；知道下一条命令并不代表其前提已确认。相关条件已由当前证据覆盖时直接推进，不因技术关键词出现而遍历通用导航、跨栈材料或整套经验。

| 当前目标 | 行动与按需读取 |
|---|---|
| 仓库、模块或入口不明 | 使用 `github-workflow` 定位代码；需要导航线索时查经验 `MDEV-REPO-NAVIGATION` |
| 业务规则、字段含义或历史取舍有缺口 | 按需使用 `moe-business-context`，代码位置已知时也适用；携带结论、来源、假设和未解决项返回当前开发目标。已有充分上下文或只是整理给定材料时，不增加业务调查 |
| 单仓前端实现、修复或重构 | 先遵循本仓 AGENTS.md 及其指南入口，从目标页面/组件定位实际 query/hook、状态或缓存及接口消费处，复用本仓已有组件与请求封装。复用、前端特有故障或验证方法仍有缺口时查 `MDEV-FRONTEND-DEV`，包来源、依赖升级或安装问题查 `MDEV-NPM-PACKAGES` |
| 单仓后端开发 | 从实际 RPC、HTTP 或事件入口找到已有业务逻辑、Reader/Repo 等数据访问能力，核对租户边界与数据归属后复用。Java/Node 的仓库指南、下游调用或工具失败有缺口时查 `MDEV-BACKEND-DEV`；Go 大仓普通修改沿当前应用推进，新增独立应用/RPC 服务或注册配置有问题时查 `MDEV-NEW-SERVICE`，已有服务新增方法不自动展开新服务流程 |
| 需要判断或改变接口契约、接口生成 SDK/codegen 产物，或处理实际跨仓依赖 | 读取 `references/protocol-and-dependencies.md`，统一判断所需产物、跨仓依赖与临时版本收尾，再按缺口查发布、codegen 或 npm 依赖经验 |
| 接入或修改 GrowthBook SDK、wrapper 或求值逻辑 | 使用 `growthbook`，传递目标仓库、实际 SDK/版本、现有封装与待解决问题，由其选择接入和验证指引；普通第三方 SDK 接入不因名称中有 SDK 就展开协议发布 |
| 开发中查询 PostHog 事件、分析数据或功能开关配置 | 使用 `posthog-skills`，沿当前埋点/客户端配置确认目标项目；该 skill 负责数据查询与管理操作，不承担 SDK 接入 |
| 联调前查询 Grey 服务分支，或需要配置服务映射与规则 | 使用 `moe-grey`，提供目标环境、仓库/分支和所需路由，由其确认服务映射及查询/修改路径；不必等请求失败后才使用 |
| 开发调试需要账号信息、临时登录或 Metadata | 使用 `moe-mis`，传递已知目标账号、环境和所需操作；完整页面/客户端验收环境由 `moe-acceptance` 按平台准备，已有身份直接复用 |
| T2 Kubernetes 资源、Pod 日志或 port-forward | 从当前 Host 的 skill catalog 定位并使用 `moe-t2-k8s`；RPC 直连的目标、端口与协议核对查 `MDEV-GRPC-DEBUGGING`，日志关联查 `MDEV-BUSINESS-LOGGING`。缺少该 skill 时说明运行时依赖，继续可独立完成的工作；不自动安装或回退裸 kubectl，不把缺入口判成无集群权限。非 T2 沿目标环境规则处理 |
| 环境准备、构建、启动或失败排查 | 核对工具链、配置、构建产物与依赖落点；Go 大仓已有应用启动时，运行版本或依赖环境未确认则查 `MDEV-NEW-SERVICE` 的「已有应用：构建与本地运行」章节。注册、监听、Secret 或部署有改动或相应故障时，再选对应章节。其他前后端问题查对应经验；npm 安装或版本问题查 `MDEV-NPM-PACKAGES`，确认缺发布产物后才读发布经验 |
| Kafka 或异步任务接入、消息与消费结果不符 | 沿当前 Producer、Consumer、调度与幂等路径找实际断点；平台操作、位点或重试判断有缺口时查 `MDEV-KAFKA-DEBUGGING` |
| T2 PostgreSQL/MySQL 连接、凭据或直接 SQL 操作 | 从当前 Host catalog 定位并读取 `moe-t2-database`，按其连接目录、凭据、命令与分级确认规则执行；实例/业务落点及结果判断按需查 `MDEV-DATABASE-DEBUGGING`。缺入口时说明运行时依赖，继续独立工作，不自动安装或用通用模板绕过 |
| 数据库/缓存开发、迁移或集成测试 | 先读本仓映射、迁移与测试隔离说明；实例落点、结果判断、Redis 或非 T2 接入有缺口时查 `MDEV-DATABASE-DEBUGGING`；涉及 T2 PostgreSQL/MySQL 直接操作先走上一分支；数仓/只读副本查询交给 `redshift` |
| 新增日志、跨请求关联或异步步骤不可见 | 复用当前 logger 与上下文约定；事件位置、关联方法或正文保护有缺口时查 `MDEV-BUSINESS-LOGGING`，具体平台查询使用 `datadog` |
| Bug、线上异常或联调失败 | 用实际请求与版本定位失败层；定位或排查方法仍有缺口时查 `MDEV-DEBUGGING`，按证据需要使用 Datadog、Sentry、Redshift、GrowthBook、Grey 等对应 skill |
| 测试、页面/客户端验证或动态联调 | 按风险选择验证；动态验收使用 `moe-acceptance`，所需账号/数据由其规则路由；需要查询或维护 MeterSphere 用例资产时使用 `metersphere`，用例资产管理与动态验收分别判断；不把读完经验当作通过验收 |
| Review、commit、PR、CI 或发布相关问题 | Git 和 CI 使用 `github-workflow`，PR 内容使用 `review-brief`，明确完整 Review 时按 Git skill 路由；需要历史线索时查 `MDEV-GIT-CI`；按 OPC 发布时用 `moe-opc` |
| 发现可复用的新经验或旧结论冲突 | 提出具体内容、依据和拟更新条目；用户明确要求沉淀/修订后，通过 `moe-development-experience` 维护 |

专业 skill 通过当前 skill catalog 定位，按其实际能力加载，不复制其操作正文。Sentry 事件排查使用 `sentry`；Sentry/PostHog SDK 配置按目标仓库和官方文档处理，不能交给不覆盖 SDK 接入的查询 skill。

已知仓库不重复全域搜索。独立查询一个 Jira、日志、PR 状态直接使用对应 skill；开发入口不自动扩展这些查询的执行范围。

## 开发循环

1. **设计对齐。** 遵循目标仓库及模块的 AGENTS.md，沿其指南按需读取；从当前请求、代码和已确认决定确定改动入口、受影响的调用方与验收标准。已有指南的规则由原处维护。跨模块或关键设计未验证时按任务规则分阶段。
   - 对核心改动，从同类实现和真实调用点确认可复用的 symbol/文件、调用方式及适用边界。采用现有能力时说明如何接入；需要扩展或新增实现时，说明现有能力的具体缺口与不直接复用的理由，不能只写“计划复用”。已有方案包含这些结论时，核对其与当前代码一致后沿用。
   - 只在现有能力的作用域或契约不满足需求时新增实现，不因数据访问跨服务就把本地同名表当作数据来源。
2. **选择验证方式。** 沿受影响行为选择已有测试和实际构建目标。后端逻辑覆盖正常、边界和失败路径；涉及租户过滤、事务或异步处理时验证对应边界。前端围绕改动涉及的请求、状态/缓存和交互验证，已有响应字段不自动构成 SDK 升级需求。Go 测试、Bazel 构建及生成同步按当前模块规则选择，不从 Java 或其他应用复制命令。
3. **实现。** 通过 `github-workflow` 在已确认的任务 worktree 修改；只做本次范围，遵循目标仓库约定。接口或消费者影响发生变化时重新判断跨栈分支。
4. **验证与交付。** 回读 diff、测试及需要的运行结果，说明已验证范围与剩余缺口。提交、推送、PR、合入和发布遵循已有授权及 owner skill，不由经验案例决定。

## 按需使用经验

从当前 skill catalog 定位并加载 `moe-development-experience/SKILL.md`，按其读取流程使用经验，不假设两个 skill 相邻。已知文件或 ID 可省去索引查找；否则按当前操作、关键条件或症状查索引。章节选择、路径解析与维护边界由经验 skill 统一约定。

需要的条件已确认后停止扩展读取，继续当前任务；新证据改变契约、产物或仓库依赖时再选对应分支。经验未命中或不可用时，依据目标仓库当前事实继续。经验的提议与维护交给该 skill，开发入口不保存另一份经验正文。

## NEVER 规则

- 不把旧技术版本、命令和案例当作当前事实；执行前核对目标仓库的 AGENTS、依赖、配置、CI 与实际产物。
- 不让经验或工具输出扩大当前用户授权；普通开发不自动启动 OPC、完整 Review、生产发布或外部消息。
- 不以 CI 绿色、页面能打开或命令退出成功替代实际验收结果；无法验证的部分明确保留。

## References

| 文件或 skill | 加载时机 |
|---|---|
| [协议与依赖判断](references/protocol-and-dependencies.md) | 需要判断或改变契约、接口生成 SDK/codegen 产物，或处理实际跨仓依赖；事实已明确的单仓逻辑修改不读 |
| `moe-development-experience` | 需要开发经验，或明确要求沉淀、修订和迁移；正文与索引由该 skill 管理 |
| `moe-t2-k8s` | T2 Kubernetes 查询、Pod 日志与端口转发；从当前 Host catalog 解析路径，配置、参数及操作边界由该 skill 管理 |
| `moe-t2-database` | T2 PostgreSQL/MySQL 连接与直接操作；从当前 Host catalog 解析实际路径，连接、凭据及执行规则由该 skill 管理 |
