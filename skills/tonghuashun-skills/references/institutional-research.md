# institutional-research：机构研究与评级查询

> 官方 SKILL.md 原文见 [`../internal-skills/hithink-insresearch-query/SKILL.md`](../internal-skills/hithink-insresearch-query/SKILL.md)。

## 适用场景

- 券商 / 机构发布的研报**评级**（买入 / 增持 / 中性 / 减持）与目标价
- 业绩预测 / 一致预期（EPS / 净利润 / 营收 等未来预测值）
- ESG 评级（环境 / 社会 / 治理）
- 信用评级 / 主体评级（债券类）
- 基金评级（晨星 / 海通 / 招商等）
- **券商金股**（每月推荐组合）

**典型用户问句**：
- "宁德时代的最新研报评级是什么？"
- "比亚迪 2025 年的一致预期净利润是多少？"
- "贵州茅台的 ESG 评级"
- "本月券商金股名单"
- "AAA 级公司债"

## 接口信息

| 项 | 值 |
|---|---|
| 路径 | `POST /v1/query2data` |
| Skill-Id | `hithink-insresearch-query` |
| Skill-Version | `1.0.0` |

### 请求体

```json
{
  "query": "<自然语言>",
  "page": "1",
  "limit": "10",
  "is_cache": "1",
  "expand_index": "true"
}
```

## 典型调用

```bash
curl -X POST https://openapi.iwencai.com/v1/query2data \
  -H "Authorization: Bearer $IWENCAI_API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-Claw-Skill-Id: hithink-insresearch-query" \
  -H "X-Claw-Skill-Version: 1.0.0" \
  -H "X-Claw-Plugin-Id: none" \
  -H "X-Claw-Plugin-Version: none" \
  -H "X-Claw-Call-Type: normal" \
  -H "X-Claw-Trace-Id: $(python3 -c 'import secrets;print(secrets.token_hex(32))')" \
  -d '{"query":"宁德时代 研报评级 最新","page":"1","limit":"10","is_cache":"1","expand_index":"true"}'
```

或：`python3 ../internal-skills/hithink-insresearch-query/scripts/cli.py "<query>"`

## Query 改写要点

- 类型词必须明确：`研报评级`、`一致预期`、`业绩预测`、`ESG 评级`、`信用评级`、`主体评级`、`基金评级`、`券商金股`
- 时间维度：`最新`、`近一年`、`2024 年`、`本月`
- 实体准确：公司全名或股票代码
- 多类型问题拆分：例如同时要评级和业绩预测，分两次调用

## 返回字段

- `datas`：评级 / 预期 / 金股结构化记录数组（字段为中文 key）
- `code_count`、`chunks_info` 同行情接口

## NEVER 规则

- ❌ 不要把"评级"和"研报全文"混淆 —— 评级是结构化数据走本 skill，研报全文走 [`report-search.md`](report-search.md)。
- ❌ 不要拿 ESG 评级问财查问询股票时只填股票代码，应写 "<公司名> ESG 评级"。
- ❌ 不要在 query 用"如何看待 / 怎么样"这类语义模糊问法，改写成具体维度。

## 输出与汇报

- 透传 JSON
- 评级回答中保留：评级机构、评级标签、目标价、评级日期
- 数据来源标注：「数据来源：同花顺问财（机构研究与评级）」

## 不在本 reference 范围

- 研报全文 / 摘要 → [`report-search.md`](report-search.md)
- 实际财务数字（不是预期）→ [`financial-data.md`](financial-data.md)
- 选股时叠加评级条件 → [`wencai-a-stock.md`](wencai-a-stock.md)
