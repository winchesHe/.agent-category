from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from dd_v3.commands import scan_slow_sql
from dd_v3.config import Config
from dd_v3.errors import ApiError, AuthError, DatadogTimeoutError


def _config() -> Config:
    return Config(
        api_key="test-key",
        app_key="test-app-key",
        api_base_url="https://api.us5.datadoghq.com",
        ui_base_url="https://us5.datadoghq.com",
        default_env="ns-production",
        timeout=30,
        max_retries=0,
    )


def _args(**overrides):
    values = {
        "from_time": "1700000000000",
        "to_time": "1700604800000",
        "database_type": "mysql",
        "scope": "database_instance:prod*",
        "min_avg_seconds": 5.0,
        "min_count": 100.0,
        "top": 400,
        "fmt": "json",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _scalar(columns):
    return {
        "data": {
            "type": "scalar_response",
            "attributes": {
                "columns": [
                    {"name": name, "type": kind, "values": values}
                    for name, kind, values in columns
                ]
            },
        }
    }


class QueueClient:
    def __init__(self, scalar_responses, sample_response=None):
        self.scalar_responses = list(scalar_responses)
        self.sample_response = sample_response or {"result": {"events": []}}
        self.posts = []
        self.ui_posts = []

    def request_read(
        self,
        method,
        path,
        *,
        params=None,
        json_body=None,
        surface="api",
    ):
        if method != "POST":
            raise AssertionError(f"unexpected method: {method}")
        if surface == "ui":
            self.ui_posts.append((path, json_body, params))
            if isinstance(self.sample_response, Exception):
                raise self.sample_response
            return self.sample_response
        self.posts.append((path, json_body))
        if not self.scalar_responses:
            raise AssertionError("unexpected scalar request")
        response = self.scalar_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

class SlowSqlTests(unittest.TestCase):
    def test_scalar_columns_reject_malformed_success_payloads(self):
        invalid_bodies = (
            {"data": {"attributes": {"columns": [123]}}},
            {
                "data": {
                    "attributes": {
                        "columns": [{"name": "query_signature", "values": None}]
                    }
                }
            },
            {
                "data": {
                    "attributes": {
                        "columns": [
                            {"name": "query_signature", "values": [["a"]]},
                            {"name": "query_signature", "values": [["b"]]},
                        ]
                    }
                }
            },
        )
        for body in invalid_bodies:
            with self.subTest(body=body), self.assertRaises(ApiError):
                scan_slow_sql._scalar_columns(body)

    def test_sample_response_distinguishes_empty_from_malformed(self):
        self.assertIsNone(scan_slow_sql._extract_sample({"result": {"events": []}}))
        for body in ({}, {"result": {}}, {"result": {"events": [123]}}):
            with self.subTest(body=body), self.assertRaises(ApiError):
                scan_slow_sql._extract_sample(body)

    @mock.patch("dd_v3.commands.scan_slow_sql.now_millis", return_value=1_700_604_800_000)
    def test_relative_from_uses_latest_seven_days(self, _mock_now):
        args = _args(from_time="7d", to_time=None)

        from_ms, to_ms = scan_slow_sql._validate_args(args)

        self.assertEqual(to_ms, 1_700_604_800_000)
        self.assertEqual(from_ms, 1_700_000_000_000)

    @mock.patch("dd_v3.commands.scan_slow_sql.now_millis", return_value=1_700_604_800_000)
    def test_double_relative_times_share_execution_reference(self, _mock_now):
        for from_time, to_time in (("now-7d", "now-1d"), ("7d", "1d")):
            with self.subTest(from_time=from_time, to_time=to_time):
                args = _args(from_time=from_time, to_time=to_time)

                from_ms, to_ms = scan_slow_sql._validate_args(args)

                self.assertEqual(from_ms, 1_700_000_000_000)
                self.assertEqual(to_ms, 1_700_518_400_000)

    def test_missing_from_is_rejected(self):
        args = _args(from_time=None, to_time=None)

        with self.assertRaisesRegex(ApiError, "--from"):
            scan_slow_sql._validate_args(args)

    def test_scan_uses_four_requests_and_returns_compact_query(self):
        signature = "aaaaaaaaaaaaaaaa"
        top_formula = "total_time_ns / executions / 1000000000"
        candidate = _scalar([
            ("query_signature", "group", [[signature], ["bbbbbbbbbbbbbbbb"]]),
            (top_formula, "number", [6.0, 4.0]),
        ])
        exact = _scalar([
            ("query_signature", "group", [[signature]]),
            ("total_time_ns", "number", [606_000_000_000.0]),
            ("executions", "number", [101.0]),
            ("total_time_ns / executions / 1000000000", "number", [6.0]),
        ])
        context = _scalar([
            ("query_signature", "group", [[signature]]),
            ("database_instance", "group", [["prod-mysql-reader.example.com"]]),
            ("dbclusteridentifier", "group", [["prod-mysql-cluster"]]),
            ("schema", "group", [["orders"]]),
            ("table", "group", [["orders", "order_audit"]]),
            ("executions", "number", [101.0]),
        ])
        sample = {
            "result": {
                "events": [
                    {
                        "event": {
                            "custom": {
                                "database_instance": "prod-mysql-reader.example.com",
                                "db": {
                                    "instance": "orders",
                                    "metadata": {"tables": ["orders", "order_items"]},
                                    "statement": "SELECT * FROM orders JOIN order_items ON ?",
                                },
                            },
                            "tags": ["dbclusteridentifier:prod-mysql-cluster"],
                        }
                    }
                ]
            }
        }
        client = QueueClient([candidate, exact, context], sample)

        result, exit_code = scan_slow_sql.execute(_args(), _config(), client=client)

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["query_count"], 1)
        query = result["queries"][0]
        self.assertEqual(query["count"], 101)
        self.assertEqual(query["normalized_sql"], "SELECT * FROM orders JOIN order_items ON ?")
        self.assertEqual(query["tables"], ["order_audit", "order_items", "orders"])
        self.assertEqual(result["sources"]["mysql"]["logical_request_count"], 4)
        self.assertEqual(len(client.posts), 3)
        self.assertEqual(len(client.ui_posts), 1)
        sample_payload = client.ui_posts[0][1]["list"]
        self.assertEqual(client.ui_posts[0][0], "/api/v1/logs-analytics/list")
        self.assertEqual(client.ui_posts[0][2], {"type": "databasequery"})
        self.assertEqual(sample_payload["indexes"], ["databasequery"])
        self.assertEqual(sample_payload["limit"], 1)
        self.assertIn("@db.query_signature:aaaaaaaaaaaaaaaa", sample_payload["search"]["query"])
        candidate_formula = client.posts[0][1]["data"]["attributes"]["formulas"][0]
        self.assertEqual(candidate_formula["limit"], {"count": 400, "order": "desc"})

    def test_thresholds_are_strict(self):
        signature = "aaaaaaaaaaaaaaaa"
        top_formula = "total_time_ns / executions / 1000000000"
        candidate = _scalar([
            ("query_signature", "group", [[signature]]),
            (top_formula, "number", [6.0]),
        ])
        exact = _scalar([
            ("query_signature", "group", [[signature]]),
            ("total_time_ns", "number", [600_000_000_000.0]),
            ("executions", "number", [100.0]),
            ("total_time_ns / executions / 1000000000", "number", [6.0]),
        ])
        client = QueueClient([candidate, exact])

        result, exit_code = scan_slow_sql.execute(_args(), _config(), client=client)

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["query_count"], 0)
        self.assertEqual(result["sources"]["mysql"]["logical_request_count"], 2)
        self.assertEqual(client.ui_posts, [])

    def test_sample_auth_failure_stops_follow_up_sample_requests(self):
        signatures = ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"]
        formula = "total_time_ns / executions / 1000000000"
        candidate = _scalar([
            ("query_signature", "group", [[signatures[0]], [signatures[1]]]),
            (formula, "number", [7.0, 6.0]),
        ])
        exact = _scalar([
            ("query_signature", "group", [[signatures[0]], [signatures[1]]]),
            ("total_time_ns", "number", [707_000_000_000.0, 606_000_000_000.0]),
            ("executions", "number", [101.0, 101.0]),
            (formula, "number", [7.0, 6.0]),
        ])
        context = _scalar([
            ("query_signature", "group", [[signatures[0]], [signatures[1]]]),
            ("database_instance", "group", [["prod-a"], ["prod-b"]]),
            ("dbclusteridentifier", "group", [["prod-cluster"], ["prod-cluster"]]),
            ("schema", "group", [["db_a"], ["db_b"]]),
            ("table", "group", [["table_a"], ["table_b"]]),
            ("executions", "number", [101.0, 101.0]),
        ])
        client = QueueClient([candidate, exact, context], AuthError("forbidden"))

        result, exit_code = scan_slow_sql.execute(_args(), _config(), client=client)

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["query_count"], 2)
        self.assertEqual(len(client.ui_posts), 1)
        self.assertEqual(result["sources"]["mysql"]["sample_errors"], 1)
        self.assertEqual(result["sources"]["mysql"]["sample_skipped"], 1)
        self.assertEqual([query["sample_status"] for query in result["queries"]], ["error", "error"])

    def test_missing_exact_candidate_fails_closed(self):
        signature = "aaaaaaaaaaaaaaaa"
        top_formula = "total_time_ns / executions / 1000000000"
        candidate = _scalar([
            ("query_signature", "group", [[signature]]),
            (top_formula, "number", [6.0]),
        ])
        exact = _scalar([
            ("query_signature", "group", []),
            ("total_time_ns", "number", []),
            ("executions", "number", []),
            (top_formula, "number", []),
        ])
        client = QueueClient([candidate, exact])

        result, exit_code = scan_slow_sql.execute(_args(), _config(), client=client)

        self.assertEqual(exit_code, 4)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["sources"]["mysql"]["error"], "api_error")

    def test_incomplete_top_boundary_fails_closed(self):
        formula = "total_time_ns / executions / 1000000000"
        client = QueueClient([
            _scalar([
                ("query_signature", "group", [["aaaaaaaaaaaaaaaa"]]),
                (formula, "number", [6.0]),
            ])
        ])

        result, exit_code = scan_slow_sql.execute(_args(top=1), _config(), client=client)

        self.assertEqual(exit_code, 4)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["sources"]["mysql"]["error"], "api_error")

    def test_all_keeps_mysql_when_postgresql_fails(self):
        mysql_formula = "total_time_ns / executions / 1000000000"
        client = QueueClient([
            _scalar([
                ("query_signature", "group", [["aaaaaaaaaaaaaaaa"]]),
                (mysql_formula, "number", [4.0]),
            ]),
            ApiError("postgres unavailable"),
        ])

        result, exit_code = scan_slow_sql.execute(
            _args(database_type="all"), _config(), client=client
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["sources"]["mysql"]["status"], "success")
        self.assertEqual(result["sources"]["postgresql"]["status"], "failed")

    def test_single_database_preserves_auth_exit_code(self):
        client = QueueClient([AuthError("forbidden")])

        result, exit_code = scan_slow_sql.execute(_args(), _config(), client=client)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(exit_code, 3)

    def test_single_database_preserves_timeout_exit_code(self):
        client = QueueClient([DatadogTimeoutError("timed out")])

        result, exit_code = scan_slow_sql.execute(_args(), _config(), client=client)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(exit_code, 5)


if __name__ == "__main__":
    unittest.main()
