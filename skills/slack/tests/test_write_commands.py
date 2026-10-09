from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sk.actor import ActorContext, activate  # noqa: E402
from sk.cli import main as cli_main  # noqa: E402
from sk.cmd_edit import run as run_edit  # noqa: E402
from sk.cmd_files_upload import run as run_files_upload  # noqa: E402
from sk.cmd_send import run as run_send  # noqa: E402
from sk.identity import SlackIdentity  # noqa: E402
from sk.errors import InvalidArgument, MentionResolutionError, SlackAPIError, WriteResultUnknown  # noqa: E402


class WriteCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.context = ActorContext(
            requested="auto",
            selected="bot",
            source_env="SLACK_BOT_TOKEN",
            identity=SlackIdentity(
                "bot", "T1", "U-BOT", "B1", "https://example.slack.com"
            ),
            token="fixture-token",
            timeout=10,
            retry_wait_budget=10,
            cache_root=root,
            files_root=root / "files",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_bot_edit_always_sets_as_user_true(self) -> None:
        write = mock.Mock()
        write.call.return_value = {"ok": True, "message": {"text": "new"}}
        args = argparse.Namespace(
            url="https://example.slack.com/archives/C123456/p1700000000000200",
            channel=None,
            ts=None,
            thread_ts=None,
            text="new",
            text_file=None,
            output=None,
        )
        original = {"bot_id": "B1", "user": "U-BOT", "text": "old"}
        with mock.patch(
            "sk.cmd_edit.select_message_author",
            return_value=(self.context, original),
        ), mock.patch.object(ActorContext, "write_client", return_value=write), mock.patch(
            "sk.cmd_edit.emit"
        ):
            run_edit(args)

        write.call.assert_called_once_with(
            "chat.update", channel="C123456", ts="1700000000.000200",
            markdown_text="new", as_user=True,
        )

    def test_send_dry_run_never_constructs_write_client(self) -> None:
        args = argparse.Namespace(
            channel="C123456",
            text="hello",
            text_file=None,
            thread_ts=None,
            format_name="markdown",
            mention_mode="literal",
            dry_run=True,
            confirm_preview=None,
            allow_broadcast=False,
            allow_usergroup_mention=False,
            unfurl_links=False,
            output=None,
        )
        channel = {"id": "C123456", "name": "release", "is_member": True}
        with mock.patch(
            "sk.cmd_send.select_write_target_with_thread",
            return_value=(self.context, channel, "yes", None),
        ), mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), mock.patch(
            "sk.cmd_send.emit"
        ) as emitted, mock.patch.object(
            ActorContext, "write_client", side_effect=AssertionError("write called")
        ):
            run_send(args)

        payload = emitted.call_args.args[0]
        self.assertEqual(payload["status"], "preview")
        self.assertEqual(payload["compiled"], {"markdown_text": "hello"})

    def test_send_dry_run_includes_block_kit_in_preview_digest(self) -> None:
        blocks_path = Path(self.temp.name) / "blocks.json"
        blocks = [
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "<https://example.com/env|Environment: staging>", "verbatim": True}
                ],
            }
        ]
        blocks_path.write_text(json.dumps(blocks), encoding="utf-8")
        args = argparse.Namespace(
            channel="C123456", text="fallback", text_file=None,
            blocks_file=str(blocks_path), thread_ts=None, format_name="markdown",
            mention_mode="literal", dry_run=True, confirm_preview=None,
            allow_broadcast=False, allow_usergroup_mention=False,
            unfurl_links=False, output=None,
        )
        channel = {"id": "C123456", "name": "release", "is_member": True}
        with mock.patch(
            "sk.cmd_send.select_write_target_with_thread",
            return_value=(self.context, channel, "yes", None),
        ), mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), mock.patch(
            "sk.cmd_send.emit"
        ) as emitted, mock.patch.object(
            ActorContext, "write_client", side_effect=AssertionError("write called")
        ), mock.patch(
            "sk.send_content.cache.load_users", return_value={}
        ) as load_users, mock.patch(
            "sk.send_content.cache.load_channels", return_value={}
        ) as load_channels:
            run_send(args)

        payload = emitted.call_args.args[0]
        expected_blocks = json.loads(json.dumps(blocks))
        self.assertEqual(payload["compiled"]["blocks"], expected_blocks)
        self.assertEqual(payload["format"], "block_kit")
        self.assertNotIn("markdown_text", payload["compiled"])
        self.assertTrue(payload["compiled"]["mrkdwn"])
        self.assertFalse(payload["compiled"]["link_names"])
        self.assertTrue(payload["preview_digest"].startswith("sha256:"))
        load_users.assert_called_once_with(self.context.cache_dir)
        load_channels.assert_called_once_with(self.context.cache_dir)

    def test_send_mention_preflight_prefers_user_then_bot(self) -> None:
        from sk.send_content import CompiledContent

        user = replace(
            self.context, selected="user", source_env="SLACK_USER_TOKEN",
            identity=SlackIdentity("user", "T1", "U1", None, "https://example.slack.com"),
            token="user-token",
        )
        args = argparse.Namespace(
            channel="C123456", text="@alice", text_file=None, thread_ts=None,
            format_name="markdown", mention_mode="resolve", dry_run=False,
            confirm_preview=None, allow_broadcast=False,
            allow_usergroup_mention=False, unfurl_links=False, output=None,
        )
        channel = {"id": "C123456", "name": "release", "is_member": True}
        compiled = CompiledContent({"markdown_text": "<@U2>"}, (), (), ())
        writer = mock.Mock()
        writer.call.return_value = {"ok": True, "ts": "1700000000.000200"}
        with mock.patch("sk.cmd_send.requested_for", return_value="auto"), \
             mock.patch("sk.cmd_send.select_write_target_with_thread",
                        side_effect=[(user, channel, "yes", None),
                                     (self.context, channel, "yes", None)]) as select, \
             mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), \
             mock.patch("sk.cmd_send._compile_payload",
                        side_effect=[MentionResolutionError("不可见"),
                                     (compiled, None)]) as compile_payload, \
             mock.patch.object(ActorContext, "write_client", autospec=True,
                               return_value=writer) as write_client, \
             mock.patch("sk.cmd_send.emit"):
            run_send(args)

        self.assertEqual(select.call_args.kwargs, {"force": "bot"})
        self.assertEqual(compile_payload.call_args_list[0].kwargs["context"].selected, "user")
        self.assertEqual(write_client.call_args.args[0].selected, "bot")
        writer.call.assert_called_once()
        self.assertEqual(write_client.call_args.args[0].fallback_reason,
                         "user_mention_resolution_failed")

    def test_markdown_send_posts_the_previewed_source_once(self) -> None:
        args = argparse.Namespace(
            channel="C123456", text="日期：**2026-09-09**，见[PR](https://example.com/pr#comment)",
            text_file=None, thread_ts=None, format_name="markdown", mention_mode="literal",
            dry_run=True, confirm_preview=None, allow_broadcast=False,
            allow_usergroup_mention=False, unfurl_links=False, output=None,
        )
        channel = {"id": "C123456", "name": "release", "is_member": True}
        write = mock.Mock()
        write.call.return_value = {"ok": True, "ts": "1700000000.000200", "message": {"text": "sent"}}
        read = mock.Mock()
        read.call.return_value = {"ok": True, "permalink": "https://example.com/message"}
        with mock.patch("sk.cmd_send.select_write_target_with_thread",
                        return_value=(self.context, channel, "yes", None)), \
             mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), \
             mock.patch("sk.cmd_send.emit") as emitted, \
             mock.patch.object(ActorContext, "read_client", return_value=read), \
             mock.patch.object(ActorContext, "write_client", return_value=write):
            run_send(args)
            write.call.assert_not_called()
            preview = emitted.call_args.args[0]
            args.confirm_preview = preview["preview_digest"]
            args.dry_run = False
            run_send(args)
            write.call.assert_called_once()
            request = write.call.call_args.kwargs
            self.assertEqual(request["markdown_text"], preview["compiled"]["markdown_text"])
            self.assertNotIn("text", request)
            self.assertNotIn("blocks", request)
            args.text += " 改动"
            with self.assertRaisesRegex(InvalidArgument, "digest 已变化"):
                run_send(args)
            write.call.assert_called_once()

    def test_markdown_failure_never_constructs_write_client(self) -> None:
        args = argparse.Namespace(
            channel="C123456", text="@channel", text_file=None, thread_ts=None,
            format_name="markdown", mention_mode="literal", dry_run=False,
            confirm_preview=None, allow_broadcast=False, allow_usergroup_mention=False,
            unfurl_links=False, output=None,
        )
        channel = {"id": "C123456", "name": "release", "is_member": True}
        with mock.patch("sk.cmd_send.select_write_target_with_thread",
                        return_value=(self.context, channel, "yes", None)), \
             mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), \
             mock.patch.object(ActorContext, "write_client", side_effect=AssertionError("write called")):
            for source in ("@channel", "<!subteam^S1>", "x" * 12001):
                args.text = source
                with self.subTest(source=source[:20]), self.assertRaises(InvalidArgument):
                    run_send(args)

    def test_markdown_edit_preview_binds_original_and_replaces_blocks(self) -> None:
        args = argparse.Namespace(
            url="https://example.slack.com/archives/C123456/p1700000000000200",
            channel=None, ts=None, thread_ts=None, text="**新内容**", text_file=None,
            format_name="markdown", mention_mode="literal", dry_run=True,
            confirm_preview=None, output=None,
        )
        original = {"user": "U-BOT", "text": "old", "blocks": [{"type": "divider"}]}
        write = mock.Mock()
        write.call.return_value = {"ok": True, "text": "新内容"}
        with mock.patch("sk.cmd_edit.select_message_author", return_value=(self.context, original)), \
             mock.patch("sk.cmd_edit.emit") as emitted, \
             mock.patch.object(ActorContext, "write_client", return_value=write):
            run_edit(args)
            write.call.assert_not_called()
            preview = emitted.call_args.args[0]
            args.confirm_preview = preview["preview_digest"]
            original["text"] = "concurrent edit"
            with self.assertRaisesRegex(InvalidArgument, "digest 已变化"):
                run_edit(args)
            write.call.assert_not_called()
            original["text"] = "old"
            args.dry_run = False
            run_edit(args)
        request = write.call.call_args.kwargs
        self.assertEqual(request["markdown_text"], "**新内容**")
        self.assertNotIn("text", request)
        self.assertNotIn("blocks", request)
        self.assertTrue(request["as_user"])
        self.assertNotIn("mrkdwn", request)
        write.call.assert_called_once()

    def test_edit_blocks_automatically_switches_from_default_markdown(self) -> None:
        path = Path(self.temp.name) / "blocks.json"
        path.write_text('[{"type":"section","text":{"type":"plain_text","text":"*新内容*"}}]', encoding="utf-8")
        args = argparse.Namespace(
            url="https://example.slack.com/archives/C123456/p1700000000000200",
            channel=None, ts=None, thread_ts=None, text="fallback", text_file=None,
            blocks_file=str(path), dry_run=True, output=None,
        )
        original = {"text": "旧 Markdown", "blocks": [{"type": "rich_text"}]}
        with mock.patch("sk.cmd_edit.select_message_author", return_value=(self.context, original)), \
             mock.patch("sk.cmd_edit.emit") as emitted, \
             mock.patch.object(ActorContext, "write_client", side_effect=AssertionError("write called")):
            run_edit(args)
        payload = emitted.call_args.args[0]
        self.assertEqual(payload["format"], "block_kit")
        self.assertEqual(payload["compiled"]["text"], "fallback")
        self.assertEqual(payload["compiled"]["blocks"][0]["text"]["text"], "*新内容*")
        self.assertNotIn("markdown_text", payload["compiled"])

    def test_default_edit_rejects_notifications_before_write(self) -> None:
        args = argparse.Namespace(
            url="https://example.slack.com/archives/C123456/p1700000000000200",
            channel=None, ts=None, thread_ts=None, text="<!channel>", text_file=None,
            output=None,
        )
        with mock.patch("sk.cmd_edit.select_message_author", return_value=(self.context, {})), \
             mock.patch.object(ActorContext, "write_client", side_effect=AssertionError("write called")):
            with self.assertRaisesRegex(InvalidArgument, "--allow-broadcast"):
                run_edit(args)

    def test_cli_send_and_edit_default_to_markdown(self) -> None:
        for command in ("send", "edit"):
            with self.subTest(command=command), \
                 mock.patch("sk.cli.cmd_" + command + ".run", return_value=0) as run:
                cli_main([command, "--channel", "C123456", "--text", "hello"])
                self.assertEqual(run.call_args.args[0].format_name, "markdown")

    def test_removed_public_formats_fail_before_network(self) -> None:
        for command in ("send", "edit"):
            for format_name in ("mrkdwn", "plain"):
                with self.subTest(command=command, format_name=format_name):
                    with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as caught:
                        cli_main([command, "--channel", "C123456", "--text", "hello",
                                  "--format", format_name])
                    self.assertEqual(caught.exception.code, 2)

    def test_invalid_blocks_fail_before_credentials_or_network(self) -> None:
        blocks_path = Path(self.temp.name) / "blocks.json"
        blocks_path.write_text("{}", encoding="utf-8")
        args = argparse.Namespace(
            channel="C123456", text="fallback", text_file=None,
            blocks_file=str(blocks_path), thread_ts=None, format_name="markdown",
            mention_mode="literal", dry_run=False, confirm_preview=None,
            allow_broadcast=False, allow_usergroup_mention=False,
            unfurl_links=False, output=None,
        )
        with mock.patch(
            "sk.cmd_send.Config", side_effect=AssertionError("credentials loaded")
        ), mock.patch(
            "sk.cmd_send.select_write_target_with_thread",
            side_effect=AssertionError("network preflight called"),
        ):
            with self.assertRaisesRegex(InvalidArgument, "non-empty JSON array"):
                run_send(args)

    def test_send_and_edit_preserve_mrkdwn_footer_and_bind_preview(self) -> None:
        path = Path(self.temp.name) / "blocks.json"
        blocks = [{"type": "context", "elements": [
            {"type": "mrkdwn", "text": ":stopwatch: 2分 · <https://example.com/pr|PR #1>", "verbatim": True}
        ]}]
        path.write_text(json.dumps(blocks), encoding="utf-8")
        for command, run, method in (("send", run_send, "chat.postMessage"), ("edit", run_edit, "chat.update")):
            with self.subTest(command=command):
                args = argparse.Namespace(
                    channel="C123456", text="fallback", text_file=None, blocks_file=str(path),
                    url="https://example.slack.com/archives/C123456/p1700000000000200",
                    ts=None, thread_ts=None, format_name="markdown", mention_mode="literal",
                    dry_run=True, confirm_preview=None, allow_broadcast=False,
                    allow_usergroup_mention=False, unfurl_links=False, output=None,
                )
                write = mock.Mock()
                write.call.return_value = {"ok": True, "ts": "1700000000.000200", "message": {"text": "sent"}}
                read = mock.Mock()
                read.call.return_value = {"ok": True, "permalink": "https://example.com/message"}
                channel = {"id": "C123456", "name": "release", "is_member": True}
                with mock.patch("sk.cmd_send.select_write_target_with_thread", return_value=(self.context, channel, "yes", None)), \
                     mock.patch("sk.cmd_edit.select_message_author", return_value=(self.context, {"text": "original"})), \
                     mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), \
                     mock.patch("sk.cmd_" + command + ".emit") as emitted, \
                     mock.patch.object(ActorContext, "read_client", return_value=read), \
                     mock.patch.object(ActorContext, "write_client", return_value=write):
                    run(args)
                    write.call.assert_not_called()
                    preview = emitted.call_args.args[0]
                    self.assertEqual(preview["compiled"]["blocks"], blocks)
                    args.confirm_preview = preview["preview_digest"]
                    args.dry_run = False
                    run(args)
                    write.call.assert_called_once()
                    self.assertEqual(write.call.call_args.args[0], method)
                    request = write.call.call_args.kwargs
                    self.assertEqual(request["blocks"], blocks)
                    self.assertEqual(request["text"], "fallback")
                    self.assertNotIn("markdown_text", request)
                    if command == "edit":
                        self.assertNotIn("mrkdwn", request)
                    changed = json.loads(json.dumps(blocks))
                    changed[0]["elements"][0]["text"] += " 改动"
                    path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaisesRegex(InvalidArgument, "digest 已变化"):
                        run(args)
                    write.call.assert_called_once()
                path.write_text(json.dumps(blocks), encoding="utf-8")

    def test_send_and_edit_reject_unapproved_mrkdwn_notifications_before_write(self) -> None:
        path = Path(self.temp.name) / "blocks.json"
        args = argparse.Namespace(
            text="fallback", text_file=None, blocks_file=str(path), channel="C123456",
            url="https://example.slack.com/archives/C123456/p1700000000000200",
            ts=None, thread_ts=None, format_name="markdown", mention_mode="literal",
            dry_run=False, confirm_preview=None, allow_broadcast=False,
            allow_usergroup_mention=False, unfurl_links=False, output=None,
        )
        channel = {"id": "C123456", "name": "release", "is_member": True}
        with mock.patch("sk.cmd_send.select_write_target_with_thread", return_value=(self.context, channel, "yes", None)), \
             mock.patch("sk.cmd_edit.select_message_author", return_value=(self.context, {})), \
             mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), \
             mock.patch.object(ActorContext, "write_client", side_effect=AssertionError("write called")):
            for token, expected in (("<!channel>", "--allow-broadcast"), ("<!subteam^S1>", "--allow-usergroup-mention")):
                path.write_text(json.dumps([{"type": "context", "elements": [
                    {"type": "mrkdwn", "text": token, "verbatim": True}
                ]}]), encoding="utf-8")
                for run in (run_send, run_edit):
                    with self.subTest(command=run.__module__, token=token), self.assertRaisesRegex(InvalidArgument, expected):
                        run(args)

    def test_send_success_survives_permalink_transport_error(self) -> None:
        args = argparse.Namespace(
            channel="C123456", text="hello", text_file=None, thread_ts=None,
            format_name="markdown", mention_mode="literal", dry_run=False,
            confirm_preview=None, allow_broadcast=False,
            allow_usergroup_mention=False, unfurl_links=False, output=None,
        )
        channel = {"id": "C123456", "name": "release", "is_member": True}
        write = mock.Mock()
        write.call.return_value = {
            "ok": True,
            "channel": "C123456",
            "ts": "1700000000.000200",
            "message": {
                "ts": "1700000000.000200", "user": "U-BOT", "bot_id": "B1",
                "text": "hello",
            },
        }
        read = mock.Mock()
        read.call.side_effect = URLError("lost")
        with mock.patch(
            "sk.cmd_send.select_write_target_with_thread",
            return_value=(self.context, channel, "yes", None),
        ), mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), mock.patch.object(
            ActorContext, "write_client", return_value=write
        ), mock.patch.object(
            ActorContext, "read_client", return_value=read
        ), mock.patch("sk.cmd_send.emit") as emitted:
            self.assertEqual(run_send(args), 0)

        payload = emitted.call_args.args[0]
        self.assertEqual(payload["status"], "sent")
        self.assertIsNone(payload["permalink"])
        self.assertTrue(any("URLError" in item for item in payload["warnings"]))
        write.call.assert_called_once()

    def test_bot_edit_can_replace_message_blocks(self) -> None:
        blocks_path = Path(self.temp.name) / "blocks.json"
        blocks = [
            {
                "type": "context",
                "elements": [{"type": "plain_text", "text": "Updated by automation"}],
            }
        ]
        blocks_path.write_text(json.dumps(blocks), encoding="utf-8")
        write = mock.Mock()
        write.call.return_value = {"ok": True, "message": {"text": "fallback"}}
        args = argparse.Namespace(
            url="https://example.slack.com/archives/C123456/p1700000000000200",
            channel=None, ts=None, thread_ts=None, text="fallback", text_file=None,
            blocks_file=str(blocks_path), mention_mode="literal",
            allow_broadcast=False, allow_usergroup_mention=False, output=None,
        )
        original = {"bot_id": "B1", "user": "U-BOT", "text": "old"}
        with mock.patch(
            "sk.cmd_edit.select_message_author",
            return_value=(self.context, original),
        ), mock.patch.object(
            ActorContext, "write_client", return_value=write
        ), mock.patch("sk.cmd_edit.emit"):
            run_edit(args)

        write.call.assert_called_once_with(
            "chat.update", channel="C123456", ts="1700000000.000200",
            text="fallback", parse="none", link_names=False,
            blocks=[
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "plain_text",
                            "text": "Updated by automation",
                        }
                    ],
                }
            ],
            as_user=True,
        )

    def test_send_success_survives_permalink_interrupt(self) -> None:
        args = argparse.Namespace(
            channel="C123456", text="hello", text_file=None, thread_ts=None,
            format_name="markdown", mention_mode="literal", dry_run=False,
            confirm_preview=None, allow_broadcast=False,
            allow_usergroup_mention=False, unfurl_links=False, output=None,
        )
        channel = {"id": "C123456", "name": "release", "is_member": True}
        write = mock.Mock()
        write.call.return_value = {
            "ok": True,
            "channel": "C123456",
            "ts": "1700000000.000200",
            "message": {"ts": "1700000000.000200", "text": "hello"},
        }
        read = mock.Mock()
        read.call.side_effect = KeyboardInterrupt
        with mock.patch(
            "sk.cmd_send.select_write_target_with_thread",
            return_value=(self.context, channel, "yes", None),
        ), mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), mock.patch.object(
            ActorContext, "write_client", return_value=write
        ), mock.patch.object(
            ActorContext, "read_client", return_value=read
        ), mock.patch("sk.cmd_send.emit") as emitted:
            self.assertEqual(run_send(args), 0)

        payload = emitted.call_args.args[0]
        self.assertEqual(payload["status"], "sent")
        self.assertIsNone(payload["permalink"])
        self.assertTrue(any("permalink 查询被中断" in item for item in payload["warnings"]))
        write.call.assert_called_once()

    def test_send_success_survives_response_normalisation_interrupt(self) -> None:
        args = argparse.Namespace(
            channel="C123456", text="hello", text_file=None, thread_ts=None,
            format_name="markdown", mention_mode="literal", dry_run=False,
            confirm_preview=None, allow_broadcast=False,
            allow_usergroup_mention=False, unfurl_links=False, output=None,
        )
        channel = {"id": "C123456", "name": "release", "is_member": True}
        write = mock.Mock()
        write.call.return_value = {
            "ok": True,
            "channel": "C123456",
            "ts": "1700000000.000200",
            "message": {"ts": "1700000000.000200", "text": "hello"},
        }
        read = mock.Mock()
        read.call.return_value = {"ok": True, "permalink": "https://example.test/p1"}
        with mock.patch(
            "sk.cmd_send.select_write_target_with_thread",
            return_value=(self.context, channel, "yes", None),
        ), mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), mock.patch.object(
            ActorContext, "write_client", return_value=write
        ), mock.patch.object(
            ActorContext, "read_client", return_value=read
        ), mock.patch(
            "sk.cmd_send.normalise_message", side_effect=KeyboardInterrupt
        ), mock.patch("sk.cmd_send.emit") as emitted:
            self.assertEqual(run_send(args), 0)

        payload = emitted.call_args.args[0]
        self.assertEqual(payload["status"], "sent")
        self.assertEqual(payload["permalink"], "https://example.test/p1")
        self.assertTrue(any("响应归一化被中断" in item for item in payload["warnings"]))
        write.call.assert_called_once()

    def test_thread_response_missing_root_is_sent_with_critical_warning(self) -> None:
        args = argparse.Namespace(
            channel="C123456", text="reply", text_file=None,
            thread_ts="1700000000.000100", format_name="markdown",
            mention_mode="literal", dry_run=False, confirm_preview=None,
            allow_broadcast=False, allow_usergroup_mention=False,
            unfurl_links=False, output=None,
        )
        channel = {"id": "C123456", "name": "release", "is_member": True}
        write = mock.Mock()
        write.call.return_value = {
            "ok": True,
            "channel": "C123456",
            "ts": "1700000000.000200",
            "message": {"ts": "1700000000.000200", "text": "reply"},
        }
        read = mock.Mock()
        read.call.return_value = {"ok": True, "permalink": "https://example.test/p1"}
        with mock.patch(
            "sk.cmd_send.select_write_target_with_thread",
            return_value=(self.context, channel, "yes", None),
        ), mock.patch("sk.cmd_send.cache.ensure_fresh", return_value={}), mock.patch.object(
            ActorContext, "write_client", return_value=write
        ), mock.patch.object(
            ActorContext, "read_client", return_value=read
        ), mock.patch("sk.cmd_send.emit") as emitted:
            self.assertEqual(run_send(args), 0)

        warnings = emitted.call_args.args[0]["warnings"]
        self.assertTrue(any("CRITICAL" in item for item in warnings))

    def test_deterministic_write_failure_emits_actor_and_scope_details(self) -> None:
        def fail(_args):
            activate(self.context)
            raise SlackAPIError(
                "chat.postMessage",
                "missing_scope",
                detail='{"needed":"chat:write","provided":"channels:history"}',
            )

        with mock.patch("sk.cli.cmd_send.run", side_effect=fail), mock.patch(
            "sk.cli.emit"
        ) as emitted:
            exit_code = cli_main(
                [
                    "send", "--channel", "C123456", "--text", "hello",
                    "--format", "markdown", "--mention-mode", "literal",
                ]
            )

        self.assertEqual(exit_code, 1)
        payload = emitted.call_args.args[0]
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["actor"]["selected"], "bot")
        self.assertEqual(payload["needed"], "chat:write")
        self.assertEqual(payload["provided"], "channels:history")

    def test_upload_unknown_preserves_completed_file_ids_and_phase(self) -> None:
        file_path = Path(self.temp.name) / "report.txt"
        file_path.write_text("hello", encoding="utf-8")
        args = argparse.Namespace(
            channel="C123456", files=[str(file_path)], filename=None,
            title=None, message=None, thread_ts=None, output=None,
            allow_broadcast=False, allow_usergroup_mention=False,
        )
        write = mock.Mock()
        write.call.side_effect = [
            {"ok": True, "upload_url": "https://upload.test", "file_id": "F1"},
            WriteResultUnknown({"status": "unknown", "reason": "timeout"}),
        ]
        with mock.patch(
            "sk.cmd_files_upload.select_write_target_with_thread",
            return_value=(
                self.context, {"id": "C123456", "name": "release"}, "yes", None
            ),
        ), mock.patch.object(ActorContext, "write_client", return_value=write):
            with self.assertRaises(WriteResultUnknown) as caught:
                run_files_upload(args)

        self.assertEqual(caught.exception.payload["delivery_phase"], "complete_upload")
        self.assertEqual(caught.exception.payload["byte_uploaded_file_ids"], ["F1"])

    def test_upload_comment_rejects_broadcast_without_explicit_allow(self) -> None:
        file_path = Path(self.temp.name) / "report.txt"
        file_path.write_text("hello", encoding="utf-8")
        args = argparse.Namespace(
            channel="C123456", files=[str(file_path)], filename=None,
            title=None, message="deploy <!channel>", thread_ts=None, output=None,
            allow_broadcast=False, allow_usergroup_mention=False,
        )
        write = mock.Mock()
        with mock.patch(
            "sk.cmd_files_upload.select_write_target_with_thread",
            return_value=(
                self.context, {"id": "C123456", "name": "release"}, "yes", None
            ),
        ), mock.patch.object(ActorContext, "write_client", return_value=write):
            with self.assertRaisesRegex(InvalidArgument, "--allow-broadcast"):
                run_files_upload(args)
        write.call.assert_not_called()

    def test_upload_comment_rejects_usergroup_without_explicit_allow(self) -> None:
        file_path = Path(self.temp.name) / "report.txt"
        file_path.write_text("hello", encoding="utf-8")
        args = argparse.Namespace(
            channel="C123456", files=[str(file_path)], filename=None,
            title=None, message="review <!subteam^S123>", thread_ts=None, output=None,
            allow_broadcast=False, allow_usergroup_mention=False,
        )
        write = mock.Mock()
        with mock.patch(
            "sk.cmd_files_upload.select_write_target_with_thread",
            return_value=(
                self.context, {"id": "C123456", "name": "release"}, "yes", None
            ),
        ), mock.patch.object(ActorContext, "write_client", return_value=write):
            with self.assertRaisesRegex(InvalidArgument, "--allow-usergroup-mention"):
                run_files_upload(args)
        write.call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
