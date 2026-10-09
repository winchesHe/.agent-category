# Obsidian 输出

## 何时读取

目标是 Obsidian Vault 或 Obsidian Flavored Markdown 时读取。若环境中有 `obsidian-markdown`，用它遵循 Vault 的既有属性、链接、附件和 callout 约定。

## 渲染规则

- Overview 作为 Hub Note，专题页使用 `[[wikilink]]` 互相导航。
- 使用 `> [!summary]`、`> [!important]` 等 callout 表达一句话结论和关键不变量，但不要让整页都变成 callout。
- 图稿放入 Vault 约定的附件目录，通过 `![[diagram.svg]]` 或 `![[diagram.png]]` 嵌入；Vault 支持 Mermaid 时也可使用 Mermaid fenced block。
- Frontmatter 只写现有 Vault 已使用或用户明确需要的字段；不要默认添加 owner、status、reviewed_at 等元数据。
- 保持文件名、标题和 wikilink 稳定。重构页面时同步更新反向链接或建立明确的迁移链接。
- 不使用依赖第三方插件的查询、布局或脚本语法，除非已确认该 Vault 使用对应插件。

## 文档集建议

```text
系统架构/
├── 系统架构概览.md
├── 请求执行模型.md
├── 状态与持久化.md
├── 能力装配.md
├── 交付与恢复.md
└── assets/
    └── architecture-*.svg
```

实际目录服从 Vault 现有组织方式，不强制创建这套结构。

## 验收

- 检查 wikilink、嵌入资源和相对路径。
- 检查属性与 Vault 既有 schema 一致。
- 打开或渲染代表性页面，确认 callout、表格、代码块和图稿没有断裂。
- 多文件文档必须能从 Overview 到达每个专题，并从专题返回 Overview。
