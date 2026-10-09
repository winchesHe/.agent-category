from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sk import actor  # noqa: E402
from sk.config import Config  # noqa: E402
from sk.errors import (  # noqa: E402
    ActorConfigError,
    ActorSelectionError,
    InvalidArgument,
    SlackAPIError,
)
from sk.identity import SlackIdentity  # noqa: E402
from sk.write_target import select_message_author  # noqa: E402
from sk.write_target import select_write_target_with_thread  # noqa: E402
from sk.write_target import validate_thread_root  # noqa: E402


def identity(kind: str, principal: str, team: str = "T1") -> SlackIdentity:
    return SlackIdentity(
        actor=kind,
        team_id=team,
        user_id="U-BOT" if kind == "bot" else principal,
        bot_id=principal if kind == "bot" else None,
        workspace_url="https://example.slack.com",
    )


class ActorTests(unittest.TestCase):
    def setUp(self) -> None:
        actor.set_requested(None)

    def tearDown(self) -> None:
        actor.set_requested(None)

    def test_read_auto_prefers_user_and_namespaces_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ,
            {
                "SLACK_BOT_TOKEN": "bot-token",
                "SLACK_USER_TOKEN": "user-token",
                "SLACK_SKILL_CACHE_DIR": temp,
            },
            clear=True,
        ), mock.patch(
            "sk.actor.discover_identity",
            side_effect=lambda token, **_: identity(
                "bot" if token == "bot-token" else "user",
                "B1" if token == "bot-token" else "U1",
            ),
        ):
            context = actor.select_read(Config())

        self.assertEqual(context.selected, "user")
        self.assertEqual(context.cache_dir, Path(temp) / "T1" / "user-U1")

    def test_same_actor_different_identity_is_configuration_error(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"SLACK_BOT_TOKEN": "one", "SLACK_TOKEN": "two"},
            clear=True,
        ), mock.patch(
            "sk.actor.discover_identity",
            side_effect=[identity("bot", "B1"), identity("bot", "B2")],
        ):
            with self.assertRaises(ActorConfigError):
                actor.discover_contexts(Config(), ("bot",))

    def test_auto_write_falls_back_to_bot_before_write(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"SLACK_BOT_TOKEN": "bot-token", "SLACK_USER_TOKEN": "user-token"},
            clear=True,
        ), mock.patch(
            "sk.actor.discover_identity",
            side_effect=lambda token, **_: identity(
                "bot" if token == "bot-token" else "user",
                "B1" if token == "bot-token" else "U1",
            ),
        ), mock.patch(
            "sk.channels.resolve_channel",
            side_effect=lambda client, *_args, **_kwargs: {
                "id": "C1",
                "name": "private",
                "is_member": client._token == "bot-token",
            },
        ), mock.patch(
            "sk.client.SlackClient.call",
            side_effect=lambda self, method, **_: {
                "ok": True,
                "channel": {
                    "id": "C1",
                    "name": "private",
                    "is_member": self._token == "bot-token",
                },
            },
            autospec=True,
        ):
            context, _channel, state = actor.select_write_target(Config(), "C1")

        self.assertEqual(state, "yes")
        self.assertEqual(context.selected, "bot")
        self.assertEqual(context.fallback_reason, "user_target_unreachable")

    def test_write_actor_preference_and_explicit_override(self) -> None:
        cases = [
            ("auto", True, True, True, "user"),
            ("auto", False, True, True, "bot"),
            ("auto", True, False, True, "user"),
            ("user", True, True, False, None),
            ("bot", True, True, True, "bot"),
        ]
        for requested, has_user, has_bot, user_reachable, expected in cases:
            with self.subTest(requested=requested, has_user=has_user,
                              has_bot=has_bot, user_reachable=user_reachable):
                env = {"SLACK_WRITE_ACTOR": requested}
                if has_user:
                    env["SLACK_USER_TOKEN"] = "user-token"
                if has_bot:
                    env["SLACK_BOT_TOKEN"] = "bot-token"
                seen = []

                def channel_info(client, method, **kwargs):
                    seen.append(client._token)
                    return {"channel": {"id": "C1", "is_member": True,
                            "is_archived": client._token == "user-token" and not user_reachable}}

                with mock.patch.dict(os.environ, env, clear=True), mock.patch(
                    "sk.actor.discover_identity",
                    side_effect=lambda token, **_: identity(
                        "bot" if token == "bot-token" else "user",
                        "B1" if token == "bot-token" else "U1",
                    ),
                ), mock.patch("sk.channels.resolve_channel", return_value={"id": "C1"}), \
                     mock.patch("sk.client.SlackClient.call", autospec=True,
                                side_effect=channel_info), \
                     mock.patch.object(actor.ActorContext, "write_client",
                                       side_effect=AssertionError("预检不得写入")):
                    if expected is None:
                        with self.assertRaises(ActorSelectionError):
                            actor.select_write_target(Config(), "C1")
                        self.assertEqual(seen, ["user-token"])
                    else:
                        context, channel, state = actor.select_write_target(Config(), "C1")
                        self.assertEqual(context.selected, expected)
                        self.assertEqual(context.requested, requested)
                        self.assertEqual(context.token, expected + "-token")
                        self.assertEqual(channel["id"], "C1")
                        self.assertEqual(state, "yes")
                        self.assertEqual(seen, [expected + "-token"])
                        if expected == "user" or requested != "auto":
                            self.assertIsNone(context.fallback_reason)

    def test_auto_write_refuses_only_unknown_candidates(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"SLACK_BOT_TOKEN": "bot-token"},
            clear=True,
        ), mock.patch(
            "sk.actor.discover_identity", return_value=identity("bot", "B1")
        ), mock.patch(
            "sk.channels.resolve_channel",
            return_value={"id": "C1", "name": "public", "is_member": False},
        ), mock.patch(
            "sk.client.SlackClient.call",
            return_value={"ok": True, "channel": {"id": "C1", "is_member": False}},
        ):
            with self.assertRaises(ActorSelectionError):
                actor.select_write_target(Config(), "C1")

    def test_explicit_user_proceeds_when_channel_read_scope_is_missing(self) -> None:
        lookup_error = SlackAPIError("conversations.info", "missing_scope")
        wrapped_error = InvalidArgument("channel 'C1' not accessible: missing_scope")
        wrapped_error.__cause__ = lookup_error
        with mock.patch.dict(
            os.environ,
            {"SLACK_USER_TOKEN": "user-token", "SLACK_WRITE_ACTOR": "user"},
            clear=True,
        ), mock.patch(
            "sk.actor.discover_identity", return_value=identity("user", "U1")
        ), mock.patch(
            "sk.channels.resolve_channel", side_effect=wrapped_error
        ):
            context, channel, state = actor.select_write_target(Config(), "C1")

        self.assertEqual(context.selected, "user")
        self.assertEqual(channel, {"id": "C1"})
        self.assertEqual(state, "unknown")
        self.assertTrue(
            any("只读预检无法证明写权限" in warning for warning in context.warnings)
        )

    def test_user_authorship_uses_authenticated_user_even_with_bot_id(self) -> None:
        context = actor.ActorContext(
            requested="user",
            selected="user",
            source_env="SLACK_USER_TOKEN",
            identity=identity("user", "U1"),
            token="user-token",
            timeout=30,
            retry_wait_budget=30,
            cache_root=Path("/tmp/cache"),
            files_root=Path("/tmp/files"),
        )

        self.assertTrue(
            actor.actor_matches_message(
                context, {"user": "U1", "bot_id": "B-APP"}
            )
        )
        self.assertFalse(
            actor.actor_matches_message(
                context, {"user": "U2", "bot_id": "B-APP"}
            )
        )

    def test_auto_authorship_does_not_let_bot_claim_user_token_message(self) -> None:
        original = {"user": "U1", "bot_id": "B-APP", "ts": "1700000000.000200"}
        with mock.patch.dict(
            os.environ,
            {
                "SLACK_BOT_TOKEN": "bot-token",
                "SLACK_USER_TOKEN": "user-token",
            },
            clear=True,
        ), mock.patch(
            "sk.actor.discover_identity",
            side_effect=lambda token, **_: SlackIdentity(
                actor="bot" if token == "bot-token" else "user",
                team_id="T1",
                user_id="U-BOT" if token == "bot-token" else "U1",
                bot_id="B-APP" if token == "bot-token" else None,
                workspace_url="https://example.slack.com",
            ),
        ), mock.patch("sk.write_target._fetch_single", return_value=original):
            context, _message = select_message_author(
                Config(),
                channel_id="C1",
                ts="1700000000.000200",
                thread_ts=None,
            )
            self.assertEqual(context.selected, "user")

            actor.set_requested("bot")
            with self.assertRaises(ActorSelectionError):
                select_message_author(
                    Config(),
                    channel_id="C1",
                    ts="1700000000.000200",
                    thread_ts=None,
                )

    def test_explicit_actor_allows_unknown_thread_preflight_on_missing_scope(self) -> None:
        context = actor.ActorContext(
            requested="user", selected="user", source_env="SLACK_USER_TOKEN",
            identity=identity("user", "U1"), token="user-token", timeout=30,
            retry_wait_budget=30, cache_root=Path("/tmp/cache"),
            files_root=Path("/tmp/files"),
        )
        client = mock.Mock()
        client.call.side_effect = SlackAPIError("conversations.replies", "missing_scope")
        with mock.patch.object(actor.ActorContext, "read_client", return_value=client):
            warning = validate_thread_root(context, "C1", "1700000000.000200")

        self.assertIn("显式 actor", warning or "")

    def test_auto_actor_refuses_unknown_thread_preflight(self) -> None:
        context = actor.ActorContext(
            requested="auto", selected="user", source_env="SLACK_USER_TOKEN",
            identity=identity("user", "U1"), token="user-token", timeout=30,
            retry_wait_budget=30, cache_root=Path("/tmp/cache"),
            files_root=Path("/tmp/files"),
        )
        client = mock.Mock()
        client.call.side_effect = SlackAPIError("conversations.replies", "missing_scope")
        with mock.patch.object(actor.ActorContext, "read_client", return_value=client):
            with self.assertRaises(InvalidArgument):
                validate_thread_root(context, "C1", "1700000000.000200")

    def test_auto_thread_preflight_falls_back_to_bot_before_write(self) -> None:
        bot = actor.ActorContext(
            requested="auto", selected="bot", source_env="SLACK_BOT_TOKEN",
            identity=identity("bot", "B1"), token="bot-token", timeout=30,
            retry_wait_budget=30, cache_root=Path("/tmp/cache"),
            files_root=Path("/tmp/files"),
        )
        user = actor.ActorContext(
            requested="auto", selected="user", source_env="SLACK_USER_TOKEN",
            identity=identity("user", "U1"), token="user-token", timeout=30,
            retry_wait_budget=30, cache_root=Path("/tmp/cache"),
            files_root=Path("/tmp/files"),
        )
        channel = {"id": "C1", "name": "private", "is_member": True}
        with mock.patch(
            "sk.write_target.select_write_target",
            side_effect=[(user, channel, "yes"), (bot, channel, "yes")],
        ) as selected, mock.patch(
            "sk.write_target.validate_thread_root",
            side_effect=[InvalidArgument("user missing_scope"), None],
        ):
            context, _channel, state, warning = select_write_target_with_thread(
                Config(), "C1", "1700000000.000200"
            )

        self.assertEqual(selected.call_count, 2)
        self.assertEqual(context.selected, "bot")
        self.assertEqual(context.fallback_reason, "user_thread_preflight_failed")
        self.assertEqual(state, "yes")
        self.assertIsNone(warning)

        for requested, first, attempts in (("auto", user, 2), ("user", user, 1),
                                           ("auto", bot, 1)):
            with self.subTest(requested=requested, first=first.selected), mock.patch(
                "sk.write_target.requested_for", return_value=requested
            ), mock.patch(
                "sk.write_target.select_write_target",
                side_effect=[(first, channel, "yes"), (bot, channel, "yes")],
            ) as selected, mock.patch(
                "sk.write_target.validate_thread_root",
                side_effect=InvalidArgument("thread 不可读"),
            ), mock.patch.object(actor.ActorContext, "write_client",
                                 side_effect=AssertionError("预检失败不得写入")):
                error = ActorSelectionError if attempts == 2 else InvalidArgument
                with self.assertRaises(error):
                    select_write_target_with_thread(Config(), "C1", "1700000000.000200")
                self.assertEqual(selected.call_count, attempts)


if __name__ == "__main__":
    unittest.main()
