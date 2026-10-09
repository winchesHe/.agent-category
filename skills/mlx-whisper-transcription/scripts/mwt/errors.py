from __future__ import annotations

EXIT_CONFIG_ERROR = 2
EXIT_PERMISSION_ERROR = 3
EXIT_OPERATION_ERROR = 4
EXIT_TIMEOUT = 5


class MwtCliError(Exception):
    def __init__(self, message: str, code: int = EXIT_OPERATION_ERROR) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def fail(message: str, code: int = EXIT_OPERATION_ERROR) -> None:
    raise MwtCliError(message, code)
