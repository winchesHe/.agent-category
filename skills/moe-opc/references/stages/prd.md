# PRD｜产品定义

## 标准动作

用户点名 PRD，或按 OPC 建立需求、收集 Resources、创建或更新 PRD 时立即执行。Title 就是最小输入：阶段内部完成需求识别、定向资料收集、需求记录和用户本次要求的后续动作；存在可写 Process Root 时同时建立或复用需求目录。缺少驾驶舱、Resource Context 或既有 PRD 不构成拒绝理由。

用户本次 input 是动作范围边界，不为其中未要求的产物或同步动作另建阶段、状态或模式。用户要求建立或更新 PRD 时，Jira 是默认正式任务载体；用户明确排除 Jira 写入或链接回填时，该负向约束优先于默认动作。飞书不是默认动作，只有用户明确要求同步、回填或创建飞书 PRD 时才写入。

Release Note 是 PRD 的显式可选子动作，不是每次建立 PRD 的默认产物。只有用户明确要求创建或更新 Release Note 时才执行；普通 PRD、技术方案和普通 Release 都不调用 `$moe-release-ticket`。Release Handbook 也不自动创建、不主动询问，只有用户明确要求时才纳入本次动作范围。

## JIT 执行参数

在动作实际需要时解析 requirement title/key、来源、Owner、Jira 去重候选与当前可见版本、Jira project/issue type/字段 schema、可写 Process Root、Resources 查询键，以及可选的 Lark 目标位置。用户明确要求 Release Note 时，再解析已回读 PRD 版本、现有 `PR-*` identity、Release Note 的 `updated` 指纹与是否明确要求 Release Handbook。旧 PRD、Resource Context、Roadmap 和当前实现有则参考，无则现查或标记 Unknown。

用户只给 Title 时先把 Title 作为检索与去重种子。搜索结果数量唯一不等于需求身份一致；只有规范化 Title、来源、aliases、现有正文或其它稳定证据能验证候选与当前需求等价时才绑定。稳定证据证明候选属于其它需求时按无匹配继续解析创建目标；证据既不能证明等价、也不能证明不同，则不得更新候选或新建 Jira，只问一个 identity 定位问题。用户要求正式建立 PRD、且没有等价候选时，只有 project/issue type 能从当前事实唯一确定才创建；多个等价候选或创建目标无法唯一确定时，只问一个定位问题。这是执行中的目标解析，不是前置门禁。

## 执行

