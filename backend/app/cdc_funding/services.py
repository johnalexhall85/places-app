from __future__ import annotations

import math
import re
from decimal import Decimal
from numbers import Real
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import cdc_funding_table, places_table

PRIME_TABLE = cdc_funding_table("prime_awards")
SUBAWARD_TABLE = cdc_funding_table("subawards")
PRIME_STATE_SUMMARY_TABLE = cdc_funding_table("prime_state_summary")
PRIME_COUNTY_SUMMARY_TABLE = cdc_funding_table("prime_county_summary")
SUBAWARD_STATE_SUMMARY_TABLE = cdc_funding_table("subaward_state_summary")
SUBAWARD_COUNTY_SUMMARY_TABLE = cdc_funding_table("subaward_county_summary")
COUNTY_BOUNDARY_TABLE = places_table("dim_county_boundary")
COUNTY_DIM_TABLE = places_table("dim_county")
STATE_BOUNDARY_TABLE = places_table("dim_state_boundary")

VALID_BASIS = {"prime", "subaward", "all"}
VALID_GEOGRAPHY = {"state", "county"}
VALID_METRICS = {
    "total_funding",
    "total_obligated",
    "total_outlayed",
    "award_count",
    "total_subaward",
    "subaward_count",
}

PRIME_METRICS = {
    "total_funding": "total_funding_amount",
    "total_obligated": "total_obligated_amount",
    "total_outlayed": "total_outlayed_amount",
    "award_count": "award_count",
}

SUBAWARD_METRICS = {
    "total_funding": "total_funding_amount",
    "total_obligated": "total_obligated_amount",
    "total_outlayed": "total_outlayed_amount",
    "award_count": "award_count",
    "total_subaward": "total_subaward_amount",
    "subaward_count": "subaward_count",
}

DOLLAR_METRICS = {
    "total_funding",
    "total_obligated",
    "total_outlayed",
    "total_subaward",
}

METRIC_LABELS = {
    "total_funding": "Total Funding",
    "total_obligated": "Total Obligated",
    "total_outlayed": "Total Outlayed",
    "award_count": "Award Count",
    "total_subaward": "Total Subaward Amount",
    "subaward_count": "Subaward Count",
}


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:name) AS exists"),
        {"name": table_name},
    ).mappings().one()
    return row["exists"] is not None


def _ensure_award_tables(db: Session) -> None:
    required = [PRIME_TABLE, SUBAWARD_TABLE]
    for table_name in required:
        if not _table_exists(db, table_name):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Required table {table_name} is missing. "
                    "Run migrations and CDC funding ingestion."
                ),
            )


def _ensure_required_tables(db: Session, *, geography: str) -> None:
    required = [
        PRIME_STATE_SUMMARY_TABLE,
        PRIME_COUNTY_SUMMARY_TABLE,
        SUBAWARD_STATE_SUMMARY_TABLE,
        SUBAWARD_COUNTY_SUMMARY_TABLE,
    ]
    _ensure_award_tables(db)
    if geography == "county":
        required.extend([COUNTY_BOUNDARY_TABLE, COUNTY_DIM_TABLE])
    else:
        required.append(STATE_BOUNDARY_TABLE)

    for table_name in required:
        if not _table_exists(db, table_name):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Required table {table_name} is missing. "
                    "Run migrations and CDC funding ingestion."
                ),
            )


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


def _strip_optional(value: str | None) -> str | None:
    token = str(value or "").strip()
    return token or None


def _normalize_basis(value: str | None, *, allow_all: bool = False) -> str:
    token = str(value or "prime").strip().lower()
    allowed = VALID_BASIS if allow_all else {"prime", "subaward"}
    if token not in allowed:
        options = "prime, subaward, or all" if allow_all else "prime or subaward"
        raise HTTPException(status_code=400, detail=f"basis must be {options}")
    return token


def _normalize_geography(value: str | None) -> str:
    token = str(value or "county").strip().lower()
    if token not in VALID_GEOGRAPHY:
        raise HTTPException(status_code=400, detail="geography must be state or county")
    return token


def _normalize_metric(value: str | None, *, basis: str) -> str:
    token = str(value or "total_funding").strip().lower()
    if token not in VALID_METRICS:
        raise HTTPException(
            status_code=400,
            detail=(
                "metric must be one of total_funding, total_obligated, total_outlayed, "
                "award_count, total_subaward, or subaward_count"
            ),
        )

    if basis == "prime" and token in {"total_subaward", "subaward_count"}:
        raise HTTPException(
            status_code=400,
            detail="total_subaward and subaward_count are only valid for basis=subaward",
        )
    return token


