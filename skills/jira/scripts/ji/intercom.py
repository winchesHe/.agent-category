"""Intercom for Jira GraphQL helpers."""
from __future__ import annotations

import html
import json
import os
import re
import shlex
import socket
import subprocess
import urllib.error
import urllib.request
from typing import Any

from ji.config import Config
from ji.errors import ApiError, AuthError, RequestTimeoutError

CONVERSATION_PATTERNS = (
    re.compile(r"app\.intercom\.com/a/inbox/[^/\s]+/(?:inbox/)?conversation/([A-Za-z0-9_-]+)", re.I),
    re.compile(r"app\.intercom\.com/a/inbox/[^/\s]+/conversations/([A-Za-z0-9_-]+)", re.I),
    re.compile(r"\bintercom\s+conversation\s+([A-Za-z0-9_-]{4,})\b", re.I),
    re.compile(r"\bconversation_id=([A-Za-z0-9_-]{4,})\b", re.I),
)
TAG_RE = re.compile(r"<[^>]+>")

CONVERSATION_DETAIL_QUERY = """
query conversationByIdWithDetails($id: String!) {
  conversation(id: $id) {
    ...ConversationDetailFields
  }
}

fragment ConversationDetailFields on CompleteConversation {
  id
  state
  created_at
  contacts {
    ...ConversationContactFields
  }
  source {
    ...ConversationSourceFields
  }
  conversation_parts {
    ...ConversationPartFields
  }
}

fragment ConversationContactFields on Contact {
  role
  id
  name
  avatar
}

fragment ConversationSourceFields on Source {
  id
  body
  author {
    type
    id
    author_name
    avatar_url
  }
  attachments {
    name
    url
    content_type
  }
}

fragment ConversationPartFields on ConversationPart {
  id
  part_type
  body
  created_at
  author {
    type
    id
    author_name
    avatar_url
  }
  assigned_to {
    id
    name
  }
  attachments {
    name
    url
    content_type
  }
}
"""


def extract_conversation_ids(texts: list[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for pattern in CONVERSATION_PATTERNS:
            for match in pattern.finditer(text or ""):
                value = match.group(1)
                if value not in seen:
                    seen.add(value)
                    found.append(value)
    return found


def build_linked_conversations(
    *,
    texts: list[str],
    links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {
        conversation_id: {"id": conversation_id, "url": None, "title": None, "source": "text"}
        for conversation_id in extract_conversation_ids(texts)
    }
    for link in links:
        haystack = " ".join(
            str(link.get(key) or "") for key in ("url", "title", "relationship")
        )
        for conversation_id in extract_conversation_ids([haystack]):
            item = by_id.setdefault(
                conversation_id,
                {"id": conversation_id, "url": None, "title": None, "source": "remote_link"},
            )
            item["url"] = item.get("url") or link.get("url")
            item["title"] = item.get("title") or link.get("title")
            item["relationship"] = item.get("relationship") or link.get("relationship")
            item["source"] = "remote_link"
    return list(by_id.values())


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    return html.unescape(TAG_RE.sub("", value)).strip()


def _auth_header(jwt: str) -> str:
    token = jwt.strip()
    return token if token.startswith("JWT ") else f"JWT {token}"


class IntercomForJiraClient:
    def __init__(self, config: Config, *, jwt: str, referrer: str | None = None) -> None:
        if not jwt:
            raise ApiError("Intercom for Jira runtime JWT is not configured")
        self.config = config
        self.jwt = jwt
        self.referrer = referrer

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        payload = {
            "query": CONVERSATION_DETAIL_QUERY,
            "variables": {"id": conversation_id},
        }
        headers = {
            "Accept": "*/*",
            "Authorization": _auth_header(self.jwt),
            "Content-Type": "application/json",
            "User-Agent": "winches-jira-skill/1.0",
        }
        referrer = self.referrer or self.config.intercom_referrer
        if referrer:
            headers["Referer"] = referrer
        req = urllib.request.Request(
            self.config.intercom_graphql_url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.intercom_timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            message = f"fetch Intercom linked conversation {conversation_id} failed with HTTP {exc.code}"
            if detail:
                message += f": {detail}"
            if exc.code in (401, 403):
                raise AuthError(message) from exc
            raise ApiError(message) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RequestTimeoutError(f"fetch Intercom linked conversation {conversation_id} timed out") from exc
        except urllib.error.URLError as exc:
            raise ApiError(
                f"fetch Intercom linked conversation {conversation_id} failed: {exc.reason}"
            ) from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(f"Intercom GraphQL returned invalid JSON: {exc}") from exc
        if data.get("errors"):
            raise ApiError(f"Intercom GraphQL errors for {conversation_id}: {data['errors']}")
        conversation = (data.get("data") or {}).get("conversation")
        if not isinstance(conversation, dict):
            raise ApiError(f"Intercom GraphQL returned no conversation for {conversation_id}")
        return simplify_conversation(conversation)


def _author(value: dict[str, Any] | None) -> dict[str, Any]:
    value = value or {}
    return {
        "type": value.get("type"),
        "id": value.get("id"),
        "author_name": value.get("author_name"),
        "avatar_url": value.get("avatar_url"),
    }


def _attachments(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {
            "name": item.get("name"),
            "url": item.get("url"),
            "content_type": item.get("content_type"),
        }
        for item in (items or [])
        if isinstance(item, dict)
    ]


def simplify_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
    source = conversation.get("source") or {}
    parts = []
    for part in conversation.get("conversation_parts") or []:
        if not isinstance(part, dict):
            continue
        parts.append(
            {
                "id": part.get("id"),
                "part_type": part.get("part_type"),
                "body": part.get("body"),
                "body_text": html_to_text(part.get("body")),
                "created_at": part.get("created_at"),
                "author": _author(part.get("author")),
                "assigned_to": part.get("assigned_to"),
                "attachments": _attachments(part.get("attachments")),
            }
        )
    return {
        "id": conversation.get("id"),
        "state": conversation.get("state"),
        "created_at": conversation.get("created_at"),
        "contacts": [
            {
                "role": contact.get("role"),
                "id": contact.get("id"),
                "name": contact.get("name"),
                "avatar": contact.get("avatar"),
            }
            for contact in (conversation.get("contacts") or [])
            if isinstance(contact, dict)
        ],
        "source": {
            "id": source.get("id"),
            "body": source.get("body"),
            "body_text": html_to_text(source.get("body")),
            "author": _author(source.get("author")),
            "attachments": _attachments(source.get("attachments")),
        },
        "conversation_parts": parts,
    }


def resolve_runtime_jwt(
    config: Config,
    *,
    issue_key: str,
    issue_id: str | None,
    project_key: str | None,
) -> str | None:
    if config.intercom_jwt:
        return config.intercom_jwt
    if not config.intercom_jwt_command:
        return None

    argv = shlex.split(config.intercom_jwt_command)
    if not argv:
        return None
    env = os.environ.copy()
    env.update(
        {
            "JIRA_ISSUE_KEY": issue_key,
            "JIRA_ISSUE_ID": issue_id or "",
            "JIRA_PROJECT_KEY": project_key or "",
            "JIRA_BASE_URL": config.jira_base_url,
        }
    )
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=config.intercom_timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ApiError(f"JIRA_INTERCOM_JWT_COMMAND failed: {exc}") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[-300:]
        raise ApiError(
            "JIRA_INTERCOM_JWT_COMMAND exited "
            f"{result.returncode}{': ' + stderr if stderr else ''}"
        )
    token = (result.stdout or "").strip().splitlines()[0] if result.stdout.strip() else ""
    return token or None
