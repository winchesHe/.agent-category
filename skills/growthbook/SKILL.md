---
name: growthbook
description: >-
  GrowthBook Management API, SDK-backed eval-feature, and official SDK
  integration guidance. Use for environments, projects, feature flags,
  experiments, attributes, metrics, force rules, real feature evaluation, or
  implementing and reviewing GrowthBook in React, React Native, SSR, Go, Java,
  Node.js, Hono, Python, FastAPI, and other supported runtimes. Entry point
  scripts/growthbook.py; management commands use GROWTHBOOK_API_TOKEN, while
  eval-feature uses GROWTHBOOK_SDK_API_HOST and GROWTHBOOK_SDK_CLIENT_KEY.
---

# GrowthBook Skill

> 别名：gw · GW · GB · 白名单 · 开关 · 灰度开关

## 1. 术语对照

| 用户说法 | 实际含义 | 对应子命令 |
|---|---|---|
| gw / GW / gb / GB / GrowthBook | GrowthBook 平台 | 全部 |
| feature / feature flag / 特性开关 | feature flag | `get-feature-flags` / `create-feature-flag` |
| 白名单 / 白名单 flag / 开关 / 灰度开关 | feature flag（通常 force 规则按条件放行） | `create-feature-flag` + `create-force-rule` |
| 实验 / AB 实验 | experiment | `get-experiments` |
| 指标 / metric / fact metric | metric / fact metric | `get-metrics` |

## 2. 脚本位置

**脚本入口始终相对于本 SKILL.md 所在目录：**

```
<本 SKILL.md 所在目录>/scripts/growthbook.py
```

> 解析规则：你是从某个绝对路径 `cat` / 读取到这份 SKILL.md 的，**那个目录就是 skill 根**。脚本必然在它的 `scripts/` 子目录下。**不要用 CWD 相对路径，始终用 SKILL_DIR 绝对路径。**

1. 已知本 SKILL.md 的绝对路径时（最常见，直接用读取它的路径）：
   ```bash
   SKILL_DIR="<本 SKILL.md 所在目录>"   # 即你读取 SKILL.md 的那个目录
   python3 "$SKILL_DIR/scripts/growthbook.py" <subcommand> [flags]
   ```
2. 不确定 SKILL.md 在哪时，按文件名向上/向下定位 skill 根：
   ```bash
   SKILL_DIR="$(dirname "$(find . -type f -path '*/growthbook/SKILL.md' 2>/dev/null | head -n1)")"
   python3 "$SKILL_DIR/scripts/growthbook.py" <subcommand> [flags]
   ```
3. 仍找不到则直接搜脚本入口，取其绝对路径调用：
   ```bash
   find . -type f -path '*/growthbook/scripts/growthbook.py' 2>/dev/null
   ```

完整目录结构（以 skill 根 `<SKILL_DIR>` 为基准，与部署位置无关）：

```
<SKILL_DIR>/                  # 本 SKILL.md 所在目录
├── SKILL.md
├── .env                      # 复制自 .env.example，与 SKILL.md 同目录
├── .env.example
├── package.json              # eval-feature 的 Node SDK 依赖
├── pnpm-lock.yaml            # Node SDK 依赖锁定
├── references/               # 官方 SDK 导航与 MoeGo 技术栈指引
└── scripts/
    ├── growthbook.py         ← 所有子命令入口
    ├── growthbook-sdk-eval.mjs ← 官方 @growthbook/growthbook SDK 本地评估入口
    └── smoke.py
```

`.env` 必须放在 `<SKILL_DIR>/`（与 SKILL.md 同目录），脚本启动时自动加载；也可用 `GROWTHBOOK_DOTENV=<path>` 指定绝对路径。

后续示例为了简洁全部用 `python3 scripts/growthbook.py ...` 形式，**AI 调用时必须替换为 `$SKILL_DIR/scripts/growthbook.py` 绝对路径**。

## 3. 前置条件

