from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import places_table
from app.funding_models.registry import published_registry_metadata, resolve_custom_mode

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
VALID_TIME_AGGREGATIONS = {"single_fiscal_year", "multi_year_total", "multi_year_average"}


def fetch_map_geojson(
    db: Session,
    *,
    funding_mode: str,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    geography_level: str | None = None,
    time_aggregation: str | None = None,
    bbox: str | None = None,
    limit: int = 6000,
) -> dict[str, Any]:
    mode = _mode_or_404(db, funding_mode)
    metric_id = _normalize_metric(metric)
    geography = _normalize_geography_level(geography_level)
    if geography == "national":
        return {"type": "FeatureCollection", "features": [], "meta": _build_meta(
            db,
            mode=mode,
            metric_id=metric_id,
            fiscal_year=fiscal_year,
            funding_type=funding_type,
            cdc_center=cdc_center,
            program_area=program_area,
            mechanism=mechanism,
            recipient_type=recipient_type,
            geography_level=geography,
            time_aggregation=time_aggregation,
        )}
    cte_sql, params = _scoped_records_cte(
        mode=mode,
        fiscal_year=fiscal_year,
        funding_type=funding_type,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )
    if geography == "state":
        rows = db.execute(
            text(
                f"""
                {cte_sql},
                national_total AS (
                    SELECT COALESCE(SUM(obligation_amount), 0)::numeric AS national_total
                    FROM scoped_records
                ),
                aggregated AS (
                    SELECT
                        recipient_state_code AS state_code,
                        MAX(recipient_state_name) AS state_name,
                        COALESCE(SUM(obligation_amount), 0)::numeric AS total_amount,
                        COUNT(*)::integer AS row_count
                    FROM scoped_records
                    WHERE recipient_state_code IS NOT NULL
                    GROUP BY recipient_state_code
                )
                SELECT
                    sb.state_abbr AS geography_id,
                    sb.name AS geography_name,
                    sb.state_abbr AS state_code,
                    sb.name AS state_name,
                    aggregated.total_amount,
                    aggregated.row_count,
                    pop.population::numeric AS population,
                    national_total.national_total,
                    ST_AsGeoJSON(sb.geom, 6)::json AS geometry
                FROM {STATE_BOUNDARY_TABLE} AS sb
                LEFT JOIN aggregated
                    ON aggregated.state_code = sb.state_abbr
                LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
                    ON pop.geography_type = 'state'
                   AND pop.geography_id = sb.state_abbr
                CROSS JOIN national_total
                WHERE sb.geom IS NOT NULL
                ORDER BY sb.state_abbr
                LIMIT :limit
                """
            ),
            params | {"limit": limit},
        ).mappings().all()
    else:
        rows = db.execute(
            text(
                f"""
                {cte_sql},
                national_total AS (
                    SELECT COALESCE(SUM(obligation_amount), 0)::numeric AS national_total
                    FROM scoped_records
                ),
                aggregated AS (
                    SELECT
                        recipient_county_fips AS county_fips,
                        recipient_state_code AS state_code,
                        MAX(recipient_county_name) AS county_name,
                        COALESCE(SUM(obligation_amount), 0)::numeric AS total_amount,
                        COUNT(*)::integer AS row_count
                    FROM scoped_records
                    WHERE recipient_county_fips IS NOT NULL
                    GROUP BY recipient_county_fips, recipient_state_code
                )
                SELECT
                    b.geoid AS geography_id,
                    COALESCE(c.county_name, b.name) AS geography_name,
                    c.state_abbr AS state_code,
                    c.state_desc AS state_name,
                    aggregated.total_amount,
                    aggregated.row_count,
                    pop.population::numeric AS population,
                    national_total.national_total,
                    ST_AsGeoJSON(b.geom, 6)::json AS geometry
                FROM {COUNTY_BOUNDARY_TABLE} AS b
                LEFT JOIN {COUNTY_DIM_TABLE} AS c
                    ON c.location_id = b.location_id
                LEFT JOIN aggregated
                    ON aggregated.county_fips = b.geoid
                LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
                    ON pop.geography_type = 'county'
                   AND pop.geography_id = b.geoid
                CROSS JOIN national_total
                WHERE b.geom IS NOT NULL
                ORDER BY b.geoid
                LIMIT :limit
                """
            ),
            params | {"limit": limit},
        ).mappings().all()
    features = [_feature_payload(row, mode=mode, metric_id=metric_id, geography=geography) for row in rows]
    return {"type": "FeatureCollection", "features": features, "meta": _build_meta(
        db,
        mode=mode,
        metric_id=metric_id,
        fiscal_year=fiscal_year,
        funding_type=funding_type,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        geography_level=geography,
        time_aggregation=time_aggregation,
    )}


