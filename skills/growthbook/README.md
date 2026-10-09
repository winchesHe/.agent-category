# growthbook skill

通过 GrowthBook Management API 管理环境、项目、Feature Flags（下文也称"白名单 / 开关"）、实验、属性和指标，并通过官方 SDK 评估某组 attributes 的真实命中结果。统一入口为 `scripts/growthbook.py`。

> 术语别名：GrowthBook 亦写作 **gw / GW / GB**；feature flag 亦叫 **白名单 / 白名单 flag / 开关 / 灰度开关**。遇到这些说法都会走本 skill。

## 目录结构

```
growthbook/
├── README.md           # 本文件：安装与使用速查
├── SKILL.md            # Skill 指引：子命令 ↔ REST API 映射、示例、故障排查
├── .env.example        # Management API 与 SDK Connection 配置模板
├── package.json        # eval-feature 使用的官方 Node SDK
├── references/         # 按技术栈加载的 SDK 集成指南
└── scripts/
    ├── growthbook.py   # 统一入口（11 个子命令，内置 .env 加载）
    ├── growthbook-sdk-eval.mjs # 官方 SDK evaluator
    └── smoke.py        # 连通性 smoke（覆盖全部子命令，写接口默认跳过）
```

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `GROWTHBOOK_API_TOKEN` | 管理命令必填 | — | Management API Bearer token；兼容旧 `GB_TOKEN` |
| `GROWTHBOOK_API_BASE_URL` | ❌ | `https://api.growthbook.io` | Management API 地址；兼容旧 `GB_APP_ORIGIN` |
| `GROWTHBOOK_SDK_API_HOST` | `eval-feature` 必填 | — | SDK Connection API host |
| `GROWTHBOOK_SDK_CLIENT_KEY` | `eval-feature` 必填 | — | SDK Connection client key |
| `GROWTHBOOK_DOTENV` | ❌ | — | 显式指定 `.env`；兼容旧 `GB_DOTENV` |

## 通过 `.env` 加载

复制示例并填入 token：

```bash
cp .env.example .env
# 编辑 .env，填入 Management API 与按需的 SDK Connection 配置
```

脚本（`growthbook.py` 与 `smoke.py`）启动时会按顺序查找 `.env` 并加载（**已存在的环境变量不会被覆盖**）：

1. `$GROWTHBOOK_DOTENV` 或旧 `$GB_DOTENV`（若设置）
2. 当前工作目录 `./.env`
3. `scripts/.env`
4. skill 根目录 `./.env`（推荐位置）

支持 `KEY=value`、`KEY="value"`、`KEY='value'`、`export KEY=value`，以 `#` 开头的行视为注释。不依赖 `python-dotenv`，纯标准库实现。

## 快速开始

```bash
export GROWTHBOOK_API_TOKEN="<your_token>"
# 自托管：export GROWTHBOOK_API_BASE_URL="https://your-gb.example.com"

python3 scripts/growthbook.py get-projects
python3 scripts/growthbook.py get-feature-flags --project "Growth" --q "checkout"
```

## 子命令一览

| 子命令 | 作用 |
|---|---|
| `get-environments` | 列出所有环境 |
| `get-projects` | 列出所有项目 |
| `resolve-project-id --project <nameOrId>` | 解析项目名/ID |
| `create-feature-flag --body-file <path\|-> \| --body-json <json>` | 创建 feature flag |
| `create-force-rule --feature-id <id> --env <env> --value <v> [...]` | 在指定环境追加/更新 force 规则 |
| `eval-feature --feature-id <key> --attributes-json <json>` | 通过官方 SDK 本地评估 feature |
| `get-feature-flags [--feature-flag-id <id>] [--project <nameOrId>] [--q <kw>] [--all] [--limit <n>]` | 获取 feature 列表或详情；默认单页，加 `--q` 或 `--all` 翻页到末尾 |
| `list-feature-keys [--project-id <id>]` | 列出 feature keys |
| `get-experiments [--experiment-id <id>] [--mode full\|summary]` | 实验列表/详情；`full` 合并 results |
| `get-attributes` | 用户属性 |
| `get-metrics [--metric-id <id>] [--project-id <id>]` | 指标；`fact__` 前缀走 fact-metrics |

完整示例见 [`SKILL.md`](./SKILL.md)。

## 连通性 smoke 脚本

`scripts/smoke.py` 覆盖 `growthbook.py` 全部 11 个子命令，自动从前一步响应里挑取 ID（project、feature、experiment、metric、fact metric），无需手动准备数据。

```bash
export GROWTHBOOK_API_TOKEN="<your_token>"
export GROWTHBOOK_SDK_API_HOST="<sdk_api_host>"
export GROWTHBOOK_SDK_CLIENT_KEY="<sdk_client_key>"
python3 scripts/smoke.py
```

**环境变量**

| 变量 | 作用 |
|---|---|
| `SMOKE_WRITE` | 设为 `1` 时，额外跑写接口：创建 `smoke_<ts>` 临时 feature flag，再追加一条 force 规则（需要手动清理） |
| `SMOKE_PROJECT` | 指定项目名或 ID；默认取 `get-projects` 返回的第一个 |

**行为**

- 每步打印 `PASS` / `SKIP` / `FAIL`
- 任一步失败立即退出并保留 `growthbook.py` 的 stderr
- 数据依赖缺失（例如项目里没有任何 feature/experiment/metric）时对应用例 `SKIP`，不会 FAIL

## 退出码

- `0`：成功
- `1`：参数缺失、Management token 未设置、HTTP 非 2xx、网络错误、JSON 解析失败等

## 依赖

- Python ≥ 3.9（管理命令仅标准库）
- Node ≥ 18；首次使用 `eval-feature` 前运行 `pnpm install --prod --frozen-lockfile`
