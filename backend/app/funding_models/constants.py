from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, SmallInteger

from app.cdc_funding.models import CdcPrimeTransaction
from app.db_fqtn import analytics_table
from app.db_schemas import ANALYTICS_SCHEMA
from app.usaspending.models import UsaspendingContractTransactionRaw

FUNDING_MODELS_SCHEMA = ANALYTICS_SCHEMA
FUNDING_PROFILE_MODELS_TABLE = analytics_table("funding_profile_models")
FUNDING_PROFILE_VERSIONS_TABLE = analytics_table("funding_profile_versions")
FUNDING_PROFILE_BUILD_RUNS_TABLE = analytics_table("funding_profile_build_runs")
FUNDING_MODE_REGISTRY_TABLE = analytics_table("funding_mode_registry")
FUNDING_MODEL_BUILDER_BASE_VIEW = analytics_table("funding_model_builder_base_v1")
FUNDING_MODEL_BUILDER_ASSISTANCE_VIEW = analytics_table("funding_model_builder_assistance_v1")
FUNDING_MODEL_BUILDER_CONTRACT_VIEW = analytics_table("funding_model_builder_contract_v1")

MODEL_STATUS_DRAFT = "draft"
MODEL_STATUS_LOCKED = "locked"
MODEL_STATUS_BUILT = "built"
MODEL_STATUS_PUBLISHED = "published"
MODEL_STATUS_ARCHIVED = "archived"

MODEL_STATUSES = {
    MODEL_STATUS_DRAFT,
    MODEL_STATUS_LOCKED,
    MODEL_STATUS_BUILT,
    MODEL_STATUS_PUBLISHED,
    MODEL_STATUS_ARCHIVED,
}
BUILD_STATUS_PENDING = "pending"
BUILD_STATUS_RUNNING = "running"
BUILD_STATUS_SUCCEEDED = "succeeded"
BUILD_STATUS_FAILED = "failed"
VALIDATION_STATUS_VALID = "valid"
VALIDATION_STATUS_INVALID = "invalid"

DEFAULT_CREATED_BY = "system"
DEFAULT_TIMEOUT_MS = 15000

INTERNAL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ASSET_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
FUNDING_MODE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

DATA_SOURCE_USASPENDING_AWARDS = "usaspending_awards"
DATA_SOURCE_USASPENDING_SUBAWARDS = "usaspending_subawards"
DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS = "usaspending_assistance_transactions"
DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS = "usaspending_contract_transactions"
DATA_SOURCE_TAGGS = "taggs"

ALL_DATA_SOURCE_KEYS = (
    DATA_SOURCE_USASPENDING_AWARDS,
    DATA_SOURCE_USASPENDING_SUBAWARDS,
    DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
    DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
    DATA_SOURCE_TAGGS,
)

FIELD_GROUP_COMMON = "common"
FIELD_GROUP_ASSISTANCE = "assistance"
FIELD_GROUP_CONTRACT = "contract"
FIELD_GROUP_LEGACY_CURATED = "legacy_curated"

FIELD_GROUP_LABELS = {
    FIELD_GROUP_COMMON: "Common",
    FIELD_GROUP_ASSISTANCE: "Assistance Only",
    FIELD_GROUP_CONTRACT: "Contract Only",
    FIELD_GROUP_LEGACY_CURATED: "Legacy Curated",
}

ALLOWED_OPERATORS = {
    "equals",
    "not_equals",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "greater_than",
    "less_than",
    "is_null",
    "is_not_null",
}

NO_VALUE_OPERATORS = {"is_null", "is_not_null"}
SEQUENCE_OPERATORS = {"in", "not_in"}
STRING_MATCH_OPERATORS = {"contains", "not_contains", "starts_with", "ends_with"}

