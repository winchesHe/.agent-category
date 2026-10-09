# MeterSphere API 参考

## 目录

- 鉴权与成功判定
- 当前实例能力
- 功能模块
- 功能用例
- 用例评审
- 能力探测

## 鉴权与成功判定

请求头使用 `accessKey` 和动态 `signature`。项目级请求同时发送 `PROJECT`。

成功必须满足：

- HTTP 状态为 2xx；
- JSON 响应不是 `success:false`；
- 写操作能够通过查询接口回读。

## 当前实例能力

使用 `GET /track/v3/api-docs` 获取测试跟踪 OpenAPI。不要依据旧版 `/functional/**` 路径猜测。

`/api/v3/api-docs` 不可用时，当前实例不支持本 skill 的接口定义/接口用例命令。

## 功能模块

- `POST /track/case/node/list/{projectId}`
- `POST /track/case/node/add`
- `POST /track/case/node/delete`，body 为模块 ID array

新增模块常用字段：`projectId`、`name`、`parentId`、`level`、`pos`。

## 功能用例

- `POST /track/test/case/list/{current}/{pageSize}`
- `GET /track/test/case/get/edit/simple/{id}`
- `POST /track/test/case/add`
- `POST /track/test/case/edit`
- `POST /track/test/case/delete/{testCaseId}`

`add` 和 `edit` 均为 `multipart/form-data`，JSON 放在名为 `request` 的 part 中。`nodePath` 是写入必填字段；编辑时保留原始 `id/refId/versionId` 并设置 `latest:true`。

## 用例评审

- 项目评审单：`POST /track/test/case/review/list/{current}/{pageSize}`
- 全部评审单：`POST /track/test/case/review/list/all`
- 评审单详情：`GET /track/test/case/review/get/{id}`
- 评审单中的用例：`POST /track/test/review/case/list/{current}/{pageSize}`，body 含 `reviewId`
- 评审模块：`POST /track/case/review/node/list/{projectId}`
- 评审人：`POST /track/test/case/review/reviewer`，body 至少含评审单 `id`

“某用例是否被评审过”采用可靠反查：遍历项目评审单，再在各评审单用例列表中按 `caseId` 匹配。匹配记录非空即为已评审。不要把 `/track/test/case/reviews/case/**` 当成按 caseId 反查评审记录；当前实例会忽略错误过滤字段并返回大量用例。

评审状态按 API 原值输出，当前常见值包括 `Prepare`、`Pass`、`UnPass`、`Underway`、`Again`。

## 能力探测

模板服务或 API 测试服务可能未部署。运行：

```bash
python3 scripts/metersphere.py doctor
```

能力不可用时返回明确错误，不切换浏览器、不猜 endpoint。
