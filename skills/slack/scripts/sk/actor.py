"""Bot/User actor 选择与不可变操作上下文。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from .client import SlackClient
from .errors import ActorConfigError, ActorSelectionError, InvalidArgument, SlackAPIError
from .identity import SlackIdentity, discover_identity
from .write_client import SlackWriteClient


ACTORS = ("auto", "bot", "user")


@dataclass(frozen=True)
class TokenSlot:
    source_env: str
    token: str
    declared_actor: Optional[str]


@dataclass(frozen=True)
class ActorContext:
    requested: str
    selected: str
    source_env: str
    identity: SlackIdentity
    token: str
    timeout: int
    retry_wait_budget: int
    cache_root: Path
    files_root: Path
    fallback_reason: Optional[str] = None
    warnings: tuple[str, ...] = ()

    @property
    def cache_dir(self) -> Path:
        label = f"{self.selected}-{self.identity.principal_id}"
        return self.cache_root / self.identity.team_id / label

    @property
    def files_dir(self) -> Path:
        label = f"{self.selected}-{self.identity.principal_id}"
        return self.files_root / self.identity.team_id / label

    def read_client(self) -> SlackClient:
        return SlackClient(self.token, timeout=self.timeout)

    def write_client(self) -> SlackWriteClient:
        return SlackWriteClient(
            self.token,
            timeout=self.timeout,
            retry_wait_budget=self.retry_wait_budget,
        )

    def public(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "selected": self.selected,
            "source_env": self.source_env,
            "team_id": self.identity.team_id,
            "user_id": self.identity.user_id,
            "bot_id": self.identity.bot_id,
            "fallback_reason": self.fallback_reason,
            "warnings": list(self.warnings),
        }


_ACTIVE: Optional[ActorContext] = None
_REQUESTED: Optional[str] = None


@dataclass
class ReadAttempt:
    """一次读 actor 尝试是否已收到主事务的 Slack 响应。"""

    primary_observed: bool = False


_READ_ATTEMPT: ContextVar[Optional[ReadAttempt]] = ContextVar(
    "slack_read_attempt", default=None
)


@contextmanager
def read_attempt() -> Iterator[ReadAttempt]:
    """为一次命令执行隔离主读取状态，避免跨重试或测试泄漏。"""

    attempt = ReadAttempt()
    token = _READ_ATTEMPT.set(attempt)
    try:
        yield attempt
    finally:
        _READ_ATTEMPT.reset(token)


def mark_primary_observed() -> None:
    """标记主读取已收到响应；后续错误不得通过换 actor 整体重跑。"""

    attempt = _READ_ATTEMPT.get()
    if attempt is not None:
        attempt.primary_observed = True


def has_primary_observation() -> bool:
    """当前读尝试是否已经收到至少一个主响应。"""

    attempt = _READ_ATTEMPT.get()
    return bool(attempt and attempt.primary_observed)


def set_requested(value: Optional[str]) -> None:
    global _REQUESTED, _ACTIVE
    _REQUESTED = value
    _ACTIVE = None


def requested_for(scope: str, cfg: Any) -> str:
    value = _REQUESTED
    if value is None:
        value = cfg.write_actor if scope == "write" else cfg.read_actor
    if value not in ACTORS:
        raise ActorConfigError(f"actor 必须是 auto|bot|user，实际为 {value!r}")
    return value


def activate(context: ActorContext) -> ActorContext:
    global _ACTIVE
    _ACTIVE = context
    return context


def current() -> Optional[ActorContext]:
    return _ACTIVE


def clear_active() -> None:
    global _ACTIVE
    _ACTIVE = None


def _raw_slots(cfg: Any) -> list[TokenSlot]:
    slots: list[TokenSlot] = []
    if cfg.bot_token:
        slots.append(TokenSlot("SLACK_BOT_TOKEN", cfg.bot_token, "bot"))
    if cfg.user_token:
        slots.append(TokenSlot("SLACK_USER_TOKEN", cfg.user_token, "user"))
    if cfg.any_token:
        slots.append(TokenSlot("SLACK_TOKEN", cfg.any_token, None))
    return slots


def discover_contexts(cfg: Any, actors: Iterable[str]) -> dict[str, ActorContext]:
    wanted = set(actors)
    requested = requested_for("read", cfg)
    found: dict[str, ActorContext] = {}
    for slot in _raw_slots(cfg):
        if slot.declared_actor and slot.declared_actor not in wanted:
            continue
        identity = discover_identity(
            slot.token,
            declared_actor=slot.declared_actor,
            source_env=slot.source_env,
            timeout=cfg.timeout,
        )
        if identity.actor not in wanted:
            continue
        existing = found.get(identity.actor)
        if existing is not None:
            if existing.identity.key != identity.key:
                raise ActorConfigError(
                    f"{identity.actor} actor 同时配置了不同身份："
                    f"{existing.source_env} 与 {slot.source_env}"
                )
            continue
        found[identity.actor] = ActorContext(
            requested=requested,
            selected=identity.actor,
            source_env=slot.source_env,
            identity=identity,
            token=slot.token,
            timeout=cfg.timeout,
            retry_wait_budget=cfg.write_retry_budget,
            cache_root=cfg.cache_root,
            files_root=cfg.files_root,
        )
    return found


def ensure_same_workspace(contexts: Iterable[ActorContext]) -> None:
    team_ids = {ctx.identity.team_id for ctx in contexts}
    if len(team_ids) > 1:
        raise ActorConfigError(
            "auto 候选 token 不属于同一 workspace：" + ", ".join(sorted(team_ids))
        )


def select_read(cfg: Any, *, force: Optional[str] = None, fallback_reason: Optional[str] = None) -> ActorContext:
    requested = force or requested_for("read", cfg)
    wanted = (requested,) if requested != "auto" else ("user", "bot")
    contexts = discover_contexts(cfg, wanted)
    if requested == "auto":
        ensure_same_workspace(contexts.values())
    for actor_name in wanted:
        ctx = contexts.get(actor_name)
        if ctx is not None:
            if requested == "auto" and fallback_reason:
                ctx = ActorContext(**{**ctx.__dict__, "fallback_reason": fallback_reason})
            return activate(ctx)
    raise ActorSelectionError(
        f"没有可用的 {requested if requested != 'auto' else 'User 或 Bot'} token"
    )


def select_search(cfg: Any) -> ActorContext:
    requested = requested_for("read", cfg)
    if requested == "bot":
        raise ActorSelectionError("search.messages 不支持 Bot Token；请使用 --as user")
    return select_read(cfg, force="user")


def _allowed_early(cfg: Any, channel: str) -> None:
    from .channels import looks_like_channel_id

    if cfg.allowed_channels and looks_like_channel_id(channel):
        if channel not in cfg.allowed_channels:
            raise InvalidArgument(
                f"channel {channel!r} is not in SLACK_SKILL_ALLOWED_CHANNELS"
            )


def _reachable(channel: dict[str, Any]) -> str:
    if channel.get("is_archived"):
        return "no"
    kind = str(channel.get("id") or "")[:1]
    if channel.get("is_im") or channel.get("is_mpim") or kind == "D":
        return "yes"
    if channel.get("is_member") is True:
        return "yes"
    return "unknown"


def _slack_error(exc: BaseException) -> Optional[str]:
    """Return the first nested Slack error code, including wrapped lookup errors."""
    cursor: Optional[BaseException] = exc
    seen: set[int] = set()
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        if isinstance(cursor, SlackAPIError):
            return cursor.error
        cursor = cursor.__cause__ or cursor.__context__
    return None


def select_write_target(
    cfg: Any, channel_input: str, *, force: Optional[str] = None
) -> tuple[ActorContext, dict[str, Any], str]:
    """在任何写请求前，用候选自己的上下文解析并预检 channel。"""
    from .channels import looks_like_channel_id, resolve_channel

    external_requested = requested_for("write", cfg)
    requested = force or external_requested
    _allowed_early(cfg, channel_input)
    wanted = (requested,) if requested != "auto" else ("user", "bot")
    contexts = discover_contexts(cfg, wanted)
    if requested == "auto":
        ensure_same_workspace(contexts.values())

    unknown: list[tuple[ActorContext, dict[str, Any], str]] = []
    failures: list[str] = []
    for actor_name in wanted:
        ctx = contexts.get(actor_name)
        if ctx is None:
            continue
        ctx = ActorContext(**{**ctx.__dict__, "requested": external_requested})
        activate(ctx)
        try:
            channel = resolve_channel(ctx.read_client(), channel_input, cfg=cfg)
            channel_id = str(channel.get("id") or "")
            if not channel_id:
                raise InvalidArgument(f"could not resolve channel from {channel_input!r}")
            if cfg.allowed_channels and channel_id not in cfg.allowed_channels:
                raise InvalidArgument(
                    f"channel {channel_id!r} is not in SLACK_SKILL_ALLOWED_CHANNELS"
                )
            info = ctx.read_client().call("conversations.info", channel=channel_id)
            channel = info.get("channel") or channel
            state = _reachable(channel)
        except (InvalidArgument, SlackAPIError) as exc:
            # A raw channel ID is already a valid write target.  Some User
            # tokens intentionally have chat:write but no conversations:read
            # scope, so an explicit actor may proceed with reachable=unknown.
            # Auto selection must still refuse this unverifiable candidate.
            if (
                external_requested != "auto"
                and force is None
                and looks_like_channel_id(channel_input)
                and _slack_error(exc) == "missing_scope"
            ):
                unknown.append((ctx, {"id": channel_input}, "unknown"))
                continue
            failures.append(f"{actor_name}: {exc}")
            continue
        if state == "yes":
            reason = None
            if requested == "auto" and actor_name == "bot":
                reason = "user_target_unreachable"
                ctx = ActorContext(**{**ctx.__dict__, "fallback_reason": reason})
            return activate(ctx), channel, state
        if state == "unknown":
            unknown.append((ctx, channel, state))

    if external_requested != "auto" and force is None and unknown:
        ctx, channel, state = unknown[0]
        warning = "只读预检无法证明写权限，将按显式 actor 执行"
        ctx = ActorContext(**{**ctx.__dict__, "warnings": (warning,)})
        return activate(ctx), channel, state
    detail = "; ".join(failures) or "候选均为 reachable=unknown"
    raise ActorSelectionError(
        f"auto 无法安全选择可写 actor（{detail}）；请显式使用 --as bot 或 --as user"
    )


def actor_matches_message(ctx: ActorContext, message: dict[str, Any]) -> bool:
    bot_id = str(message.get("bot_id") or "")
    user_id = str(message.get("user") or "")
    if ctx.selected == "bot":
        # When Slack includes a user principal, it is the strongest ownership
        # signal.  A User-token write may also carry the same App bot_id and
        # must not be claimed by the Bot actor.
        if user_id:
            return user_id == ctx.identity.user_id
        return bool(bot_id and bot_id == ctx.identity.bot_id)
    # Slack may attach the app's bot_id even when a User token authored the
    # message.  The authenticated User principal remains authoritative.
    return user_id == ctx.identity.user_id


def access_error(exc: BaseException) -> Optional[str]:
    cursor: Optional[BaseException] = exc
    seen: set[int] = set()
    allowed = {"not_in_channel", "channel_not_found", "not_allowed_token_type"}
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        if isinstance(cursor, SlackAPIError) and cursor.error in allowed:
            return cursor.error
        cursor = cursor.__cause__ or cursor.__context__
    return None


def read_fallback_error(exc: BaseException) -> Optional[str]:
    """返回允许普通读命令在首个主响应前换 actor 的 Slack 错误。"""

    cursor: Optional[BaseException] = exc
    seen: set[int] = set()
    allowed = {
        "not_in_channel",
        "channel_not_found",
        "not_allowed_token_type",
        "missing_scope",
    }
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        if isinstance(cursor, SlackAPIError) and cursor.error in allowed:
            return cursor.error
        cursor = cursor.__cause__ or cursor.__context__
    return None


__all__ = [
    "ACTORS", "ActorContext", "activate", "current", "clear_active",
    "set_requested", "requested_for", "discover_contexts", "ensure_same_workspace",
    "select_read", "select_search", "select_write_target", "actor_matches_message",
    "access_error", "read_fallback_error", "ReadAttempt", "read_attempt",
    "mark_primary_observed", "has_primary_observation",
]
