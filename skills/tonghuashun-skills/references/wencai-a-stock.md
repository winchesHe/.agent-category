# wencai-a-stock：问财选 A 股（自然语言多条件筛选）

> 官方 SKILL.md 原文见 [`../internal-skills/hithink-astock-selector/SKILL.md`](../internal-skills/hithink-astock-selector/SKILL.md)。

## 适用场景

A 股股票自然语言选股，支持多条件组合：

- **行情指标**：股价区间、涨跌幅、成交量、流通市值、换手率、振幅
- **技术形态**：均线多头排列、突破新高、K 线形态、MACD 金叉、放量、回踩支撑
- **财务指标**：ROE、营收增速、净利润增速、PE、PB、毛利率、负债率
- **行业 / 概念**：科技、医药、消费、新能源、AI、半导体、稀土、固态电池
- **组合条件**：上述任意维度多条件叠加

**典型用户问句**：
- "ROE 大于 15、PE 小于 30 的科技股"
- "今日涨停且换手率小于 20% 的股票"
- "市值大于 100 亿、近 3 年净利润复合增长率超过 20% 的医药股"
- "MACD 金叉、成交量放大的 A 股"

## 接口信息

| 项 | 值 |
|---|---|
| 路径 | `POST /v1/query2data` |
| Skill-Id | `hithink-astock-selector` |
| Skill-Version | `1.0.0` |

### 请求体

```json
{
  "query": "<改写后的自然语言选股条件>",
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
        "query": "今日涨跌幅大于5%, 流通市值大于100亿, 属于人工智能板块",
        "page": "1", "limit": "10", "is_cache": "1", "expand_index": "true",
    }).encode(),
    headers={
        "Authorization": f"Bearer {os.environ['IWENCAI_API_KEY']}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": "hithink-astock-selector",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    },
)
print(urllib.request.urlopen(req, timeout=30).read().decode())
```

或：`python3 ../internal-skills/hithink-astock-selector/scripts/cli.py "<query>"`

## Query 改写流程（强制 6 步）

1. **接收原始 query**——读取用户口语化输入
2. **拆解意图**——多个独立问题就拆成多次调用，单一意图直接进 3
3. **改写为标准问句**：
   - 口语 → 金融术语（"AI 股" → "属于人工智能板块"、"便宜的股票" → "PE 小于 X"）
   - 条件用逗号分隔
   - 保留用户核心意图，过滤主观/无法量化的形容词（"好"、"稳定"）
4. **调 API**
5. **空数据处理**：返回 `datas` 为空时，**放宽** query 重试，最多 2 次
   - 第 1 次重试：去掉最苛刻的条件
   - 第 2 次重试：进一步简化或用更通用表述
   - 仍空再告知用户「未筛到符合条件的股票」
6. **回答**：明确说明最终使用的查询语句，必要时说明做了哪些放宽

## 返回字段

- `datas`：A 股列表，每项含 `股票代码`（如 `002840.SZ`）、`股票简称`、查询条件涉及的字段值
- `code_count`：符合条件的总股票数（可能远大于 `len(datas)`）
- `chunks_info`：本次 query 拆解信息

> **分页**：`code_count > len(datas)` 时，通过递增 `page` 翻页拿完整结果。

## NEVER 规则

- ❌ 不要把口语化模糊词原样塞 query（"好股票"、"稳定的"）——网关会返回奇怪结果。
- ❌ 不要看到空 datas 就直接告诉用户"没结果"——必须先放宽 2 次。
- ❌ 不要把多个完全独立的选股请求并到一次 query（如同时筛 ROE 高的和 ROE 低的），拆成两次调用。
- ❌ 不要把 `datas` 包装成自定义结构后再交给上层。问财网关「条件六」要求透传。

## 输出与汇报

- 把 `datas` 透传给上层 LLM，由 LLM 做表格化展示
- 必须明确告知用户**最终使用的 query 语句**（含改写后的版本）
- 数据来源标注：「数据来源：同花顺问财（A 股选股）」
- 涉及推荐 / 投资建议时：补加风险提示「以上结果仅为筛选，不构成投资建议」

## 不在本 reference 范围

- 港股 / 美股 / ETF / 基金 / 期货期权选股 —— 需安装对应 `wencai-h-stock-selector` 等 skill
- 单只股票详细行情查询 → [`market-data.md`](market-data.md)
- 单只股票详细财务查询 → [`financial-data.md`](financial-data.md)
- 单只股票评级 → [`institutional-research.md`](institutional-research.md)
