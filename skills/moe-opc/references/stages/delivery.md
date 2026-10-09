# Delivery｜联调与验收

## 标准动作

用户点名 Delivery、联调验收或重新验收时，立即整理当前可用业务输入并调用 `$moe-acceptance`。不检查 Development、Approved Scope、首次 Pass、驾驶舱或任何 OPC 产物；也不展示确认卡。

联调环境、测试数据、动态 Case、证据与结论的事实源是 owner Skill。已有上下文由同一 AI 继续使用，缺什么才补什么。OPC 只传业务输入并回填结果，不要求创建 Delivery ID、冻结计划或运行旧 lane/finalize 命令；没有报告需求时，验收摘要即可交付。

## JIT 执行参数

在 owner Skill 实际需要时解析当前实现 identity、可用 AC/业务目标、surface、环境意图、账号、Flag/Grey、数据限制和允许副作用。字段缺失时先从当前系统和用户请求发现；仍未知则传 Unknown/Limitations，让 owner Skill 返回可执行结果或真实拒绝。

## 执行

1. 依据 `assets/templates/delivery-handoff.md` 形成当前可用输入，不要求先存在正式 handoff。
2. 调用 owner Skill 继续当前验收；变化后只复验受影响内容，业务标准存在关键缺口时由 owner Skill 集中对齐。
3. 回填实现与上下文、surface、各 Case 的通过/不通过/信息不足、覆盖范围、证据充分性、约定交付物完成情况、未执行项、limitations、side effects 和用户 review。实际生成报告时再记录 task_id、报告路径及已有 report_round；没有这些可选字段不阻止验收完成。
4. owner Skill 的权限、环境或安全合同真实拒绝时，记录本轮 Blocked；缺 OPC 前序产物本身不能产生 Blocked。
5. 用户显式要求产品/设计走查时加载对应 communication reference，按当前可用证据立即执行；Delivery finalized 只控制自动发起走查。

## 自动衔接

仅当 Development 准备自动进入首次 Delivery 时，使用 `execution-boundaries.md` 的自动条件。条件不满足记录 `DELIVERY_NOT_AUTO_STARTED`，不调用 owner Skill；该结果不影响之后的 Explicit Delivery。

首次 Pass 后不自动再次 Delivery。用户点名重新 Delivery 时直接执行，不读取首次生命周期或自动条件。

## 结果与回读

- 结论必须能对应实际实现、环境、Case 观察与证据；已有报告按同一路径回读和更新。报告轮次只表示内容与证据归属，不作为业务执行前置。
- OPC 的 Pass 表示约定业务目标通过，且必要证据与约定交付物完整；业务通过但证据不足不能写为 Pass。finalized 仅表示本次约定验收已结束、结果与交付物已核对，是 OPC 对实际结果的判断，不是向 owner Skill 索取的 seal 或 CLI 状态。
- Fail/Blocked/Partial 不写成 Pass，也不表示用户下次需要额外授权。
- 实现、AC、环境、账号或 Flag/Grey 变化只使受影响的旧结论适用性 Stale，不自动启动新验收或生成报告轮次。
- 记录位置不可用时在响应交付完整 owner Skill 结果，不反向否定本轮执行。
