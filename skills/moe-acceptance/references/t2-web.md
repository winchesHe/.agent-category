# T2 Web 环境准备与恢复

## 适用范围

仅在首次准备 T2 商家 Web，或其 Host/私有代理、浏览器登录、桥接合同、组件恢复及结束清理有缺口时加载。已有页面与依赖路由仍适用就直接继续，不因目标为 T2 或发生 HMR 而重复读取。后端依赖与 Grey 路由按主文件的[场景决策树](../SKILL.md#场景决策树)处理，本文负责商家 Web 的接入细节。

## 默认项目与启动

T2 Web 默认优先使用 `Boarding_Desktop` 项目。启动前先确认当前 worktree 和已有改动；没有可复用的开发服务时，在该项目根目录执行：

```bash
HTTPS=true pnpm dev
```

`HTTPS=true` 与下方 Whistle 的 HTTPS 目标保持一致。`pnpm dev` 会构建 service worker 并启动 Rsbuild；仅在启动速度或内存成为瓶颈时，按项目 README 使用 `HTTPS=true FAST_DEV=1 pnpm dev`。

端口以实际启动输出为准，常见入口为 `https://localhost:3001/`。复用服务须确认 HTTPS 可用；若实际为 HTTP，按资源归属在原 worktree 用上述命令恢复。服务所属 worktree 和版本仍需核对，不能由端口连通或代理域名推定。

### Host 与 Whistle 拓扑

浏览器的业务入口保持为真实 T2 Host：

```text
浏览器 https://go.t2.moego.dev
        ↓ 当前 session 的 Whistle 私有规则
本地 Boarding_Desktop 前端 https://localhost:<port>
        ↓ 项目现有代理配置
T2 API / 远端目标环境
```

不要让浏览器直接以 `https://localhost:<port>` 作为业务入口。这样会丢失真实 Host 下的登录上下文，并可能触发本地自签证书警告。为当前 session 创建或复用独立 Whistle 实例及规则，具体方式见下方网络准备步骤；不要切换系统全局代理。

Whistle 目标属于当前 session 的环境事实，没有必要在每个 case 中重新确认。

`web-t2` 的现有规则合同是把真实 Host 映射到本地前端端口，例如：

```text
go.t2.moego.dev 127.0.0.1:<frontend> enable://https disable://auto2http
```

`<frontend>` 必须来自当前开发服务的实际监听端口。规则需要保持本地 host 映射，不能改成远端 URL rewrite；否则本地服务失效时可能回落到远端页面，形成“本地代码已加载”的假阳性。

### 网络与身份准备

以下是缺少环境时的准备依赖，不是每个 case 的前置清单：

1. 用独立 storage/directory、proxy/UI 端口和 `PFORK_MODE=bind` 启动 `w2 run`，规则使用上面的 Host→本地前端映射。
2. 优先用 agent-browser 自启隔离浏览器，默认 headless：`agent-browser --proxy http://127.0.0.1:<proxy> --namespace <namespace> --session <session> --headed false open https://go.t2.moego.dev`。只有调用方显式指定 `--head` 时才加入 `--headed`；它自己持有浏览器控制上下文，不需要先准备外部 CDP。
3. 在浏览器控制层回读当前页面并确认 Host 正确。只有用户已经提供外部浏览器，或自启路径明确失败时，才检查 CDP page target；外部 CDP attach 属于兼容兜底，不进入默认路径。
4. 沿用实际浏览器的 namespace、session、Host、environment 和 socket root。不要把公共 `agent-browser connect <cdp>` 当作可靠的 attach-existing-CDP。
5. 自定义 socket 时沿用对应 `AGENT_BROWSER_SOCKET_DIR`；按 moe-mis Skill 确认完整参数，使用 `impersonate --source business --browser-session <session> --browser-namespace <namespace>`，再在同一 session 回读 Host 和非敏感身份。

`w2 run` 不负责安装 Whistle CA，Chrome 能否建立 HTTPS 页面依赖机器已有的 CA 信任。只在首次建 session 或出现证书/路由失败信号时处理该问题，不在每个 case 或每次 HMR 后重复检查，也不切换 macOS 全局代理。若当前机器没有可用的 CA 信任，桥接应报告为环境缺口并停止完整浏览器验收，不能让用户临时手工改规则来掩盖绑定缺口。

如果浏览器直接访问 localhost 而出现本地自签证书警告，先判断是否误用了入口。标准路径应回到真实 T2 Host 并检查当前 session 的 Whistle 路由和 CA 信任；不要把浏览器安全提示转成用户手工配置步骤，也不要绕过浏览器安全校验。

## 登录与打开

已有正确账号、环境和有效登录态时直接复用当前浏览器。需要登录时，使用 `moe-mis impersonate --source business`，显式传入当前浏览器的 `--browser-session` 与 `--browser-namespace`，沿用相同 socket 和启动配置；完成后回读账号及业务范围。仅身份失效时直接恢复 MIS 登录；首次还需准备本地前端、Whistle 和浏览器时，可使用下方 `session_login.py` 顺序准备桥接。

给定已经确认的账号和环境，桥接只完成确定的 Whistle 路由确认、浏览器 context 校验、MIS impersonate 和页面打开动作，并返回 tab/context 引用。输出前仍需检查敏感内容，不能把脚本摘要当作完整隐私保证。账号选择、白名单解释、数据策略和业务判断仍由 AI 完成。Web 场景使用 impersonate，不改用密码登录流程。

已有同账号同环境 tab 时直接复用。只有 tab 损坏、账号不匹配、环境变化或登录态明确失效时才重新建立浏览器上下文。

### 顺序准备桥接

现有 `session_login.py` 把上面的固定衔接实现为顺序准备 bridge。首次准备且参数已查明时可使用；局部故障优先用现有组件能力恢复，不把它当作每次续跑的入口。

bridge 不解析后端依赖或配置 Grey。固定顺序是：

1. 指定前端端口可连接时直接复用，否则按[默认项目与启动](#默认项目与启动)的命令新建开发服务。桥接只检查端口，不自动校验或重启已有服务。
2. 指定代理端口可连接时直接复用，否则按 Host→本地端口规则启动隔离 Whistle。当前不会验证已占用端口的规则或服务归属，不能把复用结果当作规则已核验；出现路由异常时需按实际组件能力检查。
3. 检查并复用同一 session 的 agent-browser context；没有可用 context 时才用 `--proxy`、`--namespace`、`--session` 启动隔离浏览器。只有外部浏览器场景才检查 CDP page target。
4. 使用同一 namespace/session 取得页面 URL、标题和可见文本，不返回或要求额外 context handle 文件；外部浏览器接入不属于当前 bridge 已实现路径。
5. 根据登录 URL/页面线索或 `--force-login` 决定是否调用 `moe-mis` 的显式 namespace/session 路径，准备运行期间持有资源收据锁。当前不会比对实际账号与 account-ref，AI 要依据已有身份观察判断是否匹配，不能把 MIS skipped 当成账号一致证明。
6. 回读真实 T2 Host 和身份线索后返回。当前摘要 URL 的 query/fragment 未做完整清理，输出或发布前不得直接回显未经检查的 URL。

当前实现位于 `moe-acceptance/scripts/session_login.py`。调用方传入已确认的 worktree、前端端口、账号、namespace 和 session；脚本默认以 headless 模式启动或复用资源，只有传入 `--head` 才显示窗口，并输出 JSON 摘要。例如：

```bash
python3 moe-acceptance/scripts/session_login.py \
  --worktree /absolute/path/to/Boarding_Desktop \
  --frontend-port 3001 \
  --account-ref aid:<id> \
  --namespace moe-t2 \
  --session moe-t2-web
```

需要人工观察时，在同一命令末尾增加 `--head`；不要在 session 已启动后混用两种模式，切换模式应建立新的 session。

脚本不安装 CA、不切换系统代理、不选择账号，也不判断 case 是否通过。外部浏览器的 CDP 接入仍是后续兼容项。

启动等待可用 `--startup-timeout <seconds>` 调整；日志初始化后的桥接故障返回包含 `runId` 和 `logFile`，可直接定位失败阶段。更早的参数错误可能没有运行日志，不为补日志重复整条流程。

`namespace/session` 与 MIS 使用同一名称合同：1–64 位 ASCII 字母、数字、下划线或连字符，首位不能是连字符，不允许点号。登录在启动资源前校验。浏览器首次创建前后读取实际 active 状态；导航失败但已创建时仍登记归属，无法确认原有状态时拒绝接管。

准备完成后默认保留 session 供当前验收继续。任务结束或取消时，使用同一 namespace/session 执行精确清理：

```bash
python3 moe-acceptance/scripts/session_login.py \
  --namespace moe-t2 \
  --session moe-t2-web \
  --cleanup
```

清理只定向关闭本次 bridge 创建且登记的浏览器 session，保留同 namespace 下其它 session；随后删除归属已核实的浏览器恢复态、Whistle 和 dev 临时资源。复用的已有服务不会被接管。诊断 JSONL 保留，方便追查失败原因。任务结束后下一个任务使用新的 namespace/session，直接走冷启动登录，不做旧 session 可复用性判断。

cleanup 输出 `ok:false` 时退出码为 `4`，全部成功为 `0`；现有桥接异常与超时仍返回 `5`，参数解析失败为 `2`。关闭必须返回明确成功的 JSON，否则 `browser=failed` 并保留资源收据。

恢复态清理规则：

- 合并关闭前查询路径、关闭结果 `statePath` 和收据待重试路径；先记入收据，再核验归属并删除。`active:false`、`runtime:null` 且无查询错误时，补查桥接 `--restore` 的默认 session 文件。
- 查询和保存结果明确、所有已知文件均已删除或不存在时标记 `purged`，并清除浏览器收据项；后续重试只处理剩余资源。
- 查询、保存或删除结果不明及路径越界时，返回 `browserRestore=failed` 并保留收据，按日志恢复对应组件。

重复执行会重新经过准备检查，端口可连接且页面无需登录时复用服务、浏览器并跳过 MIS。`--force-login` 强制重新 impersonate，但仍先经过 dev、Whistle 和浏览器检查；它不是 MIS-only 或任意组件修复子命令。bridge 不选择账号、不准备业务数据、不编排 case、不判断验收通过。

CA 信任属于环境能力；bridge 不提供专用 CA 安装/诊断接口。出现证书信号时按实际错误定位缺口；不通过 `ignore-certificate-errors`、系统全局代理或临时用户配置绕过安全校验。

## 失败后的局部恢复

| 信号 | 最小恢复范围 |
| --- | --- |
| 401 或明确登录失效 | 确认当前账号/环境，按 moe-mis Skill 的真实参数在同一 namespace/session 恢复身份，再回读原页面 |
| Host 或路由异常 | 检查该 session 的 Whistle 规则、代理及受影响服务，修复后重试原动作 |
| 服务连接失败 | 定位受影响进程，按项目命令恢复，不重启其它服务 |
| tab 不可用 | 先恢复当前 page，确认不可用才建立替代上下文 |

局部操作参数未知时先查询对应工具/Skill 合同；不编造 bridge 的 repair 子命令。只有现有组件能力无法满足且确实需要整条准备链时，才说明原因后使用 bridge，不能静默从头重跑。恢复后继续原 case，不重做无关账号映射和数据准备。

## 相关指引

- [account.md](account.md)：账号选择与身份缺口；MIS 原子能力由 `moe-mis` 提供。
- [parallel-browser.md](parallel-browser.md)：确需第二个浏览器上下文时的隔离与共享编辑约束。
- [case-execution.md](case-execution.md)：实际页面观察、业务判断与结果记录。
- [report-publishing.md](report-publishing.md)：已有证据的登记、报告 API 和按需发布。

T2 环境与 bridge 参数以本文及 `session_login.py --help` 为准。
