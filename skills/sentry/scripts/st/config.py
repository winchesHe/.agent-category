"""Configuration loading for the Sentry CLI."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from st.errors import MissingConfigError

_MAX_RETRIES_MIN = 0
_MAX_RETRIES_MAX = 5


@dataclass(frozen=True)
class Config:
    auth_token: str
    base_url: str
    default_org_slug: str
    default_project: str | None
    timeout: float
    max_retries: int


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and (
        (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
    ):
        return value[1:-1]
    return value


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = _strip_quotes(value)
    return values


def load_dotenv() -> None:
    """Load .env files without overriding existing environment variables."""
    if os.environ.get("SENTRY_DISABLE_DOTENV") == "1":
        return
    here = Path(__file__).resolve().parent.parent  # sentry/scripts
    candidates = [
        Path.cwd() / ".env",
        here.parent / ".env",
    ]
    seen: set[Path] = set()
    for path in candidates:
        try:
            path = path.resolve()
        except OSError:
            continue
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            values = _parse_env_file(path)
        except OSError:
            continue
        for key, value in values.items():
            if key and key not in os.environ:
                os.environ[key] = value


def normalize_base_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    if not value:
        value = "https://sentry.io"
    if value.startswith("http://"):
        raise MissingConfigError("SENTRY_BASE_URL 必须使用 https://；拒绝 http://")
    if value.startswith("https://"):
        return value
    return f"https://{value}"


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise MissingConfigError(f"{name} 必须是数字，当前值: {value!r}") from exc


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise MissingConfigError(f"{name} 必须是整数，当前值: {value!r}") from exc


def _clamp(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def load_config() -> Config:
    load_dotenv()
    if not os.environ.get("SENTRY_AUTH_TOKEN"):
        raise MissingConfigError("缺少必填环境变量: SENTRY_AUTH_TOKEN")
    project = os.environ.get("SENTRY_DEFAULT_PROJECT") or None
    return Config(
        auth_token=os.environ["SENTRY_AUTH_TOKEN"],
        base_url=normalize_base_url(os.environ.get("SENTRY_BASE_URL", "https://sentry.io")),
        default_org_slug=os.environ.get("SENTRY_ORG_SLUG", "moego-ey"),
        default_project=project,
        timeout=_float_env("SENTRY_TIMEOUT", 30.0),
        max_retries=_clamp(
            _int_env("SENTRY_MAX_RETRIES", 3),
            minimum=_MAX_RETRIES_MIN,
            maximum=_MAX_RETRIES_MAX,
        ),
    )


def get_headers(config: Config) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.auth_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
