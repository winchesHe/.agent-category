"""list-services: discover active Datadog APM services."""
from __future__ import annotations

import fnmatch
import sys
from typing import Any

from dd.client import DatadogClient
from dd.formatter import output
from dd.timeutil import parse_time_to_unix_seconds

NAME = "list-services"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="列出 APM 活跃服务")
    p.add_argument("--env", help="环境标签，默认 DD_DEFAULT_ENV/ns-production")
    p.add_argument("--from", default="1h", dest="from_time", help="起始时间，默认 1h")
    p.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    p.add_argument("--filter", dest="filter_pattern", help="通配符过滤服务名，如 moego-svc-*")
    p.add_argument("--format", dest="fmt", choices=["json", "human", "summary"], default="json")
    p.set_defaults(_handler=run)


def build_params(args, default_env: str) -> dict[str, Any]:
    return {
        "start": parse_time_to_unix_seconds(args.from_time),
        "end": parse_time_to_unix_seconds(args.to_time),
        "filter[env]": args.env or default_env,
    }


def _service_name_from_item(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return None
    attr = item.get("attributes", {}) if isinstance(item.get("attributes"), dict) else {}
    schema = attr.get("schema", {}) if isinstance(attr.get("schema"), dict) else {}
    candidates = [
        item.get("name"),
        item.get("service"),
        attr.get("service"),
        attr.get("service_name"),
        attr.get("name"),
        schema.get("dd-service"),
    ]
    for candidate in candidates:
        if candidate:
            return str(candidate)
    return None


def extract_services(body: Any) -> list[str]:
    services: list[str] = []
    items: Any = body.get("data", body) if isinstance(body, dict) else body

    # Datadog 真实形态：`data` 是单个 JSON:API resource，
    # 服务名列表挂在 attributes.services 下。
    if isinstance(items, dict):
        attrs = items.get("attributes")
        if isinstance(attrs, dict) and isinstance(attrs.get("services"), list):
            for entry in attrs["services"]:
                if isinstance(entry, str) and entry:
                    services.append(entry)
                elif isinstance(entry, dict):
                    name = _service_name_from_item(entry)
                    if name:
                        services.append(name)
        # 兼容老形态：`data` 直接是 list of resource，被上面 .get('data', body) 拆包后这里不会进
        # 这里再兼容 `{svc: {...}}` 形式的服务字典
        elif not isinstance(attrs, dict):
            for key, value in items.items():
                if isinstance(key, str) and (isinstance(value, dict) or isinstance(value, list)):
                    services.append(key)
    elif isinstance(items, list):
        for item in items:
            name = _service_name_from_item(item)
            if name:
                services.append(name)
    return sorted(set(service for service in services if service))


def _render_human(services: list[str]) -> None:
    for service in services:
        sys.stderr.write(f"{service}\n")


def run(args, config) -> int:
    params = build_params(args, config.default_env)
    sys.stderr.write(
        f"[list-services] env={params['filter[env]']} from={args.from_time} to={args.to_time}\n"
    )
    body = DatadogClient(config).get("/api/v2/apm/services", params=params)
    services = extract_services(body)
    if args.filter_pattern:
        services = [service for service in services if fnmatch.fnmatch(service, args.filter_pattern)]
    result = {
        "services": services,
        "count": len(services),
        "env": params["filter[env]"],
        "from": args.from_time,
        "to": args.to_time,
        "start": params["start"],
        "end": params["end"],
    }
    if args.fmt == "human":
        _render_human(services)
    output(result, fmt=args.fmt)
    return 0
