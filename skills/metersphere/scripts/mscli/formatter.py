from __future__ import annotations

import json
import sys
from typing import Any


def output(value: Any, output_format: str = "json") -> None:
    if output_format == "json":
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if output_format == "summary":
        if isinstance(value, dict):
            summary_keys = (
                "success", "message", "id", "num", "name", "deleted", "projectId", "keyword",
                "matchType", "itemCount", "totalCases", "reviewedCases", "unreviewedCases", "totalBugLinks",
            )
            summary = {key: value[key] for key in summary_keys if key in value}
            print(json.dumps(summary or value, ensure_ascii=False))
        else:
            print(str(value))
        return
    print(json.dumps(value, ensure_ascii=False, indent=2), file=sys.stderr)
