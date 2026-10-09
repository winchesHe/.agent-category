# iOS Simulator 本地验收

## 按当前缺口使用

适用于 `moego-mobile` 的 iOS Simulator 原生页面、控件、导航和本地代码验收。只在首次准备，或后台连接/展示/交互、多需求隔离、设备/build、账号/API 环境/Location、原生动作、更新来源及结束归属不明时读对应部分；已有正确设备、页面、身份与代码来源且上下文无变化时直接续验，不重放准备或登录。

设备、Metro、必要安装及业务身份属于同一次环境准备，由同一 AI 在本次授权内完成后接业务用例。默认后台 `simctl + Maestro`，不主动显示 Simulator.app；用户需要看现场时只补目标窗口展示，不因此重建健康环境或切换驱动，也不扩展为操作宿主无关窗口。普通 Web 仍默认 headless，商家 Web 的 `session_login.py` 不能准备本平台。

原生导航和页面操作使用目标设备上的控件；身份准备使用 MIS 深链或临时密码，API 查询按需复用 [App runtime](ios-runtime-api.md)。消息、预约、支付等写入按当前任务授权执行。

## 启动与本地代码来源

先复用已确认的产品 worktree、目标设备与开发服务。需要选择设备时，使用当前 `xcrun simctl list --json devices available` 获取 UDID/runtime/state；多台设备可以共存，只消歧本次目标，不关闭其它设备，不用模糊的 `booted` 代替明确 UDID。

本地 JS 仍由目标 `moego-mobile` worktree 的产品 `pnpm start` 提供，后台连接不依赖 Expo 的 `i` 按键。当前脚本设置分支及 `CI_ACTION=LOCALLY_DEV` 后运行 Expo，项目包含开发客户端。首次准备且 API 环境已明确时，优先按下方“API Grey”在启动命令中指定，不必进入 Settings 配置。已有兼容客户端就复用；只有缺客户端、原生依赖或配置变化等确需构建时，再按当前项目的 `pnpm ios` 路径构建并安装到明确目标设备。已有正确应用和 Metro 时不重复启动，不为补参数重放准备。

当前产品配置的 bundle identifier 为 `com.moement.moego.business`。准备时把实际安装 build 与运行中的 JS/Metro 来源分开核对：安装包名称、Metro ready、分支名或端口存活，单独都不能证明设备消费了目标 worktree。结合实际连接来源、启动记录及已加载页面/源码的必要观察建立对应；只能确认版本或内容一致时如实限定，不反推唯一 commit，不修改无关文案制造来源证据。

`Settings` 的 `Bundle Version`、`Native Version` 可辅助判断安装版本和运行形态；开发态显示 `development` 不等于已证明具体分支。当前仓库默认分支名 `production` 不是 API 环境，开发默认 T2 也不代替实际环境确认。已确认来源直接复用，变化或失败时才查受影响部分。

### 默认后台 simctl + Maestro

“后台”表示无需可见 Simulator.app 窗口，不是 Maestro 的 `--headless` 参数（该参数仅用于 Web）。已有健康设备、App、Metro 和身份直接复用；已有窗口也不为采用该方法而关闭。按缺口执行，不将以下内容作为每次续验必跑的 setup：

1. 仅目标设备尚未启动时执行 `xcrun simctl boot <明确UDID>`，等待并回读该设备状态；仅目标 App 尚未运行时执行 `xcrun simctl launch <明确UDID> <已核实bundle identifier>`。两者不负责展示 Simulator.app，也不证明目标 JS 已加载。
2. 缺开发服务时，在目标 worktree 使用产品 `pnpm start`，按下方 API Grey 规则选择环境；需要指定端口时依据当前 Expo `--port` 帮助选择未占用端口。可将 stdout/stderr 写入本任务私有日志，并保留可精确对应的进程/终端会话，不依赖后续 `i`。Metro 的 worktree、实际端口和日志来源须能对应，不能仅凭 `8081` 存活复用未知服务。
3. 使用 `maestro --device <明确UDID>` 绑定设备，按“真实动作与设备帧”读取必要状态、用已检查的短 Flow 操作开发客户端当前可见的目标 Metro 入口。实际 URL 必须对应本次服务，不默认点击历史记录第一项；入口缺失时先查现场支持的连接方式，不猜 URI scheme、不重放登录或全量 E2E。驱动可能安装或启动原生组件，按实际行为记录归属。
4. 将该设备的连接动作、对应 Metro 打包记录和加载后的页面观察关联，确认 JS 来源及必要身份/API ENV。开发客户端到 Metro 的 JS 连接与业务 API 到远端 T2/Grey 是两条独立连接；此方法本身不要求 Whistle 或本地后端，也不以 API ENV 显示代替网络命中验证。

