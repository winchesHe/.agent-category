# 开发经验索引

按当前任务的仓库、目标或症状选主题，再读相关章节。经验帮助选择操作；具体适用条件见正文，当前参数与运行状态从目标仓库和环境核对。

| ID | 正文 | 何时读取 |
|---|---|---|
| `MDEV-REPO-NAVIGATION` | [仓库导航](repo-navigation.md) | 仓库/模块归属有缺口；从实际请求、大仓应用、共享包或 Agent、MIS、CI/部署线索反查源码，已定位时不读 |
| `MDEV-BACKEND-DEV` | [Java 与 Node BFF 开发](backend-dev-flow.md) | Java/BFF 仓库指南入口、api-v3 Spotless 特殊失败、下游上下文与错误处理；实际 RPC 调用转 gRPC 专题 |
| `MDEV-NEW-SERVICE` | [Go 大仓应用运行与新增服务](backend-service-handbook.md) | 已有应用构建或本地启动，读[已有应用：构建与本地运行](backend-service-handbook.md#已有应用构建与本地运行)；新增应用/RPC 服务读入口、脚手架与注册配置；部署/Grey 异常读部署章节。仅在对应改动或症状出现时扩展 |
| `MDEV-FRONTEND-DEV` | [前端开发](frontend-dev-flow.md) | 仓库指南入口、组件/query/状态复用、前端特有故障或请求—缓存—交互验证的方法有缺口时 |
| `MDEV-API-WEB-PUBLISH` | [gRPC 协议包发布](api-web-publish-cheatsheet.md) | api-web/api-node 及 v2 确需新产物，或 tag、发布筛选、包内容不符 |
| `MDEV-BFF-PUBLISH` | [BFF 包生成与发布](bff-openapi-publish-cheatsheet.md) | 消费者需要变化后的 client/schema，或发布范围、catalog 依赖与包内容不符 |
| `MDEV-LEGACY-CODEGEN` | [Legacy OpenAPI 生成](legacy-svc-codegen.md) | 消费者确需新 runtime 类型，或文档 URL、抓取与生成 diff 不符；仅 Controller 内部改动不触发 |
| `MDEV-NPM-PACKAGES` | [npm 依赖](npm-dependencies.md) | 包源码归属、v1/v2、workspace/catalog/link、依赖声明与升级、安装 404 或实际消费版本不符 |
| `MDEV-DEBUGGING` | [联调与排障](debugging-and-observability.md) | 字段缺失、请求失败、白屏、环境/flag/数据不一致 |
| `MDEV-GIT-CI` | [Git 与 CI 排查](commit-and-review-conventions.md) | hook/分支校验失败、CI 产物与部署不一致，或自动化实际作用范围不明 |
| `MDEV-KAFKA-DEBUGGING` | [Kafka 开发与平台排查](kafka-debugging.md) | Producer/Consumer 接入、平台地址、Topic/消息/消费组操作；路由、offset/lag 与重试 |
| `MDEV-BUSINESS-LOGGING` | [业务日志开发与排障](business-chain-logging.md) | 复用 logger、新增事件与关联字段、日志查询（T2 Pod 日志交给 `moe-t2-k8s`）、持久化失败、SQL 日志正文保护 |
| `MDEV-GRPC-DEBUGGING` | [本地 gRPC 调试](local-grpc-debugging.md) | Kubernetes 入口选择（T2 使用 `moe-t2-k8s`）、Pod 转发、descriptor、网格与应用 metadata、方法与下游结果对照 |
| `MDEV-DATABASE-DEBUGGING` | [数据库与 Redis 调试](database-debugging.md) | 按环境选择数据库入口；T2 直接操作交专业 skill，实例落点、业务状态、Redis Key/TTL、测试隔离或迁移结果有缺口 |
