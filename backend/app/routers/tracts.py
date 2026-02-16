from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["tracts"])

STATE_ABBR_TO_FIPS = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "DC": "11",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
    "PR": "72",
}

STATE_FIPS_TO_ABBR = {value: key for key, value in STATE_ABBR_TO_FIPS.items()}


@router.get("/geojson/tracts")
def tracts_geojson(
    year: int = Query(...),
    measure_id: str = Query(...),
    data_value_type_id: str = Query(default="CrdPrv"),
    bbox: str = Query(..., description="west,south,east,north"),
    state_abbr: str | None = Query(default=None, min_length=2, max_length=2),
    county_fips: str | None = Query(default=None, min_length=5, max_length=5),
    simplify: float | None = Query(default=0.001, gt=0, le=0.1),
    limit: int = Query(default=25000, ge=1, le=50000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    shape_table_exists = db.execute(
        text("SELECT to_regclass('public.tract_shapes') AS exists")
    ).mappings().one()
    if shape_table_exists["exists"] is None:
        raise HTTPException(
            status_code=503,
            detail="tract_shapes is missing. Run migrations and import tract shapes.",
        )

    estimate_table_exists = db.execute(
        text("SELECT to_regclass('public.tract_estimates') AS exists")
    ).mappings().one()
    if estimate_table_exists["exists"] is None:
        raise HTTPException(
            status_code=503,
            detail="tract_estimates is missing. Run migrations and ingest tract estimates.",
        )

    try:
        west, south, east, north = (float(value) for value in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid bbox format") from exc
    if west >= east or south >= north:
        raise HTTPException(status_code=400, detail="Invalid bbox bounds")

    state_filter = ""
    county_filter = ""
    params = {
        "year": year,
        "measure_id": measure_id,
        "data_value_type_id": data_value_type_id,
        "west": west,
        "south": south,
        "east": east,
        "north": north,
        "limit": limit,
        "offset": offset,
    }

    normalized_state_abbr = state_abbr.upper() if state_abbr else None
    if normalized_state_abbr:
        statefp = STATE_ABBR_TO_FIPS.get(normalized_state_abbr)
        if statefp is None:
            raise HTTPException(status_code=400, detail="Invalid state_abbr")
        state_filter = "AND s.statefp = :statefp"
        params["statefp"] = statefp

    if county_fips:
        normalized_county_fips = county_fips.strip()
        if len(normalized_county_fips) != 5 or not normalized_county_fips.isdigit():
            raise HTTPException(status_code=400, detail="Invalid county_fips")
        county_statefp = normalized_county_fips[:2]
        county_countyfp = normalized_county_fips[2:]
        if normalized_state_abbr and params.get("statefp") != county_statefp:
            raise HTTPException(
                status_code=400,
                detail="state_abbr does not match county_fips",
            )
        county_filter = "AND s.statefp = :county_statefp AND s.countyfp = :county_countyfp"
        params["county_statefp"] = county_statefp
        params["county_countyfp"] = county_countyfp

    geometry_expr = "ST_AsGeoJSON(s.geom)::json"
    if simplify is not None:
        geometry_expr = (
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(s.geom, :simplify))::json"
        )
        params["simplify"] = simplify

    query = text(
        f"""
        WITH bbox AS (
            SELECT ST_MakeEnvelope(:west, :south, :east, :north, 4326) AS geom
        )
        SELECT
            s.geoid11 AS locationid,
            s.statefp,
            s.countyfp,
            e.year,
            e.measure_id,
            e.data_value_type_id,
            e.data_value AS value,
            e.low_confidence_limit AS low,
            e.high_confidence_limit AS high,
            e.total_population AS pop_total,
            e.total_pop_18_plus AS pop_18plus,
            e.short_question_text,
            e.state_abbr,
            {geometry_expr} AS geometry
        FROM tract_shapes AS s
        CROSS JOIN bbox
        LEFT JOIN tract_estimates AS e
            ON e.locationid = s.geoid11
            AND e.year = :year
            AND e.measure_id = :measure_id
            AND e.data_value_type_id = :data_value_type_id
        WHERE s.geom IS NOT NULL
            AND s.geom && bbox.geom
            AND ST_Intersects(s.geom, bbox.geom)
            {state_filter}
            {county_filter}
        ORDER BY s.geoid11
        LIMIT :limit
        OFFSET :offset
        """
    )

    rows = db.execute(query, params).mappings().all()

    features = []
    for row in rows:
        state_abbr_value = row["state_abbr"] or STATE_FIPS_TO_ABBR.get(row["statefp"])
        county_fips_value = f"{row['statefp']}{row['countyfp']}"
        features.append(
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "locationid": row["locationid"],
                    "year": row["year"] if row["year"] is not None else year,
                    "measure_id": row["measure_id"] or measure_id,
                    "data_value_type_id": row["data_value_type_id"]
                    or data_value_type_id,
                    "value": row["value"],
                    "low": row["low"],
                    "high": row["high"],
                    "pop_total": row["pop_total"],
                    "pop_18plus": row["pop_18plus"],
                    "county_fips": county_fips_value,
                    "state_abbr": state_abbr_value,
                    "short_question_text": row["short_question_text"],
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}
