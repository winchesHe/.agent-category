from . import branches, create, copy, delete, get, list as list_command, update

ALL = [list_command, get, branches, create, copy, update, delete]


def register(subparsers):
    for command in ALL:
        command.register(subparsers)
