from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .errors import EXIT_CONFIG_ERROR, EXIT_OPERATION_ERROR, EXIT_TIMEOUT, fail

SAMPLE_RATE = 16_000


def ffmpeg_status() -> dict[str, Any]:
    try:
        import imageio_ffmpeg

        executable = Path(imageio_ffmpeg.get_ffmpeg_exe())
        return {
            "path": str(executable),
            "exists": executable.is_file(),
            "executable": executable.is_file()
            and executable.stat().st_mode & 0o111 != 0,
        }
    except (ImportError, OSError) as error:
        return {"path": None, "exists": False, "executable": False, "error": str(error)}


def build_decode_command(executable: str, audio_path: Path) -> list[str]:
    return [
        executable,
        "-nostdin",
        "-i",
        str(audio_path),
        "-threads",
        "0",
        "-f",
        "s16le",
        "-ac",
        "1",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(SAMPLE_RATE),
        "-",
    ]


def decode_audio(
    audio_path: Path,
    *,
    executable: str | None = None,
    timeout_seconds: float | None = None,
) -> tuple[np.ndarray, float]:
    if not audio_path.is_file():
        fail(f"音频文件不存在：{audio_path}", EXIT_CONFIG_ERROR)

    if executable is None:
        status = ffmpeg_status()
        if not status["executable"]:
            fail("imageio-ffmpeg 二进制不可用，请先运行 doctor", EXIT_CONFIG_ERROR)
        executable = str(status["path"])

    try:
        process = subprocess.run(
            build_decode_command(executable, audio_path),
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        fail("音频解码超时", EXIT_TIMEOUT)

    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8", errors="replace").strip()
        detail = stderr[-2000:] if stderr else f"ffmpeg exit {process.returncode}"
        fail(f"音频解码失败：{detail}", EXIT_OPERATION_ERROR)
    if not process.stdout:
        fail("音频解码结果为空", EXIT_OPERATION_ERROR)

    pcm = np.frombuffer(process.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return pcm, len(pcm) / SAMPLE_RATE
