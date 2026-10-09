#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(text: str, fragment: str) -> None:
    if fragment not in text:
        raise AssertionError(f"SKILL.md 缺少合同片段：{fragment}")


def summarize(events: list[dict[str, object]]) -> dict[str, object]:
    started = {
        str(event["reviewer"])
        for event in events
        if event.get("type") == "started"
    }
    completed = {
        str(event["reviewer"])
        for event in events
        if event.get("type") == "completed" and event.get("usable") is True
    }
    nested = any(
        event.get("type") == "started" and event.get("parent") != "root"
        for event in events
    )
    return {"started": len(started), "completed": len(completed), "nested": nested}


def main() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    for fragment in (
        "remote-tracking ref",
        "base SHA 与 merge-base SHA",
        "started_reviewer_count",
        "completed_reviewer_count",
        "不得再委派",
        "不得调用 `spawn_agent`",
        "整棵本次审查任务树",
        "fork_turns=\"none\"",
        "范围偏移：不适用（静态审查不判断改动是否超出需求）",
    ):
        require(skill, fragment)

    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    case_ids = {case["id"] for case in cases["cases"]}
    expected_cases = {
        "branch-stale-local-base",
        "worktree-three-layers",
        "hard-two-completion",
        "no-nested-delegation",
        "static-scope",
    }
    if case_ids != expected_cases:
        raise AssertionError(f"评测 case 不完整：{sorted(case_ids)}")

    trajectories = json.loads(
        (ROOT / "evals" / "trajectory-fixtures.json").read_text(encoding="utf-8")
    )
    for fixture in trajectories["fixtures"]:
        actual = summarize(fixture["events"])
        if actual != fixture["expected"]:
            raise AssertionError(
                f"轨迹 {fixture['id']} 统计错误：expected={fixture['expected']}, actual={actual}"
            )
    print(f"review-swarm contract OK：{len(case_ids)} cases / {len(trajectories['fixtures'])} trajectories")


if __name__ == "__main__":
    main()
