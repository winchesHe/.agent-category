from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from dd.commands import aggregate_logs, get_dependencies, get_trace, list_services, search_logs, search_spans
from dd.formatter import output

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES_DIR / name).read_text())


class ExtractionTests(unittest.TestCase):
    def test_extract_log_flattens_request_trace_and_error(self) -> None:
        log = search_logs.extract_log(
            {
                "id": "log1",
                "attributes": {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "service": "svc",
                    "status": "error",
                    "attributes": {
                        "@id": "req-1",
                        "trace_id": "trace-1",
                        "http": {"method": "GET", "status_code": 500, "url_details": {"path": "/pets"}},
                        "error": {"message": "boom", "kind": "ValueError"},
                    },
                },
            }
        )
        self.assertEqual(log["message"], "GET /pets (500)")
        self.assertEqual(log["request_id"], "req-1")
        self.assertEqual(log["trace_id"], "trace-1")
        self.assertEqual(log["error"]["message"], "boom")

    def test_extract_span_converts_duration_and_flags_slow(self) -> None:
        span = search_spans.extract_span(
            {"attributes": {"duration": 5_000_000, "service": "svc", "trace_id": "t", "error": 1}},
            slow_ms=3,
        )
        self.assertEqual(span["duration_ms"], 5.0)
        self.assertTrue(span["is_slow"])
        self.assertTrue(span["is_error"])

    def test_extract_span_reads_nested_http_error_and_response(self) -> None:
        span = search_spans.extract_span(
            {
                "attributes": {
                    "custom": {
                        "duration": 11_375_244,
                        "http": {
                            "method": "POST",
                            "status_code": "500",
                            "url": "http://nlb-api.moego.pet/moego.bff/timeslot/checkTimeslotAvailability",
                            "url_details": {"path": "/moego.bff/timeslot/checkTimeslotAvailability"},
                        },
                        "error": {
                            "message": "calendar access disabled",
                            "type": "LogicException",
                            "stack": "LogicException: calendar access disabled",
                        },
                        "response": {"status_code": 500},
                    },
                    "resource_name": "POST timeslot/checkTimeslotAvailability",
                    "status": "error",
                }
            }
        )
        self.assertTrue(span["is_error"])
        self.assertEqual(span["duration_ms"], 11.38)
        self.assertEqual(span["http"]["status_code"], "500")
        self.assertEqual(span["http"]["path"], "/moego.bff/timeslot/checkTimeslotAvailability")
        self.assertEqual(span["error"]["kind"], "LogicException")
        self.assertEqual(span["response"]["status_code"], 500)

    def test_search_result_cursor_handles_null_page(self) -> None:
        self.assertIsNone(search_spans._extract_next_cursor({"meta": {"page": None}}))
        self.assertIsNone(search_logs._extract_next_cursor({"meta": {"page": None}}))
        self.assertEqual(search_spans._extract_next_cursor({"meta": {"page": {"after": "abc"}}}), "abc")

    def test_search_and_aggregate_extractors_tolerate_null_data(self) -> None:
        self.assertEqual(search_spans._extract_data_list({"data": None}), [])
        self.assertEqual(search_logs._extract_data_list({"data": None}), [])
        self.assertEqual(aggregate_logs._extract_buckets({"data": None}), [])
        self.assertEqual(aggregate_logs._extract_buckets({"data": []}), [])
        self.assertEqual(aggregate_logs._extract_buckets({"data": {"buckets": None}}), [])

    def test_get_trace_reads_nested_custom_error_and_response(self) -> None:
        spans = get_trace.build_span_tree(
            get_trace.parse_spans(
                {
                    "data": [
                        {
                            "attributes": {
                                "span_id": "1",
                                "service": "moego-bff",
                                "operation_name": "bff.handle.post",
                                "resource_name": "POST timeslot/checkTimeslotAvailability",
                                "status": "error",
                                "custom": {
                                    "duration": 11_375_244,
                                    "http": {"method": "POST", "status_code": "500"},
                                    "error": {
                                        "message": "calendar access disabled",
                                        "type": "LogicException",
                                        "stack": "LogicException: calendar access disabled",
                                    },
                                    "response": {"body": "{\"code\":500}", "status_code": 500},
                                },
                            }
                        }
                    ]
                }
            )
        )
        formatted = get_trace.format_span(spans[0])
        self.assertTrue(formatted["is_error"])
        self.assertEqual(formatted["error"]["type"], "LogicException")
        self.assertEqual(formatted["error"]["message"], "calendar access disabled")
        self.assertEqual(formatted["http"]["status_code"], "500")
        self.assertEqual(formatted["response"]["status_code"], 500)
        self.assertEqual(formatted["payload"], "{\"code\":500}")

    def test_trace_parses_map_and_computes_depth(self) -> None:
        raw = get_trace.parse_spans(
            {
                "trace": {
                    "spans": {
                        "1": {"span_id": "1", "parent_id": "0", "start": 1, "duration": 1_000_000, "service": "root"},
                        "2": {"span_id": "2", "parent_id": "1", "start": 2, "duration": 2_000_000, "service": "child"},
                    }
                }
            }
        )
        spans = [get_trace.format_span(span) for span in get_trace.build_span_tree(raw)]
        self.assertEqual(spans[0]["depth"], 0)
        self.assertEqual(spans[1]["depth"], 1)
        self.assertEqual(spans[1]["duration_ms"], 2.0)

    def test_extract_services_from_multiple_shapes(self) -> None:
        services = list_services.extract_services(
            {"data": ["svc-a", {"attributes": {"service": "svc-b"}}, {"attributes": {"schema": {"dd-service": "svc-c"}}}]}
        )
        self.assertEqual(services, ["svc-a", "svc-b", "svc-c"])

    def test_extract_dependencies_calls_is_downstream(self) -> None:
        # Datadog `/api/v1/service_dependencies` 真实形态：节点 .calls 表示「下游」。
        # `worker.calls` 包含 `svc` 表示 worker 是 svc 的上游调用方。
        result = get_dependencies.extract_dependencies(
            {
                "svc": {"calls": ["api-gw", "db"]},
                "worker": {"calls": ["svc"]},
            },
            "svc",
        )
        self.assertEqual(result["downstream"], ["api-gw", "db"])
        self.assertEqual(result["upstream"], ["worker"])
        self.assertEqual(result["dependencies"], ["api-gw", "db", "worker"])


