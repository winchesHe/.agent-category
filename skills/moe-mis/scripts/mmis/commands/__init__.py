from . import metadata, mis, ob_impersonate

ALL = [mis, ob_impersonate, metadata]


def register(subparsers):
    for command in ALL:
        command.register(subparsers)
