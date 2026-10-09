"""Read Intercom for Jira linked conversation details."""
from __future__ import annotations

import argparse
from typing import Any

from ji.client import JiraClient
from ji.config import Config
from ji.errors import JiraCliError, UsageError
from ji.formatter import output
from ji.intercom import IntercomForJiraClient, resolve_runtime_jwt
from ji.parsing import parse_issue_key
from . import read as read_command


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "intercom",
        help="Read Intercom for Jira linked conversation details by Jira issue or conversation id",
    )
    parser.add_argument("--issue", help="Jira key, Jira URL, or Slack mrkdwn Jira link")
    parser.add_argument(
        "--conversation-id",
        action="append",
        default=[],
        help="Intercom conversation id; repeat for multiple conversations",
    )
    parser.add_argument("--comment-limit", default="50", help="Comment limit for issue discovery, or 'all'")
    parser.add_argument(
        "--fields",
        default=",".join(dict.fromkeys(read_command.DEFAULT_FIELDS)),
        help="Comma-separated Jira fields for issue discovery, or *all",
    )
    parser.add_argument("--format", choices=("json", "human", "summary"), default="json")
    parser.set_defaults(_handler=run)


def _issue_context(
    client: JiraClient,
    issue_key: str,
    fields: str,
    comment_limit_raw: str,
    warnings: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    issue_fields = read_command._append_intercom_app_fields(client, fields, True, warnings)
    issue_payload = client.get_issue(issue_key, fields=issue_fields)
    comments = read_command._comments(
        client.get_comments(issue_key, read_command._comment_limit(comment_limit_raw))
    )
    fields_payload = issue_payload.get("fields") or {}
    attachments = read_command._attachments(fields_payload)
    links = read_command._issue_links(fields_payload)
    links.extend(read_command._remote_links(client, issue_key, warnings))
    linked = read_command._merge_linked_conversations(
        read_command._linked_intercom_field_conversations(issue_payload),
        read_command.build_linked_conversations(
            texts=read_command._collect_intercom_texts(issue_payload, comments, attachments, links),
            links=links,
        ),
    )
    return issue_payload, linked, issue_fields


def _seed_conversations(conversation_ids: list[str]) -> list[dict[str, Any]]:
    result = []
    seen: set[str] = set()
    for conversation_id in conversation_ids:
        value = str(conversation_id or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(
            {
                "id": value,
                "url": None,
                "title": "Explicit conversation id",
                "source": "argument",
            }
        )
    return result


def _fetch_details(
    *,
    config: Config,
    jira_client: JiraClient,
    issue: dict[str, Any] | None,
    conversations: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    try:
        jwt = resolve_runtime_jwt(
            config,
            issue_key=str((issue or {}).get("key") or ""),
            issue_id=str((issue or {}).get("id") or ""),
            project_key=((issue or {}).get("project") or {}).get("key"),
        )
    except JiraCliError as exc:
        jwt = None
        warnings.append(exc.message)

    for item in conversations:
        conversation_id = item.get("id")
        if not conversation_id:
            continue
        item_jwt = jwt
        referrer = None
        if not item_jwt and issue:
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
                warnings.append(f"intercom_dialog:{conversation_id}:{exc.message}")
        if not item_jwt:
            warnings.append(f"intercom:{conversation_id}:runtime JWT unavailable")
            continue
        try:
            client = IntercomForJiraClient(config, jwt=str(item_jwt), referrer=referrer)
            item["details"] = client.get_conversation(str(conversation_id))
        except JiraCliError as exc:
            warnings.append(f"intercom:{conversation_id}:{exc.message}")


def run(args: argparse.Namespace, config: Config) -> int:
    if not args.issue and not args.conversation_id:
        raise UsageError("intercom requires --issue and/or --conversation-id")

    jira_client = JiraClient(config)
    warnings: list[str] = []
    issue_payload: dict[str, Any] | None = None
    issue: dict[str, Any] | None = None
    issue_fields = None
    conversations = _seed_conversations(args.conversation_id)

    if args.issue:
        issue_key = parse_issue_key(args.issue)
        issue_payload, discovered, issue_fields = _issue_context(
            jira_client,
            issue_key,
            args.fields,
            args.comment_limit,
            warnings,
        )
        issue = read_command._basic_issue(issue_key, config.jira_base_url, issue_payload)
        conversations = read_command._merge_linked_conversations(discovered, conversations)

    if not conversations:
        warnings.append("no_intercom_linked_conversations_found")
    else:
        _fetch_details(
            config=config,
            jira_client=jira_client,
            issue=issue,
            conversations=conversations,
            warnings=warnings,
        )

    result = {
        "schema_version": 1,
        "command": "intercom",
        "ok": True,
        "input": {
            "issue": args.issue,
            "conversation_ids": args.conversation_id,
            "fields": issue_fields or args.fields,
        },
        "issue": issue,
        "linked_conversations": conversations,
        "warnings": list(dict.fromkeys(warnings)),
    }
    output(result, fmt=args.format)
    return 0
