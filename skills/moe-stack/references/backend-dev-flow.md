# 后端开发流程（Java + Node BFF）

适用于：在 `moego-api-v3` / `moego-svc-*` / `moego-server-*` / `moego-bff` 里加功能、改 bug。

## 1. Java 仓库通用约定

### 1.1 包分层（按 `moego-api-v3` / `moego-svc-*` 抽样验证）

```
src/main/java/com/moego/<group>/<v>/<domain>/
├── controllor/    # api-v3 用这个拼写（注意：不是 controller）
├── controller/    # svc-appointment 用 controller
├── server/        # svc-online-booking 用 server（@GrpcService 实现类）
├── convertor/     # MapStruct converter（api-v3 拼 convertor）
├── converter/     # 别的仓库拼 converter；同一仓库内统一即可
├── enricher/      # 聚合 / 现场字段填充（典型例：NewCustomerEnricher）
├── helper/        # 业务工具
├── service/       # 业务服务
├── domain/        # 领域模型（svc-appointment 有）
├── dto/           # DTO
├── client/        # 调下游 gRPC client
├── mapper/        # MyBatis Mapper（svc-* 有）
├── consumer/      # MQ / event listener（svc-* 有）
├── listener/      # event handler
├── config/
└── constant/
```

### 1.2 关键注解速查

| 注解 | 来源 | 用途 |
|---|---|---|
| `@GrpcService` | `com.moego.lib.common.grpc.server.GrpcService` | gRPC server 实现，**必须继承** `XxxServiceGrpc.XxxServiceImplBase` |
| `@RestController` | Spring | 旧 monolith（`moego-server-grooming`）HTTP 接口 |
| `@RequiredArgsConstructor` | Lombok | 构造器注入，Controller / Service 几乎都用 |
| `@Auth(AuthType.COMPANY)` | 内部 | 接口方法上注解鉴权；身份从 `AuthContext.get().companyId()` 拿 |
| `@Mapper(componentModel=SPRING, nullValueCheckStrategy=ALWAYS, collectionMappingStrategy=ADDER_PREFERRED, unmappedSourcePolicy=WARN, unmappedTargetPolicy=WARN)` | MapStruct | Converter 标准模板（`api-v3` 风格） |
| `@SpringBootTest` + `@ExtendWith(MockitoExtension.class)` | JUnit5 + Mockito | 单测基类，多数仓库另有 `MockStubs` 基类 |
| `@Transactional` | Spring | svc-* 的单测要求加，自动回滚 |

### 1.3 单测约定

- 框架：**JUnit5 + Mockito + AssertJ**（`spring-boot-starter-test`）
- gRPC 测试：`io.grpc:grpc-testing`
- 各仓库提供共享基类 `MockStubs`（`src/test/java/.../utils/MockStubs.java`）
- 命名：`XxxControllerTest` / `XxxServiceTest`，按业务域放
- `svc-online-booking` 单测必须 `@Transactional` 回滚

### 1.4 常用 Gradle 命令

```bash
# 起服务（多数仓库未在 README 显式列，按 spring-boot plugin 推断）
./gradlew bootRun                       # ⚠️ moego-svc-activity-log README 显式确认；其他仓库 README 未显式列

# 全量单测
./gradlew test

# 单测某个类
./gradlew test --tests "*NotificationControllerTest"
./gradlew :module:test --tests "*<X>Test"

# 多模块 build（如 server-grooming）
./gradlew :moego-server-grooming:test

# 格式化（spotless 强制）
./gradlew spotlessApply         # 修
./gradlew spotlessCheck          # 检查
./gradlew :moego-server-grooming:spotbugsMain   # spotbugs

# MyBatis Mapper 同步（svc-online-booking）
./gradlew mbGenerator
```

### 1.5 spotless 自定义规则（`moego-api-v3` build.gradle:78-98）

- **禁止 wildcard import**（`import com.foo.*` 直接 fail）
- **禁止 `new BizException(...)`**——强制走 `ExceptionUtil`
- 其他仓库未抽样自定义规则；若 spotless 报错，对照 `build.gradle` 看自定义 step

### 1.6 不能 commit 的目录

| 仓库 | 不能改 / 自动生成 |
|---|---|
| `moego-svc-online-booking` | `mapper/base/Base*Mapper.{java,xml}`（MyBatis Generator 产物） |
| Java 多数仓库 | `*ConverterImpl* / *MapperImpl*` 是 MapStruct 编译产物，jacoco 默认排除 |

### 1.7 gRPC client 调下游

