from __future__ import annotations

import argparse
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS_DIR))

from dd_v3.errors import ApiError
from dd_v3.log_analysis import (
    aggregate_facet_counts,
    aggregate_total,
    data_items,
    extract_pattern,
    normalize_log,
    ranked_messages,
    response_coverage,
)
from dd_v3.runtime import READ, Runtime, RuntimeContext, RuntimeState
from dd_v3.commands import (
    compare_logs,
    dashboard_lists,
    dashboards,
    error_summary,
    get_dashboard,
    log_context,
    log_patterns,
    log_services,
    trace_logs,
)

NOW_MS = 1_755_388_800_000  # 2025-08-17T08:00:00.000Z


def fixture(name: str):
    with (FIXTURES_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


def ns(**values):
    return argparse.Namespace(**values)


class RecordingClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request_read(
        self,
        method,
        path,
        *,
        params=None,
        json_body=None,
        surface="api",
    ):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json_body": json_body,
                "surface": surface,
            }
        )
        return self.responses.pop(0)


def context(*responses):
    client = RecordingClient(responses)
    runtime_context = RuntimeContext(
        config=SimpleNamespace(default_env="ns-production"),
        client=client,
        state=RuntimeState(),
    )
    return runtime_context, client


def parser_for(module):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    module.register(subparsers)
    return parser


class ParserContractTests(unittest.TestCase):
    def test_all_commands_register_read_policy(self) -> None:
        modules_and_commands = [
            (trace_logs, ["search-trace-logs", "trace-1", "--from", "1h"]),
            (log_context, ["get-log-context", "--timestamp", "now", "--query", "*"]),
            (error_summary, ["summarize-errors", "--from", "1h"]),
            (compare_logs, ["compare-log-counts", "--query", "status:error"]),
            (log_patterns, ["group-log-patterns", "--query", "*", "--from", "1h"]),
            (log_services, ["list-log-services", "--from", "1h"]),
            (dashboards, ["list-dashboards"]),
            (dashboard_lists, ["list-dashboard-lists"]),
            (dashboard_lists, ["get-dashboard-list", "1"]),
            (dashboard_lists, ["list-dashboard-list-items", "1"]),
        ]
        for module, argv in modules_and_commands:
            with self.subTest(command=argv[0]):
                args = parser_for(module).parse_args(argv)
                self.assertEqual(args._policy, READ)
                self.assertTrue(callable(args._handler))

    def test_integer_bounds_fail_at_parse_time(self) -> None:
        cases = [
            (trace_logs, ["search-trace-logs", "trace-1", "--from", "1h", "--limit", "1001"]),
            (
                log_context,
                ["get-log-context", "--timestamp", "now", "--query", "*", "--limit", "501"],
            ),
            (error_summary, ["summarize-errors", "--from", "1h", "--sample-limit", "501"]),
            (
                log_patterns,
                ["group-log-patterns", "--query", "*", "--from", "1h", "--top", "101"],
            ),
            (log_services, ["list-log-services", "--from", "1h", "--limit", "501"]),
            (dashboards, ["list-dashboards", "--count", "101"]),
            (dashboard_lists, ["get-dashboard-list", "0"]),
        ]
        for module, argv in cases:
            with self.subTest(command=argv[0]), self.assertRaises(SystemExit):
                parser_for(module).parse_args(argv)

    def test_dashboard_list_accepts_positive_int64_id(self) -> None:
        args = parser_for(dashboard_lists).parse_args(
            ["get-dashboard-list", "2147483648"]
        )
        self.assertEqual(args.list_id, 2_147_483_648)

    def test_all_commands_accept_summary_format(self) -> None:
        modules_and_commands = [
            (trace_logs, ["search-trace-logs", "trace-1", "--from", "1h"]),
            (log_context, ["get-log-context", "--timestamp", "now", "--query", "*"]),
            (error_summary, ["summarize-errors", "--from", "1h"]),
            (compare_logs, ["compare-log-counts", "--query", "status:error"]),
            (log_patterns, ["group-log-patterns", "--query", "*", "--from", "1h"]),
            (log_services, ["list-log-services", "--from", "1h"]),
            (dashboards, ["list-dashboards"]),
            (dashboard_lists, ["list-dashboard-lists"]),
            (dashboard_lists, ["get-dashboard-list", "1"]),
            (dashboard_lists, ["list-dashboard-list-items", "1"]),
        ]
        for module, argv in modules_and_commands:
            with self.subTest(command=argv[0]):
                args = parser_for(module).parse_args([*argv, "--format", "summary"])
                self.assertEqual(args.fmt, "summary")


