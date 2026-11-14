#!/usr/bin/env python3
"""Build distinct-subawardee reports for the CE24-0027 and CE23-2301 NOFOs."""

from __future__ import annotations

import csv
import html
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


DB_URL = "postgresql://places:places@localhost:5432/places"
REPORT_ROOT = Path(__file__).resolve().parents[2] / "data/reports"


@dataclass(frozen=True)
class ReportConfig:
    nofo: str
    match_fragment: str
    title: str
    slug: str
    output_folder: str

    @property
    def output_dir(self) -> Path:
        return REPORT_ROOT / self.output_folder


CONFIGS = (
    ReportConfig(
        nofo="CDC-RFA-CE-24-0027",
        match_fragment="CE-24-0027",
        title="Rape Prevention and Education",
        slug="ce24_0027",
        output_folder="ce24_0027_subawardees",
    ),
    ReportConfig(
        nofo="CDC-RFA-CE23-2301",
        match_fragment="CE23-2301",
        title=(
            "Domestic Violence Prevention Enhancement and Leadership Through Alliances "
            "(DELTA): Achieving Health Equity through Addressing Disparities (AHEAD)"
        ),
        slug="ce23_2301",
        output_folder="ce23_2301_subawardees",
    ),
)


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value).strip()


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(clean(value) or "0")
    except Exception:
        return Decimal("0")


def money(value: Any, cents: bool = True) -> str:
    return f"${decimal(value):,.2f}" if cents else f"${decimal(value):,.0f}"


def csv_money(value: Any) -> str:
    return f"{decimal(value):.2f}"


