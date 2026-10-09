import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "growthbook.py"
SDK_SCRIPT_PATH = SKILL_DIR / "scripts" / "growthbook-sdk-eval.mjs"
SMOKE_PATH = SKILL_DIR / "scripts" / "smoke.py"
ENV_EXAMPLE_PATH = SKILL_DIR / ".env.example"
SKILL_MD_PATH = SKILL_DIR / "SKILL.md"
REFERENCES_DIR = SKILL_DIR / "references"


class DummyJsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def load_growthbook_module():
    spec = importlib.util.spec_from_file_location("growthbook_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_smoke_module():
    spec = importlib.util.spec_from_file_location("growthbook_smoke_under_test", SMOKE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GrowthBookBehaviorTests(unittest.TestCase):
    def test_legacy_management_environment_aliases_remain_supported(self):
        gb = load_growthbook_module()
        with mock.patch.dict(
            gb.os.environ,
            {
                "GB_TOKEN": "legacy-token",
                "GB_APP_ORIGIN": "https://legacy.growthbook.example.com",
            },
            clear=True,
        ):
            self.assertEqual(gb.token(), "legacy-token")
            self.assertEqual(gb.origin(), "https://legacy.growthbook.example.com")

    def test_new_management_environment_names_take_precedence(self):
        gb = load_growthbook_module()
        with mock.patch.dict(
            gb.os.environ,
            {
                "GROWTHBOOK_API_TOKEN": "new-token",
                "GB_TOKEN": "legacy-token",
                "GROWTHBOOK_API_BASE_URL": "https://new.growthbook.example.com",
                "GB_APP_ORIGIN": "https://legacy.growthbook.example.com",
            },
            clear=True,
        ):
            self.assertEqual(gb.token(), "new-token")
            self.assertEqual(gb.origin(), "https://new.growthbook.example.com")

    def test_legacy_management_token_is_redacted(self):
        gb = load_growthbook_module()
        with mock.patch.dict(gb.os.environ, {"GB_TOKEN": "legacy-secret"}, clear=True):
            self.assertEqual(
                gb._redact_secrets("failed with legacy-secret"),
                "failed with <redacted:GB_TOKEN>",
            )

    def test_skill_routes_sdk_integration_to_stack_references(self):
        skill_text = SKILL_MD_PATH.read_text(encoding="utf-8")
        expected_references = {
            "sdk-navigation.md",
            "react-react-native-ssr.md",
            "go-server.md",
            "java-spring.md",
            "node-hono.md",
            "python-fastapi.md",
        }

        for reference in expected_references:
            self.assertIn(f"references/{reference}", skill_text)
            self.assertTrue((REFERENCES_DIR / reference).is_file())

        self.assertIn("lockfile", skill_text)
        self.assertIn("当前文档", skill_text)

        python_guide = (REFERENCES_DIR / "python-fastapi.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("asyncio.wait_for(", python_guide)
        self.assertIn("growthbook_init_timeout_seconds", python_guide)

    def test_sdk_navigation_covers_current_official_entries(self):
        navigation = (REFERENCES_DIR / "sdk-navigation.md").read_text(encoding="utf-8")
        official_paths = {
            "script-tag",
            "js",
            "react",
            "vue",
            "kotlin",
            "flutter",
            "swift",
            "react-native",
            "roku",
            "node",
            "nextjs",
            "php",
            "ruby",
            "python",
            "java",
            "kotlin-jvm",
            "csharp",
            "go",
            "rust",
            "elixir",
            "edge/cloudflare",
            "edge/fastly",
            "edge/lambda",
            "edge/other",
            "openfeature",
            "build-your-own",
        }

        for path in official_paths:
            self.assertIn(f"https://docs.growthbook.io/lib/{path}", navigation)

        self.assertIn("最低安全规则", navigation)

    def test_sdk_guides_do_not_hardcode_moego_connection_values(self):
        guide_text = "\n".join(
            path.read_text(encoding="utf-8") for path in REFERENCES_DIR.glob("*.md")
        )

        self.assertNotIn("growthbook.moego.pet", guide_text)
        self.assertNotRegex(guide_text, r"sdk-[A-Za-z0-9]{8,}")
        self.assertNotRegex(guide_text, r"key_prod_[A-Za-z0-9]+")

    def test_eval_feature_invokes_node_sdk_wrapper_without_management_token(self):
        gb = load_growthbook_module()
        stdout = io.StringIO()
        sdk_response = {
            "featureId": "flag-a",
            "found": True,
            "attributes": {
                "inputKeys": ["platform"],
                "used": {"platform": "web", "platfrom": "web"},
            },
            "result": {"value": True, "on": True, "source": "force", "ruleId": "rule-1"},
            "defaultWithoutAttributes": {
                "value": False,
                "on": False,
                "source": "defaultValue",
                "ruleId": None,
            },
            "warnings": ["已将 platform -> platfrom 用于兼容 MoeGo GrowthBook 历史字段"],
        }

        with mock.patch.dict(
            gb.os.environ,
            {
                "GROWTHBOOK_SDK_API_HOST": "https://cdn.growthbook.example.com",
                "GROWTHBOOK_SDK_CLIENT_KEY": "sdk-abc",
                "GROWTHBOOK_SDK_TIMEOUT_MS": "4000",
            },
            clear=True,
        ), \
             mock.patch.object(
                 gb.subprocess,
                 "run",
                 return_value=subprocess.CompletedProcess(
                     ["node", str(SDK_SCRIPT_PATH)],
                     0,
                     stdout=json.dumps(sdk_response),
                     stderr="",
                 ),
             ) as run_mock, \
             mock.patch.object(sys, "stdout", stdout):
            gb.cmd_eval_feature(
                {
                    "feature-id": "flag-a",
                    "attributes-json": '{"platform":"web"}',
                    "url": "https://app.example.com/pricing",
                }
            )

        run_mock.assert_called_once()
        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], "node")
        self.assertEqual(Path(command[1]), SDK_SCRIPT_PATH)
        self.assertNotIn("sdk-abc", command)
        stdin_payload = json.loads(run_mock.call_args.kwargs["input"])
        self.assertEqual(
            stdin_payload,
            {
                "featureId": "flag-a",
                "attributes": {"platform": "web"},
                "url": "https://app.example.com/pricing",
                "raw": False,
                "timeoutMs": 4000,
            },
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, sdk_response)

    def test_eval_feature_subprocess_error_redacts_sdk_secrets(self):
        gb = load_growthbook_module()
        with mock.patch.dict(
            gb.os.environ,
            {
                "GROWTHBOOK_API_TOKEN": "management-secret",
                "GROWTHBOOK_SDK_API_HOST": "https://cdn.growthbook.example.com",
                "GROWTHBOOK_SDK_CLIENT_KEY": "sdk-client-secret",
            },
            clear=True,
        ), \
             mock.patch.object(
                 gb.subprocess,
                 "run",
                 side_effect=subprocess.CalledProcessError(
                     1,
                     ["node", str(SDK_SCRIPT_PATH)],
                     stderr="failed for sdk-client-secret using management-secret",
                 ),
             ), \
             self.assertRaises(SystemExit) as exc, \
             mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            gb.cmd_eval_feature({"feature-id": "flag-a", "attributes-json": "{}"})

        self.assertEqual(exc.exception.code, 1)
        err = stderr.getvalue()
        self.assertIn("SDK eval 失败", err)
        self.assertIn("<redacted:GROWTHBOOK_API_TOKEN>", err)
        self.assertIn("<redacted:GROWTHBOOK_SDK_CLIENT_KEY>", err)
        self.assertNotIn("management-secret", err)
        self.assertNotIn("sdk-client-secret", err)

    def test_eval_feature_missing_config_fails_without_printing_secrets(self):
        gb = load_growthbook_module()
        with mock.patch.dict(
            gb.os.environ,
            {"GROWTHBOOK_API_TOKEN": "management-token"},
            clear=True,
        ), \
             self.assertRaises(SystemExit) as exc, \
             mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            gb.cmd_eval_feature({"feature-id": "flag-a", "attributes-json": "{}"})

        self.assertEqual(exc.exception.code, 1)
        self.assertIn("GROWTHBOOK_SDK_API_HOST", stderr.getvalue())
        self.assertIn("GROWTHBOOK_SDK_CLIENT_KEY", stderr.getvalue())
        self.assertNotIn("management-token", stderr.getvalue())

    def test_eval_feature_rejects_invalid_attributes_json(self):
        gb = load_growthbook_module()
        with mock.patch.dict(
            gb.os.environ,
            {
                "GROWTHBOOK_SDK_API_HOST": "https://cdn.growthbook.example.com",
                "GROWTHBOOK_SDK_CLIENT_KEY": "sdk-abc",
            },
            clear=True,
        ), \
             self.assertRaises(SystemExit) as exc, \
             mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            gb.cmd_eval_feature({"feature-id": "flag-a", "attributes-json": "[]"})

        self.assertEqual(exc.exception.code, 1)
        self.assertIn("--attributes-json 必须是 JSON object", stderr.getvalue())

    def test_node_sdk_eval_script_uses_growthbook_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            script = tmp_dir / "growthbook-sdk-eval.mjs"
            shutil.copyfile(SDK_SCRIPT_PATH, script)
            package_dir = tmp_dir / "node_modules" / "@growthbook" / "growthbook"
            package_dir.mkdir(parents=True)
            (package_dir / "index.js").write_text(
                """
class GrowthBook {
  constructor(options) {
    this.options = options;
    this.attributes = {};
    this.features = {
      "flag-a": { defaultValue: false, rules: [{ id: "rule-1", force: true }] },
      "checkout-flow": { defaultValue: true }
    };
  }
  async init(options) {
    this.initOptions = options;
    return { success: true, source: "network" };
  }
  getFeatures() {
    return this.features;
  }
  setAttributes(attributes) {
    this.attributes = attributes;
  }
  evalFeature(key) {
    if (!(key in this.features)) return { value: null, on: false, source: "unknown" };
    if (this.attributes.company === 8684) {
      return { value: true, on: true, source: "force", ruleId: "rule-1" };
    }
    return { value: false, on: false, source: "defaultValue" };
  }
  destroy() {}
}
module.exports = { GrowthBook };
""",
                encoding="utf-8",
            )

            proc = subprocess.run(
                ["node", str(script)],
                input=json.dumps(
                    {
                        "featureId": "flag-a",
                        "attributes": {"company": 8684, "email": "user@example.com"},
                        "raw": True,
                        "timeoutMs": 1234,
                    }
                ),
                check=True,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "GROWTHBOOK_SDK_API_HOST": "https://cdn.growthbook.example.com",
                    "GROWTHBOOK_SDK_CLIENT_KEY": "sdk-abc",
                },
            )

        payload = json.loads(proc.stdout)
        self.assertEqual(payload["featureId"], "flag-a")
        self.assertTrue(payload["found"])
        self.assertEqual(payload["attributes"]["used"]["company"], 8684)
        self.assertEqual(payload["attributes"]["used"]["email"], "***")
        self.assertEqual(payload["result"]["value"], True)
        self.assertEqual(payload["result"]["source"], "force")
        self.assertEqual(payload["result"]["ruleId"], "rule-1")
        self.assertEqual(payload["defaultWithoutAttributes"]["value"], False)
        self.assertEqual(payload["sdk"]["featureCount"], 2)
        self.assertEqual(payload["sdk"]["init"]["success"], True)
        self.assertIn("raw", payload)
        self.assertNotIn("user@example.com", proc.stdout)

    def test_node_sdk_eval_script_missing_dependency_explains_install_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            script = tmp_dir / "growthbook-sdk-eval.mjs"
            shutil.copyfile(SDK_SCRIPT_PATH, script)

            proc = subprocess.run(
                ["node", str(script)],
                input=json.dumps({"featureId": "flag-a", "attributes": {}}),
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "GROWTHBOOK_SDK_API_HOST": "https://cdn.growthbook.example.com",
                    "GROWTHBOOK_SDK_CLIENT_KEY": "sdk-abc",
                },
            )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("缺少 @growthbook/growthbook", proc.stderr)
        self.assertIn("pnpm install --prod --frozen-lockfile", proc.stderr)
        self.assertNotIn("Cannot find module", proc.stderr)

    def test_env_example_exists_with_required_templates(self):
        self.assertTrue(ENV_EXAMPLE_PATH.exists(), ".env.example should exist")
        text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
        self.assertIn("GROWTHBOOK_API_TOKEN=", text)
        self.assertIn(
            "GROWTHBOOK_API_BASE_URL=https://growthbook.moego.pet/growthbook-api",
            text,
        )
        self.assertIn("GROWTHBOOK_SDK_API_HOST=", text)
        self.assertIn("自托管时它可能与 GROWTHBOOK_API_BASE_URL 相同", text)
        self.assertIn("GROWTHBOOK_SDK_CLIENT_KEY=", text)
        self.assertIn("GROWTHBOOK_SDK_TIMEOUT_MS=10000", text)
        for old_key in ("GB_" + "EVAL_BASE_URL", "GB_" + "CLIENT_KEY"):
            self.assertNotIn(old_key, text)
        self.assertIn("# GB_TOKEN=", text)
        self.assertIn("# GB_APP_ORIGIN=", text)
        self.assertIn("# GB_DOTENV=", text)

    def test_skill_write_contract_mentions_dry_run_and_execute(self):
        text = SKILL_MD_PATH.read_text(encoding="utf-8")
        anchor = text.index("## 8. 示例")
        contract_window = text[max(0, anchor - 1200):anchor]
        self.assertIn("dry-run", contract_window)
        self.assertIn("--execute", contract_window)
        self.assertIn("确认执行吗", contract_window)
        self.assertIn("create-feature-flag --body-file ./new-flag.json --execute", text)
        self.assertIn("--value true --condition '{\"plan\":\"premium\"}' --description \"Premium override\" --execute", text)

    def test_create_feature_flag_without_execute_returns_dry_run(self):
        gb = load_growthbook_module()
        body = {"id": "new-flag", "valueType": "boolean"}
        stdout = io.StringIO()
        with mock.patch.object(gb, "_read_body", return_value=body), \
             mock.patch.object(gb, "gb") as gb_call, \
             mock.patch.object(sys, "stdout", stdout):
            gb.cmd_create_feature_flag({"body-json": json.dumps(body)})

        gb_call.assert_not_called()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["dry_run"], True)
        self.assertEqual(payload["endpoint"], "/api/v1/features")
        self.assertEqual(payload["method"], "POST")
        self.assertEqual(payload["payload"], body)

    def test_create_feature_flag_with_execute_posts(self):
        gb = load_growthbook_module()
        body = {"id": "new-flag", "valueType": "boolean"}
        response = {"feature": {"id": "new-flag"}}
        stdout = io.StringIO()
        with mock.patch.object(gb, "_read_body", return_value=body), \
             mock.patch.object(gb, "gb", return_value=response) as gb_call, \
             mock.patch.object(sys, "stdout", stdout):
            gb.cmd_create_feature_flag({"body-json": json.dumps(body), "execute": True})

        gb_call.assert_called_once_with("POST", "/api/v1/features", body)
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_create_force_rule_without_execute_returns_dry_run_diff(self):
        gb = load_growthbook_module()
        feature = {
            "id": "flag-a",
            "valueType": "boolean",
            "environments": {
                "production": {
                    "enabled": True,
                    "defaultValue": "false",
                    "rules": [],
                }
            },
        }
        stdout = io.StringIO()
        with mock.patch.object(gb, "gb", return_value={"feature": feature}) as gb_call, \
             mock.patch.object(sys, "stdout", stdout):
            gb.cmd_create_force_rule(
                {
                    "feature-id": "flag-a",
                    "env": "production",
                    "value": "true",
                    "description": "allow premium",
                }
            )

        gb_call.assert_called_once_with("GET", "/api/v1/features/flag-a")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["dry_run"], True)
        self.assertEqual(payload["endpoint"], "/api/v1/features/flag-a")
        self.assertEqual(payload["feature_id"], "flag-a")
        self.assertEqual(payload["environment"], "production")
        self.assertEqual(payload["rule_diff"], {"action": "append", "rule_id": None})
        self.assertEqual(payload["payload"]["environments"]["production"]["rules"][0]["value"], "true")

    def test_create_force_rule_with_execute_posts(self):
        gb = load_growthbook_module()
        feature = {
            "id": "flag-a",
            "valueType": "boolean",
            "environments": {
                "production": {
                    "enabled": True,
                    "defaultValue": "false",
                    "rules": [],
                }
            },
        }
        response = {"ok": True}
        stdout = io.StringIO()
        with mock.patch.object(gb, "gb", side_effect=[{"feature": feature}, response]) as gb_call, \
             mock.patch.object(sys, "stdout", stdout):
            gb.cmd_create_force_rule(
                {
                    "feature-id": "flag-a",
                    "env": "production",
                    "value": "true",
                    "execute": True,
                }
            )

        self.assertEqual(gb_call.call_args_list[0].args, ("GET", "/api/v1/features/flag-a"))
        self.assertEqual(gb_call.call_args_list[1].args[0:2], ("POST", "/api/v1/features/flag-a"))
        self.assertEqual(json.loads(stdout.getvalue()), response)

    def test_create_force_rule_boolean_rejects_invalid_literal(self):
        gb = load_growthbook_module()
        feature = {
            "id": "flag-a",
            "valueType": "boolean",
            "environments": {"production": {"rules": []}},
        }
        with mock.patch.object(gb, "gb", return_value={"feature": feature}), \
             self.assertRaises(SystemExit) as exc, \
             mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            gb.cmd_create_force_rule(
                {
                    "feature-id": "flag-a",
                    "env": "production",
                    "value": "yes",
                }
            )

        self.assertEqual(exc.exception.code, 1)
        self.assertIn("boolean 类型", stderr.getvalue())

    def test_create_force_rule_number_keeps_serialized_numeric_string(self):
        gb = load_growthbook_module()
        feature = {
            "id": "flag-a",
            "valueType": "number",
            "environments": {"production": {"rules": []}},
        }
        stdout = io.StringIO()
        with mock.patch.object(gb, "gb", return_value={"feature": feature}), \
             mock.patch.object(sys, "stdout", stdout):
            gb.cmd_create_force_rule(
                {
                    "feature-id": "flag-a",
                    "env": "production",
                    "value": "12.5",
                }
            )

        payload = json.loads(stdout.getvalue())
        rule = payload["payload"]["environments"]["production"]["rules"][0]
        self.assertEqual(rule["value"], "12.5")

    def test_create_force_rule_json_serializes_valid_json_string(self):
        gb = load_growthbook_module()
        feature = {
            "id": "flag-a",
            "valueType": "json",
            "environments": {"production": {"rules": []}},
        }
        stdout = io.StringIO()
        with mock.patch.object(gb, "gb", return_value={"feature": feature}), \
             mock.patch.object(sys, "stdout", stdout):
            gb.cmd_create_force_rule(
                {
                    "feature-id": "flag-a",
                    "env": "production",
                    "value": '{"tier":"pro","count":2}',
                }
            )

        payload = json.loads(stdout.getvalue())
        rule = payload["payload"]["environments"]["production"]["rules"][0]
        self.assertEqual(rule["value"], '{"tier": "pro", "count": 2}')

    def test_get_metrics_normalizes_list_shape(self):
        gb = load_growthbook_module()
        stdout = io.StringIO()
        responses = [
            {"metrics": [{"id": "m1"}]},
            {"factMetrics": [{"id": "fm1"}]},
        ]
        with mock.patch.object(gb, "gb", side_effect=responses), \
             mock.patch.object(sys, "stdout", stdout):
            gb.cmd_get_metrics({"project-id": "prj_1"})

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, {"metrics": [{"id": "m1"}], "factMetrics": [{"id": "fm1"}]})

    def test_fetch_all_paged_stops_when_limit_reached_during_query(self):
        gb = load_growthbook_module()
        pages = [
            {"features": [{"id": "a-one"}, {"id": "a-two"}], "hasMore": True},
            {"features": [{"id": "a-three"}, {"id": "a-four"}], "hasMore": True},
        ]
        with mock.patch.object(gb, "gb", side_effect=pages) as gb_call:
            result = gb.fetch_all_paged("/api/v1/features", query={}, overall_limit=3)

        self.assertEqual([item["id"] for item in result], ["a-one", "a-two", "a-three"])
        self.assertEqual(gb_call.call_count, 2)
        first_path = gb_call.call_args_list[0].args[1]
        second_path = gb_call.call_args_list[1].args[1]
        self.assertIn("limit=3", first_path)
        self.assertIn("offset=2", second_path)
        self.assertIn("limit=1", second_path)

    def test_get_feature_flags_query_does_not_fetch_beyond_requested_limit(self):
        gb = load_growthbook_module()
        pages = [
            {"features": [{"id": "a-one"}, {"id": "b-two"}], "hasMore": True},
            {"features": [{"id": "a-three"}, {"id": "a-four"}], "hasMore": True},
            {"features": [{"id": "z-five"}], "hasMore": False},
        ]
        stdout = io.StringIO()
        with mock.patch.object(gb, "gb", side_effect=pages) as gb_call, \
             mock.patch.object(sys, "stdout", stdout):
            gb.cmd_get_feature_flags({"q": "a", "limit": "2"})

        payload = json.loads(stdout.getvalue())
        self.assertEqual([item["id"] for item in payload["features"]], ["a-one", "a-three"])
        self.assertEqual(payload["total"], 2)
        self.assertLessEqual(gb_call.call_count, 2)

    def test_http_timeout_is_applied(self):
        gb = load_growthbook_module()
        fake_response = io.BytesIO(b'{"ok": true}')

        class DummyContext:
            def __enter__(self_inner):
                return fake_response

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        with mock.patch.dict(gb.os.environ, {"GROWTHBOOK_API_TOKEN": "secret-token"}, clear=True), \
             mock.patch.object(gb.urllib.request, "urlopen", return_value=DummyContext()) as urlopen_mock:
            gb.gb("GET", "/api/v1/projects")

        self.assertEqual(urlopen_mock.call_args.kwargs["timeout"], gb.DEFAULT_TIMEOUT_SECONDS)

    def test_smoke_run_retries_called_process_error_once_then_returns_json(self):
        smoke = load_smoke_module()
        smoke.FAILURES.clear()
        error = subprocess.CalledProcessError(
            1,
            ["growthbook.py", "get-feature-flags"],
            stderr="SSL timeout with secret-token",
        )
        success = subprocess.CompletedProcess(
            ["growthbook.py", "get-feature-flags"],
            0,
            stdout='{"features": [{"id": "flag-a"}]}',
            stderr="",
        )

        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(smoke.subprocess, "run", side_effect=[error, success]) as run_mock, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = smoke.run("get-feature-flags", ["get-feature-flags", "--limit", "5"])

        self.assertEqual(result, {"features": [{"id": "flag-a"}]})
        self.assertEqual(smoke.FAILURES, [])
        self.assertEqual(run_mock.call_count, 2)
        self.assertIn("retry get-feature-flags (1/1)", stdout.getvalue())
        self.assertNotIn("secret-token", stdout.getvalue())

    def test_smoke_run_redacts_secrets_when_all_retries_fail(self):
        smoke = load_smoke_module()
        smoke.FAILURES.clear()
        token = "gb-token-secret"
        client_key = "sdk-client-secret"
        api_host = "https://cdn.growthbook.example.com"
        error = subprocess.CalledProcessError(
            1,
            ["growthbook.py", "get-feature-flags"],
            stderr=(
                f"failed with {token}, {client_key}, and {api_host}\n"
                "second line should not be used"
            ),
        )

        with mock.patch.dict(
            os.environ,
            {
                "GROWTHBOOK_API_TOKEN": token,
                "GROWTHBOOK_SDK_CLIENT_KEY": client_key,
                "GROWTHBOOK_SDK_API_HOST": api_host,
            },
            clear=True,
        ), \
             mock.patch.object(smoke.subprocess, "run", side_effect=[error, error]) as run_mock, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = smoke.run("get-feature-flags", ["get-feature-flags", "--limit", "5"])

        self.assertIsNone(result)
        self.assertEqual(run_mock.call_count, 2)
        output = stdout.getvalue()
        failures_text = repr(smoke.FAILURES)
        for secret in (token, client_key, api_host):
            self.assertNotIn(secret, output)
            self.assertNotIn(secret, failures_text)
        self.assertIn("<redacted:GROWTHBOOK_API_TOKEN>", output)
        self.assertIn("<redacted:GROWTHBOOK_SDK_CLIENT_KEY>", output)
        self.assertIn("<redacted:GROWTHBOOK_SDK_API_HOST>", output)
        self.assertEqual(
            smoke.FAILURES,
            [
                (
                    "get-feature-flags",
                    "failed with <redacted:GROWTHBOOK_API_TOKEN>, "
                    "<redacted:GROWTHBOOK_SDK_CLIENT_KEY>, and "
                    "<redacted:GROWTHBOOK_SDK_API_HOST>",
                )
            ],
        )

    def test_smoke_run_does_not_retry_when_smoke_retries_is_zero(self):
        smoke = load_smoke_module()
        smoke.FAILURES.clear()
        error = subprocess.CalledProcessError(
            1,
            ["growthbook.py", "get-feature-flags"],
            stderr="503 Service Unavailable",
        )

        with mock.patch.dict(os.environ, {"SMOKE_RETRIES": "0"}, clear=True), \
             mock.patch.object(smoke.subprocess, "run", side_effect=error) as run_mock, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = smoke.run("get-feature-flags", ["get-feature-flags", "--limit", "5"])

        self.assertIsNone(result)
        self.assertEqual(smoke.FAILURES, [("get-feature-flags", "503 Service Unavailable")])
        self.assertEqual(run_mock.call_count, 1)
        self.assertIn("FAIL", stdout.getvalue())
        self.assertNotIn("retry get-feature-flags", stdout.getvalue())

    def test_smoke_retries_invalid_or_negative_values_default_to_zero(self):
        smoke = load_smoke_module()

        with mock.patch.dict(os.environ, {"SMOKE_RETRIES": "bad"}, clear=True):
            self.assertEqual(smoke._smoke_retries(), 0)
        with mock.patch.dict(os.environ, {"SMOKE_RETRIES": "-1"}, clear=True):
            self.assertEqual(smoke._smoke_retries(), 0)

    def test_smoke_runs_eval_feature_when_eval_env_is_configured(self):
        smoke = load_smoke_module()

        run_calls: list[tuple[str, list[str]]] = []

        def fake_run(label: str, args: list[str], *, capture: bool = True):
            run_calls.append((label, args))
            if label == "get-environments":
                return {"environments": [{"id": "production"}]}
            if label == "get-projects":
                return {"projects": [{"id": "prj_1", "name": "Growth"}]}
            if label == "resolve-project-id":
                return {"id": "prj_1", "name": "Growth"}
            if label == "get-feature-flags":
                return {"features": [{"id": "existing-flag"}]}
            if label == "get-experiments":
                return {"experiments": []}
            if label == "get-metrics":
                return {"metrics": [], "factMetrics": []}
            if label == "eval-feature":
                return {"featureId": "existing-flag", "found": True}
            return {}

        with mock.patch.dict(
            os.environ,
            {
                "GROWTHBOOK_API_TOKEN": "secret-token",
                "GROWTHBOOK_SDK_API_HOST": "https://cdn.growthbook.example.com",
                "GROWTHBOOK_SDK_CLIENT_KEY": "sdk-abc",
                "SMOKE_EVAL_ATTRIBUTES_JSON": '{"platform":"web"}',
            },
            clear=True,
        ), \
             mock.patch.object(smoke, "run", side_effect=fake_run), \
             mock.patch.object(smoke, "FAILURES", []), \
             mock.patch("sys.stdout", new_callable=io.StringIO):
            smoke.main()

        eval_feature_args = next(args for label, args in run_calls if label == "eval-feature")
        self.assertEqual(
            eval_feature_args,
            ["eval-feature", "--feature-id", "existing-flag", "--attributes-json", '{"platform":"web"}'],
        )

    def test_smoke_eval_feature_failure_causes_smoke_failure(self):
        smoke_spec = importlib.util.spec_from_file_location("growthbook_smoke_under_test", SMOKE_PATH)
        smoke = importlib.util.module_from_spec(smoke_spec)
        assert smoke_spec.loader is not None
        smoke_spec.loader.exec_module(smoke)

        failures: list[tuple[str, str]] = []

        def fake_run(label: str, args: list[str], *, capture: bool = True):
            if label == "get-environments":
                return {"environments": [{"id": "production"}]}
            if label == "get-projects":
                return {"projects": [{"id": "prj_1", "name": "Growth"}]}
            if label == "resolve-project-id":
                return {"id": "prj_1", "name": "Growth"}
            if label == "get-feature-flags":
                return {"features": [{"id": "existing-flag"}]}
            if label == "eval-feature":
                smoke.FAILURES.append(("eval-feature", "boom"))
                return None
            if label == "get-experiments":
                return {"experiments": []}
            if label == "get-metrics":
                return {"metrics": [], "factMetrics": []}
            return {}

        with mock.patch.dict(
            os.environ,
            {
                "GROWTHBOOK_API_TOKEN": "secret-token",
                "GROWTHBOOK_SDK_API_HOST": "https://cdn.growthbook.example.com",
                "GROWTHBOOK_SDK_CLIENT_KEY": "sdk-abc",
            },
            clear=True,
        ), \
             mock.patch.object(smoke, "run", side_effect=fake_run), \
             mock.patch.object(smoke, "FAILURES", failures), \
             mock.patch("sys.stdout", new_callable=io.StringIO), \
             self.assertRaises(SystemExit) as exc:
            smoke.main()

        self.assertEqual(exc.exception.code, 1)
        self.assertIn(("eval-feature", "boom"), failures)

    def test_smoke_requires_sdk_eval_env(self):
        smoke_spec = importlib.util.spec_from_file_location("growthbook_smoke_under_test", SMOKE_PATH)
        smoke = importlib.util.module_from_spec(smoke_spec)
        assert smoke_spec.loader is not None
        smoke_spec.loader.exec_module(smoke)

        with mock.patch.dict(os.environ, {"GROWTHBOOK_API_TOKEN": "secret-token"}, clear=True), \
             mock.patch("sys.stderr", new_callable=io.StringIO) as stderr, \
             self.assertRaises(SystemExit) as exc:
            smoke.main()

        self.assertEqual(exc.exception.code, 1)
        self.assertIn("GROWTHBOOK_SDK_API_HOST", stderr.getvalue())
        self.assertIn("GROWTHBOOK_SDK_CLIENT_KEY", stderr.getvalue())

    def test_smoke_write_mode_adds_execute_flag(self):
        smoke_spec = importlib.util.spec_from_file_location("growthbook_smoke_under_test", SMOKE_PATH)
        smoke = importlib.util.module_from_spec(smoke_spec)
        assert smoke_spec.loader is not None
        smoke_spec.loader.exec_module(smoke)

        run_calls: list[tuple[str, list[str]]] = []

        def fake_run(label: str, args: list[str], *, capture: bool = True):
            run_calls.append((label, args))
            if label == "get-environments":
                return {"environments": [{"id": "production"}]}
            if label == "get-projects":
                return {"projects": [{"id": "prj_1", "name": "Growth"}]}
            if label == "resolve-project-id":
                return {"id": "prj_1", "name": "Growth"}
            if label == "get-feature-flags":
                return {"features": [{"id": "existing-flag"}]}
            if label == "get-experiments":
                return {"experiments": []}
            if label == "get-metrics":
                return {"metrics": [], "factMetrics": []}
            return {}

        with mock.patch.dict(
            os.environ,
            {
                "GROWTHBOOK_API_TOKEN": "secret-token",
                "GROWTHBOOK_SDK_API_HOST": "https://cdn.growthbook.example.com",
                "GROWTHBOOK_SDK_CLIENT_KEY": "sdk-abc",
                "SMOKE_WRITE": "1",
            },
            clear=True,
        ), \
             mock.patch.object(smoke, "run", side_effect=fake_run), \
             mock.patch.object(smoke, "FAILURES", []), \
             mock.patch("sys.stdout", new_callable=io.StringIO):
            smoke.main()

        create_flag_args = next(args for label, args in run_calls if label == "create-feature-flag")
        create_rule_args = next(args for label, args in run_calls if label == "create-force-rule")
        self.assertIn("--execute", create_flag_args)
        self.assertIn("--execute", create_rule_args)


if __name__ == "__main__":
    unittest.main()
