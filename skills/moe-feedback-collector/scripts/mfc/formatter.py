import json
import sys


def output(data, output_format="json"):
    if output_format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if output_format == "summary" and isinstance(data, dict):
        text = ", ".join(f"{key}={value}" for key, value in data.items())
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    print(text, file=sys.stderr)
