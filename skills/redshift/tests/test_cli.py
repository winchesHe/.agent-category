from __future__ import annotations

import io
import json
import os

from scripts.rs.cli import main
from scripts.rs.errors import SkillError
from scripts.rs.models import CommandResult, InvocationState


def invoke(argv: list[str], dispatcher=None, environ=None):
    stdout = io.StringIO()
    stderr = io.StringIO()
    seen: list[object] = []

    def default_dispatch(args, state: InvocationState):
        seen.append(args)
        return CommandResult(data={"accepted": True}, meta={})

    code = main(
        argv,
        dispatcher=dispatcher or default_dispatch,
        stdout=stdout,
        stderr=stderr,
        environ={} if environ is None else environ,
        install_signal_handlers=False,
    )
    return code, json.loads(stdout.getvalue()), stderr.getvalue(), seen


def test_doctor_debug_keeps_connection_diagnostics_off_public_output():
    def dispatch(_args, _state):
        return CommandResult(
            data={"skillAvailable": False},
            diagnostics={
                "connectionStage": "connect",
                "driverErrorType": "OperationalError",
                "connectTimedOut": True,
                "passwordRejected": False,
                "rawMessage": "private-host private-password",
            },
        )

    code, payload, stderr, _ = invoke(["doctor", "--connect", "--debug"], dispatch)
    assert code == 0
    assert payload["data"] == {"skillAvailable": False}
    diagnostic = json.loads(stderr)
    assert diagnostic["connectionStage"] == "connect"
    assert diagnostic["connectTimedOut"] is True
    assert diagnostic["passwordRejected"] is False
    assert "private-host" not in stderr
    assert "private-password" not in stderr
    assert "diagnostics" not in payload
    _, _, ordinary_stderr, _ = invoke(["doctor", "--connect"], dispatch)
    assert ordinary_stderr == ""


def test_connection_failure_debug_preserves_safe_diagnostics() -> None:
    for command in ("query", "explain"):
        for sqlstate in ("28P01", "private-invalid-state"):
            safe = {
                "connectionStage": "connect",
                "driverErrorType": "OperationalError",
                "connectTimedOut": True,
                "passwordRejected": False,
                "tlsVerificationFailed": False,
            }

            def dispatch(_args, _state):
                raise SkillError(
                    category="connection", code="unavailable", retry_class="transient",
                    diagnostics={**safe, "sqlState": sqlstate,
                                 "rawMessage": "private-host private-password"},
                )

            argv = [command, "--sql", "SELECT 1"]
            code, payload, stderr, _ = invoke([*argv, "--debug"], dispatch)
            assert code != 0
            assert payload["error"]["code"] == "unavailable"
            diagnostic = json.loads(stderr)
            for key, value in safe.items():
                assert diagnostic[key] == value
            if sqlstate == "28P01":
                assert diagnostic["sqlState"] == sqlstate
            else:
                assert "sqlState" not in diagnostic
            for private in ("private-host", "private-password", "private-invalid-state"):
                assert private not in stderr
            assert "rawMessage" not in diagnostic
            for key in (*safe, "sqlState", "rawMessage"):
                assert key not in json.dumps(payload)
            plain_code, plain_payload, plain_stderr, _ = invoke(argv, dispatch)
            assert plain_code == code
            assert plain_payload == payload
            assert plain_stderr == ""


def test_missing_command_has_null_attribution_and_exit_two() -> None:
    code, payload, stderr, seen = invoke([])
    assert code == 2
    assert payload == {
        "schemaVersion": 1,
        "ok": False,
        "command": None,
        "error": {
            "category": "usage",
            "code": "missing_command",
            "retryClass": "after_change",
        },
    }
    assert stderr == ""
    assert seen == []


def test_unknown_command_has_stable_suggestion() -> None:
    code, payload, _, seen = invoke(["qurey"])
    assert code == 2
    assert payload["command"] is None
    assert payload["error"] == {
        "category": "usage",
        "code": "unknown_command",
        "retryClass": "after_change",
        "details": {"suggestions": ["query"]},
    }
    assert seen == []

