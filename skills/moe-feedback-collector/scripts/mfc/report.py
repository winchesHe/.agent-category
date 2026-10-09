from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DEFAULT_MIN_VOTE
from .errors import BusinessError, ConfigError
from .jira import (
    BUSINESS_CATEGORIES,
    JIRA_PRIVACY_POLICY,
    JIRA_SEARCH_FIELDS,
    JIRA_SELECTION_RULE_VERSION,
    build_jql,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
QUICK_WIN_RULE_VERSION = "canny-qw-v2"
MANAGED_SOURCE_MARKER_VERSION = "MFC_MANAGED_SOURCE_V1"
CANNY_MANAGED_CHILD_MARKER = "由 Moe Feedback Collector 自动生成的 Canny 源数据，请勿手工编辑。"
INTERCOM_PUBLISH_RULE_VERSION = "intercom-squad-features-v1"
INTERCOM_MANAGED_CHILD_MARKER = "由 Moe Feedback Collector 自动生成，请勿手工编辑。"
JIRA_PUBLISH_RULE_VERSION = JIRA_SELECTION_RULE_VERSION
JIRA_MANAGED_CHILD_MARKER = "由 Moe Feedback Collector 自动生成，请勿手工编辑。"
FACEBOOK_PUBLISH_RULE_VERSION = "facebook-channel-summary-v1"
FACEBOOK_PRIVACY_POLICY = "facebook-slack-safe-v1"
INTERCOM_PUBLISH_TYPES = (
    ("feature_feedback", "功能反馈"),
    ("feature_request", "功能需求"),
)


def managed_source_ownership_marker(source, start, end):
    return (
        f"{MANAGED_SOURCE_MARKER_VERSION}|source={str(source).strip()}|"
        f"period={start.isoformat()}..{end.isoformat()}"
    )


def managed_source_run_marker(source, start, end, run_id):
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id or any(character in normalized_run_id for character in "|\r\n"):
        raise BusinessError("来源看板 runId 无效")
    return (
        managed_source_ownership_marker(source, start, end)
        + f"|runId={normalized_run_id}"
    )


def attach_managed_source_marker(content, marker):
    title_end = content.find("</title>")
    if title_end < 0:
        raise BusinessError("来源看板缺少 title，无法写入托管身份")
    insertion = title_end + len("</title>")
    managed = f'<p><span text-color="gray">{escape(marker)}</span></p>'
    return content[:insertion] + managed + content[insertion:]


def previous_week(today=None):
    current = today or datetime.now(SHANGHAI).date()
    monday = current - timedelta(days=current.weekday() + 7)
    return monday, monday + timedelta(days=6)


def _parse_month_value(value):
    try:
        parsed = datetime.strptime(str(value or ""), "%Y-%m")
    except ValueError as exc:
        raise ConfigError("月份必须使用 YYYY-MM") from exc
    return date(parsed.year, parsed.month, 1)


def month_week_intersection(month_value, day):
    month_start = _parse_month_value(month_value)
    month_end = date(
        month_start.year,
        month_start.month,
        monthrange(month_start.year, month_start.month)[1],
    )
    week_start = day - timedelta(days=day.weekday())
    week_end = week_start + timedelta(days=6)
    return max(month_start, week_start), min(month_end, week_end)


def parse_period(
    start_value,
    end_value,
    *,
    allow_partial_period=False,
    month_segment="",
):
    if not start_value and not end_value:
        return previous_week()
    if not start_value or not end_value:
        raise ConfigError("--period-start 与 --period-end 必须同时提供")
    try:
        start = date.fromisoformat(start_value)
        end = date.fromisoformat(end_value)
    except ValueError as exc:
        raise ConfigError("周报日期必须使用 YYYY-MM-DD") from exc
    if end < start:
        raise ConfigError("周报结束日期不能早于开始日期")
    duration_days = (end - start).days
    if month_segment:
        if allow_partial_period:
            raise ConfigError("--month-segment 不能与 --allow-partial-period 同时使用")
        expected_start, expected_end = month_week_intersection(month_segment, start)
        if start != expected_start or end != expected_end:
            raise ConfigError(
                "月度边界片段必须精确等于目标月与所在 ISO 周的交集"
            )
        return start, end
    if allow_partial_period:
        if start.weekday() != 0 or duration_days > 6:
            raise ConfigError("部分反馈周期必须从周一开始，且不能跨自然周")
    elif duration_days != 6:
        raise ConfigError("反馈周期必须正好为 7 天")
    return start, end


def _date_in_shanghai(value):
    if not value:
        return None
    normalized = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SHANGHAI).date()


def _feedback_type(item):
    return str(item.get("feedbackType") or "").strip().casefold()


def _load_json(path, label):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"无法读取{label}：{path}") from exc


