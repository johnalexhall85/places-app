from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.params import Param
from sqlalchemy.orm import Session

from app.cdc_funding import intelligence
from app.cdc_funding import services
from app.cdc_funding import v11_emergency
from app.db import get_db

router = APIRouter(prefix="/api/cdc/funding", tags=["cdc-funding"])
FundingModeQuery = Literal["raw_total", "chip_normalized", "chip_normalized_v1_1"]


def _resolve_query_value(value):
    return None if isinstance(value, Param) else value


def _resolve_funding_type(funding_type, appropriation_type):
    effective_funding_type = _resolve_query_value(funding_type)
    effective_appropriation_type = _resolve_query_value(appropriation_type)
    if effective_funding_type is None:
        if effective_appropriation_type in {"covid_emergency", "other_emergency"}:
            return "emergency_response"
        if effective_appropriation_type == "regular":
            return "non_emergency_program"
    return effective_funding_type


@router.get("/methodology/summary")
def get_cdc_funding_methodology_summary():
    return services.fetch_methodology_display_summary()


@router.get("/map")
def get_cdc_funding_map(
    fiscal_year: int | None = Query(default=None),
    metric: str | None = Query(default=None),
    funding_type: str | None = Query(default=None),
    funding_mode: FundingModeQuery | None = Query(default=None),
    cdc_center: str | None = Query(default=None),
    program_area: str | None = Query(default=None),
    mechanism: str | None = Query(default=None),
    recipient_type: str | None = Query(default=None),
    geography_level: Literal["county", "state", "national"] | None = Query(default=None),
    time_aggregation: Literal["single_fiscal_year", "multi_year_total", "multi_year_average"] | None = Query(
        default=None
    ),
    geography: Literal["state", "county", "national"] | None = Query(default=None),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] | None = Query(
        default=None
    ),
    center: str | None = Query(default=None),
    bbox: str | None = Query(default=None),
    zoom: int = Query(default=6),
    limit: int = Query(default=6000, ge=1, le=50000),
    basis: str | None = Query(default=None),
    funding_geography_mode: str | None = Query(default=None),
    display_mode: str | None = Query(default=None),
    assistance_type: str | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    del zoom, basis, funding_geography_mode, display_mode, assistance_type, awarding_office, funding_office, office, state
    fiscal_year = _resolve_query_value(fiscal_year)
    metric = _resolve_query_value(metric)
    cdc_center = _resolve_query_value(cdc_center)
    program_area = _resolve_query_value(program_area)
    mechanism = _resolve_query_value(mechanism)
    recipient_type = _resolve_query_value(recipient_type)
    geography_level = _resolve_query_value(geography_level)
    geography = _resolve_query_value(geography)
    time_aggregation = _resolve_query_value(time_aggregation)
    center = _resolve_query_value(center)
    bbox = _resolve_query_value(bbox)
    effective_funding_type = _resolve_funding_type(funding_type, appropriation_type)
    return intelligence.fetch_map_geojson(
        db,
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=effective_funding_type,
        funding_mode=_resolve_query_value(funding_mode),
        cdc_center=cdc_center or center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        geography_level=geography_level or geography,
        time_aggregation=time_aggregation,
        bbox=bbox,
        limit=limit,
    )


@router.get("/legend")
def get_cdc_funding_legend(
    fiscal_year: int | None = Query(default=None),
    metric: str | None = Query(default=None),
    funding_type: str | None = Query(default=None),
    funding_mode: FundingModeQuery | None = Query(default=None),
    cdc_center: str | None = Query(default=None),
    program_area: str | None = Query(default=None),
    mechanism: str | None = Query(default=None),
    recipient_type: str | None = Query(default=None),
    geography_level: Literal["county", "state", "national"] | None = Query(default=None),
    time_aggregation: Literal["single_fiscal_year", "multi_year_total", "multi_year_average"] | None = Query(
        default=None
    ),
    geography: Literal["state", "county", "national"] | None = Query(default=None),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] | None = Query(
        default=None
    ),
    center: str | None = Query(default=None),
    bbox: str | None = Query(default=None),
    basis: str | None = Query(default=None),
    funding_geography_mode: str | None = Query(default=None),
    display_mode: str | None = Query(default=None),
    assistance_type: str | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    del basis, funding_geography_mode, display_mode, assistance_type, awarding_office, funding_office, office, state
    fiscal_year = _resolve_query_value(fiscal_year)
    metric = _resolve_query_value(metric)
    cdc_center = _resolve_query_value(cdc_center)
    program_area = _resolve_query_value(program_area)
    mechanism = _resolve_query_value(mechanism)
    recipient_type = _resolve_query_value(recipient_type)
    geography_level = _resolve_query_value(geography_level)
    geography = _resolve_query_value(geography)
    time_aggregation = _resolve_query_value(time_aggregation)
    center = _resolve_query_value(center)
    bbox = _resolve_query_value(bbox)
    effective_funding_type = _resolve_funding_type(funding_type, appropriation_type)
    return intelligence.fetch_legend_stats(
        db,
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=effective_funding_type,
        funding_mode=_resolve_query_value(funding_mode),
        cdc_center=cdc_center or center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        geography_level=geography_level or geography,
        time_aggregation=time_aggregation,
        bbox=bbox,
    )


