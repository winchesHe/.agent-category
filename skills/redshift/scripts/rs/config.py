"""Configuration loading with strict, machine-decidable failures."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Mapping, MutableMapping

from .errors import SkillError, config_error


DOTENV_MAX_BYTES = 262_144


def _read_secure_dotenv(path: Path, *, required: bool) -> str | None:
    if (
        not path.is_absolute()
        or not path.parts
        or any(component in {"", ".", ".."} for component in path.parts[1:])
    ):
        if required:
            raise config_error("invalid", key="RS_DOTENV")
        return None
    if not required:
        try:
            os.lstat(path)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise config_error("invalid", key="RS_DOTENV") from exc
    allowed_directory_owners = {0, os.geteuid()}
    directory_fd: int | None = None
    descriptor: int | None = None
    try:
        directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        root_info = os.fstat(directory_fd)
        if (
            root_info.st_uid not in allowed_directory_owners
            or stat.S_IMODE(root_info.st_mode) & 0o022
        ):
            raise config_error("invalid", key="RS_DOTENV")
        for component in path.parts[1:-1]:
            flags = os.O_RDONLY | os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            info = os.fstat(next_fd)
            if (
                info.st_uid not in allowed_directory_owners
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                os.close(next_fd)
                raise config_error("invalid", key="RS_DOTENV")
            os.close(directory_fd)
            directory_fd = next_fd
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path.name, flags, dir_fd=directory_fd)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > DOTENV_MAX_BYTES
        ):
            raise config_error("invalid", key="RS_DOTENV")
        chunks: list[bytes] = []
        remaining = DOTENV_MAX_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > DOTENV_MAX_BYTES:
            raise config_error("invalid", key="RS_DOTENV")
        try:
            return raw.decode("utf-8")
        except UnicodeError as exc:
            raise config_error("invalid", key="RS_DOTENV") from exc
    except FileNotFoundError as exc:
        if required:
            raise config_error("invalid", key="RS_DOTENV") from exc
        return None
    except (OSError, SkillError) as exc:
        if isinstance(exc, SkillError):
            raise
        raise config_error("invalid", key="RS_DOTENV") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory_fd is not None:
            os.close(directory_fd)


def load_dotenv(environ: MutableMapping[str, str] | None = None) -> None:
    """Load a secure explicit or Skill-private dotenv without overriding env."""

    target = environ if environ is not None else os.environ
    explicit = target.get("RS_DOTENV")
    if explicit:
        candidates = [(Path(explicit), True)]
    else:
        try:
            skill_root = Path(__file__).resolve().parents[2]
        except OSError:
            return
        candidates = [(skill_root / ".env", False)]

    for candidate, required in candidates:
        try:
            raw_text = _read_secure_dotenv(candidate, required=required)
        except OSError as exc:
            if required:
                raise config_error("invalid", key="RS_DOTENV") from exc
            continue
        if raw_text is None:
            continue
        for raw in raw_text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key and key not in target:
                target[key] = value


def _required(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key)
    if value is None or value == "":
        raise config_error("missing", key=key)
    return value


def output_directory(environ: Mapping[str, str] | None = None) -> Path:
    source = environ if environ is not None else os.environ
    return Path(_required(source, "REDSHIFT_OUTPUT_DIR"))
