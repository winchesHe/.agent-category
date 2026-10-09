from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DEFAULT_INTERCOM_DATASTORE_ID
from .errors import AuthError, BusinessError, ConfigError, TimeoutError

SHANGHAI = ZoneInfo("Asia/Shanghai")
INTERCOM_DATASTORE_URL = (
    "https://us5.datadoghq.com/actions/datastores/"
    + DEFAULT_INTERCOM_DATASTORE_ID
)
SAFE_FIELDS = (
    "id",
    "business_type",
    "conversation_created_at",
    "conversation_updated_at",
    "domain",
    "enterprise",
    "jira",
    "leads_business_type",
    "requirement",
    "role",
    "sentiment",
    "squad",
    "stripe_plan",
    "tier",
    "type",
)
FORBIDDEN_FIELDS = {"email", "conversation_id", "quote"}
EMAIL_PATTERN = re.compile(
    r"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
    r"(?![A-Z0-9._%+-])",
    re.IGNORECASE,
)


def period_millis(start: date, end: date) -> tuple[int, int]:
    start_value = datetime.combine(start, time.min, tzinfo=SHANGHAI)
    end_value = datetime.combine(end + timedelta(days=1), time.min, tzinfo=SHANGHAI)
    return int(start_value.timestamp() * 1000), int(end_value.timestamp() * 1000)


def period_filter(start_ms: int, end_ms: int) -> str:
    return (
        f"conversation_created_at:>={start_ms} "
        f"AND conversation_created_at:<{end_ms}"
    )


class DatadogTransport:
    def __init__(self, config):
        self.config = config

    def fetch_items(self, start_ms, end_ms, *, probe=False):
        if not self.config.datadog_script:
            raise ConfigError("找不到 datadog skill 入口")
        page_size = 20 if probe else 100
        command = [
            "uv",
            "run",
            "--script",
            str(self.config.datadog_script),
            "list-datastore-items",
            DEFAULT_INTERCOM_DATASTORE_ID,
            "--filter",
            period_filter(start_ms, end_ms),
            "--page-size",
            str(page_size),
        ]
        if not probe:
            command.extend(
                [
                    "--all-pages",
                    "--consistency-passes",
                    "2",
                    "--max-items",
                    "10000",
                ]
            )
        command.extend(["--format", "summary"])
        for field in SAFE_FIELDS:
            command.extend(["--field", field])
        try:
            result = subprocess.run(
                command,
                cwd=self.config.datadog_script.parents[1],
                check=False,
                capture_output=True,
                text=True,
                timeout=max(300, self.config.timeout * 10),
            )
        except FileNotFoundError as exc:
            raise ConfigError("找不到 uv，无法调用 datadog skill") from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Datadog Intercom 数据读取超时") from exc
        if result.returncode:
            if result.returncode == 2:
                raise ConfigError("Datadog Intercom 数据源配置不可用")
            if result.returncode == 3:
                raise AuthError("Datadog Intercom 数据源鉴权或权限不足")
            if result.returncode == 5:
                raise TimeoutError("Datadog Intercom 数据读取超时")
            raise BusinessError("Datadog Intercom 数据读取失败")
        try:
            payload = json.loads(result.stdout)
        except ValueError as exc:
            raise BusinessError("Datadog skill 返回了无效 JSON") from exc
        if not isinstance(payload, dict):
            raise BusinessError("Datadog skill 返回了无效 envelope")
        return payload


class FixtureTransport:
    def __init__(self, path):
        self.path = Path(path)

    def fetch_items(self, _start_ms, _end_ms, *, probe=False):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"无法读取 Intercom fixture：{self.path}") from exc
        if not isinstance(payload, dict):
            raise ConfigError("Intercom fixture 必须是 JSON object")
        fixture_result = payload.get("result")
        if (
            probe
            and isinstance(fixture_result, dict)
            and isinstance(fixture_result.get("items"), list)
        ):
            payload = dict(payload)
            payload["result"] = dict(payload["result"])
            payload["result"]["items"] = payload["result"]["items"][:20]
            payload["result"]["returned"] = len(payload["result"]["items"])
        return payload


def _text(value, field, *, required=False, limit=500):
    if value is None:
        if required:
            raise BusinessError(f"Intercom 数据缺少 {field}")
        return ""
    if not isinstance(value, str):
        raise BusinessError(f"Intercom 字段类型无效：{field}")
    normalized = value.strip()
    if required and not normalized:
        raise BusinessError(f"Intercom 数据缺少 {field}")
    return EMAIL_PATTERN.sub("[EMAIL]", normalized)[:limit]


