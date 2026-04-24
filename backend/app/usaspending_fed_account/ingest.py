from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from app.db_fqtn import usaspending_fed_account_table
from app.db_schemas import USASPENDING_FED_ACCOUNT_SCHEMA
from app.usaspending_fed_account.models import (
    FedAccountBalance,
    FedAccountDimension,
    FedAccountPaOc,
    FedAccountRawFileRegistry,
    FedAwardAccountBreakdown,
)

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_CHUNKSIZE = 2000
DEFAULT_DATA_DIR = (
    Path(__file__).resolve().parents[3] / "data" / "usaspending" / "fed_account_data"
).resolve()
DEFAULT_OUTPUT_PATH = (
    DEFAULT_DATA_DIR / "outputs" / "federal_account_reconciliation_fy2020_2026.csv"
)
SUPPORTED_YEARS = tuple(range(2020, 2027))
ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

DATASET_ASSISTANCE = "assistance_award_breakdown"
DATASET_CONTRACTS = "contracts_award_breakdown"
DATASET_UNLINKED = "unlinked_award_breakdown"
DATASET_BALANCES = "account_balances"
DATASET_PA_OC = "pa_oc_breakdown"
DATASET_UNKNOWN = "unknown"

AWARD_SOURCE_BY_DATASET = {
    DATASET_ASSISTANCE: "assistance",
    DATASET_CONTRACTS: "contracts",
    DATASET_UNLINKED: "unlinked",
}

BALANCE_TABLE = FedAccountBalance.__table__
DIM_ACCOUNT_TABLE = FedAccountDimension.__table__
PA_OC_TABLE = FedAccountPaOc.__table__
RAW_FILE_TABLE = FedAccountRawFileRegistry.__table__
AWARD_TABLE = FedAwardAccountBreakdown.__table__

RECONCILIATION_COLUMNS = [
    "fiscal_year",
    "federal_account_id",
    "normalized_account_key",
    "federal_account_name",
    "balance_obligations",
    "award_obligations_total",
    "assistance_award_obligations",
    "contracts_award_obligations",
    "unlinked_award_obligations",
    "pa_oc_obligations_total",
    "balance_minus_awards",
    "balance_minus_pa_oc",
    "award_match_percent_of_balance",
    "pa_oc_match_percent_of_balance",
    "record_count_awards",
    "record_count_pa_oc",
]

NULL_TOKENS = {
    "",
    "na",
    "n/a",
    "none",
    "null",
    "nan",
    "not available",
    "not provided",
}

AMOUNT_KEY_RE = re.compile(
    r"(amount|balance|budgetary|authority|obligation|obligations|obligated|outlay|"
    r"resources|ussgl|unobligated|deobligation|recoveries|refunds)",
    re.IGNORECASE,
)

STATE_NAME_TO_CODE = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "HAWAII": "HI",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "IOWA": "IA",
    "KANSAS": "KS",
    "KENTUCKY": "KY",
    "LOUISIANA": "LA",
    "MAINE": "ME",
    "MARYLAND": "MD",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "MINNESOTA": "MN",
    "MISSISSIPPI": "MS",
    "MISSOURI": "MO",
    "MONTANA": "MT",
    "NEBRASKA": "NE",
    "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND",
    "OHIO": "OH",
    "OKLAHOMA": "OK",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "VERMONT": "VT",
    "VIRGINIA": "VA",
    "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI",
    "WYOMING": "WY",
    "PUERTO RICO": "PR",
    "GUAM": "GU",
    "AMERICAN SAMOA": "AS",
    "NORTHERN MARIANA ISLANDS": "MP",
    "U.S. VIRGIN ISLANDS": "VI",
    "VIRGIN ISLANDS": "VI",
    "UNITED STATES": "US",
}
STATE_CODES = set(STATE_NAME_TO_CODE.values())

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredFedAccountFile:
    path: Path
    fiscal_year: int
    dataset_type: str
    source_agency_code: str | None
    period_label: str | None
    downloaded_at_from_filename: datetime | None


@dataclass
class FileParseStats:
    rows_seen: int = 0
    rows_loaded: int = 0
    rows_skipped: int = 0
    missing_expected_columns: set[str] = field(default_factory=set)
    bad_date_counts: Counter[str] = field(default_factory=Counter)
    bad_amount_counts: Counter[str] = field(default_factory=Counter)
    missing_account_identity_rows: int = 0


@dataclass
class IngestionRunSummary:
    dry_run: bool
    files_discovered: int = 0
    files_skipped_existing: int = 0
    files_ingested_by_type: Counter[str] = field(default_factory=Counter)
    rows_by_table_or_type: Counter[str] = field(default_factory=Counter)
    rows_by_fiscal_year: Counter[int] = field(default_factory=Counter)
    missing_columns_by_file: dict[str, list[str]] = field(default_factory=dict)
    bad_dates_by_field: Counter[str] = field(default_factory=Counter)
    bad_amounts_by_field: Counter[str] = field(default_factory=Counter)
    missing_account_identity_rows: int = 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest USAspending federal account balance, PA/OC, assistance, contract, "
            f"and unlinked account CSVs into schema {USASPENDING_FED_ACCOUNT_SCHEMA}."
        )
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or local development DSN).",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Directory containing federal account CSV files (default: {DEFAULT_DATA_DIR}).",
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="*",
        default=list(SUPPORTED_YEARS),
        help="Fiscal years to ingest or validate (default: 2020 2021 2022 2023 2024 2025 2026).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reingest files even when the file hash or path already exists in the registry.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and parse files without opening a database connection or writing rows.",
    )
    parser.add_argument(
        "--limit-rows",
        type=int,
        default=None,
        help="Optional per-file data row cap for testing.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"Database insert batch size (default: {DEFAULT_CHUNKSIZE}).",
    )
    parser.add_argument(
        "--rebuild-reconciliation",
        action="store_true",
        help="Write the account-level reconciliation CSV report after loading.",
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"Reconciliation CSV path (default: {DEFAULT_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity.",
    )
    return parser.parse_args(argv)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).replace("\ufeff", "")
    token = re.sub(r"\s+", " ", token).strip()
    if token.lower() in NULL_TOKENS:
        return None
    return token or None


