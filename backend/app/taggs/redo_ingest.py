from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.db_schemas import TAGGS_SCHEMA
from app.taggs.models import (
    TaggsAwardFundingSummary,
    TaggsCanClassification,
    TaggsIngestionRun,
    TaggsRawAward,
    TaggsStateFundingSummary,
)

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_CHUNKSIZE = 2000
DEFAULT_SUMMARY_FILENAME = "taggs_redo_ingestion_summary.json"

ENCODING_CANDIDATES = ("utf-8-sig", "cp1252", "latin-1")

EXPECTED_BASE_HEADER = [
    "Issue Date Fiscal Year",
    "OPDIV",
    "Program Office",
    "Legal Entity Name",
    "Legal Entity City",
    "Legal Entity State",
    "Legal Entity County",
    "Legal Entity Country",
    "Period of Performance Start Date",
    "Period of Performance End Date",
    "Award Termination Date",
    "UEI",
    "FON",
    "Metro/Non-Metro",
    "Recipient Class",
    "Recipient Type",
    "Recovery Act Flag",
    "Award Number",
    "Award Title",
    "Award Code",
    "Award Class",
    "Award Activity Type",
    "ALN",
    "Assistance Listing Title",
    "Funding Fiscal Year",
    "Common Accounting Number (CAN)",
    "Sum of Actions",
]

EXPECTED_ALT_HEADER = [
    "Issue Date Fiscal Year",
    "OPDIV",
    "Program Office",
    "Legal Entity Name",
    "Legal Entity State",
    "Legal Entity ZIP Code",
    "Legal Entity Congressional District",
    "Legal Entity County",
    "Legal Entity Country",
    "Period of Performance Start Date",
    "Period of Performance End Date",
    "Award Termination Date",
    "UEI",
    "FON",
    "Metro/Non-Metro",
    "Recipient Class",
    "Recipient Type",
    "Recovery Act Flag",
    "Award Number",
    "Award Title",
    "Award Code",
    "Award Class",
    "Award Activity Type",
    "ALN",
    "Assistance Listing Title",
    "Funding Fiscal Year",
    "Common Accounting Number (CAN)",
    "Sum of Actions",
]

FIELD_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "issue_date_fiscal_year": ("Issue Date Fiscal Year", "Fiscal Year of Activity"),
    "opdiv": ("OPDIV",),
    "program_office": ("Program Office",),
    "legal_entity_name": ("Legal Entity Name",),
    "legal_entity_city": ("Legal Entity City",),
    "legal_entity_state": ("Legal Entity State",),
    "legal_entity_zip_code": ("Legal Entity ZIP Code",),
    "legal_entity_congressional_district": ("Legal Entity Congressional District",),
    "legal_entity_county": ("Legal Entity County",),
    "legal_entity_country": ("Legal Entity Country",),
    "period_of_performance_start_date": ("Period of Performance Start Date",),
    "period_of_performance_end_date": ("Period of Performance End Date",),
    "award_termination_date": ("Award Termination Date",),
    "uei": ("UEI",),
    "fon": ("FON",),
    "metro_non_metro": ("Metro/Non-Metro",),
    "recipient_class": ("Recipient Class",),
    "recipient_type": ("Recipient Type",),
    "recovery_act_flag": ("Recovery Act Flag",),
    "award_number": ("Award Number",),
    "award_title": ("Award Title",),
    "budget_year": ("Budget Year",),
    "action_issue_date": ("Action Issue Date",),
    "award_code": ("Award Code",),
    "award_class": ("Award Class",),
    "award_activity_type": ("Award Activity Type",),
    "award_action_type": ("Award Action Type",),
    "aln": ("ALN",),
    "assistance_listing_title": ("Assistance Listing Title",),
    "transaction_aln": ("Transaction ALN",),
    "transaction_assistance_listing_title": ("Transaction Assistance Listing Title",),
    "funding_fiscal_year": ("Funding Fiscal Year",),
    "can_code": ("Common Accounting Number (CAN)", "CAN"),
    "distinct_award_count": ("Distinct Award Count",),
    "sum_of_actions": ("Sum of Actions",),
}

ORDERED_CANONICAL_HEADERS = list(
    dict.fromkeys(
        alias
        for aliases in FIELD_HEADER_ALIASES.values()
        for alias in aliases
    )
)

REQUIRED_HEADER_NAMES = [
    "Issue Date Fiscal Year",
    "OPDIV",
    "Program Office",
    "Legal Entity Name",
    "Award Number",
    "Award Title",
    "Award Class",
    "Award Activity Type",
    "ALN",
    "Assistance Listing Title",
    "Funding Fiscal Year",
    "Common Accounting Number (CAN)",
    "Sum of Actions",
]

SMART_TEXT_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\ufeff": "",
    }
)

UNKNOWN_COUNTY_TOKENS = {
    "UNKNOWN",
    "UNK",
    "N/A",
    "NA",
    "UNSPECIFIED",
    "UNDEFINED",
    "NOT REPORTED",
}

US_COUNTRY_TOKENS = {
    "UNITED STATES",
    "UNITED STATES OF AMERICA",
    "US",
    "U.S.",
    "USA",
}

STATE_CODE_TO_NAME = {
    "AL": "ALABAMA",
    "AK": "ALASKA",
    "AZ": "ARIZONA",
    "AR": "ARKANSAS",
    "CA": "CALIFORNIA",
    "CO": "COLORADO",
    "CT": "CONNECTICUT",
    "DE": "DELAWARE",
    "DC": "DISTRICT OF COLUMBIA",
    "FL": "FLORIDA",
    "GA": "GEORGIA",
    "HI": "HAWAII",
    "ID": "IDAHO",
    "IL": "ILLINOIS",
    "IN": "INDIANA",
    "IA": "IOWA",
    "KS": "KANSAS",
    "KY": "KENTUCKY",
    "LA": "LOUISIANA",
    "ME": "MAINE",
    "MD": "MARYLAND",
    "MA": "MASSACHUSETTS",
    "MI": "MICHIGAN",
    "MN": "MINNESOTA",
    "MS": "MISSISSIPPI",
    "MO": "MISSOURI",
    "MT": "MONTANA",
    "NE": "NEBRASKA",
    "NV": "NEVADA",
    "NH": "NEW HAMPSHIRE",
    "NJ": "NEW JERSEY",
    "NM": "NEW MEXICO",
    "NY": "NEW YORK",
    "NC": "NORTH CAROLINA",
    "ND": "NORTH DAKOTA",
    "OH": "OHIO",
    "OK": "OKLAHOMA",
    "OR": "OREGON",
    "PA": "PENNSYLVANIA",
    "RI": "RHODE ISLAND",
    "SC": "SOUTH CAROLINA",
    "SD": "SOUTH DAKOTA",
    "TN": "TENNESSEE",
    "TX": "TEXAS",
    "UT": "UTAH",
    "VT": "VERMONT",
    "VA": "VIRGINIA",
    "WA": "WASHINGTON",
    "WV": "WEST VIRGINIA",
    "WI": "WISCONSIN",
    "WY": "WYOMING",
    "AS": "AMERICAN SAMOA",
    "GU": "GUAM",
    "MP": "NORTHERN MARIANA ISLANDS",
    "PR": "PUERTO RICO",
    "VI": "U.S. VIRGIN ISLANDS",
    "FM": "FEDERATED STATES OF MICRONESIA",
    "MH": "MARSHALL ISLANDS",
    "PW": "PALAU",
}

STATE_NAME_TO_CODE = {name: code for code, name in STATE_CODE_TO_NAME.items()}
STATE_NAME_TO_CODE["U.S. VIRGIN ISLANDS"] = "VI"
STATE_NAME_TO_CODE["US VIRGIN ISLANDS"] = "VI"
STATE_NAME_TO_CODE["NORTHERN MARIANA ISLAND"] = "MP"

DOMESTIC_SCOPE_CODES = {
    code
    for code in STATE_CODE_TO_NAME
    if code not in {"FM", "MH", "PW"}
}
OBSERVED_SCOPE_CODES = set(STATE_CODE_TO_NAME)
TERRITORY_SCOPE_CODES = {"AS", "GU", "MP", "PR", "VI", "FM", "MH", "PW", "DC"}

OPDIV_ALIASES = {
    "ACF": "ACF",
    "ASPR": "ASPR",
    "CDC": "CDC",
    "DHHS/OS": "DHHS/OS",
    "HHS/OS": "DHHS/OS",
    "HHS-OS": "DHHS/OS",
    "HRSA": "HRSA",
    "OS": "DHHS/OS",
    "SAMHSA": "SAMHSA",
    "SAMSHA": "SAMHSA",
}

HEADER_ALIAS_LOOKUP = {
    re.sub(r"\s+", " ", alias.strip().lower()): canonical
    for canonical_aliases in FIELD_HEADER_ALIASES.values()
    for alias in canonical_aliases
    for canonical in canonical_aliases[:1]
}
FIELD_ALIAS_LOOKUP = {
    field_name: {
        re.sub(r"\s+", " ", alias.strip().lower())
        for alias in aliases
    }
    for field_name, aliases in FIELD_HEADER_ALIASES.items()
}

INTERNATIONAL_KEYWORD_RE = re.compile(
    r"\b("
    r"GLOBAL|INTERNATIONAL|PEPFAR|GLOBAL FUND|WORLDWIDE|OVERSEAS|ACROSS COUNTRIES|"
    r"IMPROVING HEALTH GLOBALLY|PUBLIC HEALTH IMPACT, SYSTEMS, CAPACITY AND SECURITY"
    r")\b",
    re.IGNORECASE,
)

SEED_HEADER_ALIASES = {
    "can_code": "can_code",
    "can": "can_code",
    "common_accounting_number_(can)": "can_code",
    "common_accounting_number_can": "can_code",
    "funding_stream": "funding_stream",
    "appropriation_type": "appropriation_type",
    "category_override": "category_override",
    "subcategory_override": "subcategory_override",
    "notes": "notes",
    "is_covid_related": "is_covid_related",
    "is_arpa_related": "is_arpa_related",
    "is_supplemental": "is_supplemental",
    "is_regular_appropriation": "is_regular_appropriation",
}