def _normalize_state_code(value: str | None) -> str | None:
    if value is None:
        return None
    letters = re.sub(r"[^A-Za-z]", "", str(value).strip()).upper()
    if len(letters) != 2:
        raise HTTPException(status_code=400, detail="state must be a 2-letter state code")
    return letters


def _parse_bbox(bbox: str | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    try:
        minx, miny, maxx, maxy = (float(value) for value in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid bbox format") from exc

    if minx >= maxx or miny >= maxy:
        raise HTTPException(status_code=400, detail="Invalid bbox bounds")

    return {
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
    }


def _metric_column(basis: str, metric: str) -> str:
    if basis == "prime":
        return PRIME_METRICS[metric]
    return SUBAWARD_METRICS[metric]


def _summary_table(*, basis: str, geography: str) -> str:
    if basis == "prime":
        return PRIME_STATE_SUMMARY_TABLE if geography == "state" else PRIME_COUNTY_SUMMARY_TABLE
    return SUBAWARD_STATE_SUMMARY_TABLE if geography == "state" else SUBAWARD_COUNTY_SUMMARY_TABLE


def _summary_filters_sql(
    *,
    basis: str,
    geography: str,
    assistance_type: str | None,
    fiscal_year: int | None,
    awarding_office: str | None,
    funding_office: str | None,
    center: str | None,
    state: str | None,
) -> tuple[str, dict[str, Any]]:
    conditions: list[str] = []
    params: dict[str, Any] = {}

    if assistance_type and basis == "prime":
        conditions.append("s.assistance_type_description = :assistance_type")
        params["assistance_type"] = assistance_type

    if fiscal_year is not None:
        conditions.append("s.fiscal_year = :fiscal_year")
        params["fiscal_year"] = int(fiscal_year)

    if awarding_office:
        conditions.append("s.awarding_office_name = :awarding_office")
        params["awarding_office"] = awarding_office

    if funding_office:
        conditions.append("s.funding_office_name = :funding_office")
        params["funding_office"] = funding_office

    if center:
        conditions.append(
            "(s.awarding_sub_agency_name = :center OR s.funding_sub_agency_name = :center)"
        )
        params["center"] = center

    normalized_state = _normalize_state_code(state)
    if normalized_state:
        if geography == "state":
            conditions.append("s.geography_id = :state_code")
        else:
            conditions.append("s.state_code = :state_code")
        params["state_code"] = normalized_state

    if not conditions:
        return ("", params)
    return (" AND " + " AND ".join(conditions), params)


def _summary_aggregate_sql(*, basis: str, metric_column: str, table_name: str, where_sql: str) -> str:
    if basis == "prime":
        return (
            "SELECT "
            "  s.geography_id,"
            f"  SUM(s.{metric_column}) AS metric_value,"
            "  SUM(s.total_funding_amount) AS total_funding_amount,"
            "  SUM(s.total_obligated_amount) AS total_obligated_amount,"
            "  SUM(s.total_outlayed_amount) AS total_outlayed_amount,"
            "  SUM(s.award_count) AS award_count,"
            "  0::numeric AS total_subaward_amount,"
            "  0::numeric AS subaward_count "
            f"FROM {table_name} AS s "
            "WHERE 1=1"
            f"{where_sql} "
            "GROUP BY s.geography_id"
        )

    return (
        "SELECT "
        "  s.geography_id,"
        f"  SUM(s.{metric_column}) AS metric_value,"
        "  SUM(s.total_funding_amount) AS total_funding_amount,"
        "  SUM(s.total_obligated_amount) AS total_obligated_amount,"
        "  SUM(s.total_outlayed_amount) AS total_outlayed_amount,"
        "  SUM(s.award_count) AS award_count,"
        "  SUM(s.total_subaward_amount) AS total_subaward_amount,"
        "  SUM(s.subaward_count) AS subaward_count "
        f"FROM {table_name} AS s "
        "WHERE 1=1"
        f"{where_sql} "
        "GROUP BY s.geography_id"
    )


def _quantile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    base = int(math.floor(position))
    remainder = position - base
    lower = sorted_values[base]
    upper = sorted_values[base + 1] if base + 1 < len(sorted_values) else lower
    return lower + (upper - lower) * remainder


def _compute_bins(values: list[float], *, bins: int = 5) -> list[dict[str, Any]]:
    if not values:
        return []
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        value = sorted_values[0]
        return [{"min": value, "max": value, "label": f"{value:,.1f}", "colorIndex": 0}]

    breakpoints: list[float] = []
    for index in range(bins + 1):
        fraction = index / bins
        value = _quantile(sorted_values, fraction)
        if value is None:
            continue
        breakpoints.append(float(value))

    deduped: list[float] = []
    for point in breakpoints:
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
                "label": f"{lower:,.1f} - {upper:,.1f}",
                "colorIndex": index,
            }
        )
    return output


