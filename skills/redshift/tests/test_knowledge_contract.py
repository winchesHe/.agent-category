from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from scripts.rs.connectivity.registry import load_connection_registry
from scripts.rs.catalog.enrichment import load_domain_map
from scripts.rs.catalog.snapshot import load_catalog


ROOT = Path(__file__).parents[1]


def test_connection_and_dotenv_examples_have_the_same_environment_contract() -> None:
    registry = json.loads(
        (ROOT / "connections.example.json").read_text(encoding="utf-8")
    )
    referenced_keys: list[str] = []

    def collect_env_references(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("Env") and isinstance(item, str):
                    if item not in referenced_keys:
                        referenced_keys.append(item)
                collect_env_references(item)
        elif isinstance(value, list):
            for item in value:
                collect_env_references(item)

    collect_env_references(registry)
    dotenv_keys = [
        line.split("=", 1)[0].strip()
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    ]

    assert dotenv_keys == [*referenced_keys, "REDSHIFT_OUTPUT_DIR"]


def test_documented_advanced_connection_profiles_match_the_registry_contract(
    tmp_path,
) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for index, heading in enumerate(
        (
            "Provisioned Data API + IAM DbUser",
            "Provisioned Wire + IAM",
            "Serverless Data API + SecretArn",
        )
    ):
        section = readme.split(f"### {heading}", 1)[1]
        block = section.split("```json", 1)[1].split("```", 1)[0]
        profile = json.loads(block)
        name = f"documented-{index}"
        path = tmp_path / f"{name}.json"
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "defaultConnection": name,
                    "connections": {name: profile},
                }
            ),
            encoding="utf-8",
        )
        os.chmod(path, 0o600)

        registry = load_connection_registry({"REDSHIFT_CONNECTIONS_FILE": str(path)})

        assert registry.resolve(None).name == name


def test_every_maintained_relation_mapping_exists_in_published_catalog() -> None:
    domain_map = load_domain_map(ROOT / "references" / "moego-domain-map.json")
    catalog = load_catalog(ROOT / "references" / "catalog.jsonl")
    live_objects = {relation.object for relation in catalog.relations}

    assert set(domain_map.relations).issubset(live_objects)
    assert {
        "account",
        "customer",
        "fulfillment",
        "membership",
        "order",
        "payment",
    }.issubset(
        {
            str(item["domain"])
            for item in domain_map.relations.values()
            if item["domain"] is not None
        }
    )


def test_published_catalog_has_exact_complete_empty_database_identities() -> None:
    catalog = load_catalog(ROOT / "references" / "catalog.jsonl")

    assert catalog.meta.complete_empty_databases is not None
    failed_names = {
        item["database"] for item in catalog.meta.coverage.failed_databases
    }
    complete_relation_names = {
        relation.database for relation in catalog.relations
    } - failed_names
    assert len(catalog.meta.complete_empty_databases) == (
        catalog.meta.coverage.complete_database_count - len(complete_relation_names)
    )


def test_public_docs_are_runtime_and_message_platform_neutral() -> None:
    documents = [
        ROOT / "AGENTS.md",
        ROOT / "SKILL.md",
        ROOT / "ARCHITECTURE.md",
        ROOT / "MAINTENANCE.md",
        ROOT / "README.md",
        ROOT / ".env.example",
        *sorted((ROOT / "references").glob("*.md")),
    ]
    content = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    for forbidden in ("Sherlock", "Slack", "runId", "sessionId", "bot name"):
        assert forbidden.casefold() not in content.casefold()


def test_skill_entrypoint_binding_does_not_require_reconstructing_host_paths() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    for required in (
        "直接复制 Host 本次加载的 `SKILL.md` location",
        "每个独立 shell tool call",
        "都必须在同一条 command 中重新绑定",
        'test -f "$SKILL_DIR/scripts/redshift.py"',
        "禁止根据 workspace、用户名或安装目录重新拼接",
        "禁止猜测或修改路径字符串后重试",
    ):
        assert required in skill

    assert "export SKILL_DIR" not in skill


def test_documented_entrypoint_template_executes_and_fails_closed(tmp_path) -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    template = skill.split("```bash", 1)[1].split("```", 1)[0].strip()

    copied_skill = tmp_path / "skill location with spaces"
    copied_skill.mkdir()
    (copied_skill / "scripts").mkdir()
    copied_entrypoint = copied_skill / "scripts" / "redshift.py"
    copied_entrypoint.write_text("print('entrypoint reached')\n", encoding="utf-8")
    copied_skill_file = copied_skill / "SKILL.md"
    copied_skill_file.write_text("# copied\n", encoding="utf-8")
    success_command = template.replace(
        "<loaded SKILL.md location>", str(copied_skill_file)
    ).replace(" COMMAND ...", "")

    success = subprocess.run(
        ["bash", "-c", success_command],
        check=False,
        capture_output=True,
        text=True,
    )

    assert success.returncode == 0
    assert success.stdout.strip() == "entrypoint reached"

    missing_command = template.replace(
        "<loaded SKILL.md location>", str(tmp_path / "missing" / "SKILL.md")
    ).replace(" COMMAND ...", " --help")
    missing = subprocess.run(
        ["bash", "-c", missing_command],
        check=False,
        capture_output=True,
        text=True,
    )

    assert missing.returncode == 3
    assert missing.stderr.strip() == "Redshift Skill entrypoint is unavailable"


