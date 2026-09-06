# 前端开发流程（Boarding_Desktop / moego-mobile / OB Web）

适用于：在 4 个前端仓库里加功能、升 SDK、联调后端。

## 1. 4 个前端仓库共性 / 差异

| 维度 | Boarding_Desktop | moego-mobile | moego-online-booking-client-web | OnlineBooking_Go_Web |
|---|---|---|---|---|
| 端 | 商家 PC web | 商家 mobile RN | C 端 OB web（新） | C 端 OB web（老） |
| 技术栈 | React 17 + TS 5.8 | RN 0.77 + Expo 52 + TS | React 18 + TS | **Vue 2 + Nuxt 2** + TS |
| 构建 | rsbuild (rspack) | Expo / Metro | Vite 4 + 自研 SSR `moe build` | Nuxt 2 (webpack) |
| 包管理 | pnpm 10 | pnpm 8 | pnpm 8 | yarn 1 |
| 状态管理 | **amos** + RQ v4 | **Redux + thunk** + RQ v4 | **Jotai** + RQ v5 | Vuex 3 |
| 路由 | react-router v5 | React Navigation v6 | wouter（`src/routes.ts`） | Nuxt 文件路由 |
| UI 库 | antd 4 + `@moego/ui` + `@moego/business-components` | `@ant-design/react-native` 5 + `@moego/icons-react-native` | `@headlessui/react` + `@moego/client-lib-components` | ant-design-vue + vant |
| 请求层 | `@moego/http-client` + axios | `@moego/http-client` + axios | `@moego/http-client` + `@moego/client-lib-http` + axios | `@nuxtjs/axios` |
| 测试 | **Vitest 4** + RTL | Jest 29 + RTL native | Vitest 2 + RTL | Jest 26 + Vue Test Utils |
| commitlint header | ≤110 | ≤100 | ≤100 | ≤100 |
| AGENTS.md | ✅（CLAUDE/GEMINI/.clinerules 都 symlink 到 AGENTS.md） | ✅ | ✅（含 DESIGN.md） | ❌ ⚠️ |

## 2. Boarding_Desktop 工程结构

### 2.1 顶层 src

```
src/
├── assets/, components/, layout/, style/
├── config/, constant/, init/, prepare/
├── container/<Feature>/      # 业务页面（如 Account/SignIn/SignIn.tsx）
├── store/<domain>/           # amos store，按域分子目录
│   ├── <name>.actions.ts
│   ├── <name>.boxes.ts       # amos box
│   ├── <name>.selectors.ts
│   ├── <name>.types.ts
│   ├── <name>.utils.ts
│   └── __test__/
├── middleware/               # clients.ts（RPC 客户端封装入口）
├── openApi/                  # openapi2dts 生成产物（不要手改）
│   ├── business-schema.ts, customer-schema.ts, grooming-schema.ts,
│   ├── message-schema.ts, payment-schema.ts, retail-schema.ts
│   └── schema.ts             # 汇总
├── router/{routes.tsx, paths.ts, RouteRegistry.ts}
├── service/, query/          # API 封装层 / React Query hooks
├── sw/, telemetry/           # service worker / 埋点
├── tests/, types/, utils/
```

### 2.2 dev / 联调命令

```bash
pnpm install
pnpm dev                # 完整 dev（带 TS check）
pnpm dev:fast           # FAST_DEV=1，关 TS check 加速

pnpm build              # 全量构建
pnpm check:types        # tsc --noEmit
pnpm check:biome        # biome 格式 / lint
pnpm check:deps         # dpdm 检测循环依赖
pnpm test               # vitest run
pnpm test:changed       # 仅跑变更文件相关单测（scripts/run-changed-tests.mjs）

# 升级 @moego/* 系列 SDK
pnpm openapi            # 重新生成 src/openApi/*（拉老 Java svc）
sh ./scripts/update-packages.sh @moego/api-web <dist-tag>
sh ./scripts/update-packages.sh @moego/bff-openapi <dist-tag>
sh ./scripts/update-packages.sh <dist-tag> @moego/api-web @moego/bff-openapi
# 简写：
pnpm update:web <dist-tag>     # ↔ update-packages.sh @moego/api-web
pnpm update:bff <dist-tag>     # ↔ update-packages.sh @moego/bff-openapi
pnpm update:finance            # finance kit 整组升级（用 scripts/update-finance-packages.sh）
```

### 2.3 AGENTS.md 关键守则

