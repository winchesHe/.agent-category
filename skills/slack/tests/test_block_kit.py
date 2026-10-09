from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sk import cache  # noqa: E402
from sk.actor import ActorContext  # noqa: E402
from sk.block_kit import compile_blocks, load_blocks_file  # noqa: E402
from sk.errors import InvalidArgument  # noqa: E402
from sk.identity import SlackIdentity  # noqa: E402


class BlockKitTests(unittest.TestCase):
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
                    "profile": {"display_name": "alice"},
                }
            },
        )
        cache.save_channels(self.context.cache_dir, {})

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_json(self, value: object) -> Path:
        path = Path(self.temp.name) / "blocks.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_loads_non_empty_block_array(self) -> None:
        blocks = [{"type": "context", "elements": []}]
        self.assertEqual(load_blocks_file(str(self._write_json(blocks))), blocks)

    def test_rejects_invalid_or_oversized_block_array(self) -> None:
        for value in ([], {}, [{"type": ""}], [{"type": "section"}] * 51):
            with self.subTest(value_type=type(value).__name__, size=len(value)):
                with self.assertRaises(InvalidArgument):
                    load_blocks_file(str(self._write_json(value)))

    def test_rejects_non_standard_json_constants(self) -> None:
        path = Path(self.temp.name) / "blocks.json"
        path.write_text('[{"type":"section","value":NaN}]', encoding="utf-8")
        with self.assertRaisesRegex(InvalidArgument, "non-standard JSON"):
            load_blocks_file(str(path))

    def test_context_footer_preserves_links_emoji_code_and_schema(self) -> None:
        footer = ":stopwatch: 2分10秒 · <https://example.com/tasks/12|DEMO-12>"
        source = [
            {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [
                {"type": "text", "text": "完成", "style": {"bold": True}}
            ]}]},
            {"type": "context", "block_id": "footer", "elements": [
                {"type": "mrkdwn", "text": footer, "verbatim": True},
                {"type": "mrkdwn", "text": "app · `feature/a` · <https://example.com/pr/1|PR #1>"}
            ]},
        ]
        loaded = load_blocks_file(str(self._write_json(source)))
        result = compile_blocks(loaded, mention_mode="resolve", allow_broadcast=False,
                                allow_usergroup_mention=False, context=self.context)
        self.assertEqual(result.blocks, source)
        self.assertEqual(result.mentions, ())
        self.assertEqual(result.broadcasts, ())

    def test_nested_mrkdwn_resolves_mentions_without_changing_plain_text(self) -> None:
        for verbatim in (True, False):
            source = [{"type": "container", "child_blocks": [
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": "Owner: @alice <#C1>", "verbatim": verbatim},
                    {"type": "plain_text", "text": "@alice <!channel>"},
                ]}
            ]}]
            with self.subTest(verbatim=verbatim):
                result = compile_blocks(source, mention_mode="resolve", allow_broadcast=False,
                                        allow_usergroup_mention=False, context=self.context)
                fields = result.blocks[0]["child_blocks"][0]["fields"]
                self.assertEqual(fields[0], {"type": "mrkdwn", "text": "Owner: <@U2> <#C1>",
                                             "verbatim": verbatim})
                self.assertEqual(fields[1], source[0]["child_blocks"][0]["fields"][1])
                self.assertEqual([item["id"] for item in result.mentions], ["U2", "C1"])
                self.assertEqual(source[0]["child_blocks"][0]["fields"][0]["text"], "Owner: @alice <#C1>")

    def test_nested_mrkdwn_requires_each_notification_permission(self) -> None:
        source = [{"type": "container", "child_blocks": [{"type": "context", "elements": [
            {"type": "mrkdwn", "text": "<!channel> <!subteam^S1>", "verbatim": True}
        ]}]}]
        for mode in ("literal", "resolve"):
            for allow_broadcast, allow_group in ((False, False), (False, True), (True, False), (True, True)):
                options = dict(mention_mode=mode, allow_broadcast=allow_broadcast,
                               allow_usergroup_mention=allow_group, context=self.context)
                with self.subTest(mode=mode, broadcast=allow_broadcast, group=allow_group):
                    if not (allow_broadcast and allow_group):
                        flag = "--allow-broadcast" if not allow_broadcast else "--allow-usergroup-mention"
                        with self.assertRaisesRegex(InvalidArgument, flag):
                            compile_blocks(source, **options)
                    else:
                        result = compile_blocks(source, **options)
                        self.assertEqual(result.blocks, source)
                        self.assertEqual(result.broadcasts, ({"type": "broadcast", "name": "channel"},
                                                             {"type": "usergroup", "id": "S1"}))

    def test_mrkdwn_literal_keeps_names_code_and_link_destinations(self) -> None:
        source = [{"type": "section", "text": {"type": "mrkdwn", "text": (
            "@alice <@U2> `<!channel> <!subteam^S1>` "
            "<https://example.com/@channel?q=@alice|详情>"
        )}}]
        result = compile_blocks(source, mention_mode="literal", allow_broadcast=False,
                                allow_usergroup_mention=False, context=self.context)
        self.assertEqual(result.blocks, source)
        self.assertEqual([item["id"] for item in result.mentions], ["U2"])
        self.assertEqual(result.broadcasts, ())

    def test_list_preserves_styles_links_and_mentions(self) -> None:
        elements = [{"type": "text", "text": "修复", "style": {"bold": True}},
                    {"type": "text", "text": "：保留员工。"},
                    {"type": "link", "url": "https://example.com", "text": "PR"},
                    {"type": "user", "user_id": "U2"},
                    {"type": "usergroup", "usergroup_id": "S1"}]
        blocks = [{"type": "rich_text", "elements": [{"type": "rich_text_list",
                   "style": "bullet", "elements": [{"type": "rich_text_section",
                   "elements": elements}]}]}]
        loaded = load_blocks_file(str(self._write_json(blocks)))
        with self.assertRaisesRegex(InvalidArgument, "--allow-usergroup-mention"):
            compile_blocks(loaded, mention_mode="literal", allow_broadcast=False,
                           allow_usergroup_mention=False, context=self.context)
        result = compile_blocks(loaded, mention_mode="literal", allow_broadcast=False,
                                allow_usergroup_mention=True, context=self.context)
        self.assertEqual(result.blocks, blocks)
        self.assertEqual(result.mentions[0]["id"], "U2")
        self.assertEqual(result.broadcasts, ({"type": "usergroup", "id": "S1"},))

    def test_rich_text_cannot_bypass_notification_guards(self) -> None:
        cases = (
            (
                {"type": "broadcast", "range": "channel"},
                "--allow-broadcast",
            ),
            (
                {"type": "usergroup", "usergroup_id": "S123"},
                "--allow-usergroup-mention",
            ),
        )
        for element, expected_error in cases:
            with self.subTest(element_type=element["type"]):
                with self.assertRaisesRegex(InvalidArgument, expected_error):
                    compile_blocks(
                        [
                            {
                                "type": "rich_text",
                                "elements": [
                                    {
                                        "type": "rich_text_section",
                                        "elements": [element],
                                    }
                                ],
                            }
                        ],
                        mention_mode="literal",
                        allow_broadcast=False,
                        allow_usergroup_mention=False,
                        context=self.context,
                    )

    def test_collects_allowed_rich_text_references(self) -> None:
        result = compile_blocks(
            [
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {"type": "user", "user_id": "U2"},
                                {"type": "channel", "channel_id": "C1"},
                                {"type": "broadcast", "range": "here"},
                                {"type": "usergroup", "usergroup_id": "S1"},
                            ],
                        }
                    ],
                }
            ],
            mention_mode="literal",
            allow_broadcast=True,
            allow_usergroup_mention=True,
            context=self.context,
        )
        self.assertEqual(
            result.mentions,
            (
                {"type": "user", "input": "<@U2>", "id": "U2"},
                {"type": "channel", "input": "<#C1>", "id": "C1"},
            ),
        )
        self.assertEqual(
            result.broadcasts,
            (
                {"type": "broadcast", "name": "here"},
                {"type": "usergroup", "id": "S1"},
            ),
        )

    def test_nested_markdown_keeps_schema_and_checks_notifications(self) -> None:
        source = [{"type": "container", "child_blocks": [
            {"type": "markdown", "text": "**Owner:** @alice"}
        ]}]
        options = dict(mention_mode="resolve", allow_broadcast=False,
                       allow_usergroup_mention=False, context=self.context)
        result = compile_blocks(source, **options)
        self.assertEqual(result.blocks[0]["child_blocks"][0],
                         {"type": "markdown", "text": "**Owner:** <@U2>"})
        self.assertEqual(source[0]["child_blocks"][0]["text"], "**Owner:** @alice")
        self.assertEqual([item["id"] for item in result.mentions], ["U2"])
        for token, expected in (("<!channel>", "--allow-broadcast"),
                                ("<!subteam^S1>", "--allow-usergroup-mention")):
            source[0]["child_blocks"][0]["text"] = token
            with self.subTest(token=token), self.assertRaisesRegex(InvalidArgument, expected):
                compile_blocks(source, **options)

    def test_reference_examples_load_and_compile_without_notifications(self) -> None:
        reference = (ROOT / "references" / "block-kit.md").read_text(encoding="utf-8")
        snippets = re.findall(r"```json\n(.*?)\n```", reference, re.S)
        self.assertTrue(snippets)
        for index, snippet in enumerate(snippets):
            with self.subTest(example=index):
                blocks = load_blocks_file(str(self._write_json(json.loads(snippet))))
                result = compile_blocks(
                    blocks, mention_mode="resolve", allow_broadcast=False,
                    allow_usergroup_mention=False, context=self.context,
                )
                self.assertEqual(result.mentions, ())
                self.assertEqual(result.broadcasts, ())

    def test_rejects_excessive_json_nesting(self) -> None:
        depth = 70
        path = Path(self.temp.name) / "blocks.json"
        path.write_text(
            '[{"type":"section","extra":' + "[" * depth + "0"
            + "]" * depth + "}]",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(InvalidArgument, "nesting cannot exceed"):
            load_blocks_file(str(path))

    def test_reports_parser_recursion_as_invalid_json(self) -> None:
        depth = sys.getrecursionlimit() + 100
        path = Path(self.temp.name) / "blocks.json"
        path.write_text(
            '[{"type":"section","extra":' + "[" * depth + "0"
            + "]" * depth + "}]",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(InvalidArgument, "must contain valid JSON"):
            load_blocks_file(str(path))

    def test_compile_blocks_loads_each_cache_once(self) -> None:
        blocks = [
            {
                "type": "context",
                "elements": [
                    {"type": "plain_text", "text": "status"},
                    {"type": "plain_text", "text": "owner"},
                ],
            }
        ]
        with mock.patch(
            "sk.send_content.cache.load_users", wraps=cache.load_users
        ) as load_users, mock.patch(
            "sk.send_content.cache.load_channels", wraps=cache.load_channels
        ) as load_channels:
            compile_blocks(
                blocks,
                mention_mode="literal",
                allow_broadcast=False,
                allow_usergroup_mention=False,
                context=self.context,
            )

        load_users.assert_called_once_with(self.context.cache_dir)
        load_channels.assert_called_once_with(self.context.cache_dir)


if __name__ == "__main__":
    unittest.main()
