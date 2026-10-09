#!/usr/bin/env python3
"""PostHog CLI —— 查询 / 编辑 / 创建。

所有端点抽取自 PostHog 官方 MCP（github.com/PostHog/mcp typescript/src/api/client.ts），
仅依赖 stdlib。覆盖：

    探索 / 验证：
        whoami / list-orgs / list-projects
        list-event-defs / list-property-defs

    HogQL 查询：
        query  →  POST /api/environments/<pid>/query/

    Feature Flag CRUD：
        list-flags / get-flag / create-flag / update-flag

    Insight CRUD：
        list-insights / get-insight / create-insight / update-insight

    Dashboard CRUD：
        list-dashboards / get-dashboard / create-dashboard / update-dashboard
        add-insight-to-dashboard

环境变量（按 .env 加载顺序覆盖）：
    POSTHOG_PERSONAL_API_KEY  必填。phx_ 开头的 personal token。
    POSTHOG_HOST              必填。https://us.i.posthog.com / https://eu.i.posthog.com / 自部署。
    POSTHOG_PROJECT_ID        建议填。多 project 时用来定位；不填会 list-projects 自动选第一个。
    POSTHOG_DOTENV            可选。显式指定 .env 路径。

加载顺序：进程环境 > $POSTHOG_DOTENV > CWD/.env > scripts/.env > skill 根目录 .env。

stdout = 命令结果 JSON
stderr = 提示 / 警告 / 错误，统一前缀 "[posthog] "
退出码：0 成功；2 入参错；3 鉴权或环境配置错；4 PostHog 4xx；5 PostHog 5xx 或网络错。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_HOST = "https://us.i.posthog.com"
PAGE_SIZE = 100

EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_API_4XX = 4
EXIT_API_5XX = 5


# ───────────────────────────── env / dotenv ──────────────────────────────

def _load_dotenv() -> None:
    """从 .env 加载到 os.environ（已存在的不覆盖）。"""
    here = Path(__file__).resolve().parent
    candidates: list[Path] = []
    override = os.environ.get("POSTHOG_DOTENV")
    if override:
        candidates.append(Path(override))
    candidates.extend([
        Path.cwd() / ".env",
        here / ".env",
        here.parent / ".env",  # skill 根目录
    ])
    seen: set[Path] = set()
    for p in candidates:
        try:
            p = p.resolve()
        except OSError:
            continue
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        try:
            text = p.read_text(encoding="utf-8")
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
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


def fail(msg: str, code: int = EXIT_CONFIG) -> "None":
    sys.stderr.write(f"[posthog] {msg}\n")
    sys.exit(code)


def _host() -> str:
    return (os.environ.get("POSTHOG_HOST") or DEFAULT_HOST).rstrip("/")


def _token() -> str:
    t = os.environ.get("POSTHOG_PERSONAL_API_KEY")
    if not t:
        fail("环境变量 POSTHOG_PERSONAL_API_KEY 未设置（personal API key，phx_ 开头）")
    if not t.startswith("phx_"):
        sys.stderr.write("[posthog] 警告：POSTHOG_PERSONAL_API_KEY 通常以 phx_ 开头，当前值可疑\n")
    return t  # type: ignore[return-value]


_PID_CACHE: str | None = None


def _project_id() -> str:
    """解析当前 project_id：优先环境变量，否则查 /api/projects/ 取第一个。"""
    global _PID_CACHE
    if _PID_CACHE:
        return _PID_CACHE
    pid = os.environ.get("POSTHOG_PROJECT_ID")
    if pid:
        _PID_CACHE = str(pid)
        return _PID_CACHE
    data = _http("GET", "/api/projects/")
    results = data.get("results") or []
    if not results:
        fail("POSTHOG_PROJECT_ID 未设置且 /api/projects/ 返回为空；先 list-orgs / list-projects 看看")
    pid = str(results[0]["id"])
    name = results[0].get("name", "")
    sys.stderr.write(f"[posthog] 未设置 POSTHOG_PROJECT_ID，自动选择 project_id={pid} ({name})\n")
    _PID_CACHE = pid
    return pid


# ───────────────────────────── HTTP ──────────────────────────────

def _http(
    method: str,
    path: str,
    *,
    body: Any = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = _host() + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)

    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
        "User-Agent": "winches-skills-posthog/1.0",
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"[posthog] HTTP {e.code} {method} {path}\n{body_text}\n")
        sys.exit(EXIT_API_4XX if 400 <= e.code < 500 else EXIT_API_5XX)
    except urllib.error.URLError as e:
        fail(f"网络错误：{e.reason}", EXIT_API_5XX)


def _paginate(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    max_pages: int = 50,
    stop_at: int | None = None,
) -> list[dict[str, Any]]:
    """跟着 next URL 拉所有结果（PostHog 标准分页协议）。

    stop_at: 累积条数达到后早停（不一定精确等于该值，至少不少于）。
    """
    out: list[dict[str, Any]] = []
    p = dict(params or {})
    p.setdefault("limit", PAGE_SIZE)
    next_path: str | None = path
    pages = 0
    while next_path and pages < max_pages:
        if next_path.startswith("http"):
            parsed = urllib.parse.urlparse(next_path)
            data = _http("GET", parsed.path + (f"?{parsed.query}" if parsed.query else ""))
        else:
            data = _http("GET", next_path, params=p if pages == 0 else None)
        out.extend(data.get("results") or [])
        if stop_at is not None and len(out) >= stop_at:
            break
        next_path = data.get("next")
        pages += 1
    return out


def _print(obj: Any) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2, sort_keys=False)
    sys.stdout.write("\n")


def _read_json_arg(value: str | None, file_value: str | None, *, name: str) -> Any | None:
    if value is not None and file_value is not None:
        fail(f"--{name}-json 与 --{name}-file 二选一", EXIT_USAGE)
    if value is not None:
        return json.loads(value)
    if file_value is not None:
        text = sys.stdin.read() if file_value == "-" else Path(file_value).read_text(encoding="utf-8")
        return json.loads(text)
    return None


def _read_text_arg(value: str | None, file_value: str | None, *, name: str) -> str | None:
    if value is not None and file_value is not None:
        fail(f"--{name} 与 --{name}-file 二选一", EXIT_USAGE)
    if value is not None:
        return value
    if file_value is not None:
        return sys.stdin.read() if file_value == "-" else Path(file_value).read_text(encoding="utf-8")
    return None


# ════════════════════════ identity / discovery ════════════════════════

def cmd_whoami(args: argparse.Namespace) -> None:
    """当前 token 自身信息。MCP: GET /api/personal_api_keys/@current"""
    _print(_http("GET", "/api/personal_api_keys/@current"))


def cmd_list_orgs(args: argparse.Namespace) -> None:
    """列所有组织。MCP: GET /api/organizations/"""
    _print(_http("GET", "/api/organizations/"))


def cmd_list_projects(args: argparse.Namespace) -> None:
    """列项目。MCP: GET /api/organizations/<org>/projects/ 或 GET /api/projects/"""
    if args.org:
        _print(_http("GET", f"/api/organizations/{args.org}/projects/"))
    else:
        _print(_http("GET", "/api/projects/"))


def cmd_list_event_defs(args: argparse.Namespace) -> None:
    """列 event 定义（写 HogQL 查事件名时用）。
    MCP: GET /api/projects/<pid>/event_definitions/?search=<q>
    """
    pid = _project_id()
    results = _paginate(
        f"/api/projects/{pid}/event_definitions/",
        params={"search": args.search} if args.search else None,
    )
    if args.limit:
        results = results[: args.limit]
    _print({"count": len(results), "results": results})


def cmd_list_property_defs(args: argparse.Namespace) -> None:
    """列 property 定义。MCP: GET /api/projects/<pid>/property_definitions/

    type=event 列 event property，type=person 列 person property。
    """
    pid = _project_id()
    params: dict[str, Any] = {
        "type": args.type,
        "search": args.search,
        "exclude_core_properties": "true" if args.exclude_core else None,
        "is_feature_flag": "true" if args.feature_flags_only else None,
        "exclude_hidden": "true",
    }
    if args.event_names:
        params["event_names"] = json.dumps(args.event_names.split(","))
        params["filter_by_event_names"] = "true"
    results = _paginate(f"/api/projects/{pid}/property_definitions/", params=params)
    if args.limit:
        results = results[: args.limit]
    _print({"count": len(results), "results": results})


# ════════════════════════ HogQL query ════════════════════════

def cmd_query(args: argparse.Namespace) -> None:
    """HogQL 查询。MCP: POST /api/environments/<pid>/query/

    注意：MCP 用 environments 而非 projects（PostHog 内部正在迁移）。
    """
    sql = _read_text_arg(args.sql, args.sql_file, name="sql")
    if not sql:
        fail("必须提供 --sql 或 --sql-file", EXIT_USAGE)

    body: dict[str, Any] = {"query": {"kind": "HogQLQuery", "query": sql}}
    if args.refresh:
        body["refresh"] = "blocking"

    pid = _project_id()
    resp = _http("POST", f"/api/environments/{pid}/query/", body=body)

    if args.format == "rows":
        _print({
            "columns": resp.get("columns") or [],
            "row_count": len(resp.get("results") or []),
            "rows": resp.get("results") or [],
        })
    else:
        _print(resp)


# ════════════════════════ feature flags ════════════════════════
# MCP 端点（典型于 typescript/src/api/client.ts 第 620-790 行）：
#   list   GET    /api/projects/<pid>/feature_flags/      （分页拉全量；无 server-side search）
#   get    GET    /api/projects/<pid>/feature_flags/<id>/
#   create POST   /api/projects/<pid>/feature_flags/
#   update PATCH  /api/projects/<pid>/feature_flags/<id>/
#   delete PATCH  /api/projects/<pid>/feature_flags/<id>/  body: {"deleted": true}（软删除）

def cmd_list_flags(args: argparse.Namespace) -> None:
    pid = _project_id()
    params: dict[str, Any] = {"active": args.active}
    # 有 --search 时不能早停（要扫全量后过滤）；无 --search 直接到量就停
    stop_at = None if args.search else args.limit
    results = _paginate(f"/api/projects/{pid}/feature_flags/", params=params, stop_at=stop_at)
    # PostHog 这个端点不支持 server-side search 关键词，匹配 MCP 行为：客户端过滤
    if args.search:
        s = args.search.lower()
        results = [
            f for f in results
            if s in (f.get("key") or "").lower()
            or s in (f.get("name") or "").lower()
        ]
    if args.limit:
        results = results[: args.limit]
    _print({"count": len(results), "results": results})


def _resolve_flag(pid: str, key_or_id: str) -> dict[str, Any]:
    """按数字 id 直接 GET；否则分页拉全量 + 客户端 find（与 MCP findByKey 一致）。"""
    if key_or_id.isdigit():
        return _http("GET", f"/api/projects/{pid}/feature_flags/{key_or_id}/")
    for f in _paginate(f"/api/projects/{pid}/feature_flags/"):
        if f.get("key") == key_or_id:
            # 拉详情确保拿到完整 schema（list 端点会裁字段）
            return _http("GET", f"/api/projects/{pid}/feature_flags/{f['id']}/")
    fail(f"找不到 key 或 id 为 {key_or_id!r} 的 feature flag", EXIT_API_4XX)


def cmd_get_flag(args: argparse.Namespace) -> None:
    _print(_resolve_flag(_project_id(), args.key))


def cmd_create_flag(args: argparse.Namespace) -> None:
    body = _read_json_arg(args.body_json, args.body_file, name="body")
    if body is None:
        if not args.key or not args.name:
            fail("--body-json/--body-file 缺省时，--key 与 --name 必填", EXIT_USAGE)
        rollout = args.rollout if args.rollout is not None else 0
        body = {
            "key": args.key,
            "name": args.name,
            "active": args.active != "false",
            "filters": {
                "groups": [{"properties": [], "rollout_percentage": rollout}],
            },
        }
    _print(_http("POST", f"/api/projects/{_project_id()}/feature_flags/", body=body))


def cmd_update_flag(args: argparse.Namespace) -> None:
    pid = _project_id()
    flag = _resolve_flag(pid, args.key)
    body = _read_json_arg(args.body_json, args.body_file, name="body") or {}
    if args.active is not None:
        body["active"] = args.active == "true"
    if args.name is not None:
        body["name"] = args.name
    if args.rollout is not None:
        body["filters"] = {"groups": [{"properties": [], "rollout_percentage": args.rollout}]}
    if not body:
        fail("没有可更新字段。提供 --active / --name / --rollout / --body-json / --body-file 任一", EXIT_USAGE)
    _print(_http("PATCH", f"/api/projects/{pid}/feature_flags/{flag['id']}/", body=body))


# ════════════════════════ insights ════════════════════════
# MCP 端点（典型于 client.ts 第 793-910 行）：
#   list   GET    /api/projects/<pid>/insights/?limit&offset&search
#                  注意：MCP 源码注释 "search is not implemented as a query parameter"
#                  → PostHog 这个 search 是否生效不稳定，本 CLI 透传后再客户端兜底
#   get-by-id     GET /api/projects/<pid>/insights/<id>/
#   get-by-short  GET /api/projects/<pid>/insights/?short_id=<sid>
#   create POST   /api/projects/<pid>/insights/
#   update PATCH  /api/projects/<pid>/insights/<id>/
#   delete PATCH  /api/projects/<pid>/insights/<id>/  body: {"deleted": true}（软删除）

def cmd_list_insights(args: argparse.Namespace) -> None:
    pid = _project_id()
    params: dict[str, Any] = {
        "search": args.search,
        "saved": "true" if args.saved_only else None,
    }
    # PostHog 上 insights 的 ?search= 是否生效不稳定（MCP 源码注释也提到），不论是否有 --search 都不早停
    stop_at = None if args.search else args.limit
    results = _paginate(f"/api/projects/{pid}/insights/", params=params, stop_at=stop_at)
    if args.search:
        s = args.search.lower()
        results = [
            i for i in results
            if s in (i.get("name") or "").lower()
            or s in (i.get("derived_name") or "").lower()
        ]
    if args.limit:
        results = results[: args.limit]
    _print({"count": len(results), "results": results})


def cmd_get_insight(args: argparse.Namespace) -> None:
    pid = _project_id()
    if args.id.isdigit():
        _print(_http("GET", f"/api/projects/{pid}/insights/{args.id}/"))
        return
    # 视为 short_id
    data = _http("GET", f"/api/projects/{pid}/insights/", params={"short_id": args.id})
    results = data.get("results") or []
    if not results:
        fail(f"找不到 insight {args.id!r}", EXIT_API_4XX)
    _print(results[0])


def cmd_create_insight(args: argparse.Namespace) -> None:
    body = _read_json_arg(args.body_json, args.body_file, name="body")
    if body is None:
        if not args.name or not (args.sql or args.sql_file):
            fail("--body-json/--body-file 缺省时，--name + --sql/--sql-file 必填", EXIT_USAGE)
        sql = args.sql or (sys.stdin.read() if args.sql_file == "-" else Path(args.sql_file).read_text(encoding="utf-8"))
        body = {
            "name": args.name,
            "saved": True,
            "query": {
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": sql},
            },
        }
        if args.dashboard_id:
            body["dashboards"] = [int(args.dashboard_id)]
    _print(_http("POST", f"/api/projects/{_project_id()}/insights/", body=body))


def cmd_update_insight(args: argparse.Namespace) -> None:
    pid = _project_id()
    body = _read_json_arg(args.body_json, args.body_file, name="body") or {}
    if args.name is not None:
        body["name"] = args.name
    if args.sql is not None or args.sql_file is not None:
        sql = args.sql or (sys.stdin.read() if args.sql_file == "-" else Path(args.sql_file).read_text(encoding="utf-8"))
        body["query"] = {
            "kind": "DataVisualizationNode",
            "source": {"kind": "HogQLQuery", "query": sql},
        }
    if not body:
        fail("没有可更新字段。提供 --name / --sql / --body-json / --body-file 任一", EXIT_USAGE)
    _print(_http("PATCH", f"/api/projects/{pid}/insights/{args.id}/", body=body))


# ════════════════════════ dashboards ════════════════════════
# MCP 端点（典型于 client.ts 第 970-1100 行）：
#   list   GET    /api/projects/<pid>/dashboards/?limit&offset&search
#   get    GET    /api/projects/<pid>/dashboards/<id>/
#   create POST   /api/projects/<pid>/dashboards/
#   update PATCH  /api/projects/<pid>/dashboards/<id>/
#   delete PATCH  /api/projects/<pid>/dashboards/<id>/  body: {"deleted": true}（软删除）
#   addInsight    PATCH /api/projects/<pid>/insights/<insight_id>/  body: {"dashboards": [<dashboard_id>]}
#                  ⚠ MCP 实现会"覆盖" insight 的 dashboards 列表；本 CLI 改为"追加"以避免误解关联

def cmd_list_dashboards(args: argparse.Namespace) -> None:
    pid = _project_id()
    params: dict[str, Any] = {"search": args.search}
    stop_at = None if args.search else args.limit
    results = _paginate(f"/api/projects/{pid}/dashboards/", params=params, stop_at=stop_at)
    if args.search:
        s = args.search.lower()
        results = [
            d for d in results
            if s in (d.get("name") or "").lower()
            or s in (d.get("description") or "").lower()
        ]
    if args.limit:
        results = results[: args.limit]
    _print({"count": len(results), "results": results})


def cmd_get_dashboard(args: argparse.Namespace) -> None:
    _print(_http("GET", f"/api/projects/{_project_id()}/dashboards/{args.id}/"))


def cmd_create_dashboard(args: argparse.Namespace) -> None:
    body = _read_json_arg(args.body_json, args.body_file, name="body")
    if body is None:
        if not args.name:
            fail("--body-json/--body-file 缺省时 --name 必填", EXIT_USAGE)
        body = {"name": args.name}
        if args.description:
            body["description"] = args.description
    _print(_http("POST", f"/api/projects/{_project_id()}/dashboards/", body=body))


def cmd_update_dashboard(args: argparse.Namespace) -> None:
    pid = _project_id()
    body = _read_json_arg(args.body_json, args.body_file, name="body") or {}
    if args.name is not None:
        body["name"] = args.name
    if args.description is not None:
        body["description"] = args.description
    if not body:
        fail("没有可更新字段。提供 --name / --description / --body-json / --body-file 任一", EXIT_USAGE)
    _print(_http("PATCH", f"/api/projects/{pid}/dashboards/{args.id}/", body=body))


def cmd_add_insight(args: argparse.Namespace) -> None:
    """把 insight 挂到 dashboard 上。

    MCP 实现是 PATCH dashboards: [<id>]，**会覆盖**已挂的其他 dashboard。
    本 CLI 改为先 GET 拿当前 dashboards 列表 → append → PATCH，**追加而不覆盖**。
    用 --replace 切回 MCP 行为（覆盖）。
    """
    pid = _project_id()
    did = int(args.dashboard_id)
    if args.replace:
        dashboards = [did]
    else:
        insight = _http("GET", f"/api/projects/{pid}/insights/{args.insight_id}/")
        dashboards = list(insight.get("dashboards") or [])
        if did in dashboards:
            sys.stderr.write(f"[posthog] insight {args.insight_id} 已在 dashboard {did} 上，跳过\n")
            _print(insight)
            return
        dashboards.append(did)
    _print(_http(
        "PATCH",
        f"/api/projects/{pid}/insights/{args.insight_id}/",
        body={"dashboards": dashboards},
    ))


# ────────────────────────── argparse ──────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="posthog", description="PostHog CLI（query / 编辑 / 创建）")
    sub = p.add_subparsers(dest="command", metavar="<subcommand>")
    sub.required = True

    # ── identity / discovery ──
    sub.add_parser("whoami", help="当前 personal API key 的所有者 / scope").set_defaults(func=cmd_whoami)
    sub.add_parser("list-orgs", help="列出所有 organization").set_defaults(func=cmd_list_orgs)

    lp = sub.add_parser("list-projects", help="列出 project（不传 --org 则列当前 token 可访问的所有）")
    lp.add_argument("--org", help="organization id；不传走 /api/projects/")
    lp.set_defaults(func=cmd_list_projects)

    le = sub.add_parser("list-event-defs", help="列 event 定义（写 HogQL 查事件名）")
    le.add_argument("--search", help="按名称模糊搜索（PostHog server-side）")
    le.add_argument("--limit", type=int, help="限定返回条数")
    le.set_defaults(func=cmd_list_event_defs)

    lpd = sub.add_parser("list-property-defs", help="列 property 定义（event / person）")
    lpd.add_argument("--type", choices=["event", "person"], default="event")
    lpd.add_argument("--search")
    lpd.add_argument("--event-names", help="逗号分隔的事件名，仅返回这些事件用过的 property")
    lpd.add_argument("--exclude-core", action="store_true", help="排除 PostHog 内置 $* 属性")
    lpd.add_argument("--feature-flags-only", action="store_true")
    lpd.add_argument("--limit", type=int)
    lpd.set_defaults(func=cmd_list_property_defs)

    # ── query ──
    q = sub.add_parser("query", help="跑 HogQL 查询")
    q.add_argument("--sql")
    q.add_argument("--sql-file", help="从文件读 HogQL，- 表示 stdin")
    q.add_argument("--refresh", action="store_true", help="强制刷新（refresh=blocking）")
    q.add_argument("--format", choices=["raw", "rows"], default="rows")
    q.set_defaults(func=cmd_query)

    # ── flags ──
    lf = sub.add_parser("list-flags", help="列出 feature flag")
    lf.add_argument("--active", choices=["true", "false", "STALE"])
    lf.add_argument("--search", help="客户端模糊匹配 key/name")
    lf.add_argument("--limit", type=int, default=100)
    lf.set_defaults(func=cmd_list_flags)

    gf = sub.add_parser("get-flag", help="按 key 或 id 查 flag")
    gf.add_argument("key")
    gf.set_defaults(func=cmd_get_flag)

    cf = sub.add_parser("create-flag", help="创建 flag")
    cf.add_argument("--key")
    cf.add_argument("--name")
    cf.add_argument("--rollout", type=int, help="0-100 全员百分比")
    cf.add_argument("--active", choices=["true", "false"], default="true")
    cf.add_argument("--body-json")
    cf.add_argument("--body-file")
    cf.set_defaults(func=cmd_create_flag)

    uf = sub.add_parser("update-flag", help="改 flag（按 key 或 id 定位）")
    uf.add_argument("key")
    uf.add_argument("--active", choices=["true", "false"])
    uf.add_argument("--name")
    uf.add_argument("--rollout", type=int)
    uf.add_argument("--body-json")
    uf.add_argument("--body-file")
    uf.set_defaults(func=cmd_update_flag)

    # ── insights ──
    li = sub.add_parser("list-insights", help="列出 insight")
    li.add_argument("--search")
    li.add_argument("--saved-only", action="store_true")
    li.add_argument("--limit", type=int, default=50)
    li.set_defaults(func=cmd_list_insights)

    gi = sub.add_parser("get-insight", help="按 id 或 short_id 查 insight")
    gi.add_argument("id")
    gi.set_defaults(func=cmd_get_insight)

    ci = sub.add_parser("create-insight", help="创建 insight（默认 HogQL 类型）")
    ci.add_argument("--name")
    ci.add_argument("--sql")
    ci.add_argument("--sql-file")
    ci.add_argument("--dashboard-id", help="创建后挂到指定 dashboard")
    ci.add_argument("--body-json")
    ci.add_argument("--body-file")
    ci.set_defaults(func=cmd_create_insight)

    ui = sub.add_parser("update-insight", help="改 insight")
    ui.add_argument("id")
    ui.add_argument("--name")
    ui.add_argument("--sql")
    ui.add_argument("--sql-file")
    ui.add_argument("--body-json")
    ui.add_argument("--body-file")
    ui.set_defaults(func=cmd_update_insight)

    # ── dashboards ──
    ld = sub.add_parser("list-dashboards", help="列出 dashboard")
    ld.add_argument("--search")
    ld.add_argument("--limit", type=int, default=50)
    ld.set_defaults(func=cmd_list_dashboards)

    gd = sub.add_parser("get-dashboard", help="按 id 查 dashboard")
    gd.add_argument("id")
    gd.set_defaults(func=cmd_get_dashboard)

    cd = sub.add_parser("create-dashboard", help="创建 dashboard")
    cd.add_argument("--name")
    cd.add_argument("--description")
    cd.add_argument("--body-json")
    cd.add_argument("--body-file")
    cd.set_defaults(func=cmd_create_dashboard)

    ud = sub.add_parser("update-dashboard", help="改 dashboard")
    ud.add_argument("id")
    ud.add_argument("--name")
    ud.add_argument("--description")
    ud.add_argument("--body-json")
    ud.add_argument("--body-file")
    ud.set_defaults(func=cmd_update_dashboard)

    ai = sub.add_parser(
        "add-insight-to-dashboard",
        help="把 insight 挂到 dashboard 上（默认追加，不覆盖已挂）",
    )
    ai.add_argument("dashboard_id")
    ai.add_argument("insight_id")
    ai.add_argument("--replace", action="store_true",
                    help="走 MCP 行为：覆盖 insight.dashboards = [<id>]，会摘掉其他 dashboard 的关联")
    ai.set_defaults(func=cmd_add_insight)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        args.func(args)
        return 0
    except KeyboardInterrupt:
        sys.stderr.write("[posthog] 已中断\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
