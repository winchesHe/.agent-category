"""HTTP clients for Jira and attachment operations."""
from __future__ import annotations

import base64
import json
import secrets
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from ji.adf_input import markdown_to_adf_v1
from ji.config import Config
from ji.errors import ApiError, AuthError, RequestTimeoutError
from ji.parsing import (
    SUPPORTED_IMAGE_MIMETYPES,
    detect_supported_image_mimetype,
    normalize_content_type,
    safe_filename_from_url,
)


class NoAuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Remove Authorization while following redirects to CDN/S3 hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            for header in ("Authorization", "authorization"):
                new_req.headers.pop(header, None)
                new_req.unredirected_hdrs.pop(header, None)
        return new_req


def media_id_from_url(url: str) -> str | None:
    """Extract a Jira Media Services UUID without returning its signed URL."""
    parts = [part for part in urllib.parse.urlparse(url).path.split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part != "file":
            continue
        candidate = parts[index + 1]
        try:
            return str(uuid.UUID(candidate))
        except ValueError:
            continue
    return None


def _problem_detail(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""
    text = raw_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    if isinstance(payload, dict):
        for key in ("message", "detail", "error", "errorMessages"):
            value = payload.get(key)
            if value:
                return str(value)[:500]
    return text[:500]


class JiraClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        raw_auth = f"{config.jira_login}:{config.jira_token}".encode("utf-8")
        self.authorization = "Basic " + base64.b64encode(raw_auth).decode("ascii")

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        elif path.startswith("/rest/") or path.startswith("/plugins/"):
            url = f"{self.config.jira_base_url}{path}"
        else:
            url = f"{self.config.jira_base_url}/rest/api/3/{path.lstrip('/')}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean, doseq=True)
        return url

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        label: str,
    ) -> Any:
        url = self._url(path, params)
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": self.authorization,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "winches-jira-skill/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.jira_timeout) as resp:
                raw = resp.read()
                if not raw:
                    return {"ok": True, "status": getattr(resp, "status", 200)}
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise ApiError(f"{label} returned invalid JSON: {exc}") from exc
        except urllib.error.HTTPError as exc:
            detail = _problem_detail(exc.read())
            message = f"{label} failed with HTTP {exc.code}"
            if detail:
                message += f": {detail}"
            if exc.code in (401, 403):
                raise AuthError(message) from exc
            raise ApiError(message) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RequestTimeoutError(f"{label} timed out") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise RequestTimeoutError(f"{label} timed out") from exc
            raise ApiError(f"{label} request failed: {exc.reason}") from exc

    def get_issue(self, issue_key: str, *, fields: str, expand: str = "names") -> dict[str, Any]:
        return self.request_json(
            "GET",
            f"issue/{urllib.parse.quote(issue_key)}",
            params={"fields": fields, "expand": expand},
            label=f"fetch issue {issue_key}",
        )

    def list_fields(self) -> list[dict[str, Any]]:
        result = self.request_json("GET", "field", label="list Jira fields")
        return result if isinstance(result, list) else []

    def get_comments(self, issue_key: str, limit: int | None) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        start_at = 0
        page_size = 100 if limit is None else min(max(limit, 0), 100)
        if page_size == 0:
            return comments
        while True:
            page = self.request_json(
                "GET",
                f"issue/{urllib.parse.quote(issue_key)}/comment",
                params={"startAt": start_at, "maxResults": page_size},
                label=f"fetch comments for {issue_key}",
            )
            items = page.get("comments", []) if isinstance(page, dict) else []
            comments.extend(item for item in items if isinstance(item, dict))
            if limit is not None and len(comments) >= limit:
                return comments[:limit]
            if not items or page.get("isLast") or start_at + len(items) >= page.get("total", 0):
                return comments
            start_at += len(items)

    def get_remote_links(self, issue_key: str) -> list[dict[str, Any]]:
        result = self.request_json(
            "GET",
            f"issue/{urllib.parse.quote(issue_key)}/remotelink",
            label=f"fetch remote links for {issue_key}",
        )
        return result if isinstance(result, list) else []

    def search_jql(
        self,
        *,
        jql: str,
        fields: list[str],
        limit: int,
        page_token: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "jql": jql,
            "maxResults": limit,
            "fields": fields,
        }
        if page_token:
            body["nextPageToken"] = page_token
        return self.request_json("POST", "search/jql", body=body, label="search Jira issues")

    def create_issue_api(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "issue", body={"fields": fields}, label="create Jira issue")

    def get_issue_link_types(self) -> list[dict[str, Any]]:
        result = self.request_json("GET", "issueLinkType", label="fetch Jira issue link types")
        values = result.get("issueLinkTypes", []) if isinstance(result, dict) else []
        return [item for item in values if isinstance(item, dict)]

    def create_issue_link(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.request_json("POST", "issueLink", body=payload, label="create Jira issue link")

    def get_create_fields(self, project: str, issue_type_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        fields: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        start_at = 0
        while True:
            page = self.request_json(
                "GET",
                f"issue/createmeta/{urllib.parse.quote(project)}/issuetypes/{urllib.parse.quote(issue_type_id)}",
                params={"startAt": start_at, "maxResults": 200},
                label=f"fetch create metadata for {project}/{issue_type_id}",
            )
            values = []
            if isinstance(page, dict):
                candidate = page.get("values")
                if not isinstance(candidate, list):
                    candidate = page.get("fields")
                if isinstance(candidate, list):
                    values = candidate
            if isinstance(page, dict):
                pages.append(page)
            fields.extend(item for item in values if isinstance(item, dict))
            if not values or page.get("isLast") or start_at + len(values) >= page.get("total", 0):
                return fields, pages
            start_at += len(values)

    def get_issue_numeric_id(self, issue_key: str) -> str:
        response = self.request_json(
            "GET",
            f"issue/{urllib.parse.quote(issue_key)}?fields=summary",
            label=f"resolve Jira issue id {issue_key}",
        )
        issue_id = response.get("id") if isinstance(response, dict) else None
        if not issue_id:
            raise ApiError(f"Jira returned no id for issue {issue_key}")
        return str(issue_id)

    def invoke_automation(self, payload: dict[str, Any], target: str) -> dict[str, Any]:
        target_url = self.resolve_automation_url(target)
        return self.request_json("POST", target_url, body=payload, label="invoke Jira automation")

    def resolve_automation_url(self, target: str) -> str:
        """Convert a path or absolute URL into the final POST target.

        Absolute URLs are passed through; bare paths are joined with ``jira_base_url``.
        """
        raw = (target or "").strip()
        if not raw:
            raise ApiError("automation rule URL is required")
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        return f"{self.config.jira_base_url}/{raw.lstrip('/')}"

    def update_issue(self, issue_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self.request_json(
            "PUT",
            f"issue/{urllib.parse.quote(issue_key)}",
            body={"fields": fields},
            label=f"update Jira issue {issue_key}",
        )

    def get_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        result = self.request_json(
            "GET",
            f"issue/{urllib.parse.quote(issue_key)}/transitions",
            params={"expand": "transitions.fields"},
            label=f"list transitions for Jira issue {issue_key}",
        )
        transitions = result.get("transitions", []) if isinstance(result, dict) else []
        if not isinstance(transitions, list):
            raise ApiError(f"Jira returned invalid transitions for issue {issue_key}")
        return [item for item in transitions if isinstance(item, dict)]

    def transition_issue(
        self,
        issue_key: str,
        *,
        transition_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"transition": {"id": str(transition_id)}}
        if fields:
            payload["fields"] = fields
        return self.request_json(
            "POST",
            f"issue/{urllib.parse.quote(issue_key)}/transitions",
            body=payload,
            label=f"transition Jira issue {issue_key}",
        )

    def upload_image_attachment(
        self,
        issue_key: str,
        *,
        filename: str,
        mime_type: str,
        body: bytes,
    ) -> list[dict[str, Any]]:
        """Upload one validated image using Jira's multipart attachment API."""
        boundary = f"----winches-jira-{secrets.token_hex(16)}"
        safe_name = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
        multipart = b"".join(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'.encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("ascii"),
                body,
                f"\r\n--{boundary}--\r\n".encode("ascii"),
            ]
        )
        req = urllib.request.Request(
            self._url(f"issue/{urllib.parse.quote(issue_key)}/attachments"),
            data=multipart,
            method="POST",
            headers={
                "Authorization": self.authorization,
                "Accept": "application/json",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(multipart)),
                "X-Atlassian-Token": "no-check",
                "User-Agent": "winches-jira-skill/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.jira_timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = _problem_detail(exc.read())
            message = f"upload image attachment to {issue_key} failed with HTTP {exc.code}"
            if detail:
                message += f": {detail}"
            if exc.code in (401, 403):
                raise AuthError(message) from exc
            raise ApiError(message) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RequestTimeoutError(f"upload image attachment to {issue_key} timed out") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"upload image attachment to {issue_key} failed: {exc.reason}") from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(f"upload image attachment to {issue_key} returned invalid JSON: {exc}") from exc
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ApiError(f"upload image attachment to {issue_key} returned unexpected payload")
        return payload

    def get_intercom_dialog_context(
        self,
        *,
        issue_key: str,
        issue_id: str,
        project_key: str,
        project_id: str,
        issue_type_id: str,
        selected_conversation_id: str,
    ) -> dict[str, Any]:
        product_context = {
            "project.key": project_key,
            "project.id": project_id,
            "issue.id": issue_id,
            "issue.key": issue_key,
            "issuetype.id": issue_type_id,
        }
        data = urllib.parse.urlencode(
            {
                "plugin-key": "io.toolsplus.atlassian.connect.jira.intercom",
                "product-context": json.dumps(product_context, separators=(",", ":")),
                "key": "conversation-details-dialog",
                "width": "100%",
                "height": "100%",
                "classifier": "json",
                "ac.selectedConversationId": selected_conversation_id or "undefined",
            }
        ).encode("utf-8")
        browse_url = f"{self.config.jira_base_url}/browse/{urllib.parse.quote(issue_key)}"
        req = urllib.request.Request(
            self._url("/plugins/servlet/ac/io.toolsplus.atlassian.connect.jira.intercom/conversation-details-dialog"),
            data=data,
            method="POST",
            headers={
                "Authorization": self.authorization,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": browse_url,
                "User-Agent": "winches-jira-skill/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.jira_timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = _problem_detail(exc.read())
            message = f"fetch Intercom dialog context failed with HTTP {exc.code}"
            if detail:
                message += f": {detail}"
            if exc.code in (401, 403):
                raise AuthError(message) from exc
            raise ApiError(message) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RequestTimeoutError("fetch Intercom dialog context timed out") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"fetch Intercom dialog context failed: {exc.reason}") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(f"Intercom dialog context returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ApiError("Intercom dialog context returned non-object JSON")
        return payload

    def download_attachment(
        self,
        attachment_url: str,
        *,
        output_dir: Path | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        parsed_base = urllib.parse.urlparse(self.config.jira_base_url)
        parsed_url = urllib.parse.urlparse(attachment_url)
        if parsed_url.scheme != "https" or parsed_url.hostname != parsed_base.hostname:
            return {
                "ok": False,
                "attachment_url": attachment_url,
                "errors": [f"host_not_allowed:{parsed_url.hostname or 'unknown'}"],
            }

        headers = {
            "Authorization": self.authorization,
            "User-Agent": "winches-jira-skill/1.0",
        }
        req = urllib.request.Request(attachment_url, headers=headers)
        opener = urllib.request.build_opener(NoAuthRedirectHandler())
        max_size = max_bytes or self.config.max_attachment_bytes

        try:
            with opener.open(req, timeout=self.config.jira_timeout) as resp:
                status = getattr(resp, "status", 200)
                content_type = normalize_content_type(resp.headers.get("Content-Type"))
                content_length = resp.headers.get("Content-Length")
                final_url = getattr(resp, "geturl", lambda: attachment_url)()
                if content_length and int(content_length) > max_size:
                    return {
                        "ok": False,
                        "attachment_url": attachment_url,
                        "errors": [f"too_large:{content_length}bytes,max:{max_size}"],
                    }
                body = resp.read(max_size + 1)
        except urllib.error.HTTPError as exc:
            return {"ok": False, "attachment_url": attachment_url, "errors": [f"http_error:{exc.code}"]}
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            return {"ok": False, "attachment_url": attachment_url, "errors": [f"network_error:{exc}"]}

        if status != 200:
            return {"ok": False, "attachment_url": attachment_url, "errors": [f"unexpected_status:{status}"]}
        if len(body) > max_size:
            return {"ok": False, "attachment_url": attachment_url, "errors": [f"too_large:{len(body)}bytes,max:{max_size}"]}

        errors: list[str] = []
        warnings: list[str] = []
        if content_type not in SUPPORTED_IMAGE_MIMETYPES:
            errors.append(f"content_type_rejected:{content_type or 'unknown'}")
        detected = detect_supported_image_mimetype(body)
        if detected is None:
            errors.append("magic_byte_rejected")
        elif detected not in SUPPORTED_IMAGE_MIMETYPES:
            errors.append(f"magic_byte_unsupported:{detected}")
        if errors:
            return {"ok": False, "attachment_url": attachment_url, "errors": errors}
        if content_type != detected:
            warnings.append(f"content_type_mismatch:header={content_type},detected={detected}")

        target_dir = output_dir or Path(tempfile.mkdtemp(prefix="winches-jira-"))
        filename = safe_filename_from_url(attachment_url)
        destination = target_dir / filename
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = destination.with_suffix(destination.suffix + ".part")
            tmp_path.write_bytes(body)
            tmp_path.replace(destination)
        except OSError as exc:
            return {"ok": False, "attachment_url": attachment_url, "errors": [f"write_failed:{exc}"]}

        result = {
            "ok": True,
            "attachment_url": attachment_url,
            "local_path": str(destination),
            "mime_type": detected,
            "size_bytes": len(body),
            "warnings": warnings,
        }
        media_id = media_id_from_url(final_url)
        if media_id:
            result["media_id"] = media_id
        return result


def build_api_create_fields(
    *,
    project: str,
    issue_type: str,
    summary: str,
    description: str,
    components: list[str],
    labels: list[str],
    parent: str | None,
    additional_fields: dict[str, Any],
    description_adf: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "project": {"key": project},
        "issuetype": {"name": issue_type},
        "summary": summary,
    }
    if description and description_adf is not None:
        raise ValueError("description and description_adf are mutually exclusive")
    if description_adf is not None:
        fields["description"] = description_adf
    elif description:
        fields["description"] = markdown_to_adf_v1(description).adf
    if components:
        fields["components"] = [{"name": item} for item in components]
    if labels:
        fields["labels"] = labels
    if parent:
        fields["parent"] = {"key": parent}
    fields.update(additional_fields)
    return fields
