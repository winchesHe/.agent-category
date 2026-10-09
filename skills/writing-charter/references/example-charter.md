# 范例 Charter：Engineer Knowledge Portal

> 本范例基于真实项目脱敏改写，展示多受益人、表格驱动的 Charter 形态（不含 Solution）。

---

# Engineer Knowledge Portal

> Owner: Alex (ProjM) | Sponsor: Jordan (EM)
> 状态：已批准
> 创建日期：2026-05-01

## Business Case

### 受益人与未满足需求

| 受益人 | 需要什么 | 当前差距 |
|--------|----------|----------|
| **新入职工程师**（入职 < 3 月） | 遇到工程问题时能快速找到可信答案，不依赖口口相传 | 首月 survey 均反馈"找不到准确的工程文档"是最大痛点；只能翻聊天记录或找人问 |
| **全体工程团队**（30+ 人） | 减少重复答疑的时间消耗，让知识可发现、可复用 | #tech-questions 中 60% 的问题可以被已有文档回答——但提问者找不到 |
| **团队 lead / EM** | 有治理机制确保知识不腐化 | 现有 Wiki 40% 页面超 6 个月未更新，缺少 owner 标识 |

### Supporting Observations

- 最近 3 位入职同学在首月 survey 中均反馈"找不到准确的工程文档"是最大痛点
- #tech-questions channel 中 60% 的问题可以被已有文档回答——但提问者找不到
- 现有 Wiki 页面中有 40% 超过 6 个月未更新，缺少 owner 标识
- 团队规模已超过 30 人，"问熟人"的方式边际成本显著上升

### Why Now?

1. **现在不做会发生什么**：团队继续增长，口口相传的模式将持续恶化；已有半成品页面继续消耗信任，"Wiki 没用"会成为共识；AI 协作窗口已到，但知识源不可信会放大错误
2. **现在做的窗口**：当前团队规模可控，一次性治理成本尚可承受；已有一批内容基础，不是从零开始；现在建好结构，AI 能力可以建立其上

## SMART Objective

项目结束时：
1. **Wiki 成为默认入口** — 新同学遇到工程问题时默认先查 Wiki，不再严重依赖口口相传
2. **高频问题有稳定入口** — 常见问题通过 Wiki 可快速找到答案，不需要在 Slack 里重复提问
3. **核心页面可维护** — 每个核心页面有明确的 owner 和更新机制，不再出现长期无人维护的情况

## High-Level Scope

### In Scope

| 受益人 | 施工面 | 类型 |
|--------|--------|------|
| 新入职工程师 | 信息架构冻结：一级结构、核心入口页、P0/P1/P2 页面清单 | 新增 |
| 全体工程团队 | P0/P1 页面内容建设：覆盖 Wiki 骨架和最高频问题 | 新增 |
| 团队 lead / EM | 页面治理机制：owner / status / review 周期落到每个页面 | 新增 |
| 全体工程团队 | 维护指南：《如何创建和维护 Wiki》指南页 | 新增 |
| 全体工程团队 | AI 协作能力：至少一套可用的 wiki 查询和编辑能力 | 新增 |

### Out of Scope

- 历史文档一次性清仓——不尝试补齐所有历史文档
- 替代各 squad 专业文档体系——Wiki 是统一入口，不是唯一存放地
- 大型知识平台建设——不建设复杂自动化平台或知识图谱

### Deferred

- P2 页面建设——进入下一周期 backlog
- 完整的自动过时检测系统——当维护机制跑顺后再考虑自动化
- 跨团队 Wiki 统一——先做好 Eng Wiki，其他团队按需参考

## Stakeholder & Authorization

### Power / Interest

|  | Low Interest | High Interest |
|--|--|--|
| **High Power** | — | Jordan（Sponsor，审批方案 + 资源优先级） |
| **Low Power** | — | 新 onboarding 同学（直接受益人）；跨团队协作方 PM/Design（入口用户） |

### Resources

| 角色 | 人选 | 职责 |
|------|------|------|
| Sponsor | Jordan (EM) | 优先级背书、关键取舍拍板、阶段性 review |
| Owner / ProjM | Alex | 对目标、范围、节奏、交付质量和验收负责 |
| 领域 owner | 各模块负责人 | 对所属页面的正确性和按期 review 负责 |

### Budget & Timeline

- **Budget ceiling**: 无额外预算，利用现有人力（各 owner 每周 2-4h）
- **Timeline envelope**: 90 天（3 个月）

### Communication Plan

| 时间点 | 对谁 | 沟通什么 | 方式 |
|--------|------|----------|------|
| 立项通过 | 全体 Eng | 项目启动、预告 Wiki 结构变化 | Slack #team-tech |
| 第 4 周 | Jordan | P0 页面建设进度、blocker | 1:1 |
| 第 8 周 | 全体 Eng | Wiki 试用邀请 + 反馈收集 | Slack + 表单 |
| 90 天 | Jordan | 验收数据汇报 | 书面 |

## Risk & Uncertainty

| 风险 | 可能性 | 影响 | 应对策略 |
|------|--------|------|----------|
| 范围膨胀——想一次性做完 | 中 | 高 | 锁定 P0/P1，新需求进 backlog |
| Owner 投入不足——页面停在半成品 | 中 | 高 | 先缩 P0 面积再分配 owner，避免愿望清单 |
| 写了很多但没人用 | 中 | 高 | 围绕高频路径建设，路径测试验证 |
| 页面很快过时 | 中 | 中 | Owner + 状态 + review 周期做成显式表面 |
