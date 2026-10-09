# sector-selector：问财选板块（自然语言多条件筛选板块）

> 官方 SKILL.md 原文见 [`../internal-skills/hithink-sector-selector/SKILL.md`](../internal-skills/hithink-sector-selector/SKILL.md)。

## 适用场景

A 股**板块**层面的自然语言筛选（注意：是板块，不是个股；个股筛选走 [`wencai-a-stock.md`](wencai-a-stock.md)）。支持多条件组合：

- **行业估值**：PE / PB / 估值分位（如 "PE 小于 20 的行业板块"）
- **资金流向**：主力资金净流入 / 北向资金 / 大单流入
- **涨跌幅**：涨幅前 N / 跌幅榜 / 区间涨跌幅
- **板块类型**：行业板块 / 概念板块 / 地域板块
- **成交量**：成交额 / 换手率
- **多条件组合**：上述任意维度叠加

**典型用户问句**：
- "今日涨幅最大的板块有哪些？"
- "主力资金净流入前十的概念板块"
- "PE 小于 20、近 5 日上涨的行业板块"
- "换手率排名前五的板块"
- "新能源相关的概念板块涨跌幅"

## 接口信息

| 项 | 值 |
|---|---|
| 路径 | `POST /v1/query2data` |
| Skill-Id | `hithink-sector-selector` |
| Skill-Version | `1.0.0` |

### 请求体

```json
{
  "query": "<改写后的自然语言选板块条件>",
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
        "query": "今日涨幅前十的概念板块",
        "page": "1", "limit": "10", "is_cache": "1", "expand_index": "true",
    }).encode(),
    headers={
        "Authorization": f"Bearer {os.environ['IWENCAI_API_KEY']}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": "hithink-sector-selector",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    },
)
print(urllib.request.urlopen(req, timeout=30).read().decode())
```

或：`python3 ../internal-skills/hithink-sector-selector/scripts/cli.py --query "<query>"`

## Query 改写流程（强制 6 步）

1. **接收原始 query**——读取用户口语化输入
2. **拆解意图**——多个独立板块问题就拆成多次调用，单一意图直接进 3
3. **改写为标准问句**：
   - 口语 → 金融术语（"涨得好的板块" → "涨幅前五的板块"；"便宜的行业" → "PE 小于 X 的行业板块"）
   - 条件用逗号分隔
   - 明确指出板块类型（行业 / 概念 / 地域），不要遗漏
4. **调 API**
5. **空数据处理**：返回 `datas` 为空时，**放宽** query 重试，最多 2 次（重试时 `X-Claw-Call-Type` 改为 `retry`）
   - 第 1 次重试：去掉最苛刻的条件
   - 第 2 次重试：进一步简化或换更通用表述
   - 仍空再告知用户「未筛到符合条件的板块」
6. **回答**：明确说明最终使用的查询语句，必要时说明做了哪些放宽

## 返回字段

- `datas`：板块对象数组，含 `板块名称`（如 "半导体"）、涨跌幅、主力资金净流入等查询条件涉及的字段
- `code_count`：符合条件的总板块数（可能远大于 `len(datas)`）
- `chunks_info`：本次 query 拆解信息

> **分页**：`code_count > len(datas)` 时，通过递增 `page` 翻页拿完整结果。

**响应示例：**

```json
{
  "datas": [
    {"板块名称": "半导体", "涨跌幅": 3.25, "主力资金净流入": "50亿"},
    {"板块名称": "人工智能", "涨跌幅": 2.85, "主力资金净流入": "35亿"}
  ],
  "code_count": 50,
  "chunks_info": {
    "query": "涨幅前五的板块",
    "parsed_conditions": ["涨跌幅排名前五"]
  }
}
```

## NEVER 规则

- ❌ **不要把"板块"和"个股"混在同一次 query**——本 skill 只返回板块名称及其聚合指标，不返回成分股。要个股请用 [`wencai-a-stock.md`](wencai-a-stock.md)。
- ❌ 不要把口语化模糊词原样塞 query（"好板块"、"热门板块"）——网关会返回奇怪结果。
- ❌ 不要看到空 `datas` 就直接告诉用户"没结果"——必须先放宽 2 次重试。
- ❌ 不要把 `datas` 包装成自定义结构后再交给上层。问财网关「条件六」要求透传。

## 输出与汇报

- 把 `datas` 透传给上层 LLM，由 LLM 做表格化展示
- 必须明确告知用户**最终使用的 query 语句**（含改写后的版本）
- 数据来源标注：「数据来源：同花顺问财（问财选板块）」
- 涉及推荐 / 投资建议时：补加风险提示「以上结果仅为筛选，不构成投资建议」

## 不在本 reference 范围

- 个股自然语言选股 → [`wencai-a-stock.md`](wencai-a-stock.md)
- 板块成分股、单只股票详细行情 → [`market-data.md`](market-data.md)
- 板块财务汇总 / 行业财务对比 → [`financial-data.md`](financial-data.md)
- ETF / 港股 / 美股板块 —— 本 skill 未覆盖，需安装对应 wencai skill
