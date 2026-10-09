# Sentry Query Syntax 速查

## Issue search

`list-issues` 查询 grouped issues，适合找“有哪些问题”。

```bash
uv run "$SKILL_DIR/scripts/sentry.py" list-issues \
  --query "is:unresolved lastSeen:-24h" \
  --sort date \
  --limit 20
```

常见过滤：

| 需求 | Query | Sort |
|---|---|---|
| unresolved issues | `is:unresolved` | `date` |
| 最近活跃 | `lastSeen:-24h` | `date` |
| 新出现 | `firstSeen:-7d` | `new` |
| 高影响 | `is:unresolved` | `user` |
| 高频噪音 | `is:unresolved` | `freq` |
| 指定环境 | `environment:production` | `date` |
| 指定版本 | `release:<version>` | `date` |
| 指定用户 | `user.email:<email>` | `date` |

Sort 必须放在 `--sort`，不要写到 `--query`。

## Issue event search

`list-issue-events` 查询单个 issue 内的原始 events，适合找样本和对比条件。

```bash
uv run "$SKILL_DIR/scripts/sentry.py" list-issue-events \
  --url "<issue-url>" \
  --query "environment:production release:1.2.3" \
  --sort -timestamp \
  --stats-period 14d
```

注意：

- 不要在 query 中加 `issue:`，endpoint 已经限定到单个 issue。
- 默认 sort 是 `-timestamp`，即最新 event 优先。
- 常见条件：`environment:<env>`、`release:<version>`、`user.email:<email>`、`trace:<trace-id>`、`url:"*/path/*"`、`transaction:<name>`。

## Tag values

`tag-values` 用于判断影响面和集中度。

```bash
uv run "$SKILL_DIR/scripts/sentry.py" tag-values --url "<issue-url>" --tag release
uv run "$SKILL_DIR/scripts/sentry.py" tag-values --url "<issue-url>" --tag browser.name
uv run "$SKILL_DIR/scripts/sentry.py" tag-values --url "<issue-url>" --tag os.name
```

常用 tag：

| Tag | 含义 |
|---|---|
| `release` | App/Web 版本 |
| `environment` | production/staging/development |
| `os.name` | 操作系统 |
| `browser.name` | 浏览器 |
| `device` / `device.family` | 设备 |
| `user` / `user.email` | 用户 |
| `url` | 请求或页面 URL |
| `transaction` | 页面、路由或事务名 |
| `trace` | 分布式 trace id |

Tag key 区分大小写。少见字段不要猜，先看 `fetch-event` 输出的 `event.tags` 或用 `tag-values` 验证。

## 常见陷阱

- Sentry query syntax 不是 SQL；不要写 `IS NULL`、`now()`、`today()` 等 SQL 表达式。
- 带空格的值需要加引号，如 `environment:"dev server"`。
- 字符串通配用 `*`，如 `url:"*/checkout/*"`。
- `level:error` 是错误级别，不等于“严重/高影响”；高影响优先 `--sort user` 或 `userCount`。
- event count 受采样和循环崩溃影响；影响面优先看 `userCount` 和 tag 分布。
- `firstSeen` 表示首次出现，适合“新问题”；`lastSeen` 表示最近活跃，适合“最近发生过”。
