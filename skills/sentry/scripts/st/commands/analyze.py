"""analyze: multi-event aggregation analysis with exception chain ordering and repo inference."""
from __future__ import annotations

from typing import Any

from st.client import SentryClient, path_quote
from st.commands._common import add_issue_identity_flags
from st.extract import _extract_tags
from st.urls import resolve_issue_args

NAME = "analyze"

# --- Bundle → repo mapping ---

BUNDLE_REPO_MAP: dict[str, str] = {
    "lib-moego-ui": "MoeGolibrary/moego-ui",
    "index~": "MoeGolibrary/Boarding_Desktop",
    "boarding/": "MoeGolibrary/Boarding_Desktop",
    "online-booking/": "MoeGolibrary/online-booking-client-web",
    "app/": "MoeGolibrary/website",
    "src/": "MoeGolibrary/website",
}

SCHEMA_VERSION = 2


def register(subparsers) -> None:
    p = subparsers.add_parser(
        NAME,
        help="多 event 聚合分析：exception chain 排序、repo 归属推断、fix boundary、多格式输出",
    )
    add_issue_identity_flags(p)
    p.add_argument("--mode", choices=["issue", "event", "latest"], default="issue",
                   help="issue: 多 event 聚合；event: 指定 event；latest: 最新单 event")
    p.add_argument("--event-id", help="指定 event id（mode=event 时必填）")
    p.add_argument("--events", type=int, default=5, help="issue 模式下拉取的 event 数量（默认 5）")
    p.add_argument("--target", choices=["json", "markdown", "slack", "jira", "pr"], default="json",
                   help="输出格式（默认 json）")
    p.set_defaults(_handler=run)


def run(args, config) -> int:
    org, issue_id, event_id, parsed = resolve_issue_args(args, config)
    client = SentryClient(config)

    # Fetch issue metadata
    issue_raw = client.get_issue_resource(org, issue_id)

    # Fetch events based on mode
    raw_events: list[dict[str, Any]] = []
    warnings: list[str] = []

    if args.mode == "event":
        eid = event_id or getattr(args, "event_id", None)
        if not eid:
            from st.errors import UsageError
            raise UsageError("mode=event 时必须提供 event id（通过 URL 或 --event-id）")
        raw_events = [client.get_issue_resource(org, issue_id, f"events/{path_quote(eid)}/")]
    elif args.mode == "latest":
        raw_events = [client.get_issue_resource(org, issue_id, "events/latest/")]
        warnings.append("latest event 可能是边缘样本；稳定根因需要对比多个 events")
    else:
        # issue mode: fetch multiple events
        listing = client.get_issue_resource(
            org, issue_id, "events/", params={"per_page": str(min(args.events, 100))}
        )
        event_ids = []
        if isinstance(listing, list):
            event_ids = [e.get("eventID") or e.get("id") for e in listing[:args.events] if isinstance(e, dict)]
        for eid in event_ids:
            if eid:
                ev = client.get_issue_resource(org, issue_id, f"events/{path_quote(eid)}/")
                raw_events.append(ev)
        if not raw_events:
            raw_events = [client.get_issue_resource(org, issue_id, "events/latest/")]
            warnings.append("未找到 event 列表，已回退读取 latest event")

    # Normalize and aggregate
    issue_norm = _normalize_issue(issue_raw, config.base_url, issue_id)
    events_norm = [_normalize_event(e) for e in raw_events]
    exceptions = _extract_all_exceptions(raw_events)
    breadcrumbs = _extract_all_breadcrumbs(raw_events)
    selected_event_breadcrumbs = _extract_event_breadcrumbs(raw_events[0]) if raw_events else []

    # Analysis
    exception_chain = _build_selected_exception_chain(raw_events)
    route_context = _build_route_context(selected_event_breadcrumbs)
    repo_candidates = _build_repo_candidates(exceptions)
    fix_boundary = _build_fix_boundary(exceptions, exception_chain)
    backend_correlation = _build_selected_backend_correlation(raw_events)
    root_cause_candidates = _build_root_cause_candidates(exception_chain, exceptions)

    # Build result (schema v2)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "input": {
            "url": args.url,
            "organization_slug": org,
            "issue_id": issue_id,
            "event_id": event_id,
            "mode": args.mode,
            "events_requested": args.events,
            "target": args.target,
        },
        "issue": issue_norm,
        "selected_event": events_norm[0] if events_norm else {},
        "events": events_norm,
        "exceptions": exceptions,
        "breadcrumbs": breadcrumbs,
        "analysis": {
            "exception_chain": exception_chain,
            "route_context": route_context,
            "fix_boundary": fix_boundary,
        },
        "root_cause_candidates": root_cause_candidates,
        "backend_correlation": backend_correlation,
        "repo_candidates": repo_candidates,
        "summary": {},
        "warnings": warnings,
        "errors": [],
    }

    # Build summary
    result["summary"] = _build_summary(result)

    # Render
    rendered = _render(result, args.target)
    import sys
    sys.stdout.write(rendered)
    if not rendered.endswith("\n"):
        sys.stdout.write("\n")
    return 0


