---
name: jira
description: >-
  读取 Jira 工单、评论、附件图片、关联单和 CS-* linked Intercom conversations，
  并支持搜索、创建、automation 创建、字段更新和工作流 transition。唯一入口 scripts/jira.py，
  子命令 read / intercom / search / download-attachment / upload-attachment / create-meta / create / update / link / transition。当用户提供
  Jira URL、issue key、CS- 工单、JQL、附件截图、Intercom linked conversations、
  创建工单、更新工单字段时使用。
---

# Jira Skill

通过 Jira REST API 读取 Jira 工单上下文、评论、附件截图和关联信息；`CS-*` 工单默认继续读取 Jira 中暴露的 Intercom Browse linked conversations 信息。写操作默认 dry-run，只有显式 `--execute` 才真正创建或更新。

## 前置条件

| 项 | 说明 |
|---|---|
| Python | >= 3.10 |
| 依赖 | 无第三方依赖，使用 Python 标准库 |
| 配置 | 复制 `<SKILL_DIR>/.env.example` 为 `<SKILL_DIR>/.env`（`<SKILL_DIR>` = 本 SKILL.md 所在目录），填入 Jira 账号和 token；如需读取 Intercom linked conversation 详情，填入 `JIRA_INTERCOM_JWT`。Automation rule URL 不在 `.env` 里配置，每次调用动态传 `--automation-rule`（见 Automation 创建章节） |

认证变量支持两组名称：

| 用途 | 变量 |
|---|---|
| Jira 登录 | `JIRA_LOGIN` 或 `JIRA_EMAIL` |
| Jira token | `JIRA_API_TOKEN` 或 `JIRA_TOKEN` |
| Jira 站点 | `JIRA_BASE_URL`，默认 `https://moego.atlassian.net` |
| Intercom for Jira | `JIRA_INTERCOM_JWT` 或 `JIRA_INTERCOM_JWT_COMMAND`，用于读取 linked conversation GraphQL 详情 |

## 脚本位置

**唯一入口始终相对于本 SKILL.md 所在目录：**

```
<本 SKILL.md 所在目录>/scripts/jira.py
```

> 解析规则：你是从某个绝对路径 `cat` / 读取到这份 SKILL.md 的，**那个目录就是 skill 根**，脚本必然在它的 `scripts/` 子目录下。**不要用 CWD 相对路径，始终用 SKILL_DIR 绝对路径。**

1. 已知本 SKILL.md 的绝对路径时（最常见，直接用读取它的路径）：
   ```bash
   SKILL_DIR="<本 SKILL.md 所在目录>"
   python3 "$SKILL_DIR/scripts/jira.py" <subcommand> [flags]
   ```
2. 不确定 SKILL.md 在哪时，按文件名定位 skill 根：
   ```bash
   SKILL_DIR="$(dirname "$(find . -type f -path '*/jira/SKILL.md' 2>/dev/null | head -n1)")"
   python3 "$SKILL_DIR/scripts/jira.py" <subcommand> [flags]
   ```
3. 仍找不到则直接搜脚本入口，取其绝对路径调用：
   ```bash
   find . -type f -path '*/jira/scripts/jira.py' 2>/dev/null
   ```

`.env` 必须放在 `<SKILL_DIR>/`（与 `SKILL.md` 同目录），由脚本自动加载。

后续示例为简洁使用 `python3 scripts/jira.py ...`；实际调用必须替换为 `$SKILL_DIR/scripts/jira.py` 绝对路径。

不要直接调用 `scripts/ji/commands/*.py`。

## 子命令速查表

| 子命令 | 作用 | 必填 flag |
|---|---|---|
| `read` | 读取工单基本信息、描述、CS 字段、评论、附件、关联单；`CS-*` 默认读 Intercom linked conversations | `issue` |
| `intercom` | 只读取 Intercom for Jira linked conversation；可按 Jira issue 发现 ID 或按 conversation id 直读 | `--issue` 或 `--conversation-id` |
| `search` | 用 JQL 搜索 Jira 工单，返回 Issue Type 与结构化关联单，走 POST `/rest/api/3/search/jql` | `jql` |
| `download-attachment` | 下载单个 Jira 图片附件到本地，供视觉检查；CDN 跳转可解析时返回安全的 `media_id` | `attachment_url` |
| `upload-attachment` | 上传单个本地图片附件；默认 dry-run，仅允许 PNG/JPEG/GIF/WebP | `issue` `image` |
| `create-meta` | 读取指定项目和 Issue Type 的实时创建字段、必填规则与 allowed values | `--project` `--issue-type-id` |
| `create` | 创建 Jira 工单；默认 automation 模式和 dry-run | `--project` `--issue-type` `--summary` |
| `update` | 更新 Jira 字段；默认 dry-run | `issue` `--patch` |
| `link` | 按 Jira 实时 Link Type 关联两张工单；默认 dry-run | `inward_issue` `outward_issue` `--type` |
| `transition` | 查询当前可用工作流动作，或按 ID/名称执行 transition；默认 dry-run | `issue`；执行时加 `--transition` |

