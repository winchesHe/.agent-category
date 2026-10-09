# CLI 与 Query v2 合同

## CLI 入口

优先使用已安装命令：

```bash
memory-manager <command>
```

在 memory-manager 仓库内且命令未安装时，先构建再使用仓库产物：

```bash
npm run build -w @memory-manager/core
node packages/core/dist/cli.js <command>
```

不要绕过 CLI 自行猜测 Session 格式。prepare 保存轻量选集，read/locate 由 CLI 重新读取最新权威源并重判原 Query 的内容谓词。

```bash
memory-manager context prepare --query-json '<json>'
memory-manager context prepare --query-file /absolute/path/query.json
memory-manager context status <run-id>
memory-manager context sessions <run-id> [--cursor <cursor>] [--limit <1-200>]
memory-manager context outcomes <run-id> [--status matched|not_matched|unknown] [--cursor <cursor>] [--limit <1-200>]
memory-manager context proofs <run-id> --session <session-id> [--cursor <cursor>] [--limit <1-200>]
memory-manager context locate <run-id> --session <session-id> --event <index>
memory-manager context read <run-id> --session <session-id> --part <n>
memory-manager context cleanup
memory-manager context close <run-id>
```

`--query-json` 与 `--query-file` 互斥。分页响应存在 `nextCursor` 时继续请求，直到该字段消失。

## Scan Gate 合同

`scan --all` 是候选索引刷新命令。以下 Query 在 prepare 前必须有一次成功且近期的 scan：

- 使用 `lastDays`、`since`/`until` 的“最近/最新/期间”检索；
- 省略 `where` 的全量检索；
- 按关键词、tool family、mention 或项目筛选候选；
- 用户要求“完整覆盖”“全部相关 Session”或 coverage 证明。

一次 retrieval run 只需 scan 一次，scan receipt 至少包含 `completedAt`、索引 revision/时间、扫描来源或候选数量、error 数量和 limitations。`context prepare` 应校验该 receipt；缺失或过期时返回结构化 `scan_required`，并在 `nextAction` 指向 `memory-manager scan --all`。scan 错误不得被解释为零命中。

已知 `sessionId`/event/part 的定向回读可以走显式 stale/degraded 路径，但输出必须带 `indexFreshness=stale` 和原因；该路径不能声称候选集合完整，也不能替代最新/全量 Query 的 scan。

scan receipt 只证明候选索引刷新，不证明正文已读取。`contentMode=live-source` 仍由 `context read`/`context locate` 负责；source revision 变化、selection change 和 scan 后索引变化必须分别披露。

## Query JSON v2

```json
{
  "version": 2,
  "time": { "lastDays": 30 },
  "scope": {
    "agents": ["claude", "codex", "copilot", "cursor", "opencode", "pi"],
    "projects": ["optional-project-slug"],
    "statuses": ["new", "updated", "unchanged"],
    "includeInternal": false
  },
  "where": {
    "all": [
      { "usedTool": { "families": ["computer-use", "chrome-use"] } },
      {
        "mentions": {
          "terms": ["联调"],
          "mode": "any",
          "fields": ["message"],
          "origins": ["human_user", "assistant_output"],
          "caseSensitive": false
        }
      }
    ]
  }
}
```

时间：`lastDays` 为正整数；也可使用 ISO 8601 `since` / `until`，但不能和 `lastDays` 混用。

范围：`scope` 可省略；Agent 只允许 `claude|codex|copilot|cursor|opencode|pi`。`includeInternal` 默认 false。未明确要求状态限制时，不要自行添加 `statuses`。

布尔谓词：

- `all`：任一子项未命中则未命中；没有未命中但存在 unknown 时为 unknown。
- `any`：任一子项命中即命中；无命中但存在 unknown 时为 unknown。
- `not`：保留 unknown，不把无法判断翻转成命中。
- 省略 `where`：时间/范围内所有可读 Session 都命中。

`usedTool` 表示结构化工具使用：

- `families`：常用值 `computer-use`、`chrome-use`。
- `names`：精确工具名。
- `operations`：如 `click`、`screenshot`、`navigate`。
- `provenance`：`direct|nested-ast|capability-derived`。
- 同一字段内 OR，不同字段间 AND。
- `nested-ast` 只认 AST 调用表达式；补丁、字符串、注释、fixture 不命中。疑似调用但代码无法解析时返回 unknown。

`mentions` 表示文本提及：

- `terms` 的 `mode` 为 `any|all`。
- `fields` 为 `message|tool_call_input|tool_result_output|title`，默认只有 `message`。
- `origins` 默认只有 `human_user|assistant_output`。
- 其他可显式指定的 origin：`tool_runtime|developer_instruction|host_context|skill_instruction|internal_job|historical_forward|unknown`。一般不要扩到注入来源。

## 配方一：computer-use / chrome-use / 联调复盘

用户问“找到最近 30 天 computer-use、chrome-use、联调相关的 session，并总结踩坑与快速联调经验”时使用：

```json
{
  "version": 2,
  "time": { "lastDays": 30 },
  "where": {
    "all": [
      {
        "any": [
          { "usedTool": { "families": ["computer-use", "chrome-use"] } },
          {
            "mentions": {
              "terms": ["computer-use", "chrome-use"],
              "mode": "any"
            }
          }
        ]
      },
      { "mentions": { "terms": ["联调"], "mode": "any" } }
    ]
  }
}
```

