from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/geojson", tags=["geojson"])


@router.get("/states")
def states_geojson(db: Session = Depends(get_db)):
    query = text(
        """
        SELECT
            s.state_fips,
            s.state_abbr,
            s.name,
            ST_AsGeoJSON(ST_Transform(s.geom, 4326))::json AS geometry
        FROM public.states AS s
        WHERE s.geom IS NOT NULL
        ORDER BY s.state_abbr
        """
    )

    rows = db.execute(query).mappings().all()

    features = [
        {
            "type": "Feature",
            "geometry": row["geometry"],
            "properties": {
                "state_fips": row["state_fips"],
                "state_abbr": row["state_abbr"],
                "name": row["name"],
            },
        }
        for row in rows
    ]

    return {"type": "FeatureCollection", "features": features}
