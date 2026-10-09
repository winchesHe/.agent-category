"""通过 reactions.add / reactions.remove 添加或移除当前身份的表情。

Bot/User token 均需 reactions:write；移除时必须固定 actor。

Examples
--------

    python3 scripts/slack.py react \\
        --emoji white_check_mark \\
        --channel C0123456 --ts 1700000000.000200

    python3 scripts/slack.py react \\
        --emoji eyes \\
        --url 'https://x.slack.com/archives/C0123/p1700000000000200'
"""

from __future__ import annotations

import argparse
from typing import Any

from .actor import requested_for, select_write_target
from .config import Config
from .errors import InvalidArgument, SlackAPIError
from .output import emit
from .urls import parse_permalink


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "react",
        help="添加或移除消息表情（reactions.add / reactions.remove）",
        description=(
            "默认添加表情；--remove 移除固定 Bot/User actor 的表情。"
            "所选 token 需要 reactions:write。"
        ),
    )
    p.add_argument(
        "--remove",
        action="store_true",
        help="移除表情；使用 --as bot|user 或固定 SLACK_WRITE_ACTOR，禁止 auto",
    )
    p.add_argument(
        "--emoji",
        required=True,
        help="emoji name without colons (e.g. white_check_mark, eyes, +1)",
    )
    p.add_argument(
        "--channel",
        default=None,
        help="channel id (C0...) — required if --url is not given",
    )
    p.add_argument(
        "--ts",
        default=None,
        help="message timestamp — required if --url is not given",
    )
    p.add_argument(
        "--url",
        default=None,
        help="Slack permalink (alternative to --channel + --ts)",
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
    channel_id, ts = _resolve_target(args)

    # Strip colons if user accidentally includes them.
    emoji = args.emoji.strip(":")

    if not emoji:
        raise InvalidArgument("--emoji cannot be empty")

    if cfg.allowed_channels and channel_id not in cfg.allowed_channels:
        raise InvalidArgument(
            f"channel {channel_id!r} is not in SLACK_SKILL_ALLOWED_CHANNELS"
        )

    if args.remove and requested_for("write", cfg) == "auto":
        raise InvalidArgument(
            "react --remove 必须固定原添加者身份：使用 --as bot 或 --as user，"
            "或将 SLACK_WRITE_ACTOR 配置为 bot/user"
        )

    ctx, _channel, reachable = select_write_target(cfg, channel_id)
    write = ctx.write_client()

    method = "reactions.remove" if args.remove else "reactions.add"
    already = False
    try:
        write.call(method, channel=channel_id, timestamp=ts, name=emoji)
    except SlackAPIError as exc:
        if not args.remove and exc.error == "already_reacted":
            already = True
        else:
            raise

    result: dict[str, Any] = {
        "channel": channel_id,
        "ts": ts,
        "emoji": emoji,
        "operation_status": "succeeded",
        "result": "removed" if args.remove else "reacted",
        "reachable": reachable,
    }
    if not args.remove:
        result["already_reacted"] = already
    emit(result, output=args.output)
    return 0


def _resolve_target(args: argparse.Namespace) -> tuple[str, str]:
    """Return (channel_id, ts) from --url or --channel + --ts."""
    if args.url:
        parsed = parse_permalink(args.url)
        return parsed["channel_id"], parsed["ts"]

    if not args.channel:
        raise InvalidArgument("provide --channel or --url")
    if not args.ts:
        raise InvalidArgument("provide --ts or --url")
    return args.channel, args.ts


__all__ = ["register", "run"]
