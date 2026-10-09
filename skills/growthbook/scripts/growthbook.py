#!/usr/bin/env python3
"""GrowthBook CLI — 统一入口。

环境变量：
    GROWTHBOOK_API_TOKEN       管理命令必填。Bearer token，作为 Authorization 头。
    GROWTHBOOK_API_BASE_URL    Management API 地址，默认 https://api.growthbook.io。
    GROWTHBOOK_SDK_API_HOST    eval-feature 必填。SDK Connection API host；自托管时可能与 Management API host 相同。
    GROWTHBOOK_SDK_CLIENT_KEY  eval-feature 必填。SDK Connection client key。

兼容旧配置：GB_TOKEN / GB_APP_ORIGIN / GB_DOTENV。新变量优先。

用法：
    python3 growthbook.py <subcommand> [flags]

子命令：
    get-environments
    get-projects
    resolve-project-id        --project <nameOrId>
    create-feature-flag       --body-file <path|-> | --body-json <json>
    create-force-rule         --feature-id <id> --env <env> --value <v>
                              [--condition <json>] [--description <text>]
                              [--enabled true|false] [--id <ruleId>]
    eval-feature              --feature-id <id> --attributes-json <json>
    get-feature-flags         [--feature-flag-id <id>] [--project <nameOrId>]
                              [--q <keyword>] [--all] [--limit <n>]
    list-feature-keys         [--project-id <id>]
    get-experiments           [--experiment-id <id>] [--mode full|summary]
    get-attributes
    get-metrics               [--metric-id <id>] [--project-id <id>]
                              （metric-id 以 "fact__" 前缀区分 fact metric）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_API_BASE_URL = "https://api.growthbook.io"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_SDK_TIMEOUT_MS = 10_000
DEFAULT_PAGE_SIZE = 100


def _load_dotenv() -> None:
    """从 .env 加载环境变量（已存在的变量不覆盖）。

    查找顺序：
        1. $GROWTHBOOK_DOTENV 或 $GB_DOTENV（若设置，新变量优先）
        2. CWD/.env
        3. <script_dir>/.env
        4. <script_dir>/../.env      （skill 根目录）
    仅支持 KEY=VALUE 行，忽略注释和空行；支持 "KEY=value"、"KEY='value'"、"KEY=\"value\""。
    不依赖任何第三方库。
    """
    import pathlib

    here = pathlib.Path(__file__).resolve().parent
    candidates: list[pathlib.Path] = []
    override = os.environ.get("GROWTHBOOK_DOTENV") or os.environ.get("GB_DOTENV")
    if override:
        candidates.append(pathlib.Path(override))
    candidates.extend(
        [
            pathlib.Path.cwd() / ".env",
            here / ".env",
            here.parent / ".env",
        ]
    )
    seen: set[pathlib.Path] = set()
    for path in candidates:
        try:
            path = path.resolve()
        except OSError:
            continue
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if (len(value) >= 2) and (
                (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
            ):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


def fail(msg: str) -> "None":
    sys.stderr.write(f"[growthbook] {msg}\n")
    sys.exit(1)


def origin() -> str:
    return (
        os.environ.get("GROWTHBOOK_API_BASE_URL")
        or os.environ.get("GB_APP_ORIGIN")
        or DEFAULT_API_BASE_URL
    )


def token() -> str:
    t = os.environ.get("GROWTHBOOK_API_TOKEN") or os.environ.get("GB_TOKEN")
    if not t:
        fail("环境变量 GROWTHBOOK_API_TOKEN 未设置")
    return t  # type: ignore[return-value]


def parse_flags(argv: list[str]) -> tuple[str, dict[str, Any]]:
    sub = argv[0] if argv else ""
    flags: dict[str, Any] = {}
    i = 1
    while i < len(argv):
        a = argv[i]
        if not a.startswith("--"):
            i += 1
            continue
        key = a[2:]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if nxt is None or nxt.startswith("--"):
            flags[key] = True
            i += 1
        else:
            flags[key] = nxt
            i += 2
    return sub, flags


def get_str(flags: dict[str, Any], key: str) -> str | None:
    v = flags.get(key)
    return v if isinstance(v, str) else None


def require_str(flags: dict[str, Any], key: str) -> str:
    v = get_str(flags, key)
    if not v:
        fail(f"缺少必填参数 --{key}")
    return v  # type: ignore[return-value]


def require_str_any(flags: dict[str, Any], *keys: str) -> str:
    for key in keys:
        v = get_str(flags, key)
        if v:
            return v
    rendered = "/".join(f"--{key}" for key in keys)
    fail(f"缺少必填参数 {rendered}")


def _missing_eval_config() -> str:
    return (
        "缺少 SDK eval 配置：请设置 GROWTHBOOK_SDK_API_HOST 和 "
        "GROWTHBOOK_SDK_CLIENT_KEY"
    )


def _require_sdk_env() -> None:
    if not os.environ.get("GROWTHBOOK_SDK_API_HOST") or not os.environ.get(
        "GROWTHBOOK_SDK_CLIENT_KEY"
    ):
        fail(_missing_eval_config())


def eval_timeout_ms(flags: dict[str, Any]) -> int:
    raw = get_str(flags, "sdk-timeout-ms") or os.environ.get("GROWTHBOOK_SDK_TIMEOUT_MS")
    if not raw:
        return DEFAULT_SDK_TIMEOUT_MS
    try:
        timeout = int(raw)
    except ValueError:
        fail("GROWTHBOOK_SDK_TIMEOUT_MS 必须是正整数")
    if timeout <= 0:
        fail("GROWTHBOOK_SDK_TIMEOUT_MS 必须是正整数")
    return timeout


def _read_json_object(raw: str | None, flag_name: str) -> dict[str, Any]:
    if raw is None:
        fail(f"缺少必填参数 --{flag_name}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        fail(f"--{flag_name} 必须是 JSON object")
    if not isinstance(parsed, dict):
        fail(f"--{flag_name} 必须是 JSON object")
    return parsed


def _redact_secrets(text: str) -> str:
    redacted = text
    for key in (
        "GROWTHBOOK_API_TOKEN",
        "GB_TOKEN",
        "GROWTHBOOK_SDK_CLIENT_KEY",
        "GROWTHBOOK_SDK_API_HOST",
    ):
        value = os.environ.get(key)
        if value:
            redacted = redacted.replace(value, f"<redacted:{key}>")
    return redacted


def _node_bin() -> str:
    return os.environ.get("GROWTHBOOK_NODE_BIN") or "node"


def _sdk_script_path() -> Path:
    return Path(__file__).resolve().with_name("growthbook-sdk-eval.mjs")


def gb(method: str, path: str, body: Any = None) -> Any:
    url = f"{origin()}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        fail(f"{method} {path} 失败 {e.code}: {err_body}")
    except urllib.error.URLError as e:
        fail(f"{method} {path} 网络错误: {e}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def out(data: Any) -> None:
    if isinstance(data, str):
        sys.stdout.write(data)
    else:
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")


def fetch_all_paged(
    base_path: str,
    query: dict[str, str] | None = None,
    overall_limit: int | None = None,
) -> list[Any]:
    query = dict(query or {})
    out_list: list[Any] = []
    offset = 0
    while True:
        remaining = None if overall_limit is None else overall_limit - len(out_list)
        if remaining is not None and remaining <= 0:
            break
        page_limit = min(DEFAULT_PAGE_SIZE, remaining) if remaining is not None else DEFAULT_PAGE_SIZE
        q = dict(query)
        q["limit"] = str(page_limit)
        q["offset"] = str(offset)
        qs = urllib.parse.urlencode(q)
        page = gb("GET", f"{base_path}?{qs}")
        items = (
            page.get("features")
            or page.get("items")
            or page.get("experiments")
            or page.get("metrics")
            or page.get("factMetrics")
            or page.get("projects")
            or page.get("environments")
            or page.get("attributes")
            or page.get("data")
            or []
            if isinstance(page, dict)
            else []
        )
        if remaining is not None:
            items = list(items)[:remaining]
        out_list.extend(items)
        has_more = (
            page.get("hasMore") if isinstance(page, dict) and "hasMore" in page
            else len(items) == page_limit
        )
        if not has_more or not items:
            break
        offset += len(items)
        if offset > 10000:
            break
    return out_list


def _normalize_collection_response(data: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _bool_literal(raw: str, flag_name: str) -> bool:
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    fail(f"--{flag_name} 对 boolean 类型只接受 true 或 false")


def _serialize_rule_value(feature: dict[str, Any], raw_value: str) -> str:
    vtype = feature.get("valueType") or feature.get("type")
    if vtype == "boolean":
        return "true" if _bool_literal(raw_value, "value") else "false"
    if vtype == "number":
        try:
            float(raw_value)
        except ValueError:
            fail("--value 对 number 类型必须是合法数字")
        return raw_value
    if vtype == "json":
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            fail("--value 对 json 类型必须是合法 JSON 字符串")
        return json.dumps(parsed, ensure_ascii=False)
    return raw_value


def _build_force_rule_payload(feature: dict[str, Any], flags: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    feature_id = require_str(flags, "feature-id")
    env = require_str(flags, "env")
    raw_value = require_str(flags, "value")
    description = get_str(flags, "description") or ""
    rule_id = get_str(flags, "id")
    enabled_str = get_str(flags, "enabled")
    enabled = True if enabled_str is None else _bool_literal(enabled_str, "enabled")
    condition_str = get_str(flags, "condition")

    value = _serialize_rule_value(feature, raw_value)
    rule: dict[str, Any] = {
        "type": "force",
        "description": description,
        "enabled": enabled,
        "value": value,
        "coverage": 1,
        "savedGroups": [],
        "savedGroupTargeting": [],
        "prerequisites": [],
    }
    if rule_id:
        rule["id"] = rule_id
    if condition_str:
        try:
            cond_obj = json.loads(condition_str)
        except json.JSONDecodeError:
            fail("--condition 必须是合法 JSON")
        rule["condition"] = json.dumps(cond_obj, ensure_ascii=False)
    else:
        rule["condition"] = ""

    envs_raw = dict(feature.get("environments") or {})
    cur = dict(envs_raw.get(env) or {})
    rules = list(cur.get("rules") or [])
    idx = -1
    if rule_id:
        for i, existing_rule in enumerate(rules):
            if isinstance(existing_rule, dict) and existing_rule.get("id") == rule_id:
                idx = i
                break
    if idx >= 0:
        rules[idx] = {**rules[idx], **rule}
        rule_diff = {"action": "replace", "rule_id": rule_id}
    else:
        rules.append(rule)
        rule_diff = {"action": "append", "rule_id": rule_id}

    env_payload: dict[str, Any] = {"rules": rules}
    if "enabled" in cur:
        env_payload["enabled"] = cur["enabled"]
    if "defaultValue" in cur:
        env_payload["defaultValue"] = cur["defaultValue"]

    return feature_id, env, {"environments": {env: env_payload}}, rule_diff


def _dry_run_output(method: str, endpoint: str, payload: Any, **extra: Any) -> None:
    body = {
        "dry_run": True,
        "method": method,
        "endpoint": endpoint,
        "payload": payload,
    }
    body.update(extra)
    out(body)


def _projects_list() -> list[dict[str, Any]]:
    data = gb("GET", "/api/v1/projects")
    return _normalize_collection_response(data, ("projects", "items", "data"))  # type: ignore[return-value]


def _resolve_project(project: str) -> dict[str, Any]:
    projects = _projects_list()
    hit = next((p for p in projects if p.get("id") == project), None)
    if not hit:
        hit = next(
            (
                p
                for p in projects
                if isinstance(p.get("name"), str)
                and p["name"].lower() == project.lower()
            ),
            None,
        )
    if not hit:
        fail(f"未找到 project: {project}")
    return hit  # type: ignore[return-value]


# —— 子命令 ——

def cmd_get_environments(_: dict[str, Any]) -> None:
    out(gb("GET", "/api/v1/environments"))


def cmd_get_projects(_: dict[str, Any]) -> None:
    out(gb("GET", "/api/v1/projects"))


def cmd_resolve_project_id(flags: dict[str, Any]) -> None:
    p = _resolve_project(require_str(flags, "project"))
    out({"id": p.get("id"), "name": p.get("name")})


def _read_body(flags: dict[str, Any]) -> Any:
    file = get_str(flags, "body-file")
    js = get_str(flags, "body-json")
    if file:
        if file == "-":
            text = sys.stdin.read()
        else:
            with open(file, "r", encoding="utf-8") as f:
                text = f.read()
        return json.loads(text)
    if js:
        return json.loads(js)
    fail("需要通过 --body-file <path|-> 或 --body-json <json> 提供请求体")


def cmd_create_feature_flag(flags: dict[str, Any]) -> None:
    body = _read_body(flags)
    if not flags.get("execute"):
        _dry_run_output("POST", "/api/v1/features", body)
        return
    out(gb("POST", "/api/v1/features", body))


def cmd_create_force_rule(flags: dict[str, Any]) -> None:
    feature_id = require_str(flags, "feature-id")
    current = gb(
        "GET", f"/api/v1/features/{urllib.parse.quote(feature_id, safe='')}"
    )
    feature = current.get("feature", current) if isinstance(current, dict) else {}
    feature_id, env, payload, rule_diff = _build_force_rule_payload(feature, flags)
    endpoint = f"/api/v1/features/{urllib.parse.quote(feature_id, safe='')}"
    if not flags.get("execute"):
        _dry_run_output(
            "POST",
            endpoint,
            payload,
            feature_id=feature_id,
            environment=env,
            rule_diff=rule_diff,
        )
        return
    updated = gb("POST", endpoint, payload)
    out(updated)


def cmd_eval_feature(flags: dict[str, Any]) -> None:
    feature_id = require_str(flags, "feature-id")
    input_attributes = _read_json_object(get_str(flags, "attributes-json"), "attributes-json")
    _require_sdk_env()

    request_body: dict[str, Any] = {
        "featureId": feature_id,
        "attributes": input_attributes,
        "raw": bool(flags.get("raw")),
        "timeoutMs": eval_timeout_ms(flags),
    }
    url = get_str(flags, "url")
    if url:
        request_body["url"] = url
    command = [_node_bin(), str(_sdk_script_path())]
    try:
        proc = subprocess.run(
            command,
            input=json.dumps(request_body, ensure_ascii=False),
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        fail(f"找不到 Node runtime：{_node_bin()}")
    except subprocess.CalledProcessError as e:
        message = (e.stderr or e.stdout or "").strip().splitlines()
        preview = message[0] if message else "(no output)"
        fail(f"SDK eval 失败: {_redact_secrets(preview)}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail("SDK eval 返回非 JSON")
    out(payload)


def _fetch_filtered_feature_flags(
    project_id: str | None,
    keyword: str,
    requested_limit: int | None,
) -> list[dict[str, Any]]:
    offset = 0
    matches: list[dict[str, Any]] = []
    lowered_keyword = keyword.lower()
    while True:
        remaining = None if requested_limit is None else requested_limit - len(matches)
        if remaining is not None and remaining <= 0:
            break
        page_limit = min(DEFAULT_PAGE_SIZE, remaining) if remaining is not None else DEFAULT_PAGE_SIZE
        query: dict[str, str] = {"limit": str(page_limit), "offset": str(offset)}
        if project_id:
            query["projectId"] = project_id
        page = gb("GET", f"/api/v1/features?{urllib.parse.urlencode(query)}")
        items = _normalize_collection_response(page, ("features", "items", "data"))
        if not items:
            break
        for feature in items:
            if not isinstance(feature, dict):
                continue
            tags = feature.get("tags") or []
            hay_parts = [
                str(feature.get("id") or ""),
                str(feature.get("description") or ""),
                str(feature.get("owner") or ""),
            ] + [str(tag) for tag in tags if isinstance(tag, (str, int))]
            if lowered_keyword in " ".join(hay_parts).lower():
                matches.append(feature)
                if requested_limit is not None and len(matches) >= requested_limit:
                    return matches
        has_more = page.get("hasMore") if isinstance(page, dict) and "hasMore" in page else len(items) == page_limit
        if not has_more:
            break
        offset += len(items)
        if offset > 10000:
            break
    return matches

def cmd_get_feature_flags(flags: dict[str, Any]) -> None:
    fid = get_str(flags, "feature-flag-id")
    if fid:
        out(gb("GET", f"/api/v1/features/{urllib.parse.quote(fid, safe='')}"))
        return
    project = get_str(flags, "project")
    q = get_str(flags, "q")
    limit = get_str(flags, "limit")
    all_flag = bool(flags.get("all"))

    project_id: str | None = None
    if project:
        project_id = _resolve_project(project).get("id")

    requested_limit = int(limit) if limit else None
    if q:
        result = _fetch_filtered_feature_flags(project_id, q, requested_limit)
        out({"features": result, "total": len(result)})
        return
    if all_flag:
        result = fetch_all_paged(
            "/api/v1/features",
            {"projectId": project_id} if project_id else {},
            overall_limit=requested_limit,
        )
        out({"features": result, "total": len(result)})
        return

    qs_dict: dict[str, str] = {}
    if project_id:
        qs_dict["projectId"] = project_id
    if limit:
        qs_dict["limit"] = limit
    suffix = f"?{urllib.parse.urlencode(qs_dict)}" if qs_dict else ""
    out(gb("GET", f"/api/v1/features{suffix}"))


def cmd_list_feature_keys(flags: dict[str, Any]) -> None:
    pid = get_str(flags, "project-id")
    suffix = f"?projectId={urllib.parse.quote(pid, safe='')}" if pid else ""
    out(gb("GET", f"/api/v1/feature-keys{suffix}"))


def cmd_get_experiments(flags: dict[str, Any]) -> None:
    eid = get_str(flags, "experiment-id")
    mode = get_str(flags, "mode") or "summary"
    if eid:
        detail = gb(
            "GET", f"/api/v1/experiments/{urllib.parse.quote(eid, safe='')}"
        )
        if mode == "full":
            results = gb(
                "GET",
                f"/api/v1/experiments/{urllib.parse.quote(eid, safe='')}/results",
            )
            experiment = (
                detail.get("experiment", detail)
                if isinstance(detail, dict)
                else detail
            )
            out({"experiment": experiment, "results": results})
            return
        out(detail)
        return
    out(gb("GET", "/api/v1/experiments"))


def cmd_get_attributes(_: dict[str, Any]) -> None:
    out(gb("GET", "/api/v1/attributes?limit=100"))


def cmd_get_metrics(flags: dict[str, Any]) -> None:
    mid = get_str(flags, "metric-id")
    pid = get_str(flags, "project-id")
    if mid:
        if mid.startswith("fact__"):
            raw = mid[len("fact__"):]
            out(
                gb(
                    "GET",
                    f"/api/v1/fact-metrics/{urllib.parse.quote(raw, safe='')}",
                )
            )
        else:
            out(
                gb("GET", f"/api/v1/metrics/{urllib.parse.quote(mid, safe='')}")
            )
        return
    qs = f"?projectId={urllib.parse.quote(pid, safe='')}" if pid else ""
    metrics = _normalize_collection_response(
        gb("GET", f"/api/v1/metrics{qs}"),
        ("metrics", "items", "data"),
    )
    fact_metrics = _normalize_collection_response(
        gb("GET", f"/api/v1/fact-metrics{qs}"),
        ("factMetrics", "metrics", "items", "data"),
    )
    out({"metrics": metrics, "factMetrics": fact_metrics})


TABLE = {
    "get-environments": cmd_get_environments,
    "get-projects": cmd_get_projects,
    "resolve-project-id": cmd_resolve_project_id,
    "create-feature-flag": cmd_create_feature_flag,
    "create-force-rule": cmd_create_force_rule,
    "eval-feature": cmd_eval_feature,
    "get-feature-flags": cmd_get_feature_flags,
    "list-feature-keys": cmd_list_feature_keys,
    "get-experiments": cmd_get_experiments,
    "get-attributes": cmd_get_attributes,
    "get-metrics": cmd_get_metrics,
}


def main() -> None:
    sub, flags = parse_flags(sys.argv[1:])
    fn = TABLE.get(sub)
    if not fn:
        sys.stderr.write(
            "用法: python3 growthbook.py <subcommand> [flags]\n"
            f"可用: {', '.join(TABLE.keys())}\n"
        )
        sys.exit(1 if sub else 0)
    fn(flags)


if __name__ == "__main__":
    main()
