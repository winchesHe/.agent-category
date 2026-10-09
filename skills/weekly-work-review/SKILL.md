---
name: weekly-work-review
description: >-
  生成可归档的个人全量周复盘，覆盖 MoeGo 工作、写作与创作、知识系统和有明确产物的个人项目，
  证据来源包括 AI session、Slack 协作记录、飞书/Lark 会议、本地项目和外部系统。
  归档到 Obsidian vault 的 工作/周报/YYYY/MM/日期范围/，自动判断新建或同周增量更新。
  触发词：周复盘、工作复盘、本周做了什么、周报、Sprint Review、same-week update、补会议。
  组合 memory-manager 多 agent session、Slack skill 和 lark-cli 生成可审计的周复盘包。
---

# 周工作复盘

生成一个可在同一周内迭代更新、最终归档到用户 digital-garden 的个人全量周复盘包。

## 前置配置

首次使用前读取 `.env.example` 和 `config/profile.example.json`：

- `WEEKLY_REVIEW_VAULT_ROOT` 与 `WEEKLY_REVIEW_SCRATCH_ROOT` 必须配置，且 scratch 必须位于 Vault 外。
- `WEEKLY_REVIEW_ARCHIVE_RELATIVE_DIR` 默认是 `工作/周报`。当前 Vault 使用每周单 Markdown 文件；迁移为 flat week package 前不得直接执行真实归档，避免与既有周报产生双写。
- Slack 默认使用当前 skills 仓库的 `slack/`；Lark 使用已安装的 `lark-cli`。
- `WEEKLY_REVIEW_SESSION_ARCHAEOLOGY_DIR` 是可选配置。未安装时将 sessions source 标记为 `tool_unavailable`，不得虚构 session 覆盖。
- 配置文件只保存路径和行为偏好；凭证继续由 Slack、Lark、GitHub、Jira 各自的 skill 或 CLI 管理。

采集前先跑一次环境预检，避免每个来源各自重复探测：

```bash
node <skill-dir>/scripts/check-environment.mjs --week <YYYY-MM-DD>
```

它报告 vault / scratch 合法性、周报与会议目录、`lark-cli` 登录状态、Slack skill、session 索引覆盖和 GitHub CLI，并列出降级建议。`blocking` 非空时先修配置再采集。

脚本清单：

| 脚本 | 用途 | 写入 |
|---|---|---|
| `resolve-week.mjs` | 计算周目录与主报告路径 | 只读 |
| `check-environment.mjs` | 环境预检与降级建议 | 只读 |
| `collect-sessions.mjs` | 多 agent session 证据 | 只写 scratch |
| `collect-github.mjs` | GitHub commits / PR / review 证据 | 只写 scratch |
| `collect-jira.mjs` | Jira issue / worklog 证据 | 只写 scratch |
| `collect-slack.mjs` | Slack 出站 / 被提及 / 入站 DM | 只写 scratch |
| `validate-package.mjs` | 质量门禁 + 生成 receipt | 写 `validation-result.json` |
| `export-meeting-pdfs.mjs` | 导出会议纪要 PDF | `--dry-run` 零写入 |
| `repair-meeting-docs.mjs` | 修复会议文档缺口 | `--dry-run` 零写入 |
| `migrate-legacy-weeklies.mjs` | 旧式平铺周报迁移 | 默认预览，`--apply` 才写 |
| `tests/run-tests.mjs` | 回归测试 | 只用临时目录 |

## 固定默认

这些默认是用户已明确确认的长期规则，后续运行不得再反复询问：

- **目标路径有且仅有 Vault 归档**：始终发布到 `<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/`。
- **目录结构永久稳定**：按现有 2026/06 的 `<日期范围>` 到 `week-4` 结构推导；下个月、明年仍使用 `<YYYY>/<MM>/<日期范围>/`，`<日期范围>` 由本地周一在当月的序数周计算。
- **证据范围自动化**：如果目标周目录不存在，采集该周周一到今天的完整证据；如果目标周目录已存在，采集同周增量并更新既有包；如果用户输入中明确说明具体周或日期范围，则按用户指定范围。
- **个人复盘是主产品**：正文必须覆盖本周所有有证据的实质产出，包括 MoeGo 工作、写作/创作、知识系统和有明确产物的个人项目。`Sprint Review` 只是正文中的选择性摘录，不能反向决定哪些产出进入个人复盘。
- **主线只控制叙事权重，不控制收录**：可以选择 1–3 条重点主线，但未被选为主线的实质产出仍必须进入 `本周产出总账`，并保留状态和证据锚点。
- **会议模式固定为会议 + 转写**：永远纳入飞书/Lark 会议，并在权限允许时归档完整 `会议转写.md`。
- **原始证据暂存必须在 vault 外**：禁止在 digital-garden 内创建 `work/weekly-work-review`、`Work/weekly-work-review`、`outputs/` 等临时证据目录。默认使用 vault 外 scratch 目录，例如 `<scratch-root>/<YYYY>/<MM>/<日期范围>/`。

## When to Use

