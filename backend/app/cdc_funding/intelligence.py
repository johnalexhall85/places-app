from __future__ import annotations

import copy
import json
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from numbers import Real
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import cdc_funding_table, places_table, taggs_table, usaspending_table
from app.cdc_funding import v11_emergency
from app.cdc_funding import budget_grounded
from app.cdc_funding import canonical
from app.recon.normalization import NORMALIZED_TABLE, fetch_state_normalization_lookup
from app.recon.profile_calibration import METHODOLOGY_VERSION as PROFILE_CALIBRATION_METHODOLOGY_VERSION
from app.services.chip_funding_model import (
    DEFAULT_FUNDING_MODE,
    FUNDING_MODEL_VERSION,
    FUNDING_MODE_LABELS,
    CDCFundingMode,
    CHIPFundingCacheContext,
    CHIPFundingModel,
    is_normalized_funding_mode,
    normalization_lookup_variant_for_mode,
)
from app.funding_models.registry import list_funding_mode_options

PRIME_TABLE = cdc_funding_table("prime_awards")
PRIME_TX_TABLE = cdc_funding_table("prime_transactions")
SUBAWARD_TABLE = cdc_funding_table("subawards")
STATE_BOUNDARY_TABLE = places_table("dim_state_boundary")
COUNTY_BOUNDARY_TABLE = places_table("dim_county_boundary")
COUNTY_DIM_TABLE = places_table("dim_county")
POPULATION_VIEW_TABLE = places_table("v_geography_population")
TAGGS_AWARD_SUMMARY_TABLE = taggs_table("award_funding_summary")
TAGGS_CAN_CLASSIFICATION_TABLE = taggs_table("can_classification")
CONTRACT_ENRICHED_VIEW = usaspending_table("contract_transactions_enriched")
INTELLIGENCE_STATE_CATEGORY_SUMMARY_TABLE = cdc_funding_table("intelligence_state_category_summary")
INTELLIGENCE_STATE_SUBCATEGORY_SUMMARY_TABLE = cdc_funding_table("intelligence_state_subcategory_summary")

VALID_METRICS = {
    "total_funding",
    "funding_per_capita",
    "funding_per_100k",
    "share_national",
}
VALID_FUNDING_TYPES = {
    "total_cdc_funding",
    "awards_only",
    "subawards_only",
    "awards_and_subawards",
    "emergency_response",
    "non_emergency_program",
}
VALID_MECHANISMS = {
    "all",
    "grants",
    "cooperative_agreements",
    "contracts",
    "interagency_agreements",
}
VALID_RECIPIENT_TYPES = {
    "all",
    "state_governments",
    "local_governments",
    "universities",
    "non_profits",
    "hospitals_health_systems",
    "tribal_organizations",
    "private_sector",
}
VALID_GEOGRAPHY_LEVELS = {"county", "state", "national"}
VALID_TIME_AGGREGATIONS = {
    "single_fiscal_year",
    "multi_year_total",
    "multi_year_average",
}
VALID_FUNDING_MODES = {mode.value for mode in CDCFundingMode}

PROGRAM_AREA_OPTIONS = [
    {"value": "all", "label": "All CDC Programs"},
    {"value": "chronic_disease_prevention", "label": "Chronic Disease Prevention"},
    {"value": "injury_prevention", "label": "Injury Prevention"},
    {"value": "environmental_health", "label": "Environmental Health"},
    {
        "value": "emerging_and_zoonotic_infectious_diseases",
        "label": "Emerging and Zoonotic Infectious Diseases",
    },
    {
        "value": "immunization_and_respiratory_diseases",
        "label": "Immunization and Respiratory Diseases",
    },
    {"value": "hiv_std_tb_prevention", "label": "HIV / STD / TB Prevention"},
    {
        "value": "birth_defects_disability_health",
        "label": "Birth Defects / Disability / Health",
    },
    {
        "value": "public_health_preparedness_and_response",
        "label": "Public Health Preparedness and Response",
    },
    {"value": "global_health", "label": "Global Health"},
    {
        "value": "public_health_scientific_services",
        "label": "Public Health Scientific Services",
    },
    {"value": "occupational_safety_and_health", "label": "Occupational Safety and Health"},
    {
        "value": "cross_cutting_activities_and_program_support",
        "label": "Cross-Cutting Activities and Program Support",
    },
    {"value": "other_cdc_programs", "label": "Other / Unclassified"},
]

PROGRAM_AREA_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "chronic_disease_prevention",
        (
            "chronic disease",
            "health promotion",
            "nutrition, physical activity",
            "cancer prevention",
            "diabetes",
            "million hearts",
            "heart disease",
            "obesity",
            "safe motherhood",
        ),
    ),
    (
        "injury_prevention",
        (
            "injury prevention",
            "opioid overdose",
            "drug-free communities",
            "drug free communities",
            "unintentional injury",
            "violence prevention",
        ),
    ),
    (
        "environmental_health",
        (
            "environmental health",
            "toxic substances",
            "atsdr",
            "environmental public health",
        ),
    ),
    (
        "emerging_and_zoonotic_infectious_diseases",
        (
            "emerging and zoonotic",
            "infectious disease",
            "epidemiology and laboratory capacity",
            "elc",
            "vector-borne",
            "zoonotic",
        ),
    ),
    (
        "immunization_and_respiratory_diseases",
        (
            "immunization",
            "vaccines for children",
            "respiratory diseases",
        ),
    ),
    (
        "hiv_std_tb_prevention",
        (
            "hiv",
            "viral hepatitis",
            "sti",
            "sexually transmitted",
            "std",
            "tuberculosis",
            "tb prevention",
        ),
    ),
    (
        "birth_defects_disability_health",
        (
            "birth defects",
            "developmental disabilities",
            "disability and health",
            "disability health",
        ),
    ),
    (
        "public_health_preparedness_and_response",
        (
            "preparedness",
            "crisis response",
            "emergency response",
            "public health emergency preparedness",
            "phep",
            "phssef",
        ),
    ),
    ("global_health", ("global health",)),
    (
        "public_health_scientific_services",
        (
            "public health scientific services",
            "scientific services",
            "surveillance",
            "informatics",
            "laboratory services",
            "laboratory science",
            "data modernization",
        ),
    ),
    (
        "occupational_safety_and_health",
        (
            "occupational safety",
            "niosh",
            "national occupational research agenda",
        ),
    ),
    (
        "cross_cutting_activities_and_program_support",
        (
            "cross-cutting",
            "cross cutting",
            "program support",
            "public health leadership",
            "office for state, tribal, local, and territorial support",
            "state, tribal, local, and territorial support",
        ),
    ),
)

PROGRAM_AREA_LABELS = {option["value"]: option["label"] for option in PROGRAM_AREA_OPTIONS}

METRIC_OPTIONS = [
    {"value": "total_funding", "label": "Total Funding ($)"},
    {"value": "funding_per_capita", "label": "Funding Per Capita"},
    {"value": "funding_per_100k", "label": "Funding Per 100,000 Population"},
    {"value": "share_national", "label": "Share of National CDC Funding (%)"},
]
METRIC_LABELS = {
    "total_funding": "Total CDC Funding",
    "funding_per_capita": "CDC Funding Per Capita",
    "funding_per_100k": "CDC Funding Per 100,000",
    "share_national": "Share of National CDC Funding",
}
FUNDING_TYPE_OPTIONS = [
    {"value": "total_cdc_funding", "label": "Total CDC Funding"},
    {"value": "awards_only", "label": "Awards Only"},
    {"value": "subawards_only", "label": "Subawards Only"},
    {"value": "awards_and_subawards", "label": "Awards + Subawards"},
    {"value": "emergency_response", "label": "Emergency Response Funding"},
    {"value": "non_emergency_program", "label": "Non-Emergency Program Funding"},
]
FUNDING_TYPE_LABELS = {option["value"]: option["label"] for option in FUNDING_TYPE_OPTIONS}
MECHANISM_OPTIONS = [
    {"value": "all", "label": "All Mechanisms"},
    {"value": "grants", "label": "Grants"},
    {"value": "cooperative_agreements", "label": "Cooperative Agreements"},
    {"value": "contracts", "label": "Contracts"},
    {"value": "interagency_agreements", "label": "Interagency Agreements"},
]
MECHANISM_LABELS = {option["value"]: option["label"] for option in MECHANISM_OPTIONS}
RECIPIENT_TYPE_OPTIONS = [
    {"value": "all", "label": "All Recipients"},
    {"value": "state_governments", "label": "State Governments"},
    {"value": "local_governments", "label": "Local Governments"},
    {"value": "universities", "label": "Universities"},
    {"value": "non_profits", "label": "Non-profits"},
    {"value": "hospitals_health_systems", "label": "Hospitals / Health Systems"},
    {"value": "tribal_organizations", "label": "Tribal Organizations"},
    {"value": "private_sector", "label": "Private Sector"},
]
RECIPIENT_TYPE_LABELS = {option["value"]: option["label"] for option in RECIPIENT_TYPE_OPTIONS}
GEOGRAPHY_LEVEL_OPTIONS = [
    {"value": "county", "label": "County"},
    {"value": "state", "label": "State"},
    {"value": "national", "label": "National"},
]
TIME_AGGREGATION_OPTIONS = [
    {"value": "single_fiscal_year", "label": "Single Fiscal Year"},
    {"value": "multi_year_total", "label": "Multi-Year Total"},
    {"value": "multi_year_average", "label": "Multi-Year Average"},
]
TIME_AGGREGATION_LABELS = {option["value"]: option["label"] for option in TIME_AGGREGATION_OPTIONS}
FUNDING_MODE_OPTIONS = [
    {"value": CDCFundingMode.CHIP_NORMALIZED_V11.value, "label": FUNDING_MODE_LABELS[CDCFundingMode.CHIP_NORMALIZED_V11.value]},
    {"value": CDCFundingMode.RAW_TOTAL.value, "label": FUNDING_MODE_LABELS[CDCFundingMode.RAW_TOTAL.value]},
    {"value": CDCFundingMode.CHIP_NORMALIZED.value, "label": FUNDING_MODE_LABELS[CDCFundingMode.CHIP_NORMALIZED.value]},
]

DEFAULT_NOTE = (
    "USAspending provides the transactional funding spine. TAGGS contributes ALN-linked CDC program-area "
    "enrichment, naming, and fallback classification when USAspending labels are too coarse on their own."
)
CHIP_FUNDING_MODEL = CHIPFundingModel()
FUNDING_PROFILE_VERSION = "funding_profile_result_v1"


@dataclass(frozen=True)
class FundingFilters:
    fiscal_year: int | None
    metric: str
    funding_type: str
    funding_mode: str
    program_area: str | None
    mechanism: str | None
    recipient_type: str | None
    geography_level: str
    time_aggregation: str


@dataclass(frozen=True)
class FundingProfileResult:
    geography_type: str
    geography_id: str | None
    geography_name: str | None
    state_code: str | None
    state_name: str | None
    fiscal_year: int | None
    time_aggregation: str
    timeframe_label: str
    funding_mode_requested: str
    funding_mode_effective: str
    funding_mode_label: str
    total_funding: float | None
    funding_per_capita: float | None
    funding_per_100k: float | None
    national_share: float | None
    raw_total_funding: float | None
    chip_normalized_funding: float | None
    raw_funding_per_capita: float | None
    chip_normalized_funding_per_capita: float | None
    raw_funding_per_100k: float | None
    chip_normalized_funding_per_100k: float | None
    raw_share_of_national: float | None
    chip_normalized_share_of_national: float | None
    awards_total: float | None
    subawards_total: float | None
    contracts_total: float | None
    award_count: int
    subaward_count: int
    contract_award_count: int
    population: float | None
    normalization_supported: bool
    normalization_applied: bool
    normalization_note: str | None
    normalization_factor: float | None
    normalized_amount_type: str | None
    normalization_status_label: str | None
    normalization_method: str | None
    funding_stream_logic_version: str | None
    methodology_version: str
    profile_version: str
    funding_model_version: str
    metadata: dict[str, Any]


class _ResponseCache:
    def __init__(self, *, max_size: int = 64, ttl_seconds: int = 300) -> None:
        self._max_size = max(1, int(max_size))
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        cached = self._cache.get(key)
        if cached is None:
            return None
        cached_at, payload = cached
        if time.time() - cached_at > self._ttl_seconds:
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return copy.deepcopy(payload)

    def set(self, key: str, payload: Any) -> None:
        self._cache[key] = (time.time(), copy.deepcopy(payload))
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)


SUMMARY_RESPONSE_CACHE = _ResponseCache(max_size=128, ttl_seconds=900)


def _json_number(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return float(value)
    if isinstance(value, Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return value


def _serialize_value(value: Any) -> Any:
    numeric = _json_number(value)
    if numeric is not value:
        return numeric
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return value
    return value


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:name) AS exists"),
        {"name": table_name},
    ).mappings().one()
    return row["exists"] is not None


def _table_has_rows(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(f"SELECT EXISTS (SELECT 1 FROM {table_name} LIMIT 1) AS has_rows"),
    ).mappings().one()
    return bool(row.get("has_rows"))


def _ensure_required_tables(db: Session) -> None:
    required = [
        PRIME_TABLE,
        PRIME_TX_TABLE,
        SUBAWARD_TABLE,
        STATE_BOUNDARY_TABLE,
        COUNTY_BOUNDARY_TABLE,
        COUNTY_DIM_TABLE,
        POPULATION_VIEW_TABLE,
        TAGGS_AWARD_SUMMARY_TABLE,
        TAGGS_CAN_CLASSIFICATION_TABLE,
        CONTRACT_ENRICHED_VIEW,
    ]
    missing = [table_name for table_name in required if not _table_exists(db, table_name)]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "Required CDC funding intelligence tables are missing: "
                + ", ".join(missing)
                + ". Run the CDC funding, TAGGS, and USAspending ingests first."
            ),
        )


def _intelligence_summary_tables_available(db: Session) -> bool:
    return (
        _table_exists(db, INTELLIGENCE_STATE_CATEGORY_SUMMARY_TABLE)
        and _table_exists(db, INTELLIGENCE_STATE_SUBCATEGORY_SUMMARY_TABLE)
        and _table_has_rows(db, INTELLIGENCE_STATE_CATEGORY_SUMMARY_TABLE)
        and _table_has_rows(db, INTELLIGENCE_STATE_SUBCATEGORY_SUMMARY_TABLE)
    )


def _summary_refresh_signature(db: Session) -> str | None:
    if not _intelligence_summary_tables_available(db):
        return None
    row = db.execute(
        text(
            f"""
            SELECT CONCAT_WS(
                '|',
                COALESCE((SELECT MAX(refreshed_at)::text FROM {INTELLIGENCE_STATE_CATEGORY_SUMMARY_TABLE}), 'none'),
                COALESCE((SELECT MAX(refreshed_at)::text FROM {INTELLIGENCE_STATE_SUBCATEGORY_SUMMARY_TABLE}), 'none'),
                COALESCE(
                    (
                        SELECT MAX(refreshed_at)::text
                        FROM {NORMALIZED_TABLE}
                        WHERE source_system = 'usaspending'
                    ),
                    'none'
                )
            ) AS signature
            """
        )
    ).mappings().one()
    signature = str(row.get("signature") or "").strip()
    return signature or None


