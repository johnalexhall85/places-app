from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import cdc_funding_table
from app.funding.state_lookup import normalize_state

FundingMechanism = Literal["grants_cooperative_agreements", "contracts", "all"]
Metric = Literal["total_obligations"]

DEFAULT_FUNDING_MECHANISM = "grants_cooperative_agreements"
DEFAULT_FUNDING_VIEW_MODE = "standard_usaspending"
FUNDING_VIEW_MODES = {
    "standard_usaspending": "USAspending Obligations",
    "funding_profiles_comparable": "CDC Funding Profiles Comparable",
}
SUPPLEMENTAL_HISTORY_FILTERS = {
    "all",
    "only_awards_with_supplemental_history",
    "exclude_awards_with_supplemental_history",
}
STATE_AGGREGATE = cdc_funding_table("mv_cdc_funding_map_state_all_positive")
COUNTY_AGGREGATE = cdc_funding_table("mv_cdc_funding_map_county")
FACT_TABLE = cdc_funding_table("fact_cdc_funding_prime_transaction")


def _comparable_exclusion_predicate(prefix: str = "") -> str:
    column = lambda name: f"{prefix}.{name}" if prefix else name
    return (
        f"COALESCE({column('funding_profiles_comparison_excluded')}, false) IS FALSE "
        f"AND NOT ({column('source_fiscal_year')} = 2021 "
        f"AND COALESCE({column('is_covid_era_immunization_response')}, false) IS TRUE)"
    )


def _json_number(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: _json_number(value) for key, value in dict(row).items()}


def parse_fiscal_years(value: str | int | None) -> list[int] | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return [value]
    years: list[int] = []
    for token in str(value).split(","):
        stripped = token.strip()
        if not stripped:
            continue
        try:
            year = int(stripped)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid fiscal_year: {stripped!r}") from exc
        if year < 2000 or year > 2100:
            raise HTTPException(status_code=422, detail=f"Invalid fiscal_year: {year}")
        years.append(year)
    return years or None


def latest_fiscal_year(db: Session) -> int:
    value = db.execute(text(f"SELECT MAX(source_fiscal_year) FROM {STATE_AGGREGATE}")).scalar()
    if value is None:
        raise HTTPException(status_code=404, detail="No CDC funding state aggregate rows are available.")
    return int(value)


def resolve_filters(
    db: Session,
    *,
    fiscal_year: str | int | None = None,
    funding_mechanism: str | None = None,
    include_supplemental: bool = False,
    funding_view_mode: str | None = None,
    supplemental_history_filter: str = "all",
    state: str | None = None,
    assistance_listing_number: str | None = None,
    metric: str = "total_obligations",
) -> dict[str, Any]:
    if metric != "total_obligations":
        raise HTTPException(status_code=422, detail="Only metric=total_obligations is currently supported.")
    mechanism = funding_mechanism or DEFAULT_FUNDING_MECHANISM
    if mechanism not in {"grants_cooperative_agreements", "contracts", "all"}:
        raise HTTPException(status_code=422, detail=f"Invalid funding_mechanism: {mechanism}")
    view_mode = funding_view_mode or DEFAULT_FUNDING_VIEW_MODE
    if view_mode not in FUNDING_VIEW_MODES:
        raise HTTPException(status_code=422, detail=f"Invalid funding_view_mode: {view_mode}")
    if supplemental_history_filter not in SUPPLEMENTAL_HISTORY_FILTERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid supplemental_history_filter: {supplemental_history_filter}",
        )
    years = parse_fiscal_years(fiscal_year) or [latest_fiscal_year(db)]
    state_info = normalize_state(state)
    if state is not None and state_info is None:
        raise HTTPException(status_code=422, detail=f"Invalid state: {state!r}")
    return {
        "fiscal_years": years,
        "funding_mechanism": mechanism,
        "include_supplemental": include_supplemental,
        "funding_view_mode": view_mode,
        "funding_view_mode_label": FUNDING_VIEW_MODES[view_mode],
        "supplemental_history_filter": supplemental_history_filter,
        "state": state_info.state_fips if state_info else None,
        "state_code": state_info.state_code if state_info else None,
        "assistance_listing_number": assistance_listing_number,
        "metric": metric,
    }


