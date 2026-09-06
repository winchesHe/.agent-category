# @moego/bff-openapi / bff-schemas / legacy-api 发包速查

## Registry

```
https://nexus.devops.moego.pet/repository/npm-local/
```

跟 `@moego/api-web` 同一个 nexus，依赖前端项目 `.npmrc` 的 `@moego:registry` 配置。

## 包来源

- **唯一发布源**：`moego-bff` 仓库（注意：跟 `moego-api-v3` 不同的 BFF，moego-bff 是 Node TS BFF）
- 内部 `packages/` 三个子包：
  - `packages/openapi` → `@moego/bff-openapi`（hono + zod-openapi 生成的客户端）
  - `packages/schemas` → `@moego/bff-schemas`（zod schema 共享类型）
  - `packages/legacy-api` → `@moego/legacy-api`（用 openapi2dts 从老 Java svc 拉取生成的 REST client）

## dist-tag 命名规则

`moego-bff/ci/calc-version.sh` 的 case 分支精确支持：

| 分支名 | dist-tag | 触发发包？ |
|---|---|---|
| `feature-<topic>` | `<topic>` | ✅ |
| `bugfix-<topic>` | `<topic>` | ✅ |
| `main` | `latest` | ✅ |
| `production` | — | ❌ skip（**跟 api-definitions 不同**，moego-bff 不识别 `production`）|
| `feature/<topic>` 斜杠 | — | ❌ skip |
| `feat-<topic>` / `fix-<topic>` / `hotfix-<topic>` / `release-<topic>` / `chore-<topic>` | — | ❌ skip |
| 无前缀 | — | ❌ skip |

CI 脚本的实际 case 块：

```bash
case "$BRANCH_NAME_INPUT" in
  main)
    VERSION="$MAJOR.$MINOR.$((PATCH + 1))"
    TAG=latest
    IS_PRODUCTION=true
    SHOULD_PUBLISH=true
    ;;
  feature-* | bugfix-*)
    TAG=$(echo "$BRANCH_NAME_INPUT" | sed -E 's/^(feature|bugfix)-(.*)$/\2/')
    ...
    SHOULD_PUBLISH=true
    ;;
  *)
    echo "Skip version calc on branch $BRANCH_NAME_INPUT"
    ;;
esac
```

`SHOULD_PUBLISH=false` 时 `build-publish-openapi.sh` 和 `build-publish-schemas.sh` 都会 `exit 0` 跳过。

**与 api-definitions 的差异**：`production` 在 api-definitions 走 latest 发布，在 moego-bff 走 skip。如果团队约定有"production 维护分支"，moego-bff 这边发不出，要注意。

## 版本号格式

```
MAJOR.MINOR.PATCH-<dist-tag>.<BUILD_ID>

举例：
0.1.442-grm-1728-isnewcustomer-aggregation.123
0.1.442-fulfillment-refactor.456

main 分支：MAJOR.MINOR.<PATCH+1>，如 0.1.443
```

## 关键 CI 脚本

```
moego-bff/ci/calc-version.sh           — 计算 VERSION + TAG + SHOULD_PUBLISH
moego-bff/ci/build-publish-openapi.sh  — 发 @moego/bff-openapi
moego-bff/ci/build-publish-schemas.sh  — 发 @moego/bff-schemas
moego-bff/ci/generate-legacy-api.sh    — 跑 openapi2dts 拉老 svc 生成 legacy-api
```

## 常用查询命令

```bash
# 查具体 dist-tag 对应版本
npm view "@moego/bff-openapi@<dist-tag>" version \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/

# 查所有 dist-tags
npm view @moego/bff-openapi dist-tags --json \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/

# 同样查 schemas / legacy-api
npm view "@moego/bff-schemas@<dist-tag>" version --registry=...
npm view "@moego/legacy-api@<dist-tag>" version --registry=...
```

## Boarding_Desktop 一键升级

```bash
# 默认升到 latest dist-tag
sh ./scripts/update-packages.sh @moego/bff-openapi

# 升到指定 dist-tag
sh ./scripts/update-packages.sh @moego/bff-openapi <dist-tag>

# 同时升多个包到同一 dist-tag
sh ./scripts/update-packages.sh <dist-tag> @moego/api-web @moego/bff-openapi
```

## 强制触发发包

如果本次开发**只动了 moego-api-v3 或老 svc**，moego-bff 没有任何 route 改动但需要前端拉对应 dist-tag：

```bash
cd repo/back-end/moego-bff
git checkout -b feature-<topic>
git commit --allow-empty -m "chore: trigger bff-openapi publish for <topic> <TICKET>"
git push -u origin feature-<topic>
```

## 区分三种 BFF SDK 用途

| 包 | 内容 | 何时升级 |
|---|---|---|
| `@moego/bff-openapi` | moego-bff（Node BFF）自己暴露的 REST 接口的 TS client | moego-bff 改了 server/routes/* |
| `@moego/bff-schemas` | moego-bff 内部用的 zod schema 类型，前端共用 | moego-bff 改了 schema 定义 |
| `@moego/legacy-api` | moego-bff 通过 openapi2dts 桥接的老 Java svc REST client | 老 Java svc（grooming / business / ...）改了 Controller，并且 moego-bff 跑过 generate-legacy-api 提交了生成结果 |