def load_run(manifest_path, *, object_type="post"):
    manifest = _load_json(manifest_path, "采集 manifest")
    if not isinstance(manifest, dict):
        raise BusinessError("采集 manifest 结构无效")
    run_path = manifest.get("runArtifact")
    if not run_path:
        raise BusinessError("manifest 缺少 runArtifact")
    run = _load_json(run_path, "采集结果")
    if not isinstance(run, dict) or not isinstance(run.get("manifest"), dict):
        raise BusinessError("采集结果缺少内嵌 manifest")
    embedded_manifest = run["manifest"]
    required = {"runId", "sourceKey", "mode", "status", "fetchedCount"}
    if not required.issubset(embedded_manifest):
        raise BusinessError("采集结果 manifest 合同不完整")
    if any(manifest.get(key) != value for key, value in embedded_manifest.items()):
        raise BusinessError("外层 manifest 与采集结果不一致")
    if embedded_manifest.get("status") != "succeeded":
        raise BusinessError("采集结果状态不是 succeeded")
    raw_evidence = run.get("evidence")
    raw_report_rows = run.get("reportRows")
    if not isinstance(raw_evidence, list) or not all(
        isinstance(item, dict) for item in raw_evidence
    ):
        raise BusinessError("采集结果 evidence 结构无效")
    if not isinstance(raw_report_rows, list) or not all(
        isinstance(item, dict) for item in raw_report_rows
    ):
        raise BusinessError("采集结果 reportRows 结构无效")
    fetched_count = embedded_manifest.get("fetchedCount")
    if (
        not isinstance(fetched_count, int)
        or isinstance(fetched_count, bool)
        or fetched_count != len(raw_evidence)
    ):
        raise BusinessError("采集结果数量与 manifest 不一致")
    evidence = [
        item
        for item in raw_evidence
        if item.get("objectType") == object_type
    ]
    report_rows = [
        item
        for item in raw_report_rows
        if item.get("objectType") == object_type
    ]
    return manifest, evidence, report_rows


def load_facebook_run(manifest_path):
    manifest = _load_json(manifest_path, "Facebook 采集 manifest")
    if not isinstance(manifest, dict):
        raise BusinessError("Facebook 采集 manifest 结构无效")
    run_path = manifest.get("runArtifact")
    if not run_path:
        raise BusinessError("Facebook manifest 缺少 runArtifact")
    run = _load_json(run_path, "Facebook 采集结果")
    if not isinstance(run, dict) or not isinstance(run.get("manifest"), dict):
        raise BusinessError("Facebook 采集结果缺少内嵌 manifest")
    embedded = run["manifest"]
    if any(manifest.get(key) != value for key, value in embedded.items()):
        raise BusinessError("Facebook 外层 manifest 与采集结果不一致")
    evidence = run.get("evidence")
    report_rows = run.get("reportRows")
    if (
        not isinstance(evidence, list)
        or not all(isinstance(item, dict) for item in evidence)
        or not isinstance(report_rows, list)
        or not all(isinstance(item, dict) for item in report_rows)
    ):
        raise BusinessError("Facebook 采集结果 evidence 结构无效")
    if embedded.get("newCount") != len(evidence):
        raise BusinessError("Facebook evidence 数量与 manifest 不一致")
    return manifest, evidence, report_rows


def canny_manifest_period(manifest):
    period = manifest.get("period")
    if not isinstance(period, dict):
        raise BusinessError("Canny manifest 缺少采集周期")
    try:
        start = date.fromisoformat(str(period.get("start") or ""))
        end = date.fromisoformat(str(period.get("end") or ""))
    except ValueError as exc:
        raise BusinessError("Canny manifest 采集周期无效") from exc
    if end < start or (end - start).days > 6:
        raise BusinessError("Canny manifest 采集周期必须在同一自然周内")
    return start, end


def intercom_manifest_period(manifest):
    period = manifest.get("period")
    if not isinstance(period, dict):
        raise BusinessError("Intercom manifest 缺少采集周期")
    try:
        start = date.fromisoformat(str(period.get("start") or ""))
        end = date.fromisoformat(str(period.get("end") or ""))
    except ValueError as exc:
        raise BusinessError("Intercom manifest 采集周期无效") from exc
    if end < start or (end - start).days > 6:
        raise BusinessError("Intercom manifest 采集周期必须在同一自然周内")
    return start, end


def jira_manifest_period(manifest):
    period = manifest.get("period")
    if not isinstance(period, dict):
        raise BusinessError("Jira manifest 缺少采集周期")
    try:
        start = date.fromisoformat(str(period.get("start") or ""))
        end = date.fromisoformat(str(period.get("end") or ""))
    except ValueError as exc:
        raise BusinessError("Jira manifest 采集周期无效") from exc
    if end < start or (end - start).days > 6:
        raise BusinessError("Jira manifest 采集周期必须在同一自然周内")
    return start, end


def facebook_manifest_period(manifest):
    period = manifest.get("period")
    if not isinstance(period, dict):
        raise BusinessError("Facebook manifest 缺少采集周期")
    try:
        start = date.fromisoformat(str(period.get("start") or ""))
        end = date.fromisoformat(str(period.get("end") or ""))
    except ValueError as exc:
        raise BusinessError("Facebook manifest 采集周期无效") from exc
    if end < start or (end - start).days > 6:
        raise BusinessError("Facebook manifest 采集周期必须在同一自然周内")
    return start, end


def select_intercom_rows(manifest, feedback, squad, start, end):
    if manifest.get("sourceKey") != "intercom":
        raise BusinessError("manifest 数据源不是 Intercom")
    if manifest.get("mode") != "period":
        raise BusinessError("Intercom 仅允许发布 period 模式的完整采集结果")
    manifest_start, manifest_end = intercom_manifest_period(manifest)
    if (start, end) != (manifest_start, manifest_end):
        raise BusinessError("发布周期与 Intercom manifest 采集周期不一致")
    configured_squad = str(squad or "").strip()
    if not configured_squad:
        raise ConfigError("缺少 MFC_SQUAD，无法筛选团队反馈")

    period_rows = []
    for item in feedback:
        created = _date_in_shanghai(item.get("createdAt"))
        if not created or not start <= created <= end:
            raise BusinessError("Intercom evidence 超出 manifest 周期或时间字段无效")
        period_rows.append(item)

    squad_key = configured_squad.casefold()
    squad_rows = [
        item
        for item in period_rows
        if str(item.get("squad") or "").strip().casefold() == squad_key
    ]
    allowed_types = {value for value, _label in INTERCOM_PUBLISH_TYPES}
    selected = [item for item in squad_rows if _feedback_type(item) in allowed_types]
    by_type = {
        value: sum(1 for item in selected if _feedback_type(item) == value)
        for value, _label in INTERCOM_PUBLISH_TYPES
    }
    return selected, {
        "inputRows": len(period_rows),
        "squadRows": len(squad_rows),
        "selectedRows": len(selected),
        "excludedBySquad": len(period_rows) - len(squad_rows),
        "excludedByType": len(squad_rows) - len(selected),
        "featureFeedback": by_type["feature_feedback"],
        "featureRequest": by_type["feature_request"],
    }


