# BFF 包生成与发布

- ID：`MDEV-BFF-PUBLISH`
- 适用：moego-bff 导出 client/schema 的生成与发布，或消费包版本、依赖和内容不符。

## 先确定消费者需要什么

| 对象 | 何时进入此流程 |
|---|---|
| `@moego/bff-openapi` | route 的客户端契约发生变化，消费者需要新生成的 client；仅改 handler 内部逻辑不构成升级依据 |
| `@moego/bff-schemas` | 消费者需要变化后的导出 schema；先查是直接消费，还是经其他包间接消费 |
| `@moego/legacy-api` | runtime OpenAPI 生成后，当前消费者需要变化内容；先按[legacy codegen](legacy-svc-codegen.md)区分仓内 workspace 消费与对外发布 |

开发与生成用法先读 `moego-bff/README.md` 和当前 `package.json`。不因三个包同在仓库就要求全部升级，也不因存在 package.json 就断言每个包都有相同的发布流程。

## CI 中的判断入口

| 入口 | 要核对什么 |
|---|---|
| `ci/build.sh` | 实际调用哪些版本计算、生成和发布步骤 |
| `ci/calc-version.sh` | 当前分支如何生成 VERSION、TAG、SHOULD_PUBLISH |
| `ci/build-publish-openapi.sh` | 生成 client、构建及实际发布范围；递归发布要检查当次 workspace 选择，不能仅凭脚本名推断只发一个包 |
| `ci/build-publish-schemas.sh` | schema 包版本、导出与依赖转换 |
| `ci/generate-legacy-api.sh` | runtime 类型生成；生成成功不代表已经完成某个 npm 发布 |

当前 `calc-version.sh` 为 `main` 设置 latest，为 `feature-<topic>` / `bugfix-<topic>` 设置 topic tag；其他分支保持 `SHOULD_PUBLISH=false`，包括 `production`。这与协议仓的发布脚本不同；分支通过 hook 不代表能够发包。

SHOULD_PUBLISH 为 false 时，publish 脚本可能以 0 退出。查缺失产物要读具体步骤及计算结果，不以 CI 绿色作为已发布证据。

## BFF 特有的包依赖检查

BFF 使用 catalog / workspace 管理部分依赖，选择和锁定机制见[npm 依赖](npm-dependencies.md)。当前 openapi、schemas 发布脚本会读取根 lockfile，将部分 `catalog:api` 声明转成已解析版本，发布后再恢复源码中的声明。

因此，发布后查看源码 package.json 不足以证明发布内容。需要核对实际包的：

- version、导出文件及消费者需要的方法/schema；
- api-node 与 api-node-v2 等依赖是否对应本次生成所使用的版本；
- workspace/catalog 声明是否按发布工具正确转换，消费者能否解析。

不要为消除源码中的 catalog 声明，手工把工作区全部改成固定版本。

## 查询与消费

按[npm 依赖](npm-dependencies.md#依赖声明与升级)查询准确的 bff-openapi、bff-schemas 或其他实际消费包。排除 registry、认证和 tag 错误后，仍缺产物时回到上面的发布范围与步骤核对；不把生成、部署和发包视为同一步。

需要新产物时通过 `github-workflow` 检查当前触发入口并按既有授权操作。核对发布实物后，按 npm 依赖专题处理消费仓声明、lockfile 与 catalog，再验证真实消费行为。
