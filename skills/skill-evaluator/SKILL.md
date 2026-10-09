---
name: skill-evaluator
description: >-
  评估已有 AI Agent Skill / SKILL.md 的行为质量与触发准确性，支持测试用例、断言评分、
  with_skill/without_skill 与新旧版本对照、Benchmark、人工 Viewer Review、
  description 优化、隔离 Codex 主评测、Pi 备用与工具轨迹和 headless CI。通过现有 scripts.run_ci、
  scripts.run_eval、scripts.run_loop 运行评测。用户要求评测某个 Skill、分析失败样例、
  比较版本效果或根据评测证据改进 Skill 时使用。新建 Skill、普通文案修改和无评测目标的
  SKILL.md 编辑使用系统 skill-creator；通用 API 压测、应用 CI、普通代码优化、
  Jira 查询和一般报告不触发。
---

# Skill Evaluator

从已有 Skill 和可核验的成功标准开始，完成“用例 → 执行 → 评分与人工检查 → 根据证据改进 → 回归”。
按用户请求选择其中一段；只要求评估时交付结果和建议，要求优化时才修改被测 Skill。

## 前置条件与脚本位置

- 先定位本文件所在的 `skill-evaluator/`，以下 `python -m scripts.*` 命令均从该目录运行；被测 Skill、用例和产物路径使用绝对路径。
- 读取被测 Skill 的完整 `SKILL.md`、相关 references、现有 evals 和适用仓库规则，复用已有成功标准。
- 使用 Python 3.10+；依赖按所用脚本确认。`quick_validate.py` 使用 PyYAML。Pi SDK 的 Node 版本与依赖见 `package.json`，安装与配置见 [运行时扩展](references/runtime-extensions.md)。
- 使用前读取对应命令 `--help`，保留现有各脚本的参数和输出契约，不假设它们有相同的通用 flag。
- 模型只使用 GPT 系列。用户指定时尊重指定；未指定时，Agent 先运行 `python -m scripts.run_ci --list-models`，按已配置候选和评测需求选择准确模型，使用 `--model` 与 `--selection-reason` 留下依据。不得直接沿用本机默认模型或硬编码某个 provider/模型为通用默认。
- headless 行为评测以隔离 Codex 为主，Pi SDK 为备用；具体配置与能力边界先读 [运行时扩展](references/runtime-extensions.md)。原生触发仅使用 Pi；不再提供 Claude 入口。Python 3.10 读取 Codex TOML 需要 `tomli`，3.11+ 内置支持。

## 按评测用途选择环境

| 用途 | 选择与结论 |
|---|---|
| 主力环境验收（`--purpose acceptance`，默认） | 优先用户明确指定的 GPT，其次已知日常 Codex 模型、推理等级与预算。先发现候选，再显式传参并记录依据；配置提示不是自动默认。 |
| 快速冒烟（`--purpose smoke`） | 可选更快、更便宜的 GPT 验证迭代；不能据此宣布主力环境验收完成。 |
| 通用性检查（`--purpose portability`） | 按目标模型分别执行完整对照，保留各自结论；不得把跨模型数据拼成一组基线。 |

默认用隔离 Codex 执行文本行为评测，基础设施故障时整轮切换 Pi。提前核对备用 provider/model 与支持的推理等级，必要时显式传 `--fallback-reasoning`。验收模式切换环境后，即使备用评分通过，根结论仍为 `target_unverified`，`--strict` 返回 2。查看根目录 `summary.json`、`report.md` 与 `junit.xml`，各 attempt 的报告仅描述该次评分。

当前自动 Codex 执行器关闭工具，仅覆盖隔离文本行为。涉及文件编辑、动态 references、真实工具或原生触发时，应在具备对应能力的隔离原生会话中验收并记录环境；现有 Pi fixture/触发流程是明确的专项入口，不能冒充 Codex 日常完整环境。`fake` 仅验证工具链契约。

被测模型与评分模型分别选择：优先执行确定性断言；主观质量使用能力足够且固定的评分模型或人工复核，记录评分依据。比较新旧版本、with/without skill 时固定执行与评分设置，不能让 Agent 每个 case 自由换模型。

## 场景决策树

```text
用户目标
├─ 从零新建 Skill，或只修改名称、文案、结构
│  └─ 使用系统 skill-creator；本 Skill 不承担通用创作入口
├─ 已有 Skill 的行为评测、断言失败、版本效果对比
│  └─ 读取 schemas.md → 行为评测流程 → Benchmark / Viewer
├─ Skill description 误触发、漏触发
│  └─ 触发样本 → run_eval → 需要优化时 run_loop
├─ Skill 的 Pi 工具轨迹、fixture、headless CI
│  └─ 读取 runtime-extensions.md 与 schemas.md → run_ci
├─ 已有 Benchmark / 人工反馈，需要解释或改进
│  └─ 读取原始输出与评分 → 分析原因 → 按授权迭代
└─ 通用 API benchmark、应用测试或普通代码优化
   └─ 使用对应开发或测试流程
```