def fetch_legend_stats(
    db: Session,
    *,
    funding_mode: str,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    geography_level: str | None = None,
    time_aggregation: str | None = None,
    bbox: str | None = None,
) -> dict[str, Any]:
    del bbox
    feature_collection = fetch_map_geojson(
        db,
        funding_mode=funding_mode,
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        geography_level=geography_level,
        time_aggregation=time_aggregation,
        limit=7000,
    )
    values = [
        float(feature["properties"]["value"])
        for feature in feature_collection["features"]
        if feature["properties"].get("value") is not None and math.isfinite(float(feature["properties"]["value"]))
    ]
    national_summary = fetch_national_summary(
        db,
        funding_mode=funding_mode,
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=funding_type,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )
    return {
        "metric": _normalize_metric(metric),
        "metric_label": VALID_METRICS[_normalize_metric(metric)],
        "funding_mode_requested": funding_mode,
        "funding_mode_requested_label": mode_label(db, funding_mode),
        "funding_mode_effective": funding_mode,
        "funding_mode_label": mode_label(db, funding_mode),
        "geography_level": _normalize_geography_level(geography_level),
        "time_aggregation": _normalize_time_aggregation(time_aggregation, fiscal_year=fiscal_year),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "bins": _compute_bins(values),
        "mapped_geographies": len(values),
        "n": len(values),
        "noDataCount": max(len(feature_collection["features"]) - len(values), 0),
        "legend_title": _legend_title(metric=_normalize_metric(metric), fiscal_year=fiscal_year),
        "filter_context": _filter_context(
            metric=_normalize_metric(metric),
            fiscal_year=fiscal_year,
            funding_type=funding_type,
            cdc_center=cdc_center,
            program_area=program_area,
            mechanism=mechanism,
            recipient_type=recipient_type,
            time_aggregation=time_aggregation,
        ),
        "note": f"Published custom funding mode: {mode_label(db, funding_mode)}",
        "national_summary": national_summary,
    }


def fetch_national_summary(
    db: Session,
    *,
    funding_mode: str,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    time_aggregation: str | None = None,
) -> dict[str, Any]:
    mode = _mode_or_404(db, funding_mode)
    metric_id = _normalize_metric(metric)
    cte_sql, params = _scoped_records_cte(
        mode=mode,
        fiscal_year=fiscal_year,
        funding_type=funding_type,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )
    row = db.execute(
        text(
            f"""
            {cte_sql}
            SELECT
                COALESCE(SUM(obligation_amount), 0)::numeric AS total_amount,
                COUNT(*)::integer AS row_count,
                pop.population::numeric AS population
            FROM scoped_records
            LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
                ON pop.geography_type = 'national'
               AND pop.geography_id = 'US'
            GROUP BY pop.population
            """
        ),
        params,
    ).mappings().one_or_none()
    total_amount = float(row.get("total_amount") or 0) if row else 0.0
    population = _to_float(row.get("population")) if row else None
    profile = _funding_profile_payload(
        total_amount=total_amount,
        row_count=int(row.get("row_count") or 0) if row else 0,
        population=population,
        national_total=total_amount,
        metric_id=metric_id,
        geography="national",
        mode=mode,
        geography_name="United States",
        geography_id="US",
        state_code=None,
    )
    return {
        "funding_profile": profile,
        "funding_mode_requested": funding_mode,
        "funding_mode_effective": funding_mode,
        "funding_mode_label": mode["label"],
        "total_funding_amount": total_amount,
        "funding_per_capita": profile["funding_per_capita"],
        "funding_per_100k": profile["funding_per_100k"],
        "share_national_pct": profile["national_share"],
        "population": population,
    }


