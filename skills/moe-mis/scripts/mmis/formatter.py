import json
import re
import sys

SENSITIVE_KEY = re.compile(r"(token|cookie|password|authorization|secret)", re.IGNORECASE)


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def output(data, output_format="json", allow_sensitive=False):
    safe = data if allow_sensitive else redact(data)
    if output_format == "json":
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return
    if output_format == "summary":
        if isinstance(safe, dict):
            text = ", ".join(f"{k}={v}" for k, v in safe.items())
        else:
            text = str(safe)
    else:
        text = json.dumps(safe, ensure_ascii=False, indent=2)
    print(text, file=sys.stderr)

