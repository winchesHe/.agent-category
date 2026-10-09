---
name: sentry
metadata:
  version: 1.0.4
description: >-
  通过 scripts/sentry.py 只读查询 issue、event、tag 分布与多 event 崩溃分析，
  支持异常链、仓库和修复边界候选，以及跨系统调查线索。
  触发：Sentry issue/event URL、客户端崩溃、版本或平台影响、受影响用户、breadcrumbs、stack trace。
  不触发：Performance transaction、APM 指标、SDK 配置、本地纯代码排错或 Sentry 状态写入。
---

# Sentry Skill

用只读 Sentry API 获取 issue、event、tag 分布和 crash 证据，并把观测事实、工具推断、待验证假设与跨系统 handoff 分开表达。

## 前置条件

| 项 | 要求 |
|---|---|
| Python | 3.9+ |
| 运行方式 | `uv run`，脚本内联声明 `requests` 依赖 |
| 必填配置 | Skill 根目录 `.env` 中的 `SENTRY_AUTH_TOKEN`；生产 Agent 优先使用目标组织的 Internal Integration token，并授予 Organization Read、Project Read、Issue & Event Read |
| 常用配置 | `SENTRY_BASE_URL`；从 URL 读取的 `SENTRY_ORG_SLUG`；可留空的 `SENTRY_DEFAULT_PROJECT` |

## 脚本位置

从本文件的绝对路径取得 Skill 根目录，不根据当前工作目录猜测：

```bash
SKILL_DIR="<本 SKILL.md 所在目录>"
uv run "$SKILL_DIR/scripts/sentry.py" <subcommand> [flags]
```

`.env` 放在 `$SKILL_DIR/`。后文只写子命令和参数，实际执行始终使用上述绝对入口。

## 子命令速查表

| 子命令 | 适用问题 | 必要输入 |
|---|---|---|
| `get-issue` | issue 元数据和可选 event 上下文 | `--url` 或 `--issue-id` |
| `fetch-event` | 指定 event 的 stack、breadcrumbs 和 tags | event URL，或 `--issue-id` + `--event-id` |
| `list-issues` | 最近、新增、高频或高影响 grouped issues | `--query`；按需 `--sort` |
| `list-issue-events` | 同一 issue 内按环境、版本、用户或 trace 找样本 | `--url` 或 `--issue-id` |
| `tag-values` | 判断 release、平台、用户或页面集中度 | issue 标识 + `--tag` |
| `list-projects` | 发现 project slug | 可选 `--query` |
| `analyze` | 单 issue 的多 event 聚合 crash 分析 | issue 标识；默认 `--mode issue --events 5` |

详细 query 与 sort 语法见 [references/sentry-query-syntax.md](references/sentry-query-syntax.md)。分析字段与判断方法见 [references/crash-analysis.md](references/crash-analysis.md)。

## 通用 flag

普通读取命令支持 `--format json|human|summary`，默认 json；human 摘要走 stderr。分析命令使用 `--target json|markdown|slack|jira|pr` 选择报告格式，默认 json；不同时传 --format。非 JSON 分析目标是报告文本输出，字段结构见 output-contract.md。

配置优先级是进程环境 > CWD/.env > Skill/.env；`SENTRY_DISABLE_DOTENV=1` 禁用文件读取。`SENTRY_MAX_RETRIES` 限制为 0–5。

## 核心原则

1. **先确定证据问题，再选择最短路径**：区分 issue 发现、单 event 取证、同 issue 多样本对比、影响面判断和根因分析；不为“更全面”自动扩展调用，也不重复读取当前响应已经包含的 issue 或 selected event。
2. **结论强度不超过证据强度**：latest event 是单个样本，有限 event 列表不是总体；`analyze` 的 exception chain、repo candidates 和 fix boundary 是基于现有证据的推断，不是已验证代码根因。
3. **影响面看用户和分布，不看裸 event count**：event count 会受采样、循环崩溃和重试影响；优先报告 `userCount`，再用 release、environment、OS、browser、device、user 或 URL tag 判断集中度。
4. **失败和跨系统线索都有停止边界**：空结果、401/403、timeout 只描述本次证据路径；HTTP 失败 breadcrumb 只触发 Datadog handoff，不得据此确认后端内部根因。

## NEVER 规则

