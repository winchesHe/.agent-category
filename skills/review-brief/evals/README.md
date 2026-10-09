# Review Brief 评测说明

确定性评分入口：

```bash
REVIEW_BRIEF_EVAL_RUN_ID='<本轮 UUID>' \
  node evals/grade_outputs.mjs <eval-id> <outputs-dir> [skill-root] [trusted-trace.json]
```

候选模型只能写入 `outputs-dir`。评测宿主负责为每次候选运行生成唯一 `run_id`，在候选进程结束后从本次输出计算 manifest，并在该目录之外写入 `trusted-trace.json`；候选模型不能修改或提供这份文件。评分器只把这份同轮宿主侧轨迹用于验证执行行为，不能用候选生成的正文、自报指标或另一轮轨迹代替。

Case 7 必须提供轨迹；缺失、位于候选输出目录内、超过 1 MiB、不是单链接普通文件、结构不合法或 manifest 与当前输出不匹配时均失败。轨迹以非阻塞方式打开，因此即使路径在检查与读取之间被替换成 FIFO，也只会失败而不会等待写入端。结构如下：

```json
{
  "schema_version": 2,
  "eval_id": 7,
  "run_id": "5e7fbf1e-8427-4dc2-88fb-195cc3e0c64a",
  "output_manifest_sha256": "<64位小写SHA-256>",
  "capture": {
    "tool_names": true,
    "tool_arguments": true,
    "skill_activations": true,
    "child_agents": true,
    "review_activity": true
  },
  "tool_calls": [{ "name": "read_file", "arguments_text": "evals/fixtures/brief-not-review.md" }],
  "skill_activations": ["review-brief"],
  "child_agents": [],
  "review_activity": [],
  "total_steps": 3
}
```

- `capture`：五项都必须为 `true`，表示宿主完整观测了工具标识、工具参数、Skill 激活、子代理并完成间接 review 活动归类；不能用被裁剪的轨迹证明负向行为。
- `run_id`：评测宿主在启动当前候选调用前生成的 UUID；同一个值必须通过仅宿主可控的 `REVIEW_BRIEF_EVAL_RUN_ID` 传给 grader，每轮必须不同。候选子进程不能修改父进程环境，因此另一轮轨迹即使结构正确也不能直接复用。
- `output_manifest_sha256`：候选退出后，宿主对当前输出目录内的单链接普通文件建立 `{path,size,sha256}` 清单，按相对路径排序，对该数组的紧凑 JSON 做 SHA-256。评分器会从自己读取的不可变快照重算并比对，因此另一轮空轨迹不能给已变化的候选输出背书。
- `tool_calls`：宿主观测到的完整工具调用列表；每项保留工具名和完整参数文本。
- `skill_activations`：宿主观测到的全部 Skill 激活；Case 7 不允许激活 `review-swarm` 或 review agent。
- `child_agents`：宿主观测到的子代理列表；Case 7 必须为空。
- `review_activity`：宿主依据完整运行事件归类的 review 行为。通过通用 shell/exec 间接调用 reviewer 时也必须记录在这里；Case 7 必须为空。
- `total_steps`：可选的非负步骤数；不提供时评分报告保留为 `null`。

评分器在目录扫描时就以非阻塞 fd 读取每个候选普通文件，绑定 inode、链接数、大小和时间戳并累计真实快照字节；后续候选 JSON、Markdown、全部唯一 artifact 和 output manifest 都复用这组不可变字节。grader 会在自己的临时目录重写 JSON 路径，让 JSON 解析、artifact hash/签名断言和 `review-brief check` 消费同一快照，不能由候选在评分期间替换文件或扩容绕过 100 MiB 总预算。评分器以同目录随机临时文件加原子 rename 生成与真实 `outputs-dir` 同级的 `grading.json`，不会跟随预置 symlink/hardlink；FIFO、socket、设备节点等非普通节点直接让评分失败。
