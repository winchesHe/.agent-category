from __future__ import annotations

import json
import re
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .errors import AuthError, BusinessError, ConfigError, TimeoutError

SHANGHAI = ZoneInfo("Asia/Shanghai")
JIRA_PROJECT = "CS"
FEATURE_REQUEST_TYPE = "Feature Request"
DESIGN_PROJECT = "DES"
DESIGN_ISSUE_TYPE = "Design Issue"
JIRA_SELECTION_RULE_VERSION = "jira-grooming-journey-v2"
JIRA_PRIVACY_POLICY = "jira-safe-v1"
JIRA_PAGE_SIZE = 100
JIRA_MAX_ISSUES = 10000
JIRA_SEARCH_FIELDS = (
    "summary",
    "status",
    "created",
    "issuetype",
    "issuelinks",
    "components",
    "customfield_10089",
)
BUSINESS_CATEGORIES = (
    "scheduling",
    "fulfillment",
    "communication",
    "management",
    "payment",
    "van-staff-shift-management",
    "others",
)
GROOMING_TERM_PATTERN = re.compile(r"\b(?:grooming|groomer(?:'s|s)?)\b", re.IGNORECASE)
GROOMING_EXCLUSION_PATTERN = re.compile(
    r"\b(?:daycare|boarding|kennel|training)\b", re.IGNORECASE
)
SHARED_COMPONENT_PATTERNS = (
    "appointment",
    "booking",
    "calendar",
    "client/pet/leads",
    "communication",
    "message",
    "notification",
    "payment",
    "payroll",
    "staff",
    "shift",
    "van",
)
CLASSIFICATION_PATTERNS = (
    (
        "van-staff-shift-management",
        ("van", "staff", "shift", "payroll", "time card", "clock in", "clock-in"),
    ),
    (
        "payment",
        ("payment", "payments", "tip", "tax", "invoice", "refund", "checkout"),
    ),
    (
        "communication",
        (
            "communication",
            "message",
            "sms",
            "text",
            "email",
            "reminder",
            "notification",
        ),
    ),
    (
        "fulfillment",
        (
            "add-on",
            "add on",
            "package",
            "breed",
            "service eligibility",
            "service duration",
        ),
    ),
    (
        "scheduling",
        (
            "appointment",
            "booking",
            "calendar",
            "waitlist",
            "availability",
            "capacity",
            "reschedule",
        ),
    ),
    (
        "management",
        ("agreement", "client", "pet", "report", "setting", "permission", "membership"),
    ),
)
EMAIL_PATTERN = re.compile(
    r"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
    r"(?![A-Z0-9._%+-])",
    re.IGNORECASE,
)
ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$")


def _contains_term(text: str, term: str) -> bool:
    """按完整英文词或短语匹配，避免 text/context、van/advance 等子串误判。"""
    suffix = r"(?:['’]s|s|es)?" if term[-1].isalnum() else ""
    pattern = rf"(?<![0-9a-z]){re.escape(term)}{suffix}(?![0-9a-z])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def build_jql(start: date, end: date, _squad: str) -> str:
    # Jira 的裸日期按调用账号时区解释。查询前后各扩一天，再按上海时间本地精确过滤，
    # 避免账号时区变化导致自然周边界漏数。
    query_start = start - timedelta(days=1)
    query_end_exclusive = end + timedelta(days=2)
    return (
        f"project = {JIRA_PROJECT} "
        f'AND created >= "{query_start.isoformat()}" '
        f'AND created < "{query_end_exclusive.isoformat()}" '
        "ORDER BY created DESC"
    )


