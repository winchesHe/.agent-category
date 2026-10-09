from __future__ import annotations

import platform
from typing import Any

from .errors import EXIT_CONFIG_ERROR, fail


def platform_status() -> dict[str, Any]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    supported = system == "darwin" and machine == "arm64"
    return {
        "system": system,
        "machine": machine,
        "python": platform.python_version(),
        "supported": supported,
    }


def require_supported_platform() -> None:
    status = platform_status()
    if not status["supported"]:
        fail(
            "MLX Whisper 仅支持 Apple Silicon Mac（darwin/arm64）；"
            f"当前为 {status['system']}/{status['machine']}",
            EXIT_CONFIG_ERROR,
        )