def list_filter_options(
    db: Session,
    *,
    basis: str,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis, allow_all=True)
    _ensure_award_tables(db)

    def _distinct(table_name: str, column_name: str) -> list[str]:
        rows = db.execute(
            text(
                f"""
                SELECT DISTINCT {column_name} AS value
                FROM {table_name}
                WHERE {column_name} IS NOT NULL
                  AND NULLIF(TRIM(({column_name})::text), '') IS NOT NULL
                ORDER BY {column_name}
                """
            )
        ).mappings().all()
        return [str(row["value"]).strip() for row in rows if row.get("value") is not None]

    def _union_distinct(
        left_table: str,
        left_col: str,
        right_table: str,
        right_col: str,
    ) -> list[str]:
        rows = db.execute(
            text(
                f"""
                SELECT DISTINCT value
                FROM (
                    SELECT {left_col} AS value FROM {left_table}
                    UNION ALL
                    SELECT {right_col} AS value FROM {right_table}
                ) AS unioned
                WHERE value IS NOT NULL
                  AND NULLIF(TRIM(value), '') IS NOT NULL
                ORDER BY value
                """
            )
        ).mappings().all()
        return [str(row["value"]).strip() for row in rows if row.get("value") is not None]

    if normalized_basis == "prime":
        table_name = PRIME_TABLE
        years = [
            int(value)
            for value in _distinct(PRIME_TABLE, "award_latest_action_date_fiscal_year")
            if str(value).isdigit()
        ]
        metric_options = [
            {"value": key, "label": METRIC_LABELS[key]}
            for key in ["total_funding", "total_obligated", "total_outlayed", "award_count"]
        ]
        states = db.execute(
            text(
                f"""
                SELECT recipient_state_code AS code, MAX(recipient_state_name) AS name
                FROM {PRIME_TABLE}
                WHERE recipient_state_code IS NOT NULL
                GROUP BY recipient_state_code
                ORDER BY recipient_state_code
                """
            )
        ).mappings().all()
        assistance_types = _distinct(PRIME_TABLE, "assistance_type_description")
    elif normalized_basis == "subaward":
        table_name = SUBAWARD_TABLE
        years = [
            int(value)
            for value in _distinct(SUBAWARD_TABLE, "subaward_action_date_fiscal_year")
            if str(value).isdigit()
        ]
        metric_options = [
            {"value": key, "label": METRIC_LABELS[key]}
            for key in ["total_subaward", "subaward_count"]
        ]
        states = db.execute(
            text(
                f"""
                SELECT subawardee_state_code AS code, MAX(subawardee_state_name) AS name
                FROM {SUBAWARD_TABLE}
                WHERE subawardee_state_code IS NOT NULL
                GROUP BY subawardee_state_code
                ORDER BY subawardee_state_code
                """
            )
        ).mappings().all()
        assistance_types = []
    else:
        table_name = PRIME_TABLE
        years_rows = db.execute(
            text(
                f"""
                SELECT award_latest_action_date_fiscal_year::text AS fiscal_year FROM {PRIME_TABLE}
                UNION
                SELECT subaward_action_date_fiscal_year::text AS fiscal_year FROM {SUBAWARD_TABLE}
                """
            )
        ).mappings().all()
        years = sorted(
            {
                int(str(row["fiscal_year"]))
                for row in years_rows
                if row.get("fiscal_year") is not None and str(row["fiscal_year"]).isdigit()
            },
            reverse=True,
        )
        metric_options = [
            {"value": key, "label": METRIC_LABELS[key]}
            for key in ["total_funding", "total_obligated", "total_outlayed", "award_count"]
        ]
        states = db.execute(
            text(
                f"""
                SELECT recipient_state_code AS code, MAX(recipient_state_name) AS name
                FROM {PRIME_TABLE}
                WHERE recipient_state_code IS NOT NULL
                GROUP BY recipient_state_code
                UNION
                SELECT subawardee_state_code AS code, MAX(subawardee_state_name) AS name
                FROM {SUBAWARD_TABLE}
                WHERE subawardee_state_code IS NOT NULL
                GROUP BY subawardee_state_code
                ORDER BY code
                """
            )
        ).mappings().all()
        assistance_types = _distinct(PRIME_TABLE, "assistance_type_description")

    if normalized_basis == "prime":
        awarding_offices = _distinct(PRIME_TABLE, "awarding_office_name")
        funding_offices = _distinct(PRIME_TABLE, "funding_office_name")
        centers = _union_distinct(
            PRIME_TABLE,
            "awarding_sub_agency_name",
            PRIME_TABLE,
            "funding_sub_agency_name",
        )
    elif normalized_basis == "subaward":
        awarding_offices = _distinct(SUBAWARD_TABLE, "prime_award_awarding_office_name")
        funding_offices = _distinct(SUBAWARD_TABLE, "prime_award_funding_office_name")
        centers = _union_distinct(
            SUBAWARD_TABLE,
            "prime_award_awarding_sub_agency_name",
            SUBAWARD_TABLE,
            "prime_award_funding_sub_agency_name",
        )
    else:
        awarding_offices = _union_distinct(
            PRIME_TABLE,
            "awarding_office_name",
            SUBAWARD_TABLE,
            "prime_award_awarding_office_name",
        )
        funding_offices = _union_distinct(
            PRIME_TABLE,
            "funding_office_name",
            SUBAWARD_TABLE,
            "prime_award_funding_office_name",
        )
        centers = _union_distinct(
            PRIME_TABLE,
            "awarding_sub_agency_name",
            SUBAWARD_TABLE,
            "prime_award_awarding_sub_agency_name",
        )

    years = sorted(set(years), reverse=True)

    return {
        "basis": normalized_basis,
        "metric_options": metric_options,
        "assistance_types": assistance_types,
        "fiscal_years": years,
        "awarding_offices": awarding_offices,
        "funding_offices": funding_offices,
        "centers": centers,
        "states": [
            {
                "code": str(row.get("code") or "").strip(),
                "name": str(row.get("name") or row.get("code") or "").strip(),
            }
            for row in states
            if str(row.get("code") or "").strip()
        ],
    }


