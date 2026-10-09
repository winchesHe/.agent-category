"""Shared exit codes and CLI errors for the Sentry skill."""
from __future__ import annotations

import sys
from typing import NoReturn

EXIT_OK = 0
EXIT_MISSING_CONFIG = 2
EXIT_AUTH_ERROR = 3
EXIT_API_ERROR = 4
EXIT_TIMEOUT = 5


class SentryCliError(Exception):
    """Exception carrying the process exit code expected by the CLI."""

    def __init__(self, message: str, code: int = EXIT_API_ERROR) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class MissingConfigError(SentryCliError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_MISSING_CONFIG)


class UsageError(SentryCliError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_MISSING_CONFIG)


class AuthError(SentryCliError):
    def __init__(self, message: str) -> None:
        super().__init__(message, EXIT_AUTH_ERROR)


class ApiError(SentryCliError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message, EXIT_API_ERROR)
        self.status_code = status_code


class TimeoutError(SentryCliError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message, EXIT_TIMEOUT)
        self.status_code = status_code


def fail(message: str, code: int = EXIT_API_ERROR) -> NoReturn:
    sys.stderr.write(f"[sentry] {message}\n")
    sys.exit(code)
