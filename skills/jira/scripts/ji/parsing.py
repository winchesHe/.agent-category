"""Parsing helpers for Jira command inputs and attachment metadata."""
from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from collections.abc import Iterable
from typing import Any

from ji.errors import UsageError

ISSUE_KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*-\d+)\b")
SUPPORTED_IMAGE_MIMETYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
MAGIC_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def parse_issue_key(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise UsageError("empty Jira issue value")
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].split("|", 1)[0]

    direct = ISSUE_KEY_RE.fullmatch(value)
    if direct:
        return direct.group(1).upper()

    parsed = urllib.parse.urlparse(value)
    if parsed.scheme and parsed.netloc:
        for candidate in (parsed.path, parsed.query, parsed.fragment):
            match = ISSUE_KEY_RE.search(candidate or "")
            if match:
                return match.group(1).upper()

    match = ISSUE_KEY_RE.search(value)
    if match:
        return match.group(1).upper()
    raise UsageError(f"cannot parse Jira issue key from {raw!r}")


def csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_content_type(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def detect_supported_image_mimetype(data: bytes) -> str | None:
    for signature, mime in MAGIC_SIGNATURES:
        if data.startswith(signature):
            return mime
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or "file"


def safe_filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    basename = os.path.basename(parsed.path) if parsed.path else ""
    if basename and "/" not in basename and "\\" not in basename and ".." not in basename:
        return safe_filename(basename)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"attachment-{digest}"


def iter_strings(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from iter_strings(item)
