import html
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from .errors import AuthError, SsoRejectedError, SsoUnavailableError
from .keychain import MisCredential, find_mis_session_cookie

GET_LOGIN_URL = (
    "/moego.admin.authentication.v1.AuthenticationService/GetLoginUrl"
)
LOGIN = "/moego.admin.authentication.v1.AuthenticationService/Login"
ACCOUNT_INFO = (
    "/moego.admin.authentication.v1.AuthenticationService/GetAccountInfo"
)


class LoginFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}
        self._in_form = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = values.get("action")
            self._in_form = True
        elif tag == "input" and self._in_form:
            name = values.get("name")
            if name:
                self.fields[name] = values.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form" and self._in_form:
            self._in_form = False


@dataclass(frozen=True)
class SsoResult:
    credential: MisCredential
    account: dict


class SsoAuthenticator:
    def __init__(
        self,
        base_url="https://cas.moego.pet",
        realm="Moement",
        timeout=30,
        session=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": "moego-internal-ops/sso-auth"}
        )

    def _request(self, method, url, **kwargs):
        try:
            response = getattr(self.session, method)(
                url, timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise SsoUnavailableError("SSO 服务当前不可用") from exc
        return response

    def authenticate(self, mis_url, username, password):
        if not username or not password:
            raise SsoUnavailableError(
                "未配置 MOE_MIS_SSO_USERNAME/MOE_MIS_SSO_PASSWORD；需要 Chrome control"
            )
        mis_url = mis_url.rstrip("/")
        redirect_url = mis_url + "/login?from=keycloak&redirect=%2F"

        response = self._request(
            "post",
            mis_url + GET_LOGIN_URL,
            json={"redirectUrl": redirect_url},
        )
        if response.status_code >= 400:
            raise SsoUnavailableError(
                "MIS 不支持当前 SSO GetLoginUrl 协议"
            )
        login_url = response.json().get("loginUrl")
        if not login_url:
            raise SsoUnavailableError("MIS SSO 响应缺少 loginUrl")
        actual_login = urlparse(login_url)
        expected_sso = urlparse(self.base_url)
        realm_path = f"/auth/realms/{self.realm}/"
        if (
            actual_login.scheme != expected_sso.scheme
            or actual_login.netloc != expected_sso.netloc
            or realm_path not in actual_login.path
        ):
            raise SsoUnavailableError(
                "MIS 返回了不受信任或不兼容的 SSO 登录地址"
            )

        response = self._request("get", login_url)
        if response.status_code >= 400:
            raise SsoUnavailableError("无法加载 SSO 登录表单")
        parser = LoginFormParser()
        parser.feed(response.text)
        if not parser.action:
            raise SsoUnavailableError(
                "SSO 页面不再提供兼容的账号密码登录表单"
            )

        form = parser.fields
        form.update(
            {
                "username": username,
                "password": password,
                "credentialId": form.get("credentialId", ""),
            }
        )
        action = urljoin(response.url, html.unescape(parser.action))
        response = self._request(
            "post", action, data=form, allow_redirects=False
        )
        if response.status_code not in (302, 303):
            if "invalid username or password" in response.text.lower():
                raise SsoRejectedError("SSO 用户名或密码被拒绝")
            raise SsoUnavailableError(
                "SSO 需要当前 CLI 不支持的附加认证步骤；需要 Chrome control"
            )

        query = parse_qs(urlparse(response.headers.get("Location", "")).query)
        state = query.get("state", [None])[0]
        code = query.get("code", [None])[0]
        if not state or not code:
            raise SsoUnavailableError(
                "SSO 未返回兼容的 authorization code；需要 Chrome control"
            )

        response = self._request(
            "post",
            mis_url + LOGIN,
            json={
                "keycloak": {
                    "redirectUrl": redirect_url,
                    "state": state,
                    "code": code,
                }
            },
        )
        if response.status_code in (401, 403):
            raise AuthError("SSO 已通过，但账号没有 MIS 登录权限")
        if response.status_code >= 400:
            raise SsoUnavailableError("MIS Login 协议当前不可用")

        cookies = {cookie.name: cookie.value for cookie in self.session.cookies}
        session_cookie = find_mis_session_cookie(cookies)
        if not session_cookie:
            raise SsoUnavailableError("MIS Login 未返回所需 Session Cookie")
        session_name, session_value = session_cookie
        credential = MisCredential(
            mgdid=cookies.get("MGDID", ""),
            session_cookie_name=session_name,
            session_cookie_value=session_value,
        )

        response = self._request(
            "post", mis_url + ACCOUNT_INFO, json={}
        )
        if response.status_code in (401, 403):
            raise AuthError("SSO 已通过，但账号没有 MIS API 权限")
        if response.status_code >= 400:
            raise SsoUnavailableError("MIS GetAccountInfo 当前不可用")
        account = response.json().get("account")
        if not account:
            raise AuthError("SSO 已通过，但 MIS 未返回有效账号")
        return SsoResult(credential=credential, account=account)