def normalize_header(value: Any) -> str:
    token = clean_text(value) or ""
    token = token.lower()
    token = re.sub(r"[^a-z0-9]+", "_", token)
    token = re.sub(r"_+", "_", token)
    return token.strip("_")


def normalize_key_token(value: Any) -> str | None:
    token = clean_text(value)
    if token is None:
        return None
    token = token.upper()
    token = re.sub(r"\s+", "", token)
    return token or None


def normalize_slug(value: Any) -> str | None:
    token = clean_text(value)
    if token is None:
        return None
    token = re.sub(r"[^a-z0-9]+", "_", token.lower())
    token = re.sub(r"_+", "_", token).strip("_")
    return token or None


def parse_amount(value: Any) -> Decimal | None:
    token = clean_text(value)
    if token is None:
        return None
    compact = token.replace("$", "").replace(",", "").replace(" ", "").replace("−", "-")
    negative = False
    if compact.startswith("(") and compact.endswith(")"):
        compact = compact[1:-1]
        negative = True
    if compact in {"", "-", "+", "."}:
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


def parse_date(value: Any) -> date | None:
    token = clean_text(value)
    if token is None:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def normalize_state_code(value: Any) -> str | None:
    token = clean_text(value)
    if token is None:
        return None
    compact = re.sub(r"[^A-Za-z]", "", token).upper()
    if len(compact) == 2 and compact in STATE_CODES:
        return compact
    return STATE_NAME_TO_CODE.get(token.upper())


def _get_value(row: Mapping[str, Any], *aliases: str) -> Any:
    for alias in aliases:
        normalized = normalize_header(alias)
        if normalized in row:
            return row[normalized]
    return None


def _get_text(row: Mapping[str, Any], *aliases: str) -> str | None:
    return clean_text(_get_value(row, *aliases))


def _get_amount(
    row: Mapping[str, Any],
    stats: FileParseStats,
    field_name: str,
    *aliases: str,
) -> Decimal | None:
    value = _get_value(row, *aliases)
    parsed = parse_amount(value)
    if parsed is None and clean_text(value) is not None:
        stats.bad_amount_counts[field_name] += 1
    return parsed


def _get_date(
    row: Mapping[str, Any],
    stats: FileParseStats,
    field_name: str,
    *aliases: str,
) -> date | None:
    value = _get_value(row, *aliases)
    parsed = parse_date(value)
    if parsed is None and clean_text(value) is not None:
        stats.bad_date_counts[field_name] += 1
    return parsed


def infer_dataset_type(file_name: str) -> str:
    lower = file_name.lower()
    if "assistance_accountbreakdownbyaward" in lower:
        return DATASET_ASSISTANCE
    if "contracts_accountbreakdownbyaward" in lower:
        return DATASET_CONTRACTS
    if "unlinked_accountbreakdownbyaward" in lower:
        return DATASET_UNLINKED
    if "accountbreakdownbypa-oc" in lower:
        return DATASET_PA_OC
    if "accountbalances" in lower:
        return DATASET_BALANCES
    return DATASET_UNKNOWN


def infer_fiscal_year(file_name: str) -> int | None:
    match = re.search(r"(?i)FY(20\d{2})", file_name)
    if not match:
        return None
    return int(match.group(1))


def infer_source_agency_code(file_name: str) -> str | None:
    match = re.search(r"_(\d{3,4})_FA_", file_name)
    return match.group(1) if match else None


def infer_period_label(file_name: str) -> str | None:
    match = re.match(r"(?i)(FY20\d{2}[^_]*)_", file_name)
    return match.group(1) if match else None


