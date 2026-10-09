---
name: twitter-user-posts
description: 拉取并缓存固定 X/Twitter 用户的最新帖子、长文和配图。
---

# twitter-user-posts

抓取 `users.txt` 里指定 X/Twitter 用户最近 N 小时（默认 24h，**滚动窗口**）的 post，含图片附件，按 `post_id` 缓存到本地。
重复拉取时**只 fetch 缓存里没有的 id**，已缓存的直接复用。

`users.txt` 按主题**分组**维护，目前覆盖：

- `# === stock ===` 股票/财经博主（A 股、海外华人投资资讯、宏观/政策）
- `# === AI ===` AI 相关（研究者、产品作者、AI 资讯/趋势聚合）

也可以临时追加任何主题的推主——脚本本身与主题无关，只负责"拉一批 handle 的 post + 落 cache + 出报告"。

## 何时使用

- 用户说"看下/同步/拉一下那几个推主的最近 X 条 post / 文章 / 图片"。
- 用户说"加一个推主到监控列表 / 改一下监控用户"——直接编辑 `users.txt`。
- 用户问某条历史 post——先看 `cache/<user>/<post_id>.json` 是否已缓存。

不适合：
- 抓取不在 `users.txt` 里的临时用户（直接调 `autocli twitter user-posts` 即可，无需缓存）。
- 单条 post 的详情查看（用 `autocli twitter thread --url ...`）。

## Users 选择规则（**必读**）

**根据用户意图选择 `users.txt` 里的子集**——不要默认把所有用户都拉一遍。除非用户明确说"全部 / 全员 / 所有推主"，否则按下表选：

| 用户意图（关键词触发） | 选择的分组 | 用什么命令 |
|---|---|---|
| 股票 / 财经 / A 股 / 港股 / 行情 / 大盘 / 复盘 / 个股 / 宏观 / 政策 / 板块 | `# === stock ===` 段下的用户 | `fetch_user_v2.sh handle1 handle2 ...`（多 handle 批量） |
| AI / LLM / 大模型 / 模型发布 / Prompt / Agent / Coding / 论文 / GitHub trending / 开源 | `# === AI ===` 段下的用户 | 同上 |
| 同时关心两类（"今天的动态" / "全部" / 没明确） | 全部用户 | `fetch_all_v2.sh`（直接吃整份 users.txt） |
| 用户点名了具体推主（"karpathy / 每日快讯 说了啥"） | 仅该推主 | `fetch_user_v2.sh <handle>` |

具体执行步骤：

1. **先读 `users.txt`**（`Read` 工具），按 `# === <分组名> ===` 形式的注释行切分，得到每段下的 handles。
2. 把用户意图映射到上表的"分组"。**模糊时优先问用户**："你是想看 stock 还是 AI 那批，还是全部？"，不要瞎猜。
3. 把选中分组下的 handle 列表传给 `fetch_user_v2.sh`：

   ```bash
   ./scripts/fetch_user_v2.sh dmjk001 ViewsOfChris kugo_A10 ...   # stock
   ./scripts/fetch_user_v2.sh karpathy 9hills jiayuan_jy ...      # AI
   ```

4. 拿到 JSON 后按下面「整理与输出格式」呈现。报告头注明本次覆盖的分组（"# 推特动态摘要 · stock 组 · 最近 24h"）。

> ⚠️ **不要做内容筛选**——只在"用户层"按 users.txt 分组筛选（哪些 handle 进入本次抓取），不在"post 层"再按主题过滤。一旦确定了分组，那批 handle 的所有 post 都呈现，不要去掉"看似不相关"的条目。这条规则与"内容整理约定"里的「不筛选主题」一致：用户已经在维护 users.txt 时做完了语义筛选。

## 目录结构

```
twitter-user-posts/
├── SKILL.md
├── users.txt                       # 监控的 X 用户名，按主题分组，一行一个，# 注释
├── .gitignore                      # 忽略 cache/
├── scripts/
│   ├── fetch_all_v2.sh             # 批量（推荐）：一次 autocli 调用拉全部用户
│   ├── fetch_user_v2.sh            # 单/多用户：临时调试 / 指定 handle / 按分组用
│   ├── _process_user.sh            # 内部 helper：窗口过滤+cache diff+下图+OCR+写 cache+输出
│   ├── enrich_media_ocr.py         # macOS Vision OCR：把图片文字写入 ocr_text / ocr_media
│   ├── fetch_user.sh               # v1 单用户（保留作对照参考，已不推荐）
│   └── fetch_all.sh                # v1 批量
└── cache/                          # gitignored
    └── <username>/
        ├── <post_id>.json          # post 完整 JSON（含 full_text/media_urls/OCR 字段）
        └── <post_id>/images/       # 该 post 的图片附件
```

