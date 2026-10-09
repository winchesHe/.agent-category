# 本地 gRPC 调试

- ID：`MDEV-GRPC-DEBUGGING`
- 适用：MoeGo 服务的 Pod 转发、协议与请求排查，以及调用方和下游结果对照。

## 选择 Kubernetes 入口

先确认目标环境。T2 的资源查询、日志与端口转发优先使用 `moe-t2-k8s`：从当前 Host 的可用 skill catalog 定位其实际 `SKILL.md`，读取该文件及其 `references/cluster.yaml`，再从 activated 文件所在目录解析脚本；不能从开发或经验 skill 的相邻目录、历史 checkout 路径推导。

```bash
T2_SKILL_FILE='<当前 Host catalog 中 moe-t2-k8s 的实际 SKILL.md 绝对路径>'
T2_KUBECTL="$(dirname "$T2_SKILL_FILE")/scripts/t2kubectl"
test -x "$T2_KUBECTL"
```

仅在路径已确认且检查成功后执行下文命令。catalog 未提供该 skill，或脚本缺失/不可执行时，说明缺少运行时依赖并停止 T2 集群调用；可继续本地协议、源码等独立检查。不要自动安装、复制或创建替代 wrapper，也不自动回退裸 `kubectl`；缺入口不代表缺集群权限。

保留 Host 已有的 `KUBECONFIG` / `T2_KUBECONFIG`，由 wrapper 按该 skill 的契约选择专用、Headlamp 或默认 kubeconfig；不要先用裸 `kubectl config get-contexts` 判断 T2 未配置。核对 `T2_K8S_CONTEXT` / `T2_K8S_NAMESPACE` 的有效值与本次目标一致，wrapper 的默认范围可被它们覆盖。调用参数不传 `--context`、`-n`、`--namespace` 或 `--kubeconfig`，这些参数会被 wrapper 拒绝；查询和转发也不需要设置写开关。

仅当目标明确为非 T2 时，按该环境规则确认配置与授权，将下文命令中的 `"$T2_KUBECTL"` 前缀换成 `kubectl --context '<已确认的context>' --namespace '<已确认的namespace>'`；不为其他环境设置 T2 wrapper 的覆盖变量，也不依赖当前默认 context。

## 选择目标与端口

只检查已部署 RPC 时，可用 `grpcurl → port-forward → 目标 Pod`，无需在本机启动整套应用。直连验证的是该 Pod；经过 BFF/Grey 的调用还需另行验证。

完成上述入口与有效范围核对后，再查目标服务 Pod，核对应用容器、镜像及版本。端口从实际 Service 与应用监听配置获取，不假定所有服务都是 9090。以下为 T2 示例：

```bash
"$T2_KUBECTL" get svc '<service>' -o yaml
"$T2_KUBECTL" get pods -l '<已确认的selector>' -o wide
"$T2_KUBECTL" get pod '<pod>' -o jsonpath='{.metadata.labels}{"\n"}{.spec.containers[*].name}{"\n"}{.spec.containers[*].image}{"\n"}{.status.containerStatuses[*].imageID}{"\n"}'
```

从 Service 的实际 selector 选择 Pod，不默认所有部署都使用 `app=<服务名>`；无 Service 时按部署资源的真实标签定位。保持下面的转发进程运行；Pod 重建后重新选目标，修改本地端口后同步客户端地址。

```bash
"$T2_KUBECTL" port-forward \
  --address 127.0.0.1 'pod/<pod>' '19090:<实际gRPC端口>'
```

转发建立不能证明服务能处理请求，还要执行真实 RPC。验证结束后停止本任务的转发进程。

## 使用对应版本的完整协议

Go 大仓协议从 `backend/proto/` 查起；外部下游从调用方的 import、依赖清单和锁文件定位协议版本，不能直接用最新 main 替代它。沿真实客户端调用找到完整 `package.Service/Method`，在对应 Buf 模块中生成 descriptor：

```bash
RPC_DEBUG_DIR=$(mktemp -d)
buf build --path '<service.proto相对路径>' \
  --as-file-descriptor-set -o "$RPC_DEBUG_DIR/rpc-descriptor.pb"
grpcurl -protoset "$RPC_DEBUG_DIR/rpc-descriptor.pb" list
grpcurl -protoset "$RPC_DEBUG_DIR/rpc-descriptor.pb" describe '<完整服务名>'
grpcurl -protoset "$RPC_DEBUG_DIR/rpc-descriptor.pb" describe '<完整请求类型>'
```

