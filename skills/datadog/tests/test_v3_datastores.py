from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from dd_v3.errors import ApiError
from dd_v3.runtime import READ, RuntimeContext, RuntimeState
from dd_v3.commands import datastores


def datastore(
    index: int = 1,
    *,
    name: str = "intercom-feedback",
    strategy: str = "none",
):
    return {
        "id": f"store-{index}",
        "type": "datastores",
        "attributes": {
            "name": name,
            "description": "Intercom feedback",
            "primary_column_name": "id",
            "primary_key_generation_strategy": strategy,
            "created_at": "2025-10-13T09:22:00Z",
            "modified_at": "2025-10-13T09:22:00Z",
            "creator_user_id": 123,
            "creator_user_uuid": "creator-secret",
            "org_id": 456,
        },
    }


class RecordingClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request_read(self, method, path, *, params=None, json_body=None, surface="api"):
        self.calls.append({"method": method, "path": path, "params": params})
        return self.response


def context(response):
    client = RecordingClient(response)
    return (
        RuntimeContext(config=SimpleNamespace(), client=client, state=RuntimeState()),
        client,
    )


def parser():
    value = argparse.ArgumentParser()
    subparsers = value.add_subparsers(dest="command", required=True)
    datastores.register(subparsers)
    return value


class DatastoresTests(unittest.TestCase):
    def test_parser_is_read_only(self):
        args = parser().parse_args(["list-datastores"])

        self.assertEqual(READ, args._policy)
        self.assertEqual("json", args.fmt)

    def test_lists_safe_discovery_metadata(self):
        args = parser().parse_args(["list-datastores"])
        ctx, client = context({"data": [datastore()]})

        result = datastores.run(args, ctx)

        self.assertEqual(
            [{
                "method": "GET",
                "path": "/api/v2/actions-datastores",
                "params": None,
            }],
            client.calls,
        )
        self.assertEqual("actions_datastores", result.target["kind"])
        self.assertEqual("intercom-feedback", result.result["datastores"][0]["name"])
        self.assertEqual("complete", result.meta["pagination"]["completion"])
        serialized = repr(result.result)
        self.assertNotIn("creator_user_id", serialized)
        self.assertNotIn("creator-secret", serialized)
        self.assertNotIn("org_id", serialized)

    def test_unpaged_result_is_bounded_and_marks_unknown_completion(self):
        args = parser().parse_args(["list-datastores"])
        values = [datastore(index, name=f"store-{index}") for index in range(1001)]
        ctx, _client = context({"data": values})

        result = datastores.run(args, ctx)

        self.assertEqual(1000, result.result["returned"])
        self.assertEqual(1001, result.meta["pagination"]["total"])
        self.assertEqual("unknown", result.meta["pagination"]["completion"])
        self.assertEqual(["datastores_truncated"], result.warnings)

    def test_invalid_resource_shape_fails_closed(self):
        args = parser().parse_args(["list-datastores"])
        invalid_cases = [
            [],
            {"data": {}},
            {"data": [{"id": "one", "type": "items", "attributes": {}}]},
            {"data": [datastore(strategy="invalid")]},
            {"data": [datastore(strategy=["none"])]},
        ]

        for response in invalid_cases:
            with self.subTest(response=response):
                ctx, _client = context(response)
                with self.assertRaisesRegex(ApiError, "invalid datastore"):
                    datastores.run(args, ctx)


if __name__ == "__main__":
    unittest.main()
