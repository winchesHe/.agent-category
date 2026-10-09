"""Slack token 身份发现与进程内缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .client import SlackClient
from .errors import ActorConfigError


@dataclass(frozen=True)
class SlackIdentity:
    actor: str
    team_id: str
    user_id: str
    bot_id: Optional[str]
    workspace_url: Optional[str]

    @property
    def principal_id(self) -> str:
        return self.bot_id or self.user_id

    @property
    def key(self) -> tuple[str, str, str, Optional[str]]:
        return (self.actor, self.team_id, self.user_id, self.bot_id)


_IDENTITY_CACHE: dict[str, SlackIdentity] = {}


def discover_identity(
    token: str,
    *,
    declared_actor: Optional[str],
    source_env: str,
    timeout: int,
) -> SlackIdentity:
    cached = _IDENTITY_CACHE.get(token)
    if cached is None:
        payload = SlackClient(token, timeout=timeout).call("auth.test")
        team_id = str(payload.get("team_id") or "").strip()
        user_id = str(payload.get("user_id") or payload.get("user") or "").strip()
        bot_id = str(payload.get("bot_id") or "").strip() or None
        if not team_id or not user_id:
            raise ActorConfigError(
                f"{source_env} 的 auth.test 缺少 team_id/user_id，无法建立身份上下文"
            )
        cached = SlackIdentity(
            actor="bot" if bot_id else "user",
            team_id=team_id,
            user_id=user_id,
            bot_id=bot_id,
            workspace_url=str(payload.get("url") or "").rstrip("/") or None,
        )
        _IDENTITY_CACHE[token] = cached

    if declared_actor and cached.actor != declared_actor:
        raise ActorConfigError(
            f"{source_env} 声明为 {declared_actor}，但 auth.test 识别为 {cached.actor}"
        )
    return cached


def clear_identity_cache() -> None:
    """仅供单元测试隔离进程缓存。"""
    _IDENTITY_CACHE.clear()


__all__ = ["SlackIdentity", "discover_identity", "clear_identity_cache"]
