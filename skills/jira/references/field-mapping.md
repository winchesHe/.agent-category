# CS Project Field Mapping

CS 工单常用 Jira 字段映射。更新字段时优先用 `update` 的语义 patch key；只有用户明确提供 Jira field ID 时，才使用 `additionalFields` 透传。

## Tagging

| Field ID | Name | 用途 |
|---|---|---|
| `customfield_10089` | Squad | 团队/业务域分类 |
| `customfield_11580` | Feature Domains | 功能域 |
| `components` | Components | 组件分类 |
| `customfield_10088` | Issue Cause | 根因分类；`update` patch key 为 `issueCause` |
| `customfield_10078` | Defect Type | 缺陷分类 |

## Root Cause

| Field ID | Name | 用途 |
|---|---|---|
| `customfield_10084` | Cause and Solution | 根因与解决方案；`update` patch key 为 `causeAndSolution` |

## Customer Context

| Field ID | Name |
|---|---|
| `customfield_10414` | User Tier |
| `customfield_11160` | [T1] Logo Name |
| `customfield_11382` | [T1] Location Name |
| `customfield_11157` | [T1] MoeGo Login Email |
| `customfield_11218` | MoeGo Login Email |
| `customfield_11158` | [T1] Customer Role |
| `customfield_11159` | [T1] Customer Stage |
| `customfield_11161` | [T1] User Name |
| `customfield_11317` | SLA Breach |

## Description Fields

| Field ID | Name |
|---|---|
| `description` | Description |
| `customfield_10340` | Issue Description |
| `customfield_10052` | Bug Description |
| `customfield_11156` | Reproduce Steps |
| `customfield_10084` | Cause and Solution |
| `customfield_10053` | Story Description |

## Timeline and People

| Field ID | Name |
|---|---|
| `created` | Created |
| `updated` | Updated |
| `customfield_13126` | QA Investigation Start |
| `customfield_13170` | Bug Confirmed At |
| `assignee` | Assignee |
| `creator` | Creator |
| `reporter` | Reporter |
