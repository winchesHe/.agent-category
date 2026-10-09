"""Structured stdout formatting for Datadog command results."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


def _default(o: Any):
    if isinstance(o, (datetime, date, time)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(f"not serializable: {type(o).__name__}")


def output(data: Any, *, fmt: str = "json", file=None) -> None:
    fp = file or sys.stdout
    if fmt == "summary":
        json.dump(data, fp, ensure_ascii=False, default=_default, separators=(",", ":"))
        fp.write("\n")
    else:
        json.dump(data, fp, ensure_ascii=False, default=_default, indent=2)
        fp.write("\n")
