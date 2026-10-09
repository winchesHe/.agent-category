"""Environment / token / path resolution.

- Loads ``<skill>/.env`` and ``$PWD/.env`` if present (simple parser, no deps).
- Resolves tokens per operation scope (read / search / unreads).
- Computes cache / files directories under ``<SKILL_DIR>/cache/``.
"""

from __future__ import annotations

import os
from pathlib import Path

from .errors import ActorConfigError, TokenMissingError


ENV_BOT = "SLACK_BOT_TOKEN"
ENV_USER = "SLACK_USER_TOKEN"
ENV_ANY = "SLACK_TOKEN"
ENV_CACHE_DIR = "SLACK_SKILL_CACHE_DIR"
ENV_FILES_DIR = "SLACK_SKILL_FILES_DIR"
ENV_DOWNLOAD_TYPES = "SLACK_SKILL_DOWNLOAD_TYPES"
ENV_TIMEOUT = "SLACK_SKILL_TIMEOUT"
ENV_ALLOWED_CHANNELS = "SLACK_SKILL_ALLOWED_CHANNELS"
ENV_READ_ACTOR = "SLACK_READ_ACTOR"
ENV_WRITE_ACTOR = "SLACK_WRITE_ACTOR"
ENV_WRITE_RETRY_BUDGET = "SLACK_SKILL_WRITE_RETRY_BUDGET"


_DOTENV_LOADED = False


def _parse_dotenv(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        # Env vars already set by the caller win over .env values.
        os.environ.setdefault(key, value)


def load_dotenv() -> None:
    """Load ``<SKILL_DIR>/.env`` then ``$PWD/.env``."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True

    # <SKILL_DIR>/.env — lives two levels above sk/ (scripts/sk/ -> scripts/ -> skill root)
    skill_dir = Path(__file__).resolve().parent.parent.parent
    _parse_dotenv(skill_dir / ".env")

    # $PWD/.env
    try:
        cwd = Path.cwd()
    except OSError:
        cwd = None
    if cwd is not None:
        _parse_dotenv(cwd / ".env")


class Config:
    """Resolved configuration for one CLI invocation."""

    def __init__(self) -> None:
        load_dotenv()
        self.bot_token = os.environ.get(ENV_BOT) or None
        self.user_token = os.environ.get(ENV_USER) or None
        self.any_token = os.environ.get(ENV_ANY) or None
        self.timeout = _integer_env(ENV_TIMEOUT, 60, minimum=1)
        self.write_retry_budget = _integer_env(
            ENV_WRITE_RETRY_BUDGET, 30, minimum=0
        )
        self.read_actor = (os.environ.get(ENV_READ_ACTOR) or "auto").strip().lower()
        self.write_actor = (os.environ.get(ENV_WRITE_ACTOR) or "auto").strip().lower()

        allowed = os.environ.get(ENV_ALLOWED_CHANNELS) or ""
        self.allowed_channels = {
            item.strip().lstrip("#") for item in allowed.split(",") if item.strip()
        } or None

        self.download_types_default = (
            os.environ.get(ENV_DOWNLOAD_TYPES) or "text"
        )

        # SKILL_DIR = two levels above sk/ (scripts/sk/ -> scripts/ -> skill root)
        skill_dir = Path(__file__).resolve().parent.parent.parent
        self.cache_root = Path(
            os.environ.get(ENV_CACHE_DIR) or (skill_dir / "cache")
        )
        self.files_root = Path(
            os.environ.get(ENV_FILES_DIR) or (self.cache_root / "files")
        )

    @property
    def cache_dir(self) -> Path:
        from .actor import current

        ctx = current()
        return ctx.cache_dir if ctx is not None else self.cache_root

    @property
    def files_dir(self) -> Path:
        from .actor import current

        ctx = current()
        return ctx.files_dir if ctx is not None else self.files_root

    # -- token routing -------------------------------------------------

    def token_for(self, scope: str) -> str:
        """Return a token appropriate for *scope*.

        Scopes:
          - ``"read"``    bot → user → any  (channels/users/get/replies/history/files)
          - ``"search"``  user → any        (must be xoxp)
          - ``"unreads"`` user → any        (must be xoxp)
          - ``"write"``   bot → any         (files upload / chat.postMessage)
        """
        from .actor import current, select_read, select_search

        ctx = current()
        if ctx is not None:
            if scope in ("read", "write"):
                return ctx.token
            if scope in ("search", "unreads") and ctx.selected == "user":
                return ctx.token
        if scope == "read":
            return select_read(self).token
        if scope in ("search", "unreads"):
            return select_search(self).token
        if scope == "write":
            raise TokenMissingError(
                "write actor 尚未通过目标预检锁定；写命令必须使用 select_write_target"
            )
        raise ValueError(f"unknown token scope: {scope!r}")

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)


def _integer_env(name: str, default: int, *, minimum: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ActorConfigError(f"{name} 必须是整数，实际为 {raw!r}") from None
    if value < minimum:
        raise ActorConfigError(f"{name} 必须大于等于 {minimum}，实际为 {value}")
    return value


__all__ = [
    "Config",
    "load_dotenv",
    "ENV_BOT",
    "ENV_USER",
    "ENV_ANY",
    "ENV_CACHE_DIR",
    "ENV_FILES_DIR",
    "ENV_DOWNLOAD_TYPES",
    "ENV_TIMEOUT",
    "ENV_ALLOWED_CHANNELS",
    "ENV_READ_ACTOR",
    "ENV_WRITE_ACTOR",
    "ENV_WRITE_RETRY_BUDGET",
]