- 用户要生成或更新个人全量周复盘、MoeGo 周工作复盘、周报或 Sprint Review 摘录
- 用户要把本周 AI sessions、Slack、飞书会议/妙记、文档、代码/ticket 活动合并成可归档证据包
- 用户要把写作、公众号、内容资产、知识库建设或其他有明确产物的个人项目纳入本周产出
- 用户要补充本周会议、shared clips、飞书妙记或同周增量更新
- 用户要审计过去某几周复盘质量，并反向优化本 skill 的 contract/evals/gates

## When NOT to Use

- 写单日普通日记或没有周度产出盘点需求的个人反思；用 `diary-writer` 或 vault 普通写作流程
- 将外部文章、长期判断或知识模式编译进 `Research/wiki/`；用 `llm-wiki`
- 只整理单场会议纪要或从会议纪要抽任务；用飞书会议/纪要相关 skill
- 只做 session archaeology、Slack 搜索、飞书文档读取，不生成周复盘归档包
- 非 MoeGo 的项目周报，除非用户明确要求复用本包结构

## 产出结构

写最终产物前必须先读：

- `references/output-contract.md` — 目录结构、文风、目标路径、隐私边界和质量门禁
- `references/evidence-collection.md` — AI sessions、Slack、飞书、shared clips、文档和代码/ticket 采集细则
- `references/evidence-manifest-schema.md` — manifest 字段语义与写作规则
- `references/evidence-manifest.schema.json` — manifest 正式 JSON Schema，字段必填性以它为准

**归档路径不允许心算。** 一律用 resolver 计算：

```bash
node <skill-dir>/scripts/resolve-week.mjs <YYYY-MM-DD>
```

它输出 `week_start`、`week_end`、`iso_week`、`archive_year`、`archive_month`、`week_label`、`report_file_name` 和完整路径。规则：**年月取周一，目录名用日期范围，ISO 周只作元数据。**

主归档包：

```text
<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/
  <日期范围> 周复盘.md          # 主报告，文件名含日期范围
  小时证据附录.md
  迭代记录.md
  evidence-manifest.json
  evidence-manifest.md
  validation-result.json        # validator 生成，绑定 manifest hash
  meetings/
    会议索引.md                  # 只索引，不复制会议正文
```

例：

```text
<vault>/工作/周报/2026/08/2026-08-03 至 08-09/2026-08-03 至 08-09 周复盘.md
```

跨月周归入周一所属月份；跨年周目录名用完整日期，如 `2026-12-28 至 2027-01-03`。

**会议正文的权威位置在会议目录，不在周报包内。** 与周报一致按年月分类，年月取会议日期：

```text
<vault>/工作/会议/<YYYY>/<MM>/<YYYY-MM-DD 标题>.md
```

只有一篇纪要时用单文件，文件名即 `<YYYY-MM-DD 标题>`。这样 wikilink 直接是 `[[2026-08-06 Quick Win 830 需求确认]]`，在 quick switcher 和图谱里可区分。

会议附带转写、PDF 或图片时，升级为同名目录，并保留同名主文件以免 wikilink 失效：

```text
<vault>/工作/会议/<YYYY>/<MM>/<YYYY-MM-DD 标题>/
  <YYYY-MM-DD 标题>.md      # 主文件名与目录同名，wikilink 不变
  会议转写.md
  飞书原始纪要.pdf
  assets/
```

不要把主文件统一命名为 `会议纪要.md`：Obsidian 按 basename 解析 wikilink，同名文件会互相冲突，quick switcher 里也无法区分。

周报包的 `meetings/会议索引.md` 只保存日期、标题、`source_type`、`discovery_method`、`minute_token/meeting_id`、指向会议目录的 wikilink 和一句相关性说明。同一场会议不得在多个周报包内重复存储完整转写和 PDF。

禁止把此材料写入 `Research/wiki/`。这是工作记录，不是长期知识编译。

## 工作流

### 步骤 1：自动确定目标与范围

不要对固定默认做 preflight。只有以下情况才停下来问用户：

- 用户指定的日期范围跨越多个周一，需要决定按周拆分还是创建自定义范围归档。
- 同一周存在多个候选归档目录，无法判断哪个是权威目录。
- 用户要求的目标与固定默认冲突，例如 workspace-only、非 Vault 目录、session-only 或不包含转写。
- 外部副作用、危险操作或批量写操作触发全局 SAFETY 确认。

自动确定规则：

- 未指定日期时，使用机器本地日期所在周。
- 指定具体周或日期范围时，按用户输入计算 `week_start` 和目标目录。
- 目标目录不存在：新建该周归档，证据范围为 `week_start` 到当前运行时刻；若目标周在过去，则范围为完整周。
- 目标目录已存在：同周增量更新，证据范围从该包最近一次 `迭代记录.md` / `evidence-manifest.json` 的覆盖截止之后开始；如果无法可靠读取截止时间，则扫描整周并在 manifest 中说明去重策略。
- 当天为部分日时，在 `证据口径` 和 manifest 中标注 partial day。

如果确实需要问问题，Claude Code 环境用 `AskUserQuestion`，Codex 环境用 `functions.request_user_input`；工具不可用时再用聊天问题，但必须只问阻塞项。

### 步骤 2：确定范围

提取：

