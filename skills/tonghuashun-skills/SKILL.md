---
name: tonghuashun-skills
description: "手动触发的同花顺问财金融数据入口：仅当用户明确指定使用同花顺问财或 tonghuashun-skills 时使用；按意图路由财经资讯、公告、研报、行情、评级、财务、基本资料、A 股或板块筛选和公司经营数据。"
---

# Tonghuashun Skills（同花顺问财 10 个官方 skill 的语义索引）

本 skill 不实现网关请求逻辑，而是把 `iwencai-skillhub-cli` 已安装到 [`internal-skills/`](internal-skills/) 下的 10 个官方 skill 作为执行底座，按用户意图把上下文路由到 [`references/`](references/) 下对应领域的精简文档。

## 前置条件

| 项 | 说明 |
|---|---|
| CLI 工具 | `iwencai-skillhub-cli` 已安装（路径 `~/.local/bin/`），用于（重）安装具体 skill。`iwencai-skillhub-cli install <slug>` |
| API Key | 必填环境变量 `IWENCAI_API_KEY`（已落到本 skill 目录 `.env`，**任务开始前必须 source 注入**，详见下方 § 任务开始第一件事） |
| Base URL | `IWENCAI_BASE_URL=https://openapi.iwencai.com`（环境变量可省略，默认值就是这个） |
| skill 目录 | [`internal-skills/<slug>/`](internal-skills/) 下保存了每个 skill 的官方 `internal-skill.md`、`scripts/cli.py` 或 `scripts/<skill>.py` 入口和示例 |

> **NEVER 把 API Key 提交到 git**——所有 skill 都从环境变量读取，不接受命令行参数传 Key。

## ⚠️ 任务开始第一件事：注入 .env（强制前置步骤）

每个 Claude Code 会话的 shell 环境**不会自动加载** `tonghuashun-skills/.env`，直接调 cli 会被网关 401 拒绝：
```json
{"error": "API 密钥未设置..."}
```

