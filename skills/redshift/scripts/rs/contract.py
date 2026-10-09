"""Single source of truth for public commands, parser help, and skill docs."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable, Iterable


ConfigureArgs = Callable[[argparse.ArgumentParser], None]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    summary: str
    canonical_usage: str
    configure_args: ConfigureArgs
    supported_formats: tuple[str, ...]


def _json_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("json",), default="json")


def _connection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--connection")


def _databases(parser: argparse.ArgumentParser) -> None:
    _connection(parser)
    parser.add_argument("--source-type", choices=("warehouse", "mysql", "postgres", "saas", "unknown"))
    _json_format(parser)


def _schemas(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("database")
    _connection(parser)
    parser.add_argument("--include-system", action="store_true")
    parser.add_argument("--limit", type=int, default=200)
    _json_format(parser)


def _relations(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target")
    _connection(parser)
    parser.add_argument("--kind", choices=("table", "view", "all"), default="all")
    parser.add_argument("--limit", type=int, default=200)
    _json_format(parser)


def _search(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("text", nargs="?")
    parser.add_argument("--database")
    parser.add_argument("--source-type", choices=("warehouse", "mysql", "postgres", "saas", "unknown"))
    parser.add_argument("--schema")
    parser.add_argument("--layer")
    parser.add_argument("--domain")
    parser.add_argument("--kind", choices=("table", "view", "column", "all"), default="all")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    _json_format(parser)


def _describe(parser: argparse.ArgumentParser) -> None:
    _connection(parser)
    parser.add_argument("object")
    parser.add_argument("--timeout-ms", type=int)
    _json_format(parser)


def _query(parser: argparse.ArgumentParser) -> None:
    _connection(parser)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sql")
    source.add_argument("--file")
    params = parser.add_mutually_exclusive_group()
    params.add_argument("--params")
    params.add_argument("--params-file")
    parser.add_argument("--database")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--timeout-ms", type=int)
    parser.add_argument("--format", choices=("json", "csv", "ndjson"), default="json")
    parser.add_argument("--output")
    parser.add_argument("--debug", action="store_true")


def _explain(parser: argparse.ArgumentParser) -> None:
    _connection(parser)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sql")
    source.add_argument("--file")
    params = parser.add_mutually_exclusive_group()
    params.add_argument("--params")
    params.add_argument("--params-file")
    parser.add_argument("--database")
    parser.add_argument("--timeout-ms", type=int)
    parser.add_argument("--debug", action="store_true")
    _json_format(parser)


def _recipe(parser: argparse.ArgumentParser) -> None:
    _connection(parser)
    parser.add_argument(
        "recipe_name",
        choices=(
            "list",
            "email-to-company",
            "appointment-timeline",
            "refund-origin",
            "membership-entitlement",
        ),
    )
    parser.add_argument("--email")
    parser.add_argument("--account-db")
    parser.add_argument("--biz-db")
    parser.add_argument("--appointment-id", type=int)
    parser.add_argument("--refund-id", type=int)
    parser.add_argument("--membership-id", type=int)
    parser.add_argument("--subscription-id", type=int)
    parser.add_argument("--timeout-ms", type=int)
    _json_format(parser)


def _doctor(parser: argparse.ArgumentParser) -> None:
    _connection(parser)
    parser.add_argument("--connect", action="store_true")
    parser.add_argument("--list-connections", action="store_true")
    parser.add_argument("--debug", action="store_true")
    _json_format(parser)


COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec("databases", "列出 live database 并附 catalog enrichment", "redshift databases [--connection NAME] [--source-type TYPE] [--format json]", _databases, ("json",)),
    CommandSpec("schemas", "列出当前 principal 可见的 live schema", "redshift schemas DATABASE [--connection NAME] [--include-system] [--limit LIMIT] [--format json]", _schemas, ("json",)),
    CommandSpec("relations", "列出当前 principal 可见的 live table/view", "redshift relations DATABASE.SCHEMA [--connection NAME] [--kind table|view|all] [--limit LIMIT] [--format json]", _relations, ("json",)),
    CommandSpec("search", "搜索本地 catalog", "redshift search [TEXT] [filters] [--format json]", _search, ("json",)),
    CommandSpec("describe", "读取完整对象名的 live metadata", "redshift describe DATABASE.SCHEMA.RELATION [--connection NAME] [--format json]", _describe, ("json",)),
    CommandSpec("query", "执行一条有界只读 SQL", "redshift query [--connection NAME] [--database DATABASE] (--sql SQL | --file PATH) [options]", _query, ("json", "csv", "ndjson")),
    CommandSpec("explain", "返回 Redshift EXPLAIN plan", "redshift explain [--connection NAME] [--database DATABASE] (--sql SQL | --file PATH) [options]", _explain, ("json",)),
    CommandSpec("recipe", "运行经过验证的 MoeGo recipe", "redshift recipe (list | email-to-company | appointment-timeline | refund-origin | membership-entitlement) [--connection NAME] [options]", _recipe, ("json",)),
    CommandSpec("doctor", "检查配置和可选 live capability", "redshift doctor [--connection NAME] [--connect | --list-connections] [--debug] [--format json]", _doctor, ("json",)),
)


def command_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in COMMAND_SPECS)


def find_spec(name: str) -> CommandSpec | None:
    return next((spec for spec in COMMAND_SPECS if spec.name == name), None)


def _option_strings(spec: CommandSpec) -> set[str]:
    probe = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    spec.configure_args(probe)
    return {
        option
        for action in probe._actions
        for option in action.option_strings
    }


def all_leaf_options() -> set[str]:
    return set().union(*(_option_strings(spec) for spec in COMMAND_SPECS))


def commands_for_option(option: str) -> tuple[str, ...]:
    return tuple(
        spec.name
        for spec in COMMAND_SPECS
        if option in _option_strings(spec)
    )


def contract_replay_fixture() -> dict[str, object]:
    """Render the committed deterministic parser/preflight replay fixture."""

    query = find_spec("query")
    schemas = find_spec("schemas")
    relations = find_spec("relations")
    recipe = find_spec("recipe")
    doctor = find_spec("doctor")
    if (
        query is None
        or schemas is None
        or relations is None
        or recipe is None
        or doctor is None
    ):
        raise RuntimeError(
            "contract replay requires query, schemas, relations, recipe, and doctor commands"
        )
    if "--database" not in all_leaf_options():
        raise RuntimeError("contract replay requires the query database leaf option")
    if "--connection" not in all_leaf_options():
        raise RuntimeError("contract replay requires the live connection leaf option")

    def usage_paths(command: str | None, code: str) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "ok": False,
            "command": command,
            "error.category": "usage",
            "error.code": code,
            "error.retryClass": "after_change",
        }

    def usage_case(
        case_id: str,
        args: list[str],
        *,
        command: str | None,
        code: str,
    ) -> dict[str, object]:
        return {
            "id": case_id,
            "networkRequired": False,
            "args": args,
            "expected": {
                "exitCode": 2,
                "jsonPaths": usage_paths(command, code),
            },
        }

    return {
        "schemaVersion": 1,
        "suite": "moe-redshift-v2-deterministic-cli-contract",
        "cases": [
            usage_case(
                "missing-command",
                [],
                command=None,
                code="missing_command",
            ),
            usage_case(
                "unknown-command",
                ["qurey"],
                command=None,
                code="unknown_command",
            ),
            usage_case(
                "root-database-option-scope",
                ["--database", "example_db", query.name, "--sql", "SELECT 1"],
                command=None,
                code="option_scope",
            ),
            usage_case(
                "root-connection-option-scope",
                ["--connection", "example", query.name, "--sql", "SELECT 1"],
                command=None,
                code="option_scope",
            ),
            usage_case(
                "query-missing-source",
                [query.name, "--database", "example_db"],
                command=query.name,
                code="missing_argument",
            ),
            usage_case(
                "schemas-missing-target",
                [schemas.name],
                command=schemas.name,
                code="missing_argument",
            ),
            usage_case(
                "relations-missing-target",
                [relations.name],
                command=relations.name,
                code="missing_argument",
            ),
            usage_case(
                "query-unknown-option",
                [query.name, "--sql", "SELECT 1", "--unknown-option"],
                command=query.name,
                code="unknown_option",
            ),
            usage_case(
                "recipe-invalid-name",
                [recipe.name, "unknown-recipe"],
                command=recipe.name,
                code="invalid_value",
            ),
            usage_case(
                "recipe-list-connection-invalid-combination",
                [recipe.name, "list", "--connection", "example"],
                command=recipe.name,
                code="invalid_combination",
            ),
            usage_case(
                "doctor-list-connect-invalid-combination",
                [doctor.name, "--list-connections", "--connect"],
                command=doctor.name,
                code="invalid_combination",
            ),
            usage_case(
                "json-output-invalid-combination",
                [
                    query.name,
                    "--sql",
                    "SELECT 1",
                    "--format",
                    "json",
                    "--output",
                    "result.json",
                ],
                command=query.name,
                code="invalid_combination",
            ),
            usage_case(
                "csv-output-missing-name",
                [query.name, "--sql", "SELECT 1", "--format", "csv"],
                command=query.name,
                code="missing_argument",
            ),
        ],
    }


def render_command_matrix(specs: Iterable[CommandSpec] = COMMAND_SPECS) -> str:
    rows = ["| Command | Canonical grammar | Formats |", "|---|---|---|"]
    for spec in specs:
        rows.append(
            f"| `{spec.name}` | `{spec.canonical_usage}` | `{','.join(spec.supported_formats)}` |"
        )
    return "\n".join(rows)
