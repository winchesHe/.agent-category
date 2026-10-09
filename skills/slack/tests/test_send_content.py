from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sk import cache  # noqa: E402
from sk.actor import ActorContext  # noqa: E402
from sk.errors import InvalidArgument  # noqa: E402
from sk.identity import SlackIdentity  # noqa: E402
from sk.send_content import compile_content, preview_digest  # noqa: E402


class SendContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.context = ActorContext(
            requested="user",
            selected="user",
            source_env="SLACK_USER_TOKEN",
            identity=SlackIdentity("user", "T1", "U1", None, None),
            token="fixture-token",
            timeout=10,
            retry_wait_budget=10,
            cache_root=root,
            files_root=root / "files",
        )
        cache.save_users(
            self.context.cache_dir,
            {
                "U2": {
                    "id": "U2",
                    "name": "alice",
                    "deleted": False,
                    "profile": {"display_name": "alice", "email": "alice@example.com"},
                }
            },
        )
        cache.save_channels(
            self.context.cache_dir,
            {"C2": {"id": "C2", "name": "release-ops"}},
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def compile(self, text: str, **overrides):
        params = {
            "format_name": "mrkdwn",
            "mention_mode": "resolve",
            "allow_broadcast": False,
            "allow_usergroup_mention": False,
            "context": self.context,
        }
        params.update(overrides)
        return compile_content(text, **params)

    def test_resolves_mentions_but_not_code_or_email(self) -> None:
        result = self.compile(
            "Hi @alice in #release-ops `@alice` alice@example.com\n```\n@alice\n```"
        )
        self.assertIn("<@U2>", result.params["text"])
        self.assertIn("<#C2>", result.params["text"])
        self.assertIn("`@alice`", result.params["text"])
        self.assertIn("alice@example.com", result.params["text"])

    def test_native_broadcast_and_usergroup_cannot_bypass_guard(self) -> None:
        with self.assertRaises(InvalidArgument):
            self.compile("<!here>")
        with self.assertRaises(InvalidArgument):
            self.compile("<!subteam^S123>")

    def test_literal_mode_still_blocks_human_broadcasts(self) -> None:
        for format_name in ("markdown", "mrkdwn"):
            with self.subTest(format_name=format_name):
                with self.assertRaises(InvalidArgument):
                    self.compile(
                        "notify @channel",
                        format_name=format_name,
                        mention_mode="literal",
                    )

    def test_escaped_broadcast_stays_escaped_after_guard(self) -> None:
        for format_name in ("markdown", "mrkdwn"):
            with self.subTest(format_name=format_name):
                result = self.compile(
                    r"notify \@channel and \#release-ops",
                    format_name=format_name,
                    mention_mode="literal",
                )
                self.assertEqual(
                    result.params["markdown_text" if format_name == "markdown" else "text"],
                    r"notify \@channel and \#release-ops",
                )
                self.assertEqual(result.broadcasts, ())

    def test_broadcast_inside_code_is_literal(self) -> None:
        result = self.compile("`<!channel>`")
        self.assertEqual(result.params["text"], "`<!channel>`")

    def test_plain_requires_literal_mentions(self) -> None:
        with self.assertRaises(InvalidArgument):
            self.compile("hello", format_name="plain")

    def test_markdown_preserves_source_and_enforces_native_limit(self) -> None:
        source = "**hello**\n\n| A |\n|---|\n| 1 |"
        result = self.compile(source, format_name="markdown", mention_mode="literal")
        self.assertEqual(result.params, {"markdown_text": source})
        self.assertEqual(
            self.compile("x" * 12000, format_name="markdown").params,
            {"markdown_text": "x" * 12000},
        )
        with self.assertRaises(InvalidArgument):
            self.compile("x" * 12001, format_name="markdown")

    def test_markdown_mentions_preserve_code_and_destinations(self) -> None:
        result = self.compile(
            "@alice #release-ops `@missing`\n"
            "[link](https://example.com/@channel?q=1#release-ops)",
            format_name="markdown",
        )
        self.assertEqual([item["id"] for item in result.mentions], ["U2", "C2"])
        self.assertIn("<@U2> <#C2> `@missing`", result.params["markdown_text"])
        self.assertIn("https://example.com/@channel", result.params["markdown_text"])
        self.assertTrue(result.warnings)
        self.assertEqual(result.broadcasts, ())

    def test_markdown_broadcast_needs_permission_without_local_rendering(self) -> None:
        with self.assertRaises(InvalidArgument):
            self.compile("**@channel**", format_name="markdown")
        result = self.compile("**@channel**", format_name="markdown", allow_broadcast=True)
        self.assertEqual(result.params, {"markdown_text": "**<!channel>**"})
        self.assertEqual(result.broadcasts, ({"type": "broadcast", "name": "channel"},))

    def test_markdown_code_keeps_control_tokens_literal_in_source(self) -> None:
        source = "`<!channel>` & `<@U2>`"
        result = self.compile(source, format_name="markdown")
        self.assertEqual(result.params, {"markdown_text": source})
        self.assertEqual(result.mentions, ())
        self.assertEqual(result.broadcasts, ())

    def test_preview_digest_is_stable_and_content_sensitive(self) -> None:
        one = preview_digest({"b": 2, "a": 1})
        two = preview_digest({"a": 1, "b": 2})
        self.assertEqual(one, two)
        self.assertNotEqual(one, preview_digest({"a": 2, "b": 2}))

    def test_email_and_native_mentions_are_single_pass(self) -> None:
        result = self.compile("@{alice@example.com} <@U2> <#C2>")
        self.assertEqual(result.params["text"], "<@U2> <@U2> <#C2>")
        self.assertEqual([item["id"] for item in result.mentions], ["U2", "U2", "C2"])

    def test_urls_and_issue_numbers_are_not_mentions(self) -> None:
        text = (
            "https://example.com/@alice https://example.com/#release-ops "
            "[docs](https://example.com/@channel) issue #123"
        )
        result = self.compile(text)
        self.assertEqual(result.params["text"], text)
        self.assertEqual(result.mentions, ())
        self.assertEqual(result.broadcasts, ())

    def test_markdown_link_destinations_with_balanced_or_relative_paths_are_protected(self) -> None:
        text = "[one](https://example.com/a(@alice)) [two](/users/@alice)"
        result = self.compile(text)
        self.assertEqual(result.params["text"], text)
        self.assertEqual(result.mentions, ())

    def test_bare_url_with_balanced_parentheses_is_protected(self) -> None:
        text = "https://example.com/a(@alice)"
        result = self.compile(text)
        self.assertEqual(result.params["text"], text)
        self.assertEqual(result.mentions, ())

    def test_arbitrary_code_spans_and_fences_are_protected(self) -> None:
        text = (
            "``@alice #release-ops``\n"
            "````python\n@channel #release-ops\n````\n"
            "~~~text\n@alice <!here>\n~~~"
        )
        result = self.compile(text)
        self.assertEqual(result.params["text"], text)
        self.assertEqual(result.mentions, ())
        self.assertEqual(result.broadcasts, ())


if __name__ == "__main__":
    unittest.main()
