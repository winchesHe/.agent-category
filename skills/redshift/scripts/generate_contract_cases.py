#!/usr/bin/env python3
"""Regenerate the deterministic CLI replay fixture from CommandSpec truth."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.rs.contract import contract_replay_fixture  # noqa: E402


def write_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        contract_replay_fixture(),
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "contract-cases.json",
    )
    args = parser.parse_args(argv)
    write_fixture(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
