from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from dd.commands import aggregate_logs, get_dependencies, list_services, search_logs, search_spans
from dd.errors import ApiError


def ns(**kwargs):
    return argparse.Namespace(**kwargs)


class PayloadTests(unittest.TestCase):
    def test_search_logs_payload_supports_flex_and_cursor(self) -> None:
        payload = search_logs.build_payload(
            ns(query="service:test", from_time="1h", to_time="now", limit=5, sort="-timestamp", storage="flex", cursor="abc")
        )
        self.assertEqual(payload["filter"]["from"], "now-1h")
        self.assertEqual(payload["filter"]["storage_tier"], "flex")
        self.assertEqual(payload["page"], {"limit": 5, "cursor": "abc"})

    def test_aggregate_logs_parses_percentile_compute(self) -> None:
        payload = aggregate_logs.build_payload(
            ns(
                query="status:error",
                from_time="15m",
                to_time="now",
                compute=["count", "percentile(@duration, 95)"],
                group_by=["service"],
                limit=10,
                storage="online",
                sort="count",
            )
        )
        self.assertEqual(payload["filter"]["storage_tier"], "indexes")
        self.assertEqual(payload["compute"][1], {"aggregation": "pc95", "metric": "@duration"})
        self.assertEqual(payload["group_by"][0]["facet"], "service")

    def test_aggregate_logs_rejects_fieldless_avg(self) -> None:
        with self.assertRaises(ApiError):
            aggregate_logs.parse_compute("avg")

    def test_search_spans_payload_injects_default_env(self) -> None:
        payload = search_spans.build_payload(
            ns(query="service:test", from_time="30m", to_time="now", limit=3, sort="-timestamp", cursor=None),
            "ns-production",
        )
        attrs = payload["data"]["attributes"]
        self.assertEqual(attrs["filter"]["query"], "service:test env:ns-production")
        self.assertEqual(attrs["page"], {"limit": 3})

    def test_apm_params_convert_time_to_unix_seconds(self) -> None:
        args = ns(from_time="1700000000", to_time="1700000600", env=None)
        self.assertEqual(list_services.build_params(args, "prod"), {"start": 1700000000, "end": 1700000600, "filter[env]": "prod"})
        self.assertEqual(get_dependencies.build_params(args, "prod"), {"start": 1700000000, "end": 1700000600, "env": "prod"})


if __name__ == "__main__":
    unittest.main()
