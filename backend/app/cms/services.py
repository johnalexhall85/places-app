from __future__ import annotations

import math
import re
from decimal import Decimal
from numbers import Real
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.cms import models

GV_SOURCE = "CMS FFS GV PUF"
SSP_SOURCE = "CMS SSP County FFS PUF"
VALID_GEO_LEVELS = {"county", "state", "national"}
VALID_ASSIGN_WINDOWS = {"calendar", "offset"}


def normalize_county_fips(value: str) -> str | None:
    digits = re.sub(r"[^0-9]", "", str(value or "").strip())
    if not digits or len(digits) > 5:
        return None
    normalized = digits.zfill(5)
    if not re.fullmatch(r"\d{5}", normalized):
        return None
    return normalized


def parse_required_measure_ids_csv(measure_ids: str | None) -> list[str]:
    parsed = [item.strip() for item in str(measure_ids or "").split(",") if item.strip()]
    if not parsed:
        raise ValueError("measure_ids is required")
    return parsed


def normalize_geo_level(value: str) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized not in VALID_GEO_LEVELS:
        return None
    return normalized


def normalize_assign_window(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized not in VALID_ASSIGN_WINDOWS:
        return None
    return normalized


def _json_number(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return float(value)
    if isinstance(value, Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return value


def fetch_gv_geo_rows(
    db: Session,
    *,
    level: str,
    year: int,
    age_level: str,
    measure_id: str,
) -> list[dict[str, Any]]:
    stmt = (
        select(
            models.CmsGvFact.geo_level,
            models.CmsGvFact.geo_code,
            models.CmsGeoDim.geo_name,
            models.CmsGeoDim.state_fips,
            models.CmsGeoDim.county_fips,
            models.CmsGvFact.year,
            models.CmsGvFact.age_level,
            models.CmsGvFact.measure_id,
            models.CmsGvFact.value,
            models.CmsGvFact.is_suppressed,
            models.CmsGvMeasureDim.source,
        )
        .join(
            models.CmsGeoDim,
            and_(
                models.CmsGeoDim.geo_level == models.CmsGvFact.geo_level,
                models.CmsGeoDim.geo_code == models.CmsGvFact.geo_code,
            ),
        )
        .outerjoin(
            models.CmsGvMeasureDim,
            models.CmsGvMeasureDim.measure_id == models.CmsGvFact.measure_id,
        )
        .where(
            models.CmsGvFact.geo_level == level,
            models.CmsGvFact.year == int(year),
            models.CmsGvFact.age_level == age_level,
            models.CmsGvFact.measure_id == measure_id,
        )
        .order_by(models.CmsGvFact.geo_code)
    )

    rows = db.execute(stmt).mappings().all()
    return [
        {
            "geo_level": row["geo_level"],
            "geo_code": row["geo_code"],
            "geo_name": row["geo_name"],
            "state_fips": (row["state_fips"] or "").strip() or None,
            "county_fips": (row["county_fips"] or "").strip() or None,
            "year": int(row["year"]),
            "age_level": row["age_level"],
            "measure_id": row["measure_id"],
            "value": _json_number(row["value"]),
            "is_suppressed": bool(row["is_suppressed"]),
            "source": row["source"] or GV_SOURCE,
        }
        for row in rows
    ]


def fetch_gv_measures(
    db: Session,
    *,
    level: str = "county",
) -> list[dict[str, Any]]:
    normalized_level = normalize_geo_level(level)
    if normalized_level is None:
        normalized_level = "county"

    available_measure_ids_subquery = (
        select(models.CmsGvFact.measure_id)
        .where(models.CmsGvFact.geo_level == normalized_level)
        .distinct()
        .subquery()
    )

    stmt = (
        select(
            models.CmsGvMeasureDim.measure_id,
            models.CmsGvMeasureDim.label,
            models.CmsGvMeasureDim.unit,
            models.CmsGvMeasureDim.domain,
        )
        .join(
            available_measure_ids_subquery,
            available_measure_ids_subquery.c.measure_id == models.CmsGvMeasureDim.measure_id,
        )
        .order_by(models.CmsGvMeasureDim.label.asc(), models.CmsGvMeasureDim.measure_id.asc())
    )

    rows = db.execute(stmt).mappings().all()
    return [
        {
            "measure_id": row["measure_id"],
            "label": row["label"] or row["measure_id"],
            "unit": row["unit"],
            "domain": row["domain"],
        }
        for row in rows
    ]


def fetch_gv_years(
    db: Session,
    *,
    level: str = "county",
) -> list[int]:
    normalized_level = normalize_geo_level(level)
    if normalized_level is None:
        normalized_level = "county"

    stmt = (
        select(models.CmsGvFact.year)
        .where(models.CmsGvFact.geo_level == normalized_level)
        .distinct()
        .order_by(models.CmsGvFact.year.desc())
    )
    rows = db.execute(stmt).scalars().all()
    return [int(year) for year in rows if year is not None]


def fetch_gv_county_measures(
    db: Session,
    *,
    county_fips: str,
    year: int,
    age_level: str,
    measure_ids: list[str],
) -> list[dict[str, Any]]:
    stmt = (
        select(
            models.CmsGvFact.measure_id,
            models.CmsGvFact.value,
            models.CmsGvFact.is_suppressed,
        )
        .join(
            models.CmsGeoDim,
            and_(
                models.CmsGeoDim.geo_level == models.CmsGvFact.geo_level,
                models.CmsGeoDim.geo_code == models.CmsGvFact.geo_code,
            ),
        )
        .where(
            models.CmsGvFact.geo_level == "county",
            models.CmsGeoDim.county_fips == county_fips,
            models.CmsGvFact.year == int(year),
            models.CmsGvFact.age_level == age_level,
            models.CmsGvFact.measure_id.in_(measure_ids),
        )
        .order_by(models.CmsGvFact.measure_id)
    )

    rows = db.execute(stmt).mappings().all()
    return [
        {
            "measure_id": row["measure_id"],
            "value": _json_number(row["value"]),
            "is_suppressed": bool(row["is_suppressed"]),
        }
        for row in rows
    ]


def fetch_ssp_county_measures(
    db: Session,
    *,
    county_fips: str,
    year: int,
    enrollment_type: str,
    assign_window: str,
    measure_ids: list[str],
) -> list[dict[str, Any]]:
    stmt = (
        select(
            models.CmsSspFact.measure_id,
            models.CmsSspFact.value,
            models.CmsSspFact.is_suppressed,
        )
        .where(
            models.CmsSspFact.county_fips == county_fips,
            models.CmsSspFact.year == int(year),
            models.CmsSspFact.enrollment_type == enrollment_type,
            models.CmsSspFact.assign_window == assign_window,
            models.CmsSspFact.measure_id.in_(measure_ids),
        )
        .order_by(models.CmsSspFact.measure_id)
    )

    rows = db.execute(stmt).mappings().all()
    return [
        {
            "measure_id": row["measure_id"],
            "value": _json_number(row["value"]),
            "is_suppressed": bool(row["is_suppressed"]),
        }
        for row in rows
    ]
