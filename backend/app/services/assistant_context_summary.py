from __future__ import annotations

import re
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.map_context import MapContext
from app.services.assistant_tools_impl import (
    get_estimate_county,
    get_estimate_nation,
    get_estimate_state,
)
from app.services.hpsa_summary import (
    build_hpsa_county_domain_detail,
    fetch_county_hpsa_row,
    fetch_hpsa_domain_quartiles,
    fetch_hpsa_domain_ratio_fields,
    normalize_county_fips,
    normalize_hpsa_domain,
)

HPSA_DOMAIN_LABELS = {
    "pc": "Primary Care",
    "mh": "Mental Health",
    "dh": "Dental",
}
HPSA_SEVERITY_LABELS = {
    1: "Lower",
    2: "Moderate",
    3: "High",
    4: "Very high",
}
SUGGESTED_FOLLOWUPS = [
    "How does this compare to nearby counties?",
    "Which areas have high disease burden and high shortage severity?",
    "What interventions are commonly used in high-shortage counties?",
]
YEAR_WINDOW_RE = re.compile(r"^(\d{4})\s*-\s*(\d{4})$")


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _safe_int(value: Any) -> int | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def _format_pct(value: Any, digits: int = 1) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "Not available"
    return f"{parsed:.{digits}f}%"


def _format_number(value: Any) -> str:
    parsed = _safe_int(value)
    if parsed is None:
        return "Not available"
    return f"{parsed:,}"


def _format_ci(value: Any, ci_low: Any, ci_high: Any) -> str:
    value_num = _safe_float(value)
    low_num = _safe_float(ci_low)
    high_num = _safe_float(ci_high)
    if value_num is None:
        return "Data unavailable"
    if low_num is None or high_num is None:
        return f"{value_num:.1f}% (95% CI unavailable)"
    return f"{value_num:.1f}% (95% CI {low_num:.1f} to {high_num:.1f})"


def _normalize_data_source(value: str | None) -> str:
    token = str(value or "").strip().upper()
    if token == "PLACES":
        return token
    if token in {"ACS", "ACS_NMF", "ACS-NMF"}:
        return "ACS"
    if token == "SVI":
        return token
    if token == "HPSA":
        return token
    lowered = token.lower()
    if lowered == "places":
        return "PLACES"
    if lowered in {"acs_nmf", "acs-nmf", "acs"}:
        return "ACS"
    if lowered == "svi":
        return "SVI"
    if lowered == "hpsa":
        return "HPSA"
    return token


def _parse_year(value: str | None) -> int | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    if re.fullmatch(r"\d{4}", text_value):
        return int(text_value)
    match = YEAR_WINDOW_RE.match(text_value)
    if not match:
        return None
    return int(match.group(2))


def _build_area_name(
    *,
    selected_area: Mapping[str, Any],
    county_fips: str | None,
    county_name: str | None,
    state_abbr: str | None,
) -> tuple[str, str | None]:
    selected_name = str(selected_area.get("name") or "").strip()
    if selected_name:
        area_name = selected_name
    elif county_name:
        area_name = county_name
    elif county_fips:
        area_name = county_fips
    else:
        area_name = "Selected area"

    state = str(selected_area.get("stateAbbr") or state_abbr or "").strip().upper() or None
    return area_name, state


