# mx-moni：妙想模拟组合管理（A 股模拟交易）

> 官方 SKILL.md 原文见 `~/skills/mx-moni/SKILL.md`；本文是供 AI 路由的精简摘要。

## ⚠️ macOS 首次使用前必读：修复硬编码路径

**问题**：mx-moni 在 `import` 阶段就执行 `os.makedirs('/root/.openclaw/workspace/mx_data/output', exist_ok=True)`，
macOS 用户没有 `/root` 写权限会直接抛 `PermissionError`，脚本无法加载。

**修复方案（任选一种，执行一次即可，升级 mx-moni 后需重做）**：

方案 A（推荐，修改源文件）：

```bash
# 把硬编码的 /root 路径改为 macOS 可写路径
sed -i.bak "s|OUTPUT_DIR = '/root/.openclaw/workspace/mx_data/output'|OUTPUT_DIR = os.path.expanduser('~/skills/mx-moni/output')|" \
  /Users/moego-winches/skills/mx-moni/mx_moni.py
mkdir -p /Users/moego-winches/skills/mx-moni/output
# 校验
grep -n "^OUTPUT_DIR" /Users/moego-winches/skills/mx-moni/mx_moni.py
```

方案 B（不改源文件，给 /root 软链接）：

```bash
sudo mkdir -p /root/.openclaw/workspace/mx_data
sudo ln -s /Users/moego-winches/skills/mx-moni/output /root/.openclaw/workspace/mx_data/output
```

> 方案 A 干净，方案 B 需要 sudo；推荐方案 A。**未修复前不要调用 mx-moni 任何子命令**。

## 适用场景

- **持仓查询**：当前账户的持仓股票、成本、市值、当日盈亏
- **买入 / 卖出**：限价委托或市价委托（`useMarketPrice=true`）
- **撤单**：撤指定委托或一键撤当日所有未成交
- **委托查询**：当日 / 历史委托（含已成、未成、撤单）
- **资金查询**：可用余额、总资产、冻结金额、仓位百分比
- **经验交流发帖**：调仓总结 / 心得分享

**仅支持 A 股**（6 位数字代码），不支持港股 / 美股 / 期货 / 期权 / 基金的模拟交易。

**前置要求**：用户必须先在妙想 Skills 页面（<https://dl.dfcfs.com/m/itc4>）创建模拟账户并绑定模拟组合，否则调用任意子命令会返回 `404 未绑定模拟组合账户`。

## 调用方式

**强制前置**：

1. 已按"§ macOS 首次使用前必读"完成路径修复
2. 已确认用户绑定了模拟账户
3. `set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a`

```bash
set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a; \
python3 /Users/moego-winches/skills/mx-moni/mx_moni.py "<自然语言指令>"
```

## 常见调用示例

```bash
# === 查询 ===
python3 ~/skills/mx-moni/mx_moni.py "我的资金"
python3 ~/skills/mx-moni/mx_moni.py "我的持仓"
python3 ~/skills/mx-moni/mx_moni.py "我的委托"
python3 ~/skills/mx-moni/mx_moni.py "查询成交记录"

# === 交易 ===
# 限价买入：买入 贵州茅台 600519，价格 1700 元，100 股
python3 ~/skills/mx-moni/mx_moni.py "买入 600519 1700 100"

# 市价买入：市价买入 万科A 000002，1000 股
python3 ~/skills/mx-moni/mx_moni.py "市价买入 000002 1000"

# 限价卖出 / 市价卖出
python3 ~/skills/mx-moni/mx_moni.py "卖出 600519 1750 100"
python3 ~/skills/mx-moni/mx_moni.py "市价卖出 000002 500"

# === 撤单 ===
python3 ~/skills/mx-moni/mx_moni.py "撤单 261030200000048829"
python3 ~/skills/mx-moni/mx_moni.py "一键撤单"

# === 经验发帖 ===
python3 ~/skills/mx-moni/mx_moni.py "发一下操作帖"
python3 ~/skills/mx-moni/mx_moni.py --auto-post   # 自动检测今日操作并提示
```

## 接口速查

