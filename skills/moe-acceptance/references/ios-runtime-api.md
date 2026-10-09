# 从现有 iOS App 发 API 请求

仅在需要复用已运行开发 App 的身份执行 API，或该通道连接、客户端调用与回读方式不明时加载。已有正确 App 和可用通道直接复用，不特意开商家 Web；纯 UI 续验不要求连接调试器。请求合同与写入范围仍按 [data.md](data.md) 判断。

## 连接目标运行环境

此路径用于可连接 Metro 主 JS runtime 的 iOS 开发 App，使用 Hermes / RN 0.77 的调试接口；Release 和其它平台须按各自可用的调试能力选择通道。复用本任务已确认的 worktree、Metro 地址、UDID、App bundle 与设备名；设备与服务归属不明时先按 [iOS 指引](ios-simulator.md) 消歧，不猜 8081 或第一个目标。

- 查询对应 Metro 的 `/json/list`，按已确认设备和 App 选择 `webSocketDebuggerUrl`；可使用现有 Node REPL 和可用 WebSocket 库连接。此处连接的是 App 的 JS runtime，Node REPL 或 Maestro 自身的 HTTP 请求不属于 App 内请求。
- 同一 App 可能暴露多个 runtime。先用 `Runtime.evaluate` 检查 `typeof __r === 'function' && typeof __r.getModules === 'function'`，再确认产品模块；不要把 worklet runtime 当主运行环境。同一目标串行复用已有调试连接，另开连接可能挤掉原连接。目标重启后可等待重新出现，但无界重连或静默重放请求不可取。
- 当前 Metro 开发包支持按 verbose module name 使用 `__r`。可从 `Array.from(__r.getModules())` 只投影模块 id/name，按当前源码定位客户端；不输出模块完整 exports、全局 store 或配置对象。历史模块数字 ID 不可复用。
- 当前 `moego-mobile` 的 `src/utils/env.ts` 可只投影 `Env.env`、`greyModule`、`apiHost`；`src/utils/http.ts` 导出初始化后的 `http`。首次或身份变化时，通过现有页面锚点及 `/business/account/v2/info` 的必要字段核对账号、Company/Business；已确认结果直接复用。

`__r` 或模块缺失时先核对实际 build、runtime 和源码合同，不猜全局变量、不抽取原生 token 拼接宿主请求。当前通道确实不可用时再选择另一条合适通道，并说明具体缺口。

## 使用产品客户端与有界回读

通过目标 runtime 调用既有 `http.open` / `http.rpc`，保留鉴权、环境、版本及响应插件。不要将 Web 相对路径、Cookie、`~c/~b` 或裸 fetch 照搬到 App。直接请求与 dispatch 业务 action 分开：后者可能更新本地 store、提前执行被测动作或掩盖缓存/跨端同步问题；按当前 Claim 选择。

直接求值使用 `.then` 处理异步结果，避免依赖 Hermes 对 `async` 语法的编译或 CDP `awaitPromise` 对产品 Promise 的等待行为。结果在 App 内先投影成必要字段，再写入临时结果槽，通过 `Runtime.evaluate` 有界轮询。

例如，已确认身份和接口合同后，下面的 **expression** 在 App runtime 中读取当前门店配置；它不更改配置，也不指定历史门店 ID。执行前确认该结果槽没有被其它动作占用，实际使用可换成本次唯一名称：

```javascript
(() => {
  const key = '__moeAcceptanceConfigQuery';
  if (Object.prototype.hasOwnProperty.call(globalThis, key)) {
    throw new Error('本次查询结果槽已占用');
  }
  globalThis[key] = { state: 'pending' };
  __r('src/utils/http.ts').http
    .open('GET/grooming/bookOnline/setting/info', {
      withoutClientNotification: true,
    })
    .then(response => {
      const b = response.data.bookOnlineInfo;
      globalThis[key] = {
        state: 'done',
        value: {
          companyId: b.companyId,
          businessId: b.businessId,
          availableTimeType: b.availableTimeType,
          autoAccept: b.autoAccept,
        },
      };
    })
    .catch(error => {
      globalThis[key] = { state: 'error', name: error?.name };
    });
  return { started: true };
})()
```

随后读取 `globalThis.__moeAcceptanceConfigQuery`。根据请求超时设置有限等待，例如每 100–250 ms 检查一次、最长 40 秒；遇到 `error`、连接断开或超时即停止并判断实际请求状态，不将其当空数据，也不自动再次提交。取得结果后删除本次槽 `delete globalThis.__moeAcceptanceConfigQuery`；未知写入结果先查后判，不能借重连重放。

RPC 的调用形状为 `http.rpc(<当前确认的完整 RPC 路径>, <当前业务参数>)`，例如已核实的业务只读 `GetStaffSelection`；其 businessId、entityId 和 entityType 必须来自本次对象及当前 schema。成功响应仍需核对实际业务归属和预期字段，客户端返回或 HTTP 200 不代替业务结论。

调试协议只消费所请求的返回，忽略无关 console/network 事件，不记录凭据或完整响应。Metro 默认可能打印请求和业务数据；调用含秘密的登录操作前处理日志输出，查询结果只保留本次必需投影。临时连接、结果槽和观察插件按本任务归属释放；恢复连接不重建健康 App、身份或服务。