## 通用 flag

| Flag | 说明 |
|---|---|
| `--format json|human|summary` | 默认 `json`。JSON 始终输出到 stdout；human 摘要输出到 stderr |
| `--execute` | 仅写操作支持。没有此 flag 时只输出 dry-run payload，不调用写接口 |

## 场景决策树

```text
用户给 Jira key / Jira URL / Slack mrkdwn Jira 链接，想看内容？
  -> read <issue> --comment-limit 50
  -> 如果是 CS-*，默认自动查找并读取 Intercom linked conversations

用户只想测试 Intercom linked conversation 读取？
  -> intercom --issue <issue>
  -> 已知 conversation id 时：intercom --issue <issue> --conversation-id <id>

用户要看附件截图？
  -> read <issue> --download-images
  -> 或先 read 找 attachments[].content_url，再 download-attachment <url>

用户明确要求把本地图片上传到 Jira？
  -> upload-attachment <issue> <image>
  -> 先看 dry-run 的路径、MIME、大小；确认后加 --execute

用户要找历史相似工单？
  -> search 'project = CS AND summary ~ "keyword" ORDER BY created DESC' --limit 10
  -> 需要根因详情时，再 read 候选工单，不从 search 摘要猜 Cause and Solution

用户要批量判断工单类型或关联目标？
  -> search '<JQL>' --fields summary,status,created,issuetype,issuelinks
  -> 使用 issues[].issue_type 与 issues[].links[]；不要只用 link_count 推断目标项目或类型

用户明确要创建工单？
  -> create --project <KEY> --issue-type <TYPE> --summary "..." [--description "..."]
  -> 默认 --mode automation，会调用配置的 Jira Automation manual invocation
  -> 先看 dry-run payload；确认后加 --execute

用户明确要走标准 Jira REST API 创建？
  -> create-meta --project <KEY> --issue-type-id <ID> 先核对实时字段和选项
  -> 调用方已有 ADF：优先 --description-adf-file <path|->
  -> 调用方只有 Markdown：使用 --description / --description-file，由 Skill 严格转换
  -> create --mode api --project <KEY> --issue-type <TYPE> --summary "..."
  -> 先 dry-run；确认后加 --execute

用户明确要更新字段？
  -> update <issue> --patch '{"components":["Payments"],"issueCause":"Bug"}'
  -> 先看 dry-run payload；确认后加 --execute

用户明确要关联两张 Jira 工单？
  -> link <inward-key> <outward-key> --type "Relates"
  -> 命令会读取实时 Link Type；先核对 dry-run，再加 --execute

用户要转单、推进 Jira 状态或提交设计？
  -> transition <issue> 先查询当前工单可用的 transition 和表单字段
  -> transition <issue> --transition "Design Request" [--fields '{...}']
  -> 先看 dry-run 解析出的 transition ID、必填字段和 payload；确认后加 --execute
```

## 领域知识

### `CS-*` 与 Intercom

`read CS-12345` 默认等同于 `--include-intercom auto`：

1. 读取 Jira 工单字段、描述、评论、附件元数据、关联单和 remote links。
2. 通过 Jira field catalog 发现 Intercom for Jira app 字段，优先读取 `Linked Intercom conversation IDs`。
3. 从这些文本中提取 Intercom conversation URL / conversation ID。
4. 从 Jira app 字段、remote links、字段和评论中汇总 linked conversation id、title、url 和 relationship。
5. 对每个 conversation id，优先用显式/命令/browser JWT；没有时调用 Jira Connect servlet 生成 dialog context，从 `contextJwt` 调 Intercom for Jira GraphQL。
6. 如果未发现 linked conversations 或拿不到 runtime JWT/contextJwt，输出 `warnings[]`，不要当作已读到客户原文。

