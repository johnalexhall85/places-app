from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.profile_pdf_full import (
    MISSING_TEXT,
    _escape_text,
    _extract_paragraph_and_bullets,
    _format_moe,
    _format_value,
    _ordinal,
    _render_bullets,
    _render_paragraph,
    _safe_float,
    _sanitize_text,
    _scale_image,
)
from app.services.report_branding import (
    BrandedNumberedCanvas,
    DOC_BOTTOM_MARGIN,
    DOC_LEFT_MARGIN,
    DOC_RIGHT_MARGIN,
    DOC_TOP_MARGIN,
    brief_report_styles,
    compact_table_style_commands,
)

_BRIEF_CHART_NAME = "bars_comparison"


def _section_map(narrative: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_sections = (
        narrative.get("plain_language_sections")
        if isinstance(narrative.get("plain_language_sections"), list)
        else narrative.get("sections")
    )
    mapping: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_sections, list):
        return mapping
    for section in raw_sections:
        if not isinstance(section, dict):
            continue
        section_id = _sanitize_text(section.get("section_id"), allow_empty=True).lower()
        title = _sanitize_text(section.get("title"), allow_empty=True).lower()
        key = re.sub(r"[^a-z0-9]+", "_", section_id or title).strip("_")
        if key:
            mapping[key] = section
    return mapping


def _truncate_sentences(text: str, *, max_sentences: int, max_chars: int) -> str:
    normalized = _sanitize_text(text, allow_empty=True)
    if not normalized:
        return MISSING_TEXT
    sentence_parts = re.split(r"(?<=[.!?])\s+", normalized)
    sentence_parts = [part.strip() for part in sentence_parts if part.strip()]
    if sentence_parts:
        truncated = " ".join(sentence_parts[:max_sentences]).strip()
    else:
        truncated = normalized
    if len(truncated) <= max_chars:
        return truncated
    clipped = truncated[: max_chars - 1].rstrip()
    if clipped.endswith((".", "!", "?")):
        return clipped
    return f"{clipped}."


def _ensure_summary_caution(summary: str) -> str:
    normalized = _sanitize_text(summary, allow_empty=True)
    lower = normalized.lower()
    if "model" in lower or "uncert" in lower or "confidence interval" in lower:
        return normalized
    return (
        f"{normalized} These estimates include uncertainty and should be used for planning and "
        "situational awareness, not as proof of cause."
    )


def _delta_text(local: float | None, reference: float | None, *, unit: Any) -> str:
    if local is None or reference is None:
        return MISSING_TEXT
    diff = local - reference
    if abs(diff) < 0.05:
        return "About the same"
    unit_suffix = "percentage points" if str(unit or "").strip() in {"%", "percent", "Percent"} else "units"
    direction = "above" if diff > 0 else "below"
    return f"{abs(diff):.1f} {unit_suffix} {direction}"


def _row_value_with_moe(value: Any, *, unit: Any, moe: Any) -> str:
    value_text = _format_value(value, unit=unit)
    moe_text = _format_moe(moe, unit=unit)
    if moe_text == MISSING_TEXT:
        return value_text
    # Keep compact by stripping the MOE label.
    compact_moe = moe_text.replace("MOE: ", "").replace("+/-", "±").strip()
    return f"{value_text} ({compact_moe})"


def _add_compact_table(
    story: list[Any],
    rows: list[list[str]],
    *,
    col_widths: list[float],
) -> None:
    if not rows:
        return
    table = Table(rows, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            compact_table_style_commands(
                font_size=8.6,
                right_align_columns=[1, 2, 3],
            )
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.10 * inch))


def _top_bullets(section: dict[str, Any] | None, *, max_items: int) -> list[str]:
    if not isinstance(section, dict):
        return []
    _, bullets = _extract_paragraph_and_bullets(section.get("paragraph"), section.get("bullets"))
    return bullets[:max_items]


