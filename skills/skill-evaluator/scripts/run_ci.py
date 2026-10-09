#!/usr/bin/env python3
"""隔离 Codex 优先、Pi 备用的同设置行为评测、评分与 CI 门禁。"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from scripts.aggregate_benchmark import generate_benchmark
from scripts.eval_runtime.configuration import discover_models, gpt_model, codex_connection
from scripts.eval_runtime.executors import ExecutorError, RunRequest, RunResult, create_executor, validate_result
from scripts.eval_runtime.trajectory import evaluate_assertion, match_trajectory
from scripts.generate_report import generate_html
from scripts.utils import parse_skill_md


def load_cases(path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 evals.json: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("evals"), list):
        raise ValueError("evals.json 必须包含 evals 数组")
    return str(data.get("skill_name", "")), data["evals"]


def _resolve_fixture_paths(case: dict[str, Any], skill_path: Path) -> list[str]:
    paths: list[str] = []
    for raw_path in case.get("fixtures", []):
        path = Path(raw_path)
        paths.append(str(path if path.is_absolute() else skill_path / path))
    return paths


def _write_metadata(run_dir: Path, case: dict[str, Any], eval_id: Any, eval_name: str) -> None:
    (run_dir / "eval_metadata.json").write_text(
        json.dumps(
            {
                "eval_id": eval_id,
                "eval_name": eval_name,
                "prompt": case["prompt"],
                "assertions": case.get("assertions", []),
                "trajectory": case.get("trajectory"),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


def _build_grading(
    case: dict[str, Any],
    result: Any,
    run_dir: Path,
    system_error: str | None = None,
    max_turns: int | None = None,
    max_tool_calls: int | None = None,
) -> tuple[dict[str, Any], bool, bool]:
    system_error = system_error or (str(getattr(result, "errors", [])) if getattr(result, "errors", []) else None)
    if getattr(result, "status", "completed") != "completed":
        system_error = system_error or "运行未完成"
    if system_error:
        return {"expectations": [], "summary": {"passed": 0, "failed": 0, "total": 0, "pass_rate": 0.0},
                "system_error": {"message": system_error}, "evaluation_status": "not_evaluated",
                "execution_metrics": result.metrics, "timing": result.timing}, False, True
    outputs_dir = run_dir / "outputs"
    expectations: list[dict[str, Any]] = []
    assertion_failures = 0
    for index, assertion in enumerate(case.get("assertions", [])):
        passed, evidence = evaluate_assertion(assertion, result.final_answer, outputs_dir)
        expectations.append(
            {
                "text": assertion.get("text") or f"assertion-{index + 1}: {assertion.get('type', 'contains')}",
                "passed": passed,
                "evidence": evidence,
            }
        )
        if not passed:
            assertion_failures += 1

    trajectory_spec = dict(case.get("trajectory") or {})
    if max_turns is not None:
        case_max_turns = trajectory_spec.get("max_turns")
        trajectory_spec["max_turns"] = min(case_max_turns, max_turns) if case_max_turns is not None else max_turns
    if max_tool_calls is not None:
        trajectory_spec["max_calls"] = min(trajectory_spec.get("max_calls", max_tool_calls), max_tool_calls)
    trajectory = match_trajectory(trajectory_spec or None, result.tool_calls, turns=result.metrics.get("total_turns"))
    trajectory_graded = bool(trajectory_spec)
    quality_failed = assertion_failures > 0 or trajectory["status"] == "failed"
    system_failed = system_error is not None or trajectory["status"] == "system_error"
    total = len(expectations) + (1 if trajectory_graded else 0)
    passed = sum(1 for expectation in expectations if expectation["passed"])
    if trajectory_graded and trajectory["status"] == "passed":
        passed += 1
    grading = {
        "expectations": expectations,
        "ungraded_expectations": case.get("expectations", []),
        "summary": {
            "passed": passed,
            "failed": total - passed,
            "total": total,
            "pass_rate": passed / total if total else 1.0,
        },
        "execution_metrics": result.metrics,
        "timing": result.timing,
        "trajectory": trajectory,
        "run_metadata": {
            "executor": result.executor,
            "model": result.model,
            "provider": result.provider,
            "trigger_semantics": result.trigger_semantics,
            "skill_triggered": result.skill_triggered,
            "runtime_settings": getattr(result, "runtime_settings", {}),
        },
    }
    return grading, quality_failed, system_failed


def _write_error_run(run_dir: Path, request: RunRequest, message: str, executor: str) -> Any:
    result = RunResult(request.run_id, executor, request.configuration, "", status="failed",
                       errors=[{"message": message}], model=request.model, provider=request.provider,
                       metrics={"errors_encountered": 1})
    (run_dir / "run_result.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    outputs = run_dir / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "answer.md").write_text("")
    (outputs / "metrics.json").write_text(json.dumps(result.metrics, indent=2) + "\n")
    (run_dir / "transcript.md").write_text(f"## Eval Prompt\n\n{request.prompt}\n\n## Error\n\n{message}\n")
    return result


def _run_attempt(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    skill_path = Path(args.skill_path).resolve()
    evals_path = Path(args.evals or skill_path / "evals" / "evals.json").resolve()
    skill_name, cases = load_cases(evals_path)
    if args.skill_name:
        skill_name = args.skill_name
    if not cases:
        return {"skill_name": skill_name, "runs": 0, "failures": [], "status": "no_cases"}, 3

    output_dir = Path(args.output_dir).resolve()
    iteration_dir = output_dir / "iteration-1"
    executor = create_executor(args.executor)
    gate_configurations = {"with_skill"} if args.gate_configuration == "with_skill" else {"with_skill", "without_skill"}
    failures: list[dict[str, Any]] = []
    non_gating_failures: list[dict[str, Any]] = []
    total_runs = 0
    completed_runs = 0
    not_evaluated = 0
    run_records: list[dict[str, Any]] = []
    report_records: list[dict[str, Any]] = []
    limits = {
        "timeout_seconds": args.timeout,
        "max_turns": args.max_turns,
        "max_tool_calls": args.max_tool_calls,
        "max_output_tokens": args.max_output_tokens,
        "reasoning": args.reasoning,
    }

    for case_index, case in enumerate(cases):
        eval_id = case.get("id", case_index)
        eval_name = case.get("name", f"eval-{eval_id}")
        for configuration in ("with_skill", "without_skill"):
            for run_number in range(1, args.runs + 1):
                total_runs += 1
                run_dir = iteration_dir / f"eval-{eval_id}" / configuration / f"run-{run_number}"
                run_dir.mkdir(parents=True, exist_ok=True)
                _write_metadata(run_dir, case, eval_id, eval_name)
                request = RunRequest.from_case(
                    case,
                    run_id=f"eval-{eval_id}-{configuration}-run-{run_number}",
                    configuration=configuration,
                    workspace=run_dir,
                    skill_path=skill_path,
                    model=args.model,
                    provider=args.provider,
                    limits=limits,
                )
                request.fixtures = _resolve_fixture_paths(case, skill_path)
                error_category = None
                try:
                    result = executor.run(request)
                    validate_result(result, request)
                    completed_runs += 1
                    grading, quality_failed, system_failed = _build_grading(
                        case,
                        result,
                        run_dir,
                        max_turns=request.limits.get("max_turns"),
                        max_tool_calls=request.limits.get("max_tool_calls"),
                    )
                except ExecutorError as exc:
                    error_category = exc.category
                    message = str(exc)
                    result = _write_error_run(run_dir, request, message, args.executor)
                    grading, quality_failed, system_failed = _build_grading(
                        case,
                        result,
                        run_dir,
                        system_error=message,
                        max_turns=request.limits.get("max_turns"),
                        max_tool_calls=request.limits.get("max_tool_calls"),
                    )
                (run_dir / "grading.json").write_text(json.dumps(grading, indent=2, ensure_ascii=False) + "\n")
                report_records.append(
                    {
                        "eval_id": eval_id,
                        "prompt": case["prompt"],
                        "configuration": configuration,
                        "passed": not quality_failed and not system_failed,
                    }
                )
                if not case.get("assertions") and not case.get("trajectory") and request.limits.get("max_turns") is None:
                    not_evaluated += 1
                run_records.append(
                    {
                        "name": f"eval-{eval_id}/{configuration}/run-{run_number}",
                        "failed": quality_failed or system_failed,
                        "gated": system_failed or configuration in gate_configurations,
                    }
                )
                if quality_failed or system_failed:
                    failure = {
                        "eval_id": eval_id,
                        "configuration": configuration,
                        "run_number": run_number,
                        "quality_failed": quality_failed,
                        "system_failed": system_failed,
                        "error_category": error_category,
                        "run_dir": str(run_dir),
                    }
                    if system_failed or configuration in gate_configurations:
                        failures.append(failure)
                    else:
                        non_gating_failures.append(failure)

    benchmark = generate_benchmark(iteration_dir, skill_name, str(skill_path))
    benchmark["metadata"].update(
        {
            "executor": args.executor,
            "executor_model": args.model,
            "purpose": args.purpose,
            "reasoning": args.reasoning,
            "provider": args.provider,
            "runs_per_configuration": args.runs,
        }
    )
    (iteration_dir / "benchmark.json").write_text(json.dumps(benchmark, indent=2, ensure_ascii=False) + "\n")
    (iteration_dir / "benchmark.md").write_text(_benchmark_markdown(benchmark))

    summary = {
        "skill_name": skill_name,
        "purpose": args.purpose,
        "executor": args.executor,
        "output_dir": str(output_dir),
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "not_evaluated_runs": not_evaluated,
        "runs": run_records,
        "failures": failures,
        "non_gating_failures": non_gating_failures,
        "status": "failed" if failures else "passed",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    _write_junit(output_dir / "junit.xml", summary)
    _write_report(output_dir / "report.html", skill_path, skill_name, args.executor, report_records)

    if failures:
        return summary, 2 if any(item["system_failed"] for item in failures) else 1
    return summary, 0


def run_cases(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.executor != "fake":
        args.provider, args.model = gpt_model(args.model, args.provider)
        if args.executor.startswith("pi") and not args.provider:
            raise ValueError("Pi 必须使用 --provider 或 provider/model 明确选择目录项")
        if args.executor == "codex":
            args.provider, _ = codex_connection(args.provider)
    fallback_provider = args.fallback_provider
    if args.codex_provider:
        if args.fallback_executor != "codex" or (fallback_provider and fallback_provider != args.codex_provider):
            raise ValueError("--codex-provider 仅兼容 Codex fallback，不能与 --fallback-provider 冲突")
        fallback_provider = args.codex_provider
    if args.fallback_model:
        gpt_model(args.fallback_model, fallback_provider)
    target = {key: getattr(args, key) for key in ("executor", "model", "provider", "reasoning")}
    fallback_configuration_error = None
    root = Path(args.output_dir).resolve() / (time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6])
    root.mkdir(parents=True)
    attempts = []
    current = copy.copy(args)
    visited = {args.executor}
    while True:
        current.output_dir = str(root / f"attempt-{len(attempts) + 1}-{current.executor}")
        summary, code = _run_attempt(current)
        failures = summary.get("failures", [])
        attempts.append({"executor": current.executor, "model": current.model, "provider": current.provider,
                         "purpose": args.purpose, "reasoning": current.reasoning, "selection_reason": args.selection_reason,
                         "limits": {k: getattr(current, k) for k in ("timeout", "max_turns", "max_tool_calls", "max_output_tokens")},
                         "output_dir": current.output_dir, "exit_code": code, "failures": failures})
        (root / "attempts.json").write_text(json.dumps({"attempts": attempts, "status": summary["status"]}, ensure_ascii=False, indent=2))
        # 只有明确基础设施故障才重建整轮；有效执行后的质量失败保持原结论。
        recoverable = bool(failures) and all(f.get("system_failed") and f.get("error_category") in {"runtime", "service"} for f in failures)
        if not recoverable or summary.get("non_gating_failures"):
            break
        if current.executor == "pi" and args.pi_cli_fallback and "pi-cli" not in visited and all(f["error_category"] == "runtime" for f in failures):
            current.executor = "pi-cli"
        elif args.fallback_executor != "none" and args.fallback_executor not in visited:
            current.executor = args.fallback_executor
            try:
                current.provider, current.model = gpt_model(args.fallback_model or args.model, fallback_provider)
                if current.executor == "codex":
                    current.provider, _ = codex_connection(current.provider)
                elif not current.provider:
                    raise ValueError("Pi fallback 必须通过 --fallback-provider 或 provider/model 指定已配置目录项")
            except ValueError as exc:
                fallback_configuration_error = str(exc)
                break
            current.reasoning = args.fallback_reasoning or args.reasoning
        else:
            break
        visited.add(current.executor)
    summary.setdefault("output_dir", current.output_dir)
    final_status = summary["status"]
    matched = all(attempts[-1][key] == value for key, value in target.items())
    scope = {"fake": "tooling_contract", "codex": "isolated_text"}.get(attempts[-1]["executor"], "pi_controlled")
    if args.purpose == "acceptance" and not matched and code == 0:
        summary["status"] = "target_unverified"
        code = 2
    summary.update(purpose=args.purpose, target_environment=target, target_matched=matched,
                   final_attempt_status=final_status, conclusion_scope=scope,
                   fallback_configuration_error=fallback_configuration_error)
    # 根报告保留备用评分，同时单独标记目标环境尚未完成验收。
    root_records = list(summary.get("runs", []))
    if summary["status"] == "target_unverified":
        root_records.append({"name": "目标环境验收未完成", "failed": True, "gated": True})
    _write_junit(root / "junit.xml", dict(summary, runs=root_records))
    (root / "report.md").write_text(
        f"# 评测结论\n\n用途：{args.purpose}\n\n状态：{summary['status']}\n\n"
        f"覆盖范围：{scope}；不代表完整日常工具环境验收。\n\n"
        f"目标配置：{json.dumps(target, ensure_ascii=False)}\n\n"
        f"目标匹配：{matched}；最终 attempt：{final_status}\n\n"
        f"详细评分：[{Path(summary['output_dir']).name}](./{Path(summary['output_dir']).name}/report.html)\n")
    manifest = {"attempts": attempts, "selected_attempt": len(attempts), "status": summary["status"],
                "purpose": args.purpose, "target_environment": target, "target_matched": matched,
                "conclusion_scope": scope, "fallback_configuration_error": fallback_configuration_error,
                "comparison_policy": "仅最后一次完整同设置 attempt 参与比较；禁止跨 attempt 拼接基线"}
    (root / "attempts.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    summary["attempts_file"] = str(root / "attempts.json")
    summary["attempts"] = attempts
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary, code


def _benchmark_markdown(benchmark: dict[str, Any]) -> str:
    metadata = benchmark["metadata"]
    lines = [
        f"# Skill Benchmark: {metadata['skill_name']}",
        "",
        f"- 评测用途: `{metadata.get('purpose', 'unknown')}`",
        f"- Executor: `{metadata.get('executor', 'unknown')}`",
        f"- Model: `{metadata.get('executor_model', 'unknown')}`",
        f"- Provider: `{metadata.get('provider', 'unknown')}`",
        "",
    ]
    for config, stats in benchmark.get("run_summary", {}).items():
        if config == "delta":
            continue
        lines.append(f"## {config}")
        lines.append(f"- Pass rate: {stats.get('pass_rate', {}).get('mean', 0):.2f}")
        lines.append(f"- Time: {stats.get('time_seconds', {}).get('mean', 0):.2f}s")
        tokens = stats.get("tokens", {})
        lines.append(f"- Tokens: {tokens.get('mean', 0):.0f}" if tokens.get("available_runs") else "- Tokens: 不可用")
        lines.append("")
    return "\n".join(lines)


def _write_junit(path: Path, summary: dict[str, Any]) -> None:
    records = summary.get("runs", [])
    suite = ET.Element(
        "testsuite",
        name="skill-evaluator",
        tests=str(len(records)),
        failures=str(sum(1 for record in records if record["failed"] and record.get("gated", True))),
    )
    for record in records:
        case = ET.SubElement(suite, "testcase", name=record["name"])
        if record["failed"] and record.get("gated", True):
            ET.SubElement(case, "failure", message="eval failed")
        elif record["failed"]:
            ET.SubElement(case, "skipped", message="baseline result; not part of the quality gate")
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _report_results(records: list[dict[str, Any]], configuration: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, str], list[bool]] = {}
    for record in records:
        if record["configuration"] != configuration:
            continue
        key = (record["eval_id"], record["prompt"])
        grouped.setdefault(key, []).append(bool(record["passed"]))

    results = []
    for (eval_id, prompt), outcomes in grouped.items():
        passed = sum(outcomes)
        results.append(
            {
                "query": f"eval-{eval_id}: {prompt}",
                "should_trigger": True,
                "triggers": passed,
                "runs": len(outcomes),
                "pass": passed == len(outcomes),
            }
        )
    return results


def _write_report(
    path: Path,
    skill_path: Path,
    skill_name: str,
    executor: str,
    records: list[dict[str, Any]],
) -> None:
    _, description, _ = parse_skill_md(skill_path)
    with_skill = _report_results(records, "with_skill")
    without_skill = _report_results(records, "without_skill")
    train_passed = sum(item["triggers"] for item in with_skill)
    train_total = sum(item["runs"] for item in with_skill)
    test_passed = sum(item["triggers"] for item in without_skill)
    test_total = sum(item["runs"] for item in without_skill)
    report_data = {
        "original_description": description,
        "best_description": description,
        "best_score": train_passed / train_total if train_total else 0.0,
        "best_train_score": train_passed / train_total if train_total else 0.0,
        "best_test_score": test_passed / test_total if test_total else 0.0,
        "iterations_run": 1,
        "train_size": len(with_skill),
        "test_size": len(without_skill),
        "history": [
            {
                "iteration": 1,
                "description": f"Executor: {executor}; with_skill vs without_skill",
                "train_results": with_skill,
                "test_results": without_skill,
                "train_passed": train_passed,
                "train_total": train_total,
                "test_passed": test_passed,
                "test_total": test_total,
            }
        ],
    }
    path.write_text(generate_html(report_data, skill_name=skill_name))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run headless Skill Evaluator evals")
    parser.add_argument("--skill-path", help="待评测 Skill 目录；--list-models 时可省略")
    parser.add_argument("--evals", default=None, help="evals.json 路径，默认 <skill>/evals/evals.json")
    parser.add_argument("--skill-name", default=None)
    parser.add_argument(
        "--executor",
        choices=["fake", "pi", "pi-cli", "codex"],
        default="codex",
        help="执行器，默认隔离 Codex 文本执行",
    )
    parser.add_argument("--pi-cli-fallback", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--gate-configuration",
        choices=["with_skill", "both"],
        default="with_skill",
        help="质量门禁配置，默认只门禁 with_skill；baseline 仍记录并进入报告",
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument("--max-tool-calls", type=int, default=30)
    parser.add_argument("--max-output-tokens", type=int, default=12000)
    parser.add_argument("--list-models", action="store_true", help="只读列出已配置 GPT 候选，交由 Agent 选择")
    parser.add_argument("--selection-reason", default="调用方显式指定", help="本次模型选择依据")
    parser.add_argument("--fallback-executor", choices=["pi", "codex", "none"], default="pi")
    parser.add_argument("--fallback-model", help="备用 GPT；省略时保持主模型 ID")
    parser.add_argument("--purpose", choices=["acceptance", "smoke", "portability"], default="acceptance")
    parser.add_argument("--fallback-provider", help="备用连接；Pi 必须显式指定")
    parser.add_argument("--fallback-reasoning", choices=["minimal", "low", "medium", "high", "xhigh", "max"], help="备用推理等级，省略时保持主设置")
    parser.add_argument("--codex-provider", help="备用 Codex 连接，省略时读取现有连接配置")
    parser.add_argument("--reasoning", choices=["minimal", "low", "medium", "high", "xhigh", "max"], default="medium")
    parser.add_argument("--model", default=None, help="Agent 从发现结果选择的准确 GPT ID，Pi 支持 provider/model")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--output-dir", default="./skill-eval-results")
    parser.add_argument("--strict", action="store_true", help="失败时返回门禁退出码")
    args = parser.parse_args()

    if args.list_models:
        print(json.dumps(discover_models(), ensure_ascii=False, indent=2))
        return
    if not args.skill_path:
        parser.error("必须提供 --skill-path")
    if args.runs < 1 or args.timeout <= 0:
        parser.error("runs 与 timeout 必须为正数")
    try:
        summary, exit_code = run_cases(args)
    except (OSError, ValueError) as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.strict:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