| 功能 | 路径 | 关键参数 |
|---|---|---|
| 持仓查询 | `POST /api/claw/mockTrading/positions` | `moneyUnit: 1` |
| 买入卖出 | `POST /api/claw/mockTrading/trade` | `type` (buy/sell)、`stockCode`、`price`、`quantity`、`useMarketPrice` |
| 撤单 | `POST /api/claw/mockTrading/cancel` | `orderId` + `stockCode` 或 `type: all` |
| 委托查询 | `POST /api/claw/mockTrading/orders` | `fltOrderDrt` (0/1/2)、`fltOrderStatus` |
| 资金查询 | `POST /api/claw/mockTrading/balance` | `moneyUnit: 1` |
| 经验发帖 | `POST /api/claw/mockTrading/newPost` | `text`（必须 UTF-8 编码，Header 加 `charset=UTF-8`）|

所有路径都拼接在 `${MX_API_URL}`（默认 `https://mkapi2.dfcfs.com/finskillshub`）之后；脚本已封装。

## 输出文件

| 文件 | 说明 |
|---|---|
| `~/skills/mx-moni/output/mx_moni_<query>_<timestamp>.json` | API 原始响应 |
| `~/skills/mx-moni/output/mx_moni_<query>_<timestamp>.txt` | 人类可读总结 |

## 关键约定

- **股票代码**：仅支持 A 股 6 位数字（如 `600519`、`000001`），脚本自动识别市场（沪 / 深 / 北）
- **委托数量**：必须是 100 整数倍（A 股最小交易单位 1 手 = 100 股），否则交易所拒单
- **价格精度**：沪市 ≤ 2 位小数，深市 ≤ 3 位小数（`useMarketPrice=true` 时忽略 `price`）
- **委托状态**：1 未报 / 2 已报 / 3 部成 / 4 已成 / 5 部成待撤 / 6 已报待撤 / 7 部撤 / 8 已撤 / 9 废单 / 10 撤单失败

## 异常处理

| 错误码 | 含义 | 处理 |
|---|---|---|
| 113 | 调用次数已达上限 | 妙想页面续费 |
| 114 | API 密钥不存在 / 失效 | 重置 key、更新 `.env` |
| 115 | 请求未携带 API 密钥 | 检查 `MX_APIKEY` 是否注入（先 source .env）|
| 116 | API 密钥不存在 | 同 114 |
| 404 | 未绑定模拟组合账户 | 引导用户去 <https://dl.dfcfs.com/m/itc4> 创建并绑定 |
| 501 | "买入委托失败：当前时间不可交易" | A 股交易时段外（9:30-11:30、13:00-15:00 之外）|
| `PermissionError: '/root/...'` | 没做 macOS 路径修复 | 执行 § 顶部修复 sed |

## NEVER 规则

- ❌ **不要替用户执行真实意图不明的 trade / cancel**——所有写操作（买入 / 卖出 / 撤单 / 发帖）执行前在响应里**明确说出参数**（代码 / 价格 / 数量 / 方向），获得用户确认再调；这是写操作的硬性安全护栏。
- ❌ **不要把模拟数据当真实账户**——回答里必须出现 "模拟交易" 或 "模拟组合" 字样，避免用户误以为是真实资金。
- ❌ **不要给出"建议买入 X" / "建议卖出 Y"**——本 skill 是模拟交易工具，不是投资顾问。
- ❌ **不要在非交易时段强推 trade**——会拿到 `501 当前时间不可交易`，浪费一次调用；先 `我的资金 / 我的持仓` 做查询类响应即可。
- ❌ **不要在 newPost 时用非 UTF-8 编码**——会乱码；保持 Python 默认编码即可，但**不要从外部 GBK 文件管道注入**。
- ❌ **不要跳过 macOS 路径修复直接调脚本**——会在 `import` 时崩溃，没有任何错误提示给用户。

## 输出与汇报

- 查询类（持仓 / 资金 / 委托）：直接呈现关键数值（市值 / 盈亏 / 仓位 / 委托状态）
- 交易类（buy / sell / cancel）：先复述操作、求用户确认 → 执行 → 复述结果（`orderId` + `status`）
- 发帖类：先生成内容草稿给用户审阅 → 确认后再 POST
- 末尾标注："数据来源：东方财富妙想模拟组合（非真实交易）"

## 不在本 reference 范围

- 真实 A 股行情 / 财务数据 → [`mx-data.md`](mx-data.md)
- 新闻 / 公告 / 研报 → [`mx-search.md`](mx-search.md)
- 选股 → [`mx-xuangu.md`](mx-xuangu.md)
- 自选股管理 → [`mx-zixuan.md`](mx-zixuan.md)
- **港股 / 美股 / 期货 / 期权 / 基金的模拟交易**（mx-moni 仅 A 股）
- **真实资金交易**（本 skill 只做模拟）
