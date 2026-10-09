"""只管理 session-login 自己创建的资源，不扫描或接管外部进程。"""

from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

import fcntl


class ResourceBusy(RuntimeError):
    """同一 session 正在被另一个 bridge 使用。"""


def _identity(pid: int) -> Optional[Dict[str, Any]]:
    try:
        output = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "pid=,pgid=,uid=,lstart="],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    parts = output.split()
    if len(parts) < 8:
        return None
    try:
        return {
            "pid": int(parts[0]),
            "pgid": int(parts[1]),
            "uid": parts[2],
            "startedAt": " ".join(parts[3:8]),
        }
    except ValueError:
        return None


def _matches(record: Dict[str, Any]) -> bool:
    current = _identity(int(record.get("pid", -1)))
    return bool(
        current
        and current["pid"] == record.get("pid")
        and current["pgid"] == record.get("pgid")
        and current["uid"] == record.get("uid")
        and current["startedAt"] == record.get("startedAt")
    )


def _stop_process(record: Dict[str, Any]) -> bool:
    if not _matches(record):
        return _identity(int(record.get("pid", -1))) is None
    pid = int(record["pid"])
    pgid = int(record["pgid"])
    try:
        if pgid == pid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if _identity(pid) is None:
            return True
        time.sleep(0.1)
    if _matches(record):
        try:
            os.killpg(pgid, signal.SIGKILL) if pgid == pid else os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
    return _identity(pid) is None


