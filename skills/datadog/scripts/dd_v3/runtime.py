"""Composition root and the only stdout renderer for the Datadog CLI."""
from __future__ import annotations

import argparse
import signal
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from dd_v3.config import Config, load_config
from dd_v3.errors import (
    ApiError,
    DatadogCliError,
    EXIT_API_ERROR,
    UsageError,
    WriteOutcomeUnknownError,
)
from dd_v3.formatter import error as error_envelope
from dd_v3.formatter import render, success

READ = "READ"
PREVIEWABLE_W2 = "PREVIEWABLE_W2"


@dataclass(frozen=True)
class CommandResult:
    """A command result before the runtime adds envelope fields."""

    target: Any
    result: Any
    meta: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class RuntimeState:
    """Tracks the one allowed write attempt for one CLI invocation."""

    operation_state: str = "not_started"
    write_attempts: int = 0
    write_authorized: bool = False
    verification_pending: bool = False
    known_target: Any = None

    def bind_target(self, target: Any) -> Any:
        self.known_target = target
        return target

    def authorize_write(self) -> None:
        self.write_authorized = True

    def begin_write(self) -> None:
        if not self.write_authorized:
            raise ApiError(
                "This command is not authorized to write",
                error_code="write_policy_violation",
                category="permission",
            )
        if self.write_attempts:
            raise ApiError(
                "Only one write request is allowed per invocation",
                error_code="multiple_writes_blocked",
                category="conflict",
                operation_state=self.public_operation_state,
            )
        self.write_attempts = 1
        self.operation_state = "dispatched"

    def mark_write_succeeded(self) -> None:
        self.operation_state = "succeeded"
        self.verification_pending = True

    def mark_write_rejected(self) -> None:
        self.operation_state = "rejected"
        self.verification_pending = False

    def mark_write_unknown(self) -> None:
        self.operation_state = "unknown"
        self.verification_pending = False

    def complete_write_lifecycle(self) -> None:
        self.verification_pending = False

    @property
    def public_operation_state(self) -> str:
        if self.operation_state in {"dispatched", "unknown"}:
            return "unknown"
        if self.operation_state == "succeeded":
            return "completed"
        if self.operation_state == "rejected":
            return "rejected"
        return "not_started"

    @property
    def has_uncertain_write(self) -> bool:
        return self.verification_pending or self.operation_state in {"dispatched", "unknown"}


@dataclass(frozen=True)
class RuntimeContext:
    config: Config
    client: Any
    state: RuntimeState

    def bind_target(self, target: Any) -> Any:
        """Bind a sanitized command target before the first API request."""
        return self.state.bind_target(target)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError("Invalid CLI arguments")


def _default_modules() -> Iterable[Any]:
    from dd_v3.commands import ALL

    return ALL


def _default_client_factory(config: Config, state: RuntimeState):
    from dd_v3.client import DatadogClient

    return DatadogClient(config, state=state)


def _command_hint(argv: list[str]) -> str | None:
    for value in argv:
        if not value.startswith("-"):
            return value
    return None


def _attach_known_target(exc: DatadogCliError, state: RuntimeState) -> DatadogCliError:
    if getattr(exc, "target", None) is None and state.known_target is not None:
        exc.target = state.known_target
    return exc


class Runtime:
    """Parse, execute, normalize, and atomically render one command."""

    def __init__(
        self,
        *,
        modules: Iterable[Any] | None = None,
        config_loader: Callable[[], Config] = load_config,
        client_factory: Callable[[Config, RuntimeState], Any] = _default_client_factory,
        stdout=None,
        stderr=None,
    ) -> None:
        self._modules = modules
        self._config_loader = config_loader
        self._client_factory = client_factory
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr

    def build_parser(self) -> argparse.ArgumentParser:
        parser = _Parser(
            prog="datadog",
            description="Datadog CLI（MoeGo/moe-datadog）",
        )
        subparsers = parser.add_subparsers(dest="command", metavar="<subcommand>")
        subparsers.required = True
        modules = self._modules if self._modules is not None else _default_modules()
        for module in modules:
            module.register(subparsers)
        return parser

    def run(self, argv: list[str] | None = None) -> int:
        values = list(sys.argv[1:] if argv is None else argv)
        command = _command_hint(values)
        fmt = "json"
        state = RuntimeState()
        try:
            args = self.build_parser().parse_args(values)
            command = args.command
            fmt = getattr(args, "fmt", "json")
            handler = getattr(args, "_handler", None)
            policy = getattr(args, "_policy", None)
            if handler is None or policy not in {READ, PREVIEWABLE_W2}:
                raise UsageError("Command registration is incomplete")
            if policy == PREVIEWABLE_W2 and bool(getattr(args, "execute", False)):
                state.authorize_write()
            config = self._config_loader()
            client = self._client_factory(config, state)
            result = handler(args, RuntimeContext(config=config, client=client, state=state))
            if not isinstance(result, CommandResult):
                raise ApiError(
                    "Command returned an invalid result",
                    error_code="invalid_command_result",
                )
            state.complete_write_lifecycle()
            envelope = success(
                command,
                target=result.target,
                result=result.result,
                meta=result.meta,
                verification_result=result.verification,
                warnings=result.warnings,
            )
            exit_code = 0
            document = render(envelope, fmt=fmt)
        except KeyboardInterrupt:
            if state.has_uncertain_write:
                exc = WriteOutcomeUnknownError("Datadog write outcome is unknown")
            else:
                exc = ApiError(
                    "Command interrupted",
                    error_code="interrupted",
                    operation_state=state.public_operation_state,
                )
                exc.code = 130
            exc = _attach_known_target(exc, state)
            envelope = error_envelope(command, exc)
            exit_code = exc.code
            document = render(envelope, fmt=fmt)
        except DatadogCliError as exc:
            if state.has_uncertain_write:
                exc = WriteOutcomeUnknownError("Datadog write outcome is unknown")
            elif state.write_attempts and exc.operation_state == "not_started":
                exc.operation_state = state.public_operation_state
            exc = _attach_known_target(exc, state)
            envelope = error_envelope(command, exc)
            exit_code = exc.code
            document = render(envelope, fmt=fmt)
        except Exception:
            if state.has_uncertain_write:
                exc = WriteOutcomeUnknownError("Datadog write outcome is unknown")
            else:
                exc = ApiError(
                    "Unexpected Datadog command failure",
                    operation_state=state.public_operation_state,
                )
            exc = _attach_known_target(exc, state)
            envelope = error_envelope(command, exc)
            exit_code = EXIT_API_ERROR if not state.has_uncertain_write else exc.code
            document = render(envelope, fmt=fmt)

        try:
            self._commit_output(document)
        except KeyboardInterrupt:
            self._stderr.write("[datadog] interrupted\n")
            return 130
        if not envelope["ok"]:
            self._stderr.write(f"[datadog] {envelope['error']['code']}\n")
        return exit_code

    def _commit_output(self, document: str) -> None:
        can_mask = hasattr(signal, "pthread_sigmask")
        previous_mask = (
            signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
            if can_mask
            else None
        )
        try:
            self._stdout.write(document)
            flush = getattr(self._stdout, "flush", None)
            if callable(flush):
                flush()
        finally:
            if can_mask and previous_mask is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def main(argv: list[str] | None = None) -> int:
    return Runtime().run(argv)
