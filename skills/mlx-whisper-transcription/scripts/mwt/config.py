from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MODEL_REPO = "mlx-community/whisper-large-v3-turbo"
MODEL_REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"
DEFAULT_MODEL_DIR = Path(
    "~/.local/share/mlx-whisper/models/whisper-large-v3-turbo"
).expanduser()


@dataclass(frozen=True)
class Config:
    model_dir: Path
    model_repo: str = MODEL_REPO
    model_revision: str = MODEL_REVISION


def load_config(args: object) -> Config:
    cli_value = getattr(args, "model_dir", None)
    raw_path = cli_value or os.environ.get("MLX_WHISPER_MODEL_DIR")
    model_dir = Path(raw_path).expanduser() if raw_path else DEFAULT_MODEL_DIR
    return Config(model_dir=model_dir.resolve())
