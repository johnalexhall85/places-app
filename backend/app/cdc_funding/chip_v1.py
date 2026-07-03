from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from numbers import Real
from typing import Any

from fastapi import HTTPException
from fastapi.params import Param
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import places_table, usaspending_fed_account_table
from app.services.chip_funding_model import CDCFundingMode

FUNDING_MODEL_KEY = "chip_account_classification_v1"
FUNDING_MODEL_LABEL = "CHIP Account Classification v1"
FUNDING_MODEL_DESCRIPTION = (
    "Federal-account anchored CDC funding model using reviewed CHIP account classifications."
)
CLASSIFICATION_VERSION_DEFAULT = "chip_account_classification_v1"
MODEL_VERSION = "chip_account_classification_map_api_v1"

LEGACY_FUNDING_MODEL_KEY = "chip_legacy"
LEGACY_FUNDING_MODEL_LABEL = "CHIP Legacy"
LEGACY_FUNDING_MODEL_DESCRIPTION = "Previous CHIP funding model retained as backup for demo continuity."
LEGACY_UNDERLYING_FUNDING_MODE = CDCFundingMode.CHIP_NORMALIZED.value

STATE_MV = usaspending_fed_account_table("mv_chip_v1_state_funding_map")
COUNTY_MV = usaspending_fed_account_table("mv_chip_v1_county_funding_map")
UNMAPPED_MV = usaspending_fed_account_table("mv_chip_v1_unmapped_funding_map")
AWARD_FACT_TABLE = usaspending_fed_account_table("fact_award_account_breakdown")
CLASSIFICATION_TABLE = usaspending_fed_account_table("chip_account_classification")
DIM_ACCOUNT_TABLE = usaspending_fed_account_table("dim_federal_account")
STATE_BOUNDARY_TABLE = places_table("dim_state_boundary")
COUNTY_BOUNDARY_TABLE = places_table("dim_county_boundary")
COUNTY_DIM_TABLE = places_table("dim_county")
POPULATION_VIEW_TABLE = places_table("v_geography_population")

VALID_METRICS = {
    "total_funding": "Total CDC Funding",
    "funding_per_capita": "CDC Funding Per Capita",
    "funding_per_100k": "CDC Funding Per 100,000",
    "share_national": "Share of National CDC Funding",
}
VALID_GEOGRAPHY_LEVELS = {"state", "county", "national"}
DEFAULT_FUNDING_SCOPE_LABEL = "CDC Baseline/Public Map"
PENDING_REVIEW_NOTE = "* Includes some accounts pending final review."
LEGEND_DESCRIPTION = (
    "This model uses federal account classifications to identify CDC-related funding and maps "
    "award-linked obligations by state or county."
)
STATE_SIMPLIFY_DEGREES = 0.04
COUNTY_SIMPLIFY_DEGREES = 0.02


@dataclass(frozen=True)
class ChipV1Filters:
    fiscal_year: int | None
    metric: str
    geography_level: str
    classification_version: str
    funding_scope_preset: str
    award_type: str
    emergency_supplemental_scope: str
    review_status: str
    include_pphf: bool
    transfers_scope: str
    data_source_scope: str


FUNDING_SCOPE_PRESETS = {
    "regular_grants_coops": {
        "label": "Regular CDC grants/cooperative agreements",
        "award_type": "grants_coops",
        "emergency_supplemental_scope": "exclude",
        "review_status": "reviewed_plus_needs_review",
        "include_pphf": True,
        "transfers_scope": "cdc_relevant_only",
        "data_source_scope": "combined",
    },
    "all_grants_coops": {
        "label": "All CDC grants/cooperative agreements",
        "award_type": "grants_coops",
        "emergency_supplemental_scope": "include_both",
        "review_status": "reviewed_plus_needs_review",
        "include_pphf": True,
        "transfers_scope": "include_all",
        "data_source_scope": "combined",
    },
    "all_assistance": {
        "label": "All CDC assistance",
        "award_type": "all_assistance",
        "emergency_supplemental_scope": "include_both",
        "review_status": "reviewed_plus_needs_review",
        "include_pphf": True,
        "transfers_scope": "include_all",
        "data_source_scope": "combined",
    },
    "all_obligations": {
        "label": "All CDC obligations",
        "award_type": "all_award_types",
        "emergency_supplemental_scope": "include_both",
        "review_status": "reviewed_plus_needs_review",
        "include_pphf": True,
        "transfers_scope": "include_all",
        "data_source_scope": "combined",
    },
    "custom": {
        "label": "Custom",
    },
}
VALID_FUNDING_SCOPE_PRESETS = set(FUNDING_SCOPE_PRESETS)
VALID_AWARD_TYPES = {
    "grants_coops",
    "grants_only",
    "cooperative_agreements_only",
    "direct_payments",
    "contracts",
    "all_assistance",
    "all_award_types",
}
VALID_EMERGENCY_SUPPLEMENTAL_SCOPES = {
    "exclude",
    "emergency_only",
    "supplemental_only",
    "include_both",
}
VALID_REVIEW_STATUSES = {"reviewed_only", "reviewed_plus_needs_review", "needs_review_only"}
VALID_TRANSFER_SCOPES = {"cdc_relevant_only", "exclude", "include_all"}
VALID_DATA_SOURCE_SCOPES = {"combined", "usaspending_only", "taggs_only"}

AWARD_TYPE_LABELS = {
    "grants_coops": "Grants + cooperative agreements",
    "grants_only": "Grants only",
    "cooperative_agreements_only": "Cooperative agreements only",
    "direct_payments": "Direct payments",
    "contracts": "Contracts",
    "all_assistance": "All assistance",
    "all_award_types": "All award types",
}
EMERGENCY_SUPPLEMENTAL_LABELS = {
    "exclude": "Exclude emergency and supplemental",
    "emergency_only": "Include emergency only",
    "supplemental_only": "Include supplemental only",
    "include_both": "Include both",
}
REVIEW_STATUS_LABELS = {
    "reviewed_only": "Reviewed only",
    "reviewed_plus_needs_review": "Reviewed + needs review",
    "needs_review_only": "Needs review only",
}
TRANSFER_SCOPE_LABELS = {
    "cdc_relevant_only": "Include CDC-relevant transfers",
    "exclude": "Exclude transfers",
    "include_all": "Include all transfers",
}
DATA_SOURCE_SCOPE_LABELS = {
    "combined": "USAspending + TAGGS where available",
    "usaspending_only": "USAspending only",
    "taggs_only": "TAGGS only",
}
GRANT_ASSISTANCE_TYPE_CODES = {"02", "03", "04"}
COOP_ASSISTANCE_TYPE_CODES = {"05"}
DIRECT_PAYMENT_ASSISTANCE_TYPE_CODES = {"06", "07"}
PENDING_REVIEW_STATUSES = {"candidate", "needs_review"}
PENDING_REVIEW_STATUS_SQL = "'candidate', 'needs_review'"


def is_chip_v1_mode(value: str | None) -> bool:
    return str(value or "").strip().lower() == FUNDING_MODEL_KEY


def is_legacy_mode(value: str | None) -> bool:
    return str(value or "").strip().lower() == LEGACY_FUNDING_MODEL_KEY


def public_mode_options() -> list[dict[str, Any]]:
    return [
        {
            "value": FUNDING_MODEL_KEY,
            "label": FUNDING_MODEL_LABEL,
            "description": FUNDING_MODEL_DESCRIPTION,
            "system": True,
            "is_active": True,
            "sort_order": 10,
        },
        {
            "value": LEGACY_FUNDING_MODEL_KEY,
            "label": LEGACY_FUNDING_MODEL_LABEL,
            "description": LEGACY_FUNDING_MODEL_DESCRIPTION,
            "system": True,
            "is_active": True,
            "sort_order": 20,
        },
    ]