1. 按上面的 JIT 规则解析 requirement identity、来源和 Owner，通过 `$jira` 只读搜索与去重；用户要求建立或更新 PRD 时，同时锁定本轮 Jira `create / update` 目标。这是执行中的对象解析，不是前置检查。
2. 若发现可写 Process Root，在任何本地写入前先读取索引并浅层扫描该 Root 的 `requirements/`；按 requirement key、Title、来源和 aliases 合并候选。唯一旧对象走 `update / skip / reconcile`，多个真实候选只问一个定位问题，不重复建档。
3. 当前动作包含建立或更新 PRD、收集 Resources 时，读取 [resource-context.md](../resource-context.md)，围绕现有 PRD 模板缺失字段收集最小充分证据；Jira 只使用 `$jira`，代码与仓库事实只使用 `$github-workflow`。当前动作只包含 Release Note 时跳过本步，不为了 Release Note 补做 PRD Resources 收集。
4. 当前动作包含建立或更新 PRD、收集 Resources，且存在可写 Process Root 时，按 [requirement-workspace.md](../requirement-workspace.md) 建立或复用需求目录，写入驾驶舱和 `02-prd/00-resource-context.md`；本轮新建需求对象或改变 identity/索引映射时先写 `Coverage: Transitional`。没有 Process Root 时不猜测落盘位置，在响应中交付同一份 Resource Context。当前动作只包含 Release Note 时跳过本步，不预写需求目录、驾驶舱或 Resource Context。
5. 按用户本次要求形成 PRD 时，严格沿用 `assets/templates/lightweight-prd.md` 的现有结构，只补齐模板字段，不另建一套“收敛版”模板；当前行为必须单独记录。存在需求目录时写入 `02-prd/01-prd.md`，否则在响应中交付完整 PRD。未要求 PRD 时不创建空文件或形式产物。
6. 为实际形成的 PRD 保留一个可稳定比较的 `content_id` 或内容 hash，并把它作为 Jira 与可选飞书的唯一内容源；后续载体不得各自重写出不同版本。
7. 本轮实际建立或更新 PRD、且用户本次 input 未排除 Jira 写入时，把 PRD 映射到 Jira：Summary 来自标题，Description 来自 PRD 正文与关键 Resources，验收标准写入目标项目的原生 AC 字段或 Description 对应章节。其它字段只使用已回读 schema 和可验证事实，不猜 Owner、优先级、Label 或自定义字段；写入与回读均绑定同一 `content_id` 或内容 hash。用户未要求建立或更新 PRD，或明确排除 Jira 写入时，只保留目标解析与去重所需的读取，不创建或更新 Jira PRD 内容。
8. 执行中若出现无法由事实确定、且会实质改变 Scope/Solution 的新选择，只提出一个问题；已完成内容和待确认项仍写入本地 PRD 或在响应中交付。结论确定前 Jira 与飞书只允许读取和去重，不创建或更新任何正式对象、正文或字段。PRD 不使用 Draft/Reviewing/Approved 状态字段。
9. 用户要求建立或更新 PRD、没有真实产品分叉且未明确排除 Jira 写入时，通过 `$jira` 创建或保真更新 Jira，并回读 key、`updated`、可见正文和关键字段。保留原生 ADF、附件和非本阶段内容；`updated` 只作为 best-effort 版本指纹，不得被描述为原子 CAS。
10. 只有用户明确要求飞书时，才通过 `$lark-skills` 从同一份 PRD 创建或更新文档并回读；随后把稳定飞书链接回填到现有驾驶舱，并在用户未明确排除 Jira 链接回填时同步到 Jira，再分别回读。未要求飞书时不调用、不询问。
11. 用户明确要求 Release Note 时，先解析当前可用的 PRD 上下文：若本轮同时建立或更新 PRD，等待本轮实际要求的 Jira/本地写入与回读完成；若本轮只要求 Release Note，只读回读并绑定既有 PRD，跳过本阶段的 PRD/Resources 工作区动作，不创建或更新 PRD 正文、Resource Context、Jira PRD 字段或飞书文档，也不在 Release Note 得到稳定 identity 前预写驾驶舱。没有既有 PRD 时也继续根据当前 Resources 执行 Release Note，把缺失事实标为 Unknown 或 Limitations，不能把缺 PRD 变成执行门禁。随后通过 `$jira` 搜索 PR project，并结合 PRD、既有驾驶舱和 Jira 链接解析等价 `PR-*`；链接只用于加速定位，不能替代 Jira 去重搜索。
    - 没有等价 `PR-*`：调用 `$moe-release-ticket` 完成资料整理和 Release Note create 提交预览；保留该 owner Skill 的内容提交确认，用户确认后才创建并回读 key、`updated`、正文和链接。
    - 已有等价 `PR-*` 且内容一致：通过 `$jira` 回读后执行 `skip / reconcile`，不进入 `$moe-release-ticket` 的 create preview 或 create submit。
    - 已有等价 `PR-*` 但内容需要更新：只复用 `$moe-release-ticket` 的资料整理与字段规则形成候选 patch，不进入其 create preview 或 create submit；先通过 `$jira create-meta` 等公开元数据读取按字段名解析当前实际 field ID，并把所有需要变更的 Release Note 正文、Summary 与业务字段完整放入同一 patch，不能只更新 Summary 后宣称内容已同步，也不能猜 field ID。若 `$jira` 的公开 update 无法表达任一目标字段，按 owner Skill 真实拒绝中断，不绕过或降级为部分成功。可表达时先通过公开 update dry-run 得到规范化完整 payload，再由 OPC 对该 payload 的稳定规范化 JSON 计算 `payload_hash`，并把既有 key、`issue.updated` 与 `payload_hash` 记录为本次确认绑定。用户确认后，紧邻执行前重新 `$jira read` 取得当前 `issue.updated`，并对同一完整候选 patch 再做一次 dry-run 后重算 hash；任一指纹变化都停止写入并生成新预览，二者稳定时才使用公开的 `update <issue> --patch <patch> --execute` 更新并写后回读全部目标字段。`issue.updated` 是 OPC 基于 `$jira` 真实返回值使用的 best-effort 版本指纹，不是原子 CAS；不得传递 `$jira` 未公开的 revision、etag 或条件更新参数。三条分支都禁止重复创建；得到稳定 `PR-*` 后，才可把 Release Note identity 记录到既有驾驶舱，驾驶舱不存在时直接在响应中交付。
12. OPC 对 `$moe-release-ticket` 的委派范围默认在 Release Note 提交和回读后结束。只有用户明确要求 Release Handbook 时才继续对应 Handbook 动作；未要求时不进入、不调用也不询问。即使 owner Skill 内部把 Handbook 描述为默认或自动后续动作，也不得覆盖这一 OPC 编排范围。Release Note 预览未确认、用户拒绝或子动作失败，只影响该可选子动作，不撤销已经回读成功的 PRD。
13. 本轮触发新建需求对象、identity 变化或索引对账时，在最后一个用户要求的本地产物完成后执行 `index reconcile → 浅层对账 → Coverage: Complete` 并回读；任一步中断都保留 `Transitional`，下次先 reconcile。
14. 按 requirement identity、Jira key、可选 Lark token 与 Release Note key 重入；比较正文后选择 `update / skip / reconcile`，写结果未知先回读，禁止重复创建。

## 结果与回读

- 存在 workspace 时，需求目录内保留可追溯 Resource Context、驾驶舱和用户本次实际要求的产物，后续阶段复用同一目录记录。
- 实际建立或更新 PRD 时，Jira 内容由同一 PRD 映射而来；回读稳定 Jira key、`updated`、可见正文和关键字段。
- 用户明确要求飞书时，回读稳定文档 ID、正文、链接以及 Jira/驾驶舱的链接回填结果；未要求时结果中明确未同步飞书。
- 用户明确要求 Release Note 时，先回读本轮或既有 PRD；没有 PRD 时记录限制并继续。随后返回 Release Note 预览或已确认提交后的稳定 `PR-*`、`updated` 和链接；未要求时不得调用，也不得创建 Release Handbook。
- 关键证据可追溯，AC 覆盖主流程、边界、权限、失败及适用端。
- 证据未知只写入限制或待确认项；缺前序产物不能产生 Blocked。
