from __future__ import annotations

import math
from typing import Any

MISSING_TEXT = "Not available"


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any, *, fallback: str = MISSING_TEXT) -> str:
    normalized = "" if value is None else str(value).strip()
    return normalized if normalized else fallback


def _is_percent_unit(unit: Any) -> bool:
    normalized = str(unit or "").strip().lower()
    return normalized in {"%", "percent", "percentage", "pct"}


def _format_number(value: Any, *, precision: int = 1) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return MISSING_TEXT
    return f"{parsed:.{precision}f}"


def _format_with_unit(value: Any, *, unit: Any, precision: int = 1) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return MISSING_TEXT

    if _is_percent_unit(unit):
        return f"{parsed:.{precision}f}%"

    normalized_unit = str(unit or "").strip()
    if not normalized_unit:
        return f"{parsed:.{precision}f}"
    return f"{parsed:.{precision}f} {normalized_unit}"


def _ordinal(value: Any) -> str:
    parsed = _safe_int(value)
    if parsed is None:
        return MISSING_TEXT
    abs_value = abs(parsed)
    if 10 <= (abs_value % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(abs_value % 10, "th")
    return f"{parsed}{suffix}"


def _geography_explainer(geography: str) -> str:
    normalized = str(geography or "").strip().lower()
    if normalized == "tract":
        return "census tract (a smaller neighborhood-scale statistical area)"
    return "county (a local administrative area)"


def _geography_plural(geography: str) -> str:
    normalized = str(geography or "").strip().lower()
    if normalized == "tract":
        return "tracts"
    if normalized == "county":
        return "counties"
    return "areas"


def _compare_tag(delta: float | None, *, threshold: float) -> str:
    if delta is None:
        return "Comparison unavailable"
    if abs(delta) <= threshold:
        return "Similar to the state average"
    if delta > 0:
        return "Higher than typical"
    return "Lower than typical"


def _national_tag(percentile: float | None) -> str:
    if percentile is None:
        return "National position unavailable"
    if percentile >= 75:
        return "Higher than most counties in the U.S."
    if percentile <= 25:
        return "Lower than typical"
    return "Similar to the national middle range"


def _direction_word(correlation: float | None) -> str:
    if correlation is None:
        return "a mixed"
    return "a higher" if correlation >= 0 else "a lower"


def build_profile_narrative(
    profile_json: dict[str, Any],
    *,
    include_full_narrative: bool,
) -> dict[str, Any]:
    location = profile_json.get("location") if isinstance(profile_json.get("location"), dict) else {}
    places = (
        profile_json.get("places_measure")
        if isinstance(profile_json.get("places_measure"), dict)
        else {}
    )
    references = (
        profile_json.get("reference_stats")
        if isinstance(profile_json.get("reference_stats"), dict)
        else {}
    )
    comparisons = (
        profile_json.get("comparisons")
        if isinstance(profile_json.get("comparisons"), dict)
        else {}
    )
    acs_nmf = profile_json.get("acs_nmf") if isinstance(profile_json.get("acs_nmf"), dict) else {}
    methods_caveats = [
        _clean_text(item, fallback="") for item in (profile_json.get("methods_caveats") or [])
    ]
    methods_caveats = [item for item in methods_caveats if item]

    location_name = _clean_text(
        location.get("name") or profile_json.get("location_id"),
        fallback="Selected area",
    )
    state_abbr = _clean_text(location.get("state_abbr"), fallback="N/A")
    geography = _clean_text(profile_json.get("geography"), fallback="area").lower()

    measure_name = _clean_text(
        places.get("short_question_text") or places.get("measure") or places.get("measure_id"),
        fallback="selected PLACES measure",
    )
    places_unit = places.get("unit") or "%"
    places_year = places.get("year")
    places_value = _safe_float(places.get("location_value"))
    places_ci_low = _safe_float(places.get("location_ci_low"))
    places_ci_high = _safe_float(places.get("location_ci_high"))

    state_stats = references.get("state") if isinstance(references.get("state"), dict) else {}
    us_stats = references.get("us") if isinstance(references.get("us"), dict) else {}
    state_mean = _safe_float(state_stats.get("mean"))
    us_mean = _safe_float(us_stats.get("mean"))
    us_percentile = _safe_float(references.get("us_percentile"))

    acs_primary = (
        comparisons.get("acs_primary")
        if isinstance(comparisons.get("acs_primary"), dict)
        else {}
    )
    acs_primary_measure = _clean_text(
        acs_primary.get("measure") or acs_primary.get("measure_id"),
        fallback="ACS context measure",
    )
    acs_primary_unit = acs_primary.get("unit")
    acs_primary_value = _safe_float(acs_primary.get("location_value"))
    acs_primary_moe = _safe_float(acs_primary.get("location_moe"))
    acs_primary_state = _safe_float(acs_primary.get("state_mean"))
    acs_primary_us = _safe_float(acs_primary.get("us_mean"))

    top_correlates = (
        acs_nmf.get("top_correlates") if isinstance(acs_nmf.get("top_correlates"), list) else []
    )
    acs_year_window = _clean_text(acs_nmf.get("year_window"), fallback=MISSING_TEXT)

    percentile_text = (
        f"{_ordinal(round(us_percentile))} percentile"
        if us_percentile is not None
        else MISSING_TEXT
    )
    state_delta = (
        places_value - state_mean if places_value is not None and state_mean is not None else None
    )
    us_delta = places_value - us_mean if places_value is not None and us_mean is not None else None

    summary_parts = [
        (
            f"{location_name}, {state_abbr} has an estimated "
            f"{_format_with_unit(places_value, unit=places_unit)} for {measure_name}"
            f"{f' ({places_year})' if places_year else ''}."
        ),
        (
            f"It is around the {percentile_text} nationally, with a state average of "
            f"{_format_with_unit(state_mean, unit=places_unit)} and a U.S. average of "
            f"{_format_with_unit(us_mean, unit=places_unit)}."
        ),
        (
            "These are descriptive modeled and survey estimates and should be used for planning, "
            "not as proof of cause-and-effect."
        ),
    ]
    summary_paragraph = " ".join(summary_parts)

    if not include_full_narrative:
        return {
            "summary_text": summary_paragraph,
            "summary_paragraph": summary_paragraph,
            "plain_language_sections": [],
            "technical_methods_section": {},
            "sections": [],
        }

    what_you_are_looking_at = {
        "section_id": "what_you_are_looking_at",
        "title": "What you are looking at",
        "paragraph": (
            "This profile combines PLACES health estimates and ACS non-medical factor estimates "
            f"for the selected {_geography_explainer(geography)}."
        ),
        "bullets": [
            (
                "PLACES values are modeled estimates of adult health outcomes and risk factors for "
                "small areas."
            ),
            (
                "ACS values are survey-based estimates from a rolling 5-year window and include a "
                "margin of error (MOE)."
            ),
            (
                f"Geography shown: {location_name}, {state_abbr}. PLACES year: "
                f"{places_year or MISSING_TEXT}; ACS window: {acs_year_window}."
            ),
        ],
    }

    how_to_interpret = {
        "section_id": "how_to_interpret_the_numbers",
        "title": "How to interpret the numbers",
        "paragraph": (
            f"For PLACES, {_format_with_unit(places_value, unit=places_unit)} means the estimated "
            f"share of adults with {measure_name} in this area."
        ),
        "bullets": [
            (
                "For PLACES prevalence, read values as estimated percentages of adults, with 95% "
                "confidence intervals indicating uncertainty."
            ),
            (
                "For ACS NMF, read values as 5-year survey estimates; MOE indicates the likely range "
                "around each point estimate."
            ),
            (
                "Comparisons to state and U.S. are descriptive reference points. They do not prove "
                "that one factor causes another."
            ),
        ],
    }

    key_findings: list[str] = []
    key_findings.append(
        (
            f"{_national_tag(us_percentile)}: {measure_name} is "
            f"{_format_with_unit(places_value, unit=places_unit)} "
            f"({percentile_text} nationally)."
        )
    )

    state_tag = _compare_tag(state_delta, threshold=1.0)
    if state_delta is None:
        key_findings.append(
            f"State comparison unavailable: state average for this measure is {MISSING_TEXT}."
        )
    elif abs(state_delta) <= 1.0:
        key_findings.append(
            (
                f"{state_tag}: this area is within about 1 percentage point of the state average "
                f"({_format_with_unit(state_mean, unit=places_unit)})."
            )
        )
    elif state_delta > 0:
        key_findings.append(
            (
                f"{state_tag}: this area is {abs(state_delta):.1f} percentage points above the state "
                f"average ({_format_with_unit(state_mean, unit=places_unit)})."
            )
        )
    else:
        key_findings.append(
            (
                f"{state_tag}: this area is {abs(state_delta):.1f} percentage points below the state "
                f"average ({_format_with_unit(state_mean, unit=places_unit)})."
            )
        )

    if us_delta is None:
        key_findings.append(f"U.S. comparison unavailable: U.S. average is {MISSING_TEXT}.")
    elif abs(us_delta) <= 1.0:
        key_findings.append(
            (
                "Similar to the national average: this area is within about 1 percentage point of "
                f"the U.S. average ({_format_with_unit(us_mean, unit=places_unit)})."
            )
        )
    elif us_delta > 0:
        key_findings.append(
            (
                "Higher than typical nationally: this area is "
                f"{abs(us_delta):.1f} percentage points above the U.S. average "
                f"({_format_with_unit(us_mean, unit=places_unit)})."
            )
        )
    else:
        key_findings.append(
            (
                "Lower than typical nationally: this area is "
                f"{abs(us_delta):.1f} percentage points below the U.S. average "
                f"({_format_with_unit(us_mean, unit=places_unit)})."
            )
        )

    if places_ci_low is not None and places_ci_high is not None:
        half_width = abs(places_ci_high - places_ci_low) / 2.0
        key_findings.append(
            (
                "Uncertainty note: PLACES reports a 95% confidence interval of "
                f"{_format_with_unit(places_ci_low, unit=places_unit)} to "
                f"{_format_with_unit(places_ci_high, unit=places_unit)} "
                f"(about +/- {half_width:.1f} percentage points)."
            )
        )
    else:
        key_findings.append(
            "Uncertainty note: confidence interval details were not available for this PLACES value."
        )

    if acs_primary_value is not None:
        acs_state_delta = (
            acs_primary_value - acs_primary_state
            if acs_primary_state is not None
            else None
        )
        moe_suffix = (
            f" MOE: +/- {_format_number(acs_primary_moe, precision=1)}."
            if acs_primary_moe is not None
            else ""
        )
        if acs_state_delta is None or abs(acs_state_delta) <= 1.0:
            relationship = "similar to the state average"
        elif acs_state_delta > 0:
            relationship = "above the state average"
        else:
            relationship = "below the state average"
        key_findings.append(
            (
                f"ACS context: {acs_primary_measure} is "
                f"{_format_with_unit(acs_primary_value, unit=acs_primary_unit)}, {relationship} "
                f"({_format_with_unit(acs_primary_state, unit=acs_primary_unit)} state, "
                f"{_format_with_unit(acs_primary_us, unit=acs_primary_unit)} U.S.).{moe_suffix}"
            )
        )

    key_findings_section = {
        "section_id": "what_stands_out_here",
        "title": "What stands out here",
        "paragraph": (
            "These highlights summarize where this area sits relative to state and national "
            "reference points."
        ),
        "bullets": key_findings[:5],
    }

    contributing_bullets: list[str] = [
        "Correlation does not mean one causes the other."
    ]
    for correlate in top_correlates[:3]:
        corr_value = _safe_float(correlate.get("correlation"))
        n_pairs = _safe_int(correlate.get("n_pairs"))
        correlate_measure = _clean_text(
            correlate.get("measure") or correlate.get("measure_id"),
            fallback="ACS context measure",
        )
        if corr_value is None:
            continue
        contributing_bullets.append(
            (
                f"{correlate_measure}: moves together with {measure_name} (r={corr_value:.2f}, "
                f"n={n_pairs or 0}). Across comparable {_geography_plural(geography)}, places with higher "
                f"{correlate_measure} tend to show {_direction_word(corr_value)} level of "
                f"{measure_name}; this may be related to shared conditions."
            )
        )
    if len(contributing_bullets) == 1:
        contributing_bullets.append(
            "No stable ACS correlation passed the minimum paired-observation requirement."
        )

    contributing_section = {
        "section_id": "possible_contributing_factors_to_consider",
        "title": "Possible contributing factors to consider",
        "paragraph": (
            "Related context indicators can help guide follow-up questions. These relationships are "
            "descriptive."
        ),
        "bullets": contributing_bullets,
    }

    policy_questions: list[str] = [
        "Are there service access gaps in areas where this estimate is highest?",
        (
            f"Do areas with higher {acs_primary_measure} overlap with higher {measure_name} in local "
            "maps or administrative data?"
        ),
        "Which communities may need targeted outreach or communication support?",
        "Do observed differences remain after accounting for confidence intervals and MOE?",
        "What local datasets could help validate these patterns before policy action?",
    ]

    policy_section = {
        "section_id": "policy_planning_implications",
        "title": "Policy / planning implications (questions to ask next)",
        "paragraph": (
            "Use these findings to frame neutral planning questions rather than direct conclusions "
            "about causes."
        ),
        "bullets": policy_questions,
    }

    limitations_bullets = [
        (
            "PLACES values are modeled estimates and are best used for planning and prioritization, "
            "not for evaluating local interventions on their own."
        ),
        (
            "ACS non-medical factor values are rolling 5-year estimates; adjacent windows overlap and "
            "are not independent year-to-year snapshots."
        ),
        "MOE and confidence intervals indicate uncertainty around estimates.",
        "Smaller populations, especially at tract level, can have wider uncertainty.",
        "Missing values are shown as Not available.",
    ]
    limitations_section = {
        "section_id": "data_limitations_and_cautions",
        "title": "Data limitations and cautions",
        "paragraph": (
            "Interpret results with uncertainty in mind, especially for small-area estimates."
        ),
        "bullets": limitations_bullets,
    }

    technical_methods_bullets = [
        "State and U.S. comparisons are descriptive summaries of available values in this app.",
        "Correlations are computed from finite paired observations only and are shown for context.",
    ]
    for caveat in methods_caveats:
        if caveat not in technical_methods_bullets:
            technical_methods_bullets.append(caveat)
    technical_methods_section = {
        "section_id": "technical_methods",
        "title": "Technical methods",
        "paragraph": (
            "Technical notes are included for transparency and should be read with the plain-language "
            "interpretation above."
        ),
        "bullets": technical_methods_bullets,
    }

    plain_language_sections = [
        what_you_are_looking_at,
        how_to_interpret,
        key_findings_section,
        contributing_section,
        policy_section,
        limitations_section,
    ]

    ordered_sections = [*plain_language_sections, technical_methods_section]

    return {
        "summary_text": summary_paragraph,
        "summary_paragraph": summary_paragraph,
        "plain_language_sections": plain_language_sections,
        "technical_methods_section": technical_methods_section,
        "sections": ordered_sections,
    }
