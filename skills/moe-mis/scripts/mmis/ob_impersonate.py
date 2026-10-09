import hashlib
import json
import secrets
from datetime import datetime, timezone

from .browser import expire_browser_cookies, set_browser_cookies
from .errors import BusinessError, ConfigError
from .keychain import ObSessionCredential


SESSION_FIELDS = (
    "id",
    "status",
    "impersonator",
    "createdAt",
    "updatedAt",
    "lastAccessedAt",
    "maxAge",
)


def _safe_session(value):
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in SESSION_FIELDS if key in value}


def sanitize_ob_session(raw):
    raw = raw if isinstance(raw, dict) else {}
    main_session = _safe_session(raw.get("mainSession"))
    impersonator = str(main_session.get("impersonator") or "").strip()
    sub_sessions = raw.get("subSessions") or {}
    safe_sub_sessions = []
    if isinstance(sub_sessions, dict):
        items = sub_sessions.items()
    elif isinstance(sub_sessions, list):
        items = (
            (item.get("obName", ""), item)
            for item in sub_sessions
            if isinstance(item, dict)
        )
    else:
        items = []
    for ob_name, value in sorted(items, key=lambda item: str(item[0])):
        safe_sub_sessions.append(
            {"obName": str(ob_name), **_safe_session(value)}
        )
    return {
        "active": bool(impersonator),
        "mainSession": main_session,
        "subSessions": safe_sub_sessions,
    }