- 具体日期范围（精确日期）
- 时区（默认机器时区）
- 当天是否为部分日
- 主产品固定为个人知识库中的全量复盘；Sprint Review 只决定哪些条目进入摘录，不改变个人复盘的收录范围
- 归档模式：新建包 还是 同周更新
- 目标路径：自动推导的 digital-garden Vault 归档路径
- 会议模式：固定为会议 + 转写
- 是否归档原始转写正文：固定为归档；不可用时写明原因
- 原始会议转写是否可用；可用时优先从会议纪要底部 `文字记录` docx 链接通过 `lark-cli docs +fetch --doc <docx> --doc-format markdown` 获取，并将完整 `会议转写.md` 发布到 digital-garden

默认范围按步骤 1 的自动规则执行。使用机器日期时间，不做心算。

### 步骤 3：确定周目录

周复盘归档使用稳定的 week key，禁止用运行日期或复盘结束日期作为归档标识。

规则：

- `week_key` = 复盘周的周一本地日期
- 复盘周 = 周一到周日（机器时区）
- `week_start = week_key`
- `week_end = week_start + 6 天`
- digital-garden 目录：`<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/`，由 `week_start` 推导；`<日期范围>/` 本身就是最终包目录，禁止再嵌套 `<YYYY-Www__...>` 子目录
- 同一周的周三、周五上午、周五下午、周日运行必须更新同一个目录
- 如果显式日期范围跨越多个周一，停下来问是否按周拆分还是创建自定义范围归档

已有目录处理：

1. 优先查找约定的 digital-garden 归档目录
2. 若存在，原地更新
3. 若不存在，在同月文件夹中搜索同周遗留命名（如 `<YYYYMMDD-周复盘>` 或日期落入同周的非标准目录）
4. 在 digital-garden 中，不经用户确认不得重命名非标准目录；原地更新并报告命名偏差
5. 若存在多个同周目录，停下来问哪个为准

### 步骤 4：执行前 Baseline Checklist

在正式采集证据前先做轻量 baseline，用来减少重复探索，不写成最终归档事实：

- 优先读取目标周上一周的 `evidence-manifest.md` / `evidence-manifest.json` 和 `迭代记录.md`。
- 从最近三次成功运行的 `迭代记录.md` 中读取 `Skill 运行复盘`；提取反复出现的遗漏、误判、工具缺口和用户纠正，作为本轮 rescan checklist。
- 如果上一周缺 manifest，只读 `迭代记录.md` 判断 legacy/gap，不继续纠缠一堆旧文件。
- 继续向前找最近一次成功归档。成功归档优先以该包自己的 `evidence-manifest.md` 中 `Validation Readback` 为准；没有 readback 时，可以只读复跑 `scripts/validate-package.mjs <week_dir>` 判断。
- baseline 只继承 source matrix、常见 gap、rescan checklist 和工具注意事项；禁止复用正文主线、判断或内容模板。
- 找不到可用 baseline 时，在 `迭代记录.md` 记录 `baseline unavailable` 和原因，然后允许完整扫描。

### 步骤 5：采集 AI Session 证据

使用本 skill 自带的采集器，后端是 `memory-manager` CLI，覆盖 claude / codex / opencode / pi / copilot / cursor。它只提供证据，不写复盘正文。

**必须先扫描再采集**。采集前先备份 `~/.memory-manager/memory.db`（含 `-wal`/`-shm`）到 scratch 目录，因为扫描会写这个数据库；备份完成后直接跑采集器，它默认先刷新索引：

```bash
node <skill-dir>/scripts/collect-sessions.mjs --week <YYYY-MM-DD>
```

先扫描不是可选优化。只查旧索引会漏掉「更早创建、但本周有更新」的 session，而这类 session 恰恰是延续多周的方案设计与联调工作——W32 实测因此漏掉过一整块方案设计。

默认行为：

- **先扫描再查询**。默认执行 `memory-manager scan --all` 刷新索引，再按周筛选。
- 默认输出到 `<scratch-dir>/<YYYY>/<MM>/<日期范围>/session-evidence/session-index.json`。
- 扫描只写 `~/.memory-manager` 数据库，**不写 vault**；试图写入 vault 时以 `SESSION-002` 失败。
- CLI 或工作区缺失时以 `status=tool_unavailable` 正常退出，调用方据此写 manifest。

输出的 `scan` 字段是采集覆盖度的凭据，必须回读并写进 manifest：`requested` / `skipped` / `ran` / `ok`，失败时还有 `error`。**`scan.ok` 不为 true 时不得声称覆盖完整。**

只有用户明确要求跳过扫描（例如同周内反复迭代、刚扫过、或不希望写数据库）时才加 `--no-scan`：

```bash
node <skill-dir>/scripts/collect-sessions.mjs --week <YYYY-MM-DD> --no-scan
```

**扫描失败或被跳过时的处理顺序**：`scan.ok === false` 或 `scan.skipped === true` 且 `latest_indexed_at` 早于 `week_end` 时，先向用户报告索引滞后并申请重扫，再写正文——不要先出一版带缺口的周报。用户拒绝重扫时按下面的口径约束写作：

- 滞后区间内的 session 分布标注为"证据未覆盖"，不得据此判断当天的投入水平。
- 禁止把低提交数 + 无 session 证据解释为"当天投入低"或"实际投入无法回读"。缺的是索引，不是投入。
- 依赖 session 分布的节奏分析（峰值日、空档期）在 `sessions.status = partial` 时必须显式标注不确定，或整段省略。

