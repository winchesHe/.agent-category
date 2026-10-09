# basic-info：基本资料查询（全品类标的）

> 官方 SKILL.md 原文见 [`../internal-skills/hithink-basicinfo-query/SKILL.md`](../internal-skills/hithink-basicinfo-query/SKILL.md)。

## 适用场景

- 全品类标的的**静态基本信息**：股票、指数、基金、期货、期权、可转债、债券、银行理财、保险
- 字段范围：基础信息、发行主体、机构资料、费率、上市地点、上市日期、合约规格
- 适合"是什么 / 在哪上市 / 什么时候上的"类问题

**典型用户问句**：
- "贵州茅台是哪一年上市的？"
- "沪深 300 ETF 的费率是多少？"
- "螺纹钢期货合约规格"
- "易方达蓝筹的基金经理是谁？"
- "招商银行公司债 的发行日期"

## 接口信息

| 项 | 值 |
|---|---|
| 路径 | `POST /v1/query2data` |
| Skill-Id | `hithink-basicinfo-query` |
| Skill-Version | `1.0.0` |

### 请求体

```json
{
  "query": "<自然语言基础信息问句>",
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
  -H "X-Claw-Skill-Id: hithink-basicinfo-query" \
  -H "X-Claw-Skill-Version: 1.0.0" \
  -H "X-Claw-Plugin-Id: none" \
  -H "X-Claw-Plugin-Version: none" \
  -H "X-Claw-Call-Type: normal" \
  -H "X-Claw-Trace-Id: $(python3 -c 'import secrets;print(secrets.token_hex(32))')" \
  -d '{"query":"贵州茅台 上市日期 发行价","page":"1","limit":"10","is_cache":"1","expand_index":"true"}'
```

或：`python3 ../internal-skills/hithink-basicinfo-query/scripts/cli.py "<query>"`

## Query 改写要点

- **品类关键词必带**：股票 / 基金 / 期货 / 期权 / 转债 / 债券 / 理财 / 保险
- 字段词标准化：`上市日期`、`发行主体`、`基金经理`、`管理费率`、`合约乘数`、`交割月份`、`票面利率`、`到期日`
- 多字段一次查：`贵州茅台 上市日期 上市地点 发行价 注册地`

## 返回字段

- `datas`：基础信息记录数组（按品类不同字段集差异较大）
- 例如股票会含：股票代码、简称、上市日期、上市地点、所属行业、注册地、办公地址
- 基金会含：基金代码、基金经理、管理人、托管行、管理费率、托管费率、成立日期
- 期货/期权会含：合约代码、合约月份、交割日、合约乘数、保证金比例

## NEVER 规则

- ❌ 不要把"实时净值 / 行情"问到本 skill ——基本资料是静态信息，动态数据应走 [`market-data.md`](market-data.md)。
- ❌ 不要在 query 里混入财务指标（ROE 等），那会导致返回不全，应路由到 [`financial-data.md`](financial-data.md)。
- ❌ 不同品类的字段集差异大，**不要**默认所有标的都有相同 schema；按返回字段实际为准。

## 输出与汇报

- 透传 JSON
- 输出时用表格展示，分组：标识（代码 / 名称）/ 时间（上市 / 发行 / 到期）/ 主体（管理人 / 发行人 / 注册地）/ 费率与合约规格
- 数据来源标注：「数据来源：同花顺问财（基本资料查询）」

## 不在本 reference 范围

- 实时净值 / 行情 → [`market-data.md`](market-data.md)
- 财务指标 → [`financial-data.md`](financial-data.md)
- 评级 / 信用评级 → [`institutional-research.md`](institutional-research.md)
- 公告 / 招股书原文 → [`announcement-search.md`](announcement-search.md)