def test_recognized_query_keeps_command_on_parser_error() -> None:
    code, payload, _, seen = invoke(["query", "--database", "dbt_dw"])
    assert code == 2
    assert payload["command"] == "query"
    assert payload["error"]["category"] == "usage"
    assert payload["error"]["code"] == "missing_argument"
    assert seen == []


def test_unknown_recipe_keeps_recipe_attribution() -> None:
    code, payload, _, seen = invoke(["recipe", "made-up"])
    assert code == 2
    assert payload["command"] == "recipe"
    assert payload["error"]["code"] == "invalid_value"
    assert seen == []


def test_each_maintained_recipe_requires_only_its_own_identifier() -> None:
    valid = (
        ["recipe", "email-to-company", "--email", "person@example.invalid"],
        ["recipe", "appointment-timeline", "--appointment-id", "1"],
        ["recipe", "refund-origin", "--refund-id", "1"],
        ["recipe", "membership-entitlement", "--membership-id", "1"],
        ["recipe", "membership-entitlement", "--subscription-id", "1"],
    )
    for arguments in valid:
        code, payload, _, seen = invoke(arguments)
        assert code == 0
        assert payload["ok"] is True
        assert len(seen) == 1

    invalid = (
        ["recipe", "appointment-timeline"],
        ["recipe", "refund-origin"],
        ["recipe", "membership-entitlement"],
        [
            "recipe",
            "membership-entitlement",
            "--membership-id",
            "1",
            "--subscription-id",
            "2",
        ],
        ["recipe", "appointment-timeline", "--appointment-id", "0"],
        ["recipe", "refund-origin", "--email", "person@example.invalid"],
    )
    for arguments in invalid:
        code, payload, _, seen = invoke(arguments)
        assert code == 2
        assert payload["ok"] is False
        assert seen == []


def test_leaf_database_at_root_is_option_scope_error() -> None:
    code, payload, _, seen = invoke(
        ["--database", "dbt_dw", "query", "--sql", "SELECT 1"]
    )
    assert code == 2
    assert payload["command"] is None
    assert payload["error"]["code"] == "option_scope"
    assert payload["error"]["details"]["option"] == "--database"
    assert seen == []


def test_query_leaf_database_is_accepted_without_mutating_environment() -> None:
    env = {"UNCHANGED_SENTINEL": "present"}
    before = dict(env)
    code, payload, _, seen = invoke(
        ["query", "--database", "dbt_dw", "--sql", "SELECT 1"], environ=env
    )
    assert code == 0
    assert payload["ok"] is True
    assert seen[0].database == "dbt_dw"
    assert env == before


def test_connection_is_a_live_leaf_option_and_recipe_list_stays_offline() -> None:
    code, payload, _, seen = invoke(
        ["query", "--connection", "analytics-api", "--sql", "SELECT 1"]
    )
    assert code == 0
    assert payload["ok"] is True
    assert seen[0].connection == "analytics-api"

    code, payload, _, seen = invoke(
        ["recipe", "list", "--connection", "analytics-api"]
    )
    assert code == 2
    assert payload["error"]["code"] == "invalid_combination"
    assert seen == []


def test_schemas_command_accepts_database_and_live_metadata_options() -> None:
    code, payload, _, seen = invoke(
        [
            "schemas",
            '"Mixed Database"',
            "--connection",
            "analytics-api",
            "--include-system",
            "--limit",
            "25",
        ]
    )

    assert code == 0
    assert payload["ok"] is True
    assert seen[0].command == "schemas"
    assert seen[0].database == '"Mixed Database"'
    assert seen[0].connection == "analytics-api"
    assert seen[0].include_system is True
    assert seen[0].limit == 25


def test_relations_command_accepts_database_schema_and_relation_kind() -> None:
    code, payload, _, seen = invoke(
        [
            "relations",
            '"Mixed Database"."Sales Schema"',
            "--connection",
            "analytics-api",
            "--kind",
            "view",
            "--limit",
            "50",
        ]
    )

    assert code == 0
    assert payload["ok"] is True
    assert seen[0].command == "relations"
    assert seen[0].target == '"Mixed Database"."Sales Schema"'
    assert seen[0].kind == "view"
    assert seen[0].limit == 50


