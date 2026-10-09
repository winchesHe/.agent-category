from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.commands.collect import run as collect_run
from mfc.errors import AuthError, BusinessError
from mfc.intercom import (
    SAFE_FIELDS,
    DatadogTransport,
    FixtureTransport,
    IntercomCollector,
    period_filter,
    period_millis,
)

FIXTURE = Path(__file__).parent / "fixtures" / "intercom.json"


def envelope(value, *, completion="complete", returned=1, verified=True):
    start_ms, end_ms = period_millis(date(2026, 8, 17), date(2026, 8, 23))
    return {
        "schema_version": 2,
        "command": "list-datastore-items",
        "ok": True,
        "target": {
            "kind": "actions_datastore_items",
            "datastore_id": "a56cf9ac-2d2d-4e72-b19a-f9f0107868aa",
            "filter": period_filter(start_ms, end_ms),
            "item_key": None,
            "sort": None,
            "fields": list(SAFE_FIELDS),
        },
        "result": {
            "items": [
                {
                    "id": "raw-item-id",
                    "value": value,
                }
            ],
            "returned": returned,
        },
        "meta": {
            "pagination": {
                "mode": "offset",
                "start": 0,
                "limit": 100,
                "returned": returned,
                "total": returned,
                "has_more": False,
                "next": None,
                "completion": completion,
            }
        },
        "verification": (
            {"mode": "converged-read", "passes": 2, "matched": True}
            if verified
            else None
        ),
    }


class StaticTransport:
    def __init__(self, payload):
        self.payload = payload

    def fetch_items(self, _start_ms, _end_ms, *, probe=False):
        return self.payload


