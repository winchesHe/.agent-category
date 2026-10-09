"""moe-acceptance 的低开销、脱敏运行轨迹。"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


_SENSITIVE_KEY = re.compile(r"token|cookie|password|authorization|secret|query|body", re.I)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return value[:240]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:240]


class EventLogger:
    """每次运行一个 JSONL 文件，不维护跨运行状态。"""

    def __init__(self, namespace: str, *, session: str = "", root: Optional[Path] = None):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.run_id = f"run-{stamp}-{uuid.uuid4().hex[:8]}"
        self.session_key = "sha256:" + hashlib.sha256(f"{namespace}:{session}".encode()).hexdigest()[:16]
        self.path = (root or Path("/tmp/moe-acceptance") / namespace) / "runs" / f"{self.run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seq = 0

    def emit(
        self,
        phase: str,
        action: str,
        status: str,
        *,
        duration_ms: Optional[float] = None,
        attempt: int = 1,
        trigger: str = "initial",
        retryable: bool = False,
        error_class: Optional[str] = None,
        next_action: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.seq += 1
        event: Dict[str, Any] = {
            "runId": self.run_id,
            "sessionKey": self.session_key,
            "seq": self.seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "action": action,
            "status": status,
            "attempt": attempt,
            "trigger": trigger,
            "retryable": retryable,
            "errorClass": error_class,
            "nextAction": next_action,
            "durationMs": round(duration_ms, 1) if duration_ms is not None else None,
        }
        if details:
            event["details"] = _sanitize(details)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    @staticmethod
    def elapsed(start: float) -> float:
        return (time.monotonic() - start) * 1000
