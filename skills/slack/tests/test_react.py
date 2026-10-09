from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sk.actor import set_requested  # noqa: E402
from sk.cli import main  # noqa: E402
from sk.identity import SlackIdentity  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()
        self.headers = Message()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class ReactionTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_requested, None)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "SLACK_BOT_TOKEN": "bot-fixture",
            "SLACK_USER_TOKEN": "user-fixture",
        }, clear=True))
        self.stack.enter_context(mock.patch("sk.config.load_dotenv"))
        self.discover = self.stack.enter_context(mock.patch(
            "sk.actor.discover_identity", side_effect=self.identity,
        ))
        self.stack.enter_context(mock.patch("sk.channels.resolve_channel", return_value={
            "id": "C123456", "is_member": True,
        }))
        self.read = self.stack.enter_context(mock.patch("sk.client.SlackClient.call", return_value={
            "ok": True, "channel": {"id": "C123456", "is_member": True},
        }))
        self.opened = self.stack.enter_context(mock.patch(
            "urllib.request.urlopen", return_value=FakeResponse({"ok": True}),
        ))

    @staticmethod
    def identity(token, **_kwargs):
        is_bot = token == "bot-fixture"
        return SlackIdentity(
            actor="bot" if is_bot else "user", team_id="T1",
            user_id="UBOT" if is_bot else "UUSER",
            bot_id="B1" if is_bot else None,
            workspace_url="https://example.slack.com",
        )

    def invoke(self, *extra, target=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        if target is None:
            target = ["--channel", "C123456", "--ts", "1700000000.000200"]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["react", "--emoji", "lark_onesecond", *target, *extra])
        payload = json.loads(stdout.getvalue()) if stdout.getvalue() else None
        return code, payload, stderr.getvalue()

    def test_remove_uses_fixed_actor_and_exact_reply_timestamp(self):
        for actor in ("bot", "user"):
            with self.subTest(actor=actor):
                self.opened.reset_mock()
                self.discover.reset_mock()
                code, payload, _ = self.invoke("--remove", "--as", actor, target=[
                    "--url", "https://example.slack.com/archives/C123456/"
                    "p1700000000000200?thread_ts=1700000000.000100",
                ])
                self.assertEqual(code, 0)
                self.assertEqual(payload["result"], "removed")
                self.assertEqual(payload["operation_status"], "succeeded")
                self.assertEqual(payload["actor"]["selected"], actor)
                self.assertIsNone(payload["actor"]["fallback_reason"])
                self.assertNotIn("already_reacted", payload)
                self.discover.assert_called_once()
                self.opened.assert_called_once()
                request = self.opened.call_args.args[0]
                self.assertEqual(request.full_url, "https://slack.com/api/reactions.remove")
                self.assertEqual(request.get_header("Authorization"), f"Bearer {actor}-fixture")
                self.assertEqual(parse_qs(request.data.decode()), {
                    "channel": ["C123456"], "timestamp": ["1700000000.000200"],
                    "name": ["lark_onesecond"],
                })

    def test_remove_rejects_auto_before_authentication(self):
        for extra in ([], ["--as", "auto"]):
            with self.subTest(extra=extra):
                code, payload, error = self.invoke("--remove", *extra)
                self.assertEqual(code, 4)
                self.assertIsNone(payload)
                self.assertIn("必须固定原添加者身份", error)
        self.discover.assert_not_called()
        self.opened.assert_not_called()

    def test_remove_accepts_configured_actor_but_cli_auto_overrides_it(self):
        os.environ["SLACK_WRITE_ACTOR"] = "user"
        code, payload, _ = self.invoke("--remove")
        self.assertEqual(code, 0)
        self.assertEqual(payload["actor"]["selected"], "user")
        self.opened.reset_mock()
        code, _, _ = self.invoke("--remove", "--as", "auto")
        self.assertEqual(code, 4)
        self.opened.assert_not_called()

    def test_remove_without_selected_token_does_not_use_other_actor(self):
        del os.environ["SLACK_USER_TOKEN"]
        code, _, _ = self.invoke("--remove", "--as", "user")
        self.assertEqual(code, 4)
        self.discover.assert_not_called()
        self.opened.assert_not_called()

    def test_no_reaction_and_permissions_are_failures_without_retry(self):
        for error in ("no_reaction", "missing_scope", "no_permission"):
            with self.subTest(error=error):
                self.opened.reset_mock()
                self.discover.reset_mock()
                self.opened.return_value = FakeResponse({"ok": False, "error": error})
                code, payload, _ = self.invoke("--remove", "--as", "user")
                self.assertEqual(code, 1)
                self.assertEqual(payload["status"], "failed")
                self.assertEqual(payload["reason"], error)
                self.assertEqual(payload["method"], "reactions.remove")
                self.assertEqual(payload["actor"]["selected"], "user")
                self.opened.assert_called_once()
                self.discover.assert_called_once()

    def test_ambiguous_remove_never_retries_or_changes_actor(self):
        failures = [
            URLError("lost"), TimeoutError(),
            HTTPError("https://slack.com", 500, "boom", Message(), io.BytesIO()),
            FakeResponse({"ok": False, "error": "internal_error"}),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.opened.reset_mock()
                self.discover.reset_mock()
                self.opened.side_effect = [failure]
                code, payload, _ = self.invoke("--remove", "--as", "user")
                self.assertEqual(code, 5)
                self.assertEqual(payload["status"], "unknown")
                self.assertFalse(payload["retry_safe"])
                self.assertEqual(payload["method"], "reactions.remove")
                self.assertEqual(payload["actor"]["selected"], "user")
                self.opened.assert_called_once()
                self.discover.assert_called_once()

    def test_add_keeps_default_method_and_already_reacted_semantics(self):
        for already in (False, True):
            with self.subTest(already=already):
                self.opened.return_value = FakeResponse(
                    {"ok": False, "error": "already_reacted"} if already else {"ok": True}
                )
                code, payload, _ = self.invoke()
                self.assertEqual(code, 0)
                self.assertEqual(payload["result"], "reacted")
                self.assertEqual(payload["already_reacted"], already)
                self.assertEqual(payload["actor"]["selected"], "user")
                self.assertEqual(self.opened.call_args.args[0].full_url,
                                 "https://slack.com/api/reactions.add")

    def test_remove_respects_allowed_channels_before_authentication(self):
        os.environ["SLACK_SKILL_ALLOWED_CHANNELS"] = "C999999"
        code, _, error = self.invoke("--remove", "--as", "user")
        self.assertEqual(code, 4)
        self.assertIn("SLACK_SKILL_ALLOWED_CHANNELS", error)
        self.discover.assert_not_called()
        self.opened.assert_not_called()

    def test_remove_rejects_missing_target_and_empty_emoji_without_network(self):
        for extra, target in (([], []), ([], ["--channel", "C123456"]),
                              (["--emoji", "::"], None)):
            with self.subTest(extra=extra, target=target):
                code, _, _ = self.invoke("--remove", "--as", "user", *extra, target=target)
                self.assertEqual(code, 4)
        self.discover.assert_not_called()
        self.opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
