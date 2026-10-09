import hashlib
import json
from copy import deepcopy

from .errors import BusinessError, ConfigError


def key_state_hash(key):
    encoded = json.dumps(
        key, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _value_snapshot(owner_ids, values):
    by_owner = {str(item.get("ownerId")): item for item in values}
    return [
        {
            "ownerId": owner_id,
            "value": by_owner.get(owner_id, {}).get("value"),
            "updatedAt": by_owner.get(owner_id, {}).get("updatedAt"),
        }
        for owner_id in sorted({str(item) for item in owner_ids})
    ]


def value_state_hash(key_id, owner_ids, values):
    state = {
        "keyId": str(key_id),
        "values": _value_snapshot(owner_ids, values),
    }
    encoded = json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_key_fields(fields, require_name=False):
    constraints = {
        "name": (2, 50),
        "description": (2, 255),
        "defaultValue": (0, 1024),
        "group": (1, 50),
    }
    if require_name and not fields.get("name"):
        raise ConfigError("Metadata Key name 必填")
    for field, (minimum, maximum) in constraints.items():
        if field not in fields:
            continue
        value = fields[field]
        if value is None and field in ("defaultValue",):
            continue
        length = len(value or "")
        if length < minimum or length > maximum:
            raise ConfigError(
                "Metadata {} 长度必须为 {}-{}".format(
                    field, minimum, maximum
                )
            )


class MetadataMutationService:
    def __init__(self, client):
        self.client = client

    @staticmethod
    def _verify_key(actual, expected, fields):
        mismatched = [
            field for field in fields if actual.get(field) != expected.get(field)
        ]
        if mismatched:
            raise BusinessError(
                "Metadata Key 写后回读不一致：{}".format(", ".join(mismatched))
            )

    def create(self, key_def, apply=False):
        _validate_key_fields(key_def, require_name=True)
        if self.client.find_key_by_name(key_def["name"]):
            raise BusinessError(f"Metadata Key 已存在：{key_def['name']}")
        plan = {
            "mode": "apply" if apply else "plan",
            "operation": "create",
            "after": key_def,
        }
        if not apply:
            return plan
        created = self.client.create_key(key_def)
        actual = self.client.get_key(created["id"])
        self._verify_key(actual, key_def, tuple(key_def))
        plan["result"] = actual
        return plan

    def update(
        self,
        key_id,
        changes,
        expected_updated_at=None,
        expected_state_hash=None,
        apply=False,
    ):
        before = self.client.get_key(key_id)
        partial = dict(changes)
        if not partial:
            raise ConfigError("Metadata update 至少需要一个待更新字段")
        _validate_key_fields(partial)
        after = deepcopy(before)
        after.update(partial)
        plan = {
            "mode": "apply" if apply else "plan",
            "operation": "update",
            "before": before,
            "after": after,
            "changes": partial,
            "expectedUpdatedAt": before.get("updatedAt"),
            "expectedStateHash": key_state_hash(before),
        }
        if not apply:
            return plan
        if not expected_updated_at and not expected_state_hash:
            raise ConfigError(
                "--apply update 必须传 --expected-updated-at "
                "或 --expected-state-hash"
            )
        current = self.client.get_key(key_id)
        timestamp_conflict = (
            expected_updated_at
            and current.get("updatedAt") != expected_updated_at
        )
        hash_conflict = (
            expected_state_hash
            and key_state_hash(current) != expected_state_hash
        )
        if timestamp_conflict or hash_conflict:
            raise BusinessError("Metadata Key 已被更新；请重新生成 plan")
        self.client.update_key(key_id, partial)
        actual = self.client.get_key(key_id)
        self._verify_key(actual, after, tuple(partial))
        plan["result"] = actual
        return plan

    def delete(
        self,
        key_id,
        confirm=None,
        expected_updated_at=None,
        expected_state_hash=None,
        apply=False,
    ):
        before = self.client.get_key(key_id)
        plan = {
            "mode": "apply" if apply else "plan",
            "operation": "delete",
            "before": before,
            "snapshot": before,
            "expectedUpdatedAt": before.get("updatedAt"),
            "expectedStateHash": key_state_hash(before),
        }
        if not apply:
            return plan
        if confirm != before.get("name"):
            raise ConfigError("--confirm 必须与 Metadata Key 名称完全一致")
        if not expected_updated_at and not expected_state_hash:
            raise ConfigError(
                "--apply delete 必须传 --expected-updated-at "
                "或 --expected-state-hash"
            )
        current = self.client.get_key(key_id)
        timestamp_conflict = (
            expected_updated_at
            and current.get("updatedAt") != expected_updated_at
        )
        hash_conflict = (
            expected_state_hash
            and key_state_hash(current) != expected_state_hash
        )
        if timestamp_conflict or hash_conflict:
            raise BusinessError("Metadata Key 已被更新；请重新生成 plan")
        self.client.delete_key(key_id)
        if self.client.get_key_optional(key_id) is not None:
            raise BusinessError("Metadata Key 删除后回读仍存在")
        plan["deleted"] = True
        return plan

    def set_value(
        self,
        key_id,
        owner_ids,
        value,
        expected_state_hash=None,
        apply=False,
    ):
        normalized_ids = sorted({str(item) for item in owner_ids})
        if not normalized_ids:
            raise ConfigError("set-value 至少需要一个 --owner-id")
        before_result = self.client.list_values(
            key_id, normalized_ids, page=1, page_size=max(100, len(normalized_ids))
        )
        before = before_result.get("values", [])
        current_hash = value_state_hash(key_id, normalized_ids, before)
        plan = {
            "mode": "apply" if apply else "plan",
            "operation": "set-value",
            "keyId": str(key_id),
            "ownerIds": normalized_ids,
            "before": _value_snapshot(normalized_ids, before),
            "afterValue": value,
            "expectedStateHash": current_hash,
        }
        if not apply:
            return plan
        if not expected_state_hash:
            raise ConfigError("--apply set-value 必须传 --expected-state-hash")
        latest_result = self.client.list_values(
            key_id, normalized_ids, page=1, page_size=max(100, len(normalized_ids))
        )
        latest = latest_result.get("values", [])
        if value_state_hash(key_id, normalized_ids, latest) != expected_state_hash:
            raise BusinessError("Metadata Value 已被更新；请重新生成 plan")
        self.client.batch_update_value(key_id, normalized_ids, value)
        result = self.client.list_values(
            key_id, normalized_ids, page=1, page_size=max(100, len(normalized_ids))
        )
        actual = {
            str(item.get("ownerId")): item.get("value")
            for item in result.get("values", [])
        }
        mismatched = [
            owner_id
            for owner_id in normalized_ids
            if actual.get(owner_id) != value
        ]
        if mismatched:
            raise BusinessError(
                "Metadata Value 写后回读不一致：{}".format(", ".join(mismatched))
            )
        plan["result"] = result
        return plan
