from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["history"])


@router.get("/history")
def history_series(
    geography: str = Query(..., min_length=1),
    location_id: str = Query(..., min_length=1),
    measure_id: str = Query(..., min_length=1),
    data_value_type_id: str = Query(default="CrdPrv", min_length=1),
    start_year: int = Query(default=2018, ge=1900, le=2100),
    end_year: int = Query(default=2023, ge=1900, le=2100),
    db: Session = Depends(get_db),
):
    normalized_geography = geography.strip().lower()
    if normalized_geography not in {"county", "tract"}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported geography. Supported values: county, tract",
        )
    if end_year < start_year:
        raise HTTPException(status_code=400, detail="end_year must be >= start_year")

    location_id_value = location_id.strip()
    data_value_type_id_value = data_value_type_id.strip()
    measure_id_value = measure_id.strip()

    params = {
        "location_id": location_id_value,
        "measure_id": measure_id_value,
        "data_value_type_id": data_value_type_id_value,
        "start_year": start_year,
        "end_year": end_year,
    }

    if normalized_geography == "county":
        query = text(
            """
            WITH years AS (
                SELECT generate_series(
                    CAST(:start_year AS integer),
                    CAST(:end_year AS integer)
                )::int AS year
            ),
            selected_measure AS (
                SELECT
                    id,
                    measure,
                    short_question_text,
                    data_value_type
                FROM dim_measure
                WHERE measure_id = :measure_id
                    AND data_value_type_id = :data_value_type_id
                LIMIT 1
            ),
            selected_location AS (
                SELECT county_name, state_abbr
                FROM dim_county
                WHERE location_id = :location_id
                LIMIT 1
            )
            SELECT
                y.year,
                f.data_value AS value,
                sm.measure,
                sm.short_question_text,
                sm.data_value_type,
                sl.county_name AS location_name,
                sl.state_abbr
            FROM years AS y
            LEFT JOIN selected_measure AS sm ON TRUE
            LEFT JOIN selected_location AS sl ON TRUE
            LEFT JOIN fact_estimate_county AS f
                ON f.year = y.year
                AND f.location_id = :location_id
                AND f.measure_dim_id = sm.id
            ORDER BY y.year
            """
        )
    else:
        query = text(
            """
            WITH years AS (
                SELECT generate_series(
                    CAST(:start_year AS integer),
                    CAST(:end_year AS integer)
                )::int AS year
            ),
            selected_meta AS (
                SELECT
                    measure,
                    short_question_text,
                    data_value_type,
                    location_name,
                    state_abbr
                FROM tract_estimates
                WHERE locationid = :location_id
                    AND measure_id = :measure_id
                    AND data_value_type_id = :data_value_type_id
                ORDER BY year DESC
                LIMIT 1
            )
            SELECT
                y.year,
                t.data_value AS value,
                sm.measure,
                sm.short_question_text,
                sm.data_value_type,
                sm.location_name,
                sm.state_abbr
            FROM years AS y
            LEFT JOIN selected_meta AS sm ON TRUE
            LEFT JOIN tract_estimates AS t
                ON t.year = y.year
                AND t.locationid = :location_id
                AND t.measure_id = :measure_id
                AND t.data_value_type_id = :data_value_type_id
            ORDER BY y.year
            """
        )

    rows = db.execute(query, params).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="No history rows found")

    measure_value = None
    short_question_text_value = None
    data_value_type_value = None
    location_name_value = None
    state_abbr_value = None

    for row in rows:
        if measure_value is None and row.get("measure") is not None:
            measure_value = row["measure"]
        if short_question_text_value is None and row.get("short_question_text") is not None:
            short_question_text_value = row["short_question_text"]
        if data_value_type_value is None and row.get("data_value_type") is not None:
            data_value_type_value = row["data_value_type"]
        if location_name_value is None and row.get("location_name") is not None:
            location_name_value = row["location_name"]
        if state_abbr_value is None and row.get("state_abbr") is not None:
            state_abbr_value = row["state_abbr"]

    series = []
    for row in rows:
        value = row["value"]
        series.append(
            {
                "year": int(row["year"]),
                "value": float(value) if value is not None else None,
            }
        )

    return {
        "geography": normalized_geography,
        "location_id": location_id_value,
        "location_name": location_name_value,
        "state_abbr": state_abbr_value,
        "measure_id": measure_id_value,
        "measure": measure_value,
        "short_question_text": short_question_text_value,
        "data_value_type_id": data_value_type_id_value,
        "data_value_type": data_value_type_value,
        "start_year": start_year,
        "end_year": end_year,
        "series": series,
    }