## 用法

```bash
# 单/多用户（机器可读）：返回 JSON 数组，按时间倒序
./scripts/fetch_user_v2.sh dmjk001 > posts.json
./scripts/fetch_user_v2.sh karpathy 9hills > posts.json     # AI 分组示例

# 全员批量（人类可读报告，默认最近 24 小时 / list-limit 30）
./scripts/fetch_all_v2.sh
./scripts/fetch_all_v2.sh --hours 6
./scripts/fetch_all_v2.sh --hours 72 --list-limit 60
```

### `fetch_all_v2.sh` 选项

| 选项 | 默认 | 说明 |
|---|---|---|
| `--hours N` | `24` | 窗口小时数（**滚动**：以 `now` 为终点往前推 N 小时） |
| `--list-limit N` | `30` | 每个用户拉多少条候选 post；窗口大或推主活跃时调高 |
| `--inter-user-ms N` | `1500` | adapter 内部批量循环时用户之间的间隔毫秒（实际加 0-50% 抖动），节流防 429 |
| `--batch-size N` | `4` | 单次 autocli 调用最多多少 handle；超过会因 daemon 30s 超时切批 |
| `--refresh` | off | 把窗口内全部 id 当未命中重拉（覆盖现有 cache） |
| `--json` | off | 额外把每用户完整 JSON 以 NDJSON 输出到 fd 3 |

**批量复用 cookies**：fetch_all_v2.sh 一次 autocli 调用（`twitter user-posts --usernames "h1,h2,..."`）把全部用户拉完，整批共享**一次** navigate，cookies 只刷新一次。
**命中 429 立即整批退出**（`exit 1`），不要循环重跑——X 的限流窗口会因继续请求而延长。

> 想"只拉某个分组"时，**不要** 给 `fetch_all_v2.sh` 加分组参数（脚本不识别），而是用 `fetch_user_v2.sh handle1 handle2 ...` 显式列出该分组下的 handle。

### `fetch_user_v2.sh` 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `TWITTER_POSTS_HOURS` | `24` | 窗口小时数（滚动） |
| `TWITTER_POSTS_LIST_LIMIT` | `30` | 单次 GQL list 拉多少条 |
| `TWITTER_POSTS_REFRESH` | `0` | =1 时全部重拉 |
| `TWITTER_POSTS_INTER_USER_MS` | `1500` | 批量内 handle 间间隔毫秒 |
| `TWITTER_POSTS_OCR` | `1` | 默认开启图片 OCR；除非调试，不能关。带图片 post 输出前必须有 OCR 字段或失败状态 |
| `TWITTER_POSTS_OCR_REFRESH` | `0` | =1 时重跑已有缓存的 OCR（适合修复旧缓存/算法调整后重刷） |

输出格式（stdout）：JSON 数组（按 created_at 倒序，跨多 handle 合并）。如果用 `fetch_all_v2.sh`，输出的是 Markdown 风格中文文本报告，按 `users.txt` 中的原始顺序排列每个用户区段：

```
### <username> (@<handle>)  ·  <created_at>
<内容>

  <post URL>
  📰 article: <可选，X Article 标题>
  🖼  media: <本地缓存图片路径，逗号分隔>
  📝 ocr: <可选，图片 OCR 文字摘要>
```

末尾是汇总行：`用户 X 个，时间窗口内 post 共 Y 条`。

> ⚠️ 上面是**脚本原始输出**，不是给用户看的最终格式。模型必须按下面的「整理与输出格式」重组后才能呈现给用户；尤其不能把本地图片路径当成最终内容发给用户。

---

## 整理与输出格式（**必做**）

调用 `fetch_all_v2.sh` / `fetch_user_v2.sh` 拿到原始数据后，**不要**直接把脚本输出甩给用户。
模型负责对原始 JSON / 报告做一次内容整理，然后按下面的格式呈现。

