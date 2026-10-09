"""scan-slow-sql: query slow database statements over a time window."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlencode

from dd_v3.client import DatadogClient
from dd_v3.errors import (
    ApiError,
    AuthError,
    DatadogCliError,
    EXIT_API_ERROR,
)
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import now_millis, parse_time_to_unix_millis

NAME = "scan-slow-sql"
_SCALAR_PATH = "/api/v2/query/scalar"
_SAMPLE_PATH = "/api/v1/logs-analytics/list"
_AVG_FORMULA = "total_time_ns / executions / 1000000000"
_SIGNATURE_RE = re.compile(r"^[0-9a-fA-F]+$")
_BATCH_SIZE = 100


@dataclass(frozen=True)
class DatabaseSpec:
    key: str
    label: str
    dbms_tag: str
    time_metric: str
    count_metric: str
    database_dimension: str


_SPECS = {
    "mysql": DatabaseSpec(
        key="mysql",
        label="MySQL",
        dbms_tag="mysql",
        time_metric="mysql.queries.time",
        count_metric="mysql.queries.count",
        database_dimension="schema",
    ),
    "postgresql": DatabaseSpec(
        key="postgresql",
        label="PostgreSQL",
        dbms_tag="postgres",
        time_metric="postgresql.queries.time",
        count_metric="postgresql.queries.count",
        database_dimension="db",
    ),
}


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="查询生产环境慢 SQL")
    p.add_argument(
        "--from",
        required=True,
        dest="from_time",
        help="窗口起始时间；查询最新数据时使用 7d",
    )
    p.add_argument(
        "--to",
        dest="to_time",
        help="窗口结束时间；未提供时默认取当前时间",
    )
    p.add_argument(
        "--database-type",
        choices=["all", "mysql", "postgresql"],
        default="all",
        help="数据库类型，默认 all",
    )
    p.add_argument(
        "--scope",
        default="database_instance:prod*",
        help="Datadog metric tag 过滤条件",
    )
    p.add_argument("--min-avg-seconds", type=float, default=5.0)
    p.add_argument("--min-count", type=float, default=100.0)
    p.add_argument(
        "--top",
        type=int,
        default=400,
        help="按 Avg Duration 降序读取的候选上限，默认 400",
    )
    p.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    p.set_defaults(_handler=run, _policy=READ)


def _validate_args(args) -> tuple[int, int]:
    if not args.from_time:
        raise ApiError("缺少必填参数 --from；查询最新数据时使用 --from 7d")
    reference_ms = now_millis()
    to_ms = (
        parse_time_to_unix_millis(args.to_time, now_ms=reference_ms)
        if args.to_time
        else reference_ms
    )
    from_ms = parse_time_to_unix_millis(args.from_time, now_ms=reference_ms)
    if from_ms >= to_ms:
        raise ApiError("--from 必须早于 --to")
    if not math.isfinite(args.min_avg_seconds) or args.min_avg_seconds < 0:
        raise ApiError("--min-avg-seconds 必须是大于等于 0 的有限数字")
    if not math.isfinite(args.min_count) or args.min_count < 0:
        raise ApiError("--min-count 必须是大于等于 0 的有限数字")
    if not 1 <= args.top <= 1000:
        raise ApiError("--top 必须在 1 到 1000 之间")
    if not args.scope.strip():
        raise ApiError("--scope 不能为空")
    return from_ms, to_ms


def _metric_query(name: str, metric: str, scope: str, dimensions: Iterable[str]) -> dict[str, Any]:
    group = ",".join(dimensions)
    return {
        "data_source": "metrics",
        "name": name,
        "query": f"sum:{metric}{{{scope}}} by {{{group}}}",
        "aggregator": "sum",
    }


def _scalar_payload(
    from_ms: int,
    to_ms: int,
    queries: list[dict[str, Any]],
    formulas: list[str],
    *,
    formula_limit: int | None = None,
) -> dict[str, Any]:
    formula_objects = [{"formula": formula} for formula in formulas]
    if formula_limit is not None:
        formula_objects[0]["limit"] = {"count": formula_limit, "order": "desc"}
    return {
        "data": {
            "type": "scalar_request",
            "attributes": {
                "from": from_ms,
                "to": to_ms,
                "queries": queries,
                "formulas": formula_objects,
            },
        }
    }


def _scalar_columns(body: dict[str, Any]) -> dict[str, list[Any]]:
    if not isinstance(body, dict):
        raise ApiError("Datadog scalar 响应格式无效", error_code="invalid_response")
    data = body.get("data")
    attrs = data.get("attributes") if isinstance(data, dict) else None
    columns = attrs.get("columns") if isinstance(attrs, dict) else None
    if not isinstance(columns, list) or not columns:
        raise ApiError("Datadog scalar 响应缺少 columns", error_code="invalid_response")
    result: dict[str, list[Any]] = {}
    for column in columns:
        if (
            not isinstance(column, dict)
            or not isinstance(column.get("name"), str)
            or not column["name"].strip()
            or not isinstance(column.get("values"), list)
            or column["name"] in result
        ):
            raise ApiError("Datadog scalar column 格式无效", error_code="invalid_response")
        values = column.get("values")
        result[column["name"]] = values
    return result


def _rows(columns: dict[str, list[Any]]) -> list[dict[str, Any]]:
    lengths = {len(values) for values in columns.values()}
    if len(lengths) > 1:
        raise ApiError("Datadog scalar columns 长度不一致", error_code="invalid_response")
    length = next(iter(lengths), 0)
    return [
        {name: values[index] if index < len(values) else None for name, values in columns.items()}
        for index in range(length)
    ]


def _flatten_values(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for item in value:
            values.extend(_flatten_values(item))
        return values
    if value is None:
        return []
    text = str(value).strip()
    if not text or text.lower() == "_other":
        return []
    return [text]


def _signature(value: Any) -> str | None:
    for item in _flatten_values(value):
        if _SIGNATURE_RE.fullmatch(item):
            return item.lower()
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _chunks(values: list[str], size: int = _BATCH_SIZE) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _signature_scope(scope: str, signatures: list[str]) -> str:
    joined = ",".join(signatures)
    return f"{scope} AND query_signature IN ({joined})"


def _discover_candidates(
    client: DatadogClient,
    spec: DatabaseSpec,
    *,
    from_ms: int,
    to_ms: int,
    scope: str,
    top: int,
    min_avg_seconds: float,
) -> tuple[list[str], dict[str, Any]]:
    queries = [
        _metric_query("total_time_ns", spec.time_metric, scope, ["query_signature"]),
        _metric_query("executions", spec.count_metric, scope, ["query_signature"]),
    ]
    body = client.request_read(
        "POST",
        _SCALAR_PATH,
        json_body=_scalar_payload(
            from_ms,
            to_ms,
            queries,
            [_AVG_FORMULA],
            formula_limit=top,
        ),
    )
    rows = _rows(_scalar_columns(body))
    averages: list[tuple[str, float]] = []
    null_avg_count = 0
    for row in rows:
        signature = _signature(row.get("query_signature"))
        average = _number(row.get(_AVG_FORMULA))
        if not signature or average is None:
            null_avg_count += 1
            continue
        averages.append((signature, average))

    minimum_returned = min((average for _, average in averages), default=None)
    coverage_complete = len(rows) < top or (
        minimum_returned is not None and minimum_returned <= min_avg_seconds
    )
    if not coverage_complete:
        raise ApiError(
            f"{spec.label} Top {top} 的末位 Avg Duration 仍高于阈值；"
            "无法证明候选覆盖完整，请提高 --top 或缩小 --scope"
        )
    candidates = sorted({signature for signature, average in averages if average > min_avg_seconds})
    return candidates, {
        "rows_returned": len(rows),
        "null_avg_count": null_avg_count,
        "minimum_returned_avg_seconds": minimum_returned,
        "coverage_complete": True,
    }


def _read_exact_metrics(
    client: DatadogClient,
    spec: DatabaseSpec,
    signatures: list[str],
    *,
    from_ms: int,
    to_ms: int,
    scope: str,
) -> tuple[dict[str, dict[str, float]], int]:
    exact: dict[str, dict[str, float]] = {}
    request_count = 0
    for batch in _chunks(signatures):
        batch_scope = _signature_scope(scope, batch)
        queries = [
            _metric_query("total_time_ns", spec.time_metric, batch_scope, ["query_signature"]),
            _metric_query("executions", spec.count_metric, batch_scope, ["query_signature"]),
        ]
        formulas = ["total_time_ns", "executions", _AVG_FORMULA]
        body = client.request_read(
            "POST",
            _SCALAR_PATH,
            json_body=_scalar_payload(from_ms, to_ms, queries, formulas),
        )
        request_count += 1
        for row in _rows(_scalar_columns(body)):
            signature = _signature(row.get("query_signature"))
            total_time = _number(row.get("total_time_ns"))
            executions = _number(row.get("executions"))
            if not signature or total_time is None or executions is None or executions <= 0:
                continue
            exact[signature] = {
                "total_time_ns": total_time,
                "count": executions,
                "avg_duration_seconds": total_time / executions / 1_000_000_000,
            }
    return exact, request_count


def _read_context(
    client: DatadogClient,
    spec: DatabaseSpec,
    signatures: list[str],
    *,
    from_ms: int,
    to_ms: int,
    scope: str,
) -> tuple[dict[str, dict[str, set[str]]], int]:
    contexts: dict[str, dict[str, set[str]]] = {}
    request_count = 0
    dimensions = [
        "query_signature",
        "database_instance",
        "dbclusteridentifier",
        spec.database_dimension,
        "table",
    ]
    for batch in _chunks(signatures):
        batch_scope = _signature_scope(scope, batch)
        queries = [_metric_query("executions", spec.count_metric, batch_scope, dimensions)]
        body = client.request_read(
            "POST",
            _SCALAR_PATH,
            json_body=_scalar_payload(from_ms, to_ms, queries, ["executions"]),
        )
        request_count += 1
        for row in _rows(_scalar_columns(body)):
            signature = _signature(row.get("query_signature"))
            if not signature:
                continue
            context = contexts.setdefault(
                signature,
                {"database_instances": set(), "db_cluster_identifiers": set(), "databases": set(), "tables": set()},
            )
            context["database_instances"].update(_flatten_values(row.get("database_instance")))
            context["db_cluster_identifiers"].update(_flatten_values(row.get("dbclusteridentifier")))
            context["databases"].update(_flatten_values(row.get(spec.database_dimension)))
            context["tables"].update(_flatten_values(row.get("table")))
    return contexts, request_count


def _iso_time(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _deep_get(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_path(roots: list[dict[str, Any]], paths: list[tuple[str, ...]]) -> Any:
    for root in roots:
        for path in paths:
            value = _deep_get(root, path)
            if value not in (None, "", []):
                return value
    return None


def _sample_roots(item: dict[str, Any]) -> list[dict[str, Any]]:
    roots = [item]
    for path in [("attributes",), ("attributes", "attributes"), ("event",), ("attributes", "event")]:
        value = _deep_get(item, path)
        if isinstance(value, dict):
            roots.append(value)
    return roots


def _extract_sample(body: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(body, dict):
        raise ApiError("Datadog DBM sample 响应格式无效", error_code="invalid_response")
    result = body.get("result")
    events = result.get("events") if isinstance(result, dict) else None
    if not isinstance(events, list):
        raise ApiError("Datadog DBM sample 响应格式无效", error_code="invalid_response")
    if not events:
        return None
    if any(not isinstance(event, dict) for event in events):
        raise ApiError("Datadog DBM sample event 格式无效", error_code="invalid_response")
    roots = _sample_roots(events[0])
    statement = _first_path(
        roots,
        [
            ("event", "custom", "db", "statement"),
            ("custom", "db", "statement"),
            ("db", "statement"),
        ],
    )
    database = _first_path(
        roots,
        [
            ("event", "custom", "db", "instance"),
            ("custom", "db", "instance"),
            ("db", "instance"),
        ],
    )
    tables = _first_path(
        roots,
        [
            ("event", "custom", "db", "metadata", "tables"),
            ("custom", "db", "metadata", "tables"),
            ("db", "metadata", "tables"),
        ],
    )
    instance = _first_path(
        roots,
        [
            ("event", "custom", "database_instance"),
            ("custom", "database_instance"),
            ("database_instance",),
        ],
    )
    tags = _first_path(roots, [("event", "tags"), ("tags",)])
    clusters: set[str] = set()
    for tag in _flatten_values(tags):
        key, separator, value = tag.partition(":")
        if separator and key == "dbclusteridentifier" and value:
            clusters.add(value)
    return {
        "normalized_sql": str(statement).strip() if statement else None,
        "database_instances": set(_flatten_values(instance)),
        "db_cluster_identifiers": clusters,
        "databases": set(_flatten_values(database)),
        "tables": set(_flatten_values(tables)),
    }


def _read_sample(
    client: DatadogClient,
    spec: DatabaseSpec,
    signature: str,
    *,
    from_ms: int,
    to_ms: int,
    scope: str,
) -> dict[str, Any] | None:
    query = f"dbm_type:activity dbms:{spec.dbms_tag} {scope} @db.query_signature:{signature}"
    payload = {
        "list": {
            "indexes": ["databasequery"],
            "limit": 1,
            "search": {"query": query},
            "sorts": [{"time": {"order": "desc"}}],
            "time": {"from": from_ms, "to": to_ms},
        }
    }
    body = client.request_read(
        "POST",
        _SAMPLE_PATH,
        params={"type": "databasequery"},
        json_body=payload,
        surface="ui",
    )
    return _extract_sample(body)


def _datadog_query_url(config, spec: DatabaseSpec, signature: str, scope: str, from_ms: int, to_ms: int) -> str:
    params = {
        "query": f"query_signature:{signature} {scope}",
        "dbType": spec.label,
        "fromUser": "false",
        "start": str(from_ms),
        "end": str(to_ms),
        "paused": "false",
    }
    return f"{config.ui_base_url}/databases/queries?{urlencode(params)}"


def _scan_database(
    client: DatadogClient,
    config,
    spec: DatabaseSpec,
    args,
    from_ms: int,
    to_ms: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates, coverage = _discover_candidates(
        client,
        spec,
        from_ms=from_ms,
        to_ms=to_ms,
        scope=args.scope,
        top=args.top,
        min_avg_seconds=args.min_avg_seconds,
    )
    request_count = 1
    if not candidates:
        return {
            "status": "success",
            **coverage,
            "avg_candidates": 0,
            "qualified_count": 0,
            "logical_request_count": request_count,
        }, []

    exact, exact_requests = _read_exact_metrics(
        client, spec, candidates, from_ms=from_ms, to_ms=to_ms, scope=args.scope
    )
    request_count += exact_requests
    missing_exact = sorted(set(candidates) - set(exact))
    if missing_exact:
        preview = ", ".join(missing_exact[:5])
        suffix = "..." if len(missing_exact) > 5 else ""
        raise ApiError(
            f"{spec.label} 精确指标缺少 {len(missing_exact)} 个候选 Signature: "
            f"{preview}{suffix}"
        )
    qualified = {
        signature: metrics
        for signature, metrics in exact.items()
        if metrics["avg_duration_seconds"] > args.min_avg_seconds and metrics["count"] > args.min_count
    }
    if not qualified:
        return {
            "status": "success",
            **coverage,
            "avg_candidates": len(candidates),
            "qualified_count": 0,
            "logical_request_count": request_count,
        }, []

    signatures = sorted(qualified)
    contexts, context_requests = _read_context(
        client, spec, signatures, from_ms=from_ms, to_ms=to_ms, scope=args.scope
    )
    request_count += context_requests
    queries: list[dict[str, Any]] = []
    sample_errors = 0
    sample_skipped = 0
    sample_auth_failed = False
    for signature in signatures:
        context = contexts.get(
            signature,
            {"database_instances": set(), "db_cluster_identifiers": set(), "databases": set(), "tables": set()},
        )
        normalized_sql = None
        sample_status = "found"
        if sample_auth_failed:
            sample_status = "error"
            sample_skipped += 1
        else:
            try:
                sample = _read_sample(
                    client, spec, signature, from_ms=from_ms, to_ms=to_ms, scope=args.scope
                )
                request_count += 1
                if sample is None:
                    sample_status = "not_found"
                else:
                    normalized_sql = sample["normalized_sql"]
                    for key in ("database_instances", "db_cluster_identifiers", "databases", "tables"):
                        context[key].update(sample[key])
            except AuthError:
                request_count += 1
                sample_errors += 1
                sample_auth_failed = True
                sample_status = "error"
            except DatadogCliError:
                request_count += 1
                sample_errors += 1
                sample_status = "error"
        metrics = qualified[signature]
        queries.append({
            "query_signature": signature,
            "database_type": spec.label,
            "avg_duration_seconds": round(metrics["avg_duration_seconds"], 6),
            "count": int(metrics["count"]) if metrics["count"].is_integer() else metrics["count"],
            "total_duration_seconds": round(metrics["total_time_ns"] / 1_000_000_000, 6),
            "database_instances": sorted(context["database_instances"]),
            "db_cluster_identifiers": sorted(context["db_cluster_identifiers"]),
            "databases": sorted(context["databases"]),
            "tables": sorted(context["tables"]),
            "normalized_sql": normalized_sql,
            "sample_status": sample_status,
            "datadog_query_url": _datadog_query_url(config, spec, signature, args.scope, from_ms, to_ms),
        })

    source_status = "partial_success" if sample_errors else "success"
    return {
        "status": source_status,
        **coverage,
        "avg_candidates": len(candidates),
        "qualified_count": len(queries),
        "sample_errors": sample_errors,
        "sample_skipped": sample_skipped,
        "logical_request_count": request_count,
    }, queries


def _failure_signature(exc: DatadogCliError) -> tuple[int, str, str, str, str]:
    return (
        exc.code,
        exc.category,
        exc.error_code,
        exc.retry_class,
        exc.operation_state,
    )


def _aggregate_failures(failures: list[DatadogCliError]) -> DatadogCliError:
    if not failures:
        return ApiError("Slow SQL scan failed")
    first = failures[0]
    if all(_failure_signature(exc) == _failure_signature(first) for exc in failures[1:]):
        return first

    return DatadogCliError(
        "Slow SQL sources failed",
        EXIT_API_ERROR,
        category="api",
        error_code="multiple_source_failures",
        retry_class=(
            "safe" if all(exc.retry_class == "safe" for exc in failures) else "never"
        ),
        operation_state="not_started",
    )


def _execute_with_failures(
    args,
    config,
    *,
    client: DatadogClient | None = None,
    window: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], int, list[DatadogCliError]]:
    from_ms, to_ms = window or _validate_args(args)
    client = client or DatadogClient(config)
    specs = list(_SPECS.values()) if args.database_type == "all" else [_SPECS[args.database_type]]
    sources: dict[str, Any] = {}
    queries: list[dict[str, Any]] = []
    successful_sources = 0
    failures: list[DatadogCliError] = []
    for spec in specs:
        try:
            source, source_queries = _scan_database(client, config, spec, args, from_ms, to_ms)
            sources[spec.key] = source
            queries.extend(source_queries)
            successful_sources += 1
        except DatadogCliError as exc:
            sources[spec.key] = {"status": "failed", "error": exc.error_code}
            failures.append(exc)
        except Exception:
            exc = ApiError("Slow SQL source failed", error_code="unexpected_error")
            sources[spec.key] = {"status": "failed", "error": exc.error_code}
            failures.append(exc)

    queries.sort(key=lambda item: (-item["avg_duration_seconds"], item["query_signature"]))
    if successful_sources == 0:
        status = "failed"
        exit_code = _aggregate_failures(failures).code
    elif successful_sources < len(specs) or any(source["status"] != "success" for source in sources.values()):
        status = "partial_success"
        exit_code = 0
    else:
        status = "success"
        exit_code = 0
    result = {
        "status": status,
        "window": {
            "from": _iso_time(from_ms),
            "to": _iso_time(to_ms),
            "from_ms": from_ms,
            "to_ms": to_ms,
        },
        "criteria": {
            "scope": args.scope,
            "avg_duration_seconds_gt": args.min_avg_seconds,
            "count_gt": args.min_count,
            "top": args.top,
        },
        "sources": sources,
        "queries": queries,
        "query_count": len(queries),
    }
    return result, exit_code, failures


def execute(
    args,
    config,
    *,
    client: DatadogClient | None = None,
    window: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], int]:
    result, exit_code, _failures = _execute_with_failures(
        args,
        config,
        client=client,
        window=window,
    )
    return result, exit_code


def run(args, context: RuntimeContext) -> CommandResult:
    window = _validate_args(args)
    target = context.bind_target({
        "database_type": args.database_type,
        "scope": args.scope,
        "window": {
            "from": _iso_time(window[0]),
            "to": _iso_time(window[1]),
            "from_ms": window[0],
            "to_ms": window[1],
        },
    })
    result, exit_code, failures = _execute_with_failures(
        args,
        context.config,
        client=context.client,
        window=window,
    )
    if exit_code:
        exc = _aggregate_failures(failures)
        exc.domain_result = {
            "status": result["status"],
            "sources": result["sources"],
            "queries": result["queries"],
            "query_count": result["query_count"],
        }
        exc.domain_meta = {"criteria": result["criteria"]}
        raise exc
    return CommandResult(
        target=target,
        result={
            "status": result["status"],
            "sources": result["sources"],
            "queries": result["queries"],
            "query_count": result["query_count"],
        },
        meta={"criteria": result["criteria"]},
    )
