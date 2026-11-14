#!/usr/bin/env python3
"""Build the CDC-RFA-CE-24-0027 recipient data package from local award data."""

from __future__ import annotations

import csv
import html
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


DB_URL = "postgresql://places:places@localhost:5432/places"
NOFO = "CDC-RFA-CE-24-0027"
NOFO_SHORT = "CE-24-0027"
NOFO_TITLE = "Rape Prevention and Education"
GRANTS_GOV_ID = "348310"
GRANTS_GOV_URL = f"https://www.grants.gov/search-results-detail/{GRANTS_GOV_ID}"
NOFO_PDF_URL = (
    "https://apply07.grants.gov/apply/opportunities/instructions/"
    "PKG00282390-instructions.pdf"
)
NOFO_SOURCE_LABEL = "Official application instructions PDF"
NOFO_POSTED = "September 27, 2023"
NOFO_DEADLINE = "November 30, 2023"
NOFO_PROGRAM_PERIOD = "five years"
NOFO_EXPECTED_AWARDS = "59"
NOFO_ESTIMATED_FUNDING = "$209,950,000"
NOFO_AWARD_RANGE = "$40,000 to $4,200,000"
NOFO_ELIGIBILITY = (
    "state health departments or bona fide agents, including listed U.S. territories "
    "and freely associated states"
)
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data/reports/ce24_0027_recipients"
WIDE_CSV = OUTPUT_DIR / "ce24_0027_recipient_organizations.csv"
LONG_CSV = OUTPUT_DIR / "ce24_0027_recipient_top_other_awards_long.csv"
GEOCODE_CSV = OUTPUT_DIR / "ce24_0027_census_geocoder_enrichment.csv"
MARKDOWN = OUTPUT_DIR / "CDC-RFA-CE-24-0027_recipient_dossier.md"
PDF = OUTPUT_DIR / "CDC-RFA-CE-24-0027_recipient_dossier.pdf"

# Mailing addresses for these public agencies do not resolve as street ranges in
# the Census address endpoint. Coordinates are normalized physical locations
# found for the same agency/campus, then passed to the Census geography endpoint.
GEOCODE_COORDINATE_FALLBACKS = {
    "NUF2CE002565": ("Maine DHHS, 109 Capitol Street, Augusta, ME", -69.7824, 44.3072),
    "NUF2CE002568": ("Nebraska State Office Building, 301 Centennial Mall South, Lincoln, NE", -96.7004668, 40.8108065),
    "NUF2CE002591": ("2401 Colonial Drive, Helena, MT", -111.9920513, 46.5853242),
    "NUF2CE002599": ("625 Forster Street, Harrisburg, PA", -76.8845123, 40.2670282),
    "NUF2CE002602": ("Rhode Island Capitol campus, Providence, RI", -71.4149587, 41.8308956),
    "NUF2CE002607": ("Centro Medico de Puerto Rico campus, San Juan, PR", -66.0738721, 18.3943866),
    "NUF2CE002611": ("Hospital Ground, Charlotte Amalie, VI", -64.9260595, 18.3465140),
}


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


def money(value: Any) -> str:
    return f"${decimal(value):,.0f}"


def csv_money(value: Any) -> str:
    return f"{decimal(value):.2f}"