def _components(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BusinessError("Jira components 结构无效")
    normalized = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BusinessError("Jira component 无效")
        normalized.append(_required_text(item, "component", limit=200))
    return normalized


def _scope_decision(
    *, summary: str, issue_squad: str, components: list[str], squad: str
):
    configured_squad = squad.strip().casefold()
    squad_match = issue_squad.casefold() == configured_squad
    grooming_scope = configured_squad == "grooming"
    semantic_match = grooming_scope and bool(GROOMING_TERM_PATTERN.search(summary))
    combined_components = " ".join(components).casefold()
    weak_components = (
        sorted(
            pattern
            for pattern in SHARED_COMPONENT_PATTERNS
            if _contains_term(combined_components, pattern)
        )
        if grooming_scope
        else []
    )
    strong_reasons = []
    if squad_match:
        strong_reasons.append("squad_exact")
    if semantic_match:
        strong_reasons.append("grooming_semantic")
    excluded_service = grooming_scope and GROOMING_EXCLUSION_PATTERN.search(summary)
    if excluded_service and strong_reasons:
        return "review", [*strong_reasons, "conflict:non_grooming_service"]
    if excluded_service:
        return "excluded", ["non_grooming_service"]
    if strong_reasons:
        return "selected", strong_reasons
    if weak_components:
        return "review", [f"shared_component:{value}" for value in weak_components]
    return "excluded", ["insufficient_grooming_evidence"]


def _business_classification(summary: str, components: list[str]):
    text = f"{summary} {' '.join(components)}".casefold()
    matches = [
        category
        for category, patterns in CLASSIFICATION_PATTERNS
        if any(_contains_term(text, pattern) for pattern in patterns)
    ]
    if not matches:
        return "others", [], "low"
    return matches[0], matches[1:], "high" if len(matches) == 1 else "medium"


def _period_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(start, time.min, tzinfo=SHANGHAI),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=SHANGHAI),
    )


