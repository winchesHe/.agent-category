from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .errors import AuthError, BusinessError, ConfigError, TimeoutError

SENSITIVE_KEY = re.compile(
    r"token|cookie|authorization|secret|password|__canny__requestid", re.I
)
SHANGHAI = ZoneInfo("Asia/Shanghai")


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def created_date_in_shanghai(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SHANGHAI).date()


def sanitize(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def post_snapshot(post):
    details_hash = hashlib.sha256(
        str(post.get("details") or "").encode("utf-8")
    ).hexdigest()
    return {
        "score": int(post.get("score") or 0),
        "commentCount": int(post.get("commentCount") or 0),
        "status": str(post.get("status") or ""),
        "title": str(post.get("title") or ""),
        "detailsHash": details_hash,
    }


def snapshot_hash(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def changed_fields(previous, current):
    if not previous:
        return sorted(current)
    return sorted(key for key, value in current.items() if previous.get(key) != value)


def comment_evidence(detail, post_evidence, collected_at):
    comments = detail.get("comments", {}) if isinstance(detail, dict) else {}
    if isinstance(comments, dict):
        items = comments.items()
    elif isinstance(comments, list):
        items = ((str(item.get("_id") or ""), item) for item in comments)
    else:
        return []
    result = []
    for key, comment in items:
        if not isinstance(comment, dict):
            continue
        comment_id = str(comment.get("_id") or key or "")
        if not comment_id:
            continue
        safe_comment = sanitize(comment)
        comment_hash = hashlib.sha256(
            json.dumps(
                safe_comment, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        result.append(
            {
                "evidenceId": f"canny:comment:{comment_id}",
                "eventId": hashlib.sha256(
                    f"canny:comment:{comment_id}:{comment_hash}".encode("utf-8")
                ).hexdigest(),
                "sourceKey": "canny",
                "sourceObjectId": comment_id,
                "objectType": "comment",
                "parentEvidenceId": post_evidence["evidenceId"],
                "title": "",
                "content": str(
                    comment.get("value")
                    or comment.get("content")
                    or comment.get("body")
                    or ""
                ),
                "authorRef": comment.get("authorID")
                or (comment.get("author") or {}).get("_id", ""),
                "createdAt": comment.get("created")
                or comment.get("createdAt")
                or "",
                "sourceUrl": post_evidence["sourceUrl"],
                "voteCount": 0,
                "commentCount": 0,
                "status": "",
                "snapshotHash": comment_hash,
                "changedFields": [],
                "firstSeenAt": collected_at,
                "lastSeenAt": collected_at,
                "detail": safe_comment,
            }
        )
    return result


def scan_cumulative(fetch_page, should_stop, page_cap):
    pages = 1
    latest = {"posts": [], "hasNextPage": False}
    while True:
        latest = fetch_page(pages)
        posts = latest.get("posts", [])
        if should_stop(posts, bool(latest.get("hasNextPage"))) or pages >= page_cap:
            return posts
        pages = min(page_cap, pages * 2)


class FixtureTransport:
    def __init__(self, path):
        try:
            self.data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError("无法读取 Canny fixture") from exc

    def start(self):
        return None

    def close(self):
        return None

    def ensure_authenticated(self, _account_ref):
        return {"authenticated": True, "method": "fixture"}

    def fetch_posts(self, pages, sort):
        bucket = self.data.get(f"{sort}_pages", {})
        value = bucket.get(str(pages))
        if value is None:
            ordered = sorted((int(key), item) for key, item in bucket.items())
            value = next((item for key, item in reversed(ordered) if key <= pages), None)
        if value is None:
            raise BusinessError(f"fixture 缺少 {sort} pages={pages}")
        return value

    def fetch_detail(self, post):
        return self.data.get("details", {}).get(str(post.get("_id")), {})


class BrowserTransport:
    def __init__(self, config, headed=False):
        self.config = config
        suffix = uuid.uuid4().hex[:10]
        self.namespace = f"mfc_{suffix}"
        self.session = f"canny_{suffix}"
        self.headed = headed
        self._started = False

    @property
    def prefix(self):
        command = [self.config.agent_browser]
        if self.headed:
            command.append("--headed")
        command.extend(
            ["--namespace", self.namespace, "--session", self.session]
        )
        return command

    def _run(self, args, *, input_text=None, timeout=None):
        try:
            return subprocess.run(
                [*self.prefix, *args],
                input=input_text,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout or self.config.timeout,
            )
        except FileNotFoundError as exc:
            raise ConfigError("找不到 agent-browser") from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("agent-browser 操作超时") from exc
        except subprocess.CalledProcessError as exc:
            raise BusinessError("agent-browser 操作失败") from exc

    def _eval(self, script):
        result = self._run(["eval", "--stdin", "--json"], input_text=script)
        try:
            payload = json.loads(result.stdout)
        except ValueError as exc:
            raise BusinessError("agent-browser eval 未返回 JSON") from exc
        if not payload.get("success"):
            raise BusinessError("agent-browser 页面脚本执行失败")
        return payload.get("data", {}).get("result")

    def start(self):
        self._started = True
        try:
            self._run(["open", self.config.canny_board_url], timeout=self.config.timeout)
        except Exception:
            # open 可能已经创建 session 后才返回错误，交给外层 finally 回收。
            raise

    def close(self):
        if not self._started:
            return
        try:
            self._run(["close"], timeout=30)
        except (BusinessError, TimeoutError):
            pass
        self._started = False

    def _active_tab(self):
        result = self._run(["tab", "list", "--json"])
        try:
            tabs = json.loads(result.stdout).get("data", {}).get("tabs", [])
        except ValueError as exc:
            raise BusinessError("无法读取 agent-browser tabs") from exc
        active = next((tab for tab in tabs if tab.get("active")), None)
        if not active or not re.fullmatch(r"t[1-9][0-9]*", str(active.get("tabId"))):
            raise BusinessError("无法确定 Canny 登录标签页")
        return active["tabId"]

    def _probe(self):
        return self._eval(
            """(async () => {
              const runtime = (window.__data || {}).cookies || {};
              const body = Object.assign({}, runtime, {
                boardURLNames: ['feature-request'],
                currentBoard: 'feature-request', pages: 1, sort: 'newest'
              });
              const response = await fetch('/api/posts/get', {
                method: 'POST', headers: {'content-type': 'application/json'},
                credentials: 'include', body: JSON.stringify(body)
              });
              let payload = {};
              try { payload = await response.json(); } catch (_) {}
              return {
                ok: response.ok, status: response.status,
                authorized: response.ok && Array.isArray(payload.result?.posts),
                error: payload.error ? String(payload.error).slice(0, 120) : ''
              };
            })()"""
        )

    def ensure_authenticated(self, account_ref):
        probe = self._probe()
        if probe.get("authorized"):
            return {"authenticated": True, "method": "existing-session"}
        if not account_ref:
            raise ConfigError("实时 Canny 采集需要 --account-ref")
        if not self.config.moe_mis_script:
            raise ConfigError("找不到 moe-mis 入口")

        login_url = self._eval(
            """(() => {
              const links = Array.from(document.querySelectorAll('a[href]'))
                .map(node => node.href)
                .filter(value => value.includes('go.moego.pet/sign_in'));
              return links[0] || '';
            })()"""
        )
        if not login_url:
            raise AuthError("Canny 未授权，且页面没有 MoeGo Login 入口")
        parsed = urlsplit(login_url)
        if parsed.hostname != "go.moego.pet" or parsed.path != "/sign_in":
            raise AuthError("Canny Login 入口不符合预期")
        self._run(["open", login_url])
        tab_id = self._active_tab()
        command = [
            "uv",
            "run",
            "--script",
            str(self.config.moe_mis_script),
            "--env",
            "production",
            "--format",
            "json",
            "impersonate",
            "--account-ref",
            account_ref,
            "--source",
            "business",
            "--max-age",
            "h1",
            "--unattended",
            "--browser-session",
            self.session,
            "--browser-namespace",
            self.namespace,
            "--continue-login-target",
            tab_id,
            "--allowed-redirect-host",
            "moego.canny.io",
            "--expected-final-path",
            "/feature-request",
        ]
        try:
            result = subprocess.run(
                command,
                cwd=self.config.moe_mis_workdir,
                check=True,
                capture_output=True,
                text=True,
                timeout=max(90, self.config.timeout),
            )
            receipt = json.loads(result.stdout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("moe-mis 续登超时") from exc
        except (subprocess.CalledProcessError, ValueError) as exc:
            raise AuthError("moe-mis 未能完成 Canny 续登") from exc
        if not receipt.get("continued"):
            raise AuthError("moe-mis 未返回续登成功凭据")
        probe = self._probe()
        if not probe.get("authorized"):
            raise AuthError("续登完成后 Canny 站内接口仍未授权")
        return {"authenticated": True, "method": "mis-continue-login"}

    def fetch_posts(self, pages, sort):
        script = """(async () => {
          const runtime = (window.__data || {}).cookies || {};
          const body = Object.assign({}, runtime, {
            boardURLNames: ['feature-request'], currentBoard: 'feature-request',
            pages: %d, sort: %s
          });
          const response = await fetch('/api/posts/get', {
            method: 'POST', headers: {'content-type': 'application/json'},
            credentials: 'include', body: JSON.stringify(body)
          });
          const payload = await response.json();
          if (!response.ok) return {ok: false, status: response.status, error: payload.error || ''};
          return {ok: true, posts: payload.result?.posts || [], hasNextPage: !!payload.result?.hasNextPage};
        })()""" % (pages, json.dumps(sort))
        value = self._eval(script)
        if not value.get("ok"):
            if value.get("status") in {401, 403} or "authorized" in str(value.get("error", "")):
                raise AuthError("Canny 站内接口鉴权失效")
            error = str(value.get("error") or "unknown")[:120]
            raise BusinessError(
                f"Canny /api/posts/get 返回失败：sort={sort}, pages={pages}, "
                f"status={value.get('status')}, error={error}"
            )
        return sanitize(value)

    def fetch_detail(self, post):
        post_id = str(post.get("_id") or "")
        url_name = str(post.get("urlName") or "")
        if not post_id or not re.fullmatch(r"[A-Za-z0-9_-]+", url_name):
            return {}
        self._run(
            ["open", f"https://moego.canny.io/feature-request/p/{url_name}"]
        )
        deadline = time.monotonic() + min(30, self.config.timeout)
        while time.monotonic() < deadline:
            detail = self._eval(
                """(() => {
                  const activity = (window.__data || {}).postsActivity?.[%s];
                  if (!activity || activity.loading) return {ready: false};
                  return {
                    ready: true,
                    comments: activity.comments || {},
                    activities: activity.activities || [],
                    hasMore: !!activity.hasMore
                  };
                })()""" % json.dumps(post_id)
            )
            if detail.get("ready"):
                detail.pop("ready", None)
                return sanitize(detail)
            time.sleep(0.25)
        raise TimeoutError(f"读取 Canny 详情超时：{post_id}")


class CannyCollector:
    def __init__(self, transport, *, board_url, min_vote, page_cap):
        self.transport = transport
        self.board_url = board_url.rstrip("/")
        self.min_vote = min_vote
        self.page_cap = page_cap

    def _newest(self, checkpoint, mode, period_start=None):
        boundary = checkpoint.get("lastCreated", "")
        has_baseline = bool(checkpoint.get("posts"))

        def stop(posts, has_next):
            if not has_next:
                return True
            if mode == "full" or not has_baseline:
                return False
            if period_start:
                return any(
                    created is not None and created < period_start
                    for post in posts
                    if (created := created_date_in_shanghai(post.get("created")))
                )
            if not boundary:
                return False
            return any(str(post.get("created") or "") <= boundary for post in posts)

        return scan_cumulative(
            lambda pages: self.transport.fetch_posts(pages, "newest"),
            stop,
            self.page_cap,
        )

    def _top(self, mode):
        if mode == "probe":
            return self.transport.fetch_posts(1, "score").get("posts", [])

        def stop(posts, has_next):
            if not has_next or not posts:
                return True
            return int(posts[-1].get("score") or 0) <= self.min_vote

        return scan_cumulative(
            lambda pages: self.transport.fetch_posts(pages, "score"),
            stop,
            self.page_cap,
        )

    def collect(
        self,
        checkpoint,
        mode,
        *,
        period_start: date | None = None,
        period_end: date | None = None,
    ):
        if (period_start is None) != (period_end is None):
            raise BusinessError("Canny 周期开始和结束必须同时提供")
        newest = self._newest(checkpoint, mode, period_start)
        top = self._top(mode)
        newest_ids = {
            str(post.get("_id") or "") for post in newest if post.get("_id")
        }
        observed = {}
        for post in [*newest, *top]:
            post_id = str(post.get("_id") or "")
            if post_id:
                observed[post_id] = post

        previous_posts = checkpoint.get("posts", {})
        next_posts = dict(previous_posts)
        evidence = []
        report_rows = []
        new_count = 0
        changed_count = 0
        discovered_count = 0
        snapshot_changed_count = 0
        collected_at = now_iso()
        is_baseline = not bool(previous_posts)
        for post_id, post in observed.items():
            snapshot = post_snapshot(post)
            previous = previous_posts.get(post_id, {})
            previous_snapshot = previous.get("snapshot")
            is_new = not previous_snapshot
            changes = [] if is_new else changed_fields(previous_snapshot, snapshot)
            vote_delta = (
                None
                if not previous_snapshot
                else snapshot["score"] - int(previous_snapshot.get("score") or 0)
            )
            comment_delta = (
                None
                if not previous_snapshot
                else snapshot["commentCount"]
                - int(previous_snapshot.get("commentCount") or 0)
            )
            if not is_baseline and is_new:
                discovered_count += 1
            elif changes:
                snapshot_changed_count += 1

            created = created_date_in_shanghai(post.get("created"))
            is_period_post = bool(
                period_start is not None
                and created is not None
                and period_start <= created <= period_end
            )
            if period_start is None:
                is_report_row = is_baseline or is_new or bool(changes)
                report_is_new = bool(not is_baseline and is_new)
            else:
                is_report_row = is_period_post
                report_is_new = is_period_post
            if report_is_new:
                new_count += 1
            elif is_report_row and changes:
                changed_count += 1

            signals = []
            if snapshot["score"] >= self.min_vote:
                signals.append(f"Vote {snapshot['score']} ≥ {self.min_vote}")
            if vote_delta is not None and vote_delta >= 5:
                signals.append(f"本期 Vote +{vote_delta}")
            if comment_delta is not None and comment_delta >= 3:
                signals.append(f"本期评论 +{comment_delta}")

            snap_hash = snapshot_hash(snapshot)
            event_id = hashlib.sha256(
                f"canny:{post_id}:{snap_hash}".encode("utf-8")
            ).hexdigest()
            post_evidence = {
                "evidenceId": f"canny:{post_id}",
                "eventId": event_id,
                "sourceKey": "canny",
                "sourceObjectId": post_id,
                "objectType": "post",
                "title": post.get("title") or "",
                "content": post.get("details") or "",
                "createdAt": post.get("created") or "",
                "sourceUrl": f"{self.board_url}/p/{post.get('urlName')}",
                "voteCount": snapshot["score"],
                "voteDelta": vote_delta,
                "commentCount": snapshot["commentCount"],
                "commentDelta": comment_delta,
                "status": snapshot["status"],
                "snapshotHash": snap_hash,
                "changedFields": changes,
                "isNew": report_is_new,
                "changeKind": (
                    "new"
                    if report_is_new
                    else "baseline"
                    if is_baseline
                    else "discovered"
                    if is_new
                    else "changed"
                    if changes
                    else "unchanged"
                ),
                "quickWinPrefilter": bool(signals),
                "quickWinSignals": signals,
                "firstSeenAt": previous.get("firstSeenAt") or collected_at,
                "lastSeenAt": collected_at,
            }
            evidence.append(post_evidence)
            if is_report_row:
                report_rows.append(post_evidence)
            next_posts[post_id] = {
                "snapshot": snapshot,
                "firstSeenAt": previous.get("firstSeenAt") or collected_at,
                "lastSeenAt": collected_at,
            }

        created_values = [
            str(post.get("created") or "") for post in observed.values() if post.get("created")
        ]
        last_created = max(
            [checkpoint.get("lastCreated", ""), *created_values], default=""
        )
        next_checkpoint = {
            "schemaVersion": 1,
            "sourceKey": "canny",
            "lastCreated": last_created,
            "updatedAt": collected_at,
            "posts": next_posts,
        }
        return {
            "observed": len(observed),
            "baseline": is_baseline,
            "baselineCount": len(observed) if is_baseline else 0,
            "newCount": new_count,
            "changedCount": changed_count,
            "discoveredCount": discovered_count,
            "snapshotChangedCount": snapshot_changed_count,
            "evidence": evidence,
            "reportRows": report_rows,
            "checkpoint": next_checkpoint,
        }
