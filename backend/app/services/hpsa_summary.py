from __future__ import annotations

import math
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db_fqtn import hrsa_table
from app.schemas.hpsa import (
    HPSAChoroplethCountiesResponse,
    HPSACountyDomainDetailResponse,
    HPSADomain,
    HPSADomainQuartiles,
    HPSASummaryResponse,
    HPSASummaryResponseWithLegacy,
    HPSATypeSummary,
)
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

HPSA_DOMAIN_FIELDS: dict[HPSADomain, dict[str, str]] = {
    "pc": {
        "label": "Primary Care",
        "designated": "pc_designated",
        "score": "pc_hpsa_score_max",
        "population": "pc_population_covered",
        "coverage_pct": "pc_coverage_pct",
    },
    "mh": {
        "label": "Mental Health",
        "designated": "mh_designated",
        "score": "mh_hpsa_score_max",
        "population": "mh_population_covered",
        "coverage_pct": "mh_coverage_pct",
    },
    "dh": {
        "label": "Dental",
        "designated": "dh_designated",
        "score": "dh_hpsa_score_max",
        "population": "dh_population_covered",
        "coverage_pct": "dh_coverage_pct",
    },
}

FORMAL_RATIO_KEYS = {
    "hpsaformalratio",
    "formalratio",
    "populationtoproviderratio",
    "populationproviderratio",
    "hpsapopulationtoproviderratio",
}
PROVIDER_GOAL_KEYS = {
    "providerratiogoal",
    "ratio_goal",
    "ratiogoal",
    "populationtoproviderratiogoal",
}
FTE_KEYS = {
    "fte",
    "providerfte",
    "providersfte",
    "currentfte",
    "totalfte",
    "weightedfte",
    "fulltimeequivalent",
    "providerfulltimeequivalent",
}


def normalize_county_fips(county_fips: str | None) -> str | None:
    digits = re.sub(r"[^0-9]", "", str(county_fips or ""))
    if not digits or len(digits) > 5:
        return None
    return digits.zfill(5)


def normalize_hpsa_domain(
    domain: str | None,
    *,
    default: HPSADomain | None = None,
) -> HPSADomain | None:
    if domain is None:
        return default
    normalized = str(domain).strip().lower()
    if normalized in HPSA_DOMAIN_FIELDS:
        return normalized  # type: ignore[return-value]
    return None


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    text_value = str(value).strip()
    if not text_value:
        return None
    compact = text_value.replace(",", "")
    try:
        numeric = float(compact)
    except ValueError:
        return None
    return numeric if math.isfinite(numeric) else None


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return int(round(numeric))


def _safe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    text_value = str(value).strip().lower()
    if text_value in {"true", "t", "1", "yes", "y"}:
        return True
    if text_value in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_ratio_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        numeric = _safe_float(value)
        if numeric is None:
            return None
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric}"
    text_value = str(value).strip()
    return text_value or None


def _extract_numeric_from_text(value: Any) -> float | None:
    numeric = _safe_float(value)
    if numeric is not None:
        return numeric
    text_value = str(value or "").strip().replace(",", "")
    if not text_value:
        return None
    matched = re.search(r"-?\d+(?:\.\d+)?", text_value)
    if not matched:
        return None
    try:
        parsed = float(matched.group(0))
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def compute_quartiles_from_scores(
    scores: list[float | int | Decimal | None],
) -> tuple[float | None, float | None, float | None, int]:
    numeric_scores = sorted(
        value for value in (_safe_float(score) for score in scores) if value is not None
    )
    n_counties = len(numeric_scores)
    if n_counties == 0:
        return (None, None, None, 0)

    def percentile_cont(values: list[float], percentile: float) -> float:
        if len(values) == 1:
            return values[0]
        position = (len(values) - 1) * percentile
        lower_index = int(math.floor(position))
        upper_index = int(math.ceil(position))
        lower_value = values[lower_index]
        upper_value = values[upper_index]
        fraction = position - lower_index
        return lower_value + (upper_value - lower_value) * fraction

    return (
        percentile_cont(numeric_scores, 0.25),
        percentile_cont(numeric_scores, 0.50),
        percentile_cont(numeric_scores, 0.75),
        n_counties,
    )