- api-v3 调 svc-*：通过 `@GrpcClient("svc-name")` 注入 stub
- svc-* 之间互调：同理
- 具体 stub 类来自 `@moego/api-web` 同源的 generated Java 代码（在 `moego-api-definitions` 编译产物里 jar 化）

### 1.8 grpcurl 联调

未在 Java 仓库 README 里找到 grpcurl 调用示例（⚠️ TODO）。一般用法：

```bash
# list services
grpcurl -plaintext <host>:<port> list

# call method
grpcurl -plaintext \
  -H "x-company-id: <id>" \
  -d '{"foo": "bar"}' \
  <host>:<port> com.moego.api.v3.notification.NotificationService/GetNotifications
```

需要的 proto 路径 / 端口请到对应仓库 `application.yml` 看（具体方法 ⚠️ TODO 等用到时核实）。

## 2. moego-bff（Node BFF）开发流程

### 2.1 仓库结构（pnpm workspace）

```
moego-bff/
├── server/                       # BFF 主体
│   ├── bootstrap/, init/, lib/
│   ├── middleware/               # auth-biz / svc-method-invoker / service-fetcher 等
│   ├── routes/<domain>/          # 路由（约 35 个一级目录）
│   ├── services/<domain>/        # 业务封装层（不是 gRPC client，是 BFF 内服务）
│   ├── utils/                    # invoke-svc-method / openapi / hono-route 等
│   ├── types/
│   └── index.ts                  # 入口
├── packages/openapi/             # 发布为 @moego/bff-openapi（zodios client，vite build）
├── packages/schemas/             # 发布为 @moego/bff-schemas（zod schema 裸源码）
├── packages/legacy-api/          # 发布为 @moego/legacy-api（openapi2dts 生成产物）
├── scripts/                      # codegen / 升级 / 脚手架
├── ci/                           # bump / calc-version / build-publish-* / generate-legacy-api
└── pnpm-workspace.yaml
```

### 2.2 典型 route 风格（`server/routes/example/api.ts`）

```ts
import { createRoute } from '@hono/zod-openapi';
import { AccountAuthMiddleware } from '#/middleware/auth-biz.middleware';
import { ValidatePasswordRequestSchema, ValidatePasswordResponseSchema }
  from '@moego/bff-schemas/example.schema';
import { createJsonRequest, createJsonResponse } from '#/utils/hono-route';
import { app } from './index';

const validateAccountRoute = createRoute({
  method: 'post',
  path: '/rpc/account/validate',
  middleware: AccountAuthMiddleware,
  request: createJsonRequest(ValidatePasswordRequestSchema),
  responses: {
    ...createJsonResponse(HTTP_CODE.SUCCESS, ValidatePasswordResponseSchema, '...'),
  },
});

app.openapi(validateAccountRoute, async (c) => {
  const { id, password } = c.req.valid('json');
  // 调 gRPC 下游：用 invokeSvcMethodAutoThrow，自动转 ConnectError → SvcInvokeException
  const { correct } = await c.invokeSvcMethodAutoThrow(
    AccountServiceClient,
    'validatePassword',
    { id: BigInt(id), password },
  );
  return c.json({ correct }, HTTP_CODE.SUCCESS);
});
```

**关键点**：
- route 先 `createRoute` 拿强类型，再 `app.openapi(route, handler)` 注册
- handler **不直接 import gRPC client**，统一通过 context：
  - gRPC 下游：`c.invokeSvcMethodAutoThrow(<Client>, '<method>', <payload>)`（由 `server/utils/invoke-svc-method.ts` 实现）
  - HTTP 老 svc：`c.open(action, opts)`（由 `server/middleware/service-fetcher.middleware.ts` 注入，标 `@deprecated`）
- 自动注入 dd-trace span + 灰度 forward context

### 2.3 下游调用映射

| 下游类型 | 调用方式 | 客户端来源 | 标识 |
|---|---|---|---|
| 新 Go svc / api-v3 | `c.invokeSvcMethodAutoThrow(<Client>, ...)` | `@moego/api-node-v2`（基于 `@connectrpc/connect`），老的 `@moego/api-node` 并存 | `latest` 由 pnpm catalogs 锁定 |
| 老 Java svc | `c.open(action, opts)` fetch | `@moego/legacy-api` 提供类型 `OpenApiModels` | K8s 内 `http://moego-service-${service}:${port}`（customer:9201, business:9203, payment:9204, message:9205, retail:9207, grooming:9206） |
| DB | 无直接 ORM | — | moego-bff 不直接读 DB；数据访问交给 svc |

### 2.4 本地起服务

