"""send 内容编译器：格式互斥、code-aware mention 与通知门禁。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from . import cache
from .actor import ActorContext
from .errors import InvalidArgument, MentionResolutionError


_TOKEN = re.compile(
    r"(?P<url>(?:https?://|mailto:)[^\s<>()]+)"
    r"|(?P<native_user><@(?P<native_user_id>[UW][A-Z0-9]+)(?:\|[^>]*)?>)"
    r"|(?P<native_channel><#(?P<native_channel_id>[CGD][A-Z0-9]+)(?:\|[^>]*)?>)"
    r"|(?P<usergroup><!subteam\^(?P<usergroup_id>[A-Z0-9]+)(?:\|[^>]*)?>)"
    r"|(?P<native_broadcast><!(?P<native_broadcast_name>here|channel|everyone)>)"
    r"|(?P<email>(?<![\\\w/<])@\{(?P<email_value>[^{}]+)\})"
    r"|(?P<handle>(?<![\\\w/<])@(?P<handle_value>[A-Za-z0-9._-]+))"
    r"|(?P<channel>(?<![\\\w/<])#(?P<channel_value>[A-Za-z][A-Za-z0-9_-]*))",
    re.I,
)
_FENCE_OPEN = re.compile(r"(?m)^[ \t]{0,3}(?P<marker>`{3,}|~{3,})[^\n]*(?:\n|$)")
_URL_START = re.compile(r"(?:https?://|mailto:)", re.I)


@dataclass(frozen=True)
class CompiledContent:
    params: dict[str, Any]
    mentions: tuple[dict[str, Any], ...]
    broadcasts: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ContentLookups:
    user_index: dict[str, list[dict[str, Any]]]
    channel_index: dict[str, list[dict[str, Any]]]


def load_content_lookups(context: ActorContext) -> ContentLookups:
    """为一次消息编译加载并建立可复用的 mention 索引。"""
    return ContentLookups(
        user_index=_user_index(cache.load_users(context.cache_dir)),
        channel_index=_channel_index(cache.load_channels(context.cache_dir)),
    )


def compile_content(
    text: str,
    *,
    format_name: str,
    mention_mode: str,
    allow_broadcast: bool,
    allow_usergroup_mention: bool,
    context: ActorContext,
    lookups: ContentLookups | None = None,
) -> CompiledContent:
    if format_name not in {"markdown", "mrkdwn", "plain"}:
        raise InvalidArgument("内部文本类型必须是 markdown|mrkdwn|plain")
    if mention_mode not in {"resolve", "literal"}:
        raise InvalidArgument("--mention-mode 必须是 resolve|literal")
    if format_name == "plain" and mention_mode == "resolve":
        raise InvalidArgument("plain 关闭 Slack markup，必须使用 --mention-mode literal")

    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalised:
        raise InvalidArgument("message text is empty")

    resolved_lookups = lookups or load_content_lookups(context)
    mentions: list[dict[str, Any]] = []
    broadcasts: list[dict[str, Any]] = []
    warnings: list[str] = []
    out: list[str] = []

    for protected, segment in _segments(normalised):
        if protected:
            out.append(segment)
            continue

        out.append(
            _compile_segment(
                segment,
                mention_mode=mention_mode,
                allow_broadcast=allow_broadcast,
                allow_usergroup_mention=allow_usergroup_mention,
                user_index=resolved_lookups.user_index,
                channel_index=resolved_lookups.channel_index,
                mentions=mentions,
                broadcasts=broadcasts,
            )
        )

    final = "".join(out)
    if format_name == "markdown":
        if len(final) > 12_000:
            raise InvalidArgument("markdown_text 超过 Slack 12,000 字符上限")
        params = {"markdown_text": final}
        if mentions or broadcasts:
            warnings.append(
                "Slack 未单独保证 Markdown 控制串的通知行为；需要确定通知时使用 Block Kit 显式 mention"
            )
    else:
        if len(final) > 40_000:
            raise InvalidArgument("text 超过 Slack 40,000 字符硬上限")
        if len(final) > 4_000:
            warnings.append("text 超过 4,000 字符，Slack 客户端可能截断显示")
        params = {"text": final, "mrkdwn": format_name == "mrkdwn"}

    return CompiledContent(
        params=params,
        mentions=tuple(mentions),
        broadcasts=tuple(broadcasts),
        warnings=tuple(warnings),
    )


def preview_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _segments(text: str) -> list[tuple[bool, str]]:
    """保护任意长度 backtick code span 以及 backtick/tilde fenced block。"""
    result: list[tuple[bool, str]] = []
    pos = 0
    while pos < len(text):
        match = _FENCE_OPEN.search(text, pos)
        if match is None:
            result.extend(_inline_segments(text[pos:]))
            break
        result.extend(_inline_segments(text[pos:match.start()]))
        marker = match.group("marker")
        close = re.compile(
            rf"(?m)^[ \t]{{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*(?:\n|$)"
        ).search(text, match.end())
        if close is None:
            result.append((True, text[match.start():]))
            break
        result.append((True, text[match.start():close.end()]))
        pos = close.end()
    return result or [(False, text)]


def _inline_segments(text: str) -> list[tuple[bool, str]]:
    result: list[tuple[bool, str]] = []
    pos = 0
    while pos < len(text):
        start = text.find("`", pos)
        if start < 0:
            if pos < len(text):
                result.extend(_link_destination_segments(text[pos:]))
            break
        if start > pos:
            result.extend(_link_destination_segments(text[pos:start]))
        end_run = start
        while end_run < len(text) and text[end_run] == "`":
            end_run += 1
        marker = text[start:end_run]
        close = text.find(marker, end_run)
        if close < 0:
            result.append((True, text[start:]))
            break
        close += len(marker)
        result.append((True, text[start:close]))
        pos = close
    return result


def _link_destination_segments(text: str) -> list[tuple[bool, str]]:
    """保护 Markdown destination 与裸 URL（支持平衡括号和转义）。"""
    result: list[tuple[bool, str]] = []
    pos = 0
    while pos < len(text):
        opener = text.find("](", pos)
        url_match = _URL_START.search(text, pos)
        url_start = url_match.start() if url_match else -1
        if opener < 0 and url_start < 0:
            break
        if url_start >= 0 and (opener < 0 or url_start < opener):
            cursor = url_start
            depth = 0
            while cursor < len(text):
                char = text[cursor]
                if char.isspace() or char in "<>":
                    break
                if char == "\\" and cursor + 1 < len(text):
                    cursor += 2
                    continue
                if char == "(":
                    depth += 1
                elif char == ")":
                    if depth == 0:
                        break
                    depth -= 1
                cursor += 1
            if url_start > pos:
                result.append((False, text[pos:url_start]))
            result.append((True, text[url_start:cursor]))
            pos = cursor
            continue
        destination_start = opener + 2
        depth = 1
        cursor = destination_start
        close = -1
        while cursor < len(text):
            char = text[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    close = cursor
                    break
            cursor += 1
        if close < 0:
            break
        if destination_start > pos:
            result.append((False, text[pos:destination_start]))
        result.append((True, text[destination_start:close]))
        pos = close
    if pos < len(text):
        result.append((False, text[pos:]))
    return result or ([(False, text)] if text else [])


def _compile_segment(
    segment: str,
    *,
    mention_mode: str,
    allow_broadcast: bool,
    allow_usergroup_mention: bool,
    user_index: dict[str, list[dict[str, Any]]],
    channel_index: dict[str, list[dict[str, Any]]],
    mentions: list[dict[str, Any]],
    broadcasts: list[dict[str, Any]],
) -> str:
    pieces: list[str] = []
    pos = 0
    for match in _TOKEN.finditer(segment):
        pieces.append(segment[pos:match.start()])
        token = match.group(0)
        kind = next(
            name
            for name in (
                "url", "native_user", "native_channel", "usergroup",
                "native_broadcast", "email", "handle", "channel",
            )
            if match.group(name) is not None
        )
        replacement = token
        if kind == "native_user":
            mentions.append({"type": "user", "input": token, "id": match.group("native_user_id")})
        elif kind == "native_channel":
            mentions.append({"type": "channel", "input": token, "id": match.group("native_channel_id")})
        elif kind == "usergroup":
            if not allow_usergroup_mention:
                raise InvalidArgument(
                    "消息包含用户组通知；只有显式 --allow-usergroup-mention 才能发送"
                )
            broadcasts.append({"type": "usergroup", "id": match.group("usergroup_id")})
        elif kind == "native_broadcast":
            name = str(match.group("native_broadcast_name")).lower()
            if not allow_broadcast:
                raise InvalidArgument(
                    "消息包含全频道通知；只有显式 --allow-broadcast 才能发送"
                )
            broadcasts.append({"type": "broadcast", "name": name})
        elif kind == "email" and mention_mode == "resolve":
            value = str(match.group("email_value")).strip()
            user = _unique(user_index, value, "email")
            mentions.append({"type": "user", "input": token, "id": user.get("id")})
            replacement = f"<@{user.get('id')}>"
        elif kind == "handle":
            value = str(match.group("handle_value"))
            if value.lower() in {"here", "channel", "everyone"}:
                if not allow_broadcast:
                    raise InvalidArgument(
                        "消息包含全频道通知；只有显式 --allow-broadcast 才能发送"
                    )
                name = value.lower()
                broadcasts.append({"type": "broadcast", "name": name})
                replacement = f"<!{name}>"
            elif mention_mode == "resolve":
                user = _unique(user_index, value, "handle")
                mentions.append({"type": "user", "input": token, "id": user.get("id")})
                replacement = f"<@{user.get('id')}>"
        elif kind == "channel" and mention_mode == "resolve":
            value = str(match.group("channel_value"))
            channel = _unique(channel_index, value, "channel")
            mentions.append({"type": "channel", "input": token, "id": channel.get("id")})
            replacement = f"<#{channel.get('id')}>"
        pieces.append(replacement)
        pos = match.end()
    pieces.append(segment[pos:])
    # 反斜杠是调用方对 mention/broadcast 的显式转义。门禁完成后仍须保留，
    # 避免原生格式把原本安全的 ``\\@channel`` 重新解释成通知。
    return "".join(pieces)


def _user_index(users: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for user in users.values():
        if user.get("deleted"):
            continue
        profile = user.get("profile") or {}
        for value in (
            profile.get("email"), profile.get("display_name"),
            profile.get("real_name"), user.get("real_name"), user.get("name"),
        ):
            key = str(value or "").strip().lower()
            if key:
                index.setdefault(key, []).append(user)
    return index


def _channel_index(channels: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for channel in channels.values():
        for value in (channel.get("name"), channel.get("name_normalized")):
            key = str(value or "").strip().lower()
            if key:
                index.setdefault(key, []).append(channel)
    return index


def _unique(index: dict[str, list[dict[str, Any]]], key: str, kind: str) -> dict[str, Any]:
    candidates = {str(item.get("id")): item for item in index.get(key.lower(), [])}
    if len(candidates) != 1:
        ids = sorted(item_id for item_id in candidates if item_id)
        raise MentionResolutionError(
            f"{kind} {key!r} 必须唯一匹配，实际 {len(candidates)} 个"
            + (f"：{', '.join(ids)}" if ids else "")
        )
    return next(iter(candidates.values()))


__all__ = [
    "CompiledContent",
    "ContentLookups",
    "compile_content",
    "load_content_lookups",
    "preview_digest",
]