## 行为评测

### 1. 固定范围与基线

先从已有上下文确定被测路径、目标行为、输入文件、验收标准和运行预算；只询问影响结论的缺失信息。
默认先用 2–3 个真实场景覆盖正常路径、边界与失败路径，再按发现扩展。已有完整用例时直接复用。

修改前将旧版本保存到独立 workspace 的 `skill-snapshot/`。比较 Skill 本身的增益用 `without_skill`；比较版本改进用旧快照。
新旧两组使用同一 prompt、输入、模型和资源限制，并记录版本与执行器。

结果放在被测 Skill 同级的 `<skill-name>-workspace/iteration-<N>/`，按 case 和配置分别存放。
每轮使用新目录，保留原始输出、轨迹与评分，避免覆盖基线证据。

### 2. 编写用例与断言

按 [schemas.md](references/schemas.md) 保存 `evals/evals.json`；最小结构如下：

```json
{
  "skill_name": "example-skill",
  "evals": [{
    "id": 1,
    "prompt": "真实用户任务",
    "expected_output": "可观察的预期结果",
    "files": [],
    "assertions": ["输出包含用户要求的结果"]
  }]
}
```

断言检查用户结果与业务边界，不重复实现细节。能用程序验证的内容使用确定性检查；写作、设计等主观质量交给人工判断。
每个 case 的 `eval_metadata.json` 保存 `eval_id`、`eval_name`、`prompt`、`assertions`，名称体现场景。
涉及工具顺序、参数和副作用时增加 trajectory 与 fixture；最终文字正确不能证明工具调用正确。

### 3. 执行与记录

- headless / fixture 场景读取运行时扩展后使用 `run_ci`。`fake` 只验证评测工具的契约，不能证明真实模型遵循 Skill。
- 需要原生 Agent 执行时，仅在当前环境允许且任务授权时使用隔离会话；各组明确指定 Skill 路径、输入和输出目录。受限环境可串行执行，不假装存在独立对照。
- `run_ci` 内置 `with_skill` / `without_skill`，没有 `old_skill` 参数。旧版对照需分别运行新旧快照，再按 schema 整理比较数据，不能编造 CLI flag。
- 每次运行保存完整 transcript、outputs 和工具轨迹。能获取的 `total_tokens`、`duration_ms` 立即写入 `timing.json`；无法获取的指标标注不可用，不估算。
- Runner/provider/fixture 故障单独报告，不能混入 Skill 质量得分。空输出、模型错误、非 completed 状态属于运行失败，不能用最终答案片段证明通过。
- 只对已识别的服务/运行器故障切换备用通道；质量失败、安全/权限拒绝、认证和 invalid_prompt 不切换。跨运行器或模型时重建完整同设置对照，保留每次尝试，不为提高通过率换模型。`run_ci` 自动按整轮处理；新旧快照分别运行时，Agent 必须核对两边最终 attempt 的模型、provider、reasoning、运行器和资源设置，一侧切换则另一侧以相同设置重跑。
- 模型只接收任务、指定 Skill 和公开输入；断言、expected_output、评测历史与评分文件不能暴露给被测模型。工具场景使用已去除 evals/tests 的 Skill 快照，输入和 grader 产物分开存放。

### 4. 评分、聚合与人工检查

读取 [agents/grader.md](agents/grader.md)，结合输出和轨迹逐条评分。
`grading.json.expectations[]` 必须使用 `text`、`passed`、`evidence`，保持 Viewer 兼容。

```bash
python -m scripts.aggregate_benchmark /absolute/workspace/iteration-1 --skill-name example-skill
python /absolute/skill-evaluator/eval-viewer/generate_review.py /absolute/workspace/iteration-1 --skill-name example-skill --benchmark /absolute/workspace/iteration-1/benchmark.json --static /absolute/workspace/review.html
```

`benchmark.json` / `benchmark.md` 展示通过率、耗时、tokens 与方差。原生运行目录、字段和基线配置名按 schema 写入；CI 产物直接复用。
读取 [agents/analyzer.md](agents/analyzer.md) 检查总分隐藏的问题：无区分力断言、高方差、成本与效果的取舍。