class LogPrimitiveTests(unittest.TestCase):
    def test_invalid_time_and_duration_fail_closed(self) -> None:
        with self.assertRaises(ApiError):
            trace_logs.build_payload(
                ns(trace_id="trace-1", from_time="yesterday-ish", to_time="now", limit=10, cursor=None),
                now_ms=NOW_MS,
            )
        with self.assertRaises(ApiError):
            log_context.build_payloads(
                ns(timestamp="now", query="*", service=None, before="garbage", after="5m", limit=10),
                now_ms=NOW_MS,
            )
        with self.assertRaises(ApiError):
            compare_logs.build_payloads(
                ns(query="*", period="forever", to_time="now"),
                now_ms=NOW_MS,
            )
        with self.assertRaises(ApiError):
            log_patterns.build_payload(
                ns(query="*", from_time="not-a-time", to_time="now", limit=10),
                now_ms=NOW_MS,
            )

    def test_context_requires_query_or_service(self) -> None:
        with self.assertRaisesRegex(ApiError, "--query 或 --service"):
            log_context.build_payloads(
                ns(timestamp="now", query=None, service=None, before="5m", after="5m", limit=10),
                now_ms=NOW_MS,
            )

    def test_normalized_log_omits_raw_attributes_and_error_stack(self) -> None:
        item = fixture("read_extensions_logs_v2.json")["data"][0]
        log = normalize_log(item)
        self.assertEqual(log["trace_id"], "trace-123")
        self.assertEqual(log["http"]["path"], "/orders/123")
        self.assertNotIn("raw_attributes", log)
        self.assertNotIn("stack", log["error"])

    def test_pattern_removes_dynamic_and_opaque_values(self) -> None:
        first = extract_pattern("Order 123 failed for 10.1.2.3 user first@example.com")
        second = extract_pattern("Order 456 failed for 10.2.3.4 user second@example.com")
        self.assertEqual(first, second)
        self.assertIn("<IP>", first)
        self.assertIn("<EMAIL>", first)
        self.assertEqual(
            extract_pattern("token abcdefghijklmnopqrstuvwxyz123456 was rejected"),
            "token <TOKEN> was rejected",
        )

    def test_invalid_aggregate_count_fails_closed(self) -> None:
        with self.assertRaisesRegex(ApiError, "invalid aggregate"):
            aggregate_total({"data": {"buckets": [{"computes": {"c0": "123"}}]}})
        with self.assertRaisesRegex(ApiError, "invalid aggregate"):
            aggregate_total(
                {
                    "data": {
                        "buckets": [
                            {"computes": {"c0": 1}},
                            {"computes": {"c0": 2}},
                        ]
                    }
                }
            )
        with self.assertRaisesRegex(ApiError, "invalid facet count"):
            aggregate_facet_counts(
                {"data": {"buckets": [{"by": {}, "computes": {"c0": "bad"}}]}},
                facet="service",
                output_key="service",
            )
        with self.assertRaisesRegex(ApiError, "invalid facet value"):
            aggregate_facet_counts(
                {
                    "data": {
                        "buckets": [
                            {"by": {"service": {"bad": 1}}, "computes": {"c0": 1}}
                        ]
                    }
                },
                facet="service",
                output_key="service",
            )
        with self.assertRaisesRegex(ApiError, "invalid aggregate"):
            aggregate_total({"data": {"buckets": [{"computes": {"c0": 1.9}}]}})
        with self.assertRaisesRegex(ApiError, "invalid facet count"):
            aggregate_facet_counts(
                {
                    "data": {
                        "buckets": [
                            {"by": {"service": "svc"}, "computes": {"c0": 2.7}}
                        ]
                    }
                },
                facet="service",
                output_key="service",
            )

    def test_integral_float_aggregate_count_is_normalized(self) -> None:
        self.assertEqual(
            aggregate_total({"data": {"buckets": [{"computes": {"c0": 3.0}}]}}),
            3,
        )
        self.assertEqual(
            aggregate_facet_counts(
                {
                    "data": {
                        "buckets": [
                            {"by": {"service": "svc"}, "computes": {"c0": 4.0}}
                        ]
                    }
                },
                facet="service",
                output_key="service",
            ),
            [{"service": "svc", "count": 4}],
        )

    def test_log_data_items_require_attributes_object(self) -> None:
        for body in (
            {"data": [{}]},
            {"data": [{"attributes": []}]},
            {"data": [{"attributes": {"attributes": []}}]},
            {"data": [{"attributes": {"message": {"secret": "x"}}}]},
            {"data": [{"attributes": {"service": ["svc"]}}]},
            {"data": [{"attributes": {"tags": {"bad": 1}}}]},
        ):
            with self.subTest(body=body), self.assertRaisesRegex(ApiError, "invalid"):
                data_items(body)

    def test_response_coverage_marks_timeout_and_warnings_partial(self) -> None:
        coverage, warnings = response_coverage(
            {
                "meta": {
                    "status": "timeout",
                    "warnings": [{"code": "partial_result"}],
                }
            }
        )
        self.assertTrue(coverage["partial"])
        self.assertEqual(coverage["completion"], "unknown")
        self.assertEqual(coverage["warning_count"], 1)
        self.assertEqual(
            warnings,
            ["datadog_response_timeout", "datadog_response_warnings"],
        )

    def test_response_coverage_rejects_malformed_metadata(self) -> None:
        invalid_bodies = (
            {"meta": []},
            {"meta": {"status": "unexpected"}},
            {"meta": {"warnings": {"code": "not-a-list"}}},
            {"meta": {"warnings": ["not-an-object"]}},
        )
        for body in invalid_bodies:
            with self.subTest(body=body), self.assertRaises(ApiError):
                response_coverage(body)

    def test_ranked_messages_do_not_merge_truncated_prefix_collisions(self) -> None:
        prefix = "x" * 110
        body = {
            "data": [
                {"attributes": {"message": f"{prefix}-first"}},
                {"attributes": {"message": f"{prefix}-second"}},
            ]
        }
        ranked = ranked_messages(body)
        self.assertEqual([item["sample_count"] for item in ranked], [1, 1])
        self.assertNotEqual(ranked[0]["message"], ranked[1]["message"])


class LogCommandContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logs = fixture("read_extensions_logs_v2.json")
        self.aggregates = fixture("read_extensions_aggregates_v2.json")

    def test_search_trace_logs_uses_cursor_search_contract(self) -> None:
        args = ns(
            trace_id="trace-123",
            from_time="1h",
            to_time="now",
            limit=100,
            cursor="cursor-before",
        )
        ctx, client = context(self.logs)
        with patch.object(trace_logs, "now_millis", return_value=NOW_MS):
            result = trace_logs.run(args, ctx)
        self.assertEqual(client.calls[0]["method"], "POST")
        self.assertEqual(client.calls[0]["path"], "/api/v2/logs/events/search")
        payload = client.calls[0]["json_body"]
        self.assertEqual(
            payload["filter"]["query"],
            "trace_id:trace-123 OR @trace_id:trace-123 OR @dd.trace_id:trace-123",
        )
        self.assertEqual(payload["page"], {"limit": 100, "cursor": "cursor-before"})
        self.assertEqual(result.result["returned"], 3)
        self.assertEqual(result.meta["pagination"]["next"], {"cursor": "cursor-after-1"})

    def test_get_log_context_uses_two_bounded_searches(self) -> None:
        args = ns(
            timestamp="2025-08-17T08:00:00Z",
            query="status:error",
            service="moego-api",
            before="5m",
            after="2m",
            limit=20,
        )
        before = {"data": self.logs["data"][:2]}
        after = {"data": self.logs["data"][2:]}
        ctx, client = context(before, after)
        with patch.object(log_context, "now_millis", return_value=NOW_MS):
            result = log_context.run(args, ctx)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(all(call["method"] == "POST" for call in client.calls))
        self.assertTrue(all(call["path"] == "/api/v2/logs/events/search" for call in client.calls))
        self.assertEqual(client.calls[0]["json_body"]["sort"], "-timestamp")
        self.assertEqual(client.calls[1]["json_body"]["sort"], "timestamp")
        self.assertEqual(client.calls[0]["json_body"]["filter"]["query"], "(status:error) service:moego-api")
        self.assertEqual([log["id"] for log in result.result["before"]], ["log-2", "log-1"])

    def test_summarize_errors_keeps_sample_counts_distinct_from_total(self) -> None:
        args = ns(
            from_time="1h",
            to_time="now",
            query="status:error",
            service="moego-api",
            sample_limit=200,
        )
        ctx, client = context(
            self.aggregates["by_service"],
            self.aggregates["by_error_kind"],
            self.aggregates["total"],
            self.logs,
        )
        with patch.object(error_summary, "now_millis", return_value=NOW_MS):
            result = error_summary.run(args, ctx)
        self.assertEqual(len(client.calls), 4)
        self.assertEqual([call["path"] for call in client.calls[:3]], [
            "/api/v2/logs/analytics/aggregate",
            "/api/v2/logs/analytics/aggregate",
            "/api/v2/logs/analytics/aggregate",
        ])
        self.assertEqual(client.calls[3]["path"], "/api/v2/logs/events/search")
        self.assertEqual(client.calls[0]["json_body"]["filter"]["query"], "(status:error) service:moego-api")
        self.assertEqual(result.result["total"], 123)
        self.assertEqual(result.result["message_sample"]["sample_size"], 3)
        self.assertIn("sample_count", result.result["top_messages"][0])
        self.assertNotIn("count", result.result["top_messages"][0])

    def test_summarize_errors_marks_facet_limit_as_unknown(self) -> None:
        args = ns(
            from_time="1h",
            to_time="now",
            query="status:error",
            service=None,
            sample_limit=20,
        )
        by_service = {
            "data": {
                "buckets": [
                    {"by": {"service": f"service-{index}"}, "computes": {"c0": 1}}
                    for index in range(20)
                ]
            }
        }
        empty_aggregate = {"data": {"buckets": []}}
        empty_logs = {"data": []}
        ctx, _client = context(
            by_service,
            empty_aggregate,
            empty_aggregate,
            empty_logs,
        )
        with patch.object(error_summary, "now_millis", return_value=NOW_MS):
            result = error_summary.run(args, ctx)
        self.assertEqual(
            result.meta["facet_coverage"]["by_service"]["completion"],
            "unknown",
        )
        self.assertIn("by_service_facet_may_be_truncated", result.warnings)

    def test_summarize_errors_uses_raw_bucket_count_for_facet_coverage(self) -> None:
        args = ns(
            from_time="1h",
            to_time="now",
            query="status:error",
            service=None,
            sample_limit=20,
        )
        by_service = {
            "data": {
                "buckets": [
                    {
                        "by": {"service": f"service-{index}"},
                        "computes": {"c0": 1},
                    }
                    for index in range(19)
                ]
                + [{"by": {}, "computes": {"c0": 1}}]
            }
        }
        empty_aggregate = {"data": {"buckets": []}}
        ctx, _client = context(
            by_service,
            empty_aggregate,
            empty_aggregate,
            {"data": []},
        )
        with patch.object(error_summary, "now_millis", return_value=NOW_MS):
            result = error_summary.run(args, ctx)
        self.assertEqual(len(result.result["by_service"]), 19)
        self.assertEqual(
            result.meta["facet_coverage"]["by_service"]["returned"],
            20,
        )
        self.assertEqual(
            result.meta["facet_coverage"]["by_service"]["completion"],
            "unknown",
        )

    def test_compare_previous_zero_is_unknown_percentage(self) -> None:
        args = ns(query="status:error", period="1h", to_time="now")
        ctx, client = context(self.aggregates["total"], self.aggregates["zero"])
        with patch.object(compare_logs, "now_millis", return_value=NOW_MS):
            result = compare_logs.run(args, ctx)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(all(call["path"] == "/api/v2/logs/analytics/aggregate" for call in client.calls))
        self.assertEqual(client.calls[0]["json_body"]["filter"]["query"], "status:error")
        self.assertEqual(result.result["change"]["absolute"], 123)
        self.assertIsNone(result.result["change"]["percentage_change"])
        self.assertTrue(result.result["change"]["baseline_zero"])

    def test_group_patterns_marks_sample_coverage_and_omits_samples(self) -> None:
        args = ns(query="status:error", from_time="1h", to_time="now", limit=500, top=50)
        ctx, client = context(self.logs)
        with patch.object(log_patterns, "now_millis", return_value=NOW_MS):
            result = log_patterns.run(args, ctx)
        self.assertEqual(client.calls[0]["method"], "POST")
        self.assertEqual(client.calls[0]["path"], "/api/v2/logs/events/search")
        self.assertEqual(result.result["coverage"], "sampled")
        self.assertEqual(result.result["sample_size"], 3)
        self.assertEqual(result.result["patterns"][0]["count"], 2)
        self.assertTrue(all("sample" not in pattern for pattern in result.result["patterns"]))

    def test_list_log_services_uses_bounded_service_aggregation(self) -> None:
        args = ns(from_time="1h", to_time="now", query="*", limit=2)
        ctx, client = context(self.aggregates["by_service"])
        with patch.object(log_services, "now_millis", return_value=NOW_MS):
            result = log_services.run(args, ctx)
        call = client.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/api/v2/logs/analytics/aggregate")
        self.assertEqual(call["json_body"]["filter"]["query"], "*")
        self.assertEqual(call["json_body"]["group_by"][0]["facet"], "service")
        self.assertEqual(call["json_body"]["group_by"][0]["limit"], 2)
        self.assertEqual(result.result["services"][0], {"name": "moego-api", "log_count": 100})
        self.assertEqual(result.meta["pagination"]["completion"], "unknown")

    def test_list_log_services_uses_raw_bucket_count_for_completion(self) -> None:
        args = ns(from_time="1h", to_time="now", query="*", limit=2)
        body = {
            "data": {
                "buckets": [
                    {"by": {"service": "moego-api"}, "computes": {"c0": 10}},
                    {"by": {}, "computes": {"c0": 5}},
                ]
            }
        }
        ctx, _client = context(body)
        with patch.object(log_services, "now_millis", return_value=NOW_MS):
            result = log_services.run(args, ctx)
        self.assertEqual(result.result["returned"], 1)
        self.assertEqual(result.meta["pagination"]["completion"], "unknown")


class DashboardCommandContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dashboards = fixture("read_extensions_dashboards_v1.json")
        self.dashboard_lists = fixture("read_extensions_dashboard_lists.json")

    def test_list_dashboards_uses_official_query_parameter_names(self) -> None:
        args = ns(count=2, start=20, shared=True, deleted=False)
        ctx, client = context(self.dashboards)
        result = dashboards.run(args, ctx)
        self.assertEqual(client.calls[0], {
            "method": "GET",
            "path": "/api/v1/dashboard",
            "params": {"count": 2, "start": 20, "filter[shared]": True},
            "json_body": None,
            "surface": "api",
        })
        self.assertEqual(result.result["returned"], 2)
        self.assertEqual(result.meta["pagination"]["next"], {"start": 22})
        self.assertEqual(result.meta["pagination"]["completion"], "unknown")

    def test_get_dashboard_runtime_accepts_official_scatterplot_object_requests(self) -> None:
        dashboard = {
            "id": "scatter-plot",
            "title": "Service correlation",
            "layout_type": "ordered",
            "widgets": [
                {
                    "definition": {
                        "type": "scatterplot",
                        "title": "CPU and load",
                        "requests": {
                            "table": {
                                "formulas": [
                                    {"formula": "query1", "dimension": "x"},
                                    {"formula": "query2", "dimension": "y"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:system.cpu.user{*} by {service}",
                                        "aggregator": "avg",
                                    },
                                    {
                                        "data_source": "logs",
                                        "name": "query2",
                                        "indexes": ["*"],
                                        "compute": {"aggregation": "count"},
                                        "search": {"query": "service:moego-api"},
                                    },
                                ],
                                "response_format": "timeseries",
                            }
                        },
                    }
                }
            ],
        }
        client = RecordingClient([dashboard])
        stdout = io.StringIO()
        runtime = Runtime(
            modules=[get_dashboard],
            config_loader=lambda: SimpleNamespace(default_env="ns-production"),
            client_factory=lambda config, state: client,
            stdout=stdout,
            stderr=io.StringIO(),
        )

        exit_code = runtime.run(["get-dashboard", "scatter-plot"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["target"], {"dashboard_id": "scatter-plot"})
        self.assertEqual(
            payload["result"]["widgets"][0],
            {
                "title": "CPU and load",
                "type": "scatterplot",
                "queries": [
                    {
                        "data_source": "metrics",
                        "name": "query1",
                        "query": "avg:system.cpu.user{*} by {service}",
                        "aggregator": "avg",
                    },
                    {
                        "data_source": "logs",
                        "name": "query2",
                        "indexes": ["*"],
                        "compute": {"aggregation": "count"},
                        "search": {"query": "service:moego-api"},
                    },
                ],
            },
        )

    def test_get_dashboard_runtime_preserves_scatterplot_axis_requests(self) -> None:
        client = RecordingClient(
            [
                {
                    "id": "scatter-plot",
                    "title": "Service correlation",
                    "layout_type": "ordered",
                    "widgets": [
                        {
                            "definition": {
                                "type": "scatterplot",
                                "title": "CPU and load",
                                "requests": {
                                    "x": {
                                        "q": "avg:system.cpu.user{*}",
                                        "aggregator": "avg",
                                    },
                                    "y": {"q": "avg:system.load.1{*}"},
                                },
                            }
                        },
                        {
                            "definition": {
                                "type": "scatterplot",
                                "title": "Combined requests",
                                "requests": {
                                    "table": {
                                        "queries": [
                                            {
                                                "data_source": "logs",
                                                "name": "table_query",
                                                "compute": {"aggregation": "count"},
                                            }
                                        ],
                                        "response_format": "event_list",
                                    },
                                    "x": {"q": "avg:system.cpu.user{*}"},
                                    "y": {
                                        "log_query": {
                                            "index": "*",
                                            "compute": {"aggregation": "count"},
                                            "search": {"query": "service:moego-api"},
                                        }
                                    },
                                },
                            }
                        },
                    ],
                }
            ]
        )
        stdout = io.StringIO()
        runtime = Runtime(
            modules=[get_dashboard],
            config_loader=lambda: SimpleNamespace(default_env="ns-production"),
            client_factory=lambda config, state: client,
            stdout=stdout,
            stderr=io.StringIO(),
        )

        exit_code = runtime.run(["get-dashboard", "scatter-plot"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["target"], {"dashboard_id": "scatter-plot"})
        self.assertEqual(
            payload["result"]["widgets"],
            [
                {
                    "title": "CPU and load",
                    "type": "scatterplot",
                    "queries": [
                        {
                            "axis": "x",
                            "data_source": "metrics",
                            "query": "avg:system.cpu.user{*}",
                            "aggregator": "avg",
                        },
                        {
                            "axis": "y",
                            "data_source": "metrics",
                            "query": "avg:system.load.1{*}",
                        },
                    ],
                },
                {
                    "title": "Combined requests",
                    "type": "scatterplot",
                    "queries": [
                        {
                            "data_source": "logs",
                            "name": "table_query",
                            "compute": {"aggregation": "count"},
                        },
                        {
                            "axis": "x",
                            "data_source": "metrics",
                            "query": "avg:system.cpu.user{*}",
                        },
                        {
                            "axis": "y",
                            "query_type": "log_query",
                            "index": "*",
                            "compute": {"aggregation": "count"},
                            "search": {"query": "service:moego-api"},
                        },
                    ],
                },
            ],
        )

    def test_get_dashboard_runtime_rejects_unknown_or_malformed_scatterplot_requests(self) -> None:
        invalid_requests = (
            {"z": {"q": "avg:system.cpu.user{*}"}},
            {"x": []},
            {"x": {"q": []}},
            {"x": {"q": "   "}},
            {"x": {"log_query": {}}},
            {"x": {"log_query": []}},
            {"x": {"q": "avg:system.cpu.user{*}", "unknown": True}},
            {"x": {"aggregator": "avg"}},
            {
                "x": {
                    "q": "avg:system.cpu.user{*}",
                    "log_query": {"search": {"query": "service:moego-api"}},
                }
            },
            {"x": {"q": "avg:system.cpu.user{*}", "aggregator": "median"}},
            {"x": {"q": "avg:system.cpu.user{*}", "aggregator": []}},
            {"x": {"q": "avg:system.cpu.user{*}", "aggregator": {}}},
            {"x": {"q": "avg:system.cpu.user{*}", "aggregator": True}},
            {
                "table": {
                    "formulas": [],
                    "queries": {"name": "query1"},
                    "response_format": "scalar",
                }
            },
            {
                "table": {
                    "formulas": {},
                    "queries": [],
                    "response_format": "scalar",
                }
            },
            {
                "table": {
                    "formulas": [],
                    "queries": [],
                    "response_format": "heatmap",
                }
            },
            {"table": {"queries": [], "unknown": {}}},
        )
        for requests in invalid_requests:
            with self.subTest(requests=requests):
                client = RecordingClient(
                    [
                        {
                            "id": "scatter-plot",
                            "title": "Service correlation",
                            "layout_type": "ordered",
                            "widgets": [
                                {
                                    "definition": {
                                        "type": "scatterplot",
                                        "requests": requests,
                                    }
                                }
                            ],
                        }
                    ]
                )
                stdout = io.StringIO()
                runtime = Runtime(
                    modules=[get_dashboard],
                    config_loader=lambda: SimpleNamespace(default_env="ns-production"),
                    client_factory=lambda config, state: client,
                    stdout=stdout,
                    stderr=io.StringIO(),
                )

                exit_code = runtime.run(["get-dashboard", "scatter-plot"])

                payload = json.loads(stdout.getvalue())
                self.assertEqual(exit_code, 4)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["error"]["code"], "invalid_response")
                self.assertEqual(payload["target"], {"dashboard_id": "scatter-plot"})

    def test_list_dashboards_rejects_incompatible_filters(self) -> None:
        with self.assertRaisesRegex(ApiError, "不能同时"):
            dashboards.build_params(ns(count=25, start=0, shared=True, deleted=True))

    def test_dashboard_commands_reject_invalid_success_shapes(self) -> None:
        with self.assertRaisesRegex(ApiError, "invalid dashboard"):
            dashboards.extract_dashboards({"dashboards": {}})
        with self.assertRaisesRegex(ApiError, "invalid dashboard"):
            dashboards.extract_dashboards({"dashboards": [{"title": "Missing ID"}]})
        get_ctx, _client = context({})
        with self.assertRaisesRegex(ApiError, "invalid Dashboard List"):
            dashboard_lists.run_get(ns(list_id=10), get_ctx)
        invalid_list_bodies = (
            {"dashboard_lists": [{"id": 10}]},
            {"dashboard_lists": [{"id": True, "name": "List"}]},
        )
        for body in invalid_list_bodies:
            with self.subTest(body=body), self.assertRaisesRegex(ApiError, "invalid Dashboard List"):
                dashboard_lists._dashboard_lists(body)
        invalid_item_bodies = (
            {"dashboards": [{"type": "custom_timeboard"}]},
            {"dashboards": [{"id": "abc-def"}]},
        )
        for body in invalid_item_bodies:
            with self.subTest(body=body), self.assertRaisesRegex(ApiError, "invalid Dashboard List"):
                dashboard_lists._dashboard_list_items(body)

        mismatch_ctx, _client = context(
            {"id": 11, "name": "Wrong List", "type": "manual_dashboard_list"}
        )
        with self.assertRaisesRegex(ApiError, "ID"):
            dashboard_lists.run_get(ns(list_id=10), mismatch_ctx)

        negative_total_ctx, _client = context({"dashboards": [], "total": -1})
        with self.assertRaisesRegex(ApiError, "total"):
            dashboard_lists.run_items(ns(list_id=10), negative_total_ctx)

        dashboard_mismatch_ctx, _client = context(
            {
                "id": "wrong-id",
                "title": "Wrong Dashboard",
                "layout_type": "ordered",
                "widgets": [],
            }
        )
        with self.assertRaisesRegex(ApiError, "ID"):
            get_dashboard.run(ns(dashboard_id="expected-id"), dashboard_mismatch_ctx)

        one_item = self.dashboard_lists["items"]["dashboards"][0]
        inconsistent_total_ctx, _client = context(
            {"dashboards": [one_item], "total": 0}
        )
        with self.assertRaisesRegex(ApiError, "total"):
            dashboard_lists.run_items(ns(list_id=10), inconsistent_total_ctx)

    def test_dashboard_list_commands_use_official_paths(self) -> None:
        list_ctx, list_client = context(self.dashboard_lists["all_lists"])
        listed = dashboard_lists.run_list(ns(), list_ctx)
        self.assertEqual(list_client.calls[0]["method"], "GET")
        self.assertEqual(list_client.calls[0]["path"], "/api/v1/dashboard/lists/manual")
        self.assertNotIn("email", listed.result["dashboard_lists"][0]["author"])

        get_ctx, get_client = context(self.dashboard_lists["single"])
        fetched = dashboard_lists.run_get(ns(list_id=10), get_ctx)
        self.assertEqual(get_client.calls[0]["path"], "/api/v1/dashboard/lists/manual/10")
        self.assertEqual(fetched.result["dashboard_list"]["id"], 10)

        items_ctx, items_client = context(self.dashboard_lists["items"])
        items = dashboard_lists.run_items(ns(list_id=10), items_ctx)
        self.assertEqual(
            items_client.calls[0]["path"],
            "/api/v2/dashboard/lists/manual/10/dashboards",
        )
        self.assertEqual(items.result["returned"], 2)
        self.assertEqual(items.meta["pagination"]["total"], 2)
        self.assertEqual(items.meta["pagination"]["completion"], "complete")


if __name__ == "__main__":
    unittest.main()
