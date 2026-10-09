"""list-services: read the Datadog APM service inventory for one environment."""
from __future__ import annotations

import fnmatch
from typing import Any

from dd_v3.errors import ApiError, UsageError
from dd_v3.runtime import READ, CommandResult, RuntimeContext

NAME = "list-services"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="列出环境中的 APM 服务")
    p.add_argument("--env", help="环境标签，默认 DD_DEFAULT_ENV/ns-production")
    p.add_argument("--filter", dest="filter_pattern", help="通配符过滤服务名，如 moego-svc-*")
    p.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    p.set_defaults(_handler=run, _policy=READ)


def build_params(args, default_env: str) -> dict[str, Any]:
    env = args.env if args.env is not None else default_env
    if not isinstance(env, str) or not env or env != env.strip():
        raise UsageError("--env 必须是非空 Datadog environment value")
    return {"filter[env]": env}


def extract_services(body: Any) -> list[str]:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid services response", error_code="invalid_response")
    data = body.get("data")
    attributes = data.get("attributes") if isinstance(data, dict) else None
    services = attributes.get("services") if isinstance(attributes, dict) else None
    if not isinstance(services, list) or any(
        not isinstance(service, str) or not service for service in services
    ):
        raise ApiError("Datadog returned an invalid services response", error_code="invalid_response")
    return sorted(set(services))


def run(args, context: RuntimeContext) -> CommandResult:
    params = build_params(args, context.config.default_env)
    target = context.bind_target({
        "env": params["filter[env]"],
        "filter": args.filter_pattern,
    })
    body = context.client.request_read(
        "GET",
        "/api/v2/apm/services",
        params=params,
    )
    services = extract_services(body)
    if args.filter_pattern:
        services = [service for service in services if fnmatch.fnmatch(service, args.filter_pattern)]
    return CommandResult(
        target=target,
        result={"services": services, "count": len(services)},
    )