**归属口径**：按 `updated_at` 落在复盘周计入，**不要求当周新建**。更早创建、本周继续使用的 session 同样是本周工作证据。周边界与按日归属都按配置时区计算，不用 UTC——UTC 边界会把周一 00:00–08:00（东八区）的 session 判到上一周，实测因此漏掉过一整块方案设计工作。

**工具自产 session 必须剔除**。memory-manager 的规则提取会 spawn session，再被自己的索引收回（自我回灌）。collector 已按会话正文匹配工具自身 prompt 自动剔除：JSONL 源（claude / codex）直读文件，非 JSONL 源（opencode 存 SQLite、copilot 存 `workspace.yaml`）走 `memory-manager sessions show`，该命令内部有对应 reader。`raw_count` 与 `sessions` 都是剔除后的人工口径，剔除量记在 `tool_spawned_count` / `exclusion_note`。W31 实测 326 条周命中里 203 条属此类，不剔除会让工时虚高 2.6 倍，并把峰值日判错。写正文时用 `raw_count`，不要用 `index_hits_in_week`。

`undetermined_count` 是既非 JSONL、`sessions show` 也读不到正文的会话，按人工计入但必须在附录里说明。目前只有 copilot 会落进来——它源端只持久化 metadata，`sessions show` 会明确报 "只有 metadata，源端未持久化对话"。这是源端限制，不是采集缺陷；若该数持续增长或出现其他 agent，需先查清再下工作量结论。

**必须逐条过 session 标题**，不能只用 agent / project / day 聚合计数组织正文。纯方案设计、架构决策、技术调研类工作没有 commit 锚点，只存在于 session 里；只看提交与聚合数会把这类产出整块漏掉。至少覆盖 top 项目下所有 agent 的 session 标题，发现无 commit 的实质产出时单独成条，`source` 写 `sessions`。

证据要求：

- 在 `小时证据附录.md` 或 manifest 中报告：本周 session 总数、各 agent 拆分、覆盖天数、`latest_indexed_at`、本轮 `scan` 结果（`ran`/`ok`/`skipped`）
- 按 `moego-work / writing-creation / knowledge-system / personal-project / review-meta` 分类；前四类只要形成实质产物都进入候选池
- `review-meta` 不计入生产产出，但可计入工时判断，并必须用于提炼本次 skill 的运行优化点
- session 候选写入 `candidate_items[]` 时带 `agent` 字段，便于回读来源
- 覆盖缺口必须写进 manifest；不得用"本周没有 AI 工作"掩盖未扫描
- 保持高风险操作可见：IAM、数据库变更、生产 API 调用、密钥、SSH/sudo、隐私数据、外部服务写入
- 原始 JSONL 不进 vault，只保留 `source_path` 引用；需要细读时用 `memory-manager sessions show <id>`

### 步骤 6：采集协作与外部系统证据

按 `references/evidence-collection.md` 执行。至少覆盖 AI sessions、Slack、Lark VC/calendar/minutes、shared clips、Lark Drive docs、本地 vault notes、个人创作与知识产物、GitHub/code activity、Jira/Linear/worklog。

**GitHub 活动必须用 `collect-github.mjs`，不要用本地 `git log` 作为主口径：**

```bash
node <skill-dir>/scripts/collect-github.mjs --week <YYYY-MM-DD>
```

本地 git 有三个致命缺口，实测都命中过：clone 会过期（某仓库最后 fetch 停在周中，之后的提交本地根本不存在）、可能压根没 clone、以及 PR 与 review 在本地完全不可见。W32 初版只扫了 2 个本地仓库，漏掉 6 个仓库、9 个 PR、11 个 review，并据此写出"业务侧主要是对齐而非交付"的反向结论。

采集器内部同时用 `search/commits` 和逐仓库 commits API 取并集，因为提交搜索不可靠地索引私有仓库（实测某私有仓库 74 条提交在 search 里 0 命中）；逐仓库探测还会覆盖 main / master / production，因为默认分支不一定是主干。

**PR 结局必须按 `merged_at` 判定，`state=closed` 不等于已合并。** `search/issues` 的 `state` 只有 `open` / `closed`，而 `closed` 同时包含"已合并"和"关掉没合"。实测 W32 有 2 个 PR 属后者，被误写成已交付：一个是我主动关闭重建精简版（scope 过大），另一个当天创建当天关闭且无后继 PR、Jira 单最后由他人关闭。采集器输出 `pr_created_by_outcome`（merged / closed_unmerged / open）三桶，写正文时用这个，`GITHUB-003` 回归测试锁住该区分。

关闭未合并的 PR 在产出总账里应记 `blocked` 或明确标注"关闭未合并"，不能算交付；有主动关闭原因（如 scope 收敛后重建）时要写清，否则读者无法判断是放弃还是替换。

`本周 PR 状态` 小节每行都要带一句话说明，**说明从 `gh pr view --json body` 的正文首段取，不要照抄标题或自己编**。PR 模板没填写时（body 只剩注释占位）明确标注"模板未填写，口径取自标题与 commit"，不要用标题硬凑成一句描述。规模（`+x/-y`、文件数）和 review 状态一并给出——它们是判断"卡在哪"的关键。

