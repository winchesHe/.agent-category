# MIS 操作参考

## 鉴权

MIS API 不是匿名接口。鉴权按以下顺序选择：

1. Keychain 有当前环境的有效 MIS Session：直接复用并调用 `GetAccountInfo` 验证。
2. 需要重新鉴权：首选 `.env` 的 `MOE_MIS_SSO_USERNAME` / `MOE_MIS_SSO_PASSWORD`，完成 CAS/OIDC 和 MIS Login。
3. SSO 未配置或协议不受支持：使用 Chrome control 操作当前 Chrome 的 MIS 页面，不读取任何 Cookie。
4. Chrome control 不可用：取得用户同意后显式使用 `--auth-method isolated`。

SSO 用户名或密码被明确拒绝时必须停止，不得静默降级。隔离 Chrome 缺少用户日常 Profile 的 Google 登录态、密码和设备信任，因此只能作为最后 fallback。

Chrome DevTools Protocol 只绑定 `127.0.0.1`，且只读取 MIS origin 的 Cookie。CLI 动态识别：

- 可选 `MGDID`
- `MGSID-MIS` 或名称以 `MGSID-MIS-` 开头的实际 session Cookie

Keychain service 为 `moego-internal-ops`，username 为 `mis-<env>`。value 是上述 Cookie 的 JSON，禁止导出。

## 命令

`moe-acceptance` 通过 `--browser-session/--browser-namespace` 使用当前已确认的浏览器；调用方沿用相同的实际 socket 环境与有效启动配置。`--account-ref aid:<id>` 只在进程内解析唯一邮箱，输出和 receipt 不保存邮箱。

```bash
uv run --script scripts/moe_mis.py --env t2 auth status
uv run --script scripts/moe_mis.py --env t2 auth login --force
uv run --script scripts/moe_mis.py --env t2 auth logout

uv run --script scripts/moe_mis.py --env t2 profile \
  --type email user@example.com

uv run --script scripts/moe_mis.py --env t2 impersonate \
  --email user@example.com --max-age d1 --source business

uv run --script scripts/moe_mis.py --env t2 impersonate \
  --account-ref aid:921015 --source business \
  --browser-session <已确认session> --browser-namespace <已确认namespace>

# 在已有登录标签页保留 companyID/redirect 续登（production 内部测试账号可无人值守）
uv run --script scripts/moe_mis.py --env production impersonate \
  --account-ref aid:<id> --source business --max-age h1 --unattended \
  --browser-session <session> --browser-namespace <namespace> \
  --continue-login-target <tab-id> --allowed-redirect-host moego.canny.io \
  --expected-final-path /feature-request

# 临时密码：按 MIS「Copy as password」规则生成，只复制到剪贴板
uv run --script scripts/moe_mis.py --env t2 impersonate \
  --email user@example.com --max-age d1 --source business --as-password

uv run --script scripts/moe_mis.py --env t2 ob-impersonate status
```

SSO 与隔离登录：

```bash
uv run --script scripts/moe_mis.py \
  --env production --auth-method sso auth login --force

uv run --script scripts/moe_mis.py \
  --env production --auth-method isolated auth login --force
```

`auto` 是默认值：尝试 SSO，但 SSO 不可用时不会自动启动隔离 Chrome，因为中间必须先由 skill 检查 Chrome control。

Profile type：

- `email` / `account-email`
- `aid` / `account-id`
- `bid` / `business-id`
- `cid` / `company-id`
- `sid` / `staff-id`

有效期：`h1`、`h2`、`d1`、`d7`、`d15`，默认 `d1`。来源：`business`、`customer`。

## Token 交付

