from __future__ import annotations

import hashlib
import json
from html import escape
from pathlib import Path

from .errors import BusinessError, ConfigError
from .report import (
    apply_quick_win_rule,
    choose_report_rows,
    facebook_report_titles,
    intercom_report_titles,
    jira_report_titles,
    load_facebook_run,
    load_quick_win_review,
    load_run,
    managed_source_run_marker,
    report_titles,
    select_facebook_rows,
    select_intercom_rows,
    select_jira_rows,
)

DASHBOARD_MARKER = "由 Moe Feedback Collector 自动生成的全渠道反馈总看板。"
DASHBOARD_DETAIL_MARKER = "由 Moe Feedback Collector 自动生成的周总览分析明细。"
DASHBOARD_RULE_VERSION = "cross-source-dashboard-v10"
ANALYSIS_SCHEMA_VERSION = 2
CATEGORY_DETAIL_PLACEHOLDER = "<p>__CATEGORY_DETAIL_REPORT__</p>"
SOURCE_ORDER = ("canny", "intercom", "jira", "facebook")
SOURCE_LABELS = {
    "canny": "Canny",
    "intercom": "Intercom",
    "jira": "Jira CS",
    "facebook": "Facebook Community",
}
SOURCE_COVERAGE = {
    "canny": "周期新增与关注字段变化",
    "intercom": "Squad 内功能反馈与功能需求",
    "jira": "Grooming Customer 范围内的 Feature Request 与关联 Design Issue",
    "facebook": "channel-summary：Slack 频道已汇总内容，非 Facebook 全量",
}

CATEGORY_LABELS = {
    "scheduling": "scheduling",
    "fulfillment": "fulfillment",
    "communication": "communication",
    "management": "management",
    "payment": "payment",
    "van-staff-shift-management": "van-staff-shift management",
    "others": "others",
}
CATEGORY_ORDER = tuple(CATEGORY_LABELS)


def _load_json(path, label):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"无法读取{label}：{path}") from exc
    if not isinstance(payload, dict):
        raise BusinessError(f"{label}结构无效")
    return payload


def _manifest_source(path):
    manifest = _load_json(path, "采集 manifest")
    source = str(manifest.get("sourceKey") or "").strip().casefold()
    if source not in SOURCE_ORDER:
        raise BusinessError(f"总看板不支持的数据源：{source or 'unknown'}")
    return source


def weekly_analysis_schema_version(path):
    payload = _load_json(path, "周度 AI analysis")
    version = payload.get("schemaVersion")
    if version not in {ANALYSIS_SCHEMA_VERSION, 3}:
        raise ConfigError("周度 AI analysis schemaVersion 不受支持")
    return version


def _facebook_summary(path, *, start, end, domain):
    manifest, evidence, _report_rows = load_facebook_run(path)
    rows, counts = select_facebook_rows(manifest, evidence, domain, start, end)
    feed_counts = counts["feedCounts"]
    breakdown = (
        "；".join(f"{key} {value}" for key, value in sorted(feed_counts.items()))
        or "无入选内容"
    )
    _year, _month, title = facebook_report_titles(start, end, domain)
    return (
        {
            "sourceKey": "facebook",
            "status": "ready",
            "collected": counts["observedRows"],
            "included": len(rows),
            "breakdown": breakdown,
            "coverage": SOURCE_COVERAGE["facebook"],
            "reportTitle": title,
            "markers": ["Facebook Community", "频道汇总反馈"],
            "managedMarker": managed_source_run_marker(
                "facebook", start, end, manifest.get("runId")
            ),
        },
        rows,
        str(manifest.get("runId") or "").strip(),
    )


def _record_title(item, source):
    if source == "intercom":
        return str(item.get("requirement") or "").strip()
    if source == "facebook":
        return str(item.get("title") or item.get("content") or "").strip()
    return str(item.get("title") or "").strip()


def _record_category(item, source, quick_win_selected):
    if source == "canny":
        return "Quick Win 候选" if quick_win_selected else "Canny 反馈"
    if source == "intercom":
        return {
            "feature_feedback": "功能反馈",
            "feature_request": "功能需求",
        }.get(str(item.get("feedbackType") or ""), "其它反馈")
    if source == "jira":
        labels = []
        if "feature_request" in (item.get("feedbackKinds") or []):
            labels.append("Feature Request")
        if "design_linked" in (item.get("feedbackKinds") or []):
            labels.append("关联 Design Issue")
        return " + ".join(labels) or str(item.get("issueType") or "Jira CS")
    return str(item.get("feedType") or "Facebook 反馈")


def _record_normalized_text(item, source, title):
    if source in {"canny", "facebook"}:
        value = item.get("content")
    elif source == "intercom":
        value = item.get("requirement")
    else:
        value = item.get("title")
    return str(value or title).strip()[:5000]


def _record_context_tags(item):
    tags = []
    for key in (
        "domain",
        "sentiment",
        "status",
        "role",
        "tier",
        "businessType",
        "feedbackType",
        "feedType",
        "issueType",
    ):
        value = str(item.get(key) or "").strip()[:100]
        if value and value not in tags:
            tags.append(value)
    for key in ("components", "feedbackKinds"):
        values = item.get(key)
        if not isinstance(values, list):
            continue
        for raw_value in values:
            value = str(raw_value or "").strip()[:100]
            if value and value not in tags:
                tags.append(value)
    return tags[:20]


def _normalize_records(
    source,
    rows,
    *,
    quick_win_decisions=None,
    include_analysis_fields=False,
):
    decisions = quick_win_decisions or {}
    normalized = []
    for item in rows:
        evidence_id = str(item.get("evidenceId") or "").strip()
        title = _record_title(item, source)
        if not evidence_id or not title:
            raise BusinessError(f"{SOURCE_LABELS[source]} evidence 缺少 ID 或摘要")
        source_object_id = str(item.get("sourceObjectId") or "").strip()
        quick_win_selected = source_object_id in decisions
        context_tags = _record_context_tags(item)
        source_category = _record_category(item, source, quick_win_selected)
        if include_analysis_fields and source == "canny":
            source_category = "Canny 反馈"
        record = {
            "evidenceId": evidence_id,
            "sourceKey": source,
            "sourceObjectId": source_object_id,
            "title": title[:1000],
            "category": source_category,
            "createdAt": str(item.get("createdAt") or ""),
            "sourceUrl": str(
                item.get("slackUrl") or item.get("sourceUrl") or ""
            ).strip(),
            "context": " / ".join(context_tags),
            "quickWinSelected": quick_win_selected,
        }
        if include_analysis_fields:
            record["normalizedText"] = _record_normalized_text(item, source, title)
            record["contextTags"] = context_tags
        normalized.append(record)
    return normalized


def _analysis_text(value, label, *, limit=2000):
    text = str(value or "").strip()
    if not text or len(text) > limit or any(character in text for character in "\x00"):
        raise ConfigError(f"AI analysis {label} 必须是 {limit} 字以内的非空文本")
    return text