# --- Normalization helpers ---

def _normalize_issue(raw: dict[str, Any], base_url: str, issue_id: str) -> dict[str, Any]:
    return {
        "id": str(raw.get("id", issue_id)),
        "title": raw.get("title", ""),
        "platform": raw.get("platform", ""),
        "level": raw.get("level", ""),
        "status": raw.get("status", ""),
        "first_seen": raw.get("firstSeen") or raw.get("first_seen", ""),
        "last_seen": raw.get("lastSeen") or raw.get("last_seen", ""),
        "event_count": int(raw.get("count", raw.get("event_count", 0))),
        "users_affected": int(raw.get("userCount", raw.get("users_affected", 0))),
        "url": raw.get("permalink", f"{base_url}/issues/{issue_id}/"),
    }


def _normalize_event(raw: dict[str, Any]) -> dict[str, Any]:
    tags = _extract_tags(raw)
    return {
        "event_id": raw.get("eventID") or raw.get("id") or raw.get("event_id", ""),
        "timestamp": raw.get("dateCreated") or raw.get("datetime") or raw.get("timestamp", ""),
        "release": tags.get("release", ""),
        "environment": tags.get("environment", ""),
        "transaction": tags.get("transaction", ""),
        "browser": tags.get("browser.name", ""),
        "os": tags.get("os.name", ""),
        "user": tags.get("user", ""),
    }


def _classify_bundle(filename: str) -> str:
    if filename.startswith("lib-moego-ui") or filename.startswith("lib-base"):
        return "ui_library_bundle"
    if filename.startswith(("index~", "boarding/", "online-booking/", "app/", "src/")):
        return "business_bundle"
    if filename.startswith("node_modules/"):
        return "third_party"
    return "unknown_bundle"


def _frame_source_kind(frame: dict[str, Any]) -> str:
    filename = frame.get("filename") or frame.get("absPath") or frame.get("abs_path") or ""
    return _classify_bundle(filename)


def _select_crash_frame(frames_raw: list[dict[str, Any]]) -> dict[str, Any] | None:
    """来源分类与仓库归属共用末端应用帧，避免把调用方当成直接崩溃点。"""
    in_app_frames = [frame for frame in frames_raw if _is_in_app_frame(frame)]
    if in_app_frames:
        return in_app_frames[-1]

    app_bundle_frames = [frame for frame in frames_raw if _frame_source_kind(frame) in {"ui_library_bundle", "business_bundle"}]
    if app_bundle_frames:
        return app_bundle_frames[-1]

    return frames_raw[-1] if frames_raw else None


def _infer_source_kind(frames_raw: list[dict[str, Any]]) -> str:
    frame = _select_crash_frame(frames_raw)
    return _frame_source_kind(frame) if frame is not None else "unknown_bundle"


def _is_in_app_frame(frame: dict[str, Any]) -> bool:
    if "in_app" in frame:
        return bool(frame.get("in_app"))
    if "inApp" in frame:
        return bool(frame.get("inApp"))
    return False


def _get_exception_values(event: dict[str, Any]) -> list[dict[str, Any]]:
    exc = event.get("exception")
    if isinstance(exc, dict):
        vals = exc.get("values")
        if vals:
            return vals
    for entry in event.get("entries") or []:
        if isinstance(entry, dict) and entry.get("type") == "exception":
            data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
            vals = data.get("values")
            if isinstance(vals, list):
                return vals
    return []


