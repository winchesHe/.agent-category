# Commit / PR / Review 规约

适用于：moego 项目 commit message 写法、PR 创建、code review 流程。

## 1. Commit message 规则

moego 仓库分两套实现：

### 1.1 后端 Java/Go 仓库：`.githooks/commit-msg`（bash 正则）

```
^(feat|fix|docs|style|refactor|perf|test|chore)(\(.+\))?: .{1,100} <PREFIX>[0-9]+$
```

需要手动启用：`git config core.hooksPath .githooks`。

`Merge` / `Revert` 开头的行可跳过校验。

| 仓库 | 额外 type / 前缀差异 |
|---|---|
| moego-api-v3 | 前缀含 `RPT-` |
| moego-svc-appointment | 前缀含 `GPPA-` |
| moego-server-grooming | 前缀含 `RPT-` |
| moego-client-api-v1 | 前缀含 `RPT-` |
| moego-svc-online-booking | 标准 + `CRM-` |
| moego-java-lib | 标准 + 新增 type `ci` |
| moego-open-api-v1 | type 额外 `main` / `release`；前缀集合最少（无 GRM- / ENT- / MER- 等） |
| moego-open-api-v1 | hook 写在 `hooks/`（不是 `.githooks/`），用 `make git_hook` 设置 |

### 1.2 前端 / 协议层 / Node 仓库：`commitlint.config.js` + `.husky/commit-msg`

走 `@commitlint/config-angular` preset，强制 `references-empty: [2, 'never']`（**必须带 Jira ticket**）。

| 仓库 | header-max-length 配置 |
|---|---|
| moego-bff | 100 |
| Boarding_Desktop | 110（issuePrefixes 含 GROOM-/OBV-/APP-/CS-/MOE-/TECH-/ERP-/FDN-/MER-/FIN-/IFRFE-/CA-/CRM-/DATA-/EN-/IFRBE-） |
| moego-mobile | 100（type 显式枚举，含 `wip` / `type`） |
| moego-online-booking-client-web | 100 |
| OnlineBooking_Go_Web | 100 |
| moego-api-definitions | 100 |
| moego-server-common | `[2, 'never', 100]`（仓库实际配置；同时有 bash hook） |

`Merge` / `Revert` / 自动 bump（`chore: auto bump version`）跳过。

### 1.3 标准 commit message 模板

```
<type>(<scope>): <subject> <TICKET>

例：
feat(notification): add isNewCustomer enricher GRM-1728
fix(grooming): correct refund flow edge case GROOM-2034
docs(spec): add api-v3 deployment spec TECH-0
chore: auto bump version
```

- type 选 `feat / fix / docs / style / refactor / perf / test / chore`（部分仓库支持 `ci / wip / build / revert / type`）
- scope 可选（小括号），写业务域 / 模块名
- subject 一句话动词开头，多数仓库 ≤ 100 字符，Boarding_Desktop ≤ 110 字符；以仓库 `commitlint.config.js` / hook 为准
- **结尾必须带 ticket key**（如 `GRM-1728`），CI 占位用 `TECH-0` / `ENT-0`

### 1.4 容易踩的坑

- 写成 `feat: ...` 漏 ticket key → commitlint `references-empty` fail
- header 超仓库限制 → fail
- 用中文标点 `：`（全角冒号）而不是 `:` → fail
- type 写错（`feature` / `fixed` / `Fix`）→ fail（type 大小写敏感）
- 后端仓库忘记 `git config core.hooksPath .githooks` 启用本地 hook → 本地不报错但 CI 报错

### 1.5 修改已 push 的 commit message

```bash
# 修最近一次 commit message
git commit --amend
git push --force-with-lease  # 注意 with-lease 不是 --force

# 修历史多个 commit（不要这么干，除非确认没人 base）
git rebase -i HEAD~N
```

## 2. Jira ticket 前缀对照

基于 commitlint config / `.githooks/commit-msg` 正则提取，含义大多按字面推断（⚠️ TODO 不在调研范围内的标了 TODO）：

| 前缀 | 推断含义 |
|---|---|
| `GRM-` | Grooming（美容） |
| `GROOM-` | Grooming 老 namespace |
| `MER-` | Merchant（商户后台） |
| `CRM-` | CRM |
| `OBV-` | Online Booking V?（OB） |
| `APP-` | 客户端 App |
| `MOE-` / `MOEG-` | 通用 / 老前缀 |
| `TECH-` | 基础设施 / 技术债 |
| `FDN-` | Foundation |
| `IFRBE-` / `IFRFE-` | Infra Backend / Frontend |
| `FIN-` | Fintech |
| `ERP-` | ERP |
| `CS-` | Customer Service / 客服 |
| `ENT-` | Enterprise |
| `RPT-` | Report |
| `BETA-` | beta 实验 |
| `CA-` | ⚠️ TODO（推测 Customer App / Customer Admin） |
| `PEC-` / `DBO-` / `UF-` / `MC-` / `WT-` / `EN-` / `E2E-` / `DATA-` / `IQ-` / `MP-` / `SEC-` / `GPPA-` | ⚠️ TODO 含义未确认 |