**任何调用 internal-skills/*/scripts/cli.py 的 Bash 命令，第一段必须是**：

```bash
set -a; source /Users/moego-winches/Desktop/Company/person/agent-workspace/.claude/skills/tonghuashun-skills/.env; set +a
```

推荐写法（与后续 cli 调用合并到同一个 Bash 工具调用里，避免环境变量在跨调用间丢失）：

```bash
set -a; source /Users/moego-winches/Desktop/Company/person/agent-workspace/.claude/skills/tonghuashun-skills/.env; set +a; \
python3 /Users/moego-winches/Desktop/Company/person/agent-workspace/.claude/skills/tonghuashun-skills/internal-skills/<slug>/scripts/cli.py --query "<问句>" --limit 10
```

- ✅ **同一条 Bash 命令里同时做 source + cli 调用**——子 shell 环境不会泄漏到下次 Bash 工具调用，所以「上一次 source 过」不算数。
- ✅ 并行批量查询时，每个 Bash 工具调用都各自带一遍 `set -a; source ...; set +a`，不要假设它们共享环境。
- ❌ 不要把 `IWENCAI_API_KEY` 直接拼到命令行（会进 shell history）；只通过 source .env 注入。
- ❌ 如果 `.env` 不存在或为空，**先停下来询问用户**而不是继续盲调 cli。

## 调用约定

| 约定 | 说明 |
|---|---|
| 网关 URL | 新闻 / 公告 / 研报 走 `/v1/comprehensive/search`；其余 hithink-* 数据查询走 `/v1/query2data` |
| 必填 Header | `Authorization: Bearer $IWENCAI_API_KEY`、`X-Claw-Skill-Id: <slug>`、`X-Claw-Skill-Version: <ver>`、`X-Claw-Plugin-Id: none`、`X-Claw-Plugin-Version: none`、`X-Claw-Call-Type: normal\|retry`、`X-Claw-Trace-Id: <64-hex>` |
| Trace ID | 每次请求新生成，64 位十六进制（`python3 -c 'import secrets; print(secrets.token_hex(32))'`），不可复用 |
| 透传原则 | **必须** 把网关返回 JSON 原样透传给上层 LLM，不得二次解析 / 包装 / 改键，错误响应也照传（除非网络层超时/连接失败） |
| 失败重试 | 网关错误时，`X-Claw-Call-Type` 设为 `retry` 再调；空数据时放宽 query 改写，最多 2 次 |
| 数据来源标注 | 回答用户时**必须** 显式说明 "数据来源：同花顺问财" |

## 场景决策树（用户意图 → reference / skill slug）

| 用户意图（中英关键词） | 路由到 |
|---|---|
| 财经新闻 / 政策动态 / 行业新闻 / 公司新闻 / 央行 / 板块热点 / 舆情 | [`news-search.md`](references/news-search.md) → slug `news-search` |
| 公告 / 财报披露 / 分红派息 / 回购 / 增持 / 减持 / 资产重组 / 定增 / A 股 港股 基金 ETF 公告 | [`announcement-search.md`](references/announcement-search.md) → slug `announcement-search` |
| 研报 / 研究报告 / 券商深度报告 / 投资逻辑 / 分析师观点 / 目标价 | [`report-search.md`](references/report-search.md) → slug `report-search` |
| 实时股价 / ETF 行情 / 指数行情 / 涨跌幅 / 成交量 / 成交额 / 主力资金流 / 大小单 / 技术指标（MA/MACD/KDJ/RSI） | [`market-data.md`](references/market-data.md) → slug `hithink-market-query` |
| 研报评级 / 业绩预测 / ESG 评级 / 信用评级 / 主体评级 / 基金评级 / 券商金股 / 一致预期 | [`institutional-research.md`](references/institutional-research.md) → slug `hithink-insresearch-query` |
| 营业收入 / 净利润 / ROE / ROA / 负债率 / 现金流 / 毛利率 / 净利率 / 财务指标 / 三大报表 | [`financial-data.md`](references/financial-data.md) → slug `hithink-finance-query` |
| 股票基本信息 / 基金资料 / 期货合约 / 期权合约 / 债券资料 / 费率 / 上市日期 / 发行主体 / 机构资料 | [`basic-info.md`](references/basic-info.md) → slug `hithink-basicinfo-query` |
| 选股 / A 股筛选 / 自然语言选股 / 多条件组合 / 技术形态选股 / 概念股 + 财务指标 / 问财选 A 股 | [`wencai-a-stock.md`](references/wencai-a-stock.md) → slug `hithink-astock-selector` |
| 选板块 / 行业板块 / 概念板块 / 地域板块 / 板块涨跌幅 / 板块资金流 / 板块估值 / 问财选板块 | [`sector-selector.md`](references/sector-selector.md) → slug `hithink-sector-selector` |
| 主营业务构成 / 主要客户 / 供应商 / 参控股公司 / 子公司 / 股权投资 / 重大合同 / 公司经营数据 | [`business-data.md`](references/business-data.md) → slug `hithink-business-query` |

## 领域术语对照

| 用户说法 | 同花顺概念 | reference |
|---|---|---|
| 新闻 / 消息 / 资讯 | 综合资讯（channels=news） | `news-search.md` |
| 公告 / 财报披露 | 综合资讯（channels=announcement） | `announcement-search.md` |
| 研报 / 报告 | 综合资讯（channels=report） | `report-search.md` |
| 股价 / K 线 / 涨幅 / 资金流 / 主力 / 大单 | query2data 行情类 | `market-data.md` |
| 评级 / 金股 / ESG / 业绩预测 | query2data 机构类 | `institutional-research.md` |
| 营收 / 净利润 / ROE / 财务报表指标 | query2data 财务类 | `financial-data.md` |
| 基本信息 / 资料 / 费率 / 发行 / 上市 | query2data 基本资料类 | `basic-info.md` |
| 选股 / 筛选 / "找几只..." | query2data 选股类（自然语言转 query） | `wencai-a-stock.md` |
| 选板块 / 行业 / 概念 / 地域板块 | query2data 板块筛选类（自然语言转 query） | `sector-selector.md` |
| 主营业务 / 客户 / 供应商 / 子公司 / 重大合同 | query2data 公司经营类（自然语言转 query） | `business-data.md` |

## skill slug 速查表

| 中文名 | slug | API 路径 | 版本 | 主要返回字段 |
|---|---|---|---|---|
| 新闻搜索 | `news-search` | `/v1/comprehensive/search` | 1.0.0 | 综合 news 资讯列表 |
| 公告搜索 | `announcement-search` | `/v1/comprehensive/search` | 1.0.0 | 公告资讯列表（含定期报告 / 分红派息 / 回购增持 / 资产重组） |
| 研报搜索 | `report-search` | `/v1/comprehensive/search` | 2.0.0 | 研报列表（含评级 / 目标价 / 摘要） |
| 行情数据查询 | `hithink-market-query` | `/v1/query2data` | 1.0.0 | `datas` 数组（含股票代码 / 简称 + 行情字段） |
| 机构研究与评级查询 | `hithink-insresearch-query` | `/v1/query2data` | 1.0.0 | `datas` 数组（评级 / 一致预期 / ESG / 金股） |
| 财务数据查询 | `hithink-finance-query` | `/v1/query2data` | 1.0.0 | `datas` 数组（营收 / 利润 / ROE / 现金流） |
| 基本资料查询 | `hithink-basicinfo-query` | `/v1/query2data` | 1.0.0 | `datas` 数组（基本资料 / 发行 / 上市 / 费率） |
| 问财选 A 股 | `hithink-astock-selector` | `/v1/query2data` | 1.0.0 | `datas`（股票列表）+ `code_count`（总数）+ `chunks_info` |
| 问财选板块 | `hithink-sector-selector` | `/v1/query2data` | 1.0.0 | `datas`（板块列表，含板块名称 / 涨跌幅 / 资金流等）+ `code_count` + `chunks_info` |
| 公司经营数据查询 | `hithink-business-query` | `/v1/query2data` | 1.0.0 | `datas`（经营数据列表，含主营 / 客户 / 供应商 / 参控股 / 重大合同）+ `code_count` + `chunks_info` |

## NEVER 规则

- ❌ **不要在 source .env 之前直接调 cli**——首次调用必 401，浪费一轮工具调用。
  **Why**：Claude Code 每次 Bash 工具调用都是新 shell，`IWENCAI_API_KEY` 不会从前一次跨过来。`.env` 文件必须每次显式 source。
  **如何应用**：进入本 skill 后，**第一个 Bash 调用必须**以 `set -a; source <skill 根目录>/.env; set +a;` 开头；后续每个并行 / 串行的 cli Bash 调用都重复这一段，**不要图省事跳过**。

- ❌ **不要把 API Key 硬编码 / 写进示例文件 / 提交到 git**。
  **Why**：API Key 一旦泄露相当于他人可以代为查问财，且共享配额会被耗尽。
  **如何应用**：所有 skill 的 cli/SDK 只接受 `os.environ["IWENCAI_API_KEY"]` 注入；从 .env 加载也只读到环境变量，不写入 repo 跟踪文件。

- ❌ **不要对网关返回 JSON 做二次包装 / 改键 / 过滤后再交付**。
  **Why**：问财 OpenAPI 网关「条件六」要求透明传递。包装后排查问题时，网关日志和上层数据不一致。
  **如何应用**：cli / SDK 输出层一律 `return response.json()` 或 `print(response.text)`；改写 / 总结由上层 LLM 完成。

- ❌ **不要复用 X-Claw-Trace-Id**。
  **Why**：网关用 Trace-Id 追踪请求全链路；复用会让两次请求被合并视为同一笔，监控错乱。
  **如何应用**：每次请求前用 `secrets.token_hex(32)` 重新生成，与 timestamp、参数无关。

- ❌ **不要在新闻 / 公告 / 研报场景调用 query2data**，也**不要**在行情 / 财务 / 基本资料场景调用 comprehensive/search。
  **Why**：两条线后端是不同检索服务；走错路径会得到 400 或空列表。
  **如何应用**：按"决策树 / skill slug 速查表"路由，不要凭直觉拼接 URL。

- ❌ **不要把数据来源说成"我自己查的"**。
  **Why**：本 skill 全部数据来自同花顺问财，合规要求必须标注来源。
  **如何应用**：每次回答末尾补一句 "数据来源：同花顺问财"。

- ❌ **不要为 `hithink-astock-selector` / `hithink-sector-selector` / `hithink-business-query` 等"自然语言查询"类 skill 静默放弃空数据**。
  **Why**：空数据通常是 query 改写太苛刻，简化后能拿到结果；直接放弃用户体验差。
  **如何应用**：空数据 → 简化条件重试（最多 2 次，`X-Claw-Call-Type` 改为 `retry`）→ 仍空才告知用户，并说明最终查询语句。

- ❌ **不要混淆"个股选股 / 板块筛选 / 公司经营数据"三类查询**。
  **Why**：三者底座 slug 不同（`hithink-astock-selector` / `hithink-sector-selector` / `hithink-business-query`），返回字段也不同。例如「半导体板块涨幅」走 `sector-selector`，「半导体板块里的个股」走 `astock-selector`，「某半导体公司主营业务」走 `business-query`。
  **如何应用**：用户问句里出现"板块"且关心整体（涨跌幅 / 资金流 / 估值）→ `sector-selector`；出现"哪些股票 / 哪些个股 / 选股"→ `astock-selector`；出现具体公司 + 经营关键词（主营 / 客户 / 供应商 / 子公司 / 合同）→ `business-query`。

## References 加载时机

| Reference | 触发关键词 | 是否首次必读 |
|---|---|---|
| [`news-search.md`](references/news-search.md) | 新闻 / 资讯 / 政策 / 央行 / 行业动态 / 板块热点 / 舆情 / 重大事件 | 否 |
| [`announcement-search.md`](references/announcement-search.md) | 公告 / 财报披露 / 分红 / 回购 / 增持 / 减持 / 资产重组 / 定增 / 解禁 | 否 |
| [`report-search.md`](references/report-search.md) | 研报 / 研究报告 / 券商深度 / 投资逻辑 / 目标价 / 分析师 | 否 |
| [`market-data.md`](references/market-data.md) | 股价 / 涨跌幅 / 成交量 / 成交额 / 资金流 / 主力 / 大小单 / 技术指标 / ETF / 指数 | 否 |
| [`institutional-research.md`](references/institutional-research.md) | 评级 / 业绩预测 / ESG / 信用评级 / 主体评级 / 基金评级 / 金股 / 一致预期 | 否 |
| [`financial-data.md`](references/financial-data.md) | 营收 / 净利润 / ROE / ROA / 毛利率 / 净利率 / 负债率 / 现金流 / 财务报表 | 否 |
| [`basic-info.md`](references/basic-info.md) | 股票基本信息 / 资料 / 发行 / 上市日期 / 上市地点 / 费率 / 合约 | 否 |
| [`wencai-a-stock.md`](references/wencai-a-stock.md) | 选股 / 筛选 / 找股票 / 自然语言选股 / 多条件组合 / 技术形态 + 财务 + 概念 | 否 |
| [`sector-selector.md`](references/sector-selector.md) | 选板块 / 行业板块 / 概念板块 / 地域板块 / 板块涨跌幅 / 板块资金流 / 板块估值 | 否 |
| [`business-data.md`](references/business-data.md) | 主营业务构成 / 主要客户 / 供应商 / 参控股公司 / 子公司 / 股权投资 / 重大合同 | 否 |

> 加载策略：用户意图命中决策树后，**只读取对应单份 reference**；涉及多领域的复合任务（如"找 ROE 大于 15 且最近有研报评级买入的股票"），分别加载 `wencai-a-stock.md` + `institutional-research.md` 两份。

## 安装与升级（参考）

如需重新安装某个 skill：

```bash
# 全部 10 个 skill 一次性安装到当前 tonghuashun-skills/internal-skills/
cd tonghuashun-skills
for slug in news-search announcement-search report-search \
            hithink-market-query hithink-insresearch-query \
            hithink-finance-query hithink-basicinfo-query \
            hithink-astock-selector \
            hithink-sector-selector hithink-business-query; do
  iwencai-skillhub-cli --dir ./internal-skills install "$slug" --force
done

# 配置环境变量（仅首次）
curl -fsSL https://www.iwencai.com/skillhub/static/0.0.4/setup_iwencai_env.sh \
  | bash -s -- --IWENCAI_API_KEY="<your-key>" --IWENCAI_BASE_URL=https://openapi.iwencai.com
```

## 溯源

- iwencai SkillHub 商店：https://www.iwencai.com/skillhub
- 各 skill 官方文档在 [`internal-skills/<slug>/internal-skill.md`](internal-skills/)（由 `iwencai-skillhub-cli install` 拉取后重命名）
- 网关规范见每个 skill 内部的"问财OpenAPI网关规范"章节