def select_jira_rows(manifest, feedback, scope_rows, squad, start, end):
    if manifest.get("sourceKey") != "jira":
        raise BusinessError("manifest 数据源不是 Jira")
    if manifest.get("mode") != "period":
        raise BusinessError("Jira 仅允许发布 period 模式的完整采集结果")
    manifest_start, manifest_end = jira_manifest_period(manifest)
    if (start, end) != (manifest_start, manifest_end):
        raise BusinessError("发布周期与 Jira manifest 采集周期不一致")
    configured_squad = str(squad or "").strip()
    if not configured_squad:
        raise ConfigError("缺少 MFC_SQUAD，无法发布 Jira 团队反馈")
    manifest_squad = str(manifest.get("squad") or "").strip()
    if manifest_squad.casefold() != configured_squad.casefold():
        raise BusinessError("Jira manifest Squad 与当前 MFC_SQUAD 不一致")
    if (
        manifest.get("privacyPolicy") != JIRA_PRIVACY_POLICY
        or manifest.get("selectionRule") != JIRA_PUBLISH_RULE_VERSION
    ):
        raise BusinessError("Jira manifest 规则或隐私合同不匹配")
    query = manifest.get("query")
    if (
        not isinstance(query, dict)
        or query.get("jql") != build_jql(start, end, configured_squad)
        or query.get("fields") != list(JIRA_SEARCH_FIELDS)
    ):
        raise BusinessError("Jira manifest 查询合同不匹配")

    allowed_kinds = {"feature_request", "design_linked"}
    selected = []
    source_keys = set()
    for item in feedback:
        created = _date_in_shanghai(item.get("createdAt"))
        if not created or not start <= created <= end:
            raise BusinessError("Jira evidence 超出 manifest 周期或时间字段无效")
        source_key = str(item.get("sourceObjectId") or "")
        if item.get("sourceKey") != "jira" or not source_key.startswith("CS-"):
            raise BusinessError("Jira evidence 来源身份无效")
        if source_key in source_keys:
            raise BusinessError("Jira evidence 包含重复 CS 工单")
        source_keys.add(source_key)
        if item.get("scopeDecision") != "selected":
            raise BusinessError("Jira evidence 范围判定无效")
        category = item.get("businessCategory")
        auxiliary = item.get("auxiliaryCategories")
        scope_reasons = item.get("scopeReasons")
        components = item.get("components")
        if (
            category not in BUSINESS_CATEGORIES
            or not isinstance(auxiliary, list)
            or any(
                value not in BUSINESS_CATEGORIES or value == category
                for value in auxiliary
            )
            or item.get("classificationConfidence") not in {"high", "medium", "low"}
            or not isinstance(scope_reasons, list)
            or not scope_reasons
            or not isinstance(components, list)
            or any(not isinstance(value, str) for value in components)
        ):
            raise BusinessError("Jira evidence 业务分类无效")
        kinds = item.get("feedbackKinds")
        if (
            not isinstance(kinds, list)
            or not kinds
            or any(kind not in allowed_kinds for kind in kinds)
            or len(kinds) != len(set(kinds))
        ):
            raise BusinessError("Jira evidence feedbackKinds 无效")
        if "feature_request" in kinds and item.get("issueType") != "Feature Request":
            raise BusinessError("Jira Feature Request evidence 类型不匹配")
        related_tickets = item.get("relatedTickets")
        if not isinstance(related_tickets, list):
            raise BusinessError("Jira evidence 关联单结构无效")
        if "design_linked" in kinds:
            valid_design_links = related_tickets and all(
                isinstance(ticket, dict)
                and ticket.get("projectKey") == "DES"
                and ticket.get("issueType") == "Design Issue"
                for ticket in related_tickets
            )
            if not valid_design_links:
                raise BusinessError("Jira Design evidence 关联单合同不匹配")
        elif related_tickets:
            raise BusinessError("Jira evidence 分类与关联单不一致")
        selected.append(item)

    scope_keys = set()
    review_rows = []
    excluded_rows = []
    for item in scope_rows:
        source_key = str(item.get("sourceObjectId") or "")
        created = _date_in_shanghai(item.get("createdAt"))
        if not created or not start <= created <= end:
            raise BusinessError("Jira 范围审计项超出 manifest 周期或时间字段无效")
        scope_decision = item.get("scopeDecision")
        if (
            item.get("sourceKey") != "jira"
            or not source_key.startswith("CS-")
            or scope_decision not in {"review", "excluded"}
            or source_key in source_keys
            or source_key in scope_keys
            or not isinstance(item.get("scopeReasons"), list)
            or not item.get("scopeReasons")
        ):
            raise BusinessError("Jira 范围审计项身份无效")
        scope_keys.add(source_key)
        if scope_decision == "review":
            review_rows.append(item)
        else:
            excluded_rows.append(item)

    observed = manifest.get("observedCount")
    in_period = manifest.get("inPeriodCount")
    feedback_candidate_count = manifest.get("feedbackCandidateCount")
    manual_review_count = manifest.get("manualReviewCount")
    excluded_scope_count = manifest.get("excludedScopeCount")
    if (
        not isinstance(observed, int)
        or isinstance(observed, bool)
        or not isinstance(in_period, int)
        or isinstance(in_period, bool)
        or observed < in_period
        or in_period < len(selected) + len(scope_rows)
    ):
        raise BusinessError("Jira manifest 查询计数无效")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (
            feedback_candidate_count,
            manual_review_count,
            excluded_scope_count,
        )
    ):
        raise BusinessError("Jira manifest 范围计数无效")
    if (
        feedback_candidate_count != len(selected) + len(scope_rows)
        or manual_review_count != len(review_rows)
        or excluded_scope_count != len(excluded_rows)
    ):
        raise BusinessError("Jira manifest 范围计数无效")
    return (
        selected,
        review_rows,
        excluded_rows,
        {
            "queryRows": observed,
            "inPeriodRows": in_period,
            "selectedRows": len(selected),
            "feedbackCandidates": feedback_candidate_count,
            "manualReview": len(review_rows),
            "excludedScope": len(excluded_rows),
            "featureRequest": sum(
                "feature_request" in item["feedbackKinds"] for item in selected
            ),
            "designLinked": sum(
                "design_linked" in item["feedbackKinds"] for item in selected
            ),
            "businessCategories": {
                category: sum(
                    item.get("businessCategory") == category for item in selected
                )
                for category in BUSINESS_CATEGORIES
            },
        },
    )


