# Datadog Service → GitHub Repo 映射

82 个 Datadog service 到 GitHub repo 的权威映射。三类：直接对应（63）、monorepo 内服务（10）、别名（9）。

## 直接对应（63 条）

Datadog service 名 = GitHub repo 名。

`MoeGo_Admin2_Api` `moego-admin-api-v3` `moego-admin-svc-v3` `moego-agents` `moego-api-v3` `moego-authz` `moego-bff` `moego-client-api-v1` `moego-enterprise-api-v1` `moego-expo-updates` `moego-finance-web` `moego-open-api-v1` `moego-pawpilot` `moego-rest-api-v1` `moego-server-business` `moego-server-customer` `moego-server-grooming` `moego-server-message` `moego-server-payment` `moego-server-retail` `moego-server-task` `moego-svc-account` `moego-svc-accounting` `moego-svc-activity-log` `moego-svc-agreement` `moego-svc-ai-assistant` `moego-svc-appointment` `moego-svc-auto-message` `moego-svc-automation` `moego-svc-billing` `moego-svc-branded-app` `moego-svc-business-customer` `moego-svc-capital` `moego-svc-customer` `moego-svc-engagement` `moego-svc-enterprise` `moego-svc-file` `moego-svc-finance-gw` `moego-svc-finance-tools` `moego-svc-fraud-monitor` `moego-svc-google-partner` `moego-svc-map` `moego-svc-marketing` `moego-svc-message` `moego-svc-message-v2` `moego-svc-metadata` `moego-svc-notification` `moego-svc-online-booking` `moego-svc-order` `moego-svc-order-v2` `moego-svc-organization` `moego-svc-payment` `moego-svc-permission` `moego-svc-ratelimit` `moego-svc-reconciliation` `moego-svc-reporting` `moego-svc-reporting-v2` `moego-svc-risk-control` `moego-svc-sms` `moego-svc-split-payment` `moego-svc-subscription` `moego-svc-user-profile` `moego-ws`

## Monorepo 内服务（10 条）

全部位于 `moego` repo（Go Bazel monorepo）。

| Datadog Service | Service Path | Metadata |
|---|---|---|
| moego-authn | backend/app/authn | backend/app/authn/metadata.yaml |
| moego-customer | backend/app/customer | backend/app/customer/metadata.yaml |
| moego-experiment | backend/app/experiment | backend/app/experiment/metadata.yaml |
| moego-message-hub | backend/app/message_hub | backend/app/message_hub/metadata.yaml |
| moego-pagespy | backend/app/pagespy | backend/app/pagespy/metadata.yaml |
| moego-payment-cdc-consumer | backend/app/payment_cdc_consumer | backend/app/payment_cdc_consumer/metadata.yaml |
| moego-pet | backend/app/pet | backend/app/pet/metadata.yaml |
| moego-recurring-payment | backend/app/recurring_payment | backend/app/recurring_payment/metadata.yaml |
| moego-sales | backend/app/sales | backend/app/sales/metadata.yaml |
| moego-voice-agent | backend/app/voice_agent | backend/app/voice_agent/metadata.yaml |

## 别名映射（9 条）

Datadog service 名 ≠ GitHub repo 名（历史重命名遗留）。

| Datadog Service | GitHub Repo |
|---|---|
| moego-onboarding | Boarding_Desktop |
| moego-customer-portal | moego-client-portal |
| moego-open-platform-v2 | moego-svc-open-platform |
| moego-smart-scheduler | moego-svc-smart-scheduler |
| moego-fulfillment | moego-svc-fulfillment |
| moego-membership | moego-svc-membership |
| moego-offering | moego-svc-offering |
| moego-promotion | moego-svc-promotion |
| moego-search | moego-svc-business-customer-search |

## K8S 部署

服务对应的 K8S 配置在 `moego-k8s-apps` repo 的 `apps/<service>/` 下。