def fetch_state_profile_overview(
    db: Session,
    *,
    funding_mode: str,
    state: str,
    fiscal_year: int | None = None,
    metric: str | None = None,
    funding_type: str | None = None,
    cdc_center: str | None = None,
    program_area: str | None = None,
    mechanism: str | None = None,
    recipient_type: str | None = None,
    time_aggregation: str | None = None,
) -> dict[str, Any]:
    mode = _mode_or_404(db, funding_mode)
    state_code = str(state or "").strip().upper()
    if len(state_code) != 2:
        raise HTTPException(status_code=400, detail="state must be a valid 2-letter state code")
    metric_id = _normalize_metric(metric)
    cte_sql, params = _scoped_records_cte(
        mode=mode,
        fiscal_year=fiscal_year,
        funding_type=funding_type,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
        state=state_code,
    )
    total_row = db.execute(
        text(
            f"""
            {cte_sql},
            national_total AS (
                SELECT COALESCE(SUM(obligation_amount), 0)::numeric AS national_total
                FROM scoped_records
            )
            SELECT
                COALESCE(SUM(obligation_amount), 0)::numeric AS total_amount,
                COUNT(*)::integer AS row_count,
                MAX(recipient_state_name) AS state_name,
                pop.population::numeric AS population,
                national_total.national_total
            FROM scoped_records
            LEFT JOIN {POPULATION_VIEW_TABLE} AS pop
                ON pop.geography_type = 'state'
               AND pop.geography_id = :state_code
            CROSS JOIN national_total
            GROUP BY pop.population, national_total.national_total
            """
        ),
        params | {"state_code": state_code},
    ).mappings().one_or_none()
    total_amount = float(total_row.get("total_amount") or 0) if total_row else 0.0
    population = _to_float(total_row.get("population")) if total_row else None
    national_total = _to_float(total_row.get("national_total")) if total_row else None
    profile = _funding_profile_payload(
        total_amount=total_amount,
        row_count=int(total_row.get("row_count") or 0) if total_row else 0,
        population=population,
        national_total=national_total,
        metric_id=metric_id,
        geography="state",
        mode=mode,
        geography_name=str(total_row.get("state_name") or state_code) if total_row else state_code,
        geography_id=state_code,
        state_code=state_code,
    )
    categories = db.execute(
        text(
            f"""
            {cte_sql},
            totals AS (
                SELECT COALESCE(SUM(obligation_amount), 0)::numeric AS total_amount
                FROM scoped_records
            )
            SELECT
                COALESCE(NULLIF(category, ''), 'Unclassified') AS category,
                COALESCE(SUM(obligation_amount), 0)::numeric AS amount,
                COUNT(*)::integer AS award_count,
                COUNT(DISTINCT COALESCE(NULLIF(subcategory, ''), 'Unclassified'))::integer AS subcategory_count,
                CASE
                    WHEN totals.total_amount = 0 THEN NULL
                    ELSE (SUM(obligation_amount) / totals.total_amount) * 100
                END AS share_pct
            FROM scoped_records
            CROSS JOIN totals
            GROUP BY COALESCE(NULLIF(category, ''), 'Unclassified'), totals.total_amount
            ORDER BY amount DESC, category ASC
            """
        ),
        params,
    ).mappings().all()
    subcategories = db.execute(
        text(
            f"""
            {cte_sql},
            state_totals AS (
                SELECT COALESCE(SUM(obligation_amount), 0)::numeric AS state_total
                FROM scoped_records
            ),
            category_totals AS (
                SELECT
                    COALESCE(NULLIF(category, ''), 'Unclassified') AS category,
                    COALESCE(SUM(obligation_amount), 0)::numeric AS category_total
                FROM scoped_records
                GROUP BY COALESCE(NULLIF(category, ''), 'Unclassified')
            )
            SELECT
                category_totals.category AS category,
                COALESCE(NULLIF(scoped_records.subcategory, ''), 'Unclassified') AS subcategory,
                COALESCE(SUM(scoped_records.obligation_amount), 0)::numeric AS amount,
                COUNT(*)::integer AS award_count,
                CASE
                    WHEN state_totals.state_total = 0 THEN NULL
                    ELSE (SUM(scoped_records.obligation_amount) / state_totals.state_total) * 100
                END AS share_total_pct,
                CASE
                    WHEN category_totals.category_total = 0 THEN NULL
                    ELSE (SUM(scoped_records.obligation_amount) / category_totals.category_total) * 100
                END AS share_category_pct
            FROM scoped_records
            CROSS JOIN state_totals
            INNER JOIN category_totals
                ON category_totals.category = COALESCE(NULLIF(scoped_records.category, ''), 'Unclassified')
            GROUP BY category_totals.category, COALESCE(NULLIF(scoped_records.subcategory, ''), 'Unclassified'), state_totals.state_total, category_totals.category_total
            ORDER BY amount DESC, category ASC, subcategory ASC
            """
        ),
        params,
    ).mappings().all()
    filter_context = _filter_context(
        metric=metric_id,
        fiscal_year=fiscal_year,
        funding_type=funding_type,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )
    summary = {
        "state_code": state_code,
        "state_name": profile["state_name"],
        "total_funding": total_amount,
        "population": population,
        "funding_per_capita": profile["funding_per_capita"],
        "award_count": profile["award_count"],
        "contract_award_count": 0,
        "timeframe_label": profile["timeframe_label"],
        "selected_metric": metric_id,
        "selected_metric_label": VALID_METRICS[metric_id],
        "selected_metric_value": profile["metric_value"],
        "legend_title": filter_context["legend_title"],
        "funding_mode_effective": mode["key"],
        "funding_mode_label": mode["label"],
        "normalization_note": f"Published custom funding mode built from {mode['display_name']}.",
        "filter_context": filter_context,
        "grouping": {
            "category_label": "Funding Category",
            "subcategory_label": "Funding Subcategory",
            "count_label": "Records",
            "subcategory_count_label": "Subcategories",
            "category_method": "Categories come from the built funding-model output.",
            "subcategory_method": "Subcategories come from the built funding-model output.",
        },
        "methodology_notes": [
            f"Funding mode key: {mode['key']}",
            f"Methodology version: {mode['chip_methodology_version'] or 'Not specified'}",
        ],
        "profile": profile | {"metadata": {"metric_context": filter_context}},
    }
    return {
        "summary": summary,
        "categories": {
            "rows": [{**row, "amount": _to_float(row.get("amount")), "share_pct": _to_float(row.get("share_pct"))} for row in categories],
            "grouping": summary["grouping"],
            "profile": profile | {"metadata": {"metric_context": filter_context}},
        },
        "subcategories": {
            "rows": [
                {
                    **row,
                    "amount": _to_float(row.get("amount")),
                    "share_total_pct": _to_float(row.get("share_total_pct")),
                    "share_category_pct": _to_float(row.get("share_category_pct")),
                }
                for row in subcategories
            ],
            "grouping": summary["grouping"],
            "profile": profile | {"metadata": {"metric_context": filter_context}},
        },
    }


