# @moego/* npm 包速查

整理 4 个前端仓库 package.json 里出现过的所有 `@moego/*` 包，以及来源 / 用途 / 升级方式。

## 1. 协议 / SDK 系列（最重要）

| 包 | 用途 | 来源仓库 | 升级方式 |
|---|---|---|---|
| `@moego/api-web` | gRPC client（web），按 proto 生成 | `moego-api-definitions` | `pnpm update:web <dist-tag>` |
| `@moego/api-web-v2` | gRPC client v2（基于 `@connectrpc/connect`） | 同上 | 同上（v2 codegen） |
| `@moego/api-node` | gRPC client（Node） | 同上 | moego-bff 用，catalogs 锁定 |
| `@moego/api-node-v2` | gRPC client v2（Node，基于 connectrpc） | 同上 | moego-bff 用 |
| `@moego/bff-openapi` | moego-bff REST 接口的 TS client（zodios，vite build） | `moego-bff/packages/openapi/` | `pnpm update:bff <dist-tag>` |
| `@moego/bff-schemas` | moego-bff 内部用的 zod schema，前端共用（裸源码发布） | `moego-bff/packages/schemas/` | 同上（多数前端没单独引，schemas 通过 bff-openapi 间接消费） |
| `@moego/legacy-api` | 老 Java svc REST client（openapi2dts 生成产物） | `moego-bff/packages/legacy-api/` | moego-bff 跑 `pnpm generate:legacy-api` |
| `@moego/openapi2dts` | CLI 工具：从 runtime OpenAPI 拉 → 生成 TS dts | ⚠️ TODO（独立仓库） | 各前端 `pnpm openapi` 命令调它 |

详见 SKILL.md §2 / api-web-publish-cheatsheet.md / bff-openapi-publish-cheatsheet.md / legacy-svc-codegen.md。

## 2. 基建 / 工具系列

| 包 | 用途 | 哪些仓库用 |
|---|---|---|
| `@moego/http-client` | HTTP 客户端封装（基于 axios）；请求层入口 | Boarding / mobile / OB-client-web |
| `@moego/business-tools` | 业务工具函数（时间 / 货币 / 单位 / 业务常量） | Boarding / mobile / OB-client-web |
| `@moego/tools` | 通用工具 | Boarding / mobile |
| `@moego/tools-cli` | 工具 CLI | Boarding / mobile（devDep） |
| `@moego/eslint-plugin-moego-fe` | 公司 ESLint 插件 | Boarding / mobile / OB-client-web（devDep） |
| `@moego/design-tokens` | 设计 token | Boarding / mobile |
| `@moego/expo-bundle-cli` | Expo OTA 发布 CLI | mobile |
| `@moego/pagespy` | 远程调试（移动 / 嵌入网页） | Boarding |
| `@moego/reporting` | 埋点 / 数据上报 | Boarding |
| `@moego/workflow` | 工作流引擎前端组件 | Boarding |
| `@moego/email-pro` | 邮件编辑器 | Boarding |
| `@moego/call-center` | 客服呼叫中心 | Boarding |
| `@moego/voice-react-native-sdk` | RN 语音 SDK | mobile |
| `@moego/react-native-logger` | RN 日志（workspace:* 子包） | mobile |
| `@moego/react-native-traceroute` | RN 网络追踪（workspace:* 子包） | mobile |

## 3. UI / 组件系列

| 包 | 用途 | 哪些仓库用 |
|---|---|---|
| `@moego/ui` | 底层 UI 组件（Boarding 专用，0.485.x） | Boarding |
| `@moego/business-components` | 业务通用组件（PC） | Boarding |
| `@moego/fn-components` | 函数式组件 | Boarding |
| `@moego/icons-react` | 图标组件（React，PC） | Boarding / OB-client-web |
| `@moego/icons-react-native` | 图标组件（React Native） | mobile |

## 4. Query / 状态管理

| 包 | 用途 | 哪些仓库用 |
|---|---|---|
| `@moego/query-v4-kit` | React Query v4 封装 | Boarding / mobile |
| `@moego/query-v5-kit` | React Query v5 封装 | OB-client-web |
| `@moego/query-kit` | 兼容（旧名） | OB-client-web |

## 5. Finance 系列

整组联动升级：`update:finance` / `update-finance-packages.sh`。

| 包 | 用途 | 哪些仓库用 |
|---|---|---|
| `@moego/finance-assets` | 资源（图片 / 静态） | Boarding / mobile |
| `@moego/finance-plugins` | 插件 | Boarding / mobile / OB-client-web |
| `@moego/finance-ui` | UI 组件（web） | Boarding / OB-client-web |
| `@moego/finance-ui-rn` | UI 组件（RN） | mobile |
| `@moego/finance-utils` | 工具 | 三方都用 |
| `@moego/finance-terminal` | 终端集成（web） | Boarding |
| `@moego/finance-terminal-rn` | 终端集成（RN） | mobile |
| `@moego/finance-web-kit` | web 整套 | Boarding |
| `@moego/finance-business-app-kit` | 商家 App 套件 | mobile |
| `@moego/finance-general-kit` | 通用套件 | OB-client-web |

