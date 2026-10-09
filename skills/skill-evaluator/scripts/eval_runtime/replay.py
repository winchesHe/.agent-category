"""受控工具 Replay registry。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .trajectory import deep_contains, json_strict_equal


class ReplayError(RuntimeError):
    """Fixture 未命中或格式错误。"""


class ReplayRegistry:
    def __init__(self, fixtures: list[dict[str, Any]] | None = None) -> None:
        self.fixtures = fixtures or []
        self.calls: list[dict[str, Any]] = []

    @classmethod
    def from_paths(cls, paths: list[str], base_dir: Path | None = None) -> "ReplayRegistry":
        fixtures: list[dict[str, Any]] = []
        root = base_dir or Path.cwd()
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_absolute():
                path = root / path
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise ReplayError(f"无法读取 fixture {path}: {exc}") from exc
            if isinstance(data, list):
                fixtures.extend(data)
            elif isinstance(data, dict):
                fixtures.append(data)
            else:
                raise ReplayError(f"fixture 必须是 object 或 array: {path}")
        return cls(fixtures)

    def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        args = args or {}
        call = {"tool": tool, "args": args}
        self.calls.append(call)
        for fixture in self.fixtures:
            if fixture.get("tool") != tool:
                continue
            if "args_exact" in fixture:
                if not json_strict_equal(args, fixture["args_exact"]):
                    continue
            elif not deep_contains(args, fixture.get("args_contain", {})):
                continue
            if "result" in fixture:
                return fixture["result"]
            if "response" in fixture:
                return fixture["response"]
        raise ReplayError(f"fixture miss: tool={tool}, args={json.dumps(args, ensure_ascii=False)}")
