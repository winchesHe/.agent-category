"""Deterministic value encoding and durable artifact publication."""
from __future__ import annotations

import csv
import errno
import json
import math
import os
import signal
import stat
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Mapping, Protocol, Sequence, TextIO

from .errors import Interrupted, SkillError, output_error
from .models import InvocationState


_TEMP_PREFIX = ".redshift-tmp-"
_PUBLISH_SIGNALS = {signal.SIGINT, signal.SIGTERM}
_DANGEROUS_CSV_PREFIXES = (
    "=",
    "+",
    "-",
    "@",
    "\t",
    "\r",
    "\n",
    "＝",
    "＋",
    "－",
    "＠",
)
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_INLINE_JSON_BYTES = 64 * 1024


class _TextWriter(Protocol):
    def write(self, value: str) -> int: ...


class _CappedUtf8Writer:
    def __init__(self, stream: BinaryIO, maximum_bytes: int) -> None:
        self._stream = stream
        self._maximum_bytes = maximum_bytes
        self._written_bytes = 0

    def write(self, value: str) -> int:
        encoded = value.encode("utf-8")
        if self._written_bytes + len(encoded) > self._maximum_bytes:
            raise output_error("size_limit_exceeded")
        self._stream.write(encoded)
        self._written_bytes += len(encoded)
        return len(value)


def _unsupported_value() -> SkillError:
    return output_error("unsupported_value_type")