显式使用 `--fields` 请求项目字段时，结果同时在 `requested_fields` 中返回已取到的字段值；这适合检查 `duedate`、工作流自定义字段等未被标准摘要覆盖的值。`--fields *all` 不展开该区块，避免无界复制全部字段。

如需跳过 Intercom：

```bash
python3 scripts/jira.py read CS-12345 --include-intercom never
```

### Description：ADF 优先、Markdown 兼容

标准 Jira API 创建时，调用方应优先输入完整 ADF：

```bash
python3 scripts/jira.py create --mode api --project ENG --issue-type Task \
  --summary "PRD" --description-adf-file ./description.adf.json
```

- `--description-adf-file <path|->` 是首选入口，保留 ADF 的原生结构；现有 `--additional-fields.description` 继续兼容并执行相同校验。
- `--description` / `--description-file` 接受 Markdown 或纯文本，由 Skill 按有限且严格的 `jira-md-v1` 转为 ADF；它不等于完整 ADF 能力。
- 三类 Description 输入互斥，格式只由参数决定，不自动猜测。非法 ADF、未支持 Markdown、残留标记或敏感链接会在写入前失败，不降级成字面量文本。
- Automation 的 Description 仍是 `PARAGRAPH` 字符串，不支持 ADF 输入，也不承诺 Markdown 富文本保真；需要原生富文本时改用 `--mode api`。
- API 执行成功后会回读 Description，并做忽略 Jira `attrs.localId`、保留其他结构语义的比较。

完整子集、错误码与安全策略见 `references/adf.md`。

### Automation 创建

`create` 默认 `--mode automation`，通过 Jira Automation manual invocation 创建工单。**rule URL 完全依赖调用者动态提供，没有任何静态默认 / 全局映射**——rule UUID、表单字段、所属项目都会随时变更（被删 / 重建 / 改字段），把它们硬编码进 SKILL 只会留下"看起来能用、其实早过期"的隐藏炸弹。

调用前的标准动作：

1. 在 Jira UI 打开目标工单，触发一次 manual-invocation rule（点 Automation → 选 rule → Run）。
2. 浏览器 DevTools → Network 抓那条 fetch（路径含 `gateway/api/automation/internal-api/jira/...`）。
3. 把 URL 直接传给 `--automation-rule`；body 里的 `userInputs` form 字段映射成 SKILL 输入。

⚠️ 路径前缀必须是 `gateway/api/automation/...`（不是裸 `api/automation/...`，那是浏览器内部 SPA 路径）。

#### 请求体格式

每条 manual-invocation rule 接受同一种 envelope：

```json
{
  "objects": ["ari:cloud:jira:<workspace-uuid>:issue/<numeric-id>"],
  "userInputs": {
    "<form-field-name>": {"inputType": "TEXT|PARAGRAPH|NUMBER|...", "value": "..."}
  }
}
```

| 字段 | 来源 |
|---|---|
| `objects` | `--parent <KEY>` 解析为 numeric id 后拼 ARI；可用 `--objects-issue-id <num>` 跳过 GET 查询 |
| `objects[].workspace_uuid` | 自动从 `--automation-rule` URL 中提取（`/internal-api/jira/<UUID>/`）；URL 不规范时用 `--workspace-uuid <uuid>` 手动指定 |
| `userInputs.summary` / `userInputs.description` | SKILL 默认填入 `--summary` / `--description` |
| 其他 form 字段（如 `storyPoint`） | `--automation-object '{"userInputs":{"storyPoint":{"inputType":"NUMBER","value":3}}}'` 深合并 |
| 完全自定义 envelope | `--automation-body-file <path>` 或 `-`（stdin），SKILL 自动构造全部旁路 |

#### CLI 必填项

`--mode automation` 时 `--automation-rule` 必填（除非通过 `--automation-body-file` 完全自定义 body 但仍需 `--automation-rule` 决定 POST 目标）。没有任何兜底 URL，缺失即报错。

#### 决策

- 用户给了 rule fetch 抓包 / URL → 直接 `--automation-rule <url>`
- 用户只说"创建一个工单"但没指定 rule → **不要猜测**，先问用户："请提供 Jira Automation rule 的 URL，或改用 `--mode api` 走标准 REST API"
- 调试不同 rule（如试新建的 storyPoint rule） → 抓新 fetch，每次现传

`--mode api` 不依赖 rule，只受标准 Jira hierarchy 限制（如 GRM Story 不能挂 Story 子级）。多数手动建 task 场景，`--mode api` 更直接。

