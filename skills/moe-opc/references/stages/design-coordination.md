# Design Coordination｜设计协调

## 标准动作

用户点名设计协调时立即执行：判断当前变更是否需要外部设计，创建/更新 Design Ticket，或记录 `Not Required`；设计输入已经存在时直接核对并回读。OPC 不生成 Figma。

## JIT 执行参数

在判断或写 Ticket 时解析当前产品语义、现有 UI/设计系统、Design Ticket、Assignee/Owner、Figma node/version 和适用端。当前可用 PRD 有则参考，缺少时从用户请求、Jira 和当前 UI 读取所需事实。

## 执行

1. 核对当前 UI、可复用设计系统和需要覆盖的端/状态。
2. 纯复用且语义明确时记录 `Not Required`；视觉、交互或关键状态需要新输入时创建/更新唯一 Design Ticket。
3. 写入 requirement identity、设计范围、端/状态、Owner 和交接信息并回读。
4. 已有 Figma 输入时核对 node/version、主流程、空态/loading/error/权限/响应式状态。
5. 执行中出现新的产品范围或交互策略选择时才中断询问；没有外部设计稿本身不构成 Blocked。

## 结果与回读

- 结果可以是 `Not Required`、`Requested`、`Ready` 或带 Limitations 的 Partial。
- Ticket、Owner、需求关联、字段和当前设计输入按可用对象回读。
- `Requested` 表示标准协调动作已完成但在等待真实外部输入，不等同于阶段没有执行。
- 重入按 Design Ticket identity update/skip/reconcile，不重复创建。