@router.get("/national")
def get_cdc_funding_national_summary(
    fiscal_year: int | None = Query(default=None),
    metric: str | None = Query(default=None),
    funding_type: str | None = Query(default=None),
    funding_mode: FundingModeQuery | None = Query(default=None),
    cdc_center: str | None = Query(default=None),
    program_area: str | None = Query(default=None),
    mechanism: str | None = Query(default=None),
    recipient_type: str | None = Query(default=None),
    time_aggregation: Literal["single_fiscal_year", "multi_year_total", "multi_year_average"] | None = Query(
        default=None
    ),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] | None = Query(
        default=None
    ),
    center: str | None = Query(default=None),
    basis: str | None = Query(default=None),
    funding_geography_mode: str | None = Query(default=None),
    display_mode: str | None = Query(default=None),
    assistance_type: str | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    del basis, funding_geography_mode, display_mode, assistance_type, awarding_office, funding_office, office
    fiscal_year = _resolve_query_value(fiscal_year)
    metric = _resolve_query_value(metric)
    cdc_center = _resolve_query_value(cdc_center)
    program_area = _resolve_query_value(program_area)
    mechanism = _resolve_query_value(mechanism)
    recipient_type = _resolve_query_value(recipient_type)
    time_aggregation = _resolve_query_value(time_aggregation)
    center = _resolve_query_value(center)
    effective_funding_type = _resolve_funding_type(funding_type, appropriation_type)
    return intelligence.fetch_national_summary(
        db,
        fiscal_year=fiscal_year,
        metric=metric,
        funding_type=effective_funding_type,
        funding_mode=_resolve_query_value(funding_mode),
        cdc_center=cdc_center or center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )


