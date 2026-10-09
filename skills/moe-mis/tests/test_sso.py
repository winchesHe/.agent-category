import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mmis.commands import mis as mis_commands
from mmis.config import _legacy_env_paths, _value, load_config
from mmis.errors import SsoRejectedError, SsoUnavailableError
from mmis.keychain import MisCredential
from mmis.sso import SsoAuthenticator, SsoResult


def response(status=200, payload=None, text="", url="https://example.test"):
    result = Mock()
    result.status_code = status
    result.json.return_value = payload or {}
    result.text = text
    result.url = url
    result.headers = {}
    result.raise_for_status.side_effect = None
    return result


class SsoTests(unittest.TestCase):
    def test_process_legacy_name_overrides_lower_priority_current_name(self):
        with patch("sys.stderr"):
            value = _value(
                [{"MOE_MIS_SSO_USERNAME": "file-current"}, {"MIO_SSO_USERNAME": "process-legacy"}],
                "MOE_MIS_SSO_USERNAME",
                "MIO_SSO_USERNAME",
            )
        self.assertEqual("process-legacy", value)

    def test_current_name_can_explicitly_clear_legacy_value(self):
        value = _value(
            [{"MIO_SSO_USERNAME": "legacy"}, {"MOE_MIS_SSO_USERNAME": ""}],
            "MOE_MIS_SSO_USERNAME",
            "MIO_SSO_USERNAME",
        )
        self.assertEqual("", value)

    def test_legacy_paths_include_previous_sibling_skill(self):
        skill_root = Path("/workspace/moe-mis")
        self.assertIn(
            Path("/workspace/moe-internal-ops/.env"),
            _legacy_env_paths(skill_root),
        )

    def test_config_loads_sso_without_exposing_it_in_repr(self):
        with patch.dict(
            "os.environ",
            {
                "MIO_SSO_USERNAME": "winches",
                "MIO_SSO_PASSWORD": "secret-value",
            },
            clear=False,
        ):
            config = load_config("production")
        self.assertEqual(config.sso_username, "winches")
        self.assertEqual(config.sso_password, "secret-value")
        self.assertNotIn("secret-value", repr(config))

    def test_new_environment_names_override_legacy_names(self):
        with patch.dict(
            "os.environ",
            {
                "MIO_SSO_USERNAME": "legacy",
                "MIO_SSO_PASSWORD": "legacy-secret",
                "MOE_MIS_SSO_USERNAME": "current",
                "MOE_MIS_SSO_PASSWORD": "current-secret",
            },
            clear=False,
        ):
            config = load_config("t2")
        self.assertEqual("current", config.sso_username)
        self.assertEqual("current-secret", config.sso_password)
        self.assertNotIn("current-secret", repr(config))

    def test_sso_authenticates_and_extracts_dynamic_mis_cookie(self):
        session = Mock()
        login_url_response = response(
            payload={
                "loginUrl": (
                    "https://cas.moego.pet/auth/realms/Moement/"
                    "protocol/openid-connect/auth"
                )
            }
        )
        form_response = response(
            text=(
                '<form action="https://cas.moego.pet/auth/realms/Moement/'
                'login-actions/authenticate?session_code=x">'
                '<input type="hidden" name="credentialId" value=""></form>'
            ),
            url=(
                "https://cas.moego.pet/auth/realms/Moement/"
                "protocol/openid-connect/auth"
            ),
        )
        cas_response = response(status=302)
        cas_response.headers = {
            "Location": (
                "https://mis.moego.pet/login?state=state-1"
                "&session_state=session-1&code=code-1"
            )
        }
        mis_login_response = response(payload={})
        account_response = response(
            payload={"account": {"id": "account-1", "email": "winches@moego.pet"}}
        )
        session.post.side_effect = [
            login_url_response,
            cas_response,
            mis_login_response,
            account_response,
        ]
        session.get.return_value = form_response
        jar = requests.cookies.RequestsCookieJar()
        jar.set("MGSID-MIS", "session", domain="mis.moego.pet")
        session.cookies = jar

        result = SsoAuthenticator(session=session).authenticate(
            "https://mis.moego.pet", "winches", "password"
        )

        self.assertEqual(result.account["email"], "winches@moego.pet")
        self.assertEqual(
            result.credential.session_cookie_name, "MGSID-MIS"
        )
        self.assertEqual(result.credential.mgdid, "")
        cas_payload = session.post.call_args_list[1].kwargs["data"]
        self.assertEqual(cas_payload["username"], "winches")
        self.assertEqual(cas_payload["password"], "password")

    def test_rejected_credentials_do_not_become_unavailable(self):
        session = Mock()
        session.post.return_value = response(
            payload={
                "loginUrl": (
                    "https://cas.moego.pet/auth/realms/Moement/"
                    "protocol/openid-connect/auth"
                )
            }
        )
        session.get.return_value = response(
            text='<form action="/authenticate"></form>',
            url=(
                "https://cas.moego.pet/auth/realms/Moement/"
                "protocol/openid-connect/auth"
            ),
        )
        session.post.side_effect = [
            session.post.return_value,
            response(status=200, text="Invalid username or password"),
        ]
        with self.assertRaises(SsoRejectedError):
            SsoAuthenticator(session=session).authenticate(
                "https://mis.moego.pet", "winches", "wrong"
            )

    def test_missing_login_form_is_protocol_unavailable(self):
        session = Mock()
        session.post.return_value = response(
            payload={
                "loginUrl": (
                    "https://cas.moego.pet/auth/realms/Moement/"
                    "protocol/openid-connect/auth"
                )
            }
        )
        session.get.return_value = response(text="<html></html>")
        with self.assertRaises(SsoUnavailableError):
            SsoAuthenticator(session=session).authenticate(
                "https://mis.moego.pet", "winches", "password"
            )

    def test_untrusted_sso_login_origin_is_rejected(self):
        session = Mock()
        session.post.return_value = response(
            payload={
                "loginUrl": (
                    "https://evil.example/auth/realms/Moement/"
                    "protocol/openid-connect/auth"
                )
            }
        )
        with self.assertRaises(SsoUnavailableError):
            SsoAuthenticator(session=session).authenticate(
                "https://mis.moego.pet", "winches", "password"
            )
        session.get.assert_not_called()

    @patch.object(mis_commands, "capture_mis_credential")
    @patch.object(mis_commands, "CredentialStore")
    @patch.object(mis_commands, "SsoAuthenticator")
    def test_auto_does_not_skip_chrome_control_when_sso_unavailable(
        self, authenticator_cls, store_cls, capture
    ):
        store_cls.return_value.load.return_value = None
        authenticator_cls.return_value.authenticate.side_effect = (
            SsoUnavailableError("unsupported")
        )
        config = load_config("production")
        with self.assertRaises(SsoUnavailableError):
            mis_commands._client(config, force=True, auth_method="auto")
        capture.assert_not_called()

    @patch.object(mis_commands, "capture_mis_credential")
    @patch.object(mis_commands, "CredentialStore")
    def test_isolated_fallback_must_be_explicit(self, store_cls, capture):
        credential = MisCredential(
            mgdid="device",
            session_cookie_name="MGSID-MIS-PROD",
            session_cookie_value="session",
        )
        store_cls.return_value.load.return_value = None
        capture.return_value = credential
        config = load_config("production")
        with patch.object(mis_commands.MisClient, "account_info") as account_info:
            account_info.return_value = {
                "account": {"id": "1", "email": "winches@moego.pet"}
            }
            mis_commands._client(
                config, force=True, auth_method="isolated"
            )
        capture.assert_called_once()

    @patch.object(mis_commands, "CredentialStore")
    @patch.object(mis_commands, "SsoAuthenticator")
    def test_sso_success_is_saved_to_keychain(
        self, authenticator_cls, store_cls
    ):
        credential = MisCredential(
            mgdid="device",
            session_cookie_name="MGSID-MIS-PROD",
            session_cookie_value="session",
        )
        authenticator_cls.return_value.authenticate.return_value = SsoResult(
            credential=credential,
            account={"id": "1", "email": "winches@moego.pet"},
        )
        store_cls.return_value.load.return_value = None
        config = load_config("production")
        mis_commands._client(config, force=True, auth_method="sso")
        store_cls.return_value.save.assert_called_once_with(
            "production", credential
        )


if __name__ == "__main__":
    unittest.main()