def _analysis_evidence_ids(value, label, known_ids, *, maximum=50):
    if (
        not isinstance(value, list)
        or not value
        or len(value) > maximum
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ConfigError(f"AI analysis {label} 必须包含 1-{maximum} 个 evidence ID")
    ids = [item.strip() for item in value]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"AI analysis {label} 包含重复 evidence ID")
    unknown = [item for item in ids if item not in known_ids]
    if unknown:
        raise ConfigError(f"AI analysis 引用了未知 evidence ID：{unknown[0]}")
    return ids


def load_weekly_analysis(path, snapshot, *, scope):
    payload = _load_json(path, "周度 AI analysis")
    if payload.get("schemaVersion") != ANALYSIS_SCHEMA_VERSION:
        raise ConfigError("周度 AI analysis schemaVersion 不受支持")
    if payload.get("period") != snapshot["period"]:
        raise ConfigError("周度 AI analysis 周期与总看板不一致")
    if str(payload.get("scope") or "").strip().casefold() != str(scope).strip().casefold():
        raise ConfigError("周度 AI analysis scope 与总看板不一致")
    known_ids = {item["evidenceId"] for item in snapshot["records"]}

    def normalize_items(key, *, maximum, fields):
        raw_items = payload.get(key)
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= maximum:
            raise ConfigError(f"周度 AI analysis {key} 必须包含 1-{maximum} 项")
        normalized = []
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                raise ConfigError(f"周度 AI analysis {key}[{index}] 结构无效")
            confidence = str(item.get("confidence") or "").strip().casefold()
            if confidence not in {"high", "medium", "low"}:
                raise ConfigError(f"周度 AI analysis {key}[{index}] confidence 无效")
            normalized_item = {
                field: _analysis_text(item.get(field), f"{key}[{index}].{field}")
                for field in fields
            }
            normalized_item["confidence"] = confidence
            normalized_item["evidenceIds"] = _analysis_evidence_ids(
                item.get("evidenceIds"), f"{key}[{index}].evidenceIds", known_ids
            )
            normalized.append(normalized_item)
        return normalized

    summary = normalize_items("summary", maximum=6, fields=("text",))
    themes = normalize_items(
        "themes", maximum=12, fields=("name", "summary")
    )
    insights = normalize_items(
        "insights", maximum=10, fields=("title", "observation", "whyItMatters")
    )
    recommendations = normalize_items(
        "recommendations", maximum=10, fields=("title", "action")
    )
    featured = _analysis_evidence_ids(
        payload.get("featuredEvidenceIds"),
        "featuredEvidenceIds",
        known_ids,
        maximum=30,
    )
    return {
        "schemaVersion": ANALYSIS_SCHEMA_VERSION,
        "period": snapshot["period"],
        "scope": str(scope).strip(),
        "summary": summary,
        "themes": themes,
        "featuredEvidenceIds": featured,
        "insights": insights,
        "recommendations": recommendations,
    }


def build_dashboard_snapshot(
    manifest_paths,
    *,
    squad,
    domain,
    start,
    end,
    quick_win_review="",
    require_quick_win_review=True,
    include_analysis_fields=False,
):
    paths_by_source = {}
    for path in manifest_paths:
        source = _manifest_source(path)
        if source in paths_by_source:
            raise ConfigError(f"总看板包含重复数据源：{source}")
        paths_by_source[source] = path

    summaries = {}
    run_ids = {}
    records = []
    canny_path = paths_by_source.get("canny")
    if canny_path:
        if not quick_win_review and require_quick_win_review:
            raise ConfigError("总看板包含 Canny 时必须提供 --quick-win-review")
        manifest, posts, report_rows = load_run(canny_path)
        if manifest.get("sourceKey") != "canny":
            raise BusinessError("Canny manifest 数据源不匹配")
        run_ids["canny"] = str(manifest.get("runId") or "").strip()
        weekly_rows = apply_quick_win_rule(
            choose_report_rows(manifest, posts, report_rows, start, end)
        )
        prefiltered = [item for item in weekly_rows if item.get("quickWinPrefilter")]
        decisions = (
            load_quick_win_review(quick_win_review, prefiltered)
            if quick_win_review
            else {}
        )
        _year, _month, title = report_titles(start, end)
        summaries["canny"] = {
            "sourceKey": "canny",
            "status": "ready",
            "collected": len(weekly_rows),
            "included": len(weekly_rows),
            "breakdown": (
                f"本周反馈 {len(weekly_rows)}；Quick Win 进入四源统一语义筛选"
                if include_analysis_fields
                else (
                    f"Quick Win 初筛 {len(prefiltered)}；AI 入选 {len(decisions)}"
                    if quick_win_review
                    else f"本周反馈 {len(weekly_rows)}；未读取 Quick Win 复筛"
                )
            ),
            "coverage": SOURCE_COVERAGE["canny"],
            "reportTitle": title,
            "markers": [title, "Quick Win 候选", "Canny 源数据"],
            "managedMarker": managed_source_run_marker(
                "canny", start, end, manifest.get("runId")
            ),
        }
        records.extend(
            _normalize_records(
                "canny",
                weekly_rows,
                quick_win_decisions=decisions,
                include_analysis_fields=include_analysis_fields,
            )
        )

    intercom_path = paths_by_source.get("intercom")
    if intercom_path:
        manifest, feedback, _report_rows = load_run(
            intercom_path, object_type="feedback"
        )
        run_ids["intercom"] = str(manifest.get("runId") or "").strip()
        rows, counts = select_intercom_rows(manifest, feedback, squad, start, end)
        _year, _month, title = intercom_report_titles(start, end, squad)
        summaries["intercom"] = {
            "sourceKey": "intercom",
            "status": "ready",
            "collected": counts["inputRows"],
            "included": len(rows),
            "breakdown": (
                f"功能反馈 {counts['featureFeedback']}；功能需求 {counts['featureRequest']}"
            ),
            "coverage": SOURCE_COVERAGE["intercom"],
            "reportTitle": title,
            "markers": [title, "功能反馈", "功能需求", str(squad).strip()],
            "managedMarker": managed_source_run_marker(
                "intercom", start, end, manifest.get("runId")
            ),
        }
        records.extend(
            _normalize_records(
                "intercom", rows, include_analysis_fields=include_analysis_fields
            )
        )

    jira_path = paths_by_source.get("jira")
    if jira_path:
        manifest, feedback, scope_rows = load_run(jira_path, object_type="feedback")
        run_ids["jira"] = str(manifest.get("runId") or "").strip()
        rows, _review_rows, _excluded_rows, counts = select_jira_rows(
            manifest, feedback, scope_rows, squad, start, end
        )
        _year, _month, title = jira_report_titles(start, end, squad)
        summaries["jira"] = {
            "sourceKey": "jira",
            "status": "ready",
            "collected": counts["inPeriodRows"],
            "included": len(rows),
            "breakdown": (
                f"Feature Request {counts['featureRequest']}；"
                f"关联 Design Issue {counts['designLinked']}；"
                f"待人工复核 {counts['manualReview']}；"
                f"范围排除 {counts['excludedScope']}"
            ),
            "coverage": SOURCE_COVERAGE["jira"],
            "reportTitle": title,
            "markers": [
                title,
                "功能需求",
                "关联设计单反馈",
                "待人工复核",
                "范围排除审计",
                str(squad).strip(),
            ],
            "managedMarker": managed_source_run_marker(
                "jira", start, end, manifest.get("runId")
            ),
        }
        records.extend(
            _normalize_records(
                "jira", rows, include_analysis_fields=include_analysis_fields
            )
        )

    facebook_path = paths_by_source.get("facebook")
    if facebook_path:
        facebook_summary, facebook_rows, facebook_run_id = _facebook_summary(
            facebook_path, start=start, end=end, domain=domain
        )
        run_ids["facebook"] = facebook_run_id
        summaries["facebook"] = facebook_summary
        records.extend(
            _normalize_records(
                "facebook",
                facebook_rows,
                include_analysis_fields=include_analysis_fields,
            )
        )

    record_ids = [item["evidenceId"] for item in records]
    if len(record_ids) != len(set(record_ids)):
        raise BusinessError("总看板包含重复 evidence ID")

    rows = []
    for source in SOURCE_ORDER:
        rows.append(
            summaries.get(source)
            or {
                "sourceKey": source,
                "status": "missing",
                "collected": None,
                "included": None,
                "breakdown": "未提供本周期 manifest",
                "coverage": SOURCE_COVERAGE[source],
                "reportTitle": None,
            }
        )
    snapshot = {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "squad": str(squad or "").strip(),
        "domain": str(domain or "").strip(),
        "sources": rows,
        "records": records,
        "providedSources": [
            row["sourceKey"] for row in rows if row["status"] == "ready"
        ],
        "missingSources": [
            row["sourceKey"] for row in rows if row["status"] == "missing"
        ],
        "emptySources": [
            row["sourceKey"]
            for row in rows
            if row["status"] == "ready" and int(row["included"] or 0) == 0
        ],
        "totalSignals": sum(
            int(row["included"] or 0) for row in rows if row["status"] == "ready"
        ),
        "ruleVersion": DASHBOARD_RULE_VERSION,
    }
    if include_analysis_fields:
        snapshot["sourceRunIds"] = run_ids
    return snapshot


