"""Community endpoints composed from the published single-place read contract."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.area_pilot import lookup
from app.db import get_db
from app.routers.search import search_counties

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
    }} for row in rows]


@router.get("/search")
def county_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=8, ge=1, le=25),
    db: Session = Depends(get_db),
):
    """Use the existing county-name search; indicator reads still go through lookup."""
    return search_counties(q=q, limit=limit, db=db)


@router.get("/catalog")
def community_catalog(db: Session = Depends(get_db)):
    return lookup.catalog(db)


@router.get("/county/{geoid}")
def county_profile(geoid: str, db: Session = Depends(get_db)):
    info = _county_info(db, geoid)
    catalog, measures = _measure_catalog(db)
    county = lookup.area_values(db, "county", [geoid])
    state = lookup.area_values(db, "state", [info["state_geoid"]])
    return {
        "area": info,
        "values": _enrich(county["values"], measures),
        "state_values": _enrich(state["values"], measures),
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
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["county_geoid", "county_name", "state_name", "product", "measure_id", "indicator", "value",
                     "unit", "status", "status_text", "period", "population", "uncertainty_type", "uncertainty_low",
                     "uncertainty_high", "margin_of_error", "publisher", "source_product", "source_release",
                     "release_id", "source_url", "boundary_vintage"])
    for row in rows:
        uncertainty = row["uncertainty"]
        writer.writerow([geoid, info["name"], info["state_name"], row["product"], row["measure_id"], row["label"],
                         row["value"], row["unit"], row["status"], row["status_text"], row["period"],
                         row["population"], uncertainty["kind"], uncertainty.get("low"), uncertainty.get("high"),
                         uncertainty.get("moe"), row["source"]["publisher"], row["source"]["product_name"],
                         row["source_release_id"], row["release_id"], row["source"]["landing_page"],
                         row["boundary_vintage"]])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="county-{geoid}-indicators.csv"'})
