"""JSON-only command-line adapter for the nine public Redshift commands."""
from __future__ import annotations

import argparse
import difflib
import io
import os
import signal
import sys
from collections.abc import Callable, Mapping
from typing import Any, TextIO

from .catalog.identifiers import parse_database_name, parse_database_schema_name
from .config import load_dotenv, output_directory
from .connectivity.registry import CONNECTION_NAME
from .contract import COMMAND_SPECS, all_leaf_options, command_names, commands_for_option
from .errors import Interrupted, SkillError, output_error, usage_error
from .models import CommandResult, InvocationState
from .output import (
    error_envelope,
    success_envelope,
    validate_inline_json_payload,
    validate_output_target,
    write_json,
)


Dispatcher = Callable[[argparse.Namespace, InvocationState], CommandResult]
_DIAGNOSTIC_FIELDS = {
    "command",
    "connectionDatabase",
    "sourceType",
    "sqlSha256",
    "parameterNames",
    "parameterTypes",
    "elapsedMs",
    "rowCount",
    "sqlState",
    "metadataFallbackSource",
    "connectionStage",
    "driverErrorType",
    "connectTimedOut",
    "passwordRejected",
    "tlsVerificationFailed",
}
_LAYERS = {"raw", "ods", "dwd", "dws", "ads", "dim", "audit", "tmp", "unknown"}
_LIVE_METADATA_MAX_LIMIT = 10_000