RAW_AWARDS_TABLE = TaggsRawAward.__table__
AWARD_SUMMARY_TABLE = TaggsAwardFundingSummary.__table__
STATE_SUMMARY_TABLE = TaggsStateFundingSummary.__table__
CAN_CLASSIFICATION_TABLE = TaggsCanClassification.__table__
INGESTION_RUNS_TABLE = TaggsIngestionRun.__table__

CURRENT_TAGGS_TABLES = [
    RAW_AWARDS_TABLE,
    AWARD_SUMMARY_TABLE,
    STATE_SUMMARY_TABLE,
    CAN_CLASSIFICATION_TABLE,
    INGESTION_RUNS_TABLE,
]

CURRENT_TAGGS_TABLE_NAMES = [table.name for table in CURRENT_TAGGS_TABLES]
LEGACY_TAGGS_TABLE_NAMES = [
    "award_funding_year_summary",
    "award_actions_canonical",
    "raw_web_rows",
    "scrape_runs",
]
SCHEMA_RESET_NOTICE = (
    "--drop-and-recreate recreates TAGGS tables from the current ORM definitions in "
    "app.taggs.models and does not advance alembic_version. Run alembic upgrade head "
    "to keep schema version tracking aligned."
)


@dataclass
class FileStructureInfo:
    path: Path
    encoding: str
    banner_rows: list[list[str]]
    banner_metadata: dict[str, Any]
    header_row_index: int
    normalized_header: list[str]
    canonical_header: list[str]
    source_opdiv_hint: str | None
    source_state_hint: str | None
    source_is_territory_file: bool
    unknown_headers: list[str]
    duplicate_header_targets: list[str]
    missing_required_headers: list[str]
    header_field_map: dict[str, str]


@dataclass
class ParseStats:
    main_award_rows: int = 0
    description_rows_paired: int = 0
    orphan_description_rows: int = 0
    repeated_description_rows: int = 0
    blank_rows: int = 0
    footer_rows: int = 0
    skipped_singleton_rows: int = 0
    total_csv_rows: int = 0
    funding_fiscal_years: set[int] = field(default_factory=set)
    issue_fiscal_years: set[int] = field(default_factory=set)
    can_codes: set[str] = field(default_factory=set)
    anomalies: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AwardSummaryAccumulator:
    row: dict[str, Any]
    total_sum_of_actions: Decimal = Decimal("0.00")
    raw_row_count: int = 0
    is_domestic_scope: bool = True


@dataclass
class StateSummaryAccumulator:
    funding_fiscal_year: int
    legal_entity_state_normalized: str
    opdiv: str | None
    can_code: str | None
    program_office: str | None
    aln: str | None
    is_domestic_scope: bool
    total_sum_of_actions: Decimal = Decimal("0.00")
    award_numbers: set[str] = field(default_factory=set)
    recipient_names: set[str] = field(default_factory=set)
    counties: set[str] = field(default_factory=set)


@dataclass
class CanDominanceAccumulator:
    counts: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))
    funding: defaultdict[str, Decimal] = field(
        default_factory=lambda: defaultdict(lambda: Decimal("0.00"))
    )


@dataclass
class CanClassificationAccumulator:
    can_code: str
    observed_first_fy: int | None = None
    observed_last_fy: int | None = None
    observed_row_count: int = 0
    observed_total_funding: Decimal = Decimal("0.00")
    opdiv_values: CanDominanceAccumulator = field(default_factory=CanDominanceAccumulator)
    program_office_values: CanDominanceAccumulator = field(default_factory=CanDominanceAccumulator)
    aln_values: CanDominanceAccumulator = field(default_factory=CanDominanceAccumulator)
    assistance_listing_values: CanDominanceAccumulator = field(default_factory=CanDominanceAccumulator)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Rebuild TAGGS CSV ingestion tables in schema {TAGGS_SCHEMA}.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Directory containing TAGGS redo CSV exports (defaults to data/taggs/redo).",
    )
    parser.add_argument(
        "--summary-path",
        default=None,
        help=f"Optional validation summary path (defaults to <input-dir>/{DEFAULT_SUMMARY_FILENAME}).",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"Insert batch size for database writes (default: {DEFAULT_CHUNKSIZE}).",
    )
    parser.add_argument(
        "--truncate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Truncate TAGGS raw/summary tables before loading (default: true).",
    )
    parser.add_argument(
        "--drop-and-recreate",
        action="store_true",
        help="Drop legacy/current TAGGS tables in the schema and recreate the rebuilt model before loading.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate/parse only. Skip database writes.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-file validation details while running.",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=None,
        help="Optional deterministic cap on files processed after sorting.",
    )
    parser.add_argument(
        "--rebuild-summaries",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Rebuild award/state summary tables from parsed CSV records (default: true).",
    )
    parser.add_argument(
        "--rebuild-can-table",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh the CAN inventory/classification table from observed data (default: true).",
    )
    return parser.parse_args()


def _resolve_input_dir(explicit_input_dir: str | None) -> Path:
    if explicit_input_dir:
        return Path(explicit_input_dir).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[3]
    return (repo_root / "data" / "taggs" / "redo").resolve()


def _resolve_summary_path(input_dir: Path, explicit_summary_path: str | None) -> Path:
    if explicit_summary_path:
        return Path(explicit_summary_path).expanduser().resolve()
    return (input_dir / DEFAULT_SUMMARY_FILENAME).resolve()


def discover_input_files(input_dir: Path, *, limit_files: int | None = None) -> list[Path]:
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise RuntimeError(f"Input path is not a directory: {input_dir}")

    files = sorted(path.resolve() for path in input_dir.glob("*.csv"))
    if limit_files is not None and limit_files >= 0:
        files = files[:limit_files]
    if not files:
        raise RuntimeError(f"No CSV files found in {input_dir}")
    return files


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).translate(SMART_TEXT_TRANSLATION)
    token = token.replace("\r\n", "\n").replace("\r", "\n")
    token = re.sub(r"\s+", " ", token).strip()
    return token or None


def _clean_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    token = html.unescape(str(value)).translate(SMART_TEXT_TRANSLATION)
    token = token.replace("\r\n", "\n").replace("\r", "\n")
    token = re.sub(r"<[^>]+>", "", token)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in token.split("\n")]
    cleaned = "\n".join(line for line in lines if line).strip()
    return cleaned or None


def _normalize_header_value(value: Any) -> str:
    token = str(value or "").translate(SMART_TEXT_TRANSLATION)
    token = token.replace("\r\n", "\n").replace("\r", "\n")
    token = re.sub(r"\s+", " ", token).strip()
    return token


def _normalize_header_key(value: Any) -> str:
    return re.sub(r"\s+", " ", _normalize_header_value(value).lower())


def _normalize_geo_token(value: Any) -> str | None:
    token = _clean_text(value)
    if token is None:
        return None
    return re.sub(r"\s+", " ", token.upper()).strip()


def _normalize_state_value(value: Any) -> str | None:
    token = _clean_text(value)
    if token is None:
        return None
    upper = re.sub(r"\s+", " ", token.upper()).strip()
    if upper in STATE_NAME_TO_CODE:
        return STATE_NAME_TO_CODE[upper]
    letters_only = re.sub(r"[^A-Z]", "", upper)
    if len(letters_only) == 2 and letters_only in OBSERVED_SCOPE_CODES:
        return letters_only
    return upper


def _normalize_country_value(value: Any) -> str | None:
    token = _normalize_geo_token(value)
    if token in US_COUNTRY_TOKENS:
        return "UNITED STATES"
    return token


def _parse_int(value: Any) -> int | None:
    token = _clean_text(value)
    if token is None:
        return None
    compact = token.replace(",", "")
    if not re.fullmatch(r"-?\d+", compact):
        return None
    try:
        return int(compact)
    except ValueError:
        return None


def _parse_fiscal_year(value: Any) -> int | None:
    parsed = _parse_int(value)
    if parsed is None:
        return None
    return parsed if 1900 <= parsed <= 2100 else None


def _parse_budget_year(value: Any) -> int | None:
    parsed = _parse_int(value)
    if parsed is None:
        return None
    return parsed if -100 <= parsed <= 100 else None


def _parse_date(value: Any) -> date | None:
    token = _clean_text(value)
    if token is None:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value: Any) -> Decimal | None:
    token = _clean_text(value)
    if token is None:
        return None
    compact = token.replace("$", "").replace(",", "").replace(" ", "").replace("−", "-")
    negative = False
    if compact.startswith("(") and compact.endswith(")"):
        compact = compact[1:-1]
        negative = True
    if compact in {"", "-", "+"}:
        return None
    try:
        parsed = Decimal(compact)
    except InvalidOperation:
        return None
    if not parsed.is_finite():
        return None
    if negative:
        parsed = -parsed
    return parsed.quantize(Decimal("0.01"))


def _record_anomaly(stats: ParseStats, kind: str, **payload: Any) -> None:
    if len(stats.anomalies) >= 200:
        return
    stats.anomalies.append({"kind": kind, **payload})


def _probe_encoding(path: Path) -> str:
    last_error: Exception | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                while handle.read(1024 * 1024):
                    pass
            return encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Unable to decode TAGGS CSV {path}: {last_error}")


