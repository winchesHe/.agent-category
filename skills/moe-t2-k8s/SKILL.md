---
name: moe-t2-k8s
metadata:
  version: 1.0.3
description: Manage MoeGo T2/test Kubernetes in the ns-testing namespace. Use this skill when inspecting or operating the moego-development-ns-testing context, debugging pods, deployments, services, or jobs, reading logs, using exec or port-forward, restarting or deleting test workloads, applying test manifests, or verifying T2 deployments.
---

# MoeGo T2 Kubernetes

使用本 Skill 操作 MoeGo T2 Kubernetes。

默认 context 是 `moego-development-ns-testing`。
默认 namespace 是 `ns-testing`。
`T2_K8S_CONTEXT` 和 `T2_K8S_NAMESPACE` 可覆盖这两个默认值。
因此，wrapper 不是环境隔离保证。

## 工作流程

1. 操作前读取 `references/cluster.yaml`。
2. 优先使用 `scripts/t2kubectl`。
3. 从 activated `SKILL.md` 所在目录解析脚本路径。
4. 设置 `SKILL_DIR` 为 activated `SKILL.md` 所在目录，并使用：
   `"$SKILL_DIR/scripts/t2kubectl"`。
5. 先执行只读命令。
6. 写命令必须由用户明确要求。
7. 写命令设置 `T2_K8S_ALLOW_WRITE=1`。
8. 使用 selector 获取当前 Pod 名称。
9. 不使用历史输出中的 Pod 名称。

wrapper 每次调用会使用默认值或对应环境变量解析后的 context 和 namespace。
wrapper 拒绝调用方传入以下参数：

- `--context`
- `--kubeconfig`
- `-n`
- `--namespace`

wrapper 不可用时，每条 `kubectl` 命令必须显式传入：

```text
--context moego-development-ns-testing --namespace ns-testing
```

禁止依赖当前默认 context。

## kubeconfig 配置

wrapper 按以下优先级选择 kubeconfig：

1. 进程已有的 `KUBECONFIG`。
2. `T2_KUBECONFIG` 指向的专用 kubeconfig。
3. `$HOME/.kube/headlamp-moego-development-ns-testing.kubeconfig`。
4. `$HOME/.kube/config` fallback。

只在宿主环境配置 kubeconfig。
禁止把 token、证书或 kubeconfig 写入 Skill。
禁止在输出中显示完整认证配置。

## 常用命令

以下示例中的 `$T2_KUBECTL` 指向当前 Skill 的 `scripts/t2kubectl`。

```bash
SKILL_FILE='<activated SKILL.md location>'
SKILL_DIR="$(dirname "$SKILL_FILE")"
T2_KUBECTL="$SKILL_DIR/scripts/t2kubectl"
```

```bash
"$T2_KUBECTL" get pods
"$T2_KUBECTL" get deploy,svc
"$T2_KUBECTL" describe pod/<pod-name>
"$T2_KUBECTL" logs deploy/<deployment-name> --all-containers --since=30m --tail=200
"$T2_KUBECTL" logs pod/<pod-name> -c <container-name> --previous --tail=200
"$T2_KUBECTL" rollout status deploy/<deployment-name> --timeout=120s
"$T2_KUBECTL" exec deploy/<deployment-name> -c <container-name> -- <command>
"$T2_KUBECTL" port-forward svc/<service-name> <local-port>:<service-port>
"$T2_KUBECTL" auth can-i <verb> <resource>
```

写命令示例：

```bash
T2_K8S_ALLOW_WRITE=1 "$T2_KUBECTL" rollout restart deploy/<deployment-name>
T2_K8S_ALLOW_WRITE=1 "$T2_KUBECTL" delete pod/<pod-name>
T2_K8S_ALLOW_WRITE=1 "$T2_KUBECTL" apply -f <manifest.yaml>
```

删除 Deployment、缩容到零或应用多资源 manifest 前，先说明范围和影响。

## 排障流程

1. 查找资源：

   ```bash
   "$T2_KUBECTL" get deploy,svc
   ```

2. 检查 rollout 和 Pod：

   ```bash
   "$T2_KUBECTL" rollout status deploy/<deployment-name> --timeout=120s
   "$T2_KUBECTL" get pods -l app=<app-label>
   ```

3. 读取事件和日志：

   ```bash
   "$T2_KUBECTL" describe pod/<pod-name>
   "$T2_KUBECTL" logs pod/<pod-name> --all-containers --since=30m --tail=200
   "$T2_KUBECTL" logs pod/<pod-name> -c <container-name> --previous --tail=200
   ```

4. 网络排障可使用短时 port-forward。
5. 任务结束前停止长时进程。
6. 结论必须引用对应命令输出。

## 当前行为边界

当前 wrapper 行为：

- `exec`、`debug` 和 `cp` 不触发写开关。
- 未识别的 verb 不触发写开关。
- command 前的 kubectl 全局参数可能使首个 token 不是 verb，从而绕过写分类。
- `auth reconcile`、`certificate approve` 和 `certificate deny` 未进入写分类。
- `config current-context/get-clusters/get-contexts/get-users/view` 不触发写开关。
- 其他 `config` 子命令触发写开关。
- `T2_K8S_ALLOW_ALL_NAMESPACES=1` 允许 all-namespaces 参数。
- 专用 kubeconfig 缺失时使用默认 kubeconfig fallback。
- namespace 和 cluster-scoped 限制只检查已识别的写命令。
- manifest-based `apply`、`create` 和 `replace` 只检查参数文本。wrapper 无法判断 manifest 内的 namespace 或 cluster-scoped resource。

这些行为不是安全保证。
调用方仍需按真实影响确认操作。

## 安全说明

- T2 是内部测试环境，不是本地沙箱。
- wrapper 使用默认 context 和 namespace。环境变量可覆盖默认值，因此 wrapper 不是环境隔离保证。
- kubectl 权限由凭据决定。
- RBAC 会变化。异常操作前先执行 `auth can-i`。
- 不读取或输出 Secret 内容。
- 不显示 token、证书或完整 kubeconfig。
- 不连接集群时，不得把离线测试结果写成 live 验证。
