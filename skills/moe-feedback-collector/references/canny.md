# Canny 采集协议

## 已验证入口

- Board：`https://moego.canny.io/feature-request`
- List：同源 `POST /api/posts/get`
- Detail：`/feature-request/p/<urlName>`
- Comments：详情页 `window.__data.postsActivity[postId].comments`

## 鉴权与 session 决策链

每次运行只使用一个由脚本生成的临时 `agent-browser` namespace/session；禁止使用默认
浏览器 Profile，禁止复制 cookie/token，禁止把登录过程拆到另一个标签页或另一个 session。

1. 打开 Board：`https://moego.canny.io/feature-request`。
2. 在 Board 页面上下文读取 `window.__data.cookies`，用页面内同源
   `POST /api/posts/get` 做最小 probe。
3. probe 成功（HTTP 成功且返回 `result.posts` 数组）时，session 已可用，直接采集；
   不需要 `--account-ref`。
4. probe 返回未授权时，从当前页面 DOM 读取并校验页面自己的 `https://go.moego.pet/sign_in`
   链接；不要猜 URL，也不要在 Python 中请求鉴权接口。
5. 只有第 3 步失败时才要求 `--account-ref aid:<id>`。调用 `moe-mis` production、
   business、`--unattended`，并传入同一 browser session/namespace、精确 active tab、
   redirect host `moego.canny.io` 和最终 path `/feature-request`。MIS 在进程内完成续登，
   Collector 不接触 token。
6. 续登后回到原 Board 标签页，重复第 2 步 probe；必须确认授权后才开始 New/Top、
   详情和评论采集。二次 probe 失败时停止并报告认证失败，不能把来源记为 0。
7. 无论成功或失败，关闭本次精确 session；输出只保留脱敏 manifest/evidence。

## List 请求

请求体从页面 `window.__data.cookies` 读取 Canny 自有运行字段，并补充：

```json
{
  "boardURLNames": ["feature-request"],
  "currentBoard": "feature-request",
  "pages": 1,
  "sort": "newest"
}
```

排序映射：New=`newest`，Top=`score`。`pages=N` 返回前 N×10 条累计结果。

## 基线与增量口径

- 每次 collect 都绑定一个明确的 7 天自然周：默认上一个完整自然周，也可同时传
  `--period-start / --period-end`。该周期写入 manifest；publish 和 dashboard 必须与其
  完全一致，不能把旧 run 的变化行重新解释为另一周的数据。
- 首次运行：New 排序扫描到末页，建立完整当前基线；不能把历史 Post 当前状态解释成过去一周发生的变化。
- 新帖：基线建立后，New 排序至少扫描到目标周期开始日之前，不能用上次
  `lastCreated` 提前截断，否则会漏掉上次 checkpoint 已经见过、但创建时间仍属于本期的 Post。
- 老帖：Top 排序扫描到尾部 score 不大于阈值。
- 快照：`score/commentCount/status/title/detailsHash`。
- 事件 ID：`sha256(sourceId + snapshot)`，重跑同一状态不会产生重复事件。
- 周报源数据：无论首次或增量运行，都只展示 `createdAt` 按 Asia/Shanghai 落在
  manifest 周期内的 Post。全量 evidence 与 checkpoint 仍保存在本地，用于审计和状态比较。
  Canny 没有可靠 `updatedAt`，因此旧 Post 的 Vote、评论、状态或正文快照变化不能归因到
  某个自然周，不进入周报源数据。
- 审计计数：`checkpointDiscoveredCount` 表示本次首次进入 checkpoint 的 Post 数量，
  `snapshotChangedCount` 表示两次采集间快照变化数量；两者都不等同于本周新增。
- Quick Win 初筛：Vote ≥ 3、Vote 增长 ≥ 5 或评论增长 ≥ 3；AI 再判断诉求是否明确、范围是否集中、预估改动是否较小。
- 首期不读取评论正文；智能值守不在首期范围。
- Probe：New/Top 各只读第一页，保留本次实际扫描到的全部 Post；它用于接口探测，不推进正式基线。

### Agent 运行时判定

```text
启动临时 session
  → probe Board 同源接口
      ├─ authorized=true → 直接 collect（无需 account-ref）
      └─ 未授权
          ├─ 有 account-ref → 读取页面登录链接 → MIS 原标签页续登 → 二次 probe → collect
          └─ 无 account-ref → 报告“需要 account-ref 才能续登”，不得声称 Canny 为 0
```

## 安全

- 页面运行字段只在页面上下文参与 fetch，不返回 Python。
- 输出允许包含反馈正文和评论，但敏感 key（token、cookie、authorization、secret、password）会递归脱敏。
- 每次运行无论成功或失败都关闭精确 session。