def unique(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        item = clean(value)
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def unique_join(values: Iterable[Any], separator: str = " | ") -> str:
    return separator.join(unique(values))


def most_common(values: Iterable[Any]) -> str:
    items = [clean(value) for value in values if clean(value)]
    if not items:
        return ""
    return Counter(items).most_common(1)[0][0]


def min_value(values: Iterable[Any]) -> str:
    items = sorted(clean(value) for value in values if clean(value))
    return items[0] if items else ""


def max_value(values: Iterable[Any]) -> str:
    items = sorted(clean(value) for value in values if clean(value))
    return items[-1] if items else ""


def longest(values: Iterable[Any]) -> str:
    items = unique(values)
    return max(items, key=len) if items else ""


def stripped_street(value: str) -> str:
    street = value.split(",", 1)[0].strip()
    return re.split(r"\s+(?:SUITE|STE|UNIT|ROOM|RM|FLOOR|FL)\b", street, 1, re.I)[0].strip()


def load_geocode_cache() -> dict[str, dict[str, str]]:
    if not GEOCODE_CSV.exists():
        return {}
    with GEOCODE_CSV.open(newline="", encoding="utf-8") as handle:
        return {row["award_number"]: row for row in csv.DictReader(handle)}


def geocode_recipient(award: str, address: dict[str, str]) -> dict[str, str]:
    result = {
        "award_number": award,
        "input_address": address.get("address_line_1", ""),
        "input_city": address.get("city", ""),
        "input_state": address.get("state", ""),
        "input_zip": address.get("zip_code", ""),
        "match_status": "unmatched",
        "matched_address": "",
        "longitude": "",
        "latitude": "",
        "congressional_district": "",
        "congressional_district_name": "",
        "congressional_session": "119",
        "location_basis": "recipient address supplied by USAspending",
        "geocoder_benchmark": "Public_AR_Current",
        "geocoder_vintage": "Current_Current",
        "source_url": "https://geocoding.geo.census.gov/geocoder/",
    }
    street = stripped_street(address.get("address_line_1", ""))
    if not all((street, address.get("city"), address.get("state"))):
        result["match_status"] = "insufficient_address"
        return result

    params = {
        "street": street,
        "city": address["city"],
        "state": address["state"],
        "zip": address.get("zip_code", "")[:5],
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    url = "https://geocoding.geo.census.gov/geocoder/geographies/address?" + urllib.parse.urlencode(params)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "places-app-funding-dossier/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
        matches = payload.get("result", {}).get("addressMatches", [])
        if not matches:
            fallback = GEOCODE_COORDINATE_FALLBACKS.get(award)
            if not fallback:
                return result
            fallback_label, longitude, latitude = fallback
            coordinate_params = {
                "x": longitude,
                "y": latitude,
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
                "format": "json",
            }
            coordinate_url = (
                "https://geocoding.geo.census.gov/geocoder/geographies/coordinates?"
                + urllib.parse.urlencode(coordinate_params)
            )
            with urllib.request.urlopen(coordinate_url, timeout=20) as response:
                coordinate_payload = json.load(response)
            result["match_status"] = "matched_via_normalized_coordinates"
            result["matched_address"] = fallback_label
            result["longitude"] = clean(longitude)
            result["latitude"] = clean(latitude)
            result["location_basis"] = (
                "normalized agency/campus location; district assigned by U.S. Census coordinate geography"
            )
            for geography_name, geographies in coordinate_payload.get("result", {}).get("geographies", {}).items():
                if "Congressional Districts" not in geography_name or not geographies:
                    continue
                district = geographies[0]
                district_number = clean(district.get("CD119"))
                if district_number:
                    result["congressional_district"] = f"{address.get('state', '')}-{district_number.zfill(2)}"
                result["congressional_district_name"] = clean(district.get("NAME"))
                result["congressional_session"] = clean(district.get("CDSESSN")) or "119"
                break
            return result
        match = matches[0]
        result["match_status"] = "matched"
        result["matched_address"] = clean(match.get("matchedAddress"))
        result["longitude"] = clean(match.get("coordinates", {}).get("x"))
        result["latitude"] = clean(match.get("coordinates", {}).get("y"))
        for geography_name, geographies in match.get("geographies", {}).items():
            if "Congressional Districts" not in geography_name or not geographies:
                continue
            district = geographies[0]
            district_number = clean(district.get("CD119"))
            if not district_number:
                district_number = next(
                    (clean(value) for key, value in district.items() if key.startswith("CD") and clean(value)),
                    "",
                )
            state = address.get("state", "")
            if district_number:
                result["congressional_district"] = f"{state}-{district_number.zfill(2)}"
            result["congressional_district_name"] = clean(district.get("NAME"))
            result["congressional_session"] = clean(district.get("CDSESSN")) or "119"
            break
    except Exception as exc:
        result["match_status"] = f"error: {type(exc).__name__}"
    return result


def fetch_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        taggs = conn.execute(
            """
            SELECT *
            FROM taggs.raw_awards
            WHERE fon ILIKE %s
            ORDER BY award_number, action_issue_date, id
            """,
            (f"%{NOFO_SHORT}%",),
        ).fetchall()
        usa = conn.execute(
            """
            SELECT source_fiscal_year, raw_record
            FROM cdc_funding.raw_usaspending_assistance_prime_transactions
            WHERE raw_record->>'funding_opportunity_number' ILIKE %s
            ORDER BY raw_record->>'award_id_fain', raw_record->>'action_date',
                     raw_record->>'assistance_transaction_unique_key'
            """,
            (f"%{NOFO_SHORT}%",),
        ).fetchall()
    return taggs, usa


def fetch_other_awards(ueis: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not ueis:
        return {}
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
                uei,
                award_number,
                SUM(sum_of_actions)::numeric AS total_amount,
                STRING_AGG(DISTINCT NULLIF(fon, ''), ' | ' ORDER BY NULLIF(fon, '')) AS fon,
                STRING_AGG(DISTINCT NULLIF(opdiv, ''), ' | ' ORDER BY NULLIF(opdiv, '')) AS opdiv,
                STRING_AGG(DISTINCT NULLIF(aln::text, ''), ' | ' ORDER BY NULLIF(aln::text, '')) AS aln,
                STRING_AGG(DISTINCT NULLIF(assistance_listing_title, ''), ' | '
                           ORDER BY NULLIF(assistance_listing_title, '')) AS assistance_listing_title,
                MIN(funding_fiscal_year) AS first_funding_fy,
                MAX(funding_fiscal_year) AS last_funding_fy,
                STRING_AGG(DISTINCT NULLIF(award_title, ''), ' | ' ORDER BY NULLIF(award_title, '')) AS award_title
            FROM taggs.raw_awards
            WHERE uei = ANY(%s)
              AND COALESCE(fon, '') NOT ILIKE %s
            GROUP BY uei, award_number
            HAVING SUM(sum_of_actions) > 0
            ORDER BY uei, total_amount DESC, award_number
            """,
            (ueis, f"%{NOFO_SHORT}%"),
        ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[clean(row["uei"])].append(dict(row))
    return grouped


def aggregate() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    taggs_rows, usa_wrapped = fetch_data()
    usa_rows = [dict(row["raw_record"]) | {"_source_fiscal_year": row["source_fiscal_year"]} for row in usa_wrapped]
    taggs_by_award: dict[str, list[dict[str, Any]]] = defaultdict(list)
    usa_by_award: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in taggs_rows:
        taggs_by_award[clean(row["award_number"])].append(dict(row))
    for row in usa_rows:
        usa_by_award[clean(row.get("award_id_fain"))].append(row)

    awards = sorted(set(taggs_by_award) | set(usa_by_award))
    ueis = sorted(
        {
            clean(row.get("uei") or row.get("recipient_uei"))
            for rows in list(taggs_by_award.values()) + list(usa_by_award.values())
            for row in rows
            if clean(row.get("uei") or row.get("recipient_uei"))
        }
    )
    other_awards = fetch_other_awards(ueis)
    geocode_cache = load_geocode_cache()
    geocodes: list[dict[str, str]] = []
    wide: list[dict[str, Any]] = []
    long_rows: list[dict[str, Any]] = []

    for award in awards:
        trows = taggs_by_award.get(award, [])
        urows = usa_by_award.get(award, [])
        uei = most_common([row.get("recipient_uei") for row in urows] + [row.get("uei") for row in trows])
        address = {
            "address_line_1": most_common(row.get("recipient_address_line_1") for row in urows),
            "city": most_common([row.get("recipient_city_name") for row in urows] + [row.get("legal_entity_city") for row in trows]),
            "state": most_common([row.get("recipient_state_code") for row in urows] + [row.get("legal_entity_state") for row in trows]),
            "zip_code": most_common([row.get("recipient_zip_code") for row in urows] + [row.get("legal_entity_zip") for row in trows]),
        }
        cached_geocode = geocode_cache.get(award)
        geocode = cached_geocode if cached_geocode and cached_geocode.get("congressional_district") else geocode_recipient(award, address)
        if not cached_geocode or not cached_geocode.get("congressional_district"):
            time.sleep(0.05)
        geocodes.append(geocode)

        taggs_total = sum((decimal(row.get("sum_of_actions")) for row in trows), Decimal("0"))
        usa_total = sum((decimal(row.get("federal_action_obligation")) for row in urows), Decimal("0"))
        fy_values = sorted(
            {
                int(value)
                for value in [
                    *[row.get("funding_fiscal_year") for row in trows],
                    *[row.get("action_date_fiscal_year") for row in urows],
                ]
                if clean(value).isdigit()
            }
        )
        others = other_awards.get(uei, [])
        top_ten = others[:10]
        district_taggs = unique_join(row.get("legal_entity_congressional_district") for row in trows)
        district_usa_current = unique_join(row.get("recipient_current_congressional_district") for row in urows)
        district_usa_original = unique_join(row.get("recipient_original_congressional_district") for row in urows)
        highlighted_district = (
            district_usa_current
            or district_usa_original
            or district_taggs
            or clean(geocode.get("congressional_district"))
        )
        district_source = ""
        if district_usa_current:
            district_source = "USAspending current recipient district"
        elif district_usa_original:
            district_source = "USAspending original recipient district"
        elif district_taggs:
            district_source = "TAGGS recipient district"
        elif highlighted_district:
            district_source = "U.S. Census Geocoder address match (119th Congress)"

        names_taggs = unique_join(row.get("legal_entity_name") for row in trows)
        names_usa = unique_join(row.get("recipient_name") for row in urows)
        row: dict[str, Any] = {
            "nofo_award_number": award,
            "nofo_data_source": "TAGGS+USAspending" if trows and urows else ("TAGGS" if trows else "USAspending"),
            "uei": uei,
            "recipient_name": longest([item.get("recipient_name") for item in urows] + [item.get("legal_entity_name") for item in trows]),
            "recipient_name_variants_taggs": names_taggs,
            "recipient_name_variants_usaspending": names_usa,
            "address_line_1_usaspending": address["address_line_1"],
            "address_line_2_usaspending": most_common(item.get("recipient_address_line_2") for item in urows),
            "city": address["city"],
            "state": address["state"],
            "zip_code": address["zip_code"],
            "zip_last_4_code_usaspending": most_common(item.get("recipient_zip_last_4_code") for item in urows),
            "county": most_common([item.get("recipient_county_name") for item in urows] + [item.get("legal_entity_county") for item in trows]),
            "country": most_common([item.get("recipient_country_name") for item in urows] + [item.get("legal_entity_country") for item in trows]),
            "congressional_district_highlight": highlighted_district,
            "congressional_district_highlight_source": district_source,
            "congressional_district_taggs": district_taggs,
            "congressional_district_usaspending_current": district_usa_current,
            "congressional_district_usaspending_original": district_usa_original,
            "congressional_district_census_derived": clean(geocode.get("congressional_district")),
            "congressional_district_census_name": clean(geocode.get("congressional_district_name")),
            "congressional_district_census_session": clean(geocode.get("congressional_session")),
            "census_geocoder_match_status": clean(geocode.get("match_status")),
            "census_geocoder_location_basis": clean(geocode.get("location_basis")),
            "census_geocoder_matched_address": clean(geocode.get("matched_address")),
            "census_geocoder_longitude": clean(geocode.get("longitude")),
            "census_geocoder_latitude": clean(geocode.get("latitude")),
            "parent_uei_usaspending": unique_join(item.get("recipient_parent_uei") for item in urows),
            "parent_name_usaspending": unique_join(item.get("recipient_parent_name") for item in urows),
            "recipient_class_taggs": unique_join(item.get("recipient_class") for item in trows),
            "recipient_type_taggs": unique_join(item.get("recipient_type") for item in trows),
            "business_types_code_usaspending": unique_join(item.get("business_types_code") for item in urows),
            "business_types_description_usaspending": unique_join(item.get("business_types_description") for item in urows),
            "metro_non_metro_taggs": unique_join(item.get("metro_non_metro") for item in trows),
            "recovery_act_flag_taggs": unique_join(item.get("recovery_act_flag") for item in trows),
            "opdiv_taggs": unique_join(item.get("opdiv") for item in trows),
            "program_office_taggs": unique_join(item.get("program_office") for item in trows),
            "funding_office_usaspending": unique_join(item.get("funding_office_name") for item in urows),
            "aln_taggs": unique_join(item.get("aln") for item in trows),
            "assistance_listing_title_taggs": unique_join(item.get("assistance_listing_title") for item in trows),
            "cfda_number_usaspending": unique_join(item.get("cfda_number") for item in urows),
            "cfda_title_usaspending": unique_join(item.get("cfda_title") for item in urows),
            "fon_taggs": unique_join(item.get("fon") for item in trows),
            "funding_opportunity_number_usaspending": unique_join(item.get("funding_opportunity_number") for item in urows),
            "award_title": longest([item.get("award_title") for item in trows]),
            "award_description_or_project_abstract": longest(
                [item.get("prime_award_base_transaction_description") for item in urows]
                + [item.get("transaction_description") for item in urows]
                + [item.get("award_description") for item in trows]
            ),
            "period_of_performance_start_min": min_value(
                [item.get("period_of_performance_start_date") for item in trows]
                + [item.get("period_of_performance_start_date") for item in urows]
            ),
            "period_of_performance_end_max": max_value(
                [item.get("period_of_performance_end_date") for item in trows]
                + [item.get("period_of_performance_current_end_date") for item in urows]
            ),
            "taggs_first_action_issue_date": min_value(item.get("action_issue_date") for item in trows),
            "taggs_last_action_issue_date": max_value(item.get("action_issue_date") for item in trows),
            "usaspending_first_action_date": min_value(item.get("action_date") for item in urows),
            "usaspending_last_action_date": max_value(item.get("action_date") for item in urows),
            "nofo_taggs_total_sum_of_actions": csv_money(taggs_total),
            "nofo_usaspending_total_federal_action_obligation": csv_money(usa_total),
            "nofo_best_available_total": csv_money(usa_total if urows else taggs_total),
            "other_award_count_taggs_same_uei": len(others),
            "other_awards_total_taggs_same_uei": csv_money(sum((decimal(item["total_amount"]) for item in others), Decimal("0"))),
            "top_10_other_awards_total_taggs_same_uei": csv_money(sum((decimal(item["total_amount"]) for item in top_ten), Decimal("0"))),
            "usaspending_permalink_examples": unique_join(item.get("usaspending_permalink") for item in urows),
        }
        for fy in fy_values:
            row[f"nofo_taggs_fy{fy}_sum_of_actions"] = csv_money(
                sum((decimal(item.get("sum_of_actions")) for item in trows if clean(item.get("funding_fiscal_year")) == str(fy)), Decimal("0"))
            )
            row[f"nofo_usaspending_fy{fy}_federal_action_obligation"] = csv_money(
                sum((decimal(item.get("federal_action_obligation")) for item in urows if clean(item.get("action_date_fiscal_year")) == str(fy)), Decimal("0"))
            )
        for rank in range(1, 11):
            item = top_ten[rank - 1] if rank <= len(top_ten) else {}
            for key in (
                "award_number",
                "total_amount",
                "fon",
                "opdiv",
                "aln",
                "assistance_listing_title",
                "first_funding_fy",
                "last_funding_fy",
                "award_title",
            ):
                value = item.get(key, "")
                row[f"other_award_{rank}_{key}"] = csv_money(value) if key == "total_amount" and value != "" else clean(value)
        wide.append(row)

        for rank, item in enumerate(top_ten, 1):
            long_rows.append(
                {
                    "recipient_nofo_award_number": award,
                    "recipient_uei": uei,
                    "recipient_name": row["recipient_name"],
                    "recipient_state": row["state"],
                    "recipient_congressional_district": highlighted_district,
                    "rank": rank,
                    **{key: clean(value) for key, value in item.items()},
                }
            )

    return wide, long_rows, geocodes


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def totals_by_fy(rows: list[dict[str, Any]]) -> list[tuple[int, Decimal, Decimal]]:
    years = sorted(
        {
            int(match.group(1))
            for row in rows
            for key in row
            if (match := re.fullmatch(r"nofo_taggs_fy(\d{4})_sum_of_actions", key))
        }
    )
    return [
        (
            year,
            sum((decimal(row.get(f"nofo_taggs_fy{year}_sum_of_actions")) for row in rows), Decimal("0")),
            sum((decimal(row.get(f"nofo_usaspending_fy{year}_federal_action_obligation")) for row in rows), Decimal("0")),
        )
        for year in years
    ]


def write_markdown(rows: list[dict[str, Any]]) -> None:
    source_counts = Counter(clean(row["nofo_data_source"]) for row in rows)
    districts = Counter(clean(row["congressional_district_highlight"]) or "Unresolved" for row in rows)
    states = Counter(clean(row["state"]) or "Unknown" for row in rows)
    geocode_counts = Counter(clean(row["census_geocoder_match_status"]) for row in rows)
    taggs_total = sum((decimal(row["nofo_taggs_total_sum_of_actions"]) for row in rows), Decimal("0"))
    usa_total = sum((decimal(row["nofo_usaspending_total_federal_action_obligation"]) for row in rows), Decimal("0"))
    lines = [
        f"# {NOFO} Recipient Organization Dossier",
        "",
        f"This dossier covers exact-FON recipients for **{NOFO_TITLE}** using local TAGGS and USAspending data.",
        "",
        "## Deliverables",
        "",
        f"- Recipient award rows: {len(rows)}",
        f"- TAGGS exact-FON awards represented: {sum(1 for row in rows if 'TAGGS' in row['nofo_data_source'])}",
        f"- USAspending exact-FON awards represented: {sum(1 for row in rows if 'USAspending' in row['nofo_data_source'])}",
        f"- Wide CSV: `{WIDE_CSV.name}`",
        f"- Long top-other-awards CSV: `{LONG_CSV.name}`",
        f"- Census district enrichment CSV: `{GEOCODE_CSV.name}`",
        f"- PDF: `{PDF.name}`",
        "",
        "## Official NOFO Snapshot",
        "",
        f"- Opportunity title: {NOFO_TITLE}",
        "- Assistance Listing: 93.136, Injury Prevention and Control Research and State and Community Based Programs",
        "- Funding instrument: Cooperative Agreement",
        f"- Posted: {NOFO_POSTED}",
        f"- Application deadline: {NOFO_DEADLINE}",
        f"- Expected program period: {NOFO_PROGRAM_PERIOD}",
        f"- Expected awards: {NOFO_EXPECTED_AWARDS}",
        f"- Estimated total program funding: {NOFO_ESTIMATED_FUNDING}",
        f"- Award range in the final synopsis: {NOFO_AWARD_RANGE}",
        f"- Eligible applicants: {NOFO_ELIGIBILITY}",
        f"- [Grants.gov opportunity record]({GRANTS_GOV_URL})",
        *([f"- [{NOFO_SOURCE_LABEL}]({NOFO_PDF_URL})"] if NOFO_PDF_URL != GRANTS_GOV_URL else []),
        "",
        "## Exact-FON Funding",
        "",
        f"- TAGGS: {money(taggs_total)} across {source_counts['TAGGS+USAspending'] + source_counts['TAGGS']} awards",
        f"- USAspending: {money(usa_total)} across {source_counts['TAGGS+USAspending'] + source_counts['USAspending']} awards",
        f"- Source difference (USAspending minus TAGGS): {money(usa_total - taggs_total)}",
        "",
        "| Fiscal year | TAGGS | USAspending | Difference |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for year, taggs, usa in totals_by_fy(rows):
        lines.append(f"| {year} | {money(taggs)} | {money(usa)} | {money(usa - taggs)} |")
    lines += [
        "",
        "## Congressional District Distribution",
        "",
        "District is highlighted from the award source when available; otherwise it is derived from the recipient address using the U.S. Census Geocoder and its 119th Congressional District geography.",
        "",
        "| Congressional District | Recipient awards |",
        "| --- | ---: |",
    ]
    for district, count in sorted(districts.items()):
        lines.append(f"| {district} | {count} |")
    lines += [
        "",
        "## State Distribution",
        "",
        "| State or territory | Recipient awards |",
        "| --- | ---: |",
    ]
    for state, count in sorted(states.items()):
        lines.append(f"| {state} | {count} |")
    lines += [
        "",
        "## Reconciliation and Method",
        "",
        f"- Data-source coverage: {dict(source_counts)}.",
        (
            "- Source-only awards are retained in the recipient universe and identified in the CSV."
            if source_counts.get("USAspending", 0) or source_counts.get("TAGGS", 0)
            else "- All exact-FON award numbers reconcile across TAGGS and USAspending."
        ),
        f"- Census address-match statuses: {dict(geocode_counts)}.",
        "- Congressional District is an address-based administrative geography, not a statement about the recipient's statewide service area.",
        "- Top 10 other awards are ranked by positive net TAGGS `sum_of_actions` for the same UEI, excluding this exact NOFO. They may come from any HHS operating division represented in TAGGS.",
        "- `nofo_best_available_total` uses USAspending when present and TAGGS otherwise; source totals remain separate to prevent double counting.",
        "- Local data snapshots can lag agency systems and may change after this dossier is generated.",
    ]
    MARKDOWN.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pdf_paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(html.escape(clean(value)).replace("\n", "<br/>"), style)


def draw_page_number(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawRightString(7.75 * inch, 0.38 * inch, f"{NOFO}  |  Page {doc.page}")
    canvas.restoreState()


def write_pdf(rows: list[dict[str, Any]]) -> None:
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleClean", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22,
        leading=26, textColor=colors.HexColor("#17324D"), alignment=TA_LEFT, spaceAfter=12,
    )
    h1 = ParagraphStyle(
        "H1Clean", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=15,
        leading=18, textColor=colors.HexColor("#17324D"), spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "H2Clean", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10,
        leading=12, textColor=colors.HexColor("#2F5D62"), spaceBefore=7, spaceAfter=4,
    )
    body = ParagraphStyle(
        "BodyClean", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.3,
        leading=10.5, textColor=colors.HexColor("#202B33"), spaceAfter=4,
    )
    small = ParagraphStyle(
        "SmallClean", parent=body, fontSize=7, leading=8.4, spaceAfter=0,
    )
    tiny = ParagraphStyle(
        "TinyClean", parent=body, fontSize=6.4, leading=7.5, spaceAfter=0,
    )
    district_style = ParagraphStyle(
        "District", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=17,
        leading=20, textColor=colors.white, alignment=TA_CENTER, spaceAfter=0,
    )
    center = ParagraphStyle("Center", parent=body, alignment=TA_CENTER)
    link_style = ParagraphStyle("Link", parent=small, textColor=colors.HexColor("#175CD3"))

    doc = SimpleDocTemplate(
        str(PDF), pagesize=letter, leftMargin=0.55 * inch, rightMargin=0.55 * inch,
        topMargin=0.55 * inch, bottomMargin=0.58 * inch,
        title=f"{NOFO} Recipient Organization Dossier",
        author="Generated from local TAGGS and USAspending data",
    )
    story: list[Any] = []
    taggs_total = sum((decimal(row["nofo_taggs_total_sum_of_actions"]) for row in rows), Decimal("0"))
    usa_total = sum((decimal(row["nofo_usaspending_total_federal_action_obligation"]) for row in rows), Decimal("0"))
    district_count = sum(1 for row in rows if clean(row["congressional_district_highlight"]))

    story += [
        Spacer(1, 0.32 * inch),
        pdf_paragraph(NOFO, title),
        pdf_paragraph(NOFO_TITLE, h1),
        pdf_paragraph("Recipient Organization Dossier", ParagraphStyle("Sub", parent=h1, fontSize=12, textColor=colors.HexColor("#B54708"))),
        Spacer(1, 0.16 * inch),
    ]
    summary_data = [
        [pdf_paragraph("Recipient awards", small), pdf_paragraph(str(len(rows)), h1)],
        [pdf_paragraph("TAGGS exact-FON total", small), pdf_paragraph(money(taggs_total), h1)],
        [pdf_paragraph("USAspending exact-FON total", small), pdf_paragraph(money(usa_total), h1)],
        [pdf_paragraph("Congressional Districts resolved", small), pdf_paragraph(f"{district_count} of {len(rows)}", h1)],
    ]
    summary = Table(summary_data, colWidths=[2.65 * inch, 3.7 * inch], rowHeights=[0.48 * inch] * 4)
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F7F8")),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#B8C7CC")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7E0E3")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story += [summary, Spacer(1, 0.16 * inch)]
    story.append(pdf_paragraph(
        "The award files do not supply Congressional District for these recipients. District values in this dossier are derived from recipient addresses using the U.S. Census Geocoder's current benchmark and 119th Congressional District geography. The CSV retains the match status and coordinates for auditability.",
        body,
    ))
    story.append(pdf_paragraph(
        "Top 10 other awards are positive net TAGGS awards for the same UEI, excluding this NOFO. Source totals are shown separately and are not added together.", body
    ))
    story.append(Spacer(1, 0.12 * inch))
    story.append(Paragraph(f'<link href="{GRANTS_GOV_URL}">Official Grants.gov opportunity record</link>', link_style))
    if NOFO_PDF_URL != GRANTS_GOV_URL:
        story.append(Paragraph(f'<link href="{NOFO_PDF_URL}">{html.escape(NOFO_SOURCE_LABEL)}</link>', link_style))
    story.append(PageBreak())

    story += [pdf_paragraph("Funding and Recipient Distribution", title)]
    fy_table = [[pdf_paragraph("Fiscal year", small), pdf_paragraph("TAGGS", small), pdf_paragraph("USAspending", small), pdf_paragraph("Difference", small)]]
    for year, taggs, usa in totals_by_fy(rows):
        fy_table.append([str(year), money(taggs), money(usa), money(usa - taggs)])
    table = Table(fy_table, colWidths=[1.2 * inch, 1.75 * inch, 1.75 * inch, 1.65 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8D3D8")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [pdf_paragraph("Exact-FON funding by fiscal year", h2), table, Spacer(1, 0.12 * inch)]

    district_counts = Counter(clean(row["congressional_district_highlight"]) or "Unresolved" for row in rows)
    district_items = sorted(district_counts.items())
    district_midpoint = (len(district_items) + 1) // 2
    district_left = district_items[:district_midpoint]
    district_right = district_items[district_midpoint:]
    district_rows = [[
        pdf_paragraph("District", small), pdf_paragraph("Awards", small),
        pdf_paragraph("District", small), pdf_paragraph("Awards", small),
    ]]
    for item_index in range(district_midpoint):
        left_district, left_count = district_left[item_index]
        right_district, right_count = district_right[item_index] if item_index < len(district_right) else ("", "")
        district_rows.append([left_district, str(left_count), right_district, str(right_count)])
    district_table = Table(district_rows, colWidths=[1.05 * inch, 0.4 * inch, 1.05 * inch, 0.4 * inch], repeatRows=1)
    district_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F5D62")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C8D3D8")),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FA")]),
    ]))
    state_counts = Counter(clean(row["state"]) or "Unknown" for row in rows)
    state_items = sorted(state_counts.items())
    state_midpoint = (len(state_items) + 1) // 2
    state_left = state_items[:state_midpoint]
    state_right = state_items[state_midpoint:]
    state_rows = [[
        pdf_paragraph("State", small), pdf_paragraph("Awards", small),
        pdf_paragraph("State", small), pdf_paragraph("Awards", small),
    ]]
    for item_index in range(state_midpoint):
        left_state, left_count = state_left[item_index]
        right_state, right_count = state_right[item_index] if item_index < len(state_right) else ("", "")
        state_rows.append([left_state, str(left_count), right_state, str(right_count)])
    state_table = Table(state_rows, colWidths=[1.05 * inch, 0.4 * inch, 1.05 * inch, 0.4 * inch], repeatRows=1)
    state_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B54708")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D6CDC7")),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FBF8F6")]),
    ]))
    story += [
        pdf_paragraph("Recipient awards by Congressional District and state", h2),
        Table([[district_table, state_table]], colWidths=[3.25 * inch, 3.25 * inch], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]),
        PageBreak(),
    ]

    for index, row in enumerate(rows, 1):
        district = clean(row["congressional_district_highlight"]) or "UNRESOLVED"
        story.append(pdf_paragraph(f"{index:02d}. {row['recipient_name']}", title))
        identity = Table(
            [
                [pdf_paragraph(district, district_style), pdf_paragraph("Congressional District", center)],
                [pdf_paragraph(row["nofo_award_number"], h1), pdf_paragraph(f"UEI: {row['uei']}", body)],
            ],
            colWidths=[2.15 * inch, 4.35 * inch],
            rowHeights=[0.46 * inch, 0.43 * inch],
        )
        identity.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#B54708")),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#F5EDE8")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F4F7F8")),
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#B8C7CC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, 0), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story += [identity, Spacer(1, 0.07 * inch)]

        address = ", ".join(filter(None, [
            clean(row["address_line_1_usaspending"]),
            clean(row["address_line_2_usaspending"]),
            clean(row["city"]),
            clean(row["state"]),
            clean(row["zip_code"]),
        ]))
        details = [
            ["Recipient address", address],
            ["County / country", " / ".join(filter(None, [clean(row["county"]), clean(row["country"])]))],
            ["District source", row["congressional_district_highlight_source"]],
            ["Census match", f"{row['census_geocoder_match_status']}: {row['census_geocoder_matched_address']}"],
            ["Recipient type", row["recipient_type_taggs"] or row["business_types_description_usaspending"]],
            ["Parent organization", row["parent_name_usaspending"]],
            ["Program office", row["program_office_taggs"] or row["funding_office_usaspending"]],
            ["Assistance listing", f"{row['cfda_number_usaspending'] or row['aln_taggs']} - {row['cfda_title_usaspending'] or row['assistance_listing_title_taggs']}"],
            ["Project period", f"{row['period_of_performance_start_min']} to {row['period_of_performance_end_max']}"],
            ["Data coverage", row["nofo_data_source"]],
        ]
        details_table = Table(
            [[pdf_paragraph(label, small), pdf_paragraph(value, small)] for label, value in details],
            colWidths=[1.18 * inch, 5.32 * inch],
        )
        details_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF3F4")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CED8DC")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story += [details_table]

        years = sorted(
            int(match.group(1))
            for key in row
            if (match := re.fullmatch(r"nofo_taggs_fy(\d{4})_sum_of_actions", key))
        )
        funding_data = [[pdf_paragraph("FY", small), pdf_paragraph("TAGGS", small), pdf_paragraph("USAspending", small)]]
        for year in years:
            funding_data.append([
                str(year),
                money(row.get(f"nofo_taggs_fy{year}_sum_of_actions")),
                money(row.get(f"nofo_usaspending_fy{year}_federal_action_obligation")),
            ])
        funding_data.append(["Total", money(row["nofo_taggs_total_sum_of_actions"]), money(row["nofo_usaspending_total_federal_action_obligation"])])
        funding_table = Table(funding_data, colWidths=[0.8 * inch, 1.35 * inch, 1.55 * inch])
        funding_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EEF3F4")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C8D3D8")),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 7.2),
        ]))
        story += [pdf_paragraph("Funding under this NOFO", h2), funding_table]

        other_data = [[
            pdf_paragraph("Rank", tiny), pdf_paragraph("Other award", tiny),
            pdf_paragraph("Amount", tiny), pdf_paragraph("OPDIV / ALN / FON", tiny),
        ]]
        for rank in range(1, 11):
            number = clean(row.get(f"other_award_{rank}_award_number"))
            if not number:
                continue
            descriptor = " / ".join(filter(None, [
                clean(row.get(f"other_award_{rank}_opdiv")),
                clean(row.get(f"other_award_{rank}_aln")),
                clean(row.get(f"other_award_{rank}_fon")),
            ]))
            title_text = clean(row.get(f"other_award_{rank}_award_title"))
            other_data.append([
                str(rank),
                pdf_paragraph(f"{number}<br/>{title_text}", tiny),
                money(row.get(f"other_award_{rank}_total_amount")),
                pdf_paragraph(descriptor, tiny),
            ])
        if len(other_data) == 1:
            other_data.append(["", pdf_paragraph("No other positive-net TAGGS awards found for this UEI.", tiny), "", ""])
        other_table = Table(other_data, colWidths=[0.35 * inch, 2.9 * inch, 1.05 * inch, 2.2 * inch], repeatRows=1)
        other_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F5D62")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C8D3D8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 1), (0, -1), "CENTER"),
            ("ALIGN", (2, 1), (2, -1), "RIGHT"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 6.4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FA")]),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        story += [pdf_paragraph("Top 10 other TAGGS awards for the same UEI", h2), other_table]

        if index < len(rows):
            story.append(PageBreak())

    doc.build(story, onFirstPage=draw_page_number, onLaterPages=draw_page_number)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    wide, long_rows, geocodes = aggregate()
    write_csv(WIDE_CSV, wide)
    write_csv(LONG_CSV, long_rows)
    write_csv(GEOCODE_CSV, geocodes)
    write_markdown(wide)
    write_pdf(wide)
    print(f"recipient_rows={len(wide)}")
    print(f"top_other_award_rows={len(long_rows)}")
    print(f"districts_resolved={sum(1 for row in wide if clean(row['congressional_district_highlight']))}")
    for path in (WIDE_CSV, LONG_CSV, GEOCODE_CSV, MARKDOWN, PDF):
        print(f"{path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
