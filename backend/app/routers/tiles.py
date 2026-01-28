from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["tiles"])


@router.api_route("/tiles/counties/{z}/{x}/{y}.mvt", methods=["GET", "HEAD"])
def get_county_tiles(
    z: int, x: int, y: int, request: Request, db: Session = Depends(get_db)
) -> Response:
    query = text(
        """
        WITH bounds AS (
            SELECT ST_TileEnvelope(:z, :x, :y) AS env_3857
        ),
        tile AS (
            SELECT
                b.location_id,
                b.geoid,
                b.name,
                b.statefp,
                b.countyfp,
                c.state_abbr,
                c.state_desc,
                ST_AsMVTGeom(
                    ST_Transform(b.geom, 3857),
                    bounds.env_3857,
                    4096,
                    256,
                    true
                ) AS geom
            FROM dim_county_boundary AS b
            LEFT JOIN dim_county AS c
                ON c.location_id = b.location_id
            CROSS JOIN bounds
            WHERE b.geom IS NOT NULL
                AND ST_Intersects(ST_Transform(b.geom, 3857), bounds.env_3857)
        )
        SELECT COALESCE(ST_AsMVT(tile, 'counties', 4096, 'geom'), '') AS mvt
        FROM tile
        """
    )
    result = db.execute(query, {"z": z, "x": x, "y": y}).mappings().one()
    mvt_data = result["mvt"]
    if isinstance(mvt_data, memoryview):
        mvt_bytes = mvt_data.tobytes()
    elif isinstance(mvt_data, str):
        mvt_bytes = mvt_data.encode()
    else:
        mvt_bytes = mvt_data or b""
    response = Response(
        content=mvt_bytes, media_type="application/vnd.mapbox-vector-tile"
    )
    if request.method == "HEAD":
        return Response(
            content=b"", status_code=response.status_code, headers=dict(response.headers)
        )
    return response