def _aggregate_where(filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses = ["source_fiscal_year = ANY(:fiscal_years)"]
    params: dict[str, Any] = {"fiscal_years": filters["fiscal_years"]}
    if filters["funding_mechanism"] != "all":
        clauses.append("funding_mechanism = :funding_mechanism")
        params["funding_mechanism"] = filters["funding_mechanism"]
    if filters["funding_view_mode"] == "funding_profiles_comparable":
        clauses.append(_comparable_exclusion_predicate())
    if filters["supplemental_history_filter"] == "only_awards_with_supplemental_history":
        clauses.append("COALESCE(has_overall_award_supplemental_history, false) IS TRUE")
    elif filters["supplemental_history_filter"] == "exclude_awards_with_supplemental_history":
        clauses.append("COALESCE(has_overall_award_supplemental_history, false) IS FALSE")
    if filters["state"]:
        clauses.append("state_fips = :state_fips")
        params["state_fips"] = filters["state"]
    if filters["assistance_listing_number"]:
        clauses.append("assistance_listing_number = :assistance_listing_number")
        params["assistance_listing_number"] = filters["assistance_listing_number"]
    return " AND ".join(clauses), params


FACT_STATE_EXPR = """
    CASE
        WHEN pop_state_code ~ '^[A-Za-z]{2}$' THEN pop_state_lookup.state_fips
        WHEN pop_county_fips ~ '^[0-9]{5}$' THEN LEFT(pop_county_fips, 2)
        WHEN recipient_state_code ~ '^[A-Za-z]{2}$' THEN recipient_state_lookup.state_fips
        WHEN recipient_county_fips ~ '^[0-9]{5}$' THEN LEFT(recipient_county_fips, 2)
        WHEN map_state_code ~ '^[A-Za-z]{2}$' THEN map_state_lookup.state_fips
        WHEN map_state_code ~ '^[0-9]{2}$' THEN map_state_code
        ELSE NULL
    END
"""


def _fact_state_cte() -> str:
    return f"""
        WITH state_lookup(state_fips, state_code, state_name) AS (
            SELECT * FROM (VALUES
                ('01','AL','Alabama'),('02','AK','Alaska'),('04','AZ','Arizona'),('05','AR','Arkansas'),
                ('06','CA','California'),('08','CO','Colorado'),('09','CT','Connecticut'),('10','DE','Delaware'),
                ('11','DC','District of Columbia'),('12','FL','Florida'),('13','GA','Georgia'),('15','HI','Hawaii'),
                ('16','ID','Idaho'),('17','IL','Illinois'),('18','IN','Indiana'),('19','IA','Iowa'),
                ('20','KS','Kansas'),('21','KY','Kentucky'),('22','LA','Louisiana'),('23','ME','Maine'),
                ('24','MD','Maryland'),('25','MA','Massachusetts'),('26','MI','Michigan'),('27','MN','Minnesota'),
                ('28','MS','Mississippi'),('29','MO','Missouri'),('30','MT','Montana'),('31','NE','Nebraska'),
                ('32','NV','Nevada'),('33','NH','New Hampshire'),('34','NJ','New Jersey'),('35','NM','New Mexico'),
                ('36','NY','New York'),('37','NC','North Carolina'),('38','ND','North Dakota'),('39','OH','Ohio'),
                ('40','OK','Oklahoma'),('41','OR','Oregon'),('42','PA','Pennsylvania'),('44','RI','Rhode Island'),
                ('45','SC','South Carolina'),('46','SD','South Dakota'),('47','TN','Tennessee'),('48','TX','Texas'),
                ('49','UT','Utah'),('50','VT','Vermont'),('51','VA','Virginia'),('53','WA','Washington'),
                ('54','WV','West Virginia'),('55','WI','Wisconsin'),('56','WY','Wyoming'),('60','AS','American Samoa'),
                ('66','GU','Guam'),('69','MP','Northern Mariana Islands'),('72','PR','Puerto Rico'),('78','VI','U.S. Virgin Islands')
            ) AS rows(state_fips, state_code, state_name)
        ),
        normalized_fact AS (
            SELECT
                fact.*,
                {FACT_STATE_EXPR} AS normalized_state_fips
            FROM {FACT_TABLE} AS fact
            LEFT JOIN state_lookup AS pop_state_lookup
              ON pop_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.pop_state_code), ''))
            LEFT JOIN state_lookup AS recipient_state_lookup
              ON recipient_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.recipient_state_code), ''))
            LEFT JOIN state_lookup AS map_state_lookup
              ON map_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.map_state_code), ''))
        )
    """


def _fact_where(filters: dict[str, Any], *, include_state_required: bool = True) -> tuple[str, dict[str, Any]]:
    clauses = [
        "fact.is_prime_award IS TRUE",
        "fact.is_positive_obligation IS TRUE",
        "fact.is_cdc_funded IS TRUE",
        "fact.federal_action_obligation > 0",
        "fact.source_fiscal_year = ANY(:fiscal_years)",
    ]
    params: dict[str, Any] = {"fiscal_years": filters["fiscal_years"]}
    if include_state_required:
        clauses.append("fact.normalized_state_fips IS NOT NULL")
    if filters["funding_mechanism"] != "all":
        clauses.append("fact.funding_mechanism = :funding_mechanism")
        params["funding_mechanism"] = filters["funding_mechanism"]
    if filters["funding_view_mode"] == "funding_profiles_comparable":
        clauses.append(_comparable_exclusion_predicate("fact"))
    if filters["supplemental_history_filter"] == "only_awards_with_supplemental_history":
        clauses.append("COALESCE(fact.has_overall_award_supplemental_history, false) IS TRUE")
    elif filters["supplemental_history_filter"] == "exclude_awards_with_supplemental_history":
        clauses.append("COALESCE(fact.has_overall_award_supplemental_history, false) IS FALSE")
    if filters["state"]:
        clauses.append("fact.normalized_state_fips = :state_fips")
        params["state_fips"] = filters["state"]
    if filters["assistance_listing_number"]:
        clauses.append("fact.assistance_listing_number = :assistance_listing_number")
        params["assistance_listing_number"] = filters["assistance_listing_number"]
    return " AND ".join(clauses), params


POSSIBLE_GLOBAL_OR_FOREIGN_SQL = """
    NULLIF(BTRIM(UPPER(fact.pop_country_code)), '') IS NOT NULL
        AND UPPER(fact.pop_country_code) NOT IN ('USA', 'US', 'UNITED STATES', 'UNITED STATES OF AMERICA')
    OR NULLIF(BTRIM(UPPER(fact.recipient_country_code)), '') IS NOT NULL
        AND UPPER(fact.recipient_country_code) NOT IN ('USA', 'US', 'UNITED STATES', 'UNITED STATES OF AMERICA')
    OR fact.assistance_listing_title ILIKE '%global%'
    OR fact.assistance_listing_title ILIKE '%foreign%'
    OR fact.assistance_listing_title ILIKE '%international%'
    OR fact.transaction_description ILIKE '%global%'
    OR fact.transaction_description ILIKE '%foreign%'
    OR fact.transaction_description ILIKE '%international%'
    OR fact.transaction_description ILIKE '%world health%'
    OR fact.prime_award_base_transaction_description ILIKE '%global%'
    OR fact.prime_award_base_transaction_description ILIKE '%foreign%'
    OR fact.prime_award_base_transaction_description ILIKE '%international%'
    OR fact.prime_award_base_transaction_description ILIKE '%world health%'
"""


def _fetch_unmapped_diagnostics(db: Session, filters: dict[str, Any]) -> dict[str, Any]:
    unmapped_where, unmapped_params = _fact_where(filters, include_state_required=False)
    return _row_dict(
        db.execute(
            text(
                f"""
                {_fact_state_cte()}
                SELECT
                    COALESCE(SUM(fact.federal_action_obligation), 0) AS state_unmapped_obligations,
                    COUNT(*)::bigint AS state_unmapped_transaction_count,
                    COALESCE(SUM(CASE WHEN (
                        {POSSIBLE_GLOBAL_OR_FOREIGN_SQL}
                    ) THEN fact.federal_action_obligation ELSE 0 END), 0)
                        AS possible_global_or_foreign_obligations,
                    COUNT(*) FILTER (WHERE (
                        {POSSIBLE_GLOBAL_OR_FOREIGN_SQL}
                    ))::bigint AS possible_global_or_foreign_transaction_count
                FROM normalized_fact AS fact
                WHERE {unmapped_where}
                  AND fact.normalized_state_fips IS NULL
                """
            ),
            unmapped_params,
        ).mappings().first()
        or {}
    )


def _summary_with_unmapped_fields(
    summary: dict[str, Any],
    unmapped_diagnostics: dict[str, Any],
    *,
    use_national_total: bool = False,
) -> dict[str, Any]:
    state_mapped_obligations = summary.get("total_obligations") or 0
    state_unmapped_obligations = unmapped_diagnostics.get("state_unmapped_obligations") or 0
    total_obligations_including_unmapped = state_mapped_obligations + state_unmapped_obligations
    return {
        **summary,
        **unmapped_diagnostics,
        "total_obligations": (
            total_obligations_including_unmapped
            if use_national_total
            else state_mapped_obligations
        ),
        "state_mapped_obligations": state_mapped_obligations,
        "total_obligations_including_unmapped": total_obligations_including_unmapped,
        "vfc_immunization_cooperative_agreement_obligations": summary.get("likely_vfc_obligations") or 0,
        "vaccine_purchase_obligations": None,
    }


def fetch_filters(db: Session) -> dict[str, Any]:
    latest_year = latest_fiscal_year(db)
    default_filters = resolve_filters(
        db,
        fiscal_year=latest_year,
        funding_mechanism=DEFAULT_FUNDING_MECHANISM,
        include_supplemental=False,
    )
    where_sql, params = _aggregate_where(default_filters)
    fiscal_years = [
        int(row["source_fiscal_year"])
        for row in db.execute(
            text(f"SELECT DISTINCT source_fiscal_year FROM {STATE_AGGREGATE} ORDER BY source_fiscal_year DESC")
        ).mappings().all()
    ]
    states = [
        _row_dict(row)
        for row in db.execute(
            text(
                f"""
                SELECT state_fips, state_code, state_name
                FROM {STATE_AGGREGATE}
                WHERE {where_sql}
                GROUP BY state_fips, state_code, state_name
                ORDER BY state_code
                """
            ),
            params,
        ).mappings().all()
    ]
    assistance_listings = [
        _row_dict(row)
        for row in db.execute(
            text(
                f"""
                SELECT
                    assistance_listing_number,
                    assistance_listing_title,
                    SUM(total_obligations) AS total_obligations,
                    SUM(transaction_count)::bigint AS transaction_count
                FROM {STATE_AGGREGATE}
                WHERE {where_sql}
                  AND assistance_listing_number IS NOT NULL
                GROUP BY assistance_listing_number, assistance_listing_title
                ORDER BY total_obligations DESC NULLS LAST
                """
            ),
            params,
        ).mappings().all()
    ]
    return {
        "default_geography_level": "state",
        "available_geography_levels": ["state", "county_future"],
        "default_fiscal_year": latest_year,
        "fiscal_years": fiscal_years,
        "funding_mechanisms": ["grants_cooperative_agreements", "contracts"],
        "default_funding_mechanism": DEFAULT_FUNDING_MECHANISM,
        "funding_view_modes": [
            {"value": value, "label": label}
            for value, label in FUNDING_VIEW_MODES.items()
        ],
        "default_funding_view_mode": DEFAULT_FUNDING_VIEW_MODE,
        "supplemental_history_filters": [
            {"value": "all", "label": "All awards"},
            {
                "value": "only_awards_with_supplemental_history",
                "label": "Only awards with supplemental history",
            },
            {
                "value": "exclude_awards_with_supplemental_history",
                "label": "Exclude awards with supplemental history",
            },
        ],
        "default_supplemental_history_filter": "all",
        "default_include_supplemental": False,
        "states": states,
        "assistance_listings": assistance_listings,
    }


def fetch_state_map(db: Session, **kwargs: Any) -> dict[str, Any]:
    filters = resolve_filters(db, **kwargs)
    where_sql, params = _aggregate_where(filters)
    rows = [
        _row_dict(row)
        for row in db.execute(
            text(
                f"""
                SELECT
                    state_fips,
                    state_code,
                    state_name,
                    SUM(total_obligations) AS total_obligations,
                    SUM(transaction_count)::bigint AS transaction_count,
                    SUM(award_count)::bigint AS award_count,
                    SUM(recipient_count)::bigint AS recipient_count,
                    SUM(COALESCE(obligations_from_awards_with_supplemental_history, 0))
                        AS obligations_from_awards_with_supplemental_history,
                    SUM(COALESCE(likely_vfc_obligations, 0)) AS likely_vfc_obligations,
                    SUM(COALESCE(funding_profiles_excluded_obligations, 0))
                        AS funding_profiles_excluded_obligations,
                    SUM(COALESCE(covid_era_immunization_response_obligations, 0))
                        AS covid_era_immunization_response_excluded_obligations,
                    SUM(COALESCE(covid_era_immunization_response_transaction_count, 0))::bigint
                        AS covid_era_immunization_response_excluded_transaction_count
                FROM {STATE_AGGREGATE}
                WHERE {where_sql}
                GROUP BY state_fips, state_code, state_name
                ORDER BY total_obligations DESC NULLS LAST
                """
            ),
            params,
        ).mappings().all()
    ]
    summary = {
        "total_obligations": sum(row["total_obligations"] for row in rows),
        "state_count": len(rows),
        "transaction_count": sum(row["transaction_count"] for row in rows),
        "award_count": sum(row["award_count"] for row in rows),
        "recipient_count": sum(row["recipient_count"] for row in rows),
        "obligations_from_awards_with_supplemental_history": sum(
            row.get("obligations_from_awards_with_supplemental_history") or 0 for row in rows
        ),
        "likely_vfc_obligations": sum(row.get("likely_vfc_obligations") or 0 for row in rows),
        "funding_profiles_excluded_obligations": sum(
            row.get("funding_profiles_excluded_obligations") or 0 for row in rows
        ),
        "covid_era_immunization_response_excluded_obligations": sum(
            row.get("covid_era_immunization_response_excluded_obligations") or 0 for row in rows
        ),
        "covid_era_immunization_response_excluded_transaction_count": sum(
            row.get("covid_era_immunization_response_excluded_transaction_count") or 0 for row in rows
        ),
    }
    diagnostic_where_sql, diagnostic_params = _aggregate_where({
        **filters,
        "funding_view_mode": DEFAULT_FUNDING_VIEW_MODE,
    })
    covid_era_diagnostics = _row_dict(
        db.execute(
            text(
                f"""
                SELECT
                    SUM(COALESCE(covid_era_immunization_response_obligations, 0))
                        AS covid_era_immunization_response_excluded_obligations,
                    SUM(COALESCE(covid_era_immunization_response_transaction_count, 0))::bigint
                        AS covid_era_immunization_response_excluded_transaction_count
                FROM {STATE_AGGREGATE}
                WHERE {diagnostic_where_sql}
                """
            ),
            diagnostic_params,
        ).mappings().first()
        or {}
    )
    summary.update(covid_era_diagnostics)
    unmapped_diagnostics = _fetch_unmapped_diagnostics(db, filters)
    summary = _summary_with_unmapped_fields(
        summary,
        unmapped_diagnostics,
        use_national_total=False,
    )
    return {
        "geography_level": "state",
        "funding_view_mode": filters["funding_view_mode"],
        "filters": filters,
        "summary": summary,
        "rows": rows,
    }


def fetch_summary(db: Session, **kwargs: Any) -> dict[str, Any]:
    map_payload = fetch_state_map(db, **kwargs)
    filters = map_payload["filters"]
    where_sql, params = _aggregate_where(filters)
    diagnostic_where_sql, diagnostic_params = _aggregate_where({
        **filters,
        "funding_view_mode": DEFAULT_FUNDING_VIEW_MODE,
    })
    scope_diagnostics = _row_dict(
        db.execute(
            text(
                f"""
                SELECT
                    SUM(COALESCE(obligations_from_awards_with_supplemental_history, 0))
                        AS obligations_from_awards_with_supplemental_history,
                    SUM(COALESCE(likely_vfc_obligations, 0)) AS likely_vfc_obligations,
                    SUM(COALESCE(funding_profiles_excluded_obligations, 0))
                        AS funding_profiles_excluded_obligations,
                    SUM(COALESCE(covid_era_immunization_response_obligations, 0))
                        AS covid_era_immunization_response_excluded_obligations,
                    SUM(COALESCE(covid_era_immunization_response_transaction_count, 0))::bigint
                        AS covid_era_immunization_response_excluded_transaction_count
                FROM {STATE_AGGREGATE}
                WHERE {diagnostic_where_sql}
                """
            ),
            diagnostic_params,
        ).mappings().first()
        or {}
    )
    diagnostic_fact_where, diagnostic_fact_params = _fact_where(
        {
            **filters,
            "funding_view_mode": DEFAULT_FUNDING_VIEW_MODE,
        },
        include_state_required=False,
    )
    national_covid_era_diagnostics = _row_dict(
        db.execute(
            text(
                f"""
                {_fact_state_cte()}
                SELECT
                    COALESCE(SUM(CASE WHEN COALESCE(fact.is_covid_era_immunization_response, false)
                        THEN fact.federal_action_obligation ELSE 0 END), 0)
                        AS covid_era_immunization_response_excluded_obligations,
                    COUNT(*) FILTER (WHERE COALESCE(fact.is_covid_era_immunization_response, false))::bigint
                        AS covid_era_immunization_response_excluded_transaction_count
                FROM normalized_fact AS fact
                WHERE {diagnostic_fact_where}
                """
            ),
            diagnostic_fact_params,
        ).mappings().first()
        or {}
    )
    scope_diagnostics.update(national_covid_era_diagnostics)
    top_assistance_listings = [
        _row_dict(row)
        for row in db.execute(
            text(
                f"""
                SELECT assistance_listing_number, assistance_listing_title,
                       SUM(total_obligations) AS total_obligations,
                       SUM(transaction_count)::bigint AS transaction_count,
                       SUM(COALESCE(obligations_from_awards_with_supplemental_history, 0))
                           AS obligations_from_awards_with_supplemental_history,
                       SUM(COALESCE(likely_vfc_obligations, 0)) AS likely_vfc_obligations,
                       SUM(COALESCE(funding_profiles_excluded_obligations, 0))
                           AS funding_profiles_excluded_obligations,
                       SUM(COALESCE(covid_era_immunization_response_obligations, 0))
                           AS covid_era_immunization_response_excluded_obligations,
                       SUM(COALESCE(covid_era_immunization_response_transaction_count, 0))::bigint
                           AS covid_era_immunization_response_excluded_transaction_count
                FROM {STATE_AGGREGATE}
                WHERE {where_sql}
                  AND assistance_listing_number IS NOT NULL
                GROUP BY assistance_listing_number, assistance_listing_title
                ORDER BY total_obligations DESC NULLS LAST
                LIMIT 10
                """
            ),
            params,
        ).mappings().all()
    ]
    fact_where, fact_params = _fact_where(filters)
    top_recipients = [
        _row_dict(row)
        for row in db.execute(
            text(
                f"""
                {_fact_state_cte()}
                SELECT
                    fact.recipient_name,
                    fact.recipient_uei,
                    SUM(fact.federal_action_obligation) AS total_obligations,
                    COUNT(*)::bigint AS transaction_count,
                    COUNT(DISTINCT COALESCE(NULLIF(fact.award_unique_key, ''), NULLIF(fact.generated_unique_award_id, ''), NULLIF(fact.award_id_piid, '')))::bigint AS award_count
                FROM normalized_fact AS fact
                WHERE {fact_where}
                  AND fact.recipient_name IS NOT NULL
                GROUP BY fact.recipient_name, fact.recipient_uei
                ORDER BY total_obligations DESC NULLS LAST
                LIMIT 10
                """
            ),
            fact_params,
        ).mappings().all()
    ]
    unmapped_diagnostics = {
        key: value
        for key, value in map_payload["summary"].items()
        if key in {
            "state_unmapped_obligations",
            "state_unmapped_transaction_count",
            "possible_global_or_foreign_obligations",
            "possible_global_or_foreign_transaction_count",
        }
    }
    summary = _summary_with_unmapped_fields(
        map_payload["summary"],
        unmapped_diagnostics,
        use_national_total=filters["funding_view_mode"] == "funding_profiles_comparable",
    )
    view_vfc_obligations = summary.get("likely_vfc_obligations")
    diagnostic_vfc_obligations = scope_diagnostics.get("likely_vfc_obligations")
    return {
        "geography_level": "state",
        "funding_view_mode": filters["funding_view_mode"],
        **summary,
        **scope_diagnostics,
        "vfc_immunization_cooperative_agreement_obligations": (
            view_vfc_obligations
            if view_vfc_obligations is not None
            else diagnostic_vfc_obligations
            if diagnostic_vfc_obligations is not None
            else 0
        ),
        "vaccine_purchase_obligations": None,
        "top_states": map_payload["rows"][:10],
        "top_assistance_listings": top_assistance_listings,
        "top_recipients": top_recipients,
    }


def fetch_state_awards(
    db: Session,
    state: str,
    *,
    limit: int = 100,
    offset: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    state_info = normalize_state(state)
    if state_info is None:
        raise HTTPException(status_code=422, detail=f"Invalid state: {state!r}")
    filters = resolve_filters(db, state=state_info.state_fips, **kwargs)
    fact_where, params = _fact_where(filters)
    params.update({"limit": limit, "offset": offset})
    rows = [
        _row_dict(row)
        for row in db.execute(
            text(
                f"""
                {_fact_state_cte()}
                SELECT
                    fact.source_fiscal_year,
                    fact.funding_mechanism,
                    fact.award_unique_key,
                    fact.generated_unique_award_id,
                    fact.recipient_name,
                    fact.recipient_uei,
                    fact.federal_action_obligation,
                    fact.action_date,
                    fact.assistance_listing_number,
                    fact.assistance_listing_title,
                    fact.award_type_code,
                    fact.award_type_description,
                    fact.transaction_description,
                    fact.prime_award_base_transaction_description,
                    fact.usaspending_permalink,
                    fact.map_geography_source,
                    state_lookup.state_fips AS normalized_state_fips,
                    state_lookup.state_code AS normalized_state_code,
                    state_lookup.state_name AS normalized_state_name,
                    LPAD(fact.map_county_fips, 5, '0') AS map_county_fips,
                    fact.map_county_name,
                    fact.is_covid_or_emergency_supplemental,
                    fact.covid_supplemental_obligated_amount,
                    fact.iija_supplemental_obligated_amount,
                    fact.defc_codes,
                    fact.defc_classification,
                    fact.has_overall_award_supplemental_history,
                    fact.is_likely_vfc,
                    fact.is_covid_era_immunization_response,
                    fact.is_profile_aligned_emergency_supplemental,
                    fact.funding_profiles_comparison_excluded,
                    fact.funding_profiles_exclusion_reason
                FROM normalized_fact AS fact
                JOIN state_lookup ON state_lookup.state_fips = fact.normalized_state_fips
                WHERE {fact_where}
                ORDER BY fact.federal_action_obligation DESC NULLS LAST, fact.source_row_number
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
    ]
    total_count = db.execute(
        text(
            f"""
            {_fact_state_cte()}
            SELECT COUNT(*)::bigint
            FROM normalized_fact AS fact
            WHERE {fact_where}
            """
        ),
        {key: value for key, value in params.items() if key not in {"limit", "offset"}},
    ).scalar()
    return {
        "state": {
            "state_fips": state_info.state_fips,
            "state_code": state_info.state_code,
            "state_name": state_info.state_name,
        },
        "filters": filters,
        "funding_view_mode": filters["funding_view_mode"],
        "limit": limit,
        "offset": offset,
        "total_count": int(total_count or 0),
        "rows": rows,
    }


def fetch_validation(db: Session) -> dict[str, Any]:
    raw_counts = []
    for file_type, table_name in {
        "assistance_prime_transactions": "raw_usaspending_assistance_prime_transactions",
        "assistance_subawards": "raw_usaspending_assistance_subawards",
        "contracts_prime_transactions": "raw_usaspending_contracts_prime_transactions",
        "contracts_subawards": "raw_usaspending_contracts_subawards",
    }.items():
        raw_counts.extend(
            _row_dict(row)
            for row in db.execute(
                text(
                    f"""
                    SELECT source_fiscal_year, :file_type AS source_file_type, COUNT(*)::bigint AS row_count
                    FROM {cdc_funding_table(table_name)}
                    GROUP BY source_fiscal_year
                    ORDER BY source_fiscal_year
                    """
                ),
                {"file_type": file_type},
            ).mappings().all()
        )
    return {
        "raw_row_counts": raw_counts,
        "canonical_row_counts": [
            _row_dict(row)
            for row in db.execute(
                text(
                    f"""
                    SELECT source_fiscal_year, funding_mechanism, COUNT(*)::bigint AS row_count
                    FROM {FACT_TABLE}
                    GROUP BY source_fiscal_year, funding_mechanism
                    ORDER BY source_fiscal_year, funding_mechanism
                    """
                )
            ).mappings().all()
        ],
        "obligation_counts": [
            _row_dict(row)
            for row in db.execute(
                text(f"SELECT is_positive_obligation AS bucket, COUNT(*)::bigint AS row_count FROM {FACT_TABLE} GROUP BY 1")
            ).mappings().all()
        ],
        "cdc_funded_counts": [
            _row_dict(row)
            for row in db.execute(
                text(f"SELECT is_cdc_funded AS bucket, COUNT(*)::bigint AS row_count FROM {FACT_TABLE} GROUP BY 1")
            ).mappings().all()
        ],
        "geography_source_counts": [
            _row_dict(row)
            for row in db.execute(
                text(f"SELECT map_geography_source, COUNT(*)::bigint AS row_count FROM {FACT_TABLE} GROUP BY 1 ORDER BY 1")
            ).mappings().all()
        ],
        "state_identifiable_counts": [
            _row_dict(row)
            for row in db.execute(
                text(
                    f"""
                    {_fact_state_cte()}
                    SELECT (fact.normalized_state_fips IS NOT NULL) AS state_identifiable,
                           COUNT(*)::bigint AS row_count
                    FROM normalized_fact AS fact
                    WHERE fact.is_prime_award IS TRUE
                      AND fact.is_positive_obligation IS TRUE
                      AND fact.is_cdc_funded IS TRUE
                      AND fact.federal_action_obligation > 0
                    GROUP BY 1
                    ORDER BY 1
                    """
                )
            ).mappings().all()
        ],
        "supplemental_counts": [
            _row_dict(row)
            for row in db.execute(
                text(f"SELECT is_covid_or_emergency_supplemental AS bucket, COUNT(*)::bigint AS row_count FROM {FACT_TABLE} GROUP BY 1")
            ).mappings().all()
        ],
        "default_map_eligible_counts": [
            _row_dict(row)
            for row in db.execute(
                text(f"SELECT is_default_map_eligible AS bucket, COUNT(*)::bigint AS row_count FROM {FACT_TABLE} GROUP BY 1")
            ).mappings().all()
        ],
        "funding_view_mode_totals_by_year": [
            _row_dict(row)
            for row in db.execute(
                text(
                    f"""
                    SELECT
                        source_fiscal_year,
                        SUM(CASE WHEN normalized_state_fips IS NOT NULL
                            THEN federal_action_obligation ELSE 0 END) AS standard_usaspending_state_total,
                        SUM(CASE WHEN normalized_state_fips IS NOT NULL
                              AND {_comparable_exclusion_predicate()}
                            THEN federal_action_obligation ELSE 0 END) AS funding_profiles_comparable_state_total,
                        SUM(CASE WHEN COALESCE(is_likely_vfc, false)
                            THEN federal_action_obligation ELSE 0 END) AS likely_vfc_amount,
                        SUM(CASE WHEN COALESCE(is_covid_era_immunization_response, false)
                            THEN federal_action_obligation ELSE 0 END) AS covid_era_immunization_response_amount,
                        COUNT(*) FILTER (WHERE COALESCE(is_covid_era_immunization_response, false))::bigint
                            AS covid_era_immunization_response_transaction_count,
                        SUM(CASE WHEN COALESCE(funding_profiles_comparison_excluded, false)
                            THEN federal_action_obligation ELSE 0 END) AS funding_profiles_comparison_excluded_amount,
                        SUM(CASE WHEN COALESCE(has_overall_award_supplemental_history, false)
                            THEN federal_action_obligation ELSE 0 END) AS amount_from_awards_with_overall_supplemental_history
                    FROM (
                        {_fact_state_cte()}
                        SELECT fact.*
                        FROM normalized_fact AS fact
                        WHERE fact.is_prime_award IS TRUE
                          AND fact.is_positive_obligation IS TRUE
                          AND fact.is_cdc_funded IS TRUE
                          AND fact.federal_action_obligation > 0
                    ) AS scoped
                    GROUP BY source_fiscal_year
                    ORDER BY source_fiscal_year
                    """
                )
            ).mappings().all()
        ],
        "defc_classification_totals_by_year": [
            _row_dict(row)
            for row in db.execute(
                text(
                    f"""
                    SELECT
                        source_fiscal_year,
                        COALESCE(defc_classification, 'unclassified') AS defc_classification,
                        SUM(COALESCE(federal_action_obligation, 0)) AS total_obligations,
                        COUNT(*)::bigint AS transaction_count
                    FROM {FACT_TABLE}
                    WHERE is_prime_award IS TRUE
                      AND is_positive_obligation IS TRUE
                      AND is_cdc_funded IS TRUE
                      AND federal_action_obligation > 0
                    GROUP BY source_fiscal_year, COALESCE(defc_classification, 'unclassified')
                    ORDER BY source_fiscal_year, defc_classification
                    """
                )
            ).mappings().all()
        ],
        "state_aggregate_row_counts": [
            _row_dict(row)
            for row in db.execute(
                text(
                    f"""
                    SELECT source_fiscal_year, funding_mechanism, COUNT(*)::bigint AS row_count
                    FROM {STATE_AGGREGATE}
                    GROUP BY source_fiscal_year, funding_mechanism
                    ORDER BY source_fiscal_year, funding_mechanism
                    """
                )
            ).mappings().all()
        ],
        "county_aggregate_row_counts": [
            _row_dict(row)
            for row in db.execute(
                text(
                    f"""
                    SELECT source_fiscal_year, funding_mechanism, COUNT(*)::bigint AS row_count
                    FROM {COUNTY_AGGREGATE}
                    GROUP BY source_fiscal_year, funding_mechanism
                    ORDER BY source_fiscal_year, funding_mechanism
                    """
                )
            ).mappings().all()
        ],
        "default_latest_state_map": fetch_state_map(db)["summary"],
        "top_states_latest_default": fetch_state_map(db)["rows"][:10],
        "top_assistance_listings_latest_default": fetch_summary(db)["top_assistance_listings"],
    }
