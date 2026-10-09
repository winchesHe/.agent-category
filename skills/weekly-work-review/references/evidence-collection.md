# Evidence Collection Reference

本文件定义 `weekly-work-review` 的证据采集细则。`SKILL.md` 只保留流程骨架；采集时按本文件执行，并把所有结果写入 `evidence-manifest.json`。

所有原始证据输出必须写到 vault 外 `<scratch-dir>/`，例如：

```text
<scratch-root>/<YYYY>/<MM>/<日期范围>/
```

禁止在 digital-garden 内创建 `work/weekly-work-review`、`Work/weekly-work-review` 或 `outputs/`。

## AI Sessions

使用 `scripts/collect-sessions.mjs`，后端为 `memory-manager` CLI。它只提供证据，不写最终复盘。

先备份 `~/.memory-manager/memory.db`（含 `-wal`/`-shm`）到 scratch，再采集——采集器默认会先扫描刷新索引：

```bash
node <skill-dir>/scripts/collect-sessions.mjs --week <YYYY-MM-DD>
```

覆盖的 agent：`claude`、`codex`、`opencode`、`pi`、`copilot`、`cursor`。

采集器契约：

| 行为 | 说明 |
|---|---|
| 默认先扫描 | 先跑 `scan --all` 刷新索引再查询；写 `~/.memory-manager`，不写 vault |
| `--no-scan` | 跳过刷新只查旧索引；仅在用户明确要求时使用，覆盖可能滞后 |
| `scan` 字段 | `requested`/`skipped`/`ran`/`ok`(/`error`)，必须回读并写进 manifest |
| `--stdout` | 只打印不落盘 |
| 输出位置 | `<scratch-dir>/<YYYY>/<MM>/<日期范围>/session-evidence/session-index.json` |
| 工具缺失 | `status=tool_unavailable`，退出码 0 |
| 写入 vault | 以 `SESSION-002` 失败 |

底层命令（需要手工核查时使用）：

```bash
memory-manager status                    # 工作区是否就绪
memory-manager projects list             # 项目 + session 数 + agents
memory-manager projects sessions [slug]  # 结构化 metadata
memory-manager sessions show <id>        # 读原文，大 session 加 --stream
```

要求：

- 记录本周 session 总数、各 agent 拆分、覆盖天数、`latest_indexed_at`、本轮 `scan` 结果
- `scan.ok` 不为 true（失败或被 `--no-scan` 跳过）时不得声称覆盖完整
- `latest_indexed_at` 早于 `week_end` 时，必须在 manifest 写明索引滞后与是否已重扫
- 按 `moego-work / writing-creation / knowledge-system / personal-project / review-meta` 分类，禁止默认排除个人写作或创作 session
- `review-meta` 不计入生产产出，但可计入工时，并用于提炼本轮 skill 运行优化
- 对重要 session 读源 JSONL 切片后再下结论
- 高风险操作必须显式进入 manifest：IAM、数据库、生产 API、密钥、SSH/sudo、隐私数据、外部服务写入
- 原始 session JSONL 和 prompt/tool dump 保留在 vault 外 `<scratch-dir>/`，不发布到 vault

## Slack

目标不是做普通消息搜索，而是还原本周 Slack 协作事件：参与过的 channel/DM/thread、关键 context、decision、clarification、action item、handoff 和 links。禁止把他人逐字消息、raw Slack JSON 或 DM 明细归档到 vault。

首选本地 Slack skill：

```bash
SLACK_SKILL="${WEEKLY_REVIEW_SLACK_SKILL_DIR:-<skills-repo>/slack}"
test -f "$SLACK_SKILL/scripts/slack.py" && echo "local-slack available"
```

搜索发出消息：

```bash
python3 "$SLACK_SKILL/scripts/slack.py" search \
  "from:@perfecto after:<week_start - 1d> before:<week_end + 1d>" \
  --limit 200 --sort timestamp --sort-dir asc \
  --output <scratch-dir>/slack-evidence/outbound.json
```

搜索被提及消息：

```bash
python3 "$SLACK_SKILL/scripts/slack.py" search \
  "<@perfecto_slack_user_id> after:<week_start - 1d> before:<week_end + 1d>" \
  --limit 200 --sort timestamp --sort-dir asc \
  --output <scratch-dir>/slack-evidence/inbound.json
```

本地 skill 不存在或 token 不足时，降级到 Composio Slack；两者都不可用时，manifest 记录 `tool_unavailable`。

处理规则：

- 生成 `<scratch-dir>/slack-evidence/slack-events.json` 和 `<scratch-dir>/slack-evidence/slack-summary.md`，用于内部分析。
- `evidence-manifest.md` 必须保留一版人类可读 Slack collaboration summary；scratch 只保存 raw/detail。
- Slack collaboration summary 最低包含 3 类内容：参与的主要话题、关键决策/行动/handoff、被排除的低信号 chatter 及理由。
- 若 Slack 数据不可用，summary 必须写明 `unavailable` / `partial` / `zero_result` 和原因。
- 复盘正文只保留 3-5 条最高信号协作结论，不写 Top channel 原始表，不把 `周复盘.md` 写成 Slack 日志。
- DM 只做主题级摘要，不默认列出 DM 对象、原文或对方身份；只有该身份是复盘上下文必要锚点且非敏感时才可写。
- 他人逐字消息禁止入 vault；用户 自己的关键决策表述可短引，每 thread 最多 2 句。
- raw channel/user id、`text/user/ts/blocks` dump、完整 blocks、完整 JSON 只能留在 scratch。

