# Frontend fixture：预约卡片状态信息

## 已确认需求

预约列表中的卡片需要直接展示服务状态和负责员工；取消状态使用弱化样式，避免与进行中的预约混淆。这是单个组件内的视觉与可访问性调整。

## 目标

- kind: range
- identity: fixture/frontend-booking-card
- base: fixture-base-c
- head: fixture-head-c

## Diff 摘要

```diff
diff --git a/src/booking/BookingCard.tsx b/src/booking/BookingCard.tsx
@@
 export function BookingCard({ booking }: Props) {
+  const isCancelled = booking.status === "cancelled";
   return (
-    <article className="booking-card">
+    <article className={cx("booking-card", { "booking-card--muted": isCancelled })}>
       <h3>{booking.petName}</h3>
+      <p aria-label="服务状态">{statusLabel[booking.status]}</p>
+      <p>{booking.assigneeName}</p>
     </article>
   );
 }

diff --git a/src/booking/BookingCard.css b/src/booking/BookingCard.css
@@
+.booking-card--muted { opacity: 0.62; }

diff --git a/src/generated/api-types.ts b/src/generated/api-types.ts
@@
+// 由 schema 重新生成，共 420 行机械差异

diff --git a/src/booking/__snapshots__/BookingCard.snap b/src/booking/__snapshots__/BookingCard.snap
@@
+// 快照更新，共 180 行
```

## 已有附件

- `evals/fixtures/assets/booking-card-after.png`：设计验收提供的改后截图，需挂在“预约状态信息”这一主要变化下。

## 约束

- 只生成本地中文 Review Brief。
- 根据改动复杂度自行选择 Brief 模式；已有真实 UI 截图可用于说明视觉变化。
- 生成类型和快照是机械变化，不进入阅读主线。
- 未授权 GitHub 或 Slack 写入。
