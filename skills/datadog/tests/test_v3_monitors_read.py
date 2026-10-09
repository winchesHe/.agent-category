from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from dd_v3.commands import monitors
from dd_v3.config import Config
from dd_v3.runtime import CommandResult, RuntimeContext, RuntimeState


def _config() -> Config:
    return Config(
        api_key="test-key",
        app_key="test-app-key",
        api_base_url="https://api.us5.datadoghq.com",
        ui_base_url="https://us5.datadoghq.com",
        default_env="ns-production",
        timeout=1,
        max_retries=4,
    )


def _monitor():
    return {
        "id": 42,
        "name": "Payment latency",
        "type": "query alert",
        "query": "avg(last_5m):avg:payment.latency{*} > 1",
        "modified": "2026-08-17T00:00:00+00:00",
        "overall_state": "Alert",
        "restricted_roles": ["role-1"],
        "options": {"silenced": {}},
    }


class RecordingClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.events = []

    def request_read(self, method, path, *, params=None, json_body=None, surface="api"):
        self.events.append((method, path, params))
        return self.responses.pop(0)


def _context(client) -> RuntimeContext:
    return RuntimeContext(config=_config(), client=client, state=RuntimeState())


class MonitorReadTests(unittest.TestCase):
    def test_list_monitor_adapter_is_read_only(self):
        client = RecordingClient([[_monitor()]])
        args = SimpleNamespace(
            group_states="alert,warn",
            name=None,
            tags=None,
            monitor_tags="service:payment",
            with_downtimes=False,
            page=2,
            page_size=50,
        )
        result = monitors.run_list(args, _context(client))

        self.assertIsInstance(result, CommandResult)
        self.assertEqual(result.result["count"], 1)
        self.assertEqual(result.target["page"], 2)
        self.assertEqual(client.events[0][1], "/api/v1/monitor")

    def test_search_monitor_adapter_preserves_server_metadata(self):
        response = {
            "metadata": {"page": 1, "page_count": 4, "per_page": 25, "total_count": 88},
            "monitors": [_monitor()],
        }
        client = RecordingClient([response])
        args = SimpleNamespace(
            query="service:payment status:alert",
            page=1,
            per_page=25,
            sort="status,desc",
        )
        result = monitors.run_search(args, _context(client))

        self.assertEqual(result.result["metadata"], response["metadata"])
        self.assertEqual(client.events[0][2]["per_page"], 25)


if __name__ == "__main__":
    unittest.main()