约定：自动化 / bot commit 用 `TECH-0` / `ENT-0` 作占位（如 `ci: build api-docs ... TECH-0`、`chore: update api dependencies ... ENT-0`）。

## 3. PR 模板差异

| 仓库 | 风格 / 关键字段 |
|---|---|
| moego-server-grooming | EN：Description / Changes Type / JIRA / Checklist（Docs / Monitors / DDL） |
| moego-server-common | 中文：特性 & BUG 描述 / Issue 地址 / 实现方案 |
| moego-server-api | 中文：+ 依赖 / 阻塞项 + 8 项质量检查（表结构 / SQL / 索引 / Breaking / 测试 / 自测 / QA） |
| moego-api-definitions | 中文：改动描述 / 是否评审 |
| Boarding_Desktop | 中文：内容变更 / 风险点 / 后端接口依赖 / `router/paths.ts` 变更 → P00 |
| moego-mobile | 中文：后端接口依赖 / Native 变更 + RUNTIME_VERSION |
| OnlineBooking_Go_Web | 中文：后端接口依赖 |
| moego-online-booking-client-web | 中文：后端接口依赖 |
| moego-api-v3 / moego-bff / moego-svc-* / moego / moegoapis | ⚠️ 无 PR 模板 |

**P00 概念**（Boarding 模板里专门列出）：`router/paths.ts` 变更属于"P0 风险"，需要在 PR 描述里明确标注。

## 4. CODEOWNERS

仅 3 个前端仓库有 CODEOWNERS：

- `Boarding_Desktop`
- `moego-mobile`
- `moego-online-booking-client-web`

模式：第一行 `*` + 一组 leads；下面按 `src/<feature>/` 划分 team。明显的有 Fintech Team 把 `PaymentFlow` / `Finance` / `PaymentMethod` 等目录指派给 4-5 个固定 reviewer。

后端仓库**没有** CODEOWNERS——review 走人工 @ + Slack 协调。

## 5. CI 典型 stage 序列

### 5.1 后端 Java / Go svc / moego-bff

统一调远程 reusable workflow：`MoeGolibrary/moego-actions-tool/.github/workflows/preset-{offline,online,schedule-daily}.yml@production`。本地 yaml 只是触发壳，不写 stage。

触发条件：

| workflow | 触发 | 部署 |
|---|---|---|
| `offline.yaml` / `development.yaml` | `push branches: ['*']` | testing（默认） |
| `online.yaml` / `production.yaml` | `push tags: ['*']` 或 `workflow_dispatch` | production |
| `schedule-daily.yaml` | `cron: '0 16 * * *'` | — |

通用 inputs：`environment` / `skip_canary` / `build_only` / `dry_run` / `enable_cd` / `experimental_mat_tag`。

⚠️ TODO：想看具体 stage 序列（lint / test / build / publish / deploy / integration test / canary）需要 clone `MoeGolibrary/moego-actions-tool`。

### 5.2 协议层 / API 文档：moego-api-definitions / moego-bff schema check

**本地完整定义**（不调远程 preset）：

```
lint        — buf-action + lint.sh（用 protobuf-builder docker）
build       — docker build + push ECR + 自动 commit 生成产物
              （commit message: "ci: build api-docs ... TECH-0"）
deploy      — k8s + ArgoCD sync 到 testing
notify      — slack-style curl
publish-npm — npm_publish.sh / build-publish-{openapi,schemas}.sh
              （分支前缀决定 dist-tag，详见 SKILL.md §2）
```

moego-bff 额外有 `schema-breaking-change.yaml`：PR 触发，对 `packages/schemas/**` 与 `server/routes/**` 跑 `pnpm tsx scripts/ci/check-schema-breaking.ts`，结果作为 PR comment。

### 5.3 monorepo `moego/`（Bazel）

最完整本地 pipeline（`app-ci.yaml`）：

```
lint
  → parse-changed-apps        # 按目录变更动态选 backend/frontend app
  → build-frontend / build-backend
       # bazel build + docker buildx + ECR push
       # 自动 tag release/<dir>/<app>/<yyMMdd>.<rev>
  → deploy-frontend / deploy-backend  # 调 app-deploy.yml → ArgoCD sync
  → check-api-integration-test-changes
  → run-api-integration-test           # testing-tester-arm-8x32 runner，30min
  → check-proto-changes
  → publish-npm                        # proto 变更才发包
```

### 5.4 前端 web（Boarding / OB-client-web / OnlineBooking_Go_Web）