def _fallback_standout_bullets(profile_json: dict[str, Any], *, max_items: int) -> list[str]:
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
    places = (
        profile_json.get("places_measure")
        if isinstance(profile_json.get("places_measure"), dict)
        else {}
    )
    places_comp = comparisons.get("places") if isinstance(comparisons.get("places"), dict) else {}

    unit = places.get("unit") or "%"
    measure_name = _sanitize_text(
        places.get("short_question_text") or places.get("measure") or places.get("measure_id"),
    )
    percentile = _safe_float(references.get("us_percentile"))
    local = _safe_float(places_comp.get("location_value"))
    state = _safe_float(places_comp.get("state_mean"))
    us = _safe_float(places_comp.get("us_mean"))

    bullets: list[str] = []
    if percentile is not None:
        if percentile >= 75:
            bullets.append(
                f"Higher than most counties in the U.S.: {measure_name} is around the "
                f"{_ordinal(percentile)} percentile."
            )
        elif percentile <= 25:
            bullets.append(
                f"Lower than typical nationally: {measure_name} is around the {_ordinal(percentile)} percentile."
            )
        else:
            bullets.append(f"Near the national middle range: {_ordinal(percentile)} percentile.")

    if local is not None and state is not None:
        bullets.append(
            f"Compared with state average: {_delta_text(local, state, unit=unit)} "
            f"({_format_value(local, unit=unit)} local vs {_format_value(state, unit=unit)} state)."
        )
    if local is not None and us is not None:
        bullets.append(
            f"Compared with U.S. average: {_delta_text(local, us, unit=unit)} "
            f"({_format_value(local, unit=unit)} local vs {_format_value(us, unit=unit)} U.S.)."
        )
    return bullets[:max_items]


def _factor_bullets(profile_json: dict[str, Any], *, max_items: int) -> list[str]:
    acs_nmf = profile_json.get("acs_nmf") if isinstance(profile_json.get("acs_nmf"), dict) else {}
    comparisons = (
        profile_json.get("comparisons")
        if isinstance(profile_json.get("comparisons"), dict)
        else {}
    )
    places = (
        profile_json.get("places_measure")
        if isinstance(profile_json.get("places_measure"), dict)
        else {}
    )
    place_measure_name = _sanitize_text(
        places.get("short_question_text") or places.get("measure") or places.get("measure_id"),
    )
    geography = _sanitize_text(profile_json.get("geography"), allow_empty=True).lower()
    geography_label = "tracts" if geography == "tract" else "counties"
    correlates = acs_nmf.get("top_correlates") if isinstance(acs_nmf.get("top_correlates"), list) else []
    acs_primary = (
        comparisons.get("acs_primary")
        if isinstance(comparisons.get("acs_primary"), dict)
        else {}
    )
    acs_primary_measure = _sanitize_text(acs_primary.get("measure") or acs_primary.get("measure_id"), allow_empty=True)
    acs_primary_local = _safe_float(acs_primary.get("location_value"))
    acs_primary_us = _safe_float(acs_primary.get("us_mean"))
    acs_primary_unit = acs_primary.get("unit")

    bullets: list[str] = []
    for correlate in correlates[:max_items]:
        if not isinstance(correlate, dict):
            continue
        name = _sanitize_text(correlate.get("measure") or correlate.get("measure_id"))
        corr_value = _safe_float(correlate.get("correlation"))
        n_pairs = int(_safe_float(correlate.get("n_pairs")) or 0)
        relation_direction = "higher" if (corr_value or 0.0) >= 0 else "lower"

        local_direction = "typical level unavailable"
        if acs_primary_measure and name == acs_primary_measure and acs_primary_local is not None and acs_primary_us is not None:
            if abs(acs_primary_local - acs_primary_us) <= 0.1:
                local_direction = "about typical"
            elif acs_primary_local > acs_primary_us:
                local_direction = "higher than typical"
            else:
                local_direction = "lower than typical"

        if corr_value is not None:
            bullets.append(
                f"{name}: {local_direction}. This factor tends to move together with {place_measure_name} "
                f"across {geography_label} (r={corr_value:.2f}, n={n_pairs}); higher {name} values align with "
                f"{relation_direction} {place_measure_name}. It may be relevant for planning."
            )
        else:
            bullets.append(
                f"{name}: {local_direction}. This factor is included as related context for "
                f"{place_measure_name} and may be relevant for planning."
            )

    if bullets:
        return bullets[:max_items]

    if acs_primary_measure:
        return [
            (
                f"{acs_primary_measure}: {_format_value(acs_primary_local, unit=acs_primary_unit)} local "
                f"vs {_format_value(acs_primary_us, unit=acs_primary_unit)} U.S.; this may be relevant "
                f"to planning context for {place_measure_name}."
            )
        ]
    return ["No stable related context factors were available for this profile."]


def _question_bullets(section: dict[str, Any] | None, *, max_items: int) -> list[str]:
    bullets = _top_bullets(section, max_items=max_items)
    if bullets:
        return bullets
    return [
        "Do high-need areas overlap with lower service access?",
        "Are there gaps in screening or primary care coverage where risk appears higher?",
        "Which populations are most affected and where?",
        "What local data should be reviewed before selecting actions?",
    ][:max_items]


