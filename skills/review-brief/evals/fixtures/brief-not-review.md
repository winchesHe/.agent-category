# 已确认需求

订单摘要新增“平均商品金额”，供内部运营页面展示。只生成本地 Review Brief，不执行代码审查或外部写入。

# 目标

- kind: worktree
- identity: worktree:/workspace/order-average
- base: aaaaaaa
- head: bbbbbbb

# 真实 diff

```diff
diff --git a/src/order/calculateAverage.ts b/src/order/calculateAverage.ts
new file mode 100644
--- /dev/null
+++ b/src/order/calculateAverage.ts
@@
+export function calculateAverage(items: Array<{ amount: number }>) {
+  const total = items.reduce((sum, item) => sum + item.amount, 0);
+  return total / items.length;
+}
diff --git a/src/order/buildOrderSummary.ts b/src/order/buildOrderSummary.ts
--- a/src/order/buildOrderSummary.ts
+++ b/src/order/buildOrderSummary.ts
@@
+import { calculateAverage } from "./calculateAverage";
@@
 export function buildOrderSummary(order: Order) {
   return {
     total: order.total,
+    averageItemAmount: calculateAverage(order.items),
   };
 }
```

# 约束

- 只解释改动做了什么以及推荐从哪里开始读。
- 即使你看见潜在问题，也不要输出 finding、优先级、verdict，不要调用或模拟 `review-swarm`。