复用 `preset-offline.yml` / `preset-online.yml`：

- Boarding 在 online 额外加 `collect-ui`（`pnpm collect-ui --tag`）
- OnlineBooking_Go_Web 有独立 `pull_check.yml`（commitlint + ts-ignore/deps/types/prettier 4 个 check）

### 5.5 mobile：moego-mobile

只用 `workflow_dispatch`（`mobile-build-deploy.yml`）：

- 分支名按 `testflight-*` / `online` → `production` + `appstore`
- 否则 `test` + `adhoc`

## 6. Canary / 灰度

- **canary 普遍存在**：所有 preset-{offline,online} 都接 `skip_canary: boolean`
- `app-deploy.yml`（monorepo）把 canary 写进 `service-branch-image-canary-pairs`，由 ArgoCD 灰度
- **默认值**：backend `canary=true`，frontend monorepo `skip-canary=true`（前端通常不灰度）
- 灰度域名：`*-grey-booking.*.moego.dev`

## 7. Branch 命名规则（pre-push hook）

各仓库 pre-push hook 限制分支名正则（违反会被拒）：

| 仓库 | 允许的分支 |
|---|---|
| Java 后端通用 | `^(feature\|bugfix\|master\|staging\|online\|gate\|main\|release).*$` |
| moego-bff | `^(feature\|bugfix\|refactor\|gate)-…` / `master` / `staging` / `online` / `^release-\d{6}$` / `^release$` |
| OnlineBooking_Go_Web | `^((feature\|bugfix\|gate)-[0-9a-z.-]+\|master\|staging\|online\|release(-[0-9]{6})?)$` |

**关键点**：跨仓库联动开发用 `feature-<topic>` / `bugfix-<topic>`（连字符）；其他形式（斜杠、`feat-`、`fix-`、`hotfix-` 等）一律不发 npm 包（CI skip）。详见 SKILL.md §4。

## 8. Bot / 自动化

- 全部仓库都装了 `gemini-dispatch.yml`（Gemini AI 触发）+ `codeql.yml`（CodeQL 安全扫描）
- Boarding_Desktop 额外：`auto-preview-comment.yml` / `pr-analyze.yml` / `crm-pr-notice.yml` / `sync-feature-domain.yml` / `trigger-e2e.yml` / `weekly-report.yml`
- moego-mobile 额外：`register-ios-device.yml` / `weekly-report.yml`
- moego（monorepo）额外：`security-review.yml` / `build-ci-image.yml` / `api-integration-test.yml`
- **没有** `renovate.json` / `dependabot.yml` / auto-assign
- 依赖升级走 `moego-bff/update-api.yaml`（手动 workflow_dispatch 输入 `api-node-v2` / `api-node` 分支，自动改 lockfile + 开 PR + 发 Slack）

## 9. Release / 版本号

- 没有 `release-please` / `semantic-release` / `changesets`
- monorepo `moego/`：tag 由 `app-ci.yaml` 自动打（`release/<dir>/<app>/<yyMMdd>.<rev>`）
- 其他 svc：手动 push tag 触发 production
- ⚠️ TODO：preset-online 内部是否生成 changelog 未知

## 10. Code review 流程

按惯例（基于 4 个前端仓 AGENTS.md + 仓库 PR 模板倒推）：

1. 创建 PR 后等 CI 跑（CI 必过才能 merge）
2. CODEOWNERS 仓库自动 request review；其他仓库 @ 对应 team
3. AI 工具自动评论：CodeQL（安全）、Gemini（AI review，规则见 moego-bff/GEMINI.md）
4. Reviewer 关注点（基于 PR 模板）：
   - 变更描述清晰、关联 Jira ticket
   - 风险点 / 后端接口依赖标注
   - DB schema / 索引 / breaking change 检查（后端）
   - `router/paths.ts` 变更标 P00（Boarding）
   - Native 变更标 `RUNTIME_VERSION` 影响（mobile）
5. 跨仓库联动 PR：建议在 PR 描述里**互相 link**（"depends on / blocked by"）

## 11. NEVER 规则

- **不要跳过 commit hook**（`--no-verify`）—— commitlint 是为了让 CI 不挂，跳过 hook 不能跳 CI
- **不要 push 不带 ticket 的 commit**（除非确认这条不会进主线，比如自己临时分支）
- **不要在 production / main / master 上直接 commit**——任何仓库 main 都不接受直接 push
- **不要忘记跨仓库 PR 互相 link**——评审者看不到上下游变更会盲改
- **不要把 generated code 改动 commit 在业务 commit 里混着**（如 `src/openApi/*` 改动）——评审噪音大，建议单独一个 `chore: regenerate openapi <TICKET>` commit
- **不要在 mobile 提 Native 改动而不在 PR 描述写 `RUNTIME_VERSION` 影响**——会被 reviewer 打回
