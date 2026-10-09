"""get-dependencies: extract upstream/downstream service dependencies."""
from __future__ import annotations

import sys
from typing import Any

from dd.client import DatadogClient
from dd.formatter import output
from dd.timeutil import parse_time_to_unix_seconds

NAME = "get-dependencies"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="查询服务上下游依赖")
    p.add_argument("service", help="服务名，如 moego-svc-payment")
    p.add_argument("--env", help="环境标签，默认 DD_DEFAULT_ENV/ns-production")
    p.add_argument("--from", default="1h", dest="from_time", help="起始时间，默认 1h")
    p.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    p.add_argument("--format", dest="fmt", choices=["json", "human", "summary"], default="json")
    p.set_defaults(_handler=run)


def build_params(args, default_env: str) -> dict[str, Any]:
    return {
        "start": parse_time_to_unix_seconds(args.from_time),
        "end": parse_time_to_unix_seconds(args.to_time),
        "env": args.env or default_env,
    }


def _as_service_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                name = item.get("service") or item.get("name") or item.get("service_name")
                if name:
                    result.append(str(name))
        return result
    if isinstance(value, dict):
        return [str(key) for key in value.keys()]
    return []


def _edge_value(edge: dict[str, Any], *keys: str) -> str | None:
    attr = edge.get("attributes", {}) if isinstance(edge.get("attributes"), dict) else {}
    for key in keys:
        for source in (edge, attr):
            value = source.get(key)
            if value:
                return str(value)
    return None


def _node_calls(node: Any) -> list[str]:
    """Return the explicit call list from a service-graph node."""
    if not isinstance(node, dict):
        return []
    for key in ("calls", "calls_to", "downstream", "dependencies"):
        value = node.get(key)
        if isinstance(value, list):
            return _as_service_list(value)
    return []


def _node_called_by(node: Any) -> list[str]:
    if not isinstance(node, dict):
        return []
    for key in ("called_by", "upstream", "callers"):
        value = node.get(key)
        if isinstance(value, list):
            return _as_service_list(value)
    return []


def _extract_from_edges(edges: list[Any], service: str) -> tuple[list[str], list[str]]:
    upstream: set[str] = set()
    downstream: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = _edge_value(edge, "source", "src", "caller", "parent", "from", "service")
        target = _edge_value(edge, "target", "dst", "callee", "child", "to", "dependency")
        if source == service and target:
            downstream.add(target)
        if target == service and source:
            upstream.add(source)
    return sorted(upstream), sorted(downstream)


def extract_dependencies(body: Any, service: str) -> dict[str, Any]:
    """Datadog `/api/v1/service_dependencies` 真实形态：

        {
            "<service>": {"calls": ["<downstream>", ...]},
            ...
        }

    `calls` 表示该服务调用的下游。反向调用方需要遍历整张图，把
    任何 `calls` 包含 `service` 的节点视为 upstream（caller）。
    """
    raw = body.get("data", body) if isinstance(body, dict) else body
    upstream: set[str] = set()
    downstream: set[str] = set()

    if isinstance(raw, dict):
        node = raw.get(service)
        downstream.update(_node_calls(node))
        upstream.update(_node_called_by(node))
        for source, target_info in raw.items():
            if source == service:
                continue
            if service in _node_calls(target_info):
                upstream.add(str(source))

    if isinstance(raw, list):
        up, down = _extract_from_edges(raw, service)
        upstream.update(up)
        downstream.update(down)

    upstream.discard(service)
    downstream.discard(service)
    dependencies = upstream | downstream
    return {
        "upstream": sorted(upstream),
        "downstream": sorted(downstream),
        "dependencies": sorted(dependencies),
        "raw": body,
    }


def _render_human(result: dict[str, Any]) -> None:
    sys.stderr.write("upstream:\n")
    for item in result.get("upstream", []):
        sys.stderr.write(f"  {item}\n")
    sys.stderr.write("downstream:\n")
    for item in result.get("downstream", []):
        sys.stderr.write(f"  {item}\n")


def run(args, config) -> int:
    params = build_params(args, config.default_env)
    sys.stderr.write(
        f"[get-dependencies] service={args.service} env={params['env']} "
        f"from={args.from_time} to={args.to_time}\n"
    )
    body = DatadogClient(config).get("/api/v1/service_dependencies", params=params)
    extracted = extract_dependencies(body, args.service)
    result = {
        "service": args.service,
        "env": params["env"],
        "from": args.from_time,
        "to": args.to_time,
        "start": params["start"],
        "end": params["end"],
        **extracted,
    }
    if args.fmt == "human":
        _render_human(result)
    output(result, fmt=args.fmt)
    return 0
