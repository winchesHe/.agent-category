"""校验 Markdown / Obsidian 技术文档集。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from tda.errors import EXIT_OK, EXIT_VALIDATION
from tda.formatter import add_format_argument, output


MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
WIKILINK = re.compile(r"(!?)\[\[([^\]]+)\]\]")
H1 = re.compile(r"(?m)^#\s+\S")
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_remote(target: str) -> bool:
    lowered = target.lower()
    return lowered.startswith(("http://", "https://", "mailto:", "tel:", "data:"))


def _clean_target(target: str) -> str:
    cleaned = target.strip().strip("<>")
    cleaned = cleaned.split("#", 1)[0].split("?", 1)[0]
    return unquote(cleaned).strip()


def _is_absolute(target: str) -> bool:
    return target.startswith(("/", "~/", "\\\\")) or bool(
        WINDOWS_ABSOLUTE.match(target)
    )


def _resolve_markdown(source: Path, target: str) -> Optional[Path]:
    cleaned = _clean_target(target)
    if not cleaned or _is_remote(cleaned):
        return None
    return (source.parent / cleaned).resolve()


def _resolve_wikilink(source: Path, root: Path, raw_target: str) -> Optional[Path]:
    target = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
    if not target:
        return None
    if _is_absolute(target):
        return Path(target)

    relative = Path(target)
    candidates = [source.parent / relative, root / relative]
    if relative.suffix:
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        return candidates[0].resolve()

    note_candidates = [candidate.with_suffix(".md") for candidate in candidates]
    for candidate in note_candidates:
        if candidate.exists():
            return candidate.resolve()

    matches = [path for path in root.rglob("*.md") if path.stem == relative.name]
    if len(matches) == 1:
        return matches[0].resolve()
    return note_candidates[0].resolve()


def _choose_overview(
    root: Path,
    files: list[Path],
    requested: Optional[str],
) -> Path:
    if requested:
        return (root / requested).resolve()

    exact_names = (
        "README.md",
        "overview.md",
        "architecture-overview.md",
        "系统架构概览.md",
    )
    by_name = {path.name: path for path in files}
    for name in exact_names:
        if name in by_name:
            return by_name[name].resolve()

    candidates = [
        path for path in files if "overview" in path.stem.lower() or "概览" in path.stem
    ]
    if len(candidates) == 1:
        return candidates[0].resolve()
    raise ValueError("无法唯一识别 Overview；请使用 --overview 指定相对路径")


def validate_docset(
    root: Path,
    output_format: str,
    overview_arg: Optional[str],
) -> list[str]:
    errors: list[str] = []
    root = root.resolve()
    if not root.is_dir():
        return [f"文档目录不存在: {root}"]

    files = sorted(root.rglob("*.md"))
    if not files:
        return ["文档目录中没有 Markdown 文件"]

    try:
        overview = _choose_overview(root, files, overview_arg)
    except ValueError as exc:
        errors.append(str(exc))
        overview = files[0].resolve()

    resolved_files = {path.resolve() for path in files}
    if overview not in resolved_files:
        errors.append(f"Overview 不存在或不在文档目录内: {overview}")

    overview_targets: set[Path] = set()

    for path in files:
        relative = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{relative}: 无法读取 UTF-8 文档: {exc}")
            continue

        if not H1.search(text):
            errors.append(f"{relative}: 缺少一级标题")

        if re.search(
            r"(?:^|[\s(])(?:/Users/|/home/|~/|[A-Za-z]:[\\/])",
            text,
        ):
            errors.append(f"{relative}: 包含本机绝对路径")

        if output_format == "markdown" and WIKILINK.search(text):
            errors.append(f"{relative}: 通用 Markdown 不应包含 Obsidian wikilink")
        if output_format == "markdown" and re.search(
            r"(?m)^>\s*\[![^\]]+\]",
            text,
        ):
            errors.append(f"{relative}: 通用 Markdown 不应依赖 Obsidian callout")

        for raw_target in MARKDOWN_LINK.findall(text):
            cleaned = _clean_target(raw_target)
            if not cleaned or _is_remote(cleaned):
                continue
            if _is_absolute(cleaned):
                errors.append(f"{relative}: 链接使用绝对路径 {raw_target}")
                continue
            resolved = _resolve_markdown(path, raw_target)
            if resolved is not None and not resolved.exists():
                errors.append(f"{relative}: 链接目标不存在 {raw_target}")
            elif path.resolve() == overview and resolved is not None:
                overview_targets.add(resolved)

        if output_format == "obsidian":
            for _, raw_target in WIKILINK.findall(text):
                target_without_alias = (
                    raw_target.split("|", 1)[0].split("#", 1)[0].strip()
                )
                if _is_absolute(target_without_alias):
                    errors.append(f"{relative}: wikilink 使用绝对路径 {raw_target}")
                    continue
                resolved = _resolve_wikilink(path, root, raw_target)
                if resolved is not None and not resolved.exists():
                    errors.append(f"{relative}: wikilink 或嵌入目标不存在 {raw_target}")
                elif path.resolve() == overview and resolved is not None:
                    overview_targets.add(resolved)

    for path in files:
        resolved = path.resolve()
        if resolved == overview:
            continue
        if resolved not in overview_targets:
            errors.append(f"{path.relative_to(root)}: Overview 没有直接导航到该专题")

    return errors


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "validate-docset",
        help="校验 Markdown 或 Obsidian 文档集",
    )
    parser.add_argument(
        "--document-format",
        dest="doc_format",
        choices=("markdown", "obsidian"),
        required=True,
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--overview", help="相对 --root 的 Overview 路径")
    add_format_argument(parser)
    parser.set_defaults(_handler=run)


def run(args: argparse.Namespace) -> int:
    target = args.root.resolve()
    errors = validate_docset(target, args.doc_format, args.overview)
    result = {
        "ok": not errors,
        "command": "validate-docset",
        "target": str(target),
        "document_format": args.doc_format,
        "message": (
            f"{args.doc_format} 文档集校验通过"
            if not errors
            else f"文档集校验失败，共 {len(errors)} 项"
        ),
        "errors": errors,
    }
    output(result, args.format)
    return EXIT_OK if not errors else EXIT_VALIDATION
