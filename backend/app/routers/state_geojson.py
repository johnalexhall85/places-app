from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.db_fqtn import places_table

router = APIRouter(tags=["state-boundaries"])


@router.get("/states/boundaries/geojson")
def states_boundary_geojson(
    state_abbr: str | None = Query(default=None, min_length=2, max_length=2),
    simplify: float | None = Query(default=0.02, gt=0, le=0.5),
    db: Session = Depends(get_db),
):
    boundary_table_exists = db.execute(
        text("SELECT to_regclass(:table_name) AS exists"),
        {"table_name": places_table("dim_county_boundary")},
    ).mappings().one()
    if boundary_table_exists["exists"] is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "County boundaries not loaded. Run the boundary loader script to create "
                "dim_county_boundary."
            ),
        )

    state_abbr_value = state_abbr.upper() if state_abbr else None
    state_filter = ""
    params: dict[str, object] = {}

    if state_abbr_value:
        state_filter = "WHERE states.state_abbr = :state_abbr"
        params["state_abbr"] = state_abbr_value

    geometry_expr = "ST_AsGeoJSON(states.geom)::json"
    if simplify is not None:
        geometry_expr = (
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(states.geom, :simplify))::json"
        )
        params["simplify"] = simplify

    query = text(
        f"""
        WITH states AS (
            SELECT
                COALESCE(c.state_abbr, b.statefp) AS state_abbr,
                COALESCE(c.state_desc, b.statefp) AS state_desc,
                ST_UnaryUnion(ST_Collect(b.geom)) AS geom
            FROM dim_county_boundary AS b
            LEFT JOIN dim_county AS c
                ON c.location_id = b.location_id
            WHERE b.geom IS NOT NULL
            GROUP BY
                COALESCE(c.state_abbr, b.statefp),
                COALESCE(c.state_desc, b.statefp)
        )
        SELECT
            states.state_abbr,
            states.state_desc,
            {geometry_expr} AS geometry
        FROM states
        {state_filter}
        ORDER BY states.state_abbr
        """
    )

    rows = db.execute(query, params).mappings().all()

    features = [
        {
            "type": "Feature",
            "geometry": row["geometry"],
            "properties": {
                "state_abbr": row["state_abbr"],
                "state_desc": row["state_desc"],
            },
        }
        for row in rows
    ]

    return {"type": "FeatureCollection", "features": features}
