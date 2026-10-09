# T2 Client Portal / Report Card 本地验收

## 适用范围

仅在首次准备 Client Portal / Report Card、当前 Portal 的路由或身份上下文缺失、相关组件失败，或任务结束需要按归属清理时加载。已有 Portal session 的 Host、页面、身份、对象和本地代码来源仍有效时，直接用原 `namespace/session/tab` 继续，不重启 Vite、Whistle、浏览器或登录流程。

本路径只覆盖 `moego-client-portal` 的 Vite CSR。Report Card 的 SSR、title、OG/社交分享元信息不在此路径内；需要这些结果时必须另走产品真实 SSR 链路，不能用 Vite 页面代验。

## 分阶段确认真实输入

环境准备可以独立进行，不以业务对象或写入授权为前置。首次准备 Vite/Whistle 前只需从当前任务上下文确认以下事实；已有且未变化的事实直接复用：

- 目标 `moego-client-portal` worktree 及需要验收的代码版本；
- 实际目标 Host 及本任务自有的端口、目录、namespace/session 等资源信息。稳定 T2 Host 的已知入口是 `my.t2.moego.dev`；Grey Host 必须来自当前真实配置，不能按命名规律临时拼接。

实际打开真实 Report Card 前再确认获授权的完整链接、目标对象及打开次数授权。路径 UUID 是报告对象的一部分；`reportId` 是可选参数，只有本次目标明确要求指定报告版本时才需要，不能把它列为普通 Report Card 的必填项。Portal 登录后页面则在进入前确认是否已有属于目标客户的 Portal 登录上下文；商家 Web Cookie、MIS 商家 impersonate 或 OBC Customer impersonate 都不是 Portal 身份证明。

Report Card 合法链接失效、目标所需 UUID 缺失、明确要求版本但对应 `reportId` 缺失、报告不存在或接口拒绝时，按实际观察记为信息不足或对应失败；不猜 ID、不遍历无关客户、不改 `didLogin`、不伪造 token，也不用 `preview` 冒充真实报告读取。

读取真实 Report Card 会触发打开次数请求。首次开始这组测试时统一说明测试对象、预期打开范围和该附带写入并取得授权；同一对象与同一约定测试范围内后续刷新、重开或复验可复用该授权，不必每次再问。范围、对象或副作用性质变化时重新确认。当前上下文没有明确授权时必须停在打开前，不能将推测写成授权，也不能通过拦截成功响应、修改产品代码或事后重置计数来掩盖副作用。

## 首次准备

### 1. 本地 Vite

先在目标 worktree 核对当前状态、`package.json` 和项目说明。已有服务只有在 worktree、监听地址、端口和代码来源均符合本次目标时才复用；不能只因端口可连接就认领。没有可复用服务时，在产品 worktree 启动：

```bash
pnpm exec vite --host 127.0.0.1 --port <实际空闲端口> --strictPort
```

项目已知的 CSR 脚本是 `pnpm dev:client`，Vite 默认端口为 7001 且 `strictPort`；上面的显式命令便于同时验收多个 worktree。依赖安装遵循项目锁文件、pnpm 与已有私有 registry，不修改认证配置。以真实启动输出确认最终监听，不把进程启动或首页 200 当作目标模块来自该 worktree 的证据。

### 2. session 私有 Whistle

浏览器始终访问已确认的真实 HTTPS Host。只有 SPA 路由、静态资源和 Vite 开发资源进入本地 HTTP Vite，以下三个远端前缀必须排除出本地映射：

- `/api`
- `/moego.api`
- `/moego.bff`

先选择当前任务独占的 Whistle `baseDir`、`storage`、proxy 端口和 UI 端口；所有值都要来自当前运行事实，不能复用来源不明的监听端口。规则形状为：

```text
<实际Host> http://127.0.0.1:<Vite端口> enable://https excludeFilter://<实际Host>/api excludeFilter://<实际Host>/moego.api excludeFilter://<实际Host>/moego.bff
```

`w2 --help` 已确认 `-D/--baseDir`、`-S/--storage`、`-p/--port`、`-P/--uiport`、`-H/--host`、`-r/--shadowRules` 和 `--no-prev-options` 可用。首次启动可按实际占位值执行：

```bash
PFORK_MODE=bind w2 run \
  -S <本任务storage目录> \
  -D <本任务baseDir目录> \
  -H 127.0.0.1 \
  -p <proxy端口> \
  -P <UI端口> \
  --no-prev-options \
  -r '<上方完整规则>'
```

保留机器已有 CA 信任，不使用 `--init`、系统全局代理或浏览器 `--ignore-https-errors`。证书或路由失败时只定位当前 session 的 Whistle、规则、Host 和 CA 信任；不要让浏览器改访 localhost 绕过真实 Host。

### 3. agent-browser 直接连续操作

本平台不调用 `moe-acceptance/scripts/session_login.py`。该 bridge 固定服务于商家 `Boarding_Desktop` 的 `pnpm dev`、商家 Host 路由和 MIS impersonate；更换 Host 或参数不能把它变成 Portal bridge。

没有可复用 Portal 浏览器时，使用本任务独占且已记录的 namespace/session，经私有 proxy 直接打开已授权链接。默认 headless；用户明确要求可见窗口时才使用 `--headed`：

```bash
agent-browser \
  --namespace <namespace> \
  --session <session> \
  --proxy http://127.0.0.1:<proxy端口> \
  --headed false \
  open '<已核实且获授权的完整链接>'
```

