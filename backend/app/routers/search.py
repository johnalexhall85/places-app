import re

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["search"])


class CountySearchBbox(BaseModel):
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


class CountySearchCentroid(BaseModel):
    lat: float
    lon: float


class CountySearchResult(BaseModel):
    name: str
    state_abbr: str
    county_fips: str
    bbox: CountySearchBbox
    centroid: CountySearchCentroid


def normalize_query(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_token_pattern(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", " ", value).strip().lower()
    if not cleaned:
        return "%"
    return f"%{'%'.join(cleaned.split())}%"


def parse_fips_query(value: str) -> str | None:
    lowered = value.strip().lower()
    if not lowered.startswith("fips:"):
        return None
    fips_value = value.split(":", 1)[1].strip()
    if len(fips_value) == 5 and fips_value.isdigit():
        return fips_value
    return ""


@router.get("/search/counties", response_model=list[CountySearchResult])
def search_counties(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=5, ge=1, le=25),
    db: Session = Depends(get_db),
):
    normalized_q = normalize_query(q)
    if not normalized_q:
        return []

    boundary_table_exists = db.execute(
        text("SELECT to_regclass('public.dim_county_boundary') AS exists")
    ).mappings().one()["exists"] is not None
    join_clause = (
        "LEFT JOIN dim_county_boundary AS b ON b.location_id = c.location_id"
        if boundary_table_exists
        else ""
    )
    geom_expr = "COALESCE(b.geom, c.geom)" if boundary_table_exists else "c.geom"

    fips_exact = parse_fips_query(normalized_q)
    if fips_exact == "":
        return []

    if fips_exact is not None:
        query = text(
            f"""
            SELECT
                c.county_name AS name,
                c.state_abbr,
                c.location_id AS county_fips,
                ST_XMin(ST_Envelope({geom_expr})) AS min_lon,
                ST_YMin(ST_Envelope({geom_expr})) AS min_lat,
                ST_XMax(ST_Envelope({geom_expr})) AS max_lon,
                ST_YMax(ST_Envelope({geom_expr})) AS max_lat,
                ST_Y(ST_PointOnSurface({geom_expr})) AS centroid_lat,
                ST_X(ST_PointOnSurface({geom_expr})) AS centroid_lon
            FROM dim_county AS c
            {join_clause}
            WHERE c.location_id = :fips_exact
                AND {geom_expr} IS NOT NULL
            LIMIT :limit
            """
        )
        params = {"fips_exact": fips_exact, "limit": limit}
    else:
        token_base = re.sub(r"[^0-9A-Za-z]+", " ", normalized_q).strip().lower()
        token_prefix = f"{token_base}%" if token_base else "%"
        query = text(
            f"""
            SELECT
                c.county_name AS name,
                c.state_abbr,
                c.location_id AS county_fips,
                ST_XMin(ST_Envelope({geom_expr})) AS min_lon,
                ST_YMin(ST_Envelope({geom_expr})) AS min_lat,
                ST_XMax(ST_Envelope({geom_expr})) AS max_lon,
                ST_YMax(ST_Envelope({geom_expr})) AS max_lat,
                ST_Y(ST_PointOnSurface({geom_expr})) AS centroid_lat,
                ST_X(ST_PointOnSurface({geom_expr})) AS centroid_lon
            FROM dim_county AS c
            {join_clause}
            WHERE {geom_expr} IS NOT NULL
                AND (
                    c.county_name ILIKE :contains_q
                    OR c.state_abbr ILIKE :contains_q
                    OR (c.county_name || ' ' || c.state_abbr) ILIKE :contains_q
                    OR lower(
                        trim(
                            concat_ws(
                                ' ',
                                c.county_name,
                                'county',
                                c.state_abbr,
                                c.state_desc
                            )
                        )
                    ) LIKE :token_pattern
                )
            ORDER BY
                CASE
                    WHEN lower(c.county_name) = :token_base THEN 0
                    WHEN lower(c.county_name || ' county') = :token_base THEN 1
                    WHEN lower(c.county_name || ' county ' || c.state_abbr) = :token_base THEN 2
                    WHEN lower(c.county_name) LIKE :token_prefix THEN 3
                    ELSE 10
                END,
                c.state_abbr,
                c.county_name
            LIMIT :limit
            """
        )
        params = {
            "contains_q": f"%{normalized_q}%",
            "token_pattern": normalize_token_pattern(normalized_q),
            "token_base": token_base,
            "token_prefix": token_prefix,
            "limit": limit,
        }

    rows = db.execute(query, params).mappings().all()
    return [
        {
            "name": row["name"],
            "state_abbr": row["state_abbr"],
            "county_fips": row["county_fips"],
            "bbox": {
                "min_lon": float(row["min_lon"]),
                "min_lat": float(row["min_lat"]),
                "max_lon": float(row["max_lon"]),
                "max_lat": float(row["max_lat"]),
            },
            "centroid": {
                "lat": float(row["centroid_lat"]),
                "lon": float(row["centroid_lon"]),
            },
        }
        for row in rows
    ]
