# business-data：公司经营数据查询（主营业务 / 客户 / 供应商 / 参控股 / 重大合同）

> 官方 SKILL.md 原文见 [`../internal-skills/hithink-business-query/SKILL.md`](../internal-skills/hithink-business-query/SKILL.md)。

## 适用场景

单家上市公司的"经营层面"数据（不是行情，也不是三大报表里的总览数字），覆盖：

- **主营业务构成**：产品 / 地区 / 收入占比
- **主要客户**：客户名称、销售占比、上下游集中度
- **供应商**：供应商名称、采购占比
- **参控股公司**：子公司 / 参股公司 / 控股比例
- **股权投资**：对外股权投资金额、被投公司
- **重大合同**：合同金额、对手方、披露日期

**典型用户问句**：
- "同花顺主营业务构成"
- "贵州茅台的主要客户有哪些？"
- "宁德时代前五大供应商是谁？"
- "比亚迪有哪些子公司？"
- "万科最近签了哪些重大合同？"
- "美的集团的股权投资情况"

## 接口信息

| 项 | 值 |
|---|---|
| 路径 | `POST /v1/query2data` |
| Skill-Id | `hithink-business-query` |
| Skill-Version | `1.0.0` |

### 请求体

```json
{
  "query": "<改写后的自然语言经营数据查询>",
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
        "query": "同花顺主营业务构成",
        "page": "1", "limit": "10", "is_cache": "1", "expand_index": "true",
    }).encode(),
    headers={
        "Authorization": f"Bearer {os.environ['IWENCAI_API_KEY']}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": "hithink-business-query",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    },
)
print(urllib.request.urlopen(req, timeout=30).read().decode())
```

或：`python3 ../internal-skills/hithink-business-query/scripts/cli.py --query "<query>"`

## Query 改写要点

- **公司必须明确**：用全称（"贵州茅台" 而非 "茅台"，"宁德时代" 而非 "宁王"），缺主语时网关无法定位
- **查询类型精确**：明确使用"主营业务构成 / 主要客户 / 供应商 / 参控股公司 / 股权投资 / 重大合同"等标准词
- **常用改写示例**：

| 用户原始问句 | 改写后查询 |
|-------------|-----------|
| 同花顺是做什么的 | 同花顺主营业务构成 |
| 茅台的主要客户有哪些 | 贵州茅台主要客户 |
| 这家公司有哪些子公司 | <公司名> 参控股公司 |
| 最近签了哪些大合同 | <公司名> 重大合同 |
| 投了什么 | <公司名> 股权投资 |

## 空数据处理（强制）

`datas` 为空时，**最多重试 2 次**（重试请求 `X-Claw-Call-Type` 改为 `retry`），仍空再告知用户：

1. 第 1 次重试：去掉过于苛刻的条件、保留核心实体 + 经营数据类型
2. 第 2 次重试：换更通用表述（如 "主要客户" → "前五大客户"）
3. 仍空：告知用户「未查询到该公司的经营数据」，引导到 https://www.iwencai.com/unifiedwap/chat

## 返回字段

- `datas`：经营数据对象数组，含 `股票代码`（如 "300033.SZ"）、`股票简称` 以及查询条件相关字段（业务类型 / 收入占比 / 客户名称 / 子公司名称 等）
- `code_count`：符合条件的总记录数（可能远大于 `len(datas)`）
- `chunks_info`：本次查询拆解信息

> **分页**：`code_count > len(datas)` 时，通过递增 `page` 翻页拿完整结果。

**响应示例：**

```json
{
  "datas": [
    {"股票代码": "300033.SZ", "股票简称": "同花顺", "业务类型": "金融信息服务", "收入占比": "85.23%"}
  ],
  "code_count": 5236,
  "chunks_info": {
    "query": "同花顺主营业务构成",
    "parsed_conditions": ["同花顺", "主营业务构成"]
  }
}
```

## NEVER 规则

- ❌ 不要在缺公司主语的情况下调用（如直接 "主要客户有哪些"）——必须先与用户确认或从上下文补全公司全称。
- ❌ 不要把"主营业务收入数字"和"营业总收入"混淆——后者属于财务报表，请走 [`financial-data.md`](financial-data.md)。
- ❌ 不要把口语词原样塞 query（"投了什么"、"做啥的"）——先改写为标准查询词。
- ❌ 不要把 `datas` 包装成自定义结构后再交给上层。问财网关「条件六」要求透传。
- ❌ 不要看到空 `datas` 就直接告诉用户"没结果"——必须先放宽 2 次重试。

## 输出与汇报

- 把 `datas` 透传给上层 LLM，由 LLM 做表格化展示（主营业务构成、客户名单、参控股表格等都适合表格）
- 必须明确告知用户**最终使用的 query 语句**
- 数据来源标注：「数据来源：同花顺问财（公司经营数据）」
- 涉及推荐 / 投资建议时：补加风险提示「以上结果仅供参考，不构成投资建议」

## 不在本 reference 范围

- 营收 / 净利润 / ROE / 现金流 等财务报表科目 → [`financial-data.md`](financial-data.md)
- 实时股价 / 涨跌幅 / 成交量 → [`market-data.md`](market-data.md)
- 公司基本信息（上市日期 / 注册资本 / 主营范围） → [`basic-info.md`](basic-info.md)
- 研报 / 评级 / 一致预期 → [`institutional-research.md`](institutional-research.md)
- 公告披露（分红 / 增减持 / 资产重组） → [`announcement-search.md`](announcement-search.md)
