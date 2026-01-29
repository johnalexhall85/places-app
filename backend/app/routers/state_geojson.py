from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/geojson", tags=["geojson"])

STATES_TABLE = "states"
STATES_GEOM_COL = "geom"
STATE_ID_COL = "state_fips"
STATE_NAME_COL = "name"
STATE_ABBR_COL = "state_abbr"

COUNTIES_TABLE = "dim_county_boundary"
COUNTIES_GEOM_COL = "geom"
COUNTY_ID_COL = "location_id"
COUNTY_NAME_COL = "name"
STATE_ID_FK_COL = "statefp"

MEASURES_TABLE = "dim_measure"
ESTIMATES_TABLE = "fact_estimate_county"
ESTIMATE_MEASURE_COL = "measure_dim_id"
ESTIMATE_LOCATION_COL = "location_id"
ESTIMATE_VALUE_COL = "data_value"

STATE_ESTIMATES_TABLE = "fact_estimate_state"
STATE_ESTIMATE_LOCATION_COL = "state_fips"
STATE_ESTIMATE_MEASURE_COL = "measure_dim_id"
STATE_ESTIMATE_VALUE_COL = "data_value"

BREAK_COUNT = 6


def table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:table_name) AS table_exists"),
        {"table_name": f"public.{table_name}"},
    ).mappings().one()
    return row["table_exists"] is not None


def missing_columns(db: Session, table_name: str, columns: list[str]) -> list[str]:
    rows = db.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).mappings().all()
    existing = {row["column_name"] for row in rows}
    return [column for column in columns if column not in existing]


def compute_breaks(values: list[float]) -> tuple[list[float], float | None, float | None]:
    if not values:
        return [], None, None
    min_value = min(values)
    max_value = max(values)
    if min_value == max_value:
        return [min_value for _ in range(BREAK_COUNT)], min_value, max_value
    step = (max_value - min_value) / (BREAK_COUNT - 1)
    breaks = [min_value + step * idx for idx in range(BREAK_COUNT)]
    return breaks, min_value, max_value


