---
name: browser-use
description: 自动化浏览器交互，适用于 Web 测试、表单填写、截图和数据提取。本地优先：执行 browser-use 任务命令前，先用 cookies get 确认已有本地浏览器连接；cookies 为空、未连接或失效时才 close 后重新 connect。
allowed-tools: Bash(browser-use:*)
---

# 使用 browser-use CLI 自动化浏览器

`browser-use` 命令提供快速、持久的浏览器自动化能力。始终优先使用用户本地浏览器：执行任务命令前，先用 `browser-use cookies get` 确保当前会话已经连接；只有 cookies 非空时才直接复用，不要重复运行 `browser-use connect`。

## 前置条件

```bash
browser-use cookies get   # 优先检查已有会话；只有 cookies 非空才算连接成功
browser-use close         # cookies: []、未连接或会话失效时先清理
browser-use connect       # close 后重新连接
```

## 核心流程

硬性规则：执行任何浏览器自动化任务前，先确保本地浏览器会话处于已连接且可用状态。优先用 `browser-use cookies get` 检查现有连接；只有返回的 `cookies` 非空才认定连接成功。若输出包含 `cookies: []`、命令失败、未连接或连接失效，必须先运行 `browser-use close` 清理，再运行 `browser-use connect` 重新连接。在本地连接建立前，不要运行 `open`、`state`、`click`、`input`、`eval`、`screenshot` 或其他任务命令。

1. **检查连接**：运行 `browser-use cookies get`；只有返回的 `cookies` 非空，才说明现有会话可复用
2. **按需重连**：如果返回 `cookies: []`、命令失败、未连接或会话失效，先运行 `browser-use close`，再运行 `browser-use connect` 连接到用户已有 Chrome，保留 cookie、登录态和真实浏览器状态
3. **导航页面**：`browser-use open <url>`，在已连接的本地浏览器中打开目标页面
4. **检查页面**：`browser-use state`，返回可点击元素及其索引
5. **执行交互**：使用 `state` 返回的索引，例如 `browser-use click 5`、`browser-use input 3 "text"`
6. **验证结果**：使用 `browser-use state` 或 `browser-use screenshot` 确认页面状态
7. **持续复用**：浏览器会在命令之间保持打开

如果命令失败，先运行 `browser-use close` 清理损坏会话，然后重新运行 `browser-use connect`，再用 `browser-use cookies get` 确认 cookies 非空后重试任务。

云浏览器不是默认选项。只有在用户明确要求云端执行，或本地浏览器连接不可用且用户同意兜底时，才使用 `browser-use cloud connect`。

### 如果 `browser-use connect` 失败

当 `browser-use connect` 找不到已开启远程调试的 Chrome 时，提示用户在两个本地方案中选择：

1. **使用真实 Chrome 浏览器**：用户需要先启用远程调试
   - 在 Chrome 中打开 `chrome://inspect/#remote-debugging`，或使用 `--remote-debugging-port=9222` 重新启动 Chrome
   - 然后重试 `browser-use connect`
2. **使用托管 Chromium 加载 Chrome 配置档**：不需要改动 Chrome 设置
   - 运行 `browser-use profile list` 查看可用配置档
   - 询问用户要使用哪个配置档，然后运行 `browser-use --profile "ProfileName" connect`
   - 这会启动一个独立 Chromium，并加载该配置档的 cookie、登录态和扩展

让用户选择，不要替用户假设使用哪条路径。任一本地兜底方案成功后，都要用 `browser-use cookies get` 确认 cookies 非空，再执行任务命令。

## 浏览器模式

```bash
browser-use cookies get                        # 优先执行：只有 cookies 非空才算已连接
browser-use close                              # cookies: []、未连接或会话失效时先清理
browser-use connect                            # close 后重新连接到用户 Chrome
browser-use open <url>                         # 只在确认已连接后导航
browser-use --headed open <url>                # 调试用：仅在连接路径不可用或不合适后使用
browser-use --profile "Default" connect        # 直接 connect 失败时的本地配置档兜底
browser-use cloud connect                      # 仅在用户明确同意后作为云端兜底
```

确认 cookies 非空后，后续命令都会发送到该本地浏览器，不需要额外 flag。

## 命令

