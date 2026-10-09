"""Strict-readonly psycopg2 adapter and stable external error mapping."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from .errors import Interrupted, SkillError, config_error


@dataclass(frozen=True)
class ConnectionConfig:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    database: str
    sslmode: str
    connect_timeout: int
    statement_timeout_ms: int
    sslrootcert: str | None = None


def _psycopg2() -> Any:
    try:
        import psycopg2
    except ImportError as exc:
        raise config_error("dependency_missing", key="psycopg2") from exc
    return psycopg2


def _connection_error(exc: BaseException) -> SkillError:
    code = getattr(exc, "pgcode", None)
    if code in {"28P01", "28000"}:
        stable = "auth_failed"
        retry = "after_change"
    elif code == "3D000":
        stable = "database_not_found"
        retry = "after_change"
    elif code in {"57014", "08000", "08001", "08003", "08006", "57P01"}:
        stable = "timeout" if code == "57014" else "unavailable"
        retry = "transient"
    else:
        stable = "unavailable"
        retry = "transient"
    return SkillError(
        category="connection", code=stable, retry_class=retry,
        suggestion="verify_database_credentials" if stable == "auth_failed" else None,
    )


def _open_connection(config: ConnectionConfig) -> Any:
    driver = _psycopg2()
    parameters = {
        "host": config.host,
        "port": config.port,
        "user": config.username,
        "password": config.password,
        "dbname": config.database,
        "sslmode": config.sslmode,
        "connect_timeout": config.connect_timeout,
        "application_name": "moego-redshift-skill",
    }
    if config.sslrootcert is not None:
        parameters["sslrootcert"] = config.sslrootcert
    try:
        return driver.connect(**parameters)
    except SkillError:
        raise
    except Exception as exc:
        failure = _connection_error(exc)
        # Only fixed libpq phrases become opt-in diagnostic flags. Never retain
        # the message, infer SQLSTATE from it, or change the public error code.
        message = str(exc).casefold()
        for value in (config.password, config.username, config.host, config.database):
            if value:
                message = message.replace(value.casefold(), "[redacted]")
        error_type = type(exc).__name__
        diagnostics = {
            "connectionStage": "connect",
            "driverErrorType": error_type
            if error_type in {
                "OperationalError", "InterfaceError", "DatabaseError", "Error",
                "ValueError", "TypeError", "OSError",
            } else "other",
            "connectTimedOut": (
                "timeout expired" in message or "connection timed out" in message
            ),
            "passwordRejected": "password authentication failed" in message,
            "tlsVerificationFailed": "certificate verify failed" in message,
        }
        sqlstate = getattr(exc, "pgcode", None)
        if (
            isinstance(sqlstate, str) and len(sqlstate) == 5
            and sqlstate.isascii() and sqlstate.isalnum()
            and sqlstate == sqlstate.upper()
        ):
            diagnostics["sqlState"] = sqlstate
        failure.diagnostics = diagnostics
        raise failure from exc


def _cancel_best_effort(conn: Any) -> None:
    cancel = getattr(conn, "cancel", None)
    if not callable(cancel):
        return
    try:
        cancel()
    except Exception:
        pass


@contextmanager
def connect_config(config: ConnectionConfig) -> Iterator[Any]:
    conn = _open_connection(config)
    primary_error: BaseException | None = None

    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cursor:
            cursor.execute("SET statement_timeout TO %s", (config.statement_timeout_ms,))
        yield conn
    except Interrupted as exc:
        primary_error = exc
        _cancel_best_effort(conn)
        raise
    except SkillError as exc:
        primary_error = exc
        if exc.full_code == "query.timeout":
            _cancel_best_effort(conn)
        raise
    except Exception as exc:
        primary_error = exc
        raise _connection_error(exc) from exc
    except BaseException as exc:
        primary_error = exc
        if isinstance(exc, Interrupted) or (
            isinstance(exc, SkillError) and exc.full_code == "query.timeout"
        ):
            _cancel_best_effort(conn)
        raise
    finally:
        try:
            conn.close()
        except Interrupted:
            if primary_error is None:
                raise
        except Exception:
            pass


@contextmanager
def connect_streaming_config(config: ConnectionConfig) -> Iterator[Any]:
    """Open a readonly transaction suitable for a server-side cursor."""

    conn = _open_connection(config)
    primary_error: BaseException | None = None

    try:
        try:
            conn.set_session(readonly=True, autocommit=False)
            cursor = conn.cursor()
            setup_error: BaseException | None = None
            try:
                cursor.execute(
                    "SET statement_timeout TO %s", (config.statement_timeout_ms,)
                )
            except BaseException as exc:
                setup_error = exc
                raise
            finally:
                try:
                    cursor.close()
                except Interrupted:
                    if setup_error is None:
                        raise
                except Exception:
                    pass
        except SkillError:
            raise
        except Exception as exc:
            raise _connection_error(exc) from exc
        yield conn
    except BaseException as exc:
        primary_error = exc
        if isinstance(exc, Interrupted) or (
            isinstance(exc, SkillError) and exc.full_code == "query.timeout"
        ):
            _cancel_best_effort(conn)
        raise
    finally:
        cleanup_interrupted: Interrupted | None = None
        try:
            conn.rollback()
        except Interrupted as exc:
            cleanup_interrupted = exc
        except Exception:
            pass
        try:
            conn.close()
        except Interrupted as exc:
            if cleanup_interrupted is None:
                cleanup_interrupted = exc
        except Exception:
            pass
        if cleanup_interrupted is not None and primary_error is None:
            raise cleanup_interrupted