def test_live_metadata_limit_is_positive_and_bounded() -> None:
    for arguments in (
        ["schemas", "db", "--limit", "0"],
        ["relations", "db.public", "--limit", "10001"],
    ):
        code, payload, _, seen = invoke(arguments)
        assert code == 2
        assert payload["error"]["code"] == "invalid_value"
        assert seen == []


def test_live_identifier_inputs_fail_before_config_and_never_echo_control_text() -> None:
    unsafe = "db\noperator-secret"
    cases = (
        ["schemas", unsafe],
        ["relations", f"{unsafe}.public"],
        ["query", "--database", unsafe, "--sql", "SELECT 1"],
        ["explain", "--database", unsafe, "--sql", "SELECT 1"],
        ["query", "--connection", unsafe, "--sql", "SELECT 1"],
        ["schemas", "db", "--connection", "x" * 65],
    )

    for arguments in cases:
        code, payload, _, seen = invoke(arguments)
        rendered = json.dumps(payload)
        assert code == 2
        assert payload["error"]["code"] == "invalid_value"
        assert "operator-secret" not in rendered
        assert "x" * 65 not in rendered
        assert seen == []


def test_offline_commands_do_not_load_an_invalid_dotenv(monkeypatch) -> None:
    monkeypatch.setenv("RS_DOTENV", "relative-and-invalid.env")

    for arguments in (["search", "payment"], ["recipe", "list"]):
        stdout = io.StringIO()
        seen = []

        def dispatch(args, _state):
            seen.append(args)
            return CommandResult(data={"offline": True})

        code = main(
            arguments,
            dispatcher=dispatch,
            stdout=stdout,
            stderr=io.StringIO(),
            environ=None,
            install_signal_handlers=False,
        )

        assert code == 0
        assert json.loads(stdout.getvalue())["data"] == {"offline": True}
        assert len(seen) == 1

    stdout = io.StringIO()
    code = main(
        ["query", "--sql", "SELECT 1"],
        dispatcher=lambda *_args: CommandResult(data={"unexpected": True}),
        stdout=stdout,
        stderr=io.StringIO(),
        environ=None,
        install_signal_handlers=False,
    )
    assert code == 3
    assert json.loads(stdout.getvalue())["error"]["code"] == "invalid"


def test_doctor_connection_inventory_is_explicit_and_static() -> None:
    code, payload, _, seen = invoke(["doctor", "--list-connections"])

    assert code == 0
    assert payload["ok"] is True
    assert seen[0].list_connections is True
    assert seen[0].connect is False

    code, payload, _, seen = invoke(
        ["doctor", "--list-connections", "--connect"]
    )
    assert code == 2
    assert payload["error"] == {
        "category": "usage",
        "code": "invalid_combination",
        "retryClass": "after_change",
        "details": {"arguments": ["--list-connections", "--connect"]},
    }
    assert seen == []

    code, payload, _, seen = invoke(
        ["doctor", "--list-connections", "--connection", "selected"]
    )
    assert code == 2
    assert payload["error"]["code"] == "invalid_combination"
    assert payload["error"]["details"] == {
        "arguments": ["--list-connections", "--connection"]
    }
    assert seen == []


def test_artifact_output_pairing_is_validated_before_dispatch() -> None:
    code, payload, _, seen = invoke(["query", "--sql", "SELECT 1", "--format", "csv"])
    assert code == 2
    assert payload["error"]["code"] == "missing_argument"
    assert seen == []

    code, payload, _, seen = invoke(
        ["query", "--sql", "SELECT 1", "--format", "json", "--output", "x.json"]
    )
    assert code == 2
    assert payload["error"]["code"] == "invalid_combination"
    assert seen == []


def test_artifact_output_directory_is_required_before_dispatch() -> None:
    code, payload, _, seen = invoke(
        [
            "query",
            "--sql",
            "SELECT 1",
            "--format",
            "ndjson",
            "--output",
            "results.ndjson",
        ],
        environ={},
    )
    assert code == 3
    assert payload["error"] == {
        "category": "config",
        "code": "missing",
        "retryClass": "after_change",
        "details": {"key": "REDSHIFT_OUTPUT_DIR"},
    }
    assert seen == []


