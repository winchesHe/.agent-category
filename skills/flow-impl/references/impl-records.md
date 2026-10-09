# flow-impl 实现记录模板

提供：① plan 决策记录追加（Y/N 判定 checklist + Y 时模板）② 完成 report 6 字段草稿（字段分工）

## plan 决策记录追加（Y-only + 判定 checklist）

每步完成时 flow-impl 必须：

1. **更新 plan `## 步骤节奏` 表**：当前行 `⏳ → ✅` + `reviewed` 列填 `YYYY-MM-DD`（**无论 Y/N**）
2. **判定 Y / N**（按下面 checklist）：

### Y / N 判定 checklist

满足**任一** → **Y**：

- 后续步的**观察点 / 验证方式 / 范围**被改
- 后续步**增删 / 顺序调整**
- 新产生了**未确认假设**（写进 plan § 未确认假设）
- 发现 spec 失真（已通过偏差回流改 spec）

全 N → **N**（仅填 reviewed 日期，不写决策段）。

### 例

- **Y**：步 1 实现时发现 API 响应字段名是 `customer_id` 不是 `userId`，后续步 2/3 的 UI 绑定字段都要改
- **N**：步 1 实现 BirthdayTooltip UI hardcoded 渲染完毕，后续步 2 拉数据是独立工作，不受影响

### Y 时追加段（落到 plan `## 决策记录（活更新）`）

```markdown
### 步 N 完成（YYYY-MM-DD）
- **影响**：<拆 / 删 / 调整哪些后续步>
- **新发现的事实**：<...>
- **假设回填**：<原 ⚠ X → 已确认为 Y>
```

## 完成 report 6 字段草稿

任务全部步完成时输出对话回复（**不进独立文件**）。

**模板 source of truth 在 `flow-ship/references/ship-release.md`**——本文件只列字段分工：

| 字段 | flow-impl 填 | flow-ship 补 |
|---|---|---|
| 完成日期 | —— | ✅（实际 ship 日期）|
| 改动文件 | ✅（≤ 5 个 path + 一句话）| —— |
| 步验证 | ✅（每步 verify 命令 + 输出片段）| —— |
| 偏差 | ✅（`git log -p docs/specs/<slug>.md` 摘要 / `None`） | 可重算 |
| 待跟进 | ✅（或 `None`）| —— |
| PR / Commit | —— | ✅（PR URL 或 commit hash） |

flow-impl 输出格式（缺字段用"（flow-ship 阶段补）"占位）：

```
### 完成 report 草稿（<slug>）
- **完成日期**：（flow-ship 阶段补）
- **改动文件**：<...>
- **步验证**：1 → <...> | 2 → <...>
- **偏差**：<或 None>
- **待跟进**：<或 None>
- **PR / Commit**：（flow-ship 阶段补）
```

flow-ship copy 此草稿 → spec 末尾 `## 完成 report` 章节 + 补两字段。