FIELD_OPERATORS_BY_TYPE = {
    "text": (
        "equals",
        "not_equals",
        "in",
        "not_in",
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
        "is_null",
        "is_not_null",
    ),
    "number": (
        "equals",
        "not_equals",
        "in",
        "not_in",
        "greater_than",
        "less_than",
        "is_null",
        "is_not_null",
    ),
    "boolean": (
        "equals",
        "not_equals",
        "is_null",
        "is_not_null",
    ),
    "date": (
        "equals",
        "not_equals",
        "in",
        "not_in",
        "greater_than",
        "less_than",
        "is_null",
        "is_not_null",
    ),
    "datetime": (
        "equals",
        "not_equals",
        "in",
        "not_in",
        "greater_than",
        "less_than",
        "is_null",
        "is_not_null",
    ),
}

_TOKEN_LABEL_OVERRIDES = {
    "cfda": "CFDA",
    "cdc": "CDC",
    "defc": "DEFC",
    "duns": "DUNS",
    "fain": "FAIN",
    "fips": "FIPS",
    "idv": "IDV",
    "naics": "NAICS",
    "piid": "PIID",
    "psc": "PSC",
    "uei": "UEI",
    "uri": "URI",
}

_ASSISTANCE_PREFIX = "assistance"
_CONTRACT_PREFIX = "contract"

