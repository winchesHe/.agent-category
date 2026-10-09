# mx-xuangu：妙想智能选股

> 官方 SKILL.md 原文见 `~/skills/mx-xuangu/SKILL.md`；本文是供 AI 路由的精简摘要。

## 适用场景

- **行情条件筛选**：涨幅 > X%、成交量 > Y、股价区间、市盈率 < N、市净率 < N
- **财务条件筛选**：净利润增长 > X%、ROE > N%、股息率 > N%
- **行业 / 板块筛选**：新能源板块 + 市盈率 < 30、白酒板块涨幅 > 1%、半导体毛利率 > 40%
- **指数成分股筛选**：沪深 300 成分股中分红率最高 10 只、创业板成分股 + 市盈率 < 30
- **组合条件**：价格 < 20 + 市盈率 < 20 + 涨幅 > 1% + A 股
- **A 股个股 / 上市公司 / 板块 / 指数推荐**

**典型用户问句**：

- "今日涨幅大于 2% 的 A 股"
- "净资产收益率大于 15% 的公司"
- "新能源板块市盈率小于 30 的股票"
- "沪深 300 成分股中分红率最高的 10 只股票"
- "ROE 大于 15% 且净利润连续三年增长"

## 与 mx-data 的区别

| 维度 | mx-data | mx-xuangu |
|---|---|---|
| 输入 | 已知证券（"东方财富 最新价"） | 选股条件，证券未知（"涨幅 > 2% 的 A 股"） |
| 输出 | 单 / 多证券的指标值 | 满足条件的证券列表 + 统计 |
| 典型动词 | "查 / 看 / 给我 X 的 Y" | "找 / 筛选 / 推荐满足条件的股票" |

## 调用方式

**强制前置**：`set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a`

```bash
set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a; \
python3 /Users/moego-winches/skills/mx-xuangu/mx_xuangu.py "<自然语言选股条件>" --output-dir /Users/moego-winches/skills/mx-xuangu/output
```

参数：

| 名称 | 必填 | 说明 |
|---|---|---|
| 位置参数 / `--query` | 是 | 自然语言选股条件 |
| `--output-dir` | macOS 必填 | 推荐 `~/skills/mx-xuangu/output` |

## 输出文件

| 文件 | 说明 |
|---|---|
| `mx_xuangu_<query>.csv` | 筛选结果，所有列名已转中文（股票代码 / 简称 / 最新价 / 涨跌幅 / ... ） |
| `mx_xuangu_<query>_description.txt` | 筛选条件解析 + 各条件命中数 + 总数 |
| `mx_xuangu_<query>_raw.json` | 网关原始 JSON，含 `columns` 列定义、`dataList` 行数据 |

## 常见调用示例

```bash
# 行情条件
python3 ~/skills/mx-xuangu/mx_xuangu.py "今日涨幅大于2%的A股" --output-dir ~/skills/mx-xuangu/output
python3 ~/skills/mx-xuangu/mx_xuangu.py "市盈率小于20并且市净率小于2" --output-dir ~/skills/mx-xuangu/output

# 财务条件
python3 ~/skills/mx-xuangu/mx_xuangu.py "净利润增长率大于30%的股票" --output-dir ~/skills/mx-xuangu/output
python3 ~/skills/mx-xuangu/mx_xuangu.py "股息率大于3%的银行股" --output-dir ~/skills/mx-xuangu/output

# 行业 / 板块
python3 ~/skills/mx-xuangu/mx_xuangu.py "新能源板块市盈率小于30的股票" --output-dir ~/skills/mx-xuangu/output

# 指数成分股
python3 ~/skills/mx-xuangu/mx_xuangu.py "沪深300成分股中分红率最高的10只股票" --output-dir ~/skills/mx-xuangu/output

# 组合条件
python3 ~/skills/mx-xuangu/mx_xuangu.py "价格小于20元 市盈率小于20 涨幅大于1% A股" --output-dir ~/skills/mx-xuangu/output
python3 ~/skills/mx-xuangu/mx_xuangu.py "ROE大于15% 净利润连续三年增长" --output-dir ~/skills/mx-xuangu/output
```

## 返回字段速查

顶层：

| 字段 | 释义 |
|---|---|
| `data.data.result.total` | 选股结果总数量 |
| `data.data.result.columns` | 表格列定义（含中文 title / 业务 key / 单位 / 排序方式） |
| `data.data.result.dataList` | 行数据数组，每个元素 = 一只满足条件的股票 |
| `data.data.responseConditionList` | 各单条件的命中数（用于诊断哪个条件最严苛） |
| `data.data.totalCondition` | 组合条件描述 + 总命中数 |
| `data.data.parserText` | 选股条件的解析文本（；分隔） |

dataList 行核心键：

| key | 释义 |
|---|---|
| `SECURITY_CODE` | 股票代码（如 603866） |
| `SECURITY_SHORT_NAME` | 股票简称 |
| `MARKET_SHORT_NAME` | 市场（SH/SZ） |
| `NEWEST_PRICE` | 最新价 |
| `CHG` | 涨跌幅（%） |
| `PCHG` | 涨跌额（元） |

## 异常处理

| 错误 | 原因 | 处理 |
|---|---|---|
| `401 / API密钥不存在` | key 失效 | 重置并更新 `.env` |
| `code=113` | 额度用尽 | 续费 |
| `0 rows / 筛选结果为空` | 条件太严苛 | 放宽数值阈值、减少叠加条件 |
| `解析选股条件失败` | 自然语言歧义太大 | 重写更明确的条件描述（标准金融术语） |

## NEVER 规则

- ❌ 不要在结果为空时直接告诉用户"找不到"——先看 `responseConditionList` 哪个条件命中数为 0，放宽该条件再重试一次。
- ❌ 不要在选股条件里混入"近 N 天"等时间范围（这是 mx-data 的能力）；选股是当前快照。
- ❌ 不要把选股结果当推荐 / 投资建议输出；只陈述命中列表 + 字段含义。

## 输出与汇报

- 先说"命中 N 只股票"
- 列出前 10-20 只（代码 / 名称 / 关键指标）；超过 20 只补一句 "完整列表见 CSV 文件路径"
- 标注"数据来源：东方财富妙想"

## 不在本 reference 范围

- 已知证券的指标查询 → [`mx-data.md`](mx-data.md)
- 选股结果的新闻 / 研报跟进 → [`mx-search.md`](mx-search.md)
- 把选股结果加自选 → [`mx-zixuan.md`](mx-zixuan.md)
- 模拟下单 → [`mx-moni.md`](mx-moni.md)
