"""get-dependencies: extract upstream/downstream service dependencies."""
from __future__ import annotations

from typing import Any

from dd_v3.errors import ApiError
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import parse_time_to_unix_seconds

NAME = "get-dependencies"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="查询服务上下游依赖")
    p.add_argument("service", help="服务名，如 moego-svc-payment")
    p.add_argument("--env", help="环境标签，默认 DD_DEFAULT_ENV/ns-production")
    p.add_argument("--from", default="1h", dest="from_time", help="起始时间，默认 1h")
    p.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    p.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    p.set_defaults(_handler=run, _policy=READ)


def build_params(args, default_env: str) -> dict[str, Any]:
    return {
        "start": parse_time_to_unix_seconds(args.from_time),
        "end": parse_time_to_unix_seconds(args.to_time),
        "env": args.env or default_env,
    }


def _as_service_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if value:
            return [value]
        raise ApiError("Datadog returned an invalid dependency", error_code="invalid_response")
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str) and item:
                result.append(item)
            elif isinstance(item, dict):
                name = item.get("service") or item.get("name") or item.get("service_name")
                if isinstance(name, str) and name:
                    result.append(name)
                else:
                    raise ApiError("Datadog returned an invalid dependency", error_code="invalid_response")
            else:
                raise ApiError("Datadog returned an invalid dependency", error_code="invalid_response")
        return result
    if isinstance(value, dict):
        if any(not isinstance(key, str) or not key for key in value):
            raise ApiError("Datadog returned an invalid dependency", error_code="invalid_response")
        return list(value)
    raise ApiError("Datadog returned an invalid dependency", error_code="invalid_response")


def _edge_value(edge: dict[str, Any], *keys: str) -> str | None:
    attr = edge.get("attributes", {}) if isinstance(edge.get("attributes"), dict) else {}
    for key in keys:
        for source in (edge, attr):
            value = source.get(key)
            if value:
                if not isinstance(value, str):
                    raise ApiError("Datadog returned an invalid dependency edge", error_code="invalid_response")
                return value
    return None


def _node_calls(node: Any) -> list[str]:
    """Return the explicit call list from a service-graph node."""
    if not isinstance(node, dict):
        raise ApiError("Datadog returned an invalid dependency node", error_code="invalid_response")
    for key in ("calls", "calls_to", "downstream", "dependencies"):
        if key in node:
            return _as_service_list(node[key])
    return []


def _node_called_by(node: Any) -> list[str]:
    if not isinstance(node, dict):
        raise ApiError("Datadog returned an invalid dependency node", error_code="invalid_response")
    for key in ("called_by", "upstream", "callers"):
        if key in node:
            return _as_service_list(node[key])
    return []


def _extract_from_edges(edges: list[Any], service: str) -> tuple[list[str], list[str]]:
    upstream: set[str] = set()
    downstream: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise ApiError("Datadog returned an invalid dependency edge", error_code="invalid_response")
        if "attributes" in edge and not isinstance(edge.get("attributes"), dict):
            raise ApiError("Datadog returned an invalid dependency edge", error_code="invalid_response")
        source = _edge_value(edge, "source", "src", "caller", "parent", "from", "service")
        target = _edge_value(edge, "target", "dst", "callee", "child", "to", "dependency")
        if not source or not target:
            raise ApiError("Datadog returned an invalid dependency edge", error_code="invalid_response")
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
    if not isinstance(body, (dict, list)):
        raise ApiError("Datadog returned an invalid dependencies response", error_code="invalid_response")
    raw = body.get("data", body) if isinstance(body, dict) else body
    upstream: set[str] = set()
    downstream: set[str] = set()

    if isinstance(raw, dict):
        for source, target_info in raw.items():
            if not isinstance(source, str) or not source or not isinstance(target_info, dict):
                raise ApiError("Datadog returned an invalid dependency node", error_code="invalid_response")
        node = raw.get(service)
        if node is not None:
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

    if not isinstance(raw, (dict, list)):
        raise ApiError("Datadog returned an invalid dependencies response", error_code="invalid_response")

    upstream.discard(service)
    downstream.discard(service)
    dependencies = upstream | downstream
    return {
        "upstream": sorted(upstream),
        "downstream": sorted(downstream),
        "dependencies": sorted(dependencies),
    }


def run(args, context: RuntimeContext) -> CommandResult:
    params = build_params(args, context.config.default_env)
    target = context.bind_target({
        "service": args.service,
        "env": params["env"],
        "from": args.from_time,
        "to": args.to_time,
        "start": params["start"],
        "end": params["end"],
    })
    body = context.client.request_read(
        "GET",
        "/api/v1/service_dependencies",
        params=params,
    )
    extracted = extract_dependencies(body, args.service)
    return CommandResult(
        target=target,
        result=extracted,
    )
