from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from mscli.client import Client
from mscli.commands import batch_create_cases, case_review_records, create_case, edit_case, fetch_all_pages, parse_json_source, run
from mscli.config import Config, load_config
from mscli.errors import EXIT_API, EXIT_AUTH, EXIT_TIMEOUT, CapabilityUnavailable, MeterSphereError
from mscli.formatter import output


def config() -> Config:
    return Config(
        base_url="https://ms.example.test",
        access_key="1234567890123456",
        secret_key="1234567890123456",
        project_id="project-1",
        organization_id="100001",
        workspace_id="",
        headers_json="",
        protocols_json='["HTTP"]',
        skill_root=Path(__file__).resolve().parents[1],
        env_file=None,
    )


class Response:
    def __init__(self, value):
        self.value = value
        self.headers = mock.Mock()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.value).encode()


class FakeClient:
    def __init__(self):
        self.calls = []
        self.case = {
            "id": "case-1",
            "projectId": "project-1",
            "nodeId": "node-1",
            "nodePath": "/root/temp",
            "versionId": "version-1",
            "name": "before",
            "steps": "[]",
        }

    def multipart(self, endpoint, payload, *, project_id):
        self.calls.append(("multipart", endpoint, payload, project_id))
        self.case.update(payload)
        return {"success": True, "data": {"id": "case-1"}}

    def request(self, method, endpoint, body=None, **kwargs):
        self.calls.append((method, endpoint, body, kwargs))
        if endpoint == "/track/test/case/get/edit/simple/case-1":
            return {"success": True, "data": dict(self.case)}
        if endpoint == "/track/test/case/review/list/all":
            return {"success": True, "data": [{"id": "review-1", "name": "R", "status": "Finished"}]}
        if endpoint.startswith("/track/test/review/case/list/1/"):
            return {"success": True, "data": {"listObject": [{"caseId": "case-1", "reviewStatus": "Pass"}]}}
        return {"success": True, "data": []}


class FailSecondCreateClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.multipart_count = 0

    def multipart(self, endpoint, payload, *, project_id):
        self.multipart_count += 1
        if self.multipart_count == 2:
            raise MeterSphereError("second item rejected", EXIT_API)
        return super().multipart(endpoint, payload, project_id=project_id)


class FailCreateAndRollbackClient(FailSecondCreateClient):
    def request(self, method, endpoint, body=None, **kwargs):
        if endpoint.startswith("/track/test/case/delete/"):
            raise MeterSphereError("rollback rejected", EXIT_API)
        return super().request(method, endpoint, body, **kwargs)


class PagedClient:
    def __init__(self):
        self.pages = []

    def request(self, method, endpoint, body=None, **kwargs):
        current = int(endpoint.rsplit("/", 2)[-2])
        self.pages.append(current)
        rows = [{"id": f"case-{index}"} for index in range((current - 1) * 2, min(current * 2, 5))]
        return {"success": True, "data": {"listObject": rows, "itemCount": 5}}


class ClientTests(unittest.TestCase):
    def test_explicit_env_file_overrides_skill_env_but_not_process_env(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "METERSPHERE_BASE_URL=https://explicit.test\n"
                "METERSPHERE_ACCESS_KEY=explicit-ak\n"
                "METERSPHERE_SECRET_KEY=explicit-sk\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"METERSPHERE_ENV_FILE": str(env_path)}, clear=True):
                loaded = load_config()
                self.assertEqual(loaded.base_url, "https://explicit.test")
                self.assertEqual(loaded.env_file, env_path)
            with mock.patch.dict(os.environ, {
                "METERSPHERE_ENV_FILE": str(env_path),
                "METERSPHERE_BASE_URL": "https://process.test",
                "METERSPHERE_ACCESS_KEY": "process-ak",
                "METERSPHERE_SECRET_KEY": "process-sk",
            }, clear=True):
                loaded = load_config()
                self.assertEqual(loaded.base_url, "https://process.test")

    @mock.patch.object(Client, "_signature", return_value="signature")
    @mock.patch("urllib.request.urlopen")
    def test_business_failure_is_nonzero_api_error(self, urlopen, _signature):
        urlopen.return_value = Response({"success": False, "message": "bad request"})
        with self.assertRaises(MeterSphereError) as caught:
            Client(config()).request("GET", "/broken")
        self.assertEqual(caught.exception.code, EXIT_API)

    @mock.patch.object(Client, "_signature", return_value="signature")
    @mock.patch("urllib.request.urlopen")
    def test_capability_404_wrapped_in_500_is_explicit(self, urlopen, _signature):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://ms.example.test/feature", 500, "error", {},
            io.BytesIO(b'{"message":"service call error, status 404, No static resource"}'),
        )
        with self.assertRaises(CapabilityUnavailable):
            Client(config()).request("GET", "/feature", capability="feature")

    @mock.patch.object(Client, "_signature", return_value="signature")
    @mock.patch("urllib.request.urlopen")
    def test_invalid_access_key_wrapped_in_500_is_auth_error(self, urlopen, _signature):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://ms.example.test/project", 500, "error", {},
            io.BytesIO(b"RuntimeException: invalid accessKey"),
        )
        with self.assertRaises(MeterSphereError) as caught:
            Client(config()).request("POST", "/project", {})
        self.assertEqual(caught.exception.code, EXIT_AUTH)
        self.assertNotIn("RuntimeException", str(caught.exception))

    @mock.patch.object(Client, "_signature", return_value="signature")
    @mock.patch("urllib.request.urlopen")
    def test_multipart_uses_request_json_part(self, urlopen, _signature):
        urlopen.return_value = Response({"success": True, "data": {"id": "case-1"}})
        Client(config()).multipart("/track/test/case/add", {"name": "测试"}, project_id="project-1")
        request = urlopen.call_args.args[0]
        self.assertIn('name="request"', request.data.decode())
        self.assertIn('"name": "测试"', request.data.decode())
        self.assertTrue(request.headers["Content-type"].startswith("multipart/form-data"))

    @mock.patch.object(Client, "_signature", return_value="signature")
    @mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError(TimeoutError("slow")))
    def test_timeout_uses_exit_code_five(self, _urlopen, _signature):
        with self.assertRaises(MeterSphereError) as caught:
            Client(config(), timeout=0.01).request("GET", "/slow")
        self.assertEqual(caught.exception.code, EXIT_TIMEOUT)