def dashboard_titles(start, end, scope):
    iso_year, iso_week, _weekday = start.isocalendar()
    normalized_scope = str(scope or "").strip()
    week_title = (
        f"{iso_year}-W{iso_week:02d}｜{start:%m.%d}–{end:%m.%d}｜"
        f"{normalized_scope} 反馈总览"
    )
    return str(iso_year), f"{start:%m}", week_title


def _dashboard_week_prefix(week_title):
    week_prefix = str(week_title or "").split("｜", 1)[0].strip()
    if not week_prefix:
        raise ConfigError("周总览标题缺少 ISO 周")
    return week_prefix


def dashboard_detail_titles(week_title):
    week_prefix = _dashboard_week_prefix(week_title)
    return {"category": f"{week_prefix}｜分类与主题明细"}


def _dashboard_detail_ownership_marker(snapshot, kind):
    period = snapshot["period"]
    scope = snapshot["squad"] or snapshot["domain"]
    return (
        "MFC_MANAGED_DASHBOARD_DETAIL_V1|"
        f"kind={kind}|period={period['start']}..{period['end']}|scope={scope}"
    )


def _evidence_links(ids, records_by_id, *, maximum=5):
    links = []
    for evidence_id in ids[:maximum]:
        item = records_by_id[evidence_id]
        title = escape(item["title"][:80])
        url = escape(item["sourceUrl"], quote=True)
        links.append(f'<a href="{url}">{title}</a>' if url else title)
    suffix = f" 等 {len(ids)} 条" if len(ids) > maximum else ""
    return "；".join(links) + suffix


def _render_analysis(analysis, records):
    if not analysis:
        return (
            "<h1>AI 分析</h1><callout emoji=\"📌\" background-color=\"light-gray\" "
            "border-color=\"gray\"><p>当前为 partial dry-run，尚未提供周度 AI analysis。"
            "</p></callout>"
        )
    records_by_id = {item["evidenceId"]: item for item in records}
    summary = "".join(
        (
            f"<li><p>{escape(item['text'])}</p>"
            f"<p><b>证据：</b>{_evidence_links(item['evidenceIds'], records_by_id)}；"
            f"置信度：{escape(item['confidence'])}</p></li>"
        )
        for item in analysis["summary"]
    )
    theme_rows = []
    for item in analysis["themes"]:
        sources = sorted(
            {records_by_id[value]["sourceKey"] for value in item["evidenceIds"]}
        )
        theme_rows.append(
            "<tr>"
            f"<td><b>{escape(item['name'])}</b></td>"
            f"<td>{escape(item['summary'])}</td>"
            f"<td>{len(item['evidenceIds'])}</td>"
            f"<td>{escape(' / '.join(SOURCE_LABELS[value] for value in sources))}</td>"
            f"<td>{_evidence_links(item['evidenceIds'], records_by_id)}</td>"
            f"<td>{escape(item['confidence'])}</td>"
            "</tr>"
        )
    insight_blocks = []
    for item in analysis["insights"]:
        insight_blocks.append(
            '<callout emoji="💡" background-color="light-blue" border-color="blue">'
            f"<h3>{escape(item['title'])}</h3>"
            f"<p>{escape(item['observation'])}</p>"
            f"<p><b>为什么重要：</b>{escape(item['whyItMatters'])}</p>"
            f"<p><b>证据：</b>{_evidence_links(item['evidenceIds'], records_by_id)}</p>"
            f"<p><span text-color=\"gray\">置信度：{escape(item['confidence'])}</span></p>"
            "</callout>"
        )
    recommendation_rows = []
    for item in analysis["recommendations"]:
        recommendation_rows.append(
            "<tr>"
            f"<td><b>{escape(item['title'])}</b></td>"
            f"<td>{escape(item['action'])}</td>"
            f"<td>{_evidence_links(item['evidenceIds'], records_by_id)}</td>"
            f"<td>{escape(item['confidence'])}</td>"
            "</tr>"
        )
    return (
        "<h1>本周 AI 摘要</h1>"
        '<callout emoji="🎯" background-color="light-blue" border-color="blue"><ul>'
        + summary
        + "</ul></callout>"
        "<h1>跨渠道主题</h1><table><thead><tr>"
        '<th background-color="light-gray">主题</th>'
        '<th background-color="light-gray">AI 摘要</th>'
        '<th background-color="light-gray">信号</th>'
        '<th background-color="light-gray">渠道</th>'
        '<th background-color="light-gray">代表反馈</th>'
        '<th background-color="light-gray">置信度</th>'
        "</tr></thead><tbody>" + "".join(theme_rows) + "</tbody></table>"
        "<h1>AI 洞察</h1>" + "".join(insight_blocks)
        + "<h1>建议动作</h1><table><thead><tr>"
        '<th background-color="light-gray">建议</th>'
        '<th background-color="light-gray">动作</th>'
        '<th background-color="light-gray">依据</th>'
        '<th background-color="light-gray">置信度</th>'
        "</tr></thead><tbody>" + "".join(recommendation_rows) + "</tbody></table>"
    )


