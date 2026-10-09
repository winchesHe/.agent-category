"""Stable error taxonomy for the Datadog CLI.

Only the structured fields on :class:`DatadogCliError` are public.  Exception
messages are diagnostic context for local control flow and are never rendered
to stdout or stderr by the runtime.
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_MISSING_CONFIG = 2
EXIT_AUTH_ERROR = 3
EXIT_API_ERROR = 4
EXIT_TIMEOUT = 5


class DatadogCliError(Exception):
    """Exception carrying the process exit code expected by the CLI."""

    def __init__(
        self,
        message: str,
        code: int = EXIT_API_ERROR,
        *,
        category: str = "api",
        error_code: str = "api_error",
        retry_class: str = "never",
        operation_state: str = "not_started",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.category = category
        self.error_code = error_code
        self.retry_class = retry_class
        self.operation_state = operation_state


class MissingConfigError(DatadogCliError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            EXIT_MISSING_CONFIG,
            category="config",
            error_code="missing_config",
        )


class UsageError(DatadogCliError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_USAGE, category="usage", error_code="invalid_usage")


class AuthError(DatadogCliError):
    def __init__(self, message: str, *, operation_state: str = "not_started") -> None:
        super().__init__(
            message,
            EXIT_AUTH_ERROR,
            category="auth",
            error_code="authentication_failed",
            operation_state=operation_state,
        )


class PermissionDeniedError(AuthError):
    def __init__(self, message: str, *, operation_state: str = "not_started") -> None:
        DatadogCliError.__init__(
            self,
            message,
            EXIT_AUTH_ERROR,
            category="permission",
            error_code="permission_denied",
            operation_state=operation_state,
        )


class ApiError(DatadogCliError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "api_error",
        category: str = "api",
        retry_class: str = "never",
        operation_state: str = "not_started",
    ) -> None:
        super().__init__(
            message,
            EXIT_API_ERROR,
            category=category,
            error_code=error_code,
            retry_class=retry_class,
            operation_state=operation_state,
        )


class DatadogTimeoutError(DatadogCliError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            EXIT_TIMEOUT,
            category="transient",
            error_code="request_timeout",
            retry_class="safe",
        )


class ConflictError(DatadogCliError):
    def __init__(self, message: str, *, error_code: str = "conflict") -> None:
        super().__init__(
            message,
            EXIT_API_ERROR,
            category="conflict",
            error_code=error_code,
        )


class WriteOutcomeUnknownError(DatadogCliError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            EXIT_TIMEOUT,
            category="transient",
            error_code="write_outcome_unknown",
            retry_class="never",
            operation_state="unknown",
        )
