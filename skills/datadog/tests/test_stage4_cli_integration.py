from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SKILL_DIR = Path(__file__).resolve().parents[1]
CLI = SKILL_DIR / "scripts" / "datadog.py"


class FakeDatadogServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or "0")
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                outer.requests.append({"method": "POST", "path": self.path, "body": json.loads(body)})
                self._send_json(
                    {
                        "data": [
                            {
                                "id": "log1",
                                "attributes": {
                                    "timestamp": "2024-01-01T00:00:00Z",
                                    "service": "svc",
                                    "status": "info",
                                    "message": "hello",
                                    "attributes": {"trace_id": "trace1", "@id": "req1"},
                                },
                            }
                        ],
                        "meta": {"page": {"after": "cursor1"}},
                    }
                )

            def do_GET(self):
                parsed = urlparse(self.path)
                outer.requests.append({"method": "GET", "path": parsed.path, "query": parse_qs(parsed.query)})
                if parsed.path == "/api/v2/apm/services":
                    self._send_json({"data": ["svc-a", "svc-b"]})
                else:
                    self._send_json({"trace": {"spans": {}}})

            def _send_json(self, payload):
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format, *args):
                return

        return Handler

    @property
    def site(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def run_cli(args: list[str], env: dict[str, str] | None = None):
    merged = os.environ.copy()
    merged.update(
        {
            "DD_API_KEY": "test-api-key",
            "DD_APP_KEY": "test-app-key",
            "DD_DEFAULT_ENV": "ns-production",
            "DD_DISABLE_DOTENV": "1",
        }
    )
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(SKILL_DIR),
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


class CliIntegrationTests(unittest.TestCase):
    def test_help_does_not_require_config(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CLI), "--help"],
            cwd=str(SKILL_DIR),
            env={"DD_DISABLE_DOTENV": "1"},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("search-logs", result.stdout)

    def test_missing_config_exits_2(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CLI), "list-services"],
            cwd=str(SKILL_DIR),
            env={"DD_DISABLE_DOTENV": "1"},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("缺少必填环境变量", result.stderr)

    def test_search_logs_end_to_end_against_fake_server(self) -> None:
        with FakeDatadogServer() as server:
            result = run_cli(
                ["search-logs", "--query", "service:svc", "--from", "15m", "--limit", "1"],
                {"DD_SITE": server.site},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["next_cursor"], "cursor1")
        self.assertEqual(data["logs"][0]["trace_id"], "trace1")

    def test_list_services_end_to_end_against_fake_server(self) -> None:
        with FakeDatadogServer() as server:
            result = run_cli(["list-services", "--from", "15m", "--filter", "svc-*"], {"DD_SITE": server.site})
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["services"], ["svc-a", "svc-b"])


if __name__ == "__main__":
    unittest.main()