| 项 | 说明 |
|---|---|
| Python | ≥ 3.9，管理命令只用标准库 |
| Node | ≥ 18，`eval-feature` 依赖本 skill 的 `@growthbook/growthbook` |
| `@growthbook/growthbook` | 首次使用 `eval-feature` 前，必须在本 SKILL.md 所在目录执行 `pnpm install --prod --frozen-lockfile` |
| `GROWTHBOOK_API_TOKEN` | GrowthBook Management API Bearer token，管理命令必填。可放 `.env`（与 SKILL.md 同目录）；不能用于 eval-feature |
| `GROWTHBOOK_API_BASE_URL` | Management API base URL，可选，默认 `https://api.growthbook.io`；供管理命令请求 `/api/v1/*` |
| `GROWTHBOOK_SDK_API_HOST` | SDK Connection API host，`eval-feature` 必填；自托管时可以与 `GROWTHBOOK_API_BASE_URL` 相同，但语义仍是 SDK Connection |
| `GROWTHBOOK_SDK_CLIENT_KEY` | SDK Connection client key，`eval-feature` 必填 |
| `GROWTHBOOK_SDK_TIMEOUT_MS` | SDK 初始化 timeout，可选，默认 10000ms |

兼容旧配置：`GB_TOKEN`、`GB_APP_ORIGIN`、`GB_DOTENV` 分别是前三个 Management
变量的旧别名；新变量优先。旧别名只服务本地平滑迁移，不适用于 SDK eval。

### 3.1 SDK 集成前置检查

处理 SDK 实现、review 或排障时，先执行以下步骤：