@router.get("/states")
def states_geojson(
    measure_id: str = Query(...),
    year: int = Query(...),
    data_value_type_id: str = Query(...),
    db: Session = Depends(get_db),
):
    if not table_exists(db, STATES_TABLE):
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "breaks": [],
            "min": None,
            "max": None,
            "detail": f"Missing states table: {STATES_TABLE}",
        }

    if not table_exists(db, MEASURES_TABLE):
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "breaks": [],
            "min": None,
            "max": None,
            "detail": f"Missing measures table: {MEASURES_TABLE}",
        }

    state_missing = missing_columns(
        db,
        STATES_TABLE,
        [STATE_ID_COL, STATE_NAME_COL, STATE_ABBR_COL, STATES_GEOM_COL],
    )
    if state_missing:
        raise HTTPException(
            status_code=500,
            detail=f"States table missing columns: {', '.join(state_missing)}",
        )

    params = {
        "measure_id": measure_id,
        "year": year,
        "data_value_type_id": data_value_type_id,
    }

    use_state_estimates = table_exists(db, STATE_ESTIMATES_TABLE)
    if use_state_estimates:
        state_estimate_missing = missing_columns(
            db,
            STATE_ESTIMATES_TABLE,
            [
                STATE_ESTIMATE_LOCATION_COL,
                STATE_ESTIMATE_MEASURE_COL,
                STATE_ESTIMATE_VALUE_COL,
                "year",
            ],
        )
        if state_estimate_missing:
            raise HTTPException(
                status_code=500,
                detail=(
                    "State estimate table missing columns: "
                    f"{', '.join(state_estimate_missing)}"
                ),
            )

        query = text(
            f"""
            WITH selected_measure AS (
                SELECT id
                FROM {MEASURES_TABLE}
                WHERE measure_id = :measure_id
                    AND data_value_type_id = :data_value_type_id
                LIMIT 1
            ),
            state_values AS (
                SELECT
                    e.{STATE_ESTIMATE_LOCATION_COL} AS state_fips,
                    CASE WHEN sm.id IS NULL THEN NULL ELSE e.{STATE_ESTIMATE_VALUE_COL} END AS value
                FROM {STATE_ESTIMATES_TABLE} AS e
                LEFT JOIN selected_measure AS sm ON sm.id = e.{STATE_ESTIMATE_MEASURE_COL}
                WHERE e.year = :year
            )
            SELECT
                s.{STATE_ID_COL} AS state_fips,
                s.{STATE_ABBR_COL} AS state_abbr,
                s.{STATE_NAME_COL} AS name,
                sv.value,
                ST_AsGeoJSON(ST_Transform(s.{STATES_GEOM_COL}, 4326))::jsonb AS geometry
            FROM {STATES_TABLE} AS s
            LEFT JOIN state_values AS sv
                ON sv.state_fips = s.{STATE_ID_COL}
            WHERE s.{STATES_GEOM_COL} IS NOT NULL
            ORDER BY s.{STATE_ID_COL}
            """
        )
    else:
        if not table_exists(db, COUNTIES_TABLE):
            return {
                "geojson": {"type": "FeatureCollection", "features": []},
                "breaks": [],
                "min": None,
                "max": None,
                "detail": f"Missing counties boundary table: {COUNTIES_TABLE}",
            }

        if not table_exists(db, ESTIMATES_TABLE):
            return {
                "geojson": {"type": "FeatureCollection", "features": []},
                "breaks": [],
                "min": None,
                "max": None,
                "detail": f"Missing estimates table: {ESTIMATES_TABLE}",
            }

        county_missing = missing_columns(
            db,
            COUNTIES_TABLE,
            [COUNTY_ID_COL, COUNTY_NAME_COL, STATE_ID_FK_COL, COUNTIES_GEOM_COL],
        )
        if county_missing:
            raise HTTPException(
                status_code=500,
                detail=f"County boundary table missing columns: {', '.join(county_missing)}",
            )

        estimate_missing = missing_columns(
            db,
            ESTIMATES_TABLE,
            [ESTIMATE_LOCATION_COL, ESTIMATE_MEASURE_COL, ESTIMATE_VALUE_COL, "year"],
        )
        if estimate_missing:
            raise HTTPException(
                status_code=500,
                detail=f"Estimate table missing columns: {', '.join(estimate_missing)}",
            )

        query = text(
            f"""
            WITH selected_measure AS (
                SELECT id
                FROM {MEASURES_TABLE}
                WHERE measure_id = :measure_id
                    AND data_value_type_id = :data_value_type_id
                LIMIT 1
            ),
            county_values AS (
                SELECT
                    b.{STATE_ID_FK_COL} AS state_fips,
                    AVG(
                        CASE
                            WHEN sm.id IS NULL THEN NULL
                            ELSE f.{ESTIMATE_VALUE_COL}
                        END
                    ) AS value
                FROM {COUNTIES_TABLE} AS b
                LEFT JOIN selected_measure AS sm ON TRUE
                LEFT JOIN {ESTIMATES_TABLE} AS f
                    ON f.{ESTIMATE_LOCATION_COL} = b.{COUNTY_ID_COL}
                    AND f.year = :year
                    AND f.{ESTIMATE_MEASURE_COL} = sm.id
                GROUP BY b.{STATE_ID_FK_COL}, sm.id
            )
            SELECT
                s.{STATE_ID_COL} AS state_fips,
                s.{STATE_ABBR_COL} AS state_abbr,
                s.{STATE_NAME_COL} AS name,
                cv.value,
                ST_AsGeoJSON(ST_Transform(s.{STATES_GEOM_COL}, 4326))::jsonb AS geometry
            FROM {STATES_TABLE} AS s
            LEFT JOIN county_values AS cv
                ON cv.state_fips = s.{STATE_ID_COL}
            WHERE s.{STATES_GEOM_COL} IS NOT NULL
            ORDER BY s.{STATE_ID_COL}
            """
        )

    rows = db.execute(query, params).mappings().all()
    features = []
    values = []
    for row in rows:
        value = row["value"]
        if value is not None:
            values.append(float(value))
        features.append(
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "state_fips": row["state_fips"],
                    "state_abbr": row["state_abbr"],
                    "name": row["name"],
                    "value": value,
                },
            }
        )

    breaks, min_value, max_value = compute_breaks(values)
    return {
        "geojson": {"type": "FeatureCollection", "features": features},
        "breaks": breaks,
        "min": min_value,
        "max": max_value,
    }


