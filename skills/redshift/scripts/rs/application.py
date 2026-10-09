"""Typed application-service dispatch behind the channel-neutral CLI adapter."""
from __future__ import annotations

import argparse
import hashlib
import os
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog.identifiers import (
    parse_object_name,
    render_object_name,
)
from .catalog.builder import build_catalog
from .catalog.live import describe_object, list_databases, list_relations, list_schemas
from .catalog.search import search_catalog
from .catalog.snapshot import Catalog, load_catalog
from .config import output_directory
from .connectivity import BoundConnectivityPort, ConnectivityPort, RedshiftConnectivity
from .errors import Interrupted, SkillError, usage_error
from .models import CommandResult, InvocationState, QueryResult
from .output import publish_records, validate_output_target
from .query.execute import validate_statement_timeout
from .query.params import parse_params_json
from .recipes.appointment_timeline import APPOINTMENT_DATABASE, run_appointment_timeline
from .recipes.email_to_company import (
    ACCOUNT_DATABASE,
    BUSINESS_DATABASE,
    run_email_to_company,
)
from .recipes.membership_entitlement import MEMBERSHIP_DATABASE, run_membership_entitlement
from .recipes.refund_origin import ORDER_DATABASE, PAYMENT_DATABASE, run_refund_origin
from .recipes.registry import list_recipes


CatalogLoader = Callable[[str | Path], Catalog]


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "references" / "catalog.jsonl"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_catalog_artifact(
    output: str | Path,
    *,
    connectivity: ConnectivityPort,
    generated_at: datetime,
    max_age_days: int,
    domain_map: str | Path | None = None,
    timeout_ms: int | None = None,
) -> Catalog:
    """Build one catalog through the same Connectivity Module as live commands."""

    bound = connectivity.bind_catalog()
    timeout = validate_statement_timeout(
        timeout_ms
        if timeout_ms is not None
        else bound.default_statement_timeout_ms
    )
    source = bound.catalog_source(bound.default_database, timeout)
    manager = source if hasattr(source, "__enter__") else nullcontext(source)
    with manager as active_source:
        return build_catalog(
            output,
            active_source,
            generated_at=generated_at,
            max_age_days=max_age_days,
            domain_map=domain_map,
        )


def _load_optional_catalog(path: str | Path, loader: CatalogLoader) -> Catalog | None:
    try:
        return loader(path)
    except SkillError as exc:
        if exc.full_code not in {"catalog.unavailable", "catalog.invalid"}:
            raise
        return None


def _read_text(value: str | None, path: str | None, *, argument: str) -> str:
    if value is not None:
        return value
    try:
        return Path(path or "").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise usage_error("invalid_value", details={"argument": argument}) from exc


def _with_connection_database(
    error: SkillError,
    database: str,
    connection_meta: Mapping[str, Any] | None = None,
) -> SkillError:
    meta = dict(error.meta)
    meta["connectionDatabase"] = database
    meta.update(connection_meta or {})
    return SkillError(
        category=error.category,
        code=error.code,
        retry_class=error.retry_class,
        message=error.message,
        details=error.details,
        suggestion=error.suggestion,
        exit_code_override=error.exit_code_override,
        meta=meta,
        diagnostics=error.diagnostics,
    )


def _parameter_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unsupported"


def _start_diagnostics(
    state: InvocationState,
    *,
    command: str,
    database: str,
    sql: str,
    params: Mapping[str, Any],
) -> None:
    state.diagnostics.update(
        {
            "command": command,
            "connectionDatabase": database,
            "sqlSha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            "parameterNames": sorted(params),
            "parameterTypes": {
                name: _parameter_type(params[name]) for name in sorted(params)
            },
        }
    )


def _query_result(result: QueryResult, connection_meta: Mapping[str, Any]) -> CommandResult:
    return CommandResult(
        data={
            "columns": [column.to_payload() for column in result.columns],
            "records": result.records,
            "rowCount": result.row_count,
            "truncated": result.truncated,
        },
        meta={
            "elapsedMs": result.elapsed_ms,
            "statementTimeoutMs": result.statement_timeout_ms,
            "connectionDatabase": result.connection_database,
            **connection_meta,
        },
    )


