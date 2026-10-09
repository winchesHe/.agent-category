#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "keyring>=25.0.0,<26",
#   "python-dotenv>=1.0.0,<2",
#   "requests>=2.31.0,<3",
#   "websocket-client>=1.8.0,<2",
# ]
# ///
import argparse
import sys

from mmis.commands import register
from mmis.config import load_config
from mmis.errors import CliError


def build_parser():
    parser = argparse.ArgumentParser(
        prog="moe-mis",
        description="MoeGo MIS、账号、Online Booking impersonate 与 Metadata CLI",
    )
    parser.add_argument(
        "--env", choices=["t2", "s1", "production"], help="MIS 环境"
    )
    parser.add_argument(
        "--format",
        choices=["json", "human", "summary"],
        default="json",
        help="输出格式（默认 json）",
    )
    parser.add_argument(
        "--force-login", action="store_true", help="MIS 命令强制重新登录"
    )
    parser.add_argument(
        "--auth-method",
        choices=["auto", "sso", "isolated"],
        default="auto",
        help=(
            "MIS 鉴权方法；auto/sso 使用账号密码，"
            "isolated 才启动隔离 Chrome"
        ),
    )
    register(parser.add_subparsers(dest="mis_action", required=True))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.env)
        return int(args._handler(args, config) or 0)
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("操作已取消", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
