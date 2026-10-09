# Go Server

官方入口：[GrowthBook Go SDK](https://docs.growthbook.io/lib/go)。

## 版本门禁

MoeGo Go 仓库存在多个 `growthbook-golang` 版本。当前官方文档不保证与旧 lockfile API 一致。

1. 读取 `go.mod` 和 `go.sum`。
2. 查找仓库现有 GrowthBook plugin、factory 或 wrapper。
3. 用 `go doc` 或目标版本源码确认方法名。
4. 只有目标仓库升级依赖时，才使用新版本专属 API。

不要为了使用官网新示例，顺带升级 SDK。

## 生命周期

- 在 service startup 创建一个基础 client。
- 使用带 timeout 的 context 等待首次 feature load。
- 长驻服务按现有基础设施选择 polling 或 SSE。
- 在 shutdown 调用目标版本提供的 `Close` 或等价清理方法。
- 初始化失败的处理必须与服务可用性要求一致。不要直接复制 `panic`。

## 请求隔离

基础 client 只持有共享 feature data 和全局配置。每个请求用 child client 或 attribute override：

```go
func enabled(ctx context.Context, client *growthbook.Client, companyID string) bool {
	child, err := client.WithAttributeOverrides(growthbook.Attributes{
		"company": companyID,
	})
	if err != nil {
		return false
	}
	result := child.EvalFeature(ctx, "example-feature")
	if result == nil || result.Value == nil {
		return false
	}
	value, ok := result.Value.(bool)
	return ok && value
}
```

该示例对应 MoeGo 现有旧版 API 形状。目标仓库如果安装其他版本，必须改用该版本 API。

## Fallback 与类型

- boolean gate 要显式处理 `nil`、missing 和类型不匹配。
- JSON 或 string feature 先检查类型，再解析业务结构。
- fallback 必须由业务 owner 决定。权限、安全或新路径 gate 通常 fail closed。
- 记录 feature key、source 和错误类别。不要记录 client key 或敏感 attributes。

## Tracking

- 只有实验需要 exposure tracking。
- callback 不能阻塞请求主路径。
- callback 必须使用请求 context 中的稳定主体 ID。
- tracking 失败只记录 telemetry，不改变 evaluation 结果。

## Review 清单

- [ ] 已读 `go.mod`、`go.sum` 和 wrapper。
- [ ] client 在 startup 初始化，并在 shutdown 清理。
- [ ] feature load 有 timeout。
- [ ] 请求 attributes 使用 child client，不修改共享主体状态。
- [ ] missing、错误和类型不匹配有明确 fallback。
- [ ] 配置来自环境或配置中心。
