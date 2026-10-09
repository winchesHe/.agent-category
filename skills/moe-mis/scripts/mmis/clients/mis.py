from urllib.parse import quote

from ..config import ENV_URLS
from ..errors import ConfigError

ACCOUNT_INFO = "/moego.admin.authentication.v1.AuthenticationService/GetAccountInfo"
CREATE_TOKEN = "/moego.admin.account.v1.AccountService/CreateLoginToken"
DESCRIBE_ACCOUNT = (
    "/moego.admin.account.v1.AccountService/DescribeAccountWithCompanies"
)
CHECK_OB_SESSION = (
    "/moego.admin.online_booking.v1.OnlineBookingService/CheckSession"
)
START_OB_IMPERSONATE = (
    "/moego.admin.online_booking.v1.OnlineBookingService/Impersonate"
)
STOP_OB_IMPERSONATE = (
    "/moego.admin.online_booking.v1.OnlineBookingService/RemoveImpersonate"
)

PROFILE_TYPES = {
    "email": "accountEmail",
    "account-email": "accountEmail",
    "aid": "accountId",
    "account-id": "accountId",
    "bid": "businessId",
    "business-id": "businessId",
    "cid": "companyId",
    "company-id": "companyId",
    "sid": "staffId",
    "staff-id": "staffId",
}
MAX_AGE_SECONDS = {
    "h1": "3600s",
    "h2": "7200s",
    "d1": "86400s",
    "d7": "604800s",
    "d15": "1296000s",
}
TOKEN_PASSWORD_PREFIX = "d1ad54da5f06:"


def normalize_profile_type(value):
    try:
        return PROFILE_TYPES[value]
    except KeyError as exc:
        raise ConfigError(f"未知 profile type：{value}") from exc


def build_target_url(env, source, token):
    urls = ENV_URLS[env]
    encoded = quote(token, safe="")
    if source == "customer":
        return "{}/login/welcome?token={}".format(urls["customer"], encoded)
    return "{}/sign_in?token={}".format(urls["go"], encoded)


def build_app_password(token):
    return TOKEN_PASSWORD_PREFIX + token


class MisClient:
    def __init__(self, base_url, http, credential):
        self.base_url = base_url.rstrip("/")
        self.http = http
        self.credential = credential

    @property
    def headers(self):
        return {"Cookie": self.credential.cookie_header}

    @property
    def ob_headers(self):
        return {
            "Cookie": self.http.cookie_header(self.credential.cookie_header)
        }

    def account_info(self):
        return self.http.post(
            self.base_url + ACCOUNT_INFO, json={}, headers=self.headers
        )

    def profile(self, profile_type, value):
        field = normalize_profile_type(profile_type)
        return self.http.post(
            self.base_url + DESCRIBE_ACCOUNT,
            json={"type": field, "value": value},
            headers=self.headers,
        )

    def impersonate(self, email, max_age, source):
        try:
            duration = MAX_AGE_SECONDS[max_age]
        except KeyError as exc:
            raise ConfigError(f"未知 max-age：{max_age}") from exc
        return self.http.post(
            self.base_url + CREATE_TOKEN,
            json={"email": email, "maxAge": duration, "source": source},
            headers=self.headers,
        )

    def check_ob_session(self):
        return self.http.post(
            self.base_url + CHECK_OB_SESSION,
            json={},
            headers=self.ob_headers,
        )

    def start_ob_impersonate(self):
        return self.http.post(
            self.base_url + START_OB_IMPERSONATE,
            json={},
            headers=self.ob_headers,
        )

    def stop_ob_impersonate(self):
        return self.http.post(
            self.base_url + STOP_OB_IMPERSONATE,
            json={},
            headers=self.ob_headers,
        )

    def export_ob_cookies(self):
        return self.http.export_cookies(
            excluded_names=("MGDID", self.credential.session_cookie_name)
        )

    def import_ob_cookies(self, cookies):
        self.http.import_cookies(cookies)
