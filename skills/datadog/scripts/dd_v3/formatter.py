"""Atomic JSON rendering for Datadog command envelopes."""
from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

SCHEMA_VERSION = 2


def _default(o: Any):
    if isinstance(o, (datetime, date, time)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(f"not serializable: {type(o).__name__}")


def render(data: Any, *, fmt: str = "json") -> str:
    """Return one complete JSON document without performing I/O."""
    if fmt not in {"json", "summary"}:
        raise ValueError(f"unsupported output format: {fmt}")
    if fmt == "summary":
        document = json.dumps(
            data,
            ensure_ascii=False,
            default=_default,
            allow_nan=False,
            separators=(",", ":"),
        )
    else:
        document = json.dumps(
            data,
            ensure_ascii=False,
            default=_default,
            allow_nan=False,
            indent=2,
        )
    return document + "\n"


def success(
    command: str,
    *,
    target: Any,
    result: Any,
    meta: dict[str, Any] | None = None,
    verification_result: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "ok": True,
        "target": target,
        "result": result,
        "meta": meta or {},
        "verification": verification_result,
        "warnings": warnings or [],
    }


def error(command: str, exc: Any) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "ok": False,
        "target": getattr(exc, "target", None),
        "result": getattr(exc, "domain_result", None),
        "meta": getattr(exc, "domain_meta", {}),
        "verification": None,
        "warnings": [],
        "error": {
            "category": exc.category,
            "code": exc.error_code,
            "retry_class": exc.retry_class,
            "operation_state": exc.operation_state,
        },
    }
