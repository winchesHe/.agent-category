import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from st.commands import analyze
from st.config import Config


class AnalysisBehaviorTests(unittest.TestCase):
    def run_event_analysis(self, event):
        args = SimpleNamespace(
            url=None, org=None, issue_id="123", event_id=None,
            mode="latest", events=1, target="json",
        )
        with mock.patch.object(analyze, "SentryClient") as client, mock.patch("sys.stdout", new=io.StringIO()) as stdout:
            client.return_value.get_issue_resource.side_effect = [
                {"id": "123", "title": "boom", "count": "1", "userCount": 1}, event,
            ]
            self.assertEqual(analyze.run(args, self.make_config()), 0)
        return json.loads(stdout.getvalue())

    def test_normal_console_logs_do_not_hide_navigation_before_crash(self):
        for level in ("info", "log", "debug", "warning"):
            for crash_level in ("error", "fatal"):
                with self.subTest(level=level, crash_level=crash_level):
                    result = self.run_event_analysis({"breadcrumbs": {"values": [
                        {"category": "navigation", "data": {"from": "/home", "to": "/calendar"}},
                        {"category": "console", "level": level, "message": "initialized"},
                        {"category": "navigation", "data": {"from": "/calendar", "to": "/clients/42"}},
                        {"category": "console", "level": crash_level, "message": "boom"},
                        {"category": "navigation", "data": {"from": "/clients/42", "to": "/settings"}},
                    ]}})
                    route = result["analysis"]["route_context"]
                    self.assertEqual((route["from"], route["to"]), ("/calendar", "/clients/42"))

    def test_crash_repo_and_source_kind_use_the_same_frame(self):
        cases = [
            ([{"filename": "index~entry.js", "in_app": True},
              {"filename": "lib-moego-ui.form.js", "in_app": True}], "ui_library_bundle", "MoeGolibrary/moego-ui"),
            ([{"filename": "lib-moego-ui.form.js", "inApp": True},
              {"filename": "index~entry.js", "inApp": True}], "business_bundle", "MoeGolibrary/Boarding_Desktop"),
            ([{"filename": "index~entry.js"}, {"filename": "lib-moego-ui.form.js"},
              {"filename": "node_modules/runtime.js"}], "ui_library_bundle", "MoeGolibrary/moego-ui"),
            ([{"filename": "index~entry.js", "in_app": True},
              {"filename": "lib-moego-ui.form.js", "in_app": False}], "business_bundle", "MoeGolibrary/Boarding_Desktop"),
            ([{"filename": "index~entry.js", "in_app": True},
              {"filename": "unknown.js", "in_app": True}], "unknown_bundle", None),
            ([], "unknown_bundle", None),
        ]
        for frames, source_kind, repo in cases:
            with self.subTest(frames=frames):
                result = self.run_event_analysis({"exception": {"values": [{
                    "type": "TypeError", "value": "boom", "stacktrace": {"frames": frames},
                }]}})
                self.assertEqual(result["exceptions"][0]["source_kind"], source_kind)
                boundary = result["analysis"]["fix_boundary"]
                self.assertEqual(boundary["downstream_repo"], repo)
                self.assertEqual(result["root_cause_candidates"][0]["repos"], [repo] if repo else [])
                if repo:
                    self.assertIn(repo, boundary["recommended_first_fix"])
                else:
                    self.assertIsNone(boundary["recommended_first_fix"])

    def make_config(self):
        return Config(
            auth_token="token",
            base_url="https://trusted.sentry.io",
            default_org_slug="moego",
            default_project=None,
            timeout=1.0,
            max_retries=0,
        )

    def test_source_kind_prefers_in_app_frame_over_first_frame(self):
        raw_events = [
            {
                "exception": {
                    "values": [
                        {
                            "type": "TypeError",
                            "value": "boom",
                            "stacktrace": {
                                "frames": [
                                    {"filename": "node_modules/react-dom.js", "function": "commitRoot", "in_app": False},
                                    {"filename": "index~main.chunk.js", "function": "renderCalendarView", "in_app": True},
                                ]
                            },
                        }
                    ]
                }
            }
        ]

        exceptions = analyze._extract_all_exceptions(raw_events)

        self.assertEqual(exceptions[0]["source_kind"], "business_bundle")

    def test_source_kind_falls_back_to_app_bundle_match_when_no_in_app_frame_exists(self):
        raw_events = [
            {
                "exception": {
                    "values": [
                        {
                            "type": "TypeError",
                            "value": "boom",
                            "stacktrace": {
                                "frames": [
                                    {"filename": "node_modules/react-dom.js", "function": "commitRoot", "in_app": False},
                                    {"filename": "lib-moego-ui.chunk.js", "function": "Dropdown.cleanup", "in_app": False},
                                ]
                            },
                        }
                    ]
                }
            }
        ]

        exceptions = analyze._extract_all_exceptions(raw_events)

        self.assertEqual(exceptions[0]["source_kind"], "ui_library_bundle")

    def test_analyze_uses_selected_event_navigation_before_crash(self):
        config = self.make_config()
        args = SimpleNamespace(
            url="https://evil.example.com/organizations/moego/issues/123/",
            org=None,
            issue_id=None,
            event_id=None,
            mode="issue",
            events=2,
            target="json",
        )

        issue = {"id": "123", "title": "Issue title", "count": "2", "userCount": 1}
        listing = [{"eventID": "selected"}, {"eventID": "older"}]
        selected_event = {
            "id": "selected",
            "eventID": "selected",
            "dateCreated": "2026-06-05T10:00:12Z",
            "entries": [
                {
                    "type": "breadcrumbs",
                    "data": {
                        "values": [
                            {"timestamp": "2026-06-05T10:00:00Z", "category": "navigation", "data": {"from": "/home", "to": "/calendar"}},
                            {"timestamp": "2026-06-05T10:00:10Z", "category": "navigation", "data": {"from": "/calendar", "to": "/clients/42"}},
                            {"timestamp": "2026-06-05T10:00:11Z", "category": "console", "level": "error", "message": "boom"},
                            {"timestamp": "2026-06-05T10:00:13Z", "category": "navigation", "data": {"from": "/clients/42", "to": "/settings"}},
                        ]
                    },
                }
            ],
        }
        older_event = {
            "id": "older",
            "eventID": "older",
            "dateCreated": "2026-06-05T09:00:00Z",
            "entries": [
                {
                    "type": "breadcrumbs",
                    "data": {
                        "values": [
                            {"timestamp": "2026-06-05T09:00:00Z", "category": "navigation", "data": {"from": "/legacy", "to": "/legacy-crash"}}
                        ]
                    },
                }
            ],
        }

        responses = [issue, listing, selected_event, older_event]

        class FakeClient:
            def __init__(self, client_config, *, session=None):
                self.client_config = client_config

            def get(self, path, *, params=None):
                return responses.pop(0)

            def get_issue_resource(self, org, issue_id, suffix="", *, params=None):
                return self.get(
                    f"/api/0/organizations/{org}/issues/{issue_id}/{suffix}",
                    params=params,
                )

        with mock.patch.object(analyze, "SentryClient", FakeClient), mock.patch("sys.stdout", new=io.StringIO()) as stdout:
            exit_code = analyze.run(args, config)

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["analysis"]["route_context"]["from"], "/calendar")
        self.assertEqual(result["analysis"]["route_context"]["to"], "/clients/42")

    def test_single_ui_exception_is_not_labeled_as_upstream_by_bundle_type(self):
        """bundle 类型不能在缺少时序证据时替代因果判断。"""
        exceptions = [
            {
                "type": "TypeError",
                "message": "boom",
                "source_kind": "ui_library_bundle",
                "frames": [],
            }
        ]

        chain = analyze._build_exception_chain(exceptions, [])

        self.assertEqual(chain[0]["role"], "direct_crash_point")
        self.assertIn("does not establish upstream causality", chain[0]["evidence"][0])

    def test_exception_chain_never_combines_different_events(self):
        """不同 event 的异常与 console breadcrumb 不能拼成一条因果链。"""
        raw_events = [
            {
                "exception": {"values": [{"type": "SelectedError", "value": "selected boom"}]},
                "breadcrumbs": {
                    "values": [
                        {
                            "timestamp": "2026-07-30T01:00:00Z",
                            "category": "console",
                            "level": "error",
                            "message": "selected boom",
                        }
                    ]
                },
            },
            {
                "exception": {"values": [{"type": "OlderError", "value": "older boom"}]},
                "breadcrumbs": {
                    "values": [
                        {
                            "timestamp": "2026-07-30T00:00:00Z",
                            "category": "console",
                            "level": "error",
                            "message": "older boom",
                        },
                        {
                            "timestamp": "2026-07-30T00:00:01Z",
                            "category": "fetch",
                            "message": "GET /api/old",
                            "data": {"url": "/api/old", "status_code": 503},
                        },
                    ]
                },
            },
        ]

        chain = analyze._build_selected_exception_chain(raw_events)

        self.assertEqual([item["type"] for item in chain], ["SelectedError"])
        self.assertEqual(chain[0]["role"], "direct_crash_point")
        correlation = analyze._build_selected_backend_correlation(raw_events)
        self.assertEqual(correlation["status"], "none")

    def test_fix_boundary_follows_exception_timeline_and_stays_investigative(self):
        """repo 边界遵循异常时序，并且不编造具体代码修复。"""
        exceptions = [
            {
                "type": "ApiContractError",
                "message": "missing petId",
                "frames": [{"filename": "online-booking/checkout.js"}],
            },
            {
                "type": "TypeError",
                "message": "reading id",
                "frames": [{"filename": "lib-moego-ui.form.js"}],
            },
        ]
        chain = [
            {"type": "ApiContractError", "message": "missing petId", "role": "upstream_trigger"},
            {"type": "TypeError", "message": "reading id", "role": "direct_crash_point"},
        ]
        boundary = analyze._build_fix_boundary(exceptions, chain)

        self.assertEqual(boundary["upstream_repo"], "MoeGolibrary/online-booking-client-web")
        self.assertEqual(boundary["downstream_repo"], "MoeGolibrary/moego-ui")
        self.assertIn("Investigate", boundary["recommended_first_fix"])
        self.assertNotIn("Guard null", boundary["recommended_first_fix"])
        self.assertNotIn("error boundary", boundary["recommended_followup_fix"])

    def test_fix_boundary_does_not_fill_direct_repo_from_upstream_candidate(self):
        """直接崩溃点无 repo 映射时，不得借用前置异常的 repo。"""
        exceptions = [
            {
                "type": "ApiContractError",
                "message": "missing petId",
                "frames": [{"filename": "online-booking/checkout.js"}],
            },
            {
                "type": "RuntimeError",
                "message": "external crash",
                "frames": [{"filename": "https://cdn.example.com/vendor.js"}],
            },
        ]
        chain = [
            {"type": "ApiContractError", "message": "missing petId", "role": "upstream_trigger"},
            {"type": "RuntimeError", "message": "external crash", "role": "direct_crash_point"},
        ]
        boundary = analyze._build_fix_boundary(exceptions, chain)

        self.assertEqual(boundary["upstream_repo"], "MoeGolibrary/online-booking-client-web")
        self.assertIsNone(boundary["downstream_repo"])
        self.assertIsNone(boundary["recommended_first_fix"])
        self.assertIn("preceding trigger candidate", boundary["recommended_followup_fix"])

        candidates = analyze._build_root_cause_candidates(
            [chain[1]],
            exceptions,
        )
        self.assertEqual(candidates[0]["repos"], [])

    def test_backend_correlation_uses_only_observed_query_fields(self):
        """没有 service 证据时，Datadog query 不能硬编码服务名。"""
        breadcrumbs = [
            {
                "timestamp": "2026-07-30T02:21:03Z",
                "category": "fetch",
                "message": "GET /api/v1/quotes",
                "data": {"method": "GET", "url": "/api/v1/quotes", "status_code": 503},
            }
        ]

        correlation = analyze._build_backend_correlation(breadcrumbs)

        self.assertEqual(
            correlation["datadog_queries"],
            ['status:error @http.url:"/api/v1/quotes" @http.status_code:503'],
        )
        self.assertEqual(correlation["requests"][0]["timestamp"], "2026-07-30T02:21:03Z")
        self.assertNotIn("service:", correlation["datadog_queries"][0])

    def test_backend_correlation_includes_explicit_service(self):
        """breadcrumb 明确提供 service 时才把它加入 Datadog query。"""
        breadcrumbs = [
            {
                "timestamp": "2026-07-30T02:21:03Z",
                "category": "http",
                "message": "GET /api/v1/quotes",
                "data": {
                    "method": "GET",
                    "url": "/api/v1/quotes",
                    "status_code": 503,
                    "service": "quotes-api",
                },
            }
        ]

        correlation = analyze._build_backend_correlation(breadcrumbs)

        self.assertEqual(
            correlation["datadog_queries"],
            ['service:"quotes-api" status:error @http.url:"/api/v1/quotes" @http.status_code:503'],
        )


if __name__ == "__main__":
    unittest.main()
