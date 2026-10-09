"""Shared exit codes and errors for the Jira skill."""
from __future__ import annotations

import sys
from typing import Any, NoReturn

EXIT_OK = 0
EXIT_MISSING_CONFIG = 2
EXIT_AUTH_ERROR = 3
EXIT_API_ERROR = 4
EXIT_TIMEOUT = 5


class JiraCliError(Exception):
    """Exception carrying the expected process exit code."""

    def __init__(
        self,
        message: str,
        code: int = EXIT_API_ERROR,
        *,
        error_code: str | None = None,
        details: Any | None = None,
        operation_state: str = "not_started",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.error_code = error_code
        self.details = details
        self.operation_state = operation_state


class MissingConfigError(JiraCliError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_MISSING_CONFIG)


class UsageError(JiraCliError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        details: Any | None = None,
    ) -> None:
        super().__init__(
            message,
            EXIT_MISSING_CONFIG,
            error_code=error_code,
            details=details,
        )


class ValidationError(JiraCliError):
    def __init__(
        self,
        message: str,
        details: Any | None = None,
        *,
        error_code: str = "validation_failed",
        operation_state: str = "not_started",
    ) -> None:
        super().__init__(
            message,
            EXIT_API_ERROR,
            error_code=error_code,
            details=details,
            operation_state=operation_state,
        )


class AuthError(JiraCliError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_AUTH_ERROR)


class ApiError(JiraCliError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_API_ERROR)


class RequestTimeoutError(JiraCliError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_TIMEOUT)


def fail(message: str, code: int = EXIT_API_ERROR) -> NoReturn:
    sys.stderr.write(f"[jira] {message}\n")
    sys.exit(code)
