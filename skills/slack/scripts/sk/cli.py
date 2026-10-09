"""CLI entry point — argparse with subparsers.

Every subcommand is registered on the same parser so ``slack.py --help``
shows the full surface area.  Errors raised by any subcommand flow through
:func:`main`, which appends a short, actionable hint for well-known Slack
failure codes (``channel_not_found`` → suggest ``channels --query``, etc.).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from . import (
    cmd_cache_refresh,
    cmd_channels,
    cmd_delete,
    cmd_doctor,
    cmd_edit,
    cmd_files_download,
    cmd_files_upload,
    cmd_get,
    cmd_history,
    cmd_react,
    cmd_replies,
    cmd_resolve,
    cmd_search,
    cmd_send,
    cmd_users,
)
from .actor import (
    current,
    read_attempt,
    read_fallback_error,
    select_read,
    select_search,
    set_requested,
)
from .config import Config
from .errors import (
    RateLimitBudgetExceeded,
    SlackAPIError,
    SlackSkillError,
    WriteResultUnknown,
)
from .output import emit
from .version import VERSION


# Known Slack API error codes → short, actionable hint.  Appended to the
# error line printed to stderr so the AI / human reader gets a next step.
_ERROR_HINTS: dict[str, str] = {
    "channel_not_found": (
        "try `slack.py channels --query <name>` to find the right id, "
        "or run `slack.py cache_refresh` if the name is new."
    ),
    "not_in_channel": (
        "the selected actor isn't a member of this channel. With auto, configure a "
        "reachable User or Bot token for preflight; with an explicit actor, "
        "join the channel or select another actor."
    ),
    "user_not_found": (
        "try `slack.py users --query <name>` or pass a full U0... id."
    ),
    "not_allowed_token_type": (
        "this endpoint needs a user token (xoxp). "
        "Set SLACK_USER_TOKEN in <SKILL_DIR>/.env — see .env.example."
    ),
    "missing_scope": (
        "the token is missing a required OAuth scope. "
        "See .env.example for the scope list and re-install the Slack app."
    ),
    "invalid_auth": (
        "token is invalid / expired. Check <SKILL_DIR>/.env; xoxp tokens can "
        "also be invalidated by SSO."
    ),
    "not_authed": (
        "no token sent. Set SLACK_BOT_TOKEN (or SLACK_USER_TOKEN for "
        "search) — see .env.example."
    ),
    "ratelimited": (
        "the skill already honours Retry-After; if you keep hitting this, "
        "lower concurrency or wait a minute."
    ),
    "message_not_found": (
        "permalink may be wrong, the message may be deleted, or the token "
        "cannot see that channel. For thread replies, make sure the URL "
        "has `?thread_ts=<root_ts>`."
    ),
    "file_not_found": (
        "the file id is wrong or the token can't see it. "
        "Use the id from a `get`/`replies` response (starts with F...)."
    ),
    "thread_not_found": (
        "this message isn't the root of a thread, or the thread has no "
        "replies yet. Use `get` instead, or pass a reply permalink."
    ),
    "no_permission": (
        "the selected actor lacks permission. Check that actor's write scopes and "
        "conversation membership; use doctor for read-only identity diagnostics."
    ),
    "cant_update_message": (
        "the selected actor is not the original message author. Use --as auto to "
        "match a configured Bot/User identity, or ask the original author."
    ),
    "cant_delete_message": (
        "the selected actor is not the original message author. Use --as auto to "
        "match a configured Bot/User identity, or leave the message in place."
    ),
    "already_reacted": (
        "the selected actor already added this reaction to the message. "
        "No action needed."
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slack.py",
        description=(
            "Slack skill.  Read paths enforce a read-only Web API whitelist; "
            "write paths (send/edit/delete/react/files_upload) go through a "
            "separate write-method whitelist.  See SKILL.md for "
            "AI-facing usage, README.md for a human quickstart."
        ),
        epilog=(
            "Tokens live in <SKILL_DIR>/.env (see .env.example).  "
            "Large results should use --output <file> to avoid flooding "
            "the caller's context."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"slack {VERSION} (Bot/User actor contract; 15 subcommands)",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    cmd_get.register(sub)
    cmd_replies.register(sub)
    cmd_history.register(sub)
    cmd_channels.register(sub)
    cmd_users.register(sub)
    cmd_resolve.register(sub)
    cmd_search.register(sub)
    cmd_files_download.register(sub)
    cmd_files_upload.register(sub)
    cmd_cache_refresh.register(sub)
    cmd_doctor.register(sub)

    # Write commands (message operations).
    cmd_send.register(sub)
    cmd_edit.register(sub)
    cmd_delete.register(sub)
    cmd_react.register(sub)

    for command_name, command_parser in sub.choices.items():
        if command_name == "doctor":
            continue
        command_parser.add_argument(
            "--as",
            dest="actor",
            choices=("auto", "bot", "user"),
            default=None,
            help=(
                "Slack actor. Defaults to SLACK_READ_ACTOR/SLACK_WRITE_ACTOR; "
                "explicit bot/user never falls back."
            ),
        )

    return parser


def _format_error(exc: BaseException) -> str:
    """Render an exception as a single-line ``error: ...`` message with hint.

    Hints are looked up on the original :class:`SlackAPIError`; when a
    helper wraps the API error (e.g. ``channels.resolve_channel`` raises
    :class:`InvalidArgument` with ``raise ... from err``), we walk
    ``__cause__`` so the hint still surfaces.
    """
    line = f"error: {exc}"
    api_err: SlackAPIError | None = None
    cursor: BaseException | None = exc
    seen: set[int] = set()
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        if isinstance(cursor, SlackAPIError):
            api_err = cursor
            break
        cursor = cursor.__cause__ or cursor.__context__
    if api_err is not None:
        hint = _ERROR_HINTS.get(api_err.error)
        if hint:
            line = f"{line}\nhint: {hint}"
    return line


def _run_read_command(args: argparse.Namespace, cfg: Config) -> int:
    """执行普通读取，并且只在主事务尚无响应时允许 User→Bot fallback。"""

    with read_attempt() as attempt:
        try:
            return int(args.func(args) or 0)
        except SlackSkillError as exc:
            ctx = current()
            code = read_fallback_error(exc)
            requested = getattr(args, "actor", None) or cfg.read_actor
            if (
                requested == "auto"
                and ctx is not None
                and ctx.selected == "user"
                and code
                and not attempt.primary_observed
            ):
                select_read(cfg, force="bot", fallback_reason=code)
                # Bot 重试是独立读取事务，不能继承 User 尝试的状态。
                with read_attempt():
                    return int(args.func(args) or 0)
            raise


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    set_requested(getattr(args, "actor", None))
    read_commands = {
        "get", "replies", "history", "channels", "users", "resolve",
        "files_download", "cache_refresh",
    }
    write_commands = {"send", "edit", "delete", "react", "files_upload"}

    try:
        if args.command in read_commands:
            cfg = Config()
            raw_channel = getattr(args, "channel", None)
            if raw_channel and cfg.allowed_channels:
                from .channels import looks_like_channel_id

                if looks_like_channel_id(raw_channel) and raw_channel not in cfg.allowed_channels:
                    from .errors import InvalidArgument

                    raise InvalidArgument(
                        f"channel {raw_channel!r} is not in SLACK_SKILL_ALLOWED_CHANNELS"
                    )
            select_read(cfg)
            return _run_read_command(args, cfg)
        elif args.command == "search":
            select_search(Config())
        return int(args.func(args) or 0)
    except WriteResultUnknown as exc:
        payload = dict(exc.payload)
        ctx = current()
        if ctx is not None:
            payload["actor"] = ctx.public()
        emit(payload, output=getattr(args, "output", None))
        return exc.exit_code
    except RateLimitBudgetExceeded as exc:
        payload = {
            "status": "failed",
            "retry_safe": True,
            "reason": (
                "rate_limit_retry_after_invalid"
                if exc.retry_after_seconds is None
                else "rate_limit_wait_budget_exceeded"
            ),
            "method": exc.method,
            "retry_after_seconds": exc.retry_after_seconds,
        }
        ctx = current()
        if ctx is not None:
            payload["actor"] = ctx.public()
        emit(payload, output=getattr(args, "output", None))
        return exc.exit_code
    except SlackSkillError as exc:
        ctx = current()
        if ctx is not None and args.command in write_commands:
            payload = {
                "status": "failed",
                "operation_status": "failed",
                "retry_safe": True,
                "reason": exc.error if isinstance(exc, SlackAPIError) else exc.__class__.__name__,
                "error": str(exc),
                "actor": ctx.public(),
            }
            if isinstance(exc, SlackAPIError):
                payload["method"] = exc.method
                if exc.detail:
                    try:
                        detail = json.loads(exc.detail)
                    except (TypeError, ValueError):
                        detail = None
                    if isinstance(detail, dict):
                        for key in ("needed", "provided"):
                            if detail.get(key) is not None:
                                payload[key] = detail[key]
            emit(payload, output=getattr(args, "output", None))
        else:
            line = _format_error(exc)
            if ctx is not None:
                line += (
                    f"\nactor: selected={ctx.selected}, source={ctx.source_env}, "
                    f"team_id={ctx.identity.team_id}, principal_id={ctx.identity.principal_id}"
                )
            print(line, file=sys.stderr)
        return getattr(exc, "exit_code", 1) or 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


__all__ = ["main", "build_parser"]
