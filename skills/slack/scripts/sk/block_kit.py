"""Block Kit 文件加载、基础校验与嵌套通知门禁。"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .actor import ActorContext
from .errors import InvalidArgument
from .send_content import CompiledContent, ContentLookups, compile_content, load_content_lookups


_MAX_BLOCKS_FILE_BYTES = 4 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 20_000


@dataclass(frozen=True)
class CompiledBlocks:
    blocks: list[dict[str, Any]]
    mentions: tuple[dict[str, Any], ...]
    broadcasts: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]


def compile_message(
    text: str,
    blocks: list[dict[str, Any]] | None,
    *,
    format_name: str,
    mention_mode: str,
    allow_broadcast: bool,
    allow_usergroup_mention: bool,
    context: ActorContext,
) -> tuple[CompiledContent, CompiledBlocks | None]:
    """send/edit 共用正文与 blocks 编译，生成结果仍经过原有通知门禁。"""
    if format_name != "markdown":
        raise InvalidArgument("--format 只支持 markdown；自定义布局使用 --blocks-file")
    options = dict(
        mention_mode=mention_mode, allow_broadcast=allow_broadcast,
        allow_usergroup_mention=allow_usergroup_mention,
        context=context, lookups=load_content_lookups(context),
    )
    compiled = compile_content(
        text, format_name="mrkdwn" if blocks is not None else "markdown", **options
    )
    if blocks is not None:
        # 只关闭自动名称解析，保留 Block Kit 自身声明的格式。
        compiled.params.update(parse="none", link_names=False)
    compiled_blocks = compile_blocks(blocks, **options) if blocks is not None else None
    return compiled, compiled_blocks


def load_blocks_file(value: str | None) -> list[dict[str, Any]] | None:
    """读取并执行无需凭据的 Block Kit 基础校验。"""
    if value is None:
        return None

    path = Path(value).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise InvalidArgument(f"blocks file not found: {path}")
    try:
        if path.stat().st_size > _MAX_BLOCKS_FILE_BYTES:
            raise InvalidArgument("blocks file cannot exceed 4 MiB")
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InvalidArgument(f"blocks file must be UTF-8: {path}: {exc}") from None
    try:
        blocks = json.loads(raw, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise InvalidArgument(
            f"blocks file must contain valid JSON: {path}: {exc}"
        ) from None

    if not isinstance(blocks, list) or not blocks:
        raise InvalidArgument("blocks file must contain a non-empty JSON array")
    if len(blocks) > 50:
        raise InvalidArgument("Slack message blocks cannot exceed 50 items")
    if not all(
        isinstance(block, dict)
        and isinstance(block.get("type"), str)
        and bool(block["type"].strip())
        for block in blocks
    ):
        raise InvalidArgument(
            "every Block Kit block must be a JSON object with a non-empty string type"
        )
    _validate_json_limits(blocks)
    return blocks


def compile_blocks(
    blocks: list[dict[str, Any]],
    *,
    mention_mode: str,
    allow_broadcast: bool,
    allow_usergroup_mention: bool,
    context: ActorContext,
    lookups: ContentLookups | None = None,
) -> CompiledBlocks:
    """编译嵌套 markdown/mrkdwn 文本及 rich_text 通知，保留各自 schema。"""
    _validate_json_limits(blocks)
    compiled = copy.deepcopy(blocks)
    resolved_lookups = lookups or load_content_lookups(context)
    mentions: list[dict[str, Any]] = []
    broadcasts: list[dict[str, Any]] = []
    warnings: list[str] = []

    stack: list[tuple[Any, bool]] = [(compiled, False)]
    while stack:
        value, inside_rich_text = stack.pop()
        if isinstance(value, list):
            stack.extend((item, inside_rich_text) for item in reversed(value))
            continue
        if not isinstance(value, dict):
            continue

        value_type = value.get("type")
        child_inside_rich_text = inside_rich_text or value_type == "rich_text"
        if value_type in ("markdown", "mrkdwn") and isinstance(value.get("text"), str):
            result = compile_content(
                value["text"],
                format_name=value_type,
                mention_mode=mention_mode,
                allow_broadcast=allow_broadcast,
                allow_usergroup_mention=allow_usergroup_mention,
                context=context,
                lookups=resolved_lookups,
            )
            text_key = "markdown_text" if value_type == "markdown" else "text"
            value["text"] = result.params[text_key]
            mentions.extend(result.mentions)
            broadcasts.extend(result.broadcasts)
            warnings.extend(result.warnings)
        elif inside_rich_text:
            _collect_rich_text_reference(
                value,
                allow_broadcast=allow_broadcast,
                allow_usergroup_mention=allow_usergroup_mention,
                mentions=mentions,
                broadcasts=broadcasts,
            )

        stack.extend(
            (item, child_inside_rich_text)
            for item in reversed(list(value.values()))
            if isinstance(item, (dict, list))
        )
    return CompiledBlocks(
        blocks=compiled,
        mentions=tuple(mentions),
        broadcasts=tuple(broadcasts),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _collect_rich_text_reference(
    value: dict[str, Any],
    *,
    allow_broadcast: bool,
    allow_usergroup_mention: bool,
    mentions: list[dict[str, Any]],
    broadcasts: list[dict[str, Any]],
) -> None:
    value_type = value.get("type")
    if value_type == "broadcast":
        if not allow_broadcast:
            raise InvalidArgument(
                "消息包含全频道通知；只有显式 --allow-broadcast 才能发送"
            )
        name = value.get("range")
        if isinstance(name, str) and name:
            broadcasts.append({"type": "broadcast", "name": name})
    elif value_type == "usergroup":
        if not allow_usergroup_mention:
            raise InvalidArgument(
                "消息包含用户组通知；只有显式 --allow-usergroup-mention 才能发送"
            )
        usergroup_id = value.get("usergroup_id")
        if isinstance(usergroup_id, str) and usergroup_id:
            broadcasts.append({"type": "usergroup", "id": usergroup_id})
    elif value_type == "user":
        user_id = value.get("user_id")
        if isinstance(user_id, str) and user_id:
            mentions.append({"type": "user", "input": f"<@{user_id}>", "id": user_id})
    elif value_type == "channel":
        channel_id = value.get("channel_id")
        if isinstance(channel_id, str) and channel_id:
            mentions.append(
                {"type": "channel", "input": f"<#{channel_id}>", "id": channel_id}
            )


def _validate_json_limits(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    node_count = 0
    while stack:
        current, depth = stack.pop()
        node_count += 1
        if depth > _MAX_JSON_DEPTH:
            raise InvalidArgument(
                f"blocks file JSON nesting cannot exceed {_MAX_JSON_DEPTH} levels"
            )
        if node_count > _MAX_JSON_NODES:
            raise InvalidArgument(
                f"blocks file JSON cannot exceed {_MAX_JSON_NODES} nodes"
            )
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _reject_json_constant(constant: str) -> NoReturn:
    raise InvalidArgument(f"blocks file contains non-standard JSON constant: {constant}")


__all__ = ["CompiledBlocks", "compile_blocks", "compile_message", "load_blocks_file"]
