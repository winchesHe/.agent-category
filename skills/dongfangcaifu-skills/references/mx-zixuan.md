# mx-zixuan：妙想自选股管理

> 官方 SKILL.md 原文见 `~/skills/mx-zixuan/SKILL.md`；本文是供 AI 路由的精简摘要。

## 适用场景

- 查询当前账户下的**自选股列表**（含最新价、涨跌幅、换手率、量比）
- **添加股票到自选**（支持股票名称或代码）
- **从自选删除股票**

数据归属：东方财富通行证账户（用户的妙想 API Key 已与账户绑定）。

**典型用户问句**：

- "查询我的自选股列表" / "我的自选" / "看一下自选"
- "把贵州茅台添加到自选" / "加入自选 比亚迪"
- "从我的自选股列表删除万科 A" / "删除自选 万科 A"

## 调用方式

**强制前置**：`set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a`

支持「显式子命令」和「自然语言」两种入参：

```bash
set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a

# 查询
python3 /Users/moego-winches/skills/mx-zixuan/mx_zixuan.py query --output-dir /Users/moego-winches/skills/mx-zixuan/output
# 或自然语言
python3 /Users/moego-winches/skills/mx-zixuan/mx_zixuan.py "查询我的自选股列表" --output-dir /Users/moego-winches/skills/mx-zixuan/output

# 添加
python3 /Users/moego-winches/skills/mx-zixuan/mx_zixuan.py add "贵州茅台" --output-dir /Users/moego-winches/skills/mx-zixuan/output
python3 /Users/moego-winches/skills/mx-zixuan/mx_zixuan.py add "300059" --output-dir /Users/moego-winches/skills/mx-zixuan/output
# 或自然语言
python3 /Users/moego-winches/skills/mx-zixuan/mx_zixuan.py "把贵州茅台添加到我的自选股列表" --output-dir /Users/moego-winches/skills/mx-zixuan/output

# 删除
python3 /Users/moego-winches/skills/mx-zixuan/mx_zixuan.py delete "贵州茅台" --output-dir /Users/moego-winches/skills/mx-zixuan/output
# 或自然语言
python3 /Users/moego-winches/skills/mx-zixuan/mx_zixuan.py "把万科A从我的自选股列表删除" --output-dir /Users/moego-winches/skills/mx-zixuan/output
```

参数：

| 位置 | 名称 | 必填 | 说明 |
|---|---|---|---|
| 1 | 子命令 `query` / `add` / `delete` 或自然语言问句 | 是 | 自然语言会被脚本自动识别意图 |
| 2 | 股票名称 / 代码（仅 add / delete 子命令需要） | add/delete 必填 | 推荐 6 位数字代码（成功率更高） |
| `--output-dir` | macOS 必填 | 推荐 `~/skills/mx-zixuan/output` | |

## 输出文件

| 文件 | 说明 |
|---|---|
| `mx_zixuan_<query>.csv` | 自选股列表 CSV（查询场景生成；add/delete 后建议再查一次刷新） |
| `mx_zixuan_<query>_raw.json` | 接口原始 JSON |

终端会先输出 ASCII 表格（代码 / 名称 / 最新价 / 涨跌幅 / 换手率 / 量比），可直接读取。

## 接口路径速查

| 操作 | 路径 | Header |
|---|---|---|
| 查询 | `POST https://mkapi2.dfcfs.com/finskillshub/api/claw/self-select/get` | `apikey: $MX_APIKEY` |
| 增 / 删 | `POST https://mkapi2.dfcfs.com/finskillshub/api/claw/self-select/manage` | `apikey: $MX_APIKEY`、body `{"query": "<自然语言指令>"}` |

## 异常处理

| 错误 | 原因 | 处理 |
|---|---|---|
| `401 / API密钥不存在` | key 失效 | 重置并更新 `.env` |
| `code=113` | 额度用尽 | 续费 |
| `自选股列表为空` | 账户下没自选 | 提示用户先 add 或在东方财富 App 添加 |
| `找不到该股票` | 名称 / 代码错 | 改用 6 位代码（如 600519） |
| `操作失败` | 添加时已存在 / 删除时不存在 | 先 query 确认当前列表再操作 |

## NEVER 规则

- ❌ 不要在没有 query 确认列表的情况下批量 add / delete——可能重复添加或删错。
- ❌ 不要把"自选"误路由到 mx-data（mx-data 是指标查询，自选是账户绑定的列表概念）。
- ❌ 不要替用户做无授权的 add / delete——执行写操作前在响应里明确说明"即将添加 X 到自选股，确认？"，得到确认再调。

## 输出与汇报

- query：列出表格 + 总数
- add / delete：复述操作前后差异（"已添加 X，当前共 N 只自选股"）
- 标注"数据来源：东方财富妙想"

## 不在本 reference 范围

- 自选股的实时指标查询 / K 线 → 拿到自选股代码后转 [`mx-data.md`](mx-data.md)
- 把自选股拿去模拟买卖 → [`mx-moni.md`](mx-moni.md)
- 找新股加入自选 → 先 [`mx-xuangu.md`](mx-xuangu.md) 选股，再 add
