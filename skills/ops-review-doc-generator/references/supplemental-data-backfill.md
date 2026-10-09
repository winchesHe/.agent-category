# 补充数据回填 SOP

用于初稿 evidence pack 已生成、但仍有缺口或低置信指标时，继续补拉数据并把经验沉淀回文档。适用于 Grooming Ops Review，尤其是 Tableau GRR/NDR、Datadog RUM、Lark Base/Doc、Redshift NPS/Salesforce、Jira fallback 等补数场景。

## 总原则

- 先判断缺口是否真的需要自动拉取；如果 owner 确认是人工收集项，例如 NPS official，则写成 `confidence=manual`，不计入自动补数缺口。
- 每补一条数据都写入内部 evidence/debug traceability，包括失败探针；失败原因要区分 `无数据`、`无权限`、`接口只吐部分 sheet`、`人工口径`。
- 发布版 `Data Source & Traceability` 只保留正文实际使用的数据源、已接受的 manual policy 和必要口径说明；被后续补齐或人工确认替代的 `_missing`、`gap_summary`、source search、permission denied 探针必须删除。
- 不输出 PAT、账号密码、邮箱、客户名、公司名、反馈原文、Intercom 原文或长文本明细；Retention 可展示脱敏后的简短 direct churn reason。
- 结构化 CSV/API 优先；PNG/视觉读取只作为兜底，metric `confidence` 用 `manual` 或 `visual_only`，并在 `delta` 里说明不稳定自动化。
- Dashboard 的 `view/data` 不能代表完整 dashboard；必须枚举 workbook 下相关 views/sheets，分别判断 CSV/XLSX/PNG 可用性。
- Grooming 已确认 GRR/NDR 可直接用 Tableau PNG 展示；这不是生成阻塞项，但仍要标为视觉/人工口径，不能写成结构化 verified。
- 补完后必须运行渲染检查和敏感扫描。

## 补数顺序

1. **复核 missing/低置信指标**
   - 从 evidence pack 统计 `confidence=missing`、`value=待补`、`status=missing`。
   - 对每个缺口明确它是自动数据、人工收集、目标值、还是历史参考。
   - 人工收集项示例：`Grooming-only NPS official`。当 PM/CS 确认 NPS 是人工收集时，写为 `manual_nps_collection_policy`，value 可用 `人工收集，不计入自动补数缺口`。

2. **Tableau 补拉**
   - 用 `mcp__tableau.search_content` 搜 workbook/view/datasource；不要只依赖飞书里的 URL 文本。
   - 找到 workbook 后用 `get_workbook` 枚举 views/sheets。
   - 对每个相关 view 尝试：
     - `get_view_data`：稳定 CSV 优先。
     - `get_view_image`：CSV 不吐关键指标时用高分辨率 PNG 视觉兜底。
     - `get_datasource_metadata`：能取字段就取；403 只记录权限，不要因此忽略 view/image 已能补的指标。
   - 经验：Retention/GRR/NDR dashboard 可能 `view/data` 只吐 Logo Retention 或当前焦点 sheet。GRR/NDR 这类图表若只在 PNG 上可见，写 `confidence=manual`，并在 `delta` 说明 `view/data` 未吐底层 sheet。
   - Grooming 默认已接受 GRR/NDR 的 PNG 展示。若 CSV/crosstab 拿不到，直接把高分辨率 PNG 写入 section `visuals[]`，并把视觉读数写成 `manual` 或 `visual_only` metric；不要把“请 Tableau owner 暴露底层 sheet/crosstab”放入 Meeting Notes。
   - ChurnLogos 必须尽量补 exact period 的 all-segment 明细：总 churn logos、Business Type / Segment split、tier mix，以及脱敏后的 direct churn reason。不要只输出 reason 分类质量、缺失比例或 dashboard 截图。
   - churn reason 明细写入 `sections.retention.churn_reason_details[]`，只保留日期、segment/business type、tier 和简短 reason；移除邮箱、客户名、公司名、Company ID、Intercom 原文长文本。
   - 对极端值，例如低基数导致的异常 NDR，可展示为 visual/manual 指标，但应在业务正文中降级为参考或分组现象，不作为未解释的 headline。
   - 过滤器失败时不要强行套口径。例：`Business Segment=Grooming` + `Business Type=Salon` 可能让 dashboard 变空；应记录 All segment/type 或当前可见口径。

3. **Datadog RUM / System Loading 补拉**
   - 先读 Datadog dashboard 定义，定位 widget、service、path、RUM query。
   - 常见 Grooming RUM 指标：
     - PV：按 `@view.url_path` 聚合 view count。
     - UV：按 `@usr.email` cardinality；只输出数量，不输出邮箱。
     - LCP：`@view.largest_contentful_paint` p75 / p95，按 ns 转秒。
     - INP：`@view.interaction_to_next_paint` p75 / p95，按 ns 转毫秒。
     - JS error views：`@view.error.count > 0` 的 view 数；不要写成 error event 总数。
   - RUM 路径建议至少覆盖：
     - `/calendar/grooming`
     - `/online_booking/requests`
     - `/setting/staff/workingHours`
   - 若当前 `$datadog` skill 没有封装 RUM aggregate 子命令，可用临时 API 探针补数。补齐后发布版 traceability 只保留成功的 RUM aggregate 来源，删除旧的 RUM missing 探针。

