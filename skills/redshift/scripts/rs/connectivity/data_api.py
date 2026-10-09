"""Redshift Data API Adapter with a bounded readonly session lifecycle."""
from __future__ import annotations

import time
import uuid
import importlib.util
import random
from datetime import date, datetime, time as date_time
from decimal import Decimal, InvalidOperation
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ..errors import Interrupted, SkillError
from ..catalog.redshift import (
    RedshiftCatalogSource,
    RedshiftDescribeSource,
    RedshiftLiveMetadataSource,
)
from ..models import Column, QueryResult
from ..query.execute import _bounded_limit, validate_statement_timeout
from ..query.guard import validate_read_only_sql
from ..query.parameter_plan import DataApiParameterPlan, build_parameter_plan
from ..query.explain import ExplainResult, _build_advisories
from .aws import AwsResolver, aws_error_code, map_aws_error
from .doctor import probe_metadata_capabilities, run_adapter_doctor
from .model import ConnectionProfile


DATA_API_SQL_MAX_UTF8_BYTES = 200_000
SETUP_DEADLINE_SECONDS = 120
CLEANUP_DEADLINE_SECONDS = 60
RESULT_FETCH_DEADLINE_SECONDS = 60
MAX_POLL_INTERVAL_SECONDS = 5
PHASE_DISPATCH_SAFETY_MARGIN_SECONDS = 30
_TERMINAL = {"FINISHED", "FAILED", "ABORTED"}
_TYPE_NAMES = {
    "bool": "boolean",
    "boolean": "boolean",
    "int2": "smallint",
    "smallint": "smallint",
    "int4": "integer",
    "integer": "integer",
    "int8": "bigint",
    "bigint": "bigint",
    "float4": "real",
    "real": "real",
    "float8": "double precision",
    "double precision": "double precision",
    "decimal": "numeric",
    "numeric": "numeric",
    "char": "character",
    "character": "character",
    "varchar": "character varying",
    "character varying": "character varying",
    "text": "text",
    "date": "date",
    "time": "time without time zone",
    "timetz": "time with time zone",
    "timestamp": "timestamp without time zone",
    "timestamptz": "timestamp with time zone",
    "interval": "interval",
    "varbyte": "bytea",
    "super": "super",
}


@dataclass(frozen=True)
class _Statement:
    statement_id: str
    description: Mapping[str, Any]


class _StatementWaitFailure(Exception):
    def __init__(
        self,
        error: BaseException,
        execution_state: str,
        *,
        phase: str,
        session_id: str | None,
        terminal_status: str | None = None,
    ) -> None:
        super().__init__("statement wait failed")
        self.error = error
        self.execution_state = execution_state
        self.phase = phase
        self.session_id = session_id
        self.terminal_status = terminal_status


@dataclass(frozen=True)
class _Settlement:
    execution_state: str
    description: Mapping[str, Any] | None = None


@dataclass
class DataApiStreamingQuery:
    columns: tuple[Column, ...]
    connection_database: str
    statement_timeout_ms: int
    elapsed_ms: int
    _adapter: "DataApiAdapter"
    _statement_id: str
    _first_page: Mapping[str, Any]
    _result_deadline: float
    _limit: int
    row_count: int = 0
    truncated: bool = False

    def __iter__(self) -> Iterator[dict[str, Any]]:
        names = tuple(column.name for column in self.columns)
        page = self._first_page
        seen_tokens: set[str] = set()
        while True:
            for row in self._adapter._rows(page, self.columns):
                if self.row_count >= self._limit:
                    self.truncated = True
                    return
                self.row_count += 1
                yield dict(zip(names, row))
            token = page.get("NextToken")
            if not isinstance(token, str) or not token:
                return
            if token in seen_tokens:
                raise SkillError(
                    "query", "failed", "never", details={"stage": "result_fetch"}
                )
            if self.row_count >= self._limit:
                self.truncated = True
                return
            seen_tokens.add(token)
            started = self._adapter._monotonic()
            page = self._adapter._result_page(
                self._statement_id,
                token,
                deadline=self._result_deadline,
            )
            self.elapsed_ms += int((self._adapter._monotonic() - started) * 1000)