def unique(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = clean(value)
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def unique_join(values: Iterable[Any], separator: str = " | ") -> str:
    return separator.join(unique(values))


def longest(values: Iterable[Any]) -> str:
    items = unique(values)
    return max(items, key=len) if items else ""


def most_common(values: Iterable[Any]) -> str:
    items = [clean(value) for value in values if clean(value)]
    return Counter(items).most_common(1)[0][0] if items else ""


def min_value(values: Iterable[Any]) -> str:
    items = sorted(clean(value) for value in values if clean(value))
    return items[0] if items else ""


def max_value(values: Iterable[Any]) -> str:
    items = sorted(clean(value) for value in values if clean(value))
    return items[-1] if items else ""


def display_text(value: Any) -> str:
    """Clean known legacy export artifacts for PDF display only."""
    text = clean(value)
    text = text.replace("ÃƑÂ¢Ã¢Â€ŠÂ¬Ã‚Â¢", "- ").replace("Ã¢Â€Â¢", "- ")
    return re.sub(r"\s+", " ", text).strip()


def fetch_rows(config: ReportConfig) -> list[dict[str, Any]]:
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            WITH prime_awards AS (
                SELECT
                    award_number,
                    STRING_AGG(DISTINCT NULLIF(legal_entity_name, ''), ' | '
                               ORDER BY NULLIF(legal_entity_name, '')) AS taggs_prime_recipient_names,
                    MAX(NULLIF(uei, '')) AS taggs_prime_recipient_uei,
                    SUM(sum_of_actions)::numeric AS taggs_prime_award_total
                FROM taggs.raw_awards
                WHERE fon ILIKE %s
                GROUP BY award_number
            )
            SELECT
                s.id AS source_row_id,
                s.source_fiscal_year,
                s.source_file_name,
                s.source_row_number,
                s.ingested_at,
                p.taggs_prime_recipient_names,
                p.taggs_prime_recipient_uei,
                p.taggs_prime_award_total,
                s.raw_record
            FROM prime_awards p
            JOIN cdc_funding.raw_usaspending_assistance_subawards s
              ON s.raw_record->>'prime_award_fain' = p.award_number
            ORDER BY s.raw_record->>'prime_award_fain',
                     s.raw_record->>'subawardee_uei',
                     s.raw_record->>'subaward_action_date',
                     s.id
            """,
            (f"%{config.match_fragment}%",),
        ).fetchall()
    return [dict(row) for row in rows]


def semantic_key(record: dict[str, Any]) -> tuple[str, ...]:
    return (
        clean(record.get("prime_award_fain")),
        clean(record.get("subaward_number")),
        clean(record.get("subaward_action_date")),
        clean(record.get("subawardee_uei")),
        csv_money(record.get("subaward_amount")),
        clean(record.get("subaward_description")),
    )


def action_row(config: ReportConfig, source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    records = [dict(row["raw_record"]) for row in source_rows]
    primary = max(
        records,
        key=lambda row: (
            clean(row.get("subaward_sam_report_last_modified_date")),
            clean(row.get("subaward_sam_report_year")),
            clean(row.get("subaward_sam_report_month")),
            clean(row.get("subaward_sam_report_id")),
        ),
    )
    source = source_rows[-1]
    amount = decimal(primary.get("subaward_amount"))
    return {
        "nofo": config.nofo,
        "prime_award_fain": clean(primary.get("prime_award_fain")),
        "prime_award_unique_key": clean(primary.get("prime_award_unique_key")),
        "prime_awardee_uei": clean(primary.get("prime_awardee_uei")) or clean(source.get("taggs_prime_recipient_uei")),
        "prime_awardee_name": longest(
            [primary.get("prime_awardee_name"), source.get("taggs_prime_recipient_names")]
        ),
        "taggs_prime_award_total": csv_money(source.get("taggs_prime_award_total")),
        "prime_award_amount_usaspending": csv_money(primary.get("prime_award_amount")),
        "prime_award_base_transaction_description": clean(primary.get("prime_award_base_transaction_description")),
        "prime_award_cfda_numbers_and_titles": clean(primary.get("prime_award_cfda_numbers_and_titles")),
        "prime_award_period_of_performance_start_date": clean(primary.get("prime_award_period_of_performance_start_date")),
        "prime_award_period_of_performance_current_end_date": clean(primary.get("prime_award_period_of_performance_current_end_date")),
        "subaward_number": clean(primary.get("subaward_number")),
        "subaward_type": clean(primary.get("subaward_type")),
        "subaward_action_date": clean(primary.get("subaward_action_date")),
        "subaward_action_date_fiscal_year": clean(primary.get("subaward_action_date_fiscal_year")),
        "subaward_amount": csv_money(amount),
        "subaward_description": clean(primary.get("subaward_description")),
        "subawardee_uei": clean(primary.get("subawardee_uei")),
        "subawardee_name": clean(primary.get("subawardee_name")),
        "subawardee_dba_name": clean(primary.get("subawardee_dba_name")),
        "subawardee_parent_uei": clean(primary.get("subawardee_parent_uei")),
        "subawardee_parent_name": clean(primary.get("subawardee_parent_name")),
        "subawardee_business_types": clean(primary.get("subawardee_business_types")),
        "subawardee_address_line_1": clean(primary.get("subawardee_address_line_1")),
        "subawardee_city_name": clean(primary.get("subawardee_city_name")),
        "subawardee_state_code": clean(primary.get("subawardee_state_code")),
        "subawardee_state_name": clean(primary.get("subawardee_state_name")),
        "subawardee_zip_code": clean(primary.get("subawardee_zip_code")),
        "subawardee_country_code": clean(primary.get("subawardee_country_code")),
        "subawardee_country_name": clean(primary.get("subawardee_country_name")),
        "subaward_recipient_cd_current": clean(primary.get("subaward_recipient_cd_current")),
        "subaward_recipient_cd_original": clean(primary.get("subaward_recipient_cd_original")),
        "subaward_primary_place_of_performance_city_name": clean(primary.get("subaward_primary_place_of_performance_city_name")),
        "subaward_primary_place_of_performance_state_code": clean(primary.get("subaward_primary_place_of_performance_state_code")),
        "subaward_primary_place_of_performance_country_name": clean(primary.get("subaward_primary_place_of_performance_country_name")),
        "subaward_primary_place_of_performance_address_zip_code": clean(primary.get("subaward_primary_place_of_performance_address_zip_code")),
        "subaward_place_of_performance_cd_current": clean(primary.get("subaward_place_of_performance_cd_current")),
        "subaward_place_of_performance_cd_original": clean(primary.get("subaward_place_of_performance_cd_original")),
        "subaward_sam_report_ids": unique_join(row.get("subaward_sam_report_id") for row in records),
        "subaward_sam_report_years": unique_join(row.get("subaward_sam_report_year") for row in records),
        "subaward_sam_report_months": unique_join(row.get("subaward_sam_report_month") for row in records),
        "subaward_sam_report_last_modified_dates": unique_join(
            row.get("subaward_sam_report_last_modified_date") for row in records
        ),
        "usaspending_permalinks": unique_join(row.get("usaspending_permalink") for row in records),
        "source_fiscal_years": unique_join(row.get("source_fiscal_year") for row in source_rows),
        "source_file_names": unique_join(row.get("source_file_name") for row in source_rows),
        "source_row_ids": unique_join(row.get("source_row_id") for row in source_rows),
        "raw_record_count": len(source_rows),
        "duplicate_raw_rows_removed": len(source_rows) - 1,
    }


def deduplicate_actions(config: ReportConfig, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[semantic_key(dict(row["raw_record"]))].append(row)
    actions = [action_row(config, source_rows) for source_rows in grouped.values()]
    return sorted(
        actions,
        key=lambda row: (
            row["subawardee_uei"],
            row["subaward_action_date"],
            row["prime_award_fain"],
            row["subaward_number"],
        ),
    )


def aggregate_organizations(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in actions:
        grouped[row["subawardee_uei"]].append(row)
    organizations: list[dict[str, Any]] = []
    for uei, rows in grouped.items():
        total = sum((decimal(row["subaward_amount"]) for row in rows), Decimal("0"))
        years = sorted(
            {int(row["subaward_action_date_fiscal_year"]) for row in rows if row["subaward_action_date_fiscal_year"].isdigit()}
        )
        descriptions = unique(row["subaward_description"] for row in rows)
        organization: dict[str, Any] = {
            "subawardee_uei": uei,
            "subawardee_name": longest(row["subawardee_name"] for row in rows),
            "subawardee_name_variants": unique_join(row["subawardee_name"] for row in rows),
            "subawardee_dba_names": unique_join(row["subawardee_dba_name"] for row in rows),
            "subawardee_parent_ueis": unique_join(row["subawardee_parent_uei"] for row in rows),
            "subawardee_parent_names": unique_join(row["subawardee_parent_name"] for row in rows),
            "subawardee_business_types": unique_join(row["subawardee_business_types"] for row in rows),
            "address_line_1": most_common(row["subawardee_address_line_1"] for row in rows),
            "city": most_common(row["subawardee_city_name"] for row in rows),
            "state_code": most_common(row["subawardee_state_code"] for row in rows),
            "state_name": most_common(row["subawardee_state_name"] for row in rows),
            "zip_code": most_common(row["subawardee_zip_code"] for row in rows),
            "country_code": most_common(row["subawardee_country_code"] for row in rows),
            "country_name": most_common(row["subawardee_country_name"] for row in rows),
            "recipient_cd_current_source": unique_join(row["subaward_recipient_cd_current"] for row in rows),
            "recipient_cd_original_source": unique_join(row["subaward_recipient_cd_original"] for row in rows),
            "place_of_performance_cities": unique_join(row["subaward_primary_place_of_performance_city_name"] for row in rows),
            "place_of_performance_states": unique_join(row["subaward_primary_place_of_performance_state_code"] for row in rows),
            "place_of_performance_countries": unique_join(row["subaward_primary_place_of_performance_country_name"] for row in rows),
            "place_of_performance_zip_codes": unique_join(row["subaward_primary_place_of_performance_address_zip_code"] for row in rows),
            "place_of_performance_cd_current_source": unique_join(row["subaward_place_of_performance_cd_current"] for row in rows),
            "place_of_performance_cd_original_source": unique_join(row["subaward_place_of_performance_cd_original"] for row in rows),
            "prime_award_count": len({row["prime_award_fain"] for row in rows}),
            "prime_award_fains": unique_join(row["prime_award_fain"] for row in rows),
            "prime_awardee_ueis": unique_join(row["prime_awardee_uei"] for row in rows),
            "prime_awardee_names": unique_join(row["prime_awardee_name"] for row in rows),
            "subaward_action_count": len(rows),
            "raw_record_count": sum(int(row["raw_record_count"]) for row in rows),
            "duplicate_raw_rows_removed": sum(int(row["duplicate_raw_rows_removed"]) for row in rows),
            "subaward_total_amount": csv_money(total),
            "largest_subaward_action_amount": csv_money(max(decimal(row["subaward_amount"]) for row in rows)),
            "first_subaward_action_date": min_value(row["subaward_action_date"] for row in rows),
            "last_subaward_action_date": max_value(row["subaward_action_date"] for row in rows),
            "first_subaward_fiscal_year": min(years) if years else "",
            "last_subaward_fiscal_year": max(years) if years else "",
            "subaward_numbers": unique_join(row["subaward_number"] for row in rows),
            "subaward_types": unique_join(row["subaward_type"] for row in rows),
            "description_count": len(descriptions),
            "description_examples": " || ".join(descriptions[:5]),
            "usaspending_permalinks": unique_join(row["usaspending_permalinks"] for row in rows),
        }
        for year in years:
            organization[f"fy{year}_subaward_amount"] = csv_money(
                sum(
                    (
                        decimal(row["subaward_amount"])
                        for row in rows
                        if row["subaward_action_date_fiscal_year"] == str(year)
                    ),
                    Decimal("0"),
                )
            )
            organization[f"fy{year}_subaward_action_count"] = sum(
                row["subaward_action_date_fiscal_year"] == str(year) for row in rows
            )
        organizations.append(organization)
    organizations.sort(key=lambda row: (-decimal(row["subaward_total_amount"]), row["subawardee_name"]))
    for rank, row in enumerate(organizations, 1):
        row["amount_rank"] = rank
    return organizations


def prime_summary(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in actions:
        grouped[row["prime_award_fain"]].append(row)
    result = []
    for fain, rows in grouped.items():
        result.append(
            {
                "prime_award_fain": fain,
                "prime_recipient": longest(row["prime_awardee_name"] for row in rows),
                "prime_recipient_uei": most_common(row["prime_awardee_uei"] for row in rows),
                "distinct_subawardees": len({row["subawardee_uei"] for row in rows}),
                "subaward_actions": len(rows),
                "subaward_total": sum((decimal(row["subaward_amount"]) for row in rows), Decimal("0")),
            }
        )
    return sorted(result, key=lambda row: (-row["subaward_total"], row["prime_award_fain"]))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fiscal_year_summary(actions: list[dict[str, Any]]) -> list[tuple[str, int, int, Decimal]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in actions:
        grouped[row["subaward_action_date_fiscal_year"] or "Unknown"].append(row)
    return [
        (
            year,
            len(rows),
            len({row["subawardee_uei"] for row in rows}),
            sum((decimal(row["subaward_amount"]) for row in rows), Decimal("0")),
        )
        for year, rows in sorted(grouped.items())
    ]


def write_markdown(
    config: ReportConfig,
    raw_rows: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    organizations: list[dict[str, Any]],
) -> Path:
    output = config.output_dir / f"{config.nofo}_subawardee_report.md"
    primes = prime_summary(actions)
    total = sum((decimal(row["subaward_amount"]) for row in actions), Decimal("0"))
    duplicate_count = len(raw_rows) - len(actions)
    states = Counter(row["state_code"] or "Unknown" for row in organizations)
    lines = [
        f"# {config.nofo} Distinct Subawardee Report",
        "",
        f"Program: **{config.title}**",
        "",
        "## Deliverables",
        "",
        f"- Distinct subawardees by UEI: {len(organizations)}",
        f"- Prime awards with reported subawards: {len(primes)}",
        f"- Semantically distinct subaward actions: {len(actions)}",
        f"- Raw USAspending subaward records: {len(raw_rows)}",
        f"- Duplicate raw records removed: {duplicate_count}",
        f"- Deduplicated reported subaward amount: {money(total)}",
        f"- Distinct organization CSV: `{config.slug}_distinct_subawardees.csv`",
        f"- Action-level CSV: `{config.slug}_subaward_actions.csv`",
        f"- PDF report: `{config.nofo}_subawardee_report.pdf`",
        "",
        "## Funding By Fiscal Year",
        "",
        "| Fiscal year | Actions | Subawardees | Reported amount |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for year, action_count, subawardees, amount in fiscal_year_summary(actions):
        lines.append(f"| {year} | {action_count} | {subawardees} | {money(amount)} |")
    lines += [
        "",
        "## Prime Awards With Subawards",
        "",
        "| Prime FAIN | Prime recipient | Subawardees | Actions | Reported amount |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in primes:
        lines.append(
            f"| {row['prime_award_fain']} | {row['prime_recipient']} | "
            f"{row['distinct_subawardees']} | {row['subaward_actions']} | {money(row['subaward_total'])} |"
        )
    lines += [
        "",
        "## Subawardee State Distribution",
        "",
        "| State | Distinct subawardees |",
        "| --- | ---: |",
    ]
    for state, count in sorted(states.items()):
        lines.append(f"| {state} | {count} |")
    lines += [
        "",
        "## Method",
        "",
        "- Included records are USAspending assistance subawards whose `prime_award_fain` is an exact-FON prime award in local TAGGS data.",
        "- Distinct organizations are keyed by subawardee UEI; every included record has a UEI.",
        "- Semantic duplicates use prime FAIN, subaward number, action date, subawardee UEI, amount, and description. All SAM report IDs remain in the action CSV.",
        "- Reported amounts are subaward-action amounts and should not be added to prime-award obligations as additional federal spending.",
        "- Congressional District fields supplied in the source remain in the CSVs, but no district enrichment or district-centered presentation is applied.",
        "- Local USAspending subaward data was ingested July 3, 2026 and includes source fiscal years through FY2026.",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(html.escape(clean(value)).replace("\n", "<br/>"), style)


def page_number(canvas: Any, doc: Any, config: ReportConfig) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawRightString(7.75 * inch, 0.36 * inch, f"{config.nofo}  |  Page {doc.page}")
    canvas.restoreState()


def write_pdf(
    config: ReportConfig,
    raw_rows: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    organizations: list[dict[str, Any]],
) -> Path:
    output = config.output_dir / f"{config.nofo}_subawardee_report.pdf"
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleClean", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20,
        leading=23, textColor=colors.HexColor("#17324D"), alignment=TA_LEFT, spaceAfter=9,
    )
    h1 = ParagraphStyle(
        "H1Clean", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=13,
        leading=16, textColor=colors.HexColor("#17324D"), spaceAfter=6,
    )
    h2 = ParagraphStyle(
        "H2Clean", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=9.5,
        leading=11.5, textColor=colors.HexColor("#2F5D62"), spaceBefore=5, spaceAfter=3,
    )
    body = ParagraphStyle(
        "BodyClean", parent=styles["BodyText"], fontName="Helvetica", fontSize=8,
        leading=10, textColor=colors.HexColor("#202B33"), spaceAfter=3,
    )
    small = ParagraphStyle("Small", parent=body, fontSize=6.8, leading=8, spaceAfter=0)
    tiny = ParagraphStyle("Tiny", parent=body, fontSize=6.1, leading=7.1, spaceAfter=0)
    amount_style = ParagraphStyle(
        "Amount", parent=h1, fontSize=17, leading=20, textColor=colors.white, spaceAfter=0,
    )
    doc = SimpleDocTemplate(
        str(output), pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        topMargin=0.52 * inch, bottomMargin=0.56 * inch,
        title=f"{config.nofo} Distinct Subawardee Report",
        author="Generated from local USAspending assistance-subaward data",
    )
    story: list[Any] = []
    primes = prime_summary(actions)
    total = sum((decimal(row["subaward_amount"]) for row in actions), Decimal("0"))
    duplicate_count = len(raw_rows) - len(actions)

    story += [
        Spacer(1, 0.2 * inch),
        paragraph(config.nofo, title),
        paragraph(config.title, h1),
        paragraph("Distinct Subawardee Report", ParagraphStyle("Sub", parent=h1, textColor=colors.HexColor("#B54708"))),
        Spacer(1, 0.1 * inch),
    ]
    summary_rows = [
        ["Distinct subawardees", str(len(organizations))],
        ["Prime awards with subawards", str(len(primes))],
        ["Distinct subaward actions", str(len(actions))],
        ["Deduplicated reported amount", money(total)],
    ]
    summary = Table(
        [[paragraph(label, small), paragraph(value, h1)] for label, value in summary_rows],
        colWidths=[2.6 * inch, 3.9 * inch], rowHeights=[0.45 * inch] * 4,
    )
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F7F8")),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#B8C7CC")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D7E0E3")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
    ]))
    story += [summary, Spacer(1, 0.1 * inch)]
    story.append(paragraph(
        f"The source contains {len(raw_rows)} raw records. Semantic deduplication removed {duplicate_count} exact-content repeat(s) while retaining every associated SAM report ID in the action CSV.",
        body,
    ))
    story.append(paragraph(
        "Amounts are reported subaward actions linked to the prime grant FAIN. They are uses of the prime award and must not be added to prime obligations as separate federal spending.",
        body,
    ))
    story += [paragraph("Funding by fiscal year", h2)]
    fy_data = [[paragraph("FY", small), paragraph("Actions", small), paragraph("Subawardees", small), paragraph("Reported amount", small)]]
    for year, action_count, subawardees, amount in fiscal_year_summary(actions):
        fy_data.append([year, str(action_count), str(subawardees), money(amount)])
    fy_table = Table(fy_data, colWidths=[0.8 * inch, 1.1 * inch, 1.2 * inch, 1.65 * inch])
    fy_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C8D3D8")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
    ]))
    story += [fy_table, PageBreak(), paragraph("Prime Awards With Reported Subawards", title)]

    prime_data = [[
        paragraph("Prime FAIN", small), paragraph("Prime recipient", small),
        paragraph("Subawardees", small), paragraph("Actions", small), paragraph("Amount", small),
    ]]
    for row in primes:
        prime_data.append([
            row["prime_award_fain"], paragraph(row["prime_recipient"], tiny),
            str(row["distinct_subawardees"]), str(row["subaward_actions"]), money(row["subaward_total"]),
        ])
    prime_table = LongTable(prime_data, colWidths=[1.05 * inch, 3.05 * inch, 0.72 * inch, 0.6 * inch, 1.08 * inch], repeatRows=1)
    prime_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F5D62")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C8D3D8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 6.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FA")]),
    ]))
    story += [prime_table, PageBreak(), paragraph("Distinct Subawardee Index", title)]

    index_data = [[
        paragraph("Rank", small), paragraph("Subawardee", small), paragraph("State", small),
        paragraph("UEI", small), paragraph("Actions", small), paragraph("Reported amount", small),
    ]]
    for row in organizations:
        index_data.append([
            str(row["amount_rank"]), paragraph(row["subawardee_name"], tiny), row["state_code"],
            row["subawardee_uei"], str(row["subaward_action_count"]), money(row["subaward_total_amount"]),
        ])
    index_table = LongTable(index_data, colWidths=[0.42 * inch, 2.83 * inch, 0.42 * inch, 1.15 * inch, 0.58 * inch, 1.1 * inch], repeatRows=1)
    index_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C8D3D8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 1), (0, -1), "RIGHT"),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 6.3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FA")]),
    ]))
    story += [index_table, PageBreak()]

    actions_by_uei: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in actions:
        actions_by_uei[row["subawardee_uei"]].append(row)
    for index, organization in enumerate(organizations, 1):
        org_actions = sorted(
            actions_by_uei[organization["subawardee_uei"]],
            key=lambda row: (row["subaward_action_date"], row["subaward_number"]),
        )
        story += [paragraph(f"{organization['amount_rank']:03d}. {organization['subawardee_name']}", title)]
        identity = Table(
            [
                [paragraph(money(organization["subaward_total_amount"]), amount_style), paragraph("Total reported subaward actions", body)],
                [paragraph(organization["subawardee_uei"], h1), paragraph(f"{organization['state_code']}  |  {organization['subaward_action_count']} action(s)", h1)],
            ],
            colWidths=[2.65 * inch, 3.85 * inch], rowHeights=[0.45 * inch, 0.4 * inch],
        )
        identity.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#B54708")),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#F5EDE8")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F4F7F8")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#B8C7CC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ]))
        story += [identity, Spacer(1, 0.06 * inch)]
        address = ", ".join(filter(None, [
            organization["address_line_1"], organization["city"], organization["state_code"],
            organization["zip_code"], organization["country_name"],
        ]))
        details = [
            ["Address", address],
            ["DBA", organization["subawardee_dba_names"]],
            ["Parent organization", organization["subawardee_parent_names"]],
            ["Business types", organization["subawardee_business_types"]],
            ["Prime award", organization["prime_award_fains"]],
            ["Prime recipient", organization["prime_awardee_names"]],
            ["Action period", f"{organization['first_subaward_action_date']} to {organization['last_subaward_action_date']}"],
            ["Place of performance", ", ".join(filter(None, [organization["place_of_performance_cities"], organization["place_of_performance_states"], organization["place_of_performance_countries"]]))],
        ]
        detail_table = Table(
            [[paragraph(label, small), paragraph(value, small)] for label, value in details],
            colWidths=[1.12 * inch, 5.38 * inch],
        )
        detail_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF3F4")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CED8DC")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        story += [detail_table, paragraph("Subaward action history", h2)]
        action_data = [[
            paragraph("Date", tiny), paragraph("FY", tiny), paragraph("Subaward number", tiny),
            paragraph("Amount", tiny), paragraph("Description", tiny),
        ]]
        for row in org_actions:
            description = display_text(row["subaward_description"])
            if len(description) > 115:
                description = description[:112].rsplit(" ", 1)[0] + "..."
            action_data.append([
                row["subaward_action_date"], row["subaward_action_date_fiscal_year"],
                paragraph(row["subaward_number"], tiny), money(row["subaward_amount"]),
                paragraph(description, tiny),
            ])
        action_table = Table(action_data, colWidths=[0.68 * inch, 0.35 * inch, 1.23 * inch, 0.85 * inch, 3.39 * inch], repeatRows=1)
        action_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F5D62")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.22, colors.HexColor("#C8D3D8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (3, 1), (3, -1), "RIGHT"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 5.9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FA")]),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(action_table)
        if index < len(organizations):
            story.append(PageBreak())

    callback = lambda canvas, report_doc: page_number(canvas, report_doc, config)
    doc.build(story, onFirstPage=callback, onLaterPages=callback)
    return output


def build_report(config: ReportConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    raw_rows = fetch_rows(config)
    actions = deduplicate_actions(config, raw_rows)
    organizations = aggregate_organizations(actions)
    organization_csv = config.output_dir / f"{config.slug}_distinct_subawardees.csv"
    action_csv = config.output_dir / f"{config.slug}_subaward_actions.csv"
    write_csv(organization_csv, organizations)
    write_csv(action_csv, actions)
    markdown = write_markdown(config, raw_rows, actions, organizations)
    pdf = write_pdf(config, raw_rows, actions, organizations)
    print(
        f"{config.nofo}: raw={len(raw_rows)} actions={len(actions)} "
        f"subawardees={len(organizations)} total={money(sum((decimal(row['subaward_amount']) for row in actions), Decimal('0')))}"
    )
    for path in (organization_csv, action_csv, markdown, pdf):
        print(f"  {path} ({path.stat().st_size} bytes)")


def main() -> None:
    for config in CONFIGS:
        build_report(config)


if __name__ == "__main__":
    main()
