---
name: dongfangcaifu-skills
description: 仅在明确指定东方财富妙想或 dongfangcaifu-skills 时查询金融数据、选股及管理自选股和模拟交易。
---

# Dongfangcaifu Skills（东方财富妙想 5 个官方 skill 的语义索引）

本 skill 不实现网关请求逻辑，而是把已安装在 `~/skills/` 下的 5 个官方妙想 skill 作为执行底座，
按用户意图把上下文路由到 [`references/`](references/) 下对应领域的精简文档。

## 前置条件

| 项 | 说明 |
|---|---|
| API Key | 必填环境变量 `MX_APIKEY`（已落到本 skill 目录 `.env`，**任务开始前必须 source 注入**，详见下方 § 任务开始第一件事） |
| Python 依赖 | `pandas`、`requests`、`openpyxl`（已通过 `pip3 install` 安装；缺失时 `pip3 install pandas requests openpyxl`） |
| Skill 解压位置 | `~/skills/mx-data/`、`~/skills/mx-search/`、`~/skills/mx-xuangu/`、`~/skills/mx-zixuan/`、`~/skills/mx-moni/` |
| 网关地址 | `https://mkapi2.dfcfs.com`（脚本内置，无需配置） |
| 平台兼容性 | macOS 上脚本默认输出目录是 Linux 路径 `/root/.openclaw/workspace/mx_data/output/`，**必须在调用时显式传 output 目录**（见各 reference） |

> **NEVER 把 API Key 提交到 git**——所有 skill 都从环境变量 `MX_APIKEY` 读取；本目录 `.gitignore` 已排除 `.env`。

## ⚠️ 任务开始第一件事：注入 .env（强制前置步骤）

`MX_APIKEY` **只存在本 skill 目录的 `.env` 文件中**——刻意不写入 `~/.zshrc`，避免全局污染、
避免 key 散落在多个位置难以同步。不 source 就直接调脚本会被网关 401 拒绝（`code=114 / API密钥不存在`）。

**任何调用 `~/skills/mx-*/mx_*.py` 的 Bash 命令，第一段必须是**：

```bash
set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a
```

推荐写法（与后续脚本调用合并到同一个 Bash 工具调用里，避免环境变量在跨调用间丢失）：

```bash
set -a; source /Users/moego-winches/Desktop/Company/person/skills/dongfangcaifu-skills/.env; set +a; \
python3 /Users/moego-winches/skills/<slug>/<slug>.py "<自然语言问句>" /Users/moego-winches/skills/<slug>/output
```

- ✅ **同一条 Bash 命令里同时做 source + 脚本调用**——子 shell 环境不会泄漏到下次 Bash 工具调用，上次 source 过不算数。
- ✅ 并行批量查询时，每个 Bash 工具调用都各自带一遍 `set -a; source ...; set +a`。
- ❌ 不要把 `MX_APIKEY` 直接拼到命令行（会进 shell history）；只通过 source .env 注入。
- ❌ 如果 `.env` 不存在或为空，**先停下来询问用户**而不是继续盲调脚本。

## 调用约定

| 约定 | 说明 |
|---|---|
| 网关 URL | 所有 skill 走 `https://mkapi2.dfcfs.com`（脚本内置，无需在请求里拼）|
| 必填 Header | `apikey: $MX_APIKEY`（脚本自动从环境变量读取）|
| 入参形式 | 自然语言问句字符串，作为第一个位置参数传给 `python3 mx_*.py "..."` |
| 输出目录 | macOS 上**必须**显式传 `~/skills/<slug>/output`，否则脚本会尝试写 `/root/...` 失败 |
| 透传原则 | 脚本输出（xlsx / csv / json / txt）原样保留，回答用户时基于文件内容总结，不二次伪造 |
| 失败重试 | 网关返回 `code=114`（key 失效）→ 提示用户更新 .env；`code=113`（次数超限）→ 提示去妙想页面续费 |
| 数据来源标注 | 回答用户时**必须**显式说明 "数据来源：东方财富妙想" |

## 场景决策树（用户意图 → reference / skill slug）

