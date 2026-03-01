from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.hpsa import HPSASummaryResponse, HPSASummaryResponseWithLegacy, HPSATypeSummary
from app.schemas.methodology import MethodologyNote

HPSA_FIELD_DEFINITIONS = {
    "pc_coverage_pct": "Percent of county population covered by a Primary Care HPSA designation (conservative; overlaps possible).",
    "pc_population_covered": "Population covered by Primary Care designation; aggregated using MAX among active designations in the county.",
    "mh_coverage_pct": "Percent of county population covered by a Mental Health HPSA designation (conservative; overlaps possible).",
    "mh_population_covered": "Population covered by Mental Health designation; aggregated using MAX among active designations in the county.",
    "dh_coverage_pct": "Percent of county population covered by a Dental Health HPSA designation (conservative; overlaps possible).",
    "dh_population_covered": "Population covered by Dental Health designation; aggregated using MAX among active designations in the county.",
    "population_denominator_type": "Adult 18+ when available, otherwise total population.",
}


def normalize_county_fips(county_fips: str | None) -> str | None:
    digits = re.sub(r"[^0-9]", "", str(county_fips or ""))
    if not digits or len(digits) > 5:
        return None
    return digits.zfill(5)


def fetch_county_hpsa_row(db: Session, county_fips: str) -> Mapping[str, Any] | None:
    normalized_fips = normalize_county_fips(county_fips)
    if normalized_fips is None:
        return None
    row = db.execute(
        text(
            """
            SELECT *
            FROM county_hpsa_summary
            WHERE county_fips = :county_fips
            """
        ),
        {"county_fips": normalized_fips},
    ).mappings().one_or_none()
    return row


def build_hpsa_type_summary(row: Mapping[str, Any], prefix: str) -> HPSATypeSummary:
    return HPSATypeSummary(
        designated=row.get(f"{prefix}_designated"),
        score_max=row.get(f"{prefix}_hpsa_score_max"),
        population_covered=row.get(f"{prefix}_population_covered"),
        coverage_pct=row.get(f"{prefix}_coverage_pct"),
        raw_rows_in_county=row.get(f"raw_rows_in_county_{prefix}"),
    )


def build_hpsa_methodology(row: Mapping[str, Any]) -> MethodologyNote:
    denominator_source = row.get("population_denominator_source")
    source = (
        f"HRSA HPSA Data Mart; denominator: {denominator_source}"
        if denominator_source
        else "HRSA HPSA Data Mart"
    )

    caveats: list[str] = []
    overlap_caveat = row.get("coverage_overlap_caveat")
    if overlap_caveat:
        caveats.append(str(overlap_caveat))

    return MethodologyNote(
        source=source,
        as_of_date=row.get("as_of_date"),
        calculation=row.get("coverage_pct_definition"),
        caveats=caveats,
        fields=HPSA_FIELD_DEFINITIONS,
    )


def _legacy_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = [
        "pc_designated",
        "pc_hpsa_score_max",
        "pc_population_covered",
        "pc_coverage_pct",
        "mh_designated",
        "mh_hpsa_score_max",
        "mh_population_covered",
        "mh_coverage_pct",
        "dh_designated",
        "dh_hpsa_score_max",
        "dh_population_covered",
        "dh_coverage_pct",
        "population_denominator_type",
        "population_denominator",
        "population_denominator_source",
        "coverage_population_aggregation_method",
        "coverage_overlap_caveat",
        "coverage_pct_definition",
        "pc_coverage_method",
        "mh_coverage_method",
        "dh_coverage_method",
        "raw_rows_in_county_pc",
        "raw_rows_in_county_mh",
        "raw_rows_in_county_dh",
        "as_of_date",
        "updated_at",
    ]
    return {key: row.get(key) for key in keys}


def build_hpsa_response(
    row: Mapping[str, Any],
    *,
    include_legacy: bool = True,
) -> dict[str, Any]:
    structured = HPSASummaryResponse(
        county_fips=str(row.get("county_fips")),
        state_fips=row.get("state_fips"),
        primary_care=build_hpsa_type_summary(row, "pc"),
        mental_health=build_hpsa_type_summary(row, "mh"),
        dental=build_hpsa_type_summary(row, "dh"),
        methodology=build_hpsa_methodology(row),
    ).model_dump(mode="python")

    if not include_legacy:
        return structured

    merged = {**structured, **_legacy_payload(row)}
    return HPSASummaryResponseWithLegacy(**merged).model_dump(mode="python")
