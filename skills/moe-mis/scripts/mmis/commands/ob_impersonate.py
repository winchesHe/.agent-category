from ..keychain import CredentialStore
from ..ob_impersonate import ObImpersonateService
from ..browser import browser_binding_socket_environment, browser_binding_use
from ..errors import ConfigError
from ..formatter import output


def register(actions):
    group = actions.add_parser(
        "ob-impersonate",
        help="查询、建立或停止 Online Booking impersonate session",
    )
    group.set_defaults(_handler=run)
    commands = group.add_subparsers(
        dest="ob_impersonate_action",
        required=True,
    )
    commands.add_parser("status", help="只读回读当前 OB impersonate session")
    for action, help_text in (
        ("start", "规划或建立 OB impersonate session"),
        ("stop", "规划或停止 OB impersonate session"),
        ("reconcile", "规划或恢复中断的 OB impersonate session"),
    ):
        command = commands.add_parser(action, help=help_text)
        command.add_argument(
            "--expected-state-hash",
            help="apply 前必须与 plan 返回的 expectedStateHash 一致",
        )
        command.add_argument(
            "--apply",
            action="store_true",
            help="执行写操作；省略时只生成 plan",
        )
        if action in {"start", "stop", "reconcile"}:
            browser = command.add_mutually_exclusive_group()
            browser.add_argument(
                "--browser-session",
                default="",
                help="指定已连接的 agent-browser session；新验收任务应显式指定本批目标",
            )
            browser.add_argument(
                "--browser-binding-file",
                default="",
                help="既有旧版 lane 的 BrowserBinding 绝对路径（兼容入口）",
            )
            command.add_argument(
                "--browser-namespace",
                default=None,
                help="agent-browser namespace",
            )


def execute(args, config, client):
    def execute(browser_session="", browser_namespace="moego-delivery"):
        service = ObImpersonateService(
            client,
            credential_store=CredentialStore(),
            environment=config.mis_env,
            browser_session=browser_session,
            browser_namespace=browser_namespace,
        )
        if args.ob_impersonate_action == "status":
            return service.status()
        return getattr(service, args.ob_impersonate_action)(
            expected_state_hash=args.expected_state_hash, apply=args.apply,
        )

    binding_file = getattr(args, "browser_binding_file", "")
    browser_session = getattr(args, "browser_session", "")
    browser_namespace = getattr(args, "browser_namespace", None)
    if binding_file and browser_namespace is not None:
        raise ConfigError("--browser-binding-file 与 --browser-namespace 互斥")
    if browser_namespace is not None and not browser_session:
        raise ConfigError("--browser-namespace 只能与 --browser-session 一起使用")
    if binding_file:
        with browser_binding_use(
            binding_file, expected_environment=config.mis_env
        ) as binding:
            with browser_binding_socket_environment(binding):
                result = execute(binding["session"], binding["namespace"])
            result["bindingReceipt"] = {
                "bindingId": binding["bindingId"],
                "bindingEpoch": binding["bindingEpoch"],
                "browserSession": binding["session"],
                "browserNamespace": binding["namespace"],
                "targetHost": binding["host"],
            }
    else:
        result = execute(
            browser_session,
            browser_namespace or "moego-delivery",
        )
    return {"environment": config.mis_env, **result}


def run(args, config):
    from .mis import _client

    client = _client(config, force=args.force_login, auth_method=args.auth_method)
    output(execute(args, config, client), args.format)
    return 0
