from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.usda_food_env import services

router = APIRouter(prefix="/api/usda/food-environment", tags=["usda-food-environment"])


@router.get("/variables")
def list_variables(
    q: str | None = Query(default=None),
    level: Literal["county", "state", "all"] = Query(default="county"),
    include_archival: bool = Query(default=False),
    year: int | None = Query(default=None),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return services.list_variables(
        db,
        q=q,
        level=level,
        include_archival=include_archival,
        year=year,
        category=category,
    )


@router.get("/county/{geoid}")
def get_county_detail(geoid: str, db: Session = Depends(get_db)):
    payload = services.fetch_county_detail(db, geoid=geoid)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No USDA Food Environment row for geoid={geoid}")
    return payload


@router.get("/state/{state_fips}")
def get_state_detail(state_fips: str, db: Session = Depends(get_db)):
    payload = services.fetch_state_detail(db, state_fips=state_fips)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No USDA Food Environment row for state_fips={state_fips}")
    return payload


@router.get("/map")
def get_food_environment_map(
    variable: str = Query(..., min_length=1),
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    zoom: int = Query(...),
    level: Literal["auto", "county", "state"] = Query(default="auto"),
    limit: int = Query(default=5000, ge=1, le=50000),
    db: Session = Depends(get_db),
):
    return services.fetch_map_geojson(
        db,
        variable=variable,
        bbox=bbox,
        zoom=zoom,
        level=level,
        limit=limit,
    )


@router.get("/legend")
def get_food_environment_legend(
    variable: str = Query(..., min_length=1),
    bbox: str | None = Query(default=None),
    level: Literal["auto", "county", "state"] = Query(default="auto"),
    db: Session = Depends(get_db),
):
    return services.fetch_legend(
        db,
        variable=variable,
        bbox=bbox,
        level=level,
    )
