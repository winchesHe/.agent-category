"""Upload one validated image attachment to a Jira issue."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ji.client import JiraClient
from ji.config import Config
from ji.errors import UsageError
from ji.formatter import output
from ji.parsing import SUPPORTED_IMAGE_MIMETYPES, detect_supported_image_mimetype, parse_issue_key, safe_filename


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "upload-attachment",
        help="Upload one PNG/JPEG/GIF/WebP attachment; dry-run unless --execute is set",
    )
    parser.add_argument("issue", help="Jira key, Jira URL, or Slack mrkdwn Jira link")
    parser.add_argument("image", help="Local PNG/JPEG/GIF/WebP path")
    parser.add_argument("--execute", action="store_true", help="Actually upload the image")
    parser.add_argument("--format", choices=("json", "human", "summary"), default="json")
    parser.set_defaults(_handler=run)


def inspect_image(path: Path, *, max_bytes: int) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise UsageError(f"image must be an existing regular file: {resolved}")
    size = resolved.stat().st_size
    if size <= 0:
        raise UsageError(f"image is empty: {resolved}")
    if size > max_bytes:
        raise UsageError(f"image too large: {size}bytes,max:{max_bytes}")
    body = resolved.read_bytes()
    mime_type = detect_supported_image_mimetype(body)
    if mime_type not in SUPPORTED_IMAGE_MIMETYPES:
        raise UsageError(f"unsupported image magic bytes: {resolved}")
    return {
        "path": resolved,
        "filename": safe_filename(resolved.name),
        "mime_type": mime_type,
        "size_bytes": size,
        "body": body,
    }


def run(args: argparse.Namespace, config: Config) -> int:
    issue_key = parse_issue_key(args.issue)
    image = inspect_image(Path(args.image), max_bytes=config.max_attachment_bytes)
    result: dict[str, Any] = {
        "schema_version": 1,
        "command": "upload-attachment",
        "ok": True,
        "dry_run": not args.execute,
        "issue_key": issue_key,
        "image": {
            "path": str(image["path"]),
            "filename": image["filename"],
            "mime_type": image["mime_type"],
            "size_bytes": image["size_bytes"],
        },
    }
    if args.execute:
        client = JiraClient(config)
        result["attachments"] = client.upload_image_attachment(
            issue_key,
            filename=image["filename"],
            mime_type=image["mime_type"],
            body=image["body"],
        )
    output(result, fmt=args.format)
    return 0
