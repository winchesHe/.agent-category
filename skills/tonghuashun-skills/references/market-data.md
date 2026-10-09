# market-data：行情数据查询（股票 / ETF / 指数）

> 官方 SKILL.md 原文见 [`../internal-skills/hithink-market-query/SKILL.md`](../internal-skills/hithink-market-query/SKILL.md)。

## 适用场景

- 实时 / 历史股价、涨跌幅、振幅
- 成交量 / 成交额 / 换手率
- 主力资金流向、大小单分布
- 技术指标（MA / MACD / KDJ / RSI / 布林带 等）
- 适用品类：A 股 / ETF / 指数

**典型用户问句**：
- "贵州茅台今天涨幅多少？"
- "沪深 300 最近一个月的资金流向"
- "中证 500 ETF 的成交额排名"
- "招商银行的 MACD 现在金叉了吗？"

## 接口信息

| 项 | 值 |
|---|---|
| 路径 | `POST /v1/query2data` |
| Skill-Id | `hithink-market-query` |
| Skill-Version | `1.0.0` |

### 请求体

```json
{
  "query": "<自然语言改写后的行情查询>",
  "page": "1",
  "limit": "10",
  "is_cache": "1",
  "expand_index": "true"
}
```

> 这里 query 用**自然语言句**，不是关键词列表，参考问财官网选股的写法。如："今日涨跌幅大于 5% 的科技股"、"贵州茅台 最近 30 天 涨跌幅"。

## 典型调用

```python
import os, json, secrets, urllib.request

req = urllib.request.Request(
    "https://openapi.iwencai.com/v1/query2data",
    data=json.dumps({
        "query": "贵州茅台 今日涨跌幅",
        "page": "1", "limit": "10", "is_cache": "1", "expand_index": "true",
    }).encode(),
    headers={
        "Authorization": f"Bearer {os.environ['IWENCAI_API_KEY']}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": "hithink-market-query",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    },
)
print(urllib.request.urlopen(req, timeout=30).read().decode())
```

或：`python3 ../internal-skills/hithink-market-query/scripts/cli.py "<query>"`

## 返回字段

- `datas`：行情对象数组（含 `股票代码`、`股票简称`、行情字段）
- `code_count`：符合条件的总数
- `chunks_info`：本次查询拆解信息

> 字段名是中文 key，转给上层 LLM 前**不要**改成英文。

## Query 改写要点

- 实体明确："贵州茅台" 而非 "茅台"，"沪深 300" 而非 "300 指数"
- 指标精确："涨跌幅" / "成交额" / "主力净流入" / "MACD" 直接写
- 时间范围明确："今日"、"近 5 日"、"近 30 天"、"年初至今"
- 多条件用逗号拼接：`今日涨跌幅大于 5%, 流通市值大于 100 亿`

## NEVER 规则

- ❌ 不要在 `/v1/query2data` 里塞 `channels` 参数（那是 comprehensive/search 用的），会被忽略或拒绝。
- ❌ 不要直接把用户口语原样塞 query。如"茅台咋样？" 改写成 "贵州茅台 今日行情"。
- ❌ 不要把 datas 字段二次包装。问财网关「条件六」要求透传 JSON。

## 输出与汇报

- 透传 JSON 给上层 LLM 提取关键指标
- 表格化展示行情数据时，保留字段中文名
- 数据来源标注：「数据来源：同花顺问财（行情数据查询）」

## 不在本 reference 范围

- 财务指标（ROE / 营收等）→ [`financial-data.md`](financial-data.md)
- 多条件组合选股 → [`wencai-a-stock.md`](wencai-a-stock.md)
- 机构评级 / 一致预期 → [`institutional-research.md`](institutional-research.md)
- 期货 / 期权 / 港股 / 美股 → 本套 8 个 skill 暂未覆盖，需安装对应 wencai 选股 skill
