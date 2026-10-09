class CliError(Exception):
    exit_code = 4
    code = "BUSINESS_ERROR"


class ConfigError(CliError):
    exit_code = 2
    code = "CONFIG_ERROR"


class AuthError(CliError):
    exit_code = 3
    code = "AUTH_ERROR"


class BusinessError(CliError):
    exit_code = 4
    code = "BUSINESS_ERROR"


class TimeoutError(CliError):
    exit_code = 5
    code = "TIMEOUT"
