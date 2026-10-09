# MoeGo 验收 Sites 模板

本目录保存已确认的阅读页模板。使用 shadcn 控件、MoeGo 橙色和 Manrope 字体；报告与全部案例使用同一个文档滚动条，目录随阅读位置高亮，点击目录平滑定位案例，不拦截滚轮。手机目录折行显示。目录在屏幕空间充足时吸顶，过长时随页面滚动，避免遮住正文或增加局部滚动条。

竖屏手机截图在宽屏并排时每张最大 390px，单张和叠加图最大 450px；680px 以下改为上下排列，优先保证图中文字可读。

正文中的 HTTP(S) 链接使用可点击标签，GitHub PR 显示仓库与编号；字段表达式、状态常量和反引号包裹的内容使用代码样式。40 位提交号显示前 8 位，悬停保留完整值；链接目标不改写。普通文本不解析 HTML。

截图使用原比例的大图；修复前后的完整标题紧贴各自图片上方，补充说明可展开。Case 提供 `problem` 时，开头展示“修复前问题”与 `claim` 对应的“修复后预期”，实际观察放入可展开记录；未提供问题描述时仍按句展示实际观察，不推测原问题。

## 从同一份证据生成

不直接复制演示项目。通过 `scripts/sites_report.py` 的 Python API 生成带报告数据的实例；原 `delivery_artifacts.py` 与 HTML 模板保持不变。此模板本身不附带任务数据，需要导出后才能构建。

```python
import sys
from pathlib import Path

skill_dir = Path.home() / ".agents/skills/moe-acceptance"
sys.path.insert(0, str(skill_dir / "scripts"))
from sites_report import export_sites

task_id = "实际任务ID"
task_dir = Path.home() / ".config/moego/moe-acceptance" / task_id
site_dir = export_sites(task_dir, task_id)
```

任务须已通过原 API 初始化为显式轮次模型，Case 必须有 `evidence_ids`。导出不调用 HTML 渲染、不启用 HTML 开关、不变更轮次、结论或原始媒体；不安装依赖、不创建 Site、不发布。

```text
~/.config/moego/moe-acceptance/<任务ID>/
├── manifest.json                # 唯一验收内容来源
├── assets/                      # 原始登记证据
├── report/index.html            # 原 HTML（按需生成）
└── sites/                       # 本模板生成的独立项目
    ├── .moe-acceptance-sites.json
    ├── .openai/hosting.json      # 首次创建后保存本任务 Site ID
    ├── app/                     # 模板源码
    └── public/report/
        ├── report.json          # 生成数据，不手工维护
        └── assets/              # 被引用证据的发布副本
```

媒体按 SHA-256 命名，相同内容复用一个发布文件。导出保留当前及历史轮次明确选择的媒体，不复制未采用资产、日志或原始诊断文件；不将本地绝对路径写入页面。历史内容同样可被站点访问，发布前需一并检查脱敏。

## 展示规则

| 证据 | 展示方式与条件 |
| --- | --- |
| 截图 / GIF | 原比例展示、点击放大、打开原图；GIF 保留动画 |
| 录屏 | 原生播放控制、倍速；仅在 metadata 提供时展示关键时刻 |
| 前后对比 | 同一 Case 中相同 `comparison_id` 成组；两张图的非空尺寸、视口、采集范围一致且页面引用相同时可叠加，其余并排 |
| Mobile App | 实际尺寸决定竖屏版式；只有明确 `platform` 为 `ios/android/mobile` 才标注 App，不从竖图猜平台或添加虚构设备外壳 |
| 音频 | 原生播放器与说明 |
| 无媒体 | 保留观察、预期、操作和原结论，明确本案例没有可展示媒体 |

原有 metadata 支持 `case_id/page_ref/comparison_id/viewport/capture_mode/width/height`。Sites 另读取可选 `platform`、`device`、正数 `duration_seconds` 和 `chapters: [{time: 3, label: "应用筛选"}]`；这些值必须来自真实采集事实。时间点以秒为单位，非负且不超过已记录时长；按时间顺序提供。缺失采集时间、视口和尺寸直接显示未知，不用登记时间代替。

默认以 `evidence_ids` 顺序展示全部已选媒体。可以给 `export_sites(..., presentation=配置)` 提供目录短标题和主证据：

```python
presentation = {"rounds": {"R1": {"C1": {
    "short_title": "筛选结果",
    "primary_evidence_id": "asset-2",
}}}}
site_dir = export_sites(task_dir, task_id, presentation=presentation)
```

配置只影响展示，不能改业务字段；主证据必须属于对应轮次 Case 的 `evidence_ids`。每次导出传完整配置，省略即恢复默认顺序；可将配置保存在调用方的任务说明中。主证据所在对比组保持成组，不拆开前后图。

## 更新、发布与失败处理

首次导出复制模板。后续对同一任务再次导出，只替换 `sites/public/report/`，保留源码、Git 和 `.openai/hosting.json`，继续更新同一个 Site；生成目录内的手工修改会被覆盖。模板版本不一致或现有目录不是本导出器创建时拒绝覆盖，应先检查并明确升级，不删除整个任务重来。

生成项目后，按当前可用的 Sites 构建与发布 Skill 将它作为已有 checkout：配置执行环境、安装依赖、预览、构建，再按 `.openai/hosting.json` 复用或首次登记 Site。发布只使用已检查媒体；访问范围按 `moe-acceptance/references/report-publishing.md` 的「Codex Sites」规则执行。模板不携带任何 Site ID，不能把示例 Site ID 复制给其他任务。

`npm run install:ci` 连接本机唯一的一份当前共享依赖，项目的 `node_modules` 为链接；Vite 缓存仍保存在本项目 `.sites-runtime`。模板升级后通过 `npm run install:ci -- --refresh` 统一替换依赖，不保留历史版本。已有项目迁移、旧预览更新及依赖刷新按 [本地预览的共享依赖](../../references/report-publishing.md#本地预览的共享依赖) 执行。

当前引用缺文件、非法引用、symlink、超限媒体、非法展示配置会停止导出；复制失败保留上一版生成数据。历史媒体缺失时保留历史文字和原结论，提示该轮媒体缺失。未升级旧报告拒绝导出；经原 API 显式升级后，旧快照显示“证据未复核”，只保留历史文字。原 HTML 的兼容行为保持原样。

模板包含本地字体和控件样式，不依赖字体 CDN。主题取自本任务核对过的 T2 `@moego/design-tokens 1.2.3`，Manrope 字体来自 `@moego/ui 0.487.0`；随模板保留字体与复用资源的许可文件。

## UI 走查

Case 的 `kind="ui"` 启用独立 UI 走查栏目，`ui_comparisons` 显式关联设计节点、平台和左右图片。`ui_acceptance.ui_comparison_id` 将检查点放在对应图片下；缺走查记录展示交付未完成，显式结论矛盾阻断导出。字段、诊断及历史兼容以 [报告合同](../../references/report-publishing.md#ui-走查数据与呈现) 为准。未标记的旧 Case 保持功能案例展示，不从标题或图片文件名猜测分类。模板 1.3.1 不自动覆盖已导出的旧 Site 源码；需保留本地修改并核对升级后再重新导出。
