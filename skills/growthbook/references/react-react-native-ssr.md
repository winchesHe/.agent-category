# React、React Native 与 SSR

官方入口：[React](https://docs.growthbook.io/lib/react)、[React Native](https://docs.growthbook.io/lib/react-native)、[JavaScript](https://docs.growthbook.io/lib/js)。

## 先读目标仓库

1. 读 `package.json` 和实际 lockfile。
2. 查找 `@growthbook/growthbook-react`、`@growthbook/growthbook` 和内部 wrapper。
3. 查找现有 Provider、初始化入口、attributes setter、tracking 和测试。
4. React Native 还要查 storage、SSE polyfill 和 native feature bridge。
5. SSR 还要查服务端 payload、序列化边界和 hydration 流程。

MoeGo 前端存在多个 SDK 版本和多种 wrapper。不要假设任意两个仓库的 API 相同。

## React Browser

- 在 app lifecycle 创建并初始化一个 `GrowthBook` 实例。
- 把实例交给现有 `GrowthBookProvider`。不要在组件 render 中创建实例。
- 登录态变化时更新完整 attributes。登出时清除用户 attributes。
- `useFeatureIsOn` 用于 boolean flag。其他值使用同类型 fallback。
- 初始化未完成时，使用项目已有 loading 或 fallback 策略。不要让 UI 在错误默认值与真实值间闪烁。
- SPA route 参与 targeting 或 Visual Editor 时，在 route change 后更新 URL。
- 实验接现有 analytics。tracking callback 不能抛出到业务组件。

版本边界：`init`、`loadFeatures`、`setAttributes`、`updateAttributes`、plugin 和 tracking callback 参数会随版本变化。生成代码前必须核对 lockfile 和对应版本类型。

## React Native

- 复用 app 级 client。不要为 screen 或 hook 创建新 client。
- 初始化前配置目标版本需要的 storage 或 SSE polyfill。
- 持久化匿名 ID。登录后补充稳定的 account、company、business 等 attributes。
- logout 或 tenant 切换时清除旧 attributes，避免跨账号命中。
- App 卸载订阅或 listener 时执行 cleanup。
- 网络或 feature payload 不可用时，按业务 gate 的安全方向返回 fallback。
- Client SDK payload 位于设备端。不要把敏感 targeting 规则当成保密数据。

MoeGo 代码可能把 SDK evaluation 同步给 native feature bridge。修改初始化或 attributes 时，必须检查 bridge 的同步时机和 fallback。

## SSR 与 hydration

SSR 的目标是：服务端首屏与客户端第一次 render 使用相同 payload 和相同 attributes。

推荐流程：

1. 每个 SSR request 创建独立实例或独立 request context。
2. 从已验证的 request header、cookie 或 session 构造 attributes。
3. 设置 feature fetch timeout。失败时返回明确 fallback。
4. 服务端评估后，序列化允许下发的 payload 和 attributes。
5. 客户端用该 payload 同步初始化，再挂载 Provider。
6. hydration 完成后再启动 streaming 或 refresh。
7. request 完成后销毁服务端实例。

```ts
async function getGrowthBookRenderData(
  attributes: Record<string, string>,
  payloadLoader: () => Promise<object>,
) {
  const payload = await payloadLoader();
  return { attributes, payload };
}
```

代码只说明数据边界。目标仓库应复用现有 `initSync`、payload 类型和序列化方法。

## Attributes

- attribute key 和类型必须匹配 GrowthBook 配置。ID 通常转成 string。
- 使用稳定 ID 做实验 bucketing。不要在每次 render 生成新 ID。
- 不要把 token、完整 session、未哈希的 secure attribute 写进日志。
- MoeGo 历史字段可能包含拼写兼容。先读目标仓库和 GrowthBook attributes，再决定是否保留双写。
- SSR header 只能来自可信代理或服务端 session。不要直接信任外部请求伪造的 tenant ID。

## Tracking

- feature gate 不等于 experiment exposure。只有进入实验时记录 exposure。
- 记录 experiment key、variation 和必要的稳定主体 ID。
- tracking 必须去重或遵循 SDK callback 语义。
- analytics 失败不能改变 feature 结果。
- SSR tracking 需明确在 server 还是 hydration 后 client 发送，避免重复。

## Review 清单

- [ ] 已读 lockfile 和现有 wrapper。
- [ ] client 生命周期与 app lifecycle 一致。
- [ ] tenant、登录和登出时 attributes 不串数据。
- [ ] SSR payload 和 attributes 保持 hydration 一致。
- [ ] fallback 类型与 feature 类型一致。
- [ ] tracking 不重复，不泄露敏感 attributes。
- [ ] endpoint、client key 和 decryption key 未写入代码。
