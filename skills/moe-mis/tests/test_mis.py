import json
import sys
import unittest
import tempfile
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mmis.clients.mis import (
    MisClient,
    build_app_password,
    build_target_url,
    normalize_profile_type,
)
from mmis.keychain import MisCredential
from mmis import browser as browser_helpers
from mmis.commands import mis as mis_commands
from mmis.errors import BusinessError, ConfigError
from moe_mis import build_parser


class MisTests(unittest.TestCase):
    def setUp(self):
        self.http = Mock()
        self.credential = MisCredential(
            mgdid="device",
            session_cookie_name="MGSID-MIS-CUSTOM",
            session_cookie_value="session",
        )
        self.client = MisClient("https://mis.example.test", self.http, self.credential)

    def test_cookie_header_uses_dynamic_session_cookie_name(self):
        self.client.account_info()
        headers = self.http.post.call_args.kwargs["headers"]
        self.assertEqual(headers["Cookie"], "MGDID=device; MGSID-MIS-CUSTOM=session")

    def test_cookie_header_omits_missing_optional_mgdid(self):
        credential = MisCredential(
            mgdid="",
            session_cookie_name="MGSID-MIS",
            session_cookie_value="session",
        )
        self.assertEqual(credential.cookie_header, "MGSID-MIS=session")

    def test_profile_aliases(self):
        self.assertEqual(normalize_profile_type("email"), "accountEmail")
        self.assertEqual(normalize_profile_type("bid"), "businessId")
        self.assertEqual(normalize_profile_type("staff-id"), "staffId")

    def test_profile_sends_normalized_type_and_value(self):
        self.client.profile("bid", "105215")
        payload = self.http.post.call_args.kwargs["json"]
        self.assertEqual(payload, {"type": "businessId", "value": "105215"})

    def test_customer_and_business_urls_differ(self):
        self.assertEqual(
            build_target_url("t2", "business", "abc"),
            "https://go.t2.moego.dev/sign_in?token=abc",
        )
        self.assertEqual(
            build_target_url("production", "customer", "abc"),
            "https://my.moego.pet/login/welcome?token=abc",
        )

    def test_impersonate_sends_expected_payload(self):
        self.http.post.return_value = {"token": "abc", "larkApprovalStatus": "APPROVED"}
        result = self.client.impersonate("a@example.com", "d7", "business")
        self.assertEqual(result["token"], "abc")
        payload = self.http.post.call_args.kwargs["json"]
        self.assertEqual(
            payload,
            {"email": "a@example.com", "maxAge": "604800s", "source": "business"},
        )

    def test_impersonate_defaults_to_one_day(self):
        args = build_parser().parse_args(
            ["--env", "t2", "impersonate", "--email", "a@example.com"]
        )

        self.assertEqual(args.max_age, "d1")

    def test_every_top_level_action_registers_a_handler(self):
        commands = (
            ["auth", "status"],
            ["profile", "--type", "aid", "1"],
            ["impersonate", "--email", "a@example.com"],
            ["ob-impersonate", "status"],
            ["metadata", "groups"],
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(callable(build_parser().parse_args(command)._handler))

    def test_app_password_matches_mis_copy_rule(self):
        self.assertEqual(build_app_password("abc"), "d1ad54da5f06:abc")

    @patch.object(mis_commands, "open_url")
    @patch.object(mis_commands, "_client")
    def test_impersonate_can_open_in_named_agent_browser_session(
        self, client_factory, open_url
    ):
        client_factory.return_value.impersonate.return_value = {
            "token": "secret-token",
            "larkApprovalStatus": "APPROVED",
        }
        args = SimpleNamespace(
            mis_action="impersonate",
            force_login=False,
            auth_method="auto",
            email="a@example.com",
            max_age="h1",
            source="business",
            show_token=False,
            raw_token=False,
            as_password=False,
            browser_session="mid_lane_a",
            browser_namespace="moego-delivery",
        )
        config = SimpleNamespace(mis_env="t2")

        result = mis_commands.execute(args, config)

        open_url.assert_called_once_with(
            "https://go.t2.moego.dev/sign_in?token=secret-token",
            browser_session="mid_lane_a",
            browser_namespace="moego-delivery",
        )
        self.assertEqual("mid_lane_a", result["browserSession"])
        self.assertNotIn("token", result)

    @patch.object(mis_commands, "continue_login_in_tab")
    @patch.object(mis_commands, "_client")
    def test_internal_test_account_can_continue_login_unattended(
        self, client_factory, continue_login
    ):
        client = client_factory.return_value
        client.profile.return_value = {"account": {"email": "bot@moego.pet"}}
        client.impersonate.return_value = {
            "token": "secret-token",
            "larkApprovalStatus": "APPROVED",
        }
        continue_login.return_value = {
            "continued": True,
            "targetHost": "moego.canny.io",
            "targetPath": "/feature-request",
        }
        args = SimpleNamespace(
            mis_action="impersonate",
            force_login=False,
            auth_method="auto",
            email=None,
            account_ref="aid:13156918",
            max_age="h1",
            source="business",
            show_token=False,
            raw_token=False,
            as_password=False,
            browser_session="mfc_canny",
            browser_namespace="mfc",
            browser_binding_file="",
            continue_login_target="t1",
            allowed_redirect_host="moego.canny.io",
            expected_final_path="/feature-request",
            unattended=True,
        )

        result = mis_commands.execute(args, SimpleNamespace(mis_env="production", timeout=30))

        continue_login.assert_called_once_with(
            "https://go.moego.pet/sign_in?token=secret-token",
            browser_session="mfc_canny",
            browser_namespace="mfc",
            browser_target="t1",
            allowed_redirect_host="moego.canny.io",
            expected_final_path="/feature-request",
            timeout=30,
        )
        self.assertTrue(result["continued"])
        self.assertNotIn("secret-token", str(result))

    @patch.object(mis_commands, "_client")
    def test_external_account_is_rejected_before_unattended_production_token_issue(
        self, client_factory
    ):
        client = client_factory.return_value
        args = SimpleNamespace(
            mis_action="impersonate",
            force_login=False,
            auth_method="auto",
            email="customer@example.com",
            account_ref="",
            max_age="h1",
            source="business",
            unattended=True,
        )

        with self.assertRaisesRegex(BusinessError, "@moego.pet"):
            mis_commands.execute(args, SimpleNamespace(mis_env="production"))

        client.impersonate.assert_not_called()

    @patch.object(browser_helpers.time, "sleep")
    @patch.object(browser_helpers, "_agent_browser_eval")
    @patch.object(browser_helpers.subprocess, "run")
    @patch.object(browser_helpers.shutil, "which", return_value="/fixture/agent-browser")
    def test_continue_login_passes_token_only_through_eval_stdin(
        self, _which, run, browser_eval, _sleep
    ):
        info = Mock()
        info.stdout = '{"data":{"active":true}}'
        run.return_value = info
        browser_eval.side_effect = [
            {
                "host": "go.moego.pet",
                "path": "/sign_in",
                "companyID": "company-fixture",
                "redirectUrl": "https://moego.canny.io/feature-request",
                "redirectHost": "moego.canny.io",
                "redirectProtocol": "https:",
            },
            {"started": True},
            {
                "host": "moego.canny.io",
                "path": "/feature-request",
                "hasToken": False,
            },
        ]

        receipt = browser_helpers.continue_login_in_tab(
            "https://go.moego.pet/sign_in?token=secret-token",
            browser_session="mfc_canny",
            browser_namespace="mfc",
            browser_target="t1",
            allowed_redirect_host="moego.canny.io",
            expected_final_path="/feature-request",
        )

        self.assertTrue(receipt["continued"])
        self.assertFalse(any("secret-token" in str(call) for call in run.call_args_list))
        self.assertIn("secret-token", browser_eval.call_args_list[1].args[1])

    @patch.object(mis_commands, "open_url_with_binding")
    @patch.object(mis_commands, "_client")
    def test_account_ref_resolves_email_in_process_and_returns_binding_receipt(
        self, client_factory, open_with_binding
    ):
        client = client_factory.return_value
        client.profile.return_value = {"account": {"email": "private@example.com"}}
        client.impersonate.return_value = {
            "token": "secret-token", "larkApprovalStatus": "APPROVED",
        }
        open_with_binding.return_value = {
            "bindingId": "bnd_fixture", "bindingEpoch": 4,
            "browserSession": "mid_lane_a", "browserNamespace": "mid_lane_a",
            "targetHost": "go.t2.moego.dev",
        }
        args = SimpleNamespace(
            mis_action="impersonate", force_login=False, auth_method="auto",
            email=None, account_ref="aid:921015", max_age="h1", source="business",
            show_token=False, raw_token=False, as_password=False,
            browser_session="", browser_namespace=None,
            browser_binding_file="/tmp/binding.json",
        )
        result = mis_commands.execute(args, SimpleNamespace(mis_env="t2"))
        client.profile.assert_called_once_with("aid", "921015")
        client.impersonate.assert_called_once_with("private@example.com", "h1", "business")
        open_with_binding.assert_called_once_with(
            unittest.mock.ANY,
            "/tmp/binding.json",
            expected_environment="t2",
        )
        self.assertEqual("bnd_fixture", result["bindingReceipt"]["bindingId"])
        self.assertNotIn("email", str(result).lower())

    def test_browser_binding_rejects_stale_and_wrong_host(self):
        with tempfile.TemporaryDirectory() as directory:
            bindings = Path(directory) / "lanes" / "browser-bindings"
            bindings.mkdir(parents=True)
            lane_dir = Path(directory) / "lanes" / "lane_fixture"
            lane_dir.mkdir()
            socket_root = Path(directory) / "agent-browser-socket"
            socket_root.mkdir()
            path = bindings / "bnd_fixture.json"
            value = {
                "schemaVersion": 1, "bindingId": "bnd_fixture", "bindingEpoch": 1,
                "laneId": "lane_fixture", "runtimeId": "rtm_fixture", "runtimeGeneration": 2,
                "namespace": "mid_lane", "session": "mid_lane", "cdpPort": 19400,
                "host": "go.t2.moego.dev", "status": "active",
                "environment": "t2",
                "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            }
            identity = {key: value.get(key) for key in (
                "laneId", "runtimeId", "runtimeGeneration", "bindingEpoch",
                "namespace", "session", "cdpPort", "host", "environment",
            )}
            value["bindingHash"] = hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            path.write_text(json.dumps(value), encoding="utf-8")
            (lane_dir / "lane.json").write_text(json.dumps({
                "laneId": "lane_fixture", "runtimeId": "rtm_fixture", "runtimeGeneration": 2,
                "bindingEpoch": 1, "browserBindingId": "bnd_fixture",
                "browserBindingHash": value["bindingHash"], "host": "go.t2.moego.dev",
                "ports": {"cdp": 19400},
                "chrome": {"driver": {
                    "namespace": "mid_lane", "session": "mid_lane",
                    "socketRoot": str(socket_root),
                }},
            }), encoding="utf-8")
            previous = os.environ.get("AGENT_BROWSER_SOCKET_DIR")
            with browser_helpers.browser_binding_use(path) as binding:
                self.assertEqual(
                    str(socket_root), binding["_agentBrowserSocketRoot"]
                )
                with browser_helpers.browser_binding_socket_environment(binding):
                    self.assertEqual(
                        str(socket_root),
                        os.environ["AGENT_BROWSER_SOCKET_DIR"],
                    )
            self.assertEqual(
                previous, os.environ.get("AGENT_BROWSER_SOCKET_DIR")
            )
            with self.assertRaisesRegex(ConfigError, "Host"):
                with browser_helpers.browser_binding_use(path, expected_host="booking.t2.moego.dev"):
                    pass
            with self.assertRaisesRegex(ConfigError, "环境"):
                with browser_helpers.browser_binding_use(
                    path, expected_environment="production"
                ):
                    pass
            value["status"] = "invalidated"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "失效"):
                with browser_helpers.browser_binding_use(path):
                    pass

    @patch.object(browser_helpers.webbrowser, "open")
    @patch.object(browser_helpers.subprocess, "run")
    @patch.object(browser_helpers.shutil, "which", return_value="/fixture/agent-browser")
    def test_named_browser_open_uses_exact_namespace_and_session(
        self, _which, run, system_open
    ):
        run.return_value.stdout = '{"data":{"active":true}}'
        browser_helpers.open_url(
            "https://go.t2.moego.dev/sign_in?token=secret",
            browser_session="mid_lane_a",
            browser_namespace="moego-delivery",
        )

        prefix = [
            "/fixture/agent-browser",
            "--namespace",
            "moego-delivery",
            "--session",
            "mid_lane_a",
        ]
        self.assertEqual(
            [
                call(
                    [*prefix, "session", "info", "--json"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ),
                call(
                    [
                        *prefix,
                        "open",
                        "https://go.t2.moego.dev/sign_in?token=secret",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ),
            ],
            run.call_args_list,
        )
        system_open.assert_not_called()

    def test_named_browser_open_rejects_flag_like_session(self):
        with self.assertRaisesRegex(ConfigError, "namespace/session"):
            browser_helpers.open_url(
                "https://go.t2.moego.dev/sign_in?token=secret",
                browser_session="--session",
            )

    @patch.object(browser_helpers.subprocess, "run")
    @patch.object(browser_helpers.shutil, "which", return_value="/fixture/agent-browser")
    def test_named_browser_open_refuses_inactive_session(self, _which, run):
        run.return_value.stdout = '{"data":{"active":false}}'
        with self.assertRaisesRegex(ConfigError, "先运行 lane open"):
            browser_helpers.open_url(
                "https://go.t2.moego.dev/sign_in?token=secret",
                browser_session="mid_lane_a",
            )
        self.assertEqual(1, run.call_count)

    @patch.object(browser_helpers.subprocess, "run")
    @patch.object(browser_helpers.shutil, "which", return_value="/fixture/agent-browser")
    def test_ob_cookie_injection_targets_exact_named_session(self, _which, run):
        def invoke(command, **_kwargs):
            result = Mock()
            if command[-3:] == ["cookies", "get", "--json"]:
                result.stdout = json.dumps(
                    {
                        "data": {
                            "cookies": [
                                {
                                    "name": "MGSID-OB",
                                    "domain": ".t2.moego.dev",
                                    "path": "/",
                                }
                            ]
                        }
                    }
                )
            else:
                result.stdout = '{"data":{"active":true}}'
            return result

        run.side_effect = invoke
        cookies = (
            {
                "name": "MGSID-OB",
                "value": "secret-cookie",
                "domain": ".t2.moego.dev",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "None",
            },
        )

        browser_helpers.set_browser_cookies(
            cookies,
            browser_session="mid_lane_a",
            browser_namespace="moego-delivery",
        )

        prefix = [
            "/fixture/agent-browser",
            "--namespace",
            "moego-delivery",
            "--session",
            "mid_lane_a",
        ]
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    [*prefix, "session", "info", "--json"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ),
                call(
                    [
                        *prefix,
                        "cookies",
                        "set",
                        "MGSID-OB",
                        "secret-cookie",
                        "--domain",
                        ".t2.moego.dev",
                        "--path",
                        "/",
                        "--httpOnly",
                        "--secure",
                        "--sameSite",
                        "None",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ),
                call(
                    [*prefix, "cookies", "get", "--json"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ),
            ],
        )

    @patch.object(browser_helpers.subprocess, "run")
    @patch.object(browser_helpers.shutil, "which", return_value="/fixture/agent-browser")
    def test_ob_cookie_injection_requires_write_after_readback(self, _which, run):
        result = Mock()
        result.stdout = '{"data":{"active":true,"cookies":[]}}'
        run.return_value = result

        with self.assertRaisesRegex(ConfigError, "注入后未在指定浏览器中回读到"):
            browser_helpers.set_browser_cookies(
                (
                    {
                        "name": "MGSID-OB",
                        "value": "secret-cookie",
                        "domain": ".t2.moego.dev",
                    },
                ),
                browser_session="mid_lane_a",
                browser_namespace="moego-delivery",
            )


if __name__ == "__main__":
    unittest.main()
