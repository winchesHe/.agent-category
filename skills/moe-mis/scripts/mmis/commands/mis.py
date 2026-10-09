import sys

from ..browser import (
    continue_login_in_tab,
    copy_to_clipboard,
    open_url,
    open_url_with_binding,
)
from ..cdp import capture_mis_credential
from ..clients.mis import MisClient, build_app_password, build_target_url
from ..errors import AuthError, BusinessError
from ..formatter import output
from ..http import HttpClient
from ..keychain import CredentialStore
from ..sso import SsoAuthenticator


def register(subparsers):
    actions = subparsers

    auth = actions.add_parser("auth", help="管理 MIS Session")
    auth.set_defaults(_handler=run)
    auth_actions = auth.add_subparsers(dest="auth_action", required=True)
    auth_actions.add_parser("status", help="检查登录状态")
    login = auth_actions.add_parser("login", help="通过指定方法登录")
    login.add_argument("--force", action="store_true", help="忽略已有 Session")
    auth_actions.add_parser("logout", help="删除本地 Keychain Session")

    profile = actions.add_parser("profile", help="查询账号 Profile")
    profile.set_defaults(_handler=run)
    profile.add_argument(
        "--type",
        required=True,
        choices=[
            "email",
            "account-email",
            "aid",
            "account-id",
            "bid",
            "business-id",
            "cid",
            "company-id",
            "sid",
            "staff-id",
        ],
    )
    profile.add_argument("value")

    imp = actions.add_parser("impersonate", help="生成 impersonate token")
    imp.set_defaults(_handler=run)
    principal = imp.add_mutually_exclusive_group(required=True)
    principal.add_argument("--email")
    principal.add_argument("--account-ref", help="稳定账号引用，首期仅支持 aid:<id>")
    imp.add_argument("--max-age", default="d1", choices=["h1", "h2", "d1", "d7", "d15"])
    imp.add_argument("--source", default="business", choices=["business", "customer"])
    delivery = imp.add_mutually_exclusive_group()
    delivery.add_argument(
        "--raw-token",
        action="store_true",
        help="将 token 复制到剪贴板，stdout 不显示原文",
    )
    delivery.add_argument(
        "--as-password",
        action="store_true",
        help="按 MIS Copy as password 规则生成临时登录密码并复制到剪贴板",
    )
    delivery.add_argument(
        "--show-token",
        action="store_true",
        help="在 stdout 显示敏感 token 原文",
    )
    browser_target = imp.add_mutually_exclusive_group()
    browser_target.add_argument(
        "--browser-session",
        default="",
        help="在已确认的 agent-browser 命名 session 打开登录页",
    )
    browser_target.add_argument(
        "--browser-binding-file",
        default="",
        help="既有旧版 lane 的 BrowserBinding 绝对路径（兼容入口）",
    )
    imp.add_argument(
        "--browser-namespace",
        default=None,
        help="agent-browser namespace；仅与 --browser-session 一起使用",
    )
    imp.add_argument(
        "--continue-login-target",
        default="",
        help="在指定 agent-browser tab/label 中保留 companyID 与 redirect 继续登录",
    )
    imp.add_argument(
        "--allowed-redirect-host",
        default="",
        help="原标签页续登允许返回的精确 host",
    )
    imp.add_argument(
        "--expected-final-path",
        default="/",
        help="原标签页续登成功后的精确 path",
    )
    imp.add_argument(
        "--unattended",
        action="store_true",
        help="无人值守运行；production 仅允许 @moego.pet 内部测试账号",
    )
def _client(config, force=False, auth_method="auto"):
    store = CredentialStore()
    credential = None if force else store.load(config.mis_env)
    http = HttpClient(config.timeout)
    if credential:
        candidate = MisClient(config.mis_url, http, credential)
        try:
            if candidate.account_info().get("account"):
                return candidate
        except AuthError:
            pass
    if auth_method != "isolated":
        result = SsoAuthenticator(
            base_url=config.sso_base_url,
            realm=config.sso_realm,
            timeout=config.timeout,
        ).authenticate(
            config.mis_url, config.sso_username, config.sso_password
        )
        store.save(config.mis_env, result.credential)
        return MisClient(config.mis_url, http, result.credential)
    print("请在隔离 Chrome 中完成 Google/MoeGo SSO 登录…", file=sys.stderr)
    credential = capture_mis_credential(
        config.mis_url, max(config.timeout, 180), config.chrome_binary
    )
    candidate = MisClient(config.mis_url, http, credential)
    if not candidate.account_info().get("account"):
        raise AuthError("已捕获 Session，但 MIS 未返回有效账号")
    store.save(config.mis_env, credential)
    return candidate