### 最低字段要求

每一条 post 的呈现至少包含 **3** 个字段：

1. **用户名**（推荐 `<昵称> (@<handle>)` 格式；`@` 后的 handle 用 `users.txt` 第一列；昵称用第二列展示名，没有就退化为 handle）
2. **时间**（本地 UTC+8，统一 `MM-DD HH:MM`，不论是否跨日都带日期；原始时间带 `Z` 时必须先按 UTC 解析再 `+8h`，不能直接原样展示）
3. **内容**（正文；超过 200 字时摘要为一句话 + 「全文见 🔗」）

### 推荐格式 A：按时间倒序总览（用户少、信息密度高时）

```
# 推特动态摘要 · stock 组 · 最近 24h
生成时间: 2026-05-05 12:34   覆盖用户: 13   总 post: 60

## 05-04 21:39  每日快讯 (@dmjk001)
彭博：OpenAI 已为新合资企业筹集超 40 亿美元，专注帮企业采用其 AI 软件。
https://x.com/dmjk001/status/2051295736067932551

## 05-04 21:38  每日快讯 (@dmjk001)
路透：欧盟委员会建议成员国将华为/中兴设备排除出本地电信运营商基础设施。
https://x.com/dmjk001/status/2051295426033443148

...
```

### 推荐格式 B：按用户分组（用户多、单用户 post 少时更清晰）

```
# 推特动态摘要 · AI 组 · 最近 24h

## Andrej Karpathy (@karpathy)  共 3 条
- 05-04 13:20 — ...

## 9hills (@9hills)  共 5 条
- 05-04 11:11 — 🖼 ...
- 05-04 09:11 — 📰 ...
```

格式 A 适合"逐条精读"，格式 B 适合"快速扫描"。默认用 B，用户明确说"详细列出"时切 A。
两种格式都遵循下面的「不同类型 post 的呈现规则」标注 marker（🖼 / 📰 / 🔁 / 🔗）和正文。
**所有时间统一 `MM-DD HH:MM`**（UTC+8），不论是否跨日。

### 内容整理约定

- **不筛选主题**：脚本抓到的所有 post **全部展示**，不要按"股票/AI/算力/通信"之类主题做内容筛选。模型只负责整理格式，不负责选题——用户已通过「Users 选择规则」做过博主层的筛选。
- **报告头注明分组**：本次覆盖的分组（"stock 组" / "AI 组" / "全部"）写在标题行，让用户一眼知道范围。
- **用户标注**：凡是输出里的 `@...`，都用 `users.txt` 第一列 `handle`（X URL 的 screen_name）；展示昵称用第二列 `username`，没有第二列时退化为 handle。
- **时间**：原始 `created_at` 通常是 UTC（例如 `2026-05-09T14:09:06.000Z`），**必须按 UTC 解析后转换为本地 UTC+8 展示**；禁止直接去掉 `Z` 当成本地时间展示。统一用 `MM-DD HH:MM` 格式，**不论是否跨日都带日期**。排序按原始绝对时间倒序排序，展示时再显示 UTC+8 时间。
- **正文**：保留原文优先；超长（>200 字）时摘成一句话主旨，末尾附原帖链接让用户跳转看全文。英文推主的内容**保留英文原文**，不要翻译；中文推主保留中文。
- **去重 / 合并**：多位推主转同一新闻 → 合并成一组，列出"几位都提到了"。
- **媒体 / 图片 OCR（强制）**：所有带图片/媒体的 post，在发送给用户前必须先读取 `ocr_text` / `ocr_media`，把图片里的文字内容整理进正文；**不能只贴 `🖼`、图片路径或一句“见图”**。脚本默认已用 `scripts/enrich_media_ocr.py` 写入 OCR 字段；如果字段缺失，先用 `TWITTER_POSTS_OCR_REFRESH=1 ./scripts/fetch_user_v2.sh <handle>` 或直接 `python3 scripts/enrich_media_ocr.py --cache-root cache --pretty < cache/<handle>/<id>.json` 补齐。
- **图片展示**：Slack 中不要输出本地 `local_media_paths`（用户打不开）；可以在必要时说明“原图见原帖”。如果用户明确要文件/图片，再用 Slack skill 上传附件。
- **OCR 失败兜底**：如果 `ocr_status` 是 `empty/failed/unavailable/no_image_media` 或某张图没有 `text`，条目里要明确写“图片 OCR 未识别出有效文字，建议查看原帖/原图”，不能编造图中内容。
- **链接**：每条都附原帖 url（直接放裸 URL 或 `[原帖](url)`，**不要**前缀 🔗 emoji，已在条目类型 marker 用过会重复）。
- **不展示** `metrics`（views / likes / reposts）：信号判断仅用于排序「今日重点」，正文条目里**不输出**这些数字。