`github_activity` 停留在本地 git 口径时，validator 以 `COVERAGE-007` 失败——这个缺口曾经被如实记进 manifest 然后无人处理，现在不允许再通过。

**Jira 用 `collect-jira.mjs`，不要因为工时字段为空就整块跳过：**

```bash
node <skill-dir>/scripts/collect-jira.mjs --week <YYYY-MM-DD>
```

manifest 里 Jira 拆成两个 key，不要再合成一个：

- `jira_issues`：我创建的 + 我负责且有更新的 issue。**即使 worklog 为空，这一层几乎总是有数据。**
- `jira_worklog`：工时。为空时写 `zero_result` 并说明是"字段无人填写"还是"查询失败"，两者含义完全不同。

这两层曾被合成一个 `jira_linear_worklog: not_applicable / not collected this run`，结果 W32 有 25 个自建 issue（含把 4 个 Quick Win 需求拆成 19 个子任务）整块缺席正文。`jira_*` 停在"本轮未采集"时 validator 以 `COVERAGE-008` 失败。

**Slack 必须同时采出站与入站：**

```bash
node <skill-dir>/scripts/collect-slack.mjs --week <YYYY-MM-DD>
```

出站只能说明我说了什么，入站才说明别人找我做什么。两个查询口径坑：

- **被提及必须用 `<@UID> -from:@self`。** `to:@self` 是 DM 作用域——实测它与 `to:@self is:dm` 返回值完全相等，拿它当被提及数会虚高约 10 倍。validator 以 `COVERAGE-009` 拦住只用 `to:@` 的 query。
- **`is_bot` 不可靠**，实测 `canary release`、`moego_github_actions`、`gengar` 都是 `false`。自动化要额外按作者名匹配，否则发布通知会被当成人找我：W31 被 @ 63 次里 35 次是自动化，不分开就会把发布噪音当协作量。

`slack_inbound` 停在"本轮未执行"时 validator 以 `COVERAGE-009` 失败。原始 match 正文留 scratch；**raw Slack user/channel id 不能进 vault 的 markdown**，`PRIVACY-024` 会拦。

### 范围外：用户已确认不需要的来源

以下三项是**有意排除**，不是缺口。不要在正文或 manifest 里当作"待补齐"反复提起，也不要为它们写 `skipped_reason` 式的歉疚说明：

- **PR review 的轮次与逐条评论正文**。PR 列表与 review 关系已由 `collect-github.mjs` 覆盖，评审来回耗时不纳入。
- **Linear**。团队不使用。
- **Jira worklog 字段**。JQL 可查且每次都执行，但字段无人填写（全历史仅 3 条），不作为工时口径——记 `zero_result` 并说明"字段未使用"即可。

所有来源都必须写入 `evidence-manifest.json`：

- 执行过的 source 写 `status=scanned` 或 `partial`
- 空结果写 `status=zero_result`
- 工具不可用、权限不足、用户跳过、场景不适用时分别写 `tool_unavailable`、`permission_denied`、`skipped_by_user`、`not_applicable`
- 命中的 shared clip 必须进入 `meetings/会议索引.md`，保留 `minute_token`
- 原始 Slack JSON、session JSONL、工具 dump 不进 vault
- 飞书/Lark 会议、纪要或转写如果拉到空正文、权限拒绝、明显过短的占位内容、只有元数据没有正文，或与用户给出的真实链接不一致，不能静默当作完成。先在会议文件和 `迭代记录.md` 写明 `human check required` / `permission_denied` / `empty_or_placeholder`，再请用户检查或提供真实纪要/转写/秒记链接；用户给出真链接后按该链接重建。

**Meeting Archive 效率规则**：当使用 workflow/subagent 并行归档多个会议时，应先在主 agent 做一次 `lark-cli auth status` 确认 auth 有效，然后将所有 meeting 的 doc token 列表传入 pipeline，而非每个 subagent 各自 auth。批量 `docs +fetch` 到 scratch 后再分发格式化。减少冗余 auth 开销。

### 步骤 7：Evidence Manifest、产出总账、Human Checkpoint 与主线选择

在正式写 `周复盘.md` 前，先生成或更新 `evidence-manifest.json` / `evidence-manifest.md`，并完成一次轻量 human checkpoint。

先从所有 source 构建 `output_items[]`。实质产出的定义包括：已发布/已交付资产、live 状态变化、完成验证的工程结果、形成明确文档/skill/知识资产的工作、实质推进但尚未完成的项目，以及完成 handoff/决策闭环的关键协作。普通 chatter、仅参会、重复文件和无产物探索不算独立产出。

每个 `output_item` 必须有状态、证据、正文锚点和是否适合 Sprint Review 的标记。正文中的 `本周产出总账` 必须覆盖全部 `output_items`；不允许以“没有改变本周主线”为理由排除真实产出。

完成总账后，再基于 manifest/source matrix 输出 3 个候选主线，每个候选包含 `thesis`、`supporting_evidence`、`contradicted_by`、`best_audience`。主线用于决定篇幅和叙事顺序，不用于删除产出。

生成 vault 外 scratch 文件 `<scratch-dir>/human-checkpoint.md`，内容包括：

