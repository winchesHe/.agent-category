from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import EXIT_CONFIG, MeterSphereError


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Config:
    base_url: str
    access_key: str
    secret_key: str
    project_id: str
    organization_id: str
    workspace_id: str
    headers_json: str
    protocols_json: str
    skill_root: Path
    env_file: Path | None
    timeout_seconds: float = 60.0


def load_config(require_auth: bool = True) -> Config:
    skill_root = Path(__file__).resolve().parents[2]
    explicit_raw = os.environ.get("METERSPHERE_ENV_FILE", "")
    explicit = Path(explicit_raw).expanduser() if explicit_raw else None
    candidates = [skill_root / ".env", Path.cwd() / ".env"]
    if explicit:
        candidates.append(explicit)
    process_keys = set(os.environ)
    for path in candidates:
        for key, value in _read_env_file(path).items():
            if key not in process_keys:
                os.environ[key] = value
    env_file = next((path for path in reversed(candidates) if path.is_file()), None)

    config = Config(
        base_url=os.environ.get("METERSPHERE_BASE_URL", "").rstrip("/"),
        access_key=os.environ.get("METERSPHERE_ACCESS_KEY", ""),
        secret_key=os.environ.get("METERSPHERE_SECRET_KEY", ""),
        project_id=os.environ.get("METERSPHERE_PROJECT_ID", ""),
        organization_id=os.environ.get("METERSPHERE_ORGANIZATION_ID", "100001"),
        workspace_id=os.environ.get("METERSPHERE_WORKSPACE_ID", ""),
        headers_json=os.environ.get("METERSPHERE_HEADERS_JSON", ""),
        protocols_json=os.environ.get("METERSPHERE_PROTOCOLS_JSON", '["HTTP"]'),
        skill_root=skill_root,
        env_file=env_file,
        timeout_seconds=float(os.environ.get("METERSPHERE_TIMEOUT_SECONDS", "60")),
    )
    if require_auth:
        missing = [
            name
            for name, value in (
                ("METERSPHERE_BASE_URL", config.base_url),
                ("METERSPHERE_ACCESS_KEY", config.access_key),
                ("METERSPHERE_SECRET_KEY", config.secret_key),
            )
            if not value
        ]
        if missing:
            raise MeterSphereError(f"缺少配置: {', '.join(missing)}", EXIT_CONFIG)
    return config
