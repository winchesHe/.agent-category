#!/usr/bin/env python3
"""Run trigger evaluation for a skill description.

Tests whether a skill's description causes the selected runtime to load the
skill for a set of queries. Outputs results as JSON.
"""

import argparse
import json
import sys
import tempfile
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from scripts.eval_runtime.configuration import gpt_model
from scripts.eval_runtime.executors import PiSdkExecutor, RunRequest
from scripts.utils import parse_skill_md


def find_project_root() -> Path:
    """保留调用接口；评测在独立临时目录运行。"""
    return Path.cwd()


def run_single_pi_query(
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    model: str | None = None,
    reasoning: str = "medium",
) -> bool:
    """Run a Pi-native trigger probe and require Pi to read the target skill."""
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name}-skill-{unique_id}"

    with tempfile.TemporaryDirectory(prefix="skill-trigger-") as temp_dir:
        workspace = Path(temp_dir)
        skill_dir = workspace / clean_name
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        indented_desc = "\n  ".join(skill_description.split("\n"))
        skill_file.write_text(
            f"---\n"
            f"name: {clean_name}\n"
            f"description: |\n"
            f"  {indented_desc}\n"
            f"---\n\n"
            f"# {skill_name}\n\n"
            f"This skill handles: {skill_description}\n"
        )

        result = PiSdkExecutor().run(
            RunRequest(
                run_id=f"trigger-{unique_id}",
                prompt=query,
                configuration="with_skill",
                workspace=workspace,
                skill_path=skill_dir,
                model=model,
                limits={"timeout_seconds": timeout, "trigger_only": True, "reasoning": reasoning},
            )
        )
        return result.skill_triggered is True


def run_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    num_workers: int,
    timeout: int,
    project_root: Path,
    runs_per_query: int = 1,
    trigger_threshold: float = 0.5,
    model: str | None = None,
    executor_name: str = "pi",
    reasoning: str = "medium",
) -> dict:
    """Run the full eval set and return results."""
    if executor_name != "pi":
        raise ValueError("原生触发评测仅支持 Pi；Codex 文本执行器不具有等价语义")
    gpt_model(model)
    results = []
    errors = []

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_info = {}
        for item in eval_set:
            for run_idx in range(runs_per_query):
                future = executor.submit(run_single_pi_query, item["query"], skill_name,
                                         description, timeout, model, reasoning)
                future_to_info[future] = (item, run_idx)

        query_triggers: dict[str, list[bool]] = {}
        query_items: dict[str, dict] = {}
        for future in as_completed(future_to_info):
            item, _ = future_to_info[future]
            query = item["query"]
            query_items[query] = item
            if query not in query_triggers:
                query_triggers[query] = []
            try:
                query_triggers[query].append(future.result())
            except Exception as e:
                print(f"Warning: query failed: {e}", file=sys.stderr)
                errors.append({"query": query, "error": str(e)})

    for query, triggers in query_triggers.items():
        item = query_items[query]
        failed_query = any(error["query"] == query for error in errors)
        trigger_rate = sum(triggers) / len(triggers) if triggers else 0.0
        should_trigger = item["should_trigger"]
        if should_trigger:
            did_pass = trigger_rate >= trigger_threshold
        else:
            did_pass = trigger_rate < trigger_threshold
        results.append({
            "query": query,
            "should_trigger": should_trigger,
            "trigger_rate": trigger_rate,
            "triggers": sum(triggers),
            "runs": len(triggers),
            "pass": did_pass and not failed_query,
            "evaluation_status": "not_evaluated" if failed_query else "completed",
        })

    passed = sum(1 for r in results if r["pass"])
    total = len(results)

    return {
        "skill_name": skill_name,
        "executor": executor_name,
        "model": model,
        "reasoning": reasoning,
        "errors": errors,
        "status": "failed" if errors else "completed",
        "description": description,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Run trigger evaluation for a skill description")
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON file")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument("--description", default=None, help="Override description to test")
    parser.add_argument("--num-workers", type=int, default=10, help="Number of parallel workers")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout per query in seconds")
    parser.add_argument("--runs-per-query", type=int, default=3, help="Number of runs per query")
    parser.add_argument("--trigger-threshold", type=float, default=0.5, help="Trigger rate threshold")
    parser.add_argument("--model", required=True, help="准确的 provider/GPT-model，先使用 run_ci --list-models 发现")
    parser.add_argument("--executor", choices=["pi"], default="pi", help="Trigger runtime (default: pi)")
    parser.add_argument("--reasoning", default="medium", choices=["minimal", "low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    args = parser.parse_args()

    eval_set = json.loads(Path(args.eval_set).read_text())
    skill_path = Path(args.skill_path)

    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, original_description, content = parse_skill_md(skill_path)
    description = args.description or original_description
    project_root = find_project_root()

    if args.verbose:
        print(f"Evaluating: {description}", file=sys.stderr)

    output = run_eval(
        eval_set=eval_set,
        skill_name=name,
        description=description,
        num_workers=args.num_workers,
        timeout=args.timeout,
        project_root=project_root,
        runs_per_query=args.runs_per_query,
        trigger_threshold=args.trigger_threshold,
        model=args.model,
        executor_name=args.executor,
        reasoning=args.reasoning,
    )

    if args.verbose:
        summary = output["summary"]
        print(f"Results: {summary['passed']}/{summary['total']} passed", file=sys.stderr)
        for r in output["results"]:
            status = "PASS" if r["pass"] else "FAIL"
            rate_str = f"{r['triggers']}/{r['runs']}"
            print(f"  [{status}] rate={rate_str} expected={r['should_trigger']}: {r['query'][:70]}", file=sys.stderr)

    print(json.dumps(output, indent=2))
    if output.get("errors"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
