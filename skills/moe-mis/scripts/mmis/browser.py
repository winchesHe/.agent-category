import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .errors import ConfigError

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)

_AGENT_BROWSER_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}")
_AGENT_BROWSER_TARGET = re.compile(r"(?:t[1-9][0-9]*|[A-Za-z0-9_][A-Za-z0-9_-]{0,63})")


def _agent_browser_prefix(browser_session, browser_namespace):
    if not _AGENT_BROWSER_NAME.fullmatch(
        browser_session
    ) or not _AGENT_BROWSER_NAME.fullmatch(browser_namespace):
        raise ConfigError("agent-browser namespace/session 格式无效")
    agent_browser = shutil.which("agent-browser")
    if not agent_browser:
        raise ConfigError("定向浏览器操作需要 agent-browser")
    return [
        agent_browser,
        "--namespace",
        browser_namespace,
        "--session",
        browser_session,
    ]


def _agent_browser_eval(prefix, script, timeout=30):
    """通过 stdin 执行脚本，避免把敏感值放进进程参数。"""
    result = subprocess.run(
        [*prefix, "eval", "--stdin", "--json"],
        input=script,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    payload = json.loads(result.stdout)
    if not payload.get("success"):
        raise ConfigError("agent-browser 页面脚本执行失败")
    return payload.get("data", {}).get("result")


def continue_login_in_tab(
    login_url,
    *,
    browser_session,
    browser_namespace,
    browser_target,
    allowed_redirect_host,
    expected_final_path,
    timeout=60,
):
    """在已有登录标签页续登；敏感 token 只存在于进程内和页面导航内存。"""
    prefix = _agent_browser_prefix(browser_session, browser_namespace)
    if not _AGENT_BROWSER_TARGET.fullmatch(browser_target):
        raise ConfigError("agent-browser target 格式无效")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", allowed_redirect_host):
        raise ConfigError("allowed redirect host 格式无效")
    if not expected_final_path.startswith("/") or "?" in expected_final_path:
        raise ConfigError("expected final path 必须是不含 query 的绝对路径")

    try:
        info = subprocess.run(
            [*prefix, "session", "info", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if not json.loads(info.stdout).get("data", {}).get("active"):
            raise ConfigError("指定 agent-browser session 未连接")
        subprocess.run(
            [*prefix, "tab", browser_target],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        context = _agent_browser_eval(
            prefix,
            """(() => {
              const current = new URL(location.href);
              const redirectValue = current.searchParams.get('redirect') || '';
              let redirect = null;
              try { redirect = new URL(redirectValue); } catch (_) {}
              return {
                host: current.host,
                path: current.pathname,
                companyID: current.searchParams.get('companyID') || '',
                redirectUrl: redirect ? redirect.href : '',
                redirectHost: redirect ? redirect.host : '',
                redirectProtocol: redirect ? redirect.protocol : ''
              };
            })()""",
        )
        parsed_login = urlsplit(login_url)
        if (
            context.get("host") != parsed_login.netloc
            or context.get("path") != parsed_login.path
            or not context.get("companyID")
        ):
            raise ConfigError("目标标签页不是带 companyID 的 MoeGo 登录页")
        if (
            context.get("redirectHost") != allowed_redirect_host
            or context.get("redirectProtocol") != "https:"
        ):
            raise ConfigError("目标标签页 redirect 不在允许范围")

        query = parse_qs(parsed_login.query, keep_blank_values=True)
        query["companyID"] = [context["companyID"]]
        query["redirect"] = [context["redirectUrl"]]
        continued_url = urlunsplit(
            (
                parsed_login.scheme,
                parsed_login.netloc,
                parsed_login.path,
                urlencode(query, doseq=True),
                "",
            )
        )
        navigate_script = """(() => {
          location.assign(%s);
          return {started: true};
        })()""" % json.dumps(continued_url)
        _agent_browser_eval(prefix, navigate_script)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.25)
            try:
                state = _agent_browser_eval(
                    prefix,
                    """(() => {
                      const current = new URL(location.href);
                      return {
                        host: current.host,
                        path: current.pathname,
                        hasToken: current.searchParams.has('token')
                      };
                    })()""",
                    timeout=min(30, timeout),
                )
            except (ConfigError, subprocess.CalledProcessError):
                continue
            if (
                state.get("host") == allowed_redirect_host
                and state.get("path") == expected_final_path
                and not state.get("hasToken")
            ):
                return {
                    "continued": True,
                    "targetHost": state["host"],
                    "targetPath": state["path"],
                }
        raise ConfigError("等待原标签页完成续登超时")
    except ConfigError:
        raise
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise ConfigError("无法在指定 agent-browser 标签页继续登录") from exc


def find_chrome(configured=""):
    if configured:
        if shutil.which(configured) or configured.startswith("/"):
            return configured
        raise ConfigError(f"找不到 MOE_MIS_CHROME_BINARY：{configured}")
    for candidate in CHROME_CANDIDATES:
        if shutil.which(candidate) or __import__("os").path.exists(candidate):
            return candidate
    binary = shutil.which("google-chrome") or shutil.which("chromium")
    if binary:
        return binary
    raise ConfigError("找不到 Google Chrome，请设置 MOE_MIS_CHROME_BINARY")


def open_url(url, *, browser_session="", browser_namespace="moego-delivery"):
    if browser_session:
        prefix = _agent_browser_prefix(browser_session, browser_namespace)
        try:
            info = subprocess.run(
                [*prefix, "session", "info", "--json"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if not json.loads(info.stdout).get("data", {}).get("active"):
                raise ConfigError("指定 agent-browser session 未连接；先运行 lane open")
            subprocess.run(
                [*prefix, "open", url],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except ConfigError:
            raise
        except (
            OSError,
            ValueError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise ConfigError("无法在指定 agent-browser session 打开登录页") from exc
        return
    if not webbrowser.open(url):
        subprocess.run(["open", url], check=True)


def _read_binding(path):
    target = Path(path)
    if not target.is_absolute() or target.is_symlink():
        raise ConfigError("browser binding file 必须是绝对路径普通文件")
    try:
        metadata = target.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ConfigError("browser binding file 必须是单链接普通文件")
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError("无法安全读取 BrowserBinding") from exc
    required = {
        "bindingId",
        "bindingEpoch",
        "bindingHash",
        "namespace",
        "session",
        "host",
        "status",
    }
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 or not required.issubset(value):
        raise ConfigError("BrowserBinding schema 不受支持")
    if value["status"] != "active":
        raise ConfigError("BrowserBinding 已失效")
    identity = {
        key: value.get(key)
        for key in (
            "laneId",
            "runtimeId",
            "runtimeGeneration",
            "bindingEpoch",
            "namespace",
            "session",
            "cdpPort",
            "host",
            "environment",
        )
    }
    expected_hash = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if value.get("bindingHash") != expected_hash:
        raise ConfigError("BrowserBinding identity hash 不一致")
    try:
        expires = datetime.fromisoformat(str(value["expiresAt"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise ConfigError("BrowserBinding expiresAt 无效") from exc
    if expires <= datetime.now(timezone.utc):
        raise ConfigError("BrowserBinding 已过期")
    lane_path = target.parent.parent / str(value.get("laneId", "")) / "lane.json"
    try:
        if lane_path.is_symlink() or lane_path.stat().st_nlink != 1:
            raise ConfigError("BrowserBinding lane manifest 不安全")
        lane = json.loads(lane_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError("无法回读 BrowserBinding lane manifest") from exc
    if (
        lane.get("laneId") != value.get("laneId")
        or lane.get("runtimeId") != value.get("runtimeId")
        or lane.get("runtimeGeneration") != value.get("runtimeGeneration")
        or lane.get("bindingEpoch") != value.get("bindingEpoch")
        or lane.get("browserBindingId") != value.get("bindingId")
        or lane.get("browserBindingHash") != value.get("bindingHash")
        or lane.get("host") != value.get("host")
        or lane.get("ports", {}).get("cdp") != value.get("cdpPort")
    ):
        raise ConfigError("BrowserBinding 与当前 lane/runtime generation 不一致")
    driver = lane.get("chrome", {}).get("driver", {})
    if (
        driver.get("namespace") != value.get("namespace")
        or driver.get("session") != value.get("session")
    ):
        raise ConfigError("BrowserBinding 与当前 lane browser session 不一致")
    socket_root = Path(str(driver.get("socketRoot") or ""))
    if (
        not socket_root.is_absolute()
        or socket_root.is_symlink()
        or not socket_root.is_dir()
    ):
        raise ConfigError("BrowserBinding lane socket root 无效")
    return {**value, "_agentBrowserSocketRoot": str(socket_root)}


@contextmanager
def browser_binding_socket_environment(binding):
    """让直接调用 moe-mis 的进程使用 BrowserBinding 对应的 Delivery socket。"""
    socket_root = str(binding.get("_agentBrowserSocketRoot") or "")
    if not socket_root:
        raise ConfigError("BrowserBinding 缺少 lane socket root")
    key = "AGENT_BROWSER_SOCKET_DIR"
    previous = os.environ.get(key)
    os.environ[key] = socket_root
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


@contextmanager
def browser_binding_use(path, *, expected_host="", expected_environment=""):
    target = Path(path)
    initial = _read_binding(target)
    lock = target.with_suffix(".use.lock")
    if lock.is_symlink():
        raise ConfigError("BrowserBinding use lock 不能是符号链接")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(str(lock), flags, 0o600)
    except OSError as exc:
        raise ConfigError("无法安全打开 BrowserBinding use lock") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ConfigError("BrowserBinding use lock 必须是单链接普通文件")
        fcntl.flock(fd, fcntl.LOCK_EX)
        current = _read_binding(target)
        if (
            expected_environment
            and current["environment"] != expected_environment
        ):
            raise ConfigError("BrowserBinding 环境与当前 MIS 环境不一致")
        if expected_host and current["host"] != expected_host:
            raise ConfigError("BrowserBinding Host 与目标操作不一致")
        yield current
        after = _read_binding(target)
        if after["bindingEpoch"] != current["bindingEpoch"] or after["bindingHash"] != current["bindingHash"]:
            raise ConfigError("BrowserBinding 在操作期间发生 rebind")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def open_url_with_binding(url, binding_file, *, expected_environment=""):
    urllib_parse = __import__("urllib.parse", fromlist=["urlsplit", "urlunsplit"])
    parsed = urllib_parse.urlsplit(url)
    with browser_binding_use(
        binding_file, expected_environment=expected_environment
    ) as binding:
        if not (
            parsed.hostname
            and parsed.hostname.endswith("go.t2.moego.dev")
            and str(binding["host"]).endswith("go.t2.moego.dev")
        ):
            raise ConfigError("BrowserBinding Host 与账号登录目标产品不一致")
        target_url = urllib_parse.urlunsplit(
            (parsed.scheme, binding["host"], parsed.path, parsed.query, "")
        )
        with browser_binding_socket_environment(binding):
            open_url(
                target_url,
                browser_session=binding["session"],
                browser_namespace=binding["namespace"],
            )
        return {
            "bindingId": binding["bindingId"],
            "bindingEpoch": binding["bindingEpoch"],
            "browserSession": binding["session"],
            "browserNamespace": binding["namespace"],
            "targetHost": binding["host"],
        }


def set_browser_cookies(cookies, *, browser_session, browser_namespace):
    if not browser_session:
        return {"state": "skipped", "count": 0}
    if not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", browser_session
    ) or not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", browser_namespace
    ):
        raise ConfigError("agent-browser namespace/session 格式无效")
    agent_browser = shutil.which("agent-browser")
    if not agent_browser:
        raise ConfigError("注入 OB Session 需要 agent-browser")
    prefix = [
        agent_browser,
        "--namespace",
        browser_namespace,
        "--session",
        browser_session,
    ]
    try:
        info = subprocess.run(
            [*prefix, "session", "info", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if not json.loads(info.stdout).get("data", {}).get("active"):
            raise ConfigError("指定 agent-browser session 未连接；先运行 lane open")
        for cookie in cookies:
            command = [
                *prefix,
                "cookies",
                "set",
                cookie["name"],
                cookie["value"],
            ]
            if cookie.get("domain"):
                command.extend(["--domain", cookie["domain"]])
            else:
                raise ConfigError("OB Session Cookie 缺少 domain，无法安全注入")
            command.extend(["--path", cookie.get("path") or "/"])
            if cookie.get("httpOnly"):
                command.append("--httpOnly")
            if cookie.get("secure"):
                command.append("--secure")
            same_site = cookie.get("sameSite")
            if same_site in ("Strict", "Lax", "None"):
                command.extend(["--sameSite", same_site])
            if cookie.get("expires"):
                command.extend(["--expires", str(cookie["expires"])])
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        observed = subprocess.run(
            [*prefix, "cookies", "get", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(observed.stdout)
        observed_cookies = payload.get("data", {}).get("cookies", [])
        expected_keys = {
            (
                cookie["name"],
                cookie["domain"].lstrip("."),
                cookie.get("path") or "/",
            )
            for cookie in cookies
        }
        observed_keys = {
            (
                str(cookie.get("name") or ""),
                str(cookie.get("domain") or "").lstrip("."),
                str(cookie.get("path") or "/"),
            )
            for cookie in observed_cookies
            if isinstance(cookie, dict)
        }
        if not expected_keys.issubset(observed_keys):
            raise ConfigError("OB Session Cookie 注入后未在指定浏览器中回读到")
        return {"state": "verified", "count": len(expected_keys)}
    except ConfigError:
        raise
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise ConfigError("无法向指定 agent-browser session 注入 OB Session") from exc


def expire_browser_cookies(cookies, *, browser_session, browser_namespace):
    if not browser_session or not cookies:
        return {"state": "skipped", "count": 0}
    if not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", browser_session
    ) or not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", browser_namespace
    ):
        raise ConfigError("agent-browser namespace/session 格式无效")
    agent_browser = shutil.which("agent-browser")
    if not agent_browser:
        raise ConfigError("清理 OB Session 需要 agent-browser")
    prefix = [
        agent_browser,
        "--namespace",
        browser_namespace,
        "--session",
        browser_session,
    ]
    try:
        info = subprocess.run(
            [*prefix, "session", "info", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if not json.loads(info.stdout).get("data", {}).get("active"):
            return {"state": "unavailable", "count": 0}
        for cookie in cookies:
            domain = cookie.get("domain")
            if not domain:
                raise ConfigError("OB Session Cookie 缺少 domain，无法安全清理")
            command = [
                *prefix,
                "cookies",
                "set",
                cookie["name"],
                "",
                "--domain",
                domain,
                "--path",
                cookie.get("path") or "/",
                "--expires",
                "1",
            ]
            if cookie.get("secure"):
                command.append("--secure")
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        return {"state": "expired", "count": len(cookies)}
    except ConfigError:
        raise
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise ConfigError("无法清理指定 agent-browser session 的 OB Session") from exc


def copy_to_clipboard(value):
    try:
        subprocess.run(
            ["pbcopy"], input=value, text=True, check=True, capture_output=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ConfigError(f"无法复制到剪贴板：{exc}") from exc