复用 Viewer 展示原始产物和评分，不另造 HTML。后续轮次可传 `--previous-workspace` 对比历史结果。
将 Viewer 交给用户；用户反馈从其明确导出的 `feedback.json` 读取。没有浏览器时展示静态 HTML 或直接展示 prompt、输出与评分，不声称完成了人工验收。

## 根据证据迭代

用户要求优化时，根据失败 case、transcript 和人工反馈修改 Skill：归纳可复用的规则、解释原因、删除无效约束，避免只为几个测试答案打补丁。
不改变被测 Skill 的名称和目录，除非用户明确要求改名。

改动后在新 iteration 重跑受影响场景和关键基线，汇报收益、回退与未覆盖范围。
用户已认可、达到既定验收标准或没有进一步证据支持修改时结束；“没有反馈”不等于“人工确认通过”。

需要盲测时读取 [agents/comparator.md](agents/comparator.md) 与 analyzer，以匿名 A/B 输出交给独立评估者。
当前环境不支持独立评估时说明限制，不把自评称为盲测。

## 触发评测与 description 优化

1. 先复用已有样本；新增样本通常约 20 条，正反例各 8–10 条以上。覆盖真实具体请求、近邻误触发、漏触发与相邻 Skill 分工。
2. 保存为 `[{"query": "用户请求", "should_trigger": true}]`。样本标签应表达用户期望的路由，不根据当前模型结果反向改标签。
3. 样本需要用户判断时，可用 `assets/eval_review.html` 替换其三个占位符，展示和导出；读取用户明确选定的导出文件，不按 Downloads 最新时间猜测。
4. 先运行 `run_eval` 测量当前 description；请求包含优化时再用 `run_loop`。模型、并发与超时根据实际环境设置。

```bash
python -m scripts.run_eval --skill-path /absolute/my-skill --eval-set /absolute/trigger-evals.json --executor pi --model <provider/GPT-model> --num-workers 2 --timeout 60
python -m scripts.run_loop --skill-path /absolute/my-skill --eval-set /absolute/trigger-evals.json --executor pi --model <provider/GPT-model> --num-workers 2 --timeout 60 --max-iterations 5 --runs-per-query 3 --results-dir /absolute/trigger-results
```

`run_loop` 默认按 60% train / 40% held-out test 分割，重复测量各 query，并输出 `best_description` 和迭代报告。
根据结果回看具体误触发/漏触发；在修改授权内应用候选 description，展示前后差异与得分。
只测 description 路由不能证明行为质量。Pi-native 以真实读取目标 SKILL.md 判定；Codex 文本执行不能替代原生触发。触发运行失败会返回系统错误，不能当作未触发，也不能继续用错误分数优化。description 生成复用 Pi/Codex Executor，可独立调用 `scripts.improve_description --executor codex --model <GPT-model>`；不改变触发评测的运行器。

## headless CI 与交付

```bash
python -m scripts.run_ci --skill-path /absolute/my-skill --executor fake --runs 1 --strict --output-dir /absolute/ci-results
```

默认仅 `with_skill` 纳入质量门禁，`without_skill` 是记录到 Benchmark 的基线；需要两组均阻断时使用 `--gate-configuration both`。
质量/Trajectory 失败返回 `1`，Runner/provider/fixture/协议故障返回 `2`，无 case 返回 `3`。
汇报真实执行范围、模型/版本、评分、失败证据、资源消耗与产物位置；区分静态检查、fake 契约检查和真实模型评测。
用户要求打包时使用 `python -m scripts.package_skill /absolute/my-skill`，交付生成文件。

## NEVER

- 不因提到 Skill 就启动完整评测；先匹配用户是否需要行为评估、触发优化或证据驱动改进。
- 不让 fixture 测试调用生产 API 或不受限 shell；真实模型运行设置并发、超时和资源上限。
- 不改断言迎合失败输出，不以少数样本满分宣称全面可靠。
- 不伪造基线、token、耗时、人工反馈或模型运行结果。
- 不因评测请求自动安装、发布被测 Skill 或修改外部对象。

## References

| 文件 | 加载时机 |
|---|---|
| [references/schemas.md](references/schemas.md) | 编写 evals、grading、timing、Benchmark 或 trajectory / fixture 数据前 |
| [references/runtime-extensions.md](references/runtime-extensions.md) | Pi 执行、headless CI、fixture 隔离、工具轨迹与资源限制 |
| [agents/grader.md](agents/grader.md) | 根据实际产物和轨迹评分 |
| [agents/analyzer.md](agents/analyzer.md) | 分析 Benchmark、失败模式和迭代收益 |
| [agents/comparator.md](agents/comparator.md) | 用户需要两版输出的独立盲测 |
| `assets/eval_review.html` | 需要人工审阅或编辑触发样本 |
