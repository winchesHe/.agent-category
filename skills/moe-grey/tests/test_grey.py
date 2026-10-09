import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mgrey.clients.grey import GreyClient
from mgrey.errors import BusinessError, ConfigError
from mgrey.grey_mutation import GreyMutationService


class GreyTests(unittest.TestCase):
    def setUp(self):
        self.http = Mock()
        self.client = GreyClient("https://grey.example.test", self.http)

    def test_list_uses_rpc_wrapper(self):
        self.http.post.return_value = {"greyItems": []}
        self.assertEqual(self.client.list("ns-testing"), [])
        self.assertEqual(
            self.http.post.call_args.kwargs["json"],
            {"namespace": "ns-testing"},
        )

    def test_branches_unwraps_name_wrapper(self):
        self.http.post.return_value = {
            "svcBranchesMap": {"svc-a": {"name": ["main", "feature-a"]}}
        }
        self.assertEqual(
            self.client.branches("ns-testing"),
            {"svc-a": ["main", "feature-a"]},
        )

    def test_insert_sends_direct_proto_payload(self):
        item = {
            "name": "rule-a",
            "namespace": "ns-testing",
            "svcBranchMap": {"svc-a": "main"},
        }
        self.http.post.return_value = {"id": "1", **item}
        self.client.insert(item)
        self.assertEqual(self.http.post.call_args.kwargs["json"], item)

    def test_create_without_apply_is_plan_only(self):
        self.client.get_by_name = Mock(return_value=None)
        self.client.branches = Mock(return_value={"svc-a": ["main", "feat"]})
        self.client.insert = Mock()
        service = GreyMutationService(self.client)
        result = service.create(
            namespace="ns-testing",
            name="rule-a",
            description="demo",
            jira_tickets=["OPS-1"],
            service_map={"svc-a": "feat"},
            apply=False,
        )
        self.assertEqual(result["mode"], "plan")
        self.assertEqual(result["after"]["name"], "rule-a")
        self.client.insert.assert_not_called()

    def test_update_apply_rejects_stale_updated_at(self):
        self.client.get = Mock(
            return_value={
                "id": "1",
                "name": "rule-a",
                "namespace": "ns-testing",
                "updatedAt": "newer",
            }
        )
        service = GreyMutationService(self.client)
        with self.assertRaises(BusinessError):
            service.update(
                selector={"id": "1"},
                changes={"description": "changed"},
                expected_updated_at="older",
                apply=True,
            )

    def test_delete_requires_exact_rule_name(self):
        self.client.get = Mock(
            return_value={
                "id": "1",
                "name": "rule-a",
                "namespace": "ns-testing",
                "updatedAt": "v1",
            }
        )
        service = GreyMutationService(self.client)
        with self.assertRaises(ConfigError):
            service.delete(
                selector={"id": "1"},
                confirm="RULE-A",
                expected_updated_at="v1",
                apply=True,
            )

    def test_delete_apply_verifies_item_is_absent(self):
        item = {
            "id": "1",
            "name": "rule-a",
            "namespace": "ns-testing",
            "updatedAt": "v1",
        }
        self.client.get = Mock(side_effect=[item, item])
        self.client.delete = Mock(return_value={})
        self.client.get_optional = Mock(return_value=None)
        result = GreyMutationService(self.client).delete(
            selector={"id": "1"},
            confirm="rule-a",
            expected_updated_at="v1",
            apply=True,
        )
        self.assertTrue(result["deleted"])
        self.client.get_optional.assert_called_once_with({"id": "1"})

    def test_delete_apply_accepts_soft_deleted_id_record(self):
        item = {
            "id": "1",
            "name": "rule-a",
            "namespace": "ns-testing",
            "updatedAt": "v1",
        }
        deleted = {
            **item,
            "updatedAt": "v2",
            "deletedAt": "v2",
        }
        self.client.get = Mock(side_effect=[item, item])
        self.client.delete = Mock(return_value={})
        self.client.get_optional = Mock(return_value=deleted)
        self.client.get_by_name = Mock(return_value=None)
        result = GreyMutationService(self.client).delete(
            selector={"id": "1"},
            confirm="rule-a",
            expected_updated_at="v1",
            apply=True,
        )
        self.assertTrue(result["deleted"])
        self.assertEqual(result["deletedAt"], "v2")


if __name__ == "__main__":
    unittest.main()