def select_facebook_rows(manifest, feedback, domain, start, end):
    if manifest.get("sourceKey") != "facebook":
        raise BusinessError("manifest 数据源不是 Facebook")
    if manifest.get("mode") != "period" or manifest.get("status") != "succeeded":
        raise BusinessError("Facebook 仅允许发布 period 模式的完整采集结果")
    if facebook_manifest_period(manifest) != (start, end):
        raise BusinessError("发布周期与 Facebook manifest 采集周期不一致")
    configured_domain = str(domain or "").strip()
    if not configured_domain:
        raise ConfigError("缺少 MFC_DOMAIN，无法发布 Facebook 频道反馈")
    if str(manifest.get("domain") or "").strip().casefold() != configured_domain.casefold():
        raise BusinessError("Facebook manifest Domain 与当前 MFC_DOMAIN 不一致")
    if (
        manifest.get("coverage") != "channel-summary"
        or manifest.get("privacyPolicy") != FACEBOOK_PRIVACY_POLICY
    ):
        raise BusinessError("Facebook manifest 覆盖或隐私合同不匹配")
    allowed_types = {
        "group_post",
        "campaign_comment_summary",
        "group_comment_summary",
    }
    feed_counts = {}
    evidence_ids = set()
    for item in feedback:
        evidence_id = str(item.get("evidenceId") or "")
        created = _date_in_shanghai(item.get("createdAt"))
        feed_type = str(item.get("feedType") or "")
        if not evidence_id or evidence_id in evidence_ids:
            raise BusinessError("Facebook evidence ID 缺失或重复")
        evidence_ids.add(evidence_id)
        if not created or not start <= created <= end:
            raise BusinessError("Facebook evidence 超出 manifest 周期或时间字段无效")
        if (
            item.get("sourceKey") != "facebook"
            or item.get("coverage") != "channel-summary"
            or str(item.get("domain") or "").strip().casefold()
            != configured_domain.casefold()
            or feed_type not in allowed_types
        ):
            raise BusinessError("Facebook evidence 来源、Domain 或类型合同无效")
        feed_counts[feed_type] = feed_counts.get(feed_type, 0) + 1
    fetched_count = manifest.get("fetchedCount")
    if not isinstance(fetched_count, int) or isinstance(fetched_count, bool):
        raise BusinessError("Facebook manifest 采集计数无效")
    return feedback, {
        "observedRows": fetched_count,
        "selectedRows": len(feedback),
        "feedCounts": feed_counts,
    }


def load_quick_win_review(path, candidates):
    payload = _load_json(path, "Quick Win 复筛结果")
    items = payload.get("decisions", []) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ConfigError("Quick Win 复筛结果必须是数组或 decisions 数组")
    candidate_ids = {item.get("sourceObjectId") for item in candidates}
    selected = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("selected"):
            continue
        source_id = str(item.get("sourceObjectId") or "")
        reason = str(item.get("reason") or "").strip()
        if source_id not in candidate_ids:
            raise ConfigError(f"Quick Win 复筛包含非初筛候选：{source_id}")
        if not reason:
            raise ConfigError(f"Quick Win 复筛缺少判断理由：{source_id}")
        selected[source_id] = reason
    return selected


def choose_report_rows(manifest, posts, _report_rows, start, end):
    if canny_manifest_period(manifest) != (start, end):
        raise BusinessError("发布周期与 Canny manifest 采集周期不一致")
    return [
        {**item, "isNew": True, "changeKind": "new"}
        for item in posts
        if (created := _date_in_shanghai(item.get("createdAt")))
        and start <= created <= end
    ]


def apply_quick_win_rule(rows):
    normalized = []
    for item in rows:
        signals = []
        vote_count = int(item.get("voteCount") or 0)
        vote_delta = item.get("voteDelta")
        comment_delta = item.get("commentDelta")
        if vote_count >= DEFAULT_MIN_VOTE:
            signals.append(f"Vote {vote_count} ≥ {DEFAULT_MIN_VOTE}")
        if vote_delta is not None and vote_delta >= 5:
            signals.append(f"本期 Vote +{vote_delta}")
        if comment_delta is not None and comment_delta >= 3:
            signals.append(f"本期评论 +{comment_delta}")
        normalized.append(
            {
                **item,
                "quickWinPrefilter": bool(signals),
                "quickWinSignals": signals,
            }
        )
    return normalized