### 不同类型 post 的呈现规则

判断顺序从 1→5，命中即停。

#### 1. 含媒体 post（图片 / 视频）

**判断（这是默认情况，最常见）**：`media_urls.length > 0` **或** `local_media_paths.length > 0` —— 只要带媒体就归这类，不管 `content` 长短。

为什么这么宽：很多推主（尤其股票/财经、AI 资讯）大量发"短评 + 公告/新闻/图表/截图"——主信息在图里，短文字只是引子。把这种条目按"纯文本"处理会丢核心信息。

呈现（`🖼` 图片 / `🎬` 视频；时间用 `MM-DD HH:MM`）：
```
- 05-04 10:15  🖼  FCC 拟限制中国实验室认证、推进限制中资电信相关设施
  对光模块、通信设备、运营商互联等方向有扰动，和上面两条属于同一政策线。
  ![](cache/dmjk001/2051123627303780490/images/img_001.jpg)
  https://x.com/dmjk001/status/2051123627303780490
```

要点：
- marker 用 `🖼` / `🎬`，**不要**用 `🔗`（🔗 是外链卡片专用，见 #4）。
- 同一行的标题可以来自 `content`（推主原文）；如果只发了 `t.co` 短链没文字，**必须使用 `ocr_text` / `ocr_media[].text` 里的图中文字**，用图里的关键文字 / 标题做一句话标题。
- 正文区先给推主短评（如有），再给 `图片文字/OCR` 摘要；图中 OCR 的标题、公告、数字、表格关键项必须转换成文字发出。
- Slack 输出里不要贴本地 `![](path)`（本地路径用户不可访问）；除非用户明确要附件，否则只附原帖 URL。
- 末尾给原帖 URL，裸 URL，不要再加 emoji。

#### 2. X Article（长文）post

判断：`has_article: true` 且 `article_title` 非空；或 `content` ≥ 500 字且含 markdown 标题；或正文只有/主要是 `https://x.com/i/article/...` 这类 X Article 链接。

呈现：
```
- 05-04 17:11  📰 高盛：寒武纪目标价上调至 2406 元
  AI 扩张带动国产芯片增长，2026 Q1 营收环比 +53%，买入评级上调目标价至 2406 元。
  https://x.com/dmjk001/status/2051228100357194180
```

要点：
- 标 `📰` + article 标题作为条目标题（不要用正文起首截断）。
- 一句话摘要必须**覆盖全文要点**（数字、结论、评级），别简单截断前 200 字。Article 是长文/深度分析，截断必丢关键信息。
- **禁止**输出“分享一篇 X Article 链接 / 正文只有链接 / 纯链接分享”这类占位描述。遇到 Article 必须先获取正文并总结，用总结内容替代原链接描述。
- 获取全文顺序：先看缓存里的 `article_title` / `article_text` / `article_content` / `content` 是否已有完整正文；如果只有 `https://x.com/i/article/...` 链接或摘要不足，单独调用 `autocli twitter article --url <article-or-post-url> --format json` 获取全文后再总结。
- 若 X Article 抓取失败，条目里必须明确写“Article 全文抓取失败：<原因>”，并保留原帖 URL；不要伪装成已总结。
- 看全文：`jq -r .content cache/<handle>/<id>.json` 或开原帖。

#### 3. 转推 / 引用推（Quote Tweet）

判断：`content` 起首是 `RT @xxx:`，或正文里嵌入对其它推的引用块。

呈现：
```
- 05-04 22:00  🔁 转推 @somebody
  美光 $MU 涨至 $586.8 (+8.22%)（原文）
  https://x.com/...
```

#### 4. 外链卡片（纯分享外站 URL）

判断：`content` 主体是一个或多个 `t.co` 短链，**且** `media_urls.length == 0`（**注意**：有 media 走 #1，不要在这里）。

