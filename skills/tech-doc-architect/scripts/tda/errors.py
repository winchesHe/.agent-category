"""CLI 退出码与错误载荷。"""

from __future__ import annotations

from typing import Any, Optional


EXIT_OK = 0
EXIT_INPUT = 2
EXIT_VALIDATION = 4


def error_payload(
    command: str,
    target: str,
    message: str,
    *,
    errors: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "command": command,
        "target": target,
        "message": message,
        "errors": errors or [message],
    }
