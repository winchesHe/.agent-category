# Grey Service ID 与 UI 仓库名映射

## 核心事实

Grey API 的 `svcBranchMap`、`GetServiceBranchMap` 使用部署 service ID。
Grey Web UI 为方便选择 PR 分支，会把 service ID 转成 GitHub 仓库名显示。
不要把 UI 文本直接当作 API key，也不要因为 API 列表没有仓库原名就判断
该仓库不能配置 Grey。

映射事实源：
`MoeGolibrary/moego-grey-gateway/web/src/utils.ts#getProject`。

## 显式映射

| UI / GitHub 仓库名 | Grey service ID |
|---|---|
| `Boarding_Desktop` | `moego-web-api` |
| `moego-client-web` | `moego-web-client` |
| `OnlineBooking_Go_Web` | `moego-web-ob` |
| `moego-online-booking-client-web` | `moego-web-ob-client-v3` |
| `MoeGo_Website` | `moego-web-official` |
| `moego-api-definitions` | `moego-api-docs` |

## 通用映射

Grey UI 将 `moego-service-<domain>` 显示为
`moego-server-<domain>`。反向配置时：

```text
moego-server-<domain> -> moego-service-<domain>
```

例如：

```text
moego-server-grooming -> moego-service-grooming
```

其他名称默认保持不变，但仍必须通过 `grey branches --service <service-id>`
确认 service ID 和目标分支真实存在。

## 从关联 PR 生成 Grey 的流程

1. 从主 PR body、issue key 和 GitHub 搜索取得全部关联 PR。
2. 记录每个 PR 的仓库名和 `headRefName`，只处理当前任务确实相关的 PR。
3. 按本 reference 把仓库名反向转换成 Grey service ID。
4. 对每一项运行：

   ```bash
   uv run --script scripts/moe_grey.py branches \
     --namespace ns-testing --service <service-id>
   ```

5. 确认返回列表包含 PR 的 `headRefName`；缺失时停止，不猜分支。
6. 使用底层 service ID 生成 `grey create` plan。UI 回读时显示仓库名是正常行为。
7. 检查 name、namespace、全部仓库/PR/service/branch 映射，再按
   [SKILL.md 的场景决策树](../SKILL.md#场景决策树) 执行 `--apply`。

## GRM-2164 示例

| PR 仓库 | Grey service ID | 分支 |
|---|---|---|
| `Boarding_Desktop` | `moego-web-api` | `feature-grm-2164-excluded` |
| `moego-api-definitions` | `moego-api-docs` | `feature-grm-2164-excluded-services` |
| `moego-api-v3` | `moego-api-v3` | `feature-grm-2164-excluded-services` |
| `moego-svc-order` | `moego-svc-order` | `feature-grm-2164-excluded-services` |
| `moego-server-grooming` | `moego-service-grooming` | `feature-grm-2164-obc` |
| `moego-svc-appointment` | `moego-svc-appointment` | `feature-grm-2164-excluded-services` |

示例用于说明映射方式；实际操作仍需实时读取 PR 和 Grey branches，不能把示例当作永久分支状态。
