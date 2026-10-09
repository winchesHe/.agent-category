from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.rs.config import load_dotenv
from scripts.rs.errors import SkillError


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "directory",
        "relative",
        "unsafe_mode",
        "symlink",
        "parent_symlink",
        "writable_parent",
        "oversized",
    ],
)
def test_explicit_dotenv_path_fails_closed(tmp_path, kind: str) -> None:
    dotenv = tmp_path / "selected.env"
    if kind == "directory":
        dotenv.mkdir()
    elif kind == "relative":
        dotenv = Path("selected.env")
    elif kind == "unsafe_mode":
        dotenv.write_text("REDSHIFT_CONNECTIONS_FILE=/tmp/x\n", encoding="utf-8")
        os.chmod(dotenv, 0o644)
    elif kind == "symlink":
        target = tmp_path / "real.env"
        target.write_text("REDSHIFT_CONNECTIONS_FILE=/tmp/x\n", encoding="utf-8")
        os.chmod(target, 0o600)
        dotenv.symlink_to(target)
    elif kind == "parent_symlink":
        real = tmp_path / "real"
        real.mkdir(mode=0o700)
        target = real / "selected.env"
        target.write_text("REDSHIFT_CONNECTIONS_FILE=/tmp/x\n", encoding="utf-8")
        os.chmod(target, 0o600)
        linked = tmp_path / "linked"
        linked.symlink_to(real, target_is_directory=True)
        dotenv = linked / "selected.env"
    elif kind == "writable_parent":
        unsafe = tmp_path / "unsafe"
        unsafe.mkdir(mode=0o700)
        os.chmod(unsafe, 0o770)
        dotenv = unsafe / "selected.env"
        dotenv.write_text("REDSHIFT_CONNECTIONS_FILE=/tmp/x\n", encoding="utf-8")
        os.chmod(dotenv, 0o600)
    elif kind == "oversized":
        dotenv.write_bytes(b"A" * 262_145)
        os.chmod(dotenv, 0o600)

    environment = {"RS_DOTENV": str(dotenv)}
    with pytest.raises(SkillError) as caught:
        load_dotenv(environment)
    assert caught.value.full_code == "config.invalid"
    assert caught.value.details == {"key": "RS_DOTENV"}


def test_explicit_dotenv_accepts_an_owner_controlled_absolute_file(tmp_path) -> None:
    dotenv = tmp_path / "selected.env"
    dotenv.write_text("REDSHIFT_CONNECTIONS_FILE=/secure/connections.json\n", encoding="utf-8")
    os.chmod(dotenv, 0o600)
    environment = {"RS_DOTENV": str(dotenv)}
    load_dotenv(environment)
    assert environment["REDSHIFT_CONNECTIONS_FILE"] == "/secure/connections.json"


def test_unset_dotenv_selector_uses_private_root_fallback(tmp_path, monkeypatch) -> None:
    module_path = tmp_path / "scripts" / "rs" / "config.py"
    module_path.parent.mkdir(parents=True)
    dotenv = tmp_path / ".env"
    dotenv.write_text("REDSHIFT_CONNECTIONS_FILE=/secure/connections.json\n", encoding="utf-8")
    os.chmod(dotenv, 0o600)
    monkeypatch.setattr("scripts.rs.config.__file__", str(module_path))
    environment: dict[str, str] = {}
    load_dotenv(environment)
    assert environment == {"REDSHIFT_CONNECTIONS_FILE": "/secure/connections.json"}


def test_missing_optional_skill_dotenv_ignores_a_writable_package_parent(
    tmp_path, monkeypatch
) -> None:
    writable = tmp_path / "shared"
    writable.mkdir(mode=0o700)
    os.chmod(writable, 0o777)
    module_path = writable / "skill" / "scripts" / "rs" / "config.py"
    monkeypatch.setattr("scripts.rs.config.__file__", str(module_path))
    environment: dict[str, str] = {}

    load_dotenv(environment)

    assert environment == {}


@pytest.mark.parametrize(
    ("entrypoint", "arguments"),
    [
        ("redshift.py", ["query", "--sql", "SELECT 1"]),
        ("build_catalog.py", ["--output", "unused.jsonl"]),
    ],
)
def test_invalid_utf8_dotenv_returns_typed_config_error(
    tmp_path, entrypoint: str, arguments: list[str]
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_bytes(b"REDSHIFT_CONNECTIONS_FILE=\xff\n")
    os.chmod(dotenv, 0o600)
    root = Path(__file__).parents[1]
    environment = {**os.environ, "RS_DOTENV": str(dotenv), "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.run(
        [sys.executable, str(root / "scripts" / entrypoint), *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 3
    payload = json.loads(process.stdout)
    assert payload["error"]["category"] == "config"
    assert payload["error"]["code"] == "invalid"