- 默认：在浏览器打开携带 MIS 登录凭据的目标链接，发起目标账号免输入登录；stdout 不含 URL query 或 token。
- `--raw-token`：只复制到本机剪贴板，stdout 仅返回交付元数据。
- `--as-password`：按 MIS 页面当前的 `tokenPasswordPrefix + token` 规则生成临时登录密码并复制到本机剪贴板；stdout 不显示密码原文。成功输出必须包含 `approved: true`、`copied: true` 和 `delivery: "password"`。`max-age` 与 MIS 页面保持同一组可选值。
- `--show-token`：在 JSON 中显示 token 原文。只有用户明确要求看到原文时才能使用，最终回复不得复述。
- `--continue-login-target`：在现有 `go.* /sign_in?companyID=...&redirect=...` 标签页中续登。token 通过 `agent-browser eval --stdin` 进入浏览器，不出现在命令行参数、stdout 或文件。
- Lark 状态不是 `APPROVED` 时，不复制 token，也不打开页面。

使用临时密码登录时，Email 使用命令中的同一目标邮箱，Password 直接粘贴剪贴板内容。Business 侧使用 `source=business`，Customer 侧使用 `source=customer`；`--raw-token` 不能作为密码。登录失败时核对环境、邮箱和 source，不得尝试自行拼接或改用 raw token。

Web 已有正确账号与环境的有效登录态时直接复用；需要登录时使用 `impersonate`，等价于 MIS 页面 `Login`，通过携带 MIS 凭据的链接发起目标账号免输入登录。已有隔离浏览器（包括 `moe-acceptance` 与 Canny 会话）明确传 session/namespace，并沿用其实际 socket 和启动配置；没有指定浏览器时在系统默认浏览器打开。打开后核对实际登录账号与目标环境。

MoeGo iOS App 已支持 `exp+moego-business-2://?action=login&token=<MIS原始token>`。已有正确环境及安全原生交付能力时，可用 `impersonate --source business --raw-token` 交付凭据，由交接进程从剪贴板读取到内存、编码并打开深链，无需填写邮箱密码。当前 MIS CLI 没有指定 Simulator 的参数，不把默认 Web 跳转等同原生交付。凭据及完整 URL 不进入命令参数、工具返回、Flow、文件或日志；不使用 `--show-token`，也不提取 App 内 token。需要表单登录或无法安全交接时再使用 `--as-password`。

