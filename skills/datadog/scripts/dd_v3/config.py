"""Immutable Datadog configuration with a fixed credential destination map."""
from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dd_v3.errors import MissingConfigError

DATADOG_API_TO_UI_HOST = {
    "api.datadoghq.com": "app.datadoghq.com",
    "api.us3.datadoghq.com": "us3.datadoghq.com",
    "api.us5.datadoghq.com": "us5.datadoghq.com",
    "api.datadoghq.eu": "app.datadoghq.eu",
    "api.ap1.datadoghq.com": "ap1.datadoghq.com",
    "api.ap2.datadoghq.com": "ap2.datadoghq.com",
    "api.uk1.datadoghq.com": "uk1.datadoghq.com",
    "api.ddog-gov.com": "app.ddog-gov.com",
    "api.us2.ddog-gov.com": "us2.ddog-gov.com",
}

DATADOG_SITE_TO_API_HOST = {
    "datadoghq.com": "api.datadoghq.com",
    "us3.datadoghq.com": "api.us3.datadoghq.com",
    "us5.datadoghq.com": "api.us5.datadoghq.com",
    "datadoghq.eu": "api.datadoghq.eu",
    "ap1.datadoghq.com": "api.ap1.datadoghq.com",
    "ap2.datadoghq.com": "api.ap2.datadoghq.com",
    "uk1.datadoghq.com": "api.uk1.datadoghq.com",
    "ddog-gov.com": "api.ddog-gov.com",
    "us2.ddog-gov.com": "api.us2.ddog-gov.com",
}

DEFAULT_SITE = "us5.datadoghq.com"


@dataclass(frozen=True)
class Config:
    api_key: str | None
    app_key: str | None
    api_base_url: str
    ui_base_url: str
    default_env: str
    timeout: float
    max_retries: int

    def require_credentials(self) -> tuple[str, str]:
        missing = []
        if not self.api_key:
            missing.append("DD_API_KEY")
        if not self.app_key:
            missing.append("DD_APP_KEY")
        if missing:
            raise MissingConfigError(f"Missing required environment variables: {', '.join(missing)}")
        return self.api_key, self.app_key


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and (
        (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
    ):
        return value[1:-1]
    return value


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip():
            values[key.strip()] = _strip_quotes(value)
    return values


def _exact_https_host(value: str, *, setting: str) -> str:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise MissingConfigError(
            f"{setting} must be an approved Datadog HTTPS host"
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise MissingConfigError(f"{setting} must be an approved Datadog HTTPS host")
    return parsed.hostname.lower()


def resolve_site(site: str) -> tuple[str, str]:
    """Resolve an approved Datadog site to its fixed API and UI origins."""
    raw = site.strip()
    if not raw:
        raw = DEFAULT_SITE
    if "://" in raw:
        api_host = _exact_https_host(raw, setting="DD_SITE")
    else:
        if any(character in raw for character in "/@?#:"):
            raise MissingConfigError("DD_SITE must be an approved Datadog host")
        host = raw.lower()
        api_host = DATADOG_SITE_TO_API_HOST.get(host, host)
    ui_host = DATADOG_API_TO_UI_HOST.get(api_host)
    if ui_host is None:
        raise MissingConfigError("DD_SITE must be an approved Datadog API host")
    return f"https://{api_host}", f"https://{ui_host}"


def _resolve_ui_site(value: str, *, expected_url: str) -> str:
    host = _exact_https_host(value.strip(), setting="DD_UI_SITE")
    if f"https://{host}" != expected_url:
        raise MissingConfigError("DD_UI_SITE must match the approved DD_SITE mapping")
    return expected_url


def _float_value(
    values: Mapping[str, str],
    name: str,
    default: float,
    *,
    maximum: float,
) -> float:
    value = values.get(name)
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise MissingConfigError(f"{name} must be a number") from exc
    if not math.isfinite(parsed):
        raise MissingConfigError(f"{name} must be a finite number")
    if parsed <= 0:
        raise MissingConfigError(f"{name} must be greater than zero")
    if parsed > maximum:
        raise MissingConfigError(f"{name} must be {maximum:g} or less")
    return parsed


def _int_value(
    values: Mapping[str, str],
    name: str,
    default: int,
    *,
    maximum: int,
) -> int:
    value = values.get(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise MissingConfigError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise MissingConfigError(f"{name} must be zero or greater")
    if parsed > maximum:
        raise MissingConfigError(f"{name} must be {maximum} or less")
    return parsed


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_config(
    *,
    environ: Mapping[str, str] | None = None,
    skill_root: Path | None = None,
) -> Config:
    """Load process values over the Skill-root ``.env`` without global mutation."""
    process_values = dict(os.environ if environ is None else environ)
    values: dict[str, str] = {}
    if process_values.get("DD_DISABLE_DOTENV") != "1":
        env_path = (skill_root or _skill_root()) / ".env"
        if env_path.is_file():
            try:
                values.update(_parse_env_file(env_path))
            except OSError:
                pass
    values.update(process_values)

    api_base_url, derived_ui_base_url = resolve_site(values.get("DD_SITE", DEFAULT_SITE))
    configured_ui = values.get("DD_UI_SITE")
    ui_base_url = (
        _resolve_ui_site(configured_ui, expected_url=derived_ui_base_url)
        if configured_ui
        else derived_ui_base_url
    )
    return Config(
        api_key=values.get("DD_API_KEY") or None,
        app_key=values.get("DD_APP_KEY") or None,
        api_base_url=api_base_url,
        ui_base_url=ui_base_url,
        default_env=values.get("DD_DEFAULT_ENV", "ns-production"),
        timeout=_float_value(values, "DD_TIMEOUT", 30.0, maximum=300.0),
        max_retries=_int_value(values, "DD_MAX_RETRIES", 4, maximum=10),
    )


def get_headers(config: Config) -> dict[str, str]:
    api_key, app_key = config.require_credentials()
    return {
        "DD-API-KEY": api_key,
        "DD-APPLICATION-KEY": app_key,
        "Content-Type": "application/json",
    }
