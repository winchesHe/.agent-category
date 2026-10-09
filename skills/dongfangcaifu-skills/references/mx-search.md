# mx-search：妙想金融资讯搜索

> 官方 SKILL.md 原文见 `~/skills/mx-search/SKILL.md`；本文是供 AI 路由的精简摘要。

## 适用场景

- **个股资讯**：最新公告、研报、机构观点
- **行业 / 板块新闻**：政策解读、业务进展、热点事件
- **宏观 / 市场分析**：美联储动作对 A 股影响、大盘异动原因、北向资金流向解读
- **个股事件**：分红派息、定增、增持减持、重组解读
- **交易规则**：科创板涨跌幅、新股申购规则、停复牌制度

**典型用户问句**：

- "贵州茅台最新公告"
- "人工智能板块近期新闻"
- "美联储加息对 A 股影响分析"
- "宁德时代定增预案解读"
- "科创板交易涨跌幅限制"

## 与 mx-data 的区别

| 维度 | mx-data | mx-search |
|---|---|---|
| 数据形态 | 结构化数值（价格、财务指标）| 非结构化文本（新闻正文、公告摘要、研报解读）|
| 时效要求 | 当前最新值 | 最近 N 天动态、特定事件解读 |
| 典型问句 | "茅台最新价 / ROE / 净利润" | "茅台最新研报 / 茅台分红公告" |

混淆点：「贵州茅台最新公告」走 mx-search（要的是公告文本），「贵州茅台公司基本资料」走 mx-data（要结构化字段）。

## 调用方式

**强制前置**：`set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a`

```bash
set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a; \
python3 /Users/moego-winches/skills/mx-search/mx_search.py "<自然语言问句>" /Users/moego-winches/skills/mx-search/output
```

参数：

| 位置 | 名称 | 必填 | 说明 |
|---|---|---|---|
| 1 | query | 是 | 自然语言问句 |
| 2 | output_dir | macOS 必填 | 推荐 `~/skills/mx-search/output` |

## 输出文件

| 文件 | 说明 |
|---|---|
| `mx_search_<query>.txt` | 提取后的纯文本结果（标题 / 来源 / 日期 / 内容） |
| `mx_search_<query>.json` | 网关原始 JSON，含 `secuList`（关联证券）、`trunk`（正文）等结构化字段 |

终端会格式化输出每条资讯（标题 + 来源 + 日期 + 摘要），便于直接读取。

## 常见调用示例

```bash
# 个股资讯
python3 ~/skills/mx-search/mx_search.py "东方财富最新公告" ~/skills/mx-search/output
python3 ~/skills/mx-search/mx_search.py "贵州茅台最新研报" ~/skills/mx-search/output

# 行业 / 板块
python3 ~/skills/mx-search/mx_search.py "人工智能板块近期新闻" ~/skills/mx-search/output
python3 ~/skills/mx-search/mx_search.py "新能源汽车产业政策最新解读" ~/skills/mx-search/output

# 宏观与市场
python3 ~/skills/mx-search/mx_search.py "美联储加息对A股影响分析" ~/skills/mx-search/output
python3 ~/skills/mx-search/mx_search.py "今日大盘异动原因分析" ~/skills/mx-search/output
python3 ~/skills/mx-search/mx_search.py "北向资金最新流向解读" ~/skills/mx-search/output

# 交易规则
python3 ~/skills/mx-search/mx_search.py "科创板交易涨跌幅限制" ~/skills/mx-search/output
```

## 返回字段速查

| 字段 | 释义 |
|---|---|
| `title` | 资讯标题 |
| `secuList[].secuCode` | 关联证券代码（如 002475） |
| `secuList[].secuName` | 关联证券名称（如立讯精密） |
| `secuList[].secuType` | 证券类型（股票 / 债券） |
| `trunk` | 信息核心正文 / 结构化数据块 |

## 异常处理

| 错误 | 原因 | 处理 |
|---|---|---|
| `401 / API密钥不存在` | MX_APIKEY 失效 | 重置 key 并更新 `.env` |
| `code=113` | 当日额度用尽 | 妙想页面续费 |
| `未找到相关资讯` | 关键词太偏 / 没有最新动态 | 换关键词、缩小到具体公司 / 时间 |
| `JSON 解析错误` | 网络中断 | 重试 |

## NEVER 规则

- ❌ 不要把 mx-search 用在结构化指标查询上（如 "茅台 ROE"），那是 mx-data 的活；走错路径会拿到泛泛新闻文本，浪费一轮调用。
- ❌ 不要在 query 里塞过长描述 / 代码片段；保留主体（公司名 + 事件 / 板块 + 主题）。
- ❌ 不要把搜索结果当 "我知道的" 转述；必须明确说明来源是新闻 / 公告 / 研报，并附 `title` 与 `secuList`。

## 输出与汇报

- 列出命中的关键资讯（标题 + 日期 + 摘要 + 关联证券）
- 综合多条资讯时给出整体趋势 / 共识 / 分歧
- 末尾标注："数据来源：东方财富妙想资讯搜索"

## 不在本 reference 范围

- 实时行情 / 财务数据 → [`mx-data.md`](mx-data.md)
- 选股筛选 → [`mx-xuangu.md`](mx-xuangu.md)
- 自选股 → [`mx-zixuan.md`](mx-zixuan.md)
- 模拟交易 → [`mx-moni.md`](mx-moni.md)