这个配方要求 Session 同时与目标工具和“联调”相关，避免把所有普通浏览器操作都召回；工具相关性可以来自真实调用，也可以来自真人/助手消息里的明确讨论。汇总时必须按 proof 区分：

- `tool_usage`：可以写“实际使用”。
- `mention`：只能写“讨论/提到”，需要从上下文确认是否真的操作过。

若用户只要真实调用，使用：

```json
{
  "version": 2,
  "time": { "lastDays": 30 },
  "where": {
    "usedTool": { "families": ["computer-use", "chrome-use"] }
  }
}
```

读取完成后重点关联同 `toolCallId` 的 call/result、相同步骤的重试、相同错误、阻塞任务继续的权限/环境/页面状态/工具限制，以及失败后的有效恢复动作。

## 配方二：最近 7 天全量总结

```json
{
  "version": 2,
  "time": { "lastDays": 7 }
}
```

不要添加 `where`。必须分页读完 `context sessions` 的所有 Session；对每个 Session 先实时读取 part 1 获得当前 `partCount`，再读完剩余 part。`coverage.unknown` 对应项通过 `context outcomes --status unknown` 读完并列入限制。

## Coverage、分页与完整读取

这里的“完整读取”是指读取当前权威源中的全部标准化语义事件，不是逐字节复制 Agent 的底层存储。消息、工具调用、
工具结果、媒体引用及必要 metadata 会保序提供；Codex Reader 以 `response_item` 为权威记录，去除 `event_msg`、
`turn_context` 等重复宿主视图，以及 token 计数、工具定义和 encrypted reasoning。每个保留事件都有
`sourceLocator`，需要审计时可回查原始源。

prepare/status 只返回有界摘要：

```json
{
  "runId": "...",
  "contentMode": "live-source",
  "contentStored": false,
  "coverage": {
    "candidates": 0,
    "inspected": 0,
    "matched": 0,
    "notMatched": 0,
    "unknown": 0,
    "unknownSource": 0,
    "unknownOrigin": 0,
    "unknownToolParse": 0,
    "changedDuringRun": 0
  },
  "sessionCount": 0,
  "limitations": []
}
```

`contentStored` 必须为 false；run 目录只允许有轻量 owner/manifest，不应出现 `sessions/` 或正文文件。

核对：

```text
candidates = inspected + unknown
inspected = matched + notMatched
unknown = unknownSource + unknownOrigin + unknownToolParse
```

`context sessions`、`context outcomes` 和 `context proofs` 返回：

```json
{
  "total": 1,
  "returned": 1,
  "cursor": "0",
  "nextCursor": "50",
  "items": []
}
```

prepare manifest 不含正文，`context sessions` 也不返回可能过期的 `partCount`。`nextCursor` 缺失才表示清单分页结束。维护三个账本：

```text
session_id | source_revision | expected_parts | read_parts | complete
event_hash | expected_segments | read_segments | complete
session_id | prepare_selection | current_selection | changed
```

每个 `context read` 都重新读取最新 Session，并返回 `readAt`、`selectionStatus`、`selectionChanged`、
`sourceChangedSincePrepare`、当前 `sourceRevision` 和 `partCount`。普通事件直接出现在 `events`；超大事件以
`event_segment` 跨 part 连续出现，按 `segmentIndex` 收齐，不能把单个 segment 当成完整 event。
若跨 part 的 source revision 改变，从 part 1 重读一次；再次变化则停止“完整”声明并报告未读范围。

`context sessions` 为防止 proof 数量导致输出截断，只返回准备时事件数、`proofCount`、按 kind 聚合的
`proofKinds` 和 `toolFamilies`；完整 proof 必须通过 `context proofs` 分页读取。`context locate` 实时回源，
优先按 proof 的 `sourceLocator` 映射到当前 `firstPart..lastPart`，并返回当前 selection/source change 状态。

联调复盘允许只读取全部相关 proof 的合并邻域，但必须称为“证据上下文”；最近 7 天全量总结或用户明确要求完整 Session 时，仍须读取所有 part。

## 错误处理

- scan 有错误：记录扫描不完整，不声称候选集合完整。
- `unknownSource>0`：来源缺失、损坏或不支持；读取 unknown outcome 的错误码。
- `unknownOrigin>0`：关键词只出现在无法判定来源的消息；不当作命中或未命中。
- `unknownToolParse>0`：疑似嵌套工具调用无法解析；不当作未命中。
- read 失败：重试一次；仍失败则记录 Session/part，最终报告未读范围。
- prepare 的 `changedDuringRun>0`：只表示初次判定期间源变化；read/locate 仍使用最新源并重新判断内容谓词。
- `selectionChanged=true`：该 Session 当前内容已不符合原 Query 的内容谓词，不继续作为相关证据；必要时重新 prepare。
- `sourceChangedSincePrepare=true`：这是允许的最新读取语义；多 part 时记录 revision，变化后按上文重读一次。
- 输出过大：继续逐 part/逐页读取；禁止 `head`、抽样或批量拼接截断。
- 任意失败后仍执行 `context close` 删除轻量 manifest；close 失败时报告 run id，过期项可用 `context cleanup` 清理。