def _handle_query(
    args: argparse.Namespace,
    state: InvocationState,
    *,
    environ: Mapping[str, str],
    connectivity: ConnectivityPort,
) -> CommandResult:
    sql = _read_text(args.sql, args.file, argument="--file")
    raw_params = (
        _read_text(args.params, args.params_file, argument="--params-file")
        if args.params_file
        else args.params
    )
    bound = connectivity.bind(getattr(args, "connection", None))
    database = args.database or bound.default_database
    try:
        params = parse_params_json(raw_params)
        timeout = (
            args.timeout_ms
            if args.timeout_ms is not None
            else bound.default_statement_timeout_ms
        )
        _start_diagnostics(
            state,
            command="query",
            database=database,
            sql=sql,
            params=params,
        )
        if args.format == "json":
            result = bound.query(
                database=database,
                sql=sql,
                params=params,
                limit=args.limit,
                statement_timeout_ms=timeout,
            )
            state.diagnostics.update(
                {"elapsedMs": result.elapsed_ms, "rowCount": result.row_count}
            )
            return _query_result(result, bound.public_meta(database))
        destination = output_directory(environ)
        validate_output_target(destination, args.output)
        with bound.stream_query(
            database=database,
            sql=sql,
            params=params,
            limit=args.limit,
            statement_timeout_ms=timeout,
        ) as result:
            output_ref = publish_records(
                output_dir=destination,
                final_name=args.output,
                fmt=args.format,
                columns=tuple(column.name for column in result.columns),
                records=result,
                state=state,
            )
        state.diagnostics.update(
            {"elapsedMs": result.elapsed_ms, "rowCount": result.row_count}
        )
        return CommandResult(
            data={
                "outputRef": output_ref,
                "format": args.format,
                "rowCount": result.row_count,
                "truncated": result.truncated,
            },
            meta={
                "elapsedMs": result.elapsed_ms,
                "statementTimeoutMs": result.statement_timeout_ms,
                "connectionDatabase": result.connection_database,
                **bound.public_meta(database),
            },
        )
    except Interrupted:
        raise
    except SkillError as exc:
        raise _with_connection_database(
            exc,
            database,
            bound.public_meta(database),
        ) from exc


def _handle_explain(
    args: argparse.Namespace,
    state: InvocationState,
    *,
    connectivity: ConnectivityPort,
) -> CommandResult:
    sql = _read_text(args.sql, args.file, argument="--file")
    raw_params = (
        _read_text(args.params, args.params_file, argument="--params-file")
        if args.params_file
        else args.params
    )
    bound = connectivity.bind(getattr(args, "connection", None))
    database = args.database or bound.default_database
    try:
        params = parse_params_json(raw_params)
        timeout = (
            args.timeout_ms
            if args.timeout_ms is not None
            else bound.default_statement_timeout_ms
        )
        _start_diagnostics(
            state,
            command="explain",
            database=database,
            sql=sql,
            params=params,
        )
        result = bound.explain(
            database=database,
            sql=sql,
            params=params,
            statement_timeout_ms=timeout,
        )
        state.diagnostics["elapsedMs"] = result.elapsed_ms
        return CommandResult(
            data={"plan": result.plan, "advisories": result.advisories},
            meta={
                "elapsedMs": result.elapsed_ms,
                "statementTimeoutMs": result.statement_timeout_ms,
                "connectionDatabase": result.connection_database,
                **bound.public_meta(database),
            },
        )
    except SkillError as exc:
        raise _with_connection_database(
            exc,
            database,
            bound.public_meta(database),
        ) from exc


