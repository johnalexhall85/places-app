from __future__ import annotations

import json
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
PRIME_TX_TABLE = cdc_funding_table("prime_transactions")
SUBAWARD_TABLE = cdc_funding_table("subawards")
PRIME_STATE_SUMMARY_TABLE = cdc_funding_table("prime_state_summary")
PRIME_COUNTY_SUMMARY_TABLE = cdc_funding_table("prime_county_summary")
PRIME_TX_STATE_SUMMARY_TABLE = cdc_funding_table("prime_transaction_state_summary")
PRIME_TX_COUNTY_SUMMARY_TABLE = cdc_funding_table("prime_transaction_county_summary")
SUBAWARD_STATE_SUMMARY_TABLE = cdc_funding_table("subaward_state_summary")
SUBAWARD_COUNTY_SUMMARY_TABLE = cdc_funding_table("subaward_county_summary")
AWARD_SCOPE_CLASSIFICATION_TABLE = cdc_funding_table("award_scope_classification")
COUNTY_BOUNDARY_TABLE = places_table("dim_county_boundary")
COUNTY_DIM_TABLE = places_table("dim_county")
STATE_BOUNDARY_TABLE = places_table("dim_state_boundary")

VALID_BASIS = {"prime", "subaward", "all"}
VALID_GEOGRAPHY = {"state", "county"}
VALID_METRICS = {
    "fy_obligated",
    "fy_outlayed_estimated",
    "transaction_count",
    "distinct_award_count",
    "total_subaward",
    "subaward_count",
}
VALID_SCOPE_CLASSIFICATIONS = {
    "local_county",
    "statewide",
    "multi_county",
    "multi_state",
    "unknown",
}

PRIME_METRICS = {
    "fy_obligated": "fy_obligated_amount",
    "fy_outlayed_estimated": "fy_outlayed_amount_estimated",
    "transaction_count": "transaction_count",
    "distinct_award_count": "distinct_award_count",
}

SUBAWARD_METRICS = {
    "total_subaward": "total_subaward_amount",
    "subaward_count": "subaward_count",
}

DOLLAR_METRICS = {
    "fy_obligated",
    "fy_outlayed_estimated",
    "total_subaward",
}

METRIC_LABELS = {
    "fy_obligated": "Fiscal Year Obligated",
    "fy_outlayed_estimated": "Estimated Fiscal Year Outlayed",
    "transaction_count": "Transaction Count",
    "distinct_award_count": "Distinct Awards",
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
    required = [PRIME_TABLE, PRIME_TX_TABLE, SUBAWARD_TABLE]
    for table_name in required:
        if not _table_exists(db, table_name):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Required table {table_name} is missing. "
                    "Run migrations and CDC funding ingestion."
                ),
            )


def _ensure_scope_classification_table(db: Session) -> None:
    if not _table_exists(db, AWARD_SCOPE_CLASSIFICATION_TABLE):
        raise HTTPException(
            status_code=503,
            detail=(
                f"Required table {AWARD_SCOPE_CLASSIFICATION_TABLE} is missing. "
                "Run migrations and CDC funding ingestion."
            ),
        )


def _ensure_required_tables(db: Session, *, basis: str, geography: str) -> None:
    required = (
        [PRIME_TX_STATE_SUMMARY_TABLE, PRIME_TX_COUNTY_SUMMARY_TABLE]
        if basis == "prime"
        else [SUBAWARD_STATE_SUMMARY_TABLE, SUBAWARD_COUNTY_SUMMARY_TABLE]
    )
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
    default_metric = "fy_obligated" if basis == "prime" else "total_subaward"
    token = str(value or default_metric).strip().lower()
    if token not in VALID_METRICS:
        raise HTTPException(
            status_code=400,
            detail=(
                "metric must be one of fy_obligated, fy_outlayed_estimated, transaction_count, "
                "distinct_award_count, total_subaward, or subaward_count"
            ),
        )

    if basis == "prime" and token not in PRIME_METRICS:
        raise HTTPException(
            status_code=400,
            detail=(
                "For basis=prime, metric must be one of fy_obligated, fy_outlayed_estimated, "
                "transaction_count, or distinct_award_count"
            ),
        )
    if basis == "subaward" and token not in SUBAWARD_METRICS:
        raise HTTPException(
            status_code=400,
            detail="For basis=subaward, metric must be one of total_subaward or subaward_count",
        )
    return token


