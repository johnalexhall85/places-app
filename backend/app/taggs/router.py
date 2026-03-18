from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.taggs import services

router = APIRouter(prefix="/api/taggs", tags=["taggs"])


@router.get("/filters")
def get_taggs_filters(db: Session = Depends(get_db)):
    return services.list_filter_options(db)


@router.get("/can-mapping/status")
def get_taggs_can_mapping_status(db: Session = Depends(get_db)):
    return services.fetch_can_mapping_status(db)


@router.get("/states/map")
def get_taggs_state_map(
    metric: str = Query(default="total_funding"),
    fiscal_year: int | None = Query(default=None),
    program_office: str | None = Query(default=None),
    aln: str | None = Query(default=None),
    can_code: str | None = Query(default=None),
    funding_stream: str | None = Query(default=None),
    bbox: str | None = Query(default=None),
    zoom: int = Query(default=4),
    limit: int = Query(default=100, ge=1, le=300),
    normalize: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return services.fetch_state_map_geojson(
        db,
        metric=metric,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        bbox=bbox,
        zoom=zoom,
        limit=limit,
        normalize=normalize,
    )


@router.get("/states/legend")
def get_taggs_state_legend(
    metric: str = Query(default="total_funding"),
    fiscal_year: int | None = Query(default=None),
    program_office: str | None = Query(default=None),
    aln: str | None = Query(default=None),
    can_code: str | None = Query(default=None),
    funding_stream: str | None = Query(default=None),
    normalize: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return services.fetch_state_legend(
        db,
        metric=metric,
        fiscal_year=fiscal_year,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        normalize=normalize,
    )


@router.get("/funding-profile/summary")
def get_taggs_funding_profile_summary(
    state: str = Query(..., min_length=2, max_length=2),
    fy: int | None = Query(default=None),
    program_office: str | None = Query(default=None),
    aln: str | None = Query(default=None),
    can_code: str | None = Query(default=None),
    funding_stream: str | None = Query(default=None),
    domestic_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return services.fetch_profile_summary(
        db,
        state=state,
        fiscal_year=fy,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )


@router.get("/funding-profile/categories")
def get_taggs_funding_profile_categories(
    state: str = Query(..., min_length=2, max_length=2),
    fy: int | None = Query(default=None),
    program_office: str | None = Query(default=None),
    aln: str | None = Query(default=None),
    can_code: str | None = Query(default=None),
    funding_stream: str | None = Query(default=None),
    domestic_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return services.fetch_profile_categories(
        db,
        state=state,
        fiscal_year=fy,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )


@router.get("/funding-profile/subcategories")
def get_taggs_funding_profile_subcategories(
    state: str = Query(..., min_length=2, max_length=2),
    fy: int | None = Query(default=None),
    program_office: str | None = Query(default=None),
    aln: str | None = Query(default=None),
    can_code: str | None = Query(default=None),
    funding_stream: str | None = Query(default=None),
    domestic_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return services.fetch_profile_subcategories(
        db,
        state=state,
        fiscal_year=fy,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )


@router.get("/funding-profile/can-breakdown")
def get_taggs_funding_profile_can_breakdown(
    state: str = Query(..., min_length=2, max_length=2),
    fy: int | None = Query(default=None),
    program_office: str | None = Query(default=None),
    aln: str | None = Query(default=None),
    can_code: str | None = Query(default=None),
    funding_stream: str | None = Query(default=None),
    domestic_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return services.fetch_profile_can_breakdown(
        db,
        state=state,
        fiscal_year=fy,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
    )


@router.get("/funding-profile/recipients")
def get_taggs_funding_profile_recipients(
    state: str = Query(..., min_length=2, max_length=2),
    fy: int | None = Query(default=None),
    program_office: str | None = Query(default=None),
    aln: str | None = Query(default=None),
    can_code: str | None = Query(default=None),
    funding_stream: str | None = Query(default=None),
    domestic_only: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return services.fetch_profile_recipients(
        db,
        state=state,
        fiscal_year=fy,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
        page=page,
        page_size=page_size,
    )


@router.get("/funding-profile/counties")
def get_taggs_funding_profile_counties(
    state: str = Query(..., min_length=2, max_length=2),
    fy: int | None = Query(default=None),
    program_office: str | None = Query(default=None),
    aln: str | None = Query(default=None),
    can_code: str | None = Query(default=None),
    funding_stream: str | None = Query(default=None),
    domestic_only: bool = Query(default=True),
    limit: int = Query(default=200, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    return services.fetch_profile_counties(
        db,
        state=state,
        fiscal_year=fy,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
        limit=limit,
    )


@router.get("/funding-profile/details")
def get_taggs_funding_profile_details(
    state: str = Query(..., min_length=2, max_length=2),
    fy: int | None = Query(default=None),
    program_office: str | None = Query(default=None),
    aln: str | None = Query(default=None),
    can_code: str | None = Query(default=None),
    funding_stream: str | None = Query(default=None),
    domestic_only: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="amount"),
    sort_dir: str = Query(default="desc"),
    db: Session = Depends(get_db),
):
    return services.fetch_profile_details(
        db,
        state=state,
        fiscal_year=fy,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.get("/funding-profile/details/export")
def export_taggs_funding_profile_details_csv(
    state: str = Query(..., min_length=2, max_length=2),
    fy: int | None = Query(default=None),
    program_office: str | None = Query(default=None),
    aln: str | None = Query(default=None),
    can_code: str | None = Query(default=None),
    funding_stream: str | None = Query(default=None),
    domestic_only: bool = Query(default=True),
    sort_by: str = Query(default="amount"),
    sort_dir: str = Query(default="desc"),
    db: Session = Depends(get_db),
):
    filename, csv_text = services.export_profile_details_csv(
        db,
        state=state,
        fiscal_year=fy,
        program_office=program_office,
        aln=aln,
        can_code=can_code,
        funding_stream=funding_stream,
        domestic_only=domestic_only,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(content=csv_text, media_type="text/csv", headers=headers)
