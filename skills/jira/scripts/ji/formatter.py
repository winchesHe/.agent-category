"""Structured stdout formatting for Jira command results."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


def _default(value: Any) -> str:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not serializable: {type(value).__name__}")


def _human_line(data: Any) -> str:
    if not isinstance(data, dict):
        return str(data)
    if data.get("command") == "read":
        issue = data.get("issue") or {}
        return f"{issue.get('key', '?')} [{issue.get('status', '?')}] {issue.get('summary', '')}"
    if data.get("command") == "search":
        return f"JQL returned {data.get('count', 0)} issues"
    if data.get("command") == "download-attachment":
        return f"downloaded: {data.get('local_path')}" if data.get("ok") else "download failed"
    if data.get("command") in {"create", "update", "transition"}:
        if data.get("command") == "transition" and data.get("mode") == "list":
            return f"{len(data.get('transitions') or [])} transitions available"
        if data.get("dry_run"):
            return f"{data.get('command')} dry-run payload ready"
        return f"{data.get('command')} executed"
    return json.dumps(data, ensure_ascii=False, default=_default, separators=(",", ":"))


def output(data: Any, *, fmt: str = "json") -> None:
    if fmt == "human":
        sys.stderr.write(_human_line(data) + "\n")

    if fmt == "summary":
        json.dump(data, sys.stdout, ensure_ascii=False, default=_default, separators=(",", ":"))
    else:
        json.dump(data, sys.stdout, ensure_ascii=False, default=_default, indent=2)
    sys.stdout.write("\n")