- 3 个候选主线
- 完整产出总账及各项状态
- 高信号证据列表
- 不确定项
- 敏感候选
- Slack/会议待确认点

如果交互工具可用，向用户 询问这些有价值的问题：

- 本周主线 A/B/C 哪些值得重点展开？（允许多选；未选择的产出仍保留在总账）
- 高信号证据里有没有明显漏掉的本周重点？
- 哪些 Slack/会议讨论值得写进复盘，哪些只是背景噪音？
- 哪些内容涉及 1v1、绩效、客户、事故、权限或敏感信息，需要只摘要不展开？
- 哪些内容适合 Sprint Review，哪些只适合个人复盘？

执行规则：

- Codex 环境优先用 `functions.request_user_input`，默认等待 90 秒。
- 如果 `request_user_input` 不可用或超时，记录 assumptions 后继续。
- 不进行第二轮追问，避免 checkpoint 变成新卡点。
- 不要询问是否放 vault、是否包含会议、是否跑 validator；这些已经是固定 contract。
- Vault 中只记录 checkpoint 状态、关键 assumptions 和哪些 section 使用了用户补充；详细问答只留 scratch，不进 vault。

### 步骤 8：综合生成复盘

以用户视角写作，但省略第一人称。

**日期→星期映射必须机械化**：主 agent 在委派写作前，必须用 `date` 命令或 `python3 datetime.weekday()` 预计算该周每天的星期几，生成映射表（如 `7/6=Mon/周一, 7/7=Tue/周二, ...`），并将该映射表作为硬约束传递给所有写作 subagent。禁止 subagent 自行推算星期。

推荐句式：

- `本周完成了...`
- `推进了...`
- `沉淀了...`
- `风险集中在...`

禁止：

- `我做了...`
- `我完成了...`
- 以证据方法论作为开篇
- 在主报告中放原始小时日志
- 自说自话、agent 日记腔、可见的过程叙述

默认主报告结构：

1. 本周概览
2. 本周一句话判断
3. 本周产出总账
4. 可直接贴到 Sprint Review 的内容
5. 主要推进
6. 每天在做什么
7. 协作与沟通（含会议 + Slack 异步协作）
8. 个人复盘
9. 风险、遗留问题与下周建议
10. 证据口径

`本周概览` 和 `本周一句话判断` 可以围绕重点主线组织；`本周产出总账` 必须按工作流聚合全部实质产出，标注 `已发布 / 已完成 / live / 进行中 / blocked / 暂停`。可以合并同一工作流的多个文件，禁止为了简短把其他工作流删掉。

`可直接贴到 Sprint Review 的内容` 是从总账中二次筛选的公司相关摘录，默认不超过 6 条。用户 可以只复制其中一部分；个人创作、敏感 1v1 和未完成探索可以不进入 Sprint 摘录，但仍保留在个人复盘。

`协作与沟通` 合并会议输入和 Slack 协作证据：

- `### 会议` — 飞书/Lark 会议的决策、上下文和 action item
- `### 异步协作（Slack）` — 3-5 条最高信号协作结论，覆盖参与的主要话题、关键决策/行动、links/handoff 和低信号 chatter 的排除口径；仅可少量引用 用户 自己的关键表达，每 thread 最多 2 句

当 Slack 证据不可用（连接故障或零结果）时，省略该子节并在证据口径中标注。

证据口径放末尾。读者应先看到有用的复盘内容，而非审计机制。

产出类别写成 **层级 tag**，值来自本周 `output_items[].category` 去重后按产出数降序，加在既有 `tags` 列表里：

```yaml
tags:
  - 工作/周报
  - MoeGo
  - category/engineering
  - category/knowledge-system
  - category/communication
```

**不要用 frontmatter 的 `category:` 属性。** 平铺属性只进 Properties 面板，Tags 树建不起来，侧栏里没法像目录那样展开浏览；层级 tag 才会在 Tags 面板折叠成 `category > engineering` 这种可点的节点，和 vault 现有的 `工作/周报`、`个人学习总结/方法论` 一致。`REPORT-015` 校验 tag 与 manifest 双向一致（缺 tag、或有 tag 无对应产出都会 fail）。

### 步骤 9：构建或更新归档包

创建或更新约定的归档目录。目标只能是自动推导的 digital-garden Vault 路径：

```text
<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/
```

注意：`<日期范围>/` 本身就是 digital-garden 最终包目录。禁止把 `<YYYY-Www__YYYY-MM-DD--YYYY-MM-DD-周复盘>` 这类 workspace 目录嵌套到 `<日期范围>/` 里面。
禁止在 vault 内创建任何临时证据目录，例如 `<vault>/work/weekly-work-review` 或 `<vault>/Work/weekly-work-review`。macOS/iCloud 默认大小写不敏感，`work/` 会撞到现有 `Work/`。

禁止为同一周创建 `-2`、`最新版`、`final-v2` 或以运行日期命名的兄弟目录。

更新语义：

- 重新生成或更新 `周复盘.md` 到最新证据覆盖范围
- 更新或创建 `小时证据附录.md`；无可用小时证据时写 `zero_result` / `not_applicable`
- 在 `迭代记录.md` 中追加运行时间戳、覆盖范围、来源变化和已知缺口
- upsert 会议文件夹，不覆盖未知的手动笔记
- 从实际会议文件夹重新生成 `meetings/会议索引.md`
- 禁止删除已有归档目录中的未知文件、手动笔记或附件

