from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .errors import AuthError, BusinessError, ConfigError, TimeoutError

SHANGHAI = ZoneInfo("Asia/Shanghai")
EMAIL_PATTERN = re.compile(
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE
)
SLACK_MENTION_PATTERN = re.compile(r"<@[A-Z0-9]+>")
FACEBOOK_URL_PATTERN = re.compile(
    r"https://(?:www\.)?facebook\.com/[^\s<>|]+", re.IGNORECASE
)
SUMMARY_PREFIX = re.compile(
    r"^(?P<label>"
    r"campaign\s+(?:comment|feedback)\s+summary|"
    r"facebook\s+campaign\s+feedback|"
    r"facebook\s+(?:comment|feedback)\s+summary|"
    r"campaign\s*留言总结|facebook\s*留言总结|"
    r"customer\s+replied|he\s+replied|she\s+replied"
    r")\s*[:：]\s*(?P<content>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _stable_id(*parts):
    value = ":".join(str(part or "") for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _timestamp_iso(value):
    try:
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise BusinessError("Facebook Slack 消息时间无效") from exc
    return parsed.isoformat().replace("+00:00", "Z")


def _timestamp_date(value):
    return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone(SHANGHAI).date()


def _sanitize_text(value, *, limit=10000):
    text = EMAIL_PATTERN.sub("[EMAIL]", str(value or ""))
    text = SLACK_MENTION_PATTERN.sub("", text)
    return text.strip()[:limit]


def _canonical_facebook_url(value):
    if not value:
        return ""
    raw = unquote(str(value)).strip("<>.,)")
    parsed = urlsplit(raw)
    if parsed.hostname not in {"facebook.com", "www.facebook.com"}:
        return ""
    if parsed.path.lower() in {"/o.php", "/l.php"} or "unsubscribe" in raw.lower():
        return ""
    return urlunsplit(("https", "www.facebook.com", parsed.path.rstrip("/"), "", ""))


def _group_ref(value):
    decoded = unquote(str(value or ""))
    match = re.search(r"(?:^|[/?&])groups/([^/?#&]+)", decoded, re.IGNORECASE)
    return match.group(1) if match else ""


def _facebook_email(file_value):
    senders = file_value.get("from") if isinstance(file_value, dict) else None
    if not isinstance(senders, list):
        return False
    for sender in senders:
        address = sender.get("address") if isinstance(sender, dict) else ""
        if str(address).lower().endswith("@facebookmail.com"):
            return True
    return False


def _extract_post_content(plain_text):
    match = re.search(
        r"needs approval:\s*[\"“](?P<content>.*?)[\"”]\.\s*\n\s*\n",
        plain_text,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return _sanitize_text(match.group("content"))
    return ""


def _extract_group_name(value):
    match = re.search(
        r"post in (?P<group>.+?) needs approval",
        value,
        re.IGNORECASE | re.DOTALL,
    )
    return _sanitize_text(match.group("group"), limit=200) if match else ""


def _extract_group_url(plain_text):
    urls = re.findall(r"https?://[^\s]+", plain_text)
    for url in urls:
        decoded = unquote(url)
        group = _group_ref(decoded)
        if group:
            return f"https://www.facebook.com/groups/{group}/pending_posts", group
    return "", ""


def _normalize_email(match, file_value, *, channel_id, domain):
    subject = str(file_value.get("subject") or file_value.get("title") or "")
    plain_text = str(file_value.get("plain_text") or "")
    combined = f"{subject}\n{plain_text}"
    if not _facebook_email(file_value) or "needs approval" not in combined.lower():
        return None
    file_id = str(file_value.get("id") or "")
    ts = str(match.get("ts") or "")
    if not file_id or not ts:
        raise BusinessError("Facebook Slack 邮件缺少 file id 或时间")
    source_url, group = _extract_group_url(plain_text)
    content = _extract_post_content(plain_text)
    group_name = _extract_group_name(combined)
    object_id = _stable_id(channel_id, ts, file_id)
    return {
        "schemaVersion": 1,
        "evidenceId": f"facebook:slack-email:{object_id}",
        "sourceKey": "facebook",
        "sourceObjectId": object_id,
        "objectType": "feedback",
        "feedType": "group_post",
        "domain": domain,
        "title": (content[:120] if content else "Facebook Group 新帖"),
        "content": content,
        "groupName": group_name,
        "groupRef": group,
        "approvalStatus": "pending_or_unknown",
        "createdAt": _timestamp_iso(ts),
        "sourceUrl": source_url,
        "slackUrl": str(match.get("permalink") or ""),
        "coverage": "channel-summary",
    }


def _extract_facebook_url(value):
    match = FACEBOOK_URL_PATTERN.search(value)
    return _canonical_facebook_url(match.group(0)) if match else ""


def _sanitize_summary_content(value):
    sanitized = _sanitize_text(value)
    return FACEBOOK_URL_PATTERN.sub(
        lambda match: _canonical_facebook_url(match.group(0)), sanitized
    )


def _normalize_summary(match, *, channel_id, domain):
    text = str(match.get("text_raw") or "").strip()
    parsed = SUMMARY_PREFIX.match(text)
    if not parsed:
        return None
    content = _sanitize_summary_content(parsed.group("content"))
    if not content:
        return None
    label = parsed.group("label").lower()
    feed_type = (
        "campaign_comment_summary" if "campaign" in label else "group_comment_summary"
    )
    ts = str(match.get("ts") or "")
    thread_ts = str(match.get("thread_ts") or ts)
    object_id = _stable_id(channel_id, ts)
    parent_id = _stable_id(channel_id, thread_ts)
    slack_url = str(match.get("permalink") or "")
    return {
        "schemaVersion": 1,
        "evidenceId": f"facebook:slack-summary:{object_id}",
        "sourceKey": "facebook",
        "sourceObjectId": object_id,
        "objectType": "summary",
        "feedType": feed_type,
        "parentEvidenceId": f"facebook:slack-thread:{parent_id}",
        "domain": domain,
        "title": "Campaign 留言总结" if "campaign" in label else "Facebook 留言总结",
        "content": content,
        "createdAt": _timestamp_iso(ts),
        "sourceUrl": _extract_facebook_url(text) or slack_url,
        "slackUrl": slack_url,
        "coverage": "channel-summary",
    }


class SlackTransport:
    def __init__(self, config):
        self.script = config.slack_script
        self.channel_id = config.facebook_slack_channel
        self.timeout = config.timeout

    def _run(self, args):
        if not self.script:
            raise ConfigError("找不到 slack skill")
        try:
            result = subprocess.run(
                ["python3", str(self.script), *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Facebook Slack 数据读取超时") from exc
        if result.returncode:
            stderr = result.stderr.lower()
            if any(
                marker in stderr
                for marker in (
                    "invalid_auth",
                    "not_authed",
                    "missing_scope",
                    "not_allowed_token_type",
                )
            ):
                raise AuthError("Slack 鉴权或搜索权限不足")
            if result.returncode == 2:
                raise ConfigError("Slack 数据源配置不可用")
            raise BusinessError("Slack 数据源读取失败")
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise BusinessError("slack skill 返回了无效 JSON") from exc

    def fetch_messages(self, start, end, *, probe=False):
        resolved = self._run(["resolve", self.channel_id])
        channel = resolved.get("resolved") if isinstance(resolved, dict) else None
        if (
            not isinstance(channel, dict)
            or channel.get("id") != self.channel_id
            or not channel.get("name")
        ):
            raise BusinessError("无法解析 Facebook Slack 频道")
        after = start - timedelta(days=1)
        before = end + timedelta(days=1)
        query = f"in:{channel['name']} after:{after.isoformat()} before:{before.isoformat()}"
        return self._run(
            [
                "search",
                query,
                "--sort",
                "timestamp",
                "--sort-dir",
                "asc",
                "--limit",
                "20" if probe else "1000",
            ]
        )


class FixtureTransport:
    def __init__(self, path):
        self.path = Path(path)

    def fetch_messages(self, _start, _end, *, probe=False):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"无法读取 Facebook fixture：{self.path}") from exc
        if not isinstance(payload, dict):
            raise ConfigError("Facebook fixture 必须是 JSON object")
        if probe and isinstance(payload.get("matches"), list):
            payload = dict(payload)
            payload["matches"] = payload["matches"][:20]
            payload["returned"] = len(payload["matches"])
        return payload


class FacebookCollector:
    def __init__(self, transport, *, channel_id, domain):
        self.transport = transport
        self.channel_id = channel_id
        self.domain = domain

    def collect(self, start: date, end: date, *, probe=False):
        payload = self.transport.fetch_messages(start, end, probe=probe)
        matches = payload.get("matches") if isinstance(payload, dict) else None
        if not isinstance(matches, list):
            raise BusinessError("Slack Facebook 响应缺少 matches")
        total = payload.get("total")
        returned = payload.get("returned")
        if not isinstance(total, int) or not isinstance(returned, int):
            raise BusinessError("Slack Facebook 响应缺少数量元数据")
        if returned != len(matches):
            raise BusinessError("Slack Facebook 返回数量不一致")
        if not probe and returned != total:
            raise BusinessError("Slack Facebook 搜索结果不完整")

        evidence_by_id = {}
        in_period = 0
        for match in matches:
            if not isinstance(match, dict) or not match.get("ts"):
                raise BusinessError("Slack Facebook 消息结构无效")
            if match.get("channel_id") != self.channel_id:
                raise BusinessError("Slack Facebook 消息不属于目标频道")
            try:
                message_date = _timestamp_date(match["ts"])
            except (TypeError, ValueError, OverflowError, OSError) as exc:
                raise BusinessError("Facebook Slack 消息时间无效") from exc
            if not start <= message_date <= end:
                continue
            in_period += 1
            raw = match.get("raw") if isinstance(match.get("raw"), dict) else {}
            files = raw.get("files") if isinstance(raw.get("files"), list) else []
            normalized = None
            for file_value in files:
                if not isinstance(file_value, dict):
                    continue
                normalized = _normalize_email(
                    match,
                    file_value,
                    channel_id=self.channel_id,
                    domain=self.domain,
                )
                if normalized:
                    break
            if normalized is None:
                normalized = _normalize_summary(
                    match,
                    channel_id=self.channel_id,
                    domain=self.domain,
                )
            if normalized:
                evidence_by_id[normalized["evidenceId"]] = normalized

        evidence = sorted(evidence_by_id.values(), key=lambda item: item["createdAt"])
        feed_counts = {}
        for item in evidence:
            feed = item["feedType"]
            feed_counts[feed] = feed_counts.get(feed, 0) + 1
        return {
            "observed": in_period,
            "evidence": evidence,
            "reportRows": [],
            "skipped": in_period - len(evidence),
            "feedCounts": feed_counts,
            "period": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        }
