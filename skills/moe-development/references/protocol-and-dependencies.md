# 协议与依赖判断

只在接口契约、接口生成 SDK/codegen 产物或实际跨仓依赖时读取。普通第三方 SDK 接入遵循目标仓库与对应专业 skill；只有同时涉及上述条件时才展开本文。具体仓库、命令和案例通过经验 skill 定向查找，当前代码、配置与产物决定实际路径。

## 先确定依赖与产物

写清当前任务的真实链路：协议源 → 字段生产者 → 聚合/BFF → 消费者 → 部署或发布产物。不存在的层省略，不按固定仓库名单补齐；对真实依赖确认提供方、消费者、需要的接口/产物与何时可验证。

回答：schema 是否变化；唯一协议源在哪；消费者通过 npm SDK、仓内生成代码还是已有 Struct 能力拿字段；是否确实需要尚未发布的产物。最后一项为是才进入 feature 包发布。

| 类型 | 判断与验证 |
|---|---|
| 显式 gRPC proto | 沿生成与依赖配置定位 SoT；可能在 api-definitions 或大仓等实际协议位置。核对字段号、兼容性和消费者需要的产物，不假定所有 proto 来自一个仓库 |
| 已有 `google.protobuf.Struct` 增加 key | key 本身不改变 proto schema，不产生新的生成字段；先验证当前 SDK 的 Struct/Value 访问能力。只有另有显式协议变化、缺少基础能力或明确未发布产物依赖时才升级 SDK |
| Node BFF OpenAPI | 找实际 route/zod schema 和发布 CI；需要消费者新类型时核验对应包实物，不把 Java BFF 与 Node BFF 混同 |
| legacy runtime OpenAPI | 确认 schema 是否变化、生成器实际读取的文档 URL 与目标环境；文档源包含所需契约后，消费仓生成并核对 diff。文档可能经过聚合/构建，不能只看服务部署；再按实际依赖区分仓内生成文件与对外包分发 |

## 包发布与跨仓推进

确需新包时查经验 `MDEV-API-WEB-PUBLISH` 或 `MDEV-BFF-PUBLISH`；runtime codegen 查 `MDEV-LEGACY-CODEGEN`；消费版本与升级方法不明时查 `MDEV-NPM-PACKAGES`。通过当前 skill catalog 定位经验库，不假设相邻安装。

发布动作前核对目标仓库当前 hook、CI 分支规则、dist-tag 和触发方式。hook 接受的分支未必能够发包或部署，历史 `feature-*`/`bugfix-*` 规则不能跨仓类推；同名分支只有实际路由或消费依赖要求时才约束。

同名 feature 已部署，不证明消费者安装了新包；包已升级，也不证明请求命中了新后端。分别核对 registry 与消费者实际版本、BFF/下游运行镜像和每跳路由上下文，按下表保留对应证据。

不为“前后端都改了”创建空 commit、改 proto 注释或升级包。确有未发布产物依赖且当前 CI 需要触发时，按已有授权和 Git owner skill 执行最小必要动作。

编码可以按已知契约并行，联调和交付服从实际依赖。需要上游产物的消费者，在产物可用并验证后再进入依赖它的步骤；兼容与破坏性变化的部署顺序分别判断，不按仓库名称固定排队。Git、PR 与合并操作交给 `github-workflow`。

## 临时依赖切换与收尾

确定本次 feature 包、workspace/link 或临时配置中哪些需要替换，以及正式产物是否包含同一契约。把 feature tag 改成 latest 文本，不等于临时依赖已消除。

切换后核对真实 version、lockfile、安装内容和实际解析路径；再用同一对象、身份与目标环境复验调用结果。包解析与升级方法见经验 `MDEV-NPM-PACKAGES`。PR 关联应说明尚未满足的依赖条件，不能用流水线绿色替代产物与运行验证。

## 逐层证据

| 涉及的层 | 可观察证据 |
|---|---|
| 协议 | schema/codegen diff、字段兼容性与字段号 |
| npm 产物 | 真实 publish step、registry version 和安装实物 |
| 业务服务 | 风险匹配测试，以及任务需要的目标环境响应 |
| 聚合/BFF | mapper/enricher/route 验证和实际输出 |
| runtime codegen | 同一环境的 OpenAPI JSON 与消费仓生成 diff |
| 前端 | 依赖/lockfile、类型或定向测试、缺失值处理与实际交互/请求 |
| 合并衔接 | PR 的真实依赖；消费者所需主线产物存在；临时依赖已按交付要求处理 |

某层失败时定位该层，不盲目重发所有仓库，也不宣称该链路完成。汇报用实际依赖、产物判断、验证结果与缺口，不要求简单任务填完整多层模板。