def _lookup_county_identity(db: Session, county_fips: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            SELECT
                location_id AS county_fips,
                county_name,
                state_abbr
            FROM dim_county
            WHERE location_id = :county_fips
            LIMIT 1
            """
        ),
        {"county_fips": county_fips},
    ).mappings().one_or_none()
    if row is None:
        return {
            "county_fips": county_fips,
            "county_name": None,
            "state_abbr": None,
        }
    return {
        "county_fips": str(row.get("county_fips") or county_fips),
        "county_name": str(row.get("county_name") or "").strip() or None,
        "state_abbr": str(row.get("state_abbr") or "").strip().upper() or None,
    }


def _source_context_label(source: str, detail: str, area_name: str, state_abbr: str | None) -> str:
    location = f"{area_name}, {state_abbr}" if state_abbr else area_name
    if detail:
        return f"{source} \u2022 {detail} \u2022 {location}"
    return f"{source} \u2022 {location}"


def _hpsa_summary(map_context: MapContext, db: Session) -> dict[str, Any] | None:
    geo_level = str(map_context.geoLevel or "").strip().lower()
    selected_area = map_context.selectedArea.model_dump(mode="python")
    if geo_level != "county":
        return None

    county_fips = normalize_county_fips(selected_area.get("countyFips"))
    if county_fips is None:
        return None

    raw_domain = map_context.selection.hpsaDomain or "pc"
    domain = normalize_hpsa_domain(raw_domain, default="pc")
    if domain is None:
        domain = "pc"
    domain_label = HPSA_DOMAIN_LABELS[domain]

    row = fetch_county_hpsa_row(db, county_fips)
    if row is None:
        return None

    quartile_row = fetch_hpsa_domain_quartiles(db, domain)
    ratio_fields = fetch_hpsa_domain_ratio_fields(
        db,
        county_fips=county_fips,
        domain=domain,
    )
    detail = build_hpsa_county_domain_detail(
        row=row,
        domain=domain,
        quartile_row=quartile_row,
        ratio_fields=ratio_fields,
    )
    county_identity = _lookup_county_identity(db, county_fips)
    area_name, state_abbr = _build_area_name(
        selected_area=selected_area,
        county_fips=county_fips,
        county_name=county_identity.get("county_name"),
        state_abbr=county_identity.get("state_abbr"),
    )
    title_location = f"{area_name}, {state_abbr}" if state_abbr else area_name

    designated = bool(detail.get("designated"))
    tier = _safe_int(detail.get("tier"))
    score = _safe_int(detail.get("score_max"))
    severity = HPSA_SEVERITY_LABELS.get(tier, "Not designated") if designated else "Not designated"

    methodology = detail.get("methodology") if isinstance(detail.get("methodology"), dict) else {}
    caveats = methodology.get("caveats") if isinstance(methodology.get("caveats"), list) else []
    coverage_caveat_line = str(caveats[0]).strip() if caveats else ""

    bullets: list[str]
    if designated:
        bullets = [
            f"This county is designated as a {domain_label} Health Professional Shortage Area.",
            "Severity is based on quartiles among designated counties.",
            "Higher HPSA scores indicate greater provider shortage severity.",
        ]
        coverage_pct = _safe_float(detail.get("coverage_pct"))
        population_covered = _safe_int(detail.get("population_covered"))
        if coverage_pct is not None or population_covered is not None:
            bullets.append(
                f"Estimated coverage is {_format_pct(coverage_pct)} with population covered {_format_number(population_covered)}."
            )
            if coverage_caveat_line:
                bullets.append(coverage_caveat_line)
    else:
        bullets = [
            f"This county is not designated as a {domain_label} Health Professional Shortage Area.",
            "Not designated means the county does not currently meet federal HPSA designation criteria for this domain.",
        ]

    methodology_snippet_parts = []
    source_text = str(methodology.get("source") or "").strip()
    as_of_date = str(methodology.get("as_of_date") or map_context.asOfDate or "").strip()
    if source_text:
        methodology_snippet_parts.append(source_text)
    if as_of_date:
        methodology_snippet_parts.append(f"As of {as_of_date}")
    methodology_snippet = ". ".join(methodology_snippet_parts) or None

    return {
        "context_chip": _source_context_label("HPSA", domain_label, area_name, state_abbr),
        "title": f"{domain_label} Provider Shortage \u2014 {title_location}",
        "bullets": bullets,
        "stats": [
            {"label": "Severity", "value": severity},
            {"label": "Tier", "value": str(tier) if tier is not None else "Not available"},
            {"label": "Score", "value": str(score) if score is not None else "Not available"},
            {
                "label": "Formal ratio",
                "value": str(detail.get("hpsa_formal_ratio") or "Not available"),
            },
            {
                "label": "Coverage",
                "value": _format_pct(detail.get("coverage_pct")),
            },
            {
                "label": "Population covered",
                "value": _format_number(detail.get("population_covered")),
            },
        ],
        "methodology": methodology_snippet,
        "suggestedQuestions": SUGGESTED_FOLLOWUPS,
        "dataSource": "HPSA",
    }


def _lookup_places_measure_name(db: Session, measure_id: str) -> str:
    row = db.execute(
        text(
            """
            SELECT measure
            FROM dim_measure
            WHERE measure_id = :measure_id
            ORDER BY measure
            LIMIT 1
            """
        ),
        {"measure_id": measure_id},
    ).mappings().one_or_none()
    if row is None:
        return measure_id
    return str(row.get("measure") or measure_id)


def _places_summary(map_context: MapContext, db: Session) -> dict[str, Any] | None:
    selected_area = map_context.selectedArea.model_dump(mode="python")
    county_fips = normalize_county_fips(selected_area.get("countyFips"))
    if county_fips is None:
        return None

    selection = map_context.selection
    measure_id = str(selection.placesMeasureId or "").strip()
    year = selection.placesYear
    data_type = str(selection.placesValueTypeId or "").strip()
    if not measure_id or year is None or not data_type:
        return None

    county = get_estimate_county(
        db,
        county_fips=county_fips,
        measure_id=measure_id,
        year=int(year),
        data_value_type_id=data_type,
    )
    county_identity = _lookup_county_identity(db, county_fips)
    area_name, state_abbr = _build_area_name(
        selected_area=selected_area,
        county_fips=county_fips,
        county_name=county_identity.get("county_name"),
        state_abbr=county_identity.get("state_abbr"),
    )
    measure_label = _lookup_places_measure_name(db, measure_id)

    state_estimate = None
    if state_abbr:
        state_estimate = get_estimate_state(
            db,
            state_abbr=state_abbr,
            measure_id=measure_id,
            year=int(year),
            data_value_type_id=data_type,
        )
    national_estimate = get_estimate_nation(
        db,
        measure_id=measure_id,
        year=int(year),
        data_value_type_id=data_type,
    )

    title_location = f"{area_name}, {state_abbr}" if state_abbr else area_name
    bullets = [
        f"This summary uses PLACES {year} values for {measure_label}.",
        f"County estimate: {_format_ci(county.get('value'), county.get('ci_low'), county.get('ci_high'))}.",
        "Values come directly from stored PLACES county/state/national estimates.",
    ]

    return {
        "context_chip": _source_context_label(
            "PLACES",
            f"{measure_id} \u2022 {year}",
            area_name,
            state_abbr,
        ),
        "title": f"PLACES Estimate \u2014 {title_location}",
        "bullets": bullets,
        "stats": [
            {
                "label": "County",
                "value": _format_ci(county.get("value"), county.get("ci_low"), county.get("ci_high")),
            },
            {
                "label": "State",
                "value": (
                    _format_ci(
                        state_estimate.get("value"),
                        state_estimate.get("ci_low"),
                        state_estimate.get("ci_high"),
                    )
                    if isinstance(state_estimate, dict)
                    else "Data unavailable"
                ),
            },
            {
                "label": "US",
                "value": _format_ci(
                    national_estimate.get("value"),
                    national_estimate.get("ci_low"),
                    national_estimate.get("ci_high"),
                ),
            },
            {"label": "Measure", "value": measure_id},
            {"label": "Value type", "value": data_type},
            {"label": "Year", "value": str(year)},
        ],
        "methodology": None,
        "suggestedQuestions": SUGGESTED_FOLLOWUPS,
        "dataSource": "PLACES",
    }


def _resolve_svi_year(
    db: Session,
    *,
    county_fips: str,
    requested_year: int | None,
) -> int | None:
    if requested_year is not None:
        return requested_year
    row = db.execute(
        text(
            """
            SELECT MAX(year) AS year
            FROM svi_estimates_county
            WHERE geoid = :county_fips
            """
        ),
        {"county_fips": county_fips},
    ).mappings().one_or_none()
    if row is None:
        return None
    return _safe_int(row.get("year"))


def _svi_summary(map_context: MapContext, db: Session) -> dict[str, Any] | None:
    selected_area = map_context.selectedArea.model_dump(mode="python")
    county_fips = normalize_county_fips(selected_area.get("countyFips"))
    if county_fips is None:
        return None

    selection = map_context.selection
    requested_year = selection.sviYear
    if requested_year is None:
        requested_year = _parse_year(map_context.asOfDate)
    year = _resolve_svi_year(
        db,
        county_fips=county_fips,
        requested_year=requested_year,
    )
    if year is None:
        return None

    measure_id = str(
        selection.sviMeasureId
        or selection.sviTheme
        or "RPL_THEMES"
    ).strip().upper()

    value_rows = db.execute(
        text(
            """
            SELECT measure_id, value
            FROM svi_estimates_county
            WHERE geoid = :county_fips
              AND year = :year
              AND measure_id IN ('RPL_THEMES', 'RPL_THEME1', 'RPL_THEME2', 'RPL_THEME3', 'RPL_THEME4', :measure_id)
            """
        ),
        {
            "county_fips": county_fips,
            "year": year,
            "measure_id": measure_id,
        },
    ).mappings().all()
    if not value_rows:
        return None

    value_map = {
        str(row.get("measure_id") or "").upper(): _safe_float(row.get("value"))
        for row in value_rows
    }

    metadata_rows = db.execute(
        text(
            """
            SELECT measure_id, name
            FROM svi_measures
            WHERE geography_level = 'county'
              AND year = :year
              AND measure_id IN ('RPL_THEMES', :measure_id)
            """
        ),
        {"year": year, "measure_id": measure_id},
    ).mappings().all()
    metadata_map = {
        str(row.get("measure_id") or "").upper(): str(row.get("name") or "").strip()
        for row in metadata_rows
    }

    county_identity = _lookup_county_identity(db, county_fips)
    area_name, state_abbr = _build_area_name(
        selected_area=selected_area,
        county_fips=county_fips,
        county_name=county_identity.get("county_name"),
        state_abbr=county_identity.get("state_abbr"),
    )
    selected_value = value_map.get(measure_id)
    overall_value = value_map.get("RPL_THEMES")
    measure_label = metadata_map.get(measure_id) or measure_id

    bullets = [
        f"SVI ranks range from 0 to 1.0; higher values indicate greater vulnerability.",
        f"Selected measure ({measure_label}) rank: {selected_value:.4f}."
        if selected_value is not None
        else f"No county value is available for {measure_label}.",
        "Theme values shown are from the same SVI year and county record.",
    ]

    return {
        "context_chip": _source_context_label("SVI", str(year), area_name, state_abbr),
        "title": f"Social Vulnerability Summary \u2014 {area_name}{', ' + state_abbr if state_abbr else ''}",
        "bullets": bullets,
        "stats": [
            {"label": "Year", "value": str(year)},
            {"label": "Overall rank (RPL_THEMES)", "value": f"{overall_value:.4f}" if overall_value is not None else "Not available"},
            {"label": f"{measure_id} rank", "value": f"{selected_value:.4f}" if selected_value is not None else "Not available"},
        ],
        "methodology": "CDC/ATSDR SVI county percentile rankings.",
        "suggestedQuestions": SUGGESTED_FOLLOWUPS,
        "dataSource": "SVI",
    }


def _resolve_acs_row(
    db: Session,
    *,
    county_fips: str,
    measure_id: str,
    year_window: str | None,
    data_value_type_id: str | None,
) -> Mapping[str, Any] | None:
    params: dict[str, Any] = {
        "county_fips": county_fips,
        "measure_id": measure_id,
    }
    filters = [
        "location_id = :county_fips",
        "measure_id = :measure_id",
    ]
    if year_window:
        params["year_window"] = year_window
        filters.append("year_window = :year_window")
    if data_value_type_id:
        params["data_value_type_id"] = data_value_type_id
        filters.append("data_value_type_id = :data_value_type_id")

    filter_sql = " AND ".join(filters)
    row = db.execute(
        text(
            f"""
            SELECT
                year_window,
                location_name,
                state_abbr,
                measure_id,
                measure,
                data_value_type_id,
                data_value_type,
                data_value,
                moe
            FROM acs_nmf_county_estimates
            WHERE {filter_sql}
            ORDER BY
                CASE
                    WHEN year_window ~ '^[0-9]{{4}}-[0-9]{{4}}$'
                    THEN split_part(year_window, '-', 2)::int
                    ELSE NULL
                END DESC NULLS LAST,
                year_window DESC
            LIMIT 1
            """
        ),
        params,
    ).mappings().one_or_none()
    return row


def _acs_summary(map_context: MapContext, db: Session) -> dict[str, Any] | None:
    selected_area = map_context.selectedArea.model_dump(mode="python")
    county_fips = normalize_county_fips(selected_area.get("countyFips"))
    if county_fips is None:
        return None

    selection = map_context.selection
    measure_id = str(selection.acsVariable or "").strip()
    if not measure_id:
        return None

    year_window = str(selection.acsYearWindow or map_context.asOfDate or "").strip() or None
    data_value_type_id = str(selection.acsDataValueTypeId or "").strip() or None
    row = _resolve_acs_row(
        db,
        county_fips=county_fips,
        measure_id=measure_id,
        year_window=year_window,
        data_value_type_id=data_value_type_id,
    )
    if row is None:
        return None

    county_identity = _lookup_county_identity(db, county_fips)
    area_name, state_abbr = _build_area_name(
        selected_area=selected_area,
        county_fips=county_fips,
        county_name=county_identity.get("county_name"),
        state_abbr=county_identity.get("state_abbr"),
    )
    value = _safe_float(row.get("data_value"))
    moe = _safe_float(row.get("moe"))
    resolved_year_window = str(row.get("year_window") or year_window or "unknown")
    resolved_type = str(row.get("data_value_type_id") or data_value_type_id or "value")

    bullets = [
        f"This ACS NMF summary uses year window {resolved_year_window}.",
        (
            f"Estimated value is {value:.2f} with margin of error {moe:.2f}."
            if value is not None and moe is not None
            else f"Estimated value is {value:.2f}."
            if value is not None
            else "No county estimate is available for this variable and year window."
        ),
        "Values come directly from ACS NMF county estimate records.",
    ]

    return {
        "context_chip": _source_context_label(
            "ACS",
            f"{measure_id} \u2022 {resolved_year_window}",
            area_name,
            state_abbr,
        ),
        "title": f"ACS Summary \u2014 {area_name}{', ' + state_abbr if state_abbr else ''}",
        "bullets": bullets,
        "stats": [
            {"label": "Measure", "value": str(row.get("measure") or measure_id)},
            {"label": "Year window", "value": resolved_year_window},
            {"label": "Value type", "value": resolved_type},
            {"label": "Value", "value": f"{value:.2f}" if value is not None else "Not available"},
            {"label": "MOE", "value": f"{moe:.2f}" if moe is not None else "Not available"},
        ],
        "methodology": None,
        "suggestedQuestions": SUGGESTED_FOLLOWUPS,
        "dataSource": "ACS",
    }


def build_context_summary(map_context: MapContext, db: Session) -> dict[str, Any] | None:
    source = _normalize_data_source(map_context.dataSource)
    if source == "HPSA":
        return _hpsa_summary(map_context, db)
    if source == "PLACES":
        return _places_summary(map_context, db)
    if source == "SVI":
        return _svi_summary(map_context, db)
    if source == "ACS":
        return _acs_summary(map_context, db)
    return None
