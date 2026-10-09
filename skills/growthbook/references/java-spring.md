# Java Spring

官方入口：[GrowthBook Java SDK](https://docs.growthbook.io/lib/java)。

## MoeGo 首选路径

MoeGo Java 服务优先使用 `moego-lib-feature-flag`。该 wrapper 统一处理 Spring auto-configuration、feature repository 和 `FeatureFlagContext`。

只有以下情况才直接接官方 SDK：

- 目标仓库不能使用内部 wrapper；
- wrapper 缺少已确认的必要能力；
- wrapper owner 已确认扩展方向。

不要在业务服务内复制 wrapper 的 feature fetch 和 context 构造。

## 前置检查

1. 读取 `build.gradle`、version catalog 或 Maven dependency lock。
2. 确认内部 wrapper 版本和传递的官方 SDK 版本。
3. 查找 `FeatureFlagApi`、`FeatureFlagContext` 和现有 feature enum。
4. 核对 JitPack repository 是否已由平台层配置。
5. 对照当前官方 Java 文档，但以安装版本 API 为准。

## Spring 使用方式

业务类注入内部 `FeatureFlagApi`。每次 evaluation 创建请求级 context：

```java
boolean enabled = featureFlagApi.isOn(
    FeatureFlags.EXAMPLE_FEATURE,
    FeatureFlagContext.builder()
        .company(companyId)
        .business(businessId)
        .build()
);
```

- feature key 放进目标仓库现有 enum 或 registry。
- company、business、enterprise 等 ID 按 wrapper 约定转成 string attributes。
- 额外 attributes 通过 wrapper 的扩展字段传入。
- 不要把 request context 放进 singleton mutable field。

## Fallback 与 tracking

- wrapper 返回值 API 必须收到同类型 default。
- repository 未加载、feature 缺失或反序列化失败时，使用业务定义的 fallback。
- 实验需要 tracking 时，优先扩展内部 wrapper。不要在每个业务服务重复 callback。
- tracking callback 要线程安全，并且不能抛出到业务请求。

## 配置与安全

- SDK API host 和 client key 从 Spring 配置绑定读取。
- 不在 `application-*.yaml` 示例中提交真实环境值。
- client key 不是 Management API token。不要混用两类凭据。
- JitPack 是供应链入口。新增或升级版本前检查 tag、checksum 和内部依赖策略。

## Review 清单

- [ ] 已优先复用 `moego-lib-feature-flag`。
- [ ] 已核对 wrapper 和官方 SDK 的实际版本。
- [ ] context 为请求级数据，不进入 singleton mutable state。
- [ ] feature key 使用现有 enum 或 registry。
- [ ] fallback 类型正确。
- [ ] 配置值未写入代码或文档。
