from __future__ import annotations

import pytest

from app.db_fqtn import analytics_table, budget_table, fqtn
from app.db_schemas import SCHEMA_BY_SOURCE


def test_schema_registry_has_expected_sources() -> None:
    expected_sources = {
        "places",
        "acs",
        "svi",
        "hrsa",
        "cms",
        "usda",
        "usda_food_access",
        "usda_food_environment",
        "usda_food_env",
        "fema",
        "fema_nri",
        "fema_national_risk_index",
        "cdc",
        "cdc_funding",
        "usaspending",
        "cdc_profiles",
        "taggs",
        "recon",
        "analytics",
        "budget",
    }
    assert set(SCHEMA_BY_SOURCE) == expected_sources
    for schema in SCHEMA_BY_SOURCE.values():
        assert isinstance(schema, str)
        assert schema.strip()


def test_fqtn_allows_valid_identifiers() -> None:
    assert fqtn("public", "dim_county") == "public.dim_county"
    assert fqtn("cms", "gv_fact") == "cms.gv_fact"
    assert fqtn("_custom", "table_01") == "_custom.table_01"
    assert analytics_table("chip_funding_classification_v11_ec") == "analytics.chip_funding_classification_v11_ec"
    assert budget_table("cdc_budget_tracker_raw") == "budget.cdc_budget_tracker_raw"


@pytest.mark.parametrize(
    ("schema", "table"),
    [
        ("public", "bad-name"),
        ("bad-name", "dim_county"),
        ("public", "table.with.dot"),
        ("public", "table name"),
        ("1public", "dim_county"),
        ("public", "1table"),
    ],
)
def test_fqtn_rejects_invalid_identifiers(schema: str, table: str) -> None:
    with pytest.raises(ValueError):
        fqtn(schema, table)
