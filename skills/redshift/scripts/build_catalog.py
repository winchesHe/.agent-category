#!/usr/bin/env python3
"""Maintainer CLI for building and atomically publishing the local catalog."""
from __future__ import annotations

import argparse
import os
import signal
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


HERE = Path(__file__).resolve().parent
if not __package__ and str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

if __package__:
    from .rs.application import build_catalog_artifact
    from .rs.config import load_dotenv
    from .rs.connectivity import ConnectivityPort, RedshiftConnectivity
    from .rs.errors import Interrupted, SkillError, usage_error
    from .rs.output import write_json
else:
    from rs.application import build_catalog_artifact
    from rs.config import load_dotenv
    from rs.connectivity import ConnectivityPort, RedshiftConnectivity
    from rs.errors import Interrupted, SkillError, usage_error
    from rs.output import write_json


class _ParseFailure(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ParseFailure(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="build_catalog", allow_abbrev=False)
    parser.add_argument("--output", required=True)
    parser.add_argument("--domain-map")
    parser.add_argument("--max-age-days", type=int, default=7)
    parser.add_argument("--timeout-ms", type=int)
    return parser


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coverage(catalog: Any) -> dict[str, Any]:
    value = catalog.meta.coverage
    return {
        "status": value.status,
        "visibleDatabaseCount": value.visible_database_count,
        "completeDatabaseCount": value.complete_database_count,
        "failedDatabases": [dict(item) for item in value.failed_databases],
    }


def _success(catalog: Any) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "ok": True,
        "data": {
            "generatedAt": catalog.meta.generated_at.isoformat().replace("+00:00", "Z"),
            "databaseCount": catalog.meta.database_count,
            "relationCount": catalog.meta.relation_count,
            "columnCount": catalog.meta.column_count,
            "coverage": _coverage(catalog),
        },
    }


def _failure(error: SkillError) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "ok": False,
        "error": {
            "category": error.category,
            "code": error.code,
            "retryClass": error.retry_class,
        },
    }


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    connectivity: ConnectivityPort | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> int:
    output = stdout if stdout is not None else sys.stdout
    source_environ = environ if environ is not None else os.environ
    try:
        try:
            args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
        except _ParseFailure as exc:
            code = "missing_argument" if "required" in str(exc) else "invalid_value"
            raise usage_error(code) from exc
        if args.max_age_days <= 0:
            raise usage_error(
                "invalid_value",
                details={"argument": "--max-age-days"},
            )
        if environ is None:
            load_dotenv(os.environ)
        manager = connectivity or RedshiftConnectivity(source_environ)
        catalog = build_catalog_artifact(
            args.output,
            connectivity=manager,
            generated_at=clock(),
            max_age_days=args.max_age_days,
            domain_map=args.domain_map,
            timeout_ms=args.timeout_ms,
        )
        payload = _success(catalog)
        exit_code = 0
    except KeyboardInterrupt:
        failure = Interrupted(signal.SIGINT)
        payload = _failure(failure)
        exit_code = failure.exit_code
    except SkillError as exc:
        payload = _failure(exc)
        exit_code = exc.exit_code
    except Exception:
        failure = SkillError("internal", "unexpected", "never")
        payload = _failure(failure)
        exit_code = failure.exit_code
    try:
        write_json(output, payload)
    except Exception:
        return 8
    return exit_code


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