def _normalize_state_code(value: str | None) -> str | None:
    if value is None:
        return None
    letters = re.sub(r"[^A-Za-z]", "", str(value).strip()).upper()
    if len(letters) != 2:
        raise HTTPException(status_code=400, detail="state must be a 2-letter state code")
    return letters


def _normalize_county_fips(value: str | None) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    digits = re.sub(r"[^0-9]", "", token)
    if not digits:
        raise HTTPException(status_code=400, detail="selected_county_fips must contain 5 digits")
    if len(digits) > 5:
        raise HTTPException(status_code=400, detail="selected_county_fips must contain 5 digits")
    digits = digits.zfill(5)
    if len(digits) != 5:
        raise HTTPException(status_code=400, detail="selected_county_fips must contain 5 digits")
    return digits


def _normalize_name_filter(value: str | None) -> str | None:
    token = " ".join(str(value or "").strip().split())
    if not token:
        return None
    return token.lower()


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


def _latest_prime_transaction_fiscal_year(db: Session) -> int | None:
    row = db.execute(
        text(
            f"""
            SELECT MAX(action_date_fiscal_year) AS fiscal_year
            FROM {PRIME_TX_TABLE}
            WHERE action_date_fiscal_year IS NOT NULL
            """
        )
    ).mappings().one()
    value = row.get("fiscal_year")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metric_column(basis: str, metric: str) -> str:
    if basis == "prime":
        return PRIME_METRICS[metric]
    return SUBAWARD_METRICS[metric]