原生交付、Expo 项目加载、系统确认和登录后身份核对，按 [iOS 登录指引](../../moe-acceptance/references/ios-simulator.md#携带参数的免输入登录) 执行；重新发起登录时通过 MIS 获取新凭据。

当前 Chrome UI 路径不需要提取 token：在页面审批通过后直接点击 `Login`，并验证新标签页的 host 与目标账号。不得检查 Cookie、localStorage 或包含 token 的完整 URL。

## Online Booking impersonate

`ob-impersonate` 对应 MIS 页面独立的 `Impersonate online booking user`，不是账号 token impersonate：

```bash
# read-only
uv run --script scripts/moe_mis.py --env t2 ob-impersonate status

# plan
uv run --script scripts/moe_mis.py --env t2 ob-impersonate start

# apply（hash 必须来自刚才的 plan；先满足下文真实注入限制）
uv run --script scripts/moe_mis.py --env t2 \
  ob-impersonate start --expected-state-hash "<hash>" --apply \
  --browser-session <已确认session> --browser-namespace <已确认namespace>

# cleanup 同样先 plan，再 apply
uv run --script scripts/moe_mis.py --env t2 ob-impersonate stop
uv run --script scripts/moe_mis.py --env t2 \
  ob-impersonate stop --expected-state-hash "<hash>" --apply \
  --browser-session <同批session> --browser-namespace <同批namespace>

# 中断恢复
uv run --script scripts/moe_mis.py --env t2 \
  ob-impersonate reconcile \
  --browser-session <同批session> --browser-namespace <同批namespace>
```

- `status` 调用 `CheckSession`，复用 Keychain 中独立保存的 OB Session，并只输出脱敏 session 摘要与恢复元数据；排除 `sessionData`、token、Cookie、认证 URL 与 Customer 隐私数据。
- `start/stop/reconcile` 默认只返回 plan。`--apply` 还必须提供 plan 的 `expectedStateHash`，写前重读、写后再次回读。
- 验收浏览器在 `start --apply` 时显式传入本批 session/namespace，并沿用其实际 socket 与启动配置。注入或远端验证失败自动补偿 stop；补偿失败时保留 `cleanup-required` journal。
- 远端已经 active 时，每个新浏览器仍必须各自执行一次 `start` plan → 同一目标/同一 `expectedStateHash` 的 `start --apply`；此时远端变化是 noop，但浏览器认证交付不是 noop。只运行 plan 或用 `reconcile` plan 代替，不会完成正常浏览器交付。
- `stop` 在远端 inactive 后清理浏览器 Cookie 与 Keychain；中断后先 `status`，`recoveryRequired=true` 时用 `reconcile` 恢复 active binding 或清理 inactive journal。
- `start` 写后必须是 active，且 main session 的 impersonator 与当前 MIS 账号一致；`stop` 写后必须 inactive。
- `stop` 写后确认 inactive 才清理本地 OB Keychain 记录；失败时保留记录以便重试清理。
- 真实联调必须把 start 和 finally stop 作为同一授权批次；production 需要用户明确确认具体 plan。
- 自动冒烟只运行 `status`，不得自动 apply。

OBC 身份准备按 [T2 OBC 身份登录与恢复](../../moe-acceptance/references/t2-obc.md#mis-身份登录与恢复) 判断实际登录缺口并继续验收。

## 环境

| env | MIS | business | customer |
|---|---|---|---|
| `t2` | `mis.t2.moego.dev` | `go.t2.moego.dev` | `my.t2.moego.dev` |
| `s1` | `mis.s1.moego.dev` | `go.s1.moego.dev` | `my.s1.moego.dev` |
| `production` | `mis.moego.pet` | `go.moego.pet` | `my.moego.pet` |

production impersonate 默认必须先取得用户明确授权；目标账号为 `@moego.pet` 内部测试账号时可使用 `--unattended` 自动执行。CLI 会在签发 token 前拒绝其他域名账号的无人值守请求。

## Metadata

Metadata 复用同一 MIS Session，不需要单独鉴权：

```bash
# 分组、Key
uv run --script scripts/moe_mis.py --env production metadata groups
uv run --script scripts/moe_mis.py --env production metadata list \
  --group BD --owner-type staff --name-like task --page 1 --page-size 20
uv run --script scripts/moe_mis.py --env production metadata get \
  --id <key-id>

# Value
uv run --script scripts/moe_mis.py --env production metadata values \
  --key-id <key-id> --owner-id <owner-id> --page-size 100
uv run --script scripts/moe_mis.py --env production metadata get-value \
  --key-id <key-id> --owner-id <owner-id>
```

Owner type 短名：

- `system`
- `company`
- `business`
- `staff`
- `account`
- `enterprise`

Permission level 短名：

- `owner`
- `nobody`
- `company-any-business-owner`
- `company-any-staff`
- `business-any-staff`

创建、更新、删除 Key 和设置 Value 默认只返回 plan，不发送写请求：

```bash
uv run --script scripts/moe_mis.py --env production metadata create \
  --name <name> --description "<description>" --owner-type company \
  --default-value "false" --permission-level owner --group <group>

uv run --script scripts/moe_mis.py --env production metadata update \
  --id <key-id> --description "<description>"

uv run --script scripts/moe_mis.py --env production metadata delete \
  --id <key-id>

uv run --script scripts/moe_mis.py --env production metadata set-value \
  --key-id <key-id> --owner-id <owner-id> --value "true"
```

执行规则：

- 先检查 plan 的 before/after、目标 Key/owner、权限和清理条件。
- 上述信息全部确定时可直接添加 `--apply`；存在不确定项时先向用户确认。
- update/delete 使用 plan 返回的 `expectedUpdatedAt` 或 `expectedStateHash`。production 当前可能不返回 `updatedAt`，此时使用 state hash。
- delete 还必须传 `--confirm <key-name>`。
- set-value 必须传 plan 返回的 `--expected-state-hash`。
- `--owner-id` 可重复，实现同一值的批量设置。
- update 用 `--clear-start-at` / `--clear-end-at` 清除生效时间边界。
- 真实自动冒烟只运行 groups/list/get/values/get-value 或 mutation plan，不运行 `--apply`。
