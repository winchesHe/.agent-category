"""edit/delete 原消息读取与作者 actor 锁定。"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Optional

from .actor import (
    ActorContext,
    activate,
    actor_matches_message,
    discover_contexts,
    ensure_same_workspace,
    requested_for,
    select_write_target,
)
from .cmd_get import _fetch_single
from .errors import ActorSelectionError, InvalidArgument, SlackAPIError


_TS_RE = re.compile(r"^\d+\.\d{6}$")


def validate_thread_root(
    ctx: ActorContext, channel_id: str, thread_ts: str
) -> Optional[str]:
    if not _TS_RE.fullmatch(thread_ts):
        raise InvalidArgument("thread ts 必须是字符串形式 1700000000.000200")
    try:
        payload = ctx.read_client().call(
            "conversations.replies", channel=channel_id, ts=thread_ts, limit=2
        )
    except SlackAPIError as exc:
        if ctx.requested != "auto" and exc.error == "missing_scope":
            return (
                "只读 scope 无法验证 thread root；已按显式 actor 与合法 thread_ts 执行"
            )
        raise InvalidArgument(
            f"thread root {thread_ts} 不可用：{exc.error}；请传 root message ts"
        ) from exc
    messages = payload.get("messages") or []
    if not messages or str(messages[0].get("ts") or "") != thread_ts:
        root = (messages[0] or {}).get("thread_ts") if messages else None
        suffix = f"，正确 root 可能是 {root}" if root else ""
        raise InvalidArgument(f"thread ts 不是可验证的 thread root{suffix}")
    return None


def select_write_target_with_thread(
    cfg: Any,
    channel_input: str,
    thread_ts: Optional[str],
    *,
    force: Optional[str] = None,
) -> tuple[ActorContext, dict[str, Any], str, Optional[str]]:
    """完成频道与 thread root 预检后再锁定写 actor。

    ``auto`` 的 User 通过频道预检、但无法读取 thread root 时，任何写请求都
    还没有发出，因此可以安全地让 Bot 用自己的上下文重做完整预检。
    """
    ctx, channel, reachable = select_write_target(cfg, channel_input, force=force)
    if not thread_ts:
        return ctx, channel, reachable, None

    channel_id = str(channel.get("id") or "")
    try:
        warning = validate_thread_root(ctx, channel_id, thread_ts)
        return ctx, channel, reachable, warning
    except InvalidArgument as user_error:
        if (
            force is not None
            or requested_for("write", cfg) != "auto"
            or ctx.selected != "user"
        ):
            raise

        try:
            bot_ctx, bot_channel, bot_reachable = select_write_target(
                cfg, channel_input, force="bot"
            )
            bot_channel_id = str(bot_channel.get("id") or "")
            warning = validate_thread_root(bot_ctx, bot_channel_id, thread_ts)
        except (ActorSelectionError, InvalidArgument) as bot_error:
            raise ActorSelectionError(
                "auto 无法安全选择可写 actor："
                f"user thread 预检失败（{user_error}）；"
                f"bot thread 预检失败（{bot_error}）"
            ) from bot_error

        bot_ctx = activate(
            replace(bot_ctx, fallback_reason="user_thread_preflight_failed")
        )
        return bot_ctx, bot_channel, bot_reachable, warning


def select_message_author(
    cfg: Any,
    *,
    channel_id: str,
    ts: str,
    thread_ts: Optional[str],
) -> tuple[ActorContext, dict[str, Any]]:
    if cfg.allowed_channels and channel_id not in cfg.allowed_channels:
        raise InvalidArgument(
            f"channel {channel_id!r} is not in SLACK_SKILL_ALLOWED_CHANNELS"
        )
    if not _TS_RE.fullmatch(ts):
        raise InvalidArgument("message ts 必须是字符串形式 1700000000.000200")
    if thread_ts and not _TS_RE.fullmatch(thread_ts):
        raise InvalidArgument("thread ts 必须是字符串形式 1700000000.000200")

    requested = requested_for("write", cfg)
    wanted = (requested,) if requested != "auto" else ("bot", "user")
    contexts = discover_contexts(cfg, wanted)
    if requested == "auto":
        ensure_same_workspace(contexts.values())

    details: list[str] = []
    for actor_name in wanted:
        ctx = contexts.get(actor_name)
        if ctx is None:
            continue
        ctx = ActorContext(**{**ctx.__dict__, "requested": requested})
        activate(ctx)
        root = thread_ts or ts
        try:
            message = _fetch_single(
                ctx.read_client(), channel_id=channel_id, ts=ts, thread_ts=root
            )
        except SlackAPIError as exc:
            details.append(f"{actor_name}: {exc.error}")
            continue
        if message is None:
            if thread_ts is None:
                details.append(
                    f"{actor_name}: message_not_found（若目标是 reply，请提供 --thread-ts）"
                )
            else:
                details.append(f"{actor_name}: message_not_found")
            continue
        if actor_matches_message(ctx, message):
            return activate(ctx), message
        author = message.get("bot_id") or message.get("user") or "unknown"
        details.append(f"{actor_name}: 原作者不匹配 ({author})")

    raise ActorSelectionError(
        "没有已配置 actor 能安全编辑/删除该消息：" + "; ".join(details)
    )


__all__ = [
    "select_message_author",
    "select_write_target_with_thread",
    "validate_thread_root",
]