以下命令均假设当前会话已经处于已连接状态，且 `browser-use cookies get` 返回的 cookies 非空。

```bash
# 导航
browser-use open <url>                    # 导航到 URL
browser-use back                          # 返回上一页
browser-use scroll down                   # 向下滚动（--amount N 指定像素）
browser-use scroll up                     # 向上滚动
browser-use tab list                      # 列出所有标签页
browser-use tab new [url]                 # 打开新标签页（空白页或指定 URL）
browser-use tab switch <index>            # 按索引切换标签页
browser-use tab close <index> [index...]  # 关闭一个或多个标签页

# 页面状态：交互前总是先运行 state 获取元素索引
browser-use state                         # URL、标题、可点击元素及索引
browser-use screenshot [path.png]         # 截图（不传路径则输出 base64，--full 截整页）

# 交互：使用 state 返回的索引
browser-use click <index>                 # 按索引点击元素
browser-use click <x> <y>                 # 按像素坐标点击
browser-use type "text"                   # 向当前聚焦元素输入文本
browser-use input <index> "text"          # 点击元素、清空原内容、再输入文本
browser-use input <index> ""              # 清空字段，不输入新文本
browser-use keys "Enter"                  # 发送键盘按键（也支持 "Control+a" 等）
browser-use select <index> "option"       # 选择下拉选项
browser-use upload <index> <path>         # 上传文件到文件输入框
browser-use hover <index>                 # 悬停到元素
browser-use dblclick <index>              # 双击元素
browser-use rightclick <index>            # 右键点击元素

# 数据提取
browser-use eval "js code"                # 执行 JavaScript 并返回结果
browser-use get title                     # 获取页面标题
browser-use get html [--selector "h1"]    # 获取页面 HTML（或按选择器限定范围）
browser-use get text <index>              # 获取元素文本
browser-use get value <index>             # 获取 input/textarea 值
browser-use get attributes <index>        # 获取元素属性
browser-use get bbox <index>              # 获取元素边界框（x、y、宽、高）

# 等待
browser-use wait selector "css"           # 等待元素（--state visible|hidden|attached|detached，--timeout ms）
browser-use wait text "text"              # 等待文本出现

# Cookie
browser-use cookies get [--url <url>]     # 获取 cookie（可按 URL 过滤）
browser-use cookies set <name> <value>    # 设置 cookie（--domain、--secure、--http-only、--same-site、--expires）
browser-use cookies clear [--url <url>]   # 清除 cookie
browser-use cookies export <file>         # 导出为 JSON
browser-use cookies import <file>         # 从 JSON 导入

# 会话
browser-use close                         # 关闭浏览器并停止 daemon
browser-use sessions                      # 列出活动会话
browser-use close --all                   # 关闭所有会话
```

高级浏览器控制（CDP、设备模拟、标签页激活）见 `references/cdp-python.md`。

## 云 API

```bash
browser-use cloud connect                 # 创建并连接云浏览器（零配置）
browser-use cloud login <api-key>         # 保存 API key（或设置 BROWSER_USE_API_KEY）
browser-use cloud logout                  # 删除 API key
browser-use cloud v2 GET /browsers        # REST 透传（v2 或 v3）
browser-use cloud v2 POST /tasks '{"task":"...","url":"..."}'
browser-use cloud v2 poll <task-id>       # 轮询任务直到完成
browser-use cloud v2 --help               # 查看 API endpoint
```

`cloud connect` 会创建一个带持久配置档的云浏览器（首次使用时自动创建），通过 CDP 连接，并打印实时访问 URL。`browser-use close` 会断开连接并停止云浏览器。如需自定义浏览器设置（代理、超时、指定配置档），直接使用 `cloud v2 POST /browsers` 并传入所需参数。

### Agent 自注册

仅在没有 API key 时使用（通过 `browser-use doctor` 检查是否已设置 api_key）。如果已经登录，完全跳过此步骤。

1. `browser-use cloud signup`：获取 challenge
2. 解答 challenge
3. `browser-use cloud signup --verify <challenge-id> <answer>`：验证并保存 API key
4. `browser-use cloud signup --claim`：生成 URL，供人类认领账号

## 隧道

