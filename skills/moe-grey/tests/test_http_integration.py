import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mgrey.clients.grey import GreyClient
from mgrey.errors import AuthError
from mgrey.http import HttpClient


class Handler(BaseHTTPRequestHandler):
    calls: ClassVar[list] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.calls.append((self.path, payload))
        if self.path == "/forbidden":
            self.send_response(403)
            self.end_headers()
            return
        body = json.dumps(
            {
                "items": [
                    {
                        "id": "1",
                        "name": "local-rule",
                        "namespace": payload["namespace"],
                    }
                ]
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class HttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Handler.calls = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_grey_list_round_trip(self):
        client = GreyClient(self.base_url, HttpClient(timeout=2))
        items = client.list("ns-testing")
        self.assertEqual(items[0]["name"], "local-rule")
        self.assertEqual(Handler.calls[-1][1], {"namespace": "ns-testing"})

    def test_403_maps_to_auth_error(self):
        with self.assertRaises(AuthError):
            HttpClient(timeout=2).post(self.base_url + "/forbidden", json={})


if __name__ == "__main__":
    unittest.main()