def fetch_map_geojson(
    db: Session,
    *,
    basis: str,
    geography: str,
    metric: str,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
    state: str | None = None,
    bbox: str | None = None,
    zoom: int = 6,
    limit: int = 6000,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis)
    normalized_geography = _normalize_geography(geography)
    normalized_metric = _normalize_metric(metric, basis=normalized_basis)
    _ensure_required_tables(db, geography=normalized_geography)

    metric_column = _metric_column(normalized_basis, normalized_metric)
    summary_table = _summary_table(basis=normalized_basis, geography=normalized_geography)
    filter_sql, filter_params = _summary_filters_sql(
        basis=normalized_basis,
        geography=normalized_geography,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
        state=state,
    )
    bbox_params = _parse_bbox(bbox)

    simplify_degrees = 0.02
    if zoom <= 5:
        simplify_degrees = 0.04
    elif zoom >= 9:
        simplify_degrees = 0.01

    params: dict[str, Any] = {
        **filter_params,
        "limit": max(1, min(int(limit), 20000)),
        "simplify_degrees": simplify_degrees,
    }

    summary_sql = _summary_aggregate_sql(
        basis=normalized_basis,
        metric_column=metric_column,
        table_name=summary_table,
        where_sql=filter_sql,
    )

    if normalized_geography == "county":
        bbox_cte = ""
        bbox_join = ""
        bbox_filter = ""
        if bbox_params is not None:
            bbox_cte = (
                "WITH bbox AS (SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom), "
                "summary AS ("
                + summary_sql
                + ")"
            )
            bbox_join = "CROSS JOIN bbox"
            bbox_filter = "AND b.geom && bbox.geom AND ST_Intersects(b.geom, bbox.geom)"
            params.update(bbox_params)
        else:
            bbox_cte = f"WITH summary AS ({summary_sql})"

        rows = db.execute(
            text(
                f"""
                {bbox_cte}
                SELECT
                    b.geoid AS id,
                    COALESCE(c.county_name, b.name) AS area_name,
                    c.state_abbr AS state_code,
                    c.state_desc AS state_name,
                    summary.metric_value AS value,
                    summary.total_funding_amount,
                    summary.total_obligated_amount,
                    summary.total_outlayed_amount,
                    summary.award_count,
                    summary.total_subaward_amount,
                    summary.subaward_count,
                    ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(b.geom, :simplify_degrees),
                        6
                    )::json AS geometry
                FROM {COUNTY_BOUNDARY_TABLE} AS b
                LEFT JOIN {COUNTY_DIM_TABLE} AS c
                    ON c.location_id = b.location_id
                LEFT JOIN summary
                    ON summary.geography_id = b.geoid
                {bbox_join}
                WHERE b.geom IS NOT NULL
                  {bbox_filter}
                ORDER BY b.geoid
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    else:
        bbox_filter = ""
        if bbox_params is not None:
            bbox_filter = (
                "AND sb.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
                "AND ST_Intersects(sb.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
            )
            params.update(bbox_params)

        rows = db.execute(
            text(
                f"""
                WITH summary AS ({summary_sql})
                SELECT
                    sb.state_abbr AS id,
                    COALESCE(sb.state_name, sb.state_abbr) AS area_name,
                    sb.state_abbr AS state_code,
                    COALESCE(sb.state_name, sb.state_abbr) AS state_name,
                    summary.metric_value AS value,
                    summary.total_funding_amount,
                    summary.total_obligated_amount,
                    summary.total_outlayed_amount,
                    summary.award_count,
                    summary.total_subaward_amount,
                    summary.subaward_count,
                    ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(sb.geom, :simplify_degrees),
                        6
                    )::json AS geometry
                FROM {STATE_BOUNDARY_TABLE} AS sb
                LEFT JOIN summary
                    ON summary.geography_id = sb.state_abbr
                WHERE sb.geom IS NOT NULL
                  {bbox_filter}
                ORDER BY sb.state_abbr
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

    features = []
    for row in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "id": row["id"],
                    "location_id": row["id"],
                    "name": row["area_name"],
                    "state_abbr": row["state_code"],
                    "state_name": row["state_name"],
                    "value": _json_number(row["value"]),
                    "metric": normalized_metric,
                    "metric_label": METRIC_LABELS.get(normalized_metric, normalized_metric),
                    "basis": normalized_basis,
                    "geo_level": normalized_geography,
                    "total_funding_amount": _json_number(row["total_funding_amount"]),
                    "total_obligated_amount": _json_number(row["total_obligated_amount"]),
                    "total_outlayed_amount": _json_number(row["total_outlayed_amount"]),
                    "award_count": int(row["award_count"] or 0),
                    "total_subaward_amount": _json_number(row["total_subaward_amount"]),
                    "subaward_count": int(row["subaward_count"] or 0),
                },
            }
        )

    note = (
        "Funds awarded to recipients located in this geography"
        if normalized_basis == "prime"
        else "Subawards reported to entities in this geography"
    )

    return {
        "type": "FeatureCollection",
        "basis": normalized_basis,
        "level": normalized_geography,
        "metric": normalized_metric,
        "features": features,
        "meta": {
            "note": note,
            "metric_label": METRIC_LABELS.get(normalized_metric, normalized_metric),
            "geojson_precision": 6,
            "simplify_tolerance_degrees": simplify_degrees,
        },
    }


