# mx-data：妙想金融数据查询

> 官方 SKILL.md 原文见 `~/skills/mx-data/SKILL.md`；本文是供 AI 路由的精简摘要。

## 适用场景

- 个股 / 板块 / 指数 / 基金 / 债券的**实时行情**（最新价、涨跌幅、成交量、成交额、量比、换手率）
- **历史行情**（日 / 周 / 月 K 线、近 N 年年报 / 季报收盘价、复权价）
- **主力资金流向**、大单 / 中单 / 小单、北向资金
- **财务数据**（营收、净利润、ROE、ROA、负债率、毛利率、现金流、近 N 年 / N 季度对比）
- **公司基本信息**（主营业务、董事长、总股本、市值、成立时间、上市日期）
- **股东结构**（十大股东、机构持股、股东户数、增减持记录）
- **板块 / 指数**（沪深 300 点位、新能源板块涨跌、成分股平均涨跌幅）

**典型用户问句**：

- "东方财富最新价"
- "贵州茅台近五年净利润 营业收入"
- "比亚迪近一年每个交易日的开盘价收盘价成交量"
- "宁德时代主力资金流向"
- "沪深 300 指数最新点位 涨跌幅"
- "贵州茅台十大股东"

## 调用方式

**强制前置**：`set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a`

```bash
# 推荐写法（一条 Bash 调用搞定 source + 查询）
set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a; \
python3 /Users/moego-winches/skills/mx-data/mx_data.py "<自然语言问句>" /Users/moego-winches/skills/mx-data/output
```

参数：

| 位置 | 名称 | 必填 | 说明 |
|---|---|---|---|
| 1 | query | 是 | 自然语言问句，如 `"贵州茅台近三年净利润"` |
| 2 | output_dir | macOS 必填 | 输出目录，推荐 `~/skills/mx-data/output`；省略会写 `/root/...` 失败 |

## 输出文件

调用一次会在 output_dir 下生成 3 个文件（文件名前缀 `mx_data_<query>`）：

| 文件 | 说明 |
|---|---|
| `mx_data_<query>.xlsx` | Excel，每个数据表一个 sheet；列名已转中文 |
| `mx_data_<query>_description.txt` | 查询条件、命中证券、结果统计的人类可读摘要 |
| `mx_data_<query>_raw.json` | 网关返回的原始 JSON，供二次开发 / 字段溯源 |

终端会先输出前 20 行预览（markdown 表格），便于直接读取。

## 常见调用示例

```bash
# 实时行情
python3 ~/skills/mx-data/mx_data.py "东方财富最新价" ~/skills/mx-data/output
python3 ~/skills/mx-data/mx_data.py "贵州茅台今日收盘价 涨跌幅" ~/skills/mx-data/output

# 历史行情（注意控制时间跨度，避免上下文爆炸）
python3 ~/skills/mx-data/mx_data.py "贵州茅台近五年年报收盘价" ~/skills/mx-data/output

# 财务数据
python3 ~/skills/mx-data/mx_data.py "东方财富每股收益 净资产收益率 近五年" ~/skills/mx-data/output

# 公司基本信息
python3 ~/skills/mx-data/mx_data.py "比亚迪公司简介 主营业务 成立时间" ~/skills/mx-data/output

# 股东信息
python3 ~/skills/mx-data/mx_data.py "贵州茅台十大股东" ~/skills/mx-data/output

# 板块 / 指数
python3 ~/skills/mx-data/mx_data.py "沪深300指数最新点位 涨跌幅" ~/skills/mx-data/output
```

## 异常处理

| 错误 | 原因 | 处理 |
|---|---|---|
| `401 / code=114 / API密钥不存在` | MX_APIKEY 错误或失效 | 前往 <https://dl.dfcfs.com/m/itc4> 重置 key 并更新 `.env` |
| `code=113 / 今日调用次数已达上限` | 当日额度用尽 | 妙想页面续费 |
| `数据结果为空 / No dataTable found` | 查询条件不支持 / 太严苛 | 放宽条件、确认证券名称 / 代码拼写 |
| `Connection refused` | 无法访问 mkapi2.dfcfs.com | 检查网络出口 |
| `PermissionError: [Errno 13] / root/...` | 没传 output 参数，脚本去写 `/root/...` | 显式传 `~/skills/mx-data/output` |

## NEVER 规则

- ❌ 不要查询超大时间跨度（如某股票近 3 年每日最新价 ≈ 720+ 行）→ 拆成"按年汇总"或缩小为"近 30 天" / "近 1 季度"。
- ❌ 不要把网关返回的 xlsx 字段二次重命名后再展示给用户（脚本已经做了中文列名映射，原样引用即可）。
- ❌ 不要省略 output 参数（macOS 必崩）。
- ❌ 不要回答 "数据为本人记忆" / "可能不准"——本 skill 数据是东方财富权威库实时拉取的，应当直接引用并标注来源。

## 输出与汇报

- 基于 xlsx 内容总结，引用具体数值（如 "近 5 年 ROE 分别为 X / Y / Z"）
- 回答末尾必须标注："数据来源：东方财富妙想"
- 如果是多表（多 sheet）xlsx，先说明命中了哪几个指标 / 证券，再给数据

## 不在本 reference 范围

- 新闻 / 公告 / 研报 → [`mx-search.md`](mx-search.md)
- 选股筛选 → [`mx-xuangu.md`](mx-xuangu.md)
- 自选股管理 → [`mx-zixuan.md`](mx-zixuan.md)
- 模拟交易 → [`mx-moni.md`](mx-moni.md)