呈现：
```
- 05-04 02:16  🔗 转外链 (theinformation.com)
  …（解析 t.co 后能拿到的标题/上下文；拿不到就标"[纯外链分享]"，不瞎编）
  https://x.com/dmjk001/status/2051123671687999561
```

#### 5. 纯文本

判断：`content` 非空、长度 < 500 字、`media_urls.length == 0`。

呈现：无类型 marker，标题就是 `content` 一句话或全文：
```
- 05-04 02:22  港股算力硬件大涨，节日期间发酵的 FCC 新规对算力硬件不是利空。
  https://x.com/dmjk001/status/2051125320410157504
```

### 「今日重点」小节（窗口内 post >20 时推荐）

末尾追加一个总结小节，挑出 3-5 条信号最强的，用一句话点评：

```
## 🔥 今日重点

- **OpenAI 40 亿美元新合资**（@dmjk001 05-04 21:39）— 三位推主都提到，AI 商业化加速
- **欧盟拟禁华为/中兴电信设备**（@dmjk001 05-04 21:38）— 中概通信板块情绪可能承压
- **寒武纪目标价上调至 2406**（@dmjk001 05-04 17:11）— 国产算力主线持续催化
```

挑选标准（**仅供模型内部排序，不在输出里展示数字**）：高 views / likes / reposts、多推主同时提及、涉及具体公司 / 政策 / 数据 / 技术发布。

### 失败用户的处理

新批量架构下，整批共享一次 autocli 调用：

- **整批命中 X 429**：脚本 `exit 1`，不输出报告。模型应明确告诉用户"X 限流"，建议等 5-15 分钟再试，不要循环重跑。
- **某个用户 adapter 内部失败**（UserByScreenName 拿不到 rest_id 等）：批量结果里这个 handle 缺失，报告里标 ⚠️ "拉取失败"。让用户检查 `users.txt` 拼写或 X 账号是否还在。
- **窗口内无新动态**：`(近 N 小时无新动态)` —— 不算失败。

---

## 缓存策略：list-then-diff（v2）

每次 fetch 都基于一次完整 GQL list、按 id 与本地 cache 文件**严格 diff**。命中（`cache/<id>.json` 存在）= 跳过 fetch；未命中 = 必须 fetch 并写入。这保证窗口内每一条 post 最终都会被补齐——即便缓存中间漏了几条、即便上次跑被中断。

`fetch_user_v2.sh` 流程：

1. **GQL list（1 次）**：`autocli twitter user-posts --limit LIST_LIMIT --format json`。
   - adapter 走 GQL 路径（`UserByScreenName` → `UserTweets`，cursor 分页），不依赖 DOM 滚动。
   - 不开 `--include-detail`：list 模式已返回 `full_text` + `media_urls` + `metrics`，绝大多数情况够用。
2. **窗口过滤**：保留 `created_at >= now - HOURS 小时` 的 post（滚动窗口）。
3. **diff cache**：对窗口内每个 id 看 `cache/<handle>/<id>.json` 是否存在。`TWITTER_POSTS_REFRESH=1` 时全部当未命中。
4. **下图 + OCR + 落 cache**：把未命中的 post pipe 给 `download-media.py` 下载图片，再由 `scripts/enrich_media_ocr.py` 用 macOS Vision OCR 提取图中文字，写入 `ocr_text` / `ocr_media` / `ocr_status` 后保存 cache JSON。
5. **历史缓存补 OCR**：输出前会扫描窗口内旧缓存；凡是有 `media_urls/local_media_paths` 但缺 `ocr_checked_at` 的 post，会先补 OCR 再输出。`TWITTER_POSTS_OCR_REFRESH=1` 可强制重跑 OCR。
6. **输出**：从 cache 扫窗口内全部 post，按 `created_at` 倒序输出；开启 OCR 时，带媒体但仍无 OCR 状态的条目不会进入最终输出，避免把未转换的图片帖发给用户。

失败处理：

