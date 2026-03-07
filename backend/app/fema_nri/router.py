from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.fema_nri import services

router = APIRouter(prefix="/api/fema/nri", tags=["fema-nri"])


@router.get("/measures")
def get_measure_catalog(
    level: Literal["county", "tract", "all"] = Query(default="all"),
    include_hidden: bool = Query(default=False),
):
    return services.list_measure_catalog(level=level, include_hidden=include_hidden)


@router.get("/map")
def get_fema_nri_map(
    measure: str = Query(..., min_length=1),
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    zoom: int = Query(...),
    level: Literal["auto", "county", "tract"] = Query(default="auto"),
    limit: int = Query(default=5000, ge=1, le=50000),
    db: Session = Depends(get_db),
):
    return services.fetch_map_geojson(
        db,
        measure=measure,
        bbox=bbox,
        zoom=zoom,
        level=level,
        limit=limit,
    )


@router.get("/legend")
def get_fema_nri_legend(
    measure: str = Query(..., min_length=1),
    bbox: str | None = Query(default=None),
    level: Literal["auto", "county", "tract"] = Query(default="auto"),
    db: Session = Depends(get_db),
):
    return services.fetch_legend(
        db,
        measure=measure,
        bbox=bbox,
        level=level,
    )


@router.get("/detail")
def get_fema_nri_detail(
    level: Literal["county", "tract"] = Query(...),
    geoid: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    payload = services.fetch_detail(db, level=level, geoid=geoid)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No FEMA NRI row for level={level}, geoid={geoid}")
    return payload