@router.get("/filters")
def get_cdc_funding_filters(
    basis: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    del basis
    return intelligence.list_filter_options(db)


@router.get("/profile/summary")
def get_cdc_state_profile_summary(
    state: str = Query(..., min_length=2, max_length=2),
    fiscal_year: int | None = Query(default=None),
    fy: int | None = Query(default=None),
    metric: str | None = Query(default=None),
    funding_type: str | None = Query(default=None),
    funding_mode: FundingModeQuery | None = Query(default=None),
    cdc_center: str | None = Query(default=None),
    program_area: str | None = Query(default=None),
    mechanism: str | None = Query(default=None),
    recipient_type: str | None = Query(default=None),
    time_aggregation: Literal["single_fiscal_year", "multi_year_total", "multi_year_average"] | None = Query(
        default=None
    ),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] | None = Query(
        default=None
    ),
    center: str | None = Query(default=None),
    basis: str | None = Query(default=None),
    funding_geography_mode: str | None = Query(default=None),
    assistance_type: str | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    del basis, funding_geography_mode, assistance_type, awarding_office, funding_office, office
    state = _resolve_query_value(state)
    fiscal_year = _resolve_query_value(fiscal_year)
    fy = _resolve_query_value(fy)
    metric = _resolve_query_value(metric)
    cdc_center = _resolve_query_value(cdc_center)
    program_area = _resolve_query_value(program_area)
    mechanism = _resolve_query_value(mechanism)
    recipient_type = _resolve_query_value(recipient_type)
    time_aggregation = _resolve_query_value(time_aggregation)
    center = _resolve_query_value(center)
    effective_funding_type = _resolve_funding_type(funding_type, appropriation_type)
    return intelligence.fetch_state_profile_summary(
        db,
        state=state,
        fiscal_year=fiscal_year if fiscal_year is not None else fy,
        metric=metric,
        funding_type=effective_funding_type,
        funding_mode=_resolve_query_value(funding_mode),
        cdc_center=cdc_center or center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )


@router.get("/profile/overview")
def get_cdc_state_profile_overview(
    state: str = Query(..., min_length=2, max_length=2),
    fiscal_year: int | None = Query(default=None),
    fy: int | None = Query(default=None),
    metric: str | None = Query(default=None),
    funding_type: str | None = Query(default=None),
    funding_mode: FundingModeQuery | None = Query(default=None),
    cdc_center: str | None = Query(default=None),
    program_area: str | None = Query(default=None),
    mechanism: str | None = Query(default=None),
    recipient_type: str | None = Query(default=None),
    time_aggregation: Literal["single_fiscal_year", "multi_year_total", "multi_year_average"] | None = Query(
        default=None
    ),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] | None = Query(
        default=None
    ),
    center: str | None = Query(default=None),
    basis: str | None = Query(default=None),
    funding_geography_mode: str | None = Query(default=None),
    assistance_type: str | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    del basis, funding_geography_mode, assistance_type, awarding_office, funding_office, office
    state = _resolve_query_value(state)
    fiscal_year = _resolve_query_value(fiscal_year)
    fy = _resolve_query_value(fy)
    metric = _resolve_query_value(metric)
    cdc_center = _resolve_query_value(cdc_center)
    program_area = _resolve_query_value(program_area)
    mechanism = _resolve_query_value(mechanism)
    recipient_type = _resolve_query_value(recipient_type)
    time_aggregation = _resolve_query_value(time_aggregation)
    center = _resolve_query_value(center)
    effective_funding_type = _resolve_funding_type(funding_type, appropriation_type)
    return intelligence.fetch_state_profile_overview(
        db,
        state=state,
        fiscal_year=fiscal_year if fiscal_year is not None else fy,
        metric=metric,
        funding_type=effective_funding_type,
        funding_mode=_resolve_query_value(funding_mode),
        cdc_center=cdc_center or center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )


@router.get("/profile/categories")
def get_cdc_state_profile_categories(
    state: str = Query(..., min_length=2, max_length=2),
    fiscal_year: int | None = Query(default=None),
    fy: int | None = Query(default=None),
    funding_type: str | None = Query(default=None),
    funding_mode: FundingModeQuery | None = Query(default=None),
    cdc_center: str | None = Query(default=None),
    program_area: str | None = Query(default=None),
    mechanism: str | None = Query(default=None),
    recipient_type: str | None = Query(default=None),
    time_aggregation: Literal["single_fiscal_year", "multi_year_total", "multi_year_average"] | None = Query(
        default=None
    ),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] | None = Query(
        default=None
    ),
    center: str | None = Query(default=None),
    basis: str | None = Query(default=None),
    funding_geography_mode: str | None = Query(default=None),
    assistance_type: str | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    del basis, funding_geography_mode, assistance_type, awarding_office, funding_office, office
    state = _resolve_query_value(state)
    fiscal_year = _resolve_query_value(fiscal_year)
    fy = _resolve_query_value(fy)
    cdc_center = _resolve_query_value(cdc_center)
    program_area = _resolve_query_value(program_area)
    mechanism = _resolve_query_value(mechanism)
    recipient_type = _resolve_query_value(recipient_type)
    time_aggregation = _resolve_query_value(time_aggregation)
    center = _resolve_query_value(center)
    effective_funding_type = _resolve_funding_type(funding_type, appropriation_type)
    return intelligence.fetch_state_profile_categories(
        db,
        state=state,
        fiscal_year=fiscal_year if fiscal_year is not None else fy,
        funding_type=effective_funding_type,
        funding_mode=_resolve_query_value(funding_mode),
        cdc_center=cdc_center or center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )


@router.get("/profile/subcategories")
def get_cdc_state_profile_subcategories(
    state: str = Query(..., min_length=2, max_length=2),
    fiscal_year: int | None = Query(default=None),
    fy: int | None = Query(default=None),
    funding_type: str | None = Query(default=None),
    funding_mode: FundingModeQuery | None = Query(default=None),
    cdc_center: str | None = Query(default=None),
    program_area: str | None = Query(default=None),
    mechanism: str | None = Query(default=None),
    recipient_type: str | None = Query(default=None),
    time_aggregation: Literal["single_fiscal_year", "multi_year_total", "multi_year_average"] | None = Query(
        default=None
    ),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] | None = Query(
        default=None
    ),
    center: str | None = Query(default=None),
    basis: str | None = Query(default=None),
    funding_geography_mode: str | None = Query(default=None),
    assistance_type: str | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    del basis, funding_geography_mode, assistance_type, awarding_office, funding_office, office
    state = _resolve_query_value(state)
    fiscal_year = _resolve_query_value(fiscal_year)
    fy = _resolve_query_value(fy)
    cdc_center = _resolve_query_value(cdc_center)
    program_area = _resolve_query_value(program_area)
    mechanism = _resolve_query_value(mechanism)
    recipient_type = _resolve_query_value(recipient_type)
    time_aggregation = _resolve_query_value(time_aggregation)
    center = _resolve_query_value(center)
    effective_funding_type = _resolve_funding_type(funding_type, appropriation_type)
    return intelligence.fetch_state_profile_subcategories(
        db,
        state=state,
        fiscal_year=fiscal_year if fiscal_year is not None else fy,
        funding_type=effective_funding_type,
        funding_mode=_resolve_query_value(funding_mode),
        cdc_center=cdc_center or center,
        program_area=program_area,
        mechanism=mechanism,
        recipient_type=recipient_type,
        time_aggregation=time_aggregation,
    )


@router.get("/profile/details")
def get_cdc_state_profile_details(
    state: str = Query(..., min_length=2, max_length=2),
    funding_mode: FundingModeQuery = Query(default="chip_normalized_v1_1"),
    basis: Literal["prime", "subaward"] = Query(default="prime"),
    funding_geography_mode: Literal["recipient_location", "statewide_allocation"] = Query(
        default="recipient_location"
    ),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] = Query(
        default="all"
    ),
    assistance_type: str | None = Query(default=None),
    fiscal_year: int | None = Query(default=None),
    fy: int | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    center: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="amount"),
    sort_dir: str = Query(default="desc"),
    db: Session = Depends(get_db),
):
    office_value = str(office or "").strip() or None
    awarding_office_value = str(awarding_office or "").strip() or office_value
    funding_office_value = str(funding_office or "").strip() or office_value
    resolved_funding_mode = _resolve_query_value(funding_mode) or "chip_normalized_v1_1"
    emergency_support = v11_emergency.support_status(
        funding_mode=resolved_funding_mode,
        funding_type="total_cdc_funding",
        cdc_center=None,
        program_area=None,
        mechanism=None,
        recipient_type=None,
    )
    if emergency_support.enabled and resolved_funding_mode == "raw_total":
        return v11_emergency.fetch_state_profile_details(
            db,
            state=state,
            fiscal_year=fiscal_year if fiscal_year is not None else fy,
            q=q,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    return services.fetch_state_profile_details(
        db,
        state=state,
        basis=basis,
        funding_geography_mode=funding_geography_mode,
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year if fiscal_year is not None else fy,
        normalize=resolved_funding_mode != "raw_total",
        normalization_funding_mode=resolved_funding_mode,
        awarding_office=awarding_office_value,
        funding_office=funding_office_value,
        center=center,
        q=q,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.get("/search")
def search_cdc_funding(
    q: str | None = Query(default=None),
    basis: Literal["all", "prime", "subaward"] = Query(default="all"),
    funding_geography_mode: Literal["recipient_location", "statewide_allocation"] = Query(
        default="recipient_location"
    ),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] = Query(
        default="all"
    ),
    assistance_type: str | None = Query(default=None),
    fiscal_year: int | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    funding_cio: str | None = Query(default=None),
    office: str | None = Query(default=None),
    center: str | None = Query(default=None),
    state: str | None = Query(default=None),
    selected_state_code: str | None = Query(default=None),
    selected_state_name: str | None = Query(default=None),
    selected_county_fips: str | None = Query(default=None),
    selected_county_name: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    office_value = str(office or "").strip() or None
    awarding_office_value = str(awarding_office or "").strip() or office_value
    funding_office_value = str(funding_office or funding_cio or "").strip() or office_value
    return services.search_awards(
        db,
        q=q,
        basis=basis,
        funding_geography_mode=funding_geography_mode,
        appropriation_type=appropriation_type,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office_value,
        funding_office=funding_office_value,
        center=center,
        state=state,
        selected_state_code=selected_state_code,
        selected_state_name=selected_state_name,
        selected_county_fips=selected_county_fips,
        selected_county_name=selected_county_name,
        page=page,
        page_size=page_size,
    )


@router.get("/detail")
def get_cdc_funding_detail(
    prime_unique_key: str | None = Query(default=None),
    subaward_id: int | None = Query(default=None),
    fiscal_year: int | None = Query(default=None),
    funding_geography_mode: Literal["recipient_location", "statewide_allocation"] = Query(
        default="recipient_location"
    ),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] = Query(
        default="all"
    ),
    selected_county_fips: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    payload = services.fetch_detail(
        db,
        prime_unique_key=prime_unique_key,
        subaward_id=subaward_id,
        fiscal_year=fiscal_year,
        funding_geography_mode=funding_geography_mode,
        appropriation_type=appropriation_type,
        selected_county_fips=selected_county_fips,
    )
    if payload is None:
        if prime_unique_key:
            raise HTTPException(status_code=404, detail=f"No CDC prime award for unique_key={prime_unique_key}")
        raise HTTPException(status_code=404, detail=f"No CDC subaward for id={subaward_id}")
    return payload


@router.get("/scope-classification/debug")
def get_cdc_scope_classification_debug(
    q: str | None = Query(default=None),
    scope_classification: str | None = Query(default=None),
    min_score: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return services.fetch_scope_classification_debug(
        db,
        q=q,
        scope_classification=scope_classification,
        min_score=min_score,
        page=page,
        page_size=page_size,
    )


@router.get("/allocation/debug")
def get_cdc_allocation_debug(
    assistance_award_unique_key: str | None = Query(default=None),
    award_id_fain: str | None = Query(default=None),
    fiscal_year: int | None = Query(default=None),
    limit_counties: int = Query(default=10, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return services.fetch_allocation_debug(
        db,
        assistance_award_unique_key=assistance_award_unique_key,
        award_id_fain=award_id_fain,
        fiscal_year=fiscal_year,
        limit_counties=limit_counties,
    )


@router.get("/mode-diagnostics")
def get_cdc_funding_mode_diagnostics(
    fiscal_year: list[int] | None = Query(default=None),
    state: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return intelligence.fetch_mode_diagnostics(
        db,
        fiscal_years=fiscal_year,
        states=state,
    )


@router.get("/top")
def get_cdc_funding_top(
    basis: Literal["prime", "subaward"] = Query(default="prime"),
    geography: Literal["state", "county"] = Query(default="county"),
    funding_geography_mode: Literal["recipient_location", "statewide_allocation"] = Query(
        default="recipient_location"
    ),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] = Query(
        default="all"
    ),
    geography_id: str = Query(..., min_length=1),
    metric: str | None = Query(default=None),
    assistance_type: str | None = Query(default=None),
    fiscal_year: int | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    office: str | None = Query(default=None),
    center: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    office_value = str(office or "").strip() or None
    awarding_office_value = str(awarding_office or "").strip() or office_value
    funding_office_value = str(funding_office or "").strip() or office_value
    return services.fetch_top_awards(
        db,
        basis=basis,
        geography=geography,
        funding_geography_mode=funding_geography_mode,
        appropriation_type=appropriation_type,
        geography_id=geography_id,
        metric=metric,
        assistance_type=assistance_type,
        fiscal_year=fiscal_year,
        awarding_office=awarding_office_value,
        funding_office=funding_office_value,
        center=center,
        limit=limit,
    )


@router.get("/trend")
def get_cdc_funding_trend(
    basis: Literal["prime", "subaward"] = Query(default="prime"),
    geography_type: Literal["state", "county"] = Query(default="county"),
    geography_id: str = Query(..., min_length=1),
    funding_geography_mode: Literal["recipient_location", "statewide_allocation"] = Query(
        default="recipient_location"
    ),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] = Query(
        default="all"
    ),
    metric: str | None = Query(default=None),
    assistance_type: str | None = Query(default=None),
    awarding_office: str | None = Query(default=None),
    funding_office: str | None = Query(default=None),
    funding_cio: str | None = Query(default=None),
    office: str | None = Query(default=None),
    center: str | None = Query(default=None),
    state: str | None = Query(default=None),
    start_fy: int | None = Query(default=None),
    end_fy: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    office_value = str(office or "").strip() or None
    awarding_office_value = str(awarding_office or "").strip() or office_value
    funding_office_value = str(funding_office or funding_cio or "").strip() or office_value
    return services.fetch_trend(
        db,
        basis=basis,
        geography=geography_type,
        geography_id=geography_id,
        funding_geography_mode=funding_geography_mode,
        appropriation_type=appropriation_type,
        metric=metric,
        assistance_type=assistance_type,
        awarding_office=awarding_office_value,
        funding_office=funding_office_value,
        center=center,
        state=state,
        start_fy=start_fy,
        end_fy=end_fy,
    )


@router.get("/appropriation/debug")
def get_cdc_appropriation_debug(
    q: str | None = Query(default=None),
    record_type: Literal["prime_transaction", "subaward", "prime_award"] | None = Query(default=None),
    appropriation_type: Literal["all", "regular", "covid_emergency", "other_emergency", "unknown"] = Query(
        default="all"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return services.fetch_appropriation_classification_debug(
        db,
        q=q,
        record_type=record_type,
        appropriation_type=appropriation_type,
        page=page,
        page_size=page_size,
    )


@router.get("/ingestion/debug")
def get_cdc_ingestion_debug(
    db: Session = Depends(get_db),
):
    return services.fetch_ingestion_debug(db)
