#!/usr/bin/env python3
"""建立或恢复 T2 Web 的轻量 session 登录上下文。

该脚本只做确定性桥接：开发服务、隔离 Whistle、agent-browser session 和
MIS impersonate。账号、数据、case 以及验收判断仍由调用方负责。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from urllib.parse import urlparse

try:
    from observability import EventLogger
    from lifecycle import ResourceBusy, ResourceReceipt
except ModuleNotFoundError:  # 直接从 tests 或其它目录加载脚本时使用
    sys.path.insert(0, str(Path(__file__).parent))
    from observability import EventLogger
    from lifecycle import ResourceBusy, ResourceReceipt


class BridgeError(RuntimeError):
    """可向调用方报告的非敏感桥接错误。"""

    run_id: str = ""
    log_file: str = ""


SAFE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}")


def _run(command: Sequence[str], *, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
    )


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise BridgeError(f"缺少本地依赖：{name}")
    return path


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def _wait_port(host: str, port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return
        time.sleep(0.25)
    raise BridgeError(f"服务端口未就绪：{host}:{port}")


def _stable_port(namespace: str, *, offset: int = 0) -> int:
    digest = hashlib.sha256(namespace.encode("utf-8")).digest()
    return 20000 + int.from_bytes(digest[:2], "big") % 900 + offset


def _session_root(namespace: str) -> Path:
    root = Path("/tmp/moe-acceptance") / namespace
    root.mkdir(parents=True, exist_ok=True)
    return root


def _start_dev(worktree: Path, port: int, root: Path, timeout: float, receipt: Optional[ResourceReceipt] = None) -> str:
    if _port_open("127.0.0.1", port):
        return "reused"
    pnpm = _require_binary("pnpm")
    log = (root / "dev.log").open("a", encoding="utf-8")
    env = dict(os.environ)
    env["PORT"] = str(port)
    # Whistle 固定按 HTTPS 连接本地前端，启动协议必须与规则一致。
    env["HTTPS"] = "true"
    process = subprocess.Popen(
        [pnpm, "dev"],
        cwd=str(worktree),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    (root / "dev.pid").write_text(str(process.pid), encoding="utf-8")
    if receipt is not None:
        receipt.mark_process("dev", process.pid)
    _wait_port("127.0.0.1", port, timeout)
    return "started"


def _start_whistle(host: str, frontend_port: int, proxy_port: int, root: Path, timeout: float, receipt: Optional[ResourceReceipt] = None) -> str:
    if _port_open("127.0.0.1", proxy_port):
        return "reused"
    w2 = _require_binary("w2")
    storage = root / "storage"
    directory = root / "directory"
    storage.mkdir(parents=True, exist_ok=True)
    directory.mkdir(parents=True, exist_ok=True)
    rule = f"{host} 127.0.0.1:{frontend_port} enable://https disable://auto2http"
    log = (root / "whistle.log").open("a", encoding="utf-8")
    env = dict(os.environ)
    env["PFORK_MODE"] = "bind"
    process = subprocess.Popen(
        [
            w2,
            "run",
            "-S",
            str(storage),
            "-D",
            str(directory),
            "-H",
            "127.0.0.1",
            "-p",
            str(proxy_port),
            "-P",
            str(proxy_port + 1),
            "--no-prev-options",
            "-r",
            rule,
        ],
        cwd=str(directory),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    (root / "whistle.pid").write_text(str(process.pid), encoding="utf-8")
    if receipt is not None:
        receipt.mark_process("whistle", process.pid)
    _wait_port("127.0.0.1", proxy_port, timeout)
    return "started"


def _browser_args(namespace: str, session: str, proxy_port: int, *, headed: bool = False) -> list[str]:
    args = [
        "agent-browser",
        "--namespace",
        namespace,
        "--session",
        session,
        "--proxy",
        f"http://127.0.0.1:{proxy_port}",
        "--restore",
    ]
    args.extend(["--headed"] if headed else ["--headed", "false"])
    return args


def _browser(command: Sequence[str], *, required: bool = True) -> str:
    result = _run(command)
    if required and result.returncode != 0:
        raise BridgeError("浏览器控制动作失败")
    return result.stdout.strip()


def _browser_active(namespace: str, session: str, proxy_port: int, *, headed: bool = False) -> bool:
    output = _browser(_browser_args(namespace, session, proxy_port, headed=headed) + ["session", "info", "--json"])
    try:
        data = json.loads(output)
        active = data["data"]["active"]
        if data.get("success") is False or not isinstance(active, bool):
            raise ValueError("无有效 active 状态")
        return active
    except (KeyError, TypeError, ValueError) as exc:
        raise BridgeError("无法确认浏览器是否已存在，拒绝接管") from exc


def _page_state(namespace: str, session: str, proxy_port: int, *, headed: bool = False) -> Dict[str, str]:
    prefix = _browser_args(namespace, session, proxy_port, headed=headed)
    url = _browser(prefix + ["get", "url"], required=False)
    title = _browser(prefix + ["get", "title"], required=False)
    body = _browser(prefix + ["get", "text", "body"], required=False)
    return {"url": url, "title": title, "body": body}


def _wait_authenticated_page(namespace: str, session: str, proxy_port: int, host: str, *, headed: bool = False, timeout: float = 12.0) -> Dict[str, str]:
    """等待 MIS 注入后的异步跳转，避免在 sign_in 瞬间误判失败。"""
    deadline = time.monotonic() + timeout
    last = _page_state(namespace, session, proxy_port, headed=headed)
    while time.monotonic() < deadline:
        if (
            last["url"].startswith(f"https://{host}/")
            and "/sign_in" not in last["url"]
            and "/signin" not in last["url"]
        ):
            return last
        time.sleep(0.5)
        last = _page_state(namespace, session, proxy_port, headed=headed)
    return last


def _needs_login(url: str, body: str, *, force_login: bool) -> bool:
    if force_login:
        return True
    if "/sign_in" in url or "/signin" in url:
        return True
    return not body or bool(re.search(r"sign[ -]?in|登录", body, flags=re.IGNORECASE))


def _identity(body: str) -> Dict[str, str]:
    lines = [" ".join(line.split()) for line in body.splitlines() if line.strip()]
    marker = next((line for line in lines if "DEV" in line), "")
    owner = next((line for line in lines if re.search(r"\b(Owner|Admin)\b", line)), "")
    return {"devMarker": marker[:200], "accountHint": owner[:200]}


def _timed(logger: EventLogger, phase: str, action: str, callback, *, next_action: str = ""):
    started = time.monotonic()
    logger.emit(phase, action, "started", attempt=1, next_action=next_action or None)
    try:
        result = callback()
    except Exception as exc:
        logger.emit(
            phase,
            action,
            "failed",
            duration_ms=logger.elapsed(started),
            error_class=type(exc).__name__,
            retryable=False,
            next_action=next_action or None,
        )
        raise
    status = result if isinstance(result, str) and result in {"reused", "skipped", "succeeded", "started"} else "succeeded"
    logger.emit(phase, action, status, duration_ms=logger.elapsed(started), next_action=next_action or None)
    return result


def _mis_impersonate(account_ref: str, env_name: str, source: str, session: str, namespace: str) -> None:
    mis = Path(__file__).parents[2] / "moe-mis" / "scripts" / "moe_mis.py"
    if not mis.exists():
        raise BridgeError("找不到 moe-mis 脚本")
    result = _run(
        [
            "uv",
            "run",
            "--script",
            str(mis),
            "--env",
            env_name,
            "impersonate",
            "--account-ref",
            account_ref,
            "--source",
            source,
            "--max-age",
            "h1",
            "--browser-session",
            session,
            "--browser-namespace",
            namespace,
        ]
    )
    if result.returncode != 0:
        raise BridgeError("MIS impersonate 失败")


def login(args: argparse.Namespace) -> Dict[str, Any]:
    worktree = Path(args.worktree).expanduser().resolve()
    if not worktree.is_dir():
        raise BridgeError("worktree 不存在")
    host = args.host.lower().strip()
    parsed = urlparse(f"https://{host}")
    if parsed.hostname != host or "." not in host:
        raise BridgeError("host 必须是合法的真实 T2 hostname")
    for value, label in ((args.namespace, "namespace"), (args.session, "session")):
        if not SAFE_NAME.fullmatch(value):
            raise BridgeError(f"{label} 包含不支持的字符")

    root = _session_root(args.namespace)
    logger = EventLogger(args.namespace, session=args.session, root=root)
    logger.emit("run", "session-login", "started", details={"host": host, "env": args.env, "browserMode": "head" if args.head else "headless"})
    receipt = ResourceReceipt(root, args.namespace, args.session)
    try:
        receipt.acquire()
        requested_mode = "head" if args.head else "headless"
        existing_browser = receipt.data.get("browser") or {}
        if existing_browser.get("owned") and existing_browser.get("mode") not in (None, requested_mode):
            raise BridgeError("同一 session 不能切换 head/headless，请使用新的 session")
        proxy_port = args.proxy_port or _stable_port(args.namespace)
        dev_status = _timed(logger, "dev", "ensure", lambda: _start_dev(worktree, args.frontend_port, root, args.startup_timeout, receipt), next_action="whistle")
        whistle_status = _timed(logger, "whistle", "ensure", lambda: _start_whistle(host, args.frontend_port, proxy_port, root, args.startup_timeout, receipt), next_action="browser")
        _require_binary("agent-browser")

        prefix = _browser_args(args.namespace, args.session, proxy_port, headed=args.head)
        was_active = _browser_active(args.namespace, args.session, proxy_port, headed=args.head)
        try:
            state = _timed(logger, "browser", "snapshot", lambda: _page_state(args.namespace, args.session, proxy_port, headed=args.head), next_action="host_check")
            if not state["url"].startswith(f"https://{host}/"):
                _timed(logger, "browser", "open", lambda: _browser(prefix + ["open", f"https://{host}/home/overview"]), next_action="host_check")
                state = _timed(logger, "browser", "snapshot", lambda: _page_state(args.namespace, args.session, proxy_port, headed=args.head), next_action="host_check")
        finally:
            # 导航失败不代表浏览器未创建；只按动作前后的实际状态登记归属。
            if not was_active and not receipt.data.get("browser"):
                if _browser_active(args.namespace, args.session, proxy_port, headed=args.head):
                    receipt.mark_browser(requested_mode)
        if not state["url"].startswith(f"https://{host}/"):
            raise BridgeError("浏览器未停留在目标 T2 Host")
        logger.emit("host_check", "target", "succeeded", details={"host": host})

        invoked = _needs_login(state["url"], state["body"], force_login=args.force_login)
        if invoked:
            _timed(logger, "mis", "impersonate", lambda: _mis_impersonate(args.account_ref, args.env, args.source, args.session, args.namespace), next_action="auth_wait")
            state = _timed(logger, "auth_wait", "redirect", lambda: _wait_authenticated_page(args.namespace, args.session, proxy_port, host, headed=args.head), next_action="identity")
        else:
            logger.emit("mis", "impersonate", "skipped", details={"reason": "session-authenticated"}, next_action="identity")

        if not state["url"].startswith(f"https://{host}/") or "/sign_in" in state["url"] or "/signin" in state["url"]:
            raise BridgeError("MIS 后浏览器未回到目标 T2 Host")
        identity = _timed(logger, "identity", "read", lambda: _identity(state["body"]), next_action="result")
        logger.emit("run", "session-login", "succeeded", details={"misImpersonate": invoked})
        return {
            "ok": True,
            "runId": logger.run_id,
            "logFile": str(logger.path),
            "session": {"namespace": args.namespace, "name": args.session},
            "target": {"host": host, "url": state["url"], "title": state["title"][:200]},
            "identity": identity,
            "actions": {"misImpersonate": invoked, "dev": dev_status, "whistle": whistle_status},
        }
    except Exception as exc:
        logger.emit("run", "session-login", "failed", error_class=type(exc).__name__, next_action="inspect-log")
        if isinstance(exc, (BridgeError, ResourceBusy)):
            exc.run_id = logger.run_id
            exc.log_file = str(logger.path)
        raise
    finally:
        receipt.release()


def cleanup(args: argparse.Namespace) -> Dict[str, Any]:
    if not SAFE_NAME.fullmatch(args.namespace) or not SAFE_NAME.fullmatch(args.session):
        raise BridgeError("cleanup 的 namespace/session 格式无效")
    root = _session_root(args.namespace)
    logger = EventLogger(args.namespace, session=args.session, root=root)
    receipt = ResourceReceipt(root, args.namespace, args.session)
    logger.emit("run", "cleanup", "started", details={"browserMode": "head" if args.head else "headless"})
    try:
        receipt.acquire()
        result = receipt.cleanup()
        success_values = {"closed", "already-stopped", "purged"}
        status = "succeeded" if all(value in success_values for value in result.values()) else "failed"
        logger.emit("cleanup", "resources", status, details={"resources": result})
        logger.emit("run", "cleanup", status, details={"resources": result})
        return {"ok": status == "succeeded", "runId": logger.run_id, "logFile": str(logger.path), "cleanup": result}
    except Exception as exc:
        logger.emit("run", "cleanup", "failed", error_class=type(exc).__name__, next_action="inspect-log")
        if isinstance(exc, (BridgeError, ResourceBusy)):
            exc.run_id = logger.run_id
            exc.log_file = str(logger.path)
        raise
    finally:
        receipt.release()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="建立或恢复 MoeGo T2 Web session 登录上下文")
    parser.add_argument("--worktree")
    parser.add_argument("--frontend-port", type=int)
    parser.add_argument("--host", default="go.t2.moego.dev")
    parser.add_argument("--account-ref")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--proxy-port", type=int)
    parser.add_argument("--env", default="t2", choices=("t2", "s1", "production"))
    parser.add_argument("--source", default="business", choices=("business", "customer"))
    parser.add_argument("--startup-timeout", type=float, default=45.0, help="dev/Whistle 启动等待上限（秒）")
    parser.add_argument("--head", action="store_true", help="显示浏览器窗口；默认 headless")
    parser.add_argument("--cleanup", action="store_true", help="清理该 namespace/session 本次创建的资源")
    parser.add_argument("--force-login", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.cleanup:
            if not args.namespace or not args.session:
                raise BridgeError("--cleanup 需要 --namespace 和 --session")
            result = cleanup(args)
        else:
            missing = [name for name, value in (("worktree", args.worktree), ("frontend-port", args.frontend_port), ("account-ref", args.account_ref)) if not value]
            if missing:
                raise BridgeError("缺少参数：" + ", ".join(missing))
            result = login(args)
    except (BridgeError, ResourceBusy, subprocess.TimeoutExpired) as exc:
        payload: Dict[str, Any] = {"ok": False, "error": str(exc)}
        if isinstance(exc, (BridgeError, ResourceBusy)):
            payload.update({"runId": getattr(exc, "run_id", ""), "logFile": getattr(exc, "log_file", "")})
        print(json.dumps(payload, ensure_ascii=False))
        return 5
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 4


if __name__ == "__main__":
    sys.exit(main())