def fetch_state_profile_details(
    db: Session,
    *,
    funding_mode: str,
    state: str,
    fiscal_year: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "amount",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    mode = _mode_or_404(db, funding_mode)
    state_code = str(state or "").strip().upper()
    if len(state_code) != 2:
        raise HTTPException(status_code=400, detail="state must be a valid 2-letter state code")
    safe_sort_by = {
        "category": "category",
        "subcategory": "subcategory",
        "grantee_name": "grantee_name",
        "amount": "amount",
        "latest_action_date": "fiscal_year",
    }.get(str(sort_by or "amount").strip().lower(), "amount")
    safe_sort_dir = "asc" if str(sort_dir or "desc").strip().lower() == "asc" else "desc"
    offset = max(int(page) - 1, 0) * int(page_size)
    view_name = mode["view_name"]
    query_token = str(q or "").strip().lower()
    where_filters = ["recipient_state_code = :state_code"]
    params: dict[str, Any] = {"state_code": state_code, "limit": page_size, "offset": offset}
    if fiscal_year is not None:
        where_filters.append("fiscal_year = :fiscal_year")
        params["fiscal_year"] = int(fiscal_year)
    if query_token:
        params["q"] = f"%{query_token}%"
        where_filters.append(
            "("
            "LOWER(COALESCE(category, '')) LIKE :q OR "
            "LOWER(COALESCE(subcategory, '')) LIKE :q OR "
            "LOWER(COALESCE(project_title, '')) LIKE :q OR "
            "LOWER(COALESCE(recipient_name, '')) LIKE :q"
            ")"
        )
    where_sql = " AND ".join(where_filters)
    rows = db.execute(
        text(
            f"""
            SELECT
                record_key AS record_id,
                dataset_key AS record_type,
                cfda_number AS fain,
                COALESCE(NULLIF(category, ''), 'Unclassified') AS category,
                COALESCE(NULLIF(subcategory, ''), 'Unclassified') AS subcategory,
                project_title,
                recipient_name AS grantee_name,
                NULL::text AS city,
                recipient_county_name AS county,
                obligation_amount::numeric AS amount,
                fiscal_year AS min_fiscal_year,
                fiscal_year AS max_fiscal_year,
                NULL::date AS latest_action_date,
                recipient_state_name AS state_name,
                recipient_state_code AS state_code,
                usaspending_permalink
            FROM {view_name}
            WHERE {where_sql}
            ORDER BY {safe_sort_by} {safe_sort_dir.upper()} NULLS LAST, record_key ASC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    ).mappings().all()
    total_rows = db.execute(
        text(
            f"""
            SELECT COUNT(*)::integer
            FROM {view_name}
            WHERE {where_sql}
            """
        ),
        {key: value for key, value in params.items() if key not in {"limit", "offset"}},
    ).scalar()
    return {
        "basis": "prime",
        "state_code": state_code,
        "funding_geography_mode": "recipient_location",
        "q": query_token or None,
        "page": int(page),
        "page_size": int(page_size),
        "sort_by": safe_sort_by,
        "sort_dir": safe_sort_dir,
        "total_rows": int(total_rows or 0),
        "funding_mode_label": mode["label"],
        "funding_mode_effective": mode["key"],
        "rows": [
            {
                "line_number": offset + index,
                "record_id": row.get("record_id"),
                "record_type": row.get("record_type"),
                "fain": row.get("fain"),
                "category": row.get("category"),
                "subcategory": row.get("subcategory"),
                "project_title": row.get("project_title"),
                "grantee_name": row.get("grantee_name"),
                "city": row.get("city"),
                "county": row.get("county"),
                "amount": _to_float(row.get("amount")),
                "min_fiscal_year": row.get("min_fiscal_year"),
                "max_fiscal_year": row.get("max_fiscal_year"),
                "latest_action_date": row.get("latest_action_date"),
                "state_name": row.get("state_name"),
                "state_code": row.get("state_code"),
                "usaspending_permalink": row.get("usaspending_permalink"),
            }
            for index, row in enumerate(rows, start=1)
        ],
    }


def mode_label(db: Session, funding_mode: str) -> str:
    metadata = published_registry_metadata(db, funding_mode)
    return str(metadata.get("label") if metadata else funding_mode)


def _mode_or_404(db: Session, funding_mode: str) -> dict[str, Any]:
    row = resolve_custom_mode(db, funding_mode)
    if row is None or row.profile_version is None:
        raise HTTPException(status_code=404, detail="Published funding mode not found.")
    view_name = f"analytics.{row.profile_version.chip_normalization_source_version}"
    return {
        "key": row.funding_mode_key,
        "label": row.label,
        "display_name": row.profile_model.display_name if row.profile_model else row.label,
        "chip_methodology_version": row.profile_model.chip_methodology_version if row.profile_model else None,
        "view_name": view_name,
    }


def _normalize_metric(metric: str | None) -> str:
    token = str(metric or "total_funding").strip().lower()
    if token not in VALID_METRICS:
        raise HTTPException(status_code=400, detail=f"metric must be one of {', '.join(sorted(VALID_METRICS))}")
    return token


def _normalize_geography_level(value: str | None) -> str:
    token = str(value or "state").strip().lower()
    if token not in VALID_GEOGRAPHY_LEVELS:
        raise HTTPException(status_code=400, detail=f"geography_level must be one of {', '.join(sorted(VALID_GEOGRAPHY_LEVELS))}")
    return token


def _normalize_time_aggregation(value: str | None, *, fiscal_year: int | None) -> str:
    default_value = "single_fiscal_year" if fiscal_year is not None else "multi_year_total"
    token = str(value or default_value).strip().lower()
    if token not in VALID_TIME_AGGREGATIONS:
        raise HTTPException(status_code=400, detail=f"time_aggregation must be one of {', '.join(sorted(VALID_TIME_AGGREGATIONS))}")
    return token


def _scoped_records_cte(
    *,
    mode: dict[str, Any],
    fiscal_year: int | None,
    funding_type: str | None,
    cdc_center: str | None,
    program_area: str | None,
    mechanism: str | None,
    recipient_type: str | None,
    time_aggregation: str | None,
    state: str | None = None,
) -> tuple[str, dict[str, Any]]:
    filters: list[str] = ["1=1"]
    params: dict[str, Any] = {}
    if fiscal_year is not None:
        filters.append("fiscal_year = :fiscal_year")
        params["fiscal_year"] = int(fiscal_year)
    if state:
        filters.append("recipient_state_code = :state_code")
        params["state_code"] = state
    if str(cdc_center or program_area or "").strip():
        filters.append("LOWER(COALESCE(program_area, '')) = :program_area")
        params["program_area"] = str(cdc_center or program_area).strip().lower()
    if str(mechanism or "").strip():
        filters.append("LOWER(COALESCE(mechanism, '')) = :mechanism")
        params["mechanism"] = str(mechanism).strip().lower()
    if str(recipient_type or "").strip():
        filters.append("LOWER(COALESCE(recipient_type, '')) = :recipient_type")
        params["recipient_type"] = str(recipient_type).strip().lower()
    funding_type_token = str(funding_type or "total_cdc_funding").strip().lower()
    if funding_type_token == "awards_only":
        filters.append("dataset_key = 'usaspending_awards'")
    elif funding_type_token == "subawards_only":
        filters.append("dataset_key = 'usaspending_subawards'")
    elif funding_type_token == "awards_and_subawards":
        filters.append("dataset_key IN ('usaspending_awards', 'usaspending_subawards')")
    elif funding_type_token == "emergency_response":
        filters.append("COALESCE(is_emergency_funding, FALSE) = TRUE")
    elif funding_type_token == "non_emergency_program":
        filters.append("COALESCE(is_emergency_funding, FALSE) = FALSE")
    _normalize_time_aggregation(time_aggregation, fiscal_year=fiscal_year)
    return (
        f"WITH scoped_records AS (\n"
        f"    SELECT *\n"
        f"    FROM {mode['view_name']}\n"
        f"    WHERE {' AND '.join(filters)}\n"
        f")",
        params,
    )


def _feature_payload(row, *, mode: dict[str, Any], metric_id: str, geography: str) -> dict[str, Any]:
    total_amount = _to_float(row.get("total_amount"))
    population = _to_float(row.get("population"))
    national_total = _to_float(row.get("national_total"))
    profile = _funding_profile_payload(
        total_amount=total_amount,
        row_count=int(row.get("row_count") or 0),
        population=population,
        national_total=national_total,
        metric_id=metric_id,
        geography=geography,
        mode=mode,
        geography_name=str(row.get("geography_name") or row.get("state_name") or row.get("state_code") or ""),
        geography_id=str(row.get("geography_id") or ""),
        state_code=str(row.get("state_code") or "").strip() or None,
    )
    return {
        "type": "Feature",
        "geometry": row.get("geometry"),
        "properties": {
            "id": row.get("geography_id"),
            "name": row.get("geography_name"),
            "state_code": row.get("state_code"),
            "state_abbr": row.get("state_code"),
            "state_name": row.get("state_name"),
            "geo_level": geography,
            "metric": metric_id,
            "metric_label": VALID_METRICS[metric_id],
            "value": profile["metric_value"],
            "total_funding_amount": total_amount,
            "funding_per_capita": profile["funding_per_capita"],
            "funding_per_100k": profile["funding_per_100k"],
            "share_national_pct": profile["national_share"],
            "population": population,
            "funding_mode_effective": mode["key"],
            "funding_mode_label": mode["label"],
            "funding_profile": profile,
            "metric_context": {"legend_title": profile["timeframe_label"]},
        },
    }


def _funding_profile_payload(
    *,
    total_amount: float | None,
    row_count: int,
    population: float | None,
    national_total: float | None,
    metric_id: str,
    geography: str,
    mode: dict[str, Any],
    geography_name: str,
    geography_id: str,
    state_code: str | None,
) -> dict[str, Any]:
    has_data = total_amount is not None
    total = total_amount if has_data else None
    per_capita = (total / population) if has_data and population else None
    per_100k = (total / population) * 100000 if has_data and population else None
    national_share = ((total / national_total) * 100) if has_data and national_total else None
    metric_value = {
        "total_funding": total,
        "funding_per_capita": per_capita,
        "funding_per_100k": per_100k,
        "share_national": national_share,
    }[metric_id]
    return {
        "geography_id": geography_id,
        "geography_type": geography,
        "state_code": state_code,
        "state_name": geography_name if geography == "state" else None,
        "name": geography_name,
        "total_funding": total,
        "award_count": row_count,
        "population": population,
        "funding_per_capita": per_capita,
        "funding_per_100k": per_100k,
        "national_share": national_share,
        "metric_value": metric_value,
        "timeframe_label": "Current custom funding-model filter context",
        "funding_mode_effective": mode["key"],
        "funding_mode_label": mode["label"],
        "normalization_note": f"Published custom funding mode: {mode['display_name']}",
    }


def _build_meta(
    db: Session,
    *,
    mode: dict[str, Any],
    metric_id: str,
    fiscal_year: int | None,
    funding_type: str | None,
    cdc_center: str | None,
    program_area: str | None,
    mechanism: str | None,
    recipient_type: str | None,
    geography_level: str,
    time_aggregation: str | None,
) -> dict[str, Any]:
    national_summary = fetch_national_summary(
        db,
        funding_mode=mode["key"],
        fiscal_year=fiscal_year,
        metric=metric_id,
        funding_type=funding_type,
        cdc_center=cdc_center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )
    return {
        "note": f"Published custom funding mode: {mode['label']}",
        "legend_title": _legend_title(metric=metric_id, fiscal_year=fiscal_year),
        "filter_context": _filter_context(
            metric=metric_id,
            fiscal_year=fiscal_year,
            funding_type=funding_type,
            cdc_center=cdc_center,
            program_area=program_area,
            mechanism=mechanism,
            recipient_type=recipient_type,
            time_aggregation=time_aggregation,
        ),
        "funding_mode_requested": mode["key"],
        "funding_mode_requested_label": mode["label"],
        "funding_mode_effective": mode["key"],
        "funding_mode_label": mode["label"],
        "national_summary": national_summary,
        "geography_level": geography_level,
    }


def _filter_context(
    *,
    metric: str,
    fiscal_year: int | None,
    funding_type: str | None,
    cdc_center: str | None,
    program_area: str | None,
    mechanism: str | None,
    recipient_type: str | None,
    time_aggregation: str | None,
) -> dict[str, Any]:
    funding_type_label = {
        "awards_only": "Awards Only",
        "subawards_only": "Subawards Only",
        "awards_and_subawards": "Awards + Subawards",
        "emergency_response": "Emergency Response Funding",
        "non_emergency_program": "Non-Emergency Program Funding",
        "total_cdc_funding": "Total CDC Funding",
    }.get(str(funding_type or "total_cdc_funding").strip().lower(), "Total CDC Funding")
    return {
        "metric": metric,
        "metric_label": VALID_METRICS[metric],
        "legend_title": _legend_title(metric=metric, fiscal_year=fiscal_year),
        "funding_type_label": funding_type_label,
        "cdc_center_label": str(cdc_center or program_area or "").strip() or "All CDC Programs",
        "mechanism_label": str(mechanism or "").strip() or "All Mechanisms",
        "recipient_type_label": str(recipient_type or "").strip() or "All Recipients",
        "time_aggregation_label": _normalize_time_aggregation(time_aggregation, fiscal_year=fiscal_year).replace("_", " ").title(),
    }


def _legend_title(*, metric: str, fiscal_year: int | None) -> str:
    base = VALID_METRICS[metric]
    return f"{base} - FY{fiscal_year}" if fiscal_year else f"{base} - All Years"


def _compute_bins(values: list[float]) -> list[dict[str, Any]]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return [{"min": minimum, "max": maximum, "colorIndex": 0, "label": str(round(minimum, 2))}]
    step = (maximum - minimum) / 5
    bins = []
    current_min = minimum
    for index in range(5):
        current_max = maximum if index == 4 else minimum + step * (index + 1)
        bins.append(
            {
                "min": current_min,
                "max": current_max,
                "colorIndex": index,
            }
        )
        current_min = current_max
    return bins


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