def _summary_cache_key(
    *,
    scope: str,
    filters: FundingFilters,
    include_geometry: bool = False,
    bbox: str | None = None,
    limit: int | None = None,
    state: str | None = None,
    refresh_signature: str | None = None,
) -> str:
    return json.dumps(
        {
            "scope": scope,
            "filters": {
                "fiscal_year": filters.fiscal_year,
                "metric": filters.metric,
                "funding_type": filters.funding_type,
                "funding_mode": filters.funding_mode,
                "program_area": filters.program_area,
                "mechanism": filters.mechanism,
                "recipient_type": filters.recipient_type,
                "geography_level": filters.geography_level,
                "time_aggregation": filters.time_aggregation,
            },
            "include_geometry": include_geometry,
            "bbox": bbox,
            "limit": limit,
            "state": state,
            "refresh_signature": refresh_signature,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_cached_summary_payload(
    db: Session,
    *,
    scope: str,
    filters: FundingFilters,
    include_geometry: bool = False,
    bbox: str | None = None,
    limit: int | None = None,
    state: str | None = None,
    loader: Any,
) -> Any:
    refresh_signature = _summary_refresh_signature(db)
    if refresh_signature is None:
        return loader()
    cache_key = _summary_cache_key(
        scope=scope,
        filters=filters,
        include_geometry=include_geometry,
        bbox=bbox,
        limit=limit,
        state=state,
        refresh_signature=refresh_signature,
    )
    cached = SUMMARY_RESPONSE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    payload = loader()
    SUMMARY_RESPONSE_CACHE.set(cache_key, payload)
    return payload


def _strip_optional(value: str | None) -> str | None:
    token = str(value or "").strip()
    return token or None


def _normalize_metric(value: str | None) -> str:
    token = str(value or "total_funding").strip().lower()
    if token not in VALID_METRICS:
        allowed = ", ".join(sorted(VALID_METRICS))
        raise HTTPException(status_code=400, detail=f"metric must be one of {allowed}")
    return token


def _normalize_funding_type(value: str | None) -> str:
    token = str(value or "total_cdc_funding").strip().lower()
    if token not in VALID_FUNDING_TYPES:
        allowed = ", ".join(sorted(VALID_FUNDING_TYPES))
        raise HTTPException(status_code=400, detail=f"funding_type must be one of {allowed}")
    return token


def _normalize_funding_mode(value: str | None) -> str:
    token = str(value or DEFAULT_FUNDING_MODE).strip().lower()
    if token not in VALID_FUNDING_MODES:
        allowed = ", ".join(sorted(VALID_FUNDING_MODES))
        raise HTTPException(status_code=400, detail=f"funding_mode must be one of {allowed}")
    return token


def _normalize_program_area(value: str | None) -> str | None:
    token = str(value or "").strip().lower()
    if not token or token == "all":
        return None
    allowed = {option["value"] for option in PROGRAM_AREA_OPTIONS if option["value"] != "all"}
    if token not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise HTTPException(status_code=400, detail=f"cdc_center must be one of all, {allowed_text}")
    return token


def _normalize_mechanism(value: str | None) -> str | None:
    token = str(value or "all").strip().lower()
    if token not in VALID_MECHANISMS:
        allowed = ", ".join(sorted(VALID_MECHANISMS))
        raise HTTPException(status_code=400, detail=f"mechanism must be one of {allowed}")
    return None if token == "all" else token


def _normalize_recipient_type(value: str | None) -> str | None:
    token = str(value or "all").strip().lower()
    if token not in VALID_RECIPIENT_TYPES:
        allowed = ", ".join(sorted(VALID_RECIPIENT_TYPES))
        raise HTTPException(status_code=400, detail=f"recipient_type must be one of {allowed}")
    return None if token == "all" else token


def _normalize_geography_level(value: str | None) -> str:
    token = str(value or "county").strip().lower()
    if token not in VALID_GEOGRAPHY_LEVELS:
        allowed = ", ".join(sorted(VALID_GEOGRAPHY_LEVELS))
        raise HTTPException(status_code=400, detail=f"geography_level must be one of {allowed}")
    return token


def _normalize_time_aggregation(value: str | None, *, fiscal_year: int | None) -> str:
    default_value = "single_fiscal_year" if fiscal_year is not None else "multi_year_total"
    token = str(value or default_value).strip().lower()
    if token not in VALID_TIME_AGGREGATIONS:
        allowed = ", ".join(sorted(VALID_TIME_AGGREGATIONS))
        raise HTTPException(status_code=400, detail=f"time_aggregation must be one of {allowed}")
    if fiscal_year is None and token == "single_fiscal_year":
        raise HTTPException(
            status_code=400,
            detail="time_aggregation=single_fiscal_year requires a specific fiscal_year",
        )
    return token


def _normalize_filters(
    *,
    fiscal_year: int | None,
    metric: str | None,
    funding_type: str | None,
    funding_mode: str | None,
    cdc_center: str | None,
    program_area: str | None,
    mechanism: str | None,
    recipient_type: str | None,
    geography_level: str | None,
    time_aggregation: str | None,
) -> FundingFilters:
    effective_fiscal_year = int(fiscal_year) if fiscal_year is not None else None
    effective_program_area = _normalize_program_area(cdc_center or program_area)
    return FundingFilters(
        fiscal_year=effective_fiscal_year,
        metric=_normalize_metric(metric),
        funding_type=_normalize_funding_type(funding_type),
        funding_mode=_normalize_funding_mode(funding_mode),
        program_area=effective_program_area,
        mechanism=_normalize_mechanism(mechanism),
        recipient_type=_normalize_recipient_type(recipient_type),
        geography_level=_normalize_geography_level(geography_level),
        time_aggregation=_normalize_time_aggregation(
            time_aggregation,
            fiscal_year=effective_fiscal_year,
        ),
    )


def _matching_rule(value: str, patterns: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(pattern in lowered for pattern in patterns)


def canonical_program_area(*values: Any) -> str:
    combined = " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())
    if not combined:
        return "other_cdc_programs"
    for program_area, patterns in PROGRAM_AREA_RULES:
        if _matching_rule(combined, patterns):
            return program_area
    return "other_cdc_programs"


def classify_mechanism(
    *,
    component: str,
    assistance_type_description: str | None = None,
    contract_award_type: str | None = None,
) -> str:
    if component == "contract":
        if "interagency" in str(contract_award_type or "").strip().lower():
            return "interagency_agreements"
        return "contracts"
    token = str(assistance_type_description or "").strip().lower()
    if "interagency" in token:
        return "interagency_agreements"
    if "cooperative" in token:
        return "cooperative_agreements"
    if "grant" in token:
        return "grants"
    return "grants"


def classify_recipient_type(name: str | None) -> str:
    token = str(name or "").strip().lower()
    if not token:
        return "non_profits"
    if any(piece in token for piece in ("tribe", "tribal", "pueblo", "rancheria", "nation")):
        return "tribal_organizations"
    if any(piece in token for piece in ("university", "college", "school of medicine", "community college")):
        return "universities"
    if any(piece in token for piece in ("hospital", "medical center", "health system", "healthcare system", "clinic")):
        return "hospitals_health_systems"
    if any(piece in token for piece in ("county", "city of", "parish", "borough", "municipal", "public health district")):
        return "local_governments"
    if any(
        piece in token
        for piece in (
            "state of ",
            "department of health",
            "department of public health",
            "state health",
            "commonwealth of ",
        )
    ):
        return "state_governments"
    if any(piece in token for piece in ("llc", "corp", "corporation", "inc", "ltd", "company", "co.")):
        return "private_sector"
    if any(piece in token for piece in ("foundation", "association", "coalition", "network", "institute", "society", "center for")):
        return "non_profits"
    return "non_profits"


def _safe_sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _program_area_case_sql(expr: str) -> str:
    when_clauses: list[str] = []
    for program_area, patterns in PROGRAM_AREA_RULES:
        checks = [
            f"LOWER(COALESCE({expr}, '')) LIKE '%{_safe_sql_literal(pattern)}%'"
            for pattern in patterns
        ]
        when_clauses.append(f"WHEN {' OR '.join(checks)} THEN '{program_area}'")
    return "CASE " + " ".join(when_clauses) + " ELSE 'other_cdc_programs' END"


def _mechanism_case_sql(
    *,
    component_expr: str,
    assistance_type_expr: str,
    contract_award_type_expr: str,
) -> str:
    return (
        "CASE "
        f"WHEN {component_expr} = 'contract' AND LOWER(COALESCE({contract_award_type_expr}, '')) LIKE '%interagency%' "
        "THEN 'interagency_agreements' "
        f"WHEN {component_expr} = 'contract' THEN 'contracts' "
        f"WHEN LOWER(COALESCE({assistance_type_expr}, '')) LIKE '%interagency%' THEN 'interagency_agreements' "
        f"WHEN LOWER(COALESCE({assistance_type_expr}, '')) LIKE '%cooperative%' THEN 'cooperative_agreements' "
        f"WHEN LOWER(COALESCE({assistance_type_expr}, '')) LIKE '%grant%' THEN 'grants' "
        "ELSE 'grants' END"
    )


def _recipient_type_case_sql(expr: str) -> str:
    return (
        "CASE "
        f"WHEN LOWER(COALESCE({expr}, '')) ~ '(tribe|tribal|pueblo|rancheria|nation)' THEN 'tribal_organizations' "
        f"WHEN LOWER(COALESCE({expr}, '')) ~ '(university|college|school of medicine|community college)' THEN 'universities' "
        f"WHEN LOWER(COALESCE({expr}, '')) ~ '(hospital|medical center|health system|healthcare system|clinic)' THEN 'hospitals_health_systems' "
        f"WHEN LOWER(COALESCE({expr}, '')) ~ '(county|city of|parish|borough|municipal|public health district)' THEN 'local_governments' "
        f"WHEN LOWER(COALESCE({expr}, '')) ~ '(state of |department of health|department of public health|state health|commonwealth of )' THEN 'state_governments' "
        f"WHEN LOWER(COALESCE({expr}, '')) ~ '(llc|corp|corporation|inc|ltd|company|co\\.)' THEN 'private_sector' "
        "ELSE 'non_profits' END"
    )


def _normalized_aln_expr(column_expr: str) -> str:
    return f"LPAD(REGEXP_REPLACE(COALESCE({column_expr}, ''), '[^0-9]', '', 'g'), 5, '0')"


def _normalized_county_key_expr(column_expr: str) -> str:
    return f"UPPER(REGEXP_REPLACE(COALESCE({column_expr}, ''), '[^A-Za-z0-9]', '', 'g'))"


def _bbox_params(bbox: str | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    try:
        minx, miny, maxx, maxy = [float(item) for item in str(bbox).split(",")]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bbox must be minLon,minLat,maxLon,maxLat") from exc
    if minx >= maxx or miny >= maxy:
        raise HTTPException(status_code=400, detail="bbox bounds are invalid")
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


def _compute_bins(values: list[float], bins: int = 5) -> list[dict[str, Any]]:
    if not values:
        return []
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        value = sorted_values[0]
        return [{"min": value, "max": value, "label": f"{value:,.2f}", "colorIndex": 0}]

    quantiles: list[float] = []
    for index in range(1, bins):
        raw_position = (len(sorted_values) - 1) * (index / bins)
        lower_idx = int(math.floor(raw_position))
        upper_idx = int(math.ceil(raw_position))
        lower = sorted_values[lower_idx]
        upper = sorted_values[upper_idx]
        if lower_idx == upper_idx:
            quantile = lower
        else:
            ratio = raw_position - lower_idx
            quantile = lower + (upper - lower) * ratio
        quantiles.append(float(quantile))

    points = [sorted_values[0], *quantiles, sorted_values[-1]]
    deduped: list[float] = []
    for point in points:
        if not deduped or point > deduped[-1]:
            deduped.append(point)
    if len(deduped) < 2:
        deduped = [sorted_values[0], sorted_values[-1]]

    output: list[dict[str, Any]] = []
    for index in range(len(deduped) - 1):
        lower = deduped[index]
        upper = deduped[index + 1]
        output.append(
            {
                "min": lower,
                "max": upper,
                "label": f"{lower:,.2f} - {upper:,.2f}",
                "colorIndex": index,
            }
        )
    return output


def _metric_value(row: dict[str, Any], metric: str) -> float | None:
    if metric == "total_funding":
        return _json_number(row.get("chip_total_funding"))
    if metric == "funding_per_capita":
        return _json_number(row.get("chip_per_capita_funding"))
    if metric == "funding_per_100k":
        return _json_number(row.get("chip_per_100k_funding"))
    if metric == "share_national":
        return _json_number(row.get("chip_share_of_national"))
    return None


def _profile_metric_value(profile: FundingProfileResult, metric: str) -> float | None:
    if metric == "total_funding":
        return profile.total_funding
    if metric == "funding_per_capita":
        return profile.funding_per_capita
    if metric == "funding_per_100k":
        return profile.funding_per_100k
    if metric == "share_national":
        return profile.national_share
    return None


def _chip_cache_context(
    filters: FundingFilters,
    *,
    scope: str,
    bbox: str | None = None,
    limit: int | None = None,
    state: str | None = None,
) -> CHIPFundingCacheContext:
    return CHIPFundingCacheContext(
        scope=scope,
        geography_level=filters.geography_level,
        fiscal_year=filters.fiscal_year,
        time_aggregation=filters.time_aggregation,
        funding_type=filters.funding_type,
        funding_mode=filters.funding_mode,
        program_area=filters.program_area,
        mechanism=filters.mechanism,
        recipient_type=filters.recipient_type,
        bbox=bbox,
        limit=limit,
        state=state,
    )


def _funding_profile_metadata(
    row: dict[str, Any],
    filters: FundingFilters,
    *,
    min_fiscal_year: int | None,
    max_fiscal_year: int | None,
) -> dict[str, Any]:
    return {
        "metric_context": _filter_context_payload(
            filters,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
        ),
        "chip_equity_adjusted_metrics": row.get("chip_equity_adjusted_metrics") or {},
        "funding_mode": {
            "requested": row.get("funding_mode_requested"),
            "effective": row.get("funding_mode_effective"),
            "label": row.get("funding_mode_label"),
            "normalization_supported": bool(row.get("normalization_supported")),
            "normalization_applied": bool(row.get("normalization_applied")),
            "normalization_note": row.get("normalization_note"),
            "normalization_factor": _json_number(row.get("normalization_factor")),
            "normalized_amount_type": row.get("normalized_amount_type"),
            "normalization_status_label": row.get("normalization_status_label"),
            "normalization_method": row.get("normalization_method"),
            "funding_stream_logic_version": row.get("funding_stream_logic_version"),
            "methodology_version": row.get("methodology_version"),
        },
        "chip_rollout_status": row.get("chip_rollout_status"),
        "chip_state_profile_source_version": row.get("chip_state_profile_source_version"),
        "chip_normalization_source_version": row.get("chip_normalization_source_version"),
        "run_id": row.get("run_id"),
        "min_fiscal_year": min_fiscal_year,
        "max_fiscal_year": max_fiscal_year,
    }


def _funding_profile_result_from_row(
    row: dict[str, Any],
    filters: FundingFilters,
) -> FundingProfileResult:
    min_fiscal_year = int(row["min_fiscal_year"]) if row.get("min_fiscal_year") is not None else None
    max_fiscal_year = int(row["max_fiscal_year"]) if row.get("max_fiscal_year") is not None else None
    return FundingProfileResult(
        geography_type=filters.geography_level,
        geography_id=str(row.get("geography_id")) if row.get("geography_id") is not None else None,
        geography_name=row.get("geography_name"),
        state_code=row.get("state_code"),
        state_name=row.get("state_name"),
        fiscal_year=filters.fiscal_year,
        time_aggregation=filters.time_aggregation,
        timeframe_label=_timeframe_label(
            fiscal_year=filters.fiscal_year,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
            time_aggregation=filters.time_aggregation,
        ),
        funding_mode_requested=str(row.get("funding_mode_requested") or filters.funding_mode),
        funding_mode_effective=str(row.get("funding_mode_effective") or filters.funding_mode),
        funding_mode_label=str(
            row.get("funding_mode_label")
            or FUNDING_MODE_LABELS.get(str(row.get("funding_mode_effective") or filters.funding_mode), "CDC funding")
        ),
        total_funding=_json_number(row.get("total_funding_amount")),
        funding_per_capita=_json_number(row.get("funding_per_capita")),
        funding_per_100k=_json_number(row.get("funding_per_100k")),
        national_share=_json_number(row.get("share_national_pct")),
        raw_total_funding=_json_number(row.get("raw_total_funding")),
        chip_normalized_funding=_json_number(row.get("chip_normalized_funding")),
        raw_funding_per_capita=_json_number(row.get("raw_funding_per_capita")),
        chip_normalized_funding_per_capita=_json_number(row.get("chip_normalized_funding_per_capita")),
        raw_funding_per_100k=_json_number(row.get("raw_funding_per_100k")),
        chip_normalized_funding_per_100k=_json_number(row.get("chip_normalized_funding_per_100k")),
        raw_share_of_national=_json_number(row.get("raw_share_of_national")),
        chip_normalized_share_of_national=_json_number(row.get("chip_normalized_share_of_national")),
        awards_total=_json_number(row.get("awards_amount")),
        subawards_total=_json_number(row.get("subawards_amount")),
        contracts_total=_json_number(row.get("contracts_amount")),
        award_count=int(row.get("award_count") or 0),
        subaward_count=int(row.get("subaward_count") or 0),
        contract_award_count=int(row.get("contract_award_count") or 0),
        population=_json_number(row.get("population")),
        normalization_supported=bool(row.get("normalization_supported")),
        normalization_applied=bool(row.get("normalization_applied")),
        normalization_note=row.get("normalization_note"),
        normalization_factor=_json_number(row.get("normalization_factor")),
        normalized_amount_type=row.get("normalized_amount_type"),
        normalization_status_label=row.get("normalization_status_label"),
        normalization_method=row.get("normalization_method"),
        funding_stream_logic_version=row.get("funding_stream_logic_version"),
        methodology_version=str(row.get("methodology_version") or PROFILE_CALIBRATION_METHODOLOGY_VERSION),
        profile_version=str(row.get("profile_version") or FUNDING_PROFILE_VERSION),
        funding_model_version=str(row.get("funding_model_version") or FUNDING_MODEL_VERSION),
        metadata=_funding_profile_metadata(
            row,
            filters,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
        ),
    )


def _serialize_funding_profile_result(profile: FundingProfileResult) -> dict[str, Any]:
    return {
        "geography_type": profile.geography_type,
        "geography_id": profile.geography_id,
        "geography_name": profile.geography_name,
        "state_code": profile.state_code,
        "state_name": profile.state_name,
        "fiscal_year": profile.fiscal_year,
        "time_aggregation": profile.time_aggregation,
        "timeframe_label": profile.timeframe_label,
        "funding_mode_requested": profile.funding_mode_requested,
        "funding_mode_effective": profile.funding_mode_effective,
        "funding_mode_label": profile.funding_mode_label,
        "total_funding": profile.total_funding,
        "funding_per_capita": profile.funding_per_capita,
        "funding_per_100k": profile.funding_per_100k,
        "national_share": profile.national_share,
        "raw_total_funding": profile.raw_total_funding,
        "chip_normalized_funding": profile.chip_normalized_funding,
        "raw_funding_per_capita": profile.raw_funding_per_capita,
        "chip_normalized_funding_per_capita": profile.chip_normalized_funding_per_capita,
        "raw_funding_per_100k": profile.raw_funding_per_100k,
        "chip_normalized_funding_per_100k": profile.chip_normalized_funding_per_100k,
        "raw_share_of_national": profile.raw_share_of_national,
        "chip_normalized_share_of_national": profile.chip_normalized_share_of_national,
        "awards_total": profile.awards_total,
        "subawards_total": profile.subawards_total,
        "contracts_total": profile.contracts_total,
        "award_count": profile.award_count,
        "subaward_count": profile.subaward_count,
        "contract_award_count": profile.contract_award_count,
        "population": profile.population,
        "normalization_supported": profile.normalization_supported,
        "normalization_applied": profile.normalization_applied,
        "normalization_note": profile.normalization_note,
        "normalization_factor": profile.normalization_factor,
        "normalized_amount_type": profile.normalized_amount_type,
        "normalization_status_label": profile.normalization_status_label,
        "normalization_method": profile.normalization_method,
        "funding_stream_logic_version": profile.funding_stream_logic_version,
        "methodology_version": profile.methodology_version,
        "profile_version": profile.profile_version,
        "funding_model_version": profile.funding_model_version,
        "metadata": profile.metadata,
    }


def _timeframe_label(
    *,
    fiscal_year: int | None,
    min_fiscal_year: int | None,
    max_fiscal_year: int | None,
    time_aggregation: str,
) -> str:
    if fiscal_year is not None:
        return f"FY{fiscal_year}"
    if min_fiscal_year is None or max_fiscal_year is None:
        return "All Years"
    if min_fiscal_year == max_fiscal_year:
        return f"FY{min_fiscal_year}"
    if time_aggregation == "multi_year_average":
        return f"FY{min_fiscal_year}-FY{max_fiscal_year} Multi-Year Average"
    return f"FY{min_fiscal_year}-FY{max_fiscal_year}"


def build_legend_title(
    *,
    metric: str,
    fiscal_year: int | None,
    min_fiscal_year: int | None,
    max_fiscal_year: int | None,
    time_aggregation: str,
) -> str:
    metric_label = METRIC_LABELS[metric]
    if fiscal_year is not None:
        return f"FY{fiscal_year} {metric_label}"
    if min_fiscal_year is None or max_fiscal_year is None:
        return f"All Years {metric_label}"
    if min_fiscal_year == max_fiscal_year:
        return f"FY{min_fiscal_year} {metric_label}"
    if time_aggregation == "multi_year_average":
        return f"FY{min_fiscal_year}-FY{max_fiscal_year} Multi-Year Average {metric_label}"
    return f"FY{min_fiscal_year}-FY{max_fiscal_year} {metric_label}"


def _funding_type_note(funding_type: str) -> str | None:
    if funding_type == "total_cdc_funding":
        return (
            "Default CHIP totals use prime USAspending award transactions as the core funding measure. "
            "They also include a narrow contract slice only when the contract layer is flagged as profile-relevant."
        )
    if funding_type == "awards_and_subawards":
        return (
            "Awards + Subawards is an exploratory view for analysts. Subawards are downstream of prime awards and "
            "can overlap with prime-award totals."
        )
    if funding_type == "subawards_only":
        return "Subaward totals show downstream funding reported to subrecipients and are separate from CHIP default totals."
    return None


def _metric_note(metric: str) -> str | None:
    if metric == "funding_per_capita":
        return "Per-capita values use the app population denominator derived from county population rollups."
    if metric == "funding_per_100k":
        return "Per-100,000 values use the app population denominator derived from county population rollups."
    if metric == "share_national":
        return "Share values are calculated against the filtered national CDC funding total for the active selection."
    return None


def _funding_mode_note(filters: FundingFilters) -> str:
    if filters.funding_mode == CDCFundingMode.CHIP_NORMALIZED_V11.value:
        return (
            "CHIP Normalized Funding v1.1 preserves the raw within-state distribution but rescales it to the v1.1 emergency-classification state-profile benchmark."
        )
    if filters.funding_mode == CDCFundingMode.CHIP_NORMALIZED.value:
        return (
            "CHIP Normalized Funding (Legacy) applies the frozen funding-scope reconstruction layer when the active CDC view "
            "matches the calibrated statewide total contract."
        )
    return "Raw total funding displays summed source obligations without CHIP funding-scope normalization."


def _time_aggregation_note(time_aggregation: str) -> str | None:
    if time_aggregation == "multi_year_average":
        return "Multi-Year Average divides the filtered funding total by the number of fiscal years represented in the filtered result set."
    if time_aggregation == "multi_year_total":
        return "Multi-Year Total sums funding across all filtered fiscal years."
    return None


def _active_filter_note(filters: FundingFilters) -> str:
    note_parts = [DEFAULT_NOTE, _funding_mode_note(filters)]
    note_parts.extend(
        part
        for part in (
            _funding_type_note(filters.funding_type),
            _metric_note(filters.metric),
            _time_aggregation_note(filters.time_aggregation),
            (
                "Emergency funding is classified from source appropriation flags. Records tagged as "
                "covid_emergency or other_emergency are treated as Emergency Response Funding."
                if filters.funding_type == "emergency_response"
                else None
            ),
            (
                "Non-Emergency Program Funding excludes rows tagged as covid_emergency or other_emergency."
                if filters.funding_type == "non_emergency_program"
                else None
            ),
        )
        if part
    )
    return " ".join(note_parts)


def _filter_context_payload(
    filters: FundingFilters,
    *,
    min_fiscal_year: int | None,
    max_fiscal_year: int | None,
) -> dict[str, Any]:
    return {
        "fiscal_year": filters.fiscal_year,
        "metric": filters.metric,
        "metric_label": METRIC_LABELS[filters.metric],
        "funding_type": filters.funding_type,
        "funding_type_label": FUNDING_TYPE_LABELS[filters.funding_type],
        "funding_mode": filters.funding_mode,
        "funding_mode_label": FUNDING_MODE_LABELS[filters.funding_mode],
        "cdc_center": filters.program_area,
        "cdc_center_label": (
            PROGRAM_AREA_LABELS.get(filters.program_area)
            if filters.program_area is not None
            else "All CDC Programs"
        ),
        "mechanism": filters.mechanism,
        "mechanism_label": (
            MECHANISM_LABELS.get(filters.mechanism)
            if filters.mechanism is not None
            else "All Mechanisms"
        ),
        "recipient_type": filters.recipient_type,
        "recipient_type_label": (
            RECIPIENT_TYPE_LABELS.get(filters.recipient_type)
            if filters.recipient_type is not None
            else "All Recipients"
        ),
        "geography_level": filters.geography_level,
        "time_aggregation": filters.time_aggregation,
        "time_aggregation_label": TIME_AGGREGATION_LABELS[filters.time_aggregation],
        "min_fiscal_year": min_fiscal_year,
        "max_fiscal_year": max_fiscal_year,
        "legend_title": build_legend_title(
            metric=filters.metric,
            fiscal_year=filters.fiscal_year,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
            time_aggregation=filters.time_aggregation,
        ),
    }


def _integrated_rows_cte() -> str:
    aln_key = _normalized_aln_expr("s.aln")
    dominant_category_rank = (
        "ROW_NUMBER() OVER ("
        "PARTITION BY "
        f"{aln_key} "
        "ORDER BY SUM(ABS(COALESCE(s.total_sum_of_actions, 0))) DESC, "
        "MAX(COALESCE(NULLIF(TRIM(c.effective_category), ''), 'zzzzzz')) ASC"
        ")"
    )
    contract_county_key = _normalized_county_key_expr("e.recipient_county_name")
    county_dim_key = _normalized_county_key_expr("c.county_name")
    award_program_area = _program_area_case_sql(
        "COALESCE(aln_map.raw_category, '') || ' ' || COALESCE(aln_map.program_name, '') || ' ' || "
        "COALESCE(base.center_text, '') || ' ' || COALESCE(base.program_title, '') || ' ' || COALESCE(base.contract_category_guess, '')"
    )
    mechanism_case = _mechanism_case_sql(
        component_expr="base.component",
        assistance_type_expr="base.assistance_type_description",
        contract_award_type_expr="base.contract_award_type",
    )
    recipient_case = _recipient_type_case_sql("base.recipient_name")
    return f"""
        WITH taggs_aln_candidates AS (
            SELECT
                {aln_key} AS aln_key,
                NULLIF(TRIM(c.effective_category), '') AS raw_category,
                COALESCE(
                    NULLIF(TRIM(c.effective_program_name), ''),
                    NULLIF(TRIM(c.effective_subcategory), ''),
                    NULLIF(TRIM(s.assistance_listing_title), '')
                ) AS program_name,
                SUM(ABS(COALESCE(s.total_sum_of_actions, 0)))::numeric AS weight,
                {dominant_category_rank} AS rn
            FROM {TAGGS_AWARD_SUMMARY_TABLE} AS s
            LEFT JOIN {TAGGS_CAN_CLASSIFICATION_TABLE} AS c
                ON c.can_code = s.can_code
            WHERE NULLIF(TRIM(s.aln), '') IS NOT NULL
              AND NULLIF(TRIM(c.effective_category), '') IS NOT NULL
            GROUP BY
                {aln_key},
                NULLIF(TRIM(c.effective_category), ''),
                COALESCE(
                    NULLIF(TRIM(c.effective_program_name), ''),
                    NULLIF(TRIM(c.effective_subcategory), ''),
                    NULLIF(TRIM(s.assistance_listing_title), '')
                )
        ),
        taggs_aln_mapping AS (
            SELECT
                aln_key,
                raw_category,
                program_name
            FROM taggs_aln_candidates
            WHERE rn = 1
        ),
        contract_county_lookup AS (
            SELECT
                e.id,
                c.location_id AS county_fips
            FROM {CONTRACT_ENRICHED_VIEW} AS e
            LEFT JOIN {COUNTY_DIM_TABLE} AS c
                ON c.state_abbr = e.recipient_state_code
               AND {county_dim_key} = {contract_county_key}
        ),
        base_rows AS (
            SELECT
                COALESCE(NULLIF(TRIM(tx.assistance_transaction_unique_key), ''), tx.id::text) AS row_key,
                COALESCE(
                    NULLIF(TRIM(p.fain), ''),
                    NULLIF(TRIM(tx.award_id_fain), ''),
                    NULLIF(TRIM(tx.assistance_award_unique_key), ''),
                    tx.id::text
                ) AS award_key,
                'award'::text AS component,
                tx.action_date_fiscal_year::integer AS fiscal_year,
                COALESCE(NULLIF(TRIM(tx.recipient_state_code), ''), NULLIF(TRIM(p.recipient_state_code), '')) AS state_code,
                COALESCE(
                    NULLIF(TRIM(tx.prime_award_transaction_recipient_county_fips_code), ''),
                    NULLIF(TRIM(p.recipient_county_fips), '')
                ) AS county_fips,
                COALESCE(NULLIF(TRIM(tx.recipient_name), ''), NULLIF(TRIM(p.recipient_name), ''), 'Unknown recipient') AS recipient_name,
                COALESCE(NULLIF(TRIM(p.assistance_type_description), ''), NULLIF(TRIM(tx.assistance_type_description), '')) AS assistance_type_description,
                COALESCE(NULLIF(TRIM(tx.appropriation_type), ''), NULLIF(TRIM(p.appropriation_type), ''), 'unknown') AS appropriation_type,
                COALESCE(
                    NULLIF(TRIM(p.funding_sub_agency_name), ''),
                    NULLIF(TRIM(p.awarding_sub_agency_name), ''),
                    NULLIF(TRIM(tx.funding_sub_agency_name), ''),
                    NULLIF(TRIM(tx.awarding_sub_agency_name), '')
                ) AS center_text,
                COALESCE(
                    NULLIF(TRIM(tx.cfda_title), ''),
                    NULLIF(TRIM(p.cfda_program_title), ''),
                    NULLIF(TRIM(p.cfda_numbers_and_titles), ''),
                    NULLIF(TRIM(tx.transaction_description), '')
                ) AS program_title,
                COALESCE(NULLIF(TRIM(tx.cfda_number), ''), NULLIF(TRIM(p.cfda_program_num), '')) AS aln_source,
                COALESCE(tx.federal_action_obligation, 0)::numeric AS amount,
                true AS chip_default_include,
                NULL::text AS contract_category_guess,
                NULL::text AS contract_award_type
            FROM {PRIME_TX_TABLE} AS tx
            LEFT JOIN {PRIME_TABLE} AS p
                ON p.unique_key = tx.assistance_award_unique_key

            UNION ALL

            SELECT
                COALESCE(NULLIF(TRIM(s.subaward_unique_key), ''), s.id::text) AS row_key,
                COALESCE(NULLIF(TRIM(s.subaward_unique_key), ''), NULLIF(TRIM(s.prime_award_fain), ''), s.id::text) AS award_key,
                'subaward'::text AS component,
                s.subaward_action_date_fiscal_year::integer AS fiscal_year,
                NULLIF(TRIM(s.subawardee_state_code), '') AS state_code,
                NULLIF(TRIM(s.subawardee_county_fips), '') AS county_fips,
                COALESCE(NULLIF(TRIM(s.subawardee_name), ''), 'Unknown recipient') AS recipient_name,
                NULLIF(TRIM(p.assistance_type_description), '') AS assistance_type_description,
                COALESCE(NULLIF(TRIM(s.appropriation_type), ''), NULLIF(TRIM(p.appropriation_type), ''), 'unknown') AS appropriation_type,
                COALESCE(
                    NULLIF(TRIM(s.prime_award_funding_sub_agency_name), ''),
                    NULLIF(TRIM(s.prime_award_awarding_sub_agency_name), ''),
                    NULLIF(TRIM(p.funding_sub_agency_name), ''),
                    NULLIF(TRIM(p.awarding_sub_agency_name), '')
                ) AS center_text,
                COALESCE(
                    NULLIF(TRIM(p.cfda_program_title), ''),
                    NULLIF(TRIM(s.prime_award_base_transaction_description), ''),
                    NULLIF(TRIM(s.subaward_description), '')
                ) AS program_title,
                NULLIF(TRIM(p.cfda_program_num), '') AS aln_source,
                COALESCE(s.subaward_amount, 0)::numeric AS amount,
                false AS chip_default_include,
                NULL::text AS contract_category_guess,
                NULL::text AS contract_award_type
            FROM {SUBAWARD_TABLE} AS s
            LEFT JOIN {PRIME_TABLE} AS p
                ON p.unique_key = s.prime_award_unique_key

            UNION ALL

            SELECT
                COALESCE(NULLIF(TRIM(e.contract_transaction_unique_key), ''), e.id::text) AS row_key,
                COALESCE(
                    NULLIF(TRIM(e.generated_unique_award_id), ''),
                    NULLIF(TRIM(e.contract_award_unique_key), ''),
                    NULLIF(TRIM(e.award_id_piid), ''),
                    e.id::text
                ) AS award_key,
                'contract'::text AS component,
                e.fiscal_year::integer AS fiscal_year,
                COALESCE(NULLIF(TRIM(e.recipient_state_code), ''), NULLIF(TRIM(e.normalized_recipient_state), '')) AS state_code,
                lookup.county_fips AS county_fips,
                COALESCE(NULLIF(TRIM(e.recipient_name), ''), 'Unknown recipient') AS recipient_name,
                NULL::text AS assistance_type_description,
                COALESCE(NULLIF(TRIM(e.appropriation_type), ''), 'unknown') AS appropriation_type,
                COALESCE(
                    NULLIF(TRIM(e.funding_sub_agency_name), ''),
                    NULLIF(TRIM(e.awarding_sub_agency_name), ''),
                    'CDC Contracts'
                ) AS center_text,
                COALESCE(
                    NULLIF(TRIM(e.award_description), ''),
                    NULLIF(TRIM(e.product_or_service_code_description), ''),
                    NULLIF(TRIM(e.naics_description), ''),
                    NULLIF(TRIM(e.transaction_description), '')
                ) AS program_title,
                NULL::text AS aln_source,
                COALESCE(e.transaction_obligated_amount, 0)::numeric AS amount,
                COALESCE(e.likely_profile_relevant, false) AS chip_default_include,
                NULLIF(TRIM(e.contract_category_guess), '') AS contract_category_guess,
                COALESCE(NULLIF(TRIM(e.contract_award_type), ''), NULLIF(TRIM(e.award_type), '')) AS contract_award_type
            FROM {CONTRACT_ENRICHED_VIEW} AS e
            LEFT JOIN contract_county_lookup AS lookup
                ON lookup.id = e.id
        ),
        integrated_rows AS (
            SELECT
                base.row_key,
                base.award_key,
                base.component,
                base.fiscal_year,
                base.state_code,
                base.county_fips,
                base.recipient_name,
                base.amount,
                base.appropriation_type,
                {mechanism_case} AS mechanism,
                {recipient_case} AS recipient_type,
                {award_program_area} AS program_area,
                COALESCE(
                    NULLIF(TRIM(aln_map.program_name), ''),
                    NULLIF(TRIM(base.program_title), ''),
                    NULLIF(TRIM(base.center_text), ''),
                    'Unspecified program'
                ) AS program_name,
                base.chip_default_include,
                (COALESCE(base.appropriation_type, 'unknown') IN ('covid_emergency', 'other_emergency')) AS is_emergency
            FROM base_rows AS base
            LEFT JOIN taggs_aln_mapping AS aln_map
                ON aln_map.aln_key = {_normalized_aln_expr('base.aln_source')}
        )
    """


def _filter_conditions(filters: FundingFilters, *, state: str | None = None) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = ["state_code IS NOT NULL"]
    params: dict[str, Any] = {"time_aggregation": filters.time_aggregation}

    if filters.fiscal_year is not None:
        clauses.append("fiscal_year = :fiscal_year")
        params["fiscal_year"] = filters.fiscal_year

    if filters.program_area is not None:
        clauses.append("program_area = :program_area")
        params["program_area"] = filters.program_area

    if filters.mechanism is not None:
        clauses.append("mechanism = :mechanism")
        params["mechanism"] = filters.mechanism

    if filters.recipient_type is not None:
        clauses.append("recipient_type = :recipient_type")
        params["recipient_type"] = filters.recipient_type

    if filters.funding_type == "total_cdc_funding":
        clauses.append("(component = 'award' OR (component = 'contract' AND chip_default_include = true))")
    elif filters.funding_type == "awards_only":
        clauses.append("component IN ('award', 'contract')")
    elif filters.funding_type == "subawards_only":
        clauses.append("component = 'subaward'")
    elif filters.funding_type == "awards_and_subawards":
        clauses.append("component IN ('award', 'subaward', 'contract')")
    elif filters.funding_type == "emergency_response":
        clauses.append("is_emergency = true")
    elif filters.funding_type == "non_emergency_program":
        clauses.append("is_emergency = false")

    if state is not None:
        params["state_code_filter"] = str(state).strip().upper()
        clauses.append("state_code = :state_code_filter")

    return "WHERE " + " AND ".join(clauses), params


def _summary_table_filter_conditions(
    filters: FundingFilters,
    *,
    alias: str = "s",
    state: str | None = None,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = [f"{alias}.state_code IS NOT NULL"]
    params: dict[str, Any] = {"time_aggregation": filters.time_aggregation}

    if filters.fiscal_year is not None:
        clauses.append(f"{alias}.fiscal_year = :fiscal_year")
        params["fiscal_year"] = filters.fiscal_year

    if filters.program_area is not None:
        clauses.append(f"{alias}.program_area = :program_area")
        params["program_area"] = filters.program_area

    if filters.mechanism is not None:
        clauses.append(f"{alias}.mechanism = :mechanism")
        params["mechanism"] = filters.mechanism

    if filters.recipient_type is not None:
        clauses.append(f"{alias}.recipient_type = :recipient_type")
        params["recipient_type"] = filters.recipient_type

    if filters.funding_type == "total_cdc_funding":
        clauses.append(
            f"({alias}.component = 'award' OR ({alias}.component = 'contract' AND {alias}.chip_default_include = true))"
        )
    elif filters.funding_type == "awards_only":
        clauses.append(f"{alias}.component IN ('award', 'contract')")
    elif filters.funding_type == "subawards_only":
        clauses.append(f"{alias}.component = 'subaward'")
    elif filters.funding_type == "awards_and_subawards":
        clauses.append(f"{alias}.component IN ('award', 'subaward', 'contract')")
    elif filters.funding_type == "emergency_response":
        clauses.append(f"{alias}.is_emergency = true")
    elif filters.funding_type == "non_emergency_program":
        clauses.append(f"{alias}.is_emergency = false")

    if state is not None:
        params["state_code_filter"] = str(state).strip().upper()
        clauses.append(f"{alias}.state_code = :state_code_filter")

    return "WHERE " + " AND ".join(clauses), params


def _state_summary_query(
    filters: FundingFilters,
    *,
    include_geometry: bool,
    bbox: str | None = None,
    limit: int = 200,
) -> tuple[str, dict[str, Any]]:
    where_sql, params = _summary_table_filter_conditions(filters, alias="s")
    params.update(
        {
            "limit": max(1, min(int(limit), 500)),
            "simplify_degrees": 0.04,
        }
    )
    bbox_args = _bbox_params(bbox)
    if bbox_args is not None:
        params.update(bbox_args)

    bbox_filter = ""
    if bbox_args is not None:
        bbox_filter = (
            "AND sb.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
            "AND ST_Intersects(sb.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
        )

    select_geometry = (
        "ST_AsGeoJSON(ST_SimplifyPreserveTopology(sb.geom, :simplify_degrees), 6)::json AS geometry,"
        if include_geometry
        else "NULL::json AS geometry,"
    )
    sql = f"""
        WITH filtered_rows AS (
            SELECT *
            FROM {INTELLIGENCE_STATE_CATEGORY_SUMMARY_TABLE} AS s
            {where_sql}
        ),
        year_stats AS (
            SELECT
                COUNT(DISTINCT fiscal_year)::numeric AS year_count,
                MIN(fiscal_year)::integer AS min_fiscal_year,
                MAX(fiscal_year)::integer AS max_fiscal_year
            FROM filtered_rows
        ),
        aggregated AS (
            SELECT
                s.state_code AS geography_id,
                MAX(s.state_name) AS geography_name,
                MAX(s.population)::numeric AS population,
                COALESCE(SUM(s.amount), 0)::numeric AS total_amount,
                COALESCE(SUM(s.amount) FILTER (WHERE s.component = 'award'), 0)::numeric AS awards_amount,
                COALESCE(SUM(s.amount) FILTER (WHERE s.component = 'subaward'), 0)::numeric AS subawards_amount,
                COALESCE(SUM(s.amount) FILTER (WHERE s.component = 'contract'), 0)::numeric AS contracts_amount,
                COALESCE(SUM(s.award_count), 0)::integer AS award_count,
                COALESCE(SUM(s.award_count) FILTER (WHERE s.component = 'subaward'), 0)::integer AS subaward_count,
                COALESCE(SUM(s.award_count) FILTER (WHERE s.component = 'contract'), 0)::integer AS contract_award_count
            FROM filtered_rows AS s
            GROUP BY s.state_code
        ),
        adjusted AS (
            SELECT
                aggregated.*,
                year_stats.year_count,
                year_stats.min_fiscal_year,
                year_stats.max_fiscal_year,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                        THEN aggregated.total_amount / year_stats.year_count
                    ELSE aggregated.total_amount
                END AS adjusted_amount,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                        THEN aggregated.awards_amount / year_stats.year_count
                    ELSE aggregated.awards_amount
                END AS adjusted_awards_amount,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                        THEN aggregated.subawards_amount / year_stats.year_count
                    ELSE aggregated.subawards_amount
                END AS adjusted_subawards_amount,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                        THEN aggregated.contracts_amount / year_stats.year_count
                    ELSE aggregated.contracts_amount
                END AS adjusted_contracts_amount
            FROM aggregated
            CROSS JOIN year_stats
        )
        SELECT
            sb.state_abbr AS geography_id,
            COALESCE(sb.state_name, sb.state_abbr) AS geography_name,
            sb.state_abbr AS state_code,
            COALESCE(sb.state_name, sb.state_abbr) AS state_name,
            adjusted.adjusted_amount AS raw_total_funding_amount,
            adjusted.adjusted_awards_amount AS awards_amount,
            adjusted.adjusted_subawards_amount AS subawards_amount,
            adjusted.adjusted_contracts_amount AS contracts_amount,
            COALESCE(adjusted.award_count, 0)::integer AS award_count,
            COALESCE(adjusted.subaward_count, 0)::integer AS subaward_count,
            COALESCE(adjusted.contract_award_count, 0)::integer AS contract_award_count,
            adjusted.population,
            adjusted.min_fiscal_year,
            adjusted.max_fiscal_year,
            {select_geometry}
            COALESCE(adjusted.total_amount, 0)::numeric AS raw_total_amount
        FROM {STATE_BOUNDARY_TABLE} AS sb
        LEFT JOIN adjusted
            ON adjusted.geography_id = sb.state_abbr
        WHERE sb.geom IS NOT NULL
          {bbox_filter}
        ORDER BY sb.state_abbr
        LIMIT :limit
    """
    return sql, params


def _build_national_summary_row_from_state_rows(
    db: Session,
    *,
    rows: list[dict[str, Any]],
    filters: FundingFilters,
) -> dict[str, Any]:
    min_fiscal_year = next(
        (
            int(row["min_fiscal_year"])
            for row in rows
            if row.get("min_fiscal_year") is not None
        ),
        None,
    )
    max_fiscal_year = next(
        (
            int(row["max_fiscal_year"])
            for row in rows
            if row.get("max_fiscal_year") is not None
        ),
        None,
    )
    population = sum(
        float(_json_number(row.get("population")) or 0.0)
        for row in rows
        if _json_number(row.get("population")) is not None
    ) or None
    raw_total = sum(
        float(_json_number(row.get("raw_total_funding")) or 0.0)
        for row in rows
        if _json_number(row.get("raw_total_funding")) is not None
    )
    normalized_values = [
        float(value)
        for value in (
            _json_number(row.get("chip_normalized_funding"))
            for row in rows
        )
        if value is not None and math.isfinite(float(value))
    ]
    normalized_total = sum(normalized_values) if normalized_values else None
    awards_amount = sum(float(_json_number(row.get("awards_amount")) or 0.0) for row in rows)
    subawards_amount = sum(float(_json_number(row.get("subawards_amount")) or 0.0) for row in rows)
    contracts_amount = sum(float(_json_number(row.get("contracts_amount")) or 0.0) for row in rows)
    award_count = sum(int(row.get("award_count") or 0) for row in rows)
    subaward_count = sum(int(row.get("subaward_count") or 0) for row in rows)
    contract_award_count = sum(int(row.get("contract_award_count") or 0) for row in rows)
    national_filters = FundingFilters(
        fiscal_year=filters.fiscal_year,
        metric=filters.metric,
        funding_type=filters.funding_type,
        funding_mode=filters.funding_mode,
        program_area=filters.program_area,
        mechanism=filters.mechanism,
        recipient_type=filters.recipient_type,
        geography_level="national",
        time_aggregation=filters.time_aggregation,
    )
    mode_context = CHIP_FUNDING_MODEL.build_mode_context(
        db,
        cache_context=_chip_cache_context(national_filters, scope="national_summary_from_state_summary"),
    )
    raw_result = CHIP_FUNDING_MODEL.calculate(
        total_funding=raw_total,
        population=population,
        fiscal_year=filters.fiscal_year,
        national_total_funding=raw_total,
    )
    normalized_result = CHIP_FUNDING_MODEL.calculate(
        total_funding=normalized_total,
        population=population,
        fiscal_year=filters.fiscal_year,
        national_total_funding=normalized_total,
    )
    effective_mode = (
        filters.funding_mode
        if is_normalized_funding_mode(filters.funding_mode) and normalized_total is not None
        else CDCFundingMode.RAW_TOTAL.value
    )
    selected_result = normalized_result if is_normalized_funding_mode(effective_mode) else raw_result
    payload = CHIP_FUNDING_MODEL._row_payload(
        raw_result=raw_result,
        normalized_result=normalized_result,
        selected_result=selected_result,
        row={},
        mode_context=mode_context,
        row_effective_mode=effective_mode,
        normalization_row=None,
        normalization_factor=None,
        geography_level="national",
    )
    return {
        "geography_id": "US",
        "geography_name": "United States",
        "state_code": "US",
        "state_name": "United States",
        "raw_total_funding_amount": raw_total,
        "awards_amount": awards_amount,
        "subawards_amount": subawards_amount,
        "contracts_amount": contracts_amount,
        "award_count": award_count,
        "subaward_count": subaward_count,
        "contract_award_count": contract_award_count,
        "population": population,
        "min_fiscal_year": min_fiscal_year,
        "max_fiscal_year": max_fiscal_year,
        "geometry": None,
        "raw_total_amount": raw_total,
        **payload,
    }


def _fetch_state_summary_rows(
    db: Session,
    filters: FundingFilters,
    *,
    include_geometry: bool,
    bbox: str | None = None,
    limit: int = 200,
    scope: str = "state_summary",
) -> list[dict[str, Any]]:
    def load_rows() -> list[dict[str, Any]]:
        sql, params = _state_summary_query(
            filters,
            include_geometry=include_geometry,
            bbox=bbox,
            limit=limit,
        )
        return [dict(row) for row in db.execute(text(sql), params).mappings().all()]

    rows = _read_cached_summary_payload(
        db,
        scope=scope,
        filters=filters,
        include_geometry=include_geometry,
        bbox=bbox,
        limit=limit,
        loader=load_rows,
    )
    mode_context = CHIP_FUNDING_MODEL.build_mode_context(
        db,
        cache_context=_chip_cache_context(
            filters,
            scope=scope,
            bbox=bbox,
            limit=limit,
        ),
    )
    return CHIP_FUNDING_MODEL.calculate_many(
        rows,
        cache_context=_chip_cache_context(
            filters,
            scope=scope,
            bbox=bbox,
            limit=limit,
        ),
        mode_context=mode_context,
    )


def _summary_query(
    filters: FundingFilters,
    *,
    include_geometry: bool,
    bbox: str | None = None,
    limit: int = 6000,
) -> tuple[str, dict[str, Any]]:
    base_cte = _integrated_rows_cte()
    where_sql, params = _filter_conditions(filters)
    params.update(
        {
            "limit": max(1, min(int(limit), 10000)),
            "simplify_degrees": 0.02 if filters.geography_level == "county" else 0.04,
        }
    )
    bbox_args = _bbox_params(bbox)
    if bbox_args is not None:
        params.update(bbox_args)

    bbox_filter = ""
    if filters.geography_level == "county" and bbox_args is not None:
        bbox_filter = (
            "AND b.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
            "AND ST_Intersects(b.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
        )
    elif filters.geography_level == "state" and bbox_args is not None:
        bbox_filter = (
            "AND sb.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
            "AND ST_Intersects(sb.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
        )

    if filters.geography_level == "county":
        select_geometry = (
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom, :simplify_degrees), 6)::json AS geometry,"
            if include_geometry
            else "NULL::json AS geometry,"
        )
        sql = f"""
            {base_cte},
            filtered_rows AS (
                SELECT * FROM integrated_rows
                {where_sql}
            ),
            year_stats AS (
                SELECT
                    COUNT(DISTINCT fiscal_year)::numeric AS year_count,
                    MIN(fiscal_year)::integer AS min_fiscal_year,
                    MAX(fiscal_year)::integer AS max_fiscal_year
                FROM filtered_rows
            ),
            aggregated AS (
                SELECT
                    county_fips AS geography_id,
                    MAX(state_code) AS state_code,
                    SUM(amount)::numeric AS total_amount,
                    COUNT(DISTINCT award_key)::integer AS award_count,
                    SUM(amount) FILTER (WHERE component = 'award')::numeric AS awards_amount,
                    SUM(amount) FILTER (WHERE component = 'subaward')::numeric AS subawards_amount,
                    SUM(amount) FILTER (WHERE component = 'contract')::numeric AS contracts_amount,
                    COUNT(DISTINCT award_key) FILTER (WHERE component = 'subaward')::integer AS subaward_count,
                    COUNT(DISTINCT award_key) FILTER (WHERE component = 'contract')::integer AS contract_award_count
                FROM filtered_rows
                WHERE county_fips ~ '^[0-9]{{5}}$'
                GROUP BY county_fips
            ),
            adjusted AS (
                SELECT
                    aggregated.*,
                    year_stats.year_count,
                    year_stats.min_fiscal_year,
                    year_stats.max_fiscal_year,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                            THEN aggregated.total_amount / year_stats.year_count
                        ELSE aggregated.total_amount
                    END AS adjusted_amount,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                            THEN aggregated.awards_amount / year_stats.year_count
                        ELSE aggregated.awards_amount
                    END AS adjusted_awards_amount,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                            THEN aggregated.subawards_amount / year_stats.year_count
                        ELSE aggregated.subawards_amount
                    END AS adjusted_subawards_amount,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                            THEN aggregated.contracts_amount / year_stats.year_count
                        ELSE aggregated.contracts_amount
                    END AS adjusted_contracts_amount
                FROM aggregated
                CROSS JOIN year_stats
            ),
            national_total AS (
                SELECT COALESCE(SUM(adjusted.adjusted_amount), 0)::numeric AS total_amount
                FROM adjusted
            )
            SELECT
                b.geoid AS geography_id,
                COALESCE(c.county_name, b.name) AS geography_name,
                c.state_abbr AS state_code,
                c.state_desc AS state_name,
                adjusted.adjusted_amount AS raw_total_funding_amount,
                adjusted.adjusted_awards_amount AS awards_amount,
                adjusted.adjusted_subawards_amount AS subawards_amount,
                adjusted.adjusted_contracts_amount AS contracts_amount,
                adjusted.award_count,
                adjusted.subaward_count,
                adjusted.contract_award_count,
                pop.population::numeric AS population,
                adjusted.min_fiscal_year,
                adjusted.max_fiscal_year,
                {select_geometry}
                COALESCE(adjusted.total_amount, 0)::numeric AS raw_total_amount
            FROM {COUNTY_BOUNDARY_TABLE} AS b
            LEFT JOIN {COUNTY_DIM_TABLE} AS c
                ON c.location_id = b.location_id
            LEFT JOIN adjusted
                ON adjusted.geography_id = b.geoid
            LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
                ON pop.geography_type = 'county'
               AND pop.geography_id = b.geoid
            CROSS JOIN national_total
            WHERE b.geom IS NOT NULL
              {bbox_filter}
            ORDER BY b.geoid
            LIMIT :limit
        """
        return sql, params

    if filters.geography_level == "state":
        select_geometry = (
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(sb.geom, :simplify_degrees), 6)::json AS geometry,"
            if include_geometry
            else "NULL::json AS geometry,"
        )
        sql = f"""
            {base_cte},
            filtered_rows AS (
                SELECT * FROM integrated_rows
                {where_sql}
            ),
            year_stats AS (
                SELECT
                    COUNT(DISTINCT fiscal_year)::numeric AS year_count,
                    MIN(fiscal_year)::integer AS min_fiscal_year,
                    MAX(fiscal_year)::integer AS max_fiscal_year
                FROM filtered_rows
            ),
            aggregated AS (
                SELECT
                    state_code AS geography_id,
                    SUM(amount)::numeric AS total_amount,
                    COUNT(DISTINCT award_key)::integer AS award_count,
                    SUM(amount) FILTER (WHERE component = 'award')::numeric AS awards_amount,
                    SUM(amount) FILTER (WHERE component = 'subaward')::numeric AS subawards_amount,
                    SUM(amount) FILTER (WHERE component = 'contract')::numeric AS contracts_amount,
                    COUNT(DISTINCT award_key) FILTER (WHERE component = 'subaward')::integer AS subaward_count,
                    COUNT(DISTINCT award_key) FILTER (WHERE component = 'contract')::integer AS contract_award_count
                FROM filtered_rows
                GROUP BY state_code
            ),
            adjusted AS (
                SELECT
                    aggregated.*,
                    year_stats.year_count,
                    year_stats.min_fiscal_year,
                    year_stats.max_fiscal_year,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                            THEN aggregated.total_amount / year_stats.year_count
                        ELSE aggregated.total_amount
                    END AS adjusted_amount,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                            THEN aggregated.awards_amount / year_stats.year_count
                        ELSE aggregated.awards_amount
                    END AS adjusted_awards_amount,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                            THEN aggregated.subawards_amount / year_stats.year_count
                        ELSE aggregated.subawards_amount
                    END AS adjusted_subawards_amount,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                            THEN aggregated.contracts_amount / year_stats.year_count
                        ELSE aggregated.contracts_amount
                    END AS adjusted_contracts_amount
                FROM aggregated
                CROSS JOIN year_stats
            ),
            national_total AS (
                SELECT COALESCE(SUM(adjusted.adjusted_amount), 0)::numeric AS total_amount
                FROM adjusted
            )
            SELECT
                sb.state_abbr AS geography_id,
                COALESCE(sb.state_name, sb.state_abbr) AS geography_name,
                sb.state_abbr AS state_code,
                COALESCE(sb.state_name, sb.state_abbr) AS state_name,
                adjusted.adjusted_amount AS raw_total_funding_amount,
                adjusted.adjusted_awards_amount AS awards_amount,
                adjusted.adjusted_subawards_amount AS subawards_amount,
                adjusted.adjusted_contracts_amount AS contracts_amount,
                adjusted.award_count,
                adjusted.subaward_count,
                adjusted.contract_award_count,
                pop.population::numeric AS population,
                adjusted.min_fiscal_year,
                adjusted.max_fiscal_year,
                {select_geometry}
                COALESCE(adjusted.total_amount, 0)::numeric AS raw_total_amount
            FROM {STATE_BOUNDARY_TABLE} AS sb
            LEFT JOIN adjusted
                ON adjusted.geography_id = sb.state_abbr
            LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
                ON pop.geography_type = 'state'
               AND UPPER(pop.state_abbr) = sb.state_abbr
            CROSS JOIN national_total
            WHERE sb.geom IS NOT NULL
              {bbox_filter}
            ORDER BY sb.state_abbr
            LIMIT :limit
        """
        return sql, params

    select_geometry = (
        "ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_UnaryUnion(ST_Collect(sb.geom)), :simplify_degrees), 6)::json AS geometry,"
        if include_geometry
        else "NULL::json AS geometry,"
    )
    sql = f"""
        {base_cte},
        filtered_rows AS (
            SELECT * FROM integrated_rows
            {where_sql}
        ),
        year_stats AS (
            SELECT
                COUNT(DISTINCT fiscal_year)::numeric AS year_count,
                MIN(fiscal_year)::integer AS min_fiscal_year,
                MAX(fiscal_year)::integer AS max_fiscal_year
            FROM filtered_rows
        ),
        aggregated AS (
            SELECT
                'US'::text AS geography_id,
                SUM(amount)::numeric AS total_amount,
                COUNT(DISTINCT award_key)::integer AS award_count,
                SUM(amount) FILTER (WHERE component = 'award')::numeric AS awards_amount,
                SUM(amount) FILTER (WHERE component = 'subaward')::numeric AS subawards_amount,
                SUM(amount) FILTER (WHERE component = 'contract')::numeric AS contracts_amount,
                COUNT(DISTINCT award_key) FILTER (WHERE component = 'subaward')::integer AS subaward_count,
                COUNT(DISTINCT award_key) FILTER (WHERE component = 'contract')::integer AS contract_award_count
            FROM filtered_rows
        ),
        adjusted AS (
            SELECT
                aggregated.*,
                year_stats.year_count,
                year_stats.min_fiscal_year,
                year_stats.max_fiscal_year,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                        THEN aggregated.total_amount / year_stats.year_count
                    ELSE aggregated.total_amount
                END AS adjusted_amount,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                        THEN aggregated.awards_amount / year_stats.year_count
                    ELSE aggregated.awards_amount
                END AS adjusted_awards_amount,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                        THEN aggregated.subawards_amount / year_stats.year_count
                    ELSE aggregated.subawards_amount
                END AS adjusted_subawards_amount,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                        THEN aggregated.contracts_amount / year_stats.year_count
                    ELSE aggregated.contracts_amount
                END AS adjusted_contracts_amount
            FROM aggregated
            CROSS JOIN year_stats
        )
        SELECT
            'US'::text AS geography_id,
            'United States'::text AS geography_name,
            'US'::text AS state_code,
            'United States'::text AS state_name,
            adjusted.adjusted_amount AS raw_total_funding_amount,
            adjusted.adjusted_awards_amount AS awards_amount,
            adjusted.adjusted_subawards_amount AS subawards_amount,
            adjusted.adjusted_contracts_amount AS contracts_amount,
            adjusted.award_count,
            adjusted.subaward_count,
            adjusted.contract_award_count,
            pop.population::numeric AS population,
            adjusted.min_fiscal_year,
            adjusted.max_fiscal_year,
            {select_geometry}
            COALESCE(adjusted.total_amount, 0)::numeric AS raw_total_amount
        FROM adjusted
        LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
            ON pop.geography_type = 'nation'
           AND pop.geography_id = 'US'
        CROSS JOIN {STATE_BOUNDARY_TABLE} AS sb
        WHERE sb.geom IS NOT NULL
        GROUP BY
            adjusted.adjusted_amount,
            adjusted.adjusted_awards_amount,
            adjusted.adjusted_subawards_amount,
            adjusted.adjusted_contracts_amount,
            adjusted.award_count,
            adjusted.subaward_count,
            adjusted.contract_award_count,
            adjusted.min_fiscal_year,
            adjusted.max_fiscal_year,
            adjusted.total_amount,
            pop.population
    """
    return sql, params


def _fetch_geography_rows(
    db: Session,
    filters: FundingFilters,
    *,
    include_geometry: bool,
    bbox: str | None = None,
    limit: int = 6000,
    scope: str = "map",
    state: str | None = None,
) -> list[dict[str, Any]]:
    support = v11_emergency.support_status(
        funding_mode=filters.funding_mode,
        funding_type=filters.funding_type,
        cdc_center=filters.program_area,
        program_area=filters.program_area,
        mechanism=filters.mechanism,
        recipient_type=filters.recipient_type,
    )
    if filters.geography_level == "state" and support.enabled:
        return v11_emergency.fetch_state_geography_rows(
            db,
            fiscal_year=filters.fiscal_year,
            funding_type=filters.funding_type,
            time_aggregation=filters.time_aggregation,
            include_geometry=include_geometry,
            bbox=bbox,
            limit=limit,
        )
    if _intelligence_summary_tables_available(db) and filters.geography_level == "state":
        return _fetch_state_summary_rows(
            db,
            filters,
            include_geometry=include_geometry,
            bbox=bbox,
            limit=limit,
            scope=scope,
        )
    if _intelligence_summary_tables_available(db) and filters.geography_level == "national":
        state_filters = FundingFilters(
            fiscal_year=filters.fiscal_year,
            metric=filters.metric,
            funding_type=filters.funding_type,
            funding_mode=filters.funding_mode,
            program_area=filters.program_area,
            mechanism=filters.mechanism,
            recipient_type=filters.recipient_type,
            geography_level="state",
            time_aggregation=filters.time_aggregation,
        )
        state_rows = _fetch_state_summary_rows(
            db,
            state_filters,
            include_geometry=False,
            bbox=None,
            limit=100,
            scope=f"{scope}_state_rollup",
        )
        return [_build_national_summary_row_from_state_rows(db, rows=state_rows, filters=filters)]

    sql, params = _summary_query(
        filters,
        include_geometry=include_geometry,
        bbox=bbox,
        limit=limit,
    )
    rows = [dict(row) for row in db.execute(text(sql), params).mappings().all()]
    mode_context = CHIP_FUNDING_MODEL.build_mode_context(
        db,
        cache_context=_chip_cache_context(
            filters,
            scope=scope,
            bbox=bbox,
            limit=limit,
            state=state,
        ),
    )
    transformed_rows = CHIP_FUNDING_MODEL.calculate_many(
        rows,
        cache_context=_chip_cache_context(
            filters,
            scope=scope,
            bbox=bbox,
            limit=limit,
            state=state,
        ),
        mode_context=mode_context,
    )
    return transformed_rows


def _fetch_national_summary_row(db: Session, filters: FundingFilters) -> dict[str, Any]:
    support = v11_emergency.support_status(
        funding_mode=filters.funding_mode,
        funding_type=filters.funding_type,
        cdc_center=filters.program_area,
        program_area=filters.program_area,
        mechanism=filters.mechanism,
        recipient_type=filters.recipient_type,
    )
    if support.enabled:
        return v11_emergency.fetch_national_summary_row(
            db,
            fiscal_year=filters.fiscal_year,
            funding_type=filters.funding_type,
            time_aggregation=filters.time_aggregation,
        )
    national_filters = FundingFilters(
        fiscal_year=filters.fiscal_year,
        metric=filters.metric,
        funding_type=filters.funding_type,
        funding_mode=filters.funding_mode,
        program_area=filters.program_area,
        mechanism=filters.mechanism,
        recipient_type=filters.recipient_type,
        geography_level="national",
        time_aggregation=filters.time_aggregation,
    )
    rows = _fetch_geography_rows(
        db,
        national_filters,
        include_geometry=False,
        bbox=None,
        limit=1,
        scope="national_summary",
    )
    return rows[0] if rows else {}


def _build_funding_profiles(
    db: Session,
    filters: FundingFilters,
    *,
    include_geometry: bool,
    bbox: str | None = None,
    limit: int = 6000,
    scope: str = "map",
) -> tuple[list[dict[str, Any]], list[FundingProfileResult]]:
    rows = _fetch_geography_rows(
        db,
        filters,
        include_geometry=include_geometry,
        bbox=bbox,
        limit=limit,
        scope=scope,
    )
    return rows, [_funding_profile_result_from_row(row, filters) for row in rows]


def _canonical_profile_for_state(
    db: Session,
    filters: FundingFilters,
    *,
    state_code: str,
) -> FundingProfileResult:
    state_filters = FundingFilters(
        fiscal_year=filters.fiscal_year,
        metric=filters.metric,
        funding_type=filters.funding_type,
        funding_mode=filters.funding_mode,
        program_area=filters.program_area,
        mechanism=filters.mechanism,
        recipient_type=filters.recipient_type,
        geography_level="state",
        time_aggregation=filters.time_aggregation,
    )
    rows, profiles = _build_funding_profiles(
        db,
        state_filters,
        include_geometry=False,
        bbox=None,
        limit=100,
        scope="profile_state_lookup",
    )
    del rows
    for profile in profiles:
        if str(profile.state_code or "").upper() == state_code:
            return profile
    raise HTTPException(status_code=404, detail=f"No CDC funding profile found for state {state_code}")


def _scaled_amount(value: Any, *, raw_total: float, target_total: float | None) -> float | None:
    amount = _json_number(value)
    if amount is None:
        return None
    if target_total is None or raw_total <= 0:
        return amount
    return _json_number((float(amount) / float(raw_total)) * float(target_total))


def _feature_properties(
    row: dict[str, Any],
    filters: FundingFilters,
    *,
    funding_profile: FundingProfileResult | None = None,
    include_profile: bool = True,
    lightweight: bool = False,
) -> dict[str, Any]:
    funding_profile = funding_profile or _funding_profile_result_from_row(row, filters)
    value = _profile_metric_value(funding_profile, filters.metric)
    properties = {
        "id": row.get("geography_id"),
        "location_id": row.get("geography_id"),
        "name": row.get("geography_name"),
        "state_abbr": row.get("state_code"),
        "state_name": row.get("state_name"),
        "geo_level": filters.geography_level,
        "value": value,
        "metric": filters.metric,
        "metric_label": METRIC_LABELS[filters.metric],
        "funding_type": filters.funding_type,
        "funding_type_label": FUNDING_TYPE_LABELS[filters.funding_type],
        "fiscal_year": filters.fiscal_year,
        "time_aggregation": filters.time_aggregation,
        "timeframe_label": funding_profile.timeframe_label,
        "funding_mode_requested": funding_profile.funding_mode_requested,
        "funding_mode_effective": funding_profile.funding_mode_effective,
        "funding_mode_label": funding_profile.funding_mode_label,
        "total_funding_amount": funding_profile.total_funding,
        "funding_per_capita": funding_profile.funding_per_capita,
        "funding_per_100k": funding_profile.funding_per_100k,
        "share_national_pct": funding_profile.national_share,
        "population": funding_profile.population,
        "metric_context": funding_profile.metadata["metric_context"],
        "methodology_version": funding_profile.methodology_version,
        "profile_version": funding_profile.profile_version,
        "funding_model_version": funding_profile.funding_model_version,
    }
    if include_profile:
        properties["funding_profile"] = _serialize_funding_profile_result(funding_profile)
    if lightweight:
        return properties
    properties.update(
        {
            "raw_total_funding": funding_profile.raw_total_funding,
            "raw_funding_per_capita": funding_profile.raw_funding_per_capita,
            "raw_funding_per_100k": funding_profile.raw_funding_per_100k,
            "raw_share_of_national": funding_profile.raw_share_of_national,
            "chip_normalized_funding": funding_profile.chip_normalized_funding,
            "chip_normalized_funding_per_capita": funding_profile.chip_normalized_funding_per_capita,
            "chip_normalized_funding_per_100k": funding_profile.chip_normalized_funding_per_100k,
            "chip_normalized_share_of_national": funding_profile.chip_normalized_share_of_national,
            "chip_total_funding": _json_number(row.get("chip_total_funding")),
            "chip_per_capita_funding": _json_number(row.get("chip_per_capita_funding")),
            "chip_per_100k_funding": _json_number(row.get("chip_per_100k_funding")),
            "chip_share_of_national": _json_number(row.get("chip_share_of_national")),
            "chip_equity_adjusted_metrics": row.get("chip_equity_adjusted_metrics") or {},
            "award_count": int(row.get("award_count") or 0),
            "subaward_count": int(row.get("subaward_count") or 0),
            "contract_award_count": int(row.get("contract_award_count") or 0),
            "awards_amount": _json_number(row.get("awards_amount")),
            "subawards_amount": _json_number(row.get("subawards_amount")),
            "contracts_amount": _json_number(row.get("contracts_amount")),
            "normalization_supported": funding_profile.normalization_supported,
            "normalization_applied": funding_profile.normalization_applied,
            "normalization_note": funding_profile.normalization_note,
            "normalization_factor": funding_profile.normalization_factor,
            "normalized_amount_type": funding_profile.normalized_amount_type,
            "normalization_status_label": funding_profile.normalization_status_label,
            "normalization_method": funding_profile.normalization_method,
            "funding_stream_logic_version": funding_profile.funding_stream_logic_version,
        }
    )
    return properties


def _mapping_coverage(db: Session) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            WITH taggs_aln AS (
                SELECT DISTINCT {_normalized_aln_expr('aln')} AS aln_key
                FROM {TAGGS_AWARD_SUMMARY_TABLE}
                WHERE NULLIF(TRIM(aln), '') IS NOT NULL
            )
            SELECT
                COUNT(*)::integer AS cdc_row_count,
                COUNT(*) FILTER (
                    WHERE taggs_aln.aln_key IS NOT NULL
                )::integer AS aln_matched_row_count
            FROM {PRIME_TX_TABLE} AS tx
            LEFT JOIN taggs_aln
                ON taggs_aln.aln_key = {_normalized_aln_expr('tx.cfda_number')}
            """
        )
    ).mappings().one()
    cdc_row_count = int(row.get("cdc_row_count") or 0)
    matched_row_count = int(row.get("aln_matched_row_count") or 0)
    matched_share = (matched_row_count / cdc_row_count) * 100 if cdc_row_count else 0
    return {
        "cdc_rows": cdc_row_count,
        "aln_matched_rows": matched_row_count,
        "aln_match_share_pct": round(matched_share, 2),
        "join_precedence": [
            "TAGGS effective_category and effective_program_name by normalized ALN/CFDA number",
            "CDC center and USAspending program-title fallback when ALN enrichment is missing",
            "Contract category fallback for USAspending contract rows without ALN coverage",
        ],
    }


def list_filter_options(db: Session) -> dict[str, Any]:
    _ensure_required_tables(db)

    fiscal_years = canonical.available_fiscal_years(db, geography_level="state")
    default_canonical_fiscal_year = canonical.default_fiscal_year(db, geography_level="state")
    mapping_coverage = _mapping_coverage(db)
    funding_mode_options = list_funding_mode_options(db)
    if not any(option.get("value") == canonical.FUNDING_MODEL_KEY for option in funding_mode_options):
        funding_mode_options = [canonical.mode_option(), *funding_mode_options]
    if not any(option.get("value") == budget_grounded.FUNDING_MODEL_KEY for option in funding_mode_options):
        funding_mode_options = funding_mode_options + [budget_grounded.mode_option()]
    canonical_years_by_geography = canonical.available_fiscal_years_by_geography(db)
    canonical_defaults = canonical.filter_defaults() | {
        "available_fiscal_years": fiscal_years,
        "default_fiscal_year": default_canonical_fiscal_year,
        "available_fiscal_years_by_geography": canonical_years_by_geography,
    }
    budget_grounded_years = budget_grounded.available_scope_fiscal_years(db)
    budget_grounded_defaults = budget_grounded.filter_defaults() | {
        "available_fiscal_years": budget_grounded_years,
        "default_fiscal_year": budget_grounded_years[0] if budget_grounded_years else None,
    }
    default_funding_mode = canonical.FUNDING_MODEL_KEY if fiscal_years else DEFAULT_FUNDING_MODE

    return {
        "methodology": {
            "id": "chip_funding_model",
            "label": "CHIP Funding Model",
            "default": True,
            "funding_mode_controlled": True,
        },
        "fiscal_year_options": [{"value": "all", "label": "All Years"}]
        + [
            {"value": str(year), "label": f"FY{year}"}
            for year in fiscal_years
        ],
        "default_fiscal_year": default_canonical_fiscal_year,
        "metric_options": METRIC_OPTIONS,
        "funding_type_options": FUNDING_TYPE_OPTIONS,
        "funding_mode_options": funding_mode_options,
        "default_funding_mode": default_funding_mode,
        "canonical_filter_defaults": canonical_defaults,
        "canonical_review_mode_options": canonical.review_mode_options(),
        "budget_grounded_scope_filter_defaults": budget_grounded_defaults,
        "budget_grounded_review_mode_options": budget_grounded.review_mode_options(),
        "cdc_center_options": PROGRAM_AREA_OPTIONS,
        "mechanism_options": MECHANISM_OPTIONS,
        "recipient_type_options": RECIPIENT_TYPE_OPTIONS,
        "geography_level_options": GEOGRAPHY_LEVEL_OPTIONS,
        "time_aggregation_options": TIME_AGGREGATION_OPTIONS,
        "source_blend": {
            "primary_source": "USAspending",
            "primary_role": "Transactional funding backbone for awards, subawards, and contracts",
            "complementary_source": "TAGGS",
            "complementary_role": "CDC/HHS program-area enrichment and ALN-linked classification context",
            "enrichment_strategy": mapping_coverage,
        },
        "notes": [
            DEFAULT_NOTE,
            "Canonical CDC Funding is now the default map/profile backbone and unifies budget-grounded rows with provisional profile-scope normalized rows in one downstream schema.",
            "Budget-Grounded Funding v1 remains available as a temporary debug mode alongside raw total funding, CHIP Normalized Funding v1.1, and CHIP Normalized Funding (Legacy).",
            "CHIP Normalized Funding v1.1 rescales the current map distribution to the newest v1.1 emergency-classification state-profile benchmark. The legacy normalized mode remains available for comparison.",
            "Published custom funding modes appear here after they are locked, built, and activated in the funding mode registry.",
            "Emergency vs non-emergency splits come from centralized appropriation-type classification.",
        ],
    }


def fetch_map_geojson(
    db: Session,
    *,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    funding_mode: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    geography_level: str | None = None,
    time_aggregation: str | None = None,
    bbox: str | None = None,
    limit: int = 6000,
) -> dict[str, Any]:
    _ensure_required_tables(db)
    filters = _normalize_filters(
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        funding_mode=funding_mode,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        geography_level=geography_level,
        time_aggregation=time_aggregation,
    )
    rows, profiles = _build_funding_profiles(
        db,
        filters,
        include_geometry=True,
        bbox=bbox,
        limit=limit,
        scope="map",
    )
    use_lightweight_state_features = filters.geography_level == "state"
    features: list[dict[str, Any]] = []
    metric_values: list[float] = []
    for row, profile in zip(rows, profiles, strict=False):
        properties = _feature_properties(
            row,
            filters,
            funding_profile=profile,
            include_profile=not use_lightweight_state_features,
            lightweight=use_lightweight_state_features,
        )
        value = _profile_metric_value(profile, filters.metric)
        if value is not None and math.isfinite(float(value)):
            metric_values.append(float(value))
        features.append(
            {
                "type": "Feature",
                "geometry": row.get("geometry"),
                "properties": properties,
            }
        )

    min_fiscal_year = next(
        (
            int(row["min_fiscal_year"])
            for row in rows
            if row.get("min_fiscal_year") is not None
        ),
        None,
    )
    max_fiscal_year = next(
        (
            int(row["max_fiscal_year"])
            for row in rows
            if row.get("max_fiscal_year") is not None
        ),
        None,
    )
    national_summary = _fetch_national_summary_row(db, filters)
    national_profile = _serialize_funding_profile_result(_funding_profile_result_from_row(national_summary, FundingFilters(
        fiscal_year=filters.fiscal_year,
        metric=filters.metric,
        funding_type=filters.funding_type,
        funding_mode=filters.funding_mode,
        program_area=filters.program_area,
        mechanism=filters.mechanism,
        recipient_type=filters.recipient_type,
        geography_level="national",
        time_aggregation=filters.time_aggregation,
    )))

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "note": " ".join(
                part
                for part in [
                    national_profile.get("normalization_note"),
                    _active_filter_note(filters),
                ]
                if part
            ),
            "legend_title": build_legend_title(
                metric=filters.metric,
                fiscal_year=filters.fiscal_year,
                min_fiscal_year=min_fiscal_year,
                max_fiscal_year=max_fiscal_year,
                time_aggregation=filters.time_aggregation,
            ),
            "filter_context": _filter_context_payload(
                filters,
                min_fiscal_year=min_fiscal_year,
                max_fiscal_year=max_fiscal_year,
            ),
            "funding_mode_requested": filters.funding_mode,
            "funding_mode_requested_label": FUNDING_MODE_LABELS[filters.funding_mode],
            "funding_mode_effective": national_profile.get("funding_mode_effective"),
            "funding_mode_label": national_profile.get("funding_mode_label"),
            "national_summary": {
                "funding_profile": national_profile,
                "funding_mode_requested": national_profile.get("funding_mode_requested"),
                "funding_mode_effective": national_profile.get("funding_mode_effective"),
                "funding_mode_label": national_profile.get("funding_mode_label"),
                "raw_total_funding": _json_number(national_summary.get("raw_total_funding")),
                "chip_normalized_funding": _json_number(national_summary.get("chip_normalized_funding")),
                "chip_total_funding": _json_number(national_summary.get("chip_total_funding")),
                "chip_per_capita_funding": _json_number(national_summary.get("chip_per_capita_funding")),
                "chip_per_100k_funding": _json_number(national_summary.get("chip_per_100k_funding")),
                "chip_share_of_national": _json_number(national_summary.get("chip_share_of_national")),
                "total_funding_amount": _json_number(national_summary.get("total_funding_amount")),
                "funding_per_capita": _json_number(national_summary.get("funding_per_capita")),
                "funding_per_100k": _json_number(national_summary.get("funding_per_100k")),
                "share_national_pct": _json_number(national_summary.get("share_national_pct")),
                "population": _json_number(national_summary.get("population")),
            },
        },
    }


def fetch_legend_stats(
    db: Session,
    *,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    funding_mode: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    geography_level: str | None = None,
    time_aggregation: str | None = None,
    bbox: str | None = None,
) -> dict[str, Any]:
    _ensure_required_tables(db)
    filters = _normalize_filters(
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        funding_mode=funding_mode,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        geography_level=geography_level,
        time_aggregation=time_aggregation,
    )
    rows, profiles = _build_funding_profiles(
        db,
        filters,
        include_geometry=False,
        bbox=bbox,
        limit=7000,
        scope="legend",
    )
    metric_values: list[float] = []
    mapped_geographies = 0
    total_visible_dollars = 0.0
    for row, profile in zip(rows, profiles, strict=False):
        total_funding = profile.total_funding
        if total_funding is not None:
            total_visible_dollars += float(total_funding)
        value = _profile_metric_value(profile, filters.metric)
        if value is None:
            continue
        mapped_geographies += 1
        metric_values.append(float(value))

    min_fiscal_year = next(
        (
            int(row["min_fiscal_year"])
            for row in rows
            if row.get("min_fiscal_year") is not None
        ),
        None,
    )
    max_fiscal_year = next(
        (
            int(row["max_fiscal_year"])
            for row in rows
            if row.get("max_fiscal_year") is not None
        ),
        None,
    )
    national_summary = _fetch_national_summary_row(db, filters)
    national_profile = _serialize_funding_profile_result(_funding_profile_result_from_row(national_summary, FundingFilters(
        fiscal_year=filters.fiscal_year,
        metric=filters.metric,
        funding_type=filters.funding_type,
        funding_mode=filters.funding_mode,
        program_area=filters.program_area,
        mechanism=filters.mechanism,
        recipient_type=filters.recipient_type,
        geography_level="national",
        time_aggregation=filters.time_aggregation,
    )))
    return {
        "metric": filters.metric,
        "metric_label": METRIC_LABELS[filters.metric],
        "funding_type": filters.funding_type,
        "funding_type_label": FUNDING_TYPE_LABELS[filters.funding_type],
        "funding_mode_requested": filters.funding_mode,
        "funding_mode_requested_label": FUNDING_MODE_LABELS[filters.funding_mode],
        "funding_mode_effective": national_profile.get("funding_mode_effective"),
        "funding_mode_label": national_profile.get("funding_mode_label"),
        "geography_level": filters.geography_level,
        "time_aggregation": filters.time_aggregation,
        "min": min(metric_values) if metric_values else None,
        "max": max(metric_values) if metric_values else None,
        "bins": _compute_bins(metric_values),
        "mapped_geographies": mapped_geographies,
        "n": mapped_geographies,
        "noDataCount": max(len(rows) - mapped_geographies, 0),
        "total_visible_dollars": total_visible_dollars if filters.metric != "share_national" else None,
        "legend_title": build_legend_title(
            metric=filters.metric,
            fiscal_year=filters.fiscal_year,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
            time_aggregation=filters.time_aggregation,
        ),
        "filter_context": _filter_context_payload(
            filters,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
        ),
        "note": " ".join(part for part in [national_profile.get("normalization_note"), _active_filter_note(filters)] if part),
        "national_summary": {
            "funding_profile": national_profile,
            "funding_mode_requested": national_profile.get("funding_mode_requested"),
            "funding_mode_effective": national_profile.get("funding_mode_effective"),
            "funding_mode_label": national_profile.get("funding_mode_label"),
            "raw_total_funding": _json_number(national_summary.get("raw_total_funding")),
            "chip_normalized_funding": _json_number(national_summary.get("chip_normalized_funding")),
            "chip_total_funding": _json_number(national_summary.get("chip_total_funding")),
            "chip_per_capita_funding": _json_number(national_summary.get("chip_per_capita_funding")),
            "chip_per_100k_funding": _json_number(national_summary.get("chip_per_100k_funding")),
            "chip_share_of_national": _json_number(national_summary.get("chip_share_of_national")),
            "total_funding_amount": _json_number(national_summary.get("total_funding_amount")),
            "funding_per_capita": _json_number(national_summary.get("funding_per_capita")),
            "funding_per_100k": _json_number(national_summary.get("funding_per_100k")),
            "share_national_pct": _json_number(national_summary.get("share_national_pct")),
            "population": _json_number(national_summary.get("population")),
        },
    }


def fetch_national_summary(
    db: Session,
    *,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    funding_mode: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    time_aggregation: str | None = None,
) -> dict[str, Any]:
    _ensure_required_tables(db)
    filters = _normalize_filters(
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        funding_mode=funding_mode,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        geography_level="national",
        time_aggregation=time_aggregation,
    )
    row = _fetch_national_summary_row(db, filters)
    profile = _funding_profile_result_from_row(row, filters)
    min_fiscal_year = int(row["min_fiscal_year"]) if row.get("min_fiscal_year") is not None else None
    max_fiscal_year = int(row["max_fiscal_year"]) if row.get("max_fiscal_year") is not None else None
    return {
        "profile": _serialize_funding_profile_result(profile),
        "summary": {
            "funding_mode_requested": profile.funding_mode_requested,
            "funding_mode_effective": profile.funding_mode_effective,
            "funding_mode_label": profile.funding_mode_label,
            "raw_total_funding": _json_number(row.get("raw_total_funding")),
            "chip_normalized_funding": _json_number(row.get("chip_normalized_funding")),
            "chip_total_funding": _json_number(row.get("chip_total_funding")),
            "chip_per_capita_funding": _json_number(row.get("chip_per_capita_funding")),
            "chip_per_100k_funding": _json_number(row.get("chip_per_100k_funding")),
            "chip_share_of_national": _json_number(row.get("chip_share_of_national")),
            "total_funding_amount": _json_number(row.get("total_funding_amount")),
            "funding_per_capita": _json_number(row.get("funding_per_capita")),
            "funding_per_100k": _json_number(row.get("funding_per_100k")),
            "share_national_pct": _json_number(row.get("share_national_pct")),
            "population": _json_number(row.get("population")),
            "award_count": int(row.get("award_count") or 0),
            "subaward_count": int(row.get("subaward_count") or 0),
            "contract_award_count": int(row.get("contract_award_count") or 0),
            "awards_amount": _json_number(row.get("awards_amount")),
            "subawards_amount": _json_number(row.get("subawards_amount")),
            "contracts_amount": _json_number(row.get("contracts_amount")),
        },
        "legend_title": build_legend_title(
            metric=filters.metric,
            fiscal_year=filters.fiscal_year,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
            time_aggregation=filters.time_aggregation,
        ),
        "filter_context": _filter_context_payload(
            filters,
            min_fiscal_year=min_fiscal_year,
            max_fiscal_year=max_fiscal_year,
        ),
        "note": " ".join(part for part in [profile.normalization_note, _active_filter_note(filters)] if part),
    }


def _profile_state_rows(
    db: Session,
    filters: FundingFilters,
    *,
    state: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if _intelligence_summary_tables_available(db):
        where_all_sql, params = _summary_table_filter_conditions(filters, alias="s")
        where_state_sql, state_params = _summary_table_filter_conditions(filters, alias="s", state=state)
        params = dict(params)
        state_params = dict(state_params)
        sql = f"""
            WITH filtered_all_rows AS (
                SELECT * FROM {INTELLIGENCE_STATE_SUBCATEGORY_SUMMARY_TABLE} AS s
                {where_all_sql}
            ),
            filtered_state_rows AS (
                SELECT * FROM {INTELLIGENCE_STATE_SUBCATEGORY_SUMMARY_TABLE} AS s
                {where_state_sql}
            ),
            year_stats AS (
                SELECT
                    COUNT(DISTINCT fiscal_year)::numeric AS year_count,
                    MIN(fiscal_year)::integer AS min_fiscal_year,
                    MAX(fiscal_year)::integer AS max_fiscal_year
                FROM filtered_all_rows
            ),
            national_total AS (
                SELECT
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                            THEN COALESCE(SUM(filtered_all_rows.amount), 0)::numeric / MAX(year_stats.year_count)
                        ELSE COALESCE(SUM(filtered_all_rows.amount), 0)::numeric
                    END AS total_amount
                FROM filtered_all_rows
                CROSS JOIN year_stats
            ),
            state_total AS (
                SELECT
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                            THEN COALESCE(SUM(filtered_state_rows.amount), 0)::numeric / MAX(year_stats.year_count)
                        ELSE COALESCE(SUM(filtered_state_rows.amount), 0)::numeric
                    END AS total_amount,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                            THEN COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'award'), 0)::numeric / MAX(year_stats.year_count)
                        ELSE COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'award'), 0)::numeric
                    END AS awards_amount_raw,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                            THEN COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'subaward'), 0)::numeric / MAX(year_stats.year_count)
                        ELSE COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'subaward'), 0)::numeric
                    END AS subawards_amount_raw,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                            THEN COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'contract'), 0)::numeric / MAX(year_stats.year_count)
                        ELSE COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'contract'), 0)::numeric
                    END AS contracts_amount_raw,
                    COALESCE(SUM(filtered_state_rows.award_count), 0)::integer AS award_count,
                    COALESCE(SUM(filtered_state_rows.award_count) FILTER (WHERE filtered_state_rows.component = 'subaward'), 0)::integer AS subaward_count,
                    COALESCE(SUM(filtered_state_rows.award_count) FILTER (WHERE filtered_state_rows.component = 'contract'), 0)::integer AS contract_award_count
                FROM filtered_state_rows
                CROSS JOIN year_stats
            ),
            area_rows AS (
                SELECT
                    filtered_state_rows.program_area,
                    filtered_state_rows.program_name,
                    COALESCE(SUM(filtered_state_rows.award_count), 0)::integer AS award_count,
                    CASE
                        WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                            THEN COALESCE(SUM(filtered_state_rows.amount), 0)::numeric / year_stats.year_count
                        ELSE COALESCE(SUM(filtered_state_rows.amount), 0)::numeric
                    END AS amount
                FROM filtered_state_rows
                CROSS JOIN year_stats
                GROUP BY filtered_state_rows.program_area, filtered_state_rows.program_name, year_stats.year_count
            )
            SELECT
                area_rows.program_area,
                area_rows.program_name,
                area_rows.amount,
                area_rows.award_count,
                state_total.total_amount AS state_total_amount,
                state_total.awards_amount_raw,
                state_total.subawards_amount_raw,
                state_total.contracts_amount_raw,
                state_total.award_count AS state_award_count,
                state_total.subaward_count AS state_subaward_count,
                state_total.contract_award_count,
                national_total.total_amount AS national_total_amount,
                year_stats.min_fiscal_year,
                year_stats.max_fiscal_year
            FROM area_rows
            CROSS JOIN state_total
            CROSS JOIN national_total
            CROSS JOIN year_stats
            ORDER BY area_rows.amount DESC NULLS LAST, area_rows.program_area ASC, area_rows.program_name ASC
        """
        rows = [dict(row) for row in db.execute(text(sql), state_params | params).mappings().all()]
        summary = rows[0] if rows else {}
        metadata = {
            "min_fiscal_year": int(summary["min_fiscal_year"]) if summary.get("min_fiscal_year") is not None else None,
            "max_fiscal_year": int(summary["max_fiscal_year"]) if summary.get("max_fiscal_year") is not None else None,
        }
        totals = {
            "state_total_amount": _json_number(summary.get("state_total_amount")) or 0.0,
            "awards_amount": _json_number(summary.get("awards_amount_raw")) or 0.0,
            "subawards_amount": _json_number(summary.get("subawards_amount_raw")) or 0.0,
            "contracts_amount": _json_number(summary.get("contracts_amount_raw")) or 0.0,
            "award_count": int(summary.get("state_award_count") or 0),
            "subaward_count": int(summary.get("state_subaward_count") or 0),
            "contract_award_count": int(summary.get("contract_award_count") or 0),
            "national_total_amount": _json_number(summary.get("national_total_amount")) or 0.0,
        }
        return rows, totals, metadata

    base_cte = _integrated_rows_cte()
    where_all_sql, params = _filter_conditions(filters)
    where_state_sql, state_params = _filter_conditions(filters, state=state)
    params = dict(params)
    state_params = dict(state_params)
    sql = f"""
        {base_cte},
        filtered_all_rows AS (
            SELECT * FROM integrated_rows
            {where_all_sql}
        ),
        filtered_state_rows AS (
            SELECT * FROM integrated_rows
            {where_state_sql}
        ),
        year_stats AS (
            SELECT
                COUNT(DISTINCT fiscal_year)::numeric AS year_count,
                MIN(fiscal_year)::integer AS min_fiscal_year,
                MAX(fiscal_year)::integer AS max_fiscal_year
            FROM filtered_all_rows
        ),
        national_total AS (
            SELECT
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                        THEN COALESCE(SUM(filtered_all_rows.amount), 0)::numeric / MAX(year_stats.year_count)
                    ELSE COALESCE(SUM(filtered_all_rows.amount), 0)::numeric
                END AS total_amount
            FROM filtered_all_rows
            CROSS JOIN year_stats
        ),
        state_total AS (
            SELECT
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                        THEN COALESCE(SUM(filtered_state_rows.amount), 0)::numeric / MAX(year_stats.year_count)
                    ELSE COALESCE(SUM(filtered_state_rows.amount), 0)::numeric
                END AS total_amount,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                        THEN COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'award'), 0)::numeric / MAX(year_stats.year_count)
                    ELSE COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'award'), 0)::numeric
                END AS awards_amount_raw,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                        THEN COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'subaward'), 0)::numeric / MAX(year_stats.year_count)
                    ELSE COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'subaward'), 0)::numeric
                END AS subawards_amount_raw,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(MAX(year_stats.year_count), 0) > 0
                        THEN COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'contract'), 0)::numeric / MAX(year_stats.year_count)
                    ELSE COALESCE(SUM(filtered_state_rows.amount) FILTER (WHERE filtered_state_rows.component = 'contract'), 0)::numeric
                END AS contracts_amount_raw,
                COUNT(DISTINCT filtered_state_rows.award_key)::integer AS award_count,
                COUNT(DISTINCT filtered_state_rows.award_key) FILTER (WHERE filtered_state_rows.component = 'subaward')::integer AS subaward_count,
                COUNT(DISTINCT filtered_state_rows.award_key) FILTER (WHERE filtered_state_rows.component = 'contract')::integer AS contract_award_count
            FROM filtered_state_rows
            CROSS JOIN year_stats
        ),
        area_rows AS (
            SELECT
                filtered_state_rows.program_area,
                filtered_state_rows.program_name,
                COUNT(DISTINCT filtered_state_rows.award_key)::integer AS award_count,
                CASE
                    WHEN :time_aggregation = 'multi_year_average' AND COALESCE(year_stats.year_count, 0) > 0
                        THEN COALESCE(SUM(filtered_state_rows.amount), 0)::numeric / year_stats.year_count
                    ELSE COALESCE(SUM(filtered_state_rows.amount), 0)::numeric
                END AS amount
            FROM filtered_state_rows
            CROSS JOIN year_stats
            GROUP BY filtered_state_rows.program_area, filtered_state_rows.program_name, year_stats.year_count
        )
        SELECT
            area_rows.program_area,
            area_rows.program_name,
            area_rows.amount,
            area_rows.award_count,
            state_total.total_amount AS state_total_amount,
            state_total.awards_amount_raw,
            state_total.subawards_amount_raw,
            state_total.contracts_amount_raw,
            state_total.award_count AS state_award_count,
            state_total.subaward_count AS state_subaward_count,
            state_total.contract_award_count,
            national_total.total_amount AS national_total_amount,
            year_stats.min_fiscal_year,
            year_stats.max_fiscal_year
        FROM area_rows
        CROSS JOIN state_total
        CROSS JOIN national_total
        CROSS JOIN year_stats
        ORDER BY area_rows.amount DESC NULLS LAST, area_rows.program_area ASC, area_rows.program_name ASC
    """
    rows = [dict(row) for row in db.execute(text(sql), state_params | params).mappings().all()]
    summary = rows[0] if rows else {}
    metadata = {
        "min_fiscal_year": int(summary["min_fiscal_year"]) if summary.get("min_fiscal_year") is not None else None,
        "max_fiscal_year": int(summary["max_fiscal_year"]) if summary.get("max_fiscal_year") is not None else None,
    }
    totals = {
        "state_total_amount": _json_number(summary.get("state_total_amount")) or 0.0,
        "awards_amount": _json_number(summary.get("awards_amount_raw")) or 0.0,
        "subawards_amount": _json_number(summary.get("subawards_amount_raw")) or 0.0,
        "contracts_amount": _json_number(summary.get("contracts_amount_raw")) or 0.0,
        "award_count": int(summary.get("state_award_count") or 0),
        "subaward_count": int(summary.get("state_subaward_count") or 0),
        "contract_award_count": int(summary.get("contract_award_count") or 0),
        "national_total_amount": _json_number(summary.get("national_total_amount")) or 0.0,
    }
    return rows, totals, metadata


def _state_name(db: Session, state_code: str) -> str:
    row = db.execute(
        text(
            f"""
            SELECT COALESCE(state_name, state_abbr) AS state_name
            FROM {STATE_BOUNDARY_TABLE}
            WHERE state_abbr = :state_code
            LIMIT 1
            """
        ),
        {"state_code": state_code},
    ).mappings().one_or_none()
    return str(row["state_name"]) if row and row.get("state_name") else state_code


def _state_population(db: Session, state_code: str) -> float | None:
    row = db.execute(
        text(
            f"""
            SELECT population
            FROM {POPULATION_VIEW_TABLE}
            WHERE geography_type = 'state'
              AND UPPER(state_abbr) = :state_code
            LIMIT 1
            """
        ),
        {"state_code": state_code},
    ).mappings().one_or_none()
    if not row:
        return None
    return _json_number(row.get("population"))


def _chip_share_value(
    value: Any,
    *,
    national_total_funding: Any,
    fiscal_year: int | None,
) -> float | None:
    return _json_number(
        CHIP_FUNDING_MODEL.calculate(
            total_funding=value,
            national_total_funding=national_total_funding,
            fiscal_year=fiscal_year,
        ).share_of_national
    )


def _build_state_profile_summary_payload(
    db: Session,
    *,
    state_code: str,
    filters: FundingFilters,
    canonical_profile: FundingProfileResult,
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    totals: dict[str, Any],
) -> dict[str, Any]:
    top_area = rows[0] if rows else None
    raw_state_total = float(totals["state_total_amount"] or 0.0)
    scaled_top_area_amount = (
        _scaled_amount(
            top_area.get("amount"),
            raw_total=raw_state_total,
            target_total=canonical_profile.total_funding,
        )
        if top_area
        else None
    )
    return {
        "state_code": state_code,
        "state_name": _state_name(db, state_code),
        "fiscal_year": filters.fiscal_year,
        "time_aggregation": filters.time_aggregation,
        "timeframe_label": _timeframe_label(
            fiscal_year=filters.fiscal_year,
            min_fiscal_year=metadata["min_fiscal_year"],
            max_fiscal_year=metadata["max_fiscal_year"],
            time_aggregation=filters.time_aggregation,
        ),
        "funding_mode_requested": canonical_profile.funding_mode_requested,
        "funding_mode_effective": canonical_profile.funding_mode_effective,
        "funding_mode_label": canonical_profile.funding_mode_label,
        "selected_metric": filters.metric,
        "selected_metric_label": METRIC_LABELS[filters.metric],
        "selected_metric_value": _profile_metric_value(canonical_profile, filters.metric),
        "profile": _serialize_funding_profile_result(canonical_profile),
        "raw_total_funding": canonical_profile.raw_total_funding,
        "chip_normalized_funding": canonical_profile.chip_normalized_funding,
        "chip_total_funding": canonical_profile.chip_normalized_funding,
        "chip_per_capita_funding": canonical_profile.chip_normalized_funding_per_capita,
        "chip_per_100k_funding": canonical_profile.chip_normalized_funding_per_100k,
        "chip_share_of_national": canonical_profile.chip_normalized_share_of_national,
        "chip_equity_adjusted_metrics": canonical_profile.metadata.get("chip_equity_adjusted_metrics") or {},
        "total_funding": canonical_profile.total_funding,
        "funding_per_capita": canonical_profile.funding_per_capita,
        "funding_per_100k": canonical_profile.funding_per_100k,
        "share_national_pct": canonical_profile.national_share,
        "population": canonical_profile.population,
        "awards_amount": canonical_profile.awards_total,
        "subawards_amount": canonical_profile.subawards_total,
        "contracts_amount": canonical_profile.contracts_total,
        "award_count": canonical_profile.award_count,
        "subaward_count": canonical_profile.subaward_count,
        "contract_award_count": canonical_profile.contract_award_count,
        "normalization_supported": canonical_profile.normalization_supported,
        "normalization_applied": canonical_profile.normalization_applied,
        "normalization_note": canonical_profile.normalization_note,
        "normalization_factor": canonical_profile.normalization_factor,
        "normalized_amount_type": canonical_profile.normalized_amount_type,
        "normalization_status_label": canonical_profile.normalization_status_label,
        "normalization_method": canonical_profile.normalization_method,
        "funding_stream_logic_version": canonical_profile.funding_stream_logic_version,
        "methodology_version": canonical_profile.methodology_version,
        "profile_version": canonical_profile.profile_version,
        "funding_model_version": canonical_profile.funding_model_version,
        "top_program_area": (
            {
                "value": top_area.get("program_area"),
                "label": PROGRAM_AREA_LABELS.get(top_area.get("program_area"), "Other / Unclassified"),
                "chip_total_funding": scaled_top_area_amount,
                "amount": scaled_top_area_amount,
            }
            if top_area
            else None
        ),
        "grouping": {
            "category_label": "Program Area",
            "subcategory_label": "Program",
            "category_method": "TAGGS effective CDC program-area enrichment by ALN/CFDA number, with CDC center-name fallback when no TAGGS match is available.",
            "subcategory_method": "TAGGS effective program-name enrichment by ALN/CFDA number, with USAspending program-title fallback when no TAGGS match is available.",
        },
        "legend_title": build_legend_title(
            metric=filters.metric,
            fiscal_year=filters.fiscal_year,
            min_fiscal_year=metadata["min_fiscal_year"],
            max_fiscal_year=metadata["max_fiscal_year"],
            time_aggregation=filters.time_aggregation,
        ),
        "filter_context": _filter_context_payload(
            filters,
            min_fiscal_year=metadata["min_fiscal_year"],
            max_fiscal_year=metadata["max_fiscal_year"],
        ),
        "methodology_notes": [
            note
            for note in [
                DEFAULT_NOTE,
                "State profile totals use the same CDC funding mode and filter model as the map.",
                canonical_profile.normalization_note,
                _funding_type_note(filters.funding_type),
                _time_aggregation_note(filters.time_aggregation),
            ]
            if note
        ],
    }


def _build_state_profile_categories_payload(
    *,
    state_code: str,
    filters: FundingFilters,
    canonical_profile: FundingProfileResult,
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    totals: dict[str, Any],
) -> dict[str, Any]:
    by_area: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("program_area") or "other_cdc_programs")
        current = by_area.setdefault(
            key,
            {
                "program_area": key,
                "label": PROGRAM_AREA_LABELS.get(key, "Other / Unclassified"),
                "amount": 0.0,
                "award_count": 0,
                "program_count": 0,
            },
        )
        current["amount"] += float(_json_number(row.get("amount")) or 0.0)
        current["award_count"] += int(row.get("award_count") or 0)
        current["program_count"] += 1

    raw_total_amount = float(totals["state_total_amount"] or 0.0)
    category_rows = sorted(
        by_area.values(),
        key=lambda item: (-float(item["amount"]), str(item["label"])),
    )
    return {
        "state_code": state_code,
        "profile": _serialize_funding_profile_result(canonical_profile),
        "funding_mode_requested": canonical_profile.funding_mode_requested,
        "funding_mode_effective": canonical_profile.funding_mode_effective,
        "funding_mode_label": canonical_profile.funding_mode_label,
        "methodology_version": canonical_profile.methodology_version,
        "profile_version": canonical_profile.profile_version,
        "funding_model_version": canonical_profile.funding_model_version,
        "rows": [
            {
                "geography_id": canonical_profile.geography_id,
                "category": row["label"],
                "category_value": row["program_area"],
                "chip_total_funding": _scaled_amount(
                    row["amount"],
                    raw_total=raw_total_amount,
                    target_total=canonical_profile.total_funding,
                ),
                "amount": _scaled_amount(
                    row["amount"],
                    raw_total=raw_total_amount,
                    target_total=canonical_profile.total_funding,
                ),
                "share_pct": _chip_share_value(
                    _scaled_amount(
                        row["amount"],
                        raw_total=raw_total_amount,
                        target_total=canonical_profile.total_funding,
                    ),
                    national_total_funding=canonical_profile.total_funding,
                    fiscal_year=filters.fiscal_year,
                ) or 0,
                "award_count": int(row["award_count"]),
                "subcategory_count": int(row["program_count"]),
            }
            for row in category_rows
        ],
        "grouping": {
            "category_label": "Program Area",
            "subcategory_label": "Program",
        },
        "filter_context": _filter_context_payload(
            filters,
            min_fiscal_year=metadata["min_fiscal_year"],
            max_fiscal_year=metadata["max_fiscal_year"],
        ),
    }


def _build_state_profile_subcategories_payload(
    *,
    state_code: str,
    filters: FundingFilters,
    canonical_profile: FundingProfileResult,
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    totals: dict[str, Any],
) -> dict[str, Any]:
    totals_by_area: dict[str, float] = {}
    for row in rows:
        key = str(row.get("program_area") or "other_cdc_programs")
        totals_by_area[key] = totals_by_area.get(key, 0.0) + float(_json_number(row.get("amount")) or 0.0)
    raw_total_amount = float(totals["state_total_amount"] or 0.0)
    return {
        "state_code": state_code,
        "profile": _serialize_funding_profile_result(canonical_profile),
        "funding_mode_requested": canonical_profile.funding_mode_requested,
        "funding_mode_effective": canonical_profile.funding_mode_effective,
        "funding_mode_label": canonical_profile.funding_mode_label,
        "methodology_version": canonical_profile.methodology_version,
        "profile_version": canonical_profile.profile_version,
        "funding_model_version": canonical_profile.funding_model_version,
        "rows": [
            {
                "geography_id": canonical_profile.geography_id,
                "category": PROGRAM_AREA_LABELS.get(
                    str(row.get("program_area") or "other_cdc_programs"),
                    "Other / Unclassified",
                ),
                "category_value": row.get("program_area"),
                "subcategory": row.get("program_name"),
                "chip_total_funding": _scaled_amount(
                    row.get("amount"),
                    raw_total=raw_total_amount,
                    target_total=canonical_profile.total_funding,
                ),
                "amount": _scaled_amount(
                    row.get("amount"),
                    raw_total=raw_total_amount,
                    target_total=canonical_profile.total_funding,
                ),
                "award_count": int(row.get("award_count") or 0),
                "share_total_pct": _chip_share_value(
                    _scaled_amount(
                        row.get("amount"),
                        raw_total=raw_total_amount,
                        target_total=canonical_profile.total_funding,
                    ),
                    national_total_funding=canonical_profile.total_funding,
                    fiscal_year=filters.fiscal_year,
                ) or 0,
                "share_category_pct": _chip_share_value(
                    _scaled_amount(
                        row.get("amount"),
                        raw_total=raw_total_amount,
                        target_total=canonical_profile.total_funding,
                    ),
                    national_total_funding=_scaled_amount(
                        totals_by_area[str(row.get("program_area") or "other_cdc_programs")],
                        raw_total=raw_total_amount,
                        target_total=canonical_profile.total_funding,
                    ),
                    fiscal_year=filters.fiscal_year,
                ) or 0,
            }
            for row in rows
        ],
        "grouping": {
            "category_label": "Program Area",
            "subcategory_label": "Program",
        },
        "filter_context": _filter_context_payload(
            filters,
            min_fiscal_year=metadata["min_fiscal_year"],
            max_fiscal_year=metadata["max_fiscal_year"],
        ),
    }


def fetch_state_profile_overview(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    funding_mode: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    time_aggregation: str | None = None,
) -> dict[str, Any]:
    state_code = str(state or "").strip().upper()
    if len(state_code) != 2:
        raise HTTPException(status_code=400, detail="state must be a valid 2-letter state code")
    emergency_support = v11_emergency.support_status(
        funding_mode=funding_mode,
        funding_type=funding_type,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
    )
    if emergency_support.enabled:
        return v11_emergency.fetch_state_profile_overview(
            db,
            state=state_code,
            fiscal_year=fiscal_year,
            metric=metric,
            funding_type=funding_type,
            funding_mode=funding_mode,
            cdc_center=cdc_center,
            program_area=program_area,
            mechanism=mechanism,
            recipient_type=recipient_type,
            time_aggregation=time_aggregation,
        )
    _ensure_required_tables(db)
    filters = _normalize_filters(
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        funding_mode=funding_mode,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        geography_level="state",
        time_aggregation=time_aggregation,
    )
    def _load_profile_overview() -> dict[str, Any]:
        canonical_profile = _canonical_profile_for_state(
            db,
            filters,
            state_code=state_code,
        )
        rows, totals, metadata = _profile_state_rows(db, filters, state=state_code)
        return {
            "summary": _build_state_profile_summary_payload(
                db,
                state_code=state_code,
                filters=filters,
                canonical_profile=canonical_profile,
                rows=rows,
                metadata=metadata,
                totals=totals,
            ),
            "categories": _build_state_profile_categories_payload(
                state_code=state_code,
                filters=filters,
                canonical_profile=canonical_profile,
                rows=rows,
                metadata=metadata,
                totals=totals,
            ),
            "subcategories": _build_state_profile_subcategories_payload(
                state_code=state_code,
                filters=filters,
                canonical_profile=canonical_profile,
                rows=rows,
                metadata=metadata,
                totals=totals,
            ),
        }

    return _read_cached_summary_payload(
        db,
        scope="state_profile_overview",
        filters=filters,
        state=state_code,
        loader=_load_profile_overview,
    )


def fetch_state_profile_summary(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    funding_mode: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    time_aggregation: str | None = None,
) -> dict[str, Any]:
    return fetch_state_profile_overview(
        db,
        state=state,
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        funding_mode=funding_mode,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )["summary"]


def fetch_state_profile_categories(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None = None,
    funding_type: str | None = None,
    funding_mode: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    time_aggregation: str | None = None,
) -> dict[str, Any]:
    return fetch_state_profile_overview(
        db,
        state=state,
        fiscal_year=fiscal_year,
        metric="total_funding",
        funding_type=funding_type,
        funding_mode=funding_mode,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )["categories"]


def fetch_state_profile_subcategories(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None = None,
    funding_type: str | None = None,
    funding_mode: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    time_aggregation: str | None = None,
) -> dict[str, Any]:
    return fetch_state_profile_overview(
        db,
        state=state,
        fiscal_year=fiscal_year,
        metric="total_funding",
        funding_type=funding_type,
        funding_mode=funding_mode,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )["subcategories"]


def _diagnostic_years(db: Session, *, limit: int = 3) -> list[int]:
    rows = db.execute(
        text(
            f"""
            SELECT DISTINCT fiscal_year
            FROM {NORMALIZED_TABLE}
            WHERE source_system = 'usaspending'
            ORDER BY fiscal_year DESC
            LIMIT :limit
            """
        ),
        {"limit": max(1, int(limit))},
    ).mappings().all()
    return [int(row["fiscal_year"]) for row in rows if row.get("fiscal_year") is not None]


def fetch_mode_diagnostics(
    db: Session,
    *,
    fiscal_years: list[int] | None = None,
    states: list[str] | None = None,
) -> dict[str, Any]:
    requested_years = [int(year) for year in (fiscal_years or []) if year is not None]
    effective_years = requested_years or _diagnostic_years(db, limit=3)
    effective_states = [
        str(state).strip().upper()
        for state in (states or ["AL", "CA", "NY"])
        if str(state).strip()
    ]
    rows: list[dict[str, Any]] = []
    for fiscal_year in effective_years:
        lookup = fetch_state_normalization_lookup(
            db,
            source_system="usaspending",
            fiscal_year=fiscal_year,
            lookup_variant=normalization_lookup_variant_for_mode(DEFAULT_FUNDING_MODE),
        )
        for state_code in effective_states:
            row = lookup.get(state_code)
            if row is None:
                continue
            raw_amount = _json_number(row.get("raw_amount"))
            normalized_amount = _json_number(row.get("normalized_amount"))
            difference = (
                normalized_amount - raw_amount
                if raw_amount is not None and normalized_amount is not None
                else None
            )
            rows.append(
                {
                    "state_code": state_code,
                    "fiscal_year": fiscal_year,
                    "raw_total_funding": raw_amount,
                    "chip_normalized_funding": normalized_amount,
                    "difference": difference,
                    "excluded_transfer_amount": _json_number(row.get("federal_health_transfer_amount")),
                    "excluded_procurement_research_international_amount": sum(
                        float(_json_number(row.get(field)) or 0.0)
                        for field in (
                            "procurement_support_scope_amount",
                            "biomedical_research_amount",
                            "international_health_assistance_amount",
                        )
                    ),
                    "mixed_conditional_amount": sum(
                        float(_json_number(row.get(field)) or 0.0)
                        for field in (
                            "special_transfer_amount",
                            "unknown_funding_scope_amount",
                            "emergency_public_health_amount",
                        )
                    ),
                    "core_public_health_amount": _json_number(row.get("core_public_health_amount")),
                    "normalization_factor": _json_number(row.get("normalization_factor")),
                    "normalized_amount_type": row.get("normalized_amount_type"),
                    "normalization_method": row.get("normalization_method"),
                    "funding_stream_logic_version": row.get("funding_stream_logic_version"),
                    "methodology_version": row.get("methodology_version"),
                }
            )

    return {
        "funding_mode": DEFAULT_FUNDING_MODE,
        "funding_mode_label": FUNDING_MODE_LABELS[DEFAULT_FUNDING_MODE],
        "rows": rows,
    }