_COMMON_FIELD_SPECS = [
    {
        "key": "fiscal_year",
        "column": "fiscal_year",
        "type": "number",
        "label": "Fiscal Year",
        "raw_key": "award_latest_action_date_fiscal_year | subaward_action_date_fiscal_year | action_date_fiscal_year | fiscal_year | funding_fiscal_year",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "action_date",
        "column": "action_date",
        "type": "date",
        "label": "Action Date",
        "raw_key": "action_date",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_SUBAWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
        ],
    },
    {
        "key": "modification_number",
        "column": "modification_number",
        "type": "text",
        "label": "Modification Number",
        "raw_key": "modification_number",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
        ],
    },
    {
        "key": "awarding_agency_name",
        "column": "awarding_agency_name",
        "type": "text",
        "label": "Awarding Agency Name",
        "raw_key": "awarding_agency_name",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
            DATA_SOURCE_TAGGS,
        ],
    },
    {
        "key": "awarding_subagency_name",
        "column": "awarding_subagency_name",
        "type": "text",
        "label": "Awarding Subagency Name",
        "raw_key": "awarding_sub_agency_name | program_office",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "awarding_office_name",
        "column": "awarding_office_name",
        "type": "text",
        "label": "Awarding Office Name",
        "raw_key": "awarding_office_name",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_SUBAWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
        ],
    },
    {
        "key": "funding_agency_name",
        "column": "funding_agency_name",
        "type": "text",
        "label": "Funding Agency Name",
        "raw_key": "funding_agency_name | funding_sub_agency_name | opdiv",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
            DATA_SOURCE_TAGGS,
        ],
    },
    {
        "key": "funding_subagency_name",
        "column": "funding_subagency_name",
        "type": "text",
        "label": "Funding Subagency Name",
        "raw_key": "funding_sub_agency_name",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_SUBAWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
        ],
    },
    {
        "key": "funding_office_name",
        "column": "funding_office_name",
        "type": "text",
        "label": "Funding Office Name",
        "raw_key": "funding_office_name",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_SUBAWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
        ],
    },
    {
        "key": "recipient_name",
        "column": "recipient_name",
        "type": "text",
        "label": "Recipient Name",
        "raw_key": "recipient_name | subawardee_name | legal_entity_name",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "recipient_city_name",
        "column": "recipient_city_name",
        "type": "text",
        "label": "Recipient City Name",
        "raw_key": "recipient_city_name",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_SUBAWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
        ],
    },
    {
        "key": "recipient_state_code",
        "column": "recipient_state_code",
        "type": "text",
        "label": "Recipient State Code",
        "raw_key": "recipient_state_code | subawardee_state_code | legal_entity_state_normalized",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "recipient_state_name",
        "column": "recipient_state_name",
        "type": "text",
        "label": "Recipient State Name",
        "raw_key": "recipient_state_name | subawardee_state_name",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_SUBAWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
        ],
    },
    {
        "key": "recipient_county_fips",
        "column": "recipient_county_fips",
        "type": "text",
        "label": "Recipient County FIPS",
        "raw_key": "recipient_county_fips | subawardee_county_fips | prime_award_transaction_recipient_county_fips_code",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_SUBAWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
        ],
    },
    {
        "key": "recipient_county_name",
        "column": "recipient_county_name",
        "type": "text",
        "label": "Recipient County Name",
        "raw_key": "recipient_county_name | subawardee_county_name | legal_entity_county_normalized",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
            DATA_SOURCE_TAGGS,
        ],
    },
    {
        "key": "award_type",
        "column": "award_type",
        "type": "text",
        "label": "Award Type",
        "raw_key": "assistance_type_description | award_type | subaward_description | award_title",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "assistance_listing",
        "column": "assistance_listing",
        "type": "text",
        "label": "Assistance Listing",
        "raw_key": "cfda_program_title | assistance_listing_title | cfda_title",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_TAGGS,
        ],
    },
    {
        "key": "program_activity",
        "column": "program_activity",
        "type": "text",
        "label": "Program Activity",
        "raw_key": "program_activity_name | program_activities_funding_this_award | prime_award_base_transaction_description | program_office",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "transaction_description",
        "column": "transaction_description",
        "type": "text",
        "label": "Transaction Description",
        "raw_key": "transaction_description",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
        ],
    },
    {
        "key": "prime_award_base_transaction_description",
        "column": "prime_award_base_transaction_description",
        "type": "text",
        "label": "Prime Award Base Transaction Description",
        "raw_key": "prime_award_base_transaction_description",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_SUBAWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
        ],
    },
    {
        "key": "treasury_account",
        "column": "treasury_account",
        "type": "text",
        "label": "Treasury Account",
        "raw_key": "treasury_account_symbol | can_code",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
            DATA_SOURCE_TAGGS,
        ],
    },
    {
        "key": "object_class",
        "column": "object_class",
        "type": "text",
        "label": "Object Class",
        "raw_key": "object_class | object_classes_funding_this_award | product_or_service_code",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
        ],
    },
    {
        "key": "disaster_emergency_fund_code",
        "column": "disaster_emergency_fund_code",
        "type": "text",
        "label": "Disaster Emergency Fund Code",
        "raw_key": "disaster_emergency_fund_codes_raw | disaster_emergency_fund_code",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "transaction_type",
        "column": "transaction_type",
        "type": "text",
        "label": "Transaction Type",
        "raw_key": "transaction_type",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "obligation_amount",
        "column": "obligation_amount",
        "type": "number",
        "label": "Obligation Amount",
        "raw_key": "total_obligated_amount | total_funding_amount | federal_action_obligation | transaction_obligated_amount | subaward_amount | total_sum_of_actions",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "is_emergency_funding",
        "column": "is_emergency_funding",
        "type": "boolean",
        "label": "Is Emergency Funding",
        "raw_key": "derived_from_appropriation_type_or_disaster_code",
        "group": FIELD_GROUP_LEGACY_CURATED,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "source_system",
        "column": "source_system",
        "type": "text",
        "label": "Source System",
        "raw_key": "source_system",
        "group": FIELD_GROUP_LEGACY_CURATED,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "dataset_key",
        "column": "dataset_key",
        "type": "text",
        "label": "Dataset Key",
        "raw_key": "dataset_key",
        "group": FIELD_GROUP_LEGACY_CURATED,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "funding_mechanism",
        "column": "funding_mechanism",
        "type": "text",
        "label": "Funding Mechanism",
        "raw_key": "effective_funding_stream | assistance_type_description | contract_award_type | award_title",
        "group": FIELD_GROUP_LEGACY_CURATED,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "cfda_number",
        "column": "cfda_number",
        "type": "text",
        "label": "CFDA Number",
        "raw_key": "cfda_program_num | assistance_listing_number | cfda_number | aln",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_TAGGS,
        ],
    },
    {
        "key": "appropriation_type",
        "column": "appropriation_type",
        "type": "text",
        "label": "Appropriation Type",
        "raw_key": "appropriation_type",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_SUBAWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
            DATA_SOURCE_TAGGS,
        ],
    },
    {
        "key": "program_area",
        "column": "program_area",
        "type": "text",
        "label": "Program Area",
        "raw_key": "derived_program_area",
        "group": FIELD_GROUP_LEGACY_CURATED,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "category",
        "column": "category",
        "type": "text",
        "label": "Category",
        "raw_key": "derived_category",
        "group": FIELD_GROUP_LEGACY_CURATED,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "subcategory",
        "column": "subcategory",
        "type": "text",
        "label": "Subcategory",
        "raw_key": "derived_subcategory",
        "group": FIELD_GROUP_LEGACY_CURATED,
        "applies_to_sources": list(ALL_DATA_SOURCE_KEYS),
    },
    {
        "key": "usaspending_permalink",
        "column": "usaspending_permalink",
        "type": "text",
        "label": "USAspending Permalink",
        "raw_key": "usaspending_permalink",
        "group": FIELD_GROUP_COMMON,
        "applies_to_sources": [
            DATA_SOURCE_USASPENDING_AWARDS,
            DATA_SOURCE_USASPENDING_SUBAWARDS,
            DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
            DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
        ],
    },
]

