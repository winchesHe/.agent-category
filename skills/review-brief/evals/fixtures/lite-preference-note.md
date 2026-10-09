# Lite fixture：清空偏好备注

## 已确认需求

用户在偏好设置页清空备注并保存后，旧备注仍会显示。更新接口已经约定：字段缺失表示不修改，`null` 表示清除。此次改动只修复前端 payload 的清空语义。

## 目标

- kind: worktree
- identity: fixture/lite-preference-note
- base: fixture-base-a
- head: fixture-head-a

## Diff

```diff
diff --git a/src/preferences/toUpdatePayload.ts b/src/preferences/toUpdatePayload.ts
index 12a..34b 100644
--- a/src/preferences/toUpdatePayload.ts
+++ b/src/preferences/toUpdatePayload.ts
@@ -8,7 +8,10 @@ export function toUpdatePayload(input: PreferenceForm) {
   return {
     receiveReminder: input.receiveReminder,
-    note: input.note || undefined,
+    note:
+      input.note === undefined
+        ? undefined
+        : input.note.trim() === "" ? null : input.note.trim(),
   };
 }
diff --git a/src/preferences/toUpdatePayload.test.ts b/src/preferences/toUpdatePayload.test.ts
index 56c..78d 100644
--- a/src/preferences/toUpdatePayload.test.ts
+++ b/src/preferences/toUpdatePayload.test.ts
@@ -20,3 +20,8 @@ describe("toUpdatePayload", () => {
+  it("maps an empty note to null", () => {
+    expect(toUpdatePayload({ receiveReminder: true, note: "  " }).note).toBeNull();
+  });
 });
```

## 约束

- 只生成本地中文 Review Brief。
- 没有 GitHub 或 Slack 发布授权。
- 测试可作为理解语义的证据，但用户可见 Brief 不展示测试执行状态或结果。