| 用户意图（中英关键词） | 路由到 |
|---|---|
| 个股 / 行业 / 板块 / 指数 / 基金 / 债券 实时行情 / 历史 K 线 / 主力资金流 / 估值 / 财务报表 / 股东 / 高管 / 公司基本资料 | [`mx-data.md`](references/mx-data.md) → slug `mx-data` |
| 新闻 / 公告 / 研报 / 政策解读 / 事件影响 / 板块解读 / 北向资金流向 / 大盘异动原因 / 交易规则 | [`mx-search.md`](references/mx-search.md) → slug `mx-search` |
| 选股 / A 股筛选 / 自然语言选股 / 行情条件 + 财务条件 + 行业板块 / 指数成分股筛选 | [`mx-xuangu.md`](references/mx-xuangu.md) → slug `mx-xuangu` |
| 自选股 / 查询自选 / 添加自选 / 删除自选 / "把 X 加到自选" | [`mx-zixuan.md`](references/mx-zixuan.md) → slug `mx-zixuan` |
| 模拟炒股 / 模拟交易 / 模拟买入卖出 / 模拟持仓 / 模拟资金 / 模拟撤单 / 模拟委托 / 交易经验发帖 | [`mx-moni.md`](references/mx-moni.md) → slug `mx-moni` |

## 领域术语对照

| 用户说法 | 妙想概念 | reference |
|---|---|---|
| 股价 / 涨幅 / K 线 / 主力 / 大单 / 净利润 / ROE / 股东 / 公司资料 | 金融数据查询 | `mx-data.md` |
| 新闻 / 消息 / 公告 / 研报 / 政策 / 异动解读 / 北向资金 | 资讯搜索 | `mx-search.md` |
| 选股 / 筛选 / "找几只..." | 智能选股 | `mx-xuangu.md` |
| 自选 / 关注列表 / watchlist | 自选股管理 | `mx-zixuan.md` |
| 模拟炒股 / 练手 / 验证策略 / 模拟账户 | 模拟组合管理 | `mx-moni.md` |

## skill slug 速查表

| 中文名 | slug | 入口脚本 | 主要输出 |
|---|---|---|---|
| 妙想金融数据 | `mx-data` | `~/skills/mx-data/mx_data.py` | 多 sheet xlsx + description.txt + raw.json |
| 妙想资讯搜索 | `mx-search` | `~/skills/mx-search/mx_search.py` | 提取后纯文本 .txt + raw .json |
| 妙想智能选股 | `mx-xuangu` | `~/skills/mx-xuangu/mx_xuangu.py` | 选股结果 .csv + description.txt + raw.json |
| 妙想自选股管理 | `mx-zixuan` | `~/skills/mx-zixuan/mx_zixuan.py` | 自选股 .csv + raw.json |
| 妙想模拟组合管理 | `mx-moni` | `~/skills/mx-moni/mx_moni.py` | 操作结果 .txt + .json |

## NEVER 规则

- ❌ **不要在 source .env 之前直接调脚本**——首次调用必 401，浪费一轮工具调用。
  **Why**：Claude Code 每次 Bash 工具调用都是新 zsh 子 shell + shell-snapshot，`MX_APIKEY` 不会从前一次跨过来；本 skill 刻意不污染 `~/.zshrc`，所以必须每次显式 source `.env`。
  **如何应用**：进入本 skill 后，**第一个 Bash 调用必须**以 `set -a; source <skill 根目录>/.env; set +a;` 开头；后续每个并行 / 串行的 Bash 调用都重复这一段，不要图省事跳过。

- ❌ **不要在 macOS 上调用脚本时省略 output 目录参数**——所有 5 个脚本默认输出到 `/root/.openclaw/workspace/mx_data/output/`，macOS 没有 `/root` 写权限，会直接挂掉。
  **Why**：脚本由妙想团队按 Linux 容器场景写的，未做平台适配。
  **如何应用**：mx-data / mx-search 通过第二个位置参数传 output 目录；mx-xuangu / mx-zixuan 用 `--output-dir`；mx-moni 在 import 阶段就 `os.makedirs('/root/...')`，**首次使用前必须先修复**（见 `mx-moni.md`）。

- ❌ **不要把 API Key 硬编码 / 写进示例文件 / 提交到 git**。
  **Why**：API Key 一旦泄露相当于他人可以代为查妙想，且共享配额会被耗尽。
  **如何应用**：脚本只接受 `os.environ["MX_APIKEY"]`；从 .env 加载也只读到环境变量，`.gitignore` 已排除 `.env`。

