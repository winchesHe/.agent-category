"""Update Jira issue fields with a strict patch whitelist."""
from __future__ import annotations

import argparse
import json
import urllib.parse
from typing import Any

from ji.client import JiraClient
from ji.config import Config
from ji.errors import UsageError
from ji.formatter import output
from ji.parsing import parse_issue_key

ALLOWED_PATCH_KEYS = {
    "components",
    "labels",
    "issueCause",
    "causeAndSolution",
    "additionalFields",
    "descriptionAppendLinks",
}
CUSTOM_FIELD_IDS = {
    "issueCause": "customfield_10088",
    "causeAndSolution": "customfield_10084",
}


def register(subparsers) -> None:
    parser = subparsers.add_parser("update", help="Update Jira fields; dry-run unless --execute is set")
    parser.add_argument("issue", help="Jira key, Jira URL, or Slack mrkdwn Jira link")
    parser.add_argument("--patch", required=True, help="Patch JSON object")
    parser.add_argument("--execute", action="store_true", help="Actually update the issue")
    parser.add_argument("--format", choices=("json", "human", "summary"), default="json")
    parser.set_defaults(_handler=run)


def _string_list(value: Any, key: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UsageError(f"{key} must be an array of strings")
    return [item for item in value if item.strip()]


def _parse_patch(raw_patch: str) -> dict[str, Any]:
    try:
        patch = json.loads(raw_patch)
    except json.JSONDecodeError as exc:
        raise UsageError("--patch must be valid JSON") from exc
    if not isinstance(patch, dict):
        raise UsageError("--patch must be a JSON object")
    unknown = sorted(set(patch) - ALLOWED_PATCH_KEYS)
    if unknown:
        raise UsageError("unknown patch fields: " + ", ".join(unknown))
    if not patch:
        raise UsageError("--patch must include at least one supported field")
    return patch


def _build_fields_from_patch(patch: dict[str, Any]) -> dict[str, Any]:

    fields: dict[str, Any] = {}
    if "components" in patch:
        fields["components"] = [{"name": item} for item in _string_list(patch["components"], "components")]
    if "labels" in patch:
        fields["labels"] = _string_list(patch["labels"], "labels")
    if "issueCause" in patch:
        raw = patch["issueCause"]
        values = raw if isinstance(raw, list) else [raw]
        if not all(isinstance(item, str) for item in values):
            raise UsageError("issueCause must be a string or array of strings")
        fields[CUSTOM_FIELD_IDS["issueCause"]] = [{"value": item} for item in values if item.strip()]
    if "causeAndSolution" in patch:
        if not isinstance(patch["causeAndSolution"], str):
            raise UsageError("causeAndSolution must be a string")
        fields[CUSTOM_FIELD_IDS["causeAndSolution"]] = patch["causeAndSolution"]
    if "additionalFields" in patch:
        if not isinstance(patch["additionalFields"], dict):
            raise UsageError("additionalFields must be a JSON object")
        fields.update(patch["additionalFields"])
    return fields


def _build_fields(raw_patch: str) -> dict[str, Any]:
    return _build_fields_from_patch(_parse_patch(raw_patch))


def _validate_description_append(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UsageError("descriptionAppendLinks must be a JSON object")
    heading = value.get("heading", "技术方案")
    position = value.get("position", "bottom")
    links = value.get("links")
    if not isinstance(heading, str) or not heading.strip():
        raise UsageError("descriptionAppendLinks.heading must be a non-empty string")
    if not isinstance(links, list) or not links:
        raise UsageError("descriptionAppendLinks.links must be a non-empty array")
    if position not in {"top", "bottom", "metadata"}:
        raise UsageError("descriptionAppendLinks.position must be top, bottom, or metadata")
    normalized: list[dict[str, str]] = []
    for item in links:
        if not isinstance(item, dict):
            raise UsageError("each descriptionAppendLinks link must be a JSON object")
        text = item.get("text")
        url = item.get("url")
        if not isinstance(text, str) or not text.strip():
            raise UsageError("each descriptionAppendLinks link requires non-empty text")
        if not isinstance(url, str):
            raise UsageError("each descriptionAppendLinks link requires an HTTPS url")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise UsageError("each descriptionAppendLinks link requires an HTTPS url")
        normalized.append({"text": text.strip(), "url": url.strip()})
    return {"heading": heading.strip(), "position": position, "links": normalized}


def _append_description_links(description: Any, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if description is None:
        description = {"type": "doc", "version": 1, "content": []}
    if not isinstance(description, dict) or description.get("type") != "doc":
        raise UsageError("current Jira description is not an ADF document")
    existing_content = description.get("content")
    if not isinstance(existing_content, list):
        raise UsageError("current Jira description has invalid ADF content")

    serialized = json.dumps(description, ensure_ascii=False)
    missing = [item for item in config["links"] if item["url"] not in serialized]
    existing = [item for item in config["links"] if item["url"] in serialized]
    updated = json.loads(json.dumps(description, ensure_ascii=False))
    updated_existing: list[dict[str, str]] = []

    def heading_node() -> dict[str, Any]:
        return {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": config["heading"]}],
        }

    def link_node(item: dict[str, str]) -> dict[str, Any]:
        return {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": item["text"],
                    "marks": [{"type": "link", "attrs": {"href": item["url"]}}],
                }
            ],
        }

    def update_link_text(node: Any, item: dict[str, str]) -> bool:
        if isinstance(node, list):
            return any(update_link_text(child, item) for child in node)
        if not isinstance(node, dict):
            return False
        if node.get("type") == "text":
            marks = node.get("marks", [])
            if any(
                isinstance(mark, dict)
                and mark.get("type") == "link"
                and mark.get("attrs", {}).get("href") == item["url"]
                for mark in marks
            ):
                if node.get("text") != item["text"]:
                    node["text"] = item["text"]
                    return True
                return False
        return any(update_link_text(child, item) for child in node.get("content", []))

    if config.get("position") == "metadata":
        content = updated["content"]
        remove_indexes: set[int] = set()
        for index, node in enumerate(content):
            if not isinstance(node, dict) or node.get("type") != "paragraph":
                continue
            node_json = json.dumps(node, ensure_ascii=False)
            if any(item["url"] in node_json for item in config["links"]):
                remove_indexes.add(index)
                if index > 0:
                    previous = content[index - 1]
                    if (
                        isinstance(previous, dict)
                        and previous.get("type") == "heading"
                        and config["heading"] in json.dumps(previous, ensure_ascii=False)
                    ):
                        remove_indexes.add(index - 1)
        content = [node for index, node in enumerate(content) if index not in remove_indexes]
        updated["content"] = content

        title_index = next(
            (
                index
                for index, node in enumerate(content)
                if isinstance(node, dict)
                and node.get("type") == "heading"
                and node.get("attrs", {}).get("level") == 1
            ),
            -1,
        )
        metadata_index = title_index + 1 if title_index >= 0 else 0
        metadata = content[metadata_index] if metadata_index < len(content) else None
        updated_existing = []
        for item in existing:
            if update_link_text(metadata, item):
                updated_existing.append(item)

        unresolved = [item for item in config["links"] if item["url"] not in json.dumps(metadata, ensure_ascii=False)]
        if isinstance(metadata, dict) and metadata.get("type") == "blockquote":
            paragraphs = metadata.setdefault("content", [])
            if not paragraphs or paragraphs[0].get("type") != "paragraph":
                paragraphs.insert(0, {"type": "paragraph", "content": []})
            inline = paragraphs[0].setdefault("content", [])
            for item in unresolved:
                if inline:
                    inline.append({"type": "hardBreak"})
                inline.extend(
                    [
                        {"type": "text", "text": f'{config["heading"]}：'},
                        {
                            "type": "text",
                            "text": item["text"],
                            "marks": [{"type": "link", "attrs": {"href": item["url"]}}],
                        },
                    ]
                )
        elif isinstance(metadata, dict) and metadata.get("type") == "table":
            rows = metadata.setdefault("content", [])
            for item in unresolved:
                rows.append(
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "attrs": {},
                                "content": [{"type": "paragraph", "content": [{"type": "text", "text": config["heading"]}]}],
                            },
                            {
                                "type": "tableCell",
                                "attrs": {},
                                "content": [link_node(item)],
                            },
                        ],
                    }
                )
        elif unresolved:
            metadata = {
                "type": "blockquote",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": f'{config["heading"]}：'},
                            {
                                "type": "text",
                                "text": unresolved[0]["text"],
                                "marks": [{"type": "link", "attrs": {"href": unresolved[0]["url"]}}],
                            },
                        ],
                    }
                ],
            }
            content.insert(metadata_index, metadata)
            for item in unresolved[1:]:
                metadata["content"][0]["content"].extend(
                    [
                        {"type": "hardBreak"},
                        {"type": "text", "text": f'{config["heading"]}：'},
                        {
                            "type": "text",
                            "text": item["text"],
                            "marks": [{"type": "link", "attrs": {"href": item["url"]}}],
                        },
                    ]
                )

        changed = updated != description
        return updated, {
            "preserved_existing_blocks": len(existing_content),
            "position": "metadata",
            "appended": missing,
            "updated_existing": updated_existing,
            "moved_existing": existing if remove_indexes else [],
            "skipped_existing": [item for item in existing if item not in updated_existing and not remove_indexes],
            "changed": changed,
        }

    if config.get("position") == "top":
        content = updated["content"]
        remove_indexes: set[int] = set()
        for index, node in enumerate(content):
            node_json = json.dumps(node, ensure_ascii=False)
            if any(item["url"] in node_json for item in config["links"]):
                remove_indexes.add(index)
                if index > 0:
                    previous = content[index - 1]
                    if (
                        previous.get("type") == "heading"
                        and config["heading"] in json.dumps(previous, ensure_ascii=False)
                    ):
                        remove_indexes.add(index - 1)
        remaining = [node for index, node in enumerate(content) if index not in remove_indexes]
        updated["content"] = [heading_node(), *[link_node(item) for item in config["links"]], *remaining]
        changed = updated != description
        return updated, {
            "preserved_existing_blocks": len(existing_content),
            "position": "top",
            "appended": missing,
            "updated_existing": [],
            "moved_existing": existing if changed else [],
            "skipped_existing": existing if not changed else [],
            "changed": changed,
        }

    for item in existing:
        if update_link_text(updated, item):
            updated_existing.append(item)

    skipped = [item for item in existing if item not in updated_existing]
    if missing:
        updated["content"].append(heading_node())
        for item in missing:
            updated["content"].append(link_node(item))
    return updated, {
        "preserved_existing_blocks": len(existing_content),
        "position": "bottom",
        "appended": missing,
        "updated_existing": updated_existing,
        "moved_existing": [],
        "skipped_existing": skipped,
        "changed": updated != description,
    }


def run(args: argparse.Namespace, config: Config) -> int:
    issue_key = parse_issue_key(args.issue)
    patch = _parse_patch(args.patch)
    fields = _build_fields_from_patch(patch)
    client: JiraClient | None = None
    append_result: dict[str, Any] | None = None
    if "descriptionAppendLinks" in patch:
        append_config = _validate_description_append(patch["descriptionAppendLinks"])
        client = JiraClient(config)
        current = client.get_issue(issue_key, fields="description", expand="names")
        description = current.get("fields", {}).get("description") if isinstance(current, dict) else None
        updated_description, append_result = _append_description_links(description, append_config)
        if append_result["changed"]:
            fields["description"] = updated_description
    result: dict[str, Any] = {
        "schema_version": 1,
        "command": "update",
        "ok": True,
        "dry_run": not args.execute,
        "issue_key": issue_key,
        "payload": {"fields": fields},
    }
    if append_result is not None:
        result["description_append"] = append_result
    if args.execute:
        client = client or JiraClient(config)
        result["response"] = (
            client.update_issue(issue_key, fields)
            if fields
            else {"ok": True, "skipped": True, "reason": "no changes"}
        )
    output(result, fmt=args.format)
    return 0