- 禁止改 main / release 分支
- 不擅自改 `package.json` 版本
- 不改 CI 配置
- **不写 `any`**（TS strict）
- **组件中不直接调 API**——封到 `src/query/` 或 hook
- **不能用相对路径跨层级**（用 path alias，如 `@/*`）
- 4 个细分指南位于 `docs/`：business-time-utils / query-kit / bff-usage / modal-usage

### 2.4 联调 SDK 升级流程

```bash
# 场景：后端在 feature-grm-1728-isnewcustomer-aggregation 分支发了 @moego/api-web

cd repo/front-end/Boarding_Desktop
git checkout -b feature-grm-1728-isnewcustomer-aggregation

# 一键升 + npm install
pnpm update:web grm-1728-isnewcustomer-aggregation
# 内部：fetch 实际版本号 → 改 package.json → pnpm install

pnpm dev           # 跑起来联调
pnpm check:types   # 类型对齐验证
```

## 3. moego-mobile 工程结构

### 3.1 顶层目录

```
moego-mobile/
├── ios/ (Xcode workspace + Pod)
├── android/ (gradle 工程)
├── index.js                # 应用入口
├── app.config.ts           # Expo 配置
├── react-native-logger/    # workspace:* 子包 → @moego/react-native-logger
├── react-native-traceroute/ # workspace:* → @moego/react-native-traceroute
├── scripts/                # bump_version / preassemble / build_native / replace_env / etc.
└── src/
    ├── api/, components/, entry/, libs/
    ├── modules/<Module>/   # 业务域，新代码主战场
    │   ├── <Module>.api.ts          # 必须的 API 接口定义
    │   ├── store/ components/ hooks/ utils/   # 可选
    │   └── <PageName>/<PageName>.tsx          # 大驼峰目录 + 同名 .tsx 入口
    ├── query/, services/, utils/
    └── types/openApi/      # openapi2dts 生成（不要手改）
```

### 3.2 dev 命令

```bash
pnpm install
pnpm start              # expo start
pnpm android            # 起 Android
pnpm ios                # 起 iOS
pnpm test               # jest
pnpm test:coverage
pnpm check:types
pnpm openapi            # 重新生成 src/types/openApi/
pnpm generate           # 重新生成 entry/generated/（图标、icon path 等）

# SDK 升级（同 Boarding 风格）
pnpm update:web <dist-tag>
pnpm update:bff <dist-tag>
pnpm update:finance
```

### 3.3 AGENTS.md 关键守则

- TS 禁用 `@ts-ignore`，必须用 `@ts-expect-error` + 注释
- 新代码**优先放进 `src/modules/<Module>/`**，通用后再上移
- `src/modules/` 外**禁止** `export default`
- 不准编辑 `src/entry/generated/` 和 `src/types/openApi/`（用 `pnpm generate` / `pnpm openapi` 重新生成）
- 不准直接 import RN 原生模块（统一从 `src/utils/NativeModules.ts`）
- 不准未要求改 `package.json` / `patches/`

### 3.4 环境配置（`.env`、`.env.test`）

```
EXPO_BUNDLE_SERVER_URL=https://expo-updates.moego.pet
EXPO_BUNDLE_APP_ID=moego-business
EXPO_BUNDLE_TOKEN=...
EXPO_BUNDLE_DUAL_MODE=true
EXPO_BUNDLE_CDN_BASE_URL=https://cdn.moego.pet/expo-updates/moego-business
```

这是 Expo Updates 新架构 OTA 配置。API host / BFF host 不在 `.env` 中——⚠️ TODO 应在 `src/api/` 或 `app.config.ts` 中按环境推断（未具体读到映射代码）。

## 4. moego-online-booking-client-web 工程结构

### 4.1 顶层 src

```
src/
├── App.tsx, main.tsx, routes.ts, ssr.tsx, setup.ts
├── assets/, configs/, hooks/, i18n/, init/, libs/
├── components/             # @deprecated，不要再加新通用组件
├── widgets/, hooks/, utils/  # 都 @deprecated
├── pages/, payment/, query/, service/
├── state/<domain>/         # jotai atom 按业务域拆
├── styles/, test/, traffic/, types/
```

### 4.2 dev 命令

```bash
pnpm install
pnpm dev                # vite
pnpm dev:server         # 本地 SSR 验证
pnpm build / build:client / build:server
pnpm server             # 生产模式 express
pnpm test:unit          # vitest
pnpm check:types / check:circles / check:prettier / stylefix
pnpm openapi            # 重新生成 src/types/openApi/

# 联调
pnpm linkDevLib              # link 本地 ../moego-client-libs
pnpm install:lib             # 拉远端 client-libs（latest）
pnpm install:lib --branch xxx  # 切到 feature 分支版本（对应 dist-tag）
```

