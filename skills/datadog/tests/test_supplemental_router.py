from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def load_entrypoint():
    spec = importlib.util.spec_from_file_location(
        "datadog_entrypoint",
        SCRIPTS_DIR / "datadog.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SupplementalRouterTests(unittest.TestCase):
    def test_public_supplemental_commands_are_read_only(self):
        entrypoint = load_entrypoint()
        self.assertEqual(
            set(entrypoint._SUPPLEMENTAL_COMMANDS),
            {
                "search-trace-logs",
                "get-log-context",
                "summarize-errors",
                "compare-log-counts",
                "group-log-patterns",
                "list-log-services",
                "list-dashboards",
                "list-dashboard-lists",
                "get-dashboard-list",
                "list-dashboard-list-items",
                "scan-slow-sql",
                "list-monitors",
                "search-monitors",
                "get-monitor",
                "list-datastores",
                "list-datastore-items",
            },
        )
        self.assertNotIn("mute-monitor", entrypoint._SUPPLEMENTAL_COMMANDS)
        self.assertNotIn("unmute-monitor", entrypoint._SUPPLEMENTAL_COMMANDS)

    def test_supplemental_command_delegates_to_isolated_runtime(self):
        entrypoint = load_entrypoint()
        with patch("dd_v3.runtime.main", return_value=17) as delegated:
            result = entrypoint.main(["list-monitors", "--page-size", "1"])

        self.assertEqual(result, 17)
        delegated.assert_called_once_with(["list-monitors", "--page-size", "1"])

    def test_v3_registry_has_no_monitor_write_commands(self):
        from dd_v3.commands import ALL

        names = {
            name
            for module in ALL
            for name in getattr(module, "NAMES", (getattr(module, "NAME", None),))
            if name
        }
        self.assertIn("list-monitors", names)
        self.assertIn("get-monitor", names)
        self.assertIn("list-datastores", names)
        self.assertIn("list-datastore-items", names)
        self.assertNotIn("mute-monitor", names)
        self.assertNotIn("unmute-monitor", names)


if __name__ == "__main__":
    unittest.main()