```bash
browser-use tunnel <port>                 # 启动 Cloudflare tunnel（幂等）
browser-use tunnel list                   # 显示活动 tunnel
browser-use tunnel stop <port>            # 停止 tunnel
browser-use tunnel stop --all             # 停止所有 tunnel
```

## 配置档管理

```bash
browser-use profile list                  # 列出检测到的浏览器和配置档
browser-use profile sync --all            # 同步配置档到云端
browser-use profile update                # 下载或更新 profile-use binary
```

## 命令链

命令可以用 `&&` 串联。浏览器通过 daemon 持久存在，因此串联命令是安全且高效的。

```bash
browser-use open https://example.com && browser-use state
browser-use input 5 "user@example.com" && browser-use input 6 "password" && browser-use click 7
```

不要把 `browser-use cookies get` 放进 `&&` 命令链里当作唯一判断，因为命令成功退出不等于 cookies 非空。必须先单独运行并检查输出不是 `cookies: []`，再串联后续命令。需要解析 `state` 来发现元素索引时，也要分开运行命令。

## 常见流程

### 需要登录态的浏览

当任务需要访问已登录网站（Gmail、GitHub、内部工具）时，使用 Chrome 配置档：

```bash
browser-use cookies get                             # 优先复用 cookies 非空的现有连接
browser-use close                                   # cookies: []、未连接或会话失效时先清理
browser-use connect                                 # close 后尝试用户正在运行的 Chrome
browser-use profile list                            # 如果 connect 失败，查看可用配置档
# 询问用户使用哪个配置档，然后连接到该本地配置档：
browser-use --profile "Default" connect            # 使用已有登录态的本地配置档
browser-use open https://github.com                # 只在确认已连接后导航
```

### 暴露本地开发服务

```bash
browser-use tunnel 3000                            # → https://abc.trycloudflare.com
browser-use cookies get                             # 先确认 cookies 非空；否则 close 后重新 connect
browser-use open https://abc.trycloudflare.com     # 在已连接浏览器中访问 tunnel
```

## 多浏览器

对于 subagent 工作流或并行运行多个浏览器，使用 `--session NAME`。每个会话都有自己的浏览器。见 `references/multi-session.md`。

## 配置

```bash
browser-use config list                            # 显示所有配置值
browser-use config set cloud_connect_proxy jp      # 设置配置值
browser-use config get cloud_connect_proxy         # 获取配置值
browser-use config unset cloud_connect_timeout     # 删除配置值
browser-use doctor                                 # 显示配置和诊断信息
browser-use setup                                  # 交互式安装后配置
```

配置保存在 `~/.browser-use/config.json`。

## 全局选项

| 选项 | 说明 |
|--------|-------------|
| `--headed` | 显示浏览器窗口 |
| `--profile [NAME]` | 使用真实 Chrome；裸 `--profile` 使用 "Default" |
| `--cdp-url <url>` | 通过 CDP URL 连接（`http://` 或 `ws://`） |
| `--session NAME` | 指定命名会话（默认 "default"） |
| `--json` | 以 JSON 输出 |
| `--mcp` | 通过 stdin/stdout 作为 MCP server 运行 |

## 提示

1. **总是先确认连接状态**：优先 `browser-use cookies get`，只有 cookies 非空才算成功；`cookies: []`、失败或未连接时先 `browser-use close` 再 `browser-use connect`
2. **交互前总是先运行 `state`**，查看可用元素及索引
3. **调试时使用 `--headed`**，观察浏览器正在做什么
4. **会话会持久存在**，浏览器在命令之间保持打开
5. **CLI 别名**：`bu`、`browser`、`browseruse` 都可用
6. **如果命令失败**，运行 `browser-use close`，再运行 `browser-use connect`，然后重试

## 故障处理

- **浏览器无法连接？** 先运行 `browser-use close`，再运行 `browser-use connect`；如果仍失败，按上面的本地兜底流程处理
- **浏览器无法启动？** 先运行 `browser-use close`，再运行 `browser-use connect`；只有在本地连接路径明确后，才用 `--headed` 调试
- **找不到元素？** 运行 `browser-use scroll down`，再运行 `browser-use state`
- **运行诊断：** `browser-use doctor`

## 清理

```bash
browser-use close                         # 关闭浏览器会话
browser-use tunnel stop --all             # 停止 tunnel（如有）
```