class CommandTests(unittest.TestCase):
    def test_summary_format_preserves_aggregate_counts(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            output({"success": True, "totalCases": 24012, "reviewedCases": 100}, "summary")
        self.assertEqual(json.loads(stdout.getvalue()), {"success": True, "totalCases": 24012, "reviewedCases": 100})

    def test_long_inline_batch_json_is_not_treated_as_file_path(self):
        payload = [{"name": "x" * 300}, {"name": "y" * 300}]
        self.assertEqual(parse_json_source(json.dumps(payload)), payload)

    def test_batch_create_rolls_back_earlier_items_when_later_item_fails(self):
        client = FailSecondCreateClient()
        payload = {
            "nodeId": "node-1", "nodePath": "/root/temp", "versionId": "version-1", "name": "batch", "steps": []
        }
        with self.assertRaisesRegex(MeterSphereError, "已回滚 1 条"):
            batch_create_cases(client, config(), [payload, payload])
        self.assertTrue(any(call[1] == "/track/test/case/delete/case-1" for call in client.calls))

    def test_batch_create_reports_rollback_failure(self):
        client = FailCreateAndRollbackClient()
        payload = {
            "nodeId": "node-1", "nodePath": "/root/temp", "versionId": "version-1", "name": "batch", "steps": []
        }
        with self.assertRaisesRegex(MeterSphereError, "回滚失败: case-1"):
            batch_create_cases(client, config(), [payload, payload])

    def test_fetch_all_pages_stops_at_item_count(self):
        client = PagedClient()
        rows = fetch_all_pages(
            client, "/track/test/case/list/{current}/{pageSize}", {"projectId": "project-1"},
            project_id="project-1", page_size=2,
        )
        self.assertEqual([row["id"] for row in rows], ["case-0", "case-1", "case-2", "case-3", "case-4"])
        self.assertEqual(client.pages, [1, 2, 3])

    def test_create_case_uses_multipart_and_readback(self):
        client = FakeClient()
        result = create_case(client, config(), json.dumps({
            "nodeId": "node-1", "nodePath": "/root/temp", "versionId": "version-1", "name": "created", "steps": []
        }))
        self.assertEqual(result["id"], "case-1")
        self.assertEqual(result["readback"]["data"]["name"], "created")
        self.assertEqual(client.calls[0][1], "/track/test/case/add")

    def test_edit_case_merges_existing_and_reads_back(self):
        client = FakeClient()
        result = edit_case(client, config(), "case-1", '{"name":"after"}')
        multipart_call = next(call for call in client.calls if call[0] == "multipart")
        self.assertEqual(multipart_call[1], "/track/test/case/edit")
        self.assertEqual(multipart_call[2]["name"], "after")
        self.assertTrue(multipart_call[2]["latest"])
        self.assertEqual(result["readback"]["data"]["name"], "after")

    def test_case_review_records_use_real_relationship(self):
        result = case_review_records(FakeClient(), config(), "project-1", "case-1")
        self.assertTrue(result["reviewed"])
        self.assertEqual(result["data"][0]["caseReviewStatus"], "Pass")

    def test_review_detail_uses_review_case_endpoint(self):
        client = FakeClient()
        run(config(), client, "case-review-detail", ["list", '{"reviewId":"review-1"}'])
        self.assertTrue(any(call[1] == "/track/test/review/case/list/1/20" for call in client.calls))

    def test_review_user_requires_review_id(self):
        with self.assertRaises(MeterSphereError):
            run(config(), FakeClient(), "case-review-user", ["list"])


if __name__ == "__main__":
    unittest.main()
