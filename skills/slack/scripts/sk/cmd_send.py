"""``send``：身份安全的 Markdown/Block Kit 发送与 dry-run。"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import cache
from .actor import ActorContext, activate, requested_for
from .block_kit import CompiledBlocks, compile_message, load_blocks_file
from .config import Config
from .errors import (
    ActorSelectionError,
    InvalidArgument,
    MentionResolutionError,
    SlackAPIError,
)
from .lookups import build_lookups
from .message import normalise_message
from .output import emit
from .send_content import (
    CompiledContent,
    preview_digest,
)
from .write_target import select_write_target_with_thread


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "send",
        help="send Markdown or Block Kit with actor preflight",
    )
    parser.add_argument("--channel", required=True, help="target C/G/D id or #name")
    text_group = parser.add_mutually_exclusive_group(required=True)
    text_group.add_argument("--text", default=None)
    text_group.add_argument("--text-file", dest="text_file", default=None)
    parser.add_argument(
        "--blocks-file",
        dest="blocks_file",
        default=None,
        help="非空 Block Kit 数组；按组件 schema 使用 mrkdwn/rich_text 等；需 text fallback",
    )
    parser.add_argument("--thread-ts", dest="thread_ts", default=None)
    parser.add_argument(
        "--format", dest="format_name", choices=("markdown",),
        default="markdown", help="默认 Markdown；--blocks-file 自动切换 Block Kit",
    )
    parser.add_argument(
        "--mention-mode", choices=("resolve", "literal"), default=None,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-preview", default=None)
    parser.add_argument("--allow-broadcast", action="store_true")
    parser.add_argument("--allow-usergroup-mention", action="store_true")
    parser.add_argument("--unfurl-links", action="store_true", default=False)
    parser.add_argument("--output", default=None)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    text = _resolve_text(args)
    blocks = load_blocks_file(getattr(args, "blocks_file", None))

    cfg = Config()
    ctx, channel, reachable, thread_warning = select_write_target_with_thread(
        cfg, args.channel, args.thread_ts
    )
    channel_id = str(channel.get("id") or "")
    refresh = cache.ensure_fresh(
        cfg, ("users", "channels"), client=ctx.read_client()
    )
    mention_mode = args.mention_mode or "resolve"
    try:
        compiled, compiled_blocks = _compile_payload(
            text, blocks, args=args, mention_mode=mention_mode, context=ctx
        )
    except MentionResolutionError as mention_error:
        if requested_for("write", cfg) != "auto" or ctx.selected != "user":
            raise
        try:
            ctx, channel, reachable, thread_warning = select_write_target_with_thread(
                cfg, args.channel, args.thread_ts, force="bot"
            )
        except Exception as fallback_error:
            if isinstance(fallback_error, ActorSelectionError):
                raise mention_error
            raise
        ctx = activate(replace(ctx, fallback_reason="user_mention_resolution_failed"))
        channel_id = str(channel.get("id") or "")
        refresh = cache.ensure_fresh(
            cfg, ("users", "channels"), client=ctx.read_client()
        )
        compiled, compiled_blocks = _compile_payload(
            text, blocks, args=args, mention_mode=mention_mode, context=ctx
        )
    request_params: dict[str, Any] = {
        "channel": channel_id,
        **compiled.params,
        "unfurl_links": args.unfurl_links,
        "unfurl_media": False,
        "reply_broadcast": False,
    }
    if args.thread_ts:
        request_params["thread_ts"] = args.thread_ts
    if compiled_blocks is not None:
        request_params["blocks"] = compiled_blocks.blocks

    block_mentions = compiled_blocks.mentions if compiled_blocks else ()
    block_broadcasts = compiled_blocks.broadcasts if compiled_blocks else ()
    block_warnings = compiled_blocks.warnings if compiled_blocks else ()

    digest_input = {
        "team_id": ctx.identity.team_id,
        "actor": ctx.selected,
        "principal_id": ctx.identity.principal_id,
        "channel": channel_id,
        "format": "block_kit" if blocks is not None else "markdown",
        "request": request_params,
    }
    digest = preview_digest(digest_input)
    if args.confirm_preview and args.confirm_preview != digest:
        raise InvalidArgument(
            f"preview digest 已变化：expected={args.confirm_preview}, actual={digest}"
        )

    preview = {
        "status": "preview",
        "operation_status": "succeeded",
        "channel": {
            "input": args.channel,
            "id": channel_id,
            "name": channel.get("name"),
            "reachable": reachable,
        },
        "thread_ts": args.thread_ts,
        "format": "block_kit" if blocks is not None else "markdown",
        "compiled": {
            **compiled.params,
            **({"blocks": compiled_blocks.blocks} if compiled_blocks else {}),
        },
        "mentions": list(compiled.mentions) + list(block_mentions),
        "broadcasts": list(compiled.broadcasts) + list(block_broadcasts),
        "warnings": list(ctx.warnings) + list(compiled.warnings) + list(block_warnings)
        + ([thread_warning] if thread_warning else []),
        "cache_refresh": refresh,
        "preview_digest": digest,
        "would_call": "chat.postMessage",
        "request_options": {
            "unfurl_links": args.unfurl_links,
            "unfurl_media": False,
            "reply_broadcast": False,
        },
    }
    if args.dry_run:
        emit(preview, output=args.output)
        return 0

    response = ctx.write_client().call("chat.postMessage", **request_params)
    raw_message = response.get("message") or {
        "ts": response.get("ts"),
        "thread_ts": args.thread_ts,
        "text": compiled.params.get("text") or "",
        "blocks": compiled_blocks.blocks if compiled_blocks else None,
    }
    server_channel = str(response.get("channel") or channel_id)
    server_ts = str(raw_message.get("ts") or response.get("ts") or "")
    warnings = list(ctx.warnings) + list(compiled.warnings) + list(block_warnings)
    if thread_warning:
        warnings.append(thread_warning)
    if args.thread_ts:
        returned_root = raw_message.get("thread_ts")
        if returned_root != args.thread_ts:
            warnings.append(
                "CRITICAL: Slack 返回的 thread_ts 与请求 root 不一致；消息已发送，禁止重试"
            )

    # chat.postMessage 已确认成功后，任何辅助渲染或 permalink 失败都只能
    # 降级成 warning；绝不能把已发送的消息伪装成失败而诱发重试。
    try:
        user_cache = cache.load_users(ctx.cache_dir)
        user_names = {
            uid: cache.user_display_name(user) or uid for uid, user in user_cache.items()
        }
        user_lookup, channel_lookup, subteam_lookup, _ = build_lookups(cfg, user_names)
        message = normalise_message(
            raw_message,
            channel_id=server_channel,
            user_names=user_names,
            user_lookup=user_lookup,
            channel_lookup=channel_lookup,
            subteam_lookup=subteam_lookup,
            workspace_base=ctx.identity.workspace_url,
            known_actor=ctx.public(),
        )
    except KeyboardInterrupt:
        warnings.append("消息已发送，但响应归一化被中断；禁止重试")
        message = {
            "channel_id": server_channel,
            "ts": server_ts or None,
            "thread_ts": raw_message.get("thread_ts") or server_ts or None,
            "author": {
                "id": ctx.identity.principal_id,
                "user_id": ctx.identity.user_id,
                "bot_id": ctx.identity.bot_id,
                "is_bot": ctx.selected == "bot",
            },
            "text_raw": raw_message.get("text") or "",
            "raw": raw_message,
        }
    except Exception as exc:  # noqa: BLE001 — post-send must not become failure
        warnings.append(f"消息已发送，但响应归一化失败：{exc.__class__.__name__}")
        message = {
            "channel_id": server_channel,
            "ts": server_ts or None,
            "thread_ts": raw_message.get("thread_ts") or server_ts or None,
            "author": {
                "id": ctx.identity.principal_id,
                "user_id": ctx.identity.user_id,
                "bot_id": ctx.identity.bot_id,
                "is_bot": ctx.selected == "bot",
            },
            "text_raw": raw_message.get("text") or "",
            "raw": raw_message,
        }

    permalink = None
    if server_ts:
        try:
            link = ctx.read_client().call(
                "chat.getPermalink", channel=server_channel, message_ts=server_ts
            )
            permalink = link.get("permalink")
        except KeyboardInterrupt:
            warnings.append("消息已发送，但 permalink 查询被中断；禁止重试")
        except Exception as exc:  # noqa: BLE001 — message is already sent
            reason = exc.error if isinstance(exc, SlackAPIError) else exc.__class__.__name__
            warnings.append(f"消息已发送，但 permalink 查询失败：{reason}")
    message["permalink"] = permalink
    response_warnings = (response.get("response_metadata") or {}).get("warnings") or []
    warnings.extend(str(item) for item in response_warnings)

    emit(
        {
            "status": "sent",
            "operation_status": "succeeded",
            "result": "sent",
            "request": {
                "channel_input": args.channel,
                "channel_id": channel_id,
                "thread_ts": args.thread_ts,
                "format": "block_kit" if blocks is not None else "markdown",
                "preview_digest": digest,
            },
            "channel": {"id": server_channel, "name": channel.get("name")},
            "message": message,
            "permalink": permalink,
            "warnings": warnings,
            "response_metadata": response.get("response_metadata") or {},
        },
        output=args.output,
    )
    return 0


def _resolve_text(args: argparse.Namespace) -> str:
    if args.text_file is not None:
        path = Path(args.text_file).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise InvalidArgument(f"text file not found: {path}")
        text = path.read_text(encoding="utf-8")
    else:
        text = args.text
    if text is None or text == "":
        raise InvalidArgument("message text is empty")
    return text


def _compile_payload(
    text: str,
    blocks: list[dict[str, Any]] | None,
    *,
    args: argparse.Namespace,
    mention_mode: str,
    context: ActorContext,
) -> tuple[CompiledContent, CompiledBlocks | None]:
    return compile_message(
        text, blocks,
        format_name=args.format_name,
        mention_mode=mention_mode,
        allow_broadcast=args.allow_broadcast,
        allow_usergroup_mention=args.allow_usergroup_mention,
        context=context,
    )


__all__ = ["register", "run"]
