# financial-data：财务数据查询（个股财务指标）

> 官方 SKILL.md 原文见 [`../internal-skills/hithink-finance-query/SKILL.md`](../internal-skills/hithink-finance-query/SKILL.md)。

## 适用场景

- 单只 / 多只个股的财务指标查询
- 三大报表项目：营业收入、净利润、毛利润、归母净利润、扣非净利润、经营 / 投资 / 筹资现金流
- 比率指标：ROE / ROA / 毛利率 / 净利率 / 资产负债率、流动比率 / 速动比率
- 增长率 / 同比 / 环比
- 期间维度：年报 / 半年报 / 季报 / TTM

**典型用户问句**：
- "贵州茅台 2024 年的 ROE 是多少？"
- "宁德时代近 5 年净利润复合增长率"
- "比亚迪去年的毛利率"
- "中国平安 资产负债率"

## 接口信息

| 项 | 值 |
|---|---|
| 路径 | `POST /v1/query2data` |
| Skill-Id | `hithink-finance-query` |
| Skill-Version | `1.0.0` |

### 请求体

```json
{
  "query": "<自然语言财务问句>",
  "page": "1",
  "limit": "10",
  "is_cache": "1",
  "expand_index": "true"
}
```

## 典型调用

```python
import os, json, secrets, urllib.request

req = urllib.request.Request(
    "https://openapi.iwencai.com/v1/query2data",
    data=json.dumps({
        "query": "贵州茅台 2024年 ROE 营业收入 净利润",
        "page": "1", "limit": "10", "is_cache": "1", "expand_index": "true",
    }).encode(),
    headers={
        "Authorization": f"Bearer {os.environ['IWENCAI_API_KEY']}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": "hithink-finance-query",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    },
)
print(urllib.request.urlopen(req, timeout=30).read().decode())
```

或：`python3 ../internal-skills/hithink-finance-query/scripts/cli.py "<query>"`

## Query 改写要点

- **指标名标准化**：用 `ROE` 而不是 "净资产收益率"，用 `毛利率` 而不是 "毛利占比"（问财都能识别，但精确词命中更稳）
- **时间维度**：`2024 年报`、`2024Q3`、`近 3 年`、`近 5 年`、`TTM`
- **复合指标**：把"净利润、营收、ROE 一起查"写在同一 query 里，一次返回更高效
- 多公司对比：拆成多次调用，逐个公司查后再聚合

## 返回字段

- `datas`：财务指标对象数组（中文 key，如 `净资产收益率(ROE)`、`营业收入`、`净利润`）
- 看到形如 `2024Q3`、`2024-12-31` 的报告期字段时直接保留

## NEVER 规则

- ❌ 不要在财务查询中混入"涨跌幅 / 成交量"，那是行情字段，应路由到 [`market-data.md`](market-data.md)。
- ❌ 不要把财务比率单位（%、亿元）默认为某个值——返回字段会显式带单位，回答时保留。
- ❌ 不要假设最新报告期是某一日，应按返回 `报告期` 字段为准。

## 输出与汇报

- 透传 JSON
- 多指标 / 多期间结果用表格展示，列保留中文 key
- 数据来源标注：「数据来源：同花顺问财（财务数据查询）」

## 不在本 reference 范围

- 一致预期 / 业绩预测（未来）→ [`institutional-research.md`](institutional-research.md)
- 公司主营 / 客户 / 供应商等经营数据 → 本套 8 个 skill 未覆盖，需安装 `hithink-business-query`
- 选股时叠加财务条件 → [`wencai-a-stock.md`](wencai-a-stock.md)
