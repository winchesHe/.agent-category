# Slack PR Review Request

## 动作参数

用户点名发起 PR Review 时立即执行。使用 `$github-workflow` 解析当前 PR、head/base/SHA 与真实 diff，以 `repo + PR + base + head` 定位 `$review-brief` 产物：已有同一绑定且校验通过的 `review-brief.json` 时必须复用；不存在时只生成并校验一次。随后对该 JSON 执行 `render-slack`，生成精简正文和额外视觉附件清单。使用 `$slack` 解析 Reviewer/频道并完成外部写入。

Slack 正文直接使用 `render-slack` 返回的 `blocks`（写入数组文件后传给 `--blocks-file`），整份 Brief 由渲染器放入 `context` 小字块；其 `--output` 文件作为 fallback。OPC 在这些 blocks 后追加下述验收入口或修复说明，不改写 Brief 字段；Brief 本身不追加非目标、CI、测试、Delivery 状态或风险摘要。PR Body 与 Slack 必须回读并对账同一个 `content_hash`；目标或 head 变化时重新生成，不能从旧 PR Body 或 Slack 消息反向解析语义字段。

所有 Slack 读取、发送、上传和回读使用 `SLACK_SKILL_TOKEN_MODE=user` 与 User Token。User Token 缺失、权限或 scope 不足属于当前动作的真实外部拒绝；不得尝试 Bot 或修改 Slack Skill。

## 唯一根消息

```text
<@REVIEWER_ID> [<@REVIEWER_ID_2>] 帮忙看看 PR：<PR_URL>
```

根消息不放背景、范围、验证、风险或第二条长正文；材料进入同一 `thread_ts`。PR 链接只放根消息，Brief 标题下不再追加仓库/分支链接行。

## Thread 顺序

1. 发送一条组合回复：上方是 `render-slack` 生成的整份 Review Brief context blocks；有可用 Site 时，下方紧接验收 Site 正文链接；无 Site 时，下方放修复前后说明正文。
2. 按渲染结果上传通过 `$review-brief` 门禁的图片与技术图；这些文件只帮助理解改动，是额外附件。
3. 无可用 Site 时，按下方规则发送验收附件。

## 验收材料选择

优先复用当前任务已有、已发布且 Reviewer 可访问的验收 Site。用已有发布记录或 Site 管理接口确认稳定 URL、任务归属和访问范围。

- **有可用 Site**：在 Brief blocks 后追加独立 `rich_text` 正文块，包含“验收报告：”的 text 元素和指向已确认 Site URL、标签为“查看验收报告”的 link 元素；同一条回复发到原 `thread_ts`。fallback 使用 Brief 的输出并追加报告 URL，最终以 `--blocks-file` 与 `--text-file` 发送。URL 不放入普通 text 元素，也不依赖自动识别裸链接。不再上传本地验收 HTML 或截图。
- **无可用 Site**：在 Brief context 后追加独立 `rich_text` 正文，简短说明“修复前：什么操作触发了什么问题、造成什么影响”和“修复后：改了什么、实际解决了什么问题”。从已有验收报告或同源结论提取，保留关键限制；未验证的效果不写成已解决，受控复现不冒充客户原始现场。没有报告时使用已确认的问题与修复事实，缺少结论就说明缺口，不推测补齐。将该说明同步追加到 fallback，与 Brief 同条发送；说明不写入 Review Brief 模型或改变其 content_hash。随后按下方规则将完整本地 HTML 文件上传到同一根消息的 `thread_ts`。

Site 不可访问或归属不明时，如实说明入口限制并按无可用 Site 处理；发送 Review 不自动授权新建、发布 Site 或扩大其访问权限。

没有 Site 或附件不阻止用户显式发起 Review。

## 本地 HTML 附件

本节同时适用于 PR Review 和产品/设计走查；附件位置由对应动作合同决定。

1. 复用当前任务对应版本的完整 HTML 报告，保留全部场景、结论、限制和报告内证据。确认文件可独立打开，正文和内嵌图片完整，不依赖本机路径或相邻资源文件。
2. 使用 `$slack` 的 `files_upload --file <报告.html>` 上传实际 `.html` 文件，文件名保留 `.html` 后缀并能识别任务与报告。不将 HTML 转成长截图，也不再拆发报告中的局部截图或 Primary Evidence；`review-brief` 自身的理解附件仍按其渲染结果发送。
3. 没有可用 HTML 时说明附件缺口，不以截图替代。上传失败或结果不明时按 `$slack` 的错误处理规则执行。

## 写后回读

通过 `$slack` 回读根消息、Reviewer IDs、Review Brief reply 的 `content_hash` 和频道内根消息数量；所有材料均属于同一根消息的 `thread_ts`。

按实际发送材料核对：Brief context blocks 与渲染器输出一致，有可用 Site 时核对后接正文 link 元素的 URL 与已确认 Site 一致，无 Site 时核对修复说明位于 Brief 下方且与来源结论一致；记录组合回复 `ts`，不能只检查顶层 text 中含有 URL。HTML 附件核对 File ID、文件名、类型、大小、任务/报告版本和所属 `thread_ts`，确认上传的是完整 HTML 文件；理解附件另按渲染清单核对 File IDs、数量和顺序。

附件错误默认在原 thread 补发并说明替代关系。删除/重发根消息是独立破坏性动作，需要用户明确授权；上传退出码不能替代回读。
