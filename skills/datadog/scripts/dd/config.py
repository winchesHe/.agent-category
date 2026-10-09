"""Configuration loading for the Datadog CLI."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dd.errors import MissingConfigError


@dataclass(frozen=True)
class Config:
    api_key: str
    app_key: str
    api_base_url: str
    ui_base_url: str
    default_env: str
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
    if os.environ.get("DD_DISABLE_DOTENV") == "1":
        return
    here = Path(__file__).resolve().parent.parent  # datadog/scripts
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


def normalize_api_base_url(site: str) -> str:
    raw = site.strip().rstrip("/")
    if not raw:
        raw = "us5.datadoghq.com"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("api."):
        return f"https://{raw}"
    return f"https://api.{raw}"


def normalize_ui_base_url(site: str) -> str:
    raw = site.strip().rstrip("/")
    if not raw:
        raw = "us5.datadoghq.com"
    if raw.startswith("http://") or raw.startswith("https://"):
        raw = raw.split("://", 1)[1]
    if raw.startswith("api."):
        raw = raw[len("api."):]
    return f"https://{raw}"


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


def load_config() -> Config:
    load_dotenv()
    missing = [k for k in ("DD_API_KEY", "DD_APP_KEY") if not os.environ.get(k)]
    if missing:
        raise MissingConfigError(f"缺少必填环境变量: {', '.join(missing)}")
    site = os.environ.get("DD_SITE", "us5.datadoghq.com")
    return Config(
        api_key=os.environ["DD_API_KEY"],
        app_key=os.environ["DD_APP_KEY"],
        api_base_url=normalize_api_base_url(site),
        ui_base_url=normalize_ui_base_url(os.environ.get("DD_UI_SITE", site)),
        default_env=os.environ.get("DD_DEFAULT_ENV", "ns-production"),
        timeout=_float_env("DD_TIMEOUT", 30.0),
        max_retries=_int_env("DD_MAX_RETRIES", 4),
    )


def get_headers(config: Config) -> dict[str, str]:
    return {
        "DD-API-KEY": config.api_key,
        "DD-APPLICATION-KEY": config.app_key,
        "Content-Type": "application/json",
    }
