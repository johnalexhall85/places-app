import logging

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["tiles"])
logger = logging.getLogger(__name__)


@router.api_route("/tiles/counties/{z}/{x}/{y}.mvt", methods=["GET", "HEAD"])
def get_county_tiles(
    z: int,
    x: int,
    y: int,
    request: Request,
    measure_id: str = Query(...),
    year: int = Query(...),
    data_value_type_id: str | None = Query(default="CrdPrv"),
    db: Session = Depends(get_db),
) -> Response:
    query = text(
        """
        /* tiles_v2 */
        WITH bounds AS (
            SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS env_3857
        ),
        selected_measure AS (
            SELECT id, measure_id, data_value_type_id
            FROM dim_measure
            WHERE measure_id = %(measure_id)s
              AND data_value_type_id = %(data_value_type_id)s
            LIMIT 1
        ),
        tile AS (
            SELECT
                b.location_id,
                b.name,
                c.state_abbr,
                c.state_desc,
                sm.measure_id,
                sm.data_value_type_id,
                %(year)s::int AS year,
                f.data_value,
                f.low_confidence_limit,
                f.high_confidence_limit,
                ST_AsMVTGeom(
                    ST_Transform(b.geom, 3857),
                    bounds.env_3857,
                    4096,
                    256,
                    true
                ) AS geom
            FROM dim_county_boundary b
            CROSS JOIN bounds
            LEFT JOIN selected_measure sm ON TRUE
            LEFT JOIN fact_estimate_county f
                ON f.location_id = b.location_id
                AND f.year = %(year)s
                AND f.measure_dim_id = sm.id
            LEFT JOIN dim_county c ON c.location_id = b.location_id
            WHERE b.geom IS NOT NULL
              AND ST_Intersects(ST_Transform(b.geom, 3857), bounds.env_3857)
        ),
        tile_count AS (
            SELECT COUNT(*) AS total FROM tile
        )
        SELECT
            COALESCE(ST_AsMVT(tile, 'counties', 4096, 'geom'), ''::bytea) AS mvt,
            tile_count.total AS tile_total
        FROM tile, tile_count
        """
    )
    result = db.execute(
        query,
        {
            "z": z,
            "x": x,
            "y": y,
            "measure_id": measure_id,
            "data_value_type_id": data_value_type_id or "CrdPrv",
            "year": year,
        },
    ).mappings().one()
    logger.info(
        "County tile %s/%s/%s measure=%s year=%s type=%s rows=%s",
        z,
        x,
        y,
        measure_id,
        year,
        data_value_type_id or "CrdPrv",
        result["tile_total"],
    )
    mvt_data = result["mvt"]
    if isinstance(mvt_data, memoryview):
        mvt_bytes = mvt_data.tobytes()
    elif isinstance(mvt_data, str):
        mvt_bytes = mvt_data.encode()
    else:
        mvt_bytes = mvt_data or b""
    response = Response(content=mvt_bytes, media_type="application/x-protobuf")
    if request.method == "HEAD":
        return Response(
            content=b"", status_code=response.status_code, headers=dict(response.headers)
        )
    return response