def assign_hpsa_tier(
    *,
    designated: bool | None,
    value: float | int | Decimal | None,
    q25: float | int | Decimal | None,
    q50: float | int | Decimal | None,
    q75: float | int | Decimal | None,
) -> int | None:
    if not designated:
        return None

    score_value = _safe_float(value)
    if score_value is None:
        return None

    q25_value = _safe_float(q25)
    q50_value = _safe_float(q50)
    q75_value = _safe_float(q75)
    if q25_value is None or q50_value is None or q75_value is None:
        return None

    if score_value <= q25_value:
        return 1
    if score_value <= q50_value:
        return 2
    if score_value <= q75_value:
        return 3
    return 4


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


def fetch_hpsa_domain_quartiles(db: Session, domain: HPSADomain) -> Mapping[str, Any] | None:
    quartile_table_exists = db.execute(
        text("SELECT to_regclass(:table_name) IS NOT NULL AS exists"),
        {"table_name": hrsa_table("hpsa_domain_quartiles")},
    ).mappings().one()["exists"]

    if quartile_table_exists:
        row = db.execute(
            text(
                """
                SELECT
                    domain,
                    q25,
                    q50,
                    q75,
                    n_counties,
                    as_of_date
                FROM hpsa_domain_quartiles
                WHERE domain = :domain
                """
            ),
            {"domain": domain},
        ).mappings().one_or_none()
        if row is not None:
            return row

    fields = HPSA_DOMAIN_FIELDS[domain]
    fallback_row = db.execute(
        text(
            f"""
            SELECT
                :domain AS domain,
                percentile_cont(0.25) WITHIN GROUP (ORDER BY {fields['score']}::numeric) AS q25,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY {fields['score']}::numeric) AS q50,
                percentile_cont(0.75) WITHIN GROUP (ORDER BY {fields['score']}::numeric) AS q75,
                COUNT(*)::integer AS n_counties,
                COALESCE(MAX(as_of_date), CURRENT_DATE) AS as_of_date
            FROM county_hpsa_summary
            WHERE {fields['designated']} IS TRUE
              AND {fields['score']} IS NOT NULL
            """
        ),
        {"domain": domain},
    ).mappings().one_or_none()
    return fallback_row


def fetch_hpsa_county_rows_for_domain(
    db: Session,
    domain: HPSADomain,
) -> list[Mapping[str, Any]]:
    fields = HPSA_DOMAIN_FIELDS[domain]
    query = text(
        f"""
        SELECT
            county_fips,
            {fields['designated']} AS designated,
            {fields['score']} AS value
        FROM county_hpsa_summary
        ORDER BY county_fips
        """
    )
    return db.execute(query).mappings().all()


def fetch_hpsa_county_geojson_rows(
    db: Session,
    *,
    domain: HPSADomain,
    bbox_bounds: tuple[float, float, float, float] | None = None,
    simplify: float | None = 0.02,
    limit: int = 5000,
    offset: int = 0,
) -> list[Mapping[str, Any]]:
    fields = HPSA_DOMAIN_FIELDS[domain]

    bbox_cte = ""
    bbox_join = ""
    bbox_filter = ""
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
    }
    if bbox_bounds is not None:
        minx, miny, maxx, maxy = bbox_bounds
        bbox_cte = (
            "WITH bbox AS ("
            "SELECT ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326) AS geom"
            ")"
        )
        bbox_join = "CROSS JOIN bbox"
        bbox_filter = (
            "AND b.geom && bbox.geom "
            "AND ST_Intersects(b.geom, bbox.geom)"
        )
        params.update(
            {
                "minx": minx,
                "miny": miny,
                "maxx": maxx,
                "maxy": maxy,
            }
        )

    geometry_expr = "ST_AsGeoJSON(b.geom)::json"
    if simplify is not None:
        geometry_expr = (
            "ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom, :simplify))::json"
        )
        params["simplify"] = simplify

    rows = db.execute(
        text(
            f"""
            {bbox_cte}
            SELECT
                b.location_id,
                b.geoid,
                b.name,
                b.statefp,
                b.countyfp,
                c.state_abbr,
                c.state_desc,
                c.county_name,
                h.county_fips,
                {fields['designated']} AS designated,
                {fields['score']} AS value,
                {geometry_expr} AS geometry
            FROM dim_county_boundary AS b
            {bbox_join}
            LEFT JOIN dim_county AS c
                ON c.location_id = b.location_id
            LEFT JOIN county_hpsa_summary AS h
                ON h.county_fips = b.geoid
            WHERE b.geom IS NOT NULL
                {bbox_filter}
            ORDER BY b.location_id
            LIMIT :limit
            OFFSET :offset
            """
        ),
        params,
    ).mappings().all()
    return rows


