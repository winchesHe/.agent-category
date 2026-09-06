# @moego/api-web 发包速查

## Registry

```
https://nexus.devops.moego.pet/repository/npm-local/
```

前端项目根 `.npmrc` 必须有：

```
@moego:registry=https://nexus.devops.moego.pet/repository/npm-local/
```

## 包来源

- **唯一发布源**：`moego-api-definitions` 仓库的 CI（`Build and deploy` workflow，由 push 触发）。
- 其他 moego 仓库（api-v3 / svc-* / server-*）push **不会** 触发 api-web 发包。

## dist-tag 命名规则

`moego-api-definitions/ci/npm_publish.sh` 的 case 分支精确支持以下前缀：

| 分支名 | dist-tag | 触发发包？ |
|---|---|---|
| `feature-grm-1728-isnewcustomer-aggregation` | `grm-1728-isnewcustomer-aggregation` | ✅ |
| `bugfix-payment-retry` | `payment-retry` | ✅ |
| `main` | `latest` | ✅ |
| `production` | `latest` | ✅ |
| `feature/multi-business`（**斜杠**） | — | ❌ skip |
| `feat-multi-business` | — | ❌ skip |
| `fix-something` | — | ❌ skip |
| `hotfix-urgent` | — | ❌ skip |
| `release-2.0` | — | ❌ skip |
| `chore-cleanup` | — | ❌ skip |
| `crm-ads`（无前缀） | — | ❌ skip |

CI 脚本的实际 case 块：

```bash
case "$BRANCH_NAME" in
production | main)
  export VERSION="$MAJOR.$BUILD_ID.$RUN_ATTEMPT"
  TAG=latest
  ;;
feature-* | bugfix-*)
  TAG=$(echo "$BRANCH_NAME" | sed -E 's/^(feature|bugfix)-(.*)$/\2/')
  ...
  ;;
*)
  echo "Skip publish npm on branch $BRANCH_NAME"
  exit 0
  ;;
esac
```

**任何其他前缀** 一律 `case *)` skip 发包。

## 版本号格式

```
1.109.0-<dist-tag>.<timestamp>

举例：
1.109.0-grm-1728-isnewcustomer-aggregation.20260512081215123456789
1.109.0-crm-ads.20260512072325719672322

main 分支的 latest：
1.25718343999.1  （不带 - 后缀，纯时间戳）
```

## 常用查询命令

```bash
# 查指定 dist-tag 对应的具体版本号
npm view "@moego/api-web@<dist-tag>" version \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/

# 查所有 dist-tag（list 很长）
npm view @moego/api-web dist-tags --json \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/

# 查今天发布的所有版本
npm view @moego/api-web time --json \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/ \
  | grep $(date +%Y-%m-%d)

# 查某个分支是否已发包（grep dist-tag 关键词）
npm view @moego/api-web dist-tags --json \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/ \
  | grep '<keyword>'
```

## 拉不到 dist-tag 的排查

按顺序查：

1. **分支是否存在**：`gh api repos/MoeGolibrary/moego-api-definitions/branches/feature-<topic>`
2. **CI 是否跑完**：`gh run list --repo MoeGolibrary/moego-api-definitions --branch feature-<topic>`
3. **CI 是否跳过了 publish step**：进 workflow run 看 Build/Publish Phase 日志（搜 `npm publish` / `nexus`）
4. **registry 是否配对**：`npm config get @moego:registry` 必须返回 nexus 地址，否则 404 来自公共 registry
5. **认证**：nexus 拉取通常公开读，但 npm 全局有认证时也可能干扰；try `--registry` 显式覆盖

## 强制触发发包（proto 无改动时）

如果本次开发**只动了下游（api-v3 / svc-*）**，api-definitions 分支没有任何 proto 改动，但仍需要前端拉对应 dist-tag：

方案 A（推荐）：在 api-definitions 建分支 + 推一个空 commit（注释）

```bash
cd repo/back-end/moego-api-definitions
git checkout -b feature-<topic>
git commit --allow-empty -m "chore: trigger api-web publish for <topic> <TICKET>"
git push -u origin feature-<topic>
```

方案 B：在 proto 文件里推注释类型的最小变更（例如一行 `// since <TICKET>`），让 codegen 跑一次。

方案 C（如有 CI 支持）：手动 `workflow_dispatch` 强制运行 publish workflow。

## package.json 写法

**不要**写 dist-tag 字符串：

```json
// Bad - npm 不识别这种 dist-tag 引用语法
"@moego/api-web": "grm-1728-isnewcustomer-aggregation@latest"
```

**正确做法**：fetch 实际版本号填进去。

```bash
VERSION=$(npm view "@moego/api-web@<dist-tag>" version \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/)
# 然后改 package.json：
# "@moego/api-web": "<VERSION>"
```

注意：dist-tag 对应的 version 会随分支新 push **不断更新时间戳**，要联调最新代码就重新 fetch + 改 package.json + npm install。
