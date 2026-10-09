# report-search：券商研究报告搜索

> 官方 SKILL.md 原文见 [`../internal-skills/report-search/SKILL.md`](../internal-skills/report-search/SKILL.md)。版本 **2.0.0**（不同于其他 1.0.0）。

## 适用场景

- 主流投研机构发布的研究报告检索
- 公司 / 行业 / 主题 / 宏观 类研报
- 提取分析师观点：投资逻辑、投资评级、目标价

**典型用户问句**：
- "宁德时代最近一份券商研报怎么说？"
- "光伏行业有哪些深度报告？"
- "招商证券对比亚迪的目标价是多少？"

## 接口信息

| 项 | 值 |
|---|---|
| 路径 | `POST /v1/comprehensive/search` |
| Skill-Id | `report-search` |
| Skill-Version | **`2.0.0`** |

### 请求体

```json
{
  "channels": ["report"],
  "app_id": "AIME_SKILL",
  "query": "<查询关键词，建议含公司 / 行业 + 主题>"
}
```

**`channels` 固定为 `["report"]`，`X-Claw-Skill-Version` 必须填 `2.0.0`（其他 search 类 skill 是 1.0.0，这里别填错）。**

## 典型调用

```bash
TRACE_ID=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
curl -X POST https://openapi.iwencai.com/v1/comprehensive/search \
  -H "Authorization: Bearer $IWENCAI_API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-Claw-Call-Type: normal" \
  -H "X-Claw-Skill-Id: report-search" \
  -H "X-Claw-Skill-Version: 2.0.0" \
  -H "X-Claw-Plugin-Id: none" \
  -H "X-Claw-Plugin-Version: none" \
  -H "X-Claw-Trace-Id: $TRACE_ID" \
  -d '{"channels":["report"],"app_id":"AIME_SKILL","query":"宁德时代 深度报告"}'
```

或：`python3 ../internal-skills/report-search/scripts/<entry>.py "<query>"`（具体入口见 `scripts/` 目录）。

## Query 改写要点

- 主体（公司名 / 行业 / 主题）+ 修饰词（深度、首次覆盖、跟踪、季度、调研纪要）
- 想拿评级 / 目标价：在 query 里直接含"目标价"或"评级"提示
- 时间相关问题：在 query 里写"近 30 天"、"2024Q4"等口语化时间词

## NEVER 规则

- ❌ **不要把 Skill-Version 填成 1.0.0** —— 2.0.0 才是研报当前版本，错版本会被网关拒绝或匹配错日志链路。
- ❌ 不要把 `channels` 改为 `news` / `announcement`，研报通道单独索引。
- ❌ 不要在研报检索里期望财务表数据，研报字段是非结构化全文摘要，不是行情/财务表。

## 输出与汇报

- 透传 JSON
- 回答中保留：研报标题、发布机构、研报日期、评级 / 目标价（若返回里有该字段）、研报详情链接
- 数据来源标注：「数据来源：同花顺问财（研报搜索）」

## 不在本 reference 范围

- 评级 / 一致预期 / 业绩预测的结构化数据 → [`institutional-research.md`](institutional-research.md)
- 财报实际数字（营收 / ROE） → [`financial-data.md`](financial-data.md)