def _read_ratio_fields_from_rows(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    hpsa_formal_ratio: str | None = None
    provider_ratio_goal: str | None = None
    fte: float | None = None

    for row in rows:
        data = row.get("data")
        if not isinstance(data, dict):
            continue
        for key, raw_value in data.items():
            normalized_key = _normalize_key(key)
            if not normalized_key:
                continue

            if hpsa_formal_ratio is None and (
                normalized_key in FORMAL_RATIO_KEYS
                or "formalratio" in normalized_key
                or (
                    "ratio" in normalized_key
                    and "goal" not in normalized_key
                    and "provider" in normalized_key
                )
            ):
                hpsa_formal_ratio = _normalize_ratio_text(raw_value)
                if hpsa_formal_ratio == "":
                    hpsa_formal_ratio = None
                continue

            if provider_ratio_goal is None and (
                normalized_key in PROVIDER_GOAL_KEYS
                or ("ratio" in normalized_key and "goal" in normalized_key)
            ):
                provider_ratio_goal = _normalize_ratio_text(raw_value)
                if provider_ratio_goal == "":
                    provider_ratio_goal = None
                continue

            if fte is None and (
                normalized_key in FTE_KEYS
                or normalized_key.endswith("fte")
                or "fulltimeequivalent" in normalized_key
            ):
                fte = _extract_numeric_from_text(raw_value)

        if hpsa_formal_ratio is not None and provider_ratio_goal is not None and fte is not None:
            break

    return {
        "hpsa_formal_ratio": hpsa_formal_ratio,
        "provider_ratio_goal": provider_ratio_goal,
        "fte": fte,
    }


def fetch_hpsa_domain_ratio_fields(
    db: Session,
    *,
    county_fips: str,
    domain: HPSADomain,
) -> dict[str, Any]:
    rows = db.execute(
        text(
            """
            SELECT data
            FROM hpsa_designations_raw
            WHERE county_fips = :county_fips
              AND designation_type = :domain
            ORDER BY created_at DESC, id DESC
            LIMIT 200
            """
        ),
        {"county_fips": county_fips, "domain": domain},
    ).mappings().all()
    if not rows:
        return {
            "hpsa_formal_ratio": None,
            "provider_ratio_goal": None,
            "fte": None,
        }
    return _read_ratio_fields_from_rows(rows)


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


def _build_domain_quartiles_payload(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return HPSADomainQuartiles(
            q25=None,
            q50=None,
            q75=None,
            n_counties=0,
            as_of_date=None,
        ).model_dump(mode="python")

    return HPSADomainQuartiles(
        q25=_safe_float(row.get("q25")),
        q50=_safe_float(row.get("q50")),
        q75=_safe_float(row.get("q75")),
        n_counties=_safe_int(row.get("n_counties")) or 0,
        as_of_date=row.get("as_of_date"),
    ).model_dump(mode="python")


def build_hpsa_choropleth_response(
    *,
    domain: HPSADomain,
    quartile_row: Mapping[str, Any] | None,
    county_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    quartiles = _build_domain_quartiles_payload(quartile_row)
    features: list[dict[str, Any]] = []
    for row in county_rows:
        designated = _safe_bool(row.get("designated"))
        score_value = _safe_float(row.get("value"))
        tier = assign_hpsa_tier(
            designated=designated,
            value=score_value,
            q25=quartiles.get("q25"),
            q50=quartiles.get("q50"),
            q75=quartiles.get("q75"),
        )
        features.append(
            {
                "county_fips": str(row.get("county_fips")),
                "value": score_value,
                "designated": bool(designated),
                "tier": tier,
            }
        )

    payload = HPSAChoroplethCountiesResponse(
        domain=domain,
        quartiles=HPSADomainQuartiles(**quartiles),
        features=features,
    )
    return payload.model_dump(mode="python")


def build_hpsa_counties_geojson_response(
    *,
    domain: HPSADomain,
    quartile_row: Mapping[str, Any] | None,
    county_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    quartiles = _build_domain_quartiles_payload(quartile_row)
    features: list[dict[str, Any]] = []
    for row in county_rows:
        designated = _safe_bool(row.get("designated"))
        score_value = _safe_float(row.get("value"))
        tier = assign_hpsa_tier(
            designated=designated,
            value=score_value,
            q25=quartiles.get("q25"),
            q50=quartiles.get("q50"),
            q75=quartiles.get("q75"),
        )
        county_fips = (
            normalize_county_fips(row.get("county_fips") or row.get("geoid"))
            or str(row.get("geoid") or "")
        )
        county_name = row.get("county_name") or row.get("name")
        features.append(
            {
                "type": "Feature",
                "geometry": row.get("geometry"),
                "properties": {
                    "location_id": row.get("location_id"),
                    "locationid": row.get("location_id"),
                    "geoid": row.get("geoid"),
                    "name": row.get("name"),
                    "statefp": row.get("statefp"),
                    "countyfp": row.get("countyfp"),
                    "county_fips": county_fips,
                    "state_abbr": row.get("state_abbr"),
                    "state_desc": row.get("state_desc"),
                    "county_name": county_name,
                    "location_name": county_name,
                    "value": score_value,
                    "data_value": score_value,
                    "designated": bool(designated),
                    "tier": tier,
                    "hpsa_domain": domain,
                    "dataset": "hpsa",
                    "geo_level": "county",
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "metadata": {
            "domain": domain,
            "quartiles": quartiles,
        },
        "features": features,
    }


def build_hpsa_county_domain_detail(
    *,
    row: Mapping[str, Any],
    domain: HPSADomain,
    quartile_row: Mapping[str, Any] | None = None,
    ratio_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fields = HPSA_DOMAIN_FIELDS[domain]
    quartiles = _build_domain_quartiles_payload(quartile_row)
    designated = _safe_bool(row.get(fields["designated"]))
    score_value = _safe_float(row.get(fields["score"]))
    tier = assign_hpsa_tier(
        designated=designated,
        value=score_value,
        q25=quartiles.get("q25"),
        q50=quartiles.get("q50"),
        q75=quartiles.get("q75"),
    )
    ratios = ratio_fields if isinstance(ratio_fields, Mapping) else {}

    payload = HPSACountyDomainDetailResponse(
        county_fips=str(row.get("county_fips")),
        state_fips=row.get("state_fips"),
        domain=domain,
        designated=designated,
        score_max=_safe_int(row.get(fields["score"])),
        tier=tier,
        population_covered=_safe_int(row.get(fields["population"])),
        coverage_pct=_safe_float(row.get(fields["coverage_pct"])),
        hpsa_formal_ratio=_normalize_ratio_text(ratios.get("hpsa_formal_ratio")),
        provider_ratio_goal=_normalize_ratio_text(ratios.get("provider_ratio_goal")),
        fte=_safe_float(ratios.get("fte")),
        methodology=build_hpsa_methodology(row),
    )
    return payload.model_dump(mode="python")


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