def _json_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return float(value)
    if isinstance(value, Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return None


def _serialize_value(value: Any) -> Any:
    numeric = _json_number(value)
    if numeric is not None:
        return numeric
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return value
    return value


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(text("SELECT to_regclass(:name) AS exists"), {"name": table_name}).mappings().one()
    return row.get("exists") is not None


def _matview_is_populated(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT relispopulated
            FROM pg_class
            WHERE oid = to_regclass(:name)
            """
        ),
        {"name": table_name},
    ).mappings().one_or_none()
    return bool(row and row.get("relispopulated"))


def _ensure_required_views(db: Session) -> None:
    missing = [name for name in (STATE_MV, COUNTY_MV, UNMAPPED_MV) if not _table_exists(db, name)]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "The CHIP Account Classification v1 map summaries are missing: "
                + ", ".join(missing)
                + ". Run migrations, then refresh the CHIP v1 funding map views."
            ),
        )
    unpopulated = [name for name in (STATE_MV, COUNTY_MV, UNMAPPED_MV) if not _matview_is_populated(db, name)]
    if unpopulated:
        raise HTTPException(
            status_code=503,
            detail=(
                "The CHIP Account Classification v1 map summaries exist but have not been refreshed: "
                + ", ".join(unpopulated)
                + ". Run scripts/refresh_chip_v1_funding_map_views.py."
            ),
        )


def _latest_completed_federal_fiscal_year(reference_date: date | None = None) -> int:
    today = reference_date or date.today()
    return today.year if today.month >= 10 else today.year - 1


def available_fiscal_years_by_geography(db: Session) -> dict[str, list[int]]:
    if not _table_exists(db, STATE_MV) or not _table_exists(db, COUNTY_MV):
        return {"state": [], "county": [], "national": []}
    if not _matview_is_populated(db, STATE_MV) or not _matview_is_populated(db, COUNTY_MV):
        return {"state": [], "county": [], "national": []}
    state_rows = db.execute(
        text(
            f"""
            SELECT fiscal_year
            FROM {STATE_MV}
            WHERE classification_version = :classification_version
            GROUP BY fiscal_year
            ORDER BY fiscal_year DESC
            """
        ),
        {"classification_version": CLASSIFICATION_VERSION_DEFAULT},
    ).mappings().all()
    county_rows = db.execute(
        text(
            f"""
            SELECT fiscal_year
            FROM {COUNTY_MV}
            WHERE classification_version = :classification_version
            GROUP BY fiscal_year
            ORDER BY fiscal_year DESC
            """
        ),
        {"classification_version": CLASSIFICATION_VERSION_DEFAULT},
    ).mappings().all()
    state_years = [int(row["fiscal_year"]) for row in state_rows if row.get("fiscal_year") is not None]
    county_years = [int(row["fiscal_year"]) for row in county_rows if row.get("fiscal_year") is not None]
    return {"state": state_years, "county": county_years, "national": state_years}


def available_fiscal_years(db: Session, *, geography_level: str = "state") -> list[int]:
    availability = available_fiscal_years_by_geography(db)
    level = str(geography_level or "state").strip().lower()
    return availability.get(level, availability["state"])


def default_fiscal_year(db: Session, *, geography_level: str = "state") -> int | None:
    years = available_fiscal_years(db, geography_level=geography_level)
    if not years:
        return None
    if 2023 in years:
        return 2023
    latest_completed_year = _latest_completed_federal_fiscal_year()
    for year in years:
        if year <= latest_completed_year:
            return year
    return years[0]


def filter_defaults(db: Session) -> dict[str, Any]:
    years_by_geography = available_fiscal_years_by_geography(db)
    years = years_by_geography["state"]
    preset = FUNDING_SCOPE_PRESETS["regular_grants_coops"]
    return {
        "available_fiscal_years": years,
        "available_fiscal_years_by_geography": years_by_geography,
        "default_fiscal_year": default_fiscal_year(db, geography_level="state"),
        "classification_version": CLASSIFICATION_VERSION_DEFAULT,
        "include_pending_review": True,
        "funding_scope_label": DEFAULT_FUNDING_SCOPE_LABEL,
        "funding_scope_preset": "regular_grants_coops",
        "award_type": preset["award_type"],
        "emergency_supplemental_scope": preset["emergency_supplemental_scope"],
        "review_status": preset["review_status"],
        "include_pphf": preset["include_pphf"],
        "transfers_scope": preset["transfers_scope"],
        "data_source_scope": preset["data_source_scope"],
        "funding_scope_preset_options": [
            {"value": value, "label": config["label"]}
            for value, config in FUNDING_SCOPE_PRESETS.items()
        ],
        "award_type_options": [
            {"value": value, "label": AWARD_TYPE_LABELS[value]}
            for value in (
                "grants_coops",
                "grants_only",
                "cooperative_agreements_only",
                "direct_payments",
                "contracts",
                "all_assistance",
                "all_award_types",
            )
        ],
        "emergency_supplemental_scope_options": [
            {"value": value, "label": EMERGENCY_SUPPLEMENTAL_LABELS[value]}
            for value in ("exclude", "emergency_only", "supplemental_only", "include_both")
        ],
        "review_status_options": [
            {"value": value, "label": REVIEW_STATUS_LABELS[value]}
            for value in ("reviewed_only", "reviewed_plus_needs_review", "needs_review_only")
        ],
        "pphf_options": [
            {"value": True, "label": "Include PPHF"},
            {"value": False, "label": "Exclude PPHF"},
        ],
        "transfers_scope_options": [
            {"value": value, "label": TRANSFER_SCOPE_LABELS[value]}
            for value in ("cdc_relevant_only", "exclude", "include_all")
        ],
        "data_source_scope_options": [
            {"value": value, "label": DATA_SOURCE_SCOPE_LABELS[value]}
            for value in ("combined", "usaspending_only", "taggs_only")
        ],
    }


def _normalize_metric(value: str | None) -> str:
    token = str(value or "total_funding").strip().lower()
    if token not in VALID_METRICS:
        raise HTTPException(status_code=400, detail=f"metric must be one of {', '.join(sorted(VALID_METRICS))}")
    return token


def _normalize_geography_level(value: str | None) -> str:
    token = str(value or "state").strip().lower()
    if token not in VALID_GEOGRAPHY_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"geography_level must be one of {', '.join(sorted(VALID_GEOGRAPHY_LEVELS))}",
        )
    return token


def _normalize_classification_version(value: str | None) -> str:
    token = str(value or CLASSIFICATION_VERSION_DEFAULT).strip()
    if not token:
        return CLASSIFICATION_VERSION_DEFAULT
    return token


def _normalize_choice(value: str | None, *, default: str, valid: set[str], field_name: str) -> str:
    if isinstance(value, Param):
        value = None
    token = str(value or default).strip().lower()
    if token not in valid:
        raise HTTPException(status_code=400, detail=f"{field_name} must be one of {', '.join(sorted(valid))}")
    return token


def _normalize_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, Param):
        return default
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if token in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _normalize_filters(
    db: Session,
    *,
    fiscal_year: int | None,
    metric: str | None,
    geography_level: str | None,
    classification_version: str | None = None,
    funding_scope_preset: str | None = None,
    award_type: str | None = None,
    emergency_supplemental_scope: str | None = None,
    review_status: str | None = None,
    include_pphf: Any = None,
    transfers_scope: str | None = None,
    data_source_scope: str | None = None,
) -> ChipV1Filters:
    normalized_geography = _normalize_geography_level(geography_level)
    effective_fiscal_year = int(fiscal_year) if fiscal_year is not None else default_fiscal_year(
        db,
        geography_level=normalized_geography,
    )
    preset = _normalize_choice(
        funding_scope_preset,
        default="regular_grants_coops",
        valid=VALID_FUNDING_SCOPE_PRESETS,
        field_name="funding_scope_preset",
    )
    preset_defaults = FUNDING_SCOPE_PRESETS.get(preset, {})
    should_apply_preset = preset != "custom"
    default_award_type = preset_defaults.get("award_type", "grants_coops") if should_apply_preset else "grants_coops"
    default_emergency_scope = (
        preset_defaults.get("emergency_supplemental_scope", "exclude") if should_apply_preset else "exclude"
    )
    default_review_status = (
        preset_defaults.get("review_status", "reviewed_plus_needs_review")
        if should_apply_preset
        else "reviewed_plus_needs_review"
    )
    default_include_pphf = bool(preset_defaults.get("include_pphf", True)) if should_apply_preset else True
    default_transfers_scope = (
        preset_defaults.get("transfers_scope", "cdc_relevant_only") if should_apply_preset else "cdc_relevant_only"
    )
    default_data_source_scope = (
        preset_defaults.get("data_source_scope", "combined") if should_apply_preset else "combined"
    )
    return ChipV1Filters(
        fiscal_year=effective_fiscal_year,
        metric=_normalize_metric(metric),
        geography_level=normalized_geography,
        classification_version=_normalize_classification_version(classification_version),
        funding_scope_preset=preset,
        award_type=_normalize_choice(
            default_award_type if should_apply_preset else award_type,
            default=default_award_type,
            valid=VALID_AWARD_TYPES,
            field_name="award_type",
        ),
        emergency_supplemental_scope=_normalize_choice(
            default_emergency_scope if should_apply_preset else emergency_supplemental_scope,
            default=default_emergency_scope,
            valid=VALID_EMERGENCY_SUPPLEMENTAL_SCOPES,
            field_name="emergency_supplemental_scope",
        ),
        review_status=_normalize_choice(
            default_review_status if should_apply_preset else review_status,
            default=default_review_status,
            valid=VALID_REVIEW_STATUSES,
            field_name="review_status",
        ),
        include_pphf=default_include_pphf if should_apply_preset else _normalize_bool(include_pphf, default=True),
        transfers_scope=_normalize_choice(
            default_transfers_scope if should_apply_preset else transfers_scope,
            default=default_transfers_scope,
            valid=VALID_TRANSFER_SCOPES,
            field_name="transfers_scope",
        ),
        data_source_scope=_normalize_choice(
            default_data_source_scope if should_apply_preset else data_source_scope,
            default=default_data_source_scope,
            valid=VALID_DATA_SOURCE_SCOPES,
            field_name="data_source_scope",
        ),
    )


def _metric_value(metric: str, *, total_amount: Any, population: Any, national_total: Any) -> float | None:
    total = _json_number(total_amount)
    pop = _json_number(population)
    national = _json_number(national_total)
    if total is None:
        return None
    if metric == "total_funding":
        return total
    if metric == "funding_per_capita":
        return total / pop if pop not in (None, 0) else None
    if metric == "funding_per_100k":
        return (total / pop) * 100000 if pop not in (None, 0) else None
    if metric == "share_national":
        return (total / national) * 100 if national not in (None, 0) else None
    return total


def _compute_bins(values: list[float], *, bin_count: int = 5) -> list[dict[str, Any]]:
    finite_values = sorted(value for value in values if math.isfinite(float(value)))
    if not finite_values:
        return []
    if len(set(finite_values)) == 1:
        value = finite_values[0]
        return [{"min": value, "max": value, "label": f"{value:,.1f}", "colorIndex": bin_count - 1}]
    minimum = finite_values[0]
    maximum = finite_values[-1]
    step = (maximum - minimum) / bin_count
    bins: list[dict[str, Any]] = []
    for index in range(bin_count):
        start = minimum + (step * index)
        end = maximum if index == bin_count - 1 else minimum + (step * (index + 1))
        bins.append({"min": start, "max": end, "colorIndex": index})
    return bins


def _fiscal_year_clause(filters: ChipV1Filters, *, alias: str = "m") -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {"classification_version": filters.classification_version}
    clauses = [f"{alias}.classification_version = :classification_version"]
    if filters.fiscal_year is not None:
        clauses.append(f"{alias}.fiscal_year = :fiscal_year")
        params["fiscal_year"] = int(filters.fiscal_year)
    return " AND ".join(clauses), params


def _assistance_type_expr(alias: str = "award") -> str:
    return f"""
        NULLIF(
            UPPER(BTRIM(COALESCE(
                {alias}.raw_row_json->>'assistance_type_code',
                {alias}.raw_row_json->>'award_type_code',
                {alias}.raw_row_json->>'award_type',
                {alias}.raw_row_json->>'type',
                {alias}.raw_row_json->>'assistance_type'
            ))),
            ''
        )
    """


def _classification_scope_where_clause(filters: ChipV1Filters, *, alias: str = "classification") -> str:
    clauses = [
        f"{alias}.classification_version = :classification_version",
        f"{alias}.review_status IS DISTINCT FROM 'rejected'",
        f"{alias}.is_cdc_related IS TRUE",
    ]
    if filters.fiscal_year is not None:
        clauses.append(f"{alias}.fiscal_year = :fiscal_year")

    if filters.funding_scope_preset == "regular_grants_coops":
        clauses.append(
            f"""(
                {alias}.include_in_public_map IS TRUE
             OR {alias}.include_in_chip_baseline IS TRUE
            )"""
        )
        clauses.append(f"{alias}.funding_scope IN ('regular_appropriation', 'pphf', 'transfer')")
    else:
        clauses.append(
            f"""(
                {alias}.include_in_public_map IS TRUE
             OR {alias}.include_in_chip_baseline IS TRUE
             OR {alias}.include_in_chip_emergency IS TRUE
             OR {alias}.include_in_chip_total IS TRUE
             OR {alias}.cdc_scope_category IN ('cdc_core', 'cdc_transfer', 'cdc_emergency', 'cdc_business_support', 'cdc_atdsr', 'cdc_niosh')
            )"""
        )

    if filters.review_status == "reviewed_only":
        clauses.append(f"{alias}.review_status = 'reviewed'")
    elif filters.review_status == "needs_review_only":
        clauses.append(f"{alias}.review_status IN ({PENDING_REVIEW_STATUS_SQL})")
    else:
        clauses.append(f"{alias}.review_status IN ('reviewed', {PENDING_REVIEW_STATUS_SQL})")

    if filters.emergency_supplemental_scope == "exclude":
        clauses.append(
            f"""(
                {alias}.funding_scope IS DISTINCT FROM 'emergency_supplemental'
            AND COALESCE({alias}.include_in_chip_emergency, false) IS FALSE
            )"""
        )
    elif filters.emergency_supplemental_scope == "emergency_only":
        clauses.append(f"{alias}.include_in_chip_emergency IS TRUE")
    elif filters.emergency_supplemental_scope == "supplemental_only":
        clauses.append(f"{alias}.funding_scope = 'emergency_supplemental'")

    if not filters.include_pphf:
        clauses.append(f"{alias}.funding_scope IS DISTINCT FROM 'pphf'")

    if filters.transfers_scope == "exclude":
        clauses.append(
            f"""(
                {alias}.funding_scope IS DISTINCT FROM 'transfer'
            AND {alias}.cdc_scope_category IS DISTINCT FROM 'cdc_transfer'
            )"""
        )
    elif filters.transfers_scope == "cdc_relevant_only":
        clauses.append(
            f"""(
                {alias}.funding_scope IS DISTINCT FROM 'transfer'
             OR {alias}.include_in_public_map IS TRUE
             OR {alias}.include_in_chip_baseline IS TRUE
            )"""
        )

    return " AND ".join(clauses)


def _award_prefilter_where_clause(filters: ChipV1Filters, *, alias: str = "award") -> str:
    clauses = []
    if filters.fiscal_year is not None:
        clauses.append(f"{alias}.fiscal_year = :fiscal_year")

    if filters.award_type in {
        "grants_coops",
        "grants_only",
        "cooperative_agreements_only",
        "direct_payments",
        "all_assistance",
    }:
        clauses.append(f"{alias}.award_source_type = 'assistance'")
    elif filters.award_type == "contracts":
        clauses.append(f"{alias}.award_source_type = 'contracts'")
    elif filters.award_type == "all_award_types":
        clauses.append(f"{alias}.award_source_type IN ('assistance', 'contracts', 'unlinked')")

    return " AND ".join(clauses) if clauses else "TRUE"


def _classified_awards_cte_sql(filters: ChipV1Filters) -> str:
    assistance_type_expr = _assistance_type_expr("award")
    classification_where = _classification_scope_where_clause(filters)
    award_where = _award_prefilter_where_clause(filters)
    return f"""
        candidate_classifications AS (
            SELECT
                classification.fiscal_year,
                classification.federal_account_id,
                classification.normalized_account_key,
                classification.federal_account_name,
                classification.is_cdc_related,
                classification.cdc_scope_category,
                classification.funding_scope,
                classification.include_in_chip_baseline,
                classification.include_in_chip_emergency,
                classification.include_in_chip_total,
                classification.include_in_public_map,
                classification.review_status,
                classification.classification_version
            FROM {CLASSIFICATION_TABLE} AS classification
            WHERE {classification_where}
        ),
        classified_awards AS (
            SELECT
                award.id AS award_row_id,
                award.fiscal_year,
                award.award_source_type,
                {assistance_type_expr} AS assistance_type_code,
                COALESCE(
                    award.generated_unique_award_id,
                    award.award_id,
                    award.fain,
                    award.piid,
                    award.uri,
                    award.id::text
                ) AS award_key,
                award.generated_unique_award_id,
                award.award_id,
                award.piid,
                award.fain,
                award.uri,
                award.recipient_name,
                award.recipient_state_code,
                award.recipient_county_name,
                award.recipient_county_fips,
                award.place_of_performance_state_code,
                award.place_of_performance_county_name,
                award.place_of_performance_county_fips,
                award.action_date,
                award.cfda_title,
                award.award_description,
                COALESCE(award.obligation_amount, award.transaction_obligated_amount, 0)::numeric AS obligation_amount,
                classification.normalized_account_key,
                classification.federal_account_name,
                classification.is_cdc_related,
                classification.cdc_scope_category,
                classification.funding_scope,
                classification.include_in_chip_baseline,
                classification.include_in_chip_emergency,
                classification.include_in_chip_total,
                classification.include_in_public_map,
                classification.review_status,
                classification.classification_version,
                COALESCE(
                    NULLIF(UPPER(BTRIM(award.place_of_performance_state_code)), ''),
                    NULLIF(UPPER(BTRIM(award.recipient_state_code)), '')
                ) AS state_code,
                COALESCE(
                    CASE
                        WHEN regexp_replace(COALESCE(award.place_of_performance_county_fips, ''), '[^0-9]', '', 'g') ~ '^[0-9]{{1,5}}$'
                            THEN LPAD(regexp_replace(COALESCE(award.place_of_performance_county_fips, ''), '[^0-9]', '', 'g'), 5, '0')
                        ELSE NULL
                    END,
                    CASE
                        WHEN regexp_replace(COALESCE(award.recipient_county_fips, ''), '[^0-9]', '', 'g') ~ '^[0-9]{{1,5}}$'
                            THEN LPAD(regexp_replace(COALESCE(award.recipient_county_fips, ''), '[^0-9]', '', 'g'), 5, '0')
                        ELSE NULL
                    END
                ) AS county_fips
            FROM {AWARD_FACT_TABLE} AS award
            JOIN candidate_classifications AS classification
             ON classification.fiscal_year = award.fiscal_year
            AND classification.federal_account_id = award.federal_account_id
            WHERE {award_where}
        )
    """


def _scope_where_clause(filters: ChipV1Filters, *, alias: str = "classified_awards") -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {
        "classification_version": filters.classification_version,
        "grant_codes": sorted(GRANT_ASSISTANCE_TYPE_CODES),
        "coop_codes": sorted(COOP_ASSISTANCE_TYPE_CODES),
        "grant_or_coop_codes": sorted(GRANT_ASSISTANCE_TYPE_CODES | COOP_ASSISTANCE_TYPE_CODES),
        "direct_payment_codes": sorted(DIRECT_PAYMENT_ASSISTANCE_TYPE_CODES),
    }
    clauses = [
        f"{alias}.classification_version = :classification_version",
        f"{alias}.review_status IS DISTINCT FROM 'rejected'",
        f"{alias}.is_cdc_related IS TRUE",
    ]
    if filters.fiscal_year is not None:
        clauses.append(f"{alias}.fiscal_year = :fiscal_year")
        params["fiscal_year"] = int(filters.fiscal_year)

    if filters.data_source_scope == "taggs_only":
        clauses.append("FALSE")
    elif filters.data_source_scope not in {"combined", "usaspending_only"}:
        clauses.append("FALSE")

    if filters.funding_scope_preset == "regular_grants_coops":
        clauses.append(
            f"""(
                {alias}.include_in_public_map IS TRUE
             OR {alias}.include_in_chip_baseline IS TRUE
            )"""
        )
        clauses.append(f"{alias}.funding_scope IN ('regular_appropriation', 'pphf', 'transfer')")
    else:
        clauses.append(
            f"""(
                {alias}.include_in_public_map IS TRUE
             OR {alias}.include_in_chip_baseline IS TRUE
             OR {alias}.include_in_chip_emergency IS TRUE
             OR {alias}.include_in_chip_total IS TRUE
             OR {alias}.cdc_scope_category IN ('cdc_core', 'cdc_transfer', 'cdc_emergency', 'cdc_business_support', 'cdc_atdsr', 'cdc_niosh')
            )"""
        )

    if filters.review_status == "reviewed_only":
        clauses.append(f"{alias}.review_status = 'reviewed'")
    elif filters.review_status == "needs_review_only":
        clauses.append(f"{alias}.review_status IN ({PENDING_REVIEW_STATUS_SQL})")
    else:
        clauses.append(f"{alias}.review_status IN ('reviewed', {PENDING_REVIEW_STATUS_SQL})")

    if filters.award_type == "grants_coops":
        clauses.append(
            f"""(
                {alias}.award_source_type = 'assistance'
            AND (
                    {alias}.assistance_type_code IS NULL
                 OR {alias}.assistance_type_code = ANY(:grant_or_coop_codes)
                )
            )"""
        )
    elif filters.award_type == "grants_only":
        clauses.append(f"{alias}.award_source_type = 'assistance' AND {alias}.assistance_type_code = ANY(:grant_codes)")
    elif filters.award_type == "cooperative_agreements_only":
        clauses.append(f"{alias}.award_source_type = 'assistance' AND {alias}.assistance_type_code = ANY(:coop_codes)")
    elif filters.award_type == "direct_payments":
        clauses.append(
            f"{alias}.award_source_type = 'assistance' AND {alias}.assistance_type_code = ANY(:direct_payment_codes)"
        )
    elif filters.award_type == "contracts":
        clauses.append(f"{alias}.award_source_type = 'contracts'")
    elif filters.award_type == "all_assistance":
        clauses.append(f"{alias}.award_source_type = 'assistance'")
    elif filters.award_type == "all_award_types":
        clauses.append(f"{alias}.award_source_type IN ('assistance', 'contracts', 'unlinked')")

    if filters.emergency_supplemental_scope == "exclude":
        clauses.append(
            f"""(
                {alias}.funding_scope IS DISTINCT FROM 'emergency_supplemental'
            AND COALESCE({alias}.include_in_chip_emergency, false) IS FALSE
            )"""
        )
    elif filters.emergency_supplemental_scope in {"emergency_only", "supplemental_only"}:
        clauses.append(
            f"""(
                {alias}.funding_scope = 'emergency_supplemental'
             OR {alias}.include_in_chip_emergency IS TRUE
            )"""
        )

    if not filters.include_pphf:
        clauses.append(f"{alias}.funding_scope IS DISTINCT FROM 'pphf'")

    if filters.transfers_scope == "exclude":
        clauses.append(
            f"""(
                {alias}.funding_scope IS DISTINCT FROM 'transfer'
            AND {alias}.cdc_scope_category IS DISTINCT FROM 'cdc_transfer'
            )"""
        )
    elif filters.transfers_scope == "cdc_relevant_only":
        clauses.append(
            f"""(
                {alias}.funding_scope IS DISTINCT FROM 'transfer'
             OR {alias}.include_in_public_map IS TRUE
             OR {alias}.include_in_chip_baseline IS TRUE
            )"""
        )

    return " AND ".join(clauses), params


def _filtered_awards_sql(filters: ChipV1Filters) -> tuple[str, dict[str, Any]]:
    where_sql, params = _scope_where_clause(filters)
    return (
        f"""
        WITH {_classified_awards_cte_sql(filters)},
        filtered_awards AS (
            SELECT *
            FROM classified_awards
            WHERE {where_sql}
        )
        """,
        params,
    )


def _metadata_payload(
    db: Session,
    filters: ChipV1Filters,
    *,
    geography_level: str | None = None,
) -> dict[str, Any]:
    level = str(geography_level or filters.geography_level).strip().lower()
    geography_field = "county_fips" if level == "county" else "state_code"
    cte_sql, params = _filtered_awards_sql(filters)
    row = db.execute(
        text(
            f"""
            {cte_sql}
            SELECT
                COALESCE(SUM(obligation_amount) FILTER (
                    WHERE {geography_field} IS NOT NULL AND {geography_field} <> ''
                ), 0)::numeric AS mapped_total,
                COALESCE(SUM(obligation_amount) FILTER (
                    WHERE review_status IN ('candidate', 'needs_review')
                      AND {geography_field} IS NOT NULL
                      AND {geography_field} <> ''
                ), 0)::numeric AS pending_review_total,
                COUNT(DISTINCT award_key) FILTER (
                    WHERE review_status IN ('candidate', 'needs_review')
                      AND {geography_field} IS NOT NULL
                      AND {geography_field} <> ''
                )::bigint AS pending_review_award_count,
                COUNT(DISTINCT normalized_account_key)::integer AS included_account_count,
                COUNT(DISTINCT normalized_account_key) FILTER (
                    WHERE review_status IN ('candidate', 'needs_review')
                )::integer AS pending_review_account_count,
                COALESCE(SUM(obligation_amount) FILTER (
                    WHERE {geography_field} IS NULL OR {geography_field} = ''
                ), 0)::numeric AS unmapped_award_total,
                COALESCE(SUM(obligation_amount) FILTER (
                    WHERE award_source_type = 'unlinked'
                      AND ({geography_field} IS NULL OR {geography_field} = '')
                ), 0)::numeric AS unmapped_unlinked_total,
                COUNT(DISTINCT award_key) FILTER (
                    WHERE {geography_field} IS NULL OR {geography_field} = ''
                )::bigint AS unmapped_award_count,
                COUNT(DISTINCT {geography_field}) FILTER (
                    WHERE {geography_field} IS NOT NULL AND {geography_field} <> ''
                )::integer AS mapped_row_count,
                MAX(action_date) AS last_refreshed_at
            FROM filtered_awards
            """
        ),
        params,
    ).mappings().one()
    pending_total = _json_number(row.get("pending_review_total")) or 0.0
    pending_account_count = int(row.get("pending_review_account_count") or 0)
    return {
        "funding_model": FUNDING_MODEL_KEY,
        "funding_model_label": FUNDING_MODEL_LABEL,
        "classification_version": filters.classification_version,
        "funding_scope_label": FUNDING_SCOPE_PRESETS[filters.funding_scope_preset]["label"],
        "includes_pending_review": pending_total > 0 or pending_account_count > 0,
        "pending_review_total": pending_total,
        "pending_review_account_count": pending_account_count,
        "pending_review_award_count": int(row.get("pending_review_award_count") or 0),
        "included_account_count": int(row.get("included_account_count") or 0),
        "unmapped_award_total": _json_number(row.get("unmapped_award_total")) or 0.0,
        "unmapped_unlinked_total": _json_number(row.get("unmapped_unlinked_total")) or 0.0,
        "unmapped_award_count": int(row.get("unmapped_award_count") or 0),
        "last_refreshed_at": _serialize_value(row.get("last_refreshed_at")),
        "legacy_available": True,
        "pending_review_note": PENDING_REVIEW_NOTE,
        "mapped_total": _json_number(row.get("mapped_total")) or 0.0,
        "mapped_row_count": int(row.get("mapped_row_count") or 0),
        "filter_context": _filter_context(filters, geography_level=level),
    }


def _legend_title(filters: ChipV1Filters) -> str:
    scope_label = FUNDING_SCOPE_PRESETS[filters.funding_scope_preset]["label"]
    if filters.metric == "total_funding":
        return f"{scope_label} - CHIP Account Classification v1"
    return f"{VALID_METRICS[filters.metric]} - {scope_label}"


def _timeframe_label(filters: ChipV1Filters) -> str:
    return f"FY{filters.fiscal_year}" if filters.fiscal_year is not None else "All available fiscal years"


def _filter_context(filters: ChipV1Filters, *, geography_level: str | None = None) -> dict[str, Any]:
    level = geography_level or filters.geography_level
    scope_label = FUNDING_SCOPE_PRESETS[filters.funding_scope_preset]["label"]
    return {
        "funding_type_label": scope_label,
        "funding_model": FUNDING_MODEL_KEY,
        "funding_model_label": FUNDING_MODEL_LABEL,
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "classification_version": filters.classification_version,
        "geography_level": level,
        "funding_scope_preset": filters.funding_scope_preset,
        "funding_scope_preset_label": scope_label,
        "fiscal_year": filters.fiscal_year,
        "award_type": filters.award_type,
        "award_type_label": AWARD_TYPE_LABELS[filters.award_type],
        "emergency_supplemental_scope": filters.emergency_supplemental_scope,
        "emergency_supplemental_scope_label": EMERGENCY_SUPPLEMENTAL_LABELS[filters.emergency_supplemental_scope],
        "review_status": filters.review_status,
        "review_status_label": REVIEW_STATUS_LABELS[filters.review_status],
        "include_pphf": filters.include_pphf,
        "pphf_label": "Include PPHF" if filters.include_pphf else "Exclude PPHF",
        "transfers_scope": filters.transfers_scope,
        "transfers_scope_label": TRANSFER_SCOPE_LABELS[filters.transfers_scope],
        "data_source_scope": filters.data_source_scope,
        "data_source_scope_label": DATA_SOURCE_SCOPE_LABELS[filters.data_source_scope],
        "time_aggregation_label": "Single fiscal year" if filters.fiscal_year is not None else "All available years",
        "legend_title": _legend_title(filters),
    }


def _profile_payload(
    *,
    filters: ChipV1Filters,
    geography_type: str,
    geography_id: str,
    geography_name: str,
    state_code: str | None,
    total_amount: Any,
    population: Any,
    national_total: Any,
    award_count: Any,
    assistance_obligations: Any = None,
    contracts_obligations: Any = None,
    unlinked_obligations: Any = None,
    needs_review_obligations: Any = None,
    reviewed_obligations: Any = None,
    included_account_count: Any = None,
    needs_review_account_count: Any = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total = _json_number(total_amount)
    pop = _json_number(population)
    national = _json_number(national_total)
    funding_per_capita = _metric_value("funding_per_capita", total_amount=total, population=pop, national_total=national)
    funding_per_100k = _metric_value("funding_per_100k", total_amount=total, population=pop, national_total=national)
    national_share = _metric_value("share_national", total_amount=total, population=pop, national_total=national)
    metric_value = _metric_value(filters.metric, total_amount=total, population=pop, national_total=national)
    return {
        "geography_type": geography_type,
        "geography_id": geography_id,
        "geography_name": geography_name,
        "state_code": state_code,
        "fiscal_year": filters.fiscal_year,
        "timeframe_label": _timeframe_label(filters),
        "metric": filters.metric,
        "metric_label": VALID_METRICS[filters.metric],
        "metric_value": metric_value,
        "total_funding": total,
        "funding_per_capita": funding_per_capita,
        "funding_per_100k": funding_per_100k,
        "national_share": national_share,
        "population": pop,
        "award_count": int(award_count or 0),
        "assistance_obligations": _json_number(assistance_obligations),
        "contracts_obligations": _json_number(contracts_obligations),
        "unlinked_obligations": _json_number(unlinked_obligations),
        "needs_review_obligations": _json_number(needs_review_obligations) or 0.0,
        "reviewed_obligations": _json_number(reviewed_obligations) or 0.0,
        "included_account_count": int(included_account_count or 0),
        "needs_review_account_count": int(needs_review_account_count or 0),
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "funding_model": FUNDING_MODEL_KEY,
        "funding_model_label": FUNDING_MODEL_LABEL,
        "classification_version": filters.classification_version,
        "funding_model_version": MODEL_VERSION,
        "metadata": metadata or {},
    }


def _national_totals(db: Session, filters: ChipV1Filters) -> dict[str, Any]:
    cte_sql, params = _filtered_awards_sql(filters)
    row = db.execute(
        text(
            f"""
            {cte_sql},
            state_totals AS (
                SELECT
                    COALESCE(SUM(obligation_amount), 0)::numeric AS total_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'assistance'), 0)::numeric
                        AS assistance_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'contracts'), 0)::numeric
                        AS contracts_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'unlinked'), 0)::numeric
                        AS unlinked_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE review_status IN ('candidate', 'needs_review')), 0)::numeric
                        AS needs_review_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE review_status NOT IN ('candidate', 'needs_review')), 0)::numeric
                        AS reviewed_obligations,
                    COUNT(DISTINCT award_key)::bigint AS award_count,
                    COUNT(DISTINCT award_key) FILTER (WHERE review_status IN ('candidate', 'needs_review'))::bigint
                        AS needs_review_award_count,
                    COUNT(DISTINCT normalized_account_key)::bigint AS included_account_count,
                    COUNT(DISTINCT normalized_account_key) FILTER (WHERE review_status IN ('candidate', 'needs_review'))::bigint
                        AS needs_review_account_count
                FROM filtered_awards
            ),
            population AS (
                SELECT COALESCE(SUM(pop.population), 0)::numeric AS population
                FROM {POPULATION_VIEW_TABLE} AS pop
                WHERE pop.geography_type = 'state'
            )
            SELECT state_totals.*, population.population
            FROM state_totals
            CROSS JOIN population
            """
        ),
        params,
    ).mappings().one()
    return dict(row)


def _fetch_geography_rows(
    db: Session,
    filters: ChipV1Filters,
    *,
    bbox: str | None,
    limit: int,
    include_geometry: bool,
) -> list[dict[str, Any]]:
    cte_sql, params = _filtered_awards_sql(filters)
    if filters.geography_level == "state":
        geometry_expr = (
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(sb.geom, :simplify_degrees), 6)::json AS geometry"
            if include_geometry
            else "NULL::json AS geometry"
        )
        rows = db.execute(
            text(
                f"""
                {cte_sql},
                grouped AS (
                    SELECT
                        state_code,
                        COALESCE(SUM(obligation_amount), 0)::numeric AS total_obligations,
                        COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'assistance'), 0)::numeric
                            AS assistance_obligations,
                        COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'contracts'), 0)::numeric
                            AS contracts_obligations,
                        COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'unlinked'), 0)::numeric
                            AS unlinked_obligations,
                        COALESCE(SUM(obligation_amount) FILTER (WHERE review_status IN ('candidate', 'needs_review')), 0)::numeric
                            AS needs_review_obligations,
                        COALESCE(SUM(obligation_amount) FILTER (WHERE review_status NOT IN ('candidate', 'needs_review')), 0)::numeric
                            AS reviewed_obligations,
                        COUNT(DISTINCT award_key)::bigint AS award_count,
                        COUNT(DISTINCT award_key) FILTER (WHERE review_status IN ('candidate', 'needs_review'))::bigint
                            AS needs_review_award_count,
                        COUNT(DISTINCT normalized_account_key)::bigint AS included_account_count,
                        COUNT(DISTINCT normalized_account_key) FILTER (WHERE review_status IN ('candidate', 'needs_review'))::bigint
                            AS needs_review_account_count
                    FROM filtered_awards
                    WHERE state_code IS NOT NULL AND state_code <> ''
                    GROUP BY state_code
                ),
                national_total AS (
                    SELECT COALESCE(SUM(total_obligations), 0)::numeric AS national_total
                    FROM grouped
                )
                SELECT
                    sb.state_abbr AS geography_id,
                    sb.state_name AS geography_name,
                    sb.state_abbr AS state_code,
                    sb.state_name AS state_name,
                    m.total_obligations,
                    m.assistance_obligations,
                    m.contracts_obligations,
                    m.unlinked_obligations,
                    m.needs_review_obligations,
                    m.reviewed_obligations,
                    m.award_count,
                    m.needs_review_award_count,
                    m.included_account_count,
                    m.needs_review_account_count,
                    pop.population::numeric AS population,
                    national_total.national_total,
                    {geometry_expr}
                FROM {STATE_BOUNDARY_TABLE} AS sb
                LEFT JOIN grouped AS m
                  ON m.state_code = sb.state_abbr
                LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
                  ON pop.geography_type = 'state'
                 AND pop.geography_id = sb.state_abbr
                CROSS JOIN national_total
                WHERE sb.geom IS NOT NULL
                ORDER BY sb.state_abbr
                LIMIT :limit
                """
            ),
            params | {"limit": limit, "simplify_degrees": STATE_SIMPLIFY_DEGREES},
        ).mappings().all()
        return [dict(row) for row in rows]

    bbox_clause = ""
    bbox_params: dict[str, Any] = {}
    if bbox:
        try:
            west, south, east, north = (float(part.strip()) for part in str(bbox).split(","))
            if west < east and south < north:
                bbox_clause = "AND boundary.geom && ST_MakeEnvelope(:west, :south, :east, :north, 4326)"
                bbox_params = {"west": west, "south": south, "east": east, "north": north}
        except ValueError:
            bbox_clause = ""
            bbox_params = {}
    geometry_expr = (
        "ST_AsGeoJSON(ST_SimplifyPreserveTopology(boundary.geom, :simplify_degrees), 6)::json AS geometry"
        if include_geometry
        else "NULL::json AS geometry"
    )
    rows = db.execute(
        text(
            f"""
            {cte_sql},
            grouped AS (
                SELECT
                    county_fips,
                    MIN(state_code) AS state_code,
                    COALESCE(SUM(obligation_amount), 0)::numeric AS total_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'assistance'), 0)::numeric
                        AS assistance_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'contracts'), 0)::numeric
                        AS contracts_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'unlinked'), 0)::numeric
                        AS unlinked_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE review_status IN ('candidate', 'needs_review')), 0)::numeric
                        AS needs_review_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE review_status NOT IN ('candidate', 'needs_review')), 0)::numeric
                        AS reviewed_obligations,
                    COUNT(DISTINCT award_key)::bigint AS award_count,
                    COUNT(DISTINCT award_key) FILTER (WHERE review_status IN ('candidate', 'needs_review'))::bigint
                        AS needs_review_award_count,
                    COUNT(DISTINCT normalized_account_key)::bigint AS included_account_count,
                    COUNT(DISTINCT normalized_account_key) FILTER (WHERE review_status IN ('candidate', 'needs_review'))::bigint
                        AS needs_review_account_count
                FROM filtered_awards
                WHERE county_fips IS NOT NULL AND county_fips <> ''
                GROUP BY county_fips
            ),
            national_total AS (
                SELECT COALESCE(SUM(total_obligations), 0)::numeric AS national_total
                FROM grouped
            )
            SELECT
                boundary.geoid AS geography_id,
                COALESCE(county.county_name, boundary.name) AS geography_name,
                county.state_abbr AS state_code,
                county.state_desc AS state_name,
                m.total_obligations,
                m.assistance_obligations,
                m.contracts_obligations,
                m.unlinked_obligations,
                m.needs_review_obligations,
                m.reviewed_obligations,
                m.award_count,
                m.needs_review_award_count,
                m.included_account_count,
                m.needs_review_account_count,
                pop.population::numeric AS population,
                national_total.national_total,
                {geometry_expr}
            FROM {COUNTY_BOUNDARY_TABLE} AS boundary
            LEFT JOIN {COUNTY_DIM_TABLE} AS county
              ON county.location_id = boundary.location_id
            LEFT JOIN grouped AS m
              ON m.county_fips = boundary.geoid
            LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
              ON pop.geography_type = 'county'
             AND pop.geography_id = boundary.geoid
            CROSS JOIN national_total
            WHERE boundary.geom IS NOT NULL
            {bbox_clause}
            ORDER BY boundary.geoid
            LIMIT :limit
            """
        ),
        params | bbox_params | {"limit": limit, "simplify_degrees": COUNTY_SIMPLIFY_DEGREES},
    ).mappings().all()
    return [dict(row) for row in rows]


def _feature_properties(row: dict[str, Any], filters: ChipV1Filters, *, metadata: dict[str, Any]) -> dict[str, Any]:
    total = _json_number(row.get("total_obligations"))
    population = _json_number(row.get("population"))
    national_total = _json_number(row.get("national_total"))
    value = _metric_value(filters.metric, total_amount=total, population=population, national_total=national_total)
    geography_id = str(row.get("geography_id") or "")
    geography_name = str(row.get("geography_name") or geography_id)
    state_code = str(row.get("state_code") or "").strip() or None
    profile = _profile_payload(
        filters=filters,
        geography_type=filters.geography_level,
        geography_id=geography_id,
        geography_name=geography_name,
        state_code=state_code,
        total_amount=total,
        population=population,
        national_total=national_total,
        award_count=row.get("award_count"),
        assistance_obligations=row.get("assistance_obligations"),
        contracts_obligations=row.get("contracts_obligations"),
        unlinked_obligations=row.get("unlinked_obligations"),
        needs_review_obligations=row.get("needs_review_obligations"),
        reviewed_obligations=row.get("reviewed_obligations"),
        included_account_count=row.get("included_account_count"),
        needs_review_account_count=row.get("needs_review_account_count"),
        metadata={"metric_context": _filter_context(filters), **metadata},
    )
    return {
        "id": geography_id,
        "name": geography_name,
        "state_code": state_code,
        "state_abbr": state_code,
        "state_name": row.get("state_name"),
        "geo_level": filters.geography_level,
        "metric": filters.metric,
        "metric_label": VALID_METRICS[filters.metric],
        "value": value,
        "total_funding_amount": total,
        "funding_per_capita": profile["funding_per_capita"],
        "funding_per_100k": profile["funding_per_100k"],
        "share_national_pct": profile["national_share"],
        "population": population,
        "award_count": int(row.get("award_count") or 0),
        "needs_review_obligations": _json_number(row.get("needs_review_obligations")) or 0.0,
        "reviewed_obligations": _json_number(row.get("reviewed_obligations")) or 0.0,
        "needs_review_award_count": int(row.get("needs_review_award_count") or 0),
        "included_account_count": int(row.get("included_account_count") or 0),
        "needs_review_account_count": int(row.get("needs_review_account_count") or 0),
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "funding_model": FUNDING_MODEL_KEY,
        "funding_model_label": FUNDING_MODEL_LABEL,
        "classification_version": filters.classification_version,
        "funding_profile": profile,
        "metric_context": _filter_context(filters),
    }


def _base_meta(db: Session, filters: ChipV1Filters, *, geography_level: str | None = None) -> dict[str, Any]:
    level = geography_level or filters.geography_level
    metadata = _metadata_payload(db, filters, geography_level=level)
    national = _national_totals(db, filters)
    national_profile = _profile_payload(
        filters=filters,
        geography_type="national",
        geography_id="US",
        geography_name="United States",
        state_code=None,
        total_amount=national.get("total_obligations"),
        population=national.get("population"),
        national_total=national.get("total_obligations"),
        award_count=national.get("award_count"),
        assistance_obligations=national.get("assistance_obligations"),
        contracts_obligations=national.get("contracts_obligations"),
        unlinked_obligations=national.get("unlinked_obligations"),
        needs_review_obligations=national.get("needs_review_obligations"),
        reviewed_obligations=national.get("reviewed_obligations"),
        included_account_count=metadata.get("included_account_count"),
        needs_review_account_count=metadata.get("pending_review_account_count"),
        metadata={"metric_context": _filter_context(filters, geography_level="national"), **metadata},
    )
    note_parts = [
        LEGEND_DESCRIPTION,
        "Scope includes all available fiscal years." if filters.fiscal_year is None else None,
        "Scope includes all award types." if filters.award_type == "all_award_types" else None,
        (
            "TAGGS-only scope is not available in CHIP Account Classification v1; totals are empty."
            if filters.data_source_scope == "taggs_only"
            else None
        ),
        (
            "Current source is USAspending-backed; TAGGS enrichment is not yet blended into this CHIP v1 fact table."
            if filters.data_source_scope == "combined"
            else None
        ),
        PENDING_REVIEW_NOTE if metadata["includes_pending_review"] else None,
    ]
    return {
        "note": " ".join(part for part in note_parts if part),
        "description": LEGEND_DESCRIPTION,
        "legend_title": _legend_title(filters),
        "filter_context": _filter_context(filters, geography_level=level),
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_requested_label": FUNDING_MODEL_LABEL,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "funding_model": FUNDING_MODEL_KEY,
        "funding_model_label": FUNDING_MODEL_LABEL,
        "classification_version": filters.classification_version,
        "includes_pending_review": metadata["includes_pending_review"],
        "pending_review_total": metadata["pending_review_total"],
        "pending_review_account_count": metadata["pending_review_account_count"],
        "pending_review_award_count": metadata["pending_review_award_count"],
        "unmapped_award_total": metadata["unmapped_award_total"],
        "last_refreshed_at": metadata["last_refreshed_at"],
        "legacy_available": True,
        "mapped_total": metadata["mapped_total"],
        "mapped_row_count": metadata["mapped_row_count"],
        "national_summary": {
            "funding_profile": national_profile,
            "funding_mode_requested": FUNDING_MODEL_KEY,
            "funding_mode_effective": FUNDING_MODEL_KEY,
            "funding_mode_label": FUNDING_MODEL_LABEL,
            "total_funding_amount": national_profile["total_funding"],
            "funding_per_capita": national_profile["funding_per_capita"],
            "funding_per_100k": national_profile["funding_per_100k"],
            "share_national_pct": national_profile["national_share"],
            "population": national_profile["population"],
            "pending_review_total": metadata["pending_review_total"],
            "pending_review_account_count": metadata["pending_review_account_count"],
            "pending_review_award_count": metadata["pending_review_award_count"],
        },
    }


def fetch_map_geojson(
    db: Session,
    *,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    geography_level: str | None = None,
    time_aggregation: str | None = None,
    classification_version: str | None = None,
    funding_scope_preset: str | None = None,
    award_type: str | None = None,
    emergency_supplemental_scope: str | None = None,
    review_status: str | None = None,
    include_pphf: Any = None,
    transfers_scope: str | None = None,
    data_source_scope: str | None = None,
    bbox: str | None = None,
    limit: int = 6000,
    **_: Any,
) -> dict[str, Any]:
    del funding_type, time_aggregation
    _ensure_required_views(db)
    filters = _normalize_filters(
        db,
        fiscal_year=fiscal_year,
        metric=metric,
        geography_level=geography_level,
        classification_version=classification_version,
        funding_scope_preset=funding_scope_preset,
        award_type=award_type,
        emergency_supplemental_scope=emergency_supplemental_scope,
        review_status=review_status,
        include_pphf=include_pphf,
        transfers_scope=transfers_scope,
        data_source_scope=data_source_scope,
    )
    if filters.geography_level == "national":
        meta = _base_meta(db, filters, geography_level="national")
        profile = meta["national_summary"]["funding_profile"]
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": None,
                    "properties": {
                        "id": "US",
                        "name": "United States",
                        "geo_level": "national",
                        "metric": filters.metric,
                        "metric_label": VALID_METRICS[filters.metric],
                        "value": profile["metric_value"],
                        "total_funding_amount": profile["total_funding"],
                        "funding_per_capita": profile["funding_per_capita"],
                        "funding_per_100k": profile["funding_per_100k"],
                        "share_national_pct": profile["national_share"],
                        "population": profile["population"],
                        "funding_mode_effective": FUNDING_MODEL_KEY,
                        "funding_mode_label": FUNDING_MODEL_LABEL,
                        "funding_profile": profile,
                        "metric_context": _filter_context(filters, geography_level="national"),
                    },
                }
            ],
            "meta": meta | {"mapped_geographies": 1 if profile["metric_value"] is not None else 0, "no_data_count": 0},
        }
    rows = _fetch_geography_rows(
        db,
        filters,
        bbox=bbox,
        limit=max(1, int(limit)),
        include_geometry=True,
    )
    metadata = _metadata_payload(db, filters)
    features = [
        {
            "type": "Feature",
            "geometry": row.get("geometry"),
            "properties": _feature_properties(row, filters, metadata=metadata),
        }
        for row in rows
    ]
    mapped_geographies = sum(1 for feature in features if feature.get("properties", {}).get("value") is not None)
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": _base_meta(db, filters)
        | {
            "mapped_geographies": mapped_geographies,
            "no_data_count": max(len(features) - mapped_geographies, 0),
        },
    }


def fetch_legend_stats(
    db: Session,
    *,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    geography_level: str | None = None,
    time_aggregation: str | None = None,
    classification_version: str | None = None,
    funding_scope_preset: str | None = None,
    award_type: str | None = None,
    emergency_supplemental_scope: str | None = None,
    review_status: str | None = None,
    include_pphf: Any = None,
    transfers_scope: str | None = None,
    data_source_scope: str | None = None,
    bbox: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    del funding_type, time_aggregation
    _ensure_required_views(db)
    filters = _normalize_filters(
        db,
        fiscal_year=fiscal_year,
        metric=metric,
        geography_level=geography_level,
        classification_version=classification_version,
        funding_scope_preset=funding_scope_preset,
        award_type=award_type,
        emergency_supplemental_scope=emergency_supplemental_scope,
        review_status=review_status,
        include_pphf=include_pphf,
        transfers_scope=transfers_scope,
        data_source_scope=data_source_scope,
    )
    if filters.geography_level == "national":
        payload = fetch_map_geojson(
            db,
            fiscal_year=filters.fiscal_year,
            metric=filters.metric,
            geography_level="national",
            classification_version=filters.classification_version,
            funding_scope_preset=filters.funding_scope_preset,
            award_type=filters.award_type,
            emergency_supplemental_scope=filters.emergency_supplemental_scope,
            review_status=filters.review_status,
            include_pphf=filters.include_pphf,
            transfers_scope=filters.transfers_scope,
            data_source_scope=filters.data_source_scope,
        )
        values = [
            float(feature["properties"]["value"])
            for feature in payload["features"]
            if feature["properties"].get("value") is not None
        ]
        row_count = len(payload["features"])
    else:
        rows = _fetch_geography_rows(
            db,
            filters,
            bbox=bbox,
            limit=7000,
            include_geometry=False,
        )
        values = []
        for row in rows:
            value = _metric_value(
                filters.metric,
                total_amount=row.get("total_obligations"),
                population=row.get("population"),
                national_total=row.get("national_total"),
            )
            if value is not None and math.isfinite(float(value)):
                values.append(float(value))
        row_count = len(rows)
    meta = _base_meta(db, filters)
    return {
        "metric": filters.metric,
        "metric_label": VALID_METRICS[filters.metric],
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_requested_label": FUNDING_MODEL_LABEL,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "funding_model": FUNDING_MODEL_KEY,
        "funding_model_label": FUNDING_MODEL_LABEL,
        "classification_version": filters.classification_version,
        "geography_level": filters.geography_level,
        "time_aggregation": "single_fiscal_year",
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "bins": _compute_bins(values),
        "mapped_geographies": len(values),
        "n": len(values),
        "noDataCount": max(row_count - len(values), 0),
        "total_visible_dollars": meta.get("mapped_total"),
        "legend_title": meta["legend_title"],
        "description": meta["description"],
        "filter_context": meta["filter_context"],
        "note": meta["note"],
        "national_summary": meta["national_summary"],
        "includes_pending_review": meta["includes_pending_review"],
        "pending_review_total": meta["pending_review_total"],
        "pending_review_account_count": meta["pending_review_account_count"],
        "pending_review_award_count": meta["pending_review_award_count"],
        "unmapped_award_total": meta["unmapped_award_total"],
        "last_refreshed_at": meta["last_refreshed_at"],
        "legacy_available": True,
    }


def fetch_national_summary(
    db: Session,
    *,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    time_aggregation: str | None = None,
    classification_version: str | None = None,
    funding_scope_preset: str | None = None,
    award_type: str | None = None,
    emergency_supplemental_scope: str | None = None,
    review_status: str | None = None,
    include_pphf: Any = None,
    transfers_scope: str | None = None,
    data_source_scope: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    del funding_type, time_aggregation
    _ensure_required_views(db)
    filters = _normalize_filters(
        db,
        fiscal_year=fiscal_year,
        metric=metric,
        geography_level="national",
        classification_version=classification_version,
        funding_scope_preset=funding_scope_preset,
        award_type=award_type,
        emergency_supplemental_scope=emergency_supplemental_scope,
        review_status=review_status,
        include_pphf=include_pphf,
        transfers_scope=transfers_scope,
        data_source_scope=data_source_scope,
    )
    meta = _base_meta(db, filters, geography_level="national")
    profile = meta["national_summary"]["funding_profile"]
    return {
        "profile": profile,
        "summary": {
            "funding_mode_requested": FUNDING_MODEL_KEY,
            "funding_mode_effective": FUNDING_MODEL_KEY,
            "funding_mode_label": FUNDING_MODEL_LABEL,
            "funding_model": FUNDING_MODEL_KEY,
            "funding_model_label": FUNDING_MODEL_LABEL,
            "classification_version": filters.classification_version,
            "total_funding_amount": profile["total_funding"],
            "total_funding": profile["total_funding"],
            "funding_per_capita": profile["funding_per_capita"],
            "funding_per_100k": profile["funding_per_100k"],
            "share_national_pct": profile["national_share"],
            "population": profile["population"],
            "award_count": profile["award_count"],
            "pending_review_total": meta["pending_review_total"],
            "pending_review_account_count": meta["pending_review_account_count"],
            "pending_review_award_count": meta["pending_review_award_count"],
        },
        "legend_title": meta["legend_title"],
        "filter_context": meta["filter_context"],
        "note": meta["note"],
    }


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
    return str(row.get("state_name") or state_code) if row else state_code


def _state_profile_row(db: Session, filters: ChipV1Filters, *, state_code: str) -> dict[str, Any]:
    cte_sql, params = _filtered_awards_sql(filters)
    row = db.execute(
        text(
            f"""
            {cte_sql},
            grouped AS (
                SELECT
                    state_code,
                    COALESCE(SUM(obligation_amount), 0)::numeric AS total_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'assistance'), 0)::numeric
                        AS assistance_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'contracts'), 0)::numeric
                        AS contracts_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE award_source_type = 'unlinked'), 0)::numeric
                        AS unlinked_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE review_status IN ('candidate', 'needs_review')), 0)::numeric
                        AS needs_review_obligations,
                    COALESCE(SUM(obligation_amount) FILTER (WHERE review_status NOT IN ('candidate', 'needs_review')), 0)::numeric
                        AS reviewed_obligations,
                    COUNT(DISTINCT award_key)::bigint AS award_count,
                    COUNT(DISTINCT award_key) FILTER (WHERE review_status IN ('candidate', 'needs_review'))::bigint
                        AS needs_review_award_count,
                    COUNT(DISTINCT normalized_account_key)::bigint AS included_account_count,
                    COUNT(DISTINCT normalized_account_key) FILTER (WHERE review_status IN ('candidate', 'needs_review'))::bigint
                        AS needs_review_account_count
                FROM filtered_awards
                WHERE state_code IS NOT NULL AND state_code <> ''
                GROUP BY state_code
            ),
            national_total AS (
                SELECT COALESCE(SUM(total_obligations), 0)::numeric AS national_total
                FROM grouped
            )
            SELECT
                m.*,
                pop.population::numeric AS population,
                national_total.national_total
            FROM grouped AS m
            LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
              ON pop.geography_type = 'state'
             AND pop.geography_id = m.state_code
            CROSS JOIN national_total
            WHERE m.state_code = :state_code
            LIMIT 1
            """
        ),
        params | {"state_code": state_code},
    ).mappings().one_or_none()
    return dict(row) if row else {}


def _category_rows_from_state(row: dict[str, Any]) -> list[dict[str, Any]]:
    total = _json_number(row.get("total_obligations")) or 0.0
    categories = [
        ("assistance", "Assistance awards", row.get("assistance_obligations")),
        ("contracts", "Contracts", row.get("contracts_obligations")),
        ("unlinked", "Unlinked award rows", row.get("unlinked_obligations")),
    ]
    output: list[dict[str, Any]] = []
    for key, label, amount_value in categories:
        amount = _json_number(amount_value) or 0.0
        if amount == 0:
            continue
        output.append(
            {
                "category_value": key,
                "category": label,
                "amount": amount,
                "chip_total_funding": amount,
                "share_pct": (amount / total) * 100 if total else 0,
                "award_count": int(row.get("award_count") or 0) if key != "unlinked" else int(row.get("award_count") or 0),
                "subcategory_count": 1,
            }
        )
    return sorted(output, key=lambda item: (-float(item["amount"]), str(item["category"])))


def _subcategory_rows_from_state(row: dict[str, Any]) -> list[dict[str, Any]]:
    total = _json_number(row.get("total_obligations")) or 0.0
    pending = _json_number(row.get("needs_review_obligations")) or 0.0
    reviewed = _json_number(row.get("reviewed_obligations")) or 0.0
    rows = [
        ("reviewed", "Review status", "Reviewed accounts", reviewed, int(row.get("award_count") or 0)),
        (
            "needs_review",
            "Review status",
            "Accounts pending final review",
            pending,
            int(row.get("needs_review_award_count") or 0),
        ),
    ]
    return [
        {
            "category_value": key,
            "category": category,
            "subcategory": label,
            "amount": amount,
            "chip_total_funding": amount,
            "share_total_pct": (amount / total) * 100 if total else 0,
            "share_category_pct": (amount / total) * 100 if total else 0,
            "award_count": award_count,
        }
        for key, category, label, amount, award_count in rows
        if amount
    ]


def fetch_state_profile_overview(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    time_aggregation: str | None = None,
    classification_version: str | None = None,
    funding_scope_preset: str | None = None,
    award_type: str | None = None,
    emergency_supplemental_scope: str | None = None,
    review_status: str | None = None,
    include_pphf: Any = None,
    transfers_scope: str | None = None,
    data_source_scope: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    del funding_type, time_aggregation
    state_code = str(state or "").strip().upper()
    if len(state_code) != 2:
        raise HTTPException(status_code=400, detail="state must be a valid 2-letter state code")
    _ensure_required_views(db)
    filters = _normalize_filters(
        db,
        fiscal_year=fiscal_year,
        metric=metric,
        geography_level="state",
        classification_version=classification_version,
        funding_scope_preset=funding_scope_preset,
        award_type=award_type,
        emergency_supplemental_scope=emergency_supplemental_scope,
        review_status=review_status,
        include_pphf=include_pphf,
        transfers_scope=transfers_scope,
        data_source_scope=data_source_scope,
    )
    metadata = _metadata_payload(db, filters)
    row = _state_profile_row(db, filters, state_code=state_code)
    state_name = _state_name(db, state_code)
    profile = _profile_payload(
        filters=filters,
        geography_type="state",
        geography_id=state_code,
        geography_name=state_name,
        state_code=state_code,
        total_amount=row.get("total_obligations"),
        population=row.get("population"),
        national_total=row.get("national_total"),
        award_count=row.get("award_count"),
        assistance_obligations=row.get("assistance_obligations"),
        contracts_obligations=row.get("contracts_obligations"),
        unlinked_obligations=row.get("unlinked_obligations"),
        needs_review_obligations=row.get("needs_review_obligations"),
        reviewed_obligations=row.get("reviewed_obligations"),
        included_account_count=row.get("included_account_count"),
        needs_review_account_count=row.get("needs_review_account_count"),
        metadata={"metric_context": _filter_context(filters), **metadata},
    )
    categories = {
        "state_code": state_code,
        "profile": profile,
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "rows": _category_rows_from_state(row),
        "grouping": {"category_label": "Funding Source", "subcategory_label": "Review Status"},
    }
    subcategories = {
        "state_code": state_code,
        "profile": profile,
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "rows": _subcategory_rows_from_state(row),
        "grouping": {"category_label": "Review Status", "subcategory_label": "Account Review State"},
    }
    summary = {
        "state_code": state_code,
        "state_name": state_name,
        "fiscal_year": filters.fiscal_year,
        "time_aggregation": "single_fiscal_year",
        "timeframe_label": _timeframe_label(filters),
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "funding_model": FUNDING_MODEL_KEY,
        "funding_model_label": FUNDING_MODEL_LABEL,
        "classification_version": filters.classification_version,
        "selected_metric": filters.metric,
        "selected_metric_label": VALID_METRICS[filters.metric],
        "selected_metric_value": profile["metric_value"],
        "profile": profile,
        "total_funding": profile["total_funding"],
        "funding_per_capita": profile["funding_per_capita"],
        "funding_per_100k": profile["funding_per_100k"],
        "share_national_pct": profile["national_share"],
        "population": profile["population"],
        "awards_amount": profile["assistance_obligations"],
        "contracts_amount": profile["contracts_obligations"],
        "subawards_amount": 0,
        "award_count": profile["award_count"],
        "contract_award_count": 0,
        "pending_review_total": profile["needs_review_obligations"],
        "pending_review_account_count": profile["needs_review_account_count"],
        "pending_review_award_count": int(row.get("needs_review_award_count") or 0),
        "includes_pending_review": bool((profile["needs_review_obligations"] or 0) > 0),
        "legend_title": _legend_title(filters),
        "filter_context": _filter_context(filters),
        "grouping": {
            "category_label": "Funding Source",
            "subcategory_label": "Review Status",
            "category_method": "Funding source groups come from award-linked USAspending account breakdown rows.",
            "subcategory_method": "Pending-review rows are separated from reviewed rows in the account-classified model metadata.",
        },
        "methodology_notes": [
            LEGEND_DESCRIPTION,
            PENDING_REVIEW_NOTE if metadata["includes_pending_review"] else None,
            "Profile totals use the same CHIP Account Classification v1 summary views as the map.",
        ],
        "funding_model_version": MODEL_VERSION,
        "latest_action_date_max": metadata.get("last_refreshed_at"),
    }
    summary["methodology_notes"] = [note for note in summary["methodology_notes"] if note]
    return {"summary": summary, "categories": categories, "subcategories": subcategories}


def fetch_state_profile_summary(db: Session, **kwargs: Any) -> dict[str, Any]:
    return fetch_state_profile_overview(db, **kwargs)["summary"]


def fetch_state_profile_categories(db: Session, **kwargs: Any) -> dict[str, Any]:
    return fetch_state_profile_overview(db, metric="total_funding", **kwargs)["categories"]


def fetch_state_profile_subcategories(db: Session, **kwargs: Any) -> dict[str, Any]:
    return fetch_state_profile_overview(db, metric="total_funding", **kwargs)["subcategories"]


def _classified_award_source_sql() -> str:
    return f"""
        WITH classified_awards AS (
            SELECT
                award.id AS award_row_id,
                award.fiscal_year,
                award.award_source_type,
                COALESCE(award.generated_unique_award_id, award.award_id, award.fain, award.piid, award.uri, award.id::text) AS award_key,
                award.generated_unique_award_id,
                award.award_id,
                award.piid,
                award.fain,
                award.uri,
                award.recipient_name,
                award.recipient_state_code,
                award.recipient_county_name,
                award.recipient_county_fips,
                award.place_of_performance_state_code,
                award.place_of_performance_county_name,
                award.place_of_performance_county_fips,
                award.action_date,
                award.cfda_title,
                award.award_description,
                COALESCE(award.obligation_amount, award.transaction_obligated_amount, 0)::numeric AS obligation_amount,
                classification.normalized_account_key,
                classification.federal_account_name,
                classification.cdc_scope_category,
                classification.funding_scope,
                classification.review_status,
                classification.classification_version,
                COALESCE(
                    NULLIF(UPPER(BTRIM(award.place_of_performance_state_code)), ''),
                    NULLIF(UPPER(BTRIM(award.recipient_state_code)), '')
                ) AS state_code,
                COALESCE(
                    CASE
                        WHEN regexp_replace(COALESCE(award.place_of_performance_county_fips, ''), '[^0-9]', '', 'g') ~ '^[0-9]{{1,5}}$'
                            THEN LPAD(regexp_replace(COALESCE(award.place_of_performance_county_fips, ''), '[^0-9]', '', 'g'), 5, '0')
                        ELSE NULL
                    END,
                    CASE
                        WHEN regexp_replace(COALESCE(award.recipient_county_fips, ''), '[^0-9]', '', 'g') ~ '^[0-9]{{1,5}}$'
                            THEN LPAD(regexp_replace(COALESCE(award.recipient_county_fips, ''), '[^0-9]', '', 'g'), 5, '0')
                        ELSE NULL
                    END
                ) AS county_fips
            FROM {AWARD_FACT_TABLE} AS award
            LEFT JOIN {DIM_ACCOUNT_TABLE} AS dim
              ON dim.id = award.federal_account_id
            JOIN {CLASSIFICATION_TABLE} AS classification
             ON classification.fiscal_year = award.fiscal_year
             AND (
                    classification.normalized_account_key = dim.normalized_account_key
                 OR (
                        classification.federal_account_id IS NOT NULL
                    AND classification.federal_account_id = award.federal_account_id
                 )
             )
            WHERE classification.is_cdc_related IS TRUE
              AND classification.review_status IS DISTINCT FROM 'rejected'
              AND (
                    classification.include_in_public_map IS TRUE
                 OR classification.include_in_chip_baseline IS TRUE
              )
              AND award.award_source_type IN ('assistance', 'contracts', 'unlinked')
        )
    """


def fetch_state_profile_details(
    db: Session,
    *,
    state: str,
    fiscal_year: int | None = None,
    funding_type: str | None = None,
    classification_version: str | None = None,
    funding_scope_preset: str | None = None,
    award_type: str | None = None,
    emergency_supplemental_scope: str | None = None,
    review_status: str | None = None,
    include_pphf: Any = None,
    transfers_scope: str | None = None,
    data_source_scope: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "amount",
    sort_dir: str = "desc",
    **_: Any,
) -> dict[str, Any]:
    del funding_type
    state_code = str(state or "").strip().upper()
    if len(state_code) != 2:
        raise HTTPException(status_code=400, detail="state must be a valid 2-letter state code")
    _ensure_required_views(db)
    filters = _normalize_filters(
        db,
        fiscal_year=fiscal_year,
        metric="total_funding",
        geography_level="state",
        classification_version=classification_version,
        funding_scope_preset=funding_scope_preset,
        award_type=award_type,
        emergency_supplemental_scope=emergency_supplemental_scope,
        review_status=review_status,
        include_pphf=include_pphf,
        transfers_scope=transfers_scope,
        data_source_scope=data_source_scope,
    )
    page_number = max(1, int(page))
    page_size_number = min(200, max(1, int(page_size)))
    offset = (page_number - 1) * page_size_number
    sort_columns = {
        "amount": "obligation_amount",
        "category": "cdc_scope_category",
        "subcategory": "federal_account_name",
        "grantee_name": "recipient_name",
        "latest_action_date": "action_date",
    }
    sort_column = sort_columns.get(str(sort_by or "amount").strip(), "obligation_amount")
    direction = "ASC" if str(sort_dir or "").strip().lower() == "asc" else "DESC"
    search_token = " ".join(str(q or "").strip().split())
    search_clause = ""
    params: dict[str, Any] = {
        "state_code": state_code,
        "classification_version": filters.classification_version,
        "limit": page_size_number,
        "offset": offset,
        "fiscal_year": filters.fiscal_year,
        "fiscal_year_is_null": filters.fiscal_year is None,
    }
    if search_token:
        search_clause = """
          AND (
                recipient_name ILIKE :search
             OR award_description ILIKE :search
             OR federal_account_name ILIKE :search
             OR normalized_account_key ILIKE :search
             OR fain ILIKE :search
             OR piid ILIKE :search
          )
        """
        params["search"] = f"%{search_token}%"
    cte_sql, scope_params = _filtered_awards_sql(filters)
    params |= scope_params
    rows = db.execute(
        text(
            f"""
            {cte_sql},
            filtered AS (
                SELECT *
                FROM filtered_awards
                WHERE classification_version = :classification_version
                  AND state_code = :state_code
                  {search_clause}
            )
            SELECT
                *,
                COUNT(*) OVER()::integer AS total_rows
            FROM filtered
            ORDER BY {sort_column} {direction} NULLS LAST, award_row_id ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()
    total_rows = int(rows[0].get("total_rows") or 0) if rows else 0
    detail_rows = []
    for index, row in enumerate(rows, start=1):
        amount = _json_number(row.get("obligation_amount")) or 0.0
        source_type = str(row.get("award_source_type") or "award").replace("_", " ").title()
        review_status = str(row.get("review_status") or "").replace("_", " ").title()
        detail_rows.append(
            {
                "line_number": offset + index,
                "record_id": f"chip-v1-{row.get('award_row_id')}",
                "record_type": source_type,
                "category": str(row.get("cdc_scope_category") or "CDC account").replace("_", " ").title(),
                "category_value": row.get("cdc_scope_category"),
                "subcategory": row.get("federal_account_name") or row.get("normalized_account_key"),
                "project_title": row.get("award_description") or row.get("cfda_title"),
                "grantee_name": row.get("recipient_name") or "Recipient not available",
                "amount": amount,
                "latest_action_date": _serialize_value(row.get("action_date")),
                "city": None,
                "county": row.get("place_of_performance_county_name") or row.get("recipient_county_name"),
                "state_code": row.get("state_code"),
                "county_fips": row.get("county_fips"),
                "fain": row.get("fain") or row.get("piid") or row.get("generated_unique_award_id"),
                "review_status": row.get("review_status"),
                "review_status_label": review_status,
                "usaspending_permalink": None,
            }
        )
    return {
        "state_code": state_code,
        "funding_mode_requested": FUNDING_MODEL_KEY,
        "funding_mode_effective": FUNDING_MODEL_KEY,
        "funding_mode_label": FUNDING_MODEL_LABEL,
        "funding_model": FUNDING_MODEL_KEY,
        "funding_model_label": FUNDING_MODEL_LABEL,
        "classification_version": filters.classification_version,
        "filter_context": _filter_context(filters),
        "rows": detail_rows,
        "total_rows": total_rows,
        "page": page_number,
        "page_size": page_size_number,
        "sort_by": sort_by,
        "sort_dir": direction.lower(),
        "q": search_token,
    }


def relabel_legacy_payload(payload: Any) -> Any:
    cloned = copy.deepcopy(payload)

    def _walk(value: Any) -> Any:
        if isinstance(value, list):
            return [_walk(item) for item in value]
        if not isinstance(value, dict):
            return value
        output: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"funding_mode_requested", "funding_mode_effective", "funding_model"}:
                output[key] = LEGACY_FUNDING_MODEL_KEY
            elif key in {"funding_mode_requested_label", "funding_mode_label", "funding_model_label"}:
                output[key] = LEGACY_FUNDING_MODEL_LABEL
            else:
                output[key] = _walk(item)
        return output

    relabeled = _walk(cloned)
    if isinstance(relabeled, dict):
        relabeled.setdefault("legacy_available", True)
        meta = relabeled.get("meta")
        if isinstance(meta, dict):
            meta.setdefault("legacy_available", True)
    return relabeled
