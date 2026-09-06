# 老 Java svc OpenAPI codegen 流程

适用于：`moego-server-grooming` / `moego-server-api` / `moego-server-common` / `moego-open-api-v1` 等老 Java/Spring 服务改了 `@RestController` Controller 字段，需要前端拿到新类型。

## 关键事实

**老 Java svc 不发 npm 包**。它们自己的 runtime 通过 springdoc/swagger 暴露 `/v3/api-docs`（或 `/v2/api-docs`），由消费方仓库（`moego-bff` 或前端项目）的 `openapi2dts` 工具去拉取，生成的 TS 代码**直接 commit 进消费方仓库**。

也就是说：
- 老 svc 改 Controller = "改了协议"
- 协议消费方 = **commit 进自己 repo**，不走 npm install
- 老 svc 不像 `moego-api-definitions` / `moego-bff` 有 dist-tag 概念

## 消费方仓库

| 消费方 | codegen 命令 | 输出目录 |
|---|---|---|
| `moego-bff` | `pnpm generate:legacy-api` (= `sh ./ci/generate-legacy-api.sh`) | `packages/legacy-api/src/generated/` |
| `Boarding_Desktop` | `npm run openapi` (= `openapi2dts --outputRest src/openApi/`) | `src/openApi/*.ts` |

实际目录（Boarding_Desktop）：

```
src/openApi/
├── business-schema.ts     # business 老 svc
├── customer-schema.ts     # customer 老 svc
├── grooming-schema.ts     # grooming 老 svc
├── message-schema.ts      # message 老 svc
├── payment-schema.ts      # payment 老 svc
├── retail-schema.ts       # retail 老 svc
└── schema.ts              # 汇总
```

## 正确联动开发流程

```
1. 老 svc 仓库（如 moego-server-grooming）
   - 切 feature-<topic> 分支
   - 改 @RestController 字段（DTO 上的 swagger 注解记得更新）
   - push → CI deploy 到 testing/staging
   - ⚠️ 不会发任何 npm 包，跟 nexus 完全无关

2. 等 svc 部署完成
   - 验证：用 curl 调老 svc 的 /v3/api-docs 看新字段确实在 openapi json 里
   - 如果只 deploy 到 testing，确认 openapi2dts 工具的 source URL 配置指向 testing 而不是 prod

3. 消费方仓库（前端 Boarding_Desktop 或 moego-bff）
   - 切 feature-<topic> 分支（保持同名一致）
   - 跑 codegen：
     # moego-bff
     pnpm generate:legacy-api
     # Boarding_Desktop
     npm run openapi
   - git diff 看生成的 .ts 文件，确认新字段确实出现
   - 用业务代码消费新字段
   - commit (包含 codegen 结果 + 业务代码)
   - push → 走自己 repo 的 PR 流程
```

## openapi2dts 工具的 source URL

`@moego/openapi2dts` 是公司内部 CLI 工具，通常默认拉某个固定环境（prod / staging）。如果遇到拉不到新字段：

1. 看消费方仓库根目录有没有 `.openapi2dtsrc` / `openapi2dts.config.js` / `openapi2dts.json` 等配置
2. 看 `package.json` script 命令是否带 `--server <url>` 类参数
3. 看 `openapi2dts --help` 输出

如果默认拉 prod，需要本地临时改环境变量或 flag 指向 testing/staging，codegen 完再切回 prod 跑一遍校验。

## 常见踩坑

| 现象 | 原因 | 解法 |
|---|---|---|
| codegen 跑完 `src/openApi/*.ts` 没变化 | 老 svc 改动还没 deploy 到 codegen 默认拉取的环境 | 等 deploy 或临时切环境拉 |
| 生成的 TS 字段名跟后端 DTO 不一致 | swagger 注解里 `@Schema(name=)` 跟 Java 字段名不同 | 改 swagger 注解或 Jackson `@JsonProperty` |
| 新字段是 nullable / optional，前端报类型错 | swagger 默认 required，老 DTO 没标 nullable | 后端 DTO 字段加 `@Schema(nullable=true)` 或 `@Nullable` |
| codegen 把整个文件重写，commit 噪音大 | openapi2dts 工具会重新格式化 | 接受这个事实，PR 评审时跳过生成代码 diff，只看手写代码改动 |

## NEVER 规则

- **不要在老 svc 仓库找"npm publish workflow"**——没有的，结构跟 moego-bff / moego-api-definitions 完全不同。
- **不要在前端尝试 `npm view @moego/grooming` / `@moego/business`**——这些不是独立 npm 包，是 in-tree 生成代码。
- **不要漏 commit `src/openApi/` 或 `packages/legacy-api/src/generated/` 改动**——这就是协议变更的载体，漏了等于跟后端脱钩。
- **不要在 PR 描述里只写"业务代码"忽略 codegen diff**——评审者要看哪些字段进/出来了。