def infer_downloaded_at(file_name: str) -> datetime | None:
    match = re.search(r"_(\d{4}-\d{2}-\d{2})_H(\d{2})M(\d{2})S(\d{2})", file_name)
    if not match:
        return None
    value = f"{match.group(1)} {match.group(2)}:{match.group(3)}:{match.group(4)}"
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def discover_fed_account_files(
    data_dir: Path,
    *,
    years: Iterable[int] | None = None,
) -> list[DiscoveredFedAccountFile]:
    selected_years = set(years or SUPPORTED_YEARS)
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory does not exist: {data_dir}")
    if not data_dir.is_dir():
        raise RuntimeError(f"Data path is not a directory: {data_dir}")

    discovered: list[DiscoveredFedAccountFile] = []
    for path in sorted(data_dir.rglob("*.csv")):
        if "outputs" in path.relative_to(data_dir).parts:
            continue
        fiscal_year = infer_fiscal_year(path.name)
        if fiscal_year is None:
            continue
        if fiscal_year not in selected_years:
            continue
        discovered.append(
            DiscoveredFedAccountFile(
                path=path.resolve(),
                fiscal_year=fiscal_year,
                dataset_type=infer_dataset_type(path.name),
                source_agency_code=infer_source_agency_code(path.name),
                period_label=infer_period_label(path.name),
                downloaded_at_from_filename=infer_downloaded_at(path.name),
            )
        )
    return discovered


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_encoding(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                handle.read(1024 * 1024)
            return encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Unable to decode CSV {path}: {last_error}")


def _coerce_row_width(row: list[str], expected_len: int) -> list[str]:
    if len(row) == expected_len:
        return row
    if len(row) < expected_len:
        return row + [""] * (expected_len - len(row))
    return row[:expected_len]


def _has_required_columns(
    normalized_header: set[str],
    expected: Iterable[str],
    stats: FileParseStats,
) -> None:
    for column in expected:
        normalized = normalize_header(column)
        if normalized not in normalized_header:
            stats.missing_expected_columns.add(normalized)


def _account_symbol_parts(symbol: str | None) -> tuple[str | None, str | None]:
    token = clean_text(symbol)
    if token is None:
        return None, None
    match = re.match(r"^(?P<agency>\d{3,4})-(?P<main>[A-Za-z0-9]{4})", token)
    if not match:
        return None, None
    return match.group("agency"), match.group("main")


def account_identity_from_row(
    row: Mapping[str, Any],
    *,
    source_agency_code: str | None = None,
) -> dict[str, str | None]:
    federal_account_symbol = _get_text(
        row,
        "federal_account_symbol",
        "federal_account_identifier",
        "federal_accounts_funding_this_award",
    )
    treasury_account_symbol = _get_text(
        row,
        "treasury_account_symbol",
        "treasury_account_identifier",
        "tas",
    )
    symbol_agency, symbol_main = _account_symbol_parts(federal_account_symbol)
    agency_identifier = _get_text(
        row,
        "agency_identifier",
        "agency_identifier_code",
        "agency_id",
        "agency_code",
    ) or symbol_agency or source_agency_code
    allocation_transfer_agency_identifier = _get_text(
        row,
        "allocation_transfer_agency_identifier",
        "allocation_transfer_agency",
        "ata",
    )
    main_account_code = _get_text(row, "main_account_code", "main_account") or symbol_main
    sub_account_code = _get_text(row, "sub_account_code", "sub_account")
    federal_account_name = _get_text(row, "federal_account_name")
    agency_name = _get_text(row, "agency_identifier_name", "owning_agency_name", "reporting_agency_name")
    bureau_name = _get_text(row, "bureau_name", "bureau_identifier_name", "reporting_agency_name")

    return {
        "agency_identifier": agency_identifier,
        "allocation_transfer_agency_identifier": allocation_transfer_agency_identifier,
        "main_account_code": main_account_code,
        "sub_account_code": sub_account_code,
        "treasury_account_symbol": treasury_account_symbol,
        "federal_account_symbol": federal_account_symbol,
        "federal_account_name": federal_account_name,
        "account_title": _get_text(row, "account_title", "federal_account_name"),
        "agency_name": agency_name,
        "bureau_name": bureau_name,
    }


def normalize_federal_account_key(
    row: Mapping[str, Any],
    *,
    source_agency_code: str | None = None,
) -> str | None:
    fields = account_identity_from_row(row, source_agency_code=source_agency_code)
    treasury_account_symbol = normalize_key_token(fields.get("treasury_account_symbol"))
    if treasury_account_symbol:
        return f"tas:{treasury_account_symbol}"

    federal_account_symbol = normalize_key_token(fields.get("federal_account_symbol"))
    if federal_account_symbol:
        return f"fa:{federal_account_symbol}"

    agency_identifier = normalize_key_token(fields.get("agency_identifier"))
    allocation_transfer_agency_identifier = normalize_key_token(
        fields.get("allocation_transfer_agency_identifier")
    )
    main_account_code = normalize_key_token(fields.get("main_account_code"))
    sub_account_code = normalize_key_token(fields.get("sub_account_code"))
    if agency_identifier and main_account_code:
        allocation = allocation_transfer_agency_identifier or "na"
        sub_account = sub_account_code or "na"
        return f"tas_parts:{agency_identifier}:{allocation}:{main_account_code}:{sub_account}"

    federal_account_name = normalize_slug(fields.get("federal_account_name"))
    fallback_agency = agency_identifier or normalize_key_token(source_agency_code)
    if fallback_agency and federal_account_name:
        return f"agency_name:{fallback_agency}:{federal_account_name}"
    return None


def _account_upsert_values(
    row: Mapping[str, Any],
    *,
    source_agency_code: str | None,
) -> dict[str, Any] | None:
    normalized_account_key = normalize_federal_account_key(row, source_agency_code=source_agency_code)
    if normalized_account_key is None:
        return None
    values = account_identity_from_row(row, source_agency_code=source_agency_code)
    values["normalized_account_key"] = normalized_account_key
    return values


def upsert_federal_account(
    conn: Connection,
    row: Mapping[str, Any],
    *,
    source_agency_code: str | None,
    account_cache: dict[str, int],
) -> int | None:
    values = _account_upsert_values(row, source_agency_code=source_agency_code)
    if values is None:
        return None
    normalized_key = str(values["normalized_account_key"])
    cached_id = account_cache.get(normalized_key)
    if cached_id is not None:
        return cached_id

    insert_stmt = pg_insert(DIM_ACCOUNT_TABLE).values(**values)
    update_fields = [
        "agency_identifier",
        "allocation_transfer_agency_identifier",
        "main_account_code",
        "sub_account_code",
        "treasury_account_symbol",
        "federal_account_symbol",
        "federal_account_name",
        "account_title",
        "agency_name",
        "bureau_name",
    ]
    excluded = insert_stmt.excluded
    set_values = {
        field_name: func.coalesce(getattr(excluded, field_name), getattr(DIM_ACCOUNT_TABLE.c, field_name))
        for field_name in update_fields
    }
    set_values["updated_at"] = text("now()")
    upsert_stmt = (
        insert_stmt.on_conflict_do_update(
            index_elements=[DIM_ACCOUNT_TABLE.c.normalized_account_key],
            set_=set_values,
        )
        .returning(DIM_ACCOUNT_TABLE.c.id)
    )
    account_id = conn.execute(upsert_stmt).scalar_one()
    account_cache[normalized_key] = int(account_id)
    return int(account_id)


def _raw_amount_json(
    row_by_key: Mapping[str, Any],
    original_key_by_normalized: Mapping[str, str],
    *,
    mapped_aliases: Iterable[str],
) -> dict[str, Any]:
    mapped = {normalize_header(alias) for alias in mapped_aliases}
    values: dict[str, Any] = {}
    for normalized_key, value in row_by_key.items():
        if normalized_key in mapped:
            continue
        if not AMOUNT_KEY_RE.search(normalized_key):
            continue
        cleaned = clean_text(value)
        if cleaned is None:
            continue
        values[original_key_by_normalized.get(normalized_key, normalized_key)] = cleaned
    return values


def _recipient_county_fips(row: Mapping[str, Any]) -> str | None:
    value = _get_text(row, "recipient_county_fips", "recipient_county_code")
    if value and re.fullmatch(r"\d{5}", value):
        return value
    return None


def _place_county_fips(row: Mapping[str, Any]) -> str | None:
    value = _get_text(
        row,
        "place_of_performance_county_fips",
        "primary_place_of_performance_county_fips",
        "primary_place_of_performance_county_code",
    )
    if value and re.fullmatch(r"\d{5}", value):
        return value
    return None


def build_balance_record(
    row_by_key: Mapping[str, Any],
    raw_row_json: dict[str, Any],
    original_key_by_normalized: Mapping[str, str],
    *,
    fiscal_year: int,
    raw_file_id: int,
    federal_account_id: int,
    stats: FileParseStats,
) -> dict[str, Any]:
    mapped_amount_aliases = [
        "budget_authority_appropriated_amount",
        "obligations_incurred",
        "gross_outlay_amount",
        "unobligated_balance",
        "total_budgetary_resources",
        "status_of_budgetary_resources_total",
    ]
    return {
        "fiscal_year": fiscal_year,
        "federal_account_id": federal_account_id,
        "raw_file_id": raw_file_id,
        "budget_authority_amount": _get_amount(
            row_by_key,
            stats,
            "budget_authority_amount",
            "budget_authority_amount",
            "budget_authority_appropriated_amount",
        ),
        "obligations_incurred_amount": _get_amount(
            row_by_key,
            stats,
            "obligations_incurred_amount",
            "obligations_incurred",
            "obligations_incurred_amount",
        ),
        "outlay_amount": _get_amount(
            row_by_key,
            stats,
            "outlay_amount",
            "outlay_amount",
            "gross_outlay_amount",
        ),
        "unobligated_balance_amount": _get_amount(
            row_by_key,
            stats,
            "unobligated_balance_amount",
            "unobligated_balance",
        ),
        "gross_outlay_amount": _get_amount(
            row_by_key,
            stats,
            "gross_outlay_amount",
            "gross_outlay_amount",
        ),
        "total_budgetary_resources_amount": _get_amount(
            row_by_key,
            stats,
            "total_budgetary_resources_amount",
            "total_budgetary_resources_amount",
            "total_budgetary_resources",
            "status_of_budgetary_resources_total",
        ),
        "other_amount_json": _raw_amount_json(
            row_by_key,
            original_key_by_normalized,
            mapped_aliases=mapped_amount_aliases,
        ),
        "raw_row_json": raw_row_json,
    }


def build_pa_oc_record(
    row_by_key: Mapping[str, Any],
    raw_row_json: dict[str, Any],
    original_key_by_normalized: Mapping[str, str],
    *,
    fiscal_year: int,
    raw_file_id: int,
    federal_account_id: int,
    stats: FileParseStats,
) -> dict[str, Any]:
    mapped_amount_aliases = [
        "obligations_incurred",
        "gross_outlay_amount_fyb_to_period_end",
        "gross_outlay_amount_fyb",
    ]
    return {
        "fiscal_year": fiscal_year,
        "federal_account_id": federal_account_id,
        "raw_file_id": raw_file_id,
        "program_activity_code": _get_text(row_by_key, "program_activity_code"),
        "program_activity_name": _get_text(row_by_key, "program_activity_name"),
        "object_class_code": _get_text(row_by_key, "object_class_code"),
        "object_class_name": _get_text(row_by_key, "object_class_name"),
        "direct_or_reimbursable": _get_text(
            row_by_key,
            "direct_or_reimbursable",
            "direct_or_reimbursable_funding_source",
        ),
        "obligations_incurred_amount": _get_amount(
            row_by_key,
            stats,
            "obligations_incurred_amount",
            "obligations_incurred",
            "obligations_incurred_amount",
        ),
        "outlay_amount": _get_amount(
            row_by_key,
            stats,
            "outlay_amount",
            "gross_outlay_amount_fyb_to_period_end",
            "gross_outlay_amount_fyb",
            "gross_outlay_amount",
            "outlay_amount",
        ),
        "raw_amount_json": _raw_amount_json(
            row_by_key,
            original_key_by_normalized,
            mapped_aliases=mapped_amount_aliases,
        ),
        "raw_row_json": raw_row_json,
    }


def build_award_record(
    row_by_key: Mapping[str, Any],
    raw_row_json: dict[str, Any],
    original_key_by_normalized: Mapping[str, str],
    *,
    fiscal_year: int,
    raw_file_id: int,
    federal_account_id: int | None,
    award_source_type: str,
    stats: FileParseStats,
) -> dict[str, Any]:
    transaction_amount = _get_amount(
        row_by_key,
        stats,
        "transaction_obligated_amount",
        "transaction_obligated_amount",
        "federal_action_obligation",
    )
    mapped_amount_aliases = [
        "transaction_obligated_amount",
        "federal_action_obligation",
        "gross_outlay_amount_fyb_to_period_end",
        "gross_outlay_amount_fyb",
    ]
    recipient_state = normalize_state_code(_get_value(row_by_key, "recipient_state"))
    place_state = normalize_state_code(
        _get_value(
            row_by_key,
            "place_of_performance_state_code",
            "primary_place_of_performance_state",
        )
    )
    return {
        "fiscal_year": fiscal_year,
        "federal_account_id": federal_account_id,
        "raw_file_id": raw_file_id,
        "award_source_type": award_source_type,
        "award_id": _get_text(row_by_key, "award_id", "award_unique_key"),
        "generated_unique_award_id": _get_text(
            row_by_key,
            "generated_unique_award_id",
            "award_unique_key",
        ),
        "piid": _get_text(row_by_key, "piid", "award_id_piid"),
        "fain": _get_text(row_by_key, "fain", "award_id_fain"),
        "uri": _get_text(row_by_key, "uri", "award_id_uri"),
        "assistance_listing_number": _get_text(
            row_by_key,
            "assistance_listing_number",
            "cfda_number",
            "aln",
        ),
        "recipient_name": _get_text(row_by_key, "recipient_name"),
        "recipient_uei": _get_text(row_by_key, "recipient_uei"),
        "recipient_state_code": recipient_state,
        "recipient_county_name": _get_text(row_by_key, "recipient_county"),
        "recipient_county_fips": _recipient_county_fips(row_by_key),
        "place_of_performance_state_code": place_state,
        "place_of_performance_county_name": _get_text(
            row_by_key,
            "place_of_performance_county",
            "primary_place_of_performance_county",
        ),
        "place_of_performance_county_fips": _place_county_fips(row_by_key),
        "awarding_agency_code": _get_text(row_by_key, "awarding_agency_code"),
        "awarding_agency_name": _get_text(row_by_key, "awarding_agency_name"),
        "funding_agency_code": _get_text(row_by_key, "funding_agency_code"),
        "funding_agency_name": _get_text(row_by_key, "funding_agency_name"),
        "awarding_subagency_name": _get_text(
            row_by_key,
            "awarding_subagency_name",
            "awarding_sub_agency_name",
        ),
        "funding_subagency_name": _get_text(
            row_by_key,
            "funding_subagency_name",
            "funding_sub_agency_name",
        ),
        "obligation_amount": transaction_amount,
        "outlay_amount": _get_amount(
            row_by_key,
            stats,
            "outlay_amount",
            "gross_outlay_amount_fyb_to_period_end",
            "gross_outlay_amount_fyb",
            "gross_outlay_amount",
            "outlay_amount",
        ),
        "transaction_obligated_amount": transaction_amount,
        "action_date": _get_date(
            row_by_key,
            stats,
            "action_date",
            "action_date",
            "award_base_action_date",
            "award_latest_action_date",
        ),
        "period_of_performance_start_date": _get_date(
            row_by_key,
            stats,
            "period_of_performance_start_date",
            "period_of_performance_start_date",
        ),
        "period_of_performance_current_end_date": _get_date(
            row_by_key,
            stats,
            "period_of_performance_current_end_date",
            "period_of_performance_current_end_date",
        ),
        "cfda_title": _get_text(row_by_key, "cfda_title"),
        "award_description": _get_text(
            row_by_key,
            "award_description",
            "prime_award_base_transaction_description",
        ),
        "naics_code": _get_text(row_by_key, "naics_code"),
        "naics_description": _get_text(row_by_key, "naics_description"),
        "psc_code": _get_text(row_by_key, "psc_code", "product_or_service_code"),
        "psc_description": _get_text(
            row_by_key,
            "psc_description",
            "product_or_service_code_description",
        ),
        "raw_amount_json": _raw_amount_json(
            row_by_key,
            original_key_by_normalized,
            mapped_aliases=mapped_amount_aliases,
        ),
        "raw_row_json": raw_row_json,
    }


def _insert_batch(conn: Connection, table: Any, batch: list[dict[str, Any]]) -> int:
    if not batch:
        return 0
    conn.execute(table.insert(), batch)
    count = len(batch)
    batch.clear()
    return count


def _existing_registry_rows(conn: Connection, *, file_path: str, file_hash: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(RAW_FILE_TABLE.c.id, RAW_FILE_TABLE.c.notes).where(
            (RAW_FILE_TABLE.c.file_path == file_path) | (RAW_FILE_TABLE.c.file_hash == file_hash)
        )
    ).all()
    return [dict(row._mapping) for row in rows]


def _delete_existing_file_load(conn: Connection, raw_file_ids: list[int]) -> None:
    if not raw_file_ids:
        return
    conn.execute(AWARD_TABLE.delete().where(AWARD_TABLE.c.raw_file_id.in_(raw_file_ids)))
    conn.execute(PA_OC_TABLE.delete().where(PA_OC_TABLE.c.raw_file_id.in_(raw_file_ids)))
    conn.execute(BALANCE_TABLE.delete().where(BALANCE_TABLE.c.raw_file_id.in_(raw_file_ids)))
    conn.execute(RAW_FILE_TABLE.delete().where(RAW_FILE_TABLE.c.id.in_(raw_file_ids)))


def _insert_raw_file_registry(
    conn: Connection,
    discovered_file: DiscoveredFedAccountFile,
    *,
    file_hash: str,
    notes: str | None,
) -> int:
    row = {
        "fiscal_year": discovered_file.fiscal_year,
        "file_path": str(discovered_file.path),
        "file_name": discovered_file.path.name,
        "dataset_type": discovered_file.dataset_type,
        "source_agency_code": discovered_file.source_agency_code,
        "period_label": discovered_file.period_label,
        "downloaded_at_from_filename": discovered_file.downloaded_at_from_filename,
        "row_count": 0,
        "file_hash": file_hash,
        "notes": notes,
    }
    return int(conn.execute(RAW_FILE_TABLE.insert().values(**row).returning(RAW_FILE_TABLE.c.id)).scalar_one())


def process_csv_file(
    discovered_file: DiscoveredFedAccountFile,
    *,
    conn: Connection | None,
    raw_file_id: int | None,
    dry_run: bool,
    limit_rows: int | None,
    chunksize: int,
    account_cache: dict[str, int],
) -> FileParseStats:
    stats = FileParseStats()
    encoding = probe_encoding(discovered_file.path)
    logger.info("Parsing %s as %s", discovered_file.path.name, discovered_file.dataset_type)

    with discovered_file.path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.reader(handle)
        header_row = next(reader, [])
        normalized_header = [normalize_header(value) for value in header_row]
        normalized_header_set = set(normalized_header)
        original_key_by_normalized = {
            normalized_key: original_key
            for normalized_key, original_key in zip(normalized_header, header_row, strict=False)
            if normalized_key
        }

        if discovered_file.dataset_type == DATASET_BALANCES:
            _has_required_columns(
                normalized_header_set,
                ("federal_account_symbol", "federal_account_name", "obligations_incurred"),
                stats,
            )
        elif discovered_file.dataset_type == DATASET_PA_OC:
            _has_required_columns(
                normalized_header_set,
                ("federal_account_symbol", "federal_account_name", "program_activity_code"),
                stats,
            )
        elif discovered_file.dataset_type in AWARD_SOURCE_BY_DATASET:
            _has_required_columns(
                normalized_header_set,
                ("federal_account_symbol", "federal_account_name", "award_unique_key"),
                stats,
            )

        balance_batch: list[dict[str, Any]] = []
        pa_oc_batch: list[dict[str, Any]] = []
        award_batch: list[dict[str, Any]] = []

        for row_number, raw_row in enumerate(reader, start=2):
            if limit_rows is not None and stats.rows_seen >= limit_rows:
                break
            stats.rows_seen += 1

            row = _coerce_row_width(list(raw_row), len(header_row))
            raw_row_json = dict(zip(header_row, row, strict=True))
            if not any(clean_text(value) is not None for value in raw_row_json.values()):
                stats.rows_skipped += 1
                continue
            row_by_key = {
                normalized_key: value
                for normalized_key, value in zip(normalized_header, row, strict=True)
                if normalized_key
            }

            account_id: int | None = None
            if dry_run:
                if normalize_federal_account_key(
                    row_by_key,
                    source_agency_code=discovered_file.source_agency_code,
                ) is None:
                    stats.missing_account_identity_rows += 1
                else:
                    account_id = 0
            else:
                if conn is None or raw_file_id is None:
                    raise RuntimeError("Database connection and raw_file_id are required outside dry-run.")
                account_id = upsert_federal_account(
                    conn,
                    row_by_key,
                    source_agency_code=discovered_file.source_agency_code,
                    account_cache=account_cache,
                )
                if account_id is None:
                    stats.missing_account_identity_rows += 1

            if discovered_file.dataset_type in (DATASET_BALANCES, DATASET_PA_OC) and account_id is None and not dry_run:
                raise RuntimeError(
                    f"Cannot infer account identity for {discovered_file.path.name} row {row_number}."
                )

            if discovered_file.dataset_type == DATASET_BALANCES:
                record = build_balance_record(
                    row_by_key,
                    raw_row_json,
                    original_key_by_normalized,
                    fiscal_year=discovered_file.fiscal_year,
                    raw_file_id=raw_file_id or 0,
                    federal_account_id=int(account_id or 0),
                    stats=stats,
                )
                if not dry_run:
                    balance_batch.append(record)
                    if len(balance_batch) >= chunksize:
                        _insert_batch(conn, BALANCE_TABLE, balance_batch)
                stats.rows_loaded += 1
            elif discovered_file.dataset_type == DATASET_PA_OC:
                record = build_pa_oc_record(
                    row_by_key,
                    raw_row_json,
                    original_key_by_normalized,
                    fiscal_year=discovered_file.fiscal_year,
                    raw_file_id=raw_file_id or 0,
                    federal_account_id=int(account_id or 0),
                    stats=stats,
                )
                if not dry_run:
                    pa_oc_batch.append(record)
                    if len(pa_oc_batch) >= chunksize:
                        _insert_batch(conn, PA_OC_TABLE, pa_oc_batch)
                stats.rows_loaded += 1
            elif discovered_file.dataset_type in AWARD_SOURCE_BY_DATASET:
                record = build_award_record(
                    row_by_key,
                    raw_row_json,
                    original_key_by_normalized,
                    fiscal_year=discovered_file.fiscal_year,
                    raw_file_id=raw_file_id or 0,
                    federal_account_id=account_id,
                    award_source_type=AWARD_SOURCE_BY_DATASET[discovered_file.dataset_type],
                    stats=stats,
                )
                if not dry_run:
                    award_batch.append(record)
                    if len(award_batch) >= chunksize:
                        _insert_batch(conn, AWARD_TABLE, award_batch)
                stats.rows_loaded += 1
            else:
                stats.rows_skipped += 1

        if not dry_run:
            _insert_batch(conn, BALANCE_TABLE, balance_batch)
            _insert_batch(conn, PA_OC_TABLE, pa_oc_batch)
            _insert_batch(conn, AWARD_TABLE, award_batch)

    if stats.missing_expected_columns:
        logger.warning(
            "%s missing expected columns: %s",
            discovered_file.path.name,
            ", ".join(sorted(stats.missing_expected_columns)),
        )
    if stats.bad_date_counts:
        logger.warning("%s bad dates: %s", discovered_file.path.name, dict(stats.bad_date_counts))
    if stats.bad_amount_counts:
        logger.warning("%s bad amounts: %s", discovered_file.path.name, dict(stats.bad_amount_counts))
    if stats.missing_account_identity_rows:
        logger.warning(
            "%s rows without account identity: %s",
            discovered_file.path.name,
            stats.missing_account_identity_rows,
        )
    return stats


def _table_counter_key(discovered_file: DiscoveredFedAccountFile) -> str:
    if discovered_file.dataset_type == DATASET_BALANCES:
        return "fact_account_balance"
    if discovered_file.dataset_type == DATASET_PA_OC:
        return "fact_account_pa_oc"
    if discovered_file.dataset_type in AWARD_SOURCE_BY_DATASET:
        return f"fact_award_account_breakdown:{AWARD_SOURCE_BY_DATASET[discovered_file.dataset_type]}"
    return "unknown"


def ingest_discovered_file(
    engine: Engine,
    discovered_file: DiscoveredFedAccountFile,
    *,
    force: bool,
    limit_rows: int | None,
    chunksize: int,
    account_cache: dict[str, int],
) -> tuple[bool, FileParseStats]:
    file_hash = compute_file_hash(discovered_file.path)
    with engine.begin() as conn:
        existing_rows = _existing_registry_rows(
            conn,
            file_path=str(discovered_file.path),
            file_hash=file_hash,
        )
        existing_ids = [int(row["id"]) for row in existing_rows]
        has_limited_prior_load = any(str(row.get("notes") or "").startswith("limit_rows=") for row in existing_rows)
        should_replace_limited_load = bool(existing_ids and has_limited_prior_load and limit_rows is None)
        if existing_ids and not force and not should_replace_limited_load:
            logger.info(
                "Skipping already ingested file %s (registry ids: %s)",
                discovered_file.path.name,
                existing_ids,
            )
            return False, FileParseStats()
        if existing_ids and (force or should_replace_limited_load):
            logger.info("Deleting prior rows before reingesting %s", discovered_file.path.name)
            _delete_existing_file_load(conn, existing_ids)

        notes = f"limit_rows={limit_rows}" if limit_rows is not None else None
        raw_file_id = _insert_raw_file_registry(
            conn,
            discovered_file,
            file_hash=file_hash,
            notes=notes,
        )
        stats = process_csv_file(
            discovered_file,
            conn=conn,
            raw_file_id=raw_file_id,
            dry_run=False,
            limit_rows=limit_rows,
            chunksize=chunksize,
            account_cache=account_cache,
        )
        conn.execute(
            RAW_FILE_TABLE.update()
            .where(RAW_FILE_TABLE.c.id == raw_file_id)
            .values(row_count=stats.rows_loaded)
        )
    return True, stats


def _summarize_file_stats(
    summary: IngestionRunSummary,
    discovered_file: DiscoveredFedAccountFile,
    stats: FileParseStats,
    *,
    ingested: bool,
) -> None:
    if ingested:
        summary.files_ingested_by_type[discovered_file.dataset_type] += 1
    summary.rows_by_table_or_type[_table_counter_key(discovered_file)] += stats.rows_loaded
    summary.rows_by_fiscal_year[discovered_file.fiscal_year] += stats.rows_loaded
    if stats.missing_expected_columns:
        summary.missing_columns_by_file[discovered_file.path.name] = sorted(stats.missing_expected_columns)
    summary.bad_dates_by_field.update(stats.bad_date_counts)
    summary.bad_amounts_by_field.update(stats.bad_amount_counts)
    summary.missing_account_identity_rows += stats.missing_account_identity_rows


def run_ingestion(
    *,
    data_dir: Path,
    years: Iterable[int],
    db_url: str,
    force: bool,
    dry_run: bool,
    limit_rows: int | None,
    chunksize: int,
    rebuild_reconciliation: bool,
    output_path: Path,
) -> IngestionRunSummary:
    discovered_files = discover_fed_account_files(data_dir, years=years)
    summary = IngestionRunSummary(dry_run=dry_run, files_discovered=len(discovered_files))
    if not discovered_files:
        logger.warning("No FY%s federal account CSVs discovered under %s", sorted(set(years)), data_dir)
        return summary

    logger.info("Discovered %s federal account CSV files.", len(discovered_files))
    account_cache: dict[str, int] = {}

    if dry_run:
        for discovered_file in discovered_files:
            stats = process_csv_file(
                discovered_file,
                conn=None,
                raw_file_id=None,
                dry_run=True,
                limit_rows=limit_rows,
                chunksize=chunksize,
                account_cache=account_cache,
            )
            _summarize_file_stats(summary, discovered_file, stats, ingested=True)
        print_dry_run_summary(summary, discovered_files)
        return summary

    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        for discovered_file in discovered_files:
            ingested, stats = ingest_discovered_file(
                engine,
                discovered_file,
                force=force,
                limit_rows=limit_rows,
                chunksize=chunksize,
                account_cache=account_cache,
            )
            if not ingested:
                summary.files_skipped_existing += 1
            _summarize_file_stats(summary, discovered_file, stats, ingested=ingested)

        print_database_validation_summary(engine, years=years, run_summary=summary)
        if rebuild_reconciliation:
            write_reconciliation_report(engine, years=years, output_path=output_path)
    finally:
        engine.dispose()
    return summary


def print_dry_run_summary(
    summary: IngestionRunSummary,
    discovered_files: list[DiscoveredFedAccountFile],
) -> None:
    print("\nUSAspending federal account dry run")
    print(f"Files discovered: {summary.files_discovered}")
    for dataset_type, count in sorted(Counter(file.dataset_type for file in discovered_files).items()):
        print(f"  {dataset_type}: {count} file(s)")
    print("Rows parsed by table/type:")
    for key, count in sorted(summary.rows_by_table_or_type.items()):
        print(f"  {key}: {count}")
    if summary.missing_columns_by_file:
        print("Files with missing expected columns:")
        for file_name, columns in sorted(summary.missing_columns_by_file.items()):
            print(f"  {file_name}: {', '.join(columns)}")
    if summary.bad_dates_by_field:
        print(f"Bad date values by field: {dict(summary.bad_dates_by_field)}")
    if summary.bad_amounts_by_field:
        print(f"Bad amount values by field: {dict(summary.bad_amounts_by_field)}")
    if summary.missing_account_identity_rows:
        print(f"Rows without account identity: {summary.missing_account_identity_rows}")
    print("Dry run complete; no database writes performed.")


def _year_filter_sql(years: Iterable[int]) -> tuple[str, dict[str, Any]]:
    selected_years = sorted(set(int(year) for year in years))
    if not selected_years:
        return "", {}
    return "WHERE fiscal_year = ANY(:years)", {"years": selected_years}


def fetch_reconciliation_rows(engine_or_conn: Engine | Connection, *, years: Iterable[int]) -> list[dict[str, Any]]:
    where_sql, params = _year_filter_sql(years)
    sql = text(
        f"""
        SELECT {", ".join(RECONCILIATION_COLUMNS)}
        FROM {usaspending_fed_account_table("v_account_reconciliation")}
        {where_sql}
        ORDER BY fiscal_year, normalized_account_key
        """
    )
    if isinstance(engine_or_conn, Engine):
        with engine_or_conn.connect() as conn:
            return [dict(row._mapping) for row in conn.execute(sql, params)]
    return [dict(row._mapping) for row in engine_or_conn.execute(sql, params)]


def _fetch_registry_counts(engine: Engine, years: Iterable[int]) -> dict[int, dict[str, int]]:
    selected_years = sorted(set(int(year) for year in years))
    params: dict[str, Any] = {"years": selected_years}
    sql = text(
        f"""
        SELECT fiscal_year, dataset_type, COUNT(*) AS file_count
        FROM {usaspending_fed_account_table("raw_file_registry")}
        WHERE fiscal_year = ANY(:years)
        GROUP BY fiscal_year, dataset_type
        ORDER BY fiscal_year, dataset_type
        """
    )
    output: dict[int, dict[str, int]] = defaultdict(dict)
    with engine.connect() as conn:
        for row in conn.execute(sql, params):
            output[int(row.fiscal_year)][str(row.dataset_type)] = int(row.file_count)
    return output


def _decimal_sum(rows: list[dict[str, Any]], key: str) -> Decimal:
    total = Decimal("0.00")
    for row in rows:
        value = row.get(key)
        if value is not None:
            total += Decimal(value)
    return total.quantize(Decimal("0.01"))


def print_database_validation_summary(
    engine: Engine,
    *,
    years: Iterable[int],
    run_summary: IngestionRunSummary,
) -> None:
    rows = fetch_reconciliation_rows(engine, years=years)
    rows_by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_year[int(row["fiscal_year"])].append(row)
    registry_counts = _fetch_registry_counts(engine, years)

    print("\nUSAspending federal account validation summary")
    print("Files ingested this run by type:")
    for dataset_type, count in sorted(run_summary.files_ingested_by_type.items()):
        print(f"  {dataset_type}: {count}")
    if run_summary.files_skipped_existing:
        print(f"Files skipped because already ingested: {run_summary.files_skipped_existing}")
    print("Rows ingested this run by table/type:")
    for key, count in sorted(run_summary.rows_by_table_or_type.items()):
        print(f"  {key}: {count}")

    for fiscal_year in sorted(set(int(year) for year in years)):
        fy_rows = rows_by_year.get(fiscal_year, [])
        balance = _decimal_sum(fy_rows, "balance_obligations")
        award_total = _decimal_sum(fy_rows, "award_obligations_total")
        assistance = _decimal_sum(fy_rows, "assistance_award_obligations")
        contracts = _decimal_sum(fy_rows, "contracts_award_obligations")
        unlinked = _decimal_sum(fy_rows, "unlinked_award_obligations")
        pa_oc = _decimal_sum(fy_rows, "pa_oc_obligations_total")
        print(f"\nFY{fiscal_year}")
        print(f"  files by type in registry: {registry_counts.get(fiscal_year, {})}")
        print(f"  distinct federal accounts: {len(fy_rows)}")
        print(f"  total balance obligations: {balance}")
        print(f"  total award obligations: {award_total}")
        print(f"  total assistance obligations: {assistance}")
        print(f"  total contracts obligations: {contracts}")
        print(f"  total unlinked obligations: {unlinked}")
        print(f"  total PA/OC obligations: {pa_oc}")
        print(f"  balance minus award obligations: {(balance - award_total).quantize(Decimal('0.01'))}")
        print(f"  balance minus PA/OC obligations: {(balance - pa_oc).quantize(Decimal('0.01'))}")


def _json_safe_csv_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def write_reconciliation_report(
    engine: Engine,
    *,
    years: Iterable[int],
    output_path: Path,
) -> None:
    rows = fetch_reconciliation_rows(engine, years=years)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECONCILIATION_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _json_safe_csv_value(row.get(key)) for key in RECONCILIATION_COLUMNS})
    logger.info("Wrote %s reconciliation rows to %s", len(rows), output_path)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging(args.log_level)
    run_ingestion(
        data_dir=Path(args.data_dir).expanduser().resolve(),
        years=args.years,
        db_url=args.db_url,
        force=args.force,
        dry_run=args.dry_run,
        limit_rows=args.limit_rows,
        chunksize=args.chunksize,
        rebuild_reconciliation=args.rebuild_reconciliation,
        output_path=Path(args.output_path).expanduser().resolve(),
    )


if __name__ == "__main__":
    main()
