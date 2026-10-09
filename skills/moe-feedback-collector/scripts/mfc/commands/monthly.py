from __future__ import annotations

from ..dashboard import DASHBOARD_MARKER
from ..errors import ConfigError
from ..lark import LarkWeeklyPublisher
from ..monthly import (
    build_monthly_analysis,
    build_monthly_analysis_input,
    build_monthly_audit,
    build_monthly_prompt_artifact,
    load_monthly_analysis,
    load_monthly_input,
    monthly_managed_marker,
    monthly_title,
    render_monthly_dashboard,
)


def _add_month_arguments(parser):
    parser.add_argument("--month", required=True, help="目标月份 YYYY-MM")
    parser.add_argument(
        "--exclude-date",
        action="append",
        default=[],
        help="显式覆盖例外日期 YYYY-MM-DD；只能连续排除月末日期",
    )


def register(subparsers):
    audit = subparsers.add_parser(
        "monthly-audit", help="只读审计月度周总览覆盖情况"
    )
    _add_month_arguments(audit)
    audit.set_defaults(_handler=run_audit)

    analysis_input = subparsers.add_parser(
        "monthly-analysis-input", help="构建月度语义分析输入"
    )
    _add_month_arguments(analysis_input)
    analysis_input.add_argument(
        "--analysis",
        action="append",
        required=True,
        help="已发布周总览对应的 weekly-analysis v3；按周重复传入",
    )
    analysis_input.set_defaults(_handler=run_analysis_input)

    prompt = subparsers.add_parser(
        "monthly-analysis-prompt", help="生成一次性月度语义分析提示"
    )
    prompt.add_argument("--input", required=True, help="月度分析输入 JSON")
    prompt.set_defaults(_handler=run_prompt)

    build = subparsers.add_parser(
        "monthly-analysis-build", help="校验模型输出并构建月度 analysis"
    )
    build.add_argument("--input", required=True, help="月度分析输入 JSON")
    build.add_argument("--model-output", required=True, help="模型输出 JSON")
    build.set_defaults(_handler=run_build)

    dashboard = subparsers.add_parser(
        "monthly-dashboard", help="预览或发布月度反馈重点汇总"
    )
    dashboard.add_argument("--input", required=True, help="月度分析输入 JSON")
    dashboard.add_argument("--analysis", required=True, help="月度 analysis JSON")
    dashboard.add_argument("--dry-run", action="store_true", help="只渲染，不写飞书")
    dashboard.add_argument(
        "--adopt-existing-hash",
        default="",
        help="受控接管同名未托管月页时，必须提供 audit 返回的正文 SHA-256",
    )
    dashboard.set_defaults(_handler=run_dashboard)


def _scope(config):
    value = str(config.squad or config.feedback_domain or "").strip()
    if not value:
        raise ConfigError("月度汇总需要 MFC_SQUAD 或 MFC_DOMAIN 作为稳定范围")
    return value


def _live_audit(config, month, scope, excluded_dates):
    publisher = LarkWeeklyPublisher(config)
    inspected = publisher.inspect_month(
        year_title=month[:4],
        month_title=month[5:7],
        scope=scope,
        weekly_marker=DASHBOARD_MARKER,
        monthly_title=monthly_title(month, scope),
    )
    audit = build_monthly_audit(
        month,
        scope,
        inspected["weeklyPages"],
        excluded_dates=excluded_dates,
    )
    audit["monthlyPage"] = inspected["monthlyPage"]
    return audit


def run_audit(args, config):
    return _live_audit(config, args.month, _scope(config), args.exclude_date)


def run_analysis_input(args, config):
    audit = _live_audit(config, args.month, _scope(config), args.exclude_date)
    return build_monthly_analysis_input(args.analysis, audit)


def run_prompt(args, _config):
    return build_monthly_prompt_artifact(args.input)


def run_build(args, _config):
    return build_monthly_analysis(args.input, args.model_output)


def run_dashboard(args, config):
    input_payload = load_monthly_input(args.input)
    analysis = load_monthly_analysis(args.analysis, input_payload)
    content = render_monthly_dashboard(input_payload, analysis)
    title = monthly_title(input_payload["month"], input_payload["scope"])
    marker = monthly_managed_marker(
        input_payload["month"], input_payload["scope"], input_payload["inputHash"]
    )
    result = {
        "ok": True,
        "month": input_payload["month"],
        "scope": input_payload["scope"],
        "title": title,
        "coverage": input_payload["coverage"],
        "counts": input_payload["deterministicTotals"],
        "weeklyReports": [
            {
                "segmentId": item["segmentId"],
                "title": item["title"],
                "url": item["page"]["url"],
            }
            for item in input_payload["weeklySegments"]
        ],
        "dryRun": bool(args.dry_run),
    }
    if args.dry_run:
        result["content"] = content
        return result
    result["publication"] = LarkWeeklyPublisher(config).publish_monthly(
        year_title=input_payload["month"][:4],
        month_title=input_payload["month"][5:7],
        title=title,
        content=content,
        markers=[
            "本月结论",
            "本月最重要的三件事",
            "周度脉络",
            "分类与 Quick Win",
            "周报入口与口径",
        ],
        monthly_marker=marker,
        weekly_marker=DASHBOARD_MARKER,
        weekly_pages=[item["page"] for item in input_payload["weeklySegments"]],
        adopt_existing_hash=args.adopt_existing_hash,
    )
    return result
