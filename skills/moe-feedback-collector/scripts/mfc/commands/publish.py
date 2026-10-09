from __future__ import annotations

from ..dashboard import DASHBOARD_MARKER, dashboard_titles
from ..errors import ConfigError
from ..lark import LarkWeeklyPublisher
from ..report import (
    CANNY_MANAGED_CHILD_MARKER,
    FACEBOOK_PUBLISH_RULE_VERSION,
    INTERCOM_MANAGED_CHILD_MARKER,
    INTERCOM_PUBLISH_RULE_VERSION,
    JIRA_MANAGED_CHILD_MARKER,
    JIRA_PUBLISH_RULE_VERSION,
    apply_quick_win_rule,
    attach_managed_source_marker,
    canny_manifest_period,
    choose_report_rows,
    facebook_manifest_period,
    facebook_report_titles,
    intercom_manifest_period,
    intercom_report_titles,
    jira_manifest_period,
    jira_report_titles,
    load_facebook_run,
    load_quick_win_review,
    load_run,
    managed_source_ownership_marker,
    managed_source_run_marker,
    parse_period,
    render_facebook_weekly_report,
    render_intercom_source_documents,
    render_intercom_weekly_report,
    render_jira_source_documents,
    render_jira_weekly_report,
    render_source_documents,
    render_weekly_report,
    report_titles,
    select_facebook_rows,
    select_intercom_rows,
    select_jira_rows,
)


def register(subparsers):
    parser = subparsers.add_parser("publish", help="发布反馈飞书周报")
    parser.add_argument(
        "--source", required=True, choices=["canny", "intercom", "jira", "facebook"]
    )
    parser.add_argument("--manifest", required=True, help="采集 manifest 路径")
    parser.add_argument(
        "--quick-win-review", default="", help="Canny 必填：AI Quick Win 复筛 JSON"
    )
    parser.add_argument("--period-start", default="", help="周期开始 YYYY-MM-DD")
    parser.add_argument("--period-end", default="", help="周期结束 YYYY-MM-DD")
    parser.add_argument(
        "--allow-partial-period",
        action="store_true",
        help="允许周一开始、同一自然周内少于 7 天的周期",
    )
    parser.add_argument(
        "--month-segment",
        default="",
        help="允许目标自然月与所在 ISO 周的精确边界交集，格式 YYYY-MM",
    )
    parser.add_argument("--dry-run", action="store_true", help="只渲染，不写飞书")
    parser.set_defaults(_handler=run)


def _run_canny(args, config):
    if not args.quick_win_review:
        raise ConfigError("Canny publish 必须提供 --quick-win-review")
    manifest, posts, report_rows = load_run(args.manifest)
    if manifest.get("sourceKey") != "canny":
        raise ConfigError("--source canny 与 manifest 数据源不一致")
    manifest_start, manifest_end = canny_manifest_period(manifest)
    start, end = parse_period(
        args.period_start or manifest_start.isoformat(),
        args.period_end or manifest_end.isoformat(),
        allow_partial_period=getattr(args, "allow_partial_period", False),
        month_segment=getattr(args, "month_segment", ""),
    )
    weekly_rows = apply_quick_win_rule(
        choose_report_rows(manifest, posts, report_rows, start, end)
    )
    prefiltered = [item for item in weekly_rows if item.get("quickWinPrefilter")]
    decisions = load_quick_win_review(args.quick_win_review, prefiltered)
    year_title, month_title, week_title = report_titles(start, end)
    scope = str(config.squad or config.feedback_domain or "").strip()
    if not scope:
        raise ConfigError("Canny publish 需要 MFC_SQUAD 或 MFC_DOMAIN 作为周目录范围")
    _year, _month, week_container_title = dashboard_titles(start, end, scope)
    use_source_documents = len(weekly_rows) > 50
    source_documents = (
        render_source_documents(
            weekly_rows,
            week_title,
            label="本期新增",
        )
        if use_source_documents
        else []
    )
    content = render_weekly_report(
        manifest=manifest,
        weekly_rows=weekly_rows,
        decisions=decisions,
        start=start,
        end=end,
        week_title=week_title,
        source_documents=use_source_documents,
    )
    source_marker = managed_source_run_marker(
        "canny", start, end, manifest.get("runId")
    )
    source_ownership_marker = managed_source_ownership_marker(
        "canny", start, end
    )
    content = attach_managed_source_marker(content, source_marker)
    result = {
        "ok": True,
        "source": "canny",
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "title": week_title,
        "counts": {
            "weeklySourceRows": len(weekly_rows),
            "quickWinPrefilter": len(prefiltered),
            "quickWinSelected": len(decisions),
            "sourceDocuments": len(source_documents),
        },
        "dryRun": bool(args.dry_run),
    }
    if args.dry_run:
        result["content"] = content
        if source_documents:
            result["childDocuments"] = source_documents
        return result

    publication = LarkWeeklyPublisher(config).publish(
        year_title=year_title,
        month_title=month_title,
        week_container_title=week_container_title,
        source_title=week_title,
        content=content,
        markers=[source_marker, week_title, "Quick Win 候选", "Canny 源数据"],
        managed_week_marker=DASHBOARD_MARKER,
        child_documents=source_documents,
        source_marker=source_marker,
        source_ownership_marker=source_ownership_marker,
        managed_child_prefix="源数据｜",
        managed_child_marker=CANNY_MANAGED_CHILD_MARKER,
    )
    result["publication"] = publication
    return result


