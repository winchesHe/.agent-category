# 运行时扩展

## 适用场景

当需要用隔离 Codex 或 Pi 执行 Skill、验证工具调用路径、使用固定工具返回值或在 CI 中无浏览器评测时，读取本文件。已有 Skill 的人工 Viewer Review 和 description 优化遵循 `SKILL.md` 主流程。

## Executor

`run_ci.py` 支持以下执行器；`fake` 不需要模型，真实执行必须显式选择 GPT。

| Executor | 作用 |
|---|---|
| `pi` | 备用 Pi SDK，加载实际配置的 ModelRuntime，关闭全局上下文与自动重试 |
| `pi-cli` | SDK 缺失时的备用运行器；准确核对 provider/model 目录项 |
| `codex` | 默认主执行器，`codex exec --ephemeral --json`，正式支持无工具文本行为评测与 description 生成 |
| `fake` | 本地契约测试，不调用模型 |

### 发现与选择

```bash
python -m scripts.run_ci --list-models
python -m scripts.run_ci --skill-path /absolute/my-skill --executor codex --model <GPT-model> --fallback-model <provider/GPT-model> --selection-reason "根据实际候选与评测需求作出的选择" --reasoning medium --strict
python -m scripts.run_ci --skill-path /absolute/my-skill --executor codex --model <GPT-model> --strict
```

发现只返回模型/provider、可用推理等级、配置来源与 CLI 可用性，不输出密钥，也不代表服务健康。Pi 使用准确的 `provider/model`，或 `--provider` 加模型 ID；禁止模糊匹配和非 GPT。用户未指定时由 Agent 选择再传参，脚本不会猜一个默认值。Codex 从现有 `config.toml` 复用连接字段，只将其中 GPT 默认模型与推理等级作为只读选择提示（`daily_environment`），不会自动使用；认证沿用原生 CLI。复杂 profile、内联认证头等连接配置不在复用字段中，遇到失败应报告具体限制，不改全局配置。

安装 Pi SDK 的依赖见 `package.json`；可复用全局安装，通过 `PI_CODING_AGENT_PACKAGE` 指定包根目录。`PI_CODING_AGENT_DIR` 指定已有 Pi 配置目录。Codex 必须支持 `--ignore-user-config`、`--ephemeral`、`--json` 与 `skip_host_skill_discovery` 等隔离开关，先核对本机 `codex exec --help` 和 `codex features list`。多个 CLI 并存时可用 `CODEX_EXECUTABLE` 指定已验证的可执行文件。本 Skill 不安装或改写用户认证；可用配置见 `.env.example`，环境变量由调用进程传入，不自动读取 `.env`。

### 切换与同设置对照

- `--fallback-executor pi|codex|none`：默认 Pi，只在明确的服务或运行器故障后切换一次。
- `--fallback-model`：备用 GPT；省略时保持主模型 ID。`--fallback-provider`：备用连接；Pi 必须显式指定 provider 或 provider/model，Codex 可复用现有连接。`--codex-provider` 仅保留为 Codex fallback 的兼容参数。`--fallback-reasoning` 可独立指定备用等级，省略时保持主等级。备用模型同样需要 Agent 核对可用配置。
- `--pi-cli-fallback` / `--no-pi-cli-fallback`：SDK 缺依赖时是否先整轮改用 Pi CLI；服务 5xx 不通过同网关 CLI 重试。
- `--reasoning`：本轮两组共用的推理等级，默认 medium。Pi SDK 在调用前核对该等级，拒绝自动改档；实际模型/provider/reasoning 写入运行结果，发现不一致则失败。CLI 的等级能力还需结合本地配置确认。
- 每个 attempt 独立保存全部 case、with/without、重复次数与证据。切换后从头重跑；根目录 `attempts.json` 记录失败类别、模型、provider、推理、资源参数、选择依据与每轮路径。只使用最终完整 attempt 做比较。
- 质量/trajectory 失败、权限或安全拒绝、认证、invalid_prompt、fixture miss、空输出和未知错误均不触发自动切换。5xx、连接中断、超时属于服务故障；缺运行器或不支持所需 CLI 开关属于运行器故障。

### 能力与隔离

Pi 保留 fixture 与工具轨迹；行为评测显式注入 SKILL.md，触发评测保留 Pi-native 加载。默认无工具文本场景只传公开 prompt、目标 SKILL.md 与 `files` 文本。Codex 同样显式注入这些文本，并关闭自动 Skill、用户指令、插件/MCP、shell、网络和其他外部工具，使用独立临时 cwd 与只读 sandbox。