def _timestamp(value, field, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise BusinessError(f"Intercom 时间字段无效：{field}")
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise BusinessError(f"Intercom 时间字段无效：{field}") from exc


def _normalize_item(item, start_ms, end_ms):
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        raise BusinessError("Datadog Intercom item 结构无效")
    value = item.get("value")
    if not isinstance(value, dict):
        raise BusinessError("Datadog Intercom value 结构无效")
    leaked = FORBIDDEN_FIELDS.intersection(value)
    if leaked:
        raise BusinessError("Datadog Intercom 响应包含禁止落盘的隐私字段")
    unknown = set(value) - set(SAFE_FIELDS)
    if unknown:
        raise BusinessError("Datadog Intercom 响应包含未声明字段")
    created_ms = value.get("conversation_created_at")
    if (
        not isinstance(created_ms, int)
        or isinstance(created_ms, bool)
        or not start_ms <= created_ms < end_ms
    ):
        raise BusinessError("Intercom 记录超出请求周期或时间字段无效")
    stable_id = hashlib.sha256(item["id"].encode("utf-8")).hexdigest()[:24]
    return {
        "schemaVersion": 1,
        "evidenceId": f"intercom:{stable_id}",
        "sourceKey": "intercom",
        "sourceObjectId": stable_id,
        "objectType": "feedback",
        "createdAt": _timestamp(created_ms, "conversation_created_at", required=True),
        "updatedAt": _timestamp(
            value.get("conversation_updated_at"),
            "conversation_updated_at",
        ),
        "requirement": _text(value.get("requirement"), "requirement", required=True),
        "domain": _text(value.get("domain"), "domain", limit=200),
        "feedbackType": _text(value.get("type"), "type", limit=200),
        "sentiment": _text(value.get("sentiment"), "sentiment", limit=100),
        "squad": _text(value.get("squad"), "squad", limit=200),
        "businessType": _text(value.get("business_type"), "business_type", limit=200),
        "leadsBusinessType": _text(
            value.get("leads_business_type"), "leads_business_type", limit=200
        ),
        "role": _text(value.get("role"), "role", limit=200),
        "tier": _text(value.get("tier"), "tier", limit=100),
        "enterprise": _text(value.get("enterprise"), "enterprise", limit=100),
        "stripePlan": _text(value.get("stripe_plan"), "stripe_plan", limit=200),
        "jira": _text(value.get("jira"), "jira", limit=300),
        "sourceUrl": INTERCOM_DATASTORE_URL,
    }


class IntercomCollector:
    def __init__(self, transport):
        self.transport = transport

    def collect(self, start: date, end: date, *, probe=False):
        start_ms, end_ms = period_millis(start, end)
        envelope = self.transport.fetch_items(start_ms, end_ms, probe=probe)
        if not isinstance(envelope, dict) or envelope.get("ok") is not True:
            raise BusinessError("Datadog Intercom 响应 envelope 无效")
        expected_target = {
            "kind": "actions_datastore_items",
            "datastore_id": DEFAULT_INTERCOM_DATASTORE_ID,
            "filter": period_filter(start_ms, end_ms),
            "item_key": None,
            "sort": None,
            "fields": list(SAFE_FIELDS),
        }
        if (
            envelope.get("schema_version") != 2
            or envelope.get("command") != "list-datastore-items"
            or envelope.get("target") != expected_target
        ):
            raise BusinessError("Datadog Intercom 响应合同不匹配")
        result = envelope.get("result")
        meta = envelope.get("meta")
        pagination = meta.get("pagination") if isinstance(meta, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise BusinessError("Datadog Intercom 响应缺少 items")
        if not isinstance(pagination, dict):
            raise BusinessError("Datadog Intercom 响应缺少分页元数据")
        expected_completion = {"complete", "partial"} if probe else {"complete"}
        if pagination.get("completion") not in expected_completion:
            raise BusinessError("Datadog Intercom 数据分页不完整")
        verification = envelope.get("verification")
        if not probe and (
            not isinstance(verification, dict)
            or verification.get("mode") != "converged-read"
            or verification.get("matched") is not True
            or not isinstance(verification.get("passes"), int)
            or isinstance(verification.get("passes"), bool)
            or verification["passes"] < 2
        ):
            raise BusinessError("Datadog Intercom 完整采集缺少一致性验证")
        evidence = [
            _normalize_item(item, start_ms, end_ms) for item in result["items"]
        ]
        returned = result.get("returned")
        if not isinstance(returned, int) or isinstance(returned, bool):
            raise BusinessError("Datadog Intercom 返回数量无效")
        if returned != len(evidence):
            raise BusinessError("Datadog Intercom 返回数量不一致")
        pagination_returned = pagination.get("returned")
        total = pagination.get("total")
        if (
            pagination.get("start") != 0
            or pagination_returned != returned
            or not isinstance(total, int)
            or isinstance(total, bool)
            or (not probe and total != returned)
            or (not probe and pagination.get("has_more") is not False)
            or (not probe and pagination.get("next") is not None)
        ):
            raise BusinessError("Datadog Intercom 分页数量或终态不一致")
        return {
            "observed": len(evidence),
            "evidence": evidence,
            "reportRows": [],
            "period": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "startMs": start_ms,
                "endExclusiveMs": end_ms,
            },
        }
