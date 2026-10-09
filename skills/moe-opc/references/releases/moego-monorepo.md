# MoeGo Monorepo Release｜按应用从 main 发布到 production

## 适用范围与终点

仅当仓库身份精确等于 `MoeGolibrary/moego` 时使用本协议。其它 Web、Mobile 或自定义仓库继续使用各自默认协议，不得因为名称相似而扩大 production workflow dispatch 授权。

用户明确要求“按 OPC 发布 / 上线”时，新一轮发布从远端 main 的完整快照创建或重建目标应用的固定 `release/<app_dir>/<app_name>` 分支。该精确分支已存在时，删除后同名重建属于本次发布的标准授权，无需另行确认。接受 push 自动触发的 staging 构建与部署，本分支镜像构建并推送成功、精确 tag 可用后，即自动准备 production 制品并推进生产部署，无需等待整条 staging CI 或 staging 部署结束，不再询问是否继续 production。

只有用户明确“不需要构建 production / 只发 staging”等限制时才跳过 production。更窄的“只交接分支 / 只构建镜像”同样按用户终点执行；先核验自动事件是否符合该限制，无法满足时停止并提示。

默认成功终点是 `PRODUCTION_DEPLOYED`：精确 production run 的部署步骤成功，且实际部署对象已回读到绑定的镜像版本。`PRODUCTION_DISPATCHED` 仅是中间状态。审批、权限或 workflow 能力阻塞时如实交付当前状态和恢复入口，不绕过人工审批，不声称部署已完成。

## 准备发布分支

1. 新发布通过 `$github-workflow` 回读远端 main，绑定 source_sha；恢复发布则先加载本轮已记录的分支、SHA 和 run，核对远端状态，不改绑最新 main，也不新建分支。无法区分新发布与恢复且会导致重复发布时，先澄清本轮身份。
2. 优先按用户指定的 app 核对目录与 `metadata.yaml`；未指定时再根据明确的变更范围和共享依赖解析，多个候选才询问。不能用 main 最后一个提交的 changed files 否定用户指定的应用。目录名用于 workflow 的应用输入，`.spec.name` 用于部署回读；`.spec.cd != true` 时停止标准部署路径。
3. 读取目标 SHA 的 App CI、构建脚本及实际 dispatch ref 的部署 workflow，确认固定分支名能解析到目标 app，自动事件符合本次环境范围。按下方“能力限制”处理不支持的入口。
4. 在独立任务 worktree 中准备 source_sha 完整快照；若同名本地分支已被其它 worktree 使用，使用 detached worktree，不改动或删除其它 worktree。回读精确远端发布 ref：不存在则直接普通 push；已存在则按下节删除重建。不 cherry-pick、合并 main 到旧发布线或用 tree 相同代替 SHA 相同；恢复时只复用本轮绑定对象。
5. 普通 push 后回读必须满足 `remote_release_sha == release_sha == source_sha`。用户只要求分支交接时在精确 ref 回读后结束，并报告已触发的自动事件。

### 已有固定发布分支的删除重建

仅在新一轮发布执行，恢复本轮发布不重复删除：

1. 记录精确 repo、发布 ref、old_sha 和 source_sha，确认旧提交对象已在本地保留、source_sha 已准备好。核对该应用尚未结束的发布；有其它发布正在使用此分支时停止并报告并发发布，不自动取消它。
2. 删除前再次回读远端 ref，必须仍为 old_sha；发生并发推进时停止，不删除新值。通过 `$github-workflow` 普通删除这个精确远端分支，并回读确认 ref 不存在；权限或分支保护拒绝时停止，不绕过。
3. 从已准备的 source_sha 普通 push 重建同名远端分支，不 force、不产生合并提交。若删除后被他人重建，停止并核对，不覆盖其分支。成功后按上节核验三个 SHA 相等。
4. 删除成功但重建失败时，记录删除已完成、重建未完成，以及 old_sha、source_sha 和当前远端状态。恢复先回读：ref 不存在则继续推送本轮 source_sha；等于 source_sha 则核对本轮 push run；为其它值则停止。不得重新绑定最新 main、重复删除或自动改回旧发布代码。写入结果未知同样先按精确 ref 对账。

## 核对制品并推进 production