def report_titles(start, end):
    iso_year, iso_week, _ = start.isocalendar()
    week_title = (
        f"{iso_year}-W{iso_week:02d}｜{start:%m.%d}–{end:%m.%d}｜Canny 用户反馈"
    )
    return str(iso_year), f"{start:%m}", week_title


def intercom_report_titles(start, end, squad):
    iso_year, iso_week, _ = start.isocalendar()
    week_title = (
        f"{iso_year}-W{iso_week:02d}｜{start:%m.%d}–{end:%m.%d}｜"
        f"Intercom 用户反馈｜{str(squad).strip()}"
    )
    return str(iso_year), f"{start:%m}", week_title


def jira_report_titles(start, end, squad):
    iso_year, iso_week, _ = start.isocalendar()
    week_title = (
        f"{iso_year}-W{iso_week:02d}｜{start:%m.%d}–{end:%m.%d}｜"
        f"Jira CS 反馈｜{str(squad).strip()}"
    )
    return str(iso_year), f"{start:%m}", week_title


def facebook_report_titles(start, end, domain):
    iso_year, iso_week, _ = start.isocalendar()
    week_title = (
        f"{iso_year}-W{iso_week:02d}｜{start:%m.%d}–{end:%m.%d}｜"
        f"Facebook Community｜{str(domain).strip()}"
    )
    return str(iso_year), f"{start:%m}", week_title


def _change_text(item):
    if item.get("changeKind") == "baseline":
        return "初始基线"
    if item.get("isNew"):
        return "本周新增"
    changes = []
    vote_delta = item.get("voteDelta")
    comment_delta = item.get("commentDelta")
    if vote_delta:
        changes.append(f"Vote {vote_delta:+d}")
    if comment_delta:
        changes.append(f"评论 {comment_delta:+d}")
    if "status" in item.get("changedFields", []):
        changes.append("状态变化")
    if any(
        field in item.get("changedFields", [])
        for field in ("title", "detailsHash")
    ):
        changes.append("内容变化")
    return "；".join(changes) or "—"


def _display_date(value):
    parsed = _date_in_shanghai(value)
    return parsed.isoformat() if parsed else "—"


def _rich_text(value):
    return escape(str(value or "")).replace("\n", "<br/>")