Codex 当前不执行 Pi fixture、自定义工具、文件编辑任务或原生触发；这些请求返回能力错误，不能生成虚假的工具轨迹或通过结果。需要 references 动态读取的任务保留在 Pi 工具评测，不能用只注入入口文档的文本结果替代。传入 `files` 必须是已授权公开文本，禁止指向 case/断言/历史评分。

`--timeout` 是子进程墙钟上限；turn/tool 预算由评分检查，输出 token 有原生计量时由结果检查，不能假设所有运行器均在服务端提前截断。token 不可得时报告不可用，不以字符数估算。fixture 模式不是通用操作系统 sandbox，使用隔离数据和去除评测答案的 Skill 快照。

默认 `--gate-configuration with_skill` 只把带 Skill 的运行纳入质量门禁；`without_skill` 仍会执行并进入 Benchmark，但预期 baseline 失败只记录为 informational。需要两组都阻断时显式使用 `--gate-configuration both`。任意 Executor 的系统错误、超时和协议错误始终阻断。

## Tool Trajectory

在 `evals/evals.json` 的单个 case 中增加可选 `trajectory`：

```json
{
  "trajectory": {
    "mode": "ordered",
    "calls": [
      {
        "tool": "read_issue",
        "args_contain": {"issue_key": "GRM-123"}
      }
    ],
    "max_calls": 3,
    "max_turns": 5
  },
  "fixtures": ["fixtures/grm-123.json"]
}
```

Trajectory 支持 `ordered`、`exact`、`args_contain`、`args_exact`、`args_end_with`、`max_calls` 和 `max_turns`。`args_end_with` 用于约束绝对路径等带运行时前缀的字符串，按完整路径组件匹配；例如 `{"path":"moe-opc/references/stages/prd.md"}` 可匹配任意工作树中的同一路径，但不会匹配 `not-moe-opc/...` 或其它 reference。

Fixture 默认用 `args_contain` 做子集匹配；安全关键调用可改用 `args_exact`。两种模式都按 JSON 类型比较叶子值，不允许用数字 `1` 冒充布尔值 `true`；`args_exact` 还要求实际参数与 fixture 完全相等，多出任何字段都会 fixture miss。数字遵循 JSON number 语义，因此 `-0` 与 `0` 等价。Pi SDK 与 CLI replay 共用同一 JavaScript matcher，Python trajectory/replay 遵循相同规则；fixture 模式只开放内建 `read` 与 fixture 声明的工具，以允许读取被测 Skill 的 reference 且不泄漏其它工具。Fixture miss、参数不匹配、重复调用和超额调用都应进入失败报告。

## CI 产物

每次执行生成时间戳目录，包含：

- `attempt-N-<executor>/iteration-1/`：兼容原 Viewer 的运行目录；`attempts.json` 指向各次尝试。
- 各 attempt 的 `iteration-1/benchmark.json` 与 `benchmark.md`：官方聚合格式加 executor metadata。
- `report.html`：复用官方 `scripts/generate_report.py` 的静态报告，按 `with_skill`/`without_skill` 展示本轮结果。
- `summary.json`：CI 门禁摘要。
- `junit.xml`：CI 测试报告。

JUnit 对未纳入门禁的 baseline 失败使用 `skipped`，不会伪装成通过。

退出码：`0` 通过，`1` 质量或 Trajectory 失败，`2` 系统故障，`3` 无 case。

## 安全边界

CI 默认只使用固定工具返回值 fixture/fake 工具。该 fixture 机制仅用于受控测试，不代表通用 Tool Replay 或生产工具回放。不要让 case fixture 触发生产 API、任意网络或不受限 shell。真实模型调用需要显式设置 provider/model 和资源上限，并在报告中记录 Executor、模型、Skill 加载模式和版本信息。

### 评测用途与根结论

默认执行器为隔离 Codex，`--purpose acceptance|smoke|portability` 默认 acceptance；用途选择遵循主文档“按评测用途选择环境”。description 独立生成同样默认 Codex；`run_loop` 保持显式 Pi 生成与 Pi-native 触发设置。

根 `summary.json` / `attempts.json` 记录 purpose、target_environment、target_matched、conclusion_scope 与各 attempt 设置。备用配置缺失时保留主执行诊断及 fallback_configuration_error。验收切换环境且备用通过时，根状态 target_unverified，严格退出码 2；根 JUnit 包含未完成的目标验收项，根 report.md 指向备用的局部评分。Codex 的 isolated_text、Pi 的 pi_controlled 与 fake 的 tooling_contract 均不代表完整生产环境验收。冒烟和通用性检查按最终完整 attempt 评分，仍保留切换记录。
