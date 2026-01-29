from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/geojson", tags=["geojson"])


@router.get("/states")
def states_geojson(
    measure_id: str | None = Query(default=None),
    year: int | None = Query(default=None),
    data_value_type_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    _ = (measure_id, year, data_value_type_id)
    try:
        query = text(
            """
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(
                    jsonb_build_object(
                        'type', 'Feature',
                        'id', s.state_fips,
                        'properties', jsonb_build_object(
                            'state_fips', s.state_fips,
                            'state_abbr', s.state_abbr,
                            'name', s.name
                        ),
                        'geometry', ST_AsGeoJSON(ST_Transform(s.geom, 4326))::jsonb
                    )
                ), '[]'::jsonb)
            ) AS geojson
            FROM public.states AS s
            WHERE s.geom IS NOT NULL
            """
        )

        row = db.execute(query).mappings().one_or_none()
        if not row or row["geojson"] is None:
            return {"type": "FeatureCollection", "features": []}
        return row["geojson"]
    except Exception as exc:
        message = str(exc)
        if "states" in message and "does not exist" in message:
            return {"type": "FeatureCollection", "features": []}
        raise HTTPException(status_code=500, detail=f"/geojson/states failed: {exc}")
