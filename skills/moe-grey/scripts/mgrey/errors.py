import sys


class CliError(Exception):
    exit_code = 4


class ConfigError(CliError):
    exit_code = 2


class AuthError(CliError):
    exit_code = 3


class BusinessError(CliError):
    exit_code = 4


class TimeoutError(CliError):
    exit_code = 5


def fail(message, code=4):
    print(message, file=sys.stderr)
    return code
