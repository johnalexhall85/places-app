from __future__ import annotations

from html import escape
from io import BytesIO
import math
from pathlib import Path
import re
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.report_branding import (
    BrandedNumberedCanvas,
    DOC_BOTTOM_MARGIN,
    DOC_LEFT_MARGIN,
    DOC_RIGHT_MARGIN,
    DOC_TOP_MARGIN,
    full_report_styles,
    reportlab_fonts,
    standard_table_style_commands,
)

MISSING_TEXT = "Not available"
_BULLET_PREFIX_RE = re.compile(r"^\s*bullet[\s:.\-]*", flags=re.IGNORECASE)
_NAN_INF_RE = re.compile(r"\b(?:nan|inf|infinity|-inf|\+inf)\b", flags=re.IGNORECASE)

CHART_METADATA = {
    "bars_comparison": {
        "title": "Location vs State vs U.S.",
        "caption": (
            "Side-by-side comparison for the selected PLACES measure and the primary ACS context "
            "measure."
        ),
    },
    "us_distribution": {
        "title": "National Distribution",
        "caption": (
            "Distribution across all available U.S. geographies in this dataset, with this location "
            "marked for reference."
        ),
    },
    "scatter_top_correlate": {
        "title": "Top Related Context Measure",
        "caption": (
            "Scatter plot of the PLACES measure against the top ACS measure that moves together with "
            "it in this dataset."
        ),
    },
}


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


def _sanitize_text(value: Any, *, allow_empty: bool = False) -> str:
    raw = "" if value is None else str(value)
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _NAN_INF_RE.sub(MISSING_TEXT, normalized).strip()
    if not normalized and not allow_empty:
        return MISSING_TEXT
    return normalized


def _escape_text(value: Any, *, allow_empty: bool = False) -> str:
    normalized = _sanitize_text(value, allow_empty=allow_empty)
    return escape(normalized).replace("\n", "<br/>")


def _is_percent_unit(unit: Any) -> bool:
    normalized = str(unit or "").strip().lower()
    return normalized in {"%", "percent", "percentage", "pct"}