高信号 thread 规则：

- 用户 发起或深度参与。
- 包含 decision、clarification、action item、blocker 或 handoff。
- 包含文档、PR、会议、ticket 或 release 链接。
- 被多人回复或跨天推进。

只拉取高信号 thread context。低信号 thread 不拉 context，只记录 excluded reason。若搜索结果全是低信号，可以通过，但必须有低信号排除摘要。

失败处理：

| 条件 | 动作 |
|---|---|
| 本地 skill 不存在 + Composio 不可用 | manifest 标 `tool_unavailable` |
| 本地 skill 存在但 `SLACK_USER_TOKEN` 未配置 | 降级到 Composio；仍失败则标 `permission_denied` 或 `tool_unavailable` |
| `not_allowed_token_type` | 说明 token 类型不支持 search，降级到 Composio |
| 搜索返回 0 | manifest 和 `evidence-manifest.md` 记录 `zero_result` |
| 限流 | 重试；仍失败则标 `partial` |

## Lark Meetings And Minutes

涉及飞书/Lark 时先用 `/feishu-operations` 路由。所有飞书读写走 `lark-cli`，禁止 WebFetch 或浏览器抓取飞书认证页面。

最低采集链路：

- `lark-cli auth status`
- `lark-cli vc +search`
- calendar fallback：发现已接受但没有 VC 记录的会议
- `lark-cli minutes +search --owner-ids me`
- `lark-cli minutes +search --participant-ids me`
- `lark-cli vc +notes` 仅用于发现纪要/章节/待办和辅助定位文档，不作为转写正文的首选来源
- 从会议纪要 docx 底部提取 `文字记录` docx 链接；使用 `lark-cli docs +fetch --doc <文字记录 docx> --doc-format markdown` 获取完整转写正文并写入 `会议转写.md`
- 使用 `scripts/export-meeting-pdfs.mjs <week_dir>` 批量导出 `note_doc_token` / `note_doc_url` 的纪要 PDF。该 helper 只导出会议纪要 PDF，不导出转写；缺 token 时走 `minutes +detail -> note +detail` 取 `note_doc_token`。
- `docs +fetch --api-version v2 --doc-format xml --detail full` 提取 `<whiteboard>` / `<img>`
- `whiteboard +query --output_as image` 下载白板

会议归档规则：

- 每个会议在 `meetings/` 下有独立文件夹
- upsert key 优先级：minute token、note doc token、transcript doc token、meeting id、时间 + 标题
- 每个会议文件夹包含 `会议纪要.md`、`会议转写.md`；不可用时写明原因
- 可用时包含 `exports/飞书原始纪要.pdf`
- 当 `note_doc_token` / `note_doc_url` 不可用时，`会议纪要.md` 或 manifest 必须写 `pdf_unavailable_reason`
- 会议纪要 PDF 用 `drive +export` 原样导出，不做脱敏、摘要化或二次转换
- `会议纪要.md` / `会议转写.md` 保持飞书正文语义和说话人信息；不要主动替换姓名、用户 ID、客户名或原文句子。只有凭证/密钥形状字符串触发安全门禁时才停下处理。
- 读取会议纪要 docx 时，必须保留或记录底部 `文字记录` docx 链接；它是转写正文的首选 source。不要用妙记/minutes 链接导出转写作为默认路径，妙记权限不稳定且不必要。
- 图片/白板存入本地 assets，并在 `会议纪要.md` 用相对链接引用
- 禁止把 `internal-api-drive-stream.feishu.cn` 作为持久资产链接

空内容 / 权限异常处理：

- `permission_denied`、空正文、只有标题/元数据、明显过短的秒记、错误页、或“无权限查看”不能当作完整会议证据。
- 遇到上述情况时，仍可创建会议文件夹和索引行，但必须在 `会议纪要.md` / `会议转写.md` 里写明读取状态，并在 `迭代记录.md` 标记需要 human check。
- 如果用户 提供真实纪要、转写或秒记链接，优先用用户给出的纪要/转写 docx 链接通过 `docs +fetch` 重建；秒记/minutes 链接只用于发现和元数据核对，不作为转写正文导出的默认路径。同步更新 `meetings/会议索引.md`、`evidence-manifest.*` 和已知缺口。
- 不要为了补齐会议数量，把空会议、8 秒占位记录或权限错误页写成事实性总结。

录音豆 / 独立妙记处理：

