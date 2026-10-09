# gRPC 协议包发布与排查

- ID：`MDEV-API-WEB-PUBLISH`
- 适用：消费者确需新的 api-web / api-node 或 v2 产物，以及 registry 404、发布跳过、包内容不符。

## 先确定发布源与必要产物

包名与源码归属见[npm 依赖](npm-dependencies.md)。`api-web` 与 `api-web-v2` 不能互换；沿消费者真实 import、锁文件和包元数据确认对应协议仓。

是否需要改 schema、生成或发布，由 `moe-development` 的《协议与依赖判断》确定。已有 Struct key 或仅修改服务内部逻辑，不自动产生 SDK 变化。

## 发布入口与容易漏掉的条件

| 已确认的源仓 | 读取入口 | 判断重点 |
|---|---|---|
| moego-api-definitions | `.github/workflows/ci.yaml` → `ci/build.sh`、`ci/npm_publish.sh`；包声明在 `templates/web`、`templates/node` | workflow 支持 push 和手动触发，但发布脚本仍按分支筛选；总体构建成功不代表 npm 已发布 |
| moego Go 大仓 | `.github/workflows/app-ci.yaml` 的 `check-proto-changes` / `publish-npm` → `scripts/npm_publish.sh`；包声明在 `template/ts/` | 先经过相关文件变更筛选，再执行发布脚本；筛选涉及协议、包配置、模板及生成配置等，不能简化成“只有 proto 改动才发布” |

这两个源仓的当前发布脚本将 `main` / `production` 映射为 `latest`，将 `feature-<topic>` / `bugfix-<topic>` 映射为 `<topic>`，其他分支可能以 0 退出并跳过发布。执行前回读目标脚本；该规则不适用于 BFF 或其他包。

版本号由各自脚本计算，不根据分支名、日期或另一个仓库的格式拼造 version。

## 从 registry 核对结果

已确认包来源后，按[npm 依赖](npm-dependencies.md#依赖声明与升级)查询准确包名、tag 与真实 version；这里核对协议仓发布机制。

| 现象 | 检查顺序 |
|---|---|
| 已排除 registry/认证问题，目标 tag 仍缺失 | 核对对应源仓分支、变更筛选和发布 run，区分未发布与发布到其他 tag |
| CI 绿色但 tag 不存在或仍旧 | 实际 job/step 是否运行 → 变更筛选结果 → 分支匹配 → publish 输出；不要只看总状态 |
| tag 已更新但新方法/字段不可用 | 该 version 的包内容与导出 → 生成时使用的协议 → 消费仓 lockfile 和实际安装内容 |
| 服务已部署，SDK 没变化 | 确认改动是否位于真实协议源，以及消费者是否确实需要新生成产物；服务镜像和 npm 包是不同产物 |

核对该 version 的实际导出与生成源，再确认消费者已加载；服务镜像和 npm 包分别验证。

## 确有未发布产物时再触发

先确认目标协议版本及当前 workflow 可用的触发方式，通过 `github-workflow` 在已授权范围操作。已有手动触发时不为触发而改协议注释；空 commit 也不能绕过变更筛选条件。缺少真实产物需求时，不创建空分支或触发发布。

完成判据是对应 publish 实际执行、tag 指向可核对的 version、该包包含消费者所需内容。消费端声明、lockfile 与 catalog 的升级方法见[npm 依赖](npm-dependencies.md#依赖声明与升级)。
