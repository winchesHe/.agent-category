import json
import socket
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

import websocket

from .browser import find_chrome
from .errors import AuthError, TimeoutError
from .keychain import MisCredential, find_mis_session_cookie


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _targets(port):
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
        return json.load(response)


def _rpc(ws, request_id, method, params=None):
    ws.send(
        json.dumps(
            {"id": request_id, "method": method, "params": params or {}}
        )
    )
    while True:
        message = json.loads(ws.recv())
        if message.get("id") == request_id:
            if message.get("error"):
                raise AuthError("Chrome CDP 错误：{}".format(message["error"]))
            return message.get("result", {})


def _cookies_for_origin(items, mis_url):
    host = urlsplit(mis_url).hostname or ""
    return {
        item["name"]: item["value"]
        for item in items
        if host == item.get("domain", "").lstrip(".")
        or host.endswith("." + item.get("domain", "").lstrip("."))
    }


def _read_origin_cookies(port, mis_url, request_id):
    page = next(
        (target for target in _targets(port) if target.get("type") == "page"),
        None,
    )
    if not page:
        return {}
    ws = websocket.create_connection(
        page["webSocketDebuggerUrl"],
        timeout=2,
        origin=f"http://127.0.0.1:{port}",
    )
    try:
        result = _rpc(
            ws,
            request_id,
            "Network.getCookies",
            {"urls": [mis_url]},
        )
        return _cookies_for_origin(result.get("cookies", []), mis_url)
    finally:
        ws.close()


def capture_mis_credential(mis_url, timeout=180, chrome_binary=""):
    """Use an isolated Chrome profile and read cookies only for the MIS origin."""
    port = _free_port()
    chrome = find_chrome(chrome_binary)
    with tempfile.TemporaryDirectory(prefix="mio-chrome-") as profile:
        process = subprocess.Popen(
            [
                chrome,
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={port}",
                f"--remote-allow-origins=http://127.0.0.1:{port}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                mis_url + "/login?redirect=%2F",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout
        try:
            targets = []
            while time.monotonic() < deadline:
                try:
                    targets = _targets(port)
                    if targets:
                        break
                except (OSError, URLError, ValueError):
                    time.sleep(0.25)
            page = next(
                (target for target in targets if target.get("type") == "page"), None
            )
            if not page:
                raise TimeoutError("等待 Chrome CDP 页面超时")
            request_id = 1
            while time.monotonic() < deadline:
                try:
                    cookies = _read_origin_cookies(port, mis_url, request_id)
                    session_cookie = find_mis_session_cookie(cookies)
                    if session_cookie:
                        session_name, session_value = session_cookie
                        return MisCredential(
                            mgdid=cookies.get("MGDID", ""),
                            session_cookie_name=session_name,
                            session_cookie_value=session_value,
                        )
                except (
                    OSError,
                    URLError,
                    ValueError,
                    websocket.WebSocketException,
                ):
                    # SSO navigation may destroy the previous page target.
                    # Re-resolve /json/list and connect to the current tab.
                    pass
                finally:
                    request_id += 1
                    time.sleep(0.5)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        raise TimeoutError("MIS 登录超时，未捕获到所需 Cookie")
