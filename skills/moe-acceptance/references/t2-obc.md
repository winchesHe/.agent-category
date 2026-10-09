# T2 OBC 本地验收

## 按当前缺口使用

适用于 `moego-online-booking-client-web` 的 T2 本地前端与远端 API 验收。仅首次准备，或 Business/name、Customer、路由、MIS 浏览器交付及共享状态恢复不明时读取相关部分。已有正确客户、页面和代码来源且上下文未变时，直接执行当前 case，不重读本文、不重新准备或登录。

新浏览器进入需要客户身份的 OBC 场景时，Vite、私有代理、浏览器及必要 MIS OBC impersonate / 客户登录属于同一次环境准备。由同一 AI 在授权范围内连续完成，再接业务验收；不是先让用户准备环境，再要求用户另行启动身份阶段。仅看未登录 landing 时不需要客户登录，但不能据此宣称已验证客户路径。

本指引用于 T2 Business landing、既有 Customer 免验证码登录和连续页面操作；新增客户、宠物、预约或消息发送按当前任务授权执行。

## 正确的 Business 与 Customer

先复用本次已确认的 worktree、T2 Host、Business、booking identifier、既有测试 Customer 与允许副作用。缺什么才查什么：从可信任务材料、当前产品路由和已授权查询中取值，不从旧文档固定手机号、默认商家邮箱或另一产品的客户登录态推导。

