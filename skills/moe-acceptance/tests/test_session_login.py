import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import pytest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "session_login.py"
SPEC = importlib.util.spec_from_file_location("session_login", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SessionLoginTests(unittest.TestCase):
    def test_stable_port_and_browser_isolation(self):
        self.assertEqual(MODULE._stable_port("moe-ns"), MODULE._stable_port("moe-ns"))
        args = MODULE._browser_args("moe-ns", "moe-session", 20199)
        self.assertIn("--proxy", args)
        self.assertIn("--namespace", args)
        self.assertIn("--session", args)
        self.assertEqual(args[-2:], ["--headed", "false"])
        self.assertEqual(MODULE._browser_args("moe-ns", "moe-session", 20199, headed=True)[-1], "--headed")

    def test_login_signal_and_identity_are_local(self):
        self.assertTrue(MODULE._needs_login("https://go.t2.moego.dev/sign_in", "", force_login=False))
        self.assertTrue(MODULE._needs_login("https://go.t2.moego.dev/home", "Sign in to continue", force_login=False))
        self.assertFalse(MODULE._needs_login("https://go.t2.moego.dev/home", "WH Winches He (Owner) moego\nDEV | Inv:V0", force_login=False))
        identity = MODULE._identity("WH Winches He (Owner) moego\nDEV | Inv:V0 | Pay:V1")
        self.assertEqual(identity["accountHint"], "WH Winches He (Owner) moego")
        self.assertIn("DEV", identity["devMarker"])

    def test_invalid_names_fail_closed(self):
        self.assertIsNotNone(MODULE.SAFE_NAME.fullmatch("valid-session_1"))
        self.assertIsNone(MODULE.SAFE_NAME.fullmatch("bad/session"))

    def test_event_logger_is_ordered_and_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            logger = MODULE.EventLogger("ns", session="sess", root=Path(temp))
            logger.emit("mis", "impersonate", "failed", details={"token": "secret", "attempts": 1})
            event = json.loads(logger.path.read_text(encoding="utf-8"))
            self.assertEqual(event["seq"], 1)
            self.assertEqual(event["sessionKey"][:7], "sha256:")
            self.assertEqual(event["details"]["token"], "[REDACTED]")
            self.assertEqual(event["details"]["attempts"], 1)

    def test_resource_receipt_keeps_mode_and_is_session_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = MODULE.ResourceReceipt(root, "ns", "sess")
            receipt.acquire()
            receipt.mark_browser("headless")
            receipt.release()
            restored = MODULE.ResourceReceipt(root, "ns", "sess")
            restored.acquire()
            self.assertEqual(restored.data["browser"]["mode"], "headless")
            restored.release()


if __name__ == "__main__":
    unittest.main()


@pytest.mark.parametrize("flag", ["--namespace", "--session"])
def test_invalid_mis_name_is_rejected_before_resources(tmp_path, flag):
    argv = ["--worktree", str(tmp_path), "--frontend-port", "3000", "--account-ref", "fake",
            "--namespace", "ns", "--session", "sess"]
    argv[argv.index(flag) + 1] = "probe.session"
    with patch.object(MODULE, "_session_root") as root:
        with pytest.raises(MODULE.BridgeError):
            MODULE.login(MODULE.build_parser().parse_args(argv))
        root.assert_not_called()
    assert MODULE.SAFE_NAME.fullmatch("_valid-name_1")
    assert MODULE.SAFE_NAME.fullmatch("a" * 64)
    assert not MODULE.SAFE_NAME.fullmatch("a" * 65)


@pytest.mark.parametrize("ok, code", [(True, 0), (False, 4)])
def test_cleanup_exit_code_matches_json(ok, code, capsys):
    with patch.object(MODULE, "cleanup", return_value={"ok": ok}):
        assert MODULE.main(["--namespace", "ns", "--session", "sess", "--cleanup"]) == code
    assert json.loads(capsys.readouterr().out)["ok"] is ok


@pytest.mark.parametrize("was_active, created", [(False, True), (False, False), (True, True)])
def test_failed_navigation_tracks_only_newly_created_browser(tmp_path, was_active, created):
    args = MODULE.build_parser().parse_args([
        "--worktree", str(tmp_path), "--frontend-port", "3000", "--account-ref", "fake",
        "--namespace", "ns", "--session", "sess",
    ])
    with patch.object(MODULE, "_session_root", return_value=tmp_path), \
         patch.object(MODULE, "_start_dev", return_value="reused"), \
         patch.object(MODULE, "_start_whistle", return_value="reused"), \
         patch.object(MODULE, "_require_binary", return_value="fake"), \
         patch.object(MODULE, "_browser_active", side_effect=[was_active, created]), \
         patch.object(MODULE, "_page_state", return_value={"url": "", "title": "", "body": ""}), \
         patch.object(MODULE, "_browser", side_effect=MODULE.BridgeError("导航失败")):
        with pytest.raises(MODULE.BridgeError, match="导航失败"):
            MODULE.login(args)
    receipt = tmp_path / "resources.json"
    if created and not was_active:
        assert json.loads(receipt.read_text())["browser"]["owned"] is True
    else:
        assert not receipt.exists()


@pytest.mark.parametrize("output", ['{}', '{"data":{"active":"false"}}', 'invalid'])
def test_unknown_browser_status_cannot_be_treated_as_absent(output):
    with patch.object(MODULE, "_browser", return_value=output):
        with pytest.raises(MODULE.BridgeError):
            MODULE._browser_active("ns", "sess", 20000)


@pytest.mark.parametrize("response", [
    subprocess.CompletedProcess([], 1, '{"data":{"runtime":{"restoreSavedPath":null}}}'),
    subprocess.CompletedProcess([], 0, 'invalid'),
    subprocess.CompletedProcess([], 0, '{}'),
    subprocess.CompletedProcess([], 0, '{"success":false,"data":{"runtime":{"restoreSavedPath":null}}}'),
    subprocess.CompletedProcess([], 0, '{"success":true,"data":{"active":true,"runtime":null}}'),
    subprocess.CompletedProcess([], 0, '{"success":true,"data":{"active":"false","runtime":null}}'),
    subprocess.CompletedProcess([], 0, '{"success":true,"data":{"active":false,"runtime":null,"runtimeError":"timeout"}}'),
    subprocess.TimeoutExpired("fake", 10),
])
def test_restore_lookup_failure_preserves_receipt(tmp_path, response):
    receipt = MODULE.ResourceReceipt(tmp_path, "ns", "sess")
    receipt.acquire()
    try:
        receipt.mark_browser("headless")
        with patch("lifecycle.subprocess.run", side_effect=[response, _close_response()]):
            result = receipt.cleanup()
        assert result == {"browser": "closed", "browserRestore": "failed"}
        assert receipt.path.exists()
    finally:
        receipt.release()


def _close_response(**data):
    return subprocess.CompletedProcess([], 0, json.dumps({
        "success": True,
        "data": {"closed": True, "saveStatus": "not_configured", **data},
    }))


@pytest.fixture
def owned_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    receipt = MODULE.ResourceReceipt(tmp_path, "ns", "sess")
    receipt.acquire()
    try:
        receipt.mark_browser("headless")
        yield receipt
    finally:
        receipt.release()


def _restore_file(tmp_path, session="sess"):
    path = tmp_path / ".agent-browser" / "namespaces" / "ns" / "state" / "sessions" / f"{session}-{session}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
    return path


def _info_response(path=None):
    return subprocess.CompletedProcess([], 0, json.dumps({
        "success": True,
        "data": {"runtime": {"restoreSavedPath": str(path) if path else None}},
    }))


def test_cleanup_preserves_other_session_in_same_namespace(owned_receipt):
    active_sessions = {("ns", "sess"), ("ns", "other"), ("other", "sess")}

    def run(command, **kwargs):
        if "close" not in command:
            return _info_response()
        namespace = command[command.index("--namespace") + 1]
        if "--all" in command:
            active_sessions.difference_update({key for key in active_sessions if key[0] == namespace})
        else:
            active_sessions.remove((namespace, command[command.index("--session") + 1]))
        return _close_response()

    with patch("lifecycle.subprocess.run", side_effect=run):
        assert owned_receipt.cleanup() == {"browser": "closed", "browserRestore": "purged"}
    assert active_sessions == {("ns", "other"), ("other", "sess")}
    assert not owned_receipt.path.exists()


def test_cleanup_removes_restore_first_saved_during_close(owned_receipt, tmp_path):
    saved = []

    def run(command, **kwargs):
        if "close" not in command:
            return _info_response()
        saved.append(_restore_file(tmp_path))
        return _close_response(saveStatus="saved", statePath=str(saved[0]))

    with patch("lifecycle.subprocess.run", side_effect=run):
        assert owned_receipt.cleanup() == {"browser": "closed", "browserRestore": "purged"}
    assert len(saved) == 1
    assert not saved[0].exists()
    assert not owned_receipt.path.exists()


@pytest.mark.parametrize("status", ["not_configured", "disabled", "no_browser", "skipped_restore_failed"])
@pytest.mark.parametrize("prior_file", [False, True])
def test_cleanup_handles_no_new_save_and_existing_restore(owned_receipt, tmp_path, status, prior_file):
    path = _restore_file(tmp_path) if prior_file else None
    with patch("lifecycle.subprocess.run", side_effect=[_info_response(path), _close_response(saveStatus=status)]):
        assert owned_receipt.cleanup() == {"browser": "closed", "browserRestore": "purged"}
    assert path is None or not path.exists()
    assert not owned_receipt.path.exists()


@pytest.mark.parametrize("response", [
    subprocess.CompletedProcess([], 1, '{"success":true,"data":{"closed":true}}'),
    subprocess.CompletedProcess([], 0, 'invalid'),
    subprocess.CompletedProcess([], 0, '{}'),
    subprocess.CompletedProcess([], 0, '{"success":false,"data":{"closed":true}}'),
    subprocess.CompletedProcess([], 0, '{"success":true,"data":{"closed":"true"}}'),
    subprocess.TimeoutExpired("fake", 30),
    OSError("无法运行浏览器命令"),
])
def test_close_failure_preserves_restore_and_receipt(owned_receipt, tmp_path, response):
    path = _restore_file(tmp_path)
    with patch("lifecycle.subprocess.run", side_effect=[_info_response(path), response]):
        assert owned_receipt.cleanup()["browser"] == "failed"
    assert path.exists()
    assert owned_receipt.path.exists()


@pytest.mark.parametrize("data", [
    {"saveStatus": None},
    {"saveStatus": "unknown"},
    {"saveStatus": "saved"},
    {"saveStatus": "saved", "statePath": ""},
    {"saveStatus": "saved", "statePath": 42},
    {"saveStatus": "error", "saveError": "保存失败"},
    {"saveStatus": "not_configured", "statePath": "/unexpected/path"},
])
def test_unknown_close_restore_result_preserves_receipt(owned_receipt, data):
    with patch("lifecycle.subprocess.run", side_effect=[_info_response(), _close_response(**data)]):
        assert owned_receipt.cleanup() == {"browser": "closed", "browserRestore": "failed"}
    assert owned_receipt.path.exists()


@pytest.mark.parametrize("source", ["before", "close"])
def test_cleanup_rejects_restore_owned_by_other_session(owned_receipt, tmp_path, source):
    other = _restore_file(tmp_path, "other")
    before = _info_response(other if source == "before" else None)
    close = _close_response(saveStatus="saved", statePath=str(other)) if source == "close" else _close_response()
    with patch("lifecycle.subprocess.run", side_effect=[before, close]):
        assert owned_receipt.cleanup() == {"browser": "closed", "browserRestore": "failed"}
    assert other.exists()
    assert owned_receipt.path.exists()


def test_delete_failure_remembers_close_path_for_retry(owned_receipt, tmp_path):
    path = _restore_file(tmp_path)
    unlink = Path.unlink

    def fail_restore_delete(target, *args, **kwargs):
        if target == path:
            raise PermissionError("模拟恢复文件无法删除")
        return unlink(target, *args, **kwargs)

    with patch("lifecycle.subprocess.run", side_effect=[
        _info_response(), _close_response(saveStatus="saved", statePath=str(path)),
    ]), patch.object(Path, "unlink", fail_restore_delete):
        assert owned_receipt.cleanup() == {"browser": "closed", "browserRestore": "failed"}
    assert path.exists()
    assert owned_receipt.path.exists()
    owned_receipt.release()

    retry = MODULE.ResourceReceipt(tmp_path, "ns", "sess")
    retry.acquire()
    try:
        with patch("lifecycle.subprocess.run", side_effect=[_info_response(), _close_response(saveStatus="no_browser")]):
            assert retry.cleanup() == {"browser": "closed", "browserRestore": "purged"}
        assert not path.exists()
        assert not retry.path.exists()
    finally:
        retry.release()


def test_cleanup_leaves_unowned_browser_untouched(owned_receipt):
    owned_receipt.data["browser"]["owned"] = False
    with patch("lifecycle.subprocess.run") as run:
        assert owned_receipt.cleanup() == {}
        run.assert_not_called()


@pytest.mark.parametrize("prior_file", [False, True])
def test_cleanup_with_inactive_daemon_and_null_runtime(owned_receipt, tmp_path, prior_file):
    path = _restore_file(tmp_path) if prior_file else None
    info = subprocess.CompletedProcess([], 0, json.dumps({"success": True, "data": {
        "active": False, "runtime": None, "runtimeError": None,
    }}))
    with patch("lifecycle.subprocess.run", side_effect=[info, _close_response()]):
        assert owned_receipt.cleanup() == {"browser": "closed", "browserRestore": "purged"}
    assert path is None or not path.exists()
    assert not owned_receipt.path.exists()


def test_partial_cleanup_does_not_repeat_completed_browser_work(owned_receipt, tmp_path):
    owned_receipt.data["dev"] = {"pid": 123}
    with patch("lifecycle.subprocess.run", side_effect=[_info_response(), _close_response()]), \
         patch("lifecycle._stop_process", return_value=False):
        assert owned_receipt.cleanup() == {
            "browser": "closed", "browserRestore": "purged", "dev": "preserved-identity-mismatch",
        }
    assert json.loads(owned_receipt.path.read_text())["browser"] is None
    owned_receipt.release()
    retry = MODULE.ResourceReceipt(tmp_path, "ns", "sess")
    retry.acquire()
    try:
        with patch("lifecycle.subprocess.run") as run, patch("lifecycle._stop_process", return_value=True):
            assert retry.cleanup() == {"dev": "closed"}
            run.assert_not_called()
        assert not retry.path.exists()
    finally:
        retry.release()


@pytest.mark.parametrize("prior_https", [None, "false", "true"])
def test_dev_start_uses_https_matching_whistle_without_changing_parent(tmp_path, monkeypatch, prior_https):
    if prior_https is None:
        monkeypatch.delenv("HTTPS", raising=False)
    else:
        monkeypatch.setenv("HTTPS", prior_https)
    monkeypatch.setenv("FAST_DEV", "1")
    with patch.object(MODULE, "_port_open", return_value=False), \
         patch.object(MODULE, "_require_binary", return_value="pnpm"), \
         patch.object(MODULE, "_wait_port"), \
         patch.object(MODULE.subprocess, "Popen") as start:
        start.return_value.pid = 123
        assert MODULE._start_dev(tmp_path, 3001, tmp_path, 45) == "started"
    child_env = start.call_args.kwargs["env"]
    assert child_env["HTTPS"] == "true"
    assert child_env["FAST_DEV"] == "1"
    assert child_env["PORT"] == "3001"
    assert MODULE.os.environ.get("HTTPS") == prior_https


def test_dev_reuse_does_not_restart_existing_service(tmp_path):
    with patch.object(MODULE, "_port_open", return_value=True), \
         patch.object(MODULE.subprocess, "Popen") as start:
        assert MODULE._start_dev(tmp_path, 3001, tmp_path, 45) == "reused"
    start.assert_not_called()