1. 按 `release_branch + release_sha + event=push` 绑定 App CI，核对本应用的镜像构建与推送步骤、run 输出的 Git tag 和 image tag：Git tag 指向 release_sha，镜像仓库中对应 app 的 tag 已可用，才算制品就绪。仅创建 Git tag 不够，也不能使用“最新 tag”替代本轮绑定。
2. 制品就绪后立即继续 production，不等待整个 App CI 或 staging 部署结束。整体 run 仍在运行，或仅无关 job、staging 部署失败，不否定已核验制品；镜像构建或推送未完成时等待对应步骤，失败或取消则停止。staging 由 push 自动执行，不重复 dispatch；只报告实际存在的 staging 部署结果。
3. 用户明确不需要 production 时，跳过其构建与部署，按指定终点返回实际 staging 结果；否则按下表准备 production 制品，随后自动进入去重与 dispatch，不再询问是否继续。

| 实际构建方式 | production 制品处理 |
|---|---|
| 已验证镜像跨环境共用 | 复用本分支镜像，保留 SHA/tag 绑定，不称为独立重编译 |
| 需要环境专用构建 | 用真实 production 构建入口构建同一 release_sha；回读其独立 run、Git tag（如有）及 image tag，并将生产部署绑定到该制品 |

## production workflow 去重与 dispatch

source_sha 与 release_sha 必须相等；production workflow 的 head SHA 是另一个身份。production workflow 通常从默认分支 dispatch，不能用它的 head SHA 代替被部署制品；生产制品只按 `app_dir + app_name + image_tag` 绑定。

dispatch 前通过 `$github-workflow` 按以下稳定键查询 `app-deploy.yml`：

```text
app_dir + app_name + env=production + image_tag
```

- `success / waiting / queued / in_progress`：复用精确 run，不重复 dispatch；
- `failure / cancelled`：保留失败 run。普通“发布”不自动创建第二个 run；只有用户明确要求“重新发布 / 重试生产部署”才允许重新 dispatch；
- 不存在：只 dispatch 一次。

标准 dispatch 输入固定为：

```text
workflow: app-deploy.yml
ref: 当前远端默认分支
app-dir: <backend|frontend>
apps: <app_name>
env: production
image-tag: <已核验的 production image_tag>
skip-canary: true
```

`skip-canary=true` 来自当前 MoeGo 大仓发布规则；不得采用 workflow 的 `false` 默认值，也不得从其它仓库或旧 run 推断。

dispatch 接口不直接返回 run ID。写入前记录同 workflow 的既有 run IDs 与 dispatch 时间边界；写入后按 workflow、`event=workflow_dispatch`、精确 run name、app、environment、image tag 和时间边界回读唯一新 run。结果未知时先 reconcile，禁止盲目再次 dispatch。

## 结果与恢复

- 唯一 production run 回读后记录 `PRODUCTION_DISPATCHED` 并继续跟踪该 run；queued/in_progress 时等待同一 run，不再询问是否推进 production。
- 遇到 QA/TL 等人工审批时记录 `PRODUCTION_AWAITING_APPROVAL`、精确 run URL 和所需审批，交付待审批状态；不代为审批或绕过。恢复执行时先回读同一 run，审批已完成则继续，不创建新 run。
- run 的部署步骤成功后，回读目标应用在 production 的实际部署状态与镜像版本；需要 ArgoCD Sync 时核对目标同步结果。只有状态成功且镜像与绑定制品一致时记录 `PRODUCTION_DEPLOYED`。run 成功但部署对象不可回读时记录 `DEPLOYMENT_UNVERIFIED`，不宣称完成。
- 所需镜像构建、推送或 production 部署失败/取消时停止；staging 失败按制品就绪规则处理。对象多义、权限拒绝、能力缺失或超出本轮等待窗口时，交付当前对象、状态、副作用与恢复入口，不宣称完成。
- 构建重试与发布恢复先对账本轮分支、SHA、输入和已有 run。写入结果未知时先 reconcile，不重复构建或部署；明确重试授权按上方去重规则执行。
- 用户明确跳过 production 时记录实际 staging 构建或部署结果与 `PRODUCTION_SKIPPED`。只要求更窄终点时按实际结果交付，不主动继续。

## 能力限制

- **固定分支命名**：若解析器把 `release/(backend|frontend)/` 后的全部内容作为 app_name，不能自行追加日期或版本后缀。已有固定应用分支按上节删除重建，不仅因分支存在报告 `WORKFLOW_CAPABILITY_BLOCKED`。只有真实入口无法解析目标应用或无法满足本次环境范围时才报告能力阻塞；不擅自修改业务 workflow。
- **构建与部署接口**：App CI 的 `env` 若仅支持 testing/staging，不传 `production`；只接收 image-tag 的部署 workflow 不算构建入口。接口不支持或制品无法追溯时停止并提示，不拿其它分支镜像代替。
- **更窄终点**：用户只要求构建或分支交接时，先核对 push 的自动副作用；不符合其范围则停止并提示，不先触发再取消。
