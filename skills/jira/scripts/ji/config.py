"""Configuration loading for the Jira CLI."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ji.errors import MissingConfigError

DEFAULT_JIRA_BASE_URL = "https://moego.atlassian.net"
DEFAULT_INTERCOM_GRAPHQL_URL = "https://intercom-for-jira-production.toolsplus.app/api/intercom/graphql"


@dataclass(frozen=True)
class Config:
    jira_base_url: str
    jira_login: str
    jira_token: str
    jira_timeout: float
    max_attachment_bytes: int
    intercom_jwt: str | None
    intercom_jwt_command: str | None
    intercom_graphql_url: str
    intercom_referrer: str | None
    intercom_timeout: float


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
    """Load .env files without overriding process environment variables."""
    if os.environ.get("JIRA_DISABLE_DOTENV") == "1":
        return
    skill_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path.cwd() / ".env",
        skill_root / ".env",
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


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise MissingConfigError(f"{name} must be a number, got {value!r}") from exc


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise MissingConfigError(f"{name} must be an integer, got {value!r}") from exc


def _base_url(value: str, default: str) -> str:
    raw = (value or default).strip().rstrip("/")
    if not raw:
        raw = default
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://{raw}"


def load_config() -> Config:
    load_dotenv()
    login = os.environ.get("JIRA_LOGIN") or os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN") or os.environ.get("JIRA_TOKEN")
    missing = []
    if not login:
        missing.append("JIRA_LOGIN or JIRA_EMAIL")
    if not token:
        missing.append("JIRA_API_TOKEN or JIRA_TOKEN")
    if missing:
        raise MissingConfigError("missing required environment variables: " + ", ".join(missing))

    return Config(
        jira_base_url=_base_url(os.environ.get("JIRA_BASE_URL", ""), DEFAULT_JIRA_BASE_URL),
        jira_login=login,
        jira_token=token,
        jira_timeout=_float_env("JIRA_TIMEOUT", 30.0),
        max_attachment_bytes=_int_env("JIRA_MAX_ATTACHMENT_BYTES", 20 * 1024 * 1024),
        intercom_jwt=(
            os.environ.get("JIRA_INTERCOM_JWT")
            or os.environ.get("INTERCOM_FOR_JIRA_JWT")
            or os.environ.get("INTERCOM_JIRA_JWT")
            or None
        ),
        intercom_jwt_command=os.environ.get("JIRA_INTERCOM_JWT_COMMAND") or None,
        intercom_graphql_url=_base_url(
            os.environ.get("JIRA_INTERCOM_GRAPHQL_URL", ""), DEFAULT_INTERCOM_GRAPHQL_URL
        ),
        intercom_referrer=os.environ.get("JIRA_INTERCOM_REFERRER") or None,
        intercom_timeout=_float_env("JIRA_INTERCOM_TIMEOUT", 30.0),
    )
