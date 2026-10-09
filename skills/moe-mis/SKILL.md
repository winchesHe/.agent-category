---
name: moe-mis
description: >-
  通过 scripts/moe_mis.py 操作 MoeGo MIS：登录状态与 SSO、账号 Profile、账号 impersonate、临时登录密码、Online Booking impersonate session，以及 Metadata Key/Value 查询和受控写入。触发关键词：MIS、账号查询、impersonate、临时密码、OB session、Metadata。不触发：Grey 规则和服务分支管理。
---

# MoeGo MIS

## 前置条件

- Python 3.9+，使用入口脚本的 PEP 723 依赖通过 `uv run --script` 执行。
- 认证配置写入 skill 根目录或当前目录的 `.env`；进程环境变量优先。
- MIS 与 OB Cookie 只存 macOS Keychain，沿用历史 service `moego-internal-ops`，不得写入文件、日志或回复。
- 配置使用 `MOE_MIS_*` 环境变量。

## 脚本位置

```bash
uv run --script scripts/moe_mis.py <全局参数> <subcommand>
```

不得安装或调用 `moego-mis-cli`，也不要直接调用 `mmis` 内部模块。

## 子命令速查表

| 子命令 | 作用 | 必填 flag / 参数 |
|---|---|---|
| `auth status/login/logout` | 检查、建立或删除 MIS Session | `login` 可选 `--force` |
| `profile` | 按账号、business、company、staff 标识查询 | `--type`、`value` |
| `impersonate` | 获取登录凭据并安全交付到浏览器或剪贴板 | `--email` 或 `--account-ref` |
| `ob-impersonate status/start/stop/reconcile` | 管理 OB 测试 session | apply 时使用 plan hash |
| `metadata groups/list/get/values/get-value` | 查询 Metadata | 按命令传 id、owner 等参数 |
| `metadata create/update/delete/set-value` | plan/apply 写入 Metadata | apply 时传 snapshot/hash；delete 精确确认名称 |

## 通用 flag

- `--env t2|s1|production`：MIS 环境，默认 `t2`。
- `--format json|human|summary`：默认 `json`；JSON 只写 stdout，其余信息写 stderr。
- `--force-login`：忽略缓存 Session。
- `--auth-method auto|sso|isolated`：默认 `auto`。

## 场景决策树

1. 登录状态、账号、账号登录或临时密码：使用 `auth`、`profile`、`impersonate`。
2. Online Booking 免验证码测试会话：使用 `ob-impersonate`，不要与账号 impersonate 混用。
3. Metadata：先用只读命令定位 Key/Value；写入先生成 plan，再按确定性规则决定 apply。
4. 参数、字段或资源 ID 不确定：先读 [references/mis.md](references/mis.md) 并执行对应 `--help`，禁止猜测。

## 领域知识

- MoeGo iOS App 支持登录深链：已有正确环境及安全原生交付通道时，使用 `impersonate --source business --raw-token` 获取凭据并交接给 App；需要表单登录或无法安全交接时使用 `--as-password`。交付方式与冷启动条件见 [Token 交付](references/mis.md#token-交付)。
- production 无人值守账号 impersonate 只允许 `@moego.pet` 内部测试账号。
- `--raw-token` 不是临时密码；只有用户明确要求查看原文时才使用 `--show-token`。
- OB 和 Metadata 写操作保留 plan/apply、并发快照、精确确认和写后回读。
- `moe-acceptance` 使用已确认的 `--browser-session/--browser-namespace` 指向当前浏览器，保持实际 socket 与启动配置一致。OBC 身份登录与恢复遵循其平台指引。

## NEVER 规则

- 不输出、记录或持久化 token、密码、Cookie、authorization；敏感值只通过 Keychain、目标浏览器或剪贴板交付。
- 不绕过 `expectedStateHash` / `expectedUpdatedAt`，否则并发变化可能被覆盖。
- 不用 production 真实 mutation 做自动冒烟测试。
- 不在目标、范围、差异、权限或清理状态不确定时 apply；先向用户确认。全部确定时可直接 apply，无需额外门禁。
- 不把新验收任务绑定到默认或上次使用的浏览器；明确传入本次 session/namespace，核对目标环境，并沿用有效 socket/启动配置。
- OB 联调必须在 `finally` stop 并回读 inactive；出现 `recoveryRequired` 时先 reconcile。

## 错误处理

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 参数、配置或本地依赖错误 |
| 3 | 登录、认证或权限错误 |
| 4 | API 或业务错误 |
| 5 | HTTP、CDP 或浏览器超时 |

## 示例

```bash
uv run --script scripts/moe_mis.py --env t2 auth status
uv run --script scripts/moe_mis.py --env t2 auth login --force
uv run --script scripts/moe_mis.py --env t2 auth logout
uv run --script scripts/moe_mis.py --env t2 profile --type email user@example.com
uv run --script scripts/moe_mis.py --env t2 impersonate --account-ref aid:921015 --source business
uv run --script scripts/moe_mis.py --env t2 impersonate --email user@example.com --as-password
uv run --script scripts/moe_mis.py --env t2 ob-impersonate status
uv run --script scripts/moe_mis.py --env t2 ob-impersonate start
uv run --script scripts/moe_mis.py --env t2 ob-impersonate stop
uv run --script scripts/moe_mis.py --env t2 ob-impersonate reconcile --browser-session <已确认session> --browser-namespace <已确认namespace>
uv run --script scripts/moe_mis.py --env production metadata groups
uv run --script scripts/moe_mis.py --env production metadata list --group BD --owner-type staff
uv run --script scripts/moe_mis.py --env production metadata get --id <key-id>
uv run --script scripts/moe_mis.py --env production metadata values --key-id <key-id> --owner-id <owner-id>
uv run --script scripts/moe_mis.py --env production metadata get-value --key-id <key-id> --owner-id <owner-id>
uv run --script scripts/moe_mis.py --env production metadata create --group BD --name <name> --description <description> --owner-type staff --default-value <value> --permission-level owner
uv run --script scripts/moe_mis.py --env production metadata update --id <key-id> --description <description>
uv run --script scripts/moe_mis.py --env production metadata delete --id <key-id> --confirm <key-name>
uv run --script scripts/moe_mis.py --env production metadata set-value --key-id <key-id> --owner-id <owner-id> --value <value>
```

## References

- [references/mis.md](references/mis.md)：执行 MIS、OB 或 Metadata 命令前按对应章节加载；包括浏览器登录、原生深链/临时密码交付，以及参数、状态和失败处理。
