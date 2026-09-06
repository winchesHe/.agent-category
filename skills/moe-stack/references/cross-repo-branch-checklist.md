# 跨仓库 feature 分支推进 checklist

适用于：一个 Jira ticket 涉及 proto / 后端聚合 / 前端展示，需要在多个仓库联动开发。

## 命名约定

所有联动仓库分支名**保持一致**：

```
feature-<jira-ticket-lowercase>-<topic-keywords>

例：
feature-grm-1728-isnewcustomer-aggregation
feature-erp-6446-abandoned-bookings-cleanup
```

约束（违反任一条 → CI 不发包 → 前端拉不到 dist-tag）：

- 前缀**必须**是 `feature-` 或 `bugfix-`（连字符不斜杠），CI case 严格 `feature-* | bugfix-*` 匹配
- ❌ 不要用 `feature/<topic>`（斜杠）、`feat-<topic>`、`fix-<topic>`、`hotfix-<topic>`、`release-<topic>`、`chore-<topic>`、无前缀——这些全部 skip 发包
- topic 全小写 + 连字符
- 含 Jira ticket key 便于反查
- 主线分支：`main` 始终发 latest；`production` 仅 `moego-api-definitions` 也发 latest，`moego-bff` 不识别

## 推送顺序与验证

按顺序进行，每一步**做完验证再下一步**：

### Step 1：moego-api-definitions

```bash
cd repo/back-end/moego-api-definitions
git checkout -b feature-<topic>

# 如果有 proto 改动，按需修改 .proto 文件
# 如果没有 proto 改动，至少推一个空 commit 触发 CI 发包
git commit --allow-empty -m "chore: trigger api-web publish <TICKET>"

git push -u origin feature-<topic>
```

**验证**：CI 跑完后 nexus 上应该有 dist-tag：

```bash
sleep 60  # 等 CI 发包
npm view "@moego/api-web@<topic-without-prefix>" version \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/
# 期望返回类似 1.109.0-<topic>.<timestamp>
```

如果 404：

- 检查 `gh run list --repo MoeGolibrary/moego-api-definitions --branch feature-<topic>` 是否跑完
- 检查 workflow log 是否真的执行了 publish step

### Step 2：moego-api-v3（BFF 层）

```bash
cd repo/back-end/moego-api-v3
git checkout -b feature-<topic>

# 实现业务聚合 / 字段填充 / 转发逻辑

./gradlew test --tests "*<NewClass>Test"  # 跑相关单测
./gradlew test  # 全量跑无回归

git add ...
git commit -m "feat(<scope>): <subject> <TICKET>"
git push -u origin feature-<topic>
gh pr create --title "..." --body "..."
```

**验证**：

- PR `Build and deploy` workflow success
- 部署到 testing/staging 后用 grpcurl 调对应接口确认字段
- ⚠️ 这里 push **不会**发布 api-web，所以不影响前端拉版本

### Step 3：moego-svc-*（业务服务，如有）

跟 step 2 类似流程，每个相关 svc 仓库单独 PR。

### Step 4：前端（Boarding_Desktop / moego-mobile / ...）

```bash
cd repo/front-end/<frontend-repo>
git checkout main
git pull
git checkout -b feature-<topic>

# 升级 @moego/api-web 到对应 dist-tag 的具体版本
VERSION=$(npm view "@moego/api-web@<topic-without-prefix>" version \
  --registry=https://nexus.devops.moego.pet/repository/npm-local/)
# 改 package.json 的 "@moego/api-web": "$VERSION"
# 注意：dist-tag 版本号会随后端新 push 更新时间戳，
# 想拉最新就重新 fetch + 改 + npm install

npm install  # 同步 lockfile

# 实现 UI / 渲染逻辑

# 联调
npm run dev  # 跑起来对着 backend 联调

git add ...
git commit -m "feat(<scope>): <subject> <TICKET>"
git push -u origin feature-<topic>
gh pr create --title "..." --body "..."
```

**验证**：

- 浏览器实际跑一遍 happy path 看字段是不是真的展示
- 边界 case（字段缺失 / null / false）UI 是否合理降级
- 看 React DevTools / Redux state 字段确实传到组件

## 常见踩坑

| 场景 | 错误 | 正确做法 |
|---|---|---|
| Backend 改完直接通知前端 | 漏 Step 1，前端 install 失败 | api-definitions 也要建分支推上 |
| 用 `feature/<topic>` 斜杠形式 | 部分团队 CI 对斜杠处理不一致 | 统一用 `feature-<topic>` 连字符 |
| package.json 写 `<tag>@latest` | npm 不解析这种语法 | fetch 实际 version 写进去 |
| 多次 push backend 但前端没重新 npm install | 拉到旧时间戳版本 | 每次 backend 改完，前端重新 fetch dist-tag + npm install |
| Backend PR merge 到 main 后忘了升前端 SDK | 前端 main 还在用 feature dist-tag | merge 前后前端 SDK 切回 latest（main 的版本） |

## Merge 顺序

通常 backend 先 merge，前端跟进：

```
1. api-definitions PR merge → @moego/api-web latest dist-tag 更新
2. api-v3 PR merge → 部署到 production
3. 前端 PR：把 package.json 的 @moego/api-web 从 feature dist-tag 版本
   改回 latest（拉 main 那条线的版本号），然后 merge
4. 前端部署 → 用户可见
```

step 3 很容易忘——前端 PR 不能直接 merge 时还指向 feature 分支的 dist-tag，否则一旦后端 feature 分支删除/迁移，前端 main 会拉不到包。
