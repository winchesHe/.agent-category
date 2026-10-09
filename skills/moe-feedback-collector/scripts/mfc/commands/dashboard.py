from __future__ import annotations

from ..analysis_v3 import load_weekly_analysis_v3
from ..dashboard import (
    DASHBOARD_DETAIL_MARKER,
    DASHBOARD_MARKER,
    build_dashboard_snapshot,
    dashboard_titles,
    load_weekly_analysis,
    render_dashboard_detail_documents,
    render_dashboard_detail_preview,
    render_dashboard_weekly,
    weekly_analysis_schema_version,
)
from ..errors import ConfigError
from ..lark import LarkWeeklyPublisher
from ..report import parse_period


def register(subparsers):
    parser = subparsers.add_parser("dashboard", help="发布全渠道反馈总看板")
    parser.add_argument(
        "--manifest",
        action="append",
        required=True,
        help="采集 manifest 路径；可重复传入多个数据源",
    )
    parser.add_argument(
        "--quick-win-review",
        default="",
        help="仅 schema v2 使用：Canny AI Quick Win 复筛 JSON；v3+ 由四源 analysis 统一筛选",
    )
    parser.add_argument("--analysis", default="", help="周度 AI analysis JSON")
    parser.add_argument(
        "--analysis-input",
        default="",
        help="weekly-analysis v3 对应的规范化输入 JSON",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="仅 dry-run：允许缺少来源或 AI analysis",
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


def run(args, config):
    if args.allow_partial and not args.dry_run:
        raise ConfigError("--allow-partial 只能与 --dry-run 一起使用")
    start, end = parse_period(
        args.period_start,
        args.period_end,
        allow_partial_period=getattr(args, "allow_partial_period", False),
        month_segment=getattr(args, "month_segment", ""),
    )
    scope = str(config.squad or config.feedback_domain or "").strip()
    if not scope:
        raise ConfigError("总看板需要 MFC_SQUAD 或 MFC_DOMAIN 作为稳定范围")
    analysis_version = (
        weekly_analysis_schema_version(args.analysis) if args.analysis else None
    )
    analysis_input = getattr(args, "analysis_input", "")
    if analysis_version == 2 and analysis_input:
        raise ConfigError("schemaVersion 2 的周度 AI analysis 不使用 --analysis-input")
    snapshot = build_dashboard_snapshot(
        args.manifest,
        squad=config.squad,
        domain=config.feedback_domain,
        start=start,
        end=end,
        quick_win_review=(
            args.quick_win_review if analysis_version != 3 else ""
        ),
        require_quick_win_review=analysis_version != 3,
        include_analysis_fields=analysis_version == 3,
    )
    if snapshot["missingSources"] and not args.allow_partial:
        raise ConfigError(
            "正式周总览必须包含四个来源，当前缺少："
            + ", ".join(snapshot["missingSources"])
        )
    is_month_segment = bool(str(getattr(args, "month_segment", "")).strip())
    if snapshot["emptySources"] and not args.allow_partial and not is_month_segment:
        raise ConfigError(
            "正式周总览要求四个来源均有入选数据，当前无数据："
            + ", ".join(snapshot["emptySources"])
        )
    if not args.analysis and not args.allow_partial:
        raise ConfigError("正式周总览必须提供 --analysis")
    if analysis_version == 3:
        analysis = load_weekly_analysis_v3(
            args.analysis, analysis_input, snapshot, scope=scope
        )
    elif analysis_version == 2:
        analysis = load_weekly_analysis(args.analysis, snapshot, scope=scope)
    else:
        analysis = None
    year_title, month_title, week_title = dashboard_titles(start, end, scope)
    content = render_dashboard_weekly(snapshot, week_title, analysis)
    detail_documents = render_dashboard_detail_documents(
        snapshot, week_title, analysis
    )
    expected_report_titles = {
        item["sourceKey"]: item["reportTitle"]
        for item in snapshot["sources"]
        if item.get("reportTitle")
    }
    if analysis_version == 3:
        featured_count = len(analysis["featuredEvidenceRefs"])
    elif analysis:
        featured_count = len(analysis["featuredEvidenceIds"])
    else:
        featured_count = 0
    result = {
        "ok": True,
        "period": snapshot["period"],
        "scope": scope,
        "title": week_title,
        "weekTitle": week_title,
        "counts": {
            "totalSignals": snapshot["totalSignals"],
            "providedSources": len(snapshot["providedSources"]),
            "missingSources": len(snapshot["missingSources"]),
            "emptySources": len(snapshot["emptySources"]),
        },
        "sources": snapshot["sources"],
        "analysis": {
            "provided": bool(analysis),
            "themes": len(analysis["themes"]) if analysis else 0,
            "featured": featured_count,
            "insights": len(analysis["insights"]) if analysis else 0,
            "recommendations": len(analysis["recommendations"]) if analysis else 0,
            "quickWinCandidates": (
                len(analysis["quickWinCandidates"])
                if analysis_version == 3
                else 0
            ),
        },
        "dryRun": bool(args.dry_run),
    }
    if args.dry_run:
        preview_content = render_dashboard_detail_preview(content, detail_documents)
        result["content"] = preview_content
        result["detailDocuments"] = [
            {
                "key": item["key"],
                "title": item["title"],
                "content": item["content"],
            }
            for item in detail_documents
        ]
        result["readability"] = {
            "parentCharacters": len(preview_content),
            "detailCharacters": {
                item["key"]: len(item["content"]) for item in detail_documents
            },
        }
        result["expectedSourceReports"] = expected_report_titles
        return result

    if analysis_version == 3:
        markers = [
            week_title,
            DASHBOARD_MARKER,
            "周环比",
            "本周反馈概览",
            "产品/设计关注点",
            "Quick Win 候选",
            "原始证据",
        ]
    else:
        markers = [
            week_title,
            DASHBOARD_MARKER,
            "本周总览",
            "本周 AI 摘要",
            "跨渠道主题",
            "重点反馈",
            "AI 洞察",
            "建议动作",
            "源周报入口",
        ]
    result["publication"] = LarkWeeklyPublisher(config).publish_dashboard(
        year_title=year_title,
        month_title=month_title,
        week_title=week_title,
        content=content,
        markers=markers,
        managed_marker=DASHBOARD_MARKER,
        source_reports=snapshot["sources"],
        child_documents=detail_documents,
        managed_child_marker=(
            DASHBOARD_DETAIL_MARKER if detail_documents else None
        ),
        allow_empty_sources=is_month_segment,
    )
    return result
