from ..formatter import output
from ._shared import register_action, run as execute


def register(subparsers):
    register_action(subparsers, "get", run)


def run(args, config):
    output(execute(args, config), args.format)
    return 0
