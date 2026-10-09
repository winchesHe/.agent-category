"""``edit`` subcommand — 由匹配原作者的 Bot/User actor 更新消息。

Examples
--------

    python3 scripts/slack.py edit \\
        --channel C0123456 --ts 1700000000.000200 \\
        --text 'Updated content'

    python3 scripts/slack.py edit \\
        --url 'https://x.slack.com/archives/C0123/p1700000000000200' \\
        --text-file /tmp/updated.md
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import cache
from .block_kit import compile_message, load_blocks_file
from .config import Config
from .errors import InvalidArgument
from .output import emit
from .send_content import preview_digest
from .urls import parse_permalink
from .write_target import select_message_author


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "edit",
        help="edit a message authored by a configured Bot/User actor (chat.update)",
        description=(
            "Update a message after matching its original Bot/User author. "
            "The selected token must have chat:write."
        ),
    )
    p.add_argument(
        "--channel",
        default=None,
        help="channel id (C0...) — required if --url is not given",
    )
    p.add_argument(
        "--ts",
        default=None,
        help="message timestamp to edit — required if --url is not given",
    )
    p.add_argument(
        "--url",
        default=None,
        help="Slack permalink (alternative to --channel + --ts)",
    )
    p.add_argument(
        "--thread-ts",
        dest="thread_ts",
        default=None,
        help="thread root ts；使用 channel+ts 编辑 reply 时必填",
    )
    p.add_argument(
        "--text",
        default=None,
        help="new Markdown content, or fallback when --blocks-file is supplied",
    )
    p.add_argument(
        "--text-file",
        dest="text_file",
        default=None,
        help="read new content from a file (alternative to --text)",
    )
    p.add_argument(
        "--blocks-file",
        dest="blocks_file",
        default=None,
        help="用非空 Block Kit 数组替换消息；按组件 schema 使用 mrkdwn/rich_text 等",
    )
    p.add_argument(
        "--mention-mode", choices=("resolve", "literal"), default="literal",
        help="how to handle human-style mentions in Markdown and Block Kit",
    )
    p.add_argument(
        "--format", dest="format_name", choices=("markdown",),
        default="markdown", help="默认 Markdown；--blocks-file 自动切换 Block Kit",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--confirm-preview", default=None)
    p.add_argument("--allow-broadcast", action="store_true")
    p.add_argument("--allow-usergroup-mention", action="store_true")
    p.add_argument(
        "--output",
        default=None,
        help='write JSON result to this file instead of stdout ("-" = stdout)',
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    channel_id, ts, thread_ts = _resolve_target(args)
    text = _resolve_text(args)
    blocks = load_blocks_file(getattr(args, "blocks_file", None))
    format_name = getattr(args, "format_name", "markdown")

    cfg = Config()

    if cfg.allowed_channels and channel_id not in cfg.allowed_channels:
        raise InvalidArgument(
            f"channel {channel_id!r} is not in SLACK_SKILL_ALLOWED_CHANNELS"
        )

    ctx, original = select_message_author(
        cfg, channel_id=channel_id, ts=ts, thread_ts=thread_ts
    )
    mention_mode = getattr(args, "mention_mode", "literal")
    if mention_mode == "resolve":
        cache.ensure_fresh(cfg, ("users", "channels"), client=ctx.read_client())
    compiled, compiled_blocks = compile_message(
        text, blocks, format_name=format_name, mention_mode=mention_mode,
        allow_broadcast=getattr(args, "allow_broadcast", False),
        allow_usergroup_mention=getattr(args, "allow_usergroup_mention", False),
        context=ctx,
    )
    # 从空正文组装，避免 markdown_text 与遗留 text/blocks 同时提交。
    params: dict[str, Any] = {"channel": channel_id, "ts": ts, **compiled.params}
    params.pop("mrkdwn", None)  # chat.update 未声明此参数。
    mentions, broadcasts, warnings = compiled.mentions, compiled.broadcasts, compiled.warnings
    if compiled_blocks is not None:
        params["blocks"] = compiled_blocks.blocks
        mentions += compiled_blocks.mentions
        broadcasts += compiled_blocks.broadcasts
        warnings += compiled_blocks.warnings
    if ctx.selected == "bot":
        params["as_user"] = True
    digest = preview_digest({
        "team_id": ctx.identity.team_id, "principal_id": ctx.identity.principal_id,
        "actor": ctx.selected, "format": "block_kit" if blocks is not None else "markdown",
        "request": params,
        "original": {key: original.get(key) for key in ("text", "blocks", "edited")},
    })
    expected = getattr(args, "confirm_preview", None)
    if expected and expected != digest:
        raise InvalidArgument(f"preview digest 已变化：expected={expected}, actual={digest}")
    if getattr(args, "dry_run", False):
        emit({
            "status": "preview", "operation_status": "succeeded",
            "channel": channel_id, "ts": ts, "thread_ts": thread_ts,
            "format": "block_kit" if blocks is not None else "markdown",
            "original_author": ctx.identity.principal_id,
            "original": {key: original.get(key) for key in ("text", "blocks")},
            "compiled": params, "mentions": list(mentions), "broadcasts": list(broadcasts),
            "warnings": list(ctx.warnings) + list(warnings),
            "preview_digest": digest, "would_call": "chat.update",
        }, output=args.output)
        return 0
    response = ctx.write_client().call("chat.update", **params)

    result: dict[str, Any] = {
        "channel": channel_id,
        "ts": ts,
        "thread_ts": thread_ts,
        "operation_status": "succeeded",
        "result": "edited",
        "original_author": ctx.identity.principal_id,
        "preview_digest": digest,
        "warnings": list(ctx.warnings) + list(warnings),
        "message": response.get("message") or {"text": response.get("text")},
    }
    emit(result, output=args.output)
    return 0


def _resolve_target(args: argparse.Namespace) -> tuple[str, str, str | None]:
    """Return (channel_id, ts, thread_ts) from URL or explicit args."""
    if args.url:
        parsed = parse_permalink(args.url)
        root = parsed["thread_ts"] if parsed["thread_ts"] != parsed["ts"] else None
        return parsed["channel_id"], parsed["ts"], root

    if not args.channel:
        raise InvalidArgument("provide --channel or --url")
    if not args.ts:
        raise InvalidArgument("provide --ts or --url")
    return args.channel, args.ts, args.thread_ts


def _resolve_text(args: argparse.Namespace) -> str:
    """Return validated message text from --text or --text-file."""
    if args.text_file is not None and args.text is not None:
        raise InvalidArgument("--text 与 --text-file 只能使用一个")
    if args.text_file:
        path = Path(args.text_file).expanduser().resolve()
        if not path.exists():
            raise InvalidArgument(f"text file not found: {path}")
        text = path.read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        raise InvalidArgument("provide either --text or --text-file")

    if not text:
        raise InvalidArgument("message text is empty")
    return text


__all__ = ["register", "run"]
