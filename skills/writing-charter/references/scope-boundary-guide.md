# Scope Boundary 编写指南

## 两种 Scope

| 类型 | 定义 | 在哪里定义 |
|------|------|-----------|
| Product scope | 项目交付什么产物/变化 | Charter Phase 1（本阶段） |
| Project scope | 做哪些工作来交付这些产物 | Planning Phase 2（WBS 分解） |

**Charter 中定义的是 product scope**——描述"交付什么"，不描述"做哪些工作"。

## 三件事

### In — 本项目会交付什么

描述具体的产物或变化，而非笼统的愿景：

- ✅ "为 B Web 项目接入多语言支持，覆盖中文和日语"
- ❌ "支持国际化"（太笼统）
- ❌ "用 i18next 实现翻译加载"（这是 solution detail，不是 scope）

### Out — 显式排除（不是我们的问题）

列出容易被误认为属于本项目但实际不做的东西：

- ✅ "后端 API 响应的多语言化不在本项目范围"
- ✅ "RTL（从右到左）语言支持不在本期"
- ✅ "用户自定义内容的翻译不属于本项目"

### Deferred — 承认重要但不是这期

和 Out 的区别：Deferred 的东西我们承认重要、未来会做，但不是现在：

- ✅ "邮件和 Push 通知的多语言化——重要但留到第二期"
- ✅ "翻译质量自动化检测——当翻译量达到一定规模后再建设"

## 为什么 Out 和 Deferred 比 In 更重要

> "Most scope disputes happen because two people are talking about different layers without realizing it."

In 列表告诉人们"你会做什么"——但 Out 和 Deferred 列表告诉人们"别来找我要这些"。它们防止的争议远多于 In 列表。

没有清晰的边界，就无法检测 Scope Creep——因为你不知道"边界在哪"。

## 写法原则

1. **具体到可判定**：别人读完能判断"这个需求属于 In 还是 Out"
2. **不写 solution**：Scope 描述产物特征，不描述实现方式
3. **边界而非影响**：ProjM 控制的是边界，不是涟漪效应（ripple effects）
4. **每条可独立理解**：不依赖上下文即可理解

## 常见错误

### 错误 1: In 列表过于笼统

- ❌ "建设 i18n 基础设施"
- ✅ "为 B Web 和 B App 两个项目接入统一的多语言运行时；部署翻译管理平台；建立翻译工作流 CI/CD"

### 错误 2: 没有 Out 列表

没有显式排除 → 所有人默认"你都会做" → Scope Creep

### 错误 3: Out 和 Deferred 混淆

- Out = 不是这个项目的事，可能永远不做
- Deferred = 会做但不是现在

### 错误 4: Scope 写成了 Solution

- ❌ "使用 i18next + react-i18next 作为运行时"（这是 solution）
- ✅ "所有前端项目使用同一套 i18n 运行时，支持 Web 和 RN"（这是 scope）

## 模板

```markdown
### In Scope

- [具体产物/变化 1]
- [具体产物/变化 2]
- [具体产物/变化 3]

### Out of Scope

- [显式排除 1] — [为什么排除的简要理由]
- [显式排除 2] — [理由]

### Deferred

- [重要但不是这期 1] — [何时或什么条件下做]
- [重要但不是这期 2] — [条件]
```
