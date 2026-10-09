# Tableau 拉取可用性审计

用于分析飞书文档里用到的 Tableau 数据，并判断哪些数据能通过 Tableau MCP/REST 稳定拉下来。

## 输出约束

- 全程中文输出。
- 不输出 PAT、账号密码、邮箱明细、客户敏感文本。
- Tableau MCP/REST 返回 401 时，先检查 Tableau URL 的 `/site/<contentUrl>/` 是否和 MCP/环境变量配置的 `SITE_NAME` 一致；不要直接判定 PAT 缺失。
- Tableau 数据分三类：`可直接 CSV 拉取`、`只能 PNG/视觉读取`、`非 Tableau 数据源`。

## 步骤 1：读取飞书文档

使用 `$lark-skills`：

1. 如果输入是 wiki URL，先解析 wiki token，拿真实 `obj_type` 和 `obj_token`：
   ```bash
   lark-cli wiki spaces get_node --params '{"token":"<wiki_token>"}' --format json
   ```
2. 读取大纲、Data source 表、相关章节：
   ```bash
   lark-cli docs +fetch --api-version v2 --doc <doc_token> --scope outline --format json
   lark-cli docs +fetch --api-version v2 --doc <doc_token> --scope keyword --keyword "Data source" --context-after 10 --format json
   ```
3. 抽取 Tableau / PostHog / Datadog / Jira / Lark Base / Sheet 链接，区分数据源类型。
4. 对飞书文档内 `<cite>`、`<bitable>`、`<sheet>` 标签下钻；不要只输出标签文本。

## 步骤 2：解析 Tableau URL 与认证探针

从每个 Tableau URL 解析：

| 字段 | 说明 |
|---|---|
| `server` | 例如 `https://prod-apnortheast-a.online.tableau.com` |
| `site_content_url` | URL 中 `/site/<contentUrl>/` 的 `<contentUrl>` |
| `workbook_content_url` | `/views/<workbook>/<view>` 中的 `<workbook>` |
| `view_url_name` | `/views/<workbook>/<view>` 中的 `<view>` |

认证探针：

- 若使用 Tableau MCP，先用 `search_content` / `list_views` 做只读探针。
- 若使用 REST sign-in，只输出 HTTP 状态、Tableau error code、site contentUrl 对比结果；不输出 `PAT_NAME`、`PAT_VALUE`、token。
- `PAT_VALUE` 存在不代表能登录；site 配错也会 401。

401 判断顺序：

1. URL 里是否有 `/site/<contentUrl>/`。
2. `<contentUrl>` 是否等于 MCP/环境变量配置的 `SITE_NAME`。
3. server 是否一致。
4. 再判断 PAT 是否缺失、过期或权限不足。

## 步骤 3：定位 Workbook / View / Sheet

优先 MCP：

1. `mcp__tableau.search_content` 搜 workbook/view，过滤 `contentTypes: ["workbook", "view"]`。
2. `mcp__tableau.list_workbooks` 或 `mcp__tableau.list_views` 用 `contentUrl`、`workbookName`、`viewUrlname` 精确定位。
3. `mcp__tableau.get_workbook` 列出 workbook 下所有 views/sheets。
4. 对每个相关 view/sheet 拉：
   - `mcp__tableau.get_view_data`，等价关注 `view/data?includeAllColumns=true`。
   - REST 可用时补 `crosstab/excel`。
   - `mcp__tableau.get_view_image`，REST 可用时用 `image?resolution=high`。

注意：

- Dashboard 自身的 `view/data` 可能只返回当前焦点 sheet；完整分析必须枚举 workbook sheets。
- Churn 明细类数据优先 CSV/XLSX，PNG 会截断邮箱、公司名、长文本。
- PNG 适合补齐 dashboard 上 CSV 没吐出来的总数、趋势、标注，但只能作为视觉兜底；稳定自动化要优先 CSV/XLSX。

## 步骤 4：判断可用性

对 CSV/XLSX：

- 输出行数、字段名、样例字段类型；不输出邮箱、客户名、账号、长文本明细。
- 判断是否覆盖文档中用到的指标。
- 记录过滤条件和时间范围。

对 PNG：

- 确认是否能补齐 CSV 缺失的指标。
- 说明适合“人工/视觉读取”还是“可稳定自动化”。
- 如果关键数字只能靠 PNG，标记为 `manual` 或 `visual_only`，不要写成 `verified`。

对非 Tableau：

- 分类到 PostHog / Datadog / Jira / Lark Base / Google Sheet / 其它。
- 转交对应 skill 或写入缺口表。

## 输出格式

先给一句概要：能不能拉全、主要缺口是什么。

然后输出三张表：

### 表格 1：文档章节 → 数据源链接 → 用到的指标 → 是否 Tableau

| 文档章节 | 数据源链接 | 用到的指标 | 是否 Tableau |
|---|---|---|---|

### 表格 2：Tableau view/sheet → 拉取方式 → rows/columns → 可用性

| Tableau view/sheet | 拉取方式 | rows / columns | 可用性 |
|---|---|---|---|

可用性取值：

- `可直接 CSV 拉取`
- `可 XLSX/crosstab 拉取`
- `只能 PNG/视觉读取`
- `需要枚举底层 sheet`
- `认证/权限待修复`
- `非 Tableau 数据源`

### 表格 3：缺口 → 原因 → 兜底方式

| 缺口 | 原因 | 兜底方式 |
|---|---|---|

最后给推荐后续动作，优先级按：

1. 修正 site / PAT / 权限。
2. 枚举 workbook sheets 并补 CSV/XLSX。
3. 对视觉-only 指标用高分辨率 PNG 暂时兜底。
4. 把 PostHog / Datadog / Jira / Lark Base 交给对应 skill 获取结构化数据。

## 写入 Evidence Pack

对每个 Tableau 来源写入 `traceability`：

```json
{
  "source_id": "tableau_growth_monthly",
  "source_type": "tableau_view",
  "title": "MonthlyOpsReviw",
  "source_url": "https://...",
  "query_or_filter": "site=<contentUrl>; workbook=<contentUrl>; view=<urlName>; filters=...",
  "retrieved_at": "2026-06-26T10:00:00Z",
  "owner": "owner name only"
}
```

指标 confidence：

- CSV/XLSX 结构化拉取：`verified`。
- Tableau CSV 导出后再人工计算：`derived`。
- PNG/视觉读取：`manual` 或 `visual_only`；Grooming GRR/NDR 写入 section `visuals[]`，不要写入 `open_questions`。
- 认证失败 / site 不匹配 / 权限不足：不写指标，写入 `open_questions`。