class ResourceReceipt:
    """短期、无秘密的资源所有权收据，供任务结束时精确清理。"""

    def __init__(self, root: Path, namespace: str, session: str):
        self.root = root
        self.namespace = namespace
        self.session = session
        self.path = root / "resources.json"
        self.lock_path = root / "resources.lock"
        self._lock_file = None
        self.data: Dict[str, Any] = {
            "namespace": namespace,
            "session": session,
            "dev": None,
            "whistle": None,
            "browser": None,
        }

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            self._lock_file.close()
            self._lock_file = None
            raise ResourceBusy("该 session 正在被其它运行占用") from exc
        if self.path.exists():
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                self.release()
                raise ResourceBusy("资源收据损坏，拒绝接管") from exc
            if existing.get("namespace") != self.namespace or existing.get("session") != self.session:
                self.release()
                raise ResourceBusy("资源收据与当前 session 不匹配")
            self.data.update(existing)

    def mark_process(self, name: str, pid: int) -> None:
        identity = _identity(pid)
        if identity is None:
            raise ResourceBusy(f"无法确认新建进程身份：{name}")
        self.data[name] = identity
        self.save()

    def mark_browser(self, mode: str) -> None:
        self.data["browser"] = {"namespace": self.namespace, "session": self.session, "mode": mode, "owned": True}
        self.save()

    def save(self) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(self.path)

    def release(self) -> None:
        if self._lock_file is not None:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    def cleanup(self) -> Dict[str, str]:
        results: Dict[str, str] = {}
        browser = self.data.get("browser") or {}
        if browser.get("owned"):
            try:
                restore_path = self._restore_path()
                restore_known = True
            except ResourceBusy:
                restore_path = None
                restore_known = False
            try:
                close_data = self._close_browser()
                results["browser"] = "closed"
            except ResourceBusy:
                results["browser"] = "failed"
            else:
                results["browserRestore"] = self._purge_browser_restore(close_data, restore_path, restore_known)
                if results["browserRestore"] == "purged":
                    # 其它资源可能尚未停止；重试时不再操作已完成清理的浏览器。
                    self.data["browser"] = None
                    self.save()
        for name in ("whistle", "dev"):
            record = self.data.get(name)
            if record:
                results[name] = "closed" if _stop_process(record) else "preserved-identity-mismatch"
        if results.get("whistle") == "closed":
            for name in ("whistle.pid", "storage", "directory"):
                target = self.root / name
                try:
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
                    elif target.is_file() or target.is_symlink():
                        target.unlink()
                except OSError:
                    results["whistleArtifacts"] = "failed"
        if results.get("dev") == "closed":
            try:
                (self.root / "dev.pid").unlink(missing_ok=True)
            except OSError:
                results["devArtifacts"] = "failed"
        if all(value in {"closed", "already-stopped", "purged"} for value in results.values()):
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
        return results

    def _close_browser(self) -> Dict[str, Any]:
        """只关闭收据对应的 session，并确认结构化关闭结果。"""
        try:
            result = subprocess.run(
                ["agent-browser", "--namespace", self.namespace, "--session", self.session, "close", "--json"],
                capture_output=True, text=True, timeout=30, check=False,
            )
            payload = json.loads(result.stdout)
            if result.returncode != 0 or payload["success"] is not True or payload["data"]["closed"] is not True:
                raise ValueError("关闭未确认成功")
            return payload["data"]
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
            raise ResourceBusy("无法确认浏览器已关闭，保留资源收据") from exc

    def _purge_browser_restore(self, close_data: Dict[str, Any], before_path: Optional[Path], before_known: bool) -> str:
        try:
            browser = self.data["browser"]
            saved_paths = browser.get("restorePaths", [])
            if not isinstance(saved_paths, list) or any(not isinstance(path, str) or not path for path in saved_paths):
                return "failed"
            paths = set(saved_paths)
            if before_path is not None:
                paths.add(str(before_path))
            # close 可能首次保存恢复态，不能只根据关闭前的空路径宣称清理完成。
            status = close_data.get("saveStatus")
            path = close_data.get("statePath")
            if "saveError" in close_data:
                return "failed"
            if status == "saved":
                if not isinstance(path, str) or not path:
                    return "failed"
                paths.add(path)
            elif status not in {"not_configured", "disabled", "no_browser", "skipped_restore_failed"} or path is not None:
                return "failed"
            # 删除失败后 daemon 可能已退出；先保留路径，下一次清理仍能找到文件。
            browser["restorePaths"] = sorted(paths)
            self.save()
            purged = [self._purge_restore(Path(path)) for path in paths]
            return "purged" if before_known and all(result == "purged" for result in purged) else "failed"
        except (OSError, ValueError, TypeError):
            return "failed"

    def _restore_path(self) -> Optional[Path]:
        """读取 agent-browser 报告的恢复文件，仅作为待清理候选。"""
        try:
            result = subprocess.run(
                ["agent-browser", "--namespace", self.namespace, "--session", self.session, "session", "info", "--json"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if result.returncode != 0:
                raise ValueError("查询失败")
            payload = json.loads(result.stdout)
            if payload.get("success") is False:
                raise ValueError("查询失败")
            data = payload["data"]
            runtime = data["runtime"]
            if runtime is None and data.get("active") is False and data.get("runtimeError") is None:
                # daemon 已退出时不会返回 runtime；桥接的 --restore 使用此默认文件。
                return Path.home() / ".agent-browser" / "namespaces" / self.namespace / "state" / "sessions" / f"{self.session}-{self.session}.json"
            path = runtime["restoreSavedPath"]
            if path is None or path == "":
                return None
            if not isinstance(path, str):
                raise ValueError("恢复路径类型无效")
            return Path(path)
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ResourceBusy("无法确认浏览器恢复文件，保留资源收据") from exc

    def _purge_restore(self, path: Optional[Path]) -> str:
        if path is None:
            return "purged"
        namespace_root = Path.home() / ".agent-browser" / "namespaces" / self.namespace
        try:
            resolved_root = namespace_root.resolve()
            resolved = path.resolve()
            if resolved.parent != resolved_root / "state" / "sessions" or resolved.name != f"{self.session}-{self.session}.json":
                return "failed"
            path.unlink(missing_ok=True)
            return "purged"
        except OSError:
            return "failed"
