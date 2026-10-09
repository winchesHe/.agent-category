from ..errors import BusinessError, ConfigError

SERVICE = "/moego.admin.metadata.v1.MetadataAdminService/"

OWNER_TYPES = {
    "system": "OWNER_TYPE_SYSTEM",
    "company": "OWNER_TYPE_COMPANY",
    "business": "OWNER_TYPE_BUSINESS",
    "staff": "OWNER_TYPE_STAFF",
    "account": "OWNER_TYPE_ACCOUNT",
    "enterprise": "OWNER_TYPE_ENTERPRISE",
}
PERMISSION_LEVELS = {
    "owner": "PERMISSION_LEVEL_OWNER",
    "nobody": "PERMISSION_LEVEL_NOBODY",
    "company-any-business-owner": "PERMISSION_LEVEL_COMPANY_ANY_BUSINESS_OWNER",
    "company-any-staff": "PERMISSION_LEVEL_COMPANY_ANY_STAFF",
    "business-any-staff": "PERMISSION_LEVEL_BUSINESS_ANY_STAFF",
}


def _normalize_enum(value, values, label):
    if value is None:
        return None
    normalized = values.get(value.lower(), value.upper())
    if normalized not in values.values():
        raise ConfigError(f"未知 Metadata {label}：{value}")
    return normalized


def normalize_owner_type(value):
    return _normalize_enum(value, OWNER_TYPES, "owner type")


def normalize_permission_level(value):
    return _normalize_enum(value, PERMISSION_LEVELS, "permission level")


class MetadataClient:
    def __init__(self, base_url, http, credential):
        self.base_url = base_url.rstrip("/")
        self.http = http
        self.credential = credential

    @property
    def headers(self):
        return {"Cookie": self.credential.cookie_header}

    def _post(self, method, payload):
        return self.http.post(
            self.base_url + SERVICE + method,
            json=payload,
            headers=self.headers,
        )

    def groups(self):
        return self._post("DescribeGroups", {}).get("groups", [])

    def list_keys(
        self,
        group=None,
        owner_type=None,
        name_like=None,
        page=1,
        page_size=100,
    ):
        if page < 1 or page_size < 1:
            raise ConfigError("Metadata 分页参数必须大于 0")
        payload = {"pagination": {"pageNum": page, "pageSize": page_size}}
        if group:
            payload["group"] = group
        if owner_type:
            payload["ownerType"] = normalize_owner_type(owner_type)
        if name_like:
            payload["nameLike"] = name_like
        return self._post("DescribeKeys", payload)

    def get_key(self, key_id):
        result = self._post("GetKey", {"id": str(key_id)})
        key = result.get("key")
        if not key:
            raise BusinessError(f"Metadata Key 不存在：{key_id}")
        return key

    def get_key_optional(self, key_id):
        try:
            return self.get_key(key_id)
        except BusinessError as exc:
            message = str(exc)
            if "不存在" in message or "HTTP 404" in message:
                return None
            raise

    def find_key_by_name(self, name):
        result = self.list_keys(name_like=name, page=1, page_size=100)
        return next(
            (item for item in result.get("keys", []) if item.get("name") == name),
            None,
        )

    def create_key(self, key_def):
        result = self._post("CreateKey", {"keyDef": key_def})
        return result.get("key", result)

    def update_key(self, key_id, key_def):
        return self._post(
            "UpdateKey", {"id": str(key_id), "keyDef": key_def}
        )

    def delete_key(self, key_id):
        return self._post("DeleteKey", {"id": str(key_id)})

    def list_values(
        self, key_id, owner_ids=None, page=1, page_size=100
    ):
        if page < 1 or page_size < 1:
            raise ConfigError("Metadata 分页参数必须大于 0")
        payload = {
            "keyId": str(key_id),
            "pagination": {"pageNum": page, "pageSize": page_size},
        }
        if owner_ids:
            payload["ownerIds"] = [str(item) for item in owner_ids]
        return self._post("DescribeValues", payload)

    def get_value(self, key_id, owner_id):
        return self._post(
            "GetValue",
            {"keyId": str(key_id), "ownerId": str(owner_id)},
        )

    def batch_update_value(self, key_id, owner_ids, value):
        return self._post(
            "BatchUpdateValue",
            {
                "keyId": str(key_id),
                "ownerIds": [str(item) for item in owner_ids],
                "value": value,
            },
        )
