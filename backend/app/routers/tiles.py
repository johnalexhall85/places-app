# backend/app/routers/tiles.py
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
    data_value_type_id: str = Query(default="CrdPrv"),
    db: Session = Depends(get_db),
) -> Response:
    # NOTE:
    # - Use SQLAlchemy "text()" with :named params (NOT %(...) or :year::int with a raw colon param).
    # - Avoid GROUP BY issues by computing MVT + COUNT via scalar subselects.
    # - Always return bytes for MVT. On error, return an empty tile (b"") but log the exception.

    sql = text(
        """
        /* tiles_v3 */
        WITH bounds AS (
            SELECT ST_TileEnvelope(:z, :x, :y) AS env_3857
        ),
        selected_measure AS (
            SELECT id, measure_id, data_value_type_id
            FROM dim_measure
            WHERE measure_id = (:measure_id)::text
              AND data_value_type_id = (:data_value_type_id)::text
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
                (:year)::int AS year,
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
               AND f.year = :year
               AND f.measure_dim_id = sm.id
            LEFT JOIN dim_county c
                ON c.location_id = b.location_id
            WHERE b.geom IS NOT NULL
              AND ST_Intersects(ST_Transform(b.geom, 3857), bounds.env_3857)
        )
        SELECT
            COALESCE(
                (SELECT ST_AsMVT(t, 'counties', 4096, 'geom') FROM tile t),
                ''::bytea
            ) AS mvt,
            (SELECT COUNT(*) FROM tile) AS tile_total
        """
    )

    params = {
        "z": z,
        "x": x,
        "y": y,
        "measure_id": measure_id,
        "data_value_type_id": data_value_type_id or "CrdPrv",
        "year": year,
    }

    try:
        row = db.execute(sql, params).mappings().one()
        tile_total = row.get("tile_total", 0)

        mvt_data = row.get("mvt", b"")
        if isinstance(mvt_data, memoryview):
            mvt_bytes = mvt_data.tobytes()
        elif isinstance(mvt_data, (bytes, bytearray)):
            mvt_bytes = bytes(mvt_data)
        elif isinstance(mvt_data, str):
            # Shouldn't happen (we cast to bytea), but be safe.
            mvt_bytes = mvt_data.encode("utf-8")
        else:
            mvt_bytes = b""

        logger.info(
            "County tile z=%s x=%s y=%s measure=%s year=%s type=%s rows=%s bytes=%s",
            z,
            x,
            y,
            measure_id,
            year,
            data_value_type_id or "CrdPrv",
            tile_total,
            len(mvt_bytes),
        )

        # Always respond with vector-tile protobuf
        # (Leaflet VectorGrid is fine with application/x-protobuf)
        if request.method == "HEAD":
            return Response(content=b"", media_type="application/x-protobuf")

        return Response(content=mvt_bytes, media_type="application/x-protobuf")

    except Exception:
        logger.exception(
            "Tile query failed z=%s x=%s y=%s measure=%s year=%s type=%s",
            z,
            x,
            y,
            measure_id,
            year,
            data_value_type_id or "CrdPrv",
        )
        # Return an empty tile so the frontend doesn't crash,
        # but the real error will be in the backend logs.
        if request.method == "HEAD":
            return Response(content=b"", media_type="application/x-protobuf")
        return Response(content=b"", media_type="application/x-protobuf")
