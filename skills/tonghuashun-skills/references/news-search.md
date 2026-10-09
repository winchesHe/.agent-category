# news-search：财经新闻 / 资讯搜索

> 官方 SKILL.md 原文见 [`../internal-skills/news-search/SKILL.md`](../internal-skills/news-search/SKILL.md)；本文是供 AI 路由的精简摘要。

## 适用场景

- 财经新闻搜索（行业 / 公司 / 主题）
- 政策动态查询（央行 / 监管 / 行业政策）
- 行业趋势 / 革新 / 业务进展
- 市场动态跟踪（股 / 债 / 商品 / 外汇 等市场资讯面）
- 公司业务消息（含上市与非上市公司）

**典型用户问句**：
- "最近人工智能行业有什么新政策？"
- "央行最近发布了什么货币政策？"
- "特斯拉最近的业务进展如何？"

## 接口信息

| 项 | 值 |
|---|---|
| Base URL | `https://openapi.iwencai.com` |
| 路径 | `POST /v1/comprehensive/search` |
| Skill-Id | `news-search` |
| Skill-Version | `1.0.0` |
| 鉴权 | `Authorization: Bearer $IWENCAI_API_KEY` |

### 必填 Header

```
Authorization: Bearer $IWENCAI_API_KEY
Content-Type: application/json
X-Claw-Call-Type: normal      # 重试时改 retry
X-Claw-Skill-Id: news-search
X-Claw-Skill-Version: 1.0.0
X-Claw-Plugin-Id: none
X-Claw-Plugin-Version: none
X-Claw-Trace-Id: <64-hex>     # secrets.token_hex(32)，每次新生成
```

### 请求体

```json
{
  "channels": ["news"],
  "app_id": "AIME_SKILL",
  "query": "<改写后的标准化查询关键词>"
}
```

**`channels` 固定为 `["news"]`，不要改成 announcement / report。**

## 典型调用

```bash
TRACE_ID=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
curl -X POST https://openapi.iwencai.com/v1/comprehensive/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IWENCAI_API_KEY" \
  -H "X-Claw-Call-Type: normal" \
  -H "X-Claw-Skill-Id: news-search" \
  -H "X-Claw-Skill-Version: 1.0.0" \
  -H "X-Claw-Plugin-Id: none" \
  -H "X-Claw-Plugin-Version: none" \
  -H "X-Claw-Trace-Id: $TRACE_ID" \
  -d '{"channels":["news"],"app_id":"AIME_SKILL","query":"人工智能"}'
```

Python 版（最小依赖）：

```python
import os, json, secrets, urllib.request

req = urllib.request.Request(
    "https://openapi.iwencai.com/v1/comprehensive/search",
    data=json.dumps({"channels":["news"],"app_id":"AIME_SKILL","query":"人工智能"}).encode(),
    headers={
        "Authorization": f"Bearer {os.environ['IWENCAI_API_KEY']}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": "news-search",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    },
)
print(urllib.request.urlopen(req, timeout=30).read().decode())
```

或直接用安装目录里的脚本：`python3 ../internal-skills/news-search/scripts/news_search.py "<query>"`。

## Query 改写要点

- 复杂问题拆解为多个独立 query 分别调用（如"AI 和芯片行业新闻" → 两次：`AI 行业动态` + `芯片行业新闻`）
- 口语化转标准金融术语
- 关键词不要太长，保留主体（行业名 / 公司名 / 政策名）

## NEVER 规则

- ❌ 不要修改 `channels`、`app_id`；否则路由到其他检索服务，返回空或 400。
- ❌ 不要把 API 返回的 `data` 字段二次重组成自定义结构。问财网关「条件六」要求透传。
- ❌ 不要在 `query` 里塞代码 / 特殊符号 / 长段文本，只放检索关键词。

## 输出与汇报

- 直接把网关 JSON 透传给上层 LLM 做总结
- 用户回答中必须显式标注："数据来源：同花顺问财财经资讯搜索"
- 若拆解为多次调用，回答中说明最终用了哪几个子查询

## 不在本 reference 范围

- 公告 / 财报披露 → [`announcement-search.md`](announcement-search.md)
- 研报 / 分析师报告 → [`report-search.md`](report-search.md)
- 行情数据 / 股价 → [`market-data.md`](market-data.md)