设备 Booted、App 运行、目标 Metro 连接、宿主 GUI 可见分别判断，任何一项不能单独代替其它项；资源记录与结束处理仍按下方归属规则。

### 按需展示与 Expo 交互入口

用户需要看现场且设备、App 和 Metro 已健康时，只打开或定位目标 Simulator 窗口并核对所示设备。展示不要求改用 Computer Use，可继续绑定 UDID 的 Maestro；不为显示窗口重启服务、重装 App 或重登。

`pnpm start → i` 保留为可视或显式选择的首次准备入口：在目标 worktree 的交互 TTY 中启动 Metro，等快捷键提示出现后向同一会话单独发送 `i`，不追加换行；多设备时用 `Shift+i` 选择并核对实际目标，普通 `i` 的自动选择不能保证命中本次 UDID。当前 Expo 开发客户端打开链会尝试打开并激活 Simulator.app，但进程存在或激活成功不保证目标设备窗口在用户当前桌面可见，仍需实际核对。[Expo CLI](https://docs.expo.dev/more/expo-cli/#develop)

当前核查的 Expo CLI 只有在 `CI` 未启用且 `stdout.isTTY` 为真时才创建交互界面，按键监听还要求 stdin 支持 raw mode。外层分配 PTY 不会抵消 stdout 的文件重定向或普通管道；依赖 `i` 时须保留这些交互条件，`CI_ACTION=LOCALLY_DEV` 不等于关闭 `CI`。若 Metro 已健康但未启用按键监听，使用后台路径补连接，不为按键重启服务。

### 多需求现场保留与并行

需求 A 保留现场、继续需求 B，不要求两者同时动作：为 B 使用独立且适用的资源，可保留 A 后交替验收。Simulator 支持多台设备同时运行，窗口是否显示不构成并行门槛；后台方法便于避免主动激活窗口，但不自动提供资源和数据隔离。[Apple Simulator 说明](https://developer.apple.com/videos/play/wwdc2019/418/)

仅确有独立验收收益时考虑多设备，按以下条件判断：

- **设备与动作：** 各任务绑定不同的明确 UDID，同一设备/session 内动作仍串行；不能让两个任务同时导航同一 App。Expo 自动选设备和宿主前台窗口都不能代替 UDID 绑定。
- **代码与服务：** 不同代码分支或不同启动环境使用独立 worktree、Metro 进程与端口，并核对各设备连接来源。相同 JS 与启动配置可复用同一 Metro，但 Fast Refresh、重载/开发菜单广播和服务重启可能同时影响多个客户端；共享代码修改与重启串行，不能声称独立更新或冻结了 A 的现场。
- **驱动与证据：** 分别记录驱动连接、进程与输出目录，截图和日志按任务/设备区分。当前 Maestro 支持明确设备列表及 `--shard-all` / `--shard-split`，这是测试集合的多设备执行能力，不代表多个独立 CLI 进程已在本机验证无驱动端口、安装或连接冲突。确需独立进程并行时先按当前工具合同核实这些共享资源；发生冲突只恢复受影响侧，不为并行重装其它任务的驱动。动态验收不因有分片参数就改跑完整 E2E。[Maestro 设备选择与分片](https://docs.maestro.dev/maestro-flows/flow-control-and-logic/specify-and-start-devices)
- **窗口与宿主输入：** 可见窗口仍能配合明确 UDID 的原生驱动，显示不必切换工具。当前 Computer Use 仅提供 macOS 应用级绑定，不能据此认为两个 Simulator 窗口具备独立 UDID 输入通道；依赖全局鼠标、键盘或前台焦点的动作必须串行，不能让两个 Agent 同时抢焦点。
- **业务与归属：** 账号、Location、测试对象和服务端配置须无相互干扰；设备隔离不等于远端数据隔离。各任务保留自己的设备原始状态、应用/服务创建或复用关系，结束时只处理明确自有且不再被其它任务使用的资源。

## Account、API Grey 与 biz location

已有正确项不切换。需要调整多个上下文时，通常先确认已授权 API 环境，再建立目标 account，最后选择 biz location；不是每次验收都必须执行三种切换。App 启动、登录、页面访问可能产生统计/会话请求，身份与门店切换还涉及服务端上下文请求，不能描述为零写入。

### Account

默认商家账号沿用主文件的 T2 配置规则；当前登录邮箱与目标一致且业务范围满足要求时直接保留，不因原生平台需要不同登录方式而再次询问账号或调用 MIS。

- **关联账号：** 侧边菜单 `Settings → Account → Switch account`，从当前关联列表按已确认邮箱和姓名选目标；当前账号标为 `Current`。选择后产品提交切换请求、刷新账号信息并导航到 Calendar。该列表不是任意邮箱登录器，不因列表里有账号就获得访问授权。
- **非关联账号或未登录：** 在准备授权内使用当前产品支持的登录方式。已具备安全深链交付能力时优先按下节免输入登录；需要验证登录表单或深链通道不适用时，通过真实 `Log out`/登录页使用 MIS 临时密码。加载 `moe-mis` 账号合同并查对应帮助，使用 `impersonate --as-password --source business`；Email 匹配同一目标账号，密码通过目标框的安全粘贴路径交付，不把密码取回工具输出、写入 Flow 或命令参数，不把 `--raw-token` 当密码或自行拼接密码。
- **切换后：** 核对目标邮箱、登录状态及当前 Location/页面；换 account 不保证保留原门店。登录失败只排查该目标的环境、邮箱和登录方式，不尝试其它账号、清应用数据、换 Simulator 或重装来绕过。

### 携带参数的免输入登录

当前产品 `useInitDeepLinking.ts` 接收 `exp+moego-business-2://?action=login&token=<MIS原始token>`，处理初始 URL 和运行中的 URL 事件。只需要 `action`、`token`，不需要邮箱或密码；已登录时会先登出，再通过正式登录接口取账号信息。环境须先按本次目标准备，门店按登录结果回读；不能自行添加未实现的 env、businessId 等参数，也不为健康身份重放登录。

- 通过 MIS 公开入口 `impersonate --source business --raw-token` 获取本次目标的凭据；原文只到剪贴板。交接进程在内存中读取并编码 URL，通过已确认原生能力交付。已有 App runtime 时，可在该 runtime 调用 React Native `Linking.openURL`；它经过原生 URL 入口，不是直接调用登录 action。不得将凭据或完整 URL 写入工具参数、`simctl openurl` 的 argv、Flow、文件或日志，也不提取 App 内已有 token。当前 MIS CLI 尚无直接指定 Simulator 的登录参数，不编造 `--native` 等 flag。
- **已运行且已连接目标 JS 的 App：** 直接交付深链完成登录，无需输入账号密码；按实际状态处理系统确认。没有安全深链交付通道时使用临时密码路径。
- **进程关闭的 Expo 开发包：** 先加载目标 Metro 项目，再交付登录深链。若先发送业务深链，开发启动页会暂存 URL，选择并加载项目后继续登录。开发项目连接 URL 与登录 URL 分别处理，token 仅交给业务登录入口。
- 交付后通过 UI 登录锚点和必要账号/Company/Business 回读确认身份。登录失败时核对错误和当前身份；重新发起登录时通过 MIS 获取新凭据。开发启动页可能直接显示收到的完整链接，该页截图、hierarchy 和诊断不能直接交付。结束后按归属释放临时连接、清理本次凭据，Metro 和调试事件不落秘密。

### API Grey

**启动时指定：** 当前产品已支持 `EXPO_PUBLIC_MOE_GREY`；在包含该实现的目标 worktree 中启动 Metro，ready 后按前述方式打开项目：

```bash
# 稳定 T2；指定 Grey 时将 t2 替换为已确认且已部署的名称
EXPO_PUBLIC_MOE_GREY=t2 pnpm start
```

非空启动值（去除首尾空白后）优先于 App 已保存的 API ENV，再回退到默认环境；它会写入原有 `MOE_MOBILE_ENV` 存储，使原生与内嵌 WebView 使用同一选择。省略或置空变量不会清除已保存值，也不等于回到 T2；需要稳定 T2 时显式指定 `t2`。该 key 本身不是 shell 参数，`BRANCH_NAME` 也不是 API 环境选择器。

参数仅在 `__DEV__` 开发态生效，Release 测试包和生产包忽略它。接受 `t2` 或 1–50 位小写 DNS 名称（字母、数字及内部连字符），不接受 URL、`s1`、`production` 或 `preview`；格式有效不证明 Grey 已部署。变量由 Expo 内联进 JS bundle，不能放秘密；`EXPO_NO_CLIENT_ENV_VARS=1` 会禁用该内联。修改启动值后重启对应自有 Metro 并完整重载 App，不以普通 Fast Refresh 代替；已有正确上下文则不为补参数重启。

非法值或持久化失败会让环境初始化报错并阻止进入业务页，可能表现为停在启动屏。先修正配置或排除存储问题，再重启 Metro、完整重载；移除变量只会恢复读取原保存值，恢复后仍需确认目标环境。不能从启动命令成功推断环境生效，已有有效运行观察则直接复用。

**应用内切换：** 无启动覆盖时，仍可使用 Settings 调整环境。若 `EXPO_PUBLIC_MOE_GREY` 保留非空值，环境初始化/重载会重新应用它；要改由菜单选择其它环境，先移除有效启动配置（含实际来源中的该变量），重启 Metro 并完整重载，避免菜单选择后又被覆盖。

从 `Settings` 滚动到 `DEVELOPMENT` 分组，点击其中的 `Settings`（`settings-development-row`），再点开发设置 `API ENV` 下的当前环境名。搜索并选择已确认的 Grey name，在 `Set env to ... and reload app?` 弹窗点 `Yes`；返回稳定 T2 则选 `t2`。无论通过启动参数还是菜单选择，都在加载完成后回读当前 API 环境和必要业务身份，只恢复受影响的页面前置；启动指定不要求再经菜单重复选择。

`API ENV` 与上方 `APP ENV` 的 channel/runtime/bundle 不同，不为换后端环境改 App 代码版本。列表从 Grey 服务读取名称；`Use this directly` 仅用于已有可信依据的精确名称，列表失败不允许猜名称。选择现有 Grey 不是修改规则，也不能证明服务分支部署正确；确需查询或调整 service mapping 才加载 `moe-grey`。

T2 与其 Grey 共用 T2 基础环境，不要求每次切 Grey 都重登；基础环境改变时产品还会重新初始化环境并获取账号信息，是否能复用身份以实际结果为准。不为证明经验额外切 S1/production 或跑 Grey 用例。API 环境行只说明应用显示配置；需要请求命中证据时结合实际客户端 Host、请求及必要服务端日志，不由配置显示代验。

### biz location

`Settings → Account → Switch location`（`account-switch-location-row`），选目标项，在 `Switch location` 弹窗核对名称后点 `Switch`。列表项 testID 为 `switch-location-item-<实际显示名>`，当前项标为 `Current`；切换的是 Company/Business 上下文，不是修改用户邮箱。

企业 owner 的列表项优先显示 Company 名，为空才回退 Business 名；它可能与当前 Location 锚点的 Business 名不同或重复。用已有 Company/Business 对应关系消歧，不取第一项，不创建新门店兜底。源码在切换时尝试断开读卡器并检查员工登录限制；正常路径返回 Calendar，受限时按实际提示判断，不能仅因确认框关闭就算成功。

### 必要回读与隐私

开发态已有 `e2e-current-account-email`、`e2e-current-location-name`、`e2e-current-login-state`、`e2e-current-route` 等 accessibility/testID 锚点，分别辅助确认账号、Business 名、登录状态和页面。它们不提供 Company/Business ID 或完整 build 来源；缺锚点先核对当前 build/模式和可见信息，不直接判产品失败。

切换前按本批约定保留原环境、身份与恢复责任；后续 case 复用结果，不逐项来回切换。邮箱仅用于必要目标匹配，不输出无关个人信息。开发设置页还展示环境配置和 push token，采证仅保留目标环境行或已脱敏字段，不发布整页原图、完整 hierarchy 或配置。

Metro 可能输出完整业务响应，hierarchy 也可能包含配置或客户信息；在内容进入工具返回或共享材料前，先限定为当前需要的启动/连接事实、错误摘要或目标锚点字段，不先输出完整日志再补过滤。媒体单独目视检查，诊断目录不整体加入报告。

## 真实动作与设备帧

默认使用明确绑定当前 UDID 的 Maestro/已核实原生能力；已有有效驱动可复用，不机械要求试遍所有工具。Computer Use 仅在用户选择或确有原生能力缺口时按需使用，先确认能表达目标设备内控件动作；只能观察宿主窗口不等于能控制设备。展示窗口本身不是切换驱动的理由，宿主共享输入按上方规则串行。

当前 Maestro CLI 提供显式 `--device <UDID>`、`hierarchy` 和本地 `test`。使用前按当前缺口查帮助并读取拟复用 Flow；独立 `moego-mobile-e2e/project/business-app` 已有 common/cases/suites，但固定账号、回 Home、重启、清数据、业务写入或 cloud setup 不用于健康页面续验。确需短动作文件时只放任务临时产物，检查其行为与目标，不新建 runner 或触发完整 E2E/CI。

按决策点和证据边界组织短动作：已确认、无分支的导航、断言及采证可合并，遇到新状态、权限判断或失败时停下回读，避免无意义的拆分和预编排未知流程。YAML 中 `Yes` / `No` 等可能被解析成布尔值的按钮文字须写为引号字符串。参数类型或定位失败后先确认现场：前置仍有效就修正并从失败点继续，前置失效则仅恢复必要部分；不把驱动错误记作产品失败，也不以恢复成功代替待验动作。

用当前 hierarchy/testID、可见文字和设备帧定位真实控件，执行后读取对应页面或状态。驱动 tap 返回成功不等于产品响应；有界等待后仍缺观察就记录信息不足，不盲目重试提交。设备坐标必须对应明确 UDID、尺寸与当前帧，宿主全局鼠标点击不能冒充原生触摸证据。隐藏的 `e2e-go-home-button` 是 reset 辅助能力，不能代验用户通过可见返回按钮或手势完成导航。

稳定页面 Claim 的采证应等待相关异步动作完成，并确认目标状态已出现；不能仅因驱动已启动或截图文件已生成就认定采到了目标页。瞬时状态则在出现时及时捕捉，不等整段流程结束。保存后目视检查真实设备帧，再改变待验状态，例如使用已核实的命令：

```bash
xcrun simctl io <明确UDID> screenshot <本次证据的绝对路径.png>
```

截图成功和业务动作成功分别判断；同一有效截图可用于后续 case 前置，不重复采集。hierarchy 仅作必要支撑，过程 Claim 才补短录屏，不要求固定五件套。不默认配置代理、证书或打开 Inspector；确需 API 时按 [App 内请求](ios-runtime-api.md) 复用当前客户端。主动查询的响应不能冒充某个 UI 点击自然产生的请求，缺少对应观察的子项按事实保留未验证。通用证据归属、三态结论与报告使用已有规则，不新增原生报告系统。

## 连续更新与局部恢复

| 当前情况 | 下一步 |
| --- | --- |
| 页面、身份和来源无变化 | 直接继续当前或下一 case，不重启 Metro、不重登、不重跑 setup |
| 健康后台现场仅需展示给用户 | 只打开或定位目标 Simulator 窗口并核对设备，继续复用原生驱动 |
| Metro 健康但 Expo 没有交互按键监听 | 用明确 UDID 的后台路径补 App 到目标 Metro 的连接，不为 `i` 重启服务 |
| 仅 Metro/连接失效，设备与身份仍有效 | 只恢复对应自有服务或连接，补受影响来源观察，不清数据或切账号 |
| 有真实 JS 修改 | 观察 Fast Refresh/重新加载的实际结果，恢复更新实际改变的页面前置，再复验相关动作；状态是否保留以观察为准 |
| 原生依赖、配置或目标 build 改变 | 只在确需时重建/安装，核对目标设备与来源，并恢复实际受影响的身份/页面 |
| Account、Location 或 API 环境改变 | 暂停依赖旧上下文的断言，按上方对应入口核对并恢复当前动作前置 |
| 动作未响应或驱动失败 | 检查目标设备/当前页面、遮挡、事件语义和异步条件，只修当前缺口；不以工具退出码代替业务结论 |
| case 失败、等待输入，但任务继续 | 保留现场与有效资源，不因本轮回复结束而清理 |

Fast Refresh 不保证所有改动保留状态，原生变化也不等同于 JS 更新；没有真实源码修改就不制造演示修改或声称更新/修复已验。恢复后看到目标状态不能代替重新执行待验动作，已完成且仍有效的证据保留。[React Native Fast Refresh](https://reactnative.dev/docs/fast-refresh)

## 资源归属与结束

在当前对话的 AcceptanceSession 保留实际 UDID/runtime、bundle/build、worktree/JS 来源、Metro 进程或 TTY、驱动连接，以及设备原先是否启动、应用/服务是自建还是复用和约定恢复范围；已有记录复用，不建 manifest、租约、设备池或持久状态机。

整个验收任务明确结束或取消时，先完成必要现场证据与约定的 API 环境/身份恢复，再处理自有资源：只结束本次创建且可精确对应的 Metro/驱动进程；应用确属本次启动且应结束时，才使用 `xcrun simctl terminate <UDID> <bundle identifier>`；设备只有本次启动且约定恢复为关闭时，才使用 `xcrun simctl shutdown <UDID>`。复用设备、应用与服务保留，不删除安装包或业务数据，不使用 `shutdown all`、全局关闭 Simulator 或按名称批量杀进程。

结束操作后回读目标应用/设备状态与自有进程是否停止，命令返回成功不代替最终状态确认。恢复失败或归属不明时保留需要的上下文并报告缺口，不先关掉仍需用于恢复的设备。诊断、正式证据与报告保留；直接准备的原生资源不在商家 bridge 收据内，不调用 `session_login.py --cleanup` 处理。

## 实现定位

- 产品入口：`package.json`、`app.config.ts`；环境配置：`src/utils/env.ts`、`src/entry/init/initEnv.ts`；深链接收：`useInitDeepLinking.ts`；身份及门店切换：AccountSetting、SwitchAccount、SwitchBusiness 及对应 actions。
- 开发客户端连接：Expo CLI 的 `isInteractive`、`KeyPressHandler` 和 iOS Simulator 打开链；冷启动深链转交：`EXDevLauncherController` 的 pending deep link 路径。版本变化且影响当前操作时核对对应实现。
- 设备命令以 `simctl help`、`maestro --help` 为准；凭据申请和交付使用 `moe-mis` 的公开入口。
