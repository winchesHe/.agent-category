from __future__ import annotations

import json
from copy import deepcopy

import pytest

from scripts.rs.errors import SkillError
from scripts.rs.catalog.enrichment import load_domain_map


DOMAIN_MAPPING = {
    "schemaVersion": 1,
    "databases": {
        "dbt_dw": {"sourceType": "warehouse"},
        "ambiguous": {"sourceType": "unknown"},
    },
    "relations": {
        "dbt_dw.ads.payment_summary": {
            "domain": "payment",
            "subdomain": "transaction",
            "service": "data-warehouse",
            "layer": "ads",
            "hiddenByDefault": False,
        }
    },
}


def test_domain_enrichment_loader_accepts_mapping_or_json_path(tmp_path) -> None:
    path = tmp_path / "moego-domain-map.json"
    path.write_text(json.dumps(DOMAIN_MAPPING), encoding="utf-8")

    from_mapping = load_domain_map(DOMAIN_MAPPING)
    from_path = load_domain_map(path)

    assert from_mapping == from_path
    assert from_mapping.source_type("dbt_dw") == "warehouse"
    assert from_mapping.source_type("ambiguous") == "unknown"
    assert from_mapping.source_type("unmapped") is None
    assert from_mapping.relation("dbt_dw.ads.payment_summary") == {
        "domain": "payment",
        "subdomain": "transaction",
        "service": "data-warehouse",
        "layer": "ads",
        "hiddenByDefault": False,
    }
    assert from_mapping.relation("dbt_dw.ads.unmapped") == {
        "domain": None,
        "subdomain": None,
        "service": None,
        "layer": "unknown",
        "hiddenByDefault": False,
    }


def test_domain_enrichment_accepts_canonical_quoted_object_keys() -> None:
    payload = deepcopy(DOMAIN_MAPPING)
    enrichment = payload["relations"].pop("dbt_dw.ads.payment_summary")
    object_name = 'dbt_dw."mixed.schema"."a""b"'
    payload["relations"][object_name] = enrichment

    domain_map = load_domain_map(payload)

    assert domain_map.relation(object_name)["domain"] == "payment"


@pytest.mark.parametrize(
    "variant",
    [
        "schema_version",
        "schema_version_type",
        "source_type",
        "relation_key",
        "relation_shape",
        "layer",
        "hidden",
    ],
)
def test_domain_enrichment_loader_rejects_contract_drift(variant: str) -> None:
    payload = deepcopy(DOMAIN_MAPPING)
    relation = payload["relations"]["dbt_dw.ads.payment_summary"]
    if variant == "schema_version":
        payload["schemaVersion"] = 2
    elif variant == "schema_version_type":
        payload["schemaVersion"] = True
    elif variant == "source_type":
        payload["databases"]["dbt_dw"]["sourceType"] = "guessed"
    elif variant == "relation_key":
        payload["relations"]["not-qualified"] = payload["relations"].pop(
            "dbt_dw.ads.payment_summary"
        )
    elif variant == "relation_shape":
        relation["extra"] = "not public"
    elif variant == "layer":
        relation["layer"] = "mart"
    else:
        relation["hiddenByDefault"] = "false"

    with pytest.raises(SkillError) as caught:
        load_domain_map(payload)

    assert caught.value.full_code == "catalog.invalid"