### 步骤 10：准备 Digital-Garden 目标

写入 vault 前：

1. 确认 vault 根路径：
   - `<vault-root>`
2. 读取 `<vault>/CLAUDE.md` 和 `<vault>/Work/MoeGo/README.md`
3. 使用自动推导的 MoeGo 周复盘目标路径：

```text
<vault>/工作/周报/<YYYY>/<MM>/<日期范围>/
```

digital-garden 发布路径由 `week_start` 推导：

- `YYYY` 和 `MM` 为 `week_start` 的年和月
- `N` 为该月中以周一起始的序数周号，从 1 开始
- 例：`week_start=2026-06-01` 发布到 `记录/复盘/2026/06/<日期范围>/`
- 具体日期范围写入 frontmatter `date_range: YYYY-MM-DD-YYYY-MM-DD`；不在 vault 目录名中编码日期范围

目标边界：

- 默认发布精编复盘包
- 周报包含 `<日期范围> 周复盘.md`、`小时证据附录.md`、`迭代记录.md`、`evidence-manifest.json`、`evidence-manifest.md`、`validation-result.json` 和 `meetings/会议索引.md`；会议正文归 `工作/会议/<YYYY>/<MM>/`，周报包只索引
- 即使没有会议命中，`meetings/会议索引.md` 也要存在并写明 `zero_result`
- 当 transcript/verbatim 文本可用时包含完整 `会议转写.md`
- 不因普通内部会议敏感性而阻止转写发布；用户 需要完整转写随归档一起保存
- 飞书/Lark 会议纪要 PDF 必须用 `drive +export` 原样导出为 `exports/飞书原始纪要.pdf`；不要对 PDF 做脱敏、摘要化、截图替代或二次转换
- 会议主文件与 `会议转写.md` 是会议正文归档，不是对外摘要；除凭证/密钥形状字符串触发安全门禁外，不主动替换姓名、用户 ID、客户名、说话人或原文句子
- 除非明确要求，不将原始 session JSONL、完整工具输出、Lark 元数据 dump 或 prompt 日志发布到 vault
- 保持凭证形状字符串扫描并报告命中，但不因会议内容敏感就用指针替换完整转写
- 除非用户明确批准单独的 wiki 候选项，不将周进展、会议笔记或转写写入 `Research/wiki/`

### 步骤 11：收口 Evidence Manifest 与 Validation Readback

在交付前，必须收口 `evidence-manifest.json` 和 `evidence-manifest.md`。Manifest 是本周复盘的可审计证据账本，不是可选附录。

必须读取并遵守 `references/evidence-manifest-schema.md`。

Manifest 至少覆盖以下 source：

- `sessions`
- `slack_outbound`
- `slack_inbound`
- `lark_vc`
- `lark_calendar`
- `lark_minutes_owner`
- `lark_minutes_participant`
- `shared_clip_link_extraction`
- `shared_clip_keyword_search`
- `lark_drive_docs`
- `local_vault_notes`
- `personal_outputs`
- `github_activity`
- `jira_linear_worklog`

每个 source 必须记录 `status`、`query` 或 `artifact_path`、`raw_count`、`candidate_count`、`used_count` 和 `skipped_reason`。没有执行也要写清原因：`zero_result`、`skipped_by_user`、`tool_unavailable`、`permission_denied`、`not_applicable` 之一。禁止静默缺席。

候选证据必须先进入 manifest，再决定是否写入正文：

- `candidate_items[]` 记录所有高信号证据
- `output_items[]` 记录所有经证据确认的实质产出；每一项必须进入 `周复盘.md#本周产出总账`
- `used_in_report[]` 记录被 `周复盘.md` 使用的证据
- `excluded_with_reason[]` 记录收集到但未使用的证据
- 每个 `candidate_items[]` 必须且只能进入 used 或 excluded；禁止静默未分类，也禁止同时使用和排除
- 任何 raw/candidate 数量非 0 的 source，如果 `used_count=0`，必须有排除理由
- 命中的 shared clip 必须进入 `meetings/会议索引.md`，并在 manifest 中以 `type=shared-clip` 标记

收口规则：

1. `evidence-manifest.md > Validation Readback` 必须写入真实 validator 输出，包含 `passed` 或 `failed`；只有命令本身不算 readback。
2. 最终选择的主线写入 `本周概览`；未选择的实质产出仍保留在 `本周产出总账`，不得从个人复盘消失。
3. 禁止把证据数量放进首段；数量统计只进 `证据口径` 或 `evidence-manifest.md`。
4. `主要推进` 每个小节必须至少绑定一个 evidence anchor：会议标题、minute token、doc title、repo/PR/commit、版本号、验证命令、readback 或 session id。
5. `Sprint Review` 摘录最多 6 条；每条固定包含 `交付物/判断`、`影响/状态`、`下一步/请求`，没有证据锚点则降级为”待复核”。

