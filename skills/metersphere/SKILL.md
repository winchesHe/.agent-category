---
name: metersphere
description: >-
  通过 MeterSphere API 管理测试资产，唯一 Python 入口为 scripts/metersphere.py。用于测试用例/测试 case/TC 的搜索、详情、创建、编辑、删除、批量导入，以及功能模块、用例评审、关联缺陷和 OpenAPI 接口用例场景。所有 CRUD 默认使用 API；浏览器仅用于用户明确要求的视觉检查。
---

# MeterSphere

## 前置条件

- Python 3.9+
- `openssl`
- 在进程环境、`METERSPHERE_ENV_FILE` 指定文件、当前目录 `.env` 或 skill 根目录 `.env` 中配置 API 凭证；优先级依次降低。
- 从 `.env.example` 复制配置模板，不提交真实 `.env`。

先运行：

```bash
python3 scripts/metersphere.py doctor
```

`doctor` 只返回配置是否存在、实际加载的 `.env` 路径、连通性和能力开关，不输出密钥。

## 脚本位置

唯一 Python CLI：

```bash
python3 scripts/metersphere.py [--format json|human|summary] <resource> <action> [args...]
```

旧命令 `./scripts/ms.sh ...` 仅作为兼容转发。

## 子命令速查表

| 子命令 | 作用 | 必填参数 |
|---|---|---|
| `doctor` | 检查配置、连通性与能力 | 无 |
| `organization list` | 列组织 | 无 |
| `project list` | 列项目 | 无 |
| `functional-module list` | 模块树 | `projectId` 或默认项目 |
| `functional-module create` | 创建模块并回读 | JSON/文件 |
| `functional-module delete` | 删除模块 | 模块 ID JSON array |
| `functional-case search` | 先匹配模块，未命中再搜用例 | 关键字，可选 `projectId` |
| `functional-case by-module` | 列模块及子模块下用例 | 模块关键字，可选 `projectId` |
| `functional-case list` | 分页列用例 | JSON/文件 |
| `functional-case get` | 用例详情 | `caseId` |
| `functional-case create` | multipart 创建并回读 | JSON/文件 |
| `functional-case edit` | multipart 编辑并回读 | `caseId`、JSON/文件 |
| `functional-case delete` | 删除临时用例 | `caseId` |
| `functional-case batch-create` | 批量创建并逐条回读；失败时回滚本批已创建项 | JSON array 文件/内联 JSON |
| `functional-case generate` | 从需求文本生成 3 条本地草稿 | `projectId moduleId templateId requirement-file` |
| `functional-case generate-create` | 生成并批量写入；失败时回滚 | 同上 |
| `functional-case-review list` | 反查某用例参加的评审 | 含 `caseId` 的 JSON |
| `case-review list/get` | 评审单列表/详情 | JSON 或 `reviewId` |
| `case-review-detail list` | 某评审单中的用例 | 含 `reviewId` 的 JSON |
| `case-review-module list` | 评审模块树 | `projectId` |
| `case-review-user list` | 某评审单的评审人 | `reviewId` |
| `reviewed-summary` | 汇总已评审/未评审用例 | `projectId`，可选关键字 |
| `case-report` | 用例详情、缺陷和评审 JSON | `projectId caseId` |
| `case-report-md` | 同上，Markdown 输出 | `projectId caseId` |
| `functional-template list` | 查询模板能力 | `projectId` |
| `api-module/api/api-case list` | 查询接口测试资产 | JSON/`projectId` |

## 通用 flag

- `--format json`：默认，JSON 输出到 stdout。
- `--format human`：完整结果输出到 stderr。
- `--format summary`：只输出核心字段。

## 场景决策树

1. 查找相关 case：先用 `functional-case search`。
2. 查模块全部用例：用 `functional-case by-module`。
3. 查单条用例：用 `case-report` 或 `case-report-md`，不要只返回基础详情。
4. 创建前：先查项目和模块，复制同模块真实用例的 `versionId`、`nodePath` 和字段结构。
5. 创建/编辑后：以命令返回的 `readback` 为成功依据。
6. 判断是否评审过：以实际评审关联记录非空为准，不根据状态字符串猜测。
7. 模板或接口测试能力不可用：报告 `doctor.capabilities`，不要猜路径或切浏览器。
8. 聚合查询必须翻页直到 `listObject` 数量达到 `itemCount`，不要只取前 1000 条。

## 写入字段

`functional-case create/edit` 使用 `/track/test/case/add|edit` multipart 请求。至少提供：

```json
{
  "projectId": "<projectId>",
  "nodeId": "<moduleId>",
  "nodePath": "/完整/模块/路径",
  "versionId": "<versionId>",
  "name": "<用例名>",
  "steps": [{"num": 1, "desc": "步骤", "result": "预期"}]
}
```

`nodePath` 必须显式提供，或通过 `METERSPHERE_DEFAULT_NODE_PATH` / `METERSPHERE_NODE_PATH_MAP_JSON` 配置。

## 环境变量

必填：

- `METERSPHERE_BASE_URL`
- `METERSPHERE_ACCESS_KEY`
- `METERSPHERE_SECRET_KEY`

常用可选项见 `.env.example`。配置加载顺序：进程环境 > `METERSPHERE_ENV_FILE` > CWD `.env` > `metersphere/.env`。

## NEVER 规则

- 不得用浏览器执行 MeterSphere 查询、创建、编辑、删除或认证兜底；API 失败时先检查 `doctor`、OpenAPI 和请求协议。
- 不得临时手写签名 curl；常规操作必须走 CLI。`raw` 只用于只读 OpenAPI 探索或尚未封装的诊断。
- 不得把 HTTP 2xx 当作成功；必须同时确认没有 `success:false`，写入还要检查 `readback`。
- 不得猜 project/module/template/version/nodePath；先查询或复制真实同类资产。
- 不得提交、打印或复制真实 `.env`/密钥。
- 不得在用户未授权时删除既有资产；端到端验证只创建带唯一前缀的临时资产，并在 `finally` 清理。

## 错误处理

| 退出码 | 含义 |
|---|---|
| 0 | API 和业务结果成功 |
| 2 | 缺配置或参数错误 |
| 3 | 认证/权限错误 |
| 4 | API、业务或 capability 错误 |
| 5 | 超时 |

如果实例未部署模板或接口测试模块，CLI 返回 4 和“当前实例未提供…”；不要继续猜 endpoint。

## 示例

```bash
python3 scripts/metersphere.py doctor
python3 scripts/metersphere.py functional-case search 'payment'
python3 scripts/metersphere.py functional-case get '<caseId>'
python3 scripts/metersphere.py functional-case create case.json
python3 scripts/metersphere.py functional-case edit '<caseId>' patch.json
python3 scripts/metersphere.py functional-case-review list '{"projectId":"<projectId>","caseId":"<caseId>"}'
python3 scripts/metersphere.py case-review-detail list '{"projectId":"<projectId>","reviewId":"<reviewId>","current":1,"pageSize":100}'
python3 scripts/metersphere.py case-review-user list '<reviewId>'
```

## References

- `references/ms-api.md`：确认 endpoint、multipart、写入或评审语义时读取。
- `references/ai-functional-case-prompt.md`：根据需求补充功能用例场景时读取。
- `references/ai-api-bundle-prompt.md`：实例确认支持接口测试模块后，增强 OpenAPI 用例时读取。
