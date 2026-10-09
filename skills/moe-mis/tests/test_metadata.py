import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mmis.clients.metadata import (
    MetadataClient,
    normalize_owner_type,
    normalize_permission_level,
)
from mmis.errors import BusinessError, ConfigError
from mmis.keychain import MisCredential
from mmis.metadata_mutation import (
    MetadataMutationService,
    key_state_hash,
    value_state_hash,
)
from mmis.commands import metadata as metadata_commands
from moe_mis import build_parser


class MetadataClientTests(unittest.TestCase):
    def setUp(self):
        self.http = Mock()
        self.credential = MisCredential(
            mgdid="",
            session_cookie_name="MGSID-MIS",
            session_cookie_value="session",
        )
        self.client = MetadataClient(
            "https://mis.example.test", self.http, self.credential
        )

    def test_enum_short_names_are_normalized(self):
        self.assertEqual(normalize_owner_type("staff"), "OWNER_TYPE_STAFF")
        self.assertEqual(
            normalize_owner_type("OWNER_TYPE_COMPANY"), "OWNER_TYPE_COMPANY"
        )
        self.assertEqual(
            normalize_permission_level("company-any-staff"),
            "PERMISSION_LEVEL_COMPANY_ANY_STAFF",
        )
        with self.assertRaises(ConfigError):
            normalize_owner_type("unknown")

    def test_list_keys_sends_filters_and_pagination(self):
        self.http.post.return_value = {"keys": [], "pagination": {"total": 0}}
        result = self.client.list_keys(
            group="BD",
            owner_type="staff",
            name_like="task",
            page=2,
            page_size=50,
        )
        self.assertEqual(result["keys"], [])
        self.assertEqual(
            self.http.post.call_args.kwargs["json"],
            {
                "group": "BD",
                "ownerType": "OWNER_TYPE_STAFF",
                "nameLike": "task",
                "pagination": {"pageNum": 2, "pageSize": 50},
            },
        )

    def test_value_endpoints_use_expected_payloads(self):
        self.http.post.side_effect = [
            {"owners": {}, "values": [], "pagination": {"total": 0}},
            {"key": {"id": "10"}, "value": {"ownerId": "20", "value": "on"}},
        ]
        self.client.list_values("10", ["20"], page=1, page_size=100)
        self.assertEqual(
            self.http.post.call_args_list[0].kwargs["json"],
            {
                "keyId": "10",
                "ownerIds": ["20"],
                "pagination": {"pageNum": 1, "pageSize": 100},
            },
        )
        self.client.get_value("10", "20")
        self.assertEqual(
            self.http.post.call_args_list[1].kwargs["json"],
            {"keyId": "10", "ownerId": "20"},
        )

    def test_mutation_endpoints_wrap_proto_payloads(self):
        key_def = {
            "name": "feature_x",
            "description": "Feature X",
            "ownerType": "OWNER_TYPE_COMPANY",
            "defaultValue": "off",
            "permissionLevel": "PERMISSION_LEVEL_OWNER",
            "group": "Growth",
        }
        self.http.post.side_effect = [
            {"key": {"id": "10", **key_def}},
            {},
            {},
            {},
        ]
        self.client.create_key(key_def)
        self.client.update_key("10", {"description": "Changed"})
        self.client.delete_key("10")
        self.client.batch_update_value("10", ["20", "21"], "on")
        self.assertEqual(
            [call.kwargs["json"] for call in self.http.post.call_args_list],
            [
                {"keyDef": key_def},
                {"id": "10", "keyDef": {"description": "Changed"}},
                {"id": "10"},
                {"keyId": "10", "ownerIds": ["20", "21"], "value": "on"},
            ],
        )

    def test_parser_dispatches_metadata_handler(self):
        args = build_parser().parse_args(["metadata", "groups"])

        self.assertIs(metadata_commands.run, args._handler)

    def test_skill_metadata_examples_match_parser_contract(self):
        examples = (
            [
                "metadata",
                "get-value",
                "--key-id",
                "key-1",
                "--owner-id",
                "owner-1",
            ],
            [
                "metadata",
                "create",
                "--group",
                "BD",
                "--name",
                "feature-name",
                "--description",
                "description",
                "--owner-type",
                "staff",
                "--default-value",
                "off",
                "--permission-level",
                "owner",
            ],
        )

        for example in examples:
            with self.subTest(example=example):
                self.assertIs(
                    metadata_commands.run,
                    build_parser().parse_args(example)._handler,
                )


class MetadataMutationTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.service = MetadataMutationService(self.client)

    def test_create_plan_does_not_write(self):
        self.client.find_key_by_name.return_value = None
        key_def = {
            "name": "feature_x",
            "description": "Feature X",
            "ownerType": "OWNER_TYPE_COMPANY",
            "defaultValue": "off",
            "permissionLevel": "PERMISSION_LEVEL_OWNER",
            "group": "Growth",
        }
        result = self.service.create(key_def, apply=False)
        self.assertEqual(result["mode"], "plan")
        self.assertEqual(result["after"], key_def)
        self.client.create_key.assert_not_called()

    def test_update_apply_rejects_stale_key(self):
        before = {
            "id": "10",
            "name": "feature_x",
            "description": "old",
            "updatedAt": "newer",
        }
        self.client.get_key.return_value = before
        with self.assertRaises(BusinessError):
            self.service.update(
                "10",
                {"description": "new"},
                expected_updated_at="older",
                apply=True,
            )
        self.client.update_key.assert_not_called()

    def test_delete_requires_exact_key_name(self):
        self.client.get_key.return_value = {
            "id": "10",
            "name": "feature_x",
            "updatedAt": "v1",
        }
        with self.assertRaises(ConfigError):
            self.service.delete(
                "10",
                confirm="FEATURE_X",
                expected_updated_at="v1",
                apply=True,
            )
        self.client.delete_key.assert_not_called()

    def test_update_without_updated_at_uses_state_hash(self):
        before = {
            "id": "10",
            "name": "feature_x",
            "description": "old",
        }
        after = {**before, "description": "new"}
        self.client.get_key.side_effect = [before, before, after]
        result = self.service.update(
            "10",
            {"description": "new"},
            expected_state_hash=key_state_hash(before),
            apply=True,
        )
        self.assertEqual(result["result"], after)
        self.client.update_key.assert_called_once_with(
            "10", {"description": "new"}
        )

    def test_delete_without_updated_at_uses_state_hash(self):
        before = {"id": "10", "name": "feature_x", "description": "old"}
        self.client.get_key.side_effect = [before, before]
        self.client.get_key_optional.return_value = None
        result = self.service.delete(
            "10",
            confirm="feature_x",
            expected_state_hash=key_state_hash(before),
            apply=True,
        )
        self.assertTrue(result["deleted"])
        self.client.delete_key.assert_called_once_with("10")

    def test_set_value_plan_returns_stable_state_hash_without_write(self):
        self.client.list_values.return_value = {
            "values": [
                {"ownerId": "2", "value": "old-2", "updatedAt": "v2"},
                {"ownerId": "1", "value": "old-1", "updatedAt": "v1"},
            ]
        }
        result = self.service.set_value(
            "10", ["2", "1"], "new", expected_state_hash=None, apply=False
        )
        self.assertEqual(result["mode"], "plan")
        self.assertEqual(
            result["expectedStateHash"],
            value_state_hash(
                "10",
                ["1", "2"],
                [
                    {"ownerId": "1", "value": "old-1", "updatedAt": "v1"},
                    {"ownerId": "2", "value": "old-2", "updatedAt": "v2"},
                ],
            ),
        )
        self.client.batch_update_value.assert_not_called()

    def test_set_value_apply_rejects_stale_state(self):
        self.client.list_values.return_value = {
            "values": [{"ownerId": "1", "value": "changed", "updatedAt": "v2"}]
        }
        with self.assertRaises(BusinessError):
            self.service.set_value(
                "10",
                ["1"],
                "new",
                expected_state_hash="stale",
                apply=True,
            )
        self.client.batch_update_value.assert_not_called()

    def test_set_value_apply_writes_and_verifies(self):
        before = [{"ownerId": "1", "value": "old", "updatedAt": "v1"}]
        after = [{"ownerId": "1", "value": "new", "updatedAt": "v2"}]
        self.client.list_values.side_effect = [
            {"values": before},
            {"values": before},
            {"values": after},
        ]
        expected = value_state_hash("10", ["1"], before)
        result = self.service.set_value(
            "10", ["1"], "new", expected_state_hash=expected, apply=True
        )
        self.assertEqual(result["result"]["values"], after)
        self.client.batch_update_value.assert_called_once_with("10", ["1"], "new")


if __name__ == "__main__":
    unittest.main()
