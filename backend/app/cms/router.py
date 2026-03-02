from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.cms import services
from app.db import get_db

router = APIRouter(prefix="/cms", tags=["cms"])


@router.get("/gv/measures")
def get_gv_measures(
    level: Literal["county", "state", "national"] = Query(default="county"),
    db: Session = Depends(get_db),
):
    normalized_level = services.normalize_geo_level(level)
    if normalized_level is None:
        raise HTTPException(status_code=400, detail="level must be county, state, or national")
    return services.fetch_gv_measures(db, level=normalized_level)


@router.get("/gv/years")
def get_gv_years(
    level: Literal["county", "state", "national"] = Query(default="county"),
    db: Session = Depends(get_db),
):
    normalized_level = services.normalize_geo_level(level)
    if normalized_level is None:
        raise HTTPException(status_code=400, detail="level must be county, state, or national")
    return {"years": services.fetch_gv_years(db, level=normalized_level)}


@router.get("/gv/geo")
def get_gv_geo(
    level: Literal["county", "state", "national"] = Query(default="county"),
    year: int = Query(...),
    age_level: str = Query(default="All"),
    measure_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    normalized_level = services.normalize_geo_level(level)
    if normalized_level is None:
        raise HTTPException(status_code=400, detail="level must be county, state, or national")

    cleaned_measure_id = measure_id.strip()
    if not cleaned_measure_id:
        raise HTTPException(status_code=400, detail="measure_id is required")

    rows = services.fetch_gv_geo_rows(
        db,
        level=normalized_level,
        year=year,
        age_level=age_level,
        measure_id=cleaned_measure_id,
    )
    return rows


@router.get("/gv/county/{county_fips}")
def get_gv_county(
    county_fips: str,
    year: int = Query(...),
    age_level: str = Query(default="All"),
    measure_ids: str = Query(...),
    db: Session = Depends(get_db),
):
    normalized_fips = services.normalize_county_fips(county_fips)
    if normalized_fips is None:
        raise HTTPException(status_code=400, detail="county_fips must be a valid 5-digit code")

    try:
        parsed_measure_ids = services.parse_required_measure_ids_csv(measure_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    measures = services.fetch_gv_county_measures(
        db,
        county_fips=normalized_fips,
        year=year,
        age_level=age_level,
        measure_ids=parsed_measure_ids,
    )
    return {
        "county_fips": normalized_fips,
        "year": int(year),
        "age_level": age_level,
        "measures": measures,
    }


@router.get("/ssp/county/{county_fips}")
def get_ssp_county(
    county_fips: str,
    year: int = Query(...),
    enrollment_type: str = Query(default="all"),
    assign_window: Literal["calendar", "offset"] = Query(default="offset"),
    measure_ids: str = Query(...),
    db: Session = Depends(get_db),
):
    normalized_fips = services.normalize_county_fips(county_fips)
    if normalized_fips is None:
        raise HTTPException(status_code=400, detail="county_fips must be a valid 5-digit code")

    normalized_assign_window = services.normalize_assign_window(assign_window)
    if normalized_assign_window is None:
        raise HTTPException(status_code=400, detail="assign_window must be calendar or offset")

    cleaned_enrollment_type = str(enrollment_type or "").strip().lower() or "all"
    try:
        parsed_measure_ids = services.parse_required_measure_ids_csv(measure_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    measures = services.fetch_ssp_county_measures(
        db,
        county_fips=normalized_fips,
        year=year,
        enrollment_type=cleaned_enrollment_type,
        assign_window=normalized_assign_window,
        measure_ids=parsed_measure_ids,
    )
    return {
        "county_fips": normalized_fips,
        "year": int(year),
        "enrollment_type": cleaned_enrollment_type,
        "assign_window": normalized_assign_window,
        "measures": measures,
    }