1. 读取目标仓库的 `AGENTS.md` 和存在的 `CONTEXT.md`。
2. 读取目标仓库的 lockfile 或依赖清单，确认实际 SDK、版本和 wrapper。
3. 打开 [GrowthBook 官方 SDK 导航](https://docs.growthbook.io/lib/) 和对应 SDK 当前文档。
4. 先复用目标仓库现有 wrapper、生命周期和 attributes 约定。
5. 从目标环境配置读取 SDK API host 和 client key。禁止把配置值写进代码、文档或日志。
6. 明确 fallback、tracking 和并发隔离，再生成版本相关代码。

不要用本 Skill 自带的 Node 依赖版本推断目标仓库版本。该依赖只服务 `eval-feature`。

按任务读取以下参考文件：

| 任务 | 必读文件 |
|---|---|
| 选择任意官方 SDK | [`references/sdk-navigation.md`](references/sdk-navigation.md) |
| React、React Native、SSR | [`references/react-react-native-ssr.md`](references/react-react-native-ssr.md) |
| Go Server | [`references/go-server.md`](references/go-server.md) |
| Java Spring | [`references/java-spring.md`](references/java-spring.md) |
| Node Server、Hono | [`references/node-hono.md`](references/node-hono.md) |
| Python Async、FastAPI | [`references/python-fastapi.md`](references/python-fastapi.md) |

## 4. 子命令速查

| 子命令 | REST | 关键 flags |
|---|---|---|
| `get-environments` | `GET /environments` | — |
| `get-projects` | `GET /projects` | — |
| `resolve-project-id` | `GET /projects` | `--project <nameOrId>` |
| `get-feature-flags` | `GET /features` 或 `/features/{id}` | `--feature-flag-id` / `--project` / `--q` / `--all` / `--limit` |
| `list-feature-keys` | `GET /feature-keys` | `--project-id` |
| `create-feature-flag` | `POST /features` | `--body-file <path\|->` / `--body-json <json>` / `--execute` |
| `create-force-rule` | `GET /features/{id}` + `POST /features/{id}` | `--feature-id` `--env` `--value` [`--condition` `--description` `--enabled` `--id` `--execute`] |
| `get-experiments` | `GET /experiments[/{id}][/results]` | `--experiment-id` / `--mode full\|summary` |
| `get-attributes` | `GET /attributes?limit=100` | — |
| `get-metrics` | `GET /metrics` + `/fact-metrics`；或 `/metrics/{id}` / `/fact-metrics/{id}` | `--metric-id`（`fact__` 前缀→fact 指标） / `--project-id` |
| `eval-feature` | 官方 `@growthbook/growthbook` SDK 本地评估 | `--feature-id <key>` / `--attributes-json <json>` / `--url` / `--raw` |

分页规则：`get-feature-flags` 默认单页；`--q` 或 `--all` 会自动翻页，`--limit` 直接参与分页停止条件，不再先扫完整个列表再截断。

## 5. 接口返回字段

> 仅列 AI 判断匹配时最常用的字段。完整定义见 [GrowthBook OpenAPI](https://docs.growthbook.io/api)。

### 5.1 Environment（`get-environments`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 环境 key，如 `production` |
| `description` | string | 环境说明 |
| `defaultState` | boolean | 新 feature 在此环境默认启用状态 |
| `toggleOnList` | boolean | UI 列表是否显示开关 |
| `projects` | string[] | 生效项目 ID（空=全部） |

### 5.2 Project（`get-projects` / `resolve-project-id`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | `prj_xxx` |
| `name` | string | 项目名 |
| `description` | string | — |
| `settings` | object | 项目级默认（如 `statsEngine`） |
| `dateCreated` / `dateUpdated` | ISO string | — |

`resolve-project-id` 脚本本地合成返回 `{ id, name }`。

### 5.3 Feature（`get-feature-flags` / `create-feature-flag`）

顶层：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | feature key（用户口中的"白名单名字"） |
| `project` | string | 所属项目 ID |
| `valueType` | `boolean` \| `string` \| `number` \| `json` | 值类型 |
| `defaultValue` | string | 序列化后的默认值 |
| `tags` | string[] | — |
| `owner` / `description` / `archived` | — | — |
| `environments` | map | key=envId，值见下表 |
| `revision` | object | `{ version, comment, date, publishedBy }` |

`environments[env]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `enabled` | boolean | 该环境是否启用 |
| `defaultValue` | string | 该环境默认值 |
| `rules` | array | 规则链，按顺序匹配 |
| `definition` | string | SDK 消费的最终 JSON |

`rules[]` 常见字段：

| 字段 | 出现场景 | 说明 |
|---|---|---|
| `id` / `type` / `description` / `enabled` | 所有 | `type`：`force` \| `rollout` \| `experiment` \| `experiment-ref` |
| `condition` | 所有 | GrowthBook 条件 JSON（"白名单里有哪些人"看这个） |
| `value` | `force` | 按 `valueType` 序列化 |
| `coverage` / `hashAttribute` / `value` | `rollout` | 0-1 灰度比例 |

列表响应额外字段：`limit` / `offset` / `count` / `total` / `hasMore` / `nextOffset`。

### 5.4 feature-keys（`list-feature-keys`）

返回 `string[]`，仅 key 名；"有哪些 flag"用这个最轻。

### 5.5 Experiment（`get-experiments`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `name` / `project` / `owner` | — | — |
| `trackingKey` | string | 埋点 `experiment_id` 值 |
| `hypothesis` / `description` | string | — |
| `hashAttribute` / `fallbackAttribute` | string | 分流用户标识 |
| `status` | `draft` \| `running` \| `stopped` | — |
| `variations` | array | `{ id, key, name, description, screenshots }` |
| `phases` | array | `{ name, dateStarted, dateEnded, coverage, trafficSplit }` |
| `goalMetrics` / `secondaryMetrics` / `guardrailMetrics` | string[] | metric ID 列表 |
| `archived` / `tags` | — | — |

`--mode full` 追加 `results.snapshot`：

```
snapshot.results[].variationId
snapshot.results[].users
snapshot.results[].metrics[metricId] = { value, chanceToWin, ciLow, ciHigh, risk }
```

### 5.6 Attribute（`get-attributes`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `property` | string | 属性 key（`id` / `deviceId` / `country` …） |
| `datatype` | `string` \| `number` \| `boolean` \| `enum` \| `secureString` | — |
| `format` / `enum` | — | 取值校验 |
| `projects` | string[] | — |
| `hashAttribute` / `archived` | boolean | — |

### 5.7 Metric / FactMetric（`get-metrics`）

公共字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | fact 指标以 `fact__` 前缀标识 |
| `name` / `description` | string | — |
| `projects` / `tags` | string[] | — |
| `datasourceId` | string | — |
| `inverse` / `cappingSettings` / `windowSettings` | — | 行为参数 |

Metric 专属：

| 字段 | 说明 |
|---|---|
| `type` | `binomial` \| `count` \| `duration` \| `revenue` |
| `sql` / `aggregation` | 指标查询 |
| `behavior` | `{ goal, cap, capValue, minSampleSize, riskThreshold* }` |

FactMetric 专属：

| 字段 | 说明 |
|---|---|
| `metricType` | `proportion` \| `mean` \| `ratio` \| `quantile` |
| `numerator` / `denominator` | `{ factTableId, column, filters[] }` |

列表响应：`{ metrics: [...], factMetrics: [...] }`，两者都保证是数组。

## 6. 行为约定

- 管理命令鉴权：优先使用 `GROWTHBOOK_API_TOKEN`，兼容 `GB_TOKEN`；两者均未设置时直接报错退出。
- 输出：stdout 为 JSON，便于 `| jq`。
- 错误：非 2xx 响应把 `status + body` 打到 stderr 并以非零退出码退出。
- HTTP：所有请求默认 20 秒 timeout。
- `eval-feature`：
  - 通过 Python CLI 调用 `scripts/growthbook-sdk-eval.mjs`，再使用官方 `@growthbook/growthbook` SDK 本地评估。
  - 必须配置 `GROWTHBOOK_SDK_API_HOST` 和 `GROWTHBOOK_SDK_CLIENT_KEY`。`GROWTHBOOK_SDK_API_HOST` 应来自 SDK Connections；自托管实例里它可能与 `GROWTHBOOK_API_BASE_URL` 是同一个 host。
  - **不使用 `GROWTHBOOK_API_TOKEN`**。Management API 和 `GROWTHBOOK_API_TOKEN` 不能做 eval，也不能证明某个用户真实命中特定 feature。
  - 默认输出 masked attributes，避免把 email、token、auth 等敏感属性原文写进 stdout。
  - 输入属性里如果只有 `platform`，脚本会自动补 MoeGo 历史字段 `platfrom`；AI 对外确认和内部调用都应优先使用 `platfrom`。
  - **禁止用 `/api/v1/features` 返回的 rules 手写 GrowthBook evaluator**。判断用户是否命中特定 feature flag 时必须调用 `eval-feature`，让官方 SDK 执行规则、hash、rollout、experiment 和默认值逻辑。
- `create-feature-flag`：默认只输出 dry-run JSON；必须显式加 `--execute` 才会真实 `POST`。
- `create-force-rule`：
  - 默认只输出 dry-run JSON；必须显式加 `--execute` 才会真实 `POST`
  - dry-run 输出包含 `dry_run`、目标 `endpoint`、`payload`、`feature_id`、`environment`、`rule_diff`
  - 先 `GET` feature，再按 `valueType` 解析 `--value`
  - `boolean` 只接受 `true` / `false` 字面量，其他值直接报错
  - `number` 先校验为合法数字，再把原始数字字符串写入 payload
  - `json` 先校验为合法 JSON，再把规范化后的序列化字符串写入 payload
  - `string` 按原样写入 payload
  - 不覆盖其他环境，仅改目标 `env` 的 `rules`
  - `--id` 命中已有规则则就地替换，否则追加

## 7. AI 调用约束（必须遵守）

| 场景 | 约束 |
|---|---|
| 用户用中文/口语/描述性名称指代 feature（如"税费开关"、"tax by fee"、"首页新版"） | **AI 必须自己搜索解析 key**：用 `get-feature-flags --all --q <关键词>`（必要时中英文各搜一次，或取关键词子串）在返回里按 `id` / `description` / `tags` 匹配；**禁止**要求用户提供准确的 feature key |
| 搜索命中唯一 | 直接作为目标，进入"写命令二次确认"流程 |
| 搜索命中多个 | 用**自然语言**把候选列给用户（key + 项目 + description），让用户确认是哪一个 |
| 搜索 0 结果 | 告诉用户没搜到，并问"是否新建"或"请再给一个接近的名字/描述"，不要直接创建 |
| 查找 feature 列表 | 默认**全量**：必须带 `--all`；有关键词叠 `--q`，有项目叠 `--project`。不要用默认单页 10 条得结论 |
| 只读命令 | 可直接执行 |
| 判断某个 company / business / enterprise / channel / platfrom / email 是否真实命中特定 feature | **必须调用 `eval-feature`**。禁止只看 `/api/v1/features` rules 后手写 GrowthBook evaluator 或自行模拟命中逻辑 |
| 传平台属性 | 使用 MoeGo 历史字段 `platfrom`；如用户或上游只给了 `platform`，可以同时传 `platform` 和 `platfrom`，但不要把 `platfrom` 改成 `platform` |
| `eval-feature` 返回 `found=false` | 只能说明 SDK payload 里没有这个 feature key；**不能解释成默认关闭**，应先核对 feature key、client key 对应环境和 SDK payload 数据新鲜度 |
| `eval-feature` 返回 `source=unknown` | 只能说明响应没有暴露明确来源；**不能声称命中某条具体规则**，如需规则说明再用管理命令只读查询 feature 详情 |
| 写类命令（create / update / delete） | **必须先向用户用自然语言二次确认**；未确认前如需预演，只能在 AI 内部执行**不带 `--execute`** 的 dry-run；获得明确"确认"后，AI 内部真实执行必须在相同命令上**追加 `--execute`** |
| 写类命令有歧义（同名 flag 跨项目、`--id` 是否命中既有规则） | 先只读核实，再回二次确认 |
| 目标环境未指定 | **必须询问 `development` 还是 `production`**（当前仅此两个环境）。禁止默认挑一个 |
| 向用户展示 / 确认时 | **禁止直接贴 shell 命令、CLI flags、JSON 请求体**。用自然语言描述：要改哪个 feature、哪个环境、放行哪些 business、默认值是什么、是追加还是替换已有规则。命令/JSON 只存在于 AI 内部执行时 |
| 向用户反馈规则明细 / 执行结果时 | **禁止直接返回 `fr_xxx`、UUID、revision version 等内部标识**。必须翻译成用户可理解的自然语言，例如"空规则已删除"、"现在只剩 2 条 business 放行规则：104585 和 125766"。如必须区分多条规则，优先用"104585 那条规则"、"第 2 条规则"这类说法，不要把内部 ID 直接抛给用户 |

## 7.1 自然语言 → 参数 对照（AI 内部使用，不要展示给用户）

| 用户说法 | 语义 | AI 内部调用 |
|---|---|---|
| "给 feature `X`，biz id 为 `123` 的用户开白" | 在目标环境追加 force 规则，`condition = { businessId: { $in: ["123"] } }`，`value = true` | `create-force-rule --feature-id X --env <dev\|prod> --value true --condition '{"businessId":{"$in":["123"]}}'` |
| "biz `[a, b, c]` 开白" | `$in` 多值 | `--condition '{"businessId":{"$in":["a","b","c"]}}'` |
| "把 biz `y` 追加到 `X` 的白名单" | 读→把 `y` 合进**已有**同字段 `$in`→`--id <既有规则 id>` 更新 | 先 `get-feature-flags --feature-flag-id X` 合并后 `create-force-rule --id ... --condition ...` |
| "取消 `X` 的开白 / 删掉某个 biz" | 编辑既有 force 规则 | 读→改→`create-force-rule --id ...`（二次确认） |
| 描述性名称（"税费相关那个开关"） | 先搜：`get-feature-flags --all --q <关键词>` → 多结果用自然语言列给用户确认 | — |
| 未指明环境 | 先问用户 `development` 还是 `production` | — |

属性 key 说明：用户口中"biz / business id"通常对应 attribute `businessId`；若 `get-attributes` 显示实际 key 不同（`bizId` / `business_id` 等），以实际 key 为准，并在**自然语言二次确认**里告知用户"我这边会用属性 `xxx`"。

### 7.2 二次确认话术模板（给用户看的样式）

> ✅ 正确示例（自然语言）：
> "我要在 **development 环境** 给 feature `enable_tax_by_zipcode`（税费开关）加一条放行规则：business id 为 `103622` 时返回 `true`。这会**追加**一条新规则，不会动其他规则。确认执行吗？"
>
> "如果只是预演，我会在内部先跑一次 **dry-run** 看 payload 和 rule diff；只有你明确确认后，我才会在内部对同一操作追加 `--execute` 做真实写入。"
>
> "feature `enable_grooming_cancel_reschedule_request` 的 **production 环境**里，之前那条空规则已经删除；现在只剩 2 条 business 放行规则，分别对应 `104585` 和 `125766`。"

> ❌ 错误示例（绝不要这样发给用户）：
> "将执行：`python3 .../growthbook.py create-force-rule --feature-id enable_tax_by_zipcode --env development --value true --condition '{...}'`，回复确认即可"
>
> "production 里删掉了 `fr_xxx`，还剩 `fr_xxx` 和 `fr_xxx`。"

## 8. 示例

```bash
# 环境 / 项目
python3 scripts/growthbook.py get-environments
python3 scripts/growthbook.py get-projects
python3 scripts/growthbook.py resolve-project-id --project "Growth"

# feature
python3 scripts/growthbook.py get-feature-flags --feature-flag-id my_feature
python3 scripts/growthbook.py get-feature-flags --all                      # 默认全量
python3 scripts/growthbook.py get-feature-flags --all --project "Growth" --q checkout
python3 scripts/growthbook.py list-feature-keys --project-id prj_abc
python3 scripts/growthbook.py eval-feature \
  --feature-id checkout_flow \
  --attributes-json '{"business":"10682","platfrom":"web"}'
python3 scripts/growthbook.py create-feature-flag --body-file ./new-flag.json             # dry-run 预演
python3 scripts/growthbook.py create-feature-flag --body-file ./new-flag.json --execute   # 获得明确确认后真实写入
python3 scripts/growthbook.py create-force-rule \
  --feature-id my_feature --env production \
  --value true --condition '{"plan":"premium"}' --description "Premium override"       # dry-run 预演
python3 scripts/growthbook.py create-force-rule \
  --feature-id my_feature --env production \
  --value true --condition '{"plan":"premium"}' --description "Premium override" --execute

# 实验 / 属性 / 指标
python3 scripts/growthbook.py get-experiments --experiment-id exp_123 --mode full
python3 scripts/growthbook.py get-attributes
python3 scripts/growthbook.py get-metrics --metric-id fact__fm_456
```

## 9. 故障排查

| 现象 | 处理 |
|---|---|
| `环境变量 GROWTHBOOK_API_TOKEN 未设置` | `export GROWTHBOOK_API_TOKEN=...` 或在 `.env` 中配置 |
| 401 / 403 | token 权限不足或已过期 |
| 404 `/features/{id}` | 核对 feature key 大小写/拼写 |
| 自托管 404 返回 HTML | 确认 `GROWTHBOOK_API_BASE_URL` 指向 Management API host（非前端域），不带结尾 `/` |
| `环境变量 GROWTHBOOK_SDK_API_HOST 未设置` | 为 `eval-feature` 配置 SDK Connection API host；从 SDK Connections 页面复制，自托管时可能与 Management API host 相同 |
| `环境变量 GROWTHBOOK_SDK_CLIENT_KEY 未设置` | 为 `eval-feature` 配置 SDK Connection client key；确认它对应要评估的 GrowthBook 环境 |
| `eval-feature` 返回 `found=false` | 先核对 feature key、`GROWTHBOOK_SDK_CLIENT_KEY` 对应环境、SDK payload 数据同步状态；不要解释成默认关闭 |
| `eval-feature` 返回 `source=unknown` | 只能说明 SDK 未暴露明确来源；不要声称命中特定规则，必要时再只读查询 feature 详情 |
| `无法加载 @growthbook/growthbook` | 在 skill 根目录执行 `pnpm install --prod` |
| `ModuleNotFoundError` | 使用 `python3`，Python 入口仅用标准库 |