## 6. C 端 OB Web 专属：`@moego/client-lib-*` 系列

`moego-online-booking-client-web` 走另一套体系，由 `pnpm install:lib` 管理；版本号是日期时间戳格式（如 `3.24121855045.1`），所有 `client-lib-*` 包同一组版本。

| 包 | 推断用途 |
|---|---|
| `@moego/client-lib-cli` | 配套 CLI（含 `moe build` SSR 构建） |
| `@moego/client-lib-components` | 通用组件（C 端） |
| `@moego/client-lib-widgets` | widgets |
| `@moego/client-lib-jotai` | jotai 封装 |
| `@moego/client-lib-http` | HTTP 封装 |
| `@moego/client-lib-hooks` | hooks |
| `@moego/client-lib-styles` | 样式 |
| `@moego/client-lib-utils` | 工具 |
| `@moego/client-lib-types` | 类型 |
| `@moego/client-lib-router` | 路由 |
| `@moego/client-lib-plugins` | 插件 |
| `@moego/client-lib-google-map` | Google 地图 |
| `@moego/client-lib-growthbook` | GrowthBook 实验 |

来源：独立 `moego-client-libs` 仓库（⚠️ TODO：未在本次调研范围内，需要时去 GitHub 找）。

## 7. 跨仓库出现表（哪些包在哪些前端仓库被引）

| 包 | Boarding_Desktop | moego-mobile | OB-client-web | OnlineBooking_Go_Web |
|---|---|---|---|---|
| api-web | 1.246xx | 1.235xx | 1.229xx | — |
| api-web-v2 | 1.249xx | 1.174xx | 1.174xx | — |
| bff-openapi | 0.1.451 | 0.1.428 | 0.1.412 | — |
| business-tools | 1.24.0 | 1.24.0 | 1.24.0 | — |
| http-client | 0.209.0 | 0.208.0 | ^0.208.0 | — |
| openapi2dts | 1.23.0 (dev) | ^1.35.0 (dev) | ^1.12.0 | — |
| business-components | 1.26.0 | — | — | — |
| @moego/ui | 0.485.2 | — | — | — |
| icons-react | ^3.5.0 | — | ^1.3.3 | — |
| icons-react-native | — | ^3.4.0 | — | — |
| query-v4-kit | 0.3.0 | ^0.2.0 | — | — |
| query-v5-kit | — | — | ^0.3.0 | — |
| finance-plugins | 1.0.86 | 1.0.81 | 1.0.55 | — |
| client-lib-* | — | — | 3.24121855045.1 | — |

**核心观察**：
- **OnlineBooking_Go_Web 完全不引 `@moego/*`**（老 Vue 项目独立运行）
- **Boarding + mobile 共享一套**（api-web / api-web-v2 / bff-openapi / business-tools / http-client / finance-* / query-v4-kit / openapi2dts / tools / tools-cli）
- **OB-client-web 走 `@moego/client-lib-*` 体系**，仅 bff-openapi / business-tools / http-client / finance-* 跟前两者共享
- **版本不齐很正常**——同一仓库内有联动需求的（如 `finance-*` 整组）保持对齐，跨仓库版本不要求一致

## 8. 何时升级哪个包

| 场景 | 升哪个 | 命令 |
|---|---|---|
| 后端 proto 加了字段 / 改了 schema | `@moego/api-web` (+ 可能 `api-web-v2`) | `pnpm update:web <dist-tag>` |
| moego-bff 改了 `server/routes/*` | `@moego/bff-openapi` | `pnpm update:bff <dist-tag>` |
| 老 Java svc 改了 Controller 字段 | 不升 npm，而是 `pnpm openapi` 重新生成 `src/openApi/*` | `pnpm openapi` |
| Finance 团队发了新版套件 | finance 整组 | `pnpm update:finance` |
| C 端 OB 联调 client-libs feature 分支 | `@moego/client-lib-*` 整组 | `pnpm install:lib --branch <branch>` |
| 升级公司 ESLint 规则 / 工具 | `@moego/eslint-plugin-moego-fe` / `@moego/tools` | 手动改 `package.json` + `pnpm install` |

## 9. NEVER 规则

- **不要混升 finance / client-lib 单包**——它们是整组同版本号联动，单升会导致内部 import 类型对不上。用 `update:finance` / `install:lib` 一次升一组
- **不要手改 `src/openApi/`（Boarding）/ `src/types/openApi/`（mobile, OB-client-web）/ `vendor/swagger*.ts`（OB-Go-Web）**——都是 codegen 产物
- **不要直接 npm install 全局 `npm-local` 之外的 registry 拉 `@moego/*`**——必须经过 `nexus.devops.moego.pet`，否则要么 404、要么拉到外网同名包
- **不要假设 `@moego/<X>` 一定能在公网搜到**——多数包是公司内部，只在 nexus 上
