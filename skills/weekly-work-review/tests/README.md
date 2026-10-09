# 迁移基线

本目录保存最小归档包 fixture，用于记录迁移时 `validate-package.mjs` 的行为。

当前阶段只建立基线，不声称已修复以下已知问题：

- `export-meeting-pdfs.mjs --dry-run` 可能写文件；
- validator 尚未实现完整凭证形状扫描；
- 只有 frontmatter 的会议正文可能被当作存在；
- `Validation Readback` 尚未与当前包 hash 绑定。

运行：

```bash
node weekly-work-review/scripts/validate-package.mjs weekly-work-review/tests/fixtures/minimal-valid
```