def _handle_recipe(
    args: argparse.Namespace,
    state: InvocationState,
    *,
    connectivity: ConnectivityPort,
) -> CommandResult:
    if args.recipe_name == "list":
        return CommandResult(data=list_recipes())

    bound = connectivity.bind(getattr(args, "connection", None))

    if args.recipe_name == "email-to-company":
        required_databases = (
            args.account_db or ACCOUNT_DATABASE,
            args.biz_db or BUSINESS_DATABASE,
        )
    elif args.recipe_name == "appointment-timeline":
        required_databases = (APPOINTMENT_DATABASE,)
    elif args.recipe_name == "refund-origin":
        required_databases = (PAYMENT_DATABASE, ORDER_DATABASE)
    elif args.recipe_name == "membership-entitlement":
        required_databases = (MEMBERSHIP_DATABASE,)
    else:
        raise SkillError("internal", "command_load_failed", "never")

    def execute_stage(
        *,
        sql: str,
        params: Mapping[str, Any],
        database: str,
        limit: int,
        timeout_ms: int | None,
    ) -> QueryResult:
        timeout = (
            timeout_ms
            if timeout_ms is not None
            else bound.default_statement_timeout_ms
        )
        _start_diagnostics(
            state,
            command="recipe",
            database=database,
            sql=sql,
            params=params,
        )
        return bound.query(
            database=database,
            sql=sql,
            params=params,
            limit=limit,
            statement_timeout_ms=timeout,
        )

    try:
        source = bound.catalog_source(
            bound.default_database,
            bound.default_statement_timeout_ms,
        )
        live_rows = tuple(source.show_databases())
        if any(
            not isinstance(row, Mapping) or not isinstance(row.get("name"), str)
            for row in live_rows
        ):
            raise SkillError("metadata", "incomplete", "transient")
        visible_databases = {row["name"] for row in live_rows}
        missing_databases = sorted(set(required_databases) - visible_databases)
        if missing_databases:
            raise SkillError(
                "capability",
                "recipe_source_unavailable",
                "after_change",
                details={"databases": missing_databases},
            )
        if args.recipe_name == "email-to-company":
            result = run_email_to_company(
                execute_stage,
                email=args.email,
                account_database=args.account_db or ACCOUNT_DATABASE,
                business_database=args.biz_db or BUSINESS_DATABASE,
                timeout_ms=args.timeout_ms,
            )
        elif args.recipe_name == "appointment-timeline":
            result = run_appointment_timeline(
                execute_stage,
                appointment_id=args.appointment_id,
                timeout_ms=args.timeout_ms,
            )
        elif args.recipe_name == "refund-origin":
            result = run_refund_origin(
                execute_stage,
                refund_id=args.refund_id,
                timeout_ms=args.timeout_ms,
            )
        elif args.recipe_name == "membership-entitlement":
            result = run_membership_entitlement(
                execute_stage,
                membership_id=args.membership_id,
                subscription_id=args.subscription_id,
                timeout_ms=args.timeout_ms,
            )
        else:
            raise SkillError("internal", "command_load_failed", "never")
        return CommandResult(
            data=result.data,
            meta={**result.meta, **bound.public_meta(None)},
        )
    except SkillError as exc:
        database = state.diagnostics.get("connectionDatabase")
        selected_database = (
            database if isinstance(database, str) else bound.default_database
        )
        raise _with_connection_database(
            exc,
            selected_database,
            bound.public_meta(selected_database),
        ) from exc


def _handle_databases(
    args: argparse.Namespace,
    *,
    catalog_path: str | Path,
    catalog_loader: CatalogLoader,
    clock: Callable[[], datetime],
    connectivity: BoundConnectivityPort,
) -> CommandResult:
    database = connectivity.default_database
    timeout = connectivity.default_statement_timeout_ms
    try:
        source = connectivity.catalog_source(database, timeout)
        catalog = None
        if connectivity.owns_catalog and args.source_type is not None:
            catalog = catalog_loader(catalog_path)
        live_rows = tuple(source.show_databases())
        if connectivity.owns_catalog and args.source_type is None:
            catalog = _load_optional_catalog(catalog_path, catalog_loader)
        result = list_databases(
            lambda: live_rows,
            catalog=catalog,
            now=clock(),
            source_type=args.source_type,
        )
        return CommandResult(
            data=result["data"],
            meta={**result["meta"], **connectivity.public_meta(database)},
        )
    except SkillError as exc:
        raise _with_connection_database(
            exc,
            database,
            connectivity.public_meta(database),
        ) from exc


def _handle_search(
    args: argparse.Namespace,
    *,
    catalog_path: str | Path,
    catalog_loader: CatalogLoader,
    clock: Callable[[], datetime],
) -> CommandResult:
    catalog = catalog_loader(catalog_path)
    layers = tuple(args.layer.split(",")) if args.layer else None
    return CommandResult(
        data=search_catalog(
            catalog,
            text=args.text,
            now=clock(),
            database=args.database,
            source_type=args.source_type,
            schema=args.schema,
            layer=layers,
            domain=args.domain,
            kind=args.kind,
            include_hidden=args.include_hidden,
            limit=args.limit,
        )
    )


def _handle_schemas(
    args: argparse.Namespace,
    *,
    connectivity: ConnectivityPort,
) -> CommandResult:
    bound = connectivity.bind(getattr(args, "connection", None))
    target = args.database
    try:
        source = bound.live_metadata_source(
            bound.default_database,
            bound.default_statement_timeout_ms,
        )
        result = list_schemas(
            target,
            source,
            include_system=args.include_system,
            limit=args.limit,
        )
        return CommandResult(
            data=result["data"],
            meta={**result["meta"], **bound.public_meta(bound.default_database)},
        )
    except SkillError as exc:
        raise _with_connection_database(
            exc,
            bound.default_database,
            bound.public_meta(bound.default_database),
        ) from exc


def _handle_relations(
    args: argparse.Namespace,
    *,
    connectivity: ConnectivityPort,
) -> CommandResult:
    bound = connectivity.bind(getattr(args, "connection", None))
    try:
        source = bound.live_metadata_source(
            bound.default_database,
            bound.default_statement_timeout_ms,
        )
        result = list_relations(
            args.target,
            source,
            kind=args.kind,
            limit=args.limit,
        )
        return CommandResult(
            data=result["data"],
            meta={**result["meta"], **bound.public_meta(bound.default_database)},
        )
    except SkillError as exc:
        raise _with_connection_database(
            exc,
            bound.default_database,
            bound.public_meta(bound.default_database),
        ) from exc