`list/describe` 在这里读取本地文件，没有访问服务端。reflection 未开启时使用 descriptor 即可；不要删除 proto 的依赖或校验注解来凑编译通过。

## 区分网格路由与应用上下文

先从调用方构造 metadata 的位置，沿拦截器、filter 和应用入口检查到服务端的读取与校验。Go 大仓可定向搜索：

```bash
rg -n 'x-moe-company-id|gv-|APP_VERSION|FromIncomingContext' backend/common 'backend/app/<app>'
```

| 上下文 | 要核对什么 |
|---|---|
| 租户，如 `x-moe-company-id` | 方法从 metadata、body 还是其他上下文读取；测试对象是否属于同一租户 |
| 服务版本，如 `gv-<部署服务名>` | 哪一跳使用该头、对应哪个部署服务，以及目标版本的实际值 |
| 应用内路由校验 | 直连是否仍校验版本、是否允许缺省值、是否拒绝重复头；按应用代码判断 |
| 认证与其他必填 metadata | 真实调用方如何提供，哪些由网关补入；不能把网关请求直接等同于内部 RPC |

port-forward 直连 Pod 可以绕过网格选路，应用内的校验仍然运行。通过 `moe-grey` 查询服务版本和路由；若应用使用 `APP_VERSION`，与目标 Pod 的实际值对应。不能仅根据基础/feature 名称推导所有服务相同的头要求。

## 先用读取方法确认请求

在上一步临时目录中，根据 describe 与实际调用代码准备 `rpc-request.json`，后续命令复用同一个 `RPC_DEBUG_DIR`。方法、字段层级、租户上下文和认证分别核对：BFF JSON 不一定等于 RPC JSON，同名查询方法也可能有不同请求结构。int64 ID 用 JSON 字符串，避免经过 JavaScript 时丢精度。

```bash
# 适用于转发到明文 gRPC 监听端口；TLS 端口按实际配置连接。
# metadata 按上一节核对的要求增加 -H '字段: 值'。
grpcurl -plaintext -connect-timeout 5 -max-time 30 \
  -protoset "$RPC_DEBUG_DIR/rpc-descriptor.pb" \
  -d @ 127.0.0.1:19090 '<完整服务名>/<读取方法>' < "$RPC_DEBUG_DIR/rpc-request.json"
```

例如方法确实读取公司 metadata 时，在命令中增加 `-H 'x-moe-company-id: <测试公司ID>'`；需要指定某一服务版本时，增加该服务要求的 `-H 'gv-<部署服务名>: <实际版本>'`。每个需要的字段各传一次，body 不能替代 metadata。

响应可解码后，继续判断它是否符合这条测试数据的业务含义。写入型或异步接口超时时，先查询是否已经受理再重试；成功受理也要继续验证最终结果。

## 调用方结果与来源不一致

从实际 Reader、客户端或代理定位下游方法和协议版本，用同一租户、业务对象、环境与目标版本直连对照。不要因为实现曾放在某个应用内，就把该应用本地表当作权威数据源。

来源有数据而调用方结果为空时，依次检查请求结构、身份边界、过滤条件、状态与时间窗口。先解释原测试对象的差异，不通过换一条能成功的数据结束排查。

## 常见现象

| 现象 | 下一步 |
|---|---|
| 转发建立但调用 connection refused | 查实际监听端口、容器启动日志和服务配置 |
| reflection 不支持 | 使用对应版本 descriptor |
| unknown field | describe 请求类型，核对是否混用了 BFF、另一个 RPC 或旧协议 |
| Unimplemented | 核对完整服务名、目标镜像与注册入口 |
| 缺少租户或路由不匹配 | 查该方法的 metadata 提取与校验逻辑 |
| 直连成功、BFF 失败 | 查 BFF 路由、客户端版本、每跳路由与服务发现 |
| proto HTTP annotation 对应地址 404 | annotation 不保证已配置外部网关，先确认真实暴露入口 |

需要继续查异步链路时，使用[日志](business-chain-logging.md)、[Kafka](kafka-debugging.md)或[数据库](database-debugging.md)中的对应方法。
