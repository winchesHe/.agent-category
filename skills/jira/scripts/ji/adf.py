"""Atlassian Document Format helpers."""
from __future__ import annotations

from typing import Any

CS_FIELD_MAP = {
    "customfield_10049": "priority",
    "customfield_10089": "squad",
    "customfield_11580": "feature_domains",
    "customfield_10088": "issue_cause",
    "customfield_10078": "defect_type",
    "customfield_10414": "user_tier",
    "customfield_11160": "t1_logo_name",
    "customfield_11382": "t1_location_name",
    "customfield_11157": "t1_moego_login_email",
    "customfield_11218": "moego_login_email",
    "customfield_11158": "t1_customer_role",
    "customfield_11159": "t1_customer_stage",
    "customfield_11161": "t1_user_name",
    "customfield_10048": "reproducible",
    "customfield_11317": "sla_breach",
    "customfield_13126": "qa_investigation_start",
    "customfield_13170": "bug_confirmed_at",
}

DESCRIPTION_FIELDS = {
    "description": "description",
    "customfield_10340": "issue_description",
    "customfield_10052": "bug_description",
    "customfield_11156": "reproduce_steps",
    "customfield_10084": "cause_and_solution",
    "customfield_10053": "story_description",
}


def extract_adf_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(extract_adf_text(item) for item in node)
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type", "")
    text = node.get("text", "")
    child_text = "".join(extract_adf_text(item) for item in node.get("content", []))

    if node_type == "hardBreak":
        return "\n"
    if node_type in {"paragraph", "heading"}:
        level = node.get("attrs", {}).get("level", 0)
        prefix = "#" * level + " " if level else ""
        return f"{prefix}{child_text}\n"
    if node_type in {"bulletList", "orderedList"}:
        return child_text
    if node_type == "listItem":
        return f"- {child_text.strip()}\n"
    if node_type == "codeBlock":
        return f"```\n{child_text}```\n"
    if node_type == "blockquote":
        return "\n".join(f"> {line}" for line in child_text.strip().splitlines()) + "\n"
    return text + child_text


def markdown_to_adf(markdown: str) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for paragraph in markdown.split("\n\n"):
        lines = paragraph.splitlines() or [""]
        parts: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            if index:
                parts.append({"type": "hardBreak"})
            if line:
                parts.append({"type": "text", "text": line})
        content.append({"type": "paragraph", "content": parts})
    return {"type": "doc", "version": 1, "content": content}


def extract_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        if value.get("type") == "doc":
            return extract_adf_text(value).strip()
        if "value" in value:
            return value["value"]
        if "displayName" in value:
            return value["displayName"]
        if "emailAddress" in value:
            return value["emailAddress"]
        if "name" in value:
            return value["name"]
        if "key" in value:
            return value["key"]
        return value
    if isinstance(value, list):
        parts: list[Any] = []
        for item in value:
            item_value = extract_value(item)
            if item_value is not None:
                parts.append(item_value)
        return parts
    return str(value)


def compact_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "account_id": user.get("accountId"),
        "display_name": user.get("displayName"),
        "email": user.get("emailAddress"),
        "active": user.get("active"),
    }