class _MetadataCursor:
    def __init__(
        self,
        adapter: "DataApiAdapter",
        database: str,
        statement_timeout_ms: int,
        row_limit: int = 100_000,
        overflow_policy: str = "raise",
    ) -> None:
        self._adapter = adapter
        self._database = database
        self._statement_timeout_ms = statement_timeout_ms
        self._row_limit = row_limit
        self._overflow_policy = overflow_policy
        self.description: tuple[tuple[str, str], ...] = ()
        self._rows: tuple[tuple[Any, ...], ...] = ()
        self._offset = 0
        self.metadata_overflow = False

    def __enter__(self) -> "_MetadataCursor":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def close(self) -> None:
        return None

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> None:
        try:
            columns, rows, overflow = self._adapter._metadata_records(
                database=self._database,
                sql=sql,
                params=params,
                statement_timeout_ms=self._statement_timeout_ms,
                row_limit=self._row_limit,
            )
        except Interrupted:
            raise
        except SkillError as exc:
            if exc.category in {"connection", "capability", "metadata"}:
                raise
            if exc.full_code == "query.timeout":
                raise SkillError("metadata", "timeout", "transient") from exc
            if exc.full_code == "query.submission_unknown":
                raise
            raise SkillError("metadata", "failed", "never") from exc
        if overflow and self._overflow_policy == "raise":
            raise SkillError("metadata", "limit_exceeded", "after_change")
        self.description = tuple((column.name, column.data_type) for column in columns)
        self._rows = rows
        self._offset = 0
        self.metadata_overflow = overflow

    def fetchmany(self, size: int) -> tuple[tuple[Any, ...], ...]:
        selected = self._rows[self._offset : self._offset + size]
        self._offset += len(selected)
        return selected

    def fetchall(self) -> tuple[tuple[Any, ...], ...]:
        return self._rows


class _MetadataConnection:
    def __init__(
        self,
        adapter: "DataApiAdapter",
        database: str,
        statement_timeout_ms: int,
    ) -> None:
        self._adapter = adapter
        self._database = database
        self._statement_timeout_ms = statement_timeout_ms
        self._row_limit = 100_000
        self._overflow_policy = "raise"
        self.notices: list[str] = []

    def configure_metadata(self, *, row_limit: int, overflow_policy: str) -> None:
        self._row_limit = row_limit
        self._overflow_policy = overflow_policy

    def cursor(self) -> _MetadataCursor:
        return _MetadataCursor(
            self._adapter,
            self._database,
            self._statement_timeout_ms,
            self._row_limit,
            self._overflow_policy,
        )


def _required_string(value: Any, *, stage: str) -> str:
    if not isinstance(value, str) or not value:
        raise SkillError(
            "query", "failed", "never", details={"stage": stage}
        )
    return value


def _field_value(field: Any) -> Any:
    if not isinstance(field, Mapping) or len(field) != 1:
        raise SkillError("query", "failed", "never", details={"stage": "result_fetch"})
    if field.get("isNull") is True:
        return None
    for key in ("stringValue", "longValue", "doubleValue", "booleanValue", "blobValue"):
        if key in field:
            return field[key]
    raise SkillError("query", "failed", "never", details={"stage": "result_fetch"})


def _coerce_value(value: Any, data_type: str) -> Any:
    if value is None:
        return None
    try:
        if data_type == "numeric" and not isinstance(value, Decimal):
            return Decimal(str(value))
        if data_type == "date" and isinstance(value, str):
            return date.fromisoformat(value)
        if data_type in {"time without time zone", "time with time zone"} and isinstance(
            value, str
        ):
            return date_time.fromisoformat(value)
        if data_type in {
            "timestamp without time zone",
            "timestamp with time zone",
        } and isinstance(value, str):
            return datetime.fromisoformat(value)
    except (InvalidOperation, ValueError) as exc:
        raise SkillError(
            "query", "failed", "never", details={"stage": "result_fetch"}
        ) from exc
    return value


def _columns(metadata: Any) -> tuple[Column, ...]:
    if not isinstance(metadata, list):
        raise SkillError("query", "failed", "never", details={"stage": "result_fetch"})
    columns: list[Column] = []
    for item in metadata:
        if not isinstance(item, Mapping):
            raise SkillError("query", "failed", "never", details={"stage": "result_fetch"})
        name = _required_string(item.get("name"), stage="result_fetch")
        raw_type = _required_string(item.get("typeName"), stage="result_fetch").casefold()
        columns.append(Column(name=name, data_type=_TYPE_NAMES.get(raw_type, f"type:{raw_type}")))
    duplicates = sorted(
        name
        for name, count in Counter(column.name for column in columns).items()
        if count > 1
    )
    if duplicates:
        raise SkillError(
            "query",
            "duplicate_output_column",
            "after_change",
            details={"columns": duplicates},
        )
    return tuple(columns)


