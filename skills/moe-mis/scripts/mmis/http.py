import requests
from requests.cookies import create_cookie

from .errors import AuthError, BusinessError, TimeoutError


class HttpClient:
    def __init__(self, timeout=30, session=None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def post(self, url, **kwargs):
        try:
            response = self.session.post(url, timeout=self.timeout, **kwargs)
        except requests.Timeout as exc:
            raise TimeoutError(f"请求超时：{url}") from exc
        except requests.RequestException as exc:
            raise BusinessError(f"请求失败：{exc}") from exc
        if response.status_code in (401, 403):
            raise AuthError(f"MIS 鉴权失败（HTTP {response.status_code}）")
        if response.status_code >= 400:
            raise BusinessError(
                f"API 返回 HTTP {response.status_code}：{response.text[:500]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise BusinessError("API 未返回合法 JSON") from exc
        if isinstance(data, dict) and data.get("error"):
            raise BusinessError(str(data["error"]))
        return data

    def cookie_header(self, base_header=""):
        values = {}
        for part in base_header.split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name:
                values[name] = value
        for cookie in self.session.cookies:
            values[cookie.name] = cookie.value
        return "; ".join(f"{name}={value}" for name, value in values.items())

    def export_cookies(self, excluded_names=()):
        excluded = set(excluded_names)
        result = []
        for cookie in self.session.cookies:
            if cookie.name in excluded:
                continue
            result.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain or "",
                    "path": cookie.path or "/",
                    "secure": bool(cookie.secure),
                    "expires": cookie.expires,
                    "httpOnly": bool(cookie._rest.get("HttpOnly")),
                    "sameSite": cookie._rest.get("SameSite") or "",
                }
            )
        return tuple(result)

    def import_cookies(self, cookies):
        for item in cookies:
            self.session.cookies.set_cookie(
                create_cookie(
                    name=item["name"],
                    value=item["value"],
                    domain=item.get("domain") or "",
                    path=item.get("path") or "/",
                    secure=bool(item.get("secure")),
                    expires=item.get("expires"),
                    rest={
                        "HttpOnly": item["httpOnly"],
                        "SameSite": item["sameSite"],
                    },
                )
            )