def _run_intercom(args, config):
    if args.quick_win_review:
        raise ConfigError("Intercom publish 不接受 --quick-win-review")
    manifest, feedback, _report_rows = load_run(args.manifest, object_type="feedback")
    manifest_start, manifest_end = intercom_manifest_period(manifest)
    start, end = parse_period(
        args.period_start or manifest_start.isoformat(),
        args.period_end or manifest_end.isoformat(),
        allow_partial_period=getattr(args, "allow_partial_period", False),
        month_segment=getattr(args, "month_segment", ""),
    )
    rows, counts = select_intercom_rows(
        manifest,
        feedback,
        config.squad,
        start,
        end,
    )
    year_title, month_title, week_title = intercom_report_titles(
        start, end, config.squad
    )
    _year, _month, week_container_title = dashboard_titles(
        start, end, config.squad
    )
    use_source_documents = len(rows) > 50
    source_documents = (
        render_intercom_source_documents(rows, week_title, config.squad)
        if use_source_documents
        else []
    )
    content = render_intercom_weekly_report(
        rows=rows,
        counts=counts,
        squad=config.squad,
        start=start,
        end=end,
        week_title=week_title,
        source_documents=use_source_documents,
    )
    source_marker = managed_source_run_marker(
        "intercom", start, end, manifest.get("runId")
    )
    source_ownership_marker = managed_source_ownership_marker(
        "intercom", start, end
    )
    content = attach_managed_source_marker(content, source_marker)
    result = {
        "ok": True,
        "source": "intercom",
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "title": week_title,
        "filter": {
            "squad": config.squad,
            "feedbackTypes": ["feature_feedback", "feature_request"],
            "ruleVersion": INTERCOM_PUBLISH_RULE_VERSION,
        },
        "counts": {
            **counts,
            "sourceDocuments": len(source_documents),
        },
        "dryRun": bool(args.dry_run),
    }
    if args.dry_run:
        result["content"] = content
        if source_documents:
            result["childDocuments"] = source_documents
        return result

    publication = LarkWeeklyPublisher(config).publish(
        year_title=year_title,
        month_title=month_title,
        week_container_title=week_container_title,
        source_title=week_title,
        content=content,
        markers=[source_marker, week_title, "功能反馈", "功能需求", config.squad],
        managed_week_marker=DASHBOARD_MARKER,
        child_documents=source_documents,
        source_marker=source_marker,
        source_ownership_marker=source_ownership_marker,
        managed_child_prefix=f"Intercom｜{config.squad.strip()}｜",
        managed_child_marker=INTERCOM_MANAGED_CHILD_MARKER,
    )
    result["publication"] = publication
    return result