**Manifest 生成策略**：`evidence-manifest.json` 不委派给 subagent 用 Write 工具拼接。主 agent 在收到所有 evidence summary 后，用 python3/node 脚本一次性生成完整 JSON（包含 schema 要求的全部字段：`source_path_or_token`、`evidence_ref`、`used_in` 等），确保 validator 一次通过。写入前先读取 `scripts/validate-package.mjs` 的 required fields 列表作为 checklist。

### 步骤 12：质量门禁

门禁由 validator 强制执行，不靠人工逐条回忆。**两阶段收口**，因为 readback 必须绑定最终 manifest hash：

```bash
# 1. manifest 定稿后先跑一次，拿到 manifest_sha256
node <skill-dir>/scripts/validate-package.mjs <week_dir>

# 2. 把 status/validator_version/manifest_sha256 写进
#    evidence-manifest.md > Validation Readback，然后复跑确认
node <skill-dir>/scripts/validate-package.mjs <week_dir>
```

`validation-result.json` 由 validator 写出，记录状态、时间、包路径、`manifest_sha256`、validator 版本和命中的规则 ID。它是 receipt，不要手写。

失败必须先修再交付。规则 ID 与含义：

| 规则 | 含义 |
|---|---|
| `PATH-002` | 周目录名必须是日期范围，不接受 `week-N` |
| `PATH-003` | 周目录内不得嵌套旧式 workspace 目录 |
| `REPORT-001` / `REPORT-004` | 主报告缺失，或文件名与周目录不一致 |
| `REPORT-012` / `REPORT-013` | frontmatter 缺 `week_start`/`week_end`/`iso_week`，或与 manifest 不一致 |
| `REPORT-014` | frontmatter tags 必须含 `工作/周报` |
| `REPORT-015` | 缺 `category/<value>` 层级 tag，或与 `output_items[].category` 不一致 |
| `REPORT-020` | 主报告缺必需章节 |
| `REPORT-030` | Sprint Review 摘录超过 6 条 |
| `REPORT-040` | `output_items.report_anchor` 无法在正文回读 |
| `STYLE-001` | 出现第一人称 `我做了` / `我完成了` |
| `PRIVACY-002` | 整包命中凭证形状（会议原文不豁免） |
| `PRIVACY-020`–`024` | 飞书临时资产 URL、session dump、workspace 口径、raw Slack 结构 |
| `MANIFEST-001` | 违反 `evidence-manifest.schema.json` |
| `MANIFEST-010`–`012` | source 状态与 query/artifact/skipped_reason/empty_results 不自洽 |
| `MANIFEST-020`–`023` | candidate id 重复，或引用了不存在的 candidate |
| `MANIFEST-030` / `031` | candidate 未分类，或同时 used 与 excluded |
| `COVERAGE-001`–`006` | coverage 计数与实际数组不一致，或产出覆盖不足 |
| `COVERAGE-007` | `github_activity` 仍声明本地 git 口径，PR 与 review 未采集 |
| `COVERAGE-008` | `jira_*` 仍声明"本轮未采集"，或空 worklog 未说明原因 |
| `COVERAGE-009` | `slack_inbound` 仍声明未执行，或用 `to:@` 冒充被提及 |
| `MEETING-001` | 会议索引缺必需列 |
| `MEETING-005`–`009` | 空正文、权限页、占位内容，或假冒 `transcript_publication: full` |
| `MEETING-010` / `011` | 有 note doc token 却缺 PDF，或缺 token 又无 `pdf_unavailable_reason` |
| `CLIP-001`–`003` | shared clip 未进索引或丢失 `minute_token` |
| `RECEIPT-001`–`003` | readback 缺失、记录 failed、或未绑定当前 manifest hash |

补齐会议纪要 PDF：

```bash
node <skill-dir>/scripts/export-meeting-pdfs.mjs <week_dir> --dry-run  # 先预览
node <skill-dir>/scripts/export-meeting-pdfs.mjs <week_dir>
```

`--dry-run` 保证零写入，可安全预览。修复会议文档同理：`repair-meeting-docs.mjs <week_dir> --dry-run`。

回归测试：

```bash
node <skill-dir>/tests/run-tests.mjs
```

使用 `rg`/`find`/`wc` 验证。若 Python 慢或损坏，用 Node、`jq` 和 shell 工具。

### 步骤 13：Skill 运行复盘

每次运行结束前，从本轮会话和用户纠正中提炼一次 skill 运行复盘，并追加到本周 `迭代记录.md`：

- `initial_miss`：初版遗漏、误判或过度展开了什么
- `user_correction`：用户 如何纠正
- `root_cause`：采集、分类、叙事、状态或验证 contract 的哪个环节失效
- `durable_change`：本轮已修改的 contract/eval/validator，或留待后续验证的候选改动
- `verification`：用什么当前包或测试证明改动有效

下一次运行必须读取最近三次此记录。单次偶发问题只记录；同类问题重复出现，或直接违反 用户已确认的固定默认时，同步修改 `SKILL.md`、相关 reference、eval 和 validator，禁止只修当周正文。

## 最终回复

仅返回有用的交付物链接和紧凑状态：

- digital-garden 包路径
- 主 `周复盘.md`
- 会议索引
- 已知缺口（如缺失转写权限）

除非用户要求，不在聊天中贴出完整复盘内容。

## 参考

- `references/output-contract.md` — 精确产出契约和写作规则
