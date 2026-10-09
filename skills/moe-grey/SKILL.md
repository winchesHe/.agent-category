---
name: moe-grey
description: >-
  通过 scripts/moe_grey.py 查询和管理 MoeGo Grey 规则、namespace、服务分支与 service mapping，支持带 snapshot、并发校验、精确确认和写后回读的 plan/apply CRUD。触发关键词：Grey、灰度规则、服务分支、svcBranchMap、Grey CRUD。不触发：MIS 登录、账号、OB session 或 Metadata。
---

# MoeGo Grey

## 前置条件

- Python 3.9+，通过 `uv run --script` 自动安装 `requests`。
- 无需 SSO 或 `.env`；Grey endpoint、默认 namespace 和 timeout 使用内置值，单次命令可用 `--namespace` 指定 namespace。

## 脚本位置

```bash
uv run --script scripts/moe_grey.py <全局参数> <subcommand>
```

## 子命令速查表

| 子命令 | 作用 | 必填 flag |
|---|---|---|
| `list` | 列出规则 | 可选 `--namespace` |
| `get` | 读取单条规则 | `--id` 或 `--name` |
| `branches` | 列出服务分支 | 可选 `--namespace`、`--service` |
| `create` | 规划或创建规则 | `--name`、至少一个 `--service repo=branch` |
| `copy` | 规划或复制规则 | `--from-id`/`--from-name`、`--name` |
| `update` | 规划或更新规则 | `--id` 或 `--name` |
| `delete` | 规划或删除规则 | `--id` 或 `--name`；apply 时还需 `--confirm` 与快照 |

## 通用 flag

- `--format json|human|summary`，默认 `json`。JSON 只写 stdout，其余输出写 stderr。

## 场景决策树

1. 找规则：`list` 后用 `get` 精确读取。
2. 找可用服务或分支：`branches`；由 GitHub 仓库/PR 推导时还要加载 service mapping。
3. 创建、复制、更新、删除：默认自主完成当前任务所需操作，无需用户额外授权。先运行无 `--apply` 的 plan，核对目标、差异与 snapshot 后直接 apply 并回读。
4. 参数、service ID 或规则身份不确定：先查询规则、分支及 service mapping；只有查证后仍无法确定配置方案时，才说明具体缺口和可行选项，请用户确认或授权所选方案。

## 领域知识

- UI 仓库名不一定等于 `svcBranchMap` key；根据 PR 配置 Grey 前必须使用 service mapping。
- update/delete apply 必须复用 plan 返回的 `expectedUpdatedAt`；delete 还要传与规则名完全一致的 `--confirm`。

## NEVER 规则

- 不在未查看 plan 时直接 apply。
- 不违反用户明确的只读或禁止写入限制，不在目标、范围或配置方案仍不明确时 apply，不猜测参数或规则身份。
- 不跳过 snapshot、并发校验、精确确认或写后回读。
- 不用真实 Grey mutation 做自动冒烟测试。

## 错误处理

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 参数错误 |
| 3 | 认证或权限错误 |
| 4 | API 或业务错误 |
| 5 | HTTP 超时 |

## 示例

```bash
uv run --script scripts/moe_grey.py list --namespace ns-testing
uv run --script scripts/moe_grey.py get --name <rule-name>
uv run --script scripts/moe_grey.py branches --service <service-id>
uv run --script scripts/moe_grey.py create --name <name> --service <service-id>=<branch>
uv run --script scripts/moe_grey.py copy --from-name <source> --name <target>
uv run --script scripts/moe_grey.py update --name <name> --description <description>
uv run --script scripts/moe_grey.py delete --name <name>
```

## References

- [references/grey.md](references/grey.md)：执行查询或 CRUD 时加载完整字段、plan/apply 和失败处理。
- [references/grey-service-mapping.md](references/grey-service-mapping.md)：由 GitHub 仓库、PR 或前端项目名配置 Grey 时加载。
