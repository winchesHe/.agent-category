#!/usr/bin/env python3
"""Run deterministic CLI contract fixtures against one candidate Skill directory.

This runner only validates process exit and structured JSON envelopes. It does
not load a host runtime, access external systems, or connect to Redshift.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class HarnessError(Exception):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_digest(candidate_dir: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted(
        path
        for path in candidate_dir.rglob("*.py")
        if "__pycache__" not in path.parts and not any(part.startswith(".") for part in path.relative_to(candidate_dir).parts)
    )
    for path in paths:
        relative = path.relative_to(candidate_dir).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def load_fixtures(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HarnessError(f"cannot load fixture file: {error.__class__.__name__}") from error
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise HarnessError("fixture root must be a schemaVersion=1 object")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise HarnessError("fixture cases must be a non-empty array")
    seen_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise HarnessError("every fixture case must be an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise HarnessError("every fixture case needs a string id")
        if case_id in seen_ids:
            raise HarnessError(f"duplicate fixture id: {case_id}")
        seen_ids.add(case_id)
        if case.get("networkRequired") is not False:
            raise HarnessError(f"fixture {case_id} is not deterministic: networkRequired must be false")
        if not isinstance(case.get("args"), list) or not all(isinstance(value, str) for value in case["args"]):
            raise HarnessError(f"fixture {case_id} args must be a string array")
        expected = case.get("expected")
        if not isinstance(expected, dict) or type(expected.get("exitCode")) is not int:
            raise HarnessError(f"fixture {case_id} expected.exitCode is required")
        json_paths = expected.get("jsonPaths")
        if not isinstance(json_paths, dict):
            raise HarnessError(f"fixture {case_id} expected.jsonPaths must be an object")
    return payload


def lookup_path(payload: Any, dotted_path: str) -> tuple[bool, Any]:
    current = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def scrub_environment(home: Path) -> dict[str, str]:
    allowed = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("REDSHIFT_") and not key.startswith("RS_")
    }
    allowed.update(
        {
            "HOME": str(home),
            "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        }
    )
    return allowed


def safe_actual(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    actual: dict[str, Any] = {}
    for key in ("schemaVersion", "ok", "command"):
        if key in payload and isinstance(payload[key], (str, int, bool, type(None))):
            actual[key] = payload[key]
    error = payload.get("error")
    if isinstance(error, dict):
        actual["error"] = {
            key: error[key]
            for key in ("category", "code", "retryClass")
            if key in error and isinstance(error[key], (str, int, bool, type(None)))
        }
    return actual


def run_case(entrypoint: Path, case: dict[str, Any], *, environment: dict[str, str], timeout_seconds: float) -> dict[str, Any]:
    command = [sys.executable, str(entrypoint), *case["args"]]
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return {
            "id": case["id"],
            "status": "failed",
            "issues": ["process_timeout"],
            "stdoutSha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "stderrSha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        }

    issues: list[str] = []
    expected = case["expected"]
    if process.returncode != expected["exitCode"]:
        issues.append(f"exit_code:{process.returncode}!={expected['exitCode']}")
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        payload = None
        issues.append("stdout_not_json")
    if payload is not None:
        for dotted_path, expected_value in expected["jsonPaths"].items():
            found, actual_value = lookup_path(payload, dotted_path)
            if not found:
                issues.append(f"missing_json_path:{dotted_path}")
            elif actual_value != expected_value:
                issues.append(f"json_mismatch:{dotted_path}")
    return {
        "id": case["id"],
        "status": "passed" if not issues else "failed",
        "exitCode": process.returncode,
        "actual": safe_actual(payload),
        "issues": issues,
        "stdoutSha256": hashlib.sha256(process.stdout.encode("utf-8")).hexdigest(),
        "stderrSha256": hashlib.sha256(process.stderr.encode("utf-8")).hexdigest(),
    }


def run_replay(candidate_dir: Path, fixture_path: Path, *, timeout_seconds: float) -> dict[str, Any]:
    candidate_dir = candidate_dir.resolve()
    if not candidate_dir.is_dir():
        raise HarnessError("candidate directory does not exist")
    if (candidate_dir / ".env").exists():
        raise HarnessError("candidate directory contains .env; deterministic replay refuses live configuration")
    if (candidate_dir / "connections.json").exists():
        raise HarnessError(
            "candidate directory contains connections.json; deterministic replay refuses operator configuration"
        )
    entrypoint = (candidate_dir / "scripts" / "redshift.py").resolve()
    try:
        entrypoint.relative_to(candidate_dir)
    except ValueError as error:
        raise HarnessError("candidate entrypoint escapes candidate directory") from error
    if not entrypoint.is_file():
        raise HarnessError("candidate scripts/redshift.py is missing")
    fixtures = load_fixtures(fixture_path)
    with tempfile.TemporaryDirectory(prefix="redshift-contract-replay-") as temporary_home:
        environment = scrub_environment(Path(temporary_home))
        results = [
            run_case(entrypoint, case, environment=environment, timeout_seconds=timeout_seconds)
            for case in fixtures["cases"]
        ]
    failed = sum(result["status"] == "failed" for result in results)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runner": "deterministic-cli-contract-replay",
        "candidateSha256": candidate_digest(candidate_dir),
        "fixtureSha256": sha256_file(fixture_path),
        "summary": {
            "total": len(results),
            "passed": len(results) - failed,
            "failed": failed,
        },
        "cases": results,
        "limitations": [
            "cli_contract_only",
            "no_model_or_tool_trajectory_evaluation",
            "no_network_or_live_database",
        ],
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    try:
        result = run_replay(args.candidate_dir, args.fixtures, timeout_seconds=args.timeout_seconds)
    except HarnessError as error:
        print(json.dumps({"ok": False, "category": "harness", "code": str(error)}, sort_keys=True))
        return 2
    if args.output:
        atomic_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
