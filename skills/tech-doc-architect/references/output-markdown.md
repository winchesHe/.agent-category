# 通用 Markdown 输出

## 何时读取

目标是 Git 仓库、静态站点、代码评审附件或平台无关 Markdown 时读取。

## 可移植性规则

- 使用 CommonMark / GitHub Flavored Markdown 的标题、列表、表格、代码块和相对链接。
- 不使用飞书 XML、Obsidian wikilink、专有 callout 或依赖未声明插件的语法。
- 图稿优先使用相对路径链接到 SVG / PNG；确认目标渲染器支持 Mermaid 时，可以使用 Mermaid fenced block 并保留源码。
- 多文件文档使用稳定的 kebab-case 文件名和相对链接；单文件较长时提供简洁目录。
- 代码入口链接在仓库内使用相对路径；不要输出只在当前机器有效的绝对路径。
- Frontmatter 只在目标站点或生成器需要时加入。

## 推荐结构

```text
docs/architecture/
├── README.md
├── request-lifecycle.md
├── state-and-persistence.md
├── capability-loading.md
├── delivery-and-recovery.md
└── diagrams/
```

这只是常见布局。若仓库已有文档规范，应复用现有位置、命名和导航。

## 验收

- 使用仓库现有 Markdown lint 或文档构建命令（若存在）。
- 检查所有相对链接和图片路径。
- 渲染至少一个 Overview 和一个复杂专题，确认表格、代码块和图稿可读。
- 确认从 Markdown 复制到其他平台时不会暴露本机路径或依赖隐式插件。