- 只通过 `scripts/sentry.py` 调用只读命令，不直接调用 `scripts/st/commands/*.py`，不执行 Sentry 状态变更。
- 不输出 `SENTRY_AUTH_TOKEN`、Authorization header 或 `.env` 内容；401/403 后停止当前路径，仅建议检查 token 状态、scope 和 org/project 权限。
- Sentry URL 只解析 org、issue ID 和 event ID；请求 host 始终来自 `SENTRY_BASE_URL`，且必须为 `https://`。
- `SENTRY_ORG_SLUG` 必须取 URL 中 `/organizations/<org-slug>/` 的值，不能按组织名猜测；MoeGo EU 默认值为 `moego-ey`。
- `SENTRY_DEFAULT_PROJECT` 可留空以查询整个 organization；只需缩小单次查询时优先使用 `--project`。
- `list-issues` 的排序使用 `--sort date|freq|new|user`，不把 sort 写进 `--query`。
- `list-issue-events` 已限定单个 issue，query 中不添加 `issue:`。
- 不猜少见 tag/field；先从 event tags 读取真实 key，再调用 `tag-values`。
- org-scoped 单 issue 端点遇到 5xx（含 HTTP 504）时，CLI 在既定重试结束后自动回退 bare issue 端点；4xx（含 408）和网络超时不回退，超时仍使用退出码 5。不要在 Agent 层重复模拟该逻辑。

## 场景决策树

### Step 1：确定调查契约

**输入**：用户请求，以及已知的 Sentry URL、issue/event ID、时间范围、环境、版本、平台或用户条件。

**操作**：

1. 明确要回答的是“有哪些 issue”“这个 event 发生了什么”“同一 issue 是否有共同根因”“影响谁”还是“下一步去哪里取证”。
2. 保留用户给出的时间、环境、版本和 project 条件；缺少会改变查询含义的标识时，先请求最小补充输入。
3. 若用户只提供本地异常、后端 request ID、日志/APM/指标问题且没有 Sentry 入口，说明边界并转交相邻能力，不强行使用本 Skill。

**输出**：一个可由 Sentry 证据回答的调查目标，或继续所需的最小输入。

### Step 2：选择最短证据路径

**输入**：Step 1 的调查目标。

**操作**：

| 目标 | 路径 |
|---|---|
| 最近活跃 unresolved issues | `list-issues --query "is:unresolved lastSeen:-24h" --sort date` |
| 新出现 issues | `list-issues --query "is:unresolved firstSeen:-7d" --sort new` |
| 高影响 issues | `list-issues --query "is:unresolved" --sort user` |
| 指定 event 证据 | `fetch-event`，保留 URL 中的 event ID；issue ID 模式必须显式提供 event ID |
| issue 初读 | `get-issue --include-event auto`；issue URL 无 event ID 时会读取 latest，并保留样本警告 |
| 根因或修复边界候选 | `analyze --mode issue --target json`，聚合多个 events 并生成候选链 |
| 证明多个 events 的共同点 | `list-issue-events` 选择代表样本，再分别 `fetch-event` 对比；不从 `analyze` 的去重聚合字段反推出现次数 |
| 对比 production/staging 或版本样本 | `list-issue-events --query "environment:production"`，再对代表性 event 使用 `fetch-event` |
| 版本、平台或用户集中度 | `get-issue --include-event never` 只读 `userCount` 等元数据，再按问题调用一个或多个 `tag-values` |

只有用户明确要求单个 latest、指定 event 或特定输出目标时，才使用 `analyze --mode latest|event` 或 `--target slack|jira|pr`。需要理解 bundle→repo 启发式时读取 [references/bundle-repo-resolution.md](references/bundle-repo-resolution.md)；需要机器输出字段时读取 [references/output-contract.md](references/output-contract.md)。

若当前成功响应已经覆盖调查目标，立即停止并回答。不要仅为复述 `analyze.selected_event`、issue 元数据或已返回的候选再调用 `fetch-event`、`get-issue` 或 `list-issue-events`；只有结论依赖跨 event 共同性、指定 event 原文或缺失字段时才追加取证。

**输出**：与问题匹配的最小只读命令序列，以及明确的停止条件。

### Step 3：执行并分层解释证据

**输入**：Step 2 的命令序列。

**操作**：