def _run_jira(args, config):
    if args.quick_win_review:
        raise ConfigError("Jira publish 不接受 --quick-win-review")
    manifest, feedback, scope_rows = load_run(args.manifest, object_type="feedback")
    manifest_start, manifest_end = jira_manifest_period(manifest)
    start, end = parse_period(
        args.period_start or manifest_start.isoformat(),
        args.period_end or manifest_end.isoformat(),
        allow_partial_period=getattr(args, "allow_partial_period", False),
        month_segment=getattr(args, "month_segment", ""),
    )
    rows, review_rows, excluded_rows, counts = select_jira_rows(
        manifest,
        feedback,
        scope_rows,
        config.squad,
        start,
        end,
    )
    year_title, month_title, week_title = jira_report_titles(
        start, end, config.squad
    )
    _year, _month, week_container_title = dashboard_titles(
        start, end, config.squad
    )
    use_source_documents = len(rows) > 50
    source_documents = (
        render_jira_source_documents(rows, week_title, config.squad)
        if use_source_documents
        else []
    )
    content = render_jira_weekly_report(
        rows=rows,
        review_rows=review_rows,
        excluded_rows=excluded_rows,
        counts=counts,
        squad=config.squad,
        start=start,
        end=end,
        week_title=week_title,
        source_documents=use_source_documents,
    )
    source_marker = managed_source_run_marker(
        "jira", start, end, manifest.get("runId")
    )
    source_ownership_marker = managed_source_ownership_marker(
        "jira", start, end
    )
    content = attach_managed_source_marker(content, source_marker)
    result = {
        "ok": True,
        "source": "jira",
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "title": week_title,
        "filter": {
            "squad": config.squad,
            "project": "CS",
            "featureRequestIssueType": "Feature Request",
            "designTarget": {"project": "DES", "issueType": "Design Issue"},
            "scope": "Grooming Squad exact OR explicit Grooming/groomer semantics",
            "weakSignals": "shared components -> manual review",
            "conflictingSignals": "strong scope + non-Grooming service -> manual review",
            "ruleVersion": JIRA_PUBLISH_RULE_VERSION,
        },
        "counts": {
            **counts,
            "sourceDocuments": len(source_documents),
        },
        "dryRun": bool(args.dry_run),
    }
    if args.dry_run:
        result["content"] = content
        if source_documents:
            result["childDocuments"] = source_documents
        return result

    publication = LarkWeeklyPublisher(config).publish(
        year_title=year_title,
        month_title=month_title,
        week_container_title=week_container_title,
        source_title=week_title,
        content=content,
        markers=[
            source_marker,
            week_title,
            "功能需求",
            "关联设计单反馈",
            "待人工复核",
            "范围排除审计",
            config.squad,
        ],
        managed_week_marker=DASHBOARD_MARKER,
        child_documents=source_documents,
        source_marker=source_marker,
        source_ownership_marker=source_ownership_marker,
        managed_child_prefix=f"Jira｜{config.squad.strip()}｜",
        managed_child_marker=JIRA_MANAGED_CHILD_MARKER,
    )
    result["publication"] = publication
    return result


def _run_facebook(args, config):
    if args.quick_win_review:
        raise ConfigError("Facebook publish 不接受 --quick-win-review")
    manifest, feedback, _report_rows = load_facebook_run(args.manifest)
    manifest_start, manifest_end = facebook_manifest_period(manifest)
    start, end = parse_period(
        args.period_start or manifest_start.isoformat(),
        args.period_end or manifest_end.isoformat(),
        allow_partial_period=getattr(args, "allow_partial_period", False),
        month_segment=getattr(args, "month_segment", ""),
    )
    rows, counts = select_facebook_rows(
        manifest,
        feedback,
        config.feedback_domain,
        start,
        end,
    )
    year_title, month_title, week_title = facebook_report_titles(
        start, end, config.feedback_domain
    )
    _year, _month, week_container_title = dashboard_titles(
        start, end, str(config.squad or config.feedback_domain).strip()
    )
    content = render_facebook_weekly_report(
        rows=rows,
        counts=counts,
        domain=config.feedback_domain,
        start=start,
        end=end,
        week_title=week_title,
    )
    source_marker = managed_source_run_marker(
        "facebook", start, end, manifest.get("runId")
    )
    source_ownership_marker = managed_source_ownership_marker(
        "facebook", start, end
    )
    content = attach_managed_source_marker(content, source_marker)
    result = {
        "ok": True,
        "source": "facebook",
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "title": week_title,
        "filter": {
            "domain": config.feedback_domain,
            "coverage": "channel-summary",
            "ruleVersion": FACEBOOK_PUBLISH_RULE_VERSION,
        },
        "counts": counts,
        "dryRun": bool(args.dry_run),
    }
    if args.dry_run:
        result["content"] = content
        return result

    publication = LarkWeeklyPublisher(config).publish(
        year_title=year_title,
        month_title=month_title,
        week_container_title=week_container_title,
        source_title=week_title,
        content=content,
        markers=[source_marker, week_title, "频道汇总反馈", "channel-summary"],
        managed_week_marker=DASHBOARD_MARKER,
        source_marker=source_marker,
        source_ownership_marker=source_ownership_marker,
    )
    result["publication"] = publication
    return result


def run(args, config):
    if args.source == "facebook":
        return _run_facebook(args, config)
    if args.source == "jira":
        return _run_jira(args, config)
    if args.source == "intercom":
        return _run_intercom(args, config)
    return _run_canny(args, config)