def _catalog_relation(catalog: Catalog | None, object_name: str) -> Any | None:
    if catalog is None:
        return None
    return next(
        (relation for relation in catalog.relations if relation.object == object_name),
        None,
    )


def _database_is_incomplete(catalog: Catalog | None, database: str) -> bool:
    if catalog is None:
        return False
    return any(
        item["database"] == database
        for item in catalog.meta.coverage.failed_databases
    )


def _handle_describe(
    args: argparse.Namespace,
    state: InvocationState,
    *,
    catalog_path: str | Path,
    catalog_loader: CatalogLoader,
    connectivity: ConnectivityPort,
) -> CommandResult:
    database, schema, relation_name = parse_object_name(args.object)
    normalized_object = render_object_name(database, schema, relation_name)
    bound = connectivity.bind(getattr(args, "connection", None))
    timeout = (
        args.timeout_ms
        if args.timeout_ms is not None
        else bound.default_statement_timeout_ms
    )
    catalog = (
        _load_optional_catalog(catalog_path, catalog_loader)
        if bound.owns_catalog
        else None
    )
    source = bound.describe_source(database, timeout)
    try:
        data = describe_object(
            args.object,
            source,
            known_incomplete=_database_is_incomplete(catalog, database),
        )
    except SkillError as exc:
        if exc.full_code == "metadata.not_found":
            exc = SkillError(
                category=exc.category,
                code=exc.code,
                retry_class=exc.retry_class,
                message=exc.message,
                details={**exc.details, "object": normalized_object},
                suggestion="search_object",
                exit_code_override=exc.exit_code_override,
                meta=exc.meta,
                diagnostics=exc.diagnostics,
            )
        raise _with_connection_database(
            exc,
            database,
            bound.public_meta(database),
        ) from exc
    data["object"] = normalized_object
    enrichment = _catalog_relation(catalog, normalized_object)
    if enrichment is not None:
        data.update(
            {
                "sourceType": enrichment.source_type,
                "layer": enrichment.layer,
                "relationType": enrichment.relation_type,
                "statistics": {
                    "estimatedRows": None,
                    "sizeMb": None,
                    "sortKeys": [],
                    "distributionStyle": None,
                },
                "dbt": {
                    "description": enrichment.description,
                    "tags": list(enrichment.tags),
                    "dependsOn": list(enrichment.depends_on),
                },
            }
        )
    state.diagnostics["metadataFallbackSource"] = data["metadataSource"]
    return CommandResult(data=data, meta=bound.public_meta(database))


def dispatch(
    args: argparse.Namespace,
    state: InvocationState,
    *,
    environ: Mapping[str, str] | None = None,
    catalog_path: str | Path | None = None,
    catalog_loader: CatalogLoader = load_catalog,
    clock: Callable[[], datetime] = _utc_now,
    connectivity: ConnectivityPort | None = None,
) -> CommandResult:
    source = environ if environ is not None else os.environ
    manager = connectivity or RedshiftConnectivity(source)
    selected_catalog_path = catalog_path or _catalog_path()
    if args.command == "databases":
        bound = manager.bind(getattr(args, "connection", None))
        return _handle_databases(
            args,
            catalog_path=selected_catalog_path,
            catalog_loader=catalog_loader,
            clock=clock,
            connectivity=bound,
        )
    if args.command == "search":
        return _handle_search(
            args,
            catalog_path=selected_catalog_path,
            catalog_loader=catalog_loader,
            clock=clock,
        )
    if args.command == "schemas":
        return _handle_schemas(args, connectivity=manager)
    if args.command == "relations":
        return _handle_relations(args, connectivity=manager)
    if args.command == "describe":
        return _handle_describe(
            args,
            state,
            catalog_path=selected_catalog_path,
            catalog_loader=catalog_loader,
            connectivity=manager,
        )
    if args.command == "query":
        return _handle_query(
            args,
            state,
            environ=source,
            connectivity=manager,
        )
    if args.command == "explain":
        return _handle_explain(
            args,
            state,
            connectivity=manager,
        )
    if args.command == "recipe":
        return _handle_recipe(
            args,
            state,
            connectivity=manager,
        )
    if args.command == "doctor":
        if args.list_connections:
            return manager.list_connections()
        return manager.preflight(
            getattr(args, "connection", None),
            connect_live=args.connect,
        )
    raise SkillError("internal", "command_load_failed", "never")