def ob_session_state_hash(state):
    canonical = json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ObImpersonateService:
    def __init__(
        self,
        client,
        credential_store=None,
        environment="",
        browser_session="",
        browser_namespace="moego-delivery",
    ):
        self.client = client
        self.credential_store = credential_store
        self.environment = environment
        self.browser_session = browser_session
        self.browser_namespace = browser_namespace
        self.credential = None
        self.persisted_cookies = ()
        if self.credential_store and self.environment:
            credential = self.credential_store.load_ob(self.environment)
            if credential:
                self.credential = credential
                self.persisted_cookies = credential.cookies
                self.client.import_ob_cookies(self.persisted_cookies)
                if not self.browser_session:
                    self.browser_session = credential.browser_session
                    self.browser_namespace = credential.browser_namespace

    def status(self):
        return self._decorate_status(
            sanitize_ob_session(self.client.check_ob_session())
        )

    def _decorate_status(self, remote_status):
        result = dict(remote_status)
        result.pop("recovery", None)
        local_state = self.credential.state if self.credential else "absent"
        result["recovery"] = {
            "localState": local_state,
            "generation": self.credential.generation if self.credential else "",
            "browserSession": self.browser_session,
            "recoveryRequired": local_state in {"applying", "cleanup-required"},
        }
        return result

    def start(self, expected_state_hash=None, apply=False):
        return self._change(
            action="start",
            expected_active=True,
            expected_state_hash=expected_state_hash,
            apply=apply,
        )

    def stop(self, expected_state_hash=None, apply=False):
        return self._change(
            action="stop",
            expected_active=False,
            expected_state_hash=expected_state_hash,
            apply=apply,
        )

    def reconcile(self, expected_state_hash=None, apply=False):
        before = self.status()
        current_hash = ob_session_state_hash(before)
        plan = {
            "mode": "plan",
            "action": "reconcile",
            "noop": not before["recovery"]["recoveryRequired"],
            "before": before,
            "expected": {"recoveryRequired": False},
            "expectedStateHash": current_hash,
        }
        if not apply:
            return plan
        if not expected_state_hash:
            raise ConfigError("--apply 必须同时提供 --expected-state-hash")
        if current_hash != expected_state_hash:
            raise BusinessError(
                "OB impersonate 状态已变化，请重新生成 plan 后再执行"
            )
        if before["active"]:
            if not self.persisted_cookies:
                raise BusinessError(
                    "远端 OB impersonate active，但本地没有可恢复 Cookie；请执行 stop 后重新 start"
                )
            browser_binding = set_browser_cookies(
                self.persisted_cookies,
                browser_session=self.browser_session,
                browser_namespace=self.browser_namespace,
            )
            self._save_credential(self.persisted_cookies, "active")
            result = self._decorate_status(before)
            return {
                **plan,
                "mode": "apply",
                "result": result,
                "browserBinding": browser_binding,
            }
        browser_cleanup = self._cleanup_browser()
        self._delete_credential()
        result = self._decorate_status(before)
        return {
            **plan,
            "mode": "apply",
            "result": result,
            "browserCleanup": browser_cleanup,
        }

    def _save_credential(self, cookies, state, generation=""):
        if not self.credential_store or not self.environment:
            return
        current_generation = generation or (
            self.credential.generation if self.credential else ""
        )
        credential = ObSessionCredential(
            cookies=tuple(cookies),
            state=state,
            generation=current_generation,
            created_at=(
                self.credential.created_at
                if self.credential and self.credential.created_at
                else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            ),
            browser_session=self.browser_session,
            browser_namespace=self.browser_namespace,
        )
        self.credential_store.save_ob(self.environment, credential)
        self.credential = credential
        self.persisted_cookies = credential.cookies

    def _delete_credential(self):
        if self.credential_store and self.environment:
            self.credential_store.delete_ob(self.environment)
        self.credential = None
        self.persisted_cookies = ()

    def _cleanup_browser(self):
        if not self.persisted_cookies:
            return {"state": "skipped", "count": 0}
        try:
            return expire_browser_cookies(
                self.persisted_cookies,
                browser_session=self.browser_session,
                browser_namespace=self.browser_namespace,
            )
        except ConfigError as exc:
            return {"state": "unavailable", "detail": str(exc), "count": 0}

    def _compensate_start(self, cookies):
        cleanup = {"remote": "unknown", "browser": {"state": "skipped", "count": 0}}
        try:
            self.client.stop_ob_impersonate()
            inactive = sanitize_ob_session(self.client.check_ob_session())
            if inactive["active"]:
                raise BusinessError("补偿 stop 后远端仍为 active")
            cleanup["remote"] = "inactive"
        except Exception as exc:
            if cookies:
                self._save_credential(cookies, "cleanup-required")
            cleanup["remote"] = "failed"
            cleanup["detail"] = str(exc)
            return cleanup
        cleanup["browser"] = self._cleanup_browser()
        self._delete_credential()
        return cleanup

    def _change(
        self,
        action,
        expected_active,
        expected_state_hash,
        apply,
    ):
        if apply and not expected_state_hash:
            raise ConfigError("--apply 必须同时提供 --expected-state-hash")

        before = self.status()
        current_hash = ob_session_state_hash(before)
        noop = before["active"] == expected_active
        plan = {
            "mode": "plan",
            "action": action,
            "noop": noop,
            "before": before,
            "expected": {"active": expected_active},
            "expectedStateHash": current_hash,
        }
        if not apply:
            return plan
        if current_hash != expected_state_hash:
            raise BusinessError(
                "OB impersonate 状态已变化，请重新生成 plan 后再执行"
            )
        if noop:
            browser_result = None
            if action == "start":
                if not self.persisted_cookies:
                    raise BusinessError(
                        "远端 OB impersonate active，但缺少本地 Cookie；请先 stop 再 start"
                    )
                browser_result = set_browser_cookies(
                    self.persisted_cookies,
                    browser_session=self.browser_session,
                    browser_namespace=self.browser_namespace,
                )
                self._save_credential(self.persisted_cookies, "active")
            else:
                browser_result = self._cleanup_browser()
                self._delete_credential()
            return {
                **plan,
                "mode": "apply",
                "result": self._decorate_status(before),
                "browserBinding" if action == "start" else "browserCleanup": browser_result,
            }

        expected_email = ""
        if action == "start":
            account = self.client.account_info().get("account") or {}
            expected_email = str(account.get("email") or "").strip()
            if not expected_email:
                raise BusinessError("MIS 未返回当前账号邮箱，无法验证 impersonator")
            cookies = ()
            remote_mutated = False
            try:
                self.client.start_ob_impersonate()
                remote_mutated = True
                cookies = self.client.export_ob_cookies()
                if not cookies:
                    raise BusinessError(
                        "MIS 未返回 OB Session Cookie，无法持久化联调会话"
                    )
                generation = secrets.token_hex(12)
                self._save_credential(cookies, "applying", generation)

                after = self.status()
                if not after["active"]:
                    raise BusinessError("OB impersonate 写后回读与目标状态不一致")
                actual_email = str(
                    after["mainSession"].get("impersonator") or ""
                ).strip()
                if actual_email.casefold() != expected_email.casefold():
                    raise BusinessError(
                        "OB impersonate 写后 impersonator 与当前账号不一致"
                    )
                browser_binding = set_browser_cookies(
                    cookies,
                    browser_session=self.browser_session,
                    browser_namespace=self.browser_namespace,
                )
                self._save_credential(cookies, "active", generation)
                return {
                    **plan,
                    "mode": "apply",
                    "result": self._decorate_status(after),
                    "browserBinding": browser_binding,
                }
            except Exception as exc:
                if not remote_mutated:
                    raise
                cleanup = self._compensate_start(cookies)
                if cleanup["remote"] == "inactive":
                    raise BusinessError(
                        f"OB impersonate start 未完成，已自动补偿为 inactive：{exc}"
                    ) from exc
                raise BusinessError(
                    "OB impersonate start 未完成且自动补偿失败；"
                    "请执行 reconcile/stop，当前本地恢复状态已保留"
                ) from exc
        else:
            self.client.stop_ob_impersonate()

        after = self.status()
        if after["active"] != expected_active:
            raise BusinessError("OB impersonate 写后回读与目标状态不一致")
        browser_cleanup = self._cleanup_browser()
        self._delete_credential()
        return {
            **plan,
            "mode": "apply",
            "result": self._decorate_status(after),
            "browserCleanup": browser_cleanup,
        }
