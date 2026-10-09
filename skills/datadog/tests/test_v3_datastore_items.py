from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from dd_v3.errors import ApiError, UsageError
from dd_v3.runtime import READ, RuntimeContext, RuntimeState
from dd_v3.commands import datastore_items


def response(values, *, has_more=False, total=None, fields=None):
    schema_fields = fields or [
        {"name": "id", "type": "STRING"},
        {"name": "requirement", "type": "JSON"},
        {"name": "email", "type": "JSON"},
    ]
    return {
        "data": [
            {
                "id": f"item-{index}",
                "type": "items",
                "attributes": {
                    "created_at": "2026-08-20T00:00:00Z",
                    "modified_at": "2026-08-20T01:00:00Z",
                    "value": value,
                },
            }
            for index, value in enumerate(values)
        ],
        "meta": {
            "page": {
                "hasMore": has_more,
                "totalCount": total if total is not None else len(values),
                "totalFilteredCount": total if total is not None else len(values),
            },
            "schema": {"primary_key": "id", "fields": schema_fields},
        },
    }


class RecordingClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request_read(self, method, path, *, params=None, json_body=None, surface="api"):
        self.calls.append({"method": method, "path": path, "params": params})
        return self.responses.pop(0)


def context(*responses):
    client = RecordingClient(responses)
    return (
        RuntimeContext(
            config=SimpleNamespace(), client=client, state=RuntimeState()
        ),
        client,
    )


def parser():
    value = argparse.ArgumentParser()
    subparsers = value.add_subparsers(dest="command", required=True)
    datastore_items.register(subparsers)
    return value