def _summary_table(*, basis: str, geography: str) -> str:
    if basis == "prime":
        return PRIME_TX_STATE_SUMMARY_TABLE if geography == "state" else PRIME_TX_COUNTY_SUMMARY_TABLE
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
            "  SUM(s.fy_obligated_amount) AS fy_obligated_amount,"
            "  SUM(s.fy_outlayed_amount_estimated) AS fy_outlayed_amount_estimated,"
            "  SUM(s.transaction_count) AS transaction_count,"
            "  SUM(s.distinct_award_count) AS distinct_award_count,"
            "  SUM(s.fy_obligated_amount) AS total_funding_amount,"
            "  SUM(s.fy_obligated_amount) AS total_obligated_amount,"
            "  SUM(s.fy_outlayed_amount_estimated) AS total_outlayed_amount,"
            "  SUM(s.distinct_award_count) AS award_count,"
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
        "  0::numeric AS fy_obligated_amount,"
        "  0::numeric AS fy_outlayed_amount_estimated,"
        "  0::numeric AS transaction_count,"
        "  0::numeric AS distinct_award_count,"
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
        table_name = PRIME_TX_TABLE
        years = [
            int(value)
            for value in _distinct(PRIME_TX_TABLE, "action_date_fiscal_year")
            if str(value).isdigit()
        ]
        metric_options = [
            {"value": key, "label": METRIC_LABELS[key]}
            for key in ["fy_obligated", "fy_outlayed_estimated", "distinct_award_count", "transaction_count"]
        ]
        states = db.execute(
            text(
                f"""
                SELECT
                    COALESCE(t.recipient_state_code, p.recipient_state_code) AS code,
                    MAX(COALESCE(NULLIF(t.recipient_state_name, ''), p.recipient_state_name)) AS name
                FROM {PRIME_TX_TABLE} AS t
                LEFT JOIN {PRIME_TABLE} AS p
                    ON p.unique_key = t.assistance_award_unique_key
                WHERE COALESCE(t.recipient_state_code, p.recipient_state_code) IS NOT NULL
                GROUP BY COALESCE(t.recipient_state_code, p.recipient_state_code)
                ORDER BY COALESCE(t.recipient_state_code, p.recipient_state_code)
                """
            )
        ).mappings().all()
        assistance_types = _distinct(PRIME_TX_TABLE, "assistance_type_description")
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
                SELECT action_date_fiscal_year::text AS fiscal_year FROM {PRIME_TX_TABLE}
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
            for key in ["fy_obligated", "fy_outlayed_estimated", "distinct_award_count", "transaction_count"]
        ]
        states = db.execute(
            text(
                f"""
                SELECT
                    COALESCE(t.recipient_state_code, p.recipient_state_code) AS code,
                    MAX(COALESCE(NULLIF(t.recipient_state_name, ''), p.recipient_state_name)) AS name
                FROM {PRIME_TX_TABLE} AS t
                LEFT JOIN {PRIME_TABLE} AS p
                    ON p.unique_key = t.assistance_award_unique_key
                WHERE COALESCE(t.recipient_state_code, p.recipient_state_code) IS NOT NULL
                GROUP BY COALESCE(t.recipient_state_code, p.recipient_state_code)
                UNION
                SELECT subawardee_state_code AS code, MAX(subawardee_state_name) AS name
                FROM {SUBAWARD_TABLE}
                WHERE subawardee_state_code IS NOT NULL
                GROUP BY subawardee_state_code
                ORDER BY code
                """
            )
        ).mappings().all()
        assistance_types = _distinct(PRIME_TX_TABLE, "assistance_type_description")

    if normalized_basis == "prime":
        awarding_offices = _distinct(PRIME_TX_TABLE, "awarding_office_name")
        funding_offices = _distinct(PRIME_TX_TABLE, "funding_office_name")
        centers = _union_distinct(
            PRIME_TX_TABLE,
            "awarding_sub_agency_name",
            PRIME_TX_TABLE,
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
            PRIME_TX_TABLE,
            "awarding_office_name",
            SUBAWARD_TABLE,
            "prime_award_awarding_office_name",
        )
        funding_offices = _union_distinct(
            PRIME_TX_TABLE,
            "funding_office_name",
            SUBAWARD_TABLE,
            "prime_award_funding_office_name",
        )
        centers = _union_distinct(
            PRIME_TX_TABLE,
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
    _ensure_required_tables(db, basis=normalized_basis, geography=normalized_geography)

    effective_fiscal_year = fiscal_year
    if normalized_basis == "prime" and effective_fiscal_year is None:
        effective_fiscal_year = _latest_prime_transaction_fiscal_year(db)

    metric_column = _metric_column(normalized_basis, normalized_metric)
    summary_table = _summary_table(basis=normalized_basis, geography=normalized_geography)
    filter_sql, filter_params = _summary_filters_sql(
        basis=normalized_basis,
        geography=normalized_geography,
        assistance_type=assistance_type,
        fiscal_year=effective_fiscal_year,
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
                    summary.fy_obligated_amount,
                    summary.fy_outlayed_amount_estimated,
                    summary.transaction_count,
                    summary.distinct_award_count,
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
                    summary.fy_obligated_amount,
                    summary.fy_outlayed_amount_estimated,
                    summary.transaction_count,
                    summary.distinct_award_count,
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
                    "fiscal_year": effective_fiscal_year,
                    "fy_obligated_amount": _json_number(row["fy_obligated_amount"]),
                    "fy_outlayed_amount_estimated": _json_number(row["fy_outlayed_amount_estimated"]),
                    "transaction_count": int(row["transaction_count"] or 0),
                    "distinct_award_count": int(row["distinct_award_count"] or 0),
                    "total_funding_amount": _json_number(row["total_funding_amount"]),
                    "total_obligated_amount": _json_number(row["total_obligated_amount"]),
                    "total_outlayed_amount": _json_number(row["total_outlayed_amount"]),
                    "award_count": int(row["award_count"] or 0),
                    "total_subaward_amount": _json_number(row["total_subaward_amount"]),
                    "subaward_count": int(row["subaward_count"] or 0),
                },
            }
        )

    if normalized_basis == "prime":
        if effective_fiscal_year is not None:
            note = (
                f"Prime award fiscal year {effective_fiscal_year} values are based on transaction records. "
                "Obligated amounts reflect transaction activity in that fiscal year."
            )
        else:
            note = "Prime award values are based on transaction records."
    else:
        note = "Subawards reported to entities in this geography"

    return {
        "type": "FeatureCollection",
        "basis": normalized_basis,
        "level": normalized_geography,
        "metric": normalized_metric,
        "features": features,
        "meta": {
            "note": note,
            "metric_label": METRIC_LABELS.get(normalized_metric, normalized_metric),
            "fiscal_year": effective_fiscal_year,
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
    _ensure_required_tables(db, basis=normalized_basis, geography=normalized_geography)

    effective_fiscal_year = fiscal_year
    if normalized_basis == "prime" and effective_fiscal_year is None:
        effective_fiscal_year = _latest_prime_transaction_fiscal_year(db)

    metric_column = _metric_column(normalized_basis, normalized_metric)
    summary_table = _summary_table(basis=normalized_basis, geography=normalized_geography)
    filter_sql, filter_params = _summary_filters_sql(
        basis=normalized_basis,
        geography=normalized_geography,
        assistance_type=assistance_type,
        fiscal_year=effective_fiscal_year,
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
                    summary.fy_obligated_amount,
                    summary.fy_outlayed_amount_estimated,
                    summary.transaction_count,
                    summary.distinct_award_count,
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
                    summary.fy_obligated_amount,
                    summary.fy_outlayed_amount_estimated,
                    summary.transaction_count,
                    summary.distinct_award_count,
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
            sum(int(row.get("distinct_award_count") or 0) for row in rows)
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
        "fiscal_year": effective_fiscal_year,
    }


def search_awards(
    db: Session,
    *,
    q: str | None,
    basis: str,
    assistance_type: str | None,
    fiscal_year: int | None,
    awarding_office: str | None = None,
    funding_office: str | None = None,
    center: str | None = None,
    state: str | None = None,
    selected_state_code: str | None = None,
    selected_state_name: str | None = None,
    selected_county_fips: str | None = None,
    selected_county_name: str | None = None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    normalized_basis = _normalize_basis(basis, allow_all=True)
    normalized_state_filter = _normalize_state_code(state)
    normalized_selected_state_code = _normalize_state_code(selected_state_code)
    normalized_selected_state_name = _normalize_name_filter(selected_state_name)
    normalized_selected_county_fips = _normalize_county_fips(selected_county_fips)
    normalized_selected_county_name = _normalize_name_filter(selected_county_name)
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
        prime_filters.append(
            "EXISTS ("
            f"SELECT 1 FROM {PRIME_TX_TABLE} AS tx "
            "WHERE tx.assistance_award_unique_key = p.unique_key "
            "AND tx.action_date_fiscal_year = :fiscal_year"
            ")"
        )
        sub_filters.append("s.subaward_action_date_fiscal_year = :fiscal_year")

    awarding_office = _strip_optional(awarding_office)
    if awarding_office:
        params["awarding_office"] = awarding_office
        prime_filters.append("p.awarding_office_name = :awarding_office")
        sub_filters.append("s.prime_award_awarding_office_name = :awarding_office")

    funding_office = _strip_optional(funding_office)
    if funding_office:
        params["funding_office"] = funding_office
        prime_filters.append("p.funding_office_name = :funding_office")
        sub_filters.append("s.prime_award_funding_office_name = :funding_office")

    center = _strip_optional(center)
    if center:
        params["center"] = center
        prime_filters.append("(p.awarding_sub_agency_name = :center OR p.funding_sub_agency_name = :center)")
        sub_filters.append(
            "(s.prime_award_awarding_sub_agency_name = :center OR s.prime_award_funding_sub_agency_name = :center)"
        )

    if normalized_state_filter:
        params["state_filter_code"] = normalized_state_filter
        prime_filters.append("p.recipient_state_code = :state_filter_code")
        sub_filters.append("s.subawardee_state_code = :state_filter_code")

    # County scope takes precedence over selected state scope.
    if normalized_selected_county_fips:
        params["selected_county_fips"] = normalized_selected_county_fips
        prime_filters.append("p.recipient_county_fips = :selected_county_fips")
        sub_filters.append("s.subawardee_county_fips = :selected_county_fips")
        if normalized_selected_county_name:
            params["selected_county_name"] = normalized_selected_county_name
            prime_filters.append("LOWER(TRIM(COALESCE(p.recipient_county_name, ''))) = :selected_county_name")
            sub_filters.append(
                "EXISTS ("
                f"SELECT 1 FROM {COUNTY_DIM_TABLE} AS county "
                "WHERE county.location_id = s.subawardee_county_fips "
                "AND LOWER(TRIM(COALESCE(county.county_name, ''))) = :selected_county_name"
                ")"
            )
    elif normalized_selected_state_code:
        params["selected_state_code"] = normalized_selected_state_code
        prime_filters.append("p.recipient_state_code = :selected_state_code")
        sub_filters.append("s.subawardee_state_code = :selected_state_code")
    elif normalized_selected_state_name:
        params["selected_state_name"] = normalized_selected_state_name
        prime_filters.append("LOWER(TRIM(COALESCE(p.recipient_state_name, ''))) = :selected_state_name")
        sub_filters.append("LOWER(TRIM(COALESCE(s.subawardee_state_name, ''))) = :selected_state_name")
    elif normalized_selected_county_name:
        params["selected_county_name"] = normalized_selected_county_name
        prime_filters.append("LOWER(TRIM(COALESCE(p.recipient_county_name, ''))) = :selected_county_name")
        sub_filters.append(
            "EXISTS ("
            f"SELECT 1 FROM {COUNTY_DIM_TABLE} AS county "
            "WHERE county.location_id = s.subawardee_county_fips "
            "AND LOWER(TRIM(COALESCE(county.county_name, ''))) = :selected_county_name"
            ")"
        )

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
            county.county_name AS county_name,
            COALESCE(s.subaward_description, s.prime_award_base_transaction_description) AS description,
            s.usaspending_permalink,
            s.subaward_action_date_fiscal_year AS fiscal_year,
            s.prime_award_awarding_sub_agency_name AS center_name,
            s.prime_award_awarding_office_name AS awarding_office_name,
            s.prime_award_funding_office_name AS funding_office_name
        FROM {SUBAWARD_TABLE} AS s
        LEFT JOIN {COUNTY_DIM_TABLE} AS county
            ON county.location_id = s.subawardee_county_fips
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
        "assistance_type": assistance_type,
        "fiscal_year": int(fiscal_year) if fiscal_year is not None else None,
        "awarding_office": awarding_office,
        "funding_office": funding_office,
        "center": center,
        "state": normalized_state_filter,
        "selected_state_code": normalized_selected_state_code,
        "selected_state_name": normalized_selected_state_name,
        "selected_county_fips": normalized_selected_county_fips,
        "selected_county_name": normalized_selected_county_name,
        "page": page,
        "page_size": page_size,
        "total": int(total_count or 0),
        "results": results,
    }


def fetch_scope_classification_debug(
    db: Session,
    *,
    q: str | None = None,
    scope_classification: str | None = None,
    min_score: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    _ensure_award_tables(db)
    _ensure_scope_classification_table(db)

    normalized_scope = _strip_optional(scope_classification)
    if normalized_scope is not None:
        normalized_scope = normalized_scope.lower()
        if normalized_scope not in VALID_SCOPE_CLASSIFICATIONS:
            allowed = ", ".join(sorted(VALID_SCOPE_CLASSIFICATIONS))
            raise HTTPException(status_code=400, detail=f"scope_classification must be one of {allowed}")

    page = int(page)
    page_size = int(page_size)
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 100")

    normalized_min_score = int(min_score) if min_score is not None else None
    query_token = str(q or "").strip()

    params: dict[str, Any] = {
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    filters: list[str] = []

    if query_token:
        params["q"] = f"%{query_token}%"
        filters.append(
            "("
            "COALESCE(c.award_id_fain, p.fain, '') ILIKE :q "
            "OR COALESCE(p.recipient_name, '') ILIKE :q "
            "OR COALESCE(p.cfda_program_title, '') ILIKE :q "
            "OR COALESCE(p.prime_award_base_transaction_description, '') ILIKE :q"
            ")"
        )

    if normalized_scope:
        params["scope_classification"] = normalized_scope
        filters.append("c.scope_classification = :scope_classification")

    if normalized_min_score is not None:
        params["min_score"] = normalized_min_score
        filters.append("c.scope_score >= :min_score")

    where_sql = ""
    if filters:
        where_sql = "WHERE " + " AND ".join(filters)

    base_sql = (
        f"FROM {AWARD_SCOPE_CLASSIFICATION_TABLE} AS c "
        f"LEFT JOIN {PRIME_TABLE} AS p ON p.unique_key = c.assistance_award_unique_key "
        f"{where_sql}"
    )

    rows = db.execute(
        text(
            f"""
            SELECT
                c.assistance_award_unique_key,
                COALESCE(c.award_id_fain, p.fain) AS award_id_fain,
                p.recipient_name,
                p.cfda_program_title,
                c.scope_classification,
                c.scope_score,
                c.scope_confidence,
                c.reason_codes,
                c.is_allocatable_to_counties,
                c.allocation_method_default,
                c.classifier_version
            {base_sql}
            ORDER BY
                c.scope_score DESC,
                c.scope_classification ASC,
                COALESCE(c.award_id_fain, p.fain) ASC NULLS LAST
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    total = db.execute(
        text(f"SELECT COUNT(*)::integer AS total_count {base_sql}"),
        params,
    ).mappings().one()["total_count"]

    result_rows: list[dict[str, Any]] = []
    for row in rows:
        reason_codes = row.get("reason_codes")
        if isinstance(reason_codes, str):
            try:
                parsed_reason_codes = json.loads(reason_codes)
            except json.JSONDecodeError:
                parsed_reason_codes = [reason_codes]
        elif isinstance(reason_codes, list):
            parsed_reason_codes = reason_codes
        else:
            parsed_reason_codes = []

        result_rows.append(
            {
                "assistance_award_unique_key": row.get("assistance_award_unique_key"),
                "award_id_fain": row.get("award_id_fain"),
                "recipient_name": row.get("recipient_name"),
                "program_title": row.get("cfda_program_title"),
                "scope_classification": row.get("scope_classification"),
                "scope_score": int(row.get("scope_score") or 0),
                "scope_confidence": row.get("scope_confidence"),
                "reason_codes": parsed_reason_codes,
                "is_allocatable_to_counties": bool(row.get("is_allocatable_to_counties")),
                "allocation_method_default": row.get("allocation_method_default"),
                "classifier_version": row.get("classifier_version"),
            }
        )

    return {
        "q": query_token or None,
        "scope_classification": normalized_scope,
        "min_score": normalized_min_score,
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
        "results": result_rows,
    }


def fetch_detail(
    db: Session,
    *,
    prime_unique_key: str | None = None,
    subaward_id: int | None = None,
    fiscal_year: int | None = None,
) -> dict[str, Any] | None:
    _ensure_award_tables(db)
    if bool(prime_unique_key) == bool(subaward_id):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of prime_unique_key or subaward_id",
        )

    if prime_unique_key:
        unique_key = str(prime_unique_key).strip()
        row = db.execute(
            text(f"SELECT * FROM {PRIME_TABLE} WHERE unique_key = :unique_key"),
            {"unique_key": unique_key},
        ).mappings().one_or_none()
        if row is None:
            return None
        payload = {key: _serialize_value(value) for key, value in row.items()}
        payload["record_type"] = "prime_award"
        effective_fiscal_year = fiscal_year
        if effective_fiscal_year is None:
            effective_fiscal_year = _latest_prime_transaction_fiscal_year(db)
        if effective_fiscal_year is not None:
            params = {
                "unique_key": unique_key,
                "fiscal_year": int(effective_fiscal_year),
            }
            fy_summary = db.execute(
                text(
                    f"""
                    WITH tx_ordered AS (
                        SELECT
                            tx.*,
                            LAG(tx.total_outlayed_amount_for_overall_award) OVER (
                                PARTITION BY COALESCE(
                                    tx.assistance_award_unique_key,
                                    tx.assistance_transaction_unique_key
                                )
                                ORDER BY
                                    tx.action_date NULLS FIRST,
                                    COALESCE(tx.modification_number, ''),
                                    tx.assistance_transaction_unique_key
                            ) AS prior_total_outlayed_amount_for_overall_award
                        FROM {PRIME_TX_TABLE} AS tx
                        WHERE tx.assistance_award_unique_key = :unique_key
                    ),
                    tx_year AS (
                        SELECT
                            tx_ordered.assistance_award_unique_key,
                            tx_ordered.federal_action_obligation,
                            CASE
                                WHEN tx_ordered.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                                WHEN tx_ordered.prior_total_outlayed_amount_for_overall_award IS NULL
                                    THEN tx_ordered.total_outlayed_amount_for_overall_award
                                ELSE tx_ordered.total_outlayed_amount_for_overall_award
                                    - tx_ordered.prior_total_outlayed_amount_for_overall_award
                            END AS estimated_outlay_delta
                        FROM tx_ordered
                        WHERE tx_ordered.action_date_fiscal_year = :fiscal_year
                    )
                    SELECT
                        COALESCE(SUM(tx_year.federal_action_obligation), 0) AS fy_obligated_amount,
                        COALESCE(SUM(tx_year.estimated_outlay_delta), 0) AS fy_outlayed_amount_estimated,
                        COUNT(*)::integer AS transaction_count,
                        COUNT(DISTINCT tx_year.assistance_award_unique_key)::integer AS distinct_award_count
                    FROM tx_year
                    """
                ),
                params,
            ).mappings().one()

            fy_transactions = db.execute(
                text(
                    f"""
                    WITH tx_ordered AS (
                        SELECT
                            tx.*,
                            LAG(tx.total_outlayed_amount_for_overall_award) OVER (
                                PARTITION BY COALESCE(
                                    tx.assistance_award_unique_key,
                                    tx.assistance_transaction_unique_key
                                )
                                ORDER BY
                                    tx.action_date NULLS FIRST,
                                    COALESCE(tx.modification_number, ''),
                                    tx.assistance_transaction_unique_key
                            ) AS prior_total_outlayed_amount_for_overall_award
                        FROM {PRIME_TX_TABLE} AS tx
                        WHERE tx.assistance_award_unique_key = :unique_key
                    )
                    SELECT
                        tx_ordered.assistance_transaction_unique_key,
                        tx_ordered.modification_number,
                        tx_ordered.action_date,
                        tx_ordered.action_date_fiscal_year,
                        tx_ordered.federal_action_obligation,
                        tx_ordered.total_outlayed_amount_for_overall_award,
                        CASE
                            WHEN tx_ordered.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                            WHEN tx_ordered.prior_total_outlayed_amount_for_overall_award IS NULL
                                THEN tx_ordered.total_outlayed_amount_for_overall_award
                            ELSE tx_ordered.total_outlayed_amount_for_overall_award
                                - tx_ordered.prior_total_outlayed_amount_for_overall_award
                        END AS estimated_outlay_delta,
                        tx_ordered.transaction_description,
                        tx_ordered.awarding_office_name,
                        tx_ordered.funding_office_name,
                        tx_ordered.recipient_state_code,
                        tx_ordered.prime_award_transaction_recipient_county_fips_code,
                        tx_ordered.usaspending_permalink
                    FROM tx_ordered
                    WHERE tx_ordered.action_date_fiscal_year = :fiscal_year
                    ORDER BY
                        tx_ordered.action_date DESC NULLS LAST,
                        COALESCE(tx_ordered.modification_number, '') DESC,
                        tx_ordered.assistance_transaction_unique_key DESC
                    """
                ),
                params,
            ).mappings().all()

            payload["selected_fiscal_year"] = int(effective_fiscal_year)
            payload["fy_transaction_summary"] = {
                "fy_obligated_amount": _json_number(fy_summary.get("fy_obligated_amount")),
                "fy_outlayed_amount_estimated": _json_number(
                    fy_summary.get("fy_outlayed_amount_estimated")
                ),
                "transaction_count": int(fy_summary.get("transaction_count") or 0),
                "distinct_award_count": int(fy_summary.get("distinct_award_count") or 0),
            }
            payload["fy_transactions"] = [
                {key: _serialize_value(value) for key, value in tx_row.items()}
                for tx_row in fy_transactions
            ]
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
        effective_fiscal_year = fiscal_year
        if effective_fiscal_year is None:
            effective_fiscal_year = _latest_prime_transaction_fiscal_year(db)
        if effective_fiscal_year is not None:
            params["fiscal_year"] = int(effective_fiscal_year)

        filters = [
            "tx.resolved_state_code = :geography_id"
            if normalized_geography == "state"
            else "tx.resolved_county_fips = :geography_id"
        ]
        filters.append("tx.assistance_award_unique_key IS NOT NULL")

        assistance_type = _strip_optional(assistance_type)
        if assistance_type:
            filters.append("tx.assistance_type_description = :assistance_type")
            params["assistance_type"] = assistance_type
        if effective_fiscal_year is not None:
            filters.append("tx.action_date_fiscal_year = :fiscal_year")
        if awarding_office:
            filters.append("tx.awarding_office_name = :awarding_office")
            params["awarding_office"] = awarding_office
        if funding_office:
            filters.append("tx.funding_office_name = :funding_office")
            params["funding_office"] = funding_office
        if center:
            filters.append("(tx.awarding_sub_agency_name = :center OR tx.funding_sub_agency_name = :center)")
            params["center"] = center

        order_column = {
            "fy_obligated": "fy_obligated_amount",
            "fy_outlayed_estimated": "fy_outlayed_amount_estimated",
            "transaction_count": "transaction_count",
            "distinct_award_count": "distinct_award_count",
        }.get(normalized_metric, "fy_obligated_amount")

        rows = db.execute(
            text(
                f"""
                WITH tx_ordered AS (
                    SELECT
                        t.*,
                        COALESCE(t.recipient_state_code, p.recipient_state_code) AS resolved_state_code,
                        COALESCE(NULLIF(t.recipient_state_name, ''), p.recipient_state_name) AS resolved_state_name,
                        COALESCE(
                            t.prime_award_transaction_recipient_county_fips_code,
                            p.recipient_county_fips
                        ) AS resolved_county_fips,
                        COALESCE(NULLIF(t.recipient_county_name, ''), p.recipient_county_name) AS resolved_county_name,
                        LAG(t.total_outlayed_amount_for_overall_award) OVER (
                            PARTITION BY COALESCE(
                                t.assistance_award_unique_key,
                                t.assistance_transaction_unique_key
                            )
                            ORDER BY
                                t.action_date NULLS FIRST,
                                COALESCE(t.modification_number, ''),
                                t.assistance_transaction_unique_key
                        ) AS prior_total_outlayed_amount_for_overall_award
                    FROM {PRIME_TX_TABLE} AS t
                    LEFT JOIN {PRIME_TABLE} AS p
                        ON p.unique_key = t.assistance_award_unique_key
                ),
                tx_filtered AS (
                    SELECT
                        tx.*,
                        CASE
                            WHEN tx.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                            WHEN tx.prior_total_outlayed_amount_for_overall_award IS NULL
                                THEN tx.total_outlayed_amount_for_overall_award
                            ELSE tx.total_outlayed_amount_for_overall_award
                                - tx.prior_total_outlayed_amount_for_overall_award
                        END AS estimated_outlay_delta
                    FROM tx_ordered AS tx
                    WHERE {' AND '.join(filters)}
                )
                SELECT
                    tx_filtered.assistance_award_unique_key AS record_id,
                    'prime_award'::text AS record_type,
                    MAX(COALESCE(p.fain, tx_filtered.award_id_fain)) AS fain,
                    MAX(COALESCE(p.recipient_name, tx_filtered.recipient_name)) AS entity_name,
                    MAX(tx_filtered.assistance_type_description) AS assistance_type_description,
                    COALESCE(SUM(tx_filtered.federal_action_obligation), 0) AS fy_obligated_amount,
                    COALESCE(SUM(tx_filtered.estimated_outlay_delta), 0) AS fy_outlayed_amount_estimated,
                    COUNT(*)::integer AS transaction_count,
                    COUNT(DISTINCT tx_filtered.assistance_award_unique_key)::integer AS distinct_award_count,
                    MAX(p.total_funding_amount) AS lifetime_total_funding_amount,
                    MAX(tx_filtered.action_date) AS latest_action_date,
                    MAX(tx_filtered.resolved_state_code) AS state_code,
                    MAX(tx_filtered.resolved_state_name) AS state_name,
                    MAX(tx_filtered.resolved_county_fips) AS county_fips,
                    MAX(tx_filtered.resolved_county_name) AS county_name,
                    MAX(
                        COALESCE(
                            tx_filtered.transaction_description,
                            tx_filtered.prime_award_base_transaction_description,
                            p.prime_award_base_transaction_description
                        )
                    ) AS description,
                    MAX(COALESCE(tx_filtered.usaspending_permalink, p.usaspending_permalink)) AS usaspending_permalink
                FROM tx_filtered
                LEFT JOIN {PRIME_TABLE} AS p
                    ON p.unique_key = tx_filtered.assistance_award_unique_key
                GROUP BY tx_filtered.assistance_award_unique_key
                ORDER BY {order_column} DESC NULLS LAST, MAX(tx_filtered.action_date) DESC NULLS LAST
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

    if normalized_basis == "prime":
        note = (
            f"Top awards ranked by fiscal year {params.get('fiscal_year')} transaction activity."
            if params.get("fiscal_year") is not None
            else "Top awards ranked by transaction activity."
        )
    else:
        note = "Subawards reported to entities in this geography"

    return {
        "basis": normalized_basis,
        "geography": normalized_geography,
        "geography_id": normalized_geo_id,
        "metric": normalized_metric,
        "fiscal_year": params.get("fiscal_year"),
        "note": note,
        "rows": [
            {
                "record_id": row["record_id"],
                "record_type": row["record_type"],
                "fain": row["fain"],
                "entity_name": row["entity_name"],
                "assistance_type_description": row["assistance_type_description"],
                "amount": _json_number(
                    row["fy_obligated_amount"]
                    if normalized_basis == "prime" and normalized_metric == "fy_obligated"
                    else row["fy_outlayed_amount_estimated"]
                    if normalized_basis == "prime" and normalized_metric == "fy_outlayed_estimated"
                    else row["transaction_count"]
                    if normalized_basis == "prime" and normalized_metric == "transaction_count"
                    else row["distinct_award_count"]
                    if normalized_basis == "prime"
                    else row["amount"]
                ),
                "fy_obligated_amount": _json_number(row.get("fy_obligated_amount")),
                "fy_outlayed_amount_estimated": _json_number(row.get("fy_outlayed_amount_estimated")),
                "transaction_count": int(row.get("transaction_count") or 0),
                "distinct_award_count": int(row.get("distinct_award_count") or 0),
                "lifetime_total_funding_amount": _json_number(row.get("lifetime_total_funding_amount")),
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
