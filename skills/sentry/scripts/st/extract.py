"""Compact Sentry response extraction helpers."""
from __future__ import annotations

from typing import Any


def compact_project(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "id": value.get("id"),
        "slug": value.get("slug"),
        "name": value.get("name"),
        "platform": value.get("platform"),
    }


def compact_issue(issue: dict[str, Any]) -> dict[str, Any]:
    project = compact_project(issue.get("project"))
    return {
        "id": issue.get("id"),
        "shortId": issue.get("shortId") or issue.get("short_id"),
        "title": issue.get("title"),
        "culprit": issue.get("culprit"),
        "permalink": issue.get("permalink"),
        "status": issue.get("status"),
        "level": issue.get("level"),
        "count": issue.get("count"),
        "userCount": issue.get("userCount") or issue.get("user_count"),
        "firstSeen": issue.get("firstSeen") or issue.get("first_seen"),
        "lastSeen": issue.get("lastSeen") or issue.get("last_seen"),
        "project": project,
    }


def compact_event(event: dict[str, Any], *, breadcrumb_limit: int = 15, frame_limit: int = 15) -> dict[str, Any]:
    tags = _extract_tags(event)
    exceptions = _extract_exceptions(event, frame_limit=frame_limit)
    breadcrumbs = _extract_breadcrumbs(event, limit=breadcrumb_limit)
    return {
        "id": event.get("id") or event.get("eventID") or event.get("event_id"),
        "title": event.get("title") or event.get("message"),
        "type": event.get("type"),
        "culprit": event.get("culprit"),
        "datetime": event.get("dateCreated") or event.get("datetime") or event.get("timestamp"),
        "platform": event.get("platform"),
        "projectID": event.get("projectID") or event.get("project_id"),
        "tags": tags,
        "exception": exceptions,
        "breadcrumbs": breadcrumbs,
    }


def compact_issue_event(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id") or item.get("eventID") or item.get("event_id"),
        "title": item.get("title") or item.get("message"),
        "message": item.get("message"),
        "datetime": item.get("dateCreated") or item.get("datetime") or item.get("timestamp"),
        "user": item.get("user"),
        "tags": _extract_tags(item),
        "culprit": item.get("culprit"),
        "platform": item.get("platform"),
        "url": item.get("url"),
    }


def compact_tag_value(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": item.get("value") or item.get("name") or item.get("key"),
        "count": item.get("count"),
        "firstSeen": item.get("firstSeen") or item.get("first_seen"),
        "lastSeen": item.get("lastSeen") or item.get("last_seen"),
    }


def _extract_tags(event: dict[str, Any]) -> dict[str, Any]:
    tags = event.get("tags")
    if isinstance(tags, dict):
        return dict(tags)
    result: dict[str, Any] = {}
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, dict):
                key = item.get("key") or item.get("name")
                if key:
                    result[str(key)] = item.get("value")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                result[str(item[0])] = item[1]
    return result


def _extract_exceptions(event: dict[str, Any], *, frame_limit: int) -> list[dict[str, Any]]:
    values = None
    exception = event.get("exception")
    if isinstance(exception, dict):
        values = exception.get("values")
    if values is None:
        for entry in event.get("entries") or []:
            if isinstance(entry, dict) and entry.get("type") == "exception":
                data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
                values = data.get("values")
                break
    if not isinstance(values, list):
        return []

    result: list[dict[str, Any]] = []
    for exc in values:
        if not isinstance(exc, dict):
            continue
        stacktrace = exc.get("stacktrace") if isinstance(exc.get("stacktrace"), dict) else {}
        frames = stacktrace.get("frames") if isinstance(stacktrace, dict) else []
        result.append(
            {
                "type": exc.get("type"),
                "value": exc.get("value"),
                "module": exc.get("module"),
                "mechanism": exc.get("mechanism"),
                "frames": [_compact_frame(f) for f in (frames or [])[-frame_limit:] if isinstance(f, dict)],
            }
        )
    return result


def _compact_frame(frame: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": frame.get("filename") or frame.get("absPath") or frame.get("abs_path"),
        "module": frame.get("module"),
        "function": frame.get("function"),
        "lineno": frame.get("lineno") or frame.get("lineNo") or frame.get("line_no"),
        "colno": frame.get("colno") or frame.get("colNo") or frame.get("col_no"),
        "in_app": frame.get("in_app") if "in_app" in frame else frame.get("inApp"),
        "context_line": frame.get("context_line") or frame.get("contextLine"),
    }


def _extract_breadcrumbs(event: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    values = None
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        values = breadcrumbs.get("values")
    if values is None:
        for entry in event.get("entries") or []:
            if isinstance(entry, dict) and entry.get("type") == "breadcrumbs":
                data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
                values = data.get("values")
                break
    if not isinstance(values, list):
        return []
    return [_compact_breadcrumb(v) for v in values[-limit:] if isinstance(v, dict)]


def _compact_breadcrumb(crumb: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": crumb.get("timestamp"),
        "type": crumb.get("type"),
        "category": crumb.get("category"),
        "level": crumb.get("level"),
        "message": crumb.get("message"),
        "data": crumb.get("data") or {},
    }
