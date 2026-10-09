"""确定性 Tool Trajectory 匹配器。

Trajectory 只判断结构化工具调用，不用 LLM 猜测 Agent 是否走了正确路径。
"""

from __future__ import annotations

import re
from typing import Any


def deep_contains(actual: Any, expected: Any) -> bool:
    """判断 actual 是否递归包含 expected 的关键结构。"""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and deep_contains(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(any(deep_contains(item, candidate) for item in actual) for candidate in expected)
    return json_strict_equal(actual, expected)


def json_strict_equal(actual: Any, expected: Any) -> bool:
    """按 JSON 类型严格比较，避免 Python 把 true 与 1 判为相等。"""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if isinstance(actual, (int, float)) or isinstance(expected, (int, float)):
        return (
            isinstance(actual, (int, float))
            and isinstance(expected, (int, float))
            and actual == expected
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(json_strict_equal(actual[key], expected[key]) for key in expected)
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(json_strict_equal(left, right) for left, right in zip(actual, expected))
        )
    return type(actual) is type(expected) and actual == expected


def deep_ends_with(actual: Any, expected: Any) -> bool:
    """按完整路径组件判断字符串后缀，其余类型保持 JSON 严格匹配。"""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and deep_ends_with(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(any(deep_ends_with(item, candidate) for item in actual) for candidate in expected)
    if isinstance(expected, str):
        if not isinstance(actual, str):
            return False
        normalized_actual = actual.replace("\\", "/").rstrip("/")
        normalized_expected = expected.replace("\\", "/").strip("/")
        return normalized_actual == normalized_expected or normalized_actual.endswith(f"/{normalized_expected}")
    return json_strict_equal(actual, expected)


def normalize_call(call: dict[str, Any]) -> dict[str, Any]:
    """兼容 Pi、CLI 和 fixture 使用的工具调用字段名。"""
    return {
        "tool": call.get("tool") or call.get("name") or call.get("toolName") or "",
        "args": call.get("args") if "args" in call else call.get("input", {}),
        "call_id": call.get("call_id") or call.get("toolCallId") or call.get("id"),
    }


def call_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    expected_tool = expected.get("tool") or expected.get("name")
    if expected_tool and expected_tool != actual.get("tool"):
        return False

    actual_args = actual.get("args", {})
    if "args_contain" in expected and not deep_contains(actual_args, expected["args_contain"]):
        return False
    if "args_end_with" in expected and not deep_ends_with(actual_args, expected["args_end_with"]):
        return False
    if "args_exact" in expected and not json_strict_equal(actual_args, expected["args_exact"]):
        return False
    return True


def _failure(kind: str, **details: Any) -> dict[str, Any]:
    return {"type": kind, **details}


def match_trajectory(
    spec: dict[str, Any] | None,
    calls: list[dict[str, Any]],
    turns: int | None = None,
) -> dict[str, Any]:
    """匹配一条 Trajectory，返回可直接写入 grading.json 的结果。"""
    if not spec:
        return {
            "status": "not_applicable",
            "mode": None,
            "expected_calls": [],
            "actual_calls": [normalize_call(call) for call in calls],
            "failures": [],
        }

    mode = spec.get("mode", "ordered")
    expected = list(spec.get("calls", []))
    actual = [normalize_call(call) for call in calls]
    failures: list[dict[str, Any]] = []

    max_calls = spec.get("max_calls")
    if max_calls is not None and len(actual) > max_calls:
        failures.append(_failure("max_calls_exceeded", maximum=max_calls, actual=len(actual)))
    if turns is not None and spec.get("max_turns") is not None and turns > spec["max_turns"]:
        failures.append(_failure("max_turns_exceeded", maximum=spec["max_turns"], actual=turns))

    if mode == "exact":
        if len(actual) != len(expected):
            failures.append(_failure("call_count_mismatch", expected=len(expected), actual=len(actual)))
        for index, (wanted, observed) in enumerate(zip(expected, actual)):
            if not call_matches(wanted, observed):
                failures.append(_failure("call_mismatch", index=index, expected=wanted, actual=observed))
    elif mode == "ordered":
        cursor = 0
        for wanted in expected:
            found = False
            while cursor < len(actual):
                observed = actual[cursor]
                cursor += 1
                if call_matches(wanted, observed):
                    found = True
                    break
            if not found:
                failures.append(_failure("missing_ordered_call", expected=wanted))
                break
    elif mode in {"unordered", "superset"}:
        remaining = list(actual)
        for wanted in expected:
            for index, observed in enumerate(remaining):
                if call_matches(wanted, observed):
                    remaining.pop(index)
                    break
            else:
                failures.append(_failure("missing_call", expected=wanted))
    elif mode == "subset":
        for observed in actual:
            if not any(call_matches(wanted, observed) for wanted in expected):
                failures.append(_failure("unexpected_call", actual=observed))
    else:
        failures.append(_failure("unsupported_mode", mode=mode))

    return {
        "status": "failed" if failures else "passed",
        "mode": mode,
        "expected_calls": expected,
        "actual_calls": actual,
        "failures": failures,
    }


def evaluate_assertion(assertion: dict[str, Any], final_answer: str, outputs_dir: Any) -> tuple[bool, str]:
    """执行 CI 可用的轻量确定性 Assertion。"""
    kind = assertion.get("type", "contains")
    value = assertion.get("value", "")
    text = final_answer

    if kind == "contains":
        passed = str(value) in text
        return passed, f"最终回答{'包含' if passed else '不包含'} {value!r}"
    if kind == "not_contains":
        passed = str(value) not in text
        return passed, f"最终回答{'不包含' if passed else '包含'} {value!r}"
    if kind == "regex":
        passed = re.search(str(value), text) is not None
        return passed, f"正则 {value!r}{'匹配' if passed else '未匹配'}最终回答"
    if kind == "json_valid":
        import json

        try:
            json.loads(text)
            return True, "最终回答是有效 JSON"
        except json.JSONDecodeError as exc:
            return False, f"最终回答不是有效 JSON: {exc}"
    if kind == "file_exists":
        path = outputs_dir / str(value)
        passed = path.is_file()
        return passed, f"文件 {value!r}{'存在' if passed else '不存在'}"
    return False, f"不支持的 assertion 类型: {kind}"