### Update patch 白名单

| Patch key | Jira 字段 | Value |
|---|---|---|
| `components` | Components | `["Payments"]` |
| `labels` | Labels | `["bug", "cs"]` |
| `issueCause` | `customfield_10088` | `"Bug"` 或 `["Bug"]` |
| `causeAndSolution` | `customfield_10084` | `"Root cause: ..."` |
| `additionalFields` | 用户明确提供的 Jira field ID | JSON object |
| `descriptionAppendLinks` | 保留现有原生 ADF（含图片、表格和链接），在头部元信息、Description 顶部或末尾幂等写入链接 | `{"heading":"技术方案","position":"metadata","links":[{"text":"技术方案与估时（Approved V1）","url":"https://..."}]}` |

`descriptionAppendLinks` 会先通过 Jira Skill 回读当前原生 ADF。`position` 支持 `metadata` / `top` / `bottom`（默认 `bottom`）；同一 URL 已存在时可移动到目标位置或更新显示文案，URL、文案和位置都一致时跳过写入。技术方案入口应使用 `position=metadata`：已有头部引用块时追加一行，已有头部两列表格时追加一行，否则紧跟一级标题建立简洁引用块；避免单独创建突兀的顶级章节，也避免用纯文本重建 Description 导致图片和富文本丢失。

### Workflow transition

`transition` 不硬编码状态名或 transition ID。每次都先读取当前工单可用动作，并展开 transition screen 字段：

```bash
# 查询当前可用动作及表单字段（只读）
python3 scripts/jira.py transition GRM-1947

# 按名称生成 dry-run；名称大小写不敏感，但必须完整匹配
python3 scripts/jira.py transition GRM-1947 --transition "Design Request"

# transition screen 要求字段时，通过 Jira field ID 传原生 JSON
python3 scripts/jira.py transition GRM-1947 --transition "Design Request" \
  --fields '{"assignee":{"accountId":"<syd-account-id>"}}'

# 核对 payload 后才真正执行
python3 scripts/jira.py transition GRM-1947 --transition "Design Request" \
  --fields '{"assignee":{"accountId":"<syd-account-id>"}}' --execute
```

- `--transition` 可传 transition ID 或完整名称；同名动作产生歧义时必须改传 ID。
- `--fields` 只接受所选 transition screen 中存在的字段，字段格式遵循 Jira REST API 原生格式。
- 未显式传入的必填 screen 字段，默认从当前工单读取并原值回填；`reused_current_fields` 会列出实际回填项。用户不需要为已有的 Summary、Reporter、Priority 手工重建 JSON。
- Jira transition 元数据可能把服务端实际必填字段标成非必填。已从真实 400 错误或流程规范确认这类字段后，用 `--required-fields duedate,customfield_xxx` 增加客户端门禁；dry-run 会把缺值纳入 `missing_required_fields`，不要硬编码到 Skill。
- 如需禁止回填并检查 transition 的原始要求，加 `--no-fill-current-required`。dry-run 会输出 `missing_required_fields`；仍有缺项时拒绝 `--execute`。
- 执行后会回读工单状态，并在 `verification.matched` 中核对是否到达 transition 声明的目标状态。
- transition 会触发异步创建关联单时，可用 `--wait-linked-project` 保存执行前关联快照并等待唯一的新关联单；结合 `--expected-source-assignee`、`--expected-linked-assignee` 验证源单和新单归属。没有新单、同时出现多张候选单或任一后置条件不满足时返回退出码 4，而不是把 transition 的 HTTP 204 当作流程完成。
- 只有用户已经明确授权目标 Assignee 时才加 `--repair-linked-assignee`；它会在 Automation 创建新关联单但未正确指派时修复该新单，并再次回读验证。不得用该参数猜人或改动执行前已存在的关联单。
- 转给指定人员时不要猜 `accountId`；必须先从 Jira 已知数据或用户确认的账号映射中获得。

## NEVER 规则