class IntercomCollectorTests(unittest.TestCase):
    def test_period_uses_shanghai_half_open_millisecond_window(self):
        start_ms, end_ms = period_millis(date(2026, 8, 17), date(2026, 8, 23))

        self.assertEqual(1786896000000, start_ms)
        self.assertEqual(1787500800000, end_ms)
        self.assertEqual(
            "conversation_created_at:>=1786896000000 "
            "AND conversation_created_at:<1787500800000",
            period_filter(start_ms, end_ms),
        )

    def test_fixture_normalizes_safe_fields_and_hashes_raw_item_id(self):
        result = IntercomCollector(FixtureTransport(FIXTURE)).collect(
            date(2026, 8, 17), date(2026, 8, 23)
        )

        item = result["evidence"][0]
        serialized = json.dumps(item, ensure_ascii=False)
        self.assertEqual("intercom", item["sourceKey"])
        self.assertEqual("feedback", item["objectType"])
        self.assertEqual("支持如[EMAIL]在在线预约时选择偏好员工", item["requirement"])
        self.assertNotIn("raw-datadog-item-1", serialized)
        self.assertNotIn("primary-1", serialized)
        self.assertNotIn("email", serialized)
        self.assertNotIn("conversation_id", serialized)
        self.assertNotIn("quote", serialized)
        self.assertNotIn("customer@example.com", serialized)

    def test_privacy_leak_missing_requirement_and_out_of_period_fail(self):
        base = {
            "conversation_created_at": 1787000000000,
            "requirement": "需求",
        }
        cases = [
            ({**base, "email": "customer@example.com"}, "隐私字段"),
            ({**base, "requirement": ""}, "缺少 requirement"),
            ({**base, "conversation_created_at": 1787500800000}, "超出请求周期"),
            ({**base, "conversation_created_at": "1787000000000"}, "时间字段无效"),
        ]
        for value, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                BusinessError, message
            ):
                IntercomCollector(StaticTransport(envelope(value))).collect(
                    date(2026, 8, 17), date(2026, 8, 23)
                )

    def test_full_collection_rejects_incomplete_or_inconsistent_pagination(self):
        value = {
            "conversation_created_at": 1787000000000,
            "requirement": "需求",
        }
        with self.assertRaisesRegex(BusinessError, "分页不完整"):
            IntercomCollector(
                StaticTransport(envelope(value, completion="truncated"))
            ).collect(date(2026, 8, 17), date(2026, 8, 23))
        with self.assertRaisesRegex(BusinessError, "数量不一致"):
            IntercomCollector(
                StaticTransport(envelope(value, returned=2))
            ).collect(date(2026, 8, 17), date(2026, 8, 23))

    def test_datadog_transport_projects_only_declared_fields(self):
        config = SimpleNamespace(
            datadog_script=Path("/tmp/datadog/scripts/datadog.py"),
            timeout=60,
        )
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "schema_version": 2,
                    "command": "list-datastore-items",
                    "ok": True,
                    "target": {
                        "kind": "actions_datastore_items",
                        "datastore_id": "a56cf9ac-2d2d-4e72-b19a-f9f0107868aa",
                        "filter": period_filter(1, 2),
                        "item_key": None,
                        "sort": None,
                        "fields": list(SAFE_FIELDS),
                    },
                    "result": {"items": [], "returned": 0},
                    "meta": {
                        "schema": {},
                        "pagination": {
                            "mode": "offset",
                            "start": 0,
                            "limit": 100,
                            "returned": 0,
                            "total": 0,
                            "has_more": False,
                            "next": None,
                            "completion": "complete",
                        },
                    },
                    "verification": {
                        "mode": "converged-read",
                        "passes": 2,
                        "matched": True,
                    },
                }
            ),
            stderr="",
        )
        with patch("mfc.intercom.subprocess.run", return_value=completed) as run:
            DatadogTransport(config).fetch_items(1, 2)

        command = run.call_args.args[0]
        projected = [
            command[index + 1]
            for index, value in enumerate(command[:-1])
            if value == "--field"
        ]
        self.assertEqual(list(SAFE_FIELDS), projected)
        self.assertFalse({"email", "conversation_id", "quote"}.intersection(projected))
        self.assertNotIn("--sort", command)
        self.assertIn("--all-pages", command)
        self.assertEqual("2", command[command.index("--consistency-passes") + 1])

    def test_datadog_transport_delegates_complete_pagination_to_datadog_skill(self):
        config = SimpleNamespace(
            datadog_script=Path("/tmp/datadog/scripts/datadog.py"),
            timeout=60,
        )

        payload = envelope(
            {
                "conversation_created_at": 1,
                "requirement": "需求",
            }
        )
        completed = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(payload),
        )
        with patch("mfc.intercom.subprocess.run", return_value=completed) as run:
            payload = DatadogTransport(config).fetch_items(1, 2)

        self.assertEqual(1, run.call_count)
        self.assertEqual("converged-read", payload["verification"]["mode"])

    def test_full_collection_requires_converged_read_verification(self):
        value = {
            "conversation_created_at": 1787000000000,
            "requirement": "需求",
        }
        with self.assertRaisesRegex(BusinessError, "缺少一致性验证"):
            IntercomCollector(StaticTransport(envelope(value, verified=False))).collect(
                date(2026, 8, 17), date(2026, 8, 23)
            )

    def test_collector_rejects_wrong_datadog_envelope_identity(self):
        value = {
            "conversation_created_at": 1787000000000,
            "requirement": "需求",
        }
        cases = [
            ("schema_version", 1),
            ("command", "search-logs"),
            ("target", {"kind": "actions_datastore_items"}),
        ]
        for key, replacement in cases:
            payload = envelope(value)
            payload[key] = replacement
            with self.subTest(key=key), self.assertRaisesRegex(
                BusinessError, "合同不匹配"
            ):
                IntercomCollector(StaticTransport(payload)).collect(
                    date(2026, 8, 17), date(2026, 8, 23)
                )

    def test_datadog_auth_exit_is_mapped_without_stderr_details(self):
        config = SimpleNamespace(
            datadog_script=Path("/tmp/datadog/scripts/datadog.py"),
            timeout=60,
        )
        completed = SimpleNamespace(returncode=3, stdout="", stderr="secret")
        with patch(
            "mfc.intercom.subprocess.run", return_value=completed
        ), self.assertRaisesRegex(AuthError, "鉴权或权限不足"):
            DatadogTransport(config).fetch_items(1, 2)

    def test_offline_collect_writes_private_artifacts_without_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(output_root=Path(directory))
            args = SimpleNamespace(
                source="intercom",
                mode="period",
                sink="local",
                account_ref="",
                headed=False,
                fixture=str(FIXTURE),
                period_start="2026-08-17",
                period_end="2026-08-23",
            )

            result = collect_run(args, config)

            self.assertEqual(1, result["counts"]["fetched"])
            self.assertFalse((Path(directory) / "state" / "intercom.json").exists())
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            self.assertNotIn("checkpointArtifact", manifest)
            run_text = Path(manifest["runArtifact"]).read_text(encoding="utf-8")
            self.assertNotIn("raw-datadog-item-1", run_text)
            self.assertNotIn("primary-1", run_text)
            self.assertNotIn("customer@example.com", run_text)
            self.assertEqual([], json.loads(run_text)["reportRows"])


if __name__ == "__main__":
    unittest.main()