1. 执行命令并检查退出码、warnings 与 errors；不要从 stderr 或失败响应推断业务事实。
2. 将结果分为：
   - **观测事实**：issue 状态、`userCount`、event 字段、stack、breadcrumbs、tag 分布。
   - **工具推断**：`exception_chain`、`root_cause_candidates`、`repo_candidates`、`fix_boundary`。
   - **待确认项**：有限样本无法覆盖的版本、用户、平台或代码实现。
3. `analyze` 顶层会跨样本去重 `exceptions`、合并 `breadcrumbs`，但 `exception_chain`、route context 与 `backend_correlation` 只基于 selected event，避免跨 event 拼接因果。聚合字段不保留每条线索出现在哪些 events；只有逐个读取代表 events 后，才能把重复 stack、breadcrumb 模式或 tags 写成共同线索。
4. `backend_correlation.status=potential` 时，保留 selected event 内观测到的 path、status、时间和生成的 Datadog query，转交 Datadog 继续取证；只有同一 breadcrumb 明确提供 service 时 query 才能带 service 条件。在得到后端日志/trace 前，不把后端错误写成已确认根因。
5. repo candidate 与 fix boundary 只给排查优先级；`upstream_repo` / `downstream_repo` 表示当前异常时间链的触发候选 / 直接崩溃候选，不表示依赖关系。sourcemap、route context 或代码验证缺失时，不把 bundle 前缀归属写成精确修复位置。

**输出**：事实、推断和未知项分开的证据摘要；必要时包含受约束的跨系统 handoff。

### Step 4：验证并交付

**输入**：Step 3 的证据摘要。

**操作**：

1. 检查每条结论能否追溯到本次工具结果；删除编造的字段、次数、代码位置或因果关系。
2. 检查影响面是否至少区分用户数与 event count；用户问集中度时，必须报告实际查询的 tag 和分布。
3. 检查 latest、有限样本、repo 推断与 Datadog handoff 的限制是否显式保留。
4. 证据已经回答问题时停止；只有用户目标尚未覆盖且存在明确下一条证据路径时才继续调用。

**输出**：简洁结论、关键证据、置信边界和下一步；没有证据时明确写“本次未取得可确认结论”。

## 错误处理

| 退出码 | 含义 | 处理 |
|---:|---|---|
| 0 | 成功 | 解析 stdout，并保留 warnings |
| 2 | 配置或参数错误 | 检查缺失变量、URL/ID 组合和参数；不输出变量值 |
| 3 | 401/403 | 停止当前路径，检查 token 状态、scope 与 org/project 权限 |
| 4 | API、查询语法或 404 | 修正已识别的输入错误；没有明确修正依据时不盲目重试 |
| 5 | timeout | 缩小 event 数量或查询范围后最多重试一次，并说明结果只覆盖缩小后的范围 |

## 示例

```bash
uv run "$SKILL_DIR/scripts/sentry.py" get-issue --issue-id '<issue_id>' --include-event auto
uv run "$SKILL_DIR/scripts/sentry.py" fetch-event --issue-id '<issue_id>' --event-id '<event_id>'
uv run "$SKILL_DIR/scripts/sentry.py" list-issues --query 'is:unresolved lastSeen:-24h' --sort date
uv run "$SKILL_DIR/scripts/sentry.py" list-issue-events --issue-id '<issue_id>' --query 'environment:production'
uv run "$SKILL_DIR/scripts/sentry.py" tag-values --issue-id '<issue_id>' --tag release
uv run "$SKILL_DIR/scripts/sentry.py" list-projects
uv run "$SKILL_DIR/scripts/sentry.py" analyze --issue-id '<issue_id>' --mode issue --events 5 --target json
```

## References

| 文件 | 加载时机 |
|---|---|
| [references/crash-analysis.md](references/crash-analysis.md) | 分析 exception chain、breadcrumbs、多 event、回归与平台差异时 |
| [references/sentry-query-syntax.md](references/sentry-query-syntax.md) | 构造 issue/event query、sort 或 tag key 时 |
| [references/bundle-repo-resolution.md](references/bundle-repo-resolution.md) | 解释 bundle→repo 候选及其局限时 |
| [references/output-contract.md](references/output-contract.md) | 消费 `analyze` JSON contract v2 时 |
