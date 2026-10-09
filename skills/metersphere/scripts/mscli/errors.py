from __future__ import annotations

EXIT_CONFIG = 2
EXIT_AUTH = 3
EXIT_API = 4
EXIT_TIMEOUT = 5


class MeterSphereError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_API):
        super().__init__(message)
        self.code = code


class CapabilityUnavailable(MeterSphereError):
    pass