def parse_metadata_banner(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        banner_text = "\n".join(str(item) for item in value if _clean_text(item) is not None)
    else:
        banner_text = str(value or "")
    banner_text = banner_text.translate(SMART_TEXT_TRANSLATION)
    banner_text = banner_text.replace("\r\n", "\n").replace("\r", "\n").strip()

    lines: list[str] = []
    for raw_line in banner_text.split("\n"):
        cleaned = raw_line.strip()
        if cleaned:
            lines.append(cleaned)

    export_label = lines[0] if lines else None
    metadata_fields: dict[str, str] = {}
    listed_fiscal_years: list[int] = []
    states: list[str] = []
    warnings: list[str] = []

    metadata_candidates = lines[1:] if len(lines) > 1 else []
    for line in metadata_candidates:
        for chunk in line.split(";"):
            piece = chunk.strip().lstrip(";").strip()
            if not piece or ":" not in piece:
                continue
            key, value_text = piece.split(":", 1)
            normalized_key = re.sub(r"\s+", " ", key.strip().lower())
            metadata_fields[normalized_key] = value_text.strip()

    fiscal_year_blob = " ".join(
        value
        for key, value in metadata_fields.items()
        if "fiscal year" in key
    )
    for token in re.findall(r"\d{4}", fiscal_year_blob):
        parsed = _parse_fiscal_year(token)
        if parsed is not None and parsed not in listed_fiscal_years:
            listed_fiscal_years.append(parsed)

    opdiv = _canonicalize_opdiv(_clean_text(metadata_fields.get("opdiv")))
    states_value = metadata_fields.get("states") or metadata_fields.get("state")
    if states_value:
        parsed_states: list[str] = []
        for token in states_value.split(","):
            normalized = _normalize_state_value(token)
            if normalized is None:
                continue
            if normalized not in parsed_states:
                parsed_states.append(normalized)
        states = parsed_states

    banner_valid = bool(export_label and export_label.lower() == "taggs advanced search export")
    if not banner_valid:
        warnings.append("Banner does not begin with the expected TAGGS export label.")

    return {
        "banner_text": banner_text or None,
        "banner_lines": lines,
        "export_label": export_label,
        "listed_fiscal_years": listed_fiscal_years,
        "opdiv": opdiv,
        "states": states,
        "metadata_fields": metadata_fields,
        "banner_valid": banner_valid,
        "warnings": warnings,
    }


def _canonicalize_opdiv(value: Any) -> str | None:
    token = _clean_text(value)
    if token is None:
        return None
    compact = token.upper().replace("_", "-")
    compact = re.sub(r"\s+", "", compact)
    if compact == "DHHS/OS":
        return "DHHS/OS"
    if compact in {"HHS/OS", "HHS-OS"}:
        return "DHHS/OS"
    if compact == "SAMSHA":
        return "SAMHSA"
    normalized = re.sub(r"\s+", " ", token.upper()).strip()
    return OPDIV_ALIASES.get(normalized, normalized)


def _infer_filename_metadata(path: Path) -> dict[str, Any]:
    stem = path.stem.strip()
    normalized = stem.upper().replace("_", "-")
    warnings: list[str] = []

    territory_tokens = {
        "USTS",
        "US-TS",
        "US-TS",
        "US-TERRITORIES",
        "US TERRITORIES",
        "TERRITORIES",
        "TERRITORY",
    }
    source_is_territory_file = any(token in normalized for token in territory_tokens)

    filename_state_hints: list[str] = []
    if normalized in STATE_NAME_TO_CODE:
        filename_state_hints.append(STATE_NAME_TO_CODE[normalized])
    elif normalized in STATE_CODE_TO_NAME:
        filename_state_hints.append(normalized)
    else:
        for state_name, state_code in STATE_NAME_TO_CODE.items():
            if normalized == state_name or normalized.endswith(f"-{state_name}") or normalized.startswith(
                f"{state_name}-"
            ):
                filename_state_hints.append(state_code)
                break

    filename_opdiv_hint = None
    if normalized.startswith("HHS-OS"):
        filename_opdiv_hint = "DHHS/OS"
    else:
        first_segment = normalized.split("-", 1)[0]
        filename_opdiv_hint = _canonicalize_opdiv(first_segment)

    if filename_opdiv_hint is None:
        warnings.append(f"Could not infer OPDIV from filename {path.name}.")

    return {
        "filename_opdiv_hint": filename_opdiv_hint,
        "filename_state_hints": filename_state_hints,
        "filename_is_territory_file": source_is_territory_file,
        "warnings": warnings,
    }


def infer_source_scope(path: Path, banner_metadata: dict[str, Any]) -> dict[str, Any]:
    filename_metadata = _infer_filename_metadata(path)
    warnings = list(filename_metadata["warnings"])

    banner_opdiv = _canonicalize_opdiv(banner_metadata.get("opdiv"))
    filename_opdiv_hint = filename_metadata["filename_opdiv_hint"]
    source_opdiv_hint = banner_opdiv or filename_opdiv_hint
    if banner_opdiv and filename_opdiv_hint and banner_opdiv != filename_opdiv_hint:
        warnings.append(
            f"Filename OPDIV hint {filename_opdiv_hint} disagrees with banner OPDIV {banner_opdiv}."
        )

    metadata_states = [
        normalized
        for normalized in (
            _normalize_state_value(value)
            for value in banner_metadata.get("states", [])
        )
        if normalized is not None
    ]
    filename_state_hints = list(filename_metadata["filename_state_hints"])

    source_is_territory_file = bool(
        filename_metadata["filename_is_territory_file"]
        or (metadata_states and all(state in TERRITORY_SCOPE_CODES for state in metadata_states))
    )

    source_state_hint = None
    if source_is_territory_file:
        source_state_hint = "US-TERRITORIES"
    elif len(filename_state_hints) == 1:
        source_state_hint = filename_state_hints[0]
    elif len(metadata_states) == 1:
        source_state_hint = metadata_states[0]

    if len(filename_state_hints) == 1 and len(metadata_states) == 1 and filename_state_hints[0] != metadata_states[0]:
        warnings.append(
            f"Filename state {filename_state_hints[0]} disagrees with banner state {metadata_states[0]}."
        )

    if source_is_territory_file and metadata_states and any(
        state not in TERRITORY_SCOPE_CODES for state in metadata_states
    ):
        warnings.append("Territory-style file banner includes non-territory state codes.")

    return {
        "filename_opdiv_hint": filename_opdiv_hint,
        "filename_state_hints": filename_state_hints,
        "source_opdiv_hint": source_opdiv_hint,
        "source_state_hint": source_state_hint,
        "source_is_territory_file": source_is_territory_file,
        "warnings": warnings,
    }


def _extract_banner_rows(rows: list[list[str]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        raw_non_blank_cells = [str(cell) for cell in row if _clean_text(cell) is not None]
        non_blank_cells = [_clean_text(cell) for cell in raw_non_blank_cells if _clean_text(cell) is not None]
        if not non_blank_cells:
            continue
        if len(non_blank_cells) == 1:
            cell_text = raw_non_blank_cells[0].translate(SMART_TEXT_TRANSLATION)
            cell_text = cell_text.replace("\r\n", "\n").replace("\r", "\n")
            for line in cell_text.split("\n"):
                cleaned = _clean_text(line)
                if cleaned is not None:
                    lines.append(cleaned)
        else:
            joined = " ; ".join(str(cell) for cell in non_blank_cells)
            cleaned = _clean_text(joined)
            if cleaned is not None:
                lines.append(cleaned)
    return lines


def _map_actual_header_to_canonical(value: Any) -> str | None:
    normalized = _normalize_header_key(value)
    return HEADER_ALIAS_LOOKUP.get(normalized)


def _looks_like_header_row(row: list[str]) -> bool:
    canonical_headers = {_map_actual_header_to_canonical(value) for value in row}
    recognized = {value for value in canonical_headers if value is not None}
    if "Issue Date Fiscal Year" not in recognized:
        return False
    if "Award Number" not in recognized:
        return False
    if "Funding Fiscal Year" not in recognized:
        return False
    if "Sum of Actions" not in recognized:
        return False
    return len(recognized) >= 8


def inspect_file_structure(path: Path, *, encoding: str | None = None) -> FileStructureInfo:
    parse_encoding = encoding or _probe_encoding(path)
    banner_rows: list[list[str]] = []
    header_row_index = 0
    header_row: list[str] = []

    with path.open("r", encoding=parse_encoding, newline="") as handle:
        reader = csv.reader(handle)
        for row_number, raw_row in enumerate(reader, start=1):
            normalized_row = [_normalize_header_value(value) for value in raw_row]
            if _looks_like_header_row(normalized_row):
                header_row_index = row_number
                header_row = normalized_row
                break
            banner_rows.append(list(raw_row))

    if not header_row:
        raise RuntimeError(f"{path.name}: could not locate TAGGS header row")

    banner_text = "\n".join(_extract_banner_rows(banner_rows))
    banner_metadata = parse_metadata_banner(banner_text)
    scope = infer_source_scope(path, banner_metadata)
    banner_metadata = {
        **banner_metadata,
        "filename_opdiv_hint": scope["filename_opdiv_hint"],
        "filename_state_hints": scope["filename_state_hints"],
        "source_opdiv_hint": scope["source_opdiv_hint"],
        "source_state_hint": scope["source_state_hint"],
        "source_is_territory_file": scope["source_is_territory_file"],
        "warnings": list(banner_metadata.get("warnings", [])) + scope["warnings"],
    }

    canonical_header: list[str] = []
    unknown_headers: list[str] = []
    duplicate_targets: list[str] = []
    seen_targets: set[str] = set()
    header_field_map: dict[str, str] = {}

    for actual_header in header_row:
        canonical = _map_actual_header_to_canonical(actual_header)
        if canonical is None:
            canonical_header.append(actual_header)
            unknown_headers.append(actual_header)
            continue
        canonical_header.append(canonical)
        if canonical in seen_targets:
            duplicate_targets.append(canonical)
        seen_targets.add(canonical)
        for field_name, aliases in FIELD_HEADER_ALIASES.items():
            if canonical in aliases and field_name not in header_field_map:
                header_field_map[field_name] = actual_header
                break

    missing_required_headers = [
        header_name
        for header_name in REQUIRED_HEADER_NAMES
        if header_name not in seen_targets
    ]

    return FileStructureInfo(
        path=path,
        encoding=parse_encoding,
        banner_rows=banner_rows,
        banner_metadata=banner_metadata,
        header_row_index=header_row_index,
        normalized_header=header_row,
        canonical_header=canonical_header,
        source_opdiv_hint=scope["source_opdiv_hint"],
        source_state_hint=scope["source_state_hint"],
        source_is_territory_file=scope["source_is_territory_file"],
        unknown_headers=unknown_headers,
        duplicate_header_targets=duplicate_targets,
        missing_required_headers=missing_required_headers,
        header_field_map=header_field_map,
    )


def collect_header_discrepancies(structures: list[FileStructureInfo]) -> list[dict[str, Any]]:
    if not structures:
        return []

    canonical_union = [
        header_name
        for header_name in ORDERED_CANONICAL_HEADERS
        if any(header_name in structure.canonical_header for structure in structures)
    ]

    discrepancies: list[dict[str, Any]] = []
    for structure in structures:
        missing_from_union = [
            header_name
            for header_name in canonical_union
            if header_name not in structure.canonical_header
        ]
        if not (
            missing_from_union
            or structure.unknown_headers
            or structure.duplicate_header_targets
            or structure.missing_required_headers
            or structure.banner_metadata.get("warnings")
        ):
            continue
        discrepancies.append(
            {
                "filename": structure.path.name,
                "header_row_index": structure.header_row_index,
                "actual_header": structure.normalized_header,
                "canonical_header": structure.canonical_header,
                "missing_required_headers": structure.missing_required_headers,
                "missing_from_canonical_union": missing_from_union,
                "unknown_headers": structure.unknown_headers,
                "duplicate_header_targets": structure.duplicate_header_targets,
                "warnings": structure.banner_metadata.get("warnings", []),
            }
        )
    return discrepancies


def collect_header_validation(structures: list[FileStructureInfo]) -> dict[str, Any]:
    canonical_union = [
        header_name
        for header_name in ORDERED_CANONICAL_HEADERS
        if any(header_name in structure.canonical_header for structure in structures)
    ]

    header_sets: dict[tuple[str, ...], dict[str, Any]] = {}
    fatal_errors: list[dict[str, Any]] = []
    for structure in structures:
        signature = tuple(structure.canonical_header)
        bucket = header_sets.setdefault(
            signature,
            {
                "canonical_header": list(signature),
                "files": [],
            },
        )
        bucket["files"].append(structure.path.name)

        if structure.missing_required_headers or structure.duplicate_header_targets:
            fatal_errors.append(
                {
                    "filename": structure.path.name,
                    "missing_required_headers": structure.missing_required_headers,
                    "duplicate_header_targets": structure.duplicate_header_targets,
                }
            )

    return {
        "canonical_union": canonical_union,
        "required_headers": list(REQUIRED_HEADER_NAMES),
        "observed_header_sets": list(header_sets.values()),
        "file_diffs": collect_header_discrepancies(structures),
        "fatal_errors": fatal_errors,
        "is_reconcilable": not fatal_errors,
    }


def _coerce_row_width(
    row: list[str],
    *,
    expected_len: int,
    stats: ParseStats,
    path: Path,
    row_number: int,
) -> list[str]:
    if len(row) == expected_len:
        return row
    if len(row) < expected_len:
        _record_anomaly(
            stats,
            "row_length_short",
            file=path.name,
            row_number=row_number,
            row_length=len(row),
            expected_length=expected_len,
        )
        return row + [""] * (expected_len - len(row))
    _record_anomaly(
        stats,
        "row_length_long",
        file=path.name,
        row_number=row_number,
        row_length=len(row),
        expected_length=expected_len,
    )
    return row[:expected_len]


def _classify_row(row: list[str]) -> str:
    populated_indexes = [index for index, value in enumerate(row) if _clean_text(value) is not None]
    if not populated_indexes:
        return "blank"
    if len(populated_indexes) == 1:
        token = _clean_text(row[populated_indexes[0]]) or ""
        lowered = token.lower()
        if lowered.startswith("exported on ") or lowered.startswith("page total:"):
            return "footer"
        if populated_indexes[0] == 0:
            return "description"
    if len(populated_indexes) == 1:
        return "single_column_non_description"
    return "main"


def _canonical_row_lookup(
    structure: FileStructureInfo,
    raw_row_json: dict[str, Any],
) -> dict[str, Any]:
    lookup: dict[str, Any] = {}
    for field_name, actual_header in structure.header_field_map.items():
        if actual_header in raw_row_json:
            lookup[field_name] = raw_row_json[actual_header]
    return lookup


def _parse_with_anomaly(
    parser: Any,
    value: Any,
    *,
    field_name: str,
    stats: ParseStats,
    path: Path,
    row_number: int,
) -> Any:
    parsed = parser(value)
    if parsed is None and _clean_text(value) is not None:
        _record_anomaly(
            stats,
            "invalid_field_value",
            file=path.name,
            row_number=row_number,
            field_name=field_name,
            raw_value=str(value),
        )
    return parsed


def _build_raw_award_record(
    raw_row_json: dict[str, Any],
    *,
    structure: FileStructureInfo,
    source_path: Path,
    row_number_main: int,
    stats: ParseStats,
) -> dict[str, Any]:
    payload = _canonical_row_lookup(structure, raw_row_json)

    legal_entity_state = _clean_text(payload.get("legal_entity_state"))
    legal_entity_country = _clean_text(payload.get("legal_entity_country"))

    return {
        "source_file": str(source_path.resolve()),
        "source_filename": source_path.name,
        "source_metadata_json": structure.banner_metadata,
        "source_opdiv_hint": structure.source_opdiv_hint,
        "source_state_hint": structure.source_state_hint,
        "source_is_territory_file": structure.source_is_territory_file,
        "row_number_main": row_number_main,
        "issue_date_fiscal_year": _parse_with_anomaly(
            _parse_fiscal_year,
            payload.get("issue_date_fiscal_year"),
            field_name="issue_date_fiscal_year",
            stats=stats,
            path=source_path,
            row_number=row_number_main,
        ),
        "opdiv": _canonicalize_opdiv(payload.get("opdiv")) or _clean_text(payload.get("opdiv")),
        "program_office": _clean_text(payload.get("program_office")),
        "legal_entity_name": _clean_text(payload.get("legal_entity_name")),
        "legal_entity_city": _clean_text(payload.get("legal_entity_city")),
        "legal_entity_state": legal_entity_state,
        "legal_entity_zip_code": _clean_text(payload.get("legal_entity_zip_code")),
        "legal_entity_congressional_district": _clean_text(
            payload.get("legal_entity_congressional_district")
        ),
        "legal_entity_county": _clean_text(payload.get("legal_entity_county")),
        "legal_entity_country": legal_entity_country,
        "period_of_performance_start_date": _parse_with_anomaly(
            _parse_date,
            payload.get("period_of_performance_start_date"),
            field_name="period_of_performance_start_date",
            stats=stats,
            path=source_path,
            row_number=row_number_main,
        ),
        "period_of_performance_end_date": _parse_with_anomaly(
            _parse_date,
            payload.get("period_of_performance_end_date"),
            field_name="period_of_performance_end_date",
            stats=stats,
            path=source_path,
            row_number=row_number_main,
        ),
        "award_termination_date": _parse_with_anomaly(
            _parse_date,
            payload.get("award_termination_date"),
            field_name="award_termination_date",
            stats=stats,
            path=source_path,
            row_number=row_number_main,
        ),
        "uei": _clean_text(payload.get("uei")),
        "fon": _clean_text(payload.get("fon")),
        "metro_non_metro": _clean_text(payload.get("metro_non_metro")),
        "recipient_class": _clean_text(payload.get("recipient_class")),
        "recipient_type": _clean_text(payload.get("recipient_type")),
        "recovery_act_flag": _clean_text(payload.get("recovery_act_flag")),
        "award_number": _clean_text(payload.get("award_number")),
        "award_title": _clean_text(payload.get("award_title")),
        "award_description": None,
        "budget_year": _parse_with_anomaly(
            _parse_budget_year,
            payload.get("budget_year"),
            field_name="budget_year",
            stats=stats,
            path=source_path,
            row_number=row_number_main,
        ),
        "action_issue_date": _parse_with_anomaly(
            _parse_date,
            payload.get("action_issue_date"),
            field_name="action_issue_date",
            stats=stats,
            path=source_path,
            row_number=row_number_main,
        ),
        "award_code": _clean_text(payload.get("award_code")),
        "award_class": _clean_text(payload.get("award_class")),
        "award_activity_type": _clean_text(payload.get("award_activity_type")),
        "award_action_type": _clean_text(payload.get("award_action_type")),
        "aln": _clean_text(payload.get("aln")),
        "assistance_listing_title": _clean_text(payload.get("assistance_listing_title")),
        "transaction_aln": _clean_text(payload.get("transaction_aln")),
        "transaction_assistance_listing_title": _clean_text(
            payload.get("transaction_assistance_listing_title")
        ),
        "funding_fiscal_year": _parse_with_anomaly(
            _parse_fiscal_year,
            payload.get("funding_fiscal_year"),
            field_name="funding_fiscal_year",
            stats=stats,
            path=source_path,
            row_number=row_number_main,
        ),
        "can_code": _clean_text(payload.get("can_code")),
        "distinct_award_count": _parse_with_anomaly(
            _parse_int,
            payload.get("distinct_award_count"),
            field_name="distinct_award_count",
            stats=stats,
            path=source_path,
            row_number=row_number_main,
        ),
        "sum_of_actions": _parse_with_anomaly(
            _parse_amount,
            payload.get("sum_of_actions"),
            field_name="sum_of_actions",
            stats=stats,
            path=source_path,
            row_number=row_number_main,
        ),
        "legal_entity_state_normalized": _normalize_state_value(legal_entity_state),
        "legal_entity_county_normalized": _normalize_geo_token(payload.get("legal_entity_county")),
        "legal_entity_country_normalized": _normalize_country_value(legal_entity_country),
        "raw_header_json": {
            "header_row_index": structure.header_row_index,
            "actual_headers": structure.normalized_header,
            "canonical_headers": structure.canonical_header,
            "field_to_actual_header": structure.header_field_map,
            "unknown_headers": structure.unknown_headers,
        },
        "raw_row_json": {
            "main_row": raw_row_json,
            "description_rows": [],
        },
    }


def parse_taggs_csv_file(
    path: Path,
    *,
    encoding: str | None = None,
    inspection: FileStructureInfo | None = None,
) -> tuple[list[dict[str, Any]], ParseStats, str]:
    structure = inspection or inspect_file_structure(path, encoding=encoding)
    records: list[dict[str, Any]] = []
    stats = ParseStats()

    with path.open("r", encoding=structure.encoding, newline="") as handle:
        reader = csv.reader(handle)
        for row_number, raw_row in enumerate(reader, start=1):
            stats.total_csv_rows += 1
            if row_number <= structure.header_row_index:
                continue

            row = _coerce_row_width(
                list(raw_row),
                expected_len=len(structure.normalized_header),
                stats=stats,
                path=path,
                row_number=row_number,
            )
            row_type = _classify_row(row)

            if row_type == "blank":
                stats.blank_rows += 1
                continue
            if row_type == "footer":
                stats.footer_rows += 1
                continue

            if row_type == "description":
                if not records:
                    stats.orphan_description_rows += 1
                    _record_anomaly(
                        stats,
                        "orphan_description_row",
                        file=path.name,
                        row_number=row_number,
                        value_preview=(row[0] or "")[:160],
                    )
                    continue
                description_text = _clean_multiline_text(row[0])
                if not description_text:
                    continue
                latest_record = records[-1]
                raw_description_rows = latest_record["raw_row_json"].setdefault("description_rows", [])
                raw_description_rows.append(row[0])
                if latest_record.get("award_description"):
                    latest_record["award_description"] = (
                        f"{latest_record['award_description']}\n{description_text}"
                    )
                    stats.repeated_description_rows += 1
                    _record_anomaly(
                        stats,
                        "repeated_description_row",
                        file=path.name,
                        row_number=row_number,
                    )
                else:
                    latest_record["award_description"] = description_text
                stats.description_rows_paired += 1
                continue

            if row_type == "single_column_non_description":
                stats.skipped_singleton_rows += 1
                _record_anomaly(
                    stats,
                    "single_column_non_description",
                    file=path.name,
                    row_number=row_number,
                    row=row,
                )
                continue

            raw_row_json = dict(zip(structure.normalized_header, row, strict=True))
            record = _build_raw_award_record(
                raw_row_json,
                structure=structure,
                source_path=path,
                row_number_main=row_number,
                stats=stats,
            )
            records.append(record)
            stats.main_award_rows += 1
            if record.get("funding_fiscal_year") is not None:
                stats.funding_fiscal_years.add(int(record["funding_fiscal_year"]))
            if record.get("issue_date_fiscal_year") is not None:
                stats.issue_fiscal_years.add(int(record["issue_date_fiscal_year"]))
            if record.get("can_code"):
                stats.can_codes.add(str(record["can_code"]))

    return records, stats, structure.encoding


def _normalize_key_token(value: Any) -> str | None:
    token = _clean_text(value)
    return token if token is not None else None


def _choose_preferred_text(
    existing: str | None,
    candidate: str | None,
    *,
    prefer_longest: bool = False,
) -> str | None:
    if candidate is None:
        return existing
    if existing is None:
        return candidate
    if prefer_longest and len(candidate) > len(existing):
        return candidate
    return existing


def _is_us_country(value: str | None) -> bool:
    return bool(value and value in US_COUNTRY_TOKENS)


def _is_domestic_scope(record: dict[str, Any]) -> bool:
    country = record.get("legal_entity_country_normalized")
    state = record.get("legal_entity_state_normalized")
    text_blob = " ".join(
        [
            str(record.get("award_title") or ""),
            str(record.get("assistance_listing_title") or ""),
            str(record.get("award_description") or ""),
        ]
    )
    if country and not _is_us_country(country):
        return False
    if state and state not in DOMESTIC_SCOPE_CODES:
        return False
    if INTERNATIONAL_KEYWORD_RE.search(text_blob):
        return False
    return bool(country or state)


def _is_non_us_row(record: dict[str, Any]) -> bool:
    country = record.get("legal_entity_country_normalized")
    state = record.get("legal_entity_state_normalized")
    if country and not _is_us_country(country):
        return True
    return bool(state and state not in OBSERVED_SCOPE_CODES)


def _is_undefined_county(value: str | None) -> bool:
    if value is None:
        return True
    return value in UNKNOWN_COUNTY_TOKENS


def _accumulate_award_summary(
    accumulators: dict[tuple[Any, ...], AwardSummaryAccumulator],
    record: dict[str, Any],
) -> None:
    award_number = _normalize_key_token(record.get("award_number"))
    funding_fiscal_year = record.get("funding_fiscal_year")
    if award_number is None or funding_fiscal_year is None:
        return

    key = (
        award_number,
        int(funding_fiscal_year),
        _normalize_key_token(record.get("opdiv")),
        _normalize_key_token(record.get("can_code")),
        _normalize_key_token(record.get("legal_entity_state_normalized")),
        _normalize_key_token(record.get("legal_entity_county_normalized")),
        _normalize_key_token(record.get("program_office")),
        _normalize_key_token(record.get("aln")),
    )

    accumulator = accumulators.get(key)
    if accumulator is None:
        accumulator = AwardSummaryAccumulator(
            row={
                "award_number": award_number,
                "funding_fiscal_year": int(funding_fiscal_year),
                "opdiv": record.get("opdiv"),
                "can_code": record.get("can_code"),
                "legal_entity_state_normalized": record.get("legal_entity_state_normalized"),
                "legal_entity_county_normalized": record.get("legal_entity_county_normalized"),
                "legal_entity_country_normalized": record.get("legal_entity_country_normalized"),
                "program_office": record.get("program_office"),
                "aln": record.get("aln"),
                "assistance_listing_title": record.get("assistance_listing_title"),
                "award_title": record.get("award_title"),
                "award_description": record.get("award_description"),
                "legal_entity_name": record.get("legal_entity_name"),
                "legal_entity_city": record.get("legal_entity_city"),
                "effective_program_name": None,
                "effective_category": None,
                "effective_subcategory": None,
                "effective_mapping_method": None,
                "funding_stream": None,
                "appropriation_type": None,
                "has_profile_assisted_mapping": False,
                "has_fallback_inference": False,
                "can_mapping_version": None,
            },
            is_domestic_scope=_is_domestic_scope(record),
        )
        accumulators[key] = accumulator

    accumulator.total_sum_of_actions += record.get("sum_of_actions") or Decimal("0.00")
    accumulator.raw_row_count += 1
    accumulator.is_domestic_scope = accumulator.is_domestic_scope and _is_domestic_scope(record)
    accumulator.row["opdiv"] = _choose_preferred_text(accumulator.row.get("opdiv"), record.get("opdiv"))
    accumulator.row["legal_entity_country_normalized"] = _choose_preferred_text(
        accumulator.row.get("legal_entity_country_normalized"),
        record.get("legal_entity_country_normalized"),
    )
    accumulator.row["assistance_listing_title"] = _choose_preferred_text(
        accumulator.row.get("assistance_listing_title"),
        record.get("assistance_listing_title"),
    )
    accumulator.row["award_title"] = _choose_preferred_text(
        accumulator.row.get("award_title"),
        record.get("award_title"),
        prefer_longest=True,
    )
    accumulator.row["award_description"] = _choose_preferred_text(
        accumulator.row.get("award_description"),
        record.get("award_description"),
        prefer_longest=True,
    )
    accumulator.row["legal_entity_name"] = _choose_preferred_text(
        accumulator.row.get("legal_entity_name"),
        record.get("legal_entity_name"),
    )
    accumulator.row["legal_entity_city"] = _choose_preferred_text(
        accumulator.row.get("legal_entity_city"),
        record.get("legal_entity_city"),
    )


def build_award_funding_summary_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accumulators: dict[tuple[Any, ...], AwardSummaryAccumulator] = {}
    for record in records:
        _accumulate_award_summary(accumulators, record)
    refreshed_at = datetime.now(timezone.utc)
    return [
        {
            **accumulator.row,
            "total_sum_of_actions": accumulator.total_sum_of_actions.quantize(Decimal("0.01")),
            "raw_row_count": accumulator.raw_row_count,
            "is_domestic_scope": accumulator.is_domestic_scope,
            "refreshed_at": refreshed_at,
        }
        for accumulator in accumulators.values()
    ]


def build_state_funding_summary_rows(
    award_summary_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    accumulators: dict[tuple[Any, ...], StateSummaryAccumulator] = {}

    for row in award_summary_rows:
        funding_fiscal_year = row.get("funding_fiscal_year")
        state = _normalize_state_value(row.get("legal_entity_state_normalized"))
        if funding_fiscal_year is None or state is None:
            continue
        key = (
            int(funding_fiscal_year),
            state,
            _normalize_key_token(row.get("opdiv")),
            _normalize_key_token(row.get("can_code")),
            _normalize_key_token(row.get("program_office")),
            _normalize_key_token(row.get("aln")),
            bool(row.get("is_domestic_scope")),
        )
        accumulator = accumulators.get(key)
        if accumulator is None:
            accumulator = StateSummaryAccumulator(
                funding_fiscal_year=int(funding_fiscal_year),
                legal_entity_state_normalized=state,
                opdiv=_canonicalize_opdiv(row.get("opdiv")),
                can_code=row.get("can_code"),
                program_office=row.get("program_office"),
                aln=row.get("aln"),
                is_domestic_scope=bool(row.get("is_domestic_scope")),
            )
            accumulators[key] = accumulator

        accumulator.total_sum_of_actions += row.get("total_sum_of_actions") or Decimal("0.00")
        if row.get("award_number"):
            accumulator.award_numbers.add(str(row["award_number"]))
        if row.get("legal_entity_name"):
            accumulator.recipient_names.add(str(row["legal_entity_name"]).strip())
        county = _normalize_key_token(row.get("legal_entity_county_normalized"))
        if county and county not in UNKNOWN_COUNTY_TOKENS:
            accumulator.counties.add(county)

    refreshed_at = datetime.now(timezone.utc)
    return [
        {
            "funding_fiscal_year": accumulator.funding_fiscal_year,
            "legal_entity_state_normalized": accumulator.legal_entity_state_normalized,
            "opdiv": accumulator.opdiv,
            "can_code": accumulator.can_code,
            "program_office": accumulator.program_office,
            "aln": accumulator.aln,
            "effective_program_name": None,
            "effective_category": None,
            "effective_subcategory": None,
            "effective_mapping_method": None,
            "funding_stream": None,
            "appropriation_type": None,
            "has_profile_assisted_mapping": False,
            "has_fallback_inference": False,
            "can_mapping_version": None,
            "total_sum_of_actions": accumulator.total_sum_of_actions.quantize(Decimal("0.01")),
            "award_count": len(accumulator.award_numbers),
            "unique_recipient_count": len(accumulator.recipient_names),
            "unique_county_count": len(accumulator.counties),
            "is_domestic_scope": accumulator.is_domestic_scope,
            "refreshed_at": refreshed_at,
        }
        for accumulator in accumulators.values()
    ]


def _register_dominant_value(
    accumulator: CanDominanceAccumulator,
    value: str | None,
    amount: Decimal,
) -> None:
    if value is None:
        return
    accumulator.counts[value] += 1
    accumulator.funding[value] += amount


def _accumulate_can_classification(
    accumulators: dict[str, CanClassificationAccumulator],
    record: dict[str, Any],
) -> None:
    can_code = _clean_text(record.get("can_code"))
    if can_code is None:
        return

    accumulator = accumulators.get(can_code)
    if accumulator is None:
        accumulator = CanClassificationAccumulator(can_code=can_code)
        accumulators[can_code] = accumulator

    funding_fiscal_year = record.get("funding_fiscal_year")
    if funding_fiscal_year is not None:
        funding_year = int(funding_fiscal_year)
        if accumulator.observed_first_fy is None or funding_year < accumulator.observed_first_fy:
            accumulator.observed_first_fy = funding_year
        if accumulator.observed_last_fy is None or funding_year > accumulator.observed_last_fy:
            accumulator.observed_last_fy = funding_year

    amount = record.get("sum_of_actions") or Decimal("0.00")
    accumulator.observed_row_count += 1
    accumulator.observed_total_funding += amount
    _register_dominant_value(accumulator.opdiv_values, _canonicalize_opdiv(record.get("opdiv")), amount)
    _register_dominant_value(
        accumulator.program_office_values,
        _clean_text(record.get("program_office")),
        amount,
    )
    _register_dominant_value(accumulator.aln_values, _clean_text(record.get("aln")), amount)
    _register_dominant_value(
        accumulator.assistance_listing_values,
        _clean_text(record.get("assistance_listing_title")),
        amount,
    )


def _choose_dominant_value(accumulator: CanDominanceAccumulator) -> str | None:
    if not accumulator.counts:
        return None
    return sorted(
        accumulator.counts,
        key=lambda value: (
            -accumulator.counts[value],
            -(accumulator.funding[value]),
            value,
        ),
    )[0]


def build_can_classification_rows(
    records: list[dict[str, Any]],
    *,
    preserved_rows: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    accumulators: dict[str, CanClassificationAccumulator] = {}
    for record in records:
        _accumulate_can_classification(accumulators, record)
    return _build_can_classification_rows_from_accumulators(
        accumulators,
        preserved_rows=preserved_rows,
    )


def _build_can_classification_rows_from_accumulators(
    accumulators: dict[str, CanClassificationAccumulator],
    *,
    preserved_rows: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    preserved_lookup = preserved_rows or {}
    rows: list[dict[str, Any]] = []
    refreshed_at = datetime.now(timezone.utc)
    for can_code in sorted(accumulators):
        accumulator = accumulators[can_code]
        preserved = preserved_lookup.get(can_code, {})
        rows.append(
            {
                "can_code": can_code,
                "funding_stream": preserved.get("funding_stream"),
                "appropriation_type": preserved.get("appropriation_type"),
                "category_override": preserved.get("category_override"),
                "subcategory_override": preserved.get("subcategory_override"),
                "notes": preserved.get("notes"),
                "is_covid_related": preserved.get("is_covid_related"),
                "is_arpa_related": preserved.get("is_arpa_related"),
                "is_supplemental": preserved.get("is_supplemental"),
                "is_regular_appropriation": preserved.get("is_regular_appropriation"),
                "observed_first_fy": accumulator.observed_first_fy,
                "observed_last_fy": accumulator.observed_last_fy,
                "observed_row_count": accumulator.observed_row_count,
                "observed_total_funding": accumulator.observed_total_funding.quantize(Decimal("0.01")),
                "dominant_opdiv": _choose_dominant_value(accumulator.opdiv_values),
                "dominant_program_office": _choose_dominant_value(accumulator.program_office_values),
                "dominant_aln": _choose_dominant_value(accumulator.aln_values),
                "dominant_assistance_listing_title": _choose_dominant_value(
                    accumulator.assistance_listing_values
                ),
                "profile_inferred_program_name": preserved.get("profile_inferred_program_name"),
                "profile_inferred_category": preserved.get("profile_inferred_category"),
                "profile_inferred_subcategory": preserved.get("profile_inferred_subcategory"),
                "profile_match_count": preserved.get("profile_match_count"),
                "profile_match_confidence": preserved.get("profile_match_confidence"),
                "profile_match_evidence_json": preserved.get("profile_match_evidence_json") or {},
                "fallback_inferred_program_name": preserved.get("fallback_inferred_program_name"),
                "fallback_inferred_category": preserved.get("fallback_inferred_category"),
                "fallback_inferred_subcategory": preserved.get("fallback_inferred_subcategory"),
                "fallback_guess_confidence": preserved.get("fallback_guess_confidence"),
                "fallback_guess_evidence_json": preserved.get("fallback_guess_evidence_json") or {},
                "manual_program_name": preserved.get("manual_program_name"),
                "manual_category": preserved.get("manual_category"),
                "manual_subcategory": preserved.get("manual_subcategory"),
                "manual_notes": preserved.get("manual_notes"),
                "is_manually_verified": bool(preserved.get("is_manually_verified", False)),
                "effective_program_name": preserved.get("effective_program_name"),
                "effective_category": preserved.get("effective_category"),
                "effective_subcategory": preserved.get("effective_subcategory"),
                "effective_mapping_method": preserved.get("effective_mapping_method"),
                "can_mapping_version": preserved.get("can_mapping_version"),
                "updated_at": refreshed_at,
            }
        )
    return rows


def _serialize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_json_safe(item) for item in value]
        if isinstance(value, set):
            return [_json_safe(item) for item in sorted(value)]
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return value

    return _json_safe(summary)


def _write_summary_file(summary_path: Path, summary: dict[str, Any]) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(_serialize_summary(summary), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    if size <= 0:
        return [items]
    return [items[index : index + size] for index in range(0, len(items), size)]


def _required_columns_by_table() -> dict[str, set[str]]:
    return {
        RAW_AWARDS_TABLE.name: set(RAW_AWARDS_TABLE.columns.keys()),
        AWARD_SUMMARY_TABLE.name: set(AWARD_SUMMARY_TABLE.columns.keys()),
        STATE_SUMMARY_TABLE.name: set(STATE_SUMMARY_TABLE.columns.keys()),
        CAN_CLASSIFICATION_TABLE.name: set(CAN_CLASSIFICATION_TABLE.columns.keys()),
        INGESTION_RUNS_TABLE.name: set(INGESTION_RUNS_TABLE.columns.keys()),
    }


def _ensure_schema_tables(connection: Any) -> None:
    for table_name, required_columns in _required_columns_by_table().items():
        row = connection.execute(
            text("SELECT to_regclass(:table_name) AS exists"),
            {"table_name": f"{TAGGS_SCHEMA}.{table_name}"},
        ).mappings().one()
        if row["exists"] is None:
            raise RuntimeError(
                f"Required table {TAGGS_SCHEMA}.{table_name} is missing. "
                "Run migrations or use --drop-and-recreate."
            )
        existing_columns = {
            item["column_name"]
            for item in connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = :schema_name
                      AND table_name = :table_name
                    """
                ),
                {
                    "schema_name": TAGGS_SCHEMA,
                    "table_name": table_name,
                },
            ).mappings()
        }
        missing_columns = sorted(required_columns - existing_columns)
        if missing_columns:
            raise RuntimeError(
                f"Table {TAGGS_SCHEMA}.{table_name} is missing columns {missing_columns}. "
                "Run migrations or use --drop-and-recreate."
            )


def _recreate_taggs_schema_objects(connection: Any) -> None:
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TAGGS_SCHEMA}"))
    drop_names = CURRENT_TAGGS_TABLE_NAMES + LEGACY_TAGGS_TABLE_NAMES
    for table_name in drop_names:
        connection.execute(text(f"DROP TABLE IF EXISTS {TAGGS_SCHEMA}.{table_name} CASCADE"))
    for table in CURRENT_TAGGS_TABLES:
        table.create(bind=connection)


def _truncate_rebuild_tables(connection: Any) -> None:
    connection.execute(
        text(
            f"""
            TRUNCATE TABLE
                {TAGGS_SCHEMA}.state_funding_summary,
                {TAGGS_SCHEMA}.award_funding_summary,
                {TAGGS_SCHEMA}.raw_awards
            RESTART IDENTITY
            """
        )
    )


def _insert_rows(connection: Any, table: Any, rows: list[dict[str, Any]], *, chunk_size: int) -> int:
    if not rows:
        return 0
    inserted = 0
    for chunk in _chunks(rows, chunk_size):
        connection.execute(table.insert(), chunk)
        inserted += len(chunk)
    return inserted


def _insert_ingestion_run(connection: Any, payload: dict[str, Any]) -> int:
    return int(
        connection.execute(
            INGESTION_RUNS_TABLE.insert().returning(INGESTION_RUNS_TABLE.c.id),
            payload,
        ).scalar_one()
    )


def _update_ingestion_run(
    connection: Any,
    run_id: int,
    *,
    status: str,
    summary: dict[str, Any],
    files_processed: int,
    raw_main_rows_parsed: int,
    description_rows_paired: int,
    orphan_description_rows: int,
    raw_rows_loaded: int,
    award_summary_rows_loaded: int,
    state_summary_rows_loaded: int,
    distinct_can_codes: int,
    error_message: str | None = None,
) -> None:
    connection.execute(
        INGESTION_RUNS_TABLE.update()
        .where(INGESTION_RUNS_TABLE.c.id == run_id)
        .values(
            finished_at=datetime.now(timezone.utc),
            status=status,
            files_processed=files_processed,
            raw_main_rows_parsed=raw_main_rows_parsed,
            description_rows_paired=description_rows_paired,
            orphan_description_rows=orphan_description_rows,
            raw_rows_loaded=raw_rows_loaded,
            award_summary_rows_loaded=award_summary_rows_loaded,
            state_summary_rows_loaded=state_summary_rows_loaded,
            distinct_can_codes=distinct_can_codes,
            summary_json=_serialize_summary(summary),
            error_message=error_message,
        )
    )


def _fetch_existing_can_preserved_rows(connection: Any) -> dict[str, dict[str, Any]]:
    row = connection.execute(
        text("SELECT to_regclass(:table_name) AS exists"),
        {"table_name": f"{TAGGS_SCHEMA}.can_classification"},
    ).mappings().one()
    if row["exists"] is None:
        return {}
    rows = connection.execute(
        text(f"SELECT * FROM {TAGGS_SCHEMA}.can_classification")
    ).mappings()
    return {
        str(item["can_code"]): dict(item)
        for item in rows
        if item.get("can_code") is not None
    }


def ingest(
    *,
    db_url: str,
    input_dir: Path,
    summary_path: Path,
    chunk_size: int,
    truncate: bool,
    drop_and_recreate: bool,
    dry_run: bool,
    verbose: bool,
    limit_files: int | None,
    rebuild_summaries: bool,
    rebuild_can_table: bool,
) -> dict[str, Any]:
    started_at = time.time()
    files = discover_input_files(input_dir, limit_files=limit_files)
    structures = [inspect_file_structure(path) for path in files]
    header_validation = collect_header_validation(structures)

    summary_base: dict[str, Any] = {
        "status": "success",
        "input_dir": str(input_dir),
        "summary_path": str(summary_path),
        "dry_run": bool(dry_run),
        "truncate": bool(truncate),
        "drop_and_recreate": bool(drop_and_recreate),
        "rebuild_summaries": bool(rebuild_summaries),
        "rebuild_can_table": bool(rebuild_can_table),
        "files_found": [path.name for path in files],
        "files_processed": 0,
        "header_validation": header_validation,
        "header_discrepancies": header_validation["file_diffs"],
        "files": [],
    }
    if drop_and_recreate:
        summary_base["schema_reset_notice"] = SCHEMA_RESET_NOTICE

    if not header_validation["is_reconcilable"]:
        summary_base["status"] = "failed_header_validation"
        _write_summary_file(summary_path, summary_base)
        raise RuntimeError(
            "TAGGS CSV header validation failed. "
            f"See {summary_path} for discrepancy details."
        )

    totals_main_rows = 0
    totals_description_rows = 0
    totals_orphan_rows = 0
    totals_blank_rows = 0
    totals_loaded_raw_rows = 0
    non_us_row_count = 0
    null_or_undefined_county_rows = 0

    states_or_territories_discovered: set[str] = set()
    opdivs_discovered: set[str] = set()
    funding_years_found: set[int] = set()
    metadata_funding_years_found: set[int] = set()
    issue_fiscal_years_found: set[int] = set()
    distinct_award_numbers: set[str] = set()
    distinct_can_codes: set[str] = set()
    total_funding_by_fiscal_year: defaultdict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    total_funding_by_state: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    total_funding_by_opdiv: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    file_level_anomalies: list[dict[str, Any]] = []
    award_summary_accumulators: dict[tuple[Any, ...], AwardSummaryAccumulator] = {}
    can_classification_accumulators: dict[str, CanClassificationAccumulator] = {}

    engine = None
    run_id: int | None = None
    inserted_award_summary_rows = 0
    inserted_state_summary_rows = 0
    inserted_can_rows = 0
    preserved_can_rows: dict[str, dict[str, Any]] = {}
    example_raw_row: dict[str, Any] | None = None

    if not dry_run:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.begin() as connection:
            preserved_can_rows = _fetch_existing_can_preserved_rows(connection)
            if drop_and_recreate:
                _recreate_taggs_schema_objects(connection)
            else:
                _ensure_schema_tables(connection)
            if truncate:
                _truncate_rebuild_tables(connection)
            run_id = _insert_ingestion_run(
                connection,
                {
                    "input_dir": str(input_dir),
                    "summary_path": str(summary_path),
                    "dry_run": False,
                    "truncate_requested": bool(truncate),
                    "drop_and_recreate": bool(drop_and_recreate),
                    "rebuild_summaries": bool(rebuild_summaries),
                    "rebuild_can_table": bool(rebuild_can_table),
                    "files_discovered": len(files),
                },
            )

    try:
        for structure in structures:
            banner_metadata = structure.banner_metadata
            metadata_funding_years_found.update(
                int(value)
                for value in banner_metadata.get("listed_fiscal_years", [])
                if value is not None
            )
            states_or_territories_discovered.update(
                str(value).strip().upper()
                for value in banner_metadata.get("states", [])
                if str(value).strip()
            )
            if structure.source_state_hint:
                states_or_territories_discovered.add(str(structure.source_state_hint).upper())
            if structure.source_opdiv_hint:
                opdivs_discovered.add(str(structure.source_opdiv_hint))

            records, stats, parse_encoding = parse_taggs_csv_file(
                structure.path,
                inspection=structure,
            )

            totals_main_rows += stats.main_award_rows
            totals_description_rows += stats.description_rows_paired
            totals_orphan_rows += stats.orphan_description_rows
            totals_blank_rows += stats.blank_rows
            totals_loaded_raw_rows += len(records)

            funding_years_found.update(stats.funding_fiscal_years)
            issue_fiscal_years_found.update(stats.issue_fiscal_years)
            distinct_can_codes.update(stats.can_codes)

            for record in records:
                if example_raw_row is None:
                    example_raw_row = dict(record)
                opdiv = _canonicalize_opdiv(record.get("opdiv")) or structure.source_opdiv_hint
                if opdiv:
                    opdivs_discovered.add(opdiv)
                    total_funding_by_opdiv[opdiv] += record.get("sum_of_actions") or Decimal("0.00")
                if record.get("award_number"):
                    distinct_award_numbers.add(str(record["award_number"]))
                if record.get("funding_fiscal_year") is not None and record.get("sum_of_actions") is not None:
                    total_funding_by_fiscal_year[int(record["funding_fiscal_year"])] += (
                        record["sum_of_actions"] or Decimal("0.00")
                    )
                state_key = record.get("legal_entity_state_normalized") or "UNSPECIFIED"
                total_funding_by_state[state_key] += record.get("sum_of_actions") or Decimal("0.00")
                if _is_non_us_row(record):
                    non_us_row_count += 1
                if _is_undefined_county(record.get("legal_entity_county_normalized")):
                    null_or_undefined_county_rows += 1
                _accumulate_award_summary(award_summary_accumulators, record)
                _accumulate_can_classification(can_classification_accumulators, record)

            if engine is not None:
                with engine.begin() as connection:
                    _insert_rows(
                        connection,
                        RAW_AWARDS_TABLE,
                        records,
                        chunk_size=chunk_size,
                    )

            file_summary = {
                "filename": structure.path.name,
                "encoding": parse_encoding,
                "header_row_index": structure.header_row_index,
                "source_opdiv_hint": structure.source_opdiv_hint,
                "state_or_scope_hint": structure.source_state_hint,
                "is_territory_file": structure.source_is_territory_file,
                "metadata_fiscal_years": sorted(
                    int(value)
                    for value in banner_metadata.get("listed_fiscal_years", [])
                    if value is not None
                ),
                "metadata_states": list(banner_metadata.get("states", [])),
                "data_funding_fiscal_years": sorted(int(value) for value in stats.funding_fiscal_years),
                "data_issue_fiscal_years": sorted(int(value) for value in stats.issue_fiscal_years),
                "header": {
                    "actual": structure.normalized_header,
                    "canonical": structure.canonical_header,
                    "missing_required_headers": structure.missing_required_headers,
                    "unknown_headers": structure.unknown_headers,
                    "duplicate_header_targets": structure.duplicate_header_targets,
                },
                "row_counts": {
                    "csv_rows": stats.total_csv_rows,
                    "main_award_rows": stats.main_award_rows,
                    "description_rows_paired": stats.description_rows_paired,
                    "orphan_description_rows": stats.orphan_description_rows,
                    "repeated_description_rows": stats.repeated_description_rows,
                    "blank_rows": stats.blank_rows,
                    "footer_rows": stats.footer_rows,
                    "single_column_non_description_rows": stats.skipped_singleton_rows,
                },
                "warnings": banner_metadata.get("warnings", []),
                "anomalies": stats.anomalies,
            }
            summary_base["files"].append(file_summary)
            summary_base["files_processed"] += 1
            if stats.anomalies or banner_metadata.get("warnings"):
                file_level_anomalies.append(
                    {
                        "filename": structure.path.name,
                        "warnings": banner_metadata.get("warnings", []),
                        "anomalies": stats.anomalies,
                    }
                )

            if verbose:
                print(
                    "[file]",
                    structure.path.name,
                    f"encoding={parse_encoding}",
                    f"opdiv_hint={structure.source_opdiv_hint}",
                    f"state_hint={structure.source_state_hint}",
                    f"main={stats.main_award_rows}",
                    f"desc={stats.description_rows_paired}",
                    f"orphans={stats.orphan_description_rows}",
                )

        award_summary_rows = [
            {
                **accumulator.row,
                "total_sum_of_actions": accumulator.total_sum_of_actions.quantize(Decimal("0.01")),
                "raw_row_count": accumulator.raw_row_count,
                "is_domestic_scope": accumulator.is_domestic_scope,
                "refreshed_at": datetime.now(timezone.utc),
            }
            for accumulator in award_summary_accumulators.values()
        ]
        state_summary_rows = build_state_funding_summary_rows(award_summary_rows)
        can_classification_rows = _build_can_classification_rows_from_accumulators(
            can_classification_accumulators,
            preserved_rows=preserved_can_rows,
        )

        if engine is not None:
            with engine.begin() as connection:
                if rebuild_summaries:
                    connection.execute(
                        text(
                            f"""
                            TRUNCATE TABLE
                                {TAGGS_SCHEMA}.state_funding_summary,
                                {TAGGS_SCHEMA}.award_funding_summary
                            RESTART IDENTITY
                            """
                        )
                    )
                    inserted_award_summary_rows = _insert_rows(
                        connection,
                        AWARD_SUMMARY_TABLE,
                        award_summary_rows,
                        chunk_size=chunk_size,
                    )
                    inserted_state_summary_rows = _insert_rows(
                        connection,
                        STATE_SUMMARY_TABLE,
                        state_summary_rows,
                        chunk_size=chunk_size,
                    )
                if rebuild_can_table:
                    connection.execute(text(f"TRUNCATE TABLE {TAGGS_SCHEMA}.can_classification"))
                    inserted_can_rows = _insert_rows(
                        connection,
                        CAN_CLASSIFICATION_TABLE,
                        can_classification_rows,
                        chunk_size=chunk_size,
                    )

        min_funding_fiscal_year = min(funding_years_found) if funding_years_found else None
        max_funding_fiscal_year = max(funding_years_found) if funding_years_found else None
        elapsed_seconds = round(time.time() - started_at, 2)

        summary = {
            **summary_base,
            "elapsed_seconds": elapsed_seconds,
            "states_and_territories_discovered": sorted(states_or_territories_discovered),
            "opdivs_discovered": sorted(opdivs_discovered),
            "metadata_fiscal_years_found": sorted(metadata_funding_years_found),
            "funding_fiscal_years_found": sorted(funding_years_found),
            "issue_fiscal_years_found": sorted(issue_fiscal_years_found),
            "min_funding_fiscal_year": min_funding_fiscal_year,
            "max_funding_fiscal_year": max_funding_fiscal_year,
            "total_raw_main_rows_parsed": totals_main_rows,
            "total_description_rows_paired": totals_description_rows,
            "orphan_description_rows": totals_orphan_rows,
            "blank_rows_seen": totals_blank_rows,
            "total_rows_loaded_raw_awards": totals_loaded_raw_rows,
            "total_award_funding_summary_rows": len(award_summary_rows),
            "total_state_funding_summary_rows": len(state_summary_rows),
            "total_can_classification_rows": len(can_classification_rows),
            "total_distinct_award_numbers": len(distinct_award_numbers),
            "total_distinct_can_codes": len(distinct_can_codes),
            "total_funding_by_fiscal_year": {
                str(key): str(value.quantize(Decimal("0.01")))
                for key, value in sorted(total_funding_by_fiscal_year.items())
            },
            "total_funding_by_opdiv": {
                str(key): str(value.quantize(Decimal("0.01")))
                for key, value in sorted(total_funding_by_opdiv.items())
            },
            "total_funding_by_state": {
                str(key): str(value.quantize(Decimal("0.01")))
                for key, value in sorted(total_funding_by_state.items())
            },
            "count_non_us_rows": non_us_row_count,
            "count_null_or_undefined_county_rows": null_or_undefined_county_rows,
            "file_level_anomalies": file_level_anomalies,
            "example_raw_award_row": example_raw_row,
            "example_award_funding_summary_row": award_summary_rows[0] if award_summary_rows else None,
            "example_can_classification_row": can_classification_rows[0] if can_classification_rows else None,
            "database_rows_written": {
                "raw_awards": totals_loaded_raw_rows if not dry_run else 0,
                "award_funding_summary": inserted_award_summary_rows if rebuild_summaries else 0,
                "state_funding_summary": inserted_state_summary_rows if rebuild_summaries else 0,
                "can_classification": inserted_can_rows if rebuild_can_table else 0,
            },
        }

        _write_summary_file(summary_path, summary)

        if engine is not None and run_id is not None:
            with engine.begin() as connection:
                _update_ingestion_run(
                    connection,
                    run_id,
                    status="success",
                    summary=summary,
                    files_processed=summary_base["files_processed"],
                    raw_main_rows_parsed=totals_main_rows,
                    description_rows_paired=totals_description_rows,
                    orphan_description_rows=totals_orphan_rows,
                    raw_rows_loaded=totals_loaded_raw_rows,
                    award_summary_rows_loaded=inserted_award_summary_rows if rebuild_summaries else 0,
                    state_summary_rows_loaded=inserted_state_summary_rows if rebuild_summaries else 0,
                    distinct_can_codes=len(distinct_can_codes),
                )
        if engine is not None:
            engine.dispose()
        return summary
    except Exception as exc:
        failure_summary = {
            **summary_base,
            "status": "failed",
            "error": str(exc),
            "files_processed": summary_base["files_processed"],
        }
        _write_summary_file(summary_path, failure_summary)
        if engine is not None and run_id is not None:
            with engine.begin() as connection:
                _update_ingestion_run(
                    connection,
                    run_id,
                    status="failed",
                    summary=failure_summary,
                    files_processed=summary_base["files_processed"],
                    raw_main_rows_parsed=totals_main_rows,
                    description_rows_paired=totals_description_rows,
                    orphan_description_rows=totals_orphan_rows,
                    raw_rows_loaded=totals_loaded_raw_rows,
                    award_summary_rows_loaded=inserted_award_summary_rows,
                    state_summary_rows_loaded=inserted_state_summary_rows,
                    distinct_can_codes=len(distinct_can_codes),
                    error_message=str(exc),
                )
        if engine is not None:
            engine.dispose()
        raise


def _print_summary(summary: dict[str, Any]) -> None:
    print("[done] TAGGS redo ingestion summary")
    if summary.get("schema_reset_notice"):
        print(f"  schema_reset_notice={summary.get('schema_reset_notice')}")
    print(f"  files_processed={summary.get('files_processed')}")
    print(f"  total_raw_main_rows_parsed={summary.get('total_raw_main_rows_parsed')}")
    print(f"  total_description_rows_paired={summary.get('total_description_rows_paired')}")
    print(f"  orphan_description_rows={summary.get('orphan_description_rows')}")
    print(f"  total_rows_loaded_raw_awards={summary.get('total_rows_loaded_raw_awards')}")
    print(f"  total_award_funding_summary_rows={summary.get('total_award_funding_summary_rows')}")
    print(f"  total_state_funding_summary_rows={summary.get('total_state_funding_summary_rows')}")
    print(f"  total_can_classification_rows={summary.get('total_can_classification_rows')}")
    print(f"  total_distinct_award_numbers={summary.get('total_distinct_award_numbers')}")
    print(f"  total_distinct_can_codes={summary.get('total_distinct_can_codes')}")
    print(
        f"  funding_fiscal_year_range={summary.get('min_funding_fiscal_year')}"
        f"..{summary.get('max_funding_fiscal_year')}"
    )
    print(f"  count_non_us_rows={summary.get('count_non_us_rows')}")
    print(
        "  count_null_or_undefined_county_rows="
        f"{summary.get('count_null_or_undefined_county_rows')}"
    )
    print(f"  header_discrepancies={len(summary.get('header_discrepancies') or [])}")
    print(f"  summary_json={summary.get('summary_path')}")


def main() -> None:
    args = parse_args()
    input_dir = _resolve_input_dir(args.input_dir)
    summary_path = _resolve_summary_path(input_dir, args.summary_path)

    print(f"[run] input_dir={input_dir}")
    print(f"[run] summary_path={summary_path}")
    print(
        "[run] "
        f"dry_run={bool(args.dry_run)} "
        f"truncate={bool(args.truncate)} "
        f"drop_and_recreate={bool(args.drop_and_recreate)} "
        f"rebuild_summaries={bool(args.rebuild_summaries)} "
        f"rebuild_can_table={bool(args.rebuild_can_table)}"
    )
    if args.verbose and args.drop_and_recreate:
        print(f"[warn] {SCHEMA_RESET_NOTICE}")

    summary = ingest(
        db_url=args.db_url,
        input_dir=input_dir,
        summary_path=summary_path,
        chunk_size=args.chunksize,
        truncate=bool(args.truncate),
        drop_and_recreate=bool(args.drop_and_recreate),
        dry_run=bool(args.dry_run),
        verbose=bool(args.verbose),
        limit_files=args.limit_files,
        rebuild_summaries=bool(args.rebuild_summaries),
        rebuild_can_table=bool(args.rebuild_can_table),
    )
    _print_summary(summary)


__all__ = [
    "DEFAULT_DB_URL",
    "DEFAULT_CHUNKSIZE",
    "DEFAULT_SUMMARY_FILENAME",
    "EXPECTED_BASE_HEADER",
    "EXPECTED_ALT_HEADER",
    "DOMESTIC_SCOPE_CODES",
    "FileStructureInfo",
    "INTERNATIONAL_KEYWORD_RE",
    "ParseStats",
    "SCHEMA_RESET_NOTICE",
    "SEED_HEADER_ALIASES",
    "UNKNOWN_COUNTY_TOKENS",
    "US_COUNTRY_TOKENS",
    "discover_input_files",
    "parse_metadata_banner",
    "infer_source_scope",
    "inspect_file_structure",
    "collect_header_discrepancies",
    "collect_header_validation",
    "parse_taggs_csv_file",
    "build_award_funding_summary_rows",
    "build_state_funding_summary_rows",
    "build_can_classification_rows",
    "_parse_amount",
    "_parse_budget_year",
    "_parse_date",
    "_parse_fiscal_year",
    "_parse_int",
    "_normalize_state_value",
    "ingest",
    "main",
]