```bash
# 引擎约束
# node >=23.0.0, pnpm >=9.15.3, preinstall 强制 pnpm

pnpm install
pnpm g:env          # 拉 AWS Secrets Manager 生成 .env
pnpm dev            # cross-env NODE_ENV=development tsx watch --inspect server/index.ts
pnpm build          # tsc && tsc-alias
pnpm test           # vitest run
pnpm coverage       # v8 覆盖率
pnpm check:types    # tsc --noEmit --skipLibCheck
pnpm lint           # eslint .

# 联调用
pnpm connect        # 本地连 K8s（具体语义看 scripts/core/connect.ts）
pnpm create-route   # 脚手架，新增 route 用（别名 pnpm cr）
```

### 2.5 codegen 命令

```bash
pnpm generate:zod          # proto → zod schemas（scripts/sync-models-to-zod.ts）
pnpm generate:openapi      # 扫 server/routes 生成 packages/openapi（vite build 前的 client codegen）
pnpm generate:legacy-api   # openapi2dts → packages/legacy-api/src/generated
pnpm update-api            # 一键升级 @moego/api-node*，重跑上面三步
```

### 2.6 测试约定

- **Vitest 3.2.4**（globals: true, pool: 'threads', testTimeout: 10s）
- include：`server/**`、`packages/openapi/**`、`packages/schemas/**`、`scripts/**`
- 后缀：`*.test.ts` / `*.spec.ts`

### 2.7 环境配置（`.env.example`）

只列 key，不列值：

```
NAMESPACE
AWS_REGION
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
INTERCOM_TOKEN
```

其他 key（INTERCOM_WEB_SECRET_KEY / TWILIO_ACCOUNT_TOKEN / RETELL_API_KEY / CANNY_PRIVATE_KEY）通过 `ci/env.json` 声明，对应 AWS Secrets Manager。本地用 `pnpm g:env` 拉取。

### 2.8 docs

- `docs/spec-kit/CONSTITUTION.md`：SDD 2.0 项目宪法，规定 spec 路径 `docs/spec-kit/specs/<JIRA-KEY>/spec.md`
- `docs/BFF-Product-Guide.md`：105KB 产品手册
- `GEMINI.md`：3 条 AI Code Review 守则

## 3. 后端 push → deploy 路径

所有后端仓库（Java 与 Go）共用一套基础设施：

| 触发 | workflow | 部署环境 | 说明 |
|---|---|---|---|
| `push branches: ['*']` | `offline.yaml` / `development.yaml` | testing（默认） | 调 `MoeGolibrary/moego-actions-tool/.github/workflows/preset-offline.yml@production`；feature 分支 push 后会自动部署 testing |
| `workflow_dispatch` | 同上 | testing / staging / devops | 手动选环境 + `skip_canary` / `dry_run` / `build_only` |
| `push tags: ['*']` | `online.yaml` / `production.yaml` | production | 调 `preset-online.yml@production`；canary 默认启用 |
| `cron 16:00 UTC` | `schedule-daily.yaml` | — | 每天定时（具体作用 ⚠️ TODO） |

**注意**：
- preset workflow 在 `MoeGolibrary/moego-actions-tool` 仓库，本地 yaml 只是触发壳；想看 stage 序列需要 clone 那个仓库
- moego monorepo（`moego/`）有独立 `app-ci.yaml`，按 app 维度动态选择 build/deploy；它**会**根据 proto 变更触发 `publish-npm` job
- 普通 Java/Go svc 仓库的 `.github/workflows/` **没有** `npm publish`——验证了"只有 api-definitions 和 bff 发包"

## 4. 后端 NEVER 规则

- **不要直接 commit `*ConverterImpl.java` / `*MapperImpl.java`**——MapStruct 编译产物，不进 VCS
- **不要在 Controller / Service 里直接 `new BizException(...)`**（`moego-api-v3` spotless 直接 fail）——走 `ExceptionUtil`
- **不要 wildcard import**（`import com.foo.*`）——`moego-api-v3` spotless 直接 fail
- **不要改 `mapper/base/Base*Mapper.{java,xml}`**（svc-online-booking）——MyBatis Generator 自动产物，改了下次 `./gradlew mbGenerator` 会被覆盖
- **不要假设 push 会触发 npm 包发布**——只有 `moego-api-definitions` / `moego-bff` 才有 publish step（详见 SKILL.md §2）
- **不要在 moego-bff 的 route handler 里直接 import gRPC client**——通过 `c.invokeSvcMethodAutoThrow` 走 context，否则丢 trace context、丢 grey forward
- **不要在 moego-bff 添加新的 `c.open()` 调用**（标 `@deprecated`）——优先用 gRPC 下游 `invokeSvcMethodAutoThrow`，老 svc 走法仅为兼容遗留
