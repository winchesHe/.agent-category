from ..lark import resolve_wiki
from ..schema import describe_schema


def register(subparsers):
    parser = subparsers.add_parser("schema", help="输出飞书全渠道数据模型")
    parser.set_defaults(_handler=run)


def run(_args, config):
    return {
        "wiki": resolve_wiki(config),
        "design": describe_schema(),
        "mutationPlanned": False,
    }
