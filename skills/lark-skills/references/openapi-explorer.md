# openapi-explorer：飞书 / Lark 原生 OpenAPI 兜底

对应 lark-cli 的 `lark-openapi-explorer`。当用户需求**无法**被现有 reference 或 lark-cli 已注册命令满足时，从飞书官方 markdown 文档库逐层挖掘原生 OpenAPI 接口，再用 `lark-cli api` 裸调。

> 鉴权 / 身份切换 / Permission denied 处理见 [`lark-shared.md`](./lark-shared.md)。

## 适用场景（仅当其它 reference 不覆盖）

- 部门树遍历、按部门列员工、组织架构图
- 群公告（PATCH `/im/v1/chats/:chat_id/announcement`）等没封装的 IM 长尾接口
- 任何 lark-cli 没注册 shortcut / 命令的飞书原生 OpenAPI

⚠️ 进入本 reference 前**先确认其它 reference 不能覆盖**——已有命令更安全、更稳。

## 文档库结构

飞书 OpenAPI 以分层 markdown 文档发布：

```
llms.txt                          ← 顶层索引，列出所有模块文档链接
  └─ llms-<module>.txt            ← 模块文档：功能概述 + 底层 API 链接
       └─ <api-doc>.md            ← 单个 API 完整说明（HTTP 方法 / 路径 / 参数 / 响应 / 错误码）
```

入口：

| 品牌 | 入口 |
|---|---|
| 飞书（Feishu）| `https://open.feishu.cn/llms.txt` |
| Lark | `https://open.larksuite.com/llms.txt` |

> 飞书品牌默认入口；Lark 海外品牌走 larksuite.com。如不确定用户品牌，**默认飞书**。
> 文档以**中文**编写。如果用户用英文交流，需将文档内容翻译为英文再输出。

## 挖掘流程（**严格**逐层、不跳步、不猜）

### Step 1：确认现有能力不足

```bash
# 先翻 lark-cli 是否有对应 service
lark-cli <可能的 service> --help
# 或翻本 lark-skills 的决策树（主 SKILL.md）
```

如果已有 shortcut / 命令——**直接用**，不挖。

### Step 2：从顶层索引定位模块

用 `WebFetch` 取顶层索引：

```
WebFetch https://open.feishu.cn/llms.txt
  提取问题："列出所有模块文档链接，找出与 <用户需求关键词> 相关的链接"
```

### Step 3：从模块文档定位具体 API

```
WebFetch https://open.feishu.cn/llms-docs/zh-CN/llms-<module>.txt
  提取问题："找出与 <用户需求> 相关的 API 说明和文档链接"
```

### Step 4：取 API 完整规范

```
WebFetch https://open.feishu.cn/document/server-docs/.../<api>.md
  提取问题："返回完整 API 规范：HTTP 方法、URL 路径、路径参数、查询参数、请求体字段（名称/类型/必填/说明）、响应字段、所需权限、错误码"
```

### Step 5：用 CLI 裸调

```bash
# GET
lark-cli api GET /open-apis/<path> --params '{"key":"value"}'

# POST
lark-cli api POST /open-apis/<path> --data '{"key":"value"}'

# PUT
lark-cli api PUT /open-apis/<path> --data '{"key":"value"}'

# DELETE
lark-cli api DELETE /open-apis/<path>
```

## 输出规范（呈现给用户时）

按以下顺序：

1. **API 名称与功能**：一句话描述
2. **HTTP 方法与路径**：`METHOD /open-apis/...`
3. **关键参数**：必填 + 常用可选
4. **所需权限**：scope 列表
5. **调用示例**：完整 `lark-cli api ...` 命令
6. **注意事项**：频率限制、特殊约束等

英文用户：以上 6 项翻译成英文输出。

## 安全规则

- 写入 / 删除（POST / PUT / DELETE）调用前**必须用户确认意图**
- 支持 `--dry-run` 时优先预览
- **不要凭路径猜参数**——必须从文档拿到确认
- 敏感操作（删群、移除成员、批量删数据）向用户说明影响范围

## 使用场景示例

### 场景 1：拉人进群（CLI 没封装）

```bash
# Step 1：确认 CLI 没封装
lark-cli im --help
# → 没有 chat_members create

# Step 2-4：挖文档拿到 API
# → POST /open-apis/im/v1/chats/:chat_id/members

# Step 5：调用
lark-cli api POST /open-apis/im/v1/chats/oc_xxx/members \
  --data '{"id_list":["ou_xxx","ou_yyy"]}' \
  --params '{"member_id_type":"open_id"}'
```

### 场景 2：设置群公告

```bash
# Step 1：CLI 无 announcement
lark-cli im --help

# Step 2-4：挖文档
# → PATCH /open-apis/im/v1/chats/:chat_id/announcement

# Step 5：调用
lark-cli api PATCH /open-apis/im/v1/chats/oc_xxx/announcement \
  --data '{"revision":"0","requests":["<html>公告内容</html>"]}'
```

### 场景 3：部门树查询

```bash
# 通讯录的部门搜索 / 子部门列表都是这个域
lark-cli api POST /open-apis/contact/v3/departments/search --as user \
  --params '{"department_id_type":"open_department_id"}' \
  --data '{"query":"研发"}'
```

## NEVER 规则（领域特有）

- ❌ **不要在已有 shortcut 时改走 `lark-cli api`**——shortcut 通常更稳、参数校验更好。
- ❌ **不要凭路径猜参数 / 字段名**——一律从文档取。
- ❌ **POST/PUT/DELETE 不要无确认直接执行**。
- ❌ **不要用错品牌入口**：飞书走 `feishu.cn`，Lark 走 `larksuite.com`。
- ❌ **不要把搜不到结果就当作"该 API 不存在"**——先确认搜索词、模块入口是否正确。

## 不在本 reference 范围

- 已经被 lark-cli 封装过的 service / shortcut → 走对应 reference
- 把挖到的 API 固化为 lark-skill / shortcut → 这是 lark-cli 维护者侧的事，不在 lark-skills 范围

## 溯源

- lark-cli `skills/lark-openapi-explorer/SKILL.md`（v1.0.0）
