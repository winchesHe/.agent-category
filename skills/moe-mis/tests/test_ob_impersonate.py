import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mmis.clients.mis import MisClient
from mmis.commands import ob_impersonate as ob_commands
from mmis.errors import BusinessError, ConfigError
from mmis.keychain import MisCredential, ObSessionCredential
from mmis.ob_impersonate import (
    ObImpersonateService,
    ob_session_state_hash,
    sanitize_ob_session,
)
from moe_mis import build_parser


def session(impersonator=""):
    return {
        "mainSession": {
            "id": "100",
            "impersonator": impersonator,
            "status": 1,
            "createdAt": "2026-08-11T06:20:17Z",
            "lastAccessedAt": "2026-08-11T06:20:17Z",
            "maxAge": "86400s",
            "sessionData": {"customerPhone": "+15555555555"},
            "token": "must-not-leak",
        },
        "subSessions": {
            "zeta": {
                "id": "202",
                "status": 1,
                "impersonator": impersonator,
                "createdAt": "2026-08-11T06:22:00Z",
                "lastAccessedAt": "2026-08-11T06:22:00Z",
                "maxAge": "86400s",
                "sessionData": {"customerId": "private"},
            },
            "alpha": {
                "id": "201",
                "status": 1,
                "impersonator": impersonator,
                "createdAt": "2026-08-11T06:21:00Z",
                "lastAccessedAt": "2026-08-11T06:21:00Z",
                "maxAge": "86400s",
            },
        },
    }


def service_status(raw, *, local_state="absent", generation="", browser_session=""):
    result = sanitize_ob_session(raw)
    result["recovery"] = {
        "localState": local_state,
        "generation": generation,
        "browserSession": browser_session,
        "recoveryRequired": local_state in {"applying", "cleanup-required"},
    }
    return result


class ObImpersonateClientTests(unittest.TestCase):
    def setUp(self):
        self.http = Mock()
        credential = MisCredential(
            mgdid="",
            session_cookie_name="MGSID-MIS",
            session_cookie_value="session",
        )
        self.client = MisClient(
            "https://mis.example.test", self.http, credential
        )

    def test_ob_session_endpoints_use_empty_payload(self):
        self.http.cookie_header.return_value = "MGSID-MIS=session"
        self.http.post.side_effect = [session(), session("agent@moego.pet"), session()]

        self.client.check_ob_session()
        self.client.start_ob_impersonate()
        self.client.stop_ob_impersonate()

        self.assertEqual(
            [call.args[0] for call in self.http.post.call_args_list],
            [
                "https://mis.example.test/moego.admin.online_booking.v1.OnlineBookingService/CheckSession",
                "https://mis.example.test/moego.admin.online_booking.v1.OnlineBookingService/Impersonate",
                "https://mis.example.test/moego.admin.online_booking.v1.OnlineBookingService/RemoveImpersonate",
            ],
        )
        self.assertTrue(
            all(call.kwargs["json"] == {} for call in self.http.post.call_args_list)
        )

    def test_ob_session_requests_merge_persisted_session_cookies(self):
        self.http.cookie_header.return_value = (
            "MGSID-MIS=session; MGSID-OB=ob-session"
        )

        self.client.check_ob_session()

        self.http.cookie_header.assert_called_once_with(
            "MGSID-MIS=session"
        )
        self.assertEqual(
            self.http.post.call_args.kwargs["headers"]["Cookie"],
            "MGSID-MIS=session; MGSID-OB=ob-session",
        )


class ObImpersonateServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.service = ObImpersonateService(self.client)

    def test_status_removes_session_data_and_sorts_sub_sessions(self):
        self.client.check_ob_session.return_value = session("agent@moego.pet")

        result = self.service.status()

        self.assertTrue(result["active"])
        self.assertEqual(
            [item["obName"] for item in result["subSessions"]],
            ["alpha", "zeta"],
        )
        self.assertNotIn("sessionData", result["mainSession"])
        self.assertNotIn("token", result["mainSession"])
        self.assertNotIn("sessionData", result["subSessions"][1])

    def test_state_hash_is_stable_for_sub_session_order(self):
        raw = session("agent@moego.pet")
        reversed_raw = {
            **raw,
            "subSessions": dict(reversed(list(raw["subSessions"].items()))),
        }
        self.assertEqual(
            ob_session_state_hash(sanitize_ob_session(raw)),
            ob_session_state_hash(sanitize_ob_session(reversed_raw)),
        )

    def test_start_plan_does_not_write(self):
        self.client.check_ob_session.return_value = session()

        result = self.service.start(apply=False)

        self.assertEqual(result["mode"], "plan")
        self.assertEqual(result["action"], "start")
        self.assertFalse(result["noop"])
        self.assertTrue(result["expectedStateHash"])
        self.client.start_ob_impersonate.assert_not_called()

    def test_start_apply_requires_expected_state_hash(self):
        with self.assertRaises(ConfigError):
            self.service.start(apply=True)
        self.client.check_ob_session.assert_not_called()

    def test_start_apply_rejects_stale_state(self):
        self.client.check_ob_session.return_value = session()

        with self.assertRaises(BusinessError):
            self.service.start(
                apply=True,
                expected_state_hash="stale",
            )

        self.client.start_ob_impersonate.assert_not_called()

    def test_start_apply_writes_and_verifies_impersonator(self):
        before = session()
        after = session("agent@moego.pet")
        self.client.check_ob_session.side_effect = [before, after]
        self.client.account_info.return_value = {
            "account": {"email": "agent@moego.pet"}
        }
        self.client.export_ob_cookies.return_value = (
            {
                "name": "MGSID-OB",
                "value": "ob-session",
                "domain": ".t2.moego.dev",
            },
        )

        result = self.service.start(
            apply=True,
            expected_state_hash=ob_session_state_hash(
                service_status(before)
            ),
        )

        self.assertEqual(result["mode"], "apply")
        self.assertTrue(result["result"]["active"])
        self.client.start_ob_impersonate.assert_called_once_with()

    @patch("mmis.ob_impersonate.set_browser_cookies")
    def test_start_persists_and_injects_ob_cookie(self, set_cookies):
        before = session()
        after = session("agent@moego.pet")
        cookies = (
            {
                "name": "MGSID-OB",
                "value": "ob-session",
                "domain": ".t2.moego.dev",
            },
        )
        client = Mock()
        client.check_ob_session.side_effect = [before, after]
        client.account_info.return_value = {
            "account": {"email": "agent@moego.pet"}
        }
        client.export_ob_cookies.return_value = cookies
        store = Mock()
        store.load_ob.return_value = None
        service = ObImpersonateService(
            client,
            credential_store=store,
            environment="t2",
            browser_session="mid_lane_a",
            browser_namespace="moego-delivery",
        )

        service.start(
            apply=True,
            expected_state_hash=ob_session_state_hash(
                service_status(before, browser_session="mid_lane_a")
            ),
        )

        self.assertEqual(store.save_ob.call_args.args[0], "t2")
        self.assertEqual(store.save_ob.call_args.args[1].cookies, cookies)
        set_cookies.assert_called_once_with(
            cookies,
            browser_session="mid_lane_a",
            browser_namespace="moego-delivery",
        )

    def test_status_restores_persisted_ob_cookie(self):
        cookies = ({"name": "MGSID-OB", "value": "secret"},)
        client = Mock()
        client.check_ob_session.return_value = session("agent@moego.pet")
        store = Mock()
        store.load_ob.return_value.cookies = cookies

        service = ObImpersonateService(
            client, credential_store=store, environment="t2"
        )
        result = service.status()

        client.import_ob_cookies.assert_called_once_with(cookies)
        self.assertTrue(result["active"])

    def test_start_apply_rejects_wrong_impersonator_after_write(self):
        before = session()
        after = session("other@moego.pet")
        self.client.check_ob_session.side_effect = [before, after]
        self.client.account_info.return_value = {
            "account": {"email": "agent@moego.pet"}
        }
        self.client.export_ob_cookies.return_value = (
            {"name": "MGSID-OB", "value": "secret", "domain": ".moego.pet"},
        )

        with self.assertRaises(BusinessError):
            self.service.start(
                apply=True,
                expected_state_hash=ob_session_state_hash(
                    service_status(before)
                ),
            )

    def test_stop_is_idempotent_when_already_inactive(self):
        before = session()
        self.client.check_ob_session.return_value = before

        result = self.service.stop(apply=False)

        self.assertTrue(result["noop"])
        self.client.stop_ob_impersonate.assert_not_called()

    def test_stop_apply_writes_and_verifies_inactive(self):
        before = session("agent@moego.pet")
        after = session()
        self.client.check_ob_session.side_effect = [before, after]

        result = self.service.stop(
            apply=True,
            expected_state_hash=ob_session_state_hash(
                service_status(before)
            ),
        )

        self.assertFalse(result["result"]["active"])
        self.client.stop_ob_impersonate.assert_called_once_with()

    def test_stop_deletes_persisted_cookie_only_after_verified_inactive(self):
        before = session("agent@moego.pet")
        after = session()
        client = Mock()
        client.check_ob_session.side_effect = [before, after]
        store = Mock()
        store.load_ob.return_value = ObSessionCredential(
            cookies=(
                {"name": "MGSID-OB", "value": "secret"},
            )
        )
        service = ObImpersonateService(
            client, credential_store=store, environment="t2"
        )

        service.stop(
            apply=True,
            expected_state_hash=ob_session_state_hash(
                service_status(before, local_state="active")
            ),
        )

        store.delete_ob.assert_called_once_with("t2")

    @patch("mmis.ob_impersonate.expire_browser_cookies")
    @patch("mmis.ob_impersonate.set_browser_cookies")
    def test_start_injection_failure_compensates_remote_and_local_state(
        self, set_cookies, expire_cookies
    ):
        before = session()
        after = session("agent@moego.pet")
        inactive = session()
        cookies = (
            {
                "name": "MGSID-OB",
                "value": "secret",
                "domain": ".t2.moego.dev",
            },
        )
        client = Mock()
        client.check_ob_session.side_effect = [before, after, inactive]
        client.account_info.return_value = {
            "account": {"email": "agent@moego.pet"}
        }
        client.export_ob_cookies.return_value = cookies
        store = Mock()
        store.load_ob.return_value = None
        set_cookies.side_effect = ConfigError("browser unavailable")
        expire_cookies.return_value = {"state": "expired", "count": 1}
        service = ObImpersonateService(
            client,
            credential_store=store,
            environment="t2",
            browser_session="mid_lane_a",
        )

        with self.assertRaisesRegex(BusinessError, "已自动补偿为 inactive"):
            service.start(
                apply=True,
                expected_state_hash=ob_session_state_hash(
                    service_status(before, browser_session="mid_lane_a")
                ),
            )

        client.stop_ob_impersonate.assert_called_once_with()
        store.delete_ob.assert_called_once_with("t2")
        states = [call.args[1].state for call in store.save_ob.call_args_list]
        self.assertEqual(["applying"], states)

    @patch("mmis.ob_impersonate.set_browser_cookies")
    def test_reconcile_recovers_interrupted_applying_state(self, set_cookies):
        cookies = (
            {
                "name": "MGSID-OB",
                "value": "secret",
                "domain": ".t2.moego.dev",
            },
        )
        credential = ObSessionCredential(
            cookies=cookies,
            state="applying",
            generation="generation-a",
            browser_session="mid_lane_a",
        )
        client = Mock()
        client.check_ob_session.return_value = session("agent@moego.pet")
        store = Mock()
        store.load_ob.return_value = credential
        set_cookies.return_value = {"state": "verified", "count": 1}
        service = ObImpersonateService(
            client, credential_store=store, environment="t2"
        )
        plan = service.reconcile()

        result = service.reconcile(
            expected_state_hash=plan["expectedStateHash"], apply=True
        )

        self.assertEqual("active", result["result"]["recovery"]["localState"])
        self.assertFalse(result["result"]["recovery"]["recoveryRequired"])
        self.assertEqual("active", store.save_ob.call_args.args[1].state)
        set_cookies.assert_called_once()

    @patch("mmis.ob_impersonate.expire_browser_cookies")
    def test_inactive_stop_noop_cleans_stale_keychain(self, expire_cookies):
        cookies = (
            {
                "name": "MGSID-OB",
                "value": "secret",
                "domain": ".t2.moego.dev",
            },
        )
        credential = ObSessionCredential(
            cookies=cookies,
            state="cleanup-required",
            generation="generation-a",
            browser_session="mid_lane_a",
        )
        client = Mock()
        client.check_ob_session.return_value = session()
        store = Mock()
        store.load_ob.return_value = credential
        expire_cookies.return_value = {"state": "expired", "count": 1}
        service = ObImpersonateService(
            client, credential_store=store, environment="t2"
        )
        before = service.status()

        result = service.stop(
            expected_state_hash=ob_session_state_hash(before), apply=True
        )

        self.assertEqual("absent", result["result"]["recovery"]["localState"])
        store.delete_ob.assert_called_once_with("t2")
        client.stop_ob_impersonate.assert_not_called()

    def test_parser_dispatches_ob_impersonate_handler(self):
        args = build_parser().parse_args(["ob-impersonate", "status"])

        self.assertIs(ob_commands.run, args._handler)

    @patch.object(ob_commands, "browser_binding_socket_environment")
    @patch.object(ob_commands, "browser_binding_use")
    @patch.object(ob_commands, "ObImpersonateService")
    def test_binding_execution_scopes_delivery_socket_environment(
        self, service_type, binding_use, socket_environment
    ):
        binding = {
            "bindingId": "bnd_fixture",
            "bindingEpoch": 2,
            "session": "mid_lane_a",
            "namespace": "mid_lane_a",
            "host": "booking.t2.moego.dev",
            "_agentBrowserSocketRoot": "/tmp/mid-ab-501",
        }
        binding_use.return_value = nullcontext(binding)
        socket_environment.return_value = nullcontext()
        service_type.return_value.start.return_value = {
            "mode": "apply",
            "result": {"active": True},
        }
        args = SimpleNamespace(
            ob_impersonate_action="start",
            expected_state_hash="state-hash",
            apply=True,
            browser_binding_file="/tmp/binding.json",
            browser_session="",
            browser_namespace=None,
        )

        result = ob_commands.execute(
            args,
            SimpleNamespace(mis_env="t2"),
            Mock(),
        )

        socket_environment.assert_called_once_with(binding)
        binding_use.assert_called_once_with(
            "/tmp/binding.json", expected_environment="t2"
        )
        service_type.assert_called_once_with(
            unittest.mock.ANY,
            credential_store=unittest.mock.ANY,
            environment="t2",
            browser_session="mid_lane_a",
            browser_namespace="mid_lane_a",
        )
        self.assertEqual("bnd_fixture", result["bindingReceipt"]["bindingId"])


if __name__ == "__main__":
    unittest.main()
