from __future__ import annotations

import pytest

from app.db_fqtn import fqtn
from app.db_schemas import SCHEMA_BY_SOURCE


def test_schema_registry_has_expected_sources() -> None:
    assert set(SCHEMA_BY_SOURCE) == {"places", "acs", "svi", "hrsa", "cms"}
    for schema in SCHEMA_BY_SOURCE.values():
        assert isinstance(schema, str)
        assert schema.strip()


def test_fqtn_allows_valid_identifiers() -> None:
    assert fqtn("public", "dim_county") == "public.dim_county"
    assert fqtn("cms", "gv_fact") == "cms.gv_fact"
    assert fqtn("_custom", "table_01") == "_custom.table_01"


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
