import requests

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
            raise AuthError(f"Grey 鉴权失败（HTTP {response.status_code}）")
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