- 不要直接调用 `ji/commands/*.py`；只能通过 `jira/scripts/jira.py` 入口。
- 不要把 token、Authorization header 或 `.env` 内容输出到命令行、日志或工单。
- 不要用 GET `/rest/api/3/search`；搜索必须用 POST `/rest/api/3/search/jql`。
- 不要猜 custom field ID；需要字段语义时读取 `references/field-mapping.md`。
- 不要把 search 结果里的相似单摘要当作根因；要读完整候选单后再判断。
- 不要用 `link_count` 推断关联单语义；批量分类时读取 `links[].project_key / issue_type / direction / relationship`。
- 不要对写操作省略 dry-run 检查；真正创建/更新必须显式 `--execute`。
- 不要下载非图片附件；附件下载只允许 image MIME 且必须 magic byte 校验通过。
- 不要上传非图片附件；附件上传只允许 PNG/JPEG/GIF/WebP，必须在 dry-run 与 execute 前通过 magic byte 和大小校验。
- 不要省略图片上传 dry-run；真正上传必须显式 `--execute`。
- 不要硬编码 transition ID；不同 workflow、当前状态和 Jira 配置下可用 ID 会变化，必须先动态查询。
- 不要猜或硬编码 Issue Link Type；`link` 每次从 Jira 读取实时类型并按名称精确匹配。
- 不要在存在 `missing_required_fields` 时执行 transition，也不要猜 assignee 的 `accountId`。
- 不要把 Jira 附件 URL 交给裸 `curl`；使用 `download-attachment`，避免凭据泄露和半下载文件。
- 不要把 automation rule URL 写进 `.env` 或 SKILL 常量里。rule UUID 易过期，每次调用前由用户/上下文显式提供。
- 不要把 ADF JSON 作为 Markdown 或 Automation `PARAGRAPH` 字符串传入；API 模式使用 `--description-adf-file`。
- 不要在 Markdown 转换失败后把原文降级发布；修正输入或改用完整 ADF。

## 错误处理

| 退出码 | 原因 | 处理 |
|---|---|---|
| 0 | 成功 | 解析 stdout JSON |
| 2 | 缺少必填配置、配置格式错误或参数非法 | 检查 `<SKILL_DIR>/.env`、参数和 JSON patch |
| 3 | 401/403 认证或权限错误 | 检查 Jira token、Intercom for Jira runtime JWT 和权限 |
| 4 | Jira/Intercom for Jira API、JQL、业务或附件校验错误 | 看 stderr 和 stdout `errors[]`/`warnings[]` |
| 5 | 请求超时 | 缩小范围或稍后重试 |

## 示例

