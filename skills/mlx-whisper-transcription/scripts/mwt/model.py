from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Config
from .errors import EXIT_CONFIG_ERROR, EXIT_OPERATION_ERROR, MwtCliError, fail

MODEL_METADATA = ".model.json"


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def model_status(model_dir: Path, config: Config | None = None) -> dict[str, Any]:
    config_path = model_dir / "config.json"
    weights_path = model_dir / "weights.safetensors"
    metadata_path = model_dir / MODEL_METADATA
    metadata: dict[str, Any] = {}
    model_config_valid = False
    if config_path.is_file() and not config_path.is_symlink():
        try:
            model_config = json.loads(config_path.read_text(encoding="utf-8"))
            model_config_valid = model_config.get("model_type") == "whisper"
        except (OSError, json.JSONDecodeError):
            model_config_valid = False
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}

    metadata_matches = config is None or (
        metadata.get("repo") == config.model_repo
        and metadata.get("revision") == config.model_revision
    )
    independent_files = (
        config_path.is_file()
        and not config_path.is_symlink()
        and weights_path.is_file()
        and not weights_path.is_symlink()
        and weights_path.stat().st_nlink == 1
    )
    valid = (
        model_dir.is_dir()
        and model_config_valid
        and config_path.stat().st_size > 0
        and independent_files
        and weights_path.stat().st_size > 0
        and metadata_matches
    )
    return {
        "path": str(model_dir),
        "exists": model_dir.is_dir(),
        "config_exists": config_path.is_file(),
        "config_valid": model_config_valid,
        "weights_exists": weights_path.is_file(),
        "independent_files": independent_files,
        "size_bytes": directory_size(model_dir),
        "repo": metadata.get("repo"),
        "revision": metadata.get("revision"),
        "valid": valid,
    }


def require_model(config: Config) -> dict[str, Any]:
    status = model_status(config.model_dir, config)
    if not status["valid"]:
        fail(
            f"正式模型不存在、不完整或版本不匹配：{config.model_dir}；请先运行 setup",
            EXIT_CONFIG_ERROR,
        )
    return status


def _write_metadata(path: Path, config: Config) -> None:
    metadata = {"repo": config.model_repo, "revision": config.model_revision}
    (path / MODEL_METADATA).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _replace_directory(staged: Path, destination: Path) -> None:
    backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"

    moved_old = False
    try:
        if destination.exists():
            os.replace(destination, backup)
            moved_old = True
        os.replace(staged, destination)
    except Exception:
        if destination.exists() and moved_old:
            shutil.rmtree(destination, ignore_errors=True)
        if moved_old and backup.exists():
            os.replace(backup, destination)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def _recover_interrupted_backup(config: Config) -> None:
    if config.model_dir.exists():
        return
    candidates = sorted(
        config.model_dir.parent.glob(f".{config.model_dir.name}.backup-*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        if model_status(candidate, config)["valid"]:
            os.replace(candidate, config.model_dir)
            return


def install_model(
    config: Config,
    *,
    force: bool = False,
    downloader: Callable[..., str] | None = None,
) -> dict[str, Any]:
    config.model_dir.parent.mkdir(parents=True, exist_ok=True)
    _recover_interrupted_backup(config)
    current = model_status(config.model_dir, config)
    if current["valid"] and not force:
        return {"status": "ready", "downloaded": False, "model": current}

    staged = Path(
        tempfile.mkdtemp(
            prefix=f".{config.model_dir.name}.partial-",
            dir=config.model_dir.parent,
        )
    )
    try:
        if downloader is None:
            from huggingface_hub import snapshot_download

            downloader = snapshot_download
        downloader(
            repo_id=config.model_repo,
            revision=config.model_revision,
            local_dir=staged,
        )
        staged_status = model_status(staged)
        if not staged_status["valid"]:
            fail("下载完成但模型文件不完整", EXIT_OPERATION_ERROR)
        _write_metadata(staged, config)
        if not model_status(staged, config)["valid"]:
            fail("模型版本元数据校验失败", EXIT_OPERATION_ERROR)
        _replace_directory(staged, config.model_dir)
    except PermissionError:
        raise
    except Exception as error:
        if isinstance(error, MwtCliError):
            raise
        fail(f"模型安装失败：{error}", EXIT_OPERATION_ERROR)
    finally:
        if staged.exists():
            shutil.rmtree(staged, ignore_errors=True)

    return {
        "status": "installed",
        "downloaded": True,
        "model": model_status(config.model_dir, config),
    }
