import json
import re
import sys

SENSITIVE_KEY = re.compile(
    r"(token|cookie|password|authorization|secret)", re.IGNORECASE
)


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def output(data, output_format="json"):
    safe = redact(data)
    if output_format == "json":
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return
    if output_format == "summary" and isinstance(safe, dict):
        text = ", ".join(f"{key}={value}" for key, value in safe.items())
    else:
        text = json.dumps(safe, ensure_ascii=False, indent=2)
    print(text, file=sys.stderr)
