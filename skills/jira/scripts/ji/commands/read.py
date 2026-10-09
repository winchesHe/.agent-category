"""Read a Jira issue with comments, attachments, and optional Intercom context."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from ji.adf import CS_FIELD_MAP, DESCRIPTION_FIELDS, compact_user, extract_adf_text, extract_value
from ji.client import JiraClient
from ji.config import Config
from ji.errors import JiraCliError, UsageError
from ji.formatter import output
from ji.intercom import (
    IntercomForJiraClient,
    build_linked_conversations,
    resolve_runtime_jwt,
)
from ji.parsing import csv_list, iter_strings, normalize_content_type, parse_issue_key

DEFAULT_FIELDS = [
    "summary",
    "status",
    "priority",
    "assignee",
    "reporter",
    "creator",
    "issuetype",
    "project",
    "created",
    "updated",
    "description",
    "attachment",
    "issuelinks",
    "comment",
    *CS_FIELD_MAP.keys(),
    *[field for field in DESCRIPTION_FIELDS.keys() if field != "description"],
]
LINKED_INTERCOM_IDS_FIELD_NAMES = {
    "linked intercom conversation id",
    "linked intercom conversation ids",
}
INTERCOM_APP_FIELD_NAMES = LINKED_INTERCOM_IDS_FIELD_NAMES | {
    "number of linked intercom conversations",
}
FIELD_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "read",
        help="Read a Jira issue, comments, attachments, and CS-linked Intercom conversations",
    )
    parser.add_argument("issue", help="Jira key, Jira URL, or Slack mrkdwn Jira link")
    parser.add_argument("--comment-limit", default="50", help="Comment limit, or 'all' (default: 50)")
    parser.add_argument("--download-images", action="store_true", help="Download image attachments locally")
    parser.add_argument("--image-output-dir", help="Directory for downloaded image attachments")
    parser.add_argument(
        "--include-intercom",
        choices=("auto", "always", "never"),
        default="auto",
        help="Read Intercom linked conversations (default: auto for CS-* issues)",
    )
    parser.add_argument(
        "--fields",
        default=",".join(dict.fromkeys(DEFAULT_FIELDS)),
        help="Comma-separated Jira fields, or *all",
    )
    parser.add_argument("--format", choices=("json", "human", "summary"), default="json")
    parser.set_defaults(_handler=run)


def _comment_limit(raw: str) -> int | None:
    value = str(raw).strip().lower()
    if value == "all":
        return None
    try:
        limit = int(value)
    except ValueError as exc:
        raise UsageError("--comment-limit must be an integer or 'all'") from exc
    if limit < 0:
        raise UsageError("--comment-limit must be >= 0")
    return limit


def _normalize_field_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _append_intercom_app_fields(
    client: JiraClient,
    fields: str,
    enabled: bool,
    warnings: list[str],
) -> str:
    if not enabled or fields.strip() == "*all":
        return fields
    try:
        app_field_ids = [
            str(item.get("id"))
            for item in client.list_fields()
            if _normalize_field_name(item.get("name")) in INTERCOM_APP_FIELD_NAMES
            and item.get("id")
        ]
    except JiraCliError as exc:
        warnings.append(f"intercom_app_fields_unavailable:{exc.message}")
        return fields
    if not app_field_ids:
        return fields
    return ",".join(dict.fromkeys([*csv_list(fields), *app_field_ids]))


def _basic_issue(issue_key: str, base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    fields = payload.get("fields") or {}
    return {
        "key": payload.get("key") or issue_key,
        "id": payload.get("id"),
        "url": f"{base_url}/browse/{payload.get('key') or issue_key}",
        "summary": fields.get("summary"),
        "status": extract_value(fields.get("status")),
        "priority": extract_value(fields.get("priority") or fields.get("customfield_10049")),
        "project": {
            "key": (fields.get("project") or {}).get("key"),
            "id": (fields.get("project") or {}).get("id"),
            "name": (fields.get("project") or {}).get("name"),
        },
        "issue_type": {
            "id": (fields.get("issuetype") or {}).get("id"),
            "name": extract_value(fields.get("issuetype")),
        },
        "assignee": compact_user(fields.get("assignee")),
        "reporter": compact_user(fields.get("reporter")),
        "creator": compact_user(fields.get("creator")),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
    }


def _cs_fields(fields: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_id, name in CS_FIELD_MAP.items():
        value = extract_value(fields.get(field_id))
        if value not in (None, "", []):
            result[name] = value
    components = extract_value(fields.get("components"))
    if components:
        result["components"] = components
    return result


def _descriptions(fields: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field_id, name in DESCRIPTION_FIELDS.items():
        value = extract_value(fields.get(field_id))
        if isinstance(value, str) and value.strip():
            result[name] = value.strip()
    return result


def _requested_fields(fields: dict[str, Any], requested: str) -> dict[str, Any]:
    """Return values explicitly requested through --fields.

    The structured sections above intentionally cover common Jira fields only.
    Keep explicit ad-hoc field reads observable so callers can inspect workflow
    fields such as duedate or project-specific custom fields without bypassing
    the skill entrypoint.
    """
    if requested.strip() == "*all":
        return {}
    result: dict[str, Any] = {}
    for field_id in csv_list(requested):
        value = extract_value(fields.get(field_id))
        if value is not None:
            result[field_id] = value
    return result


def _comments(comments_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for item in comments_payload:
        comments.append(
            {
                "id": item.get("id"),
                "author": compact_user(item.get("author")),
                "created": item.get("created"),
                "updated": item.get("updated"),
                "body_text": extract_adf_text(item.get("body")).strip(),
            }
        )
    return comments


def _attachments(fields: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in fields.get("attachment") or []:
        mime_type = normalize_content_type(item.get("mimeType"))
        result.append(
            {
                "id": item.get("id"),
                "filename": item.get("filename"),
                "mime_type": mime_type,
                "size": item.get("size"),
                "created": item.get("created"),
                "author": compact_user(item.get("author")),
                "content_url": item.get("content"),
                "thumbnail_url": item.get("thumbnail"),
                "is_image": mime_type.startswith("image/"),
                "downloaded": False,
                "local_path": None,
                "error": None,
            }
        )
    return result


def _issue_links(fields: dict[str, Any]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for item in fields.get("issuelinks") or []:
        link_type = item.get("type") or {}
        if item.get("outwardIssue"):
            issue = item["outwardIssue"]
            direction = link_type.get("outward") or "relates to"
        elif item.get("inwardIssue"):
            issue = item["inwardIssue"]
            direction = link_type.get("inward") or "relates to"
        else:
            continue
        issue_fields = issue.get("fields") or {}
        links.append(
            {
                "kind": "issue",
                "direction": direction,
                "key": issue.get("key"),
                "summary": issue_fields.get("summary"),
                "status": extract_value(issue_fields.get("status")),
            }
        )
    return links


def _remote_links(client: JiraClient, issue_key: str, warnings: list[str]) -> list[dict[str, Any]]:
    try:
        remote_payload = client.get_remote_links(issue_key)
    except JiraCliError as exc:
        warnings.append(f"remote_links_unavailable:{exc.message}")
        return []
    links = []
    for item in remote_payload:
        obj = item.get("object") or {}
        links.append(
            {
                "kind": "remote",
                "id": item.get("id"),
                "relationship": item.get("relationship"),
                "title": obj.get("title"),
                "url": obj.get("url"),
            }
        )
    return links


def _download_images(
    client: JiraClient,
    attachments: list[dict[str, Any]],
    output_dir: str | None,
    warnings: list[str],
) -> None:
    target_dir = Path(output_dir).expanduser() if output_dir else None
    for item in attachments:
        if not item.get("is_image"):
            continue
        url = item.get("content_url")
        if not url:
            item["error"] = "missing_content_url"
            warnings.append(f"attachment {item.get('id') or item.get('filename')} missing content url")
            continue
        result = client.download_attachment(url, output_dir=target_dir)
        if result.get("ok"):
            item["downloaded"] = True
            item["local_path"] = result.get("local_path")
            item["mime_type"] = result.get("mime_type") or item.get("mime_type")
            warnings.extend(result.get("warnings") or [])
        else:
            item["error"] = ";".join(result.get("errors") or ["download_failed"])
            warnings.append(f"attachment {item.get('id') or item.get('filename')} download failed: {item['error']}")


def _collect_intercom_texts(
    issue_payload: dict[str, Any],
    comments: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> list[str]:
    texts = list(iter_strings(issue_payload.get("fields")))
    texts.extend(comment.get("body_text") or "" for comment in comments)
    texts.extend(att.get("filename") or "" for att in attachments)
    texts.extend(link.get("url") or "" for link in links)
    texts.extend(link.get("title") or "" for link in links)
    return [text for text in texts if text]


def _ids_from_intercom_field_value(value: Any) -> list[str]:
    extracted = extract_value(value)
    found: list[str] = []
    seen: set[str] = set()

    def add(candidate: Any) -> None:
        text = str(candidate or "").strip()
        if not text:
            return
        for part in re.split(r"[\s,;]+", text):
            part = part.strip()
            if part and FIELD_ID_RE.fullmatch(part) and part not in seen:
                seen.add(part)
                found.append(part)

    if isinstance(extracted, list):
        for item in extracted:
            add(item)
    else:
        add(extracted)
    return found


def _linked_intercom_field_conversations(issue_payload: dict[str, Any]) -> list[dict[str, Any]]:
    fields = issue_payload.get("fields") or {}
    names = issue_payload.get("names") or {}
    conversations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field_id, field_name in names.items():
        if _normalize_field_name(field_name) not in LINKED_INTERCOM_IDS_FIELD_NAMES:
            continue
        for conversation_id in _ids_from_intercom_field_value(fields.get(field_id)):
            if conversation_id in seen:
                continue
            seen.add(conversation_id)
            conversations.append(
                {
                    "id": conversation_id,
                    "url": None,
                    "title": str(field_name),
                    "source": "jira_app_field",
                }
            )
    return conversations


def _merge_linked_conversations(
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in [*first, *second]:
        conversation_id = item.get("id")
        if not conversation_id:
            continue
        existing = by_id.setdefault(str(conversation_id), dict(item))
        for key, value in item.items():
            if existing.get(key) in (None, "") and value not in (None, ""):
                existing[key] = value
    return list(by_id.values())


def _read_intercom(
    *,
    config: Config,
    jira_client: JiraClient,
    issue: dict[str, Any],
    enabled: bool,
    field_conversations: list[dict[str, Any]],
    texts: list[str],
    links: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "linked_conversations": [], "warnings": []}

    linked_conversations = _merge_linked_conversations(
        field_conversations,
        build_linked_conversations(texts=texts, links=links),
    )
    local_warnings: list[str] = []
    if not linked_conversations:
        local_warnings.append("no_intercom_linked_conversations_found")
    else:
        try:
            jwt = resolve_runtime_jwt(
                config,
                issue_key=str(issue.get("key") or ""),
                issue_id=str(issue.get("id") or ""),
                project_key=(issue.get("project") or {}).get("key"),
            )
        except JiraCliError as exc:
            jwt = None
            local_warnings.append(exc.message)
        for item in linked_conversations:
            conversation_id = item.get("id")
            if not conversation_id:
                continue
            item_jwt = jwt
            referrer = None
            if not item_jwt:
                project = issue.get("project") or {}
                issue_type = issue.get("issue_type") or {}
                try:
                    dialog = jira_client.get_intercom_dialog_context(
                        issue_key=str(issue.get("key") or ""),
                        issue_id=str(issue.get("id") or ""),
                        project_key=str(project.get("key") or ""),
                        project_id=str(project.get("id") or ""),
                        issue_type_id=str(issue_type.get("id") or ""),
                        selected_conversation_id=str(conversation_id),
                    )
                    item_jwt = dialog.get("contextJwt")
                    referrer = dialog.get("url")
                    item["dialog_url"] = referrer
                except JiraCliError as exc:
                    local_warnings.append(f"intercom_dialog:{conversation_id}:{exc.message}")
            if not item_jwt:
                local_warnings.append(f"intercom:{conversation_id}:runtime JWT unavailable")
                continue
            try:
                client = IntercomForJiraClient(config, jwt=str(item_jwt), referrer=referrer)
                item["details"] = client.get_conversation(str(conversation_id))
            except JiraCliError as exc:
                local_warnings.append(f"intercom:{conversation_id}:{exc.message}")
    warnings.extend(local_warnings)
    return {
        "enabled": True,
        "linked_conversations": linked_conversations,
        "warnings": local_warnings,
    }


def run(args: argparse.Namespace, config: Config) -> int:
    issue_key = parse_issue_key(args.issue)
    comment_limit = _comment_limit(args.comment_limit)
    client = JiraClient(config)
    warnings: list[str] = []
    intercom_enabled = args.include_intercom == "always" or (
        args.include_intercom == "auto" and issue_key.startswith("CS-")
    )

    issue_fields = _append_intercom_app_fields(client, args.fields, intercom_enabled, warnings)
    issue_payload = client.get_issue(issue_key, fields=issue_fields)
    fields = issue_payload.get("fields") or {}
    comments_payload = client.get_comments(issue_key, comment_limit)
    comments = _comments(comments_payload)
    attachments = _attachments(fields)
    links = _issue_links(fields)
    links.extend(_remote_links(client, issue_key, warnings))

    if args.download_images:
        _download_images(client, attachments, args.image_output_dir, warnings)

    intercom = _read_intercom(
        config=config,
        jira_client=client,
        issue=_basic_issue(issue_key, config.jira_base_url, issue_payload),
        enabled=intercom_enabled,
        field_conversations=_linked_intercom_field_conversations(issue_payload),
        texts=_collect_intercom_texts(issue_payload, comments, attachments, links),
        links=links,
        warnings=warnings,
    )

    result = {
        "schema_version": 1,
        "command": "read",
        "ok": True,
        "input": {
            "issue": args.issue,
            "issue_key": issue_key,
            "download_images": args.download_images,
            "include_intercom": args.include_intercom,
            "fields": issue_fields,
        },
        "issue": _basic_issue(issue_key, config.jira_base_url, issue_payload),
        "requested_fields": _requested_fields(fields, args.fields),
        "cs_fields": _cs_fields(fields),
        "descriptions": _descriptions(fields),
        "comments": comments,
        "attachments": attachments,
        "links": links,
        "intercom": intercom,
        "warnings": list(dict.fromkeys(warnings)),
    }
    output(result, fmt=args.format)
    return 0