def fetch_legend_stats(
    db: Session,
    *,
    basis: str,
    geography: str,
    metric: str,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
    state: str | None = None,
    bbox: str | None = None,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis)
    normalized_geography = _normalize_geography(geography)
    normalized_metric = _normalize_metric(metric, basis=normalized_basis)
    _ensure_required_tables(db, geography=normalized_geography)

    metric_column = _metric_column(normalized_basis, normalized_metric)
    summary_table = _summary_table(basis=normalized_basis, geography=normalized_geography)
    filter_sql, filter_params = _summary_filters_sql(
        basis=normalized_basis,
        geography=normalized_geography,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office,
        funding_office=funding_office,
        center=center,
        state=state,
    )
    bbox_params = _parse_bbox(bbox)

    params: dict[str, Any] = dict(filter_params)
    summary_sql = _summary_aggregate_sql(
        basis=normalized_basis,
        metric_column=metric_column,
        table_name=summary_table,
        where_sql=filter_sql,
    )

    if normalized_geography == "county":
        bbox_join = ""
        bbox_filter = ""
        if bbox_params is not None:
            bbox_join = (
                f"JOIN {COUNTY_BOUNDARY_TABLE} AS b ON b.geoid = summary.geography_id"
            )
            bbox_filter = (
                "WHERE b.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
                "AND ST_Intersects(b.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
            )
            params.update(bbox_params)

        rows = db.execute(
            text(
                f"""
                WITH summary AS ({summary_sql})
                SELECT
                    summary.geography_id,
                    summary.metric_value,
                    summary.total_funding_amount,
                    summary.total_obligated_amount,
                    summary.total_outlayed_amount,
                    summary.award_count,
                    summary.total_subaward_amount,
                    summary.subaward_count
                FROM summary
                {bbox_join}
                {bbox_filter}
                """
            ),
            params,
        ).mappings().all()
    else:
        bbox_join = ""
        bbox_filter = ""
        if bbox_params is not None:
            bbox_join = f"JOIN {STATE_BOUNDARY_TABLE} AS sb ON sb.state_abbr = summary.geography_id"
            bbox_filter = (
                "WHERE sb.geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) "
                "AND ST_Intersects(sb.geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
            )
            params.update(bbox_params)

        rows = db.execute(
            text(
                f"""
                WITH summary AS ({summary_sql})
                SELECT
                    summary.geography_id,
                    summary.metric_value,
                    summary.total_funding_amount,
                    summary.total_obligated_amount,
                    summary.total_outlayed_amount,
                    summary.award_count,
                    summary.total_subaward_amount,
                    summary.subaward_count
                FROM summary
                {bbox_join}
                {bbox_filter}
                """
            ),
            params,
        ).mappings().all()

    metric_values = [
        float(row["metric_value"])
        for row in rows
        if row.get("metric_value") is not None and math.isfinite(float(row["metric_value"]))
    ]
    bins = _compute_bins(metric_values, bins=5)

    def _sum_column(column: str) -> float:
        return float(
            sum(
                float(row.get(column) or 0)
                for row in rows
                if row.get(column) is not None and math.isfinite(float(row.get(column)))
            )
        )

    if normalized_basis == "prime":
        total_visible_awards = int(
            sum(int(row.get("award_count") or 0) for row in rows)
        )
    else:
        total_visible_awards = int(
            sum(int(row.get("subaward_count") or 0) for row in rows)
        )

    total_visible_dollars = _sum_column(_metric_column(normalized_basis, normalized_metric))
    if normalized_metric not in DOLLAR_METRICS:
        total_visible_dollars = None

    return {
        "basis": normalized_basis,
        "geography": normalized_geography,
        "metric": normalized_metric,
        "metric_label": METRIC_LABELS.get(normalized_metric, normalized_metric),
        "min": min(metric_values) if metric_values else None,
        "max": max(metric_values) if metric_values else None,
        "bins": bins,
        "mapped_geographies": len(metric_values),
        "n": len(metric_values),
        "noDataCount": 0,
        "total_visible_dollars": total_visible_dollars,
        "total_visible_awards": total_visible_awards,
    }