def _render_featured(analysis, records):
    if not analysis:
        return ""
    records_by_id = {item["evidenceId"]: item for item in records}
    rows = []
    for evidence_id in analysis["featuredEvidenceIds"]:
        item = records_by_id[evidence_id]
        url = escape(item["sourceUrl"], quote=True)
        title = escape(item["title"])
        title_value = f'<a href="{url}">{title}</a>' if url else title
        rows.append(
            "<tr>"
            f"<td>{escape(SOURCE_LABELS[item['sourceKey']])}</td>"
            f"<td>{title_value}</td>"
            f"<td>{escape(item['category'])}</td>"
            f"<td>{escape(item['context'] or '—')}</td>"
            f"<td><code>{escape(evidence_id)}</code></td>"
            "</tr>"
        )
    return (
        "<h1>重点反馈</h1><table><thead><tr>"
        '<th background-color="light-gray">来源</th>'
        '<th background-color="light-gray">反馈摘要</th>'
        '<th background-color="light-gray">类型</th>'
        '<th background-color="light-gray">上下文</th>'
        '<th background-color="light-gray">Evidence</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _v3_evidence_maps(analysis):
    analysis_input = analysis["_analysisInput"]
    current = {
        item["evidenceId"]: item for item in analysis_input["records"]
    }
    previous = {
        item["evidenceId"]: item
        for category in analysis_input["previousBaseline"].get("categories", [])
        for item in category["representativeEvidence"]
    }
    return current, previous


def _v3_evidence_links(refs, analysis, *, maximum=5, compact=False):
    current, previous = _v3_evidence_maps(analysis)
    links = []
    for ref in refs[:maximum]:
        record = (current if ref["period"] == "current" else previous)[
            ref["evidenceId"]
        ]
        period_label = "本周" if ref["period"] == "current" else "上周"
        if compact:
            source_label = SOURCE_LABELS[record["sourceKey"]]
            label = f"{period_label}·{source_label}·{ref['evidenceId']}"
            title = escape(_compact_text(label, 52) if record["sourceUrl"] else label)
        else:
            title = escape(record["title"][:80])
        url = escape(record["sourceUrl"], quote=True)
        value = f'<a href="{url}">{title}</a>' if url else title
        links.append(value if compact else f"{period_label}：{value}")
    suffix = f" 等 {len(refs)} 条" if len(refs) > maximum else ""
    return "；".join(links) + suffix


def _evidence_ref_keys(item):
    return {
        (ref["period"], ref["evidenceId"])
        for ref in item.get("evidenceRefs", [])
    }


def _compact_text(value, maximum):
    text = str(value or "").strip()
    if len(text) <= maximum:
        return text
    return text[:maximum].rstrip() + "…"


def _pair_focus_actions(analysis, *, maximum=3):
    recommendations = analysis["recommendations"]
    used_recommendations = set()
    pairs = []
    for insight in analysis["insights"][:maximum]:
        insight_refs = _evidence_ref_keys(insight)
        best_index = None
        best_overlap = 0
        for index, recommendation in enumerate(recommendations):
            if index in used_recommendations:
                continue
            overlap = len(insight_refs & _evidence_ref_keys(recommendation))
            if overlap > best_overlap:
                best_index = index
                best_overlap = overlap
        recommendation = None
        if best_index is not None:
            used_recommendations.add(best_index)
            recommendation = recommendations[best_index]
        pairs.append((insight, recommendation))
    return pairs


def _render_v3_product_design_focus(analysis):
    summary_items = "".join(
        f"<li><p>{escape(_compact_text(item['text'], 180))}</p></li>"
        for item in analysis["summary"][:2]
    )
    focus_pairs = _pair_focus_actions(analysis)
    cards = []
    for insight, recommendation in focus_pairs:
        action = (
            escape(_compact_text(recommendation["action"], 180))
            if recommendation
            else "本项尚无与相同证据直接绑定的建议动作，请在完整明细中继续评估。"
        )
        cards.append(
            '<callout emoji="🎯" background-color="light-blue" border-color="blue">'
            f"<h3>{escape(_compact_text(insight['title'], 80))}</h3>"
            f"<p>{escape(_compact_text(insight['observation'], 180))}</p>"
            f"<p><b>为什么重要：</b>{escape(_compact_text(insight['whyItMatters'], 180))}</p>"
            f"<p><b>建议动作：</b>{action}</p>"
            f'<p><span text-color="gray">证据 {len(insight["evidenceRefs"])} 条；'
            f"置信度：{escape(insight['confidence'])}</span></p>"
            "</callout>"
        )
    hidden_insights = max(0, len(analysis["insights"]) - len(cards))
    hidden_recommendations = max(
        0,
        len(analysis["recommendations"])
        - sum(1 for _insight, recommendation in focus_pairs if recommendation),
    )
    details_note = (
        f"完整明细还包含 {hidden_insights} 项补充洞察和 "
        f"{hidden_recommendations} 项未在摘要卡片展开的建议。"
    )
    return (
        "<h1>产品/设计关注点</h1>"
        '<callout emoji="💬" background-color="light-gray" border-color="gray"><ul>'
        + summary_items
        + "</ul></callout>"
        + "".join(cards)
        + f'<p><span text-color="gray">{details_note}</span></p>'
    )


def _render_v3_comparison(snapshot, analysis):
    comparison = analysis["weekComparison"]
    heading = "<h1>周环比</h1>" + _render_v3_summary_header(snapshot, analysis)
    if comparison["status"] == "unavailable":
        reason = analysis["comparisonBaseline"]["reason"]
        return (
            heading
            + '<callout emoji="📌" background-color="light-gray" border-color="gray">'
            f"<p><b>暂不可比：</b>{escape(reason)}</p></callout>"
            "<h2>改善信号</h2><p>暂无经过证据支持的可比结论。</p>"
            "<h2>需关注项</h2><p>暂无经过证据支持的可比结论。</p>"
        )

    def compact_list(items, empty_text, color):
        visible = items[:2]
        if not visible:
            return f"<p>{empty_text}</p>"
        body = "<ul>" + "".join(
            (
                f"<li><p><b>{escape(_compact_text(item['title'], 80))}</b>："
                f"{escape(_compact_text(item['summary'], 180))}</p>"
                f'<p><span text-color="{color}">'
                f"{escape(CATEGORY_LABELS[item['businessCategory']])}｜"
                f"证据 {len(item['evidenceRefs'])} 条｜"
                f"置信度 {escape(item['confidence'])}</span></p></li>"
            )
            for item in visible
        ) + "</ul>"
        if len(items) > len(visible):
            body += (
                f'<p><span text-color="gray">另有 {len(items) - len(visible)} 项，'
                "见分析明细子文档。</span></p>"
            )
        return body

    return (
        heading
        + "<h2>改善信号</h2>"
        + compact_list(
            comparison["improvements"],
            "本周没有足够证据支持的改善信号。",
            "green",
        )
        + "<h2>需关注项</h2>"
        + compact_list(
            comparison["attentionItems"],
            "本周没有足够证据支持的新增关注项。",
            "orange",
        )
        + '<p><span text-color="gray">完整周环比证据见分析明细子文档。</span></p>'
    )


def _render_v3_category_overview(analysis):
    current_total = sum(item["currentCount"] for item in analysis["categoryOverview"])
    first_theme_by_category = {}
    for theme in analysis["themes"]:
        for category in theme["businessCategories"]:
            first_theme_by_category.setdefault(category, theme["name"])
    rows = []
    for item in analysis["categoryOverview"]:
        delta = item["delta"]
        if delta is None:
            delta_text = "不可比"
        elif delta > 0:
            delta_text = f"↑ {delta:+d}"
        elif delta < 0:
            delta_text = f"↓ {delta:+d}"
        else:
            delta_text = "→ 0"
        share = (
            f"{item['currentCount'] / current_total:.0%}" if current_total else "0%"
        )
        rows.append(
            "<tr>"
            f"<td><b>{escape(CATEGORY_LABELS[item['businessCategory']])}</b></td>"
            f"<td>{item['currentCount']}</td><td>{share}</td><td>{delta_text}</td>"
            f"<td>{escape(_compact_text(first_theme_by_category.get(item['businessCategory'], '—'), 80))}</td>"
            "</tr>"
        )
    queue = analysis["reviewQueue"]
    previous_review = (
        queue["previousCount"] if queue["previousCount"] is not None else "—"
    )
    return (
        "<h2>分类数据</h2>"
        '<callout emoji="📊" background-color="light-gray" border-color="gray">'
        "<p>分类数量表示入选反馈信号量，不等同于独立需求数或产品表现；"
        f"本周待人工复核 {queue['currentCount']} 条，上周 {previous_review} 条。</p></callout>"
        "<table><thead><tr>"
        '<th background-color="light-gray">分类</th>'
        '<th background-color="light-gray">本周</th>'
        '<th background-color="light-gray">占比</th>'
        '<th background-color="light-gray">环比</th>'
        '<th background-color="light-gray">主要主题</th>'
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        '<p><span text-color="gray">完整主题、代表反馈、分类理由及待复核项见明细子文档。</span></p>'
        + CATEGORY_DETAIL_PLACEHOLDER
    )


def _v3_evidence_categories(analysis):
    categories = {
        ("current", item["evidenceId"]): item["primaryCategory"]
        for item in analysis["classifications"]
        if item["decision"] == "classified"
    }
    for category in analysis["_analysisInput"]["previousBaseline"].get(
        "categories", []
    ):
        for item in category["representativeEvidence"]:
            categories[("previous", item["evidenceId"])] = category[
                "businessCategory"
            ]
    return categories


def _v3_item_categories(item, analysis):
    evidence_categories = _v3_evidence_categories(analysis)
    values = {
        evidence_categories.get((ref["period"], ref["evidenceId"]))
        for ref in item.get("evidenceRefs", [])
    }
    return [category for category in CATEGORY_ORDER if category in values]


def _v3_theme_owner(theme, analysis):
    declared = theme["businessCategories"]
    evidence_categories = _v3_evidence_categories(analysis)
    counts = {category: 0 for category in declared}
    for ref in theme["evidenceRefs"]:
        category = evidence_categories.get((ref["period"], ref["evidenceId"]))
        if category in counts:
            counts[category] += 1
    return min(
        declared,
        key=lambda category: (-counts[category], CATEGORY_ORDER.index(category)),
    )


def _v3_source_summary(refs, analysis):
    current, previous = _v3_evidence_maps(analysis)
    counts = {source: 0 for source in SOURCE_ORDER}
    for ref in refs:
        records = current if ref["period"] == "current" else previous
        counts[records[ref["evidenceId"]]["sourceKey"]] += 1
    return " / ".join(
        f"{SOURCE_LABELS[source]} {counts[source]}"
        for source in SOURCE_ORDER
        if counts[source]
    )


def _v3_delta_text(delta):
    if delta is None:
        return "不可比"
    if delta > 0:
        return f"+{delta}"
    return str(delta)


def _v3_category_status(category, overview, comparison):
    if any(
        item["businessCategory"] == category
        for item in comparison.get("improvements", [])
    ):
        return "改善信号", "green"
    if any(
        item["businessCategory"] == category
        for item in comparison.get("attentionItems", [])
    ):
        return "需关注", "orange"
    delta = overview["delta"]
    if delta is None:
        return "不可比", "gray"
    if delta > 0:
        return "信号增加", "gray"
    if delta < 0:
        return "信号减少（不等于改善）", "gray"
    return "持平", "gray"


def _render_v3_category_navigation(analysis):
    comparison = analysis["weekComparison"]
    total = sum(item["currentCount"] for item in analysis["categoryOverview"])
    rows = []
    for item in analysis["categoryOverview"]:
        category = item["businessCategory"]
        status, color = _v3_category_status(category, item, comparison)
        share = f"{item['currentCount'] / total:.0%}" if total else "0%"
        rows.append(
            "<tr>"
            f"<td><b>{escape(CATEGORY_LABELS[category])}</b></td>"
            f"<td>{item['currentCount']}（{share}）</td>"
            f"<td>{escape(_v3_delta_text(item['delta']))}</td>"
            f'<td><span text-color="{color}">{escape(status)}</span></td>'
            "</tr>"
        )
    return (
        "<h1>分类导航</h1>"
        '<callout emoji="📊" background-color="light-gray" border-color="gray">'
        "<p>分类数量表示入选反馈信号量，不等同于独立需求数或产品表现；"
        f"本周待人工复核 {analysis['reviewQueue']['currentCount']} 条。</p></callout>"
        "<table><thead><tr>"
        '<th background-color="light-gray">分类</th>'
        '<th background-color="light-gray">本周（占比）</th>'
        '<th background-color="light-gray">环比</th>'
        '<th background-color="light-gray">状态</th>'
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_v3_priority_changes(analysis):
    comparison = analysis["weekComparison"]

    summary = (
        "<h2>完整分析摘要</h2><ol>"
        + "".join(
            f"<li><p>{escape(item['text'])}</p>"
            '<p><span text-color="gray">原始证据：'
            f"{_v3_evidence_links(item['evidenceRefs'], analysis, maximum=len(item['evidenceRefs']), compact=True)}｜"
            f"置信度 {escape(item['confidence'])}</span></p></li>"
            for item in analysis["summary"]
        )
        + "</ol>"
    )

    def items(values, empty_text, color):
        if not values:
            return f"<p>{empty_text}</p>"
        return "<ul>" + "".join(
            f"<li><p><b>{escape(item['title'])}</b></p>"
            f"<p>{escape(_compact_text(item['summary'], 180))}</p>"
            f'<p><span text-color="{color}">'
            f"{escape(CATEGORY_LABELS[item['businessCategory']])}｜"
            f"置信度 {escape(item['confidence'])}</span></p>"
            '<p><span text-color="gray">证据：'
            f"{_v3_evidence_links(item['evidenceRefs'], analysis, maximum=len(item['evidenceRefs']), compact=True)}"
            "</span></p></li>"
            for item in values
        ) + "</ul>"

    if comparison["status"] == "unavailable":
        return (
            "<h1>需优先关注</h1>"
            f"<p>{escape(comparison['headline'])}</p>"
            '<p><span text-color="gray">本期缺少可比基线。</span></p>'
            + summary
        )
    return (
        "<h1>需优先关注</h1>"
        "<h2>改善信号</h2>"
        + items(
            comparison["improvements"],
            "本周没有足够证据支持的改善信号。",
            "green",
        )
        + "<h2>需关注项</h2>"
        + items(
            comparison["attentionItems"],
            "本周没有足够证据支持的新增关注项。",
            "orange",
        )
        + summary
    )


def _render_v3_action_items(items, label, analysis):
    if not items:
        return ""
    rows = []
    for item in items:
        if label == "洞察":
            body = (
                f"{escape(item['observation'])}</p>"
                f"<p><b>为什么重要：</b>{escape(item['whyItMatters'])}"
            )
        else:
            body = escape(item["action"])
        rows.append(
            f"<li><p><b>{label}：{escape(item['title'])}</b></p>"
            f"<p>{body}</p>"
            '<p><span text-color="gray">'
            f"证据 {len(item['evidenceRefs'])} 条｜"
            f"{escape(_v3_source_summary(item['evidenceRefs'], analysis))}｜"
            f"置信度 {escape(item['confidence'])}</span></p>"
            '<p><span text-color="gray">原始证据：'
            f"{_v3_evidence_links(item['evidenceRefs'], analysis, maximum=len(item['evidenceRefs']), compact=True)}"
            "</span></p></li>"
        )
    return "<ul>" + "".join(rows) + "</ul>"


def _render_v3_category_sections(analysis):
    current, _previous = _v3_evidence_maps(analysis)
    classifications_by_id = {
        item["evidenceId"]: item for item in analysis["classifications"]
    }
    baseline_categories = {
        item["businessCategory"]: item for item in analysis["baselineExport"]["categories"]
    }
    overview_by_category = {
        item["businessCategory"]: item for item in analysis["categoryOverview"]
    }
    theme_owner = {
        id(item): _v3_theme_owner(item, analysis) for item in analysis["themes"]
    }
    total = sum(item["currentCount"] for item in analysis["categoryOverview"])
    sections = []
    for category in CATEGORY_ORDER:
        overview = overview_by_category[category]
        status, color = _v3_category_status(
            category, overview, analysis["weekComparison"]
        )
        share = f"{overview['currentCount'] / total:.0%}" if total else "0%"
        themes = [
            item for item in analysis["themes"] if theme_owner[id(item)] == category
        ]
        representative = baseline_categories[category]["representativeEvidence"]
        category_insights = [
            item
            for item in analysis["insights"]
            if _v3_item_categories(item, analysis) == [category]
        ]
        category_recommendations = [
            item
            for item in analysis["recommendations"]
            if _v3_item_categories(item, analysis) == [category]
        ]
        if themes:
            judgment = themes[0]["summary"]
        elif representative:
            judgment = representative[0].get("summary") or current[
                representative[0]["evidenceId"]
            ]["normalizedText"]
        else:
            judgment = "本周没有已确认的重点反馈。"
        sections.append(
            f"<h1>{escape(CATEGORY_LABELS[category])}</h1>"
            f'<callout emoji="📌" background-color="light-{color}" border-color="{color}">'
            f"<p><b>{overview['currentCount']} 条</b>｜占比 {share}｜"
            f"环比 {escape(_v3_delta_text(overview['delta']))}｜{escape(status)}</p>"
            f"<p>{escape(_compact_text(judgment, 220))}</p></callout>"
        )
        sections.append("<h2>主要主题</h2>")
        if themes:
            sections.append("<ul>")
            for item in themes:
                related = [
                    value
                    for value in item["businessCategories"]
                    if value != category
                ]
                related_text = (
                    "｜关联分类 "
                    + " / ".join(CATEGORY_LABELS[value] for value in related)
                    if related
                    else ""
                )
                sections.append(
                    f"<li><p><b>{escape(item['name'])}</b>："
                    f"{escape(item['summary'])}</p>"
                    '<p><span text-color="gray">'
                    f"证据 {len(item['evidenceRefs'])} 条｜"
                    f"{escape(_v3_source_summary(item['evidenceRefs'], analysis))}｜"
                    f"置信度 {escape(item['confidence'])}{escape(related_text)}"
                    "</span></p>"
                    '<p><span text-color="gray">原始证据：'
                    f"{_v3_evidence_links(item['evidenceRefs'], analysis, maximum=len(item['evidenceRefs']), compact=True)}"
                    "</span></p></li>"
                )
            sections.append("</ul>")
        else:
            sections.append("<p>本周没有归属于该分类的独立主题。</p>")
        sections.append("<h2>代表反馈</h2>")
        if representative:
            sections.append(
                '<table><thead><tr><th background-color="light-gray">来源</th>'
                '<th background-color="light-gray">反馈</th></tr></thead><tbody>'
            )
            for item in representative[:3]:
                record = current[item["evidenceId"]]
                classification = classifications_by_id[item["evidenceId"]]
                url = escape(record["sourceUrl"], quote=True)
                raw_title = str(record["title"]).strip()
                title = escape(raw_title)
                title_value = f'<a href="{url}">{title}</a>' if url else title
                raw_summary = str(
                    item.get("summary") or record["normalizedText"]
                ).strip()
                summary = (
                    f"<p>{escape(_compact_text(raw_summary, 180))}</p>"
                    if raw_summary.casefold() != raw_title.casefold()
                    else ""
                )
                sections.append(
                    f"<tr><td>{escape(SOURCE_LABELS[record['sourceKey']])}</td>"
                    f"<td><p><b>{title_value}</b></p>{summary}"
                    '<p><span text-color="gray">分类理由：'
                    f"{escape(classification['reason'])}</span></p></td></tr>"
                )
            if len(representative) > 3:
                sections.append(
                    '<tr><td><span text-color="gray">更多</span></td>'
                    f'<td><span text-color="gray">另有 {len(representative) - 3} 条'
                    "代表反馈，请从原始证据入口继续查看。</span></td></tr>"
                )
            sections.append("</tbody></table>")
        else:
            sections.append("<p>本周没有已确认的代表反馈。</p>")
        sections.append("<h2>产品/设计动作</h2>")
        if category_insights or category_recommendations:
            sections.append(
                _render_v3_action_items(category_insights, "洞察", analysis)
            )
            sections.append(
                _render_v3_action_items(category_recommendations, "建议", analysis)
            )
        else:
            sections.append("<p>本周没有只归属于该分类的独立动作。</p>")
        sections.append(_render_v3_category_quick_wins(category, analysis))
    return "".join(sections)


def _render_v3_cross_category_actions(analysis):
    insights = [
        item
        for item in analysis["insights"]
        if len(_v3_item_categories(item, analysis)) != 1
    ]
    recommendations = [
        item
        for item in analysis["recommendations"]
        if len(_v3_item_categories(item, analysis)) != 1
    ]
    if not insights and not recommendations:
        return "<h1>跨分类事项</h1><p>本周没有需要单独展开的跨分类事项。</p>"
    return (
        "<h1>跨分类事项</h1>"
        '<callout emoji="🎯" background-color="light-blue" border-color="blue">'
        "<p>以下事项同时影响多个分类，因此只在此处展示一次。</p></callout>"
        + _render_v3_action_items(insights, "洞察", analysis)
        + _render_v3_action_items(recommendations, "建议", analysis)
    )


def _render_v3_review_queue(analysis):
    current, _previous = _v3_evidence_maps(analysis)
    review_items = [
        item for item in analysis["classifications"] if item["decision"] == "review"
    ]
    if not review_items:
        return "<h1>待人工复核</h1><p>本周没有待人工复核反馈。</p>"
    rows = []
    for item in review_items:
        record = current[item["evidenceId"]]
        url = escape(record["sourceUrl"], quote=True)
        title = escape(record["title"])
        title_value = f'<a href="{url}">{title}</a>' if url else title
        candidates = " / ".join(
            CATEGORY_LABELS[value] for value in item["candidateCategories"]
        )
        rows.append(
            f"<li><p><b>{title_value}</b>｜候选分类：{escape(candidates)}</p>"
            f"<p>{escape(item['reason'])}</p></li>"
        )
    return (
        "<h1>待人工复核</h1>"
        '<callout emoji="🧑‍⚖️" background-color="light-orange" border-color="orange">'
        f"<p>共 {len(review_items)} 条，需要补充上下文或确认唯一主分类。</p>"
        "<ul>" + "".join(rows) + "</ul></callout>"
    )


def _render_v3_category_detail_page(analysis):
    return (
        _render_v3_category_navigation(analysis)
        + _render_v3_priority_changes(analysis)
        + _render_v3_category_sections(analysis)
        + _render_v3_cross_category_actions(analysis)
        + _render_v3_review_queue(analysis)
        + "<h1>原始证据入口</h1>"
        + '<p><span text-color="gray">完整原始反馈保留在四个来源看板中，本页只展示代表反馈与分析结论。</span></p>'
        + "<p>__SOURCE_REPORTS__</p>"
    )


def _render_v3_category_quick_wins(category, analysis):
    candidates = [
        item
        for item in analysis["quickWinCandidates"]
        if item["businessCategory"] == category
    ]
    heading = f"<h2>Quick Win 候选（{len(candidates)}）</h2>"
    if not candidates:
        return heading + "<p>本分类没有同时满足三项标准的候选。</p>"
    rows = []
    for item in candidates:
        candidate_id = _quick_win_candidate_id(item)
        rows.append(
            "<tr>"
            '<td vertical-align="top">'
            f'<checkbox done="false">[{candidate_id}]</checkbox>'
            "</td>"
            '<td vertical-align="top">'
            f"<p><b>{escape(item['title'])}</b></p>"
            f"<p>{escape(_compact_text(item['summary'], 180))}</p>"
            "</td>"
            '<td vertical-align="top">'
            f"<p>{escape(_compact_text(item['whyQuickWin'], 220))}</p>"
            '<p><span text-color="gray">诉求明确 ✓｜范围集中 ✓｜预估改动较小 ✓</span></p>'
            '<p><span text-color="gray">'
            f"{escape(_v3_source_summary(item['evidenceRefs'], analysis))}｜"
            f"置信度 {escape(item['confidence'])}</span></p>"
            "</td>"
            '<td vertical-align="top"><p>'
            f"{_v3_evidence_links(item['evidenceRefs'], analysis, maximum=len(item['evidenceRefs']), compact=True)}"
            "</p></td>"
            "</tr>"
        )
    return (
        heading
        + '<p><span text-color="gray">勾选表示进入后续需求评审；本阶段不会自动创建 Jira。</span></p>'
        + '<table><colgroup><col width="130"/><col width="220"/>'
        + '<col width="300"/><col width="180"/></colgroup><thead><tr>'
        + '<th background-color="light-gray">勾选</th>'
        + '<th background-color="light-gray">候选</th>'
        + '<th background-color="light-gray">入选判断</th>'
        + '<th background-color="light-gray">原始证据</th>'
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _quick_win_candidate_id(candidate):
    evidence_ids = sorted(
        str(ref["evidenceId"]).strip() for ref in candidate["evidenceRefs"]
    )
    identity = "\n".join(
        [str(candidate["businessCategory"]).strip(), *evidence_ids]
    )
    return f"QW-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:8].upper()}"


def _quick_win_source_counts(analysis):
    current, _previous = _v3_evidence_maps(analysis)
    counts = {source: 0 for source in SOURCE_ORDER}
    for candidate in analysis["quickWinCandidates"]:
        sources = {
            current[ref["evidenceId"]]["sourceKey"]
            for ref in candidate["evidenceRefs"]
        }
        for source in sources:
            counts[source] += 1
    return counts


def _render_v3_quick_wins(analysis):
    candidates = analysis["quickWinCandidates"]
    screened_counts = "、".join(
        f"{SOURCE_LABELS[item['sourceKey']]} {item['includedCount']}"
        for item in analysis["_analysisInput"]["currentSourceRuns"]
    )
    selected_by_source = _quick_win_source_counts(analysis)
    selected_counts = "、".join(
        f"{SOURCE_LABELS[source]} {selected_by_source[source]}"
        for source in SOURCE_ORDER
    )
    category_counts = {category: 0 for category in CATEGORY_ORDER}
    for item in candidates:
        category_counts[item["businessCategory"]] += 1
    category_rows = "".join(
        "<tr>"
        f"<td>{escape(CATEGORY_LABELS[category])}</td>"
        f"<td>{category_counts[category]}</td>"
        "</tr>"
        for category in CATEGORY_ORDER
    )
    return (
        "<h1>Quick Win 候选</h1>"
        '<callout emoji="⚡" background-color="light-yellow" border-color="yellow">'
        f"<p>已逐条筛选四源全部 {len(analysis['quickWinAssessments'])} 条反馈："
        f"{escape(screened_counts)}；共归并出 <b>{len(candidates)}</b> 个候选。</p>"
        f"<p><b>候选来源覆盖：</b>{escape(selected_counts)}。</p>"
        "<p>候选同时满足诉求明确、范围集中、预估改动较小；实际成本仍需产品和工程确认。</p>"
        "</callout>"
        "<table><thead><tr>"
        '<th background-color="light-gray">分类</th>'
        '<th background-color="light-gray">候选数</th>'
        "</tr></thead><tbody>"
        + category_rows
        + "</tbody></table>"
        '<p><span text-color="gray">请在分类与主题明细中结合问题、证据和建议动作，'
        "就地勾选对应候选。</span></p>"
        + CATEGORY_DETAIL_PLACEHOLDER
    )


def _render_v3_sources(snapshot, analysis):
    source_rows = []
    for item in snapshot["sources"]:
        ready = item["status"] == "ready"
        if ready and int(item.get("included") or 0) > 0:
            status = "已采集"
        elif ready:
            status = "无入选数据"
        else:
            status = "未提供"
        color = "green" if ready else "orange"
        collected = item["collected"] if ready else "—"
        included = item["included"] if ready else "—"
        source_rows.append(
            "<tr>"
            f"<td>{escape(SOURCE_LABELS[item['sourceKey']])}</td>"
            f'<td><span text-color="{color}">{status}</span></td>'
            f"<td>{collected}</td><td>{included}</td>"
            f"<td>{escape(item['breakdown'])}</td>"
            f"<td>{escape(item['coverage'])}</td>"
            "</tr>"
        )
    return (
        "<h1>原始证据</h1><h2>四源数据概览</h2>"
        "<table><thead><tr>"
        '<th background-color="light-gray">数据源</th>'
        '<th background-color="light-gray">状态</th>'
        '<th background-color="light-gray">周期采集</th>'
        '<th background-color="light-gray">看板入选</th>'
        '<th background-color="light-gray">关键构成</th>'
        '<th background-color="light-gray">覆盖口径</th>'
        "</tr></thead><tbody>" + "".join(source_rows) + "</tbody></table>"
        "<h2>原始来源入口</h2><p>__SOURCE_REPORTS__</p>"
        "<h2>口径说明</h2>"
        f"<p>看板规则版本：{DASHBOARD_RULE_VERSION}；分析规则版本："
        f"{escape(analysis['analysisRule'])}。总数按来源相加，尚未进行跨渠道语义去重，"
        "不能解释为独立需求数；Facebook 仅代表 Slack 频道已汇总内容。</p>"
    )


def _render_v3_summary_header(snapshot, analysis):
    period = snapshot["period"]
    scope_text = snapshot["squad"] or snapshot["domain"]
    comparison = analysis["weekComparison"]
    if comparison["status"] == "available":
        previous_total = sum(
            item["previousCount"] or 0 for item in analysis["categoryOverview"]
        ) + int(analysis["reviewQueue"]["previousCount"] or 0)
        delta_text = f"{snapshot['totalSignals'] - previous_total:+d}"
    else:
        delta_text = "不可比"
    metrics = (
        ("本周信号", snapshot["totalSignals"]),
        ("较上周", delta_text),
        ("改善信号", len(comparison["improvements"])),
        ("需关注", len(comparison["attentionItems"])),
        ("Quick Win", len(analysis["quickWinCandidates"])),
    )
    headers = "".join(
        f'<th background-color="light-gray">{escape(label)}</th>'
        for label, _value in metrics
    )
    values = "".join(f"<td><b>{escape(str(value))}</b></td>" for _label, value in metrics)
    return (
        '<callout emoji="📊" background-color="light-blue" border-color="blue">'
        f"<p><b>{escape(scope_text)}</b>｜{period['start']} 至 {period['end']}</p>"
        f"<p>{escape(_compact_text(comparison['headline'], 180))}</p></callout>"
        f"<table><thead><tr>{headers}</tr></thead><tbody><tr>{values}</tr></tbody></table>"
    )


def render_dashboard_detail_documents(snapshot, week_title, analysis=None):
    if not analysis or analysis.get("schemaVersion") != 3:
        return []
    titles = dashboard_detail_titles(week_title)
    scope_text = snapshot["squad"] or snapshot["domain"]
    period = snapshot["period"]
    category_owner = _dashboard_detail_ownership_marker(snapshot, "category-analysis")
    category_content = (
        f"<title>{escape(titles['category'])}</title>"
        f'<p><span text-color="gray">{escape(DASHBOARD_DETAIL_MARKER)}</span></p>'
        f'<p><span text-color="gray">{escape(category_owner)}</span></p>'
        '<callout emoji="🔍" background-color="light-blue" border-color="blue">'
        f"<p><b>{escape(scope_text)}</b>｜{period['start']} 至 {period['end']}｜"
        "按分类查看本周变化、主要主题、代表反馈、产品/设计动作，并就地勾选 Quick Win。"
        "</p></callout>"
        + _render_v3_category_detail_page(analysis)
    )
    return [
        {
            "key": "category",
            "title": titles["category"],
            "placeholder": CATEGORY_DETAIL_PLACEHOLDER,
            "content": category_content,
            "ownershipMarker": category_owner,
            "markers": [
                DASHBOARD_DETAIL_MARKER,
                category_owner,
                "分类导航",
                "Quick Win 候选",
            ],
        },
    ]


def render_dashboard_detail_preview(content, detail_documents):
    preview = content
    for document in detail_documents:
        preview = preview.replace(
            document["placeholder"],
            f'<p><b>明细子文档：</b>{escape(document["title"])}</p>',
        )
    return preview


def _render_dashboard_weekly_v3(snapshot, week_title, analysis):
    return (
        f"<title>{escape(week_title)}</title>"
        f'<p><span text-color="gray">{escape(DASHBOARD_MARKER)}</span></p>'
        + _render_v3_comparison(snapshot, analysis)
        + "<h1>本周反馈概览</h1>"
        + _render_v3_category_overview(analysis)
        + _render_v3_product_design_focus(analysis)
        + _render_v3_quick_wins(analysis)
        + _render_v3_sources(snapshot, analysis)
    )


def render_dashboard_weekly(snapshot, week_title, analysis=None):
    if analysis and analysis.get("schemaVersion") == 3:
        return _render_dashboard_weekly_v3(snapshot, week_title, analysis)
    source_rows = []
    for item in snapshot["sources"]:
        ready = item["status"] == "ready"
        status = (
            "已采集"
            if ready and int(item.get("included") or 0) > 0
            else "无入选数据"
            if ready
            else "未提供"
        )
        color = "green" if ready else "orange"
        collected = item["collected"] if ready else "—"
        included = item["included"] if ready else "—"
        source_rows.append(
            "<tr>"
            f"<td>{escape(SOURCE_LABELS[item['sourceKey']])}</td>"
            f'<td><span text-color="{color}">{status}</span></td>'
            f"<td>{collected}</td>"
            f"<td>{included}</td>"
            f"<td>{escape(item['breakdown'])}</td>"
            f"<td>{escape(item['coverage'])}</td>"
            "</tr>"
        )
    period = snapshot["period"]
    scope_text = snapshot["squad"] or snapshot["domain"]
    return (
        f"<title>{escape(week_title)}</title>"
        f'<p><span text-color="gray">{escape(DASHBOARD_MARKER)}</span></p>'
        "<h1>本周总览</h1>"
        '<callout emoji="📊" background-color="light-blue" border-color="blue">'
        f"<p><b>{escape(scope_text)}</b>｜{period['start']} 至 {period['end']}｜"
        f"共 {snapshot['totalSignals']} 条入选信号。</p>"
        "<p>总数按来源相加，尚未进行跨渠道语义去重，不能解释为独立需求数。</p>"
        "</callout>"
        "<table><thead><tr>"
        '<th background-color="light-gray">数据源</th>'
        '<th background-color="light-gray">状态</th>'
        '<th background-color="light-gray">周期采集</th>'
        '<th background-color="light-gray">看板入选</th>'
        '<th background-color="light-gray">关键构成</th>'
        '<th background-color="light-gray">覆盖口径</th>'
        "</tr></thead><tbody>" + "".join(source_rows) + "</tbody></table>"
        + _render_analysis(analysis, snapshot.get("records") or [])
        + _render_featured(analysis, snapshot.get("records") or [])
        + "<h1>源周报入口</h1><p>__SOURCE_REPORTS__</p>"
        + "<h1>口径说明</h1>"
        + f"<p>看板规则版本：{DASHBOARD_RULE_VERSION}。缺少 manifest 的来源显示“未提供”，"
        + "不记作 0；Facebook 仅代表 Slack 频道已汇总内容。</p>"
    )
