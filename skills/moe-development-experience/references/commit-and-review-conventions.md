# Git 与 CI 排查经验

- ID：`MDEV-GIT-CI`
- 适用：MoeGo 仓库的 hook/分支校验失败、CI 产物与部署不一致，或需要判断自动化的实际作用范围。

Git 操作、完整 Review 与权限边界遵循 `github-workflow`；PR 内容使用 `review-brief`。本篇提供排查线索，不维护第二份提交规则或 PR 模板。

## 本地与 CI 校验结果不同

先看当前生效的 hook 路径、hook manager 和它调用的配置，再看失败 CI 校验的对象与范围。仓库存在 `.githooks/` 或 `.husky/`，不代表本地一定启用了它。

| 失败 | 核对重点 |
|---|---|
| references-empty / ticket 前缀不匹配 | 当前 commitlint 或 hook 的实际要求；ticket 从任务事实获取，不按历史前缀表猜业务含义 |
| header/type/格式失败 | 失败规则、当前消息与配置；不照抄另一个仓库的长度、type 或标点写法 |
| 本地成功、CI 失败 | 本地 hook 是否生效，CI 是否检查全部提交、不同 ref 或另一份配置 |
| 已有历史提交导致检查失败 | 先确认失败目标；新增一条正确提交未必修复对旧提交的校验，按 Git owner 的当前策略处理 |

需要启用 hook 时使用本仓已有安装入口，不能用猜测的目录覆盖当前 hook 配置。

## 分支能提交，不代表能发包或部署

hook 接受范围、workflow 触发条件、publish 脚本分支匹配和部署应用名限制分别检查。通过其中一项不能推断其余条件满足。

协议与 BFF 的分支/tag 差异见[协议包发布](api-web-publish-cheatsheet.md)、[BFF 发布](bff-openapi-publish-cheatsheet.md)。跨仓是否必须同名，按当前 skill catalog 定位 `moe-development` 并读取其 `references/protocol-and-dependencies.md`，不从旧分支正则推导全仓命名规则。

## 沿实际 workflow 追踪

| 观察 | 下一步 |
|---|---|
| 本仓只有 `uses: MoeGolibrary/moego-actions-tool/...` | 按这次 run 使用的 reusable workflow 及引用版本继续查；调用方 YAML 不能说明完整步骤 |
| CI 成功，但没有镜像或包 | 查对应 job/step 的 if、skip 与实际产物；不要只看顶层状态 |
| 镜像存在，但目标环境没更新 | 查这次输入的 `build_only`、`dry_run`、`enable_cd` 等实际语义，以及部署 job、GitOps/同步和运行镜像 |
| Go 大仓漏构建或漏部署应用 | 从 `app-ci.yaml` 的 changed apps 和实际应用配置定位；新增应用细节见[Go 服务经验](backend-service-handbook.md) |
| rerun 后结果不同 | 核对 run attempt、所用 ref、依赖产物与输入；rerun 是否会重新发布或部署，要读实际 workflow |

输出、构建、发布和部署可能是并行或独立 job，不按历史 stage 列表猜执行顺序。已有失败日志能定位时，先处理该条件，不通过反复 rerun 代替诊断。

## 同名工具入口可能有不同副作用

moego-bff 的本地 `update-api` 脚本与 `.github/workflows/update-api.yaml` 不等价：后者在更新后还包含创建 PR 与 Slack 通知步骤。只需要本地升级时先用本地入口；触发自动化前核对完整作用范围与当前授权。

Mobile 涉及 Native / OTA / runtime 兼容时，读 `moego-mobile/README.md` 的版本说明和当前 `app.config.ts`。构建产物与目标设备实际 runtime 要对应，不能把一次 JS 构建成功当成所有已安装客户端可用；具体版本计算仍由原仓维护。

完成排查应能说明失败条件、实际产物和目标运行状态；评审者、检查状态与合并条件由当前 PR 和仓库事实确定。
