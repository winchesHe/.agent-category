"""Create Jira issues through Jira API or automation manual invocation."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from ji.adf_input import (
    MARKDOWN_PROFILE,
    MarkdownParseResult,
    adf_semantically_equal,
    ensure_no_markdown_residual,
    markdown_to_adf_v1,
    parse_adf_json,
    validate_adf_document,
)
from ji.client import JiraClient, build_api_create_fields
from ji.config import Config
from ji.errors import UsageError, ValidationError
from ji.formatter import output
from ji.parsing import csv_list, parse_issue_key

_AUTOMATION_RULE_UUID_RE = re.compile(
    r"/automation/internal-api/jira/(?P<workspace>[0-9a-fA-F-]{36})/",
)


def register(subparsers) -> None:
    parser = subparsers.add_parser("create", help="Create a Jira issue; dry-run unless --execute is set")
    parser.add_argument("--mode", choices=("automation", "api"), default="automation")
    parser.add_argument("--project", required=True, help="Jira project key")
    parser.add_argument("--issue-type", required=True, help="Jira issue type")
    parser.add_argument("--summary", required=True, help="Issue summary")
    description = parser.add_mutually_exclusive_group()
    description.add_argument("--description", default="", help="Issue description in Markdown")
    description.add_argument("--description-file", help="Path to Markdown description, or '-' for stdin")
    description.add_argument(
        "--description-adf-file",
        help="API mode only: path to a complete ADF JSON document, or '-' for stdin",
    )
    parser.add_argument("--components", help="Comma-separated component names")
    parser.add_argument("--labels", help="Comma-separated labels")
    parser.add_argument("--assignee", help="Assignee identifier for automation payload")
    parser.add_argument("--parent", help="Parent issue key")
    parser.add_argument("--additional-fields", help="JSON object merged into Jira fields")
    parser.add_argument("--automation-object", help="JSON object deep-merged into automation payload")
    parser.add_argument(
        "--automation-rule",
        help=(
            "Required for --mode automation: full Jira Automation manual-invocation URL "
            "(or path under JIRA_BASE_URL). Grab it from a real fetch capture in the Jira UI; "
            "there is intentionally no default — rule UUIDs are not stable. Skipped only when "
            "--automation-body-file fully supplies the request body."
        ),
    )
    parser.add_argument(
        "--workspace-uuid",
        help=(
            "Override the workspace (site) UUID used to build the trigger object ARI. "
            "Defaults to the UUID parsed from --automation-rule; only needed when the URL "
            "is non-standard or unavailable."
        ),
    )
    parser.add_argument(
        "--automation-body-file",
        help=(
            "Path to a JSON file (or '-' for stdin) that fully overrides the automation request body; "
            "when set, summary / description / parent / userInputs auto-construction is skipped"
        ),
    )
    parser.add_argument(
        "--objects-issue-id",
        help="Numeric Jira issue id used to build the trigger object ARI; defaults to looking up --parent",
    )
    parser.add_argument("--execute", action="store_true", help="Actually create the issue")
    parser.add_argument("--format", choices=("json", "human", "summary"), default="json")
    parser.set_defaults(_handler=run)


def _json_object(raw: str | None, flag_name: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsageError(f"{flag_name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise UsageError(f"{flag_name} must be a JSON object")
    return value


def _description(args: argparse.Namespace) -> str:
    if args.description_file is None:
        return args.description or ""
    if args.description_file == "-":
        return sys.stdin.read()
    try:
        return Path(args.description_file).expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValidationError(
            "Markdown Description file could not be read as UTF-8",
            {"reason": "markdown_file_not_readable"},
            error_code="markdown_unsupported",
        ) from exc


def _adf_file(path: str) -> dict[str, Any]:
    try:
        raw = (
            sys.stdin.read()
            if path == "-"
            else Path(path).expanduser().read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError) as exc:
        raise ValidationError(
            "ADF Description file could not be read as UTF-8",
            {"reason": "adf_file_not_readable"},
            error_code="adf_invalid",
        ) from exc
    return parse_adf_json(raw)


def _description_input(
    args: argparse.Namespace,
    additional_fields: dict[str, Any],
) -> tuple[str, dict[str, Any] | None, str, MarkdownParseResult | None]:
    adf_path = getattr(args, "description_adf_file", None)
    markdown = _description(args)
    legacy_adf_present = "description" in additional_fields

    if adf_path and markdown:
        raise UsageError(
            "Description inputs are mutually exclusive",
            error_code="invalid_usage",
        )
    if adf_path and args.mode != "api":
        raise UsageError(
            "ADF Description input is supported only by API mode",
            error_code="adf_unsupported_transport",
            details={"transport": args.mode},
        )
    if legacy_adf_present and args.mode != "api":
        raise UsageError(
            "ADF Description input is supported only by API mode",
            error_code="adf_unsupported_transport",
            details={"transport": args.mode},
        )
    if legacy_adf_present and (adf_path or markdown):
        raise UsageError(
            "Description inputs are mutually exclusive",
            error_code="invalid_usage",
            details={"conflict": "additional_fields.description"},
        )

    if adf_path:
        return "", _adf_file(adf_path), "adf", None
    if legacy_adf_present:
        document = additional_fields.pop("description")
        return "", validate_adf_document(document), "adf", None
    if not markdown:
        return "", None, "none", None
    if args.mode == "automation":
        return markdown, None, "markdown", None

    parsed = markdown_to_adf_v1(markdown)
    return "", parsed.adf, "markdown", parsed


def _description_metadata(*, mode: str, input_format: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"description_input_format": input_format}
    if input_format == "markdown" and mode == "api":
        metadata["markdown_profile"] = MARKDOWN_PROFILE
    if input_format == "markdown" and mode == "automation":
        metadata["description_transport"] = "paragraph-string"
    return metadata


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _build_object_ari(workspace_uuid: str, issue_id: str) -> str:
    return f"ari:cloud:jira:{workspace_uuid}:issue/{issue_id}"


def _read_automation_body(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text(encoding="utf-8")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsageError(f"--automation-body-file content must be valid JSON: {exc.msg}") from exc
    if not isinstance(body, dict):
        raise UsageError("--automation-body-file content must be a JSON object")
    return body


def _extract_workspace_uuid(rule_url: str) -> str | None:
    match = _AUTOMATION_RULE_UUID_RE.search(rule_url)
    return match.group("workspace") if match else None


def _resolve_workspace_uuid(args: argparse.Namespace) -> str:
    if args.workspace_uuid:
        return args.workspace_uuid.strip()
    parsed = _extract_workspace_uuid(args.automation_rule or "")
    if parsed:
        return parsed
    raise UsageError(
        "Could not derive workspace UUID from --automation-rule; pass --workspace-uuid <uuid> "
        "or use --automation-body-file with a hand-written ARI."
    )


def _resolve_objects_issue_id(
    args: argparse.Namespace,
    *,
    config: Config,
    execute: bool,
) -> str | None:
    if args.objects_issue_id:
        return str(args.objects_issue_id).strip()
    if not args.parent:
        return None
    if not execute:
        # Dry-run keeps offline; emit a placeholder so users can review the payload shape.
        return None
    parent_key = parse_issue_key(args.parent)
    return JiraClient(config).get_issue_numeric_id(parent_key)


def _automation_payload(
    *,
    args: argparse.Namespace,
    description: str,
    automation_object: dict[str, Any],
    config: Config,
    execute: bool,
) -> tuple[dict[str, Any], str | None]:
    """Build the Jira Automation manual-invocation request body.

    Returns ``(payload, resolved_issue_id)``. ``resolved_issue_id`` is ``None`` when
    callers asked for dry-run without ``--objects-issue-id`` and we deferred the lookup.
    """
    if args.automation_body_file:
        return _read_automation_body(args.automation_body_file), None

    workspace_uuid = _resolve_workspace_uuid(args)
    resolved_id = _resolve_objects_issue_id(args, config=config, execute=execute)
    objects: list[str]
    if resolved_id:
        objects = [_build_object_ari(workspace_uuid, resolved_id)]
    elif args.parent:
        objects = [_build_object_ari(workspace_uuid, "<resolved-on-execute>")]
    else:
        objects = []

    user_inputs: dict[str, dict[str, Any]] = {
        "summary": {"inputType": "TEXT", "value": args.summary},
    }
    if description:
        user_inputs["description"] = {"inputType": "PARAGRAPH", "value": description}

    payload: dict[str, Any] = {
        "objects": objects,
        "userInputs": user_inputs,
    }
    if automation_object:
        _deep_merge(payload, automation_object)
    return payload, resolved_id


def run(args: argparse.Namespace, config: Config) -> int:
    components = csv_list(args.components)
    labels = csv_list(args.labels)
    additional_fields = _json_object(args.additional_fields, "--additional-fields")
    description, description_adf, description_input_format, markdown_result = _description_input(
        args,
        additional_fields,
    )
    automation_object = _json_object(args.automation_object, "--automation-object")
    fields = build_api_create_fields(
        project=args.project,
        issue_type=args.issue_type,
        summary=args.summary,
        description=description,
        components=components,
        labels=labels,
        parent=args.parent,
        additional_fields=additional_fields,
        description_adf=description_adf,
    )
    if markdown_result is not None:
        ensure_no_markdown_residual(markdown_result, fields["description"])
    automation_target: str | None = None
    automation_resolved_id: str | None = None
    if args.mode == "automation":
        if not args.automation_rule:
            raise UsageError(
                "--mode automation requires --automation-rule <url>. "
                "Capture the URL from a real Jira UI fetch — rule UUIDs are project- and "
                "instance-specific and intentionally have no built-in default."
            )
        payload, automation_resolved_id = _automation_payload(
            args=args,
            description=description,
            automation_object=automation_object,
            config=config,
            execute=args.execute,
        )
        automation_target = args.automation_rule.strip()
    else:
        payload = {"fields": fields}

    result: dict[str, Any] = {
        "schema_version": 1,
        "command": "create",
        "ok": True,
        "dry_run": not args.execute,
        "mode": args.mode,
        "payload": payload,
        **_description_metadata(
            mode=args.mode,
            input_format=description_input_format,
        ),
    }
    if args.mode == "automation":
        result["automation"] = {
            "target": automation_target,
            "objects_issue_id": automation_resolved_id,
        }
    if args.execute:
        client = JiraClient(config)
        if args.mode == "automation":
            response = client.invoke_automation(payload, target=automation_target or "")
        else:
            response = client.create_issue_api(fields)
        issue_key = response.get("key") if isinstance(response, dict) else None
        result["response"] = response
        if issue_key:
            result["issue"] = {
                "key": issue_key,
                "id": response.get("id"),
                "self": response.get("self"),
                "url": f"{config.jira_base_url}/browse/{issue_key}",
            }
            if args.mode == "api" and fields.get("description") is not None:
                issue = client.get_issue(
                    str(issue_key),
                    fields="description",
                    expand="names",
                )
                actual_description = (issue.get("fields") or {}).get("description")
                matched = adf_semantically_equal(
                    fields["description"],
                    actual_description,
                )
                result["verification"] = {
                    "status": "verified" if matched else "failed",
                    "description_semantically_matched": matched,
                }
                if not matched:
                    raise ValidationError(
                        "Jira issue "
                        f"{issue_key} was created, but Description readback did not preserve "
                        "the submitted ADF semantics; do not retry automatically",
                        {"issue_key": issue_key},
                        error_code="adf_postcondition_failed",
                        operation_state="completed",
                    )
    output(result, fmt=args.format)
    return 0