### 4.3 AGENTS.md 关键守则

- 新代码**优先用 `@moego/client-lib-*`**——不要再往 `src/components/` `src/hooks/` `src/utils/` `src/widgets/` 堆通用能力
- **禁止 `export default`**
- **禁止新增 `index` 文件**
- 路由统一在 `src/routes.ts`，用 `RawRoute.from()` 定义
- 富文本必须先 `dompurify`
- 路由第二段不能是 `landing`/`book`/`membership`/`package`

### 4.4 与 Boarding 的差异

- **不用 `update:web` / `update:bff`**——用 `install:lib` 拉一组 `@moego/client-lib-*`
- 状态管理是 Jotai（`store.get(...)` 而非 hook）
- React Query 是 v5（其他仓库是 v4）

## 5. OnlineBooking_Go_Web（Vue/Nuxt 老版）

老版 OB Web，独立运行，**不用 @moego/* 包**，类型走 swagger2dts 自己生成（`vendor/swagger.ts` / `vendor/swagger-rpc.ts`）。

```bash
yarn install
yarn dev    # MOE_ENV=local MOE_RPC_HOST=https://api.t2.moego.dev nuxt-ts --port 9400
yarn build
yarn test
yarn swagger     # 重新生成 vendor/swagger*.ts（≈ Boarding 的 pnpm openapi）
yarn push:test   # 把 feature 分支合到 master 并 push（CI 触发 testing 部署）
```

环境推断在 `config/host.ts`（按 host 名判断 testing / staging / prod）。

## 6. 前端通用：package.json 升级写法

**不要**直接写 dist-tag 字符串：

```json
"@moego/api-web": "grm-1728-isnewcustomer-aggregation@latest"   // npm 不解析
```

**正确做法**：先 fetch 实际版本号填进去：

```bash
VERSION=$(npm view "@moego/api-web@<dist-tag>" version \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/)
# 改 package.json：
# "@moego/api-web": "$VERSION"
```

或直接用 `update-packages.sh` / `update:web` / `update:bff` 一键完成。

注意：dist-tag 版本会随后端新 push 不断更新时间戳——想联调最新代码就重新 fetch + npm install。

## 7. 前端常见踩坑

| 现象 | 原因 | 解法 |
|---|---|---|
| 浏览器 npm install 拉不到 `@moego/<pkg>` | `.npmrc` 没配 nexus / dist-tag 不存在 | 见 SKILL.md §6 + api-web-publish-cheatsheet.md |
| pnpm install 报 engine mismatch | moego-bff 要求 node >=23，Boarding 要求 pnpm 10 | 用 `nvm` / `corepack enable` 切版本 |
| `pnpm openapi` 跑完 `src/openApi/*` 没变化 | 老 svc 还没 deploy 到 codegen 默认拉取的环境 | 见 legacy-svc-codegen.md |
| 改了组件但 amos store 没刷新 | amos 用 box 模型；selectors 没引用变更字段 | 看 store/<domain>/__test__/ 写新 selector + 测试 |
| moego-mobile metro bundler 报模块解析失败 | `react-native-logger` / `traceroute` 是 workspace 包 | 用 `pnpm install` 不要 npm；必要时清缓存 `pnpm start --reset-cache` |
| OnlineBooking_Go_Web 改完不见效 | Nuxt SSR 缓存 | 重启 `yarn dev` |

## 8. 前端 NEVER 规则

- **不要直接编辑 `src/openApi/*`（Boarding）/ `src/types/openApi/`（mobile / OB-client-web）**——这些是 codegen 产物，必须通过 `pnpm openapi` 重新生成
- **不要在 React 组件里直接 import gRPC client / 直接 import api**——按 AGENTS.md 用 `src/query/` 或 hook
- **不要往 `src/components/` `src/hooks/` `src/utils/` `src/widgets/`（OB-client-web）堆通用能力**——这 4 个目录已 @deprecated，用 `@moego/client-lib-*`
- **不要在 moego-mobile 的 `src/modules/` 外 `export default`**
- **不要在 package.json 写 dist-tag 字符串**（npm 不解析）——用 `update:web` / `update:bff` 一键升
- **不要假设 mobile 和 Boarding 共用 store 风格**——mobile 是经典 Redux + thunk，Boarding 是 amos，OB-client-web 是 Jotai
