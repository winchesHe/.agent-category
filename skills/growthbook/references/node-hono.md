# Node Server 与 Hono

官方入口：[GrowthBook Node.js SDK](https://docs.growthbook.io/lib/node)。

## 先读目标仓库

1. 读取 `package.json` 和实际 lockfile。
2. 查找 `GrowthBookClient`、初始化入口和 request middleware。
3. 查找现有 context builder、feature enum 和 fallback 测试。
4. 对照安装版本类型。不要把当前官网方法名套到旧版本。

## Process client

- 在 server startup 创建一个 `GrowthBookClient`。
- 等待 `init`，并设置有界 timeout。
- 长驻进程按现有基础设施选择 polling 或 streaming。
- 在 shutdown 执行目标版本提供的 cleanup。
- 不要在每个 Hono handler 重建 client 或重复下载 feature payload。

```ts
type GrowthBookUserContext = {
  attributes: Record<string, string>;
};

function buildUserContext(input: {
  accountId?: string;
  companyId?: string;
}): GrowthBookUserContext {
  return {
    attributes: {
      ...(input.accountId ? { id: input.accountId } : {}),
      ...(input.companyId ? { company: input.companyId } : {}),
    },
  };
}
```

## Hono 请求隔离

- middleware 从已验证的 auth context 构造新的 user context。
- middleware 把 context 放进当前 Hono request context。
- handler 把该 user context 传给共享 client。
- 不要调用共享 client 的 mutable attribute setter 保存请求用户。
- tenant 切换和 impersonation 必须从当前 auth context 重新构造 attributes。

MoeGo BFF 已有 request context builder 和 middleware。新代码应复用现有入口。

## Fallback 与错误

- `isOn` 用于 boolean gate。其他类型使用同类型 fallback。
- feature load timeout、missing feature 和 evaluation error 分开记录。
- fallback 由业务风险决定，不由 SDK 默认决定。
- 日志只记录 feature key、fallback 原因和 request correlation id。
- 不记录完整 user context、client key 或 secure attributes。

## Tracking

- 把 tracking callback 配在 process client 或现有 analytics adapter。
- callback 使用 SDK 传入的当前 user context。
- callback 失败不能抛出到 Hono request。
- 测试同一进程并发两个 tenant，确认 attributes 不串数据。

## Review 清单

- [ ] 已读 lockfile 和现有 BFF wrapper。
- [ ] process client 只初始化一次。
- [ ] Hono middleware 每次请求创建新 context。
- [ ] handler 不修改共享 user attributes。
- [ ] fallback 和错误类别明确。
- [ ] tracking 使用当前请求 context。
- [ ] 配置来自环境或配置中心。
