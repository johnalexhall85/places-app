"""Community endpoints composed from the published single-place read contract."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.area_pilot import lookup
from app.db import get_db
from app.routers.search import search_counties
from app.demo_access.settings import get_demo_access_settings
from app.services.profile_pdf_playwright import render_route_pdf_via_playwright

router = APIRouter(prefix="/community", tags=["community"])
TOPICS_PATH = Path(__file__).with_name("topics.json")


def _bad_request(error: lookup.LookupError_) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


def _county_info(db: Session, geoid: str) -> dict:
    try:
        info = lookup.area_info(db, "county", [geoid])
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error
    if not info:
        raise HTTPException(status_code=404, detail="County not found on the published boundary")
    return info[0]


def _state_info(db: Session, geoid: str) -> dict:
    try:
        info = lookup.area_info(db, "state", [geoid])
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error
    if not info:
        raise HTTPException(status_code=404, detail="State not found on the published boundary")
    return info[0]


def _district_info(db: Session, geoid: str) -> dict:
    try:
        info = lookup.area_info(db, "cd", [geoid])
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error
    if not info:
        raise HTTPException(status_code=404, detail="District not found on the 119th Congress boundary")
    return info[0]


def _measure_catalog(db: Session) -> tuple[dict, dict]:
    catalog = lookup.catalog(db)
    measures = {(m["product"], m["measure_id"]): m for m in catalog["measures"]}
    return catalog, measures


def _enrich(rows: list[dict], measures: dict) -> list[dict]:
    # Preserve every published row and its own period, population, status and release.
    return [row | {"source": {
        "publisher": measures[(row["product"], row["measure_id"])]["publisher"],
        "product_name": measures[(row["product"], row["measure_id"])]["product_name"],
        "landing_page": measures[(row["product"], row["measure_id"])]["landing_page"],
        "credit": measures[(row["product"], row["measure_id"])].get("source_credit"),
    }} for row in rows]


@router.get("/search")
def county_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=8, ge=1, le=25),
    db: Session = Depends(get_db),
):
    """Find counties and state-level areas without reading published values outside lookup."""
    needle = q.strip().casefold()
    matches = [state | {"type": "state", "state_geoid": state["geoid"]}
               for state in lookup.states(db)
               if needle in state["name"].casefold() or needle == state["geoid"]]
    counties = search_counties(q=q, limit=limit, db=db)
    return (matches + [county | {"type": "county"} for county in counties])[:limit]


@router.get("/catalog")
def community_catalog(db: Session = Depends(get_db)):
    return lookup.catalog(db)


@router.get("/states")
def community_states(db: Session = Depends(get_db)):
    return lookup.states(db)


@router.get("/state/{geoid}")
def state_profile(geoid: str, db: Session = Depends(get_db)):
    info = _state_info(db, geoid)
    catalog, measures = _measure_catalog(db)
    try:
        state = lookup.area_values(db, "state", [geoid])
        facilities = lookup.area_facilities(db, "state", geoid)
        counties = lookup.state_counties(db, geoid)
        districts = lookup.state_districts(db, geoid)
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error
    return {
        "area": info,
        "values": _enrich(state["values"], measures),
        "facilities": facilities,
        "counties": counties,
        "districts": districts,
        "releases": state["releases"],
        "products": catalog["products"],
        "limitations": [
            "BRFSS values are direct state survey estimates; PLACES county values are modeled and are not used to derive state values.",
            "Workforce, food, air quality, and other county-only measures are not summed or averaged into a state figure.",
            "Facility locations are context, not evidence of capacity, access, exposure, quality, or cause.",
        ],
    }


@router.get("/state/{geoid}/csv")
def state_csv(geoid: str, db: Session = Depends(get_db)):
    info = _state_info(db, geoid)
    _, measures = _measure_catalog(db)
    try:
        rows = _enrich(lookup.area_values(db, "state", [geoid])["values"], measures)
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["state_geoid", "state_name", "product", "measure_id", "indicator", "value", "unit", "status",
                     "status_text", "period", "population", "uncertainty_type", "uncertainty_low", "uncertainty_high",
                     "margin_of_error", "publisher", "source_product", "source_release", "release_id", "source_url",
                     "boundary_vintage", "underlying_source_credit"])
    for row in rows:
        uncertainty = row["uncertainty"]
        writer.writerow([geoid, info["name"], row["product"], row["measure_id"], row["label"], row["value"],
                         row["unit"], row["status"], row["status_text"], row["period"], row["population"],
                         uncertainty["kind"], uncertainty.get("low"), uncertainty.get("high"), uncertainty.get("moe"),
                         row["source"]["publisher"], row["source"]["product_name"], row["source_release_id"],
                         row["release_id"], row["source"]["landing_page"], row["boundary_vintage"],
                         row["source"]["credit"] or ""])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="state-{geoid}-indicators.csv"'})


@router.get("/state/{geoid}/pdf")
def state_pdf(geoid: str, request: Request, db: Session = Depends(get_db)):
    _state_info(db, geoid)
    settings = get_demo_access_settings()
    raw_cookie = request.cookies.get(settings.cookie_name)
    session_cookie = (settings.cookie_name, raw_cookie) if raw_cookie else None
    try:
        content = render_route_pdf_via_playwright(
            route_path=f"/community/state/{geoid}", session_cookie=session_cookie,
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail="State PDF rendering is unavailable") from error
    return Response(content=content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="state-{geoid}-briefing.pdf"'})


@router.get("/districts/states")
def district_states(db: Session = Depends(get_db)):
    """State names and codes for the district picker, through the published lookup contract."""
    return lookup.area_info(db, "state", [f"{code:02d}" for code in range(80)])


@router.get("/districts")
def districts_in_state(state_geoid: str = Query(...), db: Session = Depends(get_db)):
    try:
        states = lookup.area_info(db, "state", [state_geoid])
        if not states:
            raise HTTPException(status_code=404, detail="State not found")
        return {"state": states[0], "districts": lookup.state_districts(db, state_geoid)}
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error


@router.get("/district/{geoid}")
def district_briefing(geoid: str, db: Session = Depends(get_db)):
    area = _district_info(db, geoid)
    _, measures = _measure_catalog(db)
    try:
        values = lookup.area_values(db, "cd", [geoid])
        facilities = lookup.area_facilities(db, "cd", geoid)
        overlaps = lookup.district_counties(db, geoid)
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error
    return {
        "area": area,
        "values": _enrich(values["values"], measures),
        "facilities": facilities,
        "counties": overlaps,
        "releases": values["releases"],
        "limitations": [
            "Only Census Bureau ACS community characteristics are district estimates.",
            "Overlapping counties are geographic context; their values are not district estimates.",
            "Mapped facilities do not measure capacity, access, exposure, quality, or cause.",
        ],
    }


@router.get("/county/{geoid}/districts")
def districts_for_county(geoid: str, db: Session = Depends(get_db)):
    _county_info(db, geoid)
    try:
        return lookup.county_districts(db, geoid)
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error


@router.get("/county/{geoid}")
def county_profile(geoid: str, db: Session = Depends(get_db)):
    info = _county_info(db, geoid)
    catalog, measures = _measure_catalog(db)
    county = lookup.area_values(db, "county", [geoid])
    state = lookup.area_values(db, "state", [info["state_geoid"]])
    companions = lookup.state_survey_companions(db, info["state_geoid"])
    return {
        "area": info,
        "values": _enrich(county["values"], measures),
        "state_values": _enrich(state["values"], measures),
        "survey_companions": {key: _enrich([row], measures)[0]
                              for key, row in companions["companions"].items()},
        "survey_note": companions["note"],
        "facilities": lookup.area_facilities(db, "county", geoid),
        "releases": county["releases"],
        "state_releases": state["releases"],
        "products": catalog["products"],
        "limitations": [
            "Indicators describe different populations and periods; compare each measure on its own terms.",
            "Facility locations are context, not evidence of capacity, access, exposure, or cause.",
            "State values appear only where the source publishes a state estimate.",
        ],
    }


@router.get("/compare")
def compare_counties(
    geoids: str = Query(..., description="Comma-separated county GEOIDs, up to four"),
    db: Session = Depends(get_db),
):
    county_ids = list(dict.fromkeys(item.strip() for item in geoids.split(",")))
    if not 1 <= len(county_ids) <= 4 or any(not item for item in county_ids):
        raise HTTPException(status_code=400, detail="Choose one to four county GEOIDs")
    try:
        areas = lookup.area_info(db, "county", county_ids)
        values = lookup.area_values(db, "county", county_ids)
        state_companions = {state: lookup.state_survey_companions(db, state)["companions"]
                            for state in {geoid[:2] for geoid in county_ids}}
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error
    by_geoid = {area["geoid"]: area for area in areas}
    if any(geoid not in by_geoid for geoid in county_ids):
        raise HTTPException(status_code=404, detail="One or more counties were not found on the published boundary")
    _, measures = _measure_catalog(db)
    rows = _enrich(values["values"], measures)
    return {
        "areas": [by_geoid[geoid] for geoid in county_ids],
        "values": rows,
        "survey_companions": {state: {key: _enrich([row], measures)[0] for key, row in companions.items()}
                              for state, companions in state_companions.items()},
        "releases": values["releases"],
        "note": "Values are source-published estimates for each county; no ranking or combined score is calculated.",
    }


@router.get("/county/{geoid}/facilities")
def county_facilities(geoid: str, db: Session = Depends(get_db)):
    _county_info(db, geoid)
    try:
        return lookup.area_facilities(db, "county", geoid)
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error


@router.get("/county/{geoid}/tracts")
def county_tracts(
    geoid: str,
    product: str = Query(...),
    measure_id: str = Query(...),
    db: Session = Depends(get_db),
):
    _county_info(db, geoid)
    try:
        return lookup.county_tract_values(db, geoid, product, measure_id)
    except lookup.LookupError_ as error:
        raise _bad_request(error) from error


def _topics() -> list[dict]:
    return json.loads(TOPICS_PATH.read_text(encoding="utf-8"))


@router.get("/topics")
def topics(db: Session = Depends(get_db)):
    _, measures = _measure_catalog(db)
    return [_topic_with_measures(topic, measures) for topic in _topics()]


@router.get("/topics/{slug}")
def topic(slug: str, db: Session = Depends(get_db)):
    selected = next((item for item in _topics() if item["slug"] == slug), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    _, measures = _measure_catalog(db)
    return _topic_with_measures(selected, measures)


def _topic_with_measures(topic: dict, measures: dict) -> dict:
    return topic | {"measures": [measures[key] for product, measure_id in topic["measure_keys"]
                                 if (key := (product, measure_id)) in measures]}


@router.get("/county/{geoid}/csv")
def county_csv(geoid: str, db: Session = Depends(get_db)):
    info = _county_info(db, geoid)
    _, measures = _measure_catalog(db)
    rows = _enrich(lookup.area_values(db, "county", [geoid])["values"], measures)
    companions = {key: _enrich([row], measures)[0] for key, row in
                  lookup.state_survey_companions(db, geoid[:2])["companions"].items()}
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["county_geoid", "county_name", "state_name", "product", "measure_id", "indicator", "value",
                     "unit", "status", "status_text", "period", "population", "uncertainty_type", "uncertainty_low",
                     "uncertainty_high", "margin_of_error", "publisher", "source_product", "source_release",
                     "release_id", "source_url", "boundary_vintage", "underlying_source_credit",
                     "state_survey_label", "state_survey_value", "state_survey_status", "state_survey_status_text",
                     "state_survey_period", "state_survey_population", "state_survey_ci_low", "state_survey_ci_high",
                     "state_survey_publisher", "state_survey_product", "state_survey_source_release",
                     "state_survey_release_id"])
    for row in rows:
        uncertainty = row["uncertainty"]
        companion = companions.get(row["measure_id"]) if row["product"] == "places" else None
        survey_uncertainty = companion["uncertainty"] if companion else {}
        writer.writerow([geoid, info["name"], info["state_name"], row["product"], row["measure_id"], row["label"],
                         row["value"], row["unit"], row["status"], row["status_text"], row["period"],
                         row["population"], uncertainty["kind"], uncertainty.get("low"), uncertainty.get("high"),
                         uncertainty.get("moe"), row["source"]["publisher"], row["source"]["product_name"],
                         row["source_release_id"], row["release_id"], row["source"]["landing_page"],
                         row["boundary_vintage"], row["source"]["credit"] or "",
                         "State survey estimate (BRFSS)" if companion else "", companion["value"] if companion else "",
                         companion["status"] if companion else "", companion["status_text"] if companion else "",
                         companion["period"] if companion else "", companion["population"] if companion else "",
                         survey_uncertainty.get("low", ""), survey_uncertainty.get("high", ""),
                         companion["source"]["publisher"] if companion else "",
                         companion["source"]["product_name"] if companion else "",
                         companion["source_release_id"] if companion else "", companion["release_id"] if companion else ""])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="county-{geoid}-indicators.csv"'})


@router.get("/county/{geoid}/pdf")
def county_pdf(geoid: str, request: Request, db: Session = Depends(get_db)):
    _county_info(db, geoid)
    settings = get_demo_access_settings()
    raw_cookie = request.cookies.get(settings.cookie_name)
    session_cookie = (settings.cookie_name, raw_cookie) if raw_cookie else None
    try:
        content = render_route_pdf_via_playwright(
            route_path=f"/community/county/{geoid}", session_cookie=session_cookie,
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail="County PDF rendering is unavailable") from error
    return Response(content=content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="county-{geoid}-briefing.pdf"'})
