# Full fixture：预约提醒异步链路

## 已确认需求

预约创建接口不再同步调用短信供应商。成功保存预约后，系统投递提醒任务，由 worker 发送短信；供应商超时会最多重试两次，最终结果通过 webhook 回写提醒状态。目标是缩短 API 响应时间，并让未知外部结果进入可追踪状态而不是立即重复发送。

## 目标

- kind: branch
- identity: fixture/full-async-reminder
- base: fixture-base-b
- head: fixture-head-b

## Diff 摘要

```diff
diff --git a/src/api/createBooking.ts b/src/api/createBooking.ts
@@
-await smsClient.sendReminder(booking);
+await reminderService.dispatchReminder(booking.id);

diff --git a/src/reminders/reminderService.ts b/src/reminders/reminderService.ts
@@
+export async function dispatchReminder(bookingId: string) {
+  await reminderRepository.markQueued(bookingId);
+  await reminderQueue.publish({ bookingId, attempt: 0 });
+}

diff --git a/src/reminders/reminderWorker.ts b/src/reminders/reminderWorker.ts
@@
+export async function sendReminder(job: ReminderJob) {
+  try {
+    const requestId = await smsClient.send(job.bookingId);
+    await reminderRepository.markAwaitingCallback(job.bookingId, requestId);
+  } catch (error) {
+    if (isTimeout(error) && job.attempt < 2) {
+      await reminderQueue.publish({ ...job, attempt: job.attempt + 1 });
+      return;
+    }
+    await reminderRepository.markFailed(job.bookingId);
+  }
+}

diff --git a/src/webhooks/applyReminderResult.ts b/src/webhooks/applyReminderResult.ts
@@
+export async function applyReminderResult(payload: SmsCallback) {
+  await reminderRepository.completeByRequestId(payload.requestId, payload.status);
+}

diff --git a/src/reminders/reminderStatus.ts b/src/reminders/reminderStatus.ts
@@
-export type ReminderStatus = "pending" | "sent" | "failed";
+export type ReminderStatus = "pending" | "queued" | "awaiting_callback" | "sent" | "failed";
```

## 直接调用关系

1. `createBooking` 保存预约后调用 `dispatchReminder`。
2. `dispatchReminder` 先写入 `queued`，再向 `reminderQueue` 发布任务。
3. `sendReminder` 调用短信供应商；超时在队列层最多重试两次。
4. 供应商返回 request id 后进入 `awaiting_callback`。
5. `applyReminderResult` 按 request id 回写 `sent` 或 `failed`。

## 约束

- 根据行为复杂度自行选择 Brief 模式，并判断技术图是否能明显降低理解成本。
- 不执行 GitHub asset 上传或 Slack 发布。