_ASSISTANCE_EXCLUDED_COLUMNS = {
    "id",
    "action_date",
    "action_date_fiscal_year",
    "modification_number",
    "awarding_sub_agency_name",
    "funding_sub_agency_name",
    "awarding_office_name",
    "funding_office_name",
    "recipient_name",
    "recipient_city_name",
    "recipient_county_name",
    "recipient_state_code",
    "recipient_state_name",
    "assistance_type_description",
    "transaction_description",
    "prime_award_base_transaction_description",
    "cfda_number",
    "cfda_title",
    "usaspending_permalink",
    "appropriation_type",
    "raw",
    "searchable_text",
    "created_at",
    "updated_at",
}

_CONTRACT_EXCLUDED_COLUMNS = {
    "id",
    "modification_number",
    "action_date",
    "fiscal_year",
    "recipient_name",
    "recipient_state_code",
    "recipient_state_name",
    "recipient_county_name",
    "recipient_city_name",
    "awarding_agency_name",
    "awarding_sub_agency_name",
    "funding_agency_name",
    "funding_sub_agency_name",
    "appropriation_type",
    "award_type",
    "transaction_description",
    "prime_award_base_transaction_description",
    "usaspending_permalink",
    "raw_row_json",
    "loaded_at",
}

DISALLOWED_SQL_PATTERNS = (
    "insert ",
    "update ",
    "delete ",
    "alter ",
    "drop ",
    "truncate ",
    "grant ",
    "revoke ",
    "create ",
    "comment ",
    "vacuum ",
)

APPROVED_SQL_RELATIONS = {
    FUNDING_MODEL_BUILDER_BASE_VIEW,
}

BUILT_IN_FUNDING_MODES = (
    {"value": "chip_normalized_v1_1", "label": "CHIP Normalized Funding v1.1", "system": True},
    {"value": "raw_total", "label": "Raw total funding", "system": True},
    {"value": "chip_normalized", "label": "CHIP Normalized Funding (Legacy)", "system": True},
)

DEFAULT_DEFINITION = {
    "data_sources": {
        "usaspending_awards": True,
        "usaspending_subawards": False,
        "usaspending_assistance_transactions": True,
        "usaspending_contract_transactions": True,
        "taggs": True,
    },
    "options": {
        "include_finalized_only": True,
        "include_deobligations": False,
        "include_negative_adjustments": False,
        "include_pass_through_records": False,
    },
    "include_group": {"id": "include-root", "combinator": "ALL", "children": []},
    "exclude_group": {"id": "exclude-root", "combinator": "ANY", "children": []},
    "advanced_sql_enabled": False,
    "advanced_sql_override": None,
    "aggregation": {
        "default_metric": "normalized_total",
        "supported_geographies": ["nation", "state", "county"],
        "default_geography": "state",
        "default_fiscal_year": None,
    },
}


