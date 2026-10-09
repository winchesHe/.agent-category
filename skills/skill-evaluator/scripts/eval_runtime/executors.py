"""Pi/Codex Executor 的统一协议和实现。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .configuration import gpt_model, codex_connection


class ExecutorError(RuntimeError):
    """执行失败；只有明确的运行器或服务故障允许备用通道。"""

    def __init__(self, message: str, category: str | None = None):
        super().__init__(message)
        self.category = category or classify_error(message)

    @property
    def recoverable(self) -> bool:
        return self.category in {"service", "runtime"}


def classify_error(message: str) -> str:
    text = message.lower()
    if any(word in text for word in ("permission", "unauthorized", "forbidden", "401", "403", "safety", "policy", "refusal", "refused", "权限", "安全", "拒绝")):
        return "denied"
    if any(word in text for word in ("invalid_prompt", "invalid prompt", "configuration:", "fixture", "unsupported", "不支持")):
        return "configuration"
    if re.search(r"\b(?:500|502|503|504|529)\b", text) or any(word in text for word in ("timeout", "超时", "connection reset", "econnreset", "fetch failed", "service unavailable")):
        return "service"
    if any(word in text for word in ("找不到 node", "找不到 pi", "找不到 codex", "找不到 @earendil", "cannot find package", "err_module_not_found", "unknown feature flag", "unexpected argument")):
        return "runtime"
    return "protocol"


def validate_result(result: "RunResult", request: "RunRequest") -> None:
    if result.errors or result.status != "completed":
        raise ExecutorError(json.dumps(result.errors, ensure_ascii=False) if result.errors else result.status)
    output_budget = request.limits.get("max_output_tokens")
    if output_budget is not None and result.timing.get("output_tokens", 0) > output_budget:
        raise ExecutorError("输出 token 超出本轮预算", "budget")
    if not result.final_answer.strip() and not (request.limits.get("trigger_only") and result.skill_triggered):
        raise ExecutorError("模型空输出", "protocol")


def validate_model(request: "RunRequest", *, pi: bool = False) -> None:
    try:
        request.provider, request.model = gpt_model(request.model, request.provider)
    except ValueError as exc:
        raise ExecutorError(str(exc), "configuration") from exc
    if pi and not request.provider:
        raise ExecutorError("configuration: Pi 必须选择明确 provider（可用 provider/model）")



@dataclass
class RunRequest:
    run_id: str
    prompt: str
    configuration: str
    workspace: Path
    skill_path: Path | None = None
    input_files: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    provider: str | None = None
    mock_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    mock_result: dict[str, Any] | None = None
    mock_results_by_configuration: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_case(
        cls,
        case: dict[str, Any],
        run_id: str,
        configuration: str,
        workspace: Path,
        skill_path: Path | None,
        model: str | None,
        provider: str | None,
        limits: dict[str, Any],
    ) -> "RunRequest":
        return cls(
            run_id=run_id,
            prompt=case["prompt"],
            configuration=configuration,
            workspace=workspace,
            skill_path=skill_path if configuration == "with_skill" else None,
            input_files=list(case.get("files", [])),
            tools=list(case.get("tools", [])),
            fixtures=list(case.get("fixtures", [])),
            limits=limits,
            model=model,
            provider=provider,
            mock_tool_calls=list(case.get("mock_tool_calls", [])),
            mock_result=case.get("mock_result"),
            mock_results_by_configuration=dict(case.get("mock_results_by_configuration", {})),
        )


@dataclass
class RunResult:
    run_id: str
    executor: str
    configuration: str
    final_answer: str
    artifacts: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    skill_events: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    errors: list[dict[str, Any]] = field(default_factory=list)
    trigger_semantics: str = "not_applicable"
    skill_triggered: bool | None = None
    model: str | None = None
    provider: str | None = None
    runtime_settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Executor:
    name = "base"

    def run(self, request: RunRequest) -> RunResult:
        raise NotImplementedError


def _write_run_files(request: RunRequest, result: RunResult, started: float) -> None:
    outputs = request.workspace / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "answer.md").write_text(result.final_answer + ("\n" if result.final_answer else ""))
    (outputs / "tool_calls.json").write_text(json.dumps(result.tool_calls, indent=2, ensure_ascii=False) + "\n")
    (outputs / "metrics.json").write_text(json.dumps(result.metrics, indent=2, ensure_ascii=False) + "\n")
    (request.workspace / "transcript.md").write_text(
        f"## Eval Prompt\n\n{request.prompt}\n\n## Final Answer\n\n{result.final_answer}\n"
    )
    result.timing.setdefault("total_duration_seconds", round(time.monotonic() - started, 4))
    (request.workspace / "timing.json").write_text(json.dumps(result.timing, indent=2) + "\n")
    (request.workspace / "run_result.json").write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n")


class FakeExecutor(Executor):
    name = "fake"

    def run(self, request: RunRequest) -> RunResult:
        started = time.monotonic()
        data = request.mock_results_by_configuration.get(request.configuration, request.mock_result) or {}
        result = RunResult(
            run_id=request.run_id,
            executor=self.name,
            configuration=request.configuration,
            final_answer=data.get("final_answer", request.prompt),
            artifacts=list(data.get("artifacts", [])),
            tool_calls=list(data.get("tool_calls", request.mock_tool_calls)),
            metrics={
                "total_tool_calls": len(data.get("tool_calls", request.mock_tool_calls)),
                "total_steps": data.get("total_steps", 1),
                "total_turns": data.get("total_turns", 1),
                "errors_encountered": 0,
                "output_chars": len(data.get("final_answer", request.prompt)),
                "transcript_chars": len(request.prompt) + len(data.get("final_answer", request.prompt)),
            },
            model=request.model,
            provider=request.provider,
            trigger_semantics="fake",
            skill_triggered=request.configuration == "with_skill",
        )
        _write_run_files(request, result, started)
        validate_result(result, request)
        return result


def _pi_tool_names(request: RunRequest) -> list[str]:
    """解析 Pi CLI 工具白名单；fixture 模式只开放 read 与 fixture 工具。"""
    if request.fixtures:
        tool_names = ["read"]
        for fixture in _load_fixture_records(request.fixtures):
            if fixture.get("tool") and fixture["tool"] not in tool_names:
                tool_names.append(fixture["tool"])
        return tool_names
    return list(request.tools)


def _pi_cli_command(request: RunRequest, pi: str, replay_extension: Path | None = None) -> list[str]:
    """构造隔离的 Pi CLI 命令；自动 Skill 发现始终关闭。"""
    command = [
        pi,
        "--mode",
        "json",
        "--print",
        "--no-session",
        "--no-extensions",
        "--no-context-files",
        "--no-skills",
    ]
    if request.configuration == "with_skill" and request.skill_path:
        command.extend(["--skill", str(request.skill_path)])
    if request.model:
        command.extend(["--model", request.model])
    if request.provider:
        command.extend(["--provider", request.provider])
    if replay_extension:
        command.extend(["--extension", str(replay_extension)])
    tool_names = _pi_tool_names(request)
    if tool_names:
        command.extend(["--tools", ",".join(tool_names)])
    else:
        command.append("--no-tools")
    command.extend(["--thinking", request.limits.get("reasoning", "medium"), "--no-prompt-templates"])
    prompt = request.prompt
    if request.skill_path and request.configuration == "with_skill":
        prompt += "\n\n本次任务遵循以下 Skill：\n" + (request.skill_path / "SKILL.md").read_text()
    for file in request.input_files:
        prompt += "\n\n输入文件 " + Path(file).name + ":\n" + Path(file).read_text()
    command.extend(["--", prompt])
    return command


class PiCliExecutor(Executor):
    name = "pi-cli"

    def run(self, request: RunRequest) -> RunResult:
        started = time.monotonic()
        validate_model(request, pi=True)
        pi = shutil.which("pi")
        if not pi:
            raise ExecutorError("找不到 pi；请安装 Pi 或使用 --executor fake 运行契约测试")

        try:
            catalog = subprocess.run([pi, "--no-extensions", "--no-skills", "--no-context-files", "--list-models", "gpt"],
                                     capture_output=True, text=True, timeout=30, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ExecutorError("Pi 模型目录发现超时", "runtime") from exc
        candidates = {tuple(line.split()[:2]) for line in catalog.stdout.splitlines() if len(line.split()) >= 2}
        if catalog.returncode or (request.provider, request.model) not in candidates:
            raise ExecutorError("configuration: 所选 GPT/provider 不在 Pi 可用目录", "configuration")
        replay_extension = _write_pi_replay_extension(request, pi) if request.fixtures else None
        command = _pi_cli_command(request, pi, replay_extension)

        env = dict(os.environ)
        timeout = int(request.limits.get("timeout_seconds", 300))
        try:
            completed = subprocess.run(
                command,
                cwd=request.workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            (request.workspace / "pi-events.jsonl").write_bytes(exc.stdout or b"")
            raise ExecutorError(f"Pi CLI 超时 ({timeout}s)") from exc
        except OSError as exc:
            raise ExecutorError(str(exc), "runtime") from exc

        events = []
        for line in completed.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        final_answer, calls = _extract_pi_events(events)
        (request.workspace / "pi-events.jsonl").write_text(completed.stdout)
        (request.workspace / "pi-stderr.log").write_text(completed.stderr)
        for event in events:
            messages = event.get("messages", []) + ([event["message"]] if isinstance(event.get("message"), dict) else [])
            for message in messages:
                if message.get("role") == "assistant" and message.get("stopReason") in {"error", "aborted", "invalid_prompt"}:
                    raise ExecutorError(message.get("errorMessage") or message["stopReason"])
        if completed.returncode != 0:
            error = completed.stderr.strip() or f"pi exited with {completed.returncode}"
            raise ExecutorError(error)
        result = RunResult(
            run_id=request.run_id,
            executor=self.name,
            configuration=request.configuration,
            final_answer=final_answer,
            tool_calls=calls,
            metrics={
                "total_tool_calls": len(calls),
                "total_steps": len(events),
                "total_turns": _count_pi_turns(events),
                "errors_encountered": 0,
                "output_chars": len(final_answer),
                "transcript_chars": len(completed.stdout),
            },
            model=request.model,
            provider=request.provider,
            trigger_semantics="explicit" if request.configuration == "with_skill" else "not_applicable",
            skill_triggered=None,
        )
        (request.workspace / "pi-events.jsonl").write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
        )
        _write_run_files(request, result, started)
        validate_result(result, request)
        return result


class CodexCliExecutor(Executor):
    """无工具文本评测；不把 Pi fixture 或原生触发偷换成提示词模拟。"""
    name = "codex"

    def run(self, request: RunRequest) -> RunResult:
        validate_model(request)
        if request.fixtures or request.tools or request.limits.get("trigger_only"):
            raise ExecutorError("Codex 文本执行器不支持 fixture、工具白名单或 Pi-native 触发", "configuration")
        executable = os.environ.get("CODEX_EXECUTABLE") or shutil.which("codex")
        if not executable:
            raise ExecutorError("找不到 codex", "runtime")
        started = time.monotonic()
        provider, connection = codex_connection(request.provider)
        prompt = request.prompt
        if request.skill_path and request.configuration == "with_skill":
            prompt += "\n\n本次任务遵循以下 Skill：\n" + (request.skill_path / "SKILL.md").read_text()
        for file in request.input_files:
            prompt += "\n\n输入文件 " + Path(file).name + ":\n" + Path(file).read_text()
        command = [executable, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                   "--json", "--sandbox", "read-only", "--model", request.model,
                   "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
                   "-c", 'project_doc_max_bytes=0', "-c", 'suppress_unstable_features_warning=true', "-c", 'network_access=false',
                   "-c", 'mcp_servers={}', "-c", 'developer_instructions=""',
                   "-c", 'model_reasoning_effort=' + json.dumps(request.limits.get("reasoning", "medium")),
                   *connection]
        for feature in ("apps", "plugins", "hooks", "shell_tool", "unified_exec", "multi_agent",
                        "browser_use", "computer_use", "image_generation", "skill_search",
                        "skill_mcp_dependency_install"):
            command += ["--disable", feature]
        command += ["--enable", "skip_host_skill_discovery", "-"]
        # 模型工作目录与 grader/期望文件分离；输入只来自 RunRequest 的公开字段。
        with tempfile.TemporaryDirectory(prefix="codex-eval-") as cwd:
            try:
                completed = subprocess.run(command, input=prompt, cwd=cwd, capture_output=True,
                                           text=True, timeout=int(request.limits.get("timeout_seconds", 300)))
            except OSError as exc:
                raise ExecutorError(str(exc), "runtime") from exc
            except subprocess.TimeoutExpired as exc:
                (request.workspace / "codex-events.jsonl").write_bytes(exc.stdout or b"")
                raise ExecutorError("Codex 超时", "service") from exc
        (request.workspace / "codex-events.jsonl").write_text(completed.stdout)
        (request.workspace / "codex-stderr.log").write_text(completed.stderr)
        events = []
        for line in completed.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                raise ExecutorError("Codex 返回非法 JSONL", "protocol")
        failures = [e for e in events if e.get("type") in {"error", "turn.failed"}]
        if completed.returncode or failures:
            raise ExecutorError(json.dumps(failures, ensure_ascii=False) if failures else completed.stderr)
        turns = [e for e in events if e.get("type") == "turn.completed"]
        if not turns:
            raise ExecutorError("Codex 未返回 turn.completed", "protocol")
        items = [e.get("item", {}) for e in events if e.get("type") == "item.completed"]
        item_errors = [item for item in items if item.get("type") == "error"]
        if item_errors:
            raise ExecutorError(json.dumps(item_errors, ensure_ascii=False))
        calls = [item for item in items if item.get("type") not in {"agent_message", "reasoning"}]
        if calls:
            raise ExecutorError("Codex 无工具模式出现工具调用", "configuration")
        answer = "\n".join(item.get("text", "") for item in items if item.get("type") == "agent_message")
        usage = turns[-1].get("usage", {})
        timing = {"usage": usage}
        if "input_tokens" in usage and "output_tokens" in usage:
            timing.update(total_tokens=usage["input_tokens"] + usage["output_tokens"], output_tokens=usage["output_tokens"])
        result = RunResult(request.run_id, self.name, request.configuration, answer,
                           model=request.model, provider=provider,
                           runtime_settings={"path": str(Path(executable).resolve()), "reasoning": request.limits.get("reasoning", "medium"),
                                             "configuration_source": "现有 Codex 连接字段；显式模型与隔离参数"},
                           trigger_semantics="explicit" if request.skill_path else "not_applicable",
                           metrics={"total_turns": len(turns), "total_tool_calls": 0,
                                    "output_chars": len(answer), "errors_encountered": 0},
                           timing=timing)
        _write_run_files(request, result, started)
        validate_result(result, request)
        return result


class PiSdkExecutor(PiCliExecutor):
    """Pi SDK 正式适配；备用运行器由整轮调度决定。"""

    name = "pi-sdk"

    def run(self, request: RunRequest) -> RunResult:
        validate_model(request, pi=True)
        bridge = Path(__file__).with_name("pi_sdk_bridge.mjs")
        if not bridge.exists():
            raise ExecutorError(f"Pi SDK bridge 不存在: {bridge}")
        node = shutil.which("node")
        if not node:
            raise ExecutorError("找不到 node，无法运行 Pi SDK")

        started = time.monotonic()
        payload = {
            "prompt": request.prompt,
            "input_files": request.input_files,
            "cwd": str(request.workspace),
            "skill_path": str(request.skill_path) if request.skill_path else None,
            "configuration": request.configuration,
            "tools": request.tools,
            "fixtures": request.fixtures,
            "model": request.model,
            "provider": request.provider,
            "limits": request.limits,
            "trigger_only": request.limits.get("trigger_only", False),
        }
        try:
            completed = subprocess.run(
                [node, str(bridge)],
                input=json.dumps(payload),
                cwd=request.workspace,
                capture_output=True,
                text=True,
                timeout=int(request.limits.get("timeout_seconds", 300)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            (request.workspace / "pi-sdk-response.json").write_bytes(exc.stdout or b"")
            raise ExecutorError("Pi SDK bridge 超时") from exc
        except OSError as exc:
            raise ExecutorError(str(exc), "runtime") from exc
        (request.workspace / "pi-sdk-response.json").write_text(completed.stdout)
        (request.workspace / "pi-stderr.log").write_text(completed.stderr)
        if completed.returncode != 0:
            raise ExecutorError(completed.stderr.strip() or "Pi SDK bridge 失败")
        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ExecutorError(f"Pi SDK bridge 返回非法 JSON: {completed.stdout[:500]}") from exc
        result = RunResult(
            run_id=request.run_id,
            executor=self.name,
            configuration=request.configuration,
            final_answer=data.get("final_answer", ""),
            artifacts=data.get("artifacts", []),
            tool_calls=data.get("tool_calls", []),
            skill_events=data.get("skill_events", []),
            metrics=data.get("metrics", {}),
            timing=data.get("timing", {}),
            status=data.get("status", "completed"),
            errors=data.get("errors", []),
            runtime_settings={"model": data.get("actual_model"), "provider": data.get("actual_provider"),
                              "reasoning": data.get("actual_reasoning"),
                              "version": data.get("runtime_version"), "path": data.get("runtime_path")},
            trigger_semantics=data.get("trigger_semantics", "pi-native"),
            skill_triggered=data.get("skill_triggered"),
            model=request.model,
            provider=request.provider,
        )
        _write_run_files(request, result, started)
        validate_result(result, request)
        for key, expected in (("model", request.model), ("provider", request.provider), ("reasoning", request.limits.get("reasoning", "medium"))):
            actual = result.runtime_settings.get(key)
            if actual is not None and actual != expected:
                raise ExecutorError(f"configuration: Pi 实际 {key}={actual} 与请求 {expected} 不一致")
        return result


def _extract_pi_events(events: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    text_parts: list[str] = []
    calls: list[dict[str, Any]] = []
    for event in events:
        event_type = event.get("type")
        if event_type == "message_update":
            update = event.get("assistantMessageEvent", {})
            if update.get("type") == "text_delta":
                text_parts.append(update.get("delta", ""))
        elif event_type in {"tool_execution_start", "tool_call"}:
            calls.append({
                "tool": event.get("toolName") or event.get("name") or event.get("tool", ""),
                "args": event.get("args") or event.get("input", {}),
                "call_id": event.get("toolCallId") or event.get("id"),
            })
        elif event_type == "agent_end":
            for message in event.get("messages", []):
                if message.get("role") != "assistant":
                    continue
                for content in message.get("content", []):
                    if content.get("type") == "text":
                        text_parts.append(content.get("text", ""))
    return "".join(text_parts).strip(), calls


def _count_pi_turns(events: list[dict[str, Any]]) -> int:
    """按 Pi 的 turn_end 生命周期事件统计真实 Agent turn。"""
    return sum(1 for event in events if event.get("type") == "turn_end")


def _load_fixture_records(paths: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ExecutorError(f"无法读取 replay fixture {path}: {exc}") from exc
        if isinstance(data, list):
            records.extend(data)
        elif isinstance(data, dict):
            records.append(data)
        else:
            raise ExecutorError(f"fixture 必须是 object 或 array: {path}")
    return records


def _write_pi_replay_extension(request: RunRequest, pi_path: str) -> Path:
    """为 CLI fallback 生成一次性 replay extension。"""
    records = _load_fixture_records(request.fixtures)
    package_root_raw = os.environ.get("PI_CODING_AGENT_PACKAGE")
    if package_root_raw:
        package_candidates = [Path(package_root_raw)]
    else:
        resolved_pi = Path(pi_path).resolve()
        package_candidates = [resolved_pi.parent, *resolved_pi.parents]
    package_root = next(
        (
            candidate
            for candidate in package_candidates
            if (candidate / "node_modules" / "typebox" / "build" / "index.mjs").is_file()
        ),
        package_candidates[0],
    )
    typebox = package_root / "node_modules" / "typebox" / "build" / "index.mjs"
    if not typebox.is_file():
        raise ExecutorError(f"找不到 Pi TypeBox 依赖: {typebox}")
    fixture_match = Path(__file__).with_name("fixture_match.mjs")
    if not fixture_match.is_file():
        raise ExecutorError(f"找不到 fixture matcher: {fixture_match}")
    extension = request.workspace / "replay-extension.mjs"
    encoded_records = json.dumps(records, ensure_ascii=True)
    source = f'''import {{ Type }} from {json.dumps(typebox.as_uri())};
import {{ fixtureArgsMatch }} from {json.dumps(fixture_match.as_uri())};
const fixtures = {encoded_records};
export default function replayExtension(pi) {{
  for (const tool of [...new Set(fixtures.map((fixture) => fixture.tool))]) {{
    pi.registerTool({{
      name: tool,
      label: tool,
      description: `Replay tool ${{tool}}`,
      parameters: Type.Record(Type.String(), Type.Any()),
      execute: async (_id, args) => {{
        const fixture = fixtures.find((candidate) => candidate.tool === tool && fixtureArgsMatch(candidate, args || {{}}));
        if (!fixture) throw new Error(`fixture miss: tool=${{tool}}`);
        return {{ content: [{{ type: "text", text: JSON.stringify(fixture.result ?? fixture.response ?? null) }}], details: {{ replay: true }} }};
      }},
    }});
  }}
}}
'''
    extension.write_text(source)
    return extension


def create_executor(name: str) -> Executor:
    if name == "fake":
        return FakeExecutor()
    if name == "pi":
        return PiSdkExecutor()
    if name == "pi-cli":
        return PiCliExecutor()
    if name == "codex":
        return CodexCliExecutor()
    raise ValueError(f"不支持的 executor: {name}")
