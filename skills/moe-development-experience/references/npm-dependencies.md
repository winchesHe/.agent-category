# npm 包来源、依赖升级与排查

- ID：`MDEV-NPM-PACKAGES`
- 适用：MoeGo 前端、Node BFF 等消费仓的包源码归属、版本解析、workspace/catalog/link、依赖升级或安装失败。

## 从实际消费入口反查

先看目标代码的 import、对应 package.json、lockfile 和 workspace/catalog 配置，区分包名、版本与本地包路径：

1. workspace 或本地依赖沿真实路径找源码、构建输出与 exports，不能因为使用公司包名就去找独立仓库。
2. registry 包先看已安装包内容及 name、repository、homepage、exports 与 dependencies。来源不明时通过 `github-workflow` 搜索包名与发布配置；元信息只是候选，包定义和 publish 配置确认归属。
3. 生成代码继续追生成器输入、脚本、协议源或 runtime OpenAPI URL。找到发布仓库不代表本次需要发包；是否改变契约或产物由 `moe-development` 的《协议与依赖判断》确定。

共享组件、client-libs、finance 等仓库线索见[仓库导航](repo-navigation.md)。组件选用、开发链接和包组维护规则按对应共享仓 README 读取；不在这里复制各仓依赖清单或版本快照。

## 容易混淆的协议包来源

| 包 | 源码 / 产物入口 | 消费判断 |
|---|---|---|
| `@moego/api-web`、`@moego/api-node` | moego-api-definitions；`templates/web`、`templates/node` 的 package.json | 沿实际 import 找协议；不能据包名推断也包含 Go 大仓的新定义 |
| `@moego/api-web-v2`、`@moego/api-node-v2` | moego Go 大仓；`template/ts/web`、`template/ts/node` 的 package.json | 与不带 v2 的包可能同时被消费；不是改个包名就能互换 |
| `@moego/bff-openapi` | moego-bff 的 `packages/openapi/` | Node BFF 导出的 client；不是所有名为 BFF 的服务都由它定义 |
| `@moego/bff-schemas` | moego-bff 的 `packages/schemas/` | 共享 schema；核对消费者是直接依赖还是经其他包消费 |
| `@moego/legacy-api` | moego-bff 的 `packages/legacy-api/` | runtime OpenAPI 生成内容；核对本次走 workspace 还是对外分发 |
| `@moego/openapi2dts` | 消费仓实际安装的生成工具 | 先读该版本 README / 帮助；旧 OB 另有本仓 swagger 脚本，不能互套参数 |

遇到新包或映射变化时，以当前包元数据、生成配置和发布脚本确认来源，不把上表当成全量包目录。

## 版本声明、解析与源码是三件事

| 声明 / 现象 | 核对方法 |
|---|---|
| 普通 version 或 dist-tag | 对照 registry 解析结果、lockfile 与实际安装版本；声明变化不证明运行中的消费者已加载 |
| `catalog:api` 等 catalog 引用 | 继续读 `pnpm-workspace.yaml` 的 catalog 和 lockfile；只改根 package.json 可能未改变实际选择 |
| `workspace:*` | 找 workspace 的实际包目录与导出，不能把版本号查询结果当作本仓加载来源 |
| 本地 link 与已发布包不一致 | 检查解析到的真实路径、构建输出和 exports；共享仓修改不等于应用已消费 |
| 同包存在多个解析版本 | 查当前调用点解析到哪一个、由哪条依赖链引入，不只看根依赖声明 |

## 依赖声明与升级

依赖值不要写成 `"<dist-tag>@latest"`。dist-tag 可以单独作为包选择器；需要固定本次联调版本时，先查询它实际指向的 version。registry 从消费仓 scope 配置与包的 publishConfig 核对；以下使用常用 Nexus，以 api-web 为例，其他包替换为已确认的准确包名：

```bash
npm view "@moego/api-web@<dist-tag>" version \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/
npm view @moego/api-web dist-tags --json \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/
```

将返回的真实 version 用于消费仓依赖声明，再用本仓包管理器更新 lockfile。分支有新提交不代表 dist-tag 已更新；升级脚本可能只是按 tag 安装，不能以退出成功推断已精确锁定。按上一节核对声明、解析版本、安装内容和实际调用点。

### 消费仓升级入口

下面只用于定位已有能力；执行前读当前 package.json 和对应脚本，核对参数与作用范围。只升级当前消费链需要的包，包组联动由实际依赖与本仓脚本决定。

| 消费仓 / 目标 | 操作入口与边界 |
|---|---|
| Boarding_Desktop、moego-mobile 的 api-web / bff-openapi | 各仓 `update:web`、`update:bff` 与 `scripts/update-packages.sh`；按当前脚本传入 dist-tag，不把完整 version 当成 tag 参数 |
| moego-online-booking-client-web 的 client-libs | `install:lib` 用于这一组共享包；不能代替所有 SDK 或直接依赖升级 |
| moego-bff 的协议依赖 | `scripts/update-api.ts` 按包和目标分支选择，可按当前帮助使用非交互参数；可能继续执行生成步骤，回读实际依赖与生成结果，不把 catalog 中的 latest 当作已锁定版本 |

需要 runtime 类型生成时按实际消费仓读[legacy codegen](legacy-svc-codegen.md)，不把生成仓内类型当作安装 npm SDK。升级后的验证沿真实消费者进行；前端的请求、缓存与交互验证见[前端开发](frontend-dev-flow.md#5-请求状态与交互怎样验证)，Node BFF 则核对对应调用或生成结果。

## 安装或升级结果不符

| 现象 | 检查与下一步 |
|---|---|
| 查询或安装 404 | scope registry 与认证 → 准确包名/tag → 实际发布源；不回显认证配置或直接改用 latest，确认缺产物后再读对应发布专题 |
| 脚本成功但仍是旧版本 | registry 的 tag、lockfile、实际解析版本和运行中的消费者；脚本退出成功不证明这几处已同步 |
| 新字段仍不可用 | 该 version 的导出内容、当前调用点的包与协议来源；包实物缺少所需内容时查对应生成/发布源 |
| 本地共享仓已修改，消费端没变化 | 实际 link/workspace 路径、构建输出、exports 与使用位置；本地联动方法读共享仓 README |

查询成功只证明 registry 能解析目标版本；安装后仍需核对消费者实际使用的内容。当前接口和已安装产物足够时，无需为了升级而触发新发布。

## 按实际需求选择下一步

| 需要处理的内容 | 归属 |
|---|---|
| gRPC 包缺少所需协议，或 publish 被跳过 | [协议包发布](api-web-publish-cheatsheet.md) |
| BFF client/schema 导出或发布内容不符 | [BFF 生成与发布](bff-openapi-publish-cheatsheet.md) |
| runtime 文档到仓内类型 | [legacy codegen](legacy-svc-codegen.md) |
| 共享能力包组升级 | 实际共享仓 README、消费者脚本和包间依赖；有联动约束才成组处理 |

只处理本次消费者所需的依赖变化；是否需要新产物按 `moe-development` 的《协议与依赖判断》确定，不能从“后端改了”推出整组前端包都要升级。
