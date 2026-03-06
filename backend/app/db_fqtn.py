import re

from app.db_schemas import (
    ACS_SCHEMA,
    CMS_SCHEMA,
    HRSA_SCHEMA,
    PLACES_SCHEMA,
    SCHEMA_BY_SOURCE,
    SVI_SCHEMA,
    USDA_FOOD_ACCESS_SCHEMA,
    USDA_FOOD_ENV_SCHEMA,
)

IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validated_identifier(value: str, kind: str) -> str:
    normalized = str(value).strip()
    if not IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"Invalid {kind} identifier: {value!r}")
    return normalized


def fqtn(schema: str, table: str) -> str:
    safe_schema = _validated_identifier(schema, "schema")
    safe_table = _validated_identifier(table, "table")
    return f"{safe_schema}.{safe_table}"


def places_table(name: str) -> str:
    return fqtn(PLACES_SCHEMA, name)


def acs_table(name: str) -> str:
    return fqtn(ACS_SCHEMA, name)


def svi_table(name: str) -> str:
    return fqtn(SVI_SCHEMA, name)


def hrsa_table(name: str) -> str:
    return fqtn(HRSA_SCHEMA, name)


def cms_table(name: str) -> str:
    return fqtn(CMS_SCHEMA, name)


def usda_food_access_table(name: str) -> str:
    return fqtn(USDA_FOOD_ACCESS_SCHEMA, name)


def usda_food_env_table(name: str) -> str:
    return fqtn(USDA_FOOD_ENV_SCHEMA, name)


def source_table(source: str, table: str) -> str:
    source_key = str(source).strip().lower()
    schema = SCHEMA_BY_SOURCE.get(source_key)
    if schema is None:
        raise ValueError(f"Unknown source: {source!r}")
    return fqtn(schema, table)