def execute(args, config):
    if args.mis_action == "auth":
        store = CredentialStore()
        if args.auth_action == "logout":
            store.delete(config.mis_env)
            return {"authenticated": False, "environment": config.mis_env}
        if args.auth_action == "status":
            credential = store.load(config.mis_env)
            if not credential:
                return {"authenticated": False, "environment": config.mis_env}
            client = MisClient(
                config.mis_url, HttpClient(config.timeout), credential
            )
            try:
                info = client.account_info()
            except AuthError:
                return {"authenticated": False, "environment": config.mis_env}
            return {
                "authenticated": bool(info.get("account")),
                "environment": config.mis_env,
                "account": info.get("account"),
            }
        client = _client(
            config,
            force=getattr(args, "force", False),
            auth_method=args.auth_method,
        )
        info = client.account_info()
        return {
            "authenticated": bool(info.get("account")),
            "environment": config.mis_env,
            "account": info.get("account"),
        }

    client = _client(
        config, force=args.force_login, auth_method=args.auth_method
    )
    if args.mis_action == "profile":
        return client.profile(args.type, args.value)

    as_password = getattr(args, "as_password", False)
    email = getattr(args, "email", None)
    account_ref = getattr(args, "account_ref", "")
    if account_ref:
        kind, separator, value = account_ref.partition(":")
        if separator != ":" or kind != "aid" or not value:
            raise BusinessError("--account-ref 首期只支持 aid:<stable-id>")
        profile = client.profile("aid", value)
        candidates = set()
        def collect_emails(item):
            if isinstance(item, dict):
                for key, child in item.items():
                    if key.lower() in {"email", "accountemail", "account_email"} and isinstance(child, str) and "@" in child:
                        candidates.add(child)
                    else:
                        collect_emails(child)
            elif isinstance(item, list):
                for child in item:
                    collect_emails(child)
        collect_emails(profile)
        if len(candidates) != 1:
            raise BusinessError("account-ref 未能唯一解析账号邮箱")
        email = candidates.pop()
    unattended = getattr(args, "unattended", False)
    if (
        unattended
        and config.mis_env == "production"
        and not str(email or "").lower().endswith("@moego.pet")
    ):
        raise BusinessError(
            "production 无人值守 impersonate 仅允许 @moego.pet 内部测试账号"
        )
    result = client.impersonate(email, args.max_age, args.source)
    status = result.get("larkApprovalStatus", "")
    if status and status != "APPROVED":
        return {
            "approved": False,
            "larkApprovalStatus": status,
            "instanceCode": result.get("instanceCode"),
        }
    token = result.get("token")
    if not token:
        raise BusinessError("MIS 未返回 impersonate token")
    url = build_target_url(config.mis_env, args.source, token)
    response_metadata = {
        "approved": True,
        "larkApprovalStatus": status or "APPROVED",
        "remainingMaxAge": result.get("remainingMaxAge"),
        "source": args.source,
    }
    if args.show_token:
        response_metadata.update({"token": token, "sensitive": True})
        return response_metadata
    if args.raw_token:
        copy_to_clipboard(token)
        response_metadata["copied"] = True
        return response_metadata
    if as_password:
        copy_to_clipboard(build_app_password(token))
        response_metadata.update({"copied": True, "delivery": "password"})
        return response_metadata
    binding_file = getattr(args, "browser_binding_file", "")
    browser_session = getattr(args, "browser_session", "")
    browser_namespace = getattr(args, "browser_namespace", None)
    continue_login_target = getattr(args, "continue_login_target", "")
    allowed_redirect_host = getattr(args, "allowed_redirect_host", "")
    expected_final_path = getattr(args, "expected_final_path", "/")
    if binding_file and browser_namespace is not None:
        raise BusinessError("--browser-binding-file 与 --browser-namespace 互斥")
    if browser_namespace is not None and not browser_session:
        raise BusinessError("--browser-namespace 只能与 --browser-session 一起使用")
    if continue_login_target and (binding_file or not browser_session):
        raise BusinessError(
            "--continue-login-target 必须与 --browser-session 一起使用，且不支持 binding file"
        )
    if continue_login_target and not allowed_redirect_host:
        raise BusinessError("原标签页续登必须提供 --allowed-redirect-host")
    binding_receipt = None
    if continue_login_target:
        binding_receipt = continue_login_in_tab(
            url,
            browser_session=browser_session,
            browser_namespace=browser_namespace or "moego-delivery",
            browser_target=continue_login_target,
            allowed_redirect_host=allowed_redirect_host,
            expected_final_path=expected_final_path,
            timeout=max(30, config.timeout),
        )
    elif binding_file:
        binding_receipt = open_url_with_binding(
            url, binding_file, expected_environment=config.mis_env
        )
    else:
        open_url(
            url,
            browser_session=browser_session,
            browser_namespace=browser_namespace or "moego-delivery",
        )
    response_metadata["opened"] = not bool(continue_login_target)
    response_metadata["continued"] = bool(continue_login_target)
    response_metadata["targetHost"] = (
        allowed_redirect_host if continue_login_target else url.split("/", 3)[2]
    )
    if getattr(args, "browser_session", ""):
        response_metadata.update(
            {
                "browserSession": args.browser_session,
                "browserNamespace": args.browser_namespace,
            }
        )
    if binding_receipt:
        response_metadata[
            "continueReceipt" if continue_login_target else "bindingReceipt"
        ] = binding_receipt
    return response_metadata


def run(args, config):
    result = execute(args, config)
    allow_sensitive = bool(
        args.mis_action == "impersonate" and getattr(args, "show_token", False)
    )
    output(result, args.format, allow_sensitive=allow_sensitive)
    return 0
