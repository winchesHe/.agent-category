from __future__ import annotations

from ..analysis_input import build_weekly_analysis_input
from ..errors import ConfigError
from ..report import parse_period


def register(subparsers):
    parser = subparsers.add_parser(
        "analysis-input",
        help="生成本周 AI 语义分析输入",
    )
    parser.add_argument(
        "--manifest",
        action="append",
        required=True,
        help="本周采集 manifest 路径；必须精确提供四个数据源",
    )
    parser.add_argument(
        "--previous-analysis",
        default="",
        help="可选：紧邻上周已校验并发布的 weekly-analysis v3 JSON",
    )
    parser.add_argument("--period-start", default="", help="本周开始 YYYY-MM-DD")
    parser.add_argument("--period-end", default="", help="本周结束 YYYY-MM-DD")
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
    parser.set_defaults(_handler=run)


def run(args, config):
    start, end = parse_period(
        args.period_start,
        args.period_end,
        allow_partial_period=getattr(args, "allow_partial_period", False),
        month_segment=getattr(args, "month_segment", ""),
    )
    scope = str(config.squad or config.feedback_domain or "").strip()
    if not scope:
        raise ConfigError("AI 分析输入需要 MFC_SQUAD 或 MFC_DOMAIN 作为稳定范围")
    return build_weekly_analysis_input(
        args.manifest,
        squad=config.squad,
        domain=config.feedback_domain,
        start=start,
        end=end,
        scope=scope,
        previous_analysis=args.previous_analysis,
    )
