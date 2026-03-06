from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.usda_food_access import services

router = APIRouter(prefix="/api/usda/food-access", tags=["usda-food-access"])


@router.get("/variables")
def list_variables(
    q: str | None = Query(default=None),
    include_raw_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return services.list_variables(db, q=q, include_raw_only=include_raw_only)


@router.get("/tract/{geoid}")
def get_tract_detail(geoid: str, db: Session = Depends(get_db)):
    payload = services.fetch_tract_detail(db, geoid=geoid)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No USDA Food Access row for geoid={geoid}")
    return payload


@router.get("/map")
def get_food_access_map(
    variable: str = Query(..., min_length=1),
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    zoom: int = Query(...),
    limit: int = Query(default=5000, ge=1, le=50000),
    mode: str = Query(default="auto"),
    db: Session = Depends(get_db),
):
    return services.fetch_map_geojson(
        db,
        variable=variable,
        bbox=bbox,
        zoom=zoom,
        limit=limit,
        mode=mode,
    )


@router.get("/heat")
def get_food_access_heat(
    variable: str = Query(..., min_length=1),
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    zoom: int = Query(...),
    limit: int = Query(default=2000, ge=1, le=5000),
    agg: str = Query(default="auto"),
    mode: str = Query(default="auto"),
    db: Session = Depends(get_db),
):
    return services.fetch_heat_points(
        db,
        variable=variable,
        bbox=bbox,
        zoom=zoom,
        limit=limit,
        agg=agg,
        mode=mode,
    )


@router.get("/legend")
def get_food_access_legend(
    variable: str = Query(..., min_length=1),
    bins: int = Query(default=5, ge=2, le=9),
    bbox: str | None = Query(default=None),
    mode: str = Query(default="auto"),
    db: Session = Depends(get_db),
):
    return services.fetch_legend(
        db,
        variable=variable,
        bins=bins,
        bbox=bbox,
        mode=mode,
    )
