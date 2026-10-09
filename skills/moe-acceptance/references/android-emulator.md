# Android 模拟器本地验收

适用于 `moego-mobile` 的 Android 原生页面与本地联调。首次准备，或设备、APK/JS 来源、身份/API 路由、原生动作和恢复有缺口时读对应部分；已有健康 App、身份与代码来源时直接续验。

## 按缺口发现环境

设备、安装包或连接信息有缺口时，按以下顺序补线索，足以继续就停止发现：

1. 当前现场：用 `adb devices -l` 发现设备，核对目标包是否安装、服务的 cwd/端口和占用归属；需要 AVD 时再查 `emulator -list-avds`。同名 AVD 可使用不同数据目录或 `-data` 镜像，默认实例没装 App 只说明该实例的状态。
2. 当前任务记录：按已有资源记录核对实际进程、文件及对应关系是否仍有效。
3. 相关工作区的已知产物目录：按项目构建配置或已有记录定位，例如 `android/app/build/outputs/apk/`。APK 常被 Git ignore，限定目录使用包含 hidden/ignored 文件的检索：`rg --files --hidden --no-ignore -g '*.apk' <已确认的产物目录>`。区分目录不存在、检索报错和没有匹配文件；一次空结果不能证明没有可用构建产物。
4. 仍有缺口且历史会话可用时，按相关仓库、任务或设备查找成功准备记录，只提取候选路径与方法，再核对当前状态。不全盘扫描用户目录；没有历史记录也可按下文新建环境、构建安装。

