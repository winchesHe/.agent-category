"""``files_upload`` subcommand.

Uploads one or more local files to a Slack channel using the v2 flow:

1. ``files.getUploadURLExternal``  → presigned URL + ``file_id``
2. POST raw bytes to that URL
3. ``files.completeUploadExternal`` → finalise + share to ``channel_id``,
   optionally with an ``initial_comment`` and / or ``thread_ts``.

Typical user flow this enables: "导出 X 之后顺手发到 #channel"。

Examples
--------

    # 单文件 + 评论
    python3 scripts/slack.py files_upload \\
        --channel '#release-notes' --file ./out/report.pdf \\
        --message '本周报告已生成'

    # 多文件 + thread 回复
    python3 scripts/slack.py files_upload --channel C0123456 \\
        --file a.csv --file b.csv --thread-ts 1700000000.000200

The selected Bot/User token needs ``files:write`` + ``chat:write`` and must
be able to access the target conversation.
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import re
import stat
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .errors import InvalidArgument, SlackAPIError, WriteResultUnknown
from .output import emit
from .send_content import compile_content
from .write_target import select_write_target_with_thread


MAX_VERIFIED_FILE_BYTES = 25 * 1024 * 1024
MAX_VERIFIED_TOTAL_BYTES = 100 * 1024 * 1024
MAX_VERIFIED_FILES = 20


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "files_upload",
        help="upload local file(s) to a Slack channel (optionally with a comment)",
        description=(
            "Upload one or more local files to a channel via Slack's v2 "
            "external upload flow. The selected Bot/User token needs "
            "files:write + chat:write and target visibility. Use this after "
            "exporting reports / "
            "screenshots to share them with the team."
        ),
    )
    p.add_argument(
        "--channel",
        required=True,
        help="target channel: id (C0...) or name (#release or release)",
    )
    p.add_argument(
        "--file",
        action="append",
        required=True,
        dest="files",
        help="local file path; pass --file multiple times to upload several",
    )
    p.add_argument(
        "--sha256",
        action="append",
        dest="sha256s",
        help=(
            "expected lowercase SHA-256 for the corresponding --file; pass once per file. "
            "Verified uploads use the checked bytes and are limited to 20 files, "
            "25 MiB per file, and 100 MiB total"
        ),
    )
    p.add_argument(
        "--filename",
        default=None,
        help="override the displayed filename (only valid when uploading a single file)",
    )
    p.add_argument(
        "--title",
        default=None,
        help="optional file title shown in Slack (defaults to filename)",
    )
    p.add_argument(
        "--message",
        "--initial-comment",
        dest="message",
        default=None,
        help="optional comment posted alongside the file(s)",
    )
    p.add_argument("--allow-broadcast", action="store_true")
    p.add_argument("--allow-usergroup-mention", action="store_true")
    p.add_argument(
        "--thread-ts",
        dest="thread_ts",
        default=None,
        help="reply into this thread root (e.g. 1700000000.000200)",
    )
    p.add_argument(
        "--output",
        default=None,
        help='write JSON report to this file instead of stdout ("-" = stdout)',
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = Config()

    paths = [_resolve_path(p) for p in args.files]
    expected_hashes = getattr(args, "sha256s", None) or []
    if expected_hashes and len(expected_hashes) != len(paths):
        raise InvalidArgument("--sha256 must be passed once for every --file")
    if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in expected_hashes):
        raise InvalidArgument("--sha256 must be a 64-character lowercase SHA-256")
    verified_payloads = _prepare_verified_payloads(paths, expected_hashes)
    if args.filename and len(paths) != 1:
        raise InvalidArgument("--filename can only be used with a single --file")

    ctx, channel, reachable, thread_warning = select_write_target_with_thread(
        cfg, args.channel, args.thread_ts
    )
    channel_id = channel.get("id")
    if not channel_id:
        raise InvalidArgument(f"could not resolve channel from {args.channel!r}")

    if cfg.allowed_channels and channel_id not in cfg.allowed_channels:
        raise InvalidArgument(
            f"channel {channel_id!r} is not in SLACK_SKILL_ALLOWED_CHANNELS"
        )

    write = ctx.write_client()
    compiled_comment = None
    if args.message:
        compiled_comment = compile_content(
            args.message,
            format_name="mrkdwn",
            mention_mode="literal",
            allow_broadcast=args.allow_broadcast,
            allow_usergroup_mention=args.allow_usergroup_mention,
            context=ctx,
        )

    completed_files: list[dict[str, Any]] = []
    for idx, path in enumerate(paths):
        display_name = args.filename if (args.filename and len(paths) == 1) else path.name
        verified_payload = verified_payloads[idx]
        size = len(verified_payload) if verified_payload is not None else path.stat().st_size
        if size <= 0:
            raise InvalidArgument(f"refusing to upload empty file: {path}")

        try:
            upload = write.call(
                "files.getUploadURLExternal",
                filename=display_name,
                length=size,
            )
        except WriteResultUnknown as exc:
            exc.payload.update(
                delivery_phase="get_upload_url",
                current_file={"name": display_name, "size": size},
                completed_files=list(completed_files),
            )
            raise
        upload_url = upload.get("upload_url")
        file_id = upload.get("file_id")
        if not upload_url or not file_id:
            raise SlackAPIError(
                "files.getUploadURLExternal",
                "missing_upload_url_or_file_id",
                detail=str(upload)[:200],
            )

        content_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
        try:
            write.put_bytes(
                upload_url,
                path,
                content_type=content_type,
                verified_bytes=verified_payload,
            )
        except WriteResultUnknown as exc:
            exc.payload.update(
                delivery_phase="bytes_upload",
                current_file={"id": file_id, "name": display_name, "size": size},
                completed_files=list(completed_files),
            )
            raise

        entry: dict[str, Any] = {"id": file_id, "title": args.title or display_name}
        completed_files.append(entry)

    complete_params: dict[str, Any] = {
        "files": completed_files,  # JSON-encoded by the client
        "channel_id": channel_id,
    }
    if compiled_comment is not None:
        complete_params["initial_comment"] = compiled_comment.params["text"]
    if args.thread_ts:
        complete_params["thread_ts"] = args.thread_ts

    try:
        completion = write.call("files.completeUploadExternal", **complete_params)
    except WriteResultUnknown as exc:
        exc.payload.update(
            delivery_phase="complete_upload",
            completed_files=list(completed_files),
            byte_uploaded_file_ids=[item["id"] for item in completed_files],
            channel=channel_id,
            thread_ts=args.thread_ts,
        )
        raise

    files_returned = completion.get("files") or completed_files
    result: dict[str, Any] = {
        "operation_status": "succeeded",
        "result": "uploaded",
        "channel": {"id": channel_id, "name": channel.get("name")},
        "reachable": reachable,
        "uploaded": [
            {
                "id": f.get("id"),
                "title": f.get("title"),
                "permalink": f.get("permalink"),
                "local_path": str(local),
            }
            for f, local in zip(files_returned, paths)
        ],
        "thread_ts": args.thread_ts,
        "initial_comment": (
            compiled_comment.params["text"] if compiled_comment is not None else None
        ),
        "broadcasts": (
            list(compiled_comment.broadcasts) if compiled_comment is not None else []
        ),
        "warnings": (
            list(compiled_comment.warnings) if compiled_comment is not None else []
        ) + ([thread_warning] if thread_warning else []),
        "summary": {
            "count": len(paths),
            "bytes": sum(
                len(payload) if payload is not None else path.stat().st_size
                for path, payload in zip(paths, verified_payloads)
            ),
        },
    }
    emit(result, output=args.output)
    return 0


def _resolve_path(raw: str) -> Path:
    unresolved = Path(raw).expanduser()
    if unresolved.is_symlink():
        raise InvalidArgument(f"symlink is not allowed: {raw}")
    path = unresolved.resolve()
    if not path.exists():
        raise InvalidArgument(f"file not found: {raw}")
    if not path.is_file():
        raise InvalidArgument(f"not a regular file: {raw}")
    return path


def _read_verified_payload(
    path: Path,
    expected_sha256: str,
    remaining_total_bytes: int = MAX_VERIFIED_TOTAL_BYTES,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise InvalidArgument(f"cannot safely open file: {path}: {exc}") from exc
    try:
        file_obj = os.fdopen(descriptor, "rb", closefd=True)
    except Exception:
        os.close(descriptor)
        raise
    with file_obj:
        before = os.fstat(file_obj.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise InvalidArgument(f"not a single-link regular file: {path}")
        if before.st_size > MAX_VERIFIED_FILE_BYTES:
            raise InvalidArgument("--sha256 verified uploads are limited to 25 MiB per file")
        if before.st_size > remaining_total_bytes:
            raise InvalidArgument("--sha256 verified uploads are limited to 100 MiB total")
        read_limit = min(
            before.st_size + 1,
            remaining_total_bytes + 1,
            MAX_VERIFIED_FILE_BYTES + 1,
        )
        payload = file_obj.read(read_limit)
        after = os.fstat(file_obj.fileno())
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_nlink != before.st_nlink
            or after.st_size != before.st_size
            or after.st_ctime_ns != before.st_ctime_ns
            or after.st_mtime_ns != before.st_mtime_ns
            or len(payload) != before.st_size
        ):
            raise InvalidArgument(f"file changed while reading: {path}")
    if len(payload) > MAX_VERIFIED_FILE_BYTES:
        raise InvalidArgument("--sha256 verified uploads are limited to 25 MiB per file")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise InvalidArgument(
            f"SHA-256 mismatch for {path}: expected {expected_sha256}, got {actual}"
        )
    return payload


def _prepare_verified_payloads(
    paths: list[Path], expected_hashes: list[str]
) -> list[Optional[bytes]]:
    if not expected_hashes:
        return [None] * len(paths)
    if len(paths) > MAX_VERIFIED_FILES:
        raise InvalidArgument(f"--sha256 mode accepts at most {MAX_VERIFIED_FILES} files")
    payloads: list[Optional[bytes]] = []
    total = 0
    for path, expected_hash in zip(paths, expected_hashes):
        payload = _read_verified_payload(
            path,
            expected_hash,
            remaining_total_bytes=MAX_VERIFIED_TOTAL_BYTES - total,
        )
        total += len(payload)
        if total > MAX_VERIFIED_TOTAL_BYTES:
            raise InvalidArgument("--sha256 verified uploads are limited to 100 MiB total")
        payloads.append(payload)
    return payloads


__all__ = ["register", "run"]