- `minutes-owner` 或录音豆导入记录可以作为无 VC、敏感会议或未开共享会议时的有效来源，不得一概排除。
- 这类记录没有 `meeting_id` 或说话人/共享画面信息不稳定时，会议时间优先级为：纪要/转写正文前几行的 `录音时间` / `会议时间` > VC `meeting_id` 对应时间 > minutes search / 文档创建或导入时间。不要只按导入后的创建时间或搜索结果展示时间入周。
- 读取录音豆导入 docx 时，必须先 `docs +fetch` 检查标题和正文开头；例如 `录音时间：2026年6月22日 14:59 - 16:05` 应作为归档周判断依据，即使文档或文字记录是在 7/1 才导入/生成。
- 入周前与近几周已有 VC、1v1 笔记和会议转写做标题、关键词、时长、开头转写相似度去重。
- 如果高度重复于已有 VC/1v1 会议，应作为 duplicate/import artifact 处理，归到原会议所在周，不作为导入周的新会议证据。

## Shared Clips

不能把 owner/participant 搜索当作 shared clips 全量覆盖。必须额外执行：

1. Slack outbound/inbound 中抽取 `feishu.cn/minutes/<minute_token>`、`larksuite.com/minutes/<minute_token>`
2. 本地 vault `Work/MoeGo/记录/`、`Work/MoeGo/思考/` 中抽取 `minutes/<minute_token>`
3. 特别覆盖 `1v1/`、`复盘/`、`会议/`、`项目`
4. 从命中标题、1v1/会前准备/会后复盘标题、高频协作者名生成 5-20 个关键词
5. 对每个关键词执行 `lark-cli minutes +search --query "<keyword>" --start <week_start> --end <week_end> --page-size 30 --format json`
6. 对候选 token 去重后执行 `lark-cli vc +notes --minute-tokens <tokens>`，只用于发现纪要文档、章节、待办和可能的 `文字记录` docx 链接
7. 转写正文优先从纪要底部 `文字记录` docx 链接用 `docs +fetch` 获取；不要默认通过妙记/minutes 链接导出转写
8. `minutes get` 元信息为空但 `minutes +search` 或 `vc +notes` 有产物时，仍视为可用证据

归档规则：

- `meetings/会议索引.md` 中标 `source_type=shared-clip` 或 `shared-minute`
- 保留 `minute_token`
- 如果已有本地 1v1 笔记，链接该笔记作为上下文
- 能读取 transcript 时仍归档完整 `会议转写.md`
- 关键词命中和空结果都写入 `evidence-manifest.md`

**Shared minute 转写穷尽规则**：即使没有 verbatim_doc_token，也必须按以下顺序尝试获取转写，全部失败才标 `transcript_unavailable`：

1. 检查 `vc +notes` 是否已将 transcript 写到本地（`minutes/<token>/transcript.txt`）——lark-cli 默认输出到 cwd，必须检查运行目录和 scratch 目录
2. 如果 `vc +notes` 输出有 `note_doc_token`，用 `docs +fetch` 读取纪要 docx，检查底部是否有 `文字记录` 链接
3. 尝试 `lark-cli minutes +search --query <title_keyword>` 看是否返回 transcript URL 或 verbatim_doc_token
4. 三步全不行时创建 `会议转写.md` 写明 `transcript_unavailable`、已尝试的来源和失败原因

## Lark Drive Docs

Drive opened/edited/commented/recent 文档必须分组：

- `used`：进入正文或主要推进
- `background`：帮助理解，但不写正文
- `irrelevant`：与本周复盘无关
- `sensitive-excluded`：敏感或不适合进入 vault

正文只引用 `used`。完整 opened/edited 列表放 `小时证据附录.md` 或 `evidence-manifest.md`。

## Personal Outputs

周复盘是 用户 自己阅读的完整记录。除 MoeGo 工作外，必须扫描：

- `Writing/` 中本周发布、修改或生成资产的文章项目
- 活跃 `Projects/` 中本周形成正文、设计、代码、图片、排版、视频、PDF 或验证结果的项目
- 本周新增或实质更新的知识系统、compile report、skill 和长期维护资产
- 用户在本轮对话明确指出但自动扫描未命中的产出

处理规则：

- 以项目 `CONTEXT.md`、当前正文、资产树、发布状态和生成报告交叉验证；mtime 和文件数量只能证明范围，不能证明质量
- 写入 `sources_scanned.personal_outputs`
- 每个实质产出进入 `output_items[]` 和 `周复盘.md#本周产出总账`
- 已发布、已完成、live、进行中、blocked、暂停必须区分
- 个人创作默认不进入 Sprint Review，但不得因此从个人复盘移除
- 普通灵感、无产物浏览、纯工具配置和重复导出不单列为产出

## GitHub, Code, Jira, Linear, Worklog

如果工具可用，做只读采集：

- GitHub/本地 git：PR authored/reviewed/commented、commits、release、CI、repo touched
- Jira/Linear/worklog：assigned、updated、commented、resolved、worklog

如果工具不可用，manifest 标 `tool_unavailable`。AI sessions 只能解释代码活动上下文，不能替代 code/ticket source。
