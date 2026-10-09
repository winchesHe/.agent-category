# Legacy runtime OpenAPI 类型生成

- ID：`MDEV-LEGACY-CODEGEN`
- 适用：消费方通过 runtime OpenAPI 或聚合 API 文档生成类型，且需要新契约或排查生成结果。

## 先分清源、生成位置和消费方式

从实际请求及生成脚本确认：服务暴露的 schema → 生成器实际读取的文档 URL → 输出文件 → 消费者。Controller 内部实现变化不一定改变 schema；已有响应与类型足够时无需生成。

前端可能直接提交仓内生成文件；BFF 的 `packages/legacy-api` 也可能被本仓通过 workspace 消费，或参与对外包分发。是否需要 npm 包由实际依赖决定，不能一概写成“legacy 不发包”或“全部都要发包”。

| 消费仓 | 生成入口线索 |
|---|---|
| Boarding_Desktop | 当前 `openapi` script 与 `src/openApi/` |
| moego-mobile、moego-online-booking-client-web | 各仓 `openapi` script 与 `src/types/openApi/` |
| moego-bff | `generate:legacy-api` → `ci/generate-legacy-api.sh` → `packages/legacy-api/src/generated/` |
| OnlineBooking_Go_Web | 本仓 `scripts/swagger2dts.js` 与 `swagger` script，分别处理 REST/RPC 输出 |

运行命令和输出目录以当前消费仓配置为准；不要套用别仓包管理器，也不要把 runtime 生成误认成 proto SDK 发布。

## 发现真实文档地址和参数

使用消费仓已安装的 `@moego/openapi2dts` README、`--help` 与实际脚本；必要时查工具源码中的 URL 构造。不要猜配置文件名、`--server` 参数或默认生产环境。

当前工具提供 `--prefix`、`--staging` 等选择方式，具体用法由其 README 维护。已核对版本的 URL 构造中：

- 默认使用 `api-docs.t2.moego.dev`，prefix 对应 Grey 文档入口，staging 对应另一文档环境。
- `openapi2dts` 读取 `/rest/v3/<module>.json`；旧 OB 的 `swagger2dts.js` 使用 `/rest/<module>.json`，RPC 又有自己的 URL。
- 这些是文档生成/聚合入口，不能直接当作业务 API host。以本次工具输出的准确 URL 与返回 JSON 为准。

服务自身的新 schema 已可见、生成器却仍拿到旧字段时，继续核对文档聚合或构建产物、环境与分支；不能仅凭服务部署成功认为所有文档源都更新了。

## 核对生成差异

1. 在准确 URL 的 JSON 中确认目标字段、类型、required、nullable 与实际响应语义。
2. 在消费仓任务 worktree 执行当前生成入口，检查抓取日志是否覆盖目标模块，再看生成 diff。
3. 对照源 JSON、生成器转换和消费者用法，解释字段名、可空性、枚举与数值类型差异；不直接靠修改后端注解来消除前端类型错误。
4. 按仓库规则提交应跟踪的生成文件及消费代码；临时调试 JSON、日志和环境配置不混入提交。

## 容易误判的结果

| 现象 | 下一步 |
|---|---|
| 命令成功、目标文件没变化 | 对照实际抓取 URL、目标模块是否抓取成功、源 JSON 与输出目录；旧输出仍存在不证明本次成功更新 |
| 服务字段存在，生成类型缺失 | 查文档聚合是否更新、字段映射和生成器转换；先找丢失环节 |
| nullable / optional 与预期不同 | 对照该版本 OpenAPI JSON、序列化结果和工具转换规则；不存在通用的“Swagger 默认 required”结论 |
| 大量无关 diff | 核对源环境、工具版本和格式化差异，区分语义变化；不无条件接受或整批丢弃 |
| BFF 生成脚本忽略 Biome 错误后退出成功 | 回读生成文件和后续类型/格式检查；`ci/generate-legacy-api.sh` 的错误过滤不证明产物可用 |

已核对的 openapi2dts 实现会捕获单模块抓取错误后继续处理其他模块；因此要核对目标模块是否出现在抓取结果，不能仅凭总退出码判断。具体行为仍以消费仓已安装版本为准。

完成判据是同一源 JSON、生成文件与实际消费语义一致。需要对外 BFF 包时继续[BFF 生成与发布](bff-openapi-publish-cheatsheet.md)；需要跨仓衔接时按当前 skill catalog 定位 `moe-development`，读取其 `references/protocol-and-dependencies.md`。