4. **Lark Drive / Doc / Base 补查**
   - `drive +search` 的 JSON 结果通常包在外层 `data.results`，不要误读顶层 `results` 导致假空。
   - Wiki URL 先 `drive +inspect` 或 wiki node 解析，拿真实 `obj_type` / `obj_token`，再切到 doc/sheet/base。
   - 文档只按关键词局部读取：
     ```bash
     lark-cli docs +fetch --api-version v2 --doc <url> \
       --scope keyword --keyword "NPS|Grooming|May|2026|score|actual|目标" \
       --context-before 1 --context-after 1 --doc-format markdown --format json
     ```
   - Base 先解析 URL 和字段：
     ```bash
     lark-cli base +url-resolve --as user --url <base_or_wiki_url> --format json
     lark-cli base +table-list --as user --base-token <base_token> --format json
     lark-cli base +field-list --as user --base-token <base_token> --table-id <table_id> --format json
     ```
   - Base 聚合优先 `+data-query`；如遇 `91403 permission denied`，可用 bot 重试一次。仍失败则记录权限缺口，不拉行级数据。
   - 通用问卷模板、方法配置、没有 business/company/date/score 口径的 Base，不能当官方 actual。

5. **Redshift / Salesforce NPS 探针**
   - 先从 schema index 搜 `nps`、`survey`、`satisfaction`、`feedback`，再按 skill 要求 `describe-table` 或 `pg_table_def`。
   - 旧表 `dev.public.nps_info1` 只能说明历史 NPS；必须查 `min/max/count` 和目标月份行数：
     ```sql
     select min(created_at)::date, max(created_at)::date, count(*),
            sum(case when created_at >= '2026-05-01' and created_at < '2026-06-01' then 1 else 0 end)
     from public.nps_info1;
     ```
   - Salesforce NPS 表可能在 `moego_salesforce_prod.public.pro_nps__c`、`salesforce_nps__c`、`salesforce_prod_nps__c`，字段通常包括 `nps_score__c`、`survey_date__c`、`company_id__c`、`feedback__c`。
   - 如果聚合查询返回 `permission denied for relation ...`，只在内部 debug evidence 记录“存在但当前只读角色无权限”；不要输出或尝试绕过反馈明细。
   - 再查可访问下游层：
     ```sql
     select schemaname, tablename
     from pg_table_def
     where lower(tablename) like '%nps%' or lower(tablename) like '%survey%'
     group by 1,2;
     ```
     对 `dw`、`dbt_dw` 都跑一遍。无命中表示不能绕过 Salesforce relation 权限。

6. **协作消息只做 source discovery**
   - 飞书 IM / Slack 可用于找“谁提到官方源”，不能直接作为指标 actual。
   - 搜索词：`NPS source`、`NPS dashboard`、`NPS actual`、`Salesforce NPS`、`Grooming NPS`、`25NPS`、`NPS May`、中文 `净推荐值`、`问卷`、`调研`。
   - 只保留低敏摘要和是否命中，不输出客户消息、邮箱、公司名或原始反馈。
   - 若只命中 `NPS-driver`、`2025 survey`、项目讨论，结论是“不能证明本期 official actual”。

## Evidence 写法

人工收集项：

```json
{
  "name": "Grooming-only NPS official",
  "value": "人工收集，不计入自动补数缺口",
  "delta": "PM/CS 确认 NPS official 为人工收集项；本稿不再作为自动取数缺口阻塞",
  "period": "2026-05",
  "source_id": "manual_nps_collection_policy",
  "confidence": "manual"
}
```

内部 debug 失败探针示例，发布版 traceability 不保留：

```json
{
  "source_id": "internal_debug_nps_permission_probe",
  "source_type": "redshift_metadata_permission_probe",
  "title": "Redshift NPS source check",
  "source_url": "",
  "query_or_filter": "nps_info1 no target-month rows; Salesforce NPS tables exist but aggregate probes returned permission denied; no row-level text exported",
  "retrieved_at": "2026-06-26T21:20:00+08:00",
  "owner": "Data warehouse / Salesforce"
}
```

缺口降级规则：

| 情况 | Metric confidence | open_questions |
|---|---|---|
| 结构化查询拿到并可复算 | `verified` / `derived` | 不需要 |
| PNG/视觉读取 | `manual` / `visual_only` | Grooming GRR/NDR 默认不需要；其它场景可写自动化补强问题 |
| owner 确认为人工收集 | `manual` | 不作为数据缺口；发布版只保留 manual policy |
| 有表但权限不足 | 不写 actual metric；内部 debug 记录失败探针 | 发布版不保留 permission denied 探针 |
| 找不到任何源且不是人工项 | `missing` | 必须写 |

## 验收命令

渲染：

```bash
python3 /Users/moego-winches/Desktop/Company/person/skills/ops-review-doc-generator/scripts/render_grooming_ops_review.py \
  --input /tmp/grooming_ops_review_2026_05/grooming-ops-review-2026-05.evidence.json \
  --output /tmp/grooming_ops_review_2026_05/grooming-ops-review-2026-05.md \
  --check
```

敏感扫描：

```bash
grep -E -i '(password\s*[:=]|psw\s*[:=]|authorization\s*[:=]|cookie\s*[:=]|token\s*[:=]|api[_-]?key\s*[:=]|secret\s*[:=]|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})' \
  /tmp/grooming_ops_review_2026_05/grooming-ops-review-2026-05.evidence.json \
  /tmp/grooming_ops_review_2026_05/grooming-ops-review-2026-05-preview.md \
  /tmp/grooming_ops_review_2026_05/grooming-ops-review-2026-05.md
```

`grep` 退出码 `1` 表示无命中，是通过。