同任务恢复沿用归属明确且未被其它任务使用的原现场。跨任务也优先复用已有开发设备与兼容 App：核对设备是否可供本次使用、APK/JS 来源以及当前账号、Business 和 API 环境是否满足 Case；任务 ID 或分支变化本身不要求新建数据盘、重装 App 或清空数据；APK 兼容性按下方 [APK、Metro 与设备连接](#apkmetro-与设备连接) 判断。

### 选择设备与数据盘

长期开发 AVD 的默认数据盘保留已安装 App 与设置，按实际 Android 版本和设备覆盖需要复用，不按任务复制。

同一 AVD 只有在所有运行实例都以 `-read-only` 启动时才能多开。启动前核对目标 AVD 是否已有实例运行：已有可写实例（长期开发设备通常如此）时，不能再从该 AVD 启动只读或可写的第二个实例；改用其它适用 AVD，或按当前 `avdmanager` 用法创建任务私有 AVD，不为腾出 AVD 停掉其它任务或长期实例。

按当前缺口选择：

| 当前需要 | 做法 |
| --- | --- |
| 已有设备可供本次使用，App 与身份/环境满足 Case | 直接复用；缺少目标 JS 连接或产品配置时只补对应部分 |
| 需要避免改动原设备，或原现场要保留且需另一个临时实例；不要求实例关闭后恢复本次状态 | 从适用 AVD 启动 `-read-only` 临时实例，启动后核对继承的 App、身份与环境 |
| Case 要求首次安装、首次启动或干净状态，且不要求关闭后恢复 | 优先用未安装目标 App 的适用 AVD 启动 `-read-only` 临时实例，在其中完成安装与验收，退出即丢弃；不清空长期 AVD 或其它任务现场 |
| 干净状态需跨重启保留，或没有可用的干净 AVD | 使用本任务专属的新数据盘路径（`-data`，用法按 `-help-data` 核对）从初始镜像启动，启动后核对确为干净状态；不对长期 AVD 使用 `-wipe-data`，不复制旧镜像。该盘在任务结束时按下方规则清理 |
| 确需独立状态，且设备关闭后仍要恢复该任务的安装、登录或配置 | 使用任务私有可写数据盘，同任务恢复复用该盘 |

可写的任务私有数据盘一律以 `-no-snapshot-load -no-snapshot-save` 冷启动，不读写所用 AVD 的默认快照；否则可能加载与新数据盘不一致的状态，或在退出时覆盖长期 AVD 的快速启动快照。

创建任务私有 AVD、数据盘、增量文件或快照时，立即在任务记录中登记路径、基础 AVD/系统镜像、依赖和创建原因；启动 `-read-only` 实例时记录 AVD、serial 与启动时间，供异常退出后识别本次遗留的临时文件。结束清理只认已登记的资源，未登记的文件只能按归属不明保留。

不抢占占用或归属不明的设备、服务和端口，不让多个实例同时写同一数据镜像。复制旧镜像同样继承原有状态，账号、业务数据和服务端配置按 Case 单独核对。

## 设备与开发服务

默认后台启动模拟器，使用明确 serial 的 adb 或已绑定该设备的原生驱动。设备、开发客户端、Metro 和必要登录由同一 AI 按缺口准备，再继续业务 Case。

使用上方已发现且归属适用的设备与 AVD；确需临时实例时，在核对空闲端口后启动：

```bash
emulator -avd <已发现的AVD名称> -read-only -no-window -no-audio -no-boot-anim -port <空闲偶数控制端口>
adb devices -l
adb -s <已核对的serial> shell getprop sys.boot_completed
```

控制端口及相邻 adb 端口都必须空闲，合法范围按当前 `emulator -help-port` 核对。启动后从设备列表确认 serial 与目标实例的对应，不沿用历史值。`-read-only` 允许同一 AVD 的多个实例并存（前提见上方[选择设备与数据盘](#选择设备与数据盘)），退出时丢弃其修改，运行期间占用临时磁盘，异常退出后核对并清理本次遗留的临时文件；它不隔离服务端账号、业务数据或共享配置。`-no-window` 只影响显示，不等于设备已完成启动。

上表判定需要任务私有可写数据盘时，按当前 `emulator -help-datadir`、`emulator -help-data` 核对用法，再显式指定本任务路径。同任务恢复前核对原镜像及其 AVD/系统镜像是否匹配，不复制运行中的镜像。AVD、端口、内存和路径均按当前资源确定，不把历史成功参数当默认值。

`-no-snapshot-save` 只禁止保存退出快照，不能代替 `-read-only` 的磁盘改动丢弃。

`pnpm emulator-android` 对应 `scripts/start_android_emulator.sh`，当前脚本会交互选 AVD 并强停同名运行实例。需要保留已有现场时，直接复用设备或使用上面的明确启动方式，不调用该脚本重放准备。用户需要查看后台现场时先提供当前设备帧；仅有 `-no-window` 启动记录不能证明可原地打开窗口，不为展示直接结束仍需保留的实例。

缺 Metro 时在目标可编辑 worktree 使用产品 `pnpm start --port <实际Metro端口>`，保留该进程、cwd、端口和本任务私有日志的对应。脚本设置分支与 `CI_ACTION=LOCALLY_DEV`；直接调用 Expo 时不能丢掉这些产品配置。API Grey 的启动覆盖与持久化规则沿用下方产品上下文入口，已有健康 Metro 不因补参数或普通 JS 修改而重启。

## APK、Metro 与设备连接

APK 包含原生依赖，Metro 提供当前 worktree 的 JS，两者分别确认。复用候选 APK 前核对：

- 包确实具备连接本地 Metro 的开发客户端能力，例如当前构建包含 `expo-dev-client` 且有可用开发入口；文件名带 Debug 或 `debuggable` 标记不能单独证明能加载本地 JS。
- 构建来源可追溯到仓库、revision/worktree 和 variant，并结合锁文件、原生依赖与配置及构建记录判断与目标 worktree 是否兼容；几个 `package.json` 声明版本相同只作线索，不能证明 APK 内实际原生代码一致。
- 包名、签名、ABI/Android 要求与目标设备及当前安装匹配。

已有兼容开发客户端就复用。没有找到合适 APK、只有非开发包、来源无法核实或原生依赖/配置不兼容时，在当前授权内继续选择下方构建路径并定向安装，不据此结束验收。JDK、SDK、NDK 和 Gradle 版本从目标仓库配置取得，不固定为历史成功版本。

构建前读取 `pnpm exec expo run:android --help`。当前项目的 Expo CLI 有两个容易混淆的参数边界：

- `--device` 按设备名称匹配，不能把 adb 的 `emulator-<端口>` serial 直接当名称。用 `adb -s <serial> emu avd name` 核对 AVD 名，再检查 CLI 实际选择的设备。多个同名实例时，名称无法唯一定位，应将构建与定向安装分开；`ANDROID_SERIAL` 不能代替 CLI 的目标核验。
- `--no-bundler` 只跳过启动 Metro，与 `--port` 互斥，不是仅构建安装。当前 Expo CLI 仍会自动启动 App，连接端口回退到 `8081`，并对所有已连接设备写入 `tcp:8081 → tcp:8081` reverse，退出时移除该端口映射；`--device` 不限制这些转发副作用。只有目标名称唯一、Metro 确为本任务的 `8081` 服务，且所有受影响设备的该端口映射都允许本次改写和清理时，才使用 `pnpm android --device <已核对的设备名> --no-bundler`。

已有 Metro 使用自选端口、需要保留现有 reverse，或多个设备/同名实例需要定向安装时，将构建、安装与连接分开：按当前 Gradle 构建任务与 variant 生成 APK（不使用自动安装或启动任务），再用 `adb -s <serial> install -r <已核对的APK路径>` 安装，再按下方连接步骤接入已有 Metro；核对包名、安装结果及实际保留的身份。签名或版本冲突先定位，不默认卸载、清数据或降级。常规 JS 改动沿用 Metro/Fast Refresh，不能因页面失败就先重装原生包。

如果报 Reanimated 等库的 JS/native version mismatch，先核对设备上实际 APK 与目标 worktree 的原生依赖。原生包过旧时重建匹配 APK；只有确认是 JS/转换缓存不一致时才处理相应缓存。反复重启 Metro 无法替换 APK 内的原生模块，也不应为迎合旧 APK 擅改依赖版本。[Reanimated 排障](https://docs.swmansion.com/react-native-reanimated/docs/3.x/guides/troubleshooting/)

开发客户端使用 localhost 连接宿主 Metro 时，检查目标设备现有 reverse 映射，仅补本次需要的端口：

```bash
adb -s <serial> reverse --list
adb -s <serial> reverse --no-rebind tcp:<设备侧端口> tcp:<宿主Metro端口>
```

已有映射指向本次正确服务时直接复用；冲突时定位归属，不覆盖未知映射。开发客户端从实际页面选择或输入目标 Metro URL；确需用 `adb shell am start` 打开开发链接时，先核对当前包的 scheme 和开发客户端入口。这里传递的是不含凭据的项目连接地址，登录链接不能照此放入命令参数。

把设备的连接动作、目标 Metro 的打包记录与 App 加载后的页面观察关联，确认实际消费了目标 worktree。端口存活、APK 版本号、Metro ready 或 App 能打开均不能单独证明 JS 来源；源码没有变化时不制造无关文案来做证明。

## 产品身份、API 路由与数据

Android 沿用 [账号选择](account.md) 的 T2 默认账号与询问条件。已有身份符合目标就复用；账号、Company/Business 和功能资格分别判断，不因 Slack 没提供 QA 账号就跳过已配置的默认来源。

`moego-mobile` 的账号、API Grey 与 Location 使用共享产品逻辑。仅在这些操作有缺口时，复用现有文档中的 [Account](ios-simulator.md#account)、[API Grey](ios-simulator.md#api-grey) 和 [biz location](ios-simulator.md#biz-location) 产品入口；设备动作仍绑定 Android serial。启动 Grey 前确认目标 worktree 包含 `src/entry/init/initEnv.ts` 的 `EXPO_PUBLIC_MOE_GREY` 实现，按该节核对开发态、启动覆盖与菜单切换条件。不要从旧分支的参数名推断其已经生效。

缺登录态时通过产品登录/切换入口和 `moe-mis` 公开能力处理。凭据仅经已核实的安全通道交付，不放进 adb argv、动作文件、日志或截图；没有安全交付能力时说明具体缺口。Android 不使用商家 Web 的 `session_login.py`。现有 `ios-runtime-api.md` 也不自动成为 Android 调试连接合同；需要 App 内 API 时先核对当前 runtime、产品请求客户端和返回结果，再复用适用通道。

开发客户端到 Metro 与业务 API 到 T2/Grey 是两条连接。后端修复验收复用 [实际消费入口核验](repair-and-retest.md)：将本次请求的时间、可关联标识和服务端观察对应到目标部署的镜像/commit。API ENV 显示、Grey 名称或部署成功不能代替实际流量命中；证据已确认且条件未变时无需重复检查。

数据准备沿用 [data.md](data.md)，优先当前已就绪且身份匹配的 App 请求通道。API 可创建必要测试前置，Case 要验证的交互仍由真实 UI 执行；额外主动查询与某次点击自然产生的请求分别说明。操作、通知和后续付款等写入按本次授权范围执行。

## 原生动作与设备帧

按当前设备画面、可访问控件或 hierarchy 定位，再使用绑定 serial 的原生动作。adb 坐标输入只用于当前已检查设备帧中的位置，页面或尺寸变化后重新定位，不保存通用业务坐标。动作返回后检查实际页面/接口结果；结果不明的提交先回读，不盲目重放。

截图采集使用明确设备：

```bash
adb -s <serial> exec-out screencap -p > <本次证据的绝对路径.png>
```

保存后读取真实尺寸并目视检查目标对象、结果与隐私，再改变现场。Android 设备帧不套浏览器移动 viewport；报告尺寸、`capture_mode` 和裁剪范围按实际来源及现有字段合同填写。日志与 hierarchy 可能包含账号、客户或开发配置，先限定必要字段，不把完整诊断输出加入报告。通用采证与归属沿用 [evidence-capture.md](evidence-capture.md)。

## 局部恢复与结束

恢复仍受阻时，按主文件的[继续、暂停与结束](../SKILL.md#继续暂停与结束)判断下一步，保留实际结果及剩余路径的失败或排除依据。

| 触发信号 | 下一步与恢复边界 |
| --- | --- |
| 首次构建正在下载 SDK/NDK/Gradle 依赖 | 查看对应构建进程和新增日志、下载进展；有持续进展就等待，不仅因耗时长而重启。明确缺包、网络或构建错误后只处理该缺口，不默认清空缓存或更换版本 |
| 设备在线但 App 无法连接 Metro | 核对该设备的 URL、reverse 映射与目标进程；只恢复连接或自有服务，保留有效身份和数据 |
| 原生库与 JS 版本不匹配 | 按上方 APK/JS 判断处理实际不一致项，再恢复受影响页面前置 |
| 日期相关 Case 不符、会话/证书时间异常或设备显示明显旧日期 | 用 `adb -s <serial> shell date -u` 与当前 UTC 对照，区分时钟偏差和业务时区；只在本任务设备上按支持能力校准。没有校时权限时说明限制，不默认 root、改宿主时间或重建 AVD |
| JS 更新、身份或 API 环境变化 | 核对实际变化并恢复受影响的动作前置，再复验相关 Case；保留仍有效的结果 |
| Case 不通过或等待输入，整个任务仍继续 | 保留设备、Metro 与证据，从当前缺口续接 |

恢复确有需要时，按主文件的[连续上下文](../SKILL.md#连续上下文)更新已有任务记录中的最小无秘密信息：serial/AVD 与数据目录/镜像路径、APK 来源与路径、worktree/Metro、必要启动或连接参数及资源归属。不公开数据镜像。

整个任务结束或取消时，按主文件规则只结束本次创建的进程与实例；自有模拟器可用 `adb -s <serial> emu kill`，复用设备保留。只移除本次创建且仍属本次的 reverse 映射，不执行全局 adb server 重启、批量杀模拟器或清理业务数据。结束后回读目标状态，保留证据和必要诊断。

任务私有 AVD 与数据盘属于运行资源，不是正式验收证据。

- **保留**：任务仍继续、暂停待复验，或运行环境仍承担交付用途。
- **清理**：正常结束或取消且无接续用途时，先确认目标实例已退出、文件无进程占用、其它设备/快照/镜像不依赖它，再删除已登记自有的私有数据盘、增量文件（如 `.qcow2`）、不再需要的任务私有快照，以及任务私有 AVD（用法按当前 `avdmanager` 核对）。先识别依赖关系，不单删仍被增量镜像引用的底层镜像，不按文件年龄批量删除。
- **始终保留**：长期 AVD 的默认数据盘、已安装 App、复用资源、正式证据和必要诊断。
- **受阻**：路径或依赖归属不明、删除失败时保留相关文件，记录具体阻塞与实际清理结果；停机成功不能代替磁盘清理完成。

## 核对入口

- 产品：目标 worktree 的 `package.json`、`scripts/start_android_emulator.sh`、`app.config.ts`、`android/build.gradle`、`android/app/build.gradle`、`src/entry/init/initEnv.ts` 和账号/开发设置实现。
- 工具：当前 `adb --help`、`emulator -help`、`pnpm exec expo run:android --help`；参数行为有歧义时核对该安装版本的 Expo CLI 实现。
- 平台：[Android Emulator 命令行](https://developer.android.com/studio/run/emulator-commandline)、[adb 设备操作与截图](https://developer.android.com/tools/adb)、[Expo 开发构建](https://docs.expo.dev/develop/development-builds/introduction/)、[Expo 本地构建](https://docs.expo.dev/guides/local-app-development/)。