def _column_type_name(column_type) -> str:
    if isinstance(column_type, Boolean):
        return "boolean"
    if isinstance(column_type, (Integer, SmallInteger, Numeric)):
        return "number"
    if isinstance(column_type, Date):
        return "date"
    if isinstance(column_type, DateTime):
        return "datetime"
    return "text"


def _friendly_label(raw_key: str) -> str:
    pieces = [piece for piece in re.split(r"[_\.]+", str(raw_key or "").strip()) if piece]
    words: list[str] = []
    for piece in pieces:
        token = _TOKEN_LABEL_OVERRIDES.get(piece.lower())
        if token is not None:
            words.append(token)
        elif piece.isdigit():
            words.append(piece)
        else:
            words.append(piece.capitalize())
    return " ".join(words) or "Field"


def _operators_for_type(field_type: str) -> list[str]:
    return list(FIELD_OPERATORS_BY_TYPE[field_type])


def _source_specific_specs(model, *, prefix: str, group: str, data_source_key: str, excluded: Iterable[str]) -> list[dict[str, object]]:
    excluded_columns = set(excluded)
    items: list[dict[str, object]] = []
    for column in model.__table__.columns:
        raw_key = str(column.name)
        if raw_key in excluded_columns:
            continue
        field_type = _column_type_name(column.type)
        items.append(
            {
                "key": f"{prefix}.{raw_key}",
                "column": f"{prefix}_{raw_key}",
                "type": field_type,
                "label": _friendly_label(raw_key),
                "raw_key": raw_key,
                "group": group,
                "applies_to_sources": [data_source_key],
                "operators": _operators_for_type(field_type),
            }
        )
    items.sort(key=lambda item: str(item["label"]).lower())
    return items


def _with_operators(specs: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for spec in specs:
        items.append(
            {
                **spec,
                "operators": _operators_for_type(str(spec["type"])),
            }
        )
    return items


_MANUAL_FIELD_SPECS = _with_operators(_COMMON_FIELD_SPECS)
_ASSISTANCE_FIELD_SPECS = _source_specific_specs(
    CdcPrimeTransaction,
    prefix=_ASSISTANCE_PREFIX,
    group=FIELD_GROUP_ASSISTANCE,
    data_source_key=DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
    excluded=_ASSISTANCE_EXCLUDED_COLUMNS,
)
_CONTRACT_FIELD_SPECS = _source_specific_specs(
    UsaspendingContractTransactionRaw,
    prefix=_CONTRACT_PREFIX,
    group=FIELD_GROUP_CONTRACT,
    data_source_key=DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
    excluded=_CONTRACT_EXCLUDED_COLUMNS,
)

RULE_FIELD_CATALOG: list[dict[str, object]] = [
    *_MANUAL_FIELD_SPECS,
    *_ASSISTANCE_FIELD_SPECS,
    *_CONTRACT_FIELD_SPECS,
]

ALLOWED_RULE_FIELDS: dict[str, dict[str, object]] = {
    str(item["key"]): {
        "column": item["column"],
        "type": item["type"],
        "group": item["group"],
        "label": item["label"],
        "raw_key": item["raw_key"],
        "applies_to_sources": list(item["applies_to_sources"]),
        "operators": list(item["operators"]),
    }
    for item in RULE_FIELD_CATALOG
}


def funding_model_field_catalog() -> list[dict[str, object]]:
    return [
        {
            "key": str(item["key"]),
            "label": str(item["label"]),
            "raw_key": str(item["raw_key"]),
            "type": str(item["type"]),
            "group": str(item["group"]),
            "applies_to_sources": list(item["applies_to_sources"]),
            "operators": list(item["operators"]),
        }
        for item in RULE_FIELD_CATALOG
    ]
