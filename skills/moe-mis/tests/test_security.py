import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mmis.cdp import _cookies_for_origin
from mmis.formatter import output
from mmis.keychain import (
    CredentialStore,
    MisCredential,
    ObSessionCredential,
    find_mis_session_cookie,
)


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, username, value):
        self.values[(service, username)] = value

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


class SecurityTests(unittest.TestCase):
    def test_formatter_redacts_sensitive_fields_recursively(self):
        stream = StringIO()
        with redirect_stdout(stream):
            output(
                {
                    "token": "secret-token",
                    "nested": {
                        "sessionCookieValue": "secret-cookie",
                        "email": "person@example.com",
                    },
                },
                "json",
            )
        data = json.loads(stream.getvalue())
        self.assertEqual(data["token"], "[REDACTED]")
        self.assertEqual(data["nested"]["sessionCookieValue"], "[REDACTED]")
        self.assertEqual(data["nested"]["email"], "person@example.com")

    def test_show_sensitive_requires_explicit_flag(self):
        stream = StringIO()
        with redirect_stdout(stream):
            output({"token": "secret-token"}, "json", allow_sensitive=True)
        self.assertEqual(json.loads(stream.getvalue())["token"], "secret-token")

    def test_keychain_round_trip_preserves_dynamic_cookie_name(self):
        backend = FakeKeyring()
        store = CredentialStore(backend=backend)
        credential = MisCredential(
            mgdid="device",
            session_cookie_name="MGSID-MIS-S1",
            session_cookie_value="session",
        )
        store.save("s1", credential)
        self.assertEqual(store.load("s1"), credential)
        store.delete("s1")
        self.assertIsNone(store.load("s1"))

    def test_ob_session_uses_separate_keychain_record(self):
        backend = FakeKeyring()
        store = CredentialStore(backend=backend)
        credential = ObSessionCredential(
            cookies=(
                {
                    "name": "MGSID-OB",
                    "value": "secret",
                    "domain": ".t2.moego.dev",
                    "path": "/",
                },
            ),
            state="applying",
            generation="generation-a",
            created_at="2026-08-12T00:00:00Z",
            browser_session="mid_lane_a",
        )

        store.save_ob("t2", credential)

        self.assertEqual(store.load_ob("t2"), credential)
        self.assertIsNone(store.load("t2"))
        store.delete_ob("t2")
        self.assertIsNone(store.load_ob("t2"))

    def test_cdp_filters_cookies_to_mis_origin(self):
        cookies = _cookies_for_origin(
            [
                {"name": "MGDID", "value": "device", "domain": ".moego.pet"},
                {
                    "name": "MGSID-MIS-PROD",
                    "value": "session",
                    "domain": "mis.moego.pet",
                },
                {"name": "OTHER", "value": "nope", "domain": "example.com"},
            ],
            "https://mis.moego.pet",
        )
        self.assertEqual(
            cookies,
            {"MGDID": "device", "MGSID-MIS-PROD": "session"},
        )

    def test_session_cookie_supports_prod_name_without_suffix(self):
        self.assertEqual(
            find_mis_session_cookie({"MGSID-MIS": "prod-session"}),
            ("MGSID-MIS", "prod-session"),
        )


if __name__ == "__main__":
    unittest.main()