def encode_value(value: Any) -> Any:
    """Convert a supported result value into a JSON-safe deterministic value."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, Mapping):
        encoded: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise _unsupported_value()
            encoded[key] = encode_value(nested)
        return encoded
    if isinstance(value, (list, tuple)):
        return [encode_value(item) for item in value]
    raise _unsupported_value()


def validate_output_name(name: str) -> str:
    """Validate a caller-provided final filename without normalizing it."""

    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or name.startswith(".")
        or "/" in name
        or "\\" in name
        or "\x00" in name
    ):
        raise output_error("path_not_allowed")
    return name


def _json_line(value: Any) -> str:
    return json.dumps(
        encode_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def success_envelope(command: str, data: Any, meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "ok": True,
        "command": command,
        "data": encode_value(data),
        "meta": encode_value(dict(meta or {})),
    }


def error_envelope(command: str | None, error: SkillError) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "command": command,
        "error": error.to_payload(),
    }
    if error.meta:
        payload["meta"] = encode_value(dict(error.meta))
    return encode_value(payload)


def write_json(stream: TextIO, payload: Any) -> None:
    stream.write(_json_line(payload))
    stream.write("\n")
    stream.flush()


def validate_inline_json_payload(payload: Any) -> None:
    """Reject oversized inline JSON before any bytes reach stdout."""

    size = len(_json_line(payload).encode("utf-8")) + 1
    if size > MAX_INLINE_JSON_BYTES:
        raise output_error(
            "inline_size_limit_exceeded",
            suggestion="use_artifact",
        )


def _csv_value(value: Any) -> Any:
    encoded = encode_value(value)
    if encoded is None:
        return ""
    if isinstance(encoded, bool):
        return "true" if encoded else "false"
    if isinstance(encoded, (dict, list)):
        return json.dumps(
            encoded,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    if isinstance(value, str) and value.startswith(_DANGEROUS_CSV_PREFIXES):
        return f"'{encoded}"
    return encoded


def _csv_header(value: str) -> str:
    if value.startswith(_DANGEROUS_CSV_PREFIXES):
        return f"'{value}"
    return value


def _write_records(
    stream: _TextWriter,
    *,
    fmt: str,
    columns: Sequence[str],
    records: Iterable[Mapping[str, Any]],
) -> None:
    if fmt == "ndjson":
        for record in records:
            stream.write(_json_line(record))
            stream.write("\n")
        return
    if fmt == "csv":
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow([_csv_header(column) for column in columns])
        for record in records:
            writer.writerow([_csv_value(record.get(column)) for column in columns])
        return
    raise SkillError("internal", "unexpected", "never")


def _safe_unlink(
    dir_fd: int,
    name: str | None,
    *,
    primary_error: BaseException | None = None,
) -> None:
    if not name:
        return
    try:
        os.unlink(name, dir_fd=dir_fd)
    except Interrupted:
        if primary_error is None:
            raise
    except OSError:
        pass


@contextmanager
def _block_publish_signals() -> Iterable[None]:
    """Avoid a signal landing between link creation and state bookkeeping."""

    pthread_sigmask = getattr(signal, "pthread_sigmask", None)
    if pthread_sigmask is None:
        yield
        return
    previous = pthread_sigmask(signal.SIG_BLOCK, _PUBLISH_SIGNALS)
    try:
        yield
    finally:
        pthread_sigmask(signal.SIG_SETMASK, previous)


def _open_private_directory(output_dir: str | os.PathLike[str]) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(Path(output_dir), flags)
    except (OSError, TypeError, ValueError) as exc:
        raise output_error("path_not_allowed") from exc

    try:
        info = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise output_error("path_not_allowed")
    except BaseException:
        os.close(directory_fd)
        raise
    return directory_fd


def validate_output_target(
    output_dir: str | os.PathLike[str], final_name: str
) -> tuple[Path, str]:
    """Validate an artifact destination before any Redshift connection is opened."""

    validated_name = validate_output_name(final_name)
    directory_fd = _open_private_directory(output_dir)
    os.close(directory_fd)
    return Path(output_dir), validated_name


def _create_temp(directory_fd: int, temp_name: str) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    file_fd: int | None = None
    try:
        file_fd = os.open(temp_name, flags, 0o600, dir_fd=directory_fd)
        os.fchmod(file_fd, 0o600)
        return file_fd
    except BaseException as exc:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except BaseException:
                pass
            _safe_unlink(directory_fd, temp_name, primary_error=exc)
        if isinstance(exc, (Interrupted, SkillError)) or not isinstance(exc, Exception):
            raise
        raise output_error("write_failed") from exc


def publish_records(
    *,
    output_dir: str | os.PathLike[str],
    final_name: str,
    fmt: str,
    columns: Sequence[str],
    records: Iterable[Mapping[str, Any]],
    state: InvocationState,
) -> str:
    """Publish CSV/NDJSON using a durable, no-overwrite hard-link protocol."""

    final_name = validate_output_name(final_name)
    directory_fd = _open_private_directory(output_dir)
    temp_name = f"{_TEMP_PREFIX}{uuid.uuid4().hex}"
    state.temp_name = temp_name
    state.final_name = final_name
    file_fd: int | None = None

    try:
        file_fd = _create_temp(directory_fd, temp_name)
        state.artifact_state = "temp_created"
        try:
            with os.fdopen(file_fd, "wb") as binary_stream:
                file_fd = None
                stream = _CappedUtf8Writer(binary_stream, MAX_ARTIFACT_BYTES)
                _write_records(stream, fmt=fmt, columns=columns, records=records)
                binary_stream.flush()
                os.fsync(binary_stream.fileno())
        except SkillError as exc:
            _safe_unlink(directory_fd, temp_name, primary_error=exc)
            state.temp_name = None
            raise
        except BaseException as exc:
            _safe_unlink(directory_fd, temp_name, primary_error=exc)
            state.temp_name = None
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise output_error("write_failed") from exc

        try:
            with _block_publish_signals():
                os.link(
                    temp_name,
                    final_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                state.artifact_state = "final_link_created"
        except Interrupted as exc:
            _safe_unlink(directory_fd, temp_name, primary_error=exc)
            state.temp_name = None
            raise
        except OSError as exc:
            _safe_unlink(directory_fd, temp_name, primary_error=exc)
            state.temp_name = None
            if exc.errno == errno.EEXIST:
                raise output_error("already_exists") from exc
            raise output_error("write_failed") from exc

        try:
            with _block_publish_signals():
                os.unlink(temp_name, dir_fd=directory_fd)
                state.temp_name = None
                os.fsync(directory_fd)
                state.artifact_state = "durable_published"
                state.output_ref = final_name
        except Interrupted as exc:
            _safe_unlink(directory_fd, temp_name, primary_error=exc)
            state.temp_name = None
            raise
        except BaseException as exc:
            _safe_unlink(directory_fd, temp_name, primary_error=exc)
            state.temp_name = None
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise output_error("publish_unknown") from exc

        return final_name
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)