后续命令都显式携带同一 `--namespace/--session`。首次打开、上下文变化或出现失败信号时，回读必要的 URL、tab 和页面内容，确认实际 Host、目标对象及预期页面；引用自 `snapshot` 的 `@ref` 只在对应 active tab 中使用，切 tab 后重新 snapshot。已有 session 的相关事实无变化时直接执行下一个业务动作，不把 URL/tab 回读或上述准备步骤变成每个 case 的固定前置。

## 身份分流

- **Report Card：** 路由没有登录 guard 只表示前端路由形状，不代表链接公开或全 Portal 已认证。只使用本次合法分享/访问上下文，并以真实接口和内容结果判断。
- **Portal 已登录页面：** 仅复用已确认属于本次目标客户的 Portal 登录上下文。没有该上下文时，走产品真实登录页面；需要凭证、验证码、邮件/短信或其它外部发送时，遵守当前授权边界并在缺少必要输入时暂停。
- **边界：** Report Card 可见不能证明客户 profile、首页或其它登录后页面已登录；商家/MIS/OBC 的身份也不能代替 Portal 客户身份。B5.1 不承诺自动化新客户登录。

不主动提交评论、评分、预约或客户资料。受保护链接的 path/query、认证跳转参数及客户信息不写进 Git、公开报告或普通摘要。

## 路由与业务验证

真实场景开始前可清空当前 session 的 Network 观察，随后执行目标用户动作并查看实际请求：

```bash
agent-browser --namespace <namespace> --session <session> network requests --clear
agent-browser --namespace <namespace> --session <session> network requests --filter '/moego.bff'
agent-browser --namespace <namespace> --session <session> network request <实际requestId>
```

对 `/api`、`/moego.api`、`/moego.bff` 使用同样的查询方式，但只核对真实场景自然发生的请求。规则中必须同时排除三个前缀；端到端证据则按本次实际触发逐项记录 method、目标 Host、status、响应类型/必要语义和页面结果，确认未被本地 Vite 接成 SPA HTML 或本地 404。不要为了凑齐三个前缀额外寻找接口、发明 canary 或调用与场景无关的 endpoint；未自然触发的前缀明确记为“规则已配置、端到端未实测”。稳定 T2 与 Grey 的结果分别记录，不能相互外推。

业务通过至少需要：

1. 获授权对象的真实 Report Card 关键内容可见，并按 Claim 目视检查必要业务区域；
2. 页面加载的相关 Vite 模块/开发资源能与目标 worktree 对应，而不只依据地址栏、Host 或端口存活；
3. 实际触发的相关 API 请求按上述分流到当前目标远端 Host，页面结果与接口响应一致；
4. 打开次数请求及其授权范围如实记录；无法确认后端过滤或实际计数时不要写成零副作用。

Report Card 当前使用 FullPage `translateY` 分屏，未交互时约每 5 秒自动翻到下一页，普通键盘、触摸或鼠标交互会停止自动翻页（`GroomingReport.options.tsx:119-154`）；该场景下 `document` 与 `screenshot --full` 仍只能证明一个 viewport，不能代表整份报告。需要某个 section 的证据时，通过页面真实翻页动作到达目标并等待本次过渡实际稳定后再留图；不强制改 DOM、禁动画或伪造“全页”结果，过渡中画面只作诊断不作业务证据。

若本轮存在真实代码修复，确认更新信号后仅重验受影响内容；没有代码改动就不声称 HMR 或修复验证。通用 Claim、截图、隐私、报告和局部复验规则继续使用现有 references，本文件不重复。

## 局部恢复与资源归属

只恢复发生故障的一侧：Vite 失败只处理本任务 Vite，路由异常只检查本任务 Whistle，tab/session 失效才处理对应浏览器，Portal 身份失效才恢复产品真实登录。不要回退到商家 bridge 或重跑无关组件。

创建资源时就在当前 AcceptanceSession 保存精确归属，不新增 manifest、receipt 文件、session manager 或持久资源框架：

| 资源 | 当前 session 至少保存的事实 |
| --- | --- |
| Vite | worktree、启动命令、实际端口、进程/终端引用、created/reused |
| Whistle | Host、完整规则、baseDir、storage、proxy/UI 端口、进程/终端引用、created/reused |
| 浏览器 | namespace、session、tab、proxy、headed 模式、created/reused |
| 业务上下文 | 环境、对象的非秘密引用、Portal/Report Card 身份类型、打开次数授权范围 |

普通 case、HMR、本轮回复结束或等待补充时都保留这些资源。整个验收任务明确结束或取消后，只停止表中标记为本任务 `created` 且仍能精确对应的进程/浏览器，并删除本任务自有的临时 Whistle 目录；`reused` 资源、业务数据、诊断和正式证据保留。直接准备的 Portal 资源没有登记在 `session_login.py` 的 bridge receipt 中，禁止调用 bridge `--cleanup` 处理它们。精确归属丢失时保留资源并报告缺口，不使用 `close --all`、全局 `w2 stop`、全局杀进程或目录扫描猜测目标。

## 已核查来源

- `moego-client-portal` 的 `package.json`、`vite.config.ts`、`src/routes.ts`、`src/App.tsx`、`src/state/groomingReport/state.ts`、`src/state/client/state.ts`、`src/components/StateObserver.tsx` 和 `server/routes/groomingReport.ts`；核查版本见 B5 设计。
- 本机 `w2 --help`、`agent-browser --help`、`agent-browser network --help` 与 `agent-browser skills get core --full`；帮助只证明参数合同存在，不代表真实路由或业务已经通过。
