# spec 文件模板

使用方式：起草 `docs/specs/<slug>.md` 时按本模板填写。

**spec = 产品设计图 + 实现路径 + 验收 + 代码改动范围**。允许写技术细节（schema / 接口签名 / 命令示例 / 数据流）。

## 模板（按产品形态自由增删子章节）

````markdown
# <task-slug>

## 概述

产品 / 模块的整体定位 + 解决什么问题。如有，工作区固定为 `~/.<product>` 等。

核心目标：

1. ...
2. ...

## 非目标

MVP 不做以下能力：

1. ...
2. ...

## 工作区结构 / 架构

```text
~/.<product>/
  ...
```

| 路径 | 作用 |
|---|---|
| `...` | `...` |

## 数据模型 / Schema

```ts
type XxxData = {
  field: string;
  ...
};
```

或 SQL / TOML / proto 字段定义。

## 接口设计

CLI / API / SDK 接口（含命令、子命令、参数）：

```bash
<cli> command --arg
```

```ts
type AdapterInterface = {
  probe(path: string): Promise<ProbeResult>;
  discover(source: ScanSource): Promise<DiscoveredSession[]>;
  ...
};
```

## 子系统设计（按需多段）

### XxxSubsystem
### YyySubsystem

## 配置

```toml
[section]
key = "value"
```

## 安全策略

1. 数据脱敏：...
2. dry-run：...
3. 默认安全：...

## 改动范围

要改动的模块 / 文件 / 接口：

- 模块 `xxx` → 加 / 改 / 删（理由）
- 文件 `path/to/file.ts` → 改 X
- 接口 `Foo.bar()` → 签名变化（兼容性？）
- 数据迁移：旧 schema → 新 schema（迁移脚本？）

## 假设

- ⚠ <未确认假设；implement 时优先验证>

## 风险

- <风险 + 兜底方向>

## 验收链路

具体 CLI 命令 + 必须证明的事实：

```bash
<cli> init --yes
<cli> scan --all
<cli> verify
```

必须证明：

1. ...
2. ...

## 后续实现顺序

建议按最小可验证链路实现：

1. ...
2. ...
3. ...

大需求时此节细化到 `docs/plans/<slug>.md`（plan = 执行节奏 + 活更新 + Y-only 决策记录）。

<!-- 以下章节仅在实际需要时填入，无关场景删除 -->

## 依赖（涉及跨仓 / SDK / schema 时填）
- 上游 PR / npm tag / proto 版本：<...>
- 上线顺序：<前 → 后>

## 灰度（涉及 feature flag 时填）
- Flag key（GrowthBook）：<...>
- 默认值：<off / on>
- 灰度策略：<按 user / 公司 / region / 全量>

## 回归点（涉及外部 caller / 关键 UI 场景时填）
- 受影响 caller / UI 场景 / 数据维度：<列表>

## 参考
- PRD: <link>
- 相关 Jira / Slack / 飞书 / 代码: <link>
````

## 章节分类

### 必有章节

| 章节 | 内容 |
|---|---|
| `## 概述` | 产品定位 + 解决什么问题 + 核心目标编号列表 |
| `## 非目标` | 明确不做的事 |
| `## 假设` | ⚠ 标明未确认假设 |
| `## 风险` | 风险 + 兜底方向 |
| `## 验收链路` | 具体 CLI 命令 + 必须证明的 N 条事实 |
| `## 后续实现顺序` | 高层步骤列表（实现路径） |
| `## 参考` | 链接 |

### 按产品形态组织（自由增删）

| 章节 | 何时填 |
|---|---|
| `## 工作区结构 / 架构` | 涉及目录结构 / 文件布局 / 架构关系 |
| `## 数据模型 / Schema` | 有数据 / 接口需要定义 |
| `## 接口设计` | CLI / API / SDK 设计 |
| `## 子系统设计` | 多个独立 subsystem |
| `## 配置` | 需要配置文件 |
| `## 安全策略` | 涉及凭据 / 用户数据 / 安全约束 |
| `## 改动范围` | 重构 / 修改已有产品时（必有） |

### 按实际需要补充

| 章节 | 何时填 |
|---|---|
| `## 依赖` | 涉及跨仓 / SDK / schema |
| `## 灰度` | 涉及 feature flag |
| `## 回归点` | 涉及外部 caller / 关键 UI 场景 / 数据维度 |

## 关键约定

- **无 frontmatter**：spec 是普通 markdown，slug 在 filename，时间靠 git history
- **可以写技术细节**：TypeScript types / SQL schema / TOML config / 接口签名 / CLI 命令 / 数据流图 / 数据库字段表——spec 是产品规范
- **实现期偏差直接改原文**：不创建 `## 调整记录` 章节；git commit 写清"调整 spec § X：<原因>"
- **`## 后续实现顺序` 是高层路径**，大需求时细化到 `docs/plans/<slug>.md`（plan = 执行节奏 + reviewed 列 + Y-only 决策记录）
- **plan 不嵌代码细节**：plan 只写步骤节奏 + 观察点 + 验证方式 + reviewed + 决策记录；spec 才允许技术细节
- **对标 superpowers spec**：同形态（产品设计图 + 实现路径 + 验收 + 改动范围 + 后续实现顺序）；差别仅在 flow-spec 把"执行节奏"剥离到 plan
- **不要写 `## 涉及矩阵`**：涉及判断只用于 flow-spec 内部 plan 判定，不作为 spec 正文章节
