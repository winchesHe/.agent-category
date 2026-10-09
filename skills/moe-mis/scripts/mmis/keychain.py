import json
from dataclasses import asdict, dataclass

from .errors import AuthError


@dataclass(frozen=True)
class MisCredential:
    mgdid: str
    session_cookie_name: str
    session_cookie_value: str

    @property
    def cookie_header(self):
        parts = []
        if self.mgdid:
            parts.append(f"MGDID={self.mgdid}")
        parts.append(
            f"{self.session_cookie_name}={self.session_cookie_value}"
        )
        return "; ".join(parts)


@dataclass(frozen=True)
class ObSessionCredential:
    cookies: tuple
    state: str = "active"
    generation: str = ""
    created_at: str = ""
    browser_session: str = ""
    browser_namespace: str = "moego-delivery"


def find_mis_session_cookie(cookies):
    for name, value in cookies.items():
        if name == "MGSID-MIS" or name.startswith("MGSID-MIS-"):
            return name, value
    return None


class CredentialStore:
    # 保留历史 namespace，确保拆分前的 MIS/OB Session 与恢复 journal 可继续读取。
    LEGACY_KEYCHAIN_SERVICE = "moego-internal-ops"
    SERVICE = LEGACY_KEYCHAIN_SERVICE

    def __init__(self, backend=None):
        if backend is None:
            try:
                import keyring
            except ImportError as exc:
                raise AuthError("缺少 keyring 依赖，请通过 uv run --script 运行") from exc
            backend = keyring
        self.backend = backend

    def _username(self, env):
        return f"mis-{env}"

    def _ob_username(self, env):
        return f"mis-ob-{env}"

    def load(self, env):
        try:
            value = self.backend.get_password(self.SERVICE, self._username(env))
        except Exception as exc:
            raise AuthError(f"无法读取 macOS Keychain：{exc}") from exc
        if not value:
            return None
        try:
            return MisCredential(**json.loads(value))
        except (TypeError, ValueError) as exc:
            raise AuthError("Keychain 中的 MIS 凭证格式无效，请重新登录") from exc

    def save(self, env, credential):
        try:
            self.backend.set_password(
                self.SERVICE, self._username(env), json.dumps(asdict(credential))
            )
        except Exception as exc:
            raise AuthError(f"无法写入 macOS Keychain：{exc}") from exc

    def delete(self, env):
        try:
            self.backend.delete_password(self.SERVICE, self._username(env))
        except Exception as exc:
            if exc.__class__.__name__ not in ("PasswordDeleteError", "NoKeyringError"):
                raise AuthError(f"无法删除 macOS Keychain 凭证：{exc}") from exc

    def load_ob(self, env):
        try:
            value = self.backend.get_password(
                self.SERVICE, self._ob_username(env)
            )
        except Exception as exc:
            raise AuthError(f"无法读取 macOS Keychain：{exc}") from exc
        if not value:
            return None
        try:
            payload = json.loads(value)
            cookies = payload.get("cookies")
            if not isinstance(cookies, list) or not all(
                isinstance(cookie, dict) for cookie in cookies
            ):
                raise TypeError
            state = payload.get("state", "active")
            if state not in {"applying", "active", "cleanup-required"}:
                raise TypeError
            return ObSessionCredential(
                cookies=tuple(cookies),
                state=state,
                generation=str(payload.get("generation") or ""),
                created_at=str(payload.get("createdAt") or ""),
                browser_session=str(payload.get("browserSession") or ""),
                browser_namespace=str(
                    payload.get("browserNamespace") or "moego-delivery"
                ),
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise AuthError(
                "Keychain 中的 OB Session 格式无效，请先执行 stop 清理"
            ) from exc

    def save_ob(self, env, credential):
        try:
            self.backend.set_password(
                self.SERVICE,
                self._ob_username(env),
                json.dumps(
                    {
                        "cookies": list(credential.cookies),
                        "state": credential.state,
                        "generation": credential.generation,
                        "createdAt": credential.created_at,
                        "browserSession": credential.browser_session,
                        "browserNamespace": credential.browser_namespace,
                    }
                ),
            )
        except Exception as exc:
            raise AuthError(f"无法写入 macOS Keychain：{exc}") from exc

    def delete_ob(self, env):
        try:
            self.backend.delete_password(
                self.SERVICE, self._ob_username(env)
            )
        except Exception as exc:
            if exc.__class__.__name__ not in ("PasswordDeleteError", "NoKeyringError"):
                raise AuthError(f"无法删除 macOS Keychain 凭证：{exc}") from exc