class _ParseFailure(Exception):
    def __init__(self, message: str) -> None:
        super().__init__("parser failure")
        self.parser_message = message


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ParseFailure(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="redshift",
        description="MoeGo read-only Redshift data access",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for spec in COMMAND_SPECS:
        leaf = subparsers.add_parser(
            spec.name,
            help=spec.summary,
            description=spec.summary,
            allow_abbrev=False,
        )
        spec.configure_args(leaf)
    return parser


def _identify_command(argv: list[str]) -> str | None:
    if not argv:
        raise usage_error("missing_command")
    first = argv[0]
    if first in {"-h", "--help"}:
        return None
    if first in command_names():
        return first
    if first in all_leaf_options():
        raise usage_error(
            "option_scope",
            details={"option": first, "commands": list(commands_for_option(first))},
        )
    if first.startswith("-"):
        raise usage_error("unknown_option", details={"option": first})
    suggestions = difflib.get_close_matches(first, command_names(), n=3, cutoff=0.5)
    details = {"suggestions": suggestions} if suggestions else {}
    raise usage_error("unknown_command", details=details)


def _usage_from_parser(message: str) -> SkillError:
    lowered = message.lower()
    if "required" in lowered or "expected one argument" in lowered:
        return usage_error("missing_argument")
    if "not allowed with argument" in lowered:
        return usage_error("invalid_combination")
    if "unrecognized arguments" in lowered:
        option = next(
            (token for token in message.split() if token.startswith("-") and token != "-"),
            None,
        )
        details = {"option": option.rstrip(":")} if option else {}
        return usage_error("unknown_option", details=details)
    return usage_error("invalid_value")


def _positive(value: int | None, argument: str) -> None:
    if value is not None and value <= 0:
        raise usage_error("invalid_value", details={"argument": argument})


def _validate_request(
    args: argparse.Namespace,
) -> None:
    command = args.command
    connection_name = getattr(args, "connection", None)
    if connection_name is not None and not CONNECTION_NAME.fullmatch(connection_name):
        raise usage_error("invalid_value", details={"argument": "--connection"})
    if command == "query":
        if args.database is not None:
            parse_database_name(args.database)
        _positive(args.limit, "--limit")
        _positive(args.timeout_ms, "--timeout-ms")
        maximum = 200 if args.format == "json" else 100_000
        if args.limit > maximum:
            raise SkillError(
                category="query",
                code="limit_out_of_range",
                retry_class="after_change",
                details={"maximum": maximum},
            )
        if args.format in {"csv", "ndjson"} and not args.output:
            raise usage_error("missing_argument", details={"argument": "--output"})
        if args.format == "json" and args.output is not None:
            raise usage_error(
                "invalid_combination",
                details={"arguments": ["--format json", "--output"]},
            )
    elif command == "explain":
        if args.database is not None:
            parse_database_name(args.database)
        _positive(args.timeout_ms, "--timeout-ms")
    elif command == "describe":
        _positive(args.timeout_ms, "--timeout-ms")
    elif command in {"schemas", "relations"}:
        if command == "schemas":
            parse_database_name(args.database)
        else:
            parse_database_schema_name(args.target)
        _positive(args.limit, "--limit")
        if args.limit > _LIVE_METADATA_MAX_LIMIT:
            raise usage_error(
                "invalid_value",
                details={"argument": "--limit", "maximum": _LIVE_METADATA_MAX_LIMIT},
            )
    elif command == "search":
        _positive(args.limit, "--limit")
        if args.layer is not None:
            layers = args.layer.split(",")
            if not layers or any(layer not in _LAYERS for layer in layers):
                raise usage_error(
                    "invalid_value",
                    details={"argument": "--layer"},
                )
    elif command == "recipe":
        _positive(args.timeout_ms, "--timeout-ms")
        if args.recipe_name == "list" and args.connection is not None:
            raise usage_error(
                "invalid_combination",
                details={"arguments": ["recipe list", "--connection"]},
            )
        for name, value in (
            ("--appointment-id", args.appointment_id),
            ("--refund-id", args.refund_id),
            ("--membership-id", args.membership_id),
            ("--subscription-id", args.subscription_id),
        ):
            _positive(value, name)
        values = {
            "email": args.email,
            "account_db": args.account_db,
            "biz_db": args.biz_db,
            "appointment_id": args.appointment_id,
            "refund_id": args.refund_id,
            "membership_id": args.membership_id,
            "subscription_id": args.subscription_id,
        }
        allowed = {
            "list": set(),
            "email-to-company": {"email", "account_db", "biz_db"},
            "appointment-timeline": {"appointment_id"},
            "refund-origin": {"refund_id"},
            "membership-entitlement": {"membership_id", "subscription_id"},
        }[args.recipe_name]
        if any(value is not None and name not in allowed for name, value in values.items()):
            raise usage_error("invalid_combination")
        required = {
            "email-to-company": ("email",),
            "appointment-timeline": ("appointment_id",),
            "refund-origin": ("refund_id",),
        }
        missing = [name for name in required.get(args.recipe_name, ()) if values[name] is None]
        if missing:
            raise usage_error(
                "missing_argument",
                details={"argument": "--" + missing[0].replace("_", "-")},
            )
        if args.recipe_name == "membership-entitlement":
            identifiers = (args.membership_id, args.subscription_id)
            if all(value is None for value in identifiers):
                raise usage_error(
                    "missing_argument",
                    details={"argument": "--membership-id|--subscription-id"},
                )
            if all(value is not None for value in identifiers):
                raise usage_error("invalid_combination")
    elif command == "doctor":
        if args.list_connections and args.connect:
            raise usage_error(
                "invalid_combination",
                details={"arguments": ["--list-connections", "--connect"]},
            )
        if args.list_connections and args.connection is not None:
            raise usage_error(
                "invalid_combination",
                details={"arguments": ["--list-connections", "--connection"]},
            )


def _validate_environment_request(
    args: argparse.Namespace,
    environ: Mapping[str, str],
) -> None:
    if args.command == "query" and args.output is not None:
        destination = output_directory(environ)
        validate_output_target(destination, args.output)


def _default_dispatch(args: argparse.Namespace, state: InvocationState) -> CommandResult:
    try:
        from .application import dispatch
    except ImportError as exc:
        raise SkillError(
            category="internal",
            code="command_load_failed",
            retry_class="never",
        ) from exc
    return dispatch(args, state)


def _signal_handler(signum: int, _frame: Any) -> None:
    raise Interrupted(signum)


def _install_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, _signal_handler)
    return previous


def _restore_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _emit_json(stream: TextIO, payload: Any) -> None:
    """Serialize first so the public stream receives one complete JSON line write."""

    rendered = io.StringIO()
    write_json(rendered, payload)
    stream.write(rendered.getvalue())
    stream.flush()


