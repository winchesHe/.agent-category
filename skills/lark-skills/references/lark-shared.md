# lark-shared：身份 / 错误 / 协议（仅出错或不确定时查）

> ⚠️ **本 skill 假设 `lark-cli` 已安装、`config init` 已完成、所需 scope 的 `auth login` 已经做过**。本 reference 不再引导认证流程；只列遇到错误或不确定身份时如何处理。

## 1. 身份模型（`--as user/bot`）

| 身份 | 标志 | token | 适用 |
|---|---|---|---|
| **user** | `--as user` | user_access_token | 用户个人资源（个人日历 / 邮箱 / 个人云空间 / 个人任务） |
| **bot** | `--as bot` | tenant_access_token | 应用级操作；以应用名义发消息 / 创建文档（资源归 bot） |

输出会带 `[identity: bot]` 或 `[identity: user]`，**先确认身份是否与目标资源匹配**再操作。

### 关键差异

- **Bot 看不到用户资源**——`--as bot` 查日程返回 bot 自己的（多半空的）日历。
- **Bot 不能"代表用户"操作**——bot 发的消息以 app 名义，bot 创建的文档归属 bot。
- **bot 仅需后台 scope，不需要 auth login**；user 需要后台 scope **+** 用户已通过 `auth login --scope <...>` 授权（两层都满足）。

## 2. Permission denied 错误处理

错误响应通常含：

```json
{
  "ok": false,
  "error": {
    "type": "permission_denied",
    "permission_violations": ["calendar:calendar:readonly"],
    "console_url": "https://open.feishu.cn/app/<id>/auth?scope=...",
    "hint": "..."
  }
}
```

按当前身份分流：

### Bot 身份（`--as bot`）

把 `console_url` 提供给用户，引导其去飞书开发者后台开通缺失 scope。**禁止**对 bot 执行 `auth login`。

### User 身份（`--as user`）

```bash
# 推荐：按缺失 scope 精确授权（增量）
lark-cli auth login --scope "<missing_scope_from_permission_violations>"

# 或按业务域整体授权
lark-cli auth login --domain <domain>
```

> 关键：先看 `permission_violations` 的具体 scope 名，**不要先猜或盲目加 `--domain`**。

## 3. 高风险写操作（`exit 10` 协议）

lark-cli 对 `risk: "high-risk-write"` 的操作（如 `drive +delete`、批量改）有强制确认门禁。
不带 `--yes` 调用时退出码 `10`，stderr 返回结构化 envelope：

```json
{
  "ok": false,
  "error": {
    "type": "confirmation_required",
    "message": "drive +delete requires confirmation",
    "hint": "add --yes to confirm",
    "risk": {
      "level": "high-risk-write",
      "action": "drive +delete"
    }
  }
}
```

**正确处理流程**（按顺序）：

1. **识别**：exit code = `10` **且** stderr JSON `error.type == "confirmation_required"`。
2. **核对动作**：读取 `error.risk.action` 与关键参数，确认与原请求一致。
3. **核对已有授权**：按主文档“调用约定”确认相同对象、内容与操作是否已获明确授权；已充分授权不重复询问。未覆盖时展示具体动作与关键参数，等待明确同意。
4. **授权充分** → 在**原始 argv 末尾追加 `--yes`** 后重试。
5. **拒绝** → 终止，不要改写参数 / 试图绕过。

### 绝对禁止

- ❌ 未核对动作与授权就因 exit 10 自动追加 `--yes` 重试。
- ❌ 把 `confirmation_required` 当普通错误（网络 / 权限）处理。
- ❌ 在用户没明确同意前就追加 `--yes` 重试。
- ❌ 用 `sh -c` 拼接命令重试——必须 `exec.Command(argv...)` 数组形式。

### 提前预审

```bash
lark-cli drive +delete --token <file_token> --dry-run
```

`--dry-run` **不触发**门禁，会打印完整请求详情（URL / body / params）。

### 如何识别一条命令是否高风险

- **shortcut**：`lark-cli <service> +<cmd> --help` 顶部显示 `Risk: high-risk-write`
- **service 命令**：`lark-cli schema <service>.<resource>.<method> --format json` 返回值里 `"risk": "high-risk-write"`

## 4. 输出契约

| 流 | 内容 | AI 处理 |
|---|---|---|
| stdout | JSON envelope（数据） | 解析为结构化数据 |
| stderr | 进度、warning、hint、ready-marker，失败时可能含错误 envelope | 区分日志与结构化错误，结合退出码处理 |
| exit code | 0 成功；非 0 见错误 envelope | 与 stderr JSON 联合判断 |

**不要**：

- 用 grep / sed 抓 stdout 想"提取人类信息"——stdout 是 JSON。
- 把 stderr 当作错误流——很多正常进度信息也走 stderr。

## 5. 更新提示

输出 JSON 可能含 `_notice.update`：

```json
{"ok": true, "_notice": {"update": {"message": "A newer version 1.x.x is available", "command": "npm update -g @larksuite/cli && npx skills add larksuite/cli -g -y"}}}
```

**规则**：

1. 看到 `_notice.update`，**完成当前任务后**主动告知用户当前版本与最新版本号。
2. 提议执行更新（CLI 与 skills 必须同时更新）：
   ```bash
   npm update -g @larksuite/cli && npx skills add larksuite/cli -g -y
   ```
3. 提醒用户：**退出并重新打开 AI Agent** 加载新 skills。
4. 不要静默忽略；即使当前任务与更新无关也要补充告知。

## 6. 常见错误速查

| 现象 | 处理 |
|---|---|
| `[identity: bot]` 但用户期望访问个人资源 | 加 `--as user` 重跑（已授权过对应 scope 即可） |
| `permission_denied` 含 `permission_violations` | 见 §2：bot 走 console_url、user 走 `auth login --scope` |
| exit 10 + `confirmation_required` | 见 §3：用户同意后追加 `--yes` 重试 |
| `_notice.update` 出现 | 见 §5：完成任务后告知用户 |

## 7. 安全规则

- ❌ 禁止把 `appSecret` / `accessToken` 输出到终端明文。
- 写入授权统一遵循主文档“调用约定”；CLI 门禁按本文件 §3 处理。
- ✅ 危险请求用 `--dry-run` 预览。

## 在 lark-skills 内的引用方式

其它 reference 中**不要**复制本文件的鉴权 / 身份处理。如需提示，写一行链接：

> Permission denied 处理见 [`lark-shared.md`](./lark-shared.md) §2。
> exit 10 高风险确认协议见 [`lark-shared.md`](./lark-shared.md) §3。

## 溯源

- 简化自 lark-cli 仓库 `skills/lark-shared/SKILL.md`（v1.0.0），删除安装 / 初始化 / 首次 `auth login` 流程章节，仅保留出错时需要的内容。
