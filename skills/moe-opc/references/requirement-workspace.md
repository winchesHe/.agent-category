# 需求工作区协议

需求工作区用于恢复、导航和记录，不是 Explicit Execute 的运行依赖。用户给出的 Jira/DES/PR/repo 等稳定身份已能唯一定位当前动作时，先执行阶段；没有 Process Root、索引或驾驶舱不能单独产生 Blocked。

## 按需发现

只有当前动作需要更多历史上下文、Navigate 需要选择需求，或收尾需要记录时，按顺序发现：

1. 用户显式给出的驾驶舱、Process Root 或需求目录。
2. 当前会话内唯一且已验证的驾驶舱。
3. 从当前目录向上查找最近的 `<ancestor>/moe-opc/index.md`。
4. 迁移兼容：逐级检查祖先下的 `<ancestor>/moego-opc/`；命中 `index.md`，或同时存在 `context/current.md` 与 `requirements/` 时使用。
5. 仍不存在时继续执行可唯一定位的阶段动作；只有当前目标本身多义才询问。

不得扫描整个 home。

## 新需求目录

PRD 阶段当前动作包含建立或更新 PRD、收集 Resources，且发现当前范围内存在可写 Process Root 时，建立或复用以下目录，让后续阶段拥有稳定记录位置。当前动作只包含 Release Note 时不建立目录，也不预写驾驶舱、Resource Context 或 PRD：

```text
requirements/<key-or-slug>/
├── 00-需求驾驶舱.md
└── 02-prd/
    ├── 00-resource-context.md
    └── 01-prd.md
```

- PRD 可以从 Title 直接建立目录，先记录驾驶舱和 `00-resource-context.md`；只有用户本次要求实际建立 PRD 时才写入 `01-prd.md`，不创建空文件。
- 已有 requirement key 时优先用于目录名；只有 Title 时使用稳定 slug，并在后续解析到 Jira key 后更新驾驶舱与索引 identity。目录不必为了 key 变化强制重命名。
- 缺少可写 Process Root 只影响本地记录，不阻止可唯一执行的 Jira 或其它阶段动作。

## Technical Design 工作区

Technical Design 发现可写 Process Root 时，建立或复用稳定源文档：

```text
requirements/<key-or-slug>/
├── 00-需求驾驶舱.md                    # 已存在时按需更新；不为目录形式强制新建
└── 03-technical-design/
    └── 01-technical-design.md          # source_authority=local 时的唯一内容源
```

- 技术方案不依赖 `02-prd/`，不得为补齐形式创建空 PRD、Resource Context 或驾驶舱。
- `design_identity` 由 canonical requirement identity 与 `technical-design` 产物类型组成；标题变化不生成新身份。
- `content_fingerprint` 对规范化的读者可见正文计算 SHA-256，并使用 `sha256:<hex>` 表达；统一为 LF、移除每行尾随空白和文档首尾空行，保留正文内部顺序与空白。design identity、source authority、成熟度、有效性、回读时间、同步状态、执行回执和其它运行或传输元数据不写入方案正文，也不参与指纹，因此这些状态变化不会伪装成内容变化。
- `source_bindings` 记录实际使用的 Jira revision/`updated`、Design version、repo/head 和 API/data/release 边界。最近回读时间属于同步回执，不进入 `source_bindings` 或 `content_fingerprint`。
- 本地源存在时记录 `source_authority=local`；没有本地源但正式 Lark 文档存在时记录 `source_authority=lark`；两者都没有时只在当前响应交付，不写成可恢复源。
- 不得随机创建新的 Process Root。没有本地记录位置只影响载体同步状态，不影响阶段直接执行。

本地源、Lark、Jira requirement 和 Jira Tasks 分别记录 `current / stale / failed / deferred / skipped / unknown`。`deferred` 必须带 `blocked_by`、`retryable` 和恢复入口；`skipped` 只表示用户明确排除或矩阵不适用，不进入自动恢复。外部对象的稳定 key/token、task identity、link type/direction 和最近回读写入同步摘要；完整方案正文只保留在 source authority，不复制到驾驶舱或 Jira。

source authority 迁移前必须回读两端并比较规范化内容。指纹不一致且差异会改变 Scope、方案或风险时，先记录一个真实决策；禁止最后写入者静默覆盖。

## 索引

`index.md` 至少包含 Coverage、Focus、需求标识、别名、标题、终态、驾驶舱相对路径、下一步和最近验证时间。

- `Coverage: Complete`：索引覆盖该 Process Root 的驾驶舱。
- `Coverage: Transitional`：Navigate 的唯一性判断前浅层扫描旧 `requirements/` 并合并候选。

PRD 准备新建本地需求对象时，也必须在首次本地写入前浅层扫描当前 Process Root 的 `requirements/` 并合并稳定候选。这是本轮 identity 解析与去重，不是阶段资格检查；扫描范围只限已发现的 Process Root，不扩展到整个 home。

索引只影响导航覆盖，不影响显式阶段执行。旧需求按再次记录时渐进更新，不批量重写。

创建、重命名、重开、关闭或取消需求时，为保证本地记录可恢复，按 `Transitional → cockpit/阶段产物 → index reconcile → 浅层对账 → Complete` 更新。浅层对账成功后显式写入并回读 `Coverage: Complete`；任何一步失败都保留已完成外部动作的真实结果，并把本地记录标为待对账，不能把外部成功反转成阶段失败。

## Alias 解析

- canonical requirement key 直接匹配。
- DES key 通过 `$jira` 回读 Issue Link/来源需求。
- PR 使用完整 URL 或 `repo#number`，通过 `$github-workflow` 回读 repo、branch/body 和关联 key；裸 PR number 不具全局唯一性。
- 零匹配先自动发现；多匹配只问一次。只有这种目标多义可以中断当前动作。

## 驾驶舱最小结构

```markdown
# 需求驾驶舱
- Requirement：稳定 key / 标题
- 来源：用户 / Jira / Roadmap / 其它稳定入口
- Owner：当前可回读 Owner / Unknown
- Terminal：Active / Closed / Cancelled
- Focus：导航焦点
- Coverage：Complete / Transitional
- Resource Context：`02-prd/00-resource-context.md` / 无
- PRD：`02-prd/01-prd.md` / 无
- Technical Design：`03-technical-design/01-technical-design.md` / Lark token / response-only / 无
- Design Identity / Content Fingerprint：稳定值 / 无
- Source Authority：local / lark / response-only / 无

## 事实与有效性
## 稳定对象
## 当前真实阻塞
## Observation Schedule
## 决策与用户范围
## 最近执行结果
## 推荐下一步
```

兼容现有 `00-需求驾驶舱.md`，无需复制。历史 Blocked 行只作上下文，不是重新执行的解除条件。

## 结果记录

完成外部动作并回读后，优先把轻量结果追加到现有阶段产物；没有稳定产物时写驾驶舱。两者都不存在或暂不可写时，在当前响应交付完整结果即可，后续按稳定对象对账。

结果至少包含目标、实际动作、JIT 绑定、外部回读、限制、真实阻塞和下一步。Technical Design 还记录执行结果、成熟度、有效性、source authority、`design_identity`、`content_fingerprint`、各载体同步状态和恢复入口。Experience 仅在实际影响动作时按需记录。

## 终态

- **Closed**：用户显式关闭后，同步并回读对应外部终态；遗留和未观察项记录在结果中。
- **Cancelled**：用户显式取消后，记录原因、已产生副作用和可恢复资产，并同步外部终态。

重开 Closed/Cancelled 需要用户明确意图。终态写入仍遵循稳定身份和写后回读。