def main(
    argv: list[str] | None = None,
    *,
    dispatcher: Dispatcher | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
    install_signal_handlers: bool = True,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    output_stream = stdout if stdout is not None else sys.stdout
    diagnostics_stream = stderr if stderr is not None else sys.stderr
    environment = environ if environ is not None else os.environ
    state = InvocationState()
    command: str | None = None
    previous_handlers: dict[int, Any] = {}
    parsed_args: argparse.Namespace | None = None

    if install_signal_handlers:
        previous_handlers = _install_handlers()
    try:
        try:
            command = _identify_command(arguments)
            try:
                args = build_parser().parse_args(arguments)
                parsed_args = args
            except _ParseFailure as exc:
                raise _usage_from_parser(exc.parser_message) from exc
            _validate_request(args)
            offline = args.command == "search" or (
                args.command == "recipe" and args.recipe_name == "list"
            )
            if environ is None and not offline:
                load_dotenv(os.environ)
            _validate_environment_request(args, environment)
            result = (dispatcher or _default_dispatch)(args, state)
            state.diagnostics.update(result.diagnostics)
            payload = success_envelope(command or args.command, result.data, result.meta)
            if args.command == "query" and args.format == "json":
                validate_inline_json_payload(payload)
            exit_code = 0
        except Interrupted as exc:
            interrupted = Interrupted(
                exc.signum,
                {**exc.details, **state.interruption_details()},
            )
            payload = error_envelope(command, interrupted)
            exit_code = interrupted.exit_code
        except SkillError as exc:
            state.diagnostics.update({
                key: value for key, value in exc.diagnostics.items()
                if key in _DIAGNOSTIC_FIELDS and key != "sqlState"
            })
            sqlstate = exc.diagnostics.get("sqlState")
            if (
                isinstance(sqlstate, str)
                and len(sqlstate) == 5
                and sqlstate.isascii()
                and sqlstate.isalnum()
                and sqlstate == sqlstate.upper()
            ):
                state.diagnostics["sqlState"] = sqlstate
            if (
                state.artifact_state in {"final_link_created", "durable_published"}
                and exc.category == "output"
                and exc.code != "publish_unknown"
            ):
                exc = output_error("publish_unknown")
            payload = error_envelope(command, exc)
            exit_code = exc.exit_code
        except SystemExit as exc:
            if int(exc.code or 0) == 0:
                return 0
            failure = usage_error("invalid_value")
            payload = error_envelope(command, failure)
            exit_code = failure.exit_code
        except Exception:
            failure = SkillError(
                category="internal",
                code="unexpected",
                retry_class="never",
            )
            payload = error_envelope(command, failure)
            exit_code = failure.exit_code

        if parsed_args is not None and getattr(parsed_args, "debug", False):
            diagnostic = {
                "schemaVersion": 1,
                "kind": "diagnostic",
                **{
                    key: state.diagnostics[key]
                    for key in sorted(_DIAGNOSTIC_FIELDS)
                    if key in state.diagnostics
                },
            }
            try:
                _emit_json(diagnostics_stream, diagnostic)
            except Interrupted as exc:
                interrupted = Interrupted(
                    exc.signum,
                    {**exc.details, **state.interruption_details()},
                )
                payload = error_envelope(command, interrupted)
                exit_code = interrupted.exit_code
            except Exception:
                pass

        try:
            _emit_json(output_stream, payload)
        except Interrupted as exc:
            interrupted = Interrupted(
                exc.signum,
                {**exc.details, **state.interruption_details()},
            )
            interrupted_payload = error_envelope(command, interrupted)
            try:
                # One bounded retry avoids recursive output if another signal lands.
                _emit_json(output_stream, interrupted_payload)
            except BaseException:
                return 8
            return interrupted.exit_code
        except Exception:
            # A broken stdout cannot safely carry a second JSON envelope.
            try:
                diagnostics_stream.flush()
            except Exception:
                pass
            return 8
        return exit_code
    finally:
        if previous_handlers:
            _restore_handlers(previous_handlers)
