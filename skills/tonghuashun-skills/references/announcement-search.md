# announcement-search：A 股 / 港股 / 基金 / ETF 公告搜索

> 官方 SKILL.md 原文见 [`../internal-skills/announcement-search/SKILL.md`](../internal-skills/announcement-search/SKILL.md)。

## 适用场景

- 上市公司公告查询（A 股、港股、基金、ETF）
- 公告类型：定期财务报告、分红派息、回购增持、资产重组、解禁、定增配股、关联交易等
- 围绕公告事件做时间轴梳理 / 单点查询

**典型用户问句**：
- "贵州茅台最近的分红公告是什么时候发的？"
- "宁德时代有没有发回购公告？"
- "美的集团 2024 年三季报披露内容"

## 接口信息

| 项 | 值 |
|---|---|
| 路径 | `POST /v1/comprehensive/search` |
| Skill-Id | `announcement-search` |
| Skill-Version | `1.0.0` |

### 请求体

```json
{
  "channels": ["announcement"],
  "app_id": "AIME_SKILL",
  "query": "<改写后的查询，建议包含公司名 / 公告类型 / 时间范围>"
}
```

**`channels` 固定为 `["announcement"]`。**

## 典型调用

```bash
TRACE_ID=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
curl -X POST https://openapi.iwencai.com/v1/comprehensive/search \
  -H "Authorization: Bearer $IWENCAI_API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-Claw-Call-Type: normal" \
  -H "X-Claw-Skill-Id: announcement-search" \
  -H "X-Claw-Skill-Version: 1.0.0" \
  -H "X-Claw-Plugin-Id: none" \
  -H "X-Claw-Plugin-Version: none" \
  -H "X-Claw-Trace-Id: $TRACE_ID" \
  -d '{"channels":["announcement"],"app_id":"AIME_SKILL","query":"贵州茅台 分红 2024"}'
```

或：`python3 ../internal-skills/announcement-search/scripts/announcement_search.py "<query>"`

## Query 改写要点

- 显式包含**公司名称** / **股票代码** / **公告类型关键词**，命中率显著更高
- 公告类型常见关键词：`定期报告`、`分红派息`、`回购`、`增减持`、`定增`、`资产重组`、`解禁`、`关联交易`、`股权激励`
- 同时查多个公司时，**拆成多次** query 调用

## NEVER 规则

- ❌ 公告查询不要用 `news` 或 `report` 通道，否则返回的是新闻 / 研报，不是 SSE 法定披露公告。
- ❌ 不要丢失公告原文 PDF / HTML 链接字段，这是合规链路必须保留的溯源信息。
- ❌ 不要把"公司发布的新闻稿"当公告——投资者关系新闻在 [`news-search.md`](news-search.md)。

## 输出与汇报

- 透传网关 JSON
- 回答必须保留：公告标题、披露日期、原文链接（如有）
- 数据来源标注：「数据来源：同花顺问财（公告搜索）」

## 不在本 reference 范围

- 财经新闻 / 政策动态 → [`news-search.md`](news-search.md)
- 券商研报 → [`report-search.md`](report-search.md)
- 公告对应的财务指标数据（如分红率） → [`financial-data.md`](financial-data.md)
