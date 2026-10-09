import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from .errors import ConfigError

ENV_URLS = {
    "t2": {
        "mis": "https://mis.t2.moego.dev",
        "go": "https://go.t2.moego.dev",
        "customer": "https://my.t2.moego.dev",
    },
    "s1": {
        "mis": "https://mis.s1.moego.dev",
        "go": "https://go.s1.moego.dev",
        "customer": "https://my.s1.moego.dev",
    },
    "production": {
        "mis": "https://mis.moego.pet",
        "go": "https://go.moego.pet",
        "customer": "https://my.moego.pet",
    },
}


@dataclass(frozen=True)
class Config:
    mis_env: str
    timeout: float
    chrome_binary: str
    sso_username: str
    sso_password: str = field(repr=False)
    sso_base_url: str = "https://cas.moego.pet"
    sso_realm: str = "Moement"

    @property
    def mis_url(self):
        return ENV_URLS[self.mis_env]["mis"]


def _legacy_env_paths(skill_root):
    home = Path.home()
    return (
        home / ".agents" / "skills" / "moego-internal-ops" / ".env",
        home / ".codex" / "skills" / "moego-internal-ops" / ".env",
        home / ".agents" / "skills" / "moe-internal-ops" / ".env",
        home / ".codex" / "skills" / "moe-internal-ops" / ".env",
        skill_root.parent / "moe-internal-ops" / ".env",
    )


def _load_layers(skill_root):
    layers = []
    paths = (
        *_legacy_env_paths(skill_root),
        skill_root / ".env",
        Path.cwd() / ".env",
    )
    for path in paths:
        if path.exists():
            layers.append(
                {
                    key: value
                    for key, value in dotenv_values(path).items()
                    if value is not None
                }
            )
    layers.append(dict(os.environ))
    return layers


def _value(layers, current_name, legacy_name, default=""):
    for layer in reversed(layers):
        if current_name in layer:
            return layer[current_name]
        if legacy_name in layer:
            print(f"{legacy_name} 已弃用，请迁移到 {current_name}", file=sys.stderr)
            return layer[legacy_name]
    return default


def load_config(cli_env=None):
    skill_root = Path(__file__).resolve().parents[2]
    layers = _load_layers(skill_root)
    mis_env = cli_env or _value(layers, "MOE_MIS_ENV", "MIO_MIS_ENV", "t2")
    if mis_env not in ENV_URLS:
        raise ConfigError("MOE_MIS_ENV 仅支持 t2、s1、production")
    try:
        timeout = float(_value(layers, "MOE_MIS_TIMEOUT", "MIO_TIMEOUT", "30"))
    except ValueError as exc:
        raise ConfigError("MOE_MIS_TIMEOUT 必须是数字") from exc
    return Config(
        mis_env=mis_env,
        timeout=timeout,
        chrome_binary=_value(
            layers, "MOE_MIS_CHROME_BINARY", "MIO_CHROME_BINARY"
        ),
        sso_username=_value(
            layers, "MOE_MIS_SSO_USERNAME", "MIO_SSO_USERNAME"
        ),
        sso_password=_value(
            layers, "MOE_MIS_SSO_PASSWORD", "MIO_SSO_PASSWORD"
        ),
        sso_base_url=_value(
            layers, "MOE_MIS_SSO_BASE_URL", "MIO_SSO_BASE_URL", "https://cas.moego.pet"
        ).rstrip("/"),
        sso_realm=_value(
            layers, "MOE_MIS_SSO_REALM", "MIO_SSO_REALM", "Moement"
        ),
    )