def test_skill_package_has_no_agent_or_message_platform_eval_assets() -> None:
    forbidden = ("sherlock", "slack", "transcript")
    paths = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    ]

    for path in paths:
        relative = path.relative_to(ROOT).as_posix().casefold()
        assert not any(value in relative for value in forbidden), relative

    documents = [
        ROOT / "AGENTS.md",
        ROOT / "SKILL.md",
        ROOT / "ARCHITECTURE.md",
        ROOT / "MAINTENANCE.md",
        ROOT / "README.md",
        ROOT / ".env.example",
        *sorted((ROOT / "references").glob("*.md")),
        *sorted((ROOT / "scripts").rglob("*.py")),
        *sorted((ROOT / "evals").rglob("*.py")),
        *sorted((ROOT / "evals").rglob("*.md")),
        *sorted((ROOT / "evals").rglob("*.json")),
        *sorted((ROOT / "evals").rglob("*.jsonl")),
    ]
    content = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    for value in forbidden:
        assert value not in content.casefold()


def test_maintenance_uses_local_repository_gates() -> None:
    instructions = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("AGENTS.md", "MAINTENANCE.md")
    )

    for command in (
        "python3 -m pytest",
        "scripts/generate_contract_cases.py",
        "scripts/run_contract_replay.py",
        "git diff --check",
    ):
        assert command in instructions
    assert "pnpm catalog" not in instructions
    assert "ai-config.ts" not in instructions


def test_v2_has_no_migration_compatibility_seams() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "scripts" / "rs").rglob("*.py"))
    )
    public_docs = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("SKILL.md", "README.md", ".env.example", "ARCHITECTURE.md")
    )

    for removed_symbol in (
        "_legacy_registry",
        "load_connection_config",
        "profile.legacy",
        "deployment=\"legacy\"",
        "source=\"legacy\"",
        "connection_factory: Callable[..., Any] | None",
    ):
        assert removed_symbol not in source
    assert not (ROOT / "scripts" / "rs" / "doctor.py").exists()
    assert "Legacy flat" not in public_docs
    assert "synthetic `default`" not in public_docs

    builder_cli = (ROOT / "scripts" / "build_catalog.py").read_text(encoding="utf-8")
    assert "build_catalog_artifact" in builder_cli
    assert ".bind_catalog(" not in builder_cli
    assert ".catalog_source(" not in builder_cli


def test_new_recipe_objects_and_agent_guidance_are_published_together() -> None:
    domain_map = load_domain_map(ROOT / "references" / "moego-domain-map.json")
    assert domain_map.relations[
        "pg_moego_fulfillment_prod.public.appointment_status_record"
    ]["subdomain"] == "appointment-status-history"

    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    routing = (ROOT / "references" / "domain-routing.md").read_text(encoding="utf-8")
    patterns = (ROOT / "references" / "query-patterns.md").read_text(encoding="utf-8")
    for recipe in (
        "appointment-timeline",
        "refund-origin",
        "membership-entitlement",
    ):
        assert recipe in skill
        assert recipe in routing
        assert recipe in patterns
    assert patterns.count("最近验证：`2026-08-20`") >= 4
    assert "状态变化，不是" in patterns
    assert "字段级审计日志" in patterns
    assert "minor units" in routing


def test_redshift_semantics_reference_is_routed_and_self_contained() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    semantics = (ROOT / "references" / "redshift-semantics.md").read_text(
        encoding="utf-8"
    )

    assert "[redshift-semantics.md](references/redshift-semantics.md)" in skill
    for required in (
        "Redshift 不是 PostgreSQL",
        "SYS_*",
        "ResourceNotFoundException",
        "WaitTimeSeconds",
        "24 小时",
        "始终只读",
    ):
        assert required in semantics


def test_data_api_dependency_floor_includes_long_poll_service_model() -> None:
    requirement = (
        (ROOT / "requirements-data-api.txt").read_text(encoding="utf-8").strip()
    )

    assert requirement == "boto3>=1.43.55,<2"


def test_permission_recovery_routes_to_the_owning_team() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    semantics = (ROOT / "references" / "redshift-semantics.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "suggestion=request_data_access",
        "suggestion=request_platform_access",
        "Data Team",
        "SRE",
    ):
        assert required in skill
    assert "Data Team" in semantics
    assert "SRE" in semantics


def test_legacy_grooming_guidance_is_routed_and_preserves_generation_boundary() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    routing = (ROOT / "references" / "domain-routing.md").read_text(
        encoding="utf-8"
    )
    patterns = (ROOT / "references" / "query-patterns.md").read_text(
        encoding="utf-8"
    )
    legacy = (ROOT / "references" / "legacy-grooming.md").read_text(
        encoding="utf-8"
    )

    assert "legacy-grooming.md" in skill
    assert "legacy-grooming.md" in routing
    assert "legacy-grooming.md" in patterns
    assert "当前 appointment" in routing
    assert "legacy" in routing.casefold()
    assert "legacy grooming service/addon" in skill
    assert "legacy grooming service/addon" in routing
    assert "appointment/grooming/service/addon" not in skill
    assert "raw/unknown" in patterns

    for required in (
        "moe_grooming_service",
        "moe_grooming_appointment",
        "moe_grooming_pet_detail",
        "READY = 5",
        "CHECK_IN = 6",
        "EVALUATION = 4",
        "DOG_WALKING = 5",
        "GROUP_CLASS = 6",
        "status = 1 AND inactive = 0",
    ):
        assert required in legacy

    for forbidden in (
        "WHERE apt.status IN (2, 3)",
        "COUNT(DISTINCT name)",
        "Template company",
        "Demo Company",
    ):
        assert forbidden not in legacy
