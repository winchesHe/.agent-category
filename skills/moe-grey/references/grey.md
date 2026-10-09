# Grey 操作参考

## 鉴权现状

`https://grey.devops.moego.pet` 当前 Grey RPC list 接口可匿名读取，但这是服务现状，不是永久契约。CLI 不伪造凭证；若服务以后返回 401/403，应停止并按新的官方鉴权方式扩展。

## 只读命令

```bash
uv run --script scripts/moe_grey.py list --namespace ns-testing
uv run --script scripts/moe_grey.py get --id 123
uv run --script scripts/moe_grey.py get --name rule-name
uv run --script scripts/moe_grey.py branches --namespace ns-testing
uv run --script scripts/moe_grey.py branches \
  --namespace ns-testing --service moego-web-api
```

根据 GitHub PR 配置 Grey 时，必须同时读取
[grey-service-mapping.md](grey-service-mapping.md)。Grey API 使用部署 service
ID，UI 显示 GitHub 仓库名；例如：

- `Boarding_Desktop` → `moego-web-api`
- `moego-api-definitions` → `moego-api-docs`
- `moego-server-grooming` → `moego-service-grooming`

先完成映射，再用 `grey branches --service <service-id>` 验证 PR 分支。不得直接用
仓库原名查询后，因结果为空就跳过该 PR。

## Mutation 门禁

create/copy/update/delete 默认不写入，只返回：

- `mode: plan`
- `before` / `after`
- 原始 snapshot
- update/delete 所需 `expectedUpdatedAt`

按 [SKILL.md 的场景决策树](../SKILL.md#场景决策树) 核对 plan 后执行 `--apply`。update/delete 会在写入前再次读取规则并比较 `updatedAt`，发生并发更新时退出。delete 还要求 `--confirm` 与规则名称完全一致。

Grey delete 是软删除：成功后按 ID 可能仍返回带 `deletedAt` 的历史记录；按名称应
返回 404，且 namespace list 中不再出现该规则。不要把 ID tombstone 误判为删除失败。

```bash
# create plan
uv run --script scripts/moe_grey.py create \
  --name example --service moego-web-api=feature-example

# update plan / apply
uv run --script scripts/moe_grey.py update \
  --name example --description "new description"
uv run --script scripts/moe_grey.py update \
  --name example --description "new description" \
  --expected-updated-at "<plan timestamp>" --apply

# delete plan / apply
uv run --script scripts/moe_grey.py delete --name example
uv run --script scripts/moe_grey.py delete --name example \
  --expected-updated-at "<plan timestamp>" --confirm example --apply
```

服务分支参数可重复：`--service repo=branch`。创建、复制、更新会先通过 `GetServiceBranchMap` 校验映射。

## 风险约束

- 不得用真实 mutation 做测试。
- delete 的 snapshot 应保留在任务结果中，便于人工恢复。
- delete 验证以 `deletedAt` tombstone + 名称不可见，或 ID 直接 404 为成功。
- 从 PR 生成规则时，plan 必须同时展示 UI 仓库名、底层 service ID 和 PR 分支，方便用户核对。
