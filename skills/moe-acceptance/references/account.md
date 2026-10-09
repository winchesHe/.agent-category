# 账号选择与身份准备

目标是取得符合当前要求的身份。已有账号、业务范围和功能命中仍适用时直接复用；选择账号与探索业务数据不互设前置。

## 选择与核验

用户本次明确指定的账号优先；当前 session 已确认且符合要求时直接复用。首次选择 T2 商家端 Web / iOS / Android 账号且用户未指定时，由 AI 读取 `MOE_ACCEPTANCE_DEFAULT_ACCOUNT_EMAIL`，优先级为进程环境 > 当前目录 `.env` > 本 Skill 根目录 `.env`，配置示例见 [.env.example](../.env.example)。默认值只是候选起点，是否采用由本次业务范围和功能资格决定；不用于 s1/production，也不作为 Portal/OBC 客户身份。当前身份与目标一致、业务范围满足要求，就保留身份，不为使用默认值重复查 MIS、重登或询问账号。

只有需要账号引用或业务范围消歧时，才使用 moe-mis `profile --type email` 等公开查询能力解析稳定账号引用。Company、Business/Location 与账号分别核对，关联列表中的第一个 Business 不能自动当作目标。未指定账号时，默认配置缺失或候选不满足功能资格，先结合已有上下文与获准查询寻找合格候选；仍无法准备必要身份时才说明已核对条件和具体缺口并询问用户。用户明确指定账号或 Business 时保留该目标，不能为命中功能偷偷换成另一对象；不把示例邮箱或业务 ID 硬编码为兜底，不将 T2 默认账号套用到其它环境或 Portal/OBC 客户身份。

白名单需求使用 GrowthBook 查询目标环境的 feature/force rule，定位候选 business/company ID；实际命中尚不明确且影响验收时，按 GrowthBook Skill 使用官方 `eval-feature` 和正确 attributes 验证。业务 ID 不是邮箱，手工读规则或候选存在不是实际命中证明。已有命中结果仍适用时不重查；选择白名单账号不隐含修改功能规则的授权，业务配置按当前目标的数据缺口处理。

## 准备或恢复身份

Web 缺账号引用时通过 MIS 解析；身份注入使用现有 moe-mis 的 impersonate 能力，落在目标浏览器同一 namespace/session 和 socket 上下文。参数先查对应 Skill，不复制鉴权；确需完整 T2 Web 准备时，将已解析的 account reference 显式传给 `session_login.py --account-ref`，桥接不自动加载或解析默认邮箱，仅身份有缺口时复用对应 MIS 能力。登录后根据非敏感页面或接口观察核对实际身份与业务范围，不以 Host 正确或 MIS 成功代替身份一致证明。默认账号变量不改变各平台登录方式，登录失败只排查已选目标，不自动改选账号。

iOS / Android 登录/切换按对应平台 reference 的产品入口处理，不使用 Web 注入或桥接。Client Portal / Report Card 使用对应平台的合法访问上下文。T2 OBC 使用目标 Business 的有效 booking identifier 与获授权的既有 Customer，不从默认商家邮箱、Portal 登录或历史手机号推导客户身份；MIS OBC 测试模式生效后仍需经产品 UI 登录并核对实际客户。共享 impersonate 不因浏览器隔离而独立，使用与恢复必须属于本次授权范围。仅在这些平台细节有缺口时读取对应 reference。

已准备的账号直接用于当前动作。出现权限、身份、环境或功能命中不一致的信号时，只补相关核验与恢复；登录失效不意味着白名单映射失效，恢复也不触发无关数据重建。