class RealResponseFixtureTests(unittest.TestCase):
    """金丝雀测试：覆盖 Datadog v1/v2 真实响应形态，防止 extract_* 再次走错分支。"""

    def test_list_services_extracts_data_attributes_services(self) -> None:
        body = _load("list_services_v2.json")
        services = list_services.extract_services(body)
        # fixture 截取了 8 条，确保返回的是真实服务名而不是 ["attributes","id","type"]
        self.assertNotIn("attributes", services)
        self.assertNotIn("id", services)
        self.assertNotIn("type", services)
        self.assertGreaterEqual(len(services), 1)
        for svc in services:
            self.assertIsInstance(svc, str)
            self.assertTrue(svc)
        # fixture 里至少应包含一个 moego 服务
        self.assertTrue(any(s.startswith("moego-") for s in services))

    def test_search_logs_flat_attributes_extracts_service_status_message(self) -> None:
        body = _load("search_logs_v2.json")
        items = body.get("data", [])
        self.assertGreater(len(items), 0)
        log = search_logs.extract_log(items[0])
        self.assertEqual(log["service"], "moego-svc-billing")
        self.assertEqual(log["status"], "error")
        self.assertTrue(log["message"])
        self.assertTrue(log["timestamp"])
        # tags / host 是平铺字段，应该被抽取出来
        self.assertIsNotNone(log["host"])
        self.assertIsInstance(log["tags"], list)

    def test_get_dependencies_real_service_graph(self) -> None:
        body = _load("dependencies_v1.json")
        result = get_dependencies.extract_dependencies(body, "moego-svc-billing")
        # billing.calls 包含 postgres → postgres 是下游
        self.assertIn("postgres", result["downstream"])
        # subscription.calls 包含 billing → subscription 是上游
        self.assertIn("moego-svc-subscription", result["upstream"])
        # 不应再把下游误标为上游
        self.assertNotIn("postgres", result["upstream"])

    def test_get_trace_v2_spans_search_response(self) -> None:
        body = _load("trace_spans_v2.json")
        spans = get_trace.build_span_tree(get_trace.parse_spans(body))
        self.assertGreater(len(spans), 0)
        formatted = [get_trace.format_span(s) for s in spans]
        # duration 必须能从 custom.duration 或 start/end 推算出非 0
        self.assertTrue(any(f["duration_ms"] > 0 for f in formatted))
        # 字段映射：operation_name → operation, resource_name → resource
        self.assertTrue(all(f["operation"] != "unknown" for f in formatted))
        # 树深度：root 节点深度 0
        depths = sorted({f["depth"] for f in formatted})
        self.assertEqual(depths[0], 0)

    def test_search_spans_real_duration_from_custom_or_timestamps(self) -> None:
        body = _load("trace_spans_v2.json")
        items = body.get("data", [])
        self.assertGreater(len(items), 0)
        spans = [search_spans.extract_span(item) for item in items]
        # 任何一个 span 的 duration_ms 应当 > 0（来自 custom.duration 或 end-start）
        self.assertTrue(any(sp["duration_ms"] > 0 for sp in spans))
        for sp in spans:
            self.assertIsNotNone(sp["trace_id"])
            self.assertIsNotNone(sp["span_id"])


class FormatterTests(unittest.TestCase):
    def test_summary_is_single_line_json(self) -> None:
        stream = io.StringIO()
        output({"ok": True}, fmt="summary", file=stream)
        self.assertEqual(stream.getvalue(), '{"ok":true}\n')


if __name__ == "__main__":
    unittest.main()
