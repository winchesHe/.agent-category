from __future__ import annotations

from ..analysis_v3 import build_prompt_artifact, build_weekly_analysis_v3


def register(subparsers):
    prompt_parser = subparsers.add_parser(
        "analysis-prompt",
        help="为本周 v3 语义分析生成一次性模型提示",
    )
    prompt_parser.add_argument(
        "--input",
        required=True,
        help="weekly-analysis-input-v1 JSON 路径",
    )
    prompt_parser.set_defaults(_handler=run_prompt)

    build_parser = subparsers.add_parser(
        "analysis-build",
        help="校验模型输出并确定性构建 weekly-analysis-v3",
    )
    build_parser.add_argument(
        "--input",
        required=True,
        help="weekly-analysis-input-v1 JSON 路径",
    )
    build_parser.add_argument(
        "--model-output",
        required=True,
        help="一次性模型返回的 JSON 路径",
    )
    build_parser.add_argument(
        "--human-review",
        default="",
        help="可选：人工分类复核 JSON 路径",
    )
    build_parser.set_defaults(_handler=run_build)


def run_prompt(args, _config):
    return build_prompt_artifact(args.input)


def run_build(args, _config):
    return build_weekly_analysis_v3(
        args.input,
        args.model_output,
        human_review=args.human_review,
    )