@router.get("/counties")
def counties_geojson(
    measure_id: str = Query(...),
    year: int = Query(...),
    data_value_type_id: str = Query(...),
    db: Session = Depends(get_db),
):
    if not table_exists(db, COUNTIES_TABLE):
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "breaks": [],
            "min": None,
            "max": None,
            "detail": f"Missing counties boundary table: {COUNTIES_TABLE}",
        }

    if not table_exists(db, MEASURES_TABLE):
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "breaks": [],
            "min": None,
            "max": None,
            "detail": f"Missing measures table: {MEASURES_TABLE}",
        }

    if not table_exists(db, ESTIMATES_TABLE):
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "breaks": [],
            "min": None,
            "max": None,
            "detail": f"Missing estimates table: {ESTIMATES_TABLE}",
        }

    county_missing = missing_columns(
        db,
        COUNTIES_TABLE,
        [COUNTY_ID_COL, COUNTY_NAME_COL, STATE_ID_FK_COL, COUNTIES_GEOM_COL],
    )
    if county_missing:
        raise HTTPException(
            status_code=500,
            detail=f"County boundary table missing columns: {', '.join(county_missing)}",
        )

    estimate_missing = missing_columns(
        db,
        ESTIMATES_TABLE,
        [ESTIMATE_LOCATION_COL, ESTIMATE_MEASURE_COL, ESTIMATE_VALUE_COL, "year"],
    )
    if estimate_missing:
        raise HTTPException(
            status_code=500,
            detail=f"Estimate table missing columns: {', '.join(estimate_missing)}",
        )

    params = {
        "measure_id": measure_id,
        "year": year,
        "data_value_type_id": data_value_type_id,
    }

    query = text(
        f"""
        WITH selected_measure AS (
            SELECT id
            FROM {MEASURES_TABLE}
            WHERE measure_id = :measure_id
                AND data_value_type_id = :data_value_type_id
            LIMIT 1
        )
        SELECT
            b.{COUNTY_ID_COL} AS county_fips,
            b.{COUNTY_NAME_COL} AS name,
            b.{STATE_ID_FK_COL} AS state_fips,
            c.state_abbr,
            CASE WHEN sm.id IS NULL THEN NULL ELSE f.{ESTIMATE_VALUE_COL} END AS value,
            ST_AsGeoJSON(ST_Transform(b.{COUNTIES_GEOM_COL}, 4326))::jsonb AS geometry
        FROM {COUNTIES_TABLE} AS b
        LEFT JOIN selected_measure AS sm ON TRUE
        LEFT JOIN {ESTIMATES_TABLE} AS f
            ON f.{ESTIMATE_LOCATION_COL} = b.{COUNTY_ID_COL}
            AND f.year = :year
            AND f.{ESTIMATE_MEASURE_COL} = sm.id
        LEFT JOIN dim_county AS c
            ON c.location_id = b.{COUNTY_ID_COL}
        WHERE b.{COUNTIES_GEOM_COL} IS NOT NULL
        ORDER BY b.{COUNTY_ID_COL}
        """
    )

    rows = db.execute(query, params).mappings().all()
    features = []
    values = []
    for row in rows:
        value = row["value"]
        if value is not None:
            values.append(float(value))
        features.append(
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "county_fips": row["county_fips"],
                    "name": row["name"],
                    "state_fips": row["state_fips"],
                    "state_abbr": row["state_abbr"],
                    "value": value,
                },
            }
        )

    breaks, min_value, max_value = compute_breaks(values)
    return {
        "geojson": {"type": "FeatureCollection", "features": features},
        "breaks": breaks,
        "min": min_value,
        "max": max_value,
    }