- **GQL 调用失败 / 返回空**（限流、登录失效、queryId 失效等）→ `fetch_user_v2.sh` 直接 `exit 1`，**不会**回退到旧缓存或 DOM 滚动。早期版本会悄悄输出旧缓存，已移除：在 X 限流（429）场景下继续抓只会加剧限流，且调用方容易误以为同步成功。
- **adapter 层**：[~/.autocli/adapters/twitter/user-posts.yaml](~/.autocli/adapters/twitter/user-posts.yaml) 也已去掉 DOM 滚动兜底，GQL 失败一律抛错。
- list 全部都在窗口内（`list_in_window.length == list.length` 且最早一条仍 ≥ SINCE）→ 打 warn 提示 `LIST_LIMIT` 不够，建议加倍重试。

副作用：N 条全是缓存命中时，**完全不会触发** 下载和写盘，只跑了一次廉价的 GQL list 调用。

遇到 429 / 抓空：等待几分钟到一小时再试；不要无脑重跑脚本。

### 为什么不再用 v1 的"探针 + 翻倍 + 命中即返回"

v1 用"窗口最新一条 id 是否在缓存"判断命中。如果缓存中间漏了几条（前一次跑被中断、人工删了 cache 文件等），最新一条命中就直接返回，**漏的永远补不上**。
v2 改成逐 id diff，每次拉完整 list 与 cache 对账，缺什么补什么。

## 限流与 autocli 锁

`autocli` 的 `twitter user-posts` 是 browser strategy（共用一个 Chrome 登录会话），多进程同时跑会互相抢标签页。

- `fetch_user_v2.sh` / `fetch_all_v2.sh` 内部用 `mkdir /tmp/twitter-user-posts-autocli.lock` 做跨进程互斥锁。
- 新批量架构下，`fetch_all_v2.sh` 全程**只发 1 次 autocli 调用**（`--usernames` 批量），所以本来就不存在并发抢锁问题；只剩节流。
- 脚本被 SIGKILL 中途打断、锁没释放，手动 `rmdir /tmp/twitter-user-posts-autocli.lock` 即可。

### GQL 节流与防 429

X 的 web GQL 端点有短窗口限频。其中 `UserByScreenName` 限流最严（被定性为"用户搜索"行为），`UserTweets` 较宽松。三层防护：

1. **rest_id 缓存**：每个 handle 的 rest_id 落地到 `cache/.user_ids.json`，下次调用 adapter 传 `--user-ids "h=id,..."` **跳过 UserByScreenName**。N 个用户的 GQL 调用从 2N 降到 N，且绕开最容易触发限流的端点。
2. **adapter 翻页间隔**：UserTweets cursor 翻页之间 sleep `--rate-limit-ms`（默认 1200ms）+ 0-30% 随机抖动。
3. **adapter 用户间间隔**：批量模式下用户之间 sleep `--inter-user-ms`（默认 1500ms）+ 0-50% 随机抖动。

抖动是**故意机器化模式 → 模拟自然请求**：固定间距是 scraper 签名，加抖动后看起来更像浏览。

仍频繁 429：等 5-15 分钟，再用 `--inter-user-ms 3000` 重试；**不要循环重跑**——X 的限流窗口会因继续请求而持续延长。

### 批量复用（cookies / navigate 只一次）

autocli pipeline 每次都跑 `navigate https://x.com/home` (settle 3s) 来刷 ct0 + 落 same-origin。批量抓 N 个用户时如果用 N 次单用户调用，就是 N 次 navigate × 3s 浪费。

解决方案：**adapter 接受 `--usernames` 批量参数**（comma-separated），在一次 autocli pipeline 内部循环遍历所有 handle 跑 GQL。这样：
- 1 次 navigate（cookies 刷一次）
- N 次 GQL（每用户 1-2 次：UserByScreenName + UserTweets）
- adapter 内部用户间间隔 `--inter-user-ms`（默认 1500ms）

`fetch_all_v2.sh` 内部就是一次：
```bash
autocli twitter user-posts --usernames "h1,h2,h3,..." --limit 30 --inter-user-ms 1500 --format json
```

返回的 JSON 数组里每条 post 带 `requested_username` 字段，脚本按此切分，再喂给 `_process_user.sh` 做 cache diff / 下图 / 写 cache。

**`fetch_user_v2.sh` 也走同一 adapter**：传一个 handle 时用 `--username`，多个时用 `--usernames`。设计上服务"我就想看一两个用户 / 一个分组"的场景；全员监控走 `fetch_all_v2.sh`。

