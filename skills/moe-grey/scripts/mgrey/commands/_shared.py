from ..clients.grey import GreyClient
from ..errors import ConfigError
from ..grey_mutation import GreyMutationService
from ..http import HttpClient


def _selector(args, prefix=""):
    item_id = getattr(args, prefix + "id", None)
    name = getattr(args, prefix + "name", None)
    if bool(item_id) == bool(name):
        raise ConfigError("必须且只能指定 --id 或 --name")
    return {"id": item_id} if item_id else {"name": name}


def _services(values):
    result = {}
    for value in values or []:
        if "=" not in value:
            raise ConfigError("--service 必须使用 repo=branch")
        service, branch = value.split("=", 1)
        if not service or not branch:
            raise ConfigError("--service 必须使用非空 repo=branch")
        result[service] = branch
    return result


def _add_selector(parser, prefix=""):
    parser.add_argument(f"--{prefix}id")
    parser.add_argument(f"--{prefix}name")


def _add_mutation(parser):
    parser.add_argument("--apply", action="store_true")


def register_action(subparsers, action, handler):
    parser = subparsers.add_parser(action, help={
        "list": "列出规则", "get": "读取一条规则", "branches": "列出服务分支",
        "create": "规划或创建规则", "copy": "规划或复制规则",
        "update": "规划或更新规则", "delete": "规划或删除规则",
    }[action])
    if action == "list":
        parser.add_argument("--namespace")
    elif action == "get":
        _add_selector(parser)
    elif action == "branches":
        parser.add_argument("--namespace")
        parser.add_argument("--service")
    elif action == "create":
        parser.add_argument("--namespace")
        parser.add_argument("--name", required=True)
        parser.add_argument("--description", default="")
        parser.add_argument("--jira-ticket", action="append", default=[])
        parser.add_argument("--service", action="append", required=True)
        _add_mutation(parser)
    elif action == "copy":
        _add_selector(parser, "from-")
        parser.add_argument("--namespace")
        parser.add_argument("--name", required=True)
        parser.add_argument("--description")
        parser.add_argument("--jira-ticket", action="append")
        parser.add_argument("--service", action="append")
        _add_mutation(parser)
    elif action == "update":
        _add_selector(parser)
        parser.add_argument("--name-to")
        parser.add_argument("--description")
        parser.add_argument("--jira-ticket", action="append")
        parser.add_argument("--service", action="append")
        parser.add_argument("--expected-updated-at")
        _add_mutation(parser)
    else:
        _add_selector(parser)
        parser.add_argument("--confirm")
        parser.add_argument("--expected-updated-at")
        _add_mutation(parser)
    parser.set_defaults(_handler=handler)


def run(args, config):
    client = GreyClient(config.grey_base_url, HttpClient(config.timeout))
    action = args.grey_action
    if action == "list":
        namespace = args.namespace or config.grey_namespace
        return {"namespace": namespace, "items": client.list(namespace)}
    if action == "get":
        return client.get(_selector(args))
    if action == "branches":
        namespace = args.namespace or config.grey_namespace
        branches = client.branches(namespace)
        if args.service:
            branches = {args.service: branches.get(args.service, [])}
        return {"namespace": namespace, "services": branches}

    service = GreyMutationService(client)
    if action == "create":
        return service.create(
            args.namespace or config.grey_namespace,
            args.name,
            args.description,
            args.jira_ticket,
            _services(args.service),
            args.apply,
        )
    if action == "copy":
        return service.copy(
            _selector(args, "from_"),
            args.namespace or config.grey_namespace,
            args.name,
            args.description,
            args.jira_ticket,
            _services(args.service) if args.service is not None else None,
            args.apply,
        )
    if action == "update":
        changes = {
            "name": args.name_to,
            "description": args.description,
            "jiraTickets": args.jira_ticket,
            "svcBranchMap": _services(args.service)
            if args.service is not None
            else None,
        }
        return service.update(
            _selector(args), changes, args.expected_updated_at, args.apply
        )
    return service.delete(
        _selector(args), args.confirm, args.expected_updated_at, args.apply
    )