def test_json_query_does_not_require_output_directory() -> None:
    code, payload, _, seen = invoke(["query", "--sql", "SELECT 1"], environ={})
    assert code == 0
    assert payload["ok"] is True
    assert len(seen) == 1


def test_inline_json_query_has_a_serialized_byte_limit() -> None:
    def oversized(_args, _state):
        return CommandResult(data={"records": [{"wide": "x" * 70_000}]})

    code, payload, _, _ = invoke(
        ["query", "--sql", "SELECT 1"], dispatcher=oversized
    )

    assert code == 8
    assert payload == {
        "schemaVersion": 1,
        "ok": False,
        "command": "query",
        "error": {
            "category": "output",
            "code": "inline_size_limit_exceeded",
            "retryClass": "after_change",
            "suggestion": "use_artifact",
        },
    }


def test_inline_json_limit_does_not_apply_to_artifact_result_envelopes(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)

    def wide_artifact_result(_args, _state):
        return CommandResult(data={"outputRef": "wide.ndjson", "note": "x" * 70_000})

    code, payload, _, _ = invoke(
        [
            "query",
            "--sql",
            "SELECT 1",
            "--format",
            "ndjson",
            "--output",
            "wide.ndjson",
        ],
        dispatcher=wide_artifact_result,
        environ={"REDSHIFT_OUTPUT_DIR": str(tmp_path)},
    )

    assert code == 0
    assert payload["ok"] is True
    assert len(payload["data"]["note"]) == 70_000


def test_connection_and_capability_errors_have_stable_agent_actions() -> None:
    cases = (
        ("config", "connection_not_found", "after_change", "list_connections"),
        (
            "connection",
            "aws_credentials_unavailable",
            "after_change",
            "configure_aws_credentials",
        ),
        (
            "connection",
            "auth_interaction_required",
            "after_change",
            "refresh_aws_auth",
        ),
        (
            "connection",
            "permission_denied",
            "after_change",
            "request_platform_access",
        ),
        (
            "query",
            "permission_denied",
            "never",
            "request_data_access",
        ),
        (
            "metadata",
            "permission_denied",
            "never",
            "request_data_access",
        ),
        (
            "capability",
            "parameter_shape_unavailable",
            "after_change",
            "simplify_parameters",
        ),
        (
            "capability",
            "cross_database_read_unavailable",
            "never",
            "use_single_database_or_recipe",
        ),
    )

    for category, error_code, retry_class, suggestion in cases:
        def fail(_args, _state):
            raise SkillError(category, error_code, retry_class)

        code, payload, _, _ = invoke(
            ["query", "--sql", "SELECT 1"], dispatcher=fail
        )

        assert code != 0
        assert payload["error"]["suggestion"] == suggestion


def test_query_limit_has_format_specific_bounds() -> None:
    code, payload, _, seen = invoke(["query", "--sql", "SELECT 1", "--limit", "201"])
    assert code == 7
    assert payload["error"]["code"] == "limit_out_of_range"
    assert seen == []


def test_explicit_json_format_is_accepted_on_json_only_leaf() -> None:
    code, payload, _, seen = invoke(["doctor", "--format", "json"])
    assert code == 0
    assert payload["command"] == "doctor"
    assert len(seen) == 1


def test_search_layer_accepts_a_valid_list_and_rejects_unknown_values() -> None:
    code, payload, _, seen = invoke(["search", "payment", "--layer", "ads,dws"])
    assert code == 0
    assert payload["ok"] is True
    assert seen[0].layer == "ads,dws"

    code, payload, _, seen = invoke(["search", "payment", "--layer", "ads,silver"])
    assert code == 2
    assert payload["command"] == "search"
    assert payload["error"] == {
        "category": "usage",
        "code": "invalid_value",
        "retryClass": "after_change",
        "details": {"argument": "--layer"},
    }
    assert seen == []