- ❌ **不要对脚本输出的 xlsx / csv / json 做二次伪造 / 篡改**。
  **Why**：妙想 OpenAPI 数据来自东方财富权威库，二次包装可能引入错误，回答用户时也无法溯源。
  **如何应用**：基于文件内容做总结、引用具体字段；如需变换格式（如转 markdown 表格），保持数据与原文件一致。

- ❌ **不要把数据来源说成 "我自己查的" 或 "网络搜索的"**。
  **Why**：本 skill 全部数据来自东方财富妙想，合规要求必须标注来源。
  **如何应用**：每次回答末尾补一句 "数据来源：东方财富妙想"，资讯类可细化为 "数据来源：东方财富妙想资讯搜索"。

- ❌ **不要在大数据范围查询时不做拆分**（如某只股票 5 年的每日最新价 = 1200+ 行）。
  **Why**：返回内容过多会导致模型上下文爆炸 + xlsx 文件过大。
  **如何应用**：跨度大的查询拆为多次（按年 / 季度），或改成"年度 / 月度"粒度。

- ❌ **不要把 mx-moni 当真实交易接口用 / 给出投资建议**。
  **Why**：模拟组合仅供学习与策略验证；给出真实买卖建议属于无证投资咨询。
  **如何应用**：mx-moni 调用前先提示用户"以下为模拟交易，非真实资金"；不附带"建议买入"/ "建议卖出"等措辞。

## References 加载时机

| Reference | 触发关键词 | 是否首次必读 |
|---|---|---|
| [`mx-data.md`](references/mx-data.md) | 股价 / 涨跌幅 / K 线 / 主力 / 资金流 / 净利润 / ROE / 股东 / 公司基本资料 / 板块行情 | 否 |
| [`mx-search.md`](references/mx-search.md) | 新闻 / 资讯 / 公告 / 研报 / 政策 / 异动 / 北向资金 / 美联储影响 / 交易规则 | 否 |
| [`mx-xuangu.md`](references/mx-xuangu.md) | 选股 / 筛选 / 找股票 / 自然语言选股 / 多条件组合 / 行业 + 财务 + 行情 | 否 |
| [`mx-zixuan.md`](references/mx-zixuan.md) | 自选股 / 关注 / 加自选 / 删自选 / 查自选 | 否 |
| [`mx-moni.md`](references/mx-moni.md) | 模拟交易 / 模拟炒股 / 持仓 / 买入卖出 / 撤单 / 委托 / 经验发帖 | 是（首次使用 mx-moni 前必读，含 macOS 修复步骤） |

> 加载策略：用户意图命中决策树后，**只读取对应单份 reference**；涉及多领域的复合任务
>（如"先选出 ROE > 15% 的股票，再查这些股票的最新研报"），分别加载 `mx-xuangu.md` + `mx-search.md` 两份。

## 安装与升级（参考）

5 个 skill 已通过以下流程安装到 `~/skills/`：

```bash
# 1. 下载并解压（已完成，无需重复）
mkdir -p ~/skills
for url in \
  "https://marketing.dfcfw.com/res/download/A620260331IHX67H.zip" \
  "https://marketing.dfcfw.com/res/download/A620260331K5WDTK.zip" \
  "https://marketing.dfcfw.com/res/download/A620260331NXBVEY.zip" \
  "https://marketing.dfcfw.com/res/download/A6202603314TMGR1.zip" \
  "https://marketing.dfcfw.com/res/download/A620260514F818FC.zip"; do
  curl -fsSL -o /tmp/mx.zip "$url" && unzip -o -q /tmp/mx.zip -d ~/skills/
done

# 2. 安装 python 运行时依赖
pip3 install pandas requests openpyxl

# 3. 配置 API Key（已完成）
#    - 填入本 skill 目录 .env（不写入 ~/.zshrc，避免全局污染、避免 key 多处散落）
#    - agent / 脚本调用前显式 source <skill 根目录>/.env
```

升级单个 skill：重新下载对应 zip 解压覆盖 `~/skills/<slug>/` 即可；
注意 mx-moni 升级后需重做 `mx-moni.md` 里的 macOS 路径修复。

## 溯源

- 妙想 Skills 商店 / API Key 申请：<https://dl.dfcfs.com/m/itc4>
- 5 个官方 SKILL.md 原文：`~/skills/<slug>/SKILL.md`
- 返回字段释义见对应 reference 的"返回字段"小节