**架构小结**：
```
fetch_all_v2.sh ──► autocli twitter user-posts --usernames "..." ──► _process_user.sh × N (per-user cache)
                       (1 navigate, N GQL)

fetch_user_v2.sh ──► autocli twitter user-posts --usernames "..." ──► _process_user.sh × n
                       (1 navigate, n GQL)   ← n 可以是 1 也可以是某个分组的全部
```

## 维护监控列表

直接编辑 `users.txt`：

```
# === stock ===
# handle,username
# handle   = X URL 里的 screen_name (调 autocli 用)，例如 dmjk001
# username = X profile 上展示的真实昵称 (报告里展示)，例如 每日快讯
dmjk001,每日快讯
ViewsOfChris,Chris Lee
...

# === AI ===
karpathy,Andrej Karpathy
9hills
...
```

约定：
- **分组用 `# === <分组名> ===` 作为段头注释**。模型按段头切分用户，做「Users 选择规则」时识别这一行。
- 报告里的展示顺序就是 `users.txt` 中的行序。`#` 起头的其它注释行对脚本透明（脚本只解析非注释行）。
- 兼容纯 `handle` 行（此时 username 复用 handle）。
- 要批量补全 username：`autocli twitter profile <handle> --format json | jq '.[0].name'`。
- 已下线/换名的用户直接删掉那一行；老缓存可保留作为历史，也可手动 `rm -rf cache/<handle>` 清理。
- 加新分组：直接加一段新的 `# === <name> ===` 注释 + 几个 handle 即可，「Users 选择规则」表里也补一行映射。

## 前置依赖

- `autocli` 已安装并完成 X 登录（Chrome 里登录 x.com 即可，autocli 通过浏览器扩展共享 cookies）。
- `~/.autocli/adapters/twitter/user-posts.yaml`：GQL 主路径 + DOM 兜底版本（仓库里已经在用）。
- `~/.autocli/adapters/twitter/download-media.py` 存在。
- 本机有 `jq` 与 `python3`。
- 图片 OCR 依赖 macOS Vision.framework + PyObjC（本机已可用 `Foundation/AppKit/objc` 动态加载 Vision）。不要改成依赖 tesseract/easyocr/paddleocr，当前环境未安装这些组件。

## 已知边界

- **置顶 post**：v2 走 GQL UserTweets，adapter 主动跳过 `TimelinePinEntry`，置顶不会乱序也不会误进 cache。
- **回复 (replies)**：`UserTweets` operation 不返回 replies，只返回 Posts 标签页内容。要含 reply 需要换 `UserTweetsAndReplies`（adapter 暂未实现）。
- **长帖 article**：list 模式可能只能拿到摘要或只拿到 `https://x.com/i/article/...` 链接。最终报告里不能写“分享一篇 X Article 链接 / 正文只有链接”；必须单独调 `autocli twitter article --url ...` 抓取全文并总结。抓取失败时明确标注失败原因，不能用占位描述替代总结。
- **媒体下载 / OCR**：受 X/CDN 限制，偶尔某条 post 的图片拿不到本地文件，或 Vision OCR 对低清图、表格图、压缩截图识别很差。JSON 会记录 `ocr_status` 和 `ocr_media[].error/text`；最终发送时必须把可识别文字转成正文，识别失败则明确写“OCR 未识别出有效文字，建议查看原图/原帖”。要重试下载/OCR，可删 `cache/<handle>/<id>.json` 或设置 `TWITTER_POSTS_OCR_REFRESH=1`。
- **限流（429）**：`fetch_user_v2.sh` 直接 `exit 1`，`fetch_all_v2.sh` 把该用户标记为 `fail` 在报告头打 ⚠️。多次失败时等待并检查 Chrome 是否还登录着 x.com，**不要循环重跑**——会被 X 持续延长限流窗口。
- **`LIST_LIMIT` 不够**：当某推主在窗口期内 post 数量超过 `LIST_LIMIT`，list 拉不到 SINCE 之前的边界，会打 warn 提示加大。`--list-limit` 默认 30 适合大多数推主 24h 窗口；`--hours 168`（7 天）时建议 `--list-limit 100+`。

## v1 旧脚本（兜底参考）

`fetch_user.sh` / `fetch_all.sh` 是基于"窗口最新一条命中即返回 + 探针翻倍"的旧策略，留作 v2 出问题时的对照。除非 v2 有 bug，否则不应再用。差异已在「为什么不再用 v1」里说明。
