"""Inspect and execute Jira workflow transitions."""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

from ji.client import JiraClient
from ji.config import Config
from ji.errors import EXIT_API_ERROR, UsageError
from ji.formatter import output
from ji.parsing import parse_issue_key


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "transition",
        help="List or execute an available Jira workflow transition",
    )
    parser.add_argument("issue", help="Jira key, Jira URL, or Slack mrkdwn Jira link")
    parser.add_argument(
        "--transition",
        dest="transition_selector",
        help="Transition ID or exact name; omit to list available transitions",
    )
    parser.add_argument(
        "--fields",
        default="{}",
        help="Jira transition-screen fields as a JSON object",
    )
    parser.add_argument(
        "--no-fill-current-required",
        action="store_true",
        help="Do not reuse current issue values for missing required screen fields",
    )
    parser.add_argument(
        "--required-fields",
        default="",
        help="Comma-separated screen field IDs to require in addition to Jira metadata",
    )
    parser.add_argument("--wait-linked-project", help="Wait for a newly linked issue in this project")
    parser.add_argument("--expected-source-assignee", help="Expected source issue assignee accountId")
    parser.add_argument("--expected-linked-assignee", help="Expected linked issue assignee accountId")
    parser.add_argument(
        "--repair-linked-assignee",
        action="store_true",
        help="Set the linked issue assignee when it does not match the explicit expectation",
    )
    parser.add_argument("--wait-seconds", type=float, default=60.0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--execute", action="store_true", help="Actually transition the issue")
    parser.add_argument("--format", choices=("json", "human", "summary"), default="json")
    parser.set_defaults(_handler=run)


def _parse_fields(raw_fields: str) -> dict[str, Any]:
    try:
        fields = json.loads(raw_fields)
    except json.JSONDecodeError as exc:
        raise UsageError("--fields must be valid JSON") from exc
    if not isinstance(fields, dict):
        raise UsageError("--fields must be a JSON object")
    return fields


def _resolve_transition(
    transitions: list[dict[str, Any]], selector: str
) -> dict[str, Any]:
    normalized = selector.strip().casefold()
    if not normalized:
        raise UsageError("--transition cannot be empty")

    id_matches = [item for item in transitions if str(item.get("id", "")) == selector.strip()]
    if len(id_matches) == 1:
        return id_matches[0]

    name_matches = [
        item
        for item in transitions
        if isinstance(item.get("name"), str) and item["name"].strip().casefold() == normalized
    ]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        ids = ", ".join(str(item.get("id", "?")) for item in name_matches)
        raise UsageError(f"transition name is ambiguous: {selector!r} (IDs: {ids})")

    available = ", ".join(
        f"{item.get('name', '?')} ({item.get('id', '?')})" for item in transitions
    )
    suffix = f"; available: {available}" if available else "; no transitions are available"
    raise UsageError(f"transition not found: {selector!r}{suffix}")


def _simplify_field(field_id: str, metadata: Any) -> dict[str, Any]:
    raw = metadata if isinstance(metadata, dict) else {}
    schema = raw.get("schema") if isinstance(raw.get("schema"), dict) else {}
    result: dict[str, Any] = {
        "id": field_id,
        "name": raw.get("name") or field_id,
        "required": bool(raw.get("required")),
        "has_default_value": bool(raw.get("hasDefaultValue")),
        "operations": raw.get("operations") or [],
    }
    if schema:
        result["schema"] = {
            key: schema[key]
            for key in ("type", "items", "system", "custom", "customId")
            if key in schema
        }
    allowed_values = raw.get("allowedValues")
    if isinstance(allowed_values, list):
        result["allowed_values"] = allowed_values
    return result


def _simplify_transition(item: dict[str, Any], *, include_fields: bool) -> dict[str, Any]:
    target = item.get("to") if isinstance(item.get("to"), dict) else {}
    result: dict[str, Any] = {
        "id": str(item.get("id", "")),
        "name": item.get("name"),
        "target_status": target.get("name"),
        "available": item.get("isAvailable", True),
        "has_screen": bool(item.get("hasScreen")),
    }
    if include_fields:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        result["fields"] = [
            _simplify_field(field_id, metadata) for field_id, metadata in fields.items()
        ]
    return result


def _validate_fields(
    selected: dict[str, Any], fields: dict[str, Any], extra_required: set[str] | None = None
) -> list[str]:
    metadata = selected.get("fields") if isinstance(selected.get("fields"), dict) else {}
    unknown = sorted(set(fields) - set(metadata))
    if unknown:
        raise UsageError(
            "fields are not present on the selected transition screen: " + ", ".join(unknown)
        )
    required = {
        field_id
        for field_id, raw in metadata.items()
        if isinstance(raw, dict)
        and raw.get("required")
        and not raw.get("hasDefaultValue")
    }
    for field_id in extra_required or set():
        if field_id not in metadata:
            raise UsageError(f"required field is not present on the selected transition screen: {field_id}")
        required.add(field_id)
    return sorted(required - set(fields))


def _linked_issue_keys(issue: dict[str, Any], project: str) -> list[str]:
    fields = issue.get("fields") if isinstance(issue, dict) else {}
    links = fields.get("issuelinks") if isinstance(fields, dict) else []
    prefix = project.strip().upper() + "-"
    found: list[str] = []
    for link in links or []:
        if not isinstance(link, dict):
            continue
        candidate = link.get("outwardIssue") or link.get("inwardIssue") or {}
        key = str(candidate.get("key") or "")
        if key.upper().startswith(prefix) and key not in found:
            found.append(key)
    return found


def _account_id(issue: dict[str, Any]) -> str | None:
    fields = issue.get("fields") if isinstance(issue, dict) else {}
    assignee = fields.get("assignee") if isinstance(fields, dict) else None
    return str(assignee.get("accountId")) if isinstance(assignee, dict) and assignee.get("accountId") else None


def _normalize_current_value(metadata: dict[str, Any], value: Any) -> Any:
    if value is None:
        return None
    schema = metadata.get("schema") if isinstance(metadata.get("schema"), dict) else {}
    value_type = schema.get("type")
    if value_type == "user" and isinstance(value, dict):
        account_id = value.get("accountId")
        return {"accountId": account_id} if account_id else None
    if value_type in {"priority", "option", "status", "resolution"} and isinstance(value, dict):
        object_id = value.get("id")
        return {"id": str(object_id)} if object_id is not None else None
    return value


def _fill_current_required_fields(
    client: JiraClient,
    issue_key: str,
    selected: dict[str, Any],
    fields: dict[str, Any],
    missing: list[str],
) -> list[str]:
    if not missing:
        return []
    issue = client.get_issue(issue_key, fields=",".join(missing))
    current_fields = issue.get("fields") if isinstance(issue, dict) else {}
    if not isinstance(current_fields, dict):
        current_fields = {}
    metadata = selected.get("fields") if isinstance(selected.get("fields"), dict) else {}
    reused: list[str] = []
    for field_id in missing:
        raw_metadata = metadata.get(field_id)
        if not isinstance(raw_metadata, dict):
            continue
        value = _normalize_current_value(raw_metadata, current_fields.get(field_id))
        if value is not None:
            fields[field_id] = value
            reused.append(field_id)
    return reused


def run(args: argparse.Namespace, config: Config) -> int:
    issue_key = parse_issue_key(args.issue)
    client = JiraClient(config)
    transitions = client.get_transitions(issue_key)
    selector = getattr(args, "transition_selector", None)

    if selector is None:
        if args.execute:
            raise UsageError("--execute requires --transition")
        result = {
            "schema_version": 1,
            "command": "transition",
            "ok": True,
            "dry_run": True,
            "mode": "list",
            "issue_key": issue_key,
            "transitions": [
                _simplify_transition(item, include_fields=True) for item in transitions
            ],
        }
        output(result, fmt=args.format)
        return 0

    fields = _parse_fields(args.fields)
    selected = _resolve_transition(transitions, selector)
    extra_required = {item.strip() for item in str(getattr(args, "required_fields", "")).split(",") if item.strip()}
    missing_required_fields = _validate_fields(selected, fields, extra_required)
    reused_current_fields: list[str] = []
    if missing_required_fields and not getattr(args, "no_fill_current_required", False):
        reused_current_fields = _fill_current_required_fields(
            client,
            issue_key,
            selected,
            fields,
            missing_required_fields,
        )
        missing_required_fields = _validate_fields(selected, fields, extra_required)
    payload: dict[str, Any] = {"transition": {"id": str(selected.get("id"))}}
    if fields:
        payload["fields"] = fields
    result = {
        "schema_version": 1,
        "command": "transition",
        "ok": True,
        "dry_run": not args.execute,
        "issue_key": issue_key,
        "selected_transition": _simplify_transition(selected, include_fields=True),
        "reused_current_fields": reused_current_fields,
        "missing_required_fields": missing_required_fields,
        "payload": payload,
        "postconditions": {
            "wait_linked_project": getattr(args, "wait_linked_project", None),
            "expected_source_assignee": getattr(args, "expected_source_assignee", None),
            "expected_linked_assignee": getattr(args, "expected_linked_assignee", None),
            "repair_linked_assignee": bool(getattr(args, "repair_linked_assignee", False)),
        },
    }
    if args.execute:
        if missing_required_fields:
            raise UsageError(
                "missing required transition fields: " + ", ".join(missing_required_fields)
            )
        wait_project = str(getattr(args, "wait_linked_project", "") or "").strip().upper()
        expected_source = getattr(args, "expected_source_assignee", None)
        expected_linked = getattr(args, "expected_linked_assignee", None)
        if getattr(args, "repair_linked_assignee", False) and not expected_linked:
            raise UsageError("--repair-linked-assignee requires --expected-linked-assignee")
        before_issue = None
        before_linked: set[str] = set()
        if wait_project or expected_source:
            before_issue = client.get_issue(issue_key, fields="status,assignee,issuelinks")
            if wait_project:
                before_linked = set(_linked_issue_keys(before_issue, wait_project))

        result["response"] = client.transition_issue(
            issue_key,
            transition_id=str(selected.get("id")),
            fields=fields,
        )
        issue_after = client.get_issue(issue_key, fields="status,assignee,issuelinks")
        raw_status = (
            issue_after.get("fields", {}).get("status")
            if isinstance(issue_after, dict) and isinstance(issue_after.get("fields"), dict)
            else None
        )
        actual_status = raw_status.get("name") if isinstance(raw_status, dict) else raw_status
        expected_status = (
            selected.get("to", {}).get("name")
            if isinstance(selected.get("to"), dict)
            else None
        )
        result["verification"] = {
            "actual_status": actual_status,
            "expected_status": expected_status,
            "matched": bool(
                actual_status
                and expected_status
                and str(actual_status).strip().casefold()
                == str(expected_status).strip().casefold()
            ),
        }
        source_assignee = _account_id(issue_after)
        result["verification"]["source_assignee"] = {
            "actual": source_assignee,
            "expected": expected_source,
            "matched": expected_source is None or source_assignee == expected_source,
        }

        linked_issue = None
        linked_key = None
        linked_candidates: list[str] = []
        if wait_project:
            deadline = time.monotonic() + max(0.0, float(getattr(args, "wait_seconds", 60.0)))
            while True:
                current = client.get_issue(issue_key, fields="status,assignee,issuelinks")
                new_keys = [key for key in _linked_issue_keys(current, wait_project) if key not in before_linked]
                linked_candidates = new_keys
                if len(new_keys) == 1:
                    linked_key = new_keys[0]
                    linked_issue = client.get_issue(
                        linked_key,
                        fields="summary,status,assignee,reporter,creator,project,issuetype,description,duedate,customfield_12242,customfield_10089,issuelinks",
                    )
                    break
                if len(new_keys) > 1:
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(max(0.1, float(getattr(args, "poll_seconds", 5.0))))

        linked_assignee = _account_id(linked_issue or {})
        repaired = False
        if (
            linked_key
            and expected_linked
            and linked_assignee != expected_linked
            and getattr(args, "repair_linked_assignee", False)
        ):
            client.update_issue(linked_key, {"assignee": {"accountId": expected_linked}})
            linked_issue = client.get_issue(linked_key, fields="summary,status,assignee,project,issuelinks")
            linked_assignee = _account_id(linked_issue)
            repaired = True
        result["verification"]["linked_issue"] = {
            "key": linked_key,
            "candidates": linked_candidates,
            "project": wait_project or None,
            "found": not wait_project or linked_key is not None,
            "assignee": {
                "actual": linked_assignee,
                "expected": expected_linked,
                "matched": expected_linked is None or linked_assignee == expected_linked,
                "repaired": repaired,
            },
        }
        matched = (
            result["verification"]["matched"]
            and result["verification"]["source_assignee"]["matched"]
            and result["verification"]["linked_issue"]["found"]
            and result["verification"]["linked_issue"]["assignee"]["matched"]
        )
        result["verification"]["all_matched"] = matched
        result["ok"] = matched
    output(result, fmt=args.format)
    return 0 if result.get("ok") else EXIT_API_ERROR
