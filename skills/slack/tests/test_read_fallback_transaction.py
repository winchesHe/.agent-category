from __future__ import annotations

import argparse
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sk import actor, cache, cli  # noqa: E402
from sk import cmd_cache_refresh, cmd_channels, cmd_files_download  # noqa: E402
from sk import cmd_get, cmd_history, cmd_replies, cmd_resolve, cmd_users  # noqa: E402
from sk.errors import InvalidArgument, SlackAPIError  # noqa: E402


class _Config:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.timeout = 1
        self.read_actor = "auto"

    def token_for(self, _scope: str) -> str:
        return "token"


class ReadFallbackTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        actor.set_requested(None)

    def tearDown(self) -> None:
        actor.set_requested(None)

    def test_first_primary_missing_scope_falls_back_from_user_to_bot(self) -> None:
        func = mock.Mock(side_effect=[SlackAPIError("users.info", "missing_scope"), 0])
        args = argparse.Namespace(actor=None, func=func)
        user = SimpleNamespace(selected="user")

        with mock.patch("sk.cli.current", return_value=user), mock.patch(
            "sk.cli.select_read"
        ) as select_read:
            result = cli._run_read_command(args, SimpleNamespace(read_actor="auto"))

        self.assertEqual(result, 0)
        self.assertEqual(func.call_count, 2)
        select_read.assert_called_once_with(
            mock.ANY, force="bot", fallback_reason="missing_scope"
        )

    def test_successful_primary_page_prevents_whole_command_fallback(self) -> None:
        def fail_after_primary(_args):
            actor.mark_primary_observed()
            raise SlackAPIError("conversations.history", "not_in_channel")

        args = argparse.Namespace(actor=None, func=fail_after_primary)
        user = SimpleNamespace(selected="user")
        with mock.patch("sk.cli.current", return_value=user), mock.patch(
            "sk.cli.select_read"
        ) as select_read:
            with self.assertRaises(SlackAPIError):
                cli._run_read_command(args, SimpleNamespace(read_actor="auto"))

        select_read.assert_not_called()

    def test_helper_response_does_not_close_fallback(self) -> None:
        calls = 0

        def command(_args):
            nonlocal calls
            calls += 1
            if calls == 1:
                # Helper 成功但没有调用 mark_primary_observed。
                raise SlackAPIError("conversations.history", "channel_not_found")
            return 0

        args = argparse.Namespace(actor=None, func=command)
        user = SimpleNamespace(selected="user")
        with mock.patch("sk.cli.current", return_value=user), mock.patch(
            "sk.cli.select_read"
        ) as select_read:
            self.assertEqual(
                cli._run_read_command(args, SimpleNamespace(read_actor="auto")), 0
            )

        select_read.assert_called_once()

    def test_get_marks_even_an_empty_primary_response(self) -> None:
        client = mock.Mock()
        client.call.return_value = {"messages": []}
        with actor.read_attempt() as attempt:
            self.assertIsNone(
                cmd_get._fetch_single(
                    client, channel_id="C1", ts="1.000001", thread_ts=""
                )
            )
            self.assertTrue(attempt.primary_observed)

    def test_replies_second_page_failure_keeps_primary_observed(self) -> None:
        client = mock.Mock()
        client.call.side_effect = [
            {
                "messages": [{"ts": "1.000001"}],
                "response_metadata": {"next_cursor": "next"},
            },
            SlackAPIError("conversations.replies", "missing_scope"),
        ]
        with actor.read_attempt() as attempt:
            with self.assertRaises(SlackAPIError):
                cmd_replies._fetch_thread(
                    client, channel_id="C1", thread_ts="1.000001", limit=None
                )
            self.assertTrue(attempt.primary_observed)

    def test_history_resolution_helper_does_not_mark_primary(self) -> None:
        from sk.channels import resolve_channel

        client = mock.Mock()
        client.call.return_value = {"channel": {"id": "C1", "name": "eng"}}
        with tempfile.TemporaryDirectory() as temp, actor.read_attempt() as attempt:
            channel = resolve_channel(
                client, "C1", cfg=_Config(Path(temp))
            )
            self.assertEqual(channel["id"], "C1")
            self.assertFalse(attempt.primary_observed)

    def test_history_second_page_failure_does_not_allow_actor_switch(self) -> None:
        client = mock.Mock()
        client.call.side_effect = [
            {
                "messages": [{"ts": "2.000001"}],
                "response_metadata": {"next_cursor": "next"},
            },
            SlackAPIError("conversations.history", "not_in_channel"),
        ]
        with actor.read_attempt() as attempt:
            with self.assertRaises(InvalidArgument) as raised:
                cmd_history._fetch_history(
                    client, channel_id="C1", count=None, oldest_ts=None
                )
            self.assertTrue(attempt.primary_observed)
        self.assertIn("selected actor", str(raised.exception))
        self.assertNotIn("bot is not", str(raised.exception))

    def test_channels_declares_empty_cache_refresh_as_primary(self) -> None:
        args = argparse.Namespace(
            limit=10,
            query=None,
            ch_type="any",
            sort="name",
            include_archived=False,
            output=None,
        )
        with tempfile.TemporaryDirectory() as temp:
            cfg = _Config(Path(temp))
            with mock.patch("sk.cmd_channels.Config", return_value=cfg), mock.patch(
                "sk.cmd_channels.cache.ensure_fresh", return_value={}
            ) as ensure_fresh, mock.patch("sk.cmd_channels.emit"):
                cmd_channels.run(args)
        ensure_fresh.assert_called_once_with(
            cfg, ["channels"], primary_if_empty=True
        )

    def test_empty_cache_refresh_propagates_first_access_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cfg = _Config(Path(temp))
            failure = SlackAPIError("conversations.list", "missing_scope")
            with mock.patch(
                "sk.cmd_cache_refresh._fetch_channels", side_effect=failure
            ):
                with self.assertRaises(SlackAPIError):
                    cache.ensure_fresh(
                        cfg,
                        ["channels"],
                        client=mock.Mock(),
                        primary_if_empty=True,
                    )

    def test_stale_nonempty_cache_refresh_remains_auxiliary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cfg = _Config(Path(temp))
            cache.save_channels(cfg.cache_dir, {"C1": {"id": "C1"}})
            failure = SlackAPIError("conversations.list", "missing_scope")
            with mock.patch("sk.cache.is_stale", return_value=True), mock.patch(
                "sk.cmd_cache_refresh._fetch_channels", side_effect=failure
            ), actor.read_attempt() as attempt:
                report = cache.ensure_fresh(
                    cfg,
                    ["channels"],
                    client=mock.Mock(),
                    primary_if_empty=True,
                )
                self.assertFalse(attempt.primary_observed)
        self.assertIn("refresh_failed", str(report["channels"]["reason"]))

    def test_users_live_lookup_marks_primary(self) -> None:
        args = argparse.Namespace(
            uid="U1",
            email=None,
            query=None,
            limit=20,
            include_deleted=False,
            include_bots=False,
            output=None,
        )
        client = mock.Mock()
        client.call.return_value = {"user": {"id": "U1"}}
        with tempfile.TemporaryDirectory() as temp:
            cfg = _Config(Path(temp))
            with mock.patch("sk.cmd_users.Config", return_value=cfg), mock.patch(
                "sk.cmd_users.SlackClient", return_value=client
            ), mock.patch("sk.cmd_users.emit"), actor.read_attempt() as attempt:
                cmd_users.run(args)
                self.assertTrue(attempt.primary_observed)

    def test_resolve_live_lookup_marks_primary(self) -> None:
        client = mock.Mock()
        client.call.return_value = {"user": {"id": "U1"}}
        with tempfile.TemporaryDirectory() as temp:
            cfg = _Config(Path(temp))
            with mock.patch("sk.cmd_resolve.SlackClient", return_value=client), \
                    actor.read_attempt() as attempt:
                kind, resolved, _candidates, _refresh = cmd_resolve._dispatch(cfg, "U1")
                self.assertEqual(kind, "user")
                self.assertEqual(resolved["id"], "U1")
                self.assertTrue(attempt.primary_observed)

    def test_file_metadata_marks_before_download_helper_failure(self) -> None:
        client = mock.Mock()
        client.call.return_value = {"file": {"id": "F1"}}
        with tempfile.TemporaryDirectory() as temp, mock.patch(
            "sk.cmd_files_download.download_file", side_effect=RuntimeError("download")
        ), actor.read_attempt() as attempt:
            with self.assertRaises(RuntimeError):
                cmd_files_download._run_by_file_id(
                    client,
                    file_id="F1",
                    token="token",
                    files_dir=Path(temp),
                    categories={"all"},
                    timeout=1,
                )
            self.assertTrue(attempt.primary_observed)

    def test_cache_refresh_marks_first_page_before_later_failure(self) -> None:
        client = mock.Mock()
        client.call.side_effect = [
            {
                "members": [{"id": "U1"}],
                "response_metadata": {"next_cursor": "next"},
            },
            SlackAPIError("users.list", "missing_scope"),
        ]
        with actor.read_attempt() as attempt:
            with self.assertRaises(SlackAPIError):
                cmd_cache_refresh._fetch_users(
                    client, on_page=actor.mark_primary_observed
                )
            self.assertTrue(attempt.primary_observed)

    def test_cache_refresh_subteams_first_access_error_reaches_cli_fallback(self) -> None:
        args = argparse.Namespace(
            skip_users=True,
            skip_channels=True,
            skip_subteams=False,
            output=None,
        )
        selected_user = SimpleNamespace(requested="auto", selected="user")
        with tempfile.TemporaryDirectory() as temp:
            cfg = _Config(Path(temp))
            cfg.ensure_dirs = mock.Mock()
            with mock.patch(
                "sk.cmd_cache_refresh.Config", return_value=cfg
            ), mock.patch("sk.cmd_cache_refresh.SlackClient"), mock.patch(
                "sk.cmd_cache_refresh.current", return_value=selected_user
            ), mock.patch(
                "sk.cmd_cache_refresh._fetch_subteams",
                side_effect=SlackAPIError("usergroups.list", "missing_scope"),
            ), actor.read_attempt():
                with self.assertRaises(SlackAPIError):
                    cmd_cache_refresh.run(args)

    def test_doctor_does_not_accept_actor_override(self) -> None:
        parser = cli.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["doctor", "--as", "bot"])


if __name__ == "__main__":
    unittest.main()