def _ordinal(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return MISSING_TEXT
    rounded = int(round(parsed))
    abs_value = abs(rounded)
    if 10 <= (abs_value % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(abs_value % 10, "th")
    return f"{rounded}{suffix}"


def _format_value(value: Any, *, precision: int = 1, unit: Any = None) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return MISSING_TEXT
    if _is_percent_unit(unit):
        return f"{parsed:.{precision}f}%"
    normalized_unit = str(unit or "").strip()
    if normalized_unit:
        return f"{parsed:.{precision}f} {normalized_unit}"
    return f"{parsed:.{precision}f}"


def _format_ci(low: Any, high: Any, *, unit: Any = None) -> str:
    low_value = _safe_float(low)
    high_value = _safe_float(high)
    if low_value is None or high_value is None:
        return MISSING_TEXT
    return f"{_format_value(low_value, unit=unit)} to {_format_value(high_value, unit=unit)}"


def _format_moe(value: Any, *, unit: Any = None) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return MISSING_TEXT
    if _is_percent_unit(unit):
        return f"MOE: +/- {parsed:.1f}%"
    normalized_unit = str(unit or "").strip()
    if normalized_unit:
        return f"MOE: +/- {parsed:.1f} {normalized_unit}"
    return f"MOE: +/- {parsed:.1f}"


def _normalize_bullet_line(text: Any) -> tuple[str, bool]:
    raw = _sanitize_text(text, allow_empty=True)
    if not raw:
        return "", False
    is_prefixed = bool(_BULLET_PREFIX_RE.match(raw))
    cleaned = _BULLET_PREFIX_RE.sub("", raw).strip()
    if cleaned.startswith("- "):
        cleaned = cleaned[2:].strip()
    if cleaned.startswith("* "):
        cleaned = cleaned[2:].strip()
    return cleaned, is_prefixed


def _extract_paragraph_and_bullets(
    paragraph: Any,
    bullets: Any,
) -> tuple[str | None, list[str]]:
    paragraph_lines: list[str] = []
    bullet_items: list[str] = []

    if isinstance(paragraph, str):
        for raw_line in paragraph.splitlines():
            cleaned, is_prefixed = _normalize_bullet_line(raw_line)
            if not cleaned:
                continue
            if is_prefixed:
                bullet_items.append(cleaned)
            else:
                paragraph_lines.append(cleaned)
    elif paragraph is not None:
        cleaned = _sanitize_text(paragraph, allow_empty=True)
        if cleaned:
            paragraph_lines.append(cleaned)

    if isinstance(bullets, list):
        raw_bullets = bullets
    elif bullets is None:
        raw_bullets = []
    else:
        raw_bullets = [bullets]

    for bullet in raw_bullets:
        if isinstance(bullet, str):
            lines = bullet.splitlines() or [bullet]
        else:
            lines = [bullet]
        for raw_line in lines:
            cleaned, _ = _normalize_bullet_line(raw_line)
            if cleaned:
                bullet_items.append(cleaned)

    deduped_bullets: list[str] = []
    seen: set[str] = set()
    for item in bullet_items:
        normalized = _sanitize_text(item, allow_empty=True)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped_bullets.append(normalized)

    paragraph_text = " ".join(paragraph_lines).strip()
    return (paragraph_text if paragraph_text else None), deduped_bullets


def _render_paragraph(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_escape_text(text), style)


def _render_bullets(
    story: list[Any],
    bullets: list[str],
    *,
    style: ParagraphStyle,
) -> None:
    if not bullets:
        return
    fonts = reportlab_fonts()
    items = [
        ListItem(_render_paragraph(item, style), leftIndent=6)
        for item in bullets
    ]
    story.append(
        ListFlowable(
            items,
            bulletType="bullet",
            leftIndent=14,
            bulletFontName=fonts["regular"],
            bulletFontSize=9,
            bulletDedent=4,
            spaceBefore=2,
            spaceAfter=6,
        )
    )


def _render_section(
    story: list[Any],
    *,
    section: dict[str, Any] | None,
    heading_style: ParagraphStyle,
    body_style: ParagraphStyle,
    spacer_height: float = 0.09 * inch,
) -> None:
    if not isinstance(section, dict):
        return
    title = _sanitize_text(section.get("title"), allow_empty=True)
    paragraph_text, bullets = _extract_paragraph_and_bullets(
        section.get("paragraph"),
        section.get("bullets"),
    )

    if title and paragraph_text:
        story.append(
            KeepTogether(
                [
                    Paragraph(_escape_text(title), heading_style),
                    _render_paragraph(paragraph_text, body_style),
                ]
            )
        )
    elif title:
        story.append(Paragraph(_escape_text(title), heading_style))
    elif paragraph_text:
        story.append(_render_paragraph(paragraph_text, body_style))

    _render_bullets(story, bullets, style=body_style)
    story.append(Spacer(1, spacer_height))


def _normalized_section_key(section: dict[str, Any]) -> str:
    section_id = _sanitize_text(section.get("section_id"), allow_empty=True).lower()
    title = _sanitize_text(section.get("title"), allow_empty=True).lower()
    candidate = section_id or title
    return re.sub(r"[^a-z0-9]+", "_", candidate).strip("_")


def _scale_image(path: Path, *, max_width: float, max_height: float) -> Image:
    image_reader = ImageReader(str(path))
    width, height = image_reader.getSize()
    if width <= 0 or height <= 0:
        image = Image(str(path))
        image.hAlign = "LEFT"
        return image

    scale = min(max_width / float(width), max_height / float(height), 1.0)
    image = Image(str(path), width=width * scale, height=height * scale)
    image.hAlign = "LEFT"
    return image


def _add_table(
    story: list[Any],
    rows: list[list[str]],
    col_widths: list[float],
    *,
    right_align_columns: list[int] | None = None,
) -> None:
    if not rows:
        return
    table = Table(rows, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            standard_table_style_commands(
                font_size=9.0,
                right_align_columns=right_align_columns,
            )
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.17 * inch))


def render_profile_pdf_full(
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
    styles = full_report_styles()
    title_style = styles["title"]
    subtitle_style = styles["subtitle"]
    h2_style = styles["h2"]
    h3_style = styles["h3"]
    body_style = styles["body"]
    caption_style = styles["caption"]
    small_style = styles["small"]

    story: list[Any] = []

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
    narrative = profile_json.get("narrative") if isinstance(profile_json.get("narrative"), dict) else {}
    comparisons = (
        profile_json.get("comparisons")
        if isinstance(profile_json.get("comparisons"), dict)
        else {}
    )

    location_name = _sanitize_text(location.get("name") or profile_json.get("location_id"))
    geography = _sanitize_text(profile_json.get("geography"), allow_empty=True) or "area"
    state_abbr = _sanitize_text(location.get("state_abbr"), allow_empty=True) or "N/A"
    report_title = f"Full Profile: {location_name} ({state_abbr})"
    subtitle = f"Geography: {geography}"
    story.append(
        KeepTogether(
            [
                Paragraph(_escape_text(report_title), title_style),
                Paragraph(_escape_text(subtitle), subtitle_style),
            ]
        )
    )
    story.append(Spacer(1, 0.12 * inch))

    summary_text = narrative.get("summary_paragraph") or narrative.get("summary_text") or MISSING_TEXT
    raw_sections = (
        narrative.get("plain_language_sections")
        if isinstance(narrative.get("plain_language_sections"), list)
        else narrative.get("sections")
    )
    section_map: dict[str, dict[str, Any]] = {}
    if isinstance(raw_sections, list):
        for raw_section in raw_sections:
            if not isinstance(raw_section, dict):
                continue
            key = _normalized_section_key(raw_section)
            if not key:
                continue
            section_map[key] = raw_section

    technical_section = (
        narrative.get("technical_methods_section")
        if isinstance(narrative.get("technical_methods_section"), dict)
        else None
    )
    if technical_section:
        section_map.setdefault("technical_methods", technical_section)

    what_section = section_map.get("what_you_are_looking_at")
    interpret_section = section_map.get("how_to_interpret_the_numbers")
    findings_section = section_map.get("what_stands_out_here")
    factors_section = section_map.get("possible_contributing_factors_to_consider")
    questions_section = section_map.get("policy_planning_implications")
    limitations_section = section_map.get("data_limitations_and_cautions")

    story.append(
        KeepTogether(
            [
                Paragraph("Executive Summary (plain language)", h2_style),
                _render_paragraph(summary_text, body_style),
            ]
        )
    )
    story.append(Spacer(1, 0.05 * inch))
    _render_section(story, section=what_section, heading_style=h3_style, body_style=body_style)
    _render_section(story, section=interpret_section, heading_style=h3_style, body_style=body_style)

    findings_paragraph, findings_bullets = _extract_paragraph_and_bullets(
        findings_section.get("paragraph") if isinstance(findings_section, dict) else None,
        findings_section.get("bullets") if isinstance(findings_section, dict) else None,
    )
    findings_intro = (
        findings_paragraph
        or "These highlights summarize where this area sits relative to state and national references."
    )
    story.append(
        KeepTogether(
            [
                Paragraph("Key Findings", h2_style),
                _render_paragraph(findings_intro, body_style),
            ]
        )
    )
    _render_bullets(
        story,
        findings_bullets or ["No key findings were available."],
        style=body_style,
    )
    story.append(Spacer(1, 0.06 * inch))

    story.append(
        KeepTogether(
            [
                Paragraph("Key Numbers", h2_style),
                _render_paragraph("Core computed values and uncertainty ranges.", body_style),
            ]
        )
    )
    places_unit = places.get("unit") or "%"
    us_percentile = references.get("us_percentile")
    key_stats_rows = [
        ["Metric", "Value"],
        [
            "PLACES measure",
            _sanitize_text(
                places.get("short_question_text") or places.get("measure") or places.get("measure_id")
            ),
        ],
        ["Year", _sanitize_text(places.get("year"))],
        [
            "Location value",
            _format_value(places.get("location_value"), unit=places_unit),
        ],
        [
            "95% confidence interval",
            _format_ci(places.get("location_ci_low"), places.get("location_ci_high"), unit=places_unit),
        ],
        ["US percentile", f"{_ordinal(us_percentile)} percentile"],
    ]
    _add_table(story, key_stats_rows, [2.4 * inch, 3.8 * inch])

    story.append(
        KeepTogether(
            [
                Paragraph("Comparisons", h2_style),
                _render_paragraph(
                    "Location values compared with state and U.S. descriptive reference averages.",
                    body_style,
                ),
            ]
        )
    )
    places_comparison = comparisons.get("places") if isinstance(comparisons, dict) else {}
    comparison_rows = [
        ["Measure", "Location", "State average", "U.S. average"],
        [
            "PLACES",
            _format_value((places_comparison or {}).get("location_value"), unit=places_unit),
            _format_value((places_comparison or {}).get("state_mean"), unit=places_unit),
            _format_value((places_comparison or {}).get("us_mean"), unit=places_unit),
        ],
    ]
    acs_primary = comparisons.get("acs_primary") if isinstance(comparisons, dict) else None
    if isinstance(acs_primary, dict):
        acs_unit = acs_primary.get("unit")
        location_value = _format_value(acs_primary.get("location_value"), unit=acs_unit)
        moe_text = _format_moe(acs_primary.get("location_moe"), unit=acs_unit)
        if moe_text != MISSING_TEXT and location_value != MISSING_TEXT:
            location_value = f"{location_value} ({moe_text})"
        comparison_rows.append(
            [
                _sanitize_text(acs_primary.get("measure") or acs_primary.get("measure_id") or "ACS"),
                location_value,
                _format_value(acs_primary.get("state_mean"), unit=acs_unit),
                _format_value(acs_primary.get("us_mean"), unit=acs_unit),
            ]
        )
    _add_table(
        story,
        comparison_rows,
        [2.1 * inch, 1.7 * inch, 1.4 * inch, 1.4 * inch],
        right_align_columns=[1, 2, 3],
    )

    factors_paragraph, factors_bullets = _extract_paragraph_and_bullets(
        factors_section.get("paragraph") if isinstance(factors_section, dict) else None,
        factors_section.get("bullets") if isinstance(factors_section, dict) else None,
    )
    factors_intro = (
        factors_paragraph
        or "Related context indicators can help guide follow-up questions. These are descriptive."
    )
    story.append(
        KeepTogether(
            [
                Paragraph("Possible contributing factors to consider", h2_style),
                _render_paragraph(factors_intro, body_style),
            ]
        )
    )
    if not any("correlation does not mean" in bullet.lower() for bullet in factors_bullets):
        factors_bullets = ["Correlation does not mean one causes the other.", *factors_bullets]
    _render_bullets(
        story,
        factors_bullets or ["No related context factors were available."],
        style=body_style,
    )

    if isinstance(questions_section, dict):
        question_paragraph, question_bullets = _extract_paragraph_and_bullets(
            questions_section.get("paragraph"),
            questions_section.get("bullets"),
        )
        story.append(Paragraph("Questions to ask next", h3_style))
        if question_paragraph:
            story.append(_render_paragraph(question_paragraph, body_style))
        _render_bullets(story, question_bullets, style=body_style)
        story.append(Spacer(1, 0.05 * inch))

    story.append(
        KeepTogether(
            [
                Paragraph("Charts", h2_style),
                _render_paragraph("Visual context for the profile values and comparisons.", body_style),
            ]
        )
    )
    chart_order = ["bars_comparison", "us_distribution", "scatter_top_correlate"]
    rendered_chart_count = 0
    for chart_name in chart_order:
        raw_path = chart_paths.get(chart_name)
        if not raw_path:
            continue
        chart_path = Path(raw_path)
        if not chart_path.exists():
            continue
        chart_meta = CHART_METADATA.get(chart_name, {})
        chart_title = chart_meta.get("title") or chart_name.replace("_", " ").title()
        chart_caption = chart_meta.get("caption") or ""
        story.append(Paragraph(_escape_text(chart_title), h3_style))
        if chart_caption:
            story.append(Paragraph(_escape_text(chart_caption), caption_style))
        chart_image = _scale_image(
            chart_path,
            max_width=doc.width,
            max_height=3.4 * inch,
        )
        story.append(chart_image)
        story.append(Spacer(1, 0.15 * inch))
        rendered_chart_count += 1
    if rendered_chart_count == 0:
        story.append(_render_paragraph("No charts were available for this profile.", body_style))

    limits_paragraph, limits_bullets = _extract_paragraph_and_bullets(
        limitations_section.get("paragraph") if isinstance(limitations_section, dict) else None,
        limitations_section.get("bullets") if isinstance(limitations_section, dict) else None,
    )
    limits_intro = (
        limits_paragraph
        or "Interpret this profile with uncertainty in mind, especially for smaller geographies."
    )
    story.append(
        KeepTogether(
            [
                Paragraph("Methods + Limitations", h2_style),
                _render_paragraph(limits_intro, small_style),
            ]
        )
    )
    if limits_bullets:
        _render_bullets(story, limits_bullets, style=small_style)

    if isinstance(technical_section, dict):
        tech_paragraph, tech_bullets = _extract_paragraph_and_bullets(
            technical_section.get("paragraph"),
            technical_section.get("bullets"),
        )
        story.append(Paragraph("Technical methods", h3_style))
        if tech_paragraph:
            story.append(_render_paragraph(tech_paragraph, small_style))
        _render_bullets(story, tech_bullets, style=small_style)

    methods = profile_json.get("methods_caveats") or []
    methods_bullets = []
    seen_methods: set[str] = set()
    for method in methods:
        cleaned, _ = _normalize_bullet_line(method)
        if not cleaned:
            continue
        if cleaned in seen_methods:
            continue
        seen_methods.add(cleaned)
        methods_bullets.append(cleaned)
    if methods_bullets:
        _render_bullets(story, methods_bullets, style=small_style)

    doc.build(story, canvasmaker=BrandedNumberedCanvas)
    return buffer.getvalue()
