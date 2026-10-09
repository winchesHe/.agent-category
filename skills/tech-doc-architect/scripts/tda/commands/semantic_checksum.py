"""检查多种输出是否保留相同的规范化技术结论。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tda.errors import EXIT_INPUT, EXIT_OK, EXIT_VALIDATION, error_payload
from tda.formatter import add_format_argument, output


def validate_checksum(payload: Any, base_dir: Path) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["checksum 根节点必须是 object"]

    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims or not all(
        isinstance(claim, str) and claim.strip() for claim in claims
    ):
        errors.append("claims 必须是非空字符串数组")

    outputs = payload.get("outputs")
    if not isinstance(outputs, dict) or len(outputs) < 2:
        errors.append("outputs 必须至少包含两个载体")
        return errors

    resolved_base = base_dir.resolve()
    for output_name, raw_paths in outputs.items():
        if not isinstance(output_name, str) or not output_name.strip():
            errors.append("outputs 的载体名称必须是非空字符串")
            continue
        if not isinstance(raw_paths, list) or not raw_paths:
            errors.append(f"outputs.{output_name} 必须包含至少一个文本文件")
            continue

        chunks: list[str] = []
        for raw_path in raw_paths:
            if not isinstance(raw_path, str) or not raw_path.strip():
                errors.append(f"outputs.{output_name} 包含无效路径")
                continue
            path = (resolved_base / raw_path).resolve()
            try:
                path.relative_to(resolved_base)
            except ValueError:
                errors.append(f"outputs.{output_name} 路径越出 checksum 目录: {raw_path}")
                continue
            if not path.is_file():
                errors.append(f"outputs.{output_name} 文件不存在: {raw_path}")
                continue
            try:
                chunks.append(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError) as exc:
                errors.append(f"outputs.{output_name} 无法读取 {raw_path}: {exc}")

        combined = "\n".join(chunks)
        if isinstance(claims, list):
            for claim in claims:
                if isinstance(claim, str) and claim.strip() and claim not in combined:
                    errors.append(f"outputs.{output_name} 缺少规范化结论: {claim}")

    return errors


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "validate-semantic-checksum",
        help="校验多个载体的规范化技术结论",
    )
    parser.add_argument("path", type=Path)
    add_format_argument(parser)
    parser.set_defaults(_handler=run)


def run(args: argparse.Namespace) -> int:
    target = args.path.resolve()
    if not target.is_file():
        payload = error_payload(
            "validate-semantic-checksum",
            str(target),
            f"checksum 文件不存在: {target}",
        )
        output(payload, args.format)
        return EXIT_INPUT

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = error_payload(
            "validate-semantic-checksum",
            str(target),
            f"无法读取 checksum: {exc}",
        )
        output(result, args.format)
        return EXIT_INPUT

    errors = validate_checksum(payload, target.parent)
    result = {
        "ok": not errors,
        "command": "validate-semantic-checksum",
        "target": str(target),
        "message": (
            "多载体语义校验和通过"
            if not errors
            else f"语义校验和失败，共 {len(errors)} 项"
        ),
        "errors": errors,
    }
    output(result, args.format)
    return EXIT_OK if not errors else EXIT_VALIDATION