def _extract_all_exceptions(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    exceptions: list[dict[str, Any]] = []
    order = 0
    for event in raw_events:
        for exc in _get_exception_values(event):
            key = f"{exc.get('type')}:{exc.get('value')}"
            if key not in seen:
                seen.add(key)
                frames_raw = (exc.get("stacktrace") or {}).get("frames") or []
                source_kind = _infer_source_kind([f for f in frames_raw if isinstance(f, dict)])
                frames = []
                for f in frames_raw:
                    frames.append({
                        "filename": f.get("filename") or f.get("absPath") or f.get("abs_path", ""),
                        "function": f.get("function", "?"),
                        "line": f.get("lineNo") or f.get("lineno") or f.get("line_no", 0),
                        "in_app": _is_in_app_frame(f),
                        "module": f.get("module", ""),
                    })
                exceptions.append({
                    "type": exc.get("type", ""),
                    "message": exc.get("value", ""),
                    "source_kind": source_kind,
                    "frames": frames,
                    "order": order,
                })
                order += 1
    return exceptions


def _extract_event_breadcrumbs(event: dict[str, Any]) -> list[dict[str, Any]]:
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
    return [_normalize_breadcrumb(v) for v in values if isinstance(v, dict)]


def _extract_all_breadcrumbs(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_crumbs: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for event in raw_events:
        values = _extract_event_breadcrumbs(event)
        for crumb in values:
            ts = crumb.get("timestamp", "")
            cat = crumb.get("category", "")
            msg = crumb.get("message", "")
            dedup_key = f"{ts}:{cat}:{msg}"
            if dedup_key not in seen_keys:
                seen_keys.add(dedup_key)
                all_crumbs.append(crumb)
    all_crumbs.sort(key=lambda c: c.get("timestamp", ""))
    return all_crumbs


def _normalize_breadcrumb(crumb: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "timestamp": crumb.get("timestamp", ""),
        "category": crumb.get("category", ""),
        "message": crumb.get("message", ""),
    }
    if crumb.get("level"):
        normalized["level"] = crumb["level"]
    if crumb.get("data"):
        normalized["data"] = crumb["data"]
    return normalized


def _build_exception_chain(exceptions: list[dict[str, Any]], breadcrumbs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    console_errors: list[str] = []
    for crumb in breadcrumbs:
        if crumb.get("category") == "console" and crumb.get("level") == "error":
            console_errors.append(crumb.get("message", ""))

    chain: list[dict[str, Any]] = []
    # 单条 console error 只能证明同一时点出现过线索，不能建立上下游顺序。
    first_error_msg = console_errors[0] if len(console_errors) > 1 else None
    last_error_msg = console_errors[-1] if len(console_errors) > 1 else None

    for exc in exceptions:
        msg = exc.get("message", "")
        exc_type = exc.get("type", "")

        if first_error_msg and msg in first_error_msg:
            role = "upstream_trigger"
            rank = 1
            evidence = ["appears first in breadcrumb console error sequence"]
        elif last_error_msg and msg in last_error_msg:
            role = "direct_crash_point"
            rank = 2
            evidence = ["appears last in breadcrumb console error sequence"]
        else:
            role = "direct_crash_point"
            rank = 2
            evidence = ["observed exception; breadcrumb sequence does not establish upstream causality"]

        if exc.get("source_kind"):
            evidence.append(f"source is {exc['source_kind']}")

        chain.append({
            "rank": rank,
            "type": exc_type,
            "message": msg,
            "role": role,
            "evidence": evidence,
        })

    chain.sort(key=lambda c: c["rank"])
    return chain


def _build_selected_exception_chain(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只在 selected event 内建立异常时序，避免跨 event 拼接因果链。"""
    if not raw_events:
        return []
    selected_event = raw_events[0]
    exceptions = _extract_all_exceptions([selected_event])
    breadcrumbs = _extract_event_breadcrumbs(selected_event)
    return _build_exception_chain(exceptions, breadcrumbs)


def _build_route_context(selected_breadcrumbs: list[dict[str, Any]]) -> dict[str, Any]:
    crash_index = len(selected_breadcrumbs)
    for index, crumb in enumerate(selected_breadcrumbs):
        if crumb.get("level") in {"error", "fatal"} or crumb.get("category") in {"exception", "error"}:
            crash_index = index
            break

    for crumb in reversed(selected_breadcrumbs[:crash_index]):
        if crumb.get("category") == "navigation":
            nav_data = crumb.get("data", {})
            from_route = nav_data.get("from", "")
            to_route = nav_data.get("to", "")
            route = to_route or from_route
            path_only = route.split("?")[0]
            parts = [p for p in path_only.split("/") if p]
            domains = [part.capitalize() for part in parts]
            return {"from": from_route, "to": to_route, "feature_domains": domains}
    return {"from": "", "to": "", "feature_domains": []}


def _build_repo_candidates(exceptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_repos: set[str] = set()
    for exc in exceptions:
        for frame in exc.get("frames", []):
            filename = frame.get("filename", "")
            for prefix, repo in BUNDLE_REPO_MAP.items():
                if filename.startswith(prefix) and repo not in seen_repos:
                    seen_repos.add(repo)
                    func_name = frame.get("function", "")
                    exc_msg = exc.get("message", "")
                    candidates.append({
                        "repo": repo,
                        "reason": f"{prefix} bundle, {func_name} — {exc_msg}",
                        "confidence": 0.9 if exc.get("source_kind") == "ui_library_bundle" else 0.75,
                    })
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


def _repo_for_exception(exception: dict[str, Any]) -> str | None:
    """只映射选中的崩溃帧；无法识别时保留未知，不借用其他调用帧的仓库。"""
    frame = _select_crash_frame(exception.get("frames", []))
    if frame is None:
        return None
    filename = frame.get("filename", "")
    for prefix, repo in BUNDLE_REPO_MAP.items():
        if filename.startswith(prefix):
            return repo
    return None


def _build_fix_boundary(
    exceptions: list[dict[str, Any]],
    exception_chain: list[dict[str, Any]],
) -> dict[str, Any]:
    upstream_repo = None
    downstream_repo = None

    roles = {
        (entry.get("type", ""), entry.get("message", "")): entry.get("role")
        for entry in exception_chain
    }

    for exc in exceptions:
        role = roles.get((exc.get("type", ""), exc.get("message", "")))
        repo = _repo_for_exception(exc)
        if role == "upstream_trigger" and not upstream_repo:
            upstream_repo = repo
        elif role == "direct_crash_point" and not downstream_repo:
            downstream_repo = repo

    return {
        "upstream_repo": upstream_repo,
        "downstream_repo": downstream_repo,
        "recommended_first_fix": (
            f"Investigate the observed direct crash frame in {downstream_repo}; "
            "verify it with sourcemap and source code"
            if downstream_repo else None
        ),
        "recommended_followup_fix": (
            f"Investigate the preceding trigger candidate in {upstream_repo}; "
            "verify event ordering and data flow"
            if upstream_repo else None
        ),
    }


def _build_backend_correlation(breadcrumbs: list[dict[str, Any]]) -> dict[str, Any]:
    failing_requests: list[dict[str, Any]] = []
    for crumb in breadcrumbs:
        if crumb.get("category") not in ("fetch", "xhr", "http"):
            continue
        data = crumb.get("data", {})
        status = data.get("status_code", data.get("statusCode", 0))
        if isinstance(status, int) and status >= 400:
            request = {
                "method": data.get("method", "GET"),
                "url": data.get("url", ""),
                "status_code": status,
                "timestamp": crumb.get("timestamp", ""),
            }
            service = next(
                (
                    data.get(key).strip()
                    for key in ("service", "service.name", "service_name")
                    if isinstance(data.get(key), str) and data.get(key).strip()
                ),
                "",
            )
            if service:
                request["service"] = service
            failing_requests.append(request)

    if not failing_requests:
        return {
            "status": "none",
            "reason": "no failing HTTP before crash",
            "requests": [],
            "datadog_queries": [],
            "datadog_links": [],
        }

    queries: list[str] = []
    for req in failing_requests:
        url_path = req["url"]
        status = req["status_code"]
        terms: list[str] = []
        if req.get("service"):
            service = str(req["service"]).replace("\\", "\\\\").replace('"', '\\"')
            terms.append(f'service:"{service}"')
        terms.append("status:error")
        if url_path:
            escaped_path = str(url_path).replace("\\", "\\\\").replace('"', '\\"')
            terms.append(f'@http.url:"{escaped_path}"')
        terms.append(f"@http.status_code:{status}")
        queries.append(" ".join(terms))

    first_request = failing_requests[0]
    observed_at = f" at {first_request['timestamp']}" if first_request.get("timestamp") else ""

    return {
        "status": "potential",
        "reason": (
            f"HTTP {first_request['status_code']} on {first_request['url']}{observed_at} "
            "observed in breadcrumbs before crash"
        ),
        "requests": failing_requests,
        "datadog_queries": queries,
        "datadog_links": [],
    }


def _build_selected_backend_correlation(raw_events: list[dict[str, Any]]) -> dict[str, Any]:
    """只用 selected event 的 breadcrumbs 建立后端关联。"""
    selected_breadcrumbs = _extract_event_breadcrumbs(raw_events[0]) if raw_events else []
    return _build_backend_correlation(selected_breadcrumbs)


def _build_root_cause_candidates(
    exception_chain: list[dict[str, Any]],
    exceptions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    rank = 1
    repos_by_exception = {
        (exc.get("type", ""), exc.get("message", "")): _repo_for_exception(exc)
        for exc in exceptions
    }
    for exc in exception_chain:
        repo = repos_by_exception.get((exc.get("type", ""), exc.get("message", "")))
        candidates.append({
            "rank": rank,
            "label": f"{exc.get('type', 'Error')}: {exc.get('message', '')[:60]}",
            "confidence": 0.85 if exc.get("role") == "upstream_trigger" else 0.6,
            "repos": [repo] if repo else [],
            "evidence": exc.get("evidence", []),
        })
        rank += 1
    return candidates


# --- Summary and rendering ---

def _build_summary(data: dict[str, Any]) -> dict[str, Any]:
    analysis = data.get("analysis", {})
    issue = data.get("issue", {})
    chain = analysis.get("exception_chain", [])
    fix = analysis.get("fix_boundary", {})
    bc = data.get("backend_correlation", {})

    upstream = next((e for e in chain if e.get("role") == "upstream_trigger"), None)
    crash = next((e for e in chain if e.get("role") == "direct_crash_point"), None)

    upstream_desc = f"{upstream['type']}: {upstream['message']}" if upstream else "N/A"
    crash_desc = f"{crash['type']}: {crash['message']}" if crash else "N/A"

    users = issue.get("users_affected", "?")
    one_line = f"{issue.get('title', 'Unknown crash')}，影响 {users} 用户"

    fix_first = fix.get("recommended_first_fix")
    fix_follow = fix.get("recommended_followup_fix")
    fix_parts = [item for item in (fix_first, fix_follow) if item]
    fix_rec = "；随后 ".join(fix_parts) if fix_parts else "N/A"

    inv_steps: list[str] = []
    route = analysis.get("route_context", {})
    if route.get("from"):
        inv_steps.append(f"1. 用户从 {route['from']} 导航到 {route.get('to', '?')}")
    step = 2
    for exc in chain:
        role_label = "上游触发" if exc.get("role") == "upstream_trigger" else "直接崩溃点"
        inv_steps.append(f"{step}. [{role_label}] {exc.get('type')}: {exc.get('message')}")
        step += 1
    if bc.get("status") != "none":
        inv_steps.append(f"{step}. 后端关联：{bc.get('reason', '')}")

    residual: list[str] = []
    if bc.get("status") == "potential":
        residual.append("后端错误与前端崩溃是否存在因果关系待确认")
    if fix_parts:
        residual.append("repo 与 fix boundary 需要 sourcemap 和源码验证")

    return {
        "one_line": one_line,
        "direct_crash_point": crash_desc,
        "upstream_trigger": upstream_desc,
        "fix_recommendation": fix_rec,
        "investigation_chain": "\n".join(inv_steps),
        "residual_unknowns": residual,
    }


def _render(data: dict[str, Any], target: str) -> str:
    import json as _json
    if target == "json":
        return _json.dumps(data, ensure_ascii=False, indent=2)
    if target == "markdown":
        return _render_markdown(data)
    if target == "slack":
        return _render_slack(data)
    if target == "jira":
        return _render_jira(data)
    if target == "pr":
        return _render_pr(data)
    return _json.dumps(data, ensure_ascii=False, indent=2)


def _render_markdown(data: dict[str, Any]) -> str:
    summary = data.get("summary", {})
    issue = data.get("issue", {})
    analysis = data.get("analysis", {})
    lines = [
        f"# {issue.get('title', 'Sentry Investigation')}",
        "",
        summary.get("one_line", ""),
        "",
        "## Exception Chain",
    ]
    for exc in analysis.get("exception_chain", []):
        role_label = "上游触发" if exc.get("role") == "upstream_trigger" else "直接崩溃点"
        lines.append(f"- **[{role_label}]** {exc.get('type')}: {exc.get('message')}")
    lines.extend([
        "",
        "## Fix Boundary",
        f"- First fix: {analysis.get('fix_boundary', {}).get('recommended_first_fix') or 'N/A'}",
        f"- Follow-up: {analysis.get('fix_boundary', {}).get('recommended_followup_fix') or 'N/A'}",
    ])
    bc = data.get("backend_correlation", {})
    if bc.get("status") != "none":
        lines.extend(["", "## Backend Correlation", f"Status: {bc.get('status')} — {bc.get('reason', '')}"])
        for q in bc.get("datadog_queries", []):
            lines.append(f"- `{q}`")
    return "\n".join(lines)


def _render_slack(data: dict[str, Any]) -> str:
    summary = data.get("summary", {})
    lines = [
        summary.get("one_line", ""),
        "",
        "**:mag: 调查线索**",
        f"- 上游触发：{summary.get('upstream_trigger', 'N/A')}",
        f"- 直接崩溃点：{summary.get('direct_crash_point', 'N/A')}",
        "",
        "**:compass: 建议修复边界**",
        summary.get("fix_recommendation", "N/A"),
    ]
    bc = data.get("backend_correlation", {})
    if bc.get("status") != "none":
        lines.extend(["", "**:link: 后端关联**", bc.get("reason", "")])
    unknowns = summary.get("residual_unknowns", [])
    if unknowns:
        lines.extend(["", "**:question: 待确认**"])
        for u in unknowns:
            lines.append(f"- {u}")
    return "\n".join(lines)


def _render_pr(data: dict[str, Any]) -> str:
    summary = data.get("summary", {})
    issue = data.get("issue", {})
    lines = [
        "## 背景",
        "",
        f"{summary.get('one_line', '')}",
        "",
        f"Sentry Issue: [{issue.get('title', '')}]({issue.get('url', '')})",
        f"影响用户数：{issue.get('users_affected', 'N/A')}",
        "",
        "## 排查过程",
        "",
        summary.get("investigation_chain", "N/A"),
        "",
        "## 根因链",
        "",
    ]
    for rc in data.get("root_cause_candidates", []):
        confidence_pct = int(rc.get("confidence", 0) * 100)
        lines.append(f"- [{confidence_pct}%] {rc.get('label', '')} → {', '.join(rc.get('repos', []))}")
    lines.extend([
        "",
        "## 修复方案选择",
        "",
        summary.get("fix_recommendation", "N/A"),
        "",
        "## 风险说明",
        "",
    ])
    unknowns = summary.get("residual_unknowns", [])
    if unknowns:
        for u in unknowns:
            lines.append(f"- {u}")
    else:
        lines.append("无已知残余风险。")
    return "\n".join(lines)


def _render_jira(data: dict[str, Any]) -> str:
    summary = data.get("summary", {})
    analysis = data.get("analysis", {})
    lines = [
        "## Root Cause",
        "",
        summary.get("one_line", ""),
        "",
    ]
    for exc in analysis.get("exception_chain", []):
        role_label = "Upstream Trigger" if exc.get("role") == "upstream_trigger" else "Direct Crash Point"
        lines.append(f"- *{role_label}*: {exc.get('type')}: {exc.get('message')}")
    lines.extend([
        "",
        "## Solution",
        "",
        summary.get("fix_recommendation", "N/A"),
        "",
        "## Remaining Unknowns",
        "",
    ])
    unknowns = summary.get("residual_unknowns", [])
    if unknowns:
        for u in unknowns:
            lines.append(f"- {u}")
    else:
        lines.append("None identified.")
    return "\n".join(lines)