def search_awards(
    db: Session,
    *,
    q: str | None,
    basis: str,
    assistance_type: str | None,
    fiscal_year: int | None,
    state: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis, allow_all=True)
    normalized_state = _normalize_state_code(state)
    query_token = str(q or "").strip()
    _ensure_award_tables(db)

    page = int(page)
    page_size = int(page_size)
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 100")

    params: dict[str, Any] = {
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }

    prime_filters: list[str] = []
    sub_filters: list[str] = []

    if query_token:
        params["q"] = f"%{query_token}%"
        prime_filters.append("(p.searchable_text ILIKE :q OR p.fain ILIKE :q OR p.recipient_name ILIKE :q)")
        sub_filters.append("(s.searchable_text ILIKE :q OR s.prime_award_fain ILIKE :q OR s.subawardee_name ILIKE :q)")

    assistance_type = _strip_optional(assistance_type)
    if assistance_type:
        params["assistance_type"] = assistance_type
        prime_filters.append("p.assistance_type_description = :assistance_type")

    if fiscal_year is not None:
        params["fiscal_year"] = int(fiscal_year)
        prime_filters.append("p.award_latest_action_date_fiscal_year = :fiscal_year")
        sub_filters.append("s.subaward_action_date_fiscal_year = :fiscal_year")

    if normalized_state:
        params["state_code"] = normalized_state
        prime_filters.append("p.recipient_state_code = :state_code")
        sub_filters.append("s.subawardee_state_code = :state_code")

    prime_where = ""
    if prime_filters:
        prime_where = "WHERE " + " AND ".join(prime_filters)

    sub_where = ""
    if sub_filters:
        sub_where = "WHERE " + " AND ".join(sub_filters)

    prime_sql = f"""
        SELECT
            p.unique_key AS record_id,
            'prime_award'::text AS record_type,
            p.fain,
            p.recipient_name AS entity_name,
            p.assistance_type_description,
            p.total_funding_amount AS amount,
            p.award_latest_action_date AS latest_action_date,
            p.recipient_state_code AS state_code,
            p.recipient_state_name AS state_name,
            p.recipient_county_fips AS county_fips,
            p.recipient_county_name AS county_name,
            p.prime_award_base_transaction_description AS description,
            p.usaspending_permalink,
            p.award_latest_action_date_fiscal_year AS fiscal_year,
            p.awarding_sub_agency_name AS center_name,
            p.awarding_office_name AS awarding_office_name,
            p.funding_office_name AS funding_office_name
        FROM {PRIME_TABLE} AS p
        {prime_where}
    """

    sub_sql = f"""
        SELECT
            s.id::text AS record_id,
            'subaward'::text AS record_type,
            s.prime_award_fain AS fain,
            s.subawardee_name AS entity_name,
            NULL::text AS assistance_type_description,
            s.subaward_amount AS amount,
            s.subaward_action_date AS latest_action_date,
            s.subawardee_state_code AS state_code,
            s.subawardee_state_name AS state_name,
            s.subawardee_county_fips AS county_fips,
            NULL::text AS county_name,
            COALESCE(s.subaward_description, s.prime_award_base_transaction_description) AS description,
            s.usaspending_permalink,
            s.subaward_action_date_fiscal_year AS fiscal_year,
            s.prime_award_awarding_sub_agency_name AS center_name,
            s.prime_award_awarding_office_name AS awarding_office_name,
            s.prime_award_funding_office_name AS funding_office_name
        FROM {SUBAWARD_TABLE} AS s
        {sub_where}
    """

    if normalized_basis == "prime":
        combined_sql = prime_sql
    elif normalized_basis == "subaward":
        combined_sql = sub_sql
    else:
        combined_sql = f"{prime_sql} UNION ALL {sub_sql}"

    rows = db.execute(
        text(
            f"""
            SELECT *
            FROM ({combined_sql}) AS combined
            ORDER BY combined.latest_action_date DESC NULLS LAST, combined.amount DESC NULLS LAST
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    total_count = db.execute(
        text(f"SELECT COUNT(*)::integer AS total_count FROM ({combined_sql}) AS combined"),
        params,
    ).mappings().one()["total_count"]

    results = [
        {
            "record_id": row["record_id"],
            "record_type": row["record_type"],
            "fain": row["fain"],
            "entity_name": row["entity_name"],
            "assistance_type_description": row["assistance_type_description"],
            "amount": _json_number(row["amount"]),
            "latest_action_date": row["latest_action_date"].isoformat() if row["latest_action_date"] else None,
            "state_code": row["state_code"],
            "state_name": row["state_name"],
            "county_fips": row["county_fips"],
            "county_name": row["county_name"],
            "description": row["description"],
            "usaspending_permalink": row["usaspending_permalink"],
            "fiscal_year": row["fiscal_year"],
            "center_name": row["center_name"],
            "awarding_office_name": row["awarding_office_name"],
            "funding_office_name": row["funding_office_name"],
        }
        for row in rows
    ]

    return {
        "basis": normalized_basis,
        "q": query_token,
        "page": page,
        "page_size": page_size,
        "total": int(total_count or 0),
        "results": results,
    }


def fetch_detail(
    db: Session,
    *,
    prime_unique_key: str | None = None,
    subaward_id: int | None = None,
) -> dict[str, Any] | None:
    _ensure_award_tables(db)
    if bool(prime_unique_key) == bool(subaward_id):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of prime_unique_key or subaward_id",
        )

    if prime_unique_key:
        row = db.execute(
            text(f"SELECT * FROM {PRIME_TABLE} WHERE unique_key = :unique_key"),
            {"unique_key": str(prime_unique_key).strip()},
        ).mappings().one_or_none()
        if row is None:
            return None
        payload = {key: _serialize_value(value) for key, value in row.items()}
        payload["record_type"] = "prime_award"
        return payload

    row = db.execute(
        text(f"SELECT * FROM {SUBAWARD_TABLE} WHERE id = :subaward_id"),
        {"subaward_id": int(subaward_id)},
    ).mappings().one_or_none()
    if row is None:
        return None
    payload = {key: _serialize_value(value) for key, value in row.items()}
    payload["record_type"] = "subaward"
    return payload


def fetch_top_awards(
    db: Session,
    *,
    basis: str,
    geography: str,
    geography_id: str,
    metric: str,
    assistance_type: str | None = None,
    fiscal_year: int | None = None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis)
    normalized_geography = _normalize_geography(geography)
    normalized_metric = _normalize_metric(metric, basis=normalized_basis)
    _ensure_award_tables(db)

    if normalized_geography == "state":
        normalized_geo_id = _normalize_state_code(geography_id)
        if normalized_geo_id is None:
            raise HTTPException(status_code=400, detail="geography_id must be a 2-letter state code")
    else:
        digits = re.sub(r"[^0-9]", "", str(geography_id).strip())
        if len(digits) != 5:
            raise HTTPException(status_code=400, detail="geography_id must be a 5-digit county FIPS")
        normalized_geo_id = digits

    top_limit = max(1, min(int(limit), 50))

    params: dict[str, Any] = {
        "geography_id": normalized_geo_id,
        "limit": top_limit,
    }

    if normalized_basis == "prime":
        filters = [
            "p.recipient_state_code = :geography_id"
            if normalized_geography == "state"
            else "p.recipient_county_fips = :geography_id"
        ]

        assistance_type = _strip_optional(assistance_type)
        if assistance_type:
            filters.append("p.assistance_type_description = :assistance_type")
            params["assistance_type"] = assistance_type
        if fiscal_year is not None:
            filters.append("p.award_latest_action_date_fiscal_year = :fiscal_year")
            params["fiscal_year"] = int(fiscal_year)
        if awarding_office:
            filters.append("p.awarding_office_name = :awarding_office")
            params["awarding_office"] = awarding_office
        if funding_office:
            filters.append("p.funding_office_name = :funding_office")
            params["funding_office"] = funding_office
        if center:
            filters.append("(p.awarding_sub_agency_name = :center OR p.funding_sub_agency_name = :center)")
            params["center"] = center

        order_column = {
            "total_funding": "p.total_funding_amount",
            "total_obligated": "p.total_obligated_amount",
            "total_outlayed": "p.total_outlayed_amount",
            "award_count": "p.total_funding_amount",
        }.get(normalized_metric, "p.total_funding_amount")

        rows = db.execute(
            text(
                f"""
                SELECT
                    p.unique_key AS record_id,
                    'prime_award'::text AS record_type,
                    p.fain,
                    p.recipient_name AS entity_name,
                    p.assistance_type_description,
                    p.total_funding_amount AS amount,
                    p.award_latest_action_date AS latest_action_date,
                    p.recipient_state_code AS state_code,
                    p.recipient_state_name AS state_name,
                    p.recipient_county_fips AS county_fips,
                    p.recipient_county_name AS county_name,
                    p.prime_award_base_transaction_description AS description,
                    p.usaspending_permalink
                FROM {PRIME_TABLE} AS p
                WHERE {' AND '.join(filters)}
                ORDER BY {order_column} DESC NULLS LAST, p.award_latest_action_date DESC NULLS LAST
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    else:
        filters = [
            "s.subawardee_state_code = :geography_id"
            if normalized_geography == "state"
            else "s.subawardee_county_fips = :geography_id"
        ]

        if fiscal_year is not None:
            filters.append("s.subaward_action_date_fiscal_year = :fiscal_year")
            params["fiscal_year"] = int(fiscal_year)
        if awarding_office:
            filters.append("s.prime_award_awarding_office_name = :awarding_office")
            params["awarding_office"] = awarding_office
        if funding_office:
            filters.append("s.prime_award_funding_office_name = :funding_office")
            params["funding_office"] = funding_office
        if center:
            filters.append(
                "(s.prime_award_awarding_sub_agency_name = :center OR s.prime_award_funding_sub_agency_name = :center)"
            )
            params["center"] = center

        rows = db.execute(
            text(
                f"""
                SELECT
                    s.id::text AS record_id,
                    'subaward'::text AS record_type,
                    s.prime_award_fain AS fain,
                    s.subawardee_name AS entity_name,
                    NULL::text AS assistance_type_description,
                    s.subaward_amount AS amount,
                    s.subaward_action_date AS latest_action_date,
                    s.subawardee_state_code AS state_code,
                    s.subawardee_state_name AS state_name,
                    s.subawardee_county_fips AS county_fips,
                    NULL::text AS county_name,
                    COALESCE(s.subaward_description, s.prime_award_base_transaction_description) AS description,
                    s.usaspending_permalink
                FROM {SUBAWARD_TABLE} AS s
                WHERE {' AND '.join(filters)}
                ORDER BY s.subaward_amount DESC NULLS LAST, s.subaward_action_date DESC NULLS LAST
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

    note = (
        "Funds awarded to recipients located in this geography"
        if normalized_basis == "prime"
        else "Subawards reported to entities in this geography"
    )

    return {
        "basis": normalized_basis,
        "geography": normalized_geography,
        "geography_id": normalized_geo_id,
        "metric": normalized_metric,
        "note": note,
        "rows": [
            {
                "record_id": row["record_id"],
                "record_type": row["record_type"],
                "fain": row["fain"],
                "entity_name": row["entity_name"],
                "assistance_type_description": row["assistance_type_description"],
                "amount": _json_number(row["amount"]),
                "latest_action_date": row["latest_action_date"].isoformat() if row["latest_action_date"] else None,
                "state_code": row["state_code"],
                "state_name": row["state_name"],
                "county_fips": row["county_fips"],
                "county_name": row["county_name"],
                "description": row["description"],
                "usaspending_permalink": row["usaspending_permalink"],
            }
            for row in rows
        ],
    }