def _key_numbers_rows(profile_json: dict[str, Any], *, max_acs_rows: int) -> list[list[str]]:
    places = (
        profile_json.get("places_measure")
        if isinstance(profile_json.get("places_measure"), dict)
        else {}
    )
    comparisons = (
        profile_json.get("comparisons")
        if isinstance(profile_json.get("comparisons"), dict)
        else {}
    )
    acs_nmf = profile_json.get("acs_nmf") if isinstance(profile_json.get("acs_nmf"), dict) else {}
    location = profile_json.get("location") if isinstance(profile_json.get("location"), dict) else {}

    places_comp = comparisons.get("places") if isinstance(comparisons.get("places"), dict) else {}
    places_unit = places.get("unit") or "%"
    places_name = _sanitize_text(
        places.get("short_question_text") or places.get("measure") or places.get("measure_id"),
    )
    rows = [
        ["Metric", "Local", "State", "U.S."],
        [
            places_name,
            _format_value(places_comp.get("location_value"), unit=places_unit),
            _format_value(places_comp.get("state_mean"), unit=places_unit),
            _format_value(places_comp.get("us_mean"), unit=places_unit),
        ],
    ]

    acs_primary = (
        comparisons.get("acs_primary")
        if isinstance(comparisons.get("acs_primary"), dict)
        else {}
    )
    primary_measure_id = _sanitize_text(acs_primary.get("measure_id"), allow_empty=True)
    acs_rows_added = 0
    if acs_primary:
        rows.append(
            [
                _sanitize_text(acs_primary.get("measure") or acs_primary.get("measure_id")),
                _row_value_with_moe(
                    acs_primary.get("location_value"),
                    unit=acs_primary.get("unit"),
                    moe=acs_primary.get("location_moe"),
                ),
                _format_value(acs_primary.get("state_mean"), unit=acs_primary.get("unit")),
                _format_value(acs_primary.get("us_mean"), unit=acs_primary.get("unit")),
            ]
        )
        acs_rows_added += 1

    location_measures = (
        acs_nmf.get("location_measures")
        if isinstance(acs_nmf.get("location_measures"), list)
        else []
    )
    for measure in location_measures:
        if acs_rows_added >= max_acs_rows:
            break
        if not isinstance(measure, dict):
            continue
        measure_id = _sanitize_text(measure.get("measure_id"), allow_empty=True)
        if primary_measure_id and measure_id == primary_measure_id:
            continue
        rows.append(
            [
                _sanitize_text(measure.get("measure") or measure.get("measure_id")),
                _row_value_with_moe(measure.get("value"), unit=measure.get("unit"), moe=measure.get("moe")),
                "—",
                "—",
            ]
        )
        acs_rows_added += 1

    population = None
    for candidate in (
        location.get("population"),
        location.get("pop_18plus"),
        profile_json.get("population"),
        profile_json.get("population_18plus"),
    ):
        parsed = _safe_float(candidate)
        if parsed is not None:
            population = int(round(parsed))
            break
    if population is not None:
        rows.append(["Population", f"{population:,}", "—", "—"])

    return rows[:10]


