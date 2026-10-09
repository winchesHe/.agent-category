from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from ..audio import decode_audio
from ..config import Config
from ..errors import EXIT_CONFIG_ERROR, EXIT_OPERATION_ERROR, MwtCliError, fail
from ..formatter import add_format_argument, output
from ..model import require_model
from ..platform import require_supported_platform

SUPPORTED_OUTPUT_FORMATS = ("txt", "srt", "json")


def parse_output_formats(value: str) -> tuple[str, ...]:
    if value == "all":
        return SUPPORTED_OUTPUT_FORMATS
    formats = tuple(
        dict.fromkeys(part.strip().lower() for part in value.split(",") if part.strip())
    )
    if not formats:
        fail("--output-formats 不能为空", EXIT_CONFIG_ERROR)
    invalid = [item for item in formats if item not in SUPPORTED_OUTPUT_FORMATS]
    if invalid:
        fail(f"不支持的输出格式：{', '.join(invalid)}", EXIT_CONFIG_ERROR)
    return formats


def resolve_output_name(audio_path: Path, value: str | None) -> str:
    name = value or f"{audio_path.stem}-转写"
    if not name or Path(name).name != name or name in {".", ".."}:
        fail("--output-name 必须是文件名，不能包含目录", EXIT_CONFIG_ERROR)
    return name


def output_paths(
    output_dir: Path, output_name: str, formats: tuple[str, ...]
) -> dict[str, Path]:
    base = output_dir / output_name
    return {item: base.with_suffix(f".{item}") for item in formats}


def validate_targets(targets: dict[str, Path], input_path: Path) -> None:
    input_resolved = input_path.resolve()
    for target in targets.values():
        if target.exists() and not target.is_file():
            fail(f"目标路径不是普通文件，拒绝替换：{target}", EXIT_OPERATION_ERROR)
        if target.resolve() == input_resolved:
            fail(f"目标路径与输入音频相同，拒绝覆盖：{target}", EXIT_OPERATION_ERROR)
        if target.exists() and input_path.exists() and target.samefile(input_path):
            fail(f"目标路径指向输入音频，拒绝覆盖：{target}", EXIT_OPERATION_ERROR)


def commit_artifacts(
    staged: dict[str, Path],
    targets: dict[str, Path],
    *,
    overwrite: bool,
    backup_dir: Path,
    input_path: Path | None = None,
) -> None:
    if input_path is not None:
        validate_targets(targets, input_path)
    existing = [path for path in targets.values() if path.exists()]
    if existing and not overwrite:
        fail(
            "目标文件已存在，拒绝覆盖：" + ", ".join(str(path) for path in existing),
            EXIT_OPERATION_ERROR,
        )

    backups: dict[Path, Path] = {}
    committed: list[Path] = []
    try:
        for target in existing:
            backup = backup_dir / f"backup-{len(backups)}-{target.name}"
            os.replace(target, backup)
            backups[target] = backup
        for output_format, source in staged.items():
            target = targets[output_format]
            os.replace(source, target)
            committed.append(target)
    except Exception:
        for target in committed:
            target.unlink(missing_ok=True)
        for target, backup in backups.items():
            if backup.exists():
                os.replace(backup, target)
        raise


def run_inference(pcm: Any, model_dir: Path, options: dict[str, Any]) -> dict[str, Any]:
    import mlx_whisper

    # Third-party progress or language-detection messages must never corrupt JSON stdout.
    with redirect_stdout(sys.stderr):
        return mlx_whisper.transcribe(
            pcm,
            path_or_hf_repo=str(model_dir),
            verbose=None,
            **options,
        )


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("transcribe", help="离线转写单个本地音频")
    parser.add_argument("audio", help="本地音频文件路径")
    parser.add_argument("--model-dir", help="覆盖正式模型目录")
    parser.add_argument("--output-dir", help="产物目录（默认：音频所在目录）")
    parser.add_argument("--output-name", help="产物基础文件名（不含扩展名）")
    parser.add_argument(
        "--output-formats",
        default="all",
        help="txt,srt,json 的逗号列表，或 all（默认：all）",
    )
    parser.add_argument("--language", default="auto", help="语言代码，默认 auto")
    parser.add_argument("--initial-prompt", help="可选上下文提示词，可能诱导幻觉")
    parser.add_argument(
        "--word-timestamps",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="启用词级时间戳（默认启用）",
    )
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有产物")
    add_format_argument(parser)
    parser.set_defaults(_handler=run)


def run(args: Any, config: Config) -> int:
    require_supported_platform()
    model = require_model(config)
    audio_path = Path(args.audio).expanduser().resolve()
    if not audio_path.is_file():
        fail(f"音频文件不存在：{audio_path}", EXIT_CONFIG_ERROR)

    destination = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else audio_path.parent
    )
    destination.mkdir(parents=True, exist_ok=True)
    formats = parse_output_formats(args.output_formats)
    output_name = resolve_output_name(audio_path, args.output_name)
    targets = output_paths(destination, output_name, formats)
    validate_targets(targets, audio_path)
    existing = [path for path in targets.values() if path.exists()]
    if existing and not args.overwrite:
        fail(
            "目标文件已存在，拒绝覆盖：" + ", ".join(str(path) for path in existing),
            EXIT_OPERATION_ERROR,
        )

    pcm, duration = decode_audio(audio_path)
    try:
        from mlx_whisper.writers import get_writer

        options: dict[str, Any] = {
            "task": "transcribe",
            "word_timestamps": args.word_timestamps,
        }
        if args.language != "auto":
            options["language"] = args.language
        if args.initial_prompt:
            options["initial_prompt"] = args.initial_prompt
        result = run_inference(pcm, config.model_dir, options)
    except Exception as error:  # noqa: BLE001 - Third-party inference boundary.
        fail(f"MLX Whisper 转写失败：{error}", EXIT_OPERATION_ERROR)

    temp_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_name}.partial-", dir=destination)
    )
    try:
        staged: dict[str, Path] = {}
        writer_options = {"max_line_width": None, "max_line_count": None}
        for output_format in formats:
            writer = get_writer(output_format, str(temp_dir))
            writer(result, output_name, options=writer_options)
            generated = (temp_dir / output_name).with_suffix(f".{output_format}")
            if not generated.is_file():
                fail(f"未生成预期产物：{generated}", EXIT_OPERATION_ERROR)
            staged[output_format] = generated
        commit_artifacts(
            staged,
            targets,
            overwrite=args.overwrite,
            backup_dir=temp_dir,
            input_path=audio_path,
        )
    except PermissionError:
        raise
    except Exception as error:
        if isinstance(error, MwtCliError):
            raise
        fail(f"转写产物写入失败：{error}", EXIT_OPERATION_ERROR)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    segments = result.get("segments", [])
    payload = {
        "command": "transcribe",
        "status": "ok",
        "input": str(audio_path),
        "model": {
            "repo": model.get("repo") or config.model_repo,
            "revision": model.get("revision") or config.model_revision,
            "path": str(config.model_dir),
        },
        "language": result.get("language"),
        "duration_seconds": round(duration, 3),
        "segments": len(segments),
        "outputs": [str(targets[item]) for item in formats],
        "summary": f"已生成 {len(formats)} 个转写产物",
    }
    output(payload, args.format)
    return 0
