from ..clients.metadata import (
    MetadataClient,
    normalize_owner_type,
    normalize_permission_level,
)
from ..errors import ConfigError
from ..formatter import output
from ..metadata_mutation import MetadataMutationService


def _add_pagination(parser):
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=100)


def _add_key_fields(parser, required=False):
    parser.add_argument("--description", required=required)
    parser.add_argument("--owner-type", required=required)
    parser.add_argument("--default-value", required=required)
    parser.add_argument("--start-at")
    parser.add_argument("--end-at")
    parser.add_argument("--permission-level", required=required)
    parser.add_argument("--group", required=required)


def _add_apply(parser):
    parser.add_argument("--apply", action="store_true")


def register(actions):
    domain = actions.add_parser(
        "metadata", help="查询和受控管理 MIS Metadata"
    )
    domain.set_defaults(_handler=run)
    commands = domain.add_subparsers(dest="metadata_action", required=True)

    commands.add_parser("groups", help="列出 Metadata 分组")

    list_parser = commands.add_parser("list", help="分页列出 Metadata Key")
    list_parser.add_argument("--group")
    list_parser.add_argument("--owner-type")
    list_parser.add_argument("--name-like")
    _add_pagination(list_parser)

    get_parser = commands.add_parser("get", help="读取一个 Metadata Key")
    get_parser.add_argument("--id", required=True)

    create = commands.add_parser("create", help="规划或创建 Metadata Key")
    create.add_argument("--name", required=True)
    _add_key_fields(create, required=True)
    _add_apply(create)

    update = commands.add_parser("update", help="规划或更新 Metadata Key")
    update.add_argument("--id", required=True)
    _add_key_fields(update)
    update.add_argument("--clear-start-at", action="store_true")
    update.add_argument("--clear-end-at", action="store_true")
    update.add_argument("--expected-updated-at")
    update.add_argument("--expected-state-hash")
    _add_apply(update)

    delete = commands.add_parser("delete", help="规划或删除 Metadata Key")
    delete.add_argument("--id", required=True)
    delete.add_argument("--confirm")
    delete.add_argument("--expected-updated-at")
    delete.add_argument("--expected-state-hash")
    _add_apply(delete)

    values = commands.add_parser("values", help="分页读取 Metadata Value")
    values.add_argument("--key-id", required=True)
    values.add_argument("--owner-id", action="append")
    _add_pagination(values)

    get_value = commands.add_parser(
        "get-value", help="读取一个 owner 的 Metadata Value"
    )
    get_value.add_argument("--key-id", required=True)
    get_value.add_argument("--owner-id", required=True)

    set_value = commands.add_parser(
        "set-value", help="规划或批量设置 Metadata Value"
    )
    set_value.add_argument("--key-id", required=True)
    set_value.add_argument("--owner-id", action="append", required=True)
    set_value.add_argument("--value", required=True)
    set_value.add_argument("--expected-state-hash")
    _add_apply(set_value)


def _key_def(args):
    return {
        "name": args.name,
        "description": args.description,
        "ownerType": normalize_owner_type(args.owner_type),
        "defaultValue": args.default_value,
        **({"startAt": args.start_at} if args.start_at else {}),
        **({"endAt": args.end_at} if args.end_at else {}),
        "permissionLevel": normalize_permission_level(args.permission_level),
        "group": args.group,
    }


def _key_changes(args):
    if args.clear_start_at and args.start_at is not None:
        raise ConfigError("--start-at 与 --clear-start-at 不能同时使用")
    if args.clear_end_at and args.end_at is not None:
        raise ConfigError("--end-at 与 --clear-end-at 不能同时使用")
    source = {
        "description": args.description,
        "ownerType": normalize_owner_type(args.owner_type),
        "defaultValue": args.default_value,
        "permissionLevel": normalize_permission_level(args.permission_level),
        "group": args.group,
    }
    changes = {key: value for key, value in source.items() if value is not None}
    if args.clear_start_at:
        changes["startAt"] = None
    elif args.start_at is not None:
        changes["startAt"] = args.start_at
    if args.clear_end_at:
        changes["endAt"] = None
    elif args.end_at is not None:
        changes["endAt"] = args.end_at
    return changes


def execute(args, config, mis_client):
    client = MetadataClient(
        config.mis_url, mis_client.http, mis_client.credential
    )
    action = args.metadata_action
    if action == "groups":
        return {"groups": client.groups()}
    if action == "list":
        return client.list_keys(
            group=args.group,
            owner_type=args.owner_type,
            name_like=args.name_like,
            page=args.page,
            page_size=args.page_size,
        )
    if action == "get":
        return {"key": client.get_key(args.id)}
    if action == "values":
        return client.list_values(
            args.key_id, args.owner_id, args.page, args.page_size
        )
    if action == "get-value":
        return client.get_value(args.key_id, args.owner_id)

    service = MetadataMutationService(client)
    if action == "create":
        return service.create(_key_def(args), apply=args.apply)
    if action == "update":
        return service.update(
            args.id,
            _key_changes(args),
            expected_updated_at=args.expected_updated_at,
            expected_state_hash=args.expected_state_hash,
            apply=args.apply,
        )
    if action == "delete":
        return service.delete(
            args.id,
            confirm=args.confirm,
            expected_updated_at=args.expected_updated_at,
            expected_state_hash=args.expected_state_hash,
            apply=args.apply,
        )
    return service.set_value(
        args.key_id,
        args.owner_id,
        args.value,
        expected_state_hash=args.expected_state_hash,
        apply=args.apply,
    )


def run(args, config):
    from .mis import _client

    mis_client = _client(
        config, force=args.force_login, auth_method=args.auth_method
    )
    output(execute(args, config, mis_client), args.format)
    return 0