- `name` 是目标 Business 的 Online Booking identifier，不是商家显示名或邮箱。MIS Profile 可定位账号及候选 Business，但 booking identifier 可能为空或有歧义；已有有效入口直接复用，否则按通用的 [T2 测试数据查找与准备](data.md#t2-测试数据查找与准备)查询该 Business 的真实 booking 配置，或从可信业务链接消歧，不选第一条记录或猜拼 URL。客户输入缺失时，沿同一规则查该业务范围内的既有 Customer；已有有效客户不重复查询。
- 稳定 T2 入口线索为 `booking.t2.moego.dev`，首次入口使用 `/ol/landing?name=<已核实identifier>`。通过 URL query API 编码，打开后回读实际 Business；地址栏正确不等于命中正确商家。
- Customer 必须已存在且属于本次允许访问的范围。没有 OTP、出现 Add a pet 或 MIS 返回 active 都不足以证明目标客户已登录；同时核对产品客户信息和 Business。新客户访客分支也可能不发验证码，不能将它误判为既有客户 impersonate 成功。反过来，已核对为正确既有客户时，空宠物列表或 Add a pet 入口本身不构成身份失败，应按该客户的实际数据和本次标准判断，不为补齐列表创建宠物。
- name 缺失、错商家或客户不匹配时，暂停依赖该身份的动作，定位对应输入；不猜验证码、不创建新客户兜底，也不改前端登录状态或拦截成功响应。

资源参数齐全而业务输入尚缺时，可先准备不依赖客户的 Vite/代理；实际业务访问、身份操作前再补齐对象与授权。页面访问和登录可能伴随 session、访问统计等请求，不能将只读业务目标描述成零写入；同一明确范围的已有授权直接复用。

## 首次环境准备

### 本地页面与远端 API

先核对产品 worktree 状态、`package.json` 与实际服务归属。已知项目使用 Vite，`pnpm dev` 默认 HTTP 6001、strictPort；没有符合本次目标的服务时，可在该 worktree 选择空闲端口启动：

```bash
pnpm exec vite --host 127.0.0.1 --port <实际空闲端口> --strictPort
```

浏览器仍访问真实 T2 HTTPS Host，任务私有 Whistle 只将页面、静态模块和开发资源映射到本地 Vite。OBC 的四个 API 前缀都要保持远端：`/api`、`/moego.api`、`/moego.client`、`/moego.bff`。

```text
<实际Host> http://127.0.0.1:<Vite端口> enable://https excludeFilter://<实际Host>/api excludeFilter://<实际Host>/moego.api excludeFilter://<实际Host>/moego.client excludeFilter://<实际Host>/moego.bff
```

用当前 `w2 --help` 核实 `--baseDir`、`--storage`、`--port`、`--uiport`、`--host`、`--shadowRules` 和 `--no-prev-options`，为本任务选择独占目录和端口。浏览器通过该 proxy 工作；不改系统全局代理、开发者 `.env` 或证书校验。Vite 的内置 Grey proxy 来自 `dotenv.config().parsed.GREY`，只设置进程 `GREY` 不能保证改变 upstream；上面的远端排除规则必须由实际请求验证。

已有浏览器符合目标时复用，否则用明确的 namespace/session、私有 proxy 创建，默认 headless。按当前 `agent-browser --help` 核实参数，后续始终使用同一目标；与 MIS 子进程保持相同的实际 socket 环境。没有授权业务链接时，不提前打开真实页面。

私有代理浏览器的有效启动配置也要保持一致，包括 proxy、headed 等设置；仅 namespace/session 相同不足以保证复用。让直接调用与 MIS 子进程通过同一 `AGENT_BROWSER_CONFIG` 文件沿用有效配置，避免启动参数变化触发浏览器重启。已有配置直接沿用，不为每个 case 重建文件、重复检查或重新登录；只有配置变化或出现重启、身份失效信号时，才核实受影响的浏览器与客户上下文。

本平台不调用 `session_login.py`：它是商家 Web 顺序准备桥接，不能换个 Host 当作 OBC 登录，也不是局部修复入口。参数不明时查当前工具帮助，按当前浏览器上下文调用所需组件。

### 在同一次准备中建立客户身份

加载 `moe-mis` 的 OBC 章节并核对对应 `--help`，唯一入口为它的 `scripts/moe_mis.py`。使用 `ob-impersonate`，不使用商家账号 `impersonate`，通过公开参数选择目标浏览器。

目标浏览器和恢复路径可用、对象与权限明确后，首次准备按 MIS 现有 `status`、`start` plan 和写后回读合同继续；将该 plan 的 `expectedStateHash` 传给 `--expected-state-hash`，再使用 `--apply`。新浏览器必须实际获得对应认证交付，另一浏览器已登录或远端 active 不能代验。远端状态变化时重新核实原因，不盲目刷新 hash 重试。

使用 `--browser-session` 与 `--browser-namespace` 显式指定当次目标，并沿用相同 socket；不能省略后使用默认或 Keychain 中上次任务的浏览器。共享状态已有 active/recoveryRequired 时先核实归属，只有属于本批且操作授权清楚时才按 MIS 合同复用或 reconcile；不擅自 stop/start 接管他人的使用。

正常新浏览器交付仍走 `start` plan/apply；即使远端已 active，远端 noop 也不代表浏览器交付可以省略。`reconcile` 用于明确的中断恢复，不把它或单独的 plan 当作正常交付完成。已有健康客户 session 则两者都不重跑。

MIS 测试模式生效后，经产品 UI 输入已确认的既有 Customer，核对真实登录结果与 Business/客户上下文。当前产品既有客户分支在发送验证码结果 `success=false` 时走免验证码登录；这只是诊断线索，不允许伪造响应。出现验证码页时暂停依赖动作，不重发短信/邮件，不猜码，也不把身份准备失败直接判成待验业务功能失败。

### MIS 身份登录与恢复

使用现有 MIS 入口完成已授权的目标用户登录。Cookie 的工具内部传递方式不作为验收阻塞，也不额外要求用户确认泄露风险或先修工具。无法完成授权登录时，定位实际缺口（如 MIS 登录失效、浏览器认证交付失败、目标客户不匹配），按已有授权恢复；确需用户补充时只询问缺失的身份或授权信息。

登录成功以目标浏览器中的 Business 与 Customer 核对为准。结束时按[局部恢复与结束](#局部恢复与结束)核验恢复；清理未完成单独报告，不以远端 inactive 或工具返回成功代替浏览器恢复结果。

## 用观察决定下一步

进入正确上下文后，case 按本次标准和页面观察动态选择，不强制重放 landing、登录、宠物、下一用例的固定清单。业务结果、本地来源、路由、HMR 和恢复分别判断：

- 页面内容应与本次 Business / Customer 一致。根据 Claim 及时保存并目视检查必要业务区域，不能只用成功 toast 或 HTML 200 判通过。
- 相关实际 Vite/源码模块应对应目标 worktree。仅 Host、端口存活、import 名称或源码里存在某分支，不证明页面正在消费该代码。
- 四前缀规则均需正确，但端到端仅核对真实场景自然产生的请求，包括目标 Host、method、status、必要响应语义和页面结果；未触发的前缀记为规则已配置、端到端未验，不额外造探针补齐。
- 当前 `agent-browser network requests` / `network request` 可用于读必要请求。过滤观察，不将认证 header、Cookie、完整敏感 body 或客户隐私输出到摘要和 Git。
- 有真实源码改动时观察更新信号，在原 tab、身份与数据上复验受影响内容；没有改动不制造演示修改或声称 HMR/业务修复已验。

## 局部恢复与结束

| 当前变化 | 下一步 |
| --- | --- |
| 上下文无变化，继续当前或下一 case | 直接动作，复用有效观察与授权，不重新准备或 MIS start |
| 仅 Vite 或代理失败，客户身份仍有效 | 只恢复对应自有服务/规则，补受影响来源或请求观察，不重建身份 |
| tab/session 失效或客户身份失效 | 暂停依赖断言；定位受影响组件，按已授权恢复路径处理，再核对业务身份与当前动作前置 |
| Business/name 或客户输入不一致 | 核对输入来源和实际页面，不把问题转嫁给验证码或随机切换客户 |
| case 失败、信息不足、等待补充，但任务继续 | 保留上下文与恢复信息，不因本轮回复结束执行 stop/cleanup |
| 任务结束、取消或明确终止当前身份使用 | 按实际归属恢复 MIS，再处理自有浏览器/服务；恢复失败不能按成功收尾 |

首次创建时在当前 AcceptanceSession 保留非秘密的精确资源归属：worktree 与服务进程、Whistle 目录/端口/规则、浏览器 namespace/session/tab/socket 环境、created/reused，以及共享身份的环境、允许范围和恢复责任。不另建 manifest、租约、持久化认证池或状态机；无变化时不重新登记。

MIS 的 start 与匹配 finally stop 属于同一次授权使用范围，不是每条 case 的生命周期。确实结束时，按现有 plan/hash 合同执行 stop 或必要 reconcile，分别回读远端 inactive、目标浏览器认证残留处理和本地恢复状态。失败时保留恢复材料并说明缺口，不清空 Keychain 冒充完成，不先关闭仍需用于恢复的浏览器。

只清理本任务 created 且可精确对应的浏览器、Vite、Whistle 及临时代理目录；reused 服务、业务数据、诊断和正式证据保留。直接准备的资源未登记在商家 bridge 中，不调用 `session_login.py --cleanup`，不全局关浏览器、停代理或杀进程。共享状态不属于本批时不主动终止。

## 事实来源与验证边界

- 产品事实核查于 `moego-online-booking-client-web` 的 `9e2967d0e126f0ddbf3a14d3ab49e6b0093c089d`：`package.json`、`vite.config.ts`、`src/routes.ts`、`src/utils/name.ts`、`src/state/business/state.ts` 和 `src/hooks/useBook.ts`。实际版本变化且影响决策时核实相关部分。
- MIS 参数与状态来自现有 `moe-mis` 的命令、浏览器交付和 `ob_impersonate` 实现；身份交付与恢复以实际浏览器结果为准。
- 源码、帮助和离线样本不等于真实客户登录或恢复通过；真实结果必须绑定当次页面、目标及观察。