def _timestamp(value, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BusinessError(f"Jira 数据缺少 {field}")
    normalized = value.strip().replace("Z", "+00:00")
    if re.search(r"[+-][0-9]{4}$", normalized):
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise BusinessError(f"Jira 时间字段无效：{field}") from exc
    if parsed.tzinfo is None:
        raise BusinessError(f"Jira 时间字段缺少时区：{field}")
    return parsed


def _required_text(value, field: str, *, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BusinessError(f"Jira 数据缺少 {field}")
    return EMAIL_PATTERN.sub("[EMAIL]", value.strip())[:limit]


def _issue_key(value, field: str) -> str:
    if not isinstance(value, str) or not ISSUE_KEY_PATTERN.fullmatch(value):
        raise BusinessError(f"Jira issue key 无效：{field}")
    return value


def _design_links(issue: dict) -> list[dict]:
    raw_links = issue.get("links")
    if not isinstance(raw_links, list):
        raise BusinessError("Jira search 结果缺少结构化 links")
    selected = {}
    for link in raw_links:
        if not isinstance(link, dict):
            raise BusinessError("Jira link 结构无效")
        project_key = str(link.get("project_key") or "").strip()
        if project_key != DESIGN_PROJECT:
            continue
        issue_type = str(link.get("issue_type") or "").strip()
        if not issue_type:
            raise BusinessError("Jira DES 关联单缺少 issue type")
        if issue_type != DESIGN_ISSUE_TYPE:
            continue
        key = _issue_key(link.get("key"), "link.key")
        selected[key] = {
            "key": key,
            "projectKey": DESIGN_PROJECT,
            "issueType": DESIGN_ISSUE_TYPE,
            "status": str(link.get("status") or "").strip(),
            "linkType": str(link.get("type") or "").strip(),
            "direction": str(link.get("direction") or "").strip(),
            "relationship": str(link.get("relationship") or "").strip(),
            "url": f"https://moego.atlassian.net/browse/{key}",
        }
    return [selected[key] for key in sorted(selected)]


def _normalize_issue(
    issue: dict,
    *,
    squad: str,
    start_at: datetime,
    end_exclusive_at: datetime,
) -> tuple[dict | None, bool]:
    if not isinstance(issue, dict):
        raise BusinessError("Jira search issue 结构无效")
    key = _issue_key(issue.get("key"), "issue.key")
    if not key.startswith(f"{JIRA_PROJECT}-"):
        raise BusinessError("Jira search 返回了非 CS 工单")
    created = _timestamp(issue.get("created"), "created")
    created_shanghai = created.astimezone(SHANGHAI)
    if not start_at <= created_shanghai < end_exclusive_at:
        return None, False
    issue_squad = str(issue.get("squad") or "").strip()
    if issue_squad:
        issue_squad = _required_text(issue_squad, "squad", limit=200)
    issue_type = _required_text(issue.get("issue_type"), "issue_type", limit=200)
    summary = _required_text(issue.get("summary"), "summary")
    components = _components(issue.get("components"))
    design_links = _design_links(issue)
    feedback_kinds = []
    if issue_type == FEATURE_REQUEST_TYPE:
        feedback_kinds.append("feature_request")
    if design_links:
        feedback_kinds.append("design_linked")
    if not feedback_kinds:
        return None, True
    scope_decision, scope_reasons = _scope_decision(
        summary=summary,
        issue_squad=issue_squad,
        components=components,
        squad=squad,
    )
    business_category, auxiliary_categories, classification_confidence = (
        _business_classification(summary, components)
    )
    normalized = {
        "schemaVersion": 1,
        "evidenceId": f"jira:{key}",
        "sourceKey": "jira",
        "sourceObjectId": key,
        "objectType": "feedback",
        "createdAt": created.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "title": summary,
        "squad": issue_squad,
        "components": components,
        "issueType": issue_type,
        "status": _required_text(issue.get("status"), "status", limit=200),
        "feedbackKinds": feedback_kinds,
        "scopeDecision": scope_decision,
        "scopeReasons": scope_reasons,
        "businessCategory": business_category,
        "auxiliaryCategories": auxiliary_categories,
        "classificationConfidence": classification_confidence,
        "relatedTickets": design_links,
        "sourceUrl": f"https://moego.atlassian.net/browse/{key}",
    }
    return (
        normalized,
        True,
    )


class JiraTransport:
    def __init__(self, config):
        self.config = config

    def search(self, jql: str, fields: tuple[str, ...], page_token: str | None):
        if not self.config.jira_script:
            raise ConfigError("找不到 jira skill 入口")
        command = [
            "uv",
            "run",
            "--script",
            str(self.config.jira_script),
            "search",
            jql,
            "--limit",
            str(JIRA_PAGE_SIZE),
            "--fields",
            ",".join(fields),
            "--format",
            "json",
        ]
        if page_token:
            command.extend(["--page-token", page_token])
        try:
            result = subprocess.run(
                command,
                cwd=self.config.jira_script.parents[1],
                check=False,
                capture_output=True,
                text=True,
                timeout=max(120, self.config.timeout * 4),
            )
        except FileNotFoundError as exc:
            raise ConfigError("找不到 uv，无法调用 jira skill") from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Jira 反馈读取超时") from exc
        if result.returncode:
            if result.returncode == 2:
                raise ConfigError("Jira 数据源配置不可用")
            if result.returncode == 3:
                raise AuthError("Jira 数据源鉴权或权限不足")
            if result.returncode == 5:
                raise TimeoutError("Jira 反馈读取超时")
            raise BusinessError("Jira 反馈读取失败")
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise BusinessError("jira skill 返回了无效 JSON") from exc


class FixtureTransport:
    def __init__(self, path):
        self.path = Path(path)
        self._index = 0
        self._expected_token = None

    def search(self, _jql: str, _fields: tuple[str, ...], page_token: str | None):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"无法读取 Jira fixture：{self.path}") from exc
        pages = payload.get("pages") if isinstance(payload, dict) else None
        if not isinstance(pages, list):
            return payload
        if page_token != self._expected_token or self._index >= len(pages):
            raise ConfigError("Jira fixture 分页 token 不匹配")
        page = pages[self._index]
        self._index += 1
        if not isinstance(page, dict):
            raise ConfigError("Jira fixture page 必须是 JSON object")
        self._expected_token = page.get("next_page_token")
        return page


class JiraCollector:
    def __init__(self, transport):
        self.transport = transport

    def collect(self, start: date, end: date, squad: str):
        configured_squad = str(squad or "").strip()
        jql = build_jql(start, end, configured_squad)
        page_token = None
        seen_tokens = set()
        seen_keys = set()
        issues = []
        while True:
            envelope = self.transport.search(jql, JIRA_SEARCH_FIELDS, page_token)
            if (
                not isinstance(envelope, dict)
                or envelope.get("ok") is not True
                or envelope.get("schema_version") != 1
                or envelope.get("command") != "search"
                or envelope.get("jql") != jql
                or envelope.get("fields") != list(JIRA_SEARCH_FIELDS)
            ):
                raise BusinessError("Jira search 响应合同不匹配")
            page_issues = envelope.get("issues")
            if not isinstance(page_issues, list):
                raise BusinessError("Jira search 响应缺少 issues")
            count = envelope.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count != len(page_issues):
                raise BusinessError("Jira search 返回数量不一致")
            for issue in page_issues:
                if not isinstance(issue, dict):
                    raise BusinessError("Jira search issue 结构无效")
                key = _issue_key(issue.get("key"), "issue.key")
                if key in seen_keys:
                    raise BusinessError("Jira search 分页返回重复工单")
                seen_keys.add(key)
                issues.append(issue)
            if len(issues) > JIRA_MAX_ISSUES:
                raise BusinessError("Jira search 超过 10000 条安全上限")
            is_last = envelope.get("is_last")
            if not isinstance(is_last, bool):
                raise BusinessError("Jira search 缺少完整分页状态")
            next_token = envelope.get("next_page_token")
            if is_last:
                if next_token:
                    raise BusinessError("Jira search 终页仍返回下一页 token")
                break
            if not isinstance(next_token, str) or not next_token:
                raise BusinessError("Jira search 分页未完成")
            if next_token in seen_tokens:
                raise BusinessError("Jira search 分页 token 循环")
            seen_tokens.add(next_token)
            page_token = next_token

        start_at, end_exclusive_at = _period_bounds(start, end)
        evidence = []
        review_rows = []
        excluded_rows = []
        in_period = 0
        feedback_candidates = 0
        for issue in issues:
            normalized, is_in_period = _normalize_issue(
                issue,
                squad=configured_squad,
                start_at=start_at,
                end_exclusive_at=end_exclusive_at,
            )
            if is_in_period:
                in_period += 1
            if normalized:
                feedback_candidates += 1
                if normalized["scopeDecision"] == "selected":
                    evidence.append(normalized)
                elif normalized["scopeDecision"] == "review":
                    review_rows.append(normalized)
                else:
                    excluded_rows.append(normalized)
        evidence.sort(key=lambda item: (item["createdAt"], item["sourceObjectId"]), reverse=True)
        review_rows.sort(
            key=lambda item: (item["createdAt"], item["sourceObjectId"]), reverse=True
        )
        excluded_rows.sort(
            key=lambda item: (item["createdAt"], item["sourceObjectId"]), reverse=True
        )
        return {
            "observed": len(issues),
            "inPeriod": in_period,
            "selected": len(evidence),
            "featureRequest": sum(
                "feature_request" in item["feedbackKinds"] for item in evidence
            ),
            "designLinked": sum(
                "design_linked" in item["feedbackKinds"] for item in evidence
            ),
            "feedbackCandidates": feedback_candidates,
            "manualReview": len(review_rows),
            "excludedScope": len(excluded_rows),
            "evidence": evidence,
            "reportRows": review_rows + excluded_rows,
            "period": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "timezone": "Asia/Shanghai",
            },
            "query": {
                "jql": jql,
                "fields": list(JIRA_SEARCH_FIELDS),
                "observed": len(issues),
                "inPeriod": in_period,
            },
        }