def render_profile_pdf_brief(
    *,
    profile_json: dict[str, Any],
    chart_paths: dict[str, str],
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=DOC_LEFT_MARGIN,
        rightMargin=DOC_RIGHT_MARGIN,
        topMargin=DOC_TOP_MARGIN,
        bottomMargin=DOC_BOTTOM_MARGIN,
    )
    styles = brief_report_styles()
    title_style = styles["title"]
    subtitle_style = styles["subtitle"]
    note_style = styles["note"]
    h2_style = styles["h2"]
    body_style = styles["body"]
    small_style = styles["small"]

    narrative = profile_json.get("narrative") if isinstance(profile_json.get("narrative"), dict) else {}
    location = profile_json.get("location") if isinstance(profile_json.get("location"), dict) else {}
    places = (
        profile_json.get("places_measure")
        if isinstance(profile_json.get("places_measure"), dict)
        else {}
    )
    acs_nmf = profile_json.get("acs_nmf") if isinstance(profile_json.get("acs_nmf"), dict) else {}

    section_map = _section_map(narrative)
    standout_section = section_map.get("what_stands_out_here")
    contributing_section = section_map.get("possible_contributing_factors_to_consider")
    questions_section = section_map.get("policy_planning_implications")

    max_standout = 4
    max_factors = 3
    max_questions = 4
    summary_char_limit = 800

    summary_text = narrative.get("summary_paragraph") or narrative.get("summary_text") or MISSING_TEXT
    summary_text = _ensure_summary_caution(
        _truncate_sentences(summary_text, max_sentences=4, max_chars=summary_char_limit)
    )

    standout_bullets = _top_bullets(standout_section, max_items=max_standout)
    if not standout_bullets:
        standout_bullets = _fallback_standout_bullets(profile_json, max_items=max_standout)
    factor_bullets = _factor_bullets(profile_json, max_items=max_factors)
    question_bullets = _question_bullets(questions_section, max_items=max_questions)

    content_weight = (
        len(summary_text)
        + sum(len(item) for item in standout_bullets)
        + sum(len(item) for item in factor_bullets)
        + sum(len(item) for item in question_bullets)
    )
    include_chart = True
    if content_weight > 1900:
        standout_bullets = standout_bullets[:3]
        factor_bullets = factor_bullets[:3]
        question_bullets = question_bullets[:3]
        include_chart = False
    if content_weight > 2400:
        summary_text = _truncate_sentences(summary_text, max_sentences=3, max_chars=520)
        standout_bullets = standout_bullets[:2]
        factor_bullets = factor_bullets[:2]
        question_bullets = question_bullets[:2]
        include_chart = False

    location_name = _sanitize_text(location.get("name") or profile_json.get("location_id"))
    geography = _sanitize_text(profile_json.get("geography"), allow_empty=True) or "area"
    places_year = _sanitize_text(places.get("year"), allow_empty=True) or MISSING_TEXT
    places_measure_name = _sanitize_text(
        places.get("short_question_text") or places.get("measure") or places.get("measure_id")
    )
    acs_window = _sanitize_text(acs_nmf.get("year_window"), allow_empty=True) or MISSING_TEXT

    header_title = f"{location_name} — Local Health & Community Factors Snapshot"
    header_sub = (
        f"Geography: {geography.title()} | PLACES: {places_year}, {places_measure_name} | "
        f"ACS context window: {acs_window}"
    )
    header_note = (
        "Estimates are model-based (PLACES) and survey-based (ACS). For planning and situational awareness."
    )

    story: list[Any] = []
    story.append(
        KeepTogether(
            [
                Paragraph(_escape_text(header_title), title_style),
                Paragraph(_escape_text(header_sub), subtitle_style),
                Paragraph(_escape_text(header_note), note_style),
            ]
        )
    )
    story.append(Spacer(1, 0.04 * inch))

    story.append(Paragraph("Executive Summary", h2_style))
    story.append(_render_paragraph(summary_text, body_style))

    story.append(Paragraph("What stands out", h2_style))
    _render_bullets(story, standout_bullets[:6], style=body_style)

    contributing_intro = None
    if isinstance(contributing_section, dict):
        contributing_intro, _ = _extract_paragraph_and_bullets(
            contributing_section.get("paragraph"),
            contributing_section.get("bullets"),
        )
    story.append(Paragraph("Possible contributing factors to consider", h2_style))
    if contributing_intro:
        story.append(_render_paragraph(contributing_intro, body_style))
    _render_bullets(story, factor_bullets[:3], style=body_style)
    story.append(_render_paragraph("These are associations, not proof of cause.", small_style))

    story.append(Paragraph("Questions to ask next", h2_style))
    _render_bullets(story, question_bullets[:6], style=body_style)

    story.append(Paragraph("Key Numbers", h2_style))
    key_rows = _key_numbers_rows(profile_json, max_acs_rows=4)
    _add_compact_table(
        story,
        key_rows,
        col_widths=[2.8 * inch, 1.15 * inch, 1.05 * inch, 1.05 * inch],
    )

    if include_chart:
        raw_chart_path = chart_paths.get(_BRIEF_CHART_NAME)
        if raw_chart_path:
            chart_path = Path(raw_chart_path)
            if chart_path.exists():
                story.append(Paragraph("Mini Visual", h2_style))
                chart_image = _scale_image(
                    chart_path,
                    max_width=doc.width,
                    max_height=2.0 * inch,
                )
                story.append(chart_image)
                story.append(Spacer(1, 0.08 * inch))

    story.append(Spacer(1, 0.06 * inch))
    story.append(Paragraph("Methods / Limitations", h2_style))
    method_lines = [
        "PLACES values are modeled estimates and are not designed to evaluate local interventions on their own.",
        "ACS context values are rolling 5-year survey estimates; MOE indicates uncertainty.",
        "Use these data for planning, targeting, and situational awareness.",
    ]
    for line in method_lines:
        story.append(_render_paragraph(line, small_style))

    doc.build(story, canvasmaker=BrandedNumberedCanvas)
    return buffer.getvalue()