def _source_table(rows):
    if not rows:
        return "<p>本期无源数据。</p>"
    body = []
    for item in sorted(
        rows,
        key=lambda value: (
            _date_in_shanghai(value.get("createdAt")) or date.min,
            int(value.get("voteCount") or 0),
        ),
        reverse=True,
    ):
        url = escape(str(item.get("sourceUrl") or ""), quote=True)
        body.append(
            "<tr>"
            f"<td>{escape(str(item.get('title') or ''))}</td>"
            f"<td>{int(item.get('voteCount') or 0)}</td>"
            f"<td>{int(item.get('commentCount') or 0)}</td>"
            f"<td>{escape(_change_text(item))}</td>"
            f"<td>{escape(str(item.get('status') or '—'))}</td>"
            f"<td>{_display_date(item.get('createdAt'))}</td>"
            f"<td><a href=\"{url}\">原文</a></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th background-color=\"light-gray\">标题</th>"
        "<th background-color=\"light-gray\">Vote</th>"
        "<th background-color=\"light-gray\">评论</th>"
        "<th background-color=\"light-gray\">本期变化</th>"
        "<th background-color=\"light-gray\">状态</th>"
        "<th background-color=\"light-gray\">发布时间</th>"
        "<th background-color=\"light-gray\">原文</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _quick_win_table(rows, decisions):
    selected = [
        item for item in rows if item.get("sourceObjectId") in decisions
    ]
    if not selected:
        return "<p>本期无 Quick Win 候选。</p>"
    body = []
    for item in sorted(selected, key=lambda value: int(value.get("voteCount") or 0), reverse=True):
        source_id = item.get("sourceObjectId")
        url = escape(str(item.get("sourceUrl") or ""), quote=True)
        body.append(
            "<tr>"
            f"<td>{escape(str(item.get('title') or ''))}</td>"
            f"<td>{int(item.get('voteCount') or 0)}</td>"
            f"<td>{escape(decisions[source_id])}</td>"
            f"<td>{escape(str(item.get('status') or '—'))}</td>"
            f"<td><a href=\"{url}\">原文</a></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th background-color=\"light-gray\">标题</th>"
        "<th background-color=\"light-gray\">Vote</th>"
        "<th background-color=\"light-gray\">入选理由</th>"
        "<th background-color=\"light-gray\">状态</th>"
        "<th background-color=\"light-gray\">原文</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _intercom_table(rows):
    if not rows:
        return "<p>本期无符合条件的数据。</p>"
    body = []
    for item in sorted(
        rows,
        key=lambda value: _date_in_shanghai(value.get("createdAt")) or date.min,
        reverse=True,
    ):
        body.append(
            "<tr>"
            f"<td>{_rich_text(item.get('requirement'))}</td>"
            f"<td>{_rich_text(item.get('domain') or '—')}</td>"
            f"<td>{_rich_text(item.get('sentiment') or '—')}</td>"
            f"<td>{_rich_text(item.get('businessType') or '—')}</td>"
            f"<td>{_rich_text(item.get('role') or '—')}</td>"
            f"<td>{_rich_text(item.get('stripePlan') or '—')}</td>"
            f"<td>{_display_date(item.get('createdAt'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        '<th background-color="light-gray">需求</th>'
        '<th background-color="light-gray">Domain</th>'
        '<th background-color="light-gray">情绪</th>'
        '<th background-color="light-gray">业务类型</th>'
        '<th background-color="light-gray">角色</th>'
        '<th background-color="light-gray">套餐</th>'
        '<th background-color="light-gray">创建日期</th>'
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
    )


def render_intercom_weekly_report(
    *, rows, counts, squad, start, end, week_title, source_documents=False
):
    overview = (
        "<table><thead><tr>"
        '<th background-color="light-gray">周期</th>'
        '<th background-color="light-gray">团队</th>'
        '<th background-color="light-gray">采集总数</th>'
        '<th background-color="light-gray">团队内反馈</th>'
        '<th background-color="light-gray">功能反馈</th>'
        '<th background-color="light-gray">功能需求</th>'
        '<th background-color="light-gray">规则版本</th>'
        "</tr></thead><tbody><tr>"
        f"<td>{start.isoformat()} 至 {end.isoformat()}</td>"
        f"<td>{escape(squad)}</td>"
        f"<td>{counts['inputRows']}</td>"
        f"<td>{counts['squadRows']}</td>"
        f"<td>{counts['featureFeedback']}</td>"
        f"<td>{counts['featureRequest']}</td>"
        f"<td>{INTERCOM_PUBLISH_RULE_VERSION}</td>"
        "</tr></tbody></table>"
    )
    feedback_rows = [
        item for item in rows if _feedback_type(item) == "feature_feedback"
    ]
    request_rows = [item for item in rows if _feedback_type(item) == "feature_request"]
    if source_documents:
        feedback_content = (
            f"<p>共 {len(feedback_rows)} 条，完整明细见下方 Intercom 源数据子文档。</p>"
        )
        request_content = (
            f"<p>共 {len(request_rows)} 条，完整明细见下方 Intercom 源数据子文档。</p>"
        )
        source_content = "<p>__SOURCE_DOCUMENTS__</p>"
    else:
        feedback_content = _intercom_table(feedback_rows)
        request_content = _intercom_table(request_rows)
        source_content = ""
    return (
        f"<title>{escape(week_title)}</title>"
        "<h1>本周概览</h1>"
        + overview
        + "<p>筛选口径：Squad 精确匹配配置值；类型仅包含 feature_feedback 与 feature_request。</p>"
        + "<h1>一、功能反馈</h1>"
        + feedback_content
        + "<h1>二、功能需求</h1>"
        + request_content
        + ("<h1>三、Intercom 源数据</h1>" + source_content if source_content else "")
    )


def render_intercom_source_documents(rows, week_title, squad, *, chunk_size=100):
    documents = []
    for feedback_type, label in INTERCOM_PUBLISH_TYPES:
        typed_rows = [item for item in rows if _feedback_type(item) == feedback_type]
        for offset in range(0, len(typed_rows), chunk_size):
            chunk = typed_rows[offset : offset + chunk_size]
            start_index = offset + 1
            end_index = offset + len(chunk)
            title = (
                f"Intercom｜{str(squad).strip()}｜{label}｜"
                f"{start_index}-{end_index}"
            )
            documents.append(
                {
                    "title": title,
                    "content": (
                        f"<title>{escape(title)}</title>"
                        f'<p><span text-color="gray">'
                        f"{escape(INTERCOM_MANAGED_CHILD_MARKER)}</span></p>"
                        f"<p>所属周报：{escape(week_title)}；本页 {len(chunk)} 条。</p>"
                        + _intercom_table(chunk)
                    ),
                }
            )
    return documents


def _jira_related_tickets(item):
    links = []
    for ticket in item.get("relatedTickets") or []:
        url = escape(str(ticket.get("url") or ""), quote=True)
        key = escape(str(ticket.get("key") or ""))
        status = escape(str(ticket.get("status") or "—"))
        links.append(f'<a href="{url}">{key}</a>（{status}）')
    return "<br/>".join(links) or "—"


def _jira_table(rows):
    if not rows:
        return "<p>本期无符合条件的数据。</p>"
    body = []
    for item in sorted(
        rows,
        key=lambda value: _date_in_shanghai(value.get("createdAt")) or date.min,
        reverse=True,
    ):
        source_url = escape(str(item.get("sourceUrl") or ""), quote=True)
        source_key = escape(str(item.get("sourceObjectId") or ""))
        auxiliary_categories = ", ".join(item.get("auxiliaryCategories") or [])
        body.append(
            "<tr>"
            f'<td><a href="{source_url}">{source_key}</a></td>'
            f"<td>{_rich_text(item.get('title'))}</td>"
            f"<td>{escape(str(item.get('issueType') or '—'))}</td>"
            f"<td>{escape(str(item.get('status') or '—'))}</td>"
            f"<td>{escape(str(item.get('squad') or '—'))}</td>"
            f"<td>{escape(str(item.get('businessCategory') or '—'))}</td>"
            f"<td>{escape(auxiliary_categories or '—')}</td>"
            f"<td>{escape(str(item.get('classificationConfidence') or '—'))}</td>"
            f"<td>{_jira_related_tickets(item)}</td>"
            f"<td>{_display_date(item.get('createdAt'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        '<th background-color="light-gray">CS Ticket</th>'
        '<th background-color="light-gray">标题</th>'
        '<th background-color="light-gray">Issue Type</th>'
        '<th background-color="light-gray">状态</th>'
        '<th background-color="light-gray">承接 Squad</th>'
        '<th background-color="light-gray">主分类</th>'
        '<th background-color="light-gray">辅助分类</th>'
        '<th background-color="light-gray">分类置信度</th>'
        '<th background-color="light-gray">Design Ticket</th>'
        '<th background-color="light-gray">创建日期</th>'
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
    )


def _jira_scope_table(rows):
    if not rows:
        return "<p>本期无符合条件的数据。</p>"
    body = []
    for item in sorted(
        rows,
        key=lambda value: _date_in_shanghai(value.get("createdAt")) or date.min,
        reverse=True,
    ):
        source_url = escape(str(item.get("sourceUrl") or ""), quote=True)
        source_key = escape(str(item.get("sourceObjectId") or ""))
        scope_reasons = ", ".join(item.get("scopeReasons") or [])
        components = ", ".join(item.get("components") or [])
        body.append(
            "<tr>"
            f'<td><a href="{source_url}">{source_key}</a></td>'
            f"<td>{_rich_text(item.get('title'))}</td>"
            f"<td>{escape(str(item.get('squad') or '—'))}</td>"
            f"<td>{escape(str(item.get('scopeDecision') or '—'))}</td>"
            f"<td>{escape(scope_reasons or '—')}</td>"
            f"<td>{escape(components or '—')}</td>"
            f"<td>{_display_date(item.get('createdAt'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        '<th background-color="light-gray">CS Ticket</th>'
        '<th background-color="light-gray">标题</th>'
        '<th background-color="light-gray">承接 Squad</th>'
        '<th background-color="light-gray">范围判定</th>'
        '<th background-color="light-gray">判定依据</th>'
        '<th background-color="light-gray">Components</th>'
        '<th background-color="light-gray">创建日期</th>'
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
    )


def render_jira_weekly_report(
    *,
    rows,
    review_rows,
    excluded_rows,
    counts,
    squad,
    start,
    end,
    week_title,
    source_documents=False,
):
    overview = (
        "<table><thead><tr>"
        '<th background-color="light-gray">周期</th>'
        '<th background-color="light-gray">团队</th>'
        '<th background-color="light-gray">查询返回</th>'
        '<th background-color="light-gray">周期内 CS</th>'
        '<th background-color="light-gray">入选反馈</th>'
        '<th background-color="light-gray">待人工复核</th>'
        '<th background-color="light-gray">范围排除</th>'
        '<th background-color="light-gray">Feature Request</th>'
        '<th background-color="light-gray">关联 Design Issue</th>'
        '<th background-color="light-gray">规则版本</th>'
        "</tr></thead><tbody><tr>"
        f"<td>{start.isoformat()} 至 {end.isoformat()}</td>"
        f"<td>{escape(squad)}</td>"
        f"<td>{counts['queryRows']}</td>"
        f"<td>{counts['inPeriodRows']}</td>"
        f"<td>{counts['selectedRows']}</td>"
        f"<td>{counts['manualReview']}</td>"
        f"<td>{counts['excludedScope']}</td>"
        f"<td>{counts['featureRequest']}</td>"
        f"<td>{counts['designLinked']}</td>"
        f"<td>{JIRA_PUBLISH_RULE_VERSION}</td>"
        "</tr></tbody></table>"
    )
    category_overview = (
        "<table><thead><tr>"
        + "".join(
            f'<th background-color="light-gray">{escape(category)}</th>'
            for category in BUSINESS_CATEGORIES
        )
        + "</tr></thead><tbody><tr>"
        + "".join(
            f"<td>{counts['businessCategories'][category]}</td>"
            for category in BUSINESS_CATEGORIES
        )
        + "</tr></tbody></table>"
    )
    feature_rows = [
        item for item in rows if "feature_request" in item.get("feedbackKinds", [])
    ]
    design_rows = [
        item for item in rows if "design_linked" in item.get("feedbackKinds", [])
    ]
    if source_documents:
        feature_content = f"<p>共 {len(feature_rows)} 条，完整明细见下方 Jira 子文档。</p>"
        design_content = f"<p>共 {len(design_rows)} 条，完整明细见下方 Jira 子文档。</p>"
        source_content = "<h1>五、Jira 源数据</h1><p>__SOURCE_DOCUMENTS__</p>"
    else:
        feature_content = _jira_table(feature_rows)
        design_content = _jira_table(design_rows)
        source_content = ""
    return (
        f"<title>{escape(week_title)}</title>"
        "<h1>本周概览</h1>"
        + overview
        + "<h2>业务分类分布</h2>"
        + category_overview
        + "<p>筛选口径：先保留 CS Feature Request 或关联 DES / Design Issue 的"
        "反馈候选；再以 Grooming Squad 精确命中或标题中的明确 Grooming / groomer "
        "业务语义确认范围。Appointment、Communication、Payment、Staff/Shift 等"
        "公共组件只作为弱证据，进入人工复核；强证据与 Daycare、Boarding 等明确"
        "非 Grooming 服务冲突时也进入人工复核，不自动纳入。</p>"
        + "<h1>一、功能需求（Feature Request）</h1>"
        + feature_content
        + "<h1>二、关联设计单反馈</h1>"
        + design_content
        + "<h1>三、待人工复核</h1>"
        + _jira_scope_table(review_rows)
        + "<h1>四、范围排除审计</h1>"
        + _jira_scope_table(excluded_rows)
        + source_content
    )


def render_jira_source_documents(rows, week_title, squad, *, chunk_size=100):
    documents = []
    groups = (
        ("feature_request", "功能需求"),
        ("design_linked", "关联设计单反馈"),
    )
    for kind, label in groups:
        typed_rows = [item for item in rows if kind in item.get("feedbackKinds", [])]
        for offset in range(0, len(typed_rows), chunk_size):
            chunk = typed_rows[offset : offset + chunk_size]
            start_index = offset + 1
            end_index = offset + len(chunk)
            title = f"Jira｜{str(squad).strip()}｜{label}｜{start_index}-{end_index}"
            documents.append(
                {
                    "title": title,
                    "content": (
                        f"<title>{escape(title)}</title>"
                        f'<p><span text-color="gray">'
                        f"{escape(JIRA_MANAGED_CHILD_MARKER)}</span></p>"
                        f"<p>所属周报：{escape(week_title)}；本页 {len(chunk)} 条。</p>"
                        + _jira_table(chunk)
                    ),
                }
            )
    return documents


def _facebook_table(rows):
    if not rows:
        return "<p>本期无符合条件的频道汇总反馈。</p>"
    body = []
    for item in sorted(
        rows,
        key=lambda value: _date_in_shanghai(value.get("createdAt")) or date.min,
        reverse=True,
    ):
        url = escape(
            str(item.get("slackUrl") or item.get("sourceUrl") or ""), quote=True
        )
        title = _rich_text(item.get("title") or item.get("content"))
        title_value = f'<a href="{url}">{title}</a>' if url else title
        body.append(
            "<tr>"
            f"<td>{title_value}</td>"
            f"<td>{escape(str(item.get('feedType') or '—'))}</td>"
            f"<td>{escape(str(item.get('groupName') or '—'))}</td>"
            f"<td>{_display_date(item.get('createdAt'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        '<th background-color="light-gray">反馈摘要</th>'
        '<th background-color="light-gray">类型</th>'
        '<th background-color="light-gray">Group</th>'
        '<th background-color="light-gray">日期</th>'
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
    )


def render_facebook_weekly_report(*, rows, counts, domain, start, end, week_title):
    feed_breakdown = "；".join(
        f"{key} {value}" for key, value in sorted(counts["feedCounts"].items())
    ) or "无入选内容"
    return (
        f"<title>{escape(week_title)}</title>"
        "<h1>本周概览</h1>"
        '<callout emoji="📌" background-color="light-blue" border-color="blue">'
        f"<p>{start.isoformat()} 至 {end.isoformat()}｜Domain：{escape(domain)}｜"
        f"频道观察 {counts['observedRows']} 条，入选 {counts['selectedRows']} 条。</p>"
        f"<p>{escape(feed_breakdown)}</p>"
        "</callout>"
        "<h1>频道汇总反馈</h1>"
        + _facebook_table(rows)
        + "<h1>口径说明</h1>"
        f"<p>规则版本：{FACEBOOK_PUBLISH_RULE_VERSION}。本页只代表 Slack 频道已汇总的 "
        "Facebook Community 内容，覆盖口径为 channel-summary，不代表 Facebook 全量。</p>"
    )


def render_weekly_report(
    *,
    manifest,
    weekly_rows,
    decisions,
    start,
    end,
    week_title,
    source_documents=False,
):
    quick_win_count = sum(
        1 for item in weekly_rows if item.get("sourceObjectId") in decisions
    )
    baseline = bool(manifest.get("baseline"))
    overview = (
        "<table><thead><tr>"
        "<th background-color=\"light-gray\">周期</th>"
        "<th background-color=\"light-gray\">本期源数据</th>"
        "<th background-color=\"light-gray\">Quick Win 候选</th>"
        "<th background-color=\"light-gray\">规则版本</th>"
        "</tr></thead><tbody><tr>"
        f"<td>{start.isoformat()} 至 {end.isoformat()}</td>"
        f"<td>{len(weekly_rows)}</td><td>{quick_win_count}</td>"
        f"<td>{QUICK_WIN_RULE_VERSION}</td>"
        "</tr></tbody></table>"
    )
    baseline_notice = ""
    if baseline:
        baseline_notice = (
            "<callout emoji=\"📌\" background-color=\"light-blue\" border-color=\"blue\">"
            "<p>这是首次运行：由于上周之前没有历史快照，"
            "只能准确识别上周新增 Post，无法还原老 Post 在上周发生的 Vote、评论或状态变化。</p>"
            "</callout>"
        )
    source_section = (
        "<p>__SOURCE_DOCUMENTS__</p>"
        if source_documents
        else _source_table(weekly_rows)
    )
    return (
        f"<title>{escape(week_title)}</title>"
        "<h1>本周概览</h1>"
        + overview
        + baseline_notice
        + "<h1>一、Quick Win 候选</h1>"
        + _quick_win_table(weekly_rows, decisions)
        + "<p>候选结果来自规则初筛与 AI 语义复核，仍需产品和工程确认实际改动成本。</p>"
        + "<h1>二、Canny 源数据</h1>"
        + source_section
    )


def render_source_documents(
    weekly_rows, week_title, *, label="本期新增与变化", chunk_size=100
):
    documents = []
    for offset in range(0, len(weekly_rows), chunk_size):
        chunk = weekly_rows[offset : offset + chunk_size]
        start_index = offset + 1
        end_index = offset + len(chunk)
        title = f"源数据｜{label}｜{start_index}-{end_index}"
        blocks = [
            f"<title>{escape(title)}</title>",
            f'<p><span text-color="gray">{escape(CANNY_MANAGED_CHILD_MARKER)}</span></p>',
            f"<p>所属周报：{escape(week_title)}；本页 {len(chunk)} 条。</p>",
        ]
        for index, item in enumerate(chunk, start=start_index):
            url = escape(str(item.get("sourceUrl") or ""), quote=True)
            blocks.append(
                "<p>"
                f"<b>{index}. {_rich_text(item.get('title'))}</b><br/>"
                f"Vote：{int(item.get('voteCount') or 0)}；"
                f"评论：{int(item.get('commentCount') or 0)}；"
                f"变化：{escape(_change_text(item))}；"
                f"状态：{_rich_text(item.get('status') or '—')}；"
                f"发布时间：{_display_date(item.get('createdAt'))}；"
                f"<a href=\"{url}\">查看原文</a>"
                "</p>"
            )
            blocks.append(
                f"<blockquote>{_rich_text(item.get('content') or '无正文')}</blockquote>"
            )
        documents.append({"title": title, "content": "".join(blocks)})
    return documents