```bash
# 读 Jira 工单；CS-* 会自动尝试读取 Intercom linked conversations
python3 scripts/jira.py read CS-43756

# 读工单并下载图片附件
python3 scripts/jira.py read CS-43756 --download-images --image-output-dir /tmp/cs-43756

# 跳过 Intercom
python3 scripts/jira.py read CS-43756 --include-intercom never

# 只测试 Intercom for Jira linked conversations
python3 scripts/jira.py intercom --issue CS-43756

# 已知 conversation id 时直读；传 issue 可在缺少 JWT 时走 Connect servlet context
python3 scripts/jira.py intercom --issue CS-43756 --conversation-id 123456

# 搜索历史相似单
python3 scripts/jira.py search 'project = CS AND summary ~ "deposit" ORDER BY created DESC' --limit 10

# 批量读取 Issue Type 与结构化关联单
python3 scripts/jira.py search 'project = CS AND created >= -7d ORDER BY created DESC' \
  --fields summary,status,created,issuetype,issuelinks,customfield_10089 --limit 100

# 下载单个图片附件
python3 scripts/jira.py download-attachment 'https://moego.atlassian.net/rest/api/3/attachment/content/12345'

# 上传单个图片附件：先 dry-run，再执行
python3 scripts/jira.py upload-attachment GRM-1947 ./screenshot.png
python3 scripts/jira.py upload-attachment GRM-1947 ./screenshot.png --execute

# Automation 创建：先 dry-run
python3 scripts/jira.py create --project CS --issue-type Bug --summary "Payment issue" --description "Customer reports payment failure"

# Automation 创建：确认后执行
python3 scripts/jira.py create --project CS --issue-type Bug --summary "Payment issue" --description "Customer reports payment failure" --execute

# Automation 创建：rule URL 必填，从 Jira UI 抓 fetch 拿
python3 scripts/jira.py create --project GRM --issue-type Task --summary "..." --description "..." --parent GRM-1729 \
  --automation-rule "https://moego.atlassian.net/gateway/api/automation/internal-api/jira/<workspace-uuid>/pro/rest/v1/rules/manual/invocation/<rule-uuid>"

# Automation 创建：手动指定 numeric issue id 跳过 GET 查询
python3 scripts/jira.py create --project GRM --issue-type Task --summary "..." --parent GRM-1729 \
  --objects-issue-id 128285 \
  --automation-rule "<rule-url>"

# Automation 创建：注入额外 form 字段（如 storyPoint=3）
python3 scripts/jira.py create --project GRM --issue-type Task --summary "..." --parent GRM-1729 \
  --automation-rule "<rule-url>" \
  --automation-object '{"userInputs":{"storyPoint":{"inputType":"NUMBER","value":3}}}'

# Automation 创建：完全自定义 envelope（适配字段格式不同的 rule）
python3 scripts/jira.py create --project GRM --issue-type Task --summary _ \
  --automation-rule "<rule-url>" --automation-body-file ./body.json

# Automation 创建：URL 不规范时手动指定 workspace UUID
python3 scripts/jira.py create --project GRM --issue-type Task --summary "..." --parent GRM-1729 \
  --automation-rule "<rule-url>" --workspace-uuid 8af4d020-016c-4a31-ab80-20d541f14545

# 标准 Jira API 创建（不依赖 automation rule，最直接）
python3 scripts/jira.py create-meta --project PR --issue-type-id 10889
python3 scripts/jira.py create --mode api --project ENG --issue-type Task --summary "Follow up CS issue"

# 标准 Jira API 创建：已有 ADF 时优先用专用入口
python3 scripts/jira.py create --mode api --project ENG --issue-type Task --summary "PRD" \
  --description-adf-file ./description.adf.json

# 标准 Jira API 创建：只有 Markdown 时由 Skill 转换
python3 scripts/jira.py create --mode api --project ENG --issue-type Task --summary "PRD" \
  --description-file ./prd.md

# 更新字段：先 dry-run
python3 scripts/jira.py update CS-43756 --patch '{"components":["Payments"],"issueCause":"Bug"}'

# 保留现有 PRD ADF，在头部元信息中幂等写入技术方案入口：先 dry-run，再执行
python3 scripts/jira.py update GRM-1947 --patch '{"descriptionAppendLinks":{"heading":"技术方案","position":"metadata","links":[{"text":"技术方案与估时（Approved V1）","url":"https://example.feishu.cn/wiki/xxx"}]}}'
python3 scripts/jira.py update GRM-1947 --patch '{"descriptionAppendLinks":{"heading":"技术方案","position":"metadata","links":[{"text":"技术方案与估时（Approved V1）","url":"https://example.feishu.cn/wiki/xxx"}]}}' --execute

# 更新字段：确认后执行
python3 scripts/jira.py update CS-43756 --patch '{"components":["Payments"],"issueCause":"Bug"}' --execute

# 关联两张工单：先 dry-run，再执行
python3 scripts/jira.py link PR-243 GRM-1947 --type "Relates"
python3 scripts/jira.py link PR-243 GRM-1947 --type "Relates" --execute

# 查询可用 transition；再按名称 dry-run
python3 scripts/jira.py transition GRM-1947
python3 scripts/jira.py transition GRM-1947 --transition "Design Request"

# 转给指定设计师并进入目标状态：核对 dry-run 后执行
python3 scripts/jira.py transition GRM-1947 --transition "Design Request" \
  --fields '{"assignee":{"accountId":"<syd-account-id>"}}' --execute

# 触发异步关联单并完成闭环验收；required-fields 用于覆盖 Jira 错误的非必填元数据
python3 scripts/jira.py transition GRM-1947 --transition "Design Request" \
  --fields '{"duedate":"2026-08-30","customfield_12242":{"id":"<sizing-option-id>"}}' \
  --required-fields duedate,customfield_12242 \
  --wait-linked-project DES \
  --expected-source-assignee '<source-account-id>' \
  --expected-linked-assignee '<designer-account-id>' \
  --repair-linked-assignee --execute
```

## References

| 文件 | 加载时机 |
|---|---|
| `references/field-mapping.md` | 读取/创建/更新/分析 CS 工单字段、需要 custom field ID 或字段语义时 |
| `references/jql-patterns.md` | 构造 JQL、搜索历史相似单、过滤 Squad/Component/Feature Domain 时 |
| `references/intercom-linked-conversations.md` | CS 工单未发现 Intercom linked conversations、需要调整 conversation ID 提取规则时 |
| `references/adf.md` | 创建工单 Description、选择 ADF/Markdown 输入、排查转换或链接校验错误时 |
