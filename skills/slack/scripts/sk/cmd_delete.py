"""``delete`` subcommand — 由匹配原作者的 Bot/User actor 删除消息。

Examples
--------

    python3 scripts/slack.py delete \\
        --channel C0123456 --ts 1700000000.000200

    python3 scripts/slack.py delete \\
        --url 'https://x.slack.com/archives/C0123/p1700000000000200'
"""

from __future__ import annotations

import argparse
from typing import Any

from .config import Config
from .errors import InvalidArgument
from .output import emit
from .urls import parse_permalink
from .write_target import select_message_author


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "delete",
        help="delete a message authored by a configured Bot/User actor (chat.delete)",
        description=(
            "Delete a message after matching its original Bot/User author. "
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
        help="message timestamp to delete — required if --url is not given",
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
        help="thread root ts；使用 channel+ts 删除 reply 时必填",
    )
    p.add_argument(
        "--output",
        default=None,
        help='write JSON result to this file instead of stdout ("-" = stdout)',
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = Config()

    # Resolve channel + ts from permalink or explicit args.
    channel_id, ts, thread_ts = _resolve_target(args)

    if cfg.allowed_channels and channel_id not in cfg.allowed_channels:
        raise InvalidArgument(
            f"channel {channel_id!r} is not in SLACK_SKILL_ALLOWED_CHANNELS"
        )

    ctx, original = select_message_author(
        cfg, channel_id=channel_id, ts=ts, thread_ts=thread_ts
    )
    ctx.write_client().call("chat.delete", channel=channel_id, ts=ts)

    result: dict[str, Any] = {
        "channel": channel_id,
        "ts": ts,
        "thread_ts": thread_ts,
        "deleted": True,
        "operation_status": "succeeded",
        "result": "deleted",
        "original_author": ctx.identity.principal_id,
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


__all__ = ["register", "run"]