class DatastoreItemsTests(unittest.TestCase):
    def test_parser_is_read_only_and_filters_are_mutually_exclusive(self):
        args = parser().parse_args(
            ["list-datastore-items", "store-1", "--filter", "domain:Grooming"]
        )
        self.assertEqual(READ, args._policy)
        with self.assertRaises(SystemExit):
            parser().parse_args(
                [
                    "list-datastore-items",
                    "store-1",
                    "--filter",
                    "domain:Grooming",
                    "--item-key",
                    "one",
                ]
            )

    def test_single_page_projects_fields_and_exposes_next_offset(self):
        args = parser().parse_args(
            [
                "list-datastore-items",
                "store-1",
                "--page-size",
                "2",
                "--field",
                "id",
                "--field",
                "requirement",
            ]
        )
        ctx, client = context(
            response(
                [
                    {"id": "1", "requirement": "需求一", "email": "one@example.com"},
                    {"id": "2", "requirement": "需求二", "email": "two@example.com"},
                ],
                has_more=True,
                total=3,
            )
        )

        result = datastore_items.run(args, ctx)

        self.assertEqual(
            {"id": "1", "requirement": "需求一"},
            result.result["items"][0]["value"],
        )
        self.assertNotIn("email", result.result["items"][0]["value"])
        self.assertEqual("partial", result.meta["pagination"]["completion"])
        self.assertEqual({"offset": 2}, result.meta["pagination"]["next"])
        self.assertEqual(2, client.calls[0]["params"]["page[limit]"])

    def test_all_pages_stops_when_complete(self):
        args = parser().parse_args(
            [
                "list-datastore-items",
                "store-1",
                "--all-pages",
                "--sort",
                "id",
                "--page-size",
                "2",
                "--field",
                "requirement",
            ]
        )
        first = response(
            [{"requirement": "一"}, {"requirement": "二"}],
            has_more=True,
            total=3,
        )
        second = response([{"requirement": "三"}], has_more=False, total=3)
        second["data"][0]["id"] = "item-2"
        ctx, client = context(first, second)

        result = datastore_items.run(args, ctx)

        self.assertEqual(3, result.result["returned"])
        self.assertEqual("complete", result.meta["pagination"]["completion"])
        self.assertEqual(2, client.calls[1]["params"]["page[offset]"])
        self.assertEqual("id", client.calls[1]["params"]["sort"])
        self.assertEqual(
            {"mode": "stable-sort", "field": "id", "passes": 1, "matched": True},
            result.verification,
        )

    def test_all_pages_marks_max_items_truncation(self):
        args = parser().parse_args(
            [
                "list-datastore-items",
                "store-1",
                "--all-pages",
                "--sort",
                "id",
                "--page-size",
                "2",
                "--max-items",
                "2",
            ]
        )
        ctx, _client = context(
            response([{"id": "1"}, {"id": "2"}], has_more=True, total=3)
        )

        result = datastore_items.run(args, ctx)

        self.assertEqual("truncated", result.meta["pagination"]["completion"])
        self.assertEqual(["datastore_items_truncated"], result.warnings)
        self.assertIsNone(result.verification)

    def test_unknown_field_and_invalid_response_fail_closed(self):
        args = parser().parse_args(
            ["list-datastore-items", "store-1", "--field", "missing"]
        )
        ctx, _client = context(response([], fields=[{"name": "id", "type": "STRING"}]))
        with self.assertRaisesRegex(ApiError, "requested fields"):
            datastore_items.run(args, ctx)

        ctx, _client = context({"data": [], "meta": {}})
        args = parser().parse_args(["list-datastore-items", "store-1"])
        with self.assertRaisesRegex(ApiError, "metadata"):
            datastore_items.run(args, ctx)

    def test_total_change_during_pagination_fails(self):
        args = parser().parse_args(
            [
                "list-datastore-items",
                "store-1",
                "--all-pages",
                "--sort",
                "id",
                "--page-size",
                "1",
            ]
        )
        ctx, _client = context(
            response([{"id": "1"}], has_more=True, total=2),
            response([{"id": "2"}], has_more=False, total=3),
        )
        with self.assertRaisesRegex(ApiError, "count changed"):
            datastore_items.run(args, ctx)

    def test_duplicate_ids_during_pagination_fail(self):
        args = parser().parse_args(
            [
                "list-datastore-items",
                "store-1",
                "--all-pages",
                "--sort",
                "id",
                "--page-size",
                "1",
            ]
        )
        first = response([{"id": "1"}], has_more=True, total=2)
        second = response([{"id": "2"}], has_more=False, total=2)
        second["data"][0]["id"] = first["data"][0]["id"]
        ctx, _client = context(first, second)

        with self.assertRaisesRegex(ApiError, "duplicate item ids"):
            datastore_items.run(args, ctx)

    def test_all_pages_requires_sort_or_consistency_passes(self):
        args = parser().parse_args(
            ["list-datastore-items", "store-1", "--all-pages"]
        )
        ctx, _client = context()

        with self.assertRaisesRegex(UsageError, "一致性扫描"):
            datastore_items.run(args, ctx)

    def test_consistency_passes_require_unsorted_all_pages(self):
        args = parser().parse_args(
            ["list-datastore-items", "store-1", "--consistency-passes", "2"]
        )
        with self.assertRaisesRegex(UsageError, "只能与 --all-pages"):
            datastore_items.run(args, context()[0])

        args = parser().parse_args(
            [
                "list-datastore-items",
                "store-1",
                "--all-pages",
                "--sort",
                "id",
                "--consistency-passes",
                "2",
            ]
        )
        with self.assertRaisesRegex(UsageError, "不能同时使用"):
            datastore_items.run(args, context()[0])

    def test_all_pages_without_sort_requires_identical_consistency_passes(self):
        args = parser().parse_args(
            [
                "list-datastore-items",
                "store-1",
                "--all-pages",
                "--consistency-passes",
                "2",
                "--page-size",
                "2",
            ]
        )
        first_page = response([{"id": "1"}, {"id": "2"}], has_more=True, total=3)
        second_page = response([{"id": "3"}], total=3)
        second_page["data"][0]["id"] = "item-2"
        ctx, client = context(first_page, second_page, first_page, second_page)

        result = datastore_items.run(args, ctx)

        self.assertEqual(4, len(client.calls))
        self.assertEqual("complete", result.meta["pagination"]["completion"])
        self.assertEqual(
            {"mode": "converged-read", "passes": 2, "matched": True},
            result.verification,
        )
        self.assertNotIn("sort", client.calls[0]["params"])

    def test_consistency_pass_rejects_changed_item_set_or_content(self):
        args = parser().parse_args(
            [
                "list-datastore-items",
                "store-1",
                "--all-pages",
                "--consistency-passes",
                "2",
            ]
        )
        first = response([{"id": "1", "requirement": "旧值"}])
        changed = response([{"id": "1", "requirement": "新值"}])
        ctx, _client = context(first, changed)

        with self.assertRaisesRegex(ApiError, "did not converge"):
            datastore_items.run(args, ctx)

    def test_terminal_page_must_match_total_filtered_count(self):
        args = parser().parse_args(
            [
                "list-datastore-items",
                "store-1",
                "--all-pages",
                "--sort",
                "id",
            ]
        )
        ctx, _client = context(
            response([{"id": "1"}], has_more=False, total=2)
        )

        with self.assertRaisesRegex(ApiError, "totalFilteredCount"):
            datastore_items.run(args, ctx)


if __name__ == "__main__":
    unittest.main()