class DataApiAdapter:
    def __init__(
        self,
        profile: ConnectionProfile,
        environ: Mapping[str, str],
        *,
        aws_resolver_factory: Any = AwsResolver,
        invocation_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float], float] = lambda interval: random.uniform(
            interval / 2, interval
        ),
        dependency_available: Callable[[], bool] = lambda: importlib.util.find_spec("boto3")
        is not None,
    ) -> None:
        self.profile = profile
        self._resolver = aws_resolver_factory(profile, environ)
        self.__client: Any | None = None
        self._environ = dict(environ)
        self._invocation_id = invocation_id_factory()
        self._monotonic = monotonic
        self._sleep = sleep
        self._jitter = jitter
        self._dependency_available = dependency_available
        self._phase_counter = 0

    @property
    def _client(self) -> Any:
        if self.__client is None:
            self.__client = self._resolver.data_api_client()
        return self.__client

    def _token(self, phase: str) -> str:
        self._phase_counter += 1
        return f"{self._invocation_id}-{self._phase_counter}-{phase}"

    def _validate_lifecycle(self, statement_timeout_ms: int) -> None:
        keepalive = self.profile.session_keepalive_seconds
        api_timeout = self.profile.aws_api_timeout_seconds
        if keepalive < (
            MAX_POLL_INTERVAL_SECONDS
            + 2 * api_timeout
            + PHASE_DISPATCH_SAFETY_MARGIN_SECONDS
        ):
            raise SkillError(
                "config",
                "invalid_combination",
                "after_change",
                details={"connection": self.profile.name},
            )
        total = (
            SETUP_DEADLINE_SECONDS
            + ((statement_timeout_ms + 999) // 1000)
            + CLEANUP_DEADLINE_SECONDS
            + PHASE_DISPATCH_SAFETY_MARGIN_SECONDS
        )
        if total > 86_400:
            raise SkillError(
                "config",
                "invalid_combination",
                "after_change",
                details={"connection": self.profile.name},
            )

    def _long_poll_seconds(self, remaining: float | None = None) -> int:
        network_bound = max(1, self.profile.aws_api_timeout_seconds // 2)
        if remaining is None:
            return min(30, network_bound)
        return max(1, min(30, network_bound, int(remaining)))

    def _wait(
        self,
        statement_id: str,
        *,
        deadline: float,
        stage: str,
    ) -> Mapping[str, Any]:
        interval = 0.25
        transient_failures = 0
        while True:
            now = self._monotonic()
            if deadline - now <= 0:
                raise SkillError(
                    "query", "timeout", "transient", details={"stage": stage}
                )
            try:
                description = self._client.describe_statement(
                    Id=statement_id,
                    WaitTimeSeconds=self._long_poll_seconds(deadline - now),
                )
            except Interrupted:
                raise
            except Exception as exc:
                mapped = map_aws_error(exc, stage=stage)
                if mapped.full_code not in {
                    "connection.endpoint_unreachable",
                    "connection.unavailable",
                }:
                    raise SkillError(
                        "query", "failed", "never", details={"stage": stage}
                    ) from exc
                transient_failures += 1
                if transient_failures >= 3 or self._monotonic() >= deadline:
                    raise SkillError(
                        "query", "timeout", "transient", details={"stage": stage}
                    ) from exc
                self._sleep(self._jitter(interval))
                interval = min(MAX_POLL_INTERVAL_SECONDS, interval * 2)
                continue
            if self._monotonic() >= deadline:
                raise SkillError(
                    "query", "timeout", "transient", details={"stage": stage}
                )
            status = description.get("Status") if isinstance(description, Mapping) else None
            if status in _TERMINAL:
                return description

    def _execute_statement(
        self,
        *,
        database: str,
        sql: str,
        phase: str,
        session_id: str | None,
        keepalive: int,
        parameters: tuple[dict[str, str], ...] = (),
        deadline: float,
    ) -> _Statement:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise SkillError(
                "query",
                "timeout",
                "transient",
                details={"stage": phase, "executionState": "stopped"},
            )
        request: dict[str, Any] = {
            "Sql": sql,
            "ClientToken": self._token(phase),
            "SessionKeepAliveSeconds": keepalive,
            "WaitTimeSeconds": self._long_poll_seconds(remaining),
        }
        if session_id is None:
            request.update(self._resolver.data_api_request(database))
        else:
            request["SessionId"] = session_id
        if parameters:
            request["Parameters"] = list(parameters)
        try:
            response = self._client.execute_statement(**request)
        except Interrupted as exc:
            interrupted = Interrupted(
                exc.signum,
                details={"stage": phase, "executionState": "may_be_running"},
            )
            raise _StatementWaitFailure(
                interrupted,
                "may_be_running",
                phase=phase,
                session_id=session_id,
            ) from exc
        except Exception as exc:
            mapped = map_aws_error(exc, stage=phase)
            if mapped.full_code in {
                "connection.endpoint_unreachable",
                "connection.unavailable",
            }:
                error = (
                    SkillError(
                        "query",
                        "submission_unknown",
                        "never",
                        details={
                            "stage": phase,
                            "executionState": "may_be_running",
                        },
                    )
                    if phase == "user"
                    else SkillError(
                        "query",
                        "failed",
                        "never",
                        details={
                            "stage": phase,
                            "executionState": "may_be_running",
                        },
                    )
                )
                raise _StatementWaitFailure(
                    error,
                    "may_be_running",
                    phase=phase,
                    session_id=session_id,
                ) from exc
            raise mapped from exc
        raw_statement_id = response.get("Id") if isinstance(response, Mapping) else None
        if not isinstance(raw_statement_id, str) or not raw_statement_id:
            error = (
                SkillError(
                    "query",
                    "submission_unknown",
                    "never",
                    details={"stage": phase, "executionState": "may_be_running"},
                )
                if phase == "user"
                else SkillError(
                    "query",
                    "failed",
                    "never",
                    details={"stage": phase, "executionState": "may_be_running"},
                )
            )
            raise _StatementWaitFailure(
                error,
                "may_be_running",
                phase=phase,
                session_id=session_id,
            )
        statement_id = raw_statement_id
        try:
            description = self._wait(
                statement_id,
                deadline=deadline,
                stage=phase,
            )
        except (Interrupted, SkillError) as exc:
            settlement = self._cancel_and_settle(statement_id)
            settled_session = session_id
            if settled_session is None and settlement.description is not None:
                candidate = settlement.description.get("SessionId")
                if isinstance(candidate, str) and candidate:
                    settled_session = candidate
            error: BaseException = exc
            if isinstance(exc, Interrupted):
                error = Interrupted(
                    exc.signum,
                    details={
                        **exc.details,
                        "stage": phase,
                        "executionState": settlement.execution_state,
                    },
                )
            elif isinstance(exc, SkillError):
                error = SkillError(
                    category=exc.category,
                    code=exc.code,
                    retry_class=exc.retry_class,
                    message=exc.message,
                    details={
                        **exc.details,
                        "executionState": settlement.execution_state,
                    },
                    suggestion=exc.suggestion,
                    exit_code_override=exc.exit_code_override,
                    meta=exc.meta,
                    diagnostics=exc.diagnostics,
                )
            raise _StatementWaitFailure(
                error,
                settlement.execution_state,
                phase=phase,
                session_id=settled_session,
                terminal_status=(
                    settlement.description.get("Status")
                    if settlement.description is not None
                    and isinstance(settlement.description.get("Status"), str)
                    else None
                ),
            ) from exc
        return _Statement(statement_id=statement_id, description=description)

    def _cancel_and_settle(self, statement_id: str) -> _Settlement:
        deadline = self._monotonic() + CLEANUP_DEADLINE_SECONDS
        try:
            self._client.cancel_statement(Id=statement_id)
        except Exception:
            return _Settlement("may_be_running")
        while True:
            now = self._monotonic()
            if deadline - now < 1:
                return _Settlement("may_be_running")
            try:
                description = self._client.describe_statement(
                    Id=statement_id,
                    WaitTimeSeconds=self._long_poll_seconds(deadline - now),
                )
            except Exception:
                return _Settlement("may_be_running")
            if isinstance(description, Mapping) and description.get("Status") in _TERMINAL:
                return _Settlement("stopped", description)

    def _first_result(
        self,
        statement: _Statement,
        *,
        stage: str,
        deadline: float,
    ) -> Mapping[str, Any]:
        if statement.description.get("HasResultSet") is not True:
            raise SkillError("query", "failed", "never", details={"stage": stage})
        try:
            return self._result_page(
                statement.statement_id,
                None,
                deadline=deadline,
            )
        except SkillError as exc:
            if stage == "result_fetch":
                raise
            raise SkillError("query", "failed", "never", details={"stage": stage}) from exc

    def _result_page(
        self,
        statement_id: str,
        token: str | None,
        *,
        deadline: float,
    ) -> Mapping[str, Any]:
        interval = 0.25
        transient_failures = 0
        while True:
            now = self._monotonic()
            if deadline - now < 1:
                raise SkillError(
                    "query", "failed", "never", details={"stage": "result_fetch"}
                )
            try:
                request: dict[str, Any] = {
                    "Id": statement_id,
                    "WaitTimeSeconds": self._long_poll_seconds(deadline - now),
                }
                if token is not None:
                    request["NextToken"] = token
                result = self._client.get_statement_result(**request)
            except Interrupted:
                raise
            except Exception as exc:
                mapped = map_aws_error(exc, stage="result_fetch")
                result_not_ready = aws_error_code(exc) == "ResourceNotFoundException"
                transient = mapped.full_code in {
                    "connection.endpoint_unreachable",
                    "connection.unavailable",
                }
                if not result_not_ready and not transient:
                    raise SkillError(
                        "query", "failed", "never", details={"stage": "result_fetch"}
                    ) from exc
                if transient:
                    transient_failures += 1
                    if transient_failures >= 3:
                        raise SkillError(
                            "query",
                            "failed",
                            "never",
                            details={"stage": "result_fetch"},
                        ) from exc
                self._sleep(self._jitter(interval))
                interval = min(MAX_POLL_INTERVAL_SECONDS, interval * 2)
                continue
            if not isinstance(result, Mapping):
                raise SkillError(
                    "query", "failed", "never", details={"stage": "result_fetch"}
                )
            if self._monotonic() >= deadline:
                raise SkillError(
                    "query", "failed", "never", details={"stage": "result_fetch"}
                )
            return result

    def _readonly_user_statement(
        self,
        *,
        database: str,
        sql: str,
        parameters: tuple[dict[str, str], ...],
        statement_timeout_ms: int,
    ) -> _Statement:
        self._validate_lifecycle(statement_timeout_ms)
        keepalive = self.profile.session_keepalive_seconds
        setup_deadline = self._monotonic() + SETUP_DEADLINE_SECONDS
        try:
            self._remaining_setup_budget(setup_deadline, stage="begin")
            begin = self._execute_statement(
                database=database,
                sql="BEGIN READ ONLY",
                phase="begin",
                session_id=None,
                keepalive=keepalive,
                deadline=setup_deadline,
            )
        except _StatementWaitFailure as failure:
            self._raise_wait_failure(failure, database, None)
        self._require_finished(begin, stage="begin")
        session_id = _required_string(begin.description.get("SessionId"), stage="begin")
        try:
            self._remaining_setup_budget(setup_deadline, stage="timeout")
            timeout_setup = self._execute_statement(
                database=database,
                sql=f"SET statement_timeout TO {statement_timeout_ms}",
                phase="timeout",
                session_id=session_id,
                keepalive=keepalive,
                deadline=setup_deadline,
            )
            self._require_finished(timeout_setup, stage="timeout")
            self._require_session(timeout_setup, session_id, stage="timeout")
            self._remaining_setup_budget(setup_deadline, stage="probe")
            probe = self._execute_statement(
                database=database,
                sql="SHOW transaction_read_only",
                phase="probe",
                session_id=session_id,
                keepalive=keepalive,
                deadline=setup_deadline,
            )
            self._require_finished(probe, stage="probe")
            self._require_session(probe, session_id, stage="probe")
            probe_result = self._first_result(
                probe,
                stage="probe",
                deadline=setup_deadline,
            )
            records = probe_result.get("Records")
            readonly = (
                isinstance(records, list)
                and len(records) == 1
                and isinstance(records[0], list)
                and len(records[0]) == 1
                and str(_field_value(records[0][0])).casefold()
                in {"on", "true", "t", "1"}
            )
            if not readonly:
                raise SkillError(
                    "capability", "readonly_unavailable", "after_change"
                )
        except _StatementWaitFailure as failure:
            self._raise_wait_failure(failure, database, session_id)
        except BaseException:
            self._rollback_best_effort(database, session_id)
            raise
        try:
            user = self._execute_statement(
                database=database,
                sql=sql,
                phase="user",
                session_id=session_id,
                keepalive=keepalive,
                parameters=parameters,
                deadline=self._monotonic()
                + max(1, (statement_timeout_ms + 999) // 1000),
            )
        except _StatementWaitFailure as failure:
            self._raise_wait_failure(failure, database, session_id)
        except SkillError as exc:
            if exc.full_code != "query.submission_unknown":
                self._rollback_best_effort(database, session_id)
            raise
        try:
            self._require_session(user, session_id, stage="user")
            if user.description.get("Status") != "FINISHED":
                raise SkillError(
                    "query", "failed", "never", details={"stage": "user"}
                )
        except BaseException:
            self._rollback_best_effort(database, session_id)
            raise
        self._rollback(database, session_id)
        return user

    def _remaining_setup_budget(self, deadline: float, *, stage: str) -> float:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise SkillError(
                "query",
                "timeout",
                "transient",
                details={"stage": stage, "executionState": "stopped"},
            )
        return remaining

    def _raise_wait_failure(
        self,
        failure: _StatementWaitFailure,
        database: str,
        fallback_session_id: str | None,
    ) -> None:
        session_id = failure.session_id or fallback_session_id
        if (
            failure.execution_state == "stopped"
            and session_id is not None
            and (
                failure.phase != "begin"
                or failure.terminal_status == "FINISHED"
            )
        ):
            self._rollback_best_effort(database, session_id)
        raise failure.error

    def _rollback(self, database: str, session_id: str) -> None:
        try:
            rollback = self._execute_statement(
                database=database,
                sql="ROLLBACK",
                phase="rollback",
                session_id=session_id,
                keepalive=0,
                deadline=self._monotonic() + CLEANUP_DEADLINE_SECONDS,
            )
            self._require_finished(rollback, stage="cleanup")
            self._require_session(rollback, session_id, stage="cleanup")
        except (SkillError, _StatementWaitFailure) as exc:
            raise SkillError(
                "query", "failed", "never", details={"stage": "cleanup"}
            ) from exc

    def _rollback_best_effort(self, database: str, session_id: str) -> None:
        try:
            self._rollback(database, session_id)
        except BaseException:
            return

    def _require_finished(self, statement: _Statement, *, stage: str) -> None:
        if statement.description.get("Status") != "FINISHED":
            raise SkillError(
                "query", "failed", "never", details={"stage": stage}
            )

    def _require_session(
        self,
        statement: _Statement,
        expected: str,
        *,
        stage: str,
    ) -> None:
        if statement.description.get("SessionId") != expected:
            raise SkillError(
                "query", "failed", "never", details={"stage": stage}
            )

    def _rows(
        self,
        result: Mapping[str, Any],
        columns: tuple[Column, ...],
    ) -> list[tuple[Any, ...]]:
        raw_records = result.get("Records", [])
        if not isinstance(raw_records, list):
            raise SkillError(
                "query", "failed", "never", details={"stage": "result_fetch"}
            )
        rows: list[tuple[Any, ...]] = []
        for record in raw_records:
            if not isinstance(record, list) or len(record) != len(columns):
                raise SkillError(
                    "query", "failed", "never", details={"stage": "result_fetch"}
                )
            rows.append(
                tuple(
                    _coerce_value(_field_value(field), column.data_type)
                    for field, column in zip(record, columns)
                )
            )
        return rows

    def _metadata_records(
        self,
        *,
        database: str,
        sql: str,
        params: Mapping[str, Any] | None,
        statement_timeout_ms: int,
        row_limit: int,
    ) -> tuple[tuple[Column, ...], tuple[tuple[Any, ...], ...], bool]:
        rendered = build_parameter_plan(sql, params).for_data_api()
        if len(rendered.sql.encode("utf-8")) > DATA_API_SQL_MAX_UTF8_BYTES:
            raise SkillError("metadata", "incomplete", "transient")
        user = self._readonly_user_statement(
            database=database,
            sql=rendered.sql,
            parameters=rendered.parameters,
            statement_timeout_ms=statement_timeout_ms,
        )
        result_deadline = self._monotonic() + RESULT_FETCH_DEADLINE_SECONDS
        page = self._first_result(
            user,
            stage="result_fetch",
            deadline=result_deadline,
        )
        columns = _columns(page.get("ColumnMetadata"))
        rows: list[tuple[Any, ...]] = []
        seen_tokens: set[str] = set()
        if row_limit <= 0:
            raise SkillError("metadata", "limit_exceeded", "after_change")
        overflow = False
        while True:
            page_rows = self._rows(page, columns)
            remaining = row_limit - len(rows)
            if len(page_rows) > remaining:
                rows.extend(page_rows[:remaining])
                overflow = True
                break
            rows.extend(page_rows)
            token = page.get("NextToken")
            if not isinstance(token, str) or not token:
                break
            if token in seen_tokens:
                raise SkillError("metadata", "incomplete", "transient")
            seen_tokens.add(token)
            page = self._result_page(
                user.statement_id,
                token,
                deadline=result_deadline,
            )
        return columns, tuple(rows), overflow

    def query(
        self,
        *,
        database: str,
        sql: str,
        params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        statement_timeout_ms: int = 30_000,
    ) -> QueryResult:
        timeout = validate_statement_timeout(statement_timeout_ms)
        bounded_limit = _bounded_limit(limit, "json")
        readonly_sql = validate_read_only_sql(sql)
        rendered: DataApiParameterPlan = build_parameter_plan(
            readonly_sql, params
        ).for_data_api()
        final_sql = (
            "SELECT * FROM (\n"
            f"{rendered.sql}\n"
            f") AS _moego_result LIMIT {bounded_limit + 1}"
        )
        if len(final_sql.encode("utf-8")) > DATA_API_SQL_MAX_UTF8_BYTES:
            raise SkillError(
                "capability", "transport_unavailable", "after_change"
            )
        started = self._monotonic()
        user = self._readonly_user_statement(
            database=database,
            sql=final_sql,
            parameters=rendered.parameters,
            statement_timeout_ms=timeout,
        )
        result_deadline = self._monotonic() + RESULT_FETCH_DEADLINE_SECONDS
        first = self._first_result(
            user,
            stage="result_fetch",
            deadline=result_deadline,
        )
        columns = _columns(first.get("ColumnMetadata"))
        rows = self._rows(first, columns)
        token = first.get("NextToken")
        seen_tokens: set[str] = set()
        while isinstance(token, str) and token and len(rows) <= bounded_limit:
            if token in seen_tokens:
                raise SkillError(
                    "query", "failed", "never", details={"stage": "result_fetch"}
                )
            seen_tokens.add(token)
            page = self._result_page(
                user.statement_id,
                token,
                deadline=result_deadline,
            )
            rows.extend(self._rows(page, columns))
            token = page.get("NextToken") if isinstance(page, Mapping) else None
        truncated = len(rows) > bounded_limit or bool(token)
        visible = rows[:bounded_limit]
        names = tuple(column.name for column in columns)
        records = tuple(dict(zip(names, row)) for row in visible)
        return QueryResult(
            columns=columns,
            records=records,
            row_count=len(records),
            truncated=truncated,
            elapsed_ms=int((self._monotonic() - started) * 1000),
            connection_database=database,
            statement_timeout_ms=timeout,
        )

    @contextmanager
    def stream_query(
        self,
        *,
        database: str,
        sql: str,
        params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        statement_timeout_ms: int = 30_000,
    ) -> Iterator[DataApiStreamingQuery]:
        timeout = validate_statement_timeout(statement_timeout_ms)
        bounded_limit = _bounded_limit(limit, "ndjson")
        readonly_sql = validate_read_only_sql(sql)
        rendered = build_parameter_plan(readonly_sql, params).for_data_api()
        final_sql = (
            "SELECT * FROM (\n"
            f"{rendered.sql}\n"
            f") AS _moego_result LIMIT {bounded_limit + 1}"
        )
        if len(final_sql.encode("utf-8")) > DATA_API_SQL_MAX_UTF8_BYTES:
            raise SkillError(
                "capability", "transport_unavailable", "after_change"
            )
        started = self._monotonic()
        user = self._readonly_user_statement(
            database=database,
            sql=final_sql,
            parameters=rendered.parameters,
            statement_timeout_ms=timeout,
        )
        result_deadline = self._monotonic() + RESULT_FETCH_DEADLINE_SECONDS
        first = self._first_result(
            user,
            stage="result_fetch",
            deadline=result_deadline,
        )
        stream = DataApiStreamingQuery(
            columns=_columns(first.get("ColumnMetadata")),
            connection_database=database,
            statement_timeout_ms=timeout,
            elapsed_ms=int((self._monotonic() - started) * 1000),
            _adapter=self,
            _statement_id=user.statement_id,
            _first_page=first,
            _result_deadline=result_deadline,
            _limit=bounded_limit,
        )
        yield stream

    def explain(
        self,
        *,
        database: str,
        sql: str,
        params: Mapping[str, Any] | None = None,
        statement_timeout_ms: int = 30_000,
    ) -> ExplainResult:
        timeout = validate_statement_timeout(statement_timeout_ms)
        readonly_sql = validate_read_only_sql(sql)
        rendered = build_parameter_plan(readonly_sql, params).for_data_api()
        final_sql = f"EXPLAIN\n{rendered.sql}"
        if len(final_sql.encode("utf-8")) > DATA_API_SQL_MAX_UTF8_BYTES:
            raise SkillError(
                "capability", "transport_unavailable", "after_change"
            )
        started = self._monotonic()
        user = self._readonly_user_statement(
            database=database,
            sql=final_sql,
            parameters=rendered.parameters,
            statement_timeout_ms=timeout,
        )
        result_deadline = self._monotonic() + RESULT_FETCH_DEADLINE_SECONDS
        page = self._first_result(
            user,
            stage="result_fetch",
            deadline=result_deadline,
        )
        columns = _columns(page.get("ColumnMetadata"))
        if len(columns) != 1:
            raise SkillError(
                "query", "failed", "never", details={"stage": "result_fetch"}
            )
        plan: list[str] = []
        seen_tokens: set[str] = set()
        while True:
            plan.extend(str(row[0]) for row in self._rows(page, columns))
            token = page.get("NextToken")
            if not isinstance(token, str) or not token:
                break
            if token in seen_tokens:
                raise SkillError(
                    "query", "failed", "never", details={"stage": "result_fetch"}
                )
            seen_tokens.add(token)
            page = self._result_page(
                user.statement_id,
                token,
                deadline=result_deadline,
            )
        try:
            advisories = _build_advisories(readonly_sql)
        except Exception:
            advisories = ()
        return ExplainResult(
            plan=tuple(plan),
            advisories=advisories,
            elapsed_ms=int((self._monotonic() - started) * 1000),
            connection_database=database,
            statement_timeout_ms=timeout,
        )

    @contextmanager
    def _metadata_connection(
        self,
        *,
        database: str,
        statement_timeout_ms: int,
    ) -> Iterator[_MetadataConnection]:
        yield _MetadataConnection(self, database, statement_timeout_ms)

    def catalog_source(self, database: str, timeout: int) -> RedshiftCatalogSource:
        return RedshiftCatalogSource(
            control_database=database,
            statement_timeout_ms=timeout,
            connection_factory=self._metadata_connection,
        )

    def describe_source(self, database: str, timeout: int) -> RedshiftDescribeSource:
        return RedshiftDescribeSource(
            control_database=database,
            statement_timeout_ms=timeout,
            connection_factory=self._metadata_connection,
        )

    def live_metadata_source(
        self, database: str, timeout: int
    ) -> RedshiftLiveMetadataSource:
        return RedshiftLiveMetadataSource(
            control_database=database,
            statement_timeout_ms=timeout,
            connection_factory=self._metadata_connection,
        )

    def _live_probe(self) -> Mapping[str, Any]:
        try:
            self.query(
                database=self.profile.database,
                sql="SELECT 1 AS value",
                params={},
                limit=1,
                statement_timeout_ms=min(self.profile.statement_timeout_ms, 30_000),
            )
        except SkillError as exc:
            return {
                "connectivity": "unavailable",
                "readonly": False,
                "code": exc.full_code,
            }
        return probe_metadata_capabilities(
            {
            "connectivity": "available",
            "readonly": True,
            "showDatabases": "not_checked",
            "crossDatabaseRead": "not_checked",
            },
            database=self.profile.database,
            source=self.catalog_source(
                self.profile.database,
                min(self.profile.statement_timeout_ms, 30_000),
            ),
            execute_query=self.query,
            statement_timeout_ms=min(self.profile.statement_timeout_ms, 30_000),
        )

    def preflight(self, *, connect_live: bool):
        def static_config_check() -> None:
            self._validate_lifecycle(self.profile.statement_timeout_ms)
            if self.profile.authentication.mode == "secret":
                self._resolver.secret_arn()

        return run_adapter_doctor(
            environ=self._environ,
            dependency_name="boto3",
            dependency_available=self._dependency_available,
            static_config_check=static_config_check,
            connect_live=connect_live,
            live_probe=self._live_probe,
        )
