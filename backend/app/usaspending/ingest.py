from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db_schemas import USASPENDING_SCHEMA
from app.db_fqtn import usaspending_table
from app.usaspending.models import (
    UsaspendingContractCategoryRule,
    UsaspendingContractFederalAccountInventory,
    UsaspendingContractStateYearSummary,
    UsaspendingContractTransactionRaw,
    UsaspendingIngestionRun,
)

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_CHUNKSIZE = 2000
DEFAULT_SUMMARY_FILENAME = "contracts_ingestion_summary.json"
ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

MATCHING_SIGNATURE_HEADERS = {
    "contract_transaction_unique_key",
    "contract_award_unique_key",
    "award_id_piid",
    "action_date",
    "action_date_fiscal_year",
    "federal_action_obligation",
}

NULL_TOKENS = {
    "",
    "na",
    "n/a",
    "none",
    "null",
    "nan",
}

CATEGORY_LIKELY_VFC = "likely_vfc_vaccine_purchase"
CATEGORY_IMMUNIZATION = "likely_immunization_related"
CATEGORY_LAB = "likely_lab_or_testing"
CATEGORY_ADMIN = "likely_admin_or_operations"
CATEGORY_IT = "likely_it_or_data"
CATEGORY_RESEARCH = "likely_research_or_evaluation"
CATEGORY_OTHER = "other_contract"
CATEGORY_UNKNOWN = "unknown"

SUPPORTED_MATCH_FIELDS = {
    "award_description",
    "product_or_service_code",
    "product_or_service_code_description",
    "naics_code",
    "naics_description",
    "federal_account_symbol",
    "normalized_federal_account_symbol",
    "funding_agency_name",
    "awarding_agency_name",
    "contract_award_type",
    "contract_transaction_type",
}

DEFAULT_CONTRACT_CATEGORY_RULES = [
    {
        "priority": 10,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "vaccines for children",
        "assigned_category": CATEGORY_LIKELY_VFC,
        "notes": "Explicit VFC award-description reference.",
    },
    {
        "priority": 12,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": " vfc ",
        "assigned_category": CATEGORY_LIKELY_VFC,
        "notes": "Explicit VFC acronym in free text.",
    },
    {
        "priority": 20,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "immunization",
        "assigned_category": CATEGORY_IMMUNIZATION,
        "notes": "Immunization-related description keyword.",
    },
    {
        "priority": 22,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "vaccine",
        "assigned_category": CATEGORY_IMMUNIZATION,
        "notes": "General vaccine-related description keyword.",
    },
    {
        "priority": 24,
        "match_field": "product_or_service_code_description",
        "match_type": "contains",
        "match_value": "biological",
        "assigned_category": CATEGORY_IMMUNIZATION,
        "notes": "PSC description suggests biologics or vaccines.",
    },
    {
        "priority": 26,
        "match_field": "product_or_service_code_description",
        "match_type": "contains",
        "match_value": "pharmaceutical",
        "assigned_category": CATEGORY_IMMUNIZATION,
        "notes": "PSC description suggests pharmaceutical procurement.",
    },
    {
        "priority": 40,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "laboratory",
        "assigned_category": CATEGORY_LAB,
        "notes": "Laboratory-related description keyword.",
    },
    {
        "priority": 42,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "testing",
        "assigned_category": CATEGORY_LAB,
        "notes": "Testing-related description keyword.",
    },
    {
        "priority": 44,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "surveillance",
        "assigned_category": CATEGORY_LAB,
        "notes": "Surveillance-related description keyword.",
    },
    {
        "priority": 46,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "sequencing",
        "assigned_category": CATEGORY_LAB,
        "notes": "Sequencing-related description keyword.",
    },
    {
        "priority": 60,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "software",
        "assigned_category": CATEGORY_IT,
        "notes": "Software-related description keyword.",
    },
    {
        "priority": 62,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "informatics",
        "assigned_category": CATEGORY_IT,
        "notes": "Informatics-related description keyword.",
    },
    {
        "priority": 64,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "data",
        "assigned_category": CATEGORY_IT,
        "notes": "Data-related description keyword.",
    },
    {
        "priority": 66,
        "match_field": "product_or_service_code_description",
        "match_type": "contains",
        "match_value": "it and telecom",
        "assigned_category": CATEGORY_IT,
        "notes": "PSC description suggests IT or telecom work.",
    },
    {
        "priority": 80,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "janitorial",
        "assigned_category": CATEGORY_ADMIN,
        "notes": "Janitorial support contract.",
    },
    {
        "priority": 82,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "custodial",
        "assigned_category": CATEGORY_ADMIN,
        "notes": "Custodial support contract.",
    },
    {
        "priority": 84,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "facility",
        "assigned_category": CATEGORY_ADMIN,
        "notes": "Facilities or operations support contract.",
    },
    {
        "priority": 86,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "administrative",
        "assigned_category": CATEGORY_ADMIN,
        "notes": "Administrative support contract.",
    },
    {
        "priority": 88,
        "match_field": "product_or_service_code_description",
        "match_type": "contains",
        "match_value": "custodial",
        "assigned_category": CATEGORY_ADMIN,
        "notes": "PSC description suggests custodial work.",
    },
    {
        "priority": 100,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "research",
        "assigned_category": CATEGORY_RESEARCH,
        "notes": "Research-related description keyword.",
    },
    {
        "priority": 102,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "evaluation",
        "assigned_category": CATEGORY_RESEARCH,
        "notes": "Evaluation-related description keyword.",
    },
    {
        "priority": 104,
        "match_field": "award_description",
        "match_type": "contains",
        "match_value": "study",
        "assigned_category": CATEGORY_RESEARCH,
        "notes": "Study-related description keyword.",
    },
]

RAW_TABLE = UsaspendingContractTransactionRaw.__table__
STATE_SUMMARY_TABLE = UsaspendingContractStateYearSummary.__table__
ACCOUNT_INVENTORY_TABLE = UsaspendingContractFederalAccountInventory.__table__
CATEGORY_RULES_TABLE = UsaspendingContractCategoryRule.__table__
INGESTION_RUNS_TABLE = UsaspendingIngestionRun.__table__
CURRENT_TABLES = [
    RAW_TABLE,
    STATE_SUMMARY_TABLE,
    ACCOUNT_INVENTORY_TABLE,
    CATEGORY_RULES_TABLE,
    INGESTION_RUNS_TABLE,
]

RAW_TABLE_FQTN = usaspending_table("contract_transactions_raw")
ENRICHED_VIEW_FQTN = usaspending_table("contract_transactions_enriched")
STATE_SUMMARY_FQTN = usaspending_table("contract_state_year_summary")
ACCOUNT_INVENTORY_FQTN = usaspending_table("contract_federal_account_inventory")


@dataclass
class FileInspection:
    path: Path
    encoding: str
    header_row: list[str]
    normalized_header: list[str]
    normalized_header_keys: list[str]
    is_matching_contract_transaction: bool
    missing_signature_headers: list[str]


@dataclass
class FileParseStats:
    total_csv_rows: int = 0
    loaded_rows: int = 0
    blank_rows: int = 0
    anomalies: list[dict[str, Any]] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Ingest USAspending CDC contract transaction CSVs into schema {USASPENDING_SCHEMA}.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Directory containing USAspending contract CSV files (defaults to data/usaspending/contracts).",
    )
    parser.add_argument(
        "--summary-path",
        default=None,
        help=f"Optional summary path (defaults to <input-dir>/{DEFAULT_SUMMARY_FILENAME}).",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"Insert batch size for database writes (default: {DEFAULT_CHUNKSIZE}).",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate raw and derived contract tables before loading.",
    )
    parser.add_argument(
        "--drop-and-recreate",
        action="store_true",
        help="Drop and recreate USAspending contract tables and views before loading.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and parse files without writing to the database.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-file validation and load details.",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=None,
        help="Optional deterministic cap on discovered CSV files after sorting.",
    )
    parser.add_argument(
        "--rebuild-summaries",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh the enriched view and summary tables after loading (default: true).",
    )
    return parser.parse_args()


def _resolve_input_dir(explicit_input_dir: str | None) -> Path:
    if explicit_input_dir:
        return Path(explicit_input_dir).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[3]
    return (repo_root / "data" / "usaspending" / "contracts").resolve()


def _resolve_summary_path(input_dir: Path, explicit_summary_path: str | None) -> Path:
    if explicit_summary_path:
        return Path(explicit_summary_path).expanduser().resolve()
    return (input_dir / DEFAULT_SUMMARY_FILENAME).resolve()


def discover_csv_files(input_dir: Path, *, limit_files: int | None = None) -> list[Path]:
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
    token = str(value).replace("\ufeff", "")
    token = token.replace("\r\n", "\n").replace("\r", "\n")
    token = re.sub(r"\s+", " ", token).strip()
    if token.lower() in NULL_TOKENS:
        return None
    return token or None


def _normalize_header_value(value: Any) -> str:
    token = str(value or "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", token).strip()


def _normalize_header_key(value: Any) -> str:
    token = _normalize_header_value(value).lower()
    token = re.sub(r"[^a-z0-9]+", "_", token)
    return token.strip("_")


def _parse_decimal(value: Any) -> Decimal | None:
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


def _normalize_state_code(value: Any) -> str | None:
    token = _clean_text(value)
    if token is None:
        return None
    letters = re.sub(r"[^A-Za-z]", "", token).upper()
    if len(letters) == 2:
        return letters
    return None


def _canonicalize_account_list(value: Any) -> str | None:
    token = _clean_text(value)
    if token is None:
        return None
    parts: list[str] = []
    seen: set[str] = set()
    for raw_piece in token.split(";"):
        piece = re.sub(r"\s+", " ", raw_piece).strip()
        if not piece:
            continue
        canonical = piece.upper()
        if canonical in seen:
            continue
        seen.add(canonical)
        parts.append(piece)
    return ";".join(parts) or None


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
    raise RuntimeError(f"Unable to decode contract CSV {path}: {last_error}")


def inspect_contract_csv(path: Path) -> FileInspection:
    encoding = _probe_encoding(path)
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.reader(handle)
        header_row = next(reader, [])

    normalized_header = [_normalize_header_value(value) for value in header_row]
    normalized_header_keys = [_normalize_header_key(value) for value in header_row]
    missing_signature_headers = sorted(
        signature_header
        for signature_header in MATCHING_SIGNATURE_HEADERS
        if signature_header not in normalized_header_keys
    )

    return FileInspection(
        path=path,
        encoding=encoding,
        header_row=header_row,
        normalized_header=normalized_header,
        normalized_header_keys=normalized_header_keys,
        is_matching_contract_transaction=not missing_signature_headers,
        missing_signature_headers=missing_signature_headers,
    )


def _column_diff(actual: list[str], reference: list[str]) -> dict[str, Any]:
    missing = [column for column in reference if column not in actual]
    extra = [column for column in actual if column not in reference]
    order_differences: list[dict[str, Any]] = []
    if not missing and not extra and len(actual) == len(reference):
        for index, (actual_value, reference_value) in enumerate(
            zip(actual, reference, strict=True),
            start=1,
        ):
            if actual_value != reference_value:
                order_differences.append(
                    {
                        "position": index,
                        "reference": reference_value,
                        "actual": actual_value,
                    }
                )
    return {
        "missing_columns": missing,
        "extra_columns": extra,
        "column_order_differences": order_differences,
        "is_compatible": not missing and not extra,
    }


def validate_csv_headers(structures: list[FileInspection]) -> dict[str, Any]:
    matching = [structure for structure in structures if structure.is_matching_contract_transaction]
    skipped = [structure for structure in structures if not structure.is_matching_contract_transaction]

    if not matching:
        raise RuntimeError("No contract prime-transaction CSV files were detected in the input directory.")

    reference = matching[0]
    header_discrepancies: list[dict[str, Any]] = []
    incompatible_headers = False

    for structure in matching:
        diff = _column_diff(structure.normalized_header, reference.normalized_header)
        if structure.path != reference.path and (
            diff["missing_columns"]
            or diff["extra_columns"]
            or diff["column_order_differences"]
        ):
            header_discrepancies.append(
                {
                    "filename": structure.path.name,
                    "kind": "matching_file_difference",
                    "reference_file": reference.path.name,
                    **diff,
                }
            )
        if not diff["is_compatible"]:
            incompatible_headers = True

    for structure in skipped:
        header_discrepancies.append(
            {
                "filename": structure.path.name,
                "kind": "nonmatching_csv",
                "missing_signature_headers": structure.missing_signature_headers,
                "header_actual": structure.normalized_header,
            }
        )

    return {
        "reference_header_file": reference.path.name,
        "reference_header": reference.normalized_header,
        "files_discovered": [structure.path.name for structure in structures],
        "matching_files": [structure.path.name for structure in matching],
        "skipped_nonmatching_files": [structure.path.name for structure in skipped],
        "header_discrepancies": header_discrepancies,
        "has_incompatible_matching_headers": incompatible_headers,
    }


def _record_anomaly(stats: FileParseStats, kind: str, **payload: Any) -> None:
    if len(stats.anomalies) >= 200:
        return
    stats.anomalies.append({"kind": kind, **payload})


def _coerce_row_width(
    row: list[str],
    *,
    expected_len: int,
    stats: FileParseStats,
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


def _get_value(row_by_key: dict[str, Any], *aliases: str) -> Any:
    for alias in aliases:
        if alias in row_by_key:
            return row_by_key[alias]
    return None


def _parse_with_anomaly(
    parser: Any,
    value: Any,
    *,
    field_name: str,
    stats: FileParseStats,
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


def _build_contract_record(
    raw_row_json: dict[str, Any],
    row_by_key: dict[str, Any],
    *,
    source_path: Path,
    row_number: int,
    stats: FileParseStats,
) -> dict[str, Any]:
    contract_award_unique_key = _clean_text(_get_value(row_by_key, "contract_award_unique_key"))
    recipient_state_code = _clean_text(_get_value(row_by_key, "recipient_state_code"))
    normalized_recipient_state = _normalize_state_code(recipient_state_code)
    if recipient_state_code and normalized_recipient_state is None:
        _record_anomaly(
            stats,
            "invalid_state_code",
            file=source_path.name,
            row_number=row_number,
            field_name="recipient_state_code",
            raw_value=recipient_state_code,
        )

    federal_accounts = _clean_text(
        _get_value(row_by_key, "federal_accounts_funding_this_award", "federal_account_symbol")
    )
    treasury_accounts = _clean_text(
        _get_value(row_by_key, "treasury_accounts_funding_this_award", "treasury_account_symbol")
    )
    normalized_federal_accounts = _canonicalize_account_list(federal_accounts)

    transaction_description = _clean_text(_get_value(row_by_key, "transaction_description"))
    prime_award_base_transaction_description = _clean_text(
        _get_value(row_by_key, "prime_award_base_transaction_description")
    )

    return {
        "source_file": str(source_path.resolve()),
        "source_filename": source_path.name,
        "row_number": row_number,
        "raw_row_json": raw_row_json,
        "contract_transaction_unique_key": _clean_text(
            _get_value(row_by_key, "contract_transaction_unique_key")
        ),
        "contract_award_unique_key": contract_award_unique_key,
        "generated_unique_award_id": _clean_text(
            _get_value(row_by_key, "generated_unique_award_id")
        )
        or contract_award_unique_key,
        "award_id_piid": _clean_text(_get_value(row_by_key, "award_id_piid")),
        "parent_award_id_piid": _clean_text(_get_value(row_by_key, "parent_award_id_piid")),
        "modification_number": _clean_text(_get_value(row_by_key, "modification_number")),
        "transaction_number": _clean_text(_get_value(row_by_key, "transaction_number")),
        "action_date": _parse_with_anomaly(
            _parse_date,
            _get_value(row_by_key, "action_date"),
            field_name="action_date",
            stats=stats,
            path=source_path,
            row_number=row_number,
        ),
        "fiscal_year": _parse_with_anomaly(
            _parse_int,
            _get_value(row_by_key, "action_date_fiscal_year", "fiscal_year"),
            field_name="fiscal_year",
            stats=stats,
            path=source_path,
            row_number=row_number,
        ),
        "transaction_obligated_amount": _parse_with_anomaly(
            _parse_decimal,
            _get_value(row_by_key, "federal_action_obligation", "transaction_obligated_amount"),
            field_name="transaction_obligated_amount",
            stats=stats,
            path=source_path,
            row_number=row_number,
        ),
        "total_dollars_obligated": _parse_with_anomaly(
            _parse_decimal,
            _get_value(row_by_key, "total_dollars_obligated"),
            field_name="total_dollars_obligated",
            stats=stats,
            path=source_path,
            row_number=row_number,
        ),
        "current_total_value_of_award": _parse_with_anomaly(
            _parse_decimal,
            _get_value(row_by_key, "current_total_value_of_award"),
            field_name="current_total_value_of_award",
            stats=stats,
            path=source_path,
            row_number=row_number,
        ),
        "potential_total_value_of_award": _parse_with_anomaly(
            _parse_decimal,
            _get_value(row_by_key, "potential_total_value_of_award"),
            field_name="potential_total_value_of_award",
            stats=stats,
            path=source_path,
            row_number=row_number,
        ),
        "recipient_name": _clean_text(_get_value(row_by_key, "recipient_name")),
        "recipient_state_code": recipient_state_code,
        "recipient_state_name": _clean_text(_get_value(row_by_key, "recipient_state_name")),
        "recipient_county_name": _clean_text(_get_value(row_by_key, "recipient_county_name")),
        "recipient_city_name": _clean_text(_get_value(row_by_key, "recipient_city_name")),
        "recipient_country_code": _clean_text(_get_value(row_by_key, "recipient_country_code")),
        "recipient_country_name": _clean_text(_get_value(row_by_key, "recipient_country_name")),
        "recipient_zip": _clean_text(_get_value(row_by_key, "recipient_zip_4_code", "recipient_zip")),
        "awarding_agency_name": _clean_text(_get_value(row_by_key, "awarding_agency_name")),
        "awarding_sub_agency_name": _clean_text(
            _get_value(row_by_key, "awarding_sub_agency_name")
        ),
        "funding_agency_name": _clean_text(_get_value(row_by_key, "funding_agency_name")),
        "funding_sub_agency_name": _clean_text(_get_value(row_by_key, "funding_sub_agency_name")),
        "federal_account_symbol": federal_accounts,
        "treasury_account_symbol": treasury_accounts,
        "federal_accounts_funding_this_award": federal_accounts,
        "treasury_accounts_funding_this_award": treasury_accounts,
        "object_classes_funding_this_award": _clean_text(
            _get_value(row_by_key, "object_classes_funding_this_award")
        ),
        "program_activities_funding_this_award": _clean_text(
            _get_value(row_by_key, "program_activities_funding_this_award")
        ),
        "disaster_emergency_fund_code": _clean_text(
            _get_value(
                row_by_key,
                "disaster_emergency_fund_code",
                "disaster_emergency_fund_codes_for_overall_award",
            )
        ),
        "appropriation_account": _clean_text(_get_value(row_by_key, "appropriation_account")),
        "appropriation_type": _clean_text(_get_value(row_by_key, "appropriation_type")),
        "award_description": _clean_text(
            _get_value(
                row_by_key,
                "award_description",
                "transaction_description",
                "prime_award_base_transaction_description",
            )
        ),
        "transaction_description": transaction_description,
        "prime_award_base_transaction_description": prime_award_base_transaction_description,
        "product_or_service_code": _clean_text(_get_value(row_by_key, "product_or_service_code")),
        "product_or_service_code_description": _clean_text(
            _get_value(row_by_key, "product_or_service_code_description")
        ),
        "naics_code": _clean_text(_get_value(row_by_key, "naics_code")),
        "naics_description": _clean_text(_get_value(row_by_key, "naics_description")),
        "contract_award_type": _clean_text(
            _get_value(row_by_key, "contract_award_type", "award_type")
        ),
        "contract_transaction_type": _clean_text(
            _get_value(row_by_key, "contract_transaction_type", "action_type")
        ),
        "award_type": _clean_text(_get_value(row_by_key, "award_type")),
        "action_type": _clean_text(_get_value(row_by_key, "action_type")),
        "idv_type": _clean_text(_get_value(row_by_key, "idv_type")),
        "idv_reference": _clean_text(
            _get_value(row_by_key, "idv_reference", "parent_award_id_piid")
        ),
        "legal_entity_country_code": _clean_text(
            _get_value(row_by_key, "legal_entity_country_code", "recipient_country_code")
        ),
        "legal_entity_state_code": _clean_text(
            _get_value(row_by_key, "legal_entity_state_code", "recipient_state_code")
        ),
        "normalized_recipient_state": normalized_recipient_state,
        "normalized_federal_account_symbol": normalized_federal_accounts,
        "usaspending_permalink": _clean_text(_get_value(row_by_key, "usaspending_permalink")),
    }


def parse_contract_csv_file(
    path: Path,
    *,
    inspection: FileInspection | None = None,
) -> tuple[list[dict[str, Any]], FileParseStats, str]:
    structure = inspection or inspect_contract_csv(path)
    records: list[dict[str, Any]] = []
    stats = FileParseStats()

    with path.open("r", encoding=structure.encoding, newline="") as handle:
        reader = csv.reader(handle)
        header_row = next(reader, [])
        stats.total_csv_rows = 1
        expected_len = len(header_row)

        for row_number, raw_row in enumerate(reader, start=2):
            stats.total_csv_rows += 1
            row = _coerce_row_width(
                list(raw_row),
                expected_len=expected_len,
                stats=stats,
                path=path,
                row_number=row_number,
            )
            raw_row_json = dict(zip(header_row, row, strict=True))
            if not any(_clean_text(value) is not None for value in raw_row_json.values()):
                stats.blank_rows += 1
                continue

            row_by_key = {
                _normalize_header_key(key): value
                for key, value in raw_row_json.items()
                if key is not None
            }
            record = _build_contract_record(
                raw_row_json,
                row_by_key,
                source_path=path,
                row_number=row_number,
                stats=stats,
            )
            records.append(record)
            stats.loaded_rows += 1

    return records, stats, structure.encoding


def _field_value_for_rule(record: dict[str, Any], field_name: str) -> str | None:
    if field_name not in SUPPORTED_MATCH_FIELDS:
        return None
    return _clean_text(record.get(field_name))


def _rule_matches(record: dict[str, Any], rule: dict[str, Any]) -> bool:
    field_value = _field_value_for_rule(record, str(rule.get("match_field") or ""))
    if field_value is None:
        return False

    normalized_value = field_value.lower()
    match_value = _clean_text(rule.get("match_value"))
    if match_value is None:
        return False
    normalized_match_value = match_value.lower()
    match_type = str(rule.get("match_type") or "").strip().lower()

    if match_type == "contains":
        return normalized_match_value in normalized_value
    if match_type == "equals":
        return normalized_value == normalized_match_value
    if match_type == "starts_with":
        return normalized_value.startswith(normalized_match_value)
    if match_type == "regex":
        return re.search(match_value, field_value, flags=re.IGNORECASE) is not None
    return False


def _fallback_contract_category(record: dict[str, Any]) -> str:
    for field_name in (
        "award_description",
        "product_or_service_code",
        "product_or_service_code_description",
        "naics_code",
        "naics_description",
        "normalized_federal_account_symbol",
        "funding_agency_name",
        "awarding_agency_name",
    ):
        if _clean_text(record.get(field_name)) is not None:
            return CATEGORY_OTHER
    return CATEGORY_UNKNOWN


def classify_contract_record(
    record: dict[str, Any],
    *,
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    active_rules = [
        rule
        for rule in (rules or DEFAULT_CONTRACT_CATEGORY_RULES)
        if bool(rule.get("is_active", True))
    ]
    active_rules.sort(key=lambda rule: (int(rule.get("priority") or 0), str(rule.get("match_value") or "")))

    matched_rule = None
    for rule in active_rules:
        if _rule_matches(record, rule):
            matched_rule = rule
            break

    category = (
        str(matched_rule.get("assigned_category"))
        if matched_rule is not None
        else _fallback_contract_category(record)
    )
    likely_profile_relevant = category == CATEGORY_LIKELY_VFC

    if matched_rule is not None and likely_profile_relevant:
        reason = "Matched a conservative VFC-focused contract category rule."
    elif matched_rule is not None:
        reason = "Matched a first-pass deterministic contract category rule."
    elif category == CATEGORY_UNKNOWN:
        reason = "Insufficient award description, PSC, NAICS, or account detail for classification."
    else:
        reason = "No active rule matched; defaulted to other_contract."

    return {
        "matched_rule": matched_rule,
        "contract_category_guess": category,
        "likely_profile_relevant": likely_profile_relevant,
        "profile_relevance_reason": reason,
    }


def _award_key(record: dict[str, Any]) -> str | None:
    for field_name in ("generated_unique_award_id", "contract_award_unique_key", "award_id_piid"):
        token = _clean_text(record.get(field_name))
        if token is not None:
            return token
    return None


def _split_account_symbols(value: Any) -> list[str]:
    token = _canonicalize_account_list(value)
    if token is None:
        return []
    return [piece for piece in token.split(";") if piece]


def build_state_year_summary_rows(
    records: list[dict[str, Any]],
    *,
    rules: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    accumulators: dict[tuple[Any, ...], dict[str, Any]] = {}

    for record in records:
        classification = classify_contract_record(record, rules=rules)
        key = (
            record.get("fiscal_year"),
            record.get("normalized_recipient_state") or record.get("recipient_state_code"),
            record.get("normalized_federal_account_symbol") or record.get("federal_account_symbol"),
            record.get("funding_agency_name"),
            record.get("awarding_agency_name"),
            classification["contract_category_guess"],
        )
        accumulator = accumulators.get(key)
        if accumulator is None:
            accumulator = {
                "fiscal_year": key[0],
                "recipient_state_code": key[1],
                "federal_account_symbol": key[2],
                "funding_agency_name": key[3],
                "awarding_agency_name": key[4],
                "contract_category_guess": key[5],
                "total_transaction_obligated_amount": Decimal("0.00"),
                "transaction_count": 0,
                "unique_awards": set(),
            }
            accumulators[key] = accumulator

        accumulator["total_transaction_obligated_amount"] += record.get(
            "transaction_obligated_amount"
        ) or Decimal("0.00")
        accumulator["transaction_count"] += 1
        award_key = _award_key(record)
        if award_key is not None:
            accumulator["unique_awards"].add(award_key)

    rows: list[dict[str, Any]] = []
    for accumulator in sorted(
        accumulators.values(),
        key=lambda row: (
            row["fiscal_year"] or 0,
            row["recipient_state_code"] or "",
            row["federal_account_symbol"] or "",
            row["contract_category_guess"] or "",
        ),
    ):
        rows.append(
            {
                "fiscal_year": accumulator["fiscal_year"],
                "recipient_state_code": accumulator["recipient_state_code"],
                "federal_account_symbol": accumulator["federal_account_symbol"],
                "funding_agency_name": accumulator["funding_agency_name"],
                "awarding_agency_name": accumulator["awarding_agency_name"],
                "contract_category_guess": accumulator["contract_category_guess"],
                "total_transaction_obligated_amount": accumulator["total_transaction_obligated_amount"].quantize(
                    Decimal("0.01")
                ),
                "transaction_count": accumulator["transaction_count"],
                "unique_award_count": len(accumulator["unique_awards"]),
            }
        )
    return rows


def build_federal_account_inventory_rows(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    accumulators: dict[str, dict[str, Any]] = {}

    for record in records:
        award_key = _award_key(record)
        for account_symbol in _split_account_symbols(
            record.get("normalized_federal_account_symbol") or record.get("federal_account_symbol")
        ):
            accumulator = accumulators.get(account_symbol)
            if accumulator is None:
                accumulator = {
                    "federal_account_symbol": account_symbol,
                    "treasury_account_symbols": set(),
                    "appropriation_types": set(),
                    "first_fiscal_year": None,
                    "last_fiscal_year": None,
                    "total_transaction_obligated_amount": Decimal("0.00"),
                    "transaction_count": 0,
                    "unique_awards": set(),
                }
                accumulators[account_symbol] = accumulator

            treasury_symbol = _clean_text(record.get("treasury_account_symbol"))
            if treasury_symbol is not None:
                accumulator["treasury_account_symbols"].add(treasury_symbol)
            appropriation_type = _clean_text(record.get("appropriation_type"))
            if appropriation_type is not None:
                accumulator["appropriation_types"].add(appropriation_type)

            fiscal_year = record.get("fiscal_year")
            if fiscal_year is not None:
                if accumulator["first_fiscal_year"] is None or fiscal_year < accumulator["first_fiscal_year"]:
                    accumulator["first_fiscal_year"] = fiscal_year
                if accumulator["last_fiscal_year"] is None or fiscal_year > accumulator["last_fiscal_year"]:
                    accumulator["last_fiscal_year"] = fiscal_year

            accumulator["total_transaction_obligated_amount"] += record.get(
                "transaction_obligated_amount"
            ) or Decimal("0.00")
            accumulator["transaction_count"] += 1
            if award_key is not None:
                accumulator["unique_awards"].add(award_key)

    rows: list[dict[str, Any]] = []
    for account_symbol in sorted(accumulators):
        accumulator = accumulators[account_symbol]
        rows.append(
            {
                "federal_account_symbol": account_symbol,
                "treasury_account_symbol": "; ".join(sorted(accumulator["treasury_account_symbols"])) or None,
                "appropriation_type": "; ".join(sorted(accumulator["appropriation_types"])) or None,
                "first_fiscal_year": accumulator["first_fiscal_year"],
                "last_fiscal_year": accumulator["last_fiscal_year"],
                "total_transaction_obligated_amount": accumulator["total_transaction_obligated_amount"].quantize(
                    Decimal("0.01")
                ),
                "transaction_count": accumulator["transaction_count"],
                "unique_award_count": len(accumulator["unique_awards"]),
            }
        )
    return rows


def _serialize_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize_json_value(item) for item in value]
    return value


def build_summary_snapshot(
    records: list[dict[str, Any]],
    *,
    validation_summary: dict[str, Any],
    file_stats: dict[str, FileParseStats],
    files_processed: list[str],
) -> dict[str, Any]:
    obligations_by_fiscal_year: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    obligations_by_state: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    distinct_federal_accounts: set[str] = set()
    distinct_funding_agencies: set[str] = set()
    distinct_awarding_agencies: set[str] = set()
    category_counts: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "transaction_count": 0,
            "total_transaction_obligated_amount": Decimal("0.00"),
        }
    )

    min_fiscal_year = None
    max_fiscal_year = None
    likely_profile_relevant_total_amount = Decimal("0.00")

    for record in records:
        fiscal_year = record.get("fiscal_year")
        amount = record.get("transaction_obligated_amount") or Decimal("0.00")
        state_code = record.get("normalized_recipient_state") or record.get("recipient_state_code")
        classification = classify_contract_record(record)

        if fiscal_year is not None:
            obligations_by_fiscal_year[int(fiscal_year)] += amount
            min_fiscal_year = fiscal_year if min_fiscal_year is None else min(min_fiscal_year, fiscal_year)
            max_fiscal_year = fiscal_year if max_fiscal_year is None else max(max_fiscal_year, fiscal_year)
        if state_code is not None:
            obligations_by_state[str(state_code)] += amount

        distinct_federal_accounts.update(
            _split_account_symbols(record.get("normalized_federal_account_symbol") or record.get("federal_account_symbol"))
        )
        funding_agency = _clean_text(record.get("funding_agency_name"))
        if funding_agency is not None:
            distinct_funding_agencies.add(funding_agency)
        awarding_agency = _clean_text(record.get("awarding_agency_name"))
        if awarding_agency is not None:
            distinct_awarding_agencies.add(awarding_agency)

        category_bucket = category_counts[classification["contract_category_guess"]]
        category_bucket["transaction_count"] += 1
        category_bucket["total_transaction_obligated_amount"] += amount

        if classification["likely_profile_relevant"]:
            likely_profile_relevant_total_amount += amount

    return {
        "status": "dry_run",
        "schema": USASPENDING_SCHEMA,
        "files_discovered": validation_summary["files_discovered"],
        "matching_files": validation_summary["matching_files"],
        "skipped_nonmatching_files": validation_summary["skipped_nonmatching_files"],
        "files_processed": files_processed,
        "total_rows_loaded": len(records),
        "min_fiscal_year": min_fiscal_year,
        "max_fiscal_year": max_fiscal_year,
        "total_obligations_by_fiscal_year": [
            {"fiscal_year": fiscal_year, "total_transaction_obligated_amount": total}
            for fiscal_year, total in sorted(obligations_by_fiscal_year.items())
        ],
        "total_obligations_by_recipient_state": [
            {"recipient_state_code": state_code, "total_transaction_obligated_amount": total}
            for state_code, total in sorted(obligations_by_state.items())
        ],
        "distinct_federal_account_symbols_observed": sorted(distinct_federal_accounts),
        "distinct_funding_agencies_observed": sorted(distinct_funding_agencies),
        "distinct_awarding_agencies_observed": sorted(distinct_awarding_agencies),
        "category_guess_counts": [
            {
                "contract_category_guess": category,
                **payload,
            }
            for category, payload in sorted(category_counts.items())
        ],
        "likely_profile_relevant_total_amount": likely_profile_relevant_total_amount,
        "header_discrepancies": validation_summary["header_discrepancies"],
        "file_level_anomalies": [
            {
                "filename": filename,
                "total_csv_rows": stats.total_csv_rows,
                "loaded_rows": stats.loaded_rows,
                "blank_rows": stats.blank_rows,
                "anomalies": stats.anomalies,
            }
            for filename, stats in sorted(file_stats.items())
        ],
    }


def _enriched_view_sql() -> str:
    field_expression = """
        CASE rules.match_field
            WHEN 'award_description' THEN COALESCE(raw.award_description, '')
            WHEN 'product_or_service_code' THEN COALESCE(raw.product_or_service_code, '')
            WHEN 'product_or_service_code_description' THEN COALESCE(raw.product_or_service_code_description, '')
            WHEN 'naics_code' THEN COALESCE(raw.naics_code, '')
            WHEN 'naics_description' THEN COALESCE(raw.naics_description, '')
            WHEN 'federal_account_symbol' THEN COALESCE(raw.federal_account_symbol, '')
            WHEN 'normalized_federal_account_symbol' THEN COALESCE(raw.normalized_federal_account_symbol, '')
            WHEN 'funding_agency_name' THEN COALESCE(raw.funding_agency_name, '')
            WHEN 'awarding_agency_name' THEN COALESCE(raw.awarding_agency_name, '')
            WHEN 'contract_award_type' THEN COALESCE(raw.contract_award_type, '')
            WHEN 'contract_transaction_type' THEN COALESCE(raw.contract_transaction_type, '')
            ELSE ''
        END
    """

    category_expression = """
        COALESCE(
            matched_rule.assigned_category,
            CASE
                WHEN COALESCE(raw.award_description, raw.product_or_service_code, raw.product_or_service_code_description,
                              raw.naics_code, raw.naics_description, raw.normalized_federal_account_symbol,
                              raw.funding_agency_name, raw.awarding_agency_name) IS NOT NULL
                    THEN 'other_contract'
                ELSE 'unknown'
            END
        )
    """

    return f"""
        CREATE OR REPLACE VIEW {ENRICHED_VIEW_FQTN} AS
        WITH ranked_rules AS (
            SELECT
                raw.id AS raw_id,
                rules.rule_id,
                rules.priority,
                rules.match_field,
                rules.match_type,
                rules.match_value,
                rules.assigned_category,
                rules.notes,
                ROW_NUMBER() OVER (
                    PARTITION BY raw.id
                    ORDER BY rules.priority ASC, rules.rule_id ASC
                ) AS rn
            FROM {RAW_TABLE_FQTN} AS raw
            JOIN {usaspending_table("contract_category_rules")} AS rules
                ON rules.is_active = TRUE
               AND rules.match_field IN ({", ".join(f"'{field}'" for field in sorted(SUPPORTED_MATCH_FIELDS))})
               AND CASE
                    WHEN rules.match_type = 'contains'
                        THEN LOWER({field_expression}) LIKE '%' || LOWER(rules.match_value) || '%'
                    WHEN rules.match_type = 'equals'
                        THEN LOWER({field_expression}) = LOWER(rules.match_value)
                    WHEN rules.match_type = 'starts_with'
                        THEN LOWER({field_expression}) LIKE LOWER(rules.match_value) || '%'
                    WHEN rules.match_type = 'regex'
                        THEN {field_expression} ~* rules.match_value
                    ELSE FALSE
               END
        ),
        matched_rule AS (
            SELECT *
            FROM ranked_rules
            WHERE rn = 1
        )
        SELECT
            raw.*,
            matched_rule.rule_id AS matched_rule_id,
            matched_rule.priority AS matched_rule_priority,
            matched_rule.match_field AS matched_rule_field,
            matched_rule.match_type AS matched_rule_type,
            matched_rule.match_value AS matched_rule_value,
            matched_rule.notes AS matched_rule_notes,
            {category_expression} AS contract_category_guess,
            ({category_expression} = '{CATEGORY_LIKELY_VFC}') AS likely_profile_relevant,
            CASE
                WHEN {category_expression} = '{CATEGORY_LIKELY_VFC}' AND matched_rule.rule_id IS NOT NULL
                    THEN 'Matched a conservative VFC-focused contract category rule.'
                WHEN matched_rule.rule_id IS NOT NULL
                    THEN 'Matched a first-pass deterministic contract category rule.'
                WHEN {category_expression} = '{CATEGORY_UNKNOWN}'
                    THEN 'Insufficient award description, PSC, NAICS, or account detail for classification.'
                ELSE 'No active rule matched; defaulted to other_contract.'
            END AS profile_relevance_reason
        FROM {RAW_TABLE_FQTN} AS raw
        LEFT JOIN matched_rule
            ON matched_rule.raw_id = raw.id
    """


def create_schema_objects(connection: Any, *, drop_and_recreate: bool = False) -> None:
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {USASPENDING_SCHEMA}"))
    if drop_and_recreate:
        connection.execute(text(f"DROP VIEW IF EXISTS {ENRICHED_VIEW_FQTN}"))
        for table in reversed(CURRENT_TABLES):
            table.drop(bind=connection, checkfirst=True)
    for table in CURRENT_TABLES:
        table.create(bind=connection, checkfirst=True)
    connection.execute(text(_enriched_view_sql()))


def truncate_contract_tables(connection: Any) -> None:
    connection.execute(text(f"TRUNCATE TABLE {STATE_SUMMARY_FQTN} RESTART IDENTITY"))
    connection.execute(text(f"TRUNCATE TABLE {ACCOUNT_INVENTORY_FQTN}"))
    connection.execute(text(f"TRUNCATE TABLE {RAW_TABLE_FQTN} RESTART IDENTITY"))


def bootstrap_contract_category_rules(connection: Any) -> None:
    insert_stmt = pg_insert(CATEGORY_RULES_TABLE).values(DEFAULT_CONTRACT_CATEGORY_RULES)
    connection.execute(
        insert_stmt.on_conflict_do_nothing(
            constraint="uq_usaspending_contract_category_rules_match"
        )
    )


def replace_file_rows(
    connection: Any,
    *,
    source_filename: str,
    rows: list[dict[str, Any]],
    chunksize: int,
) -> None:
    connection.execute(
        text(f"DELETE FROM {RAW_TABLE_FQTN} WHERE source_filename = :source_filename"),
        {"source_filename": source_filename},
    )
    if not rows:
        return

    for start in range(0, len(rows), max(chunksize, 1)):
        chunk = rows[start : start + max(chunksize, 1)]
        connection.execute(RAW_TABLE.insert(), chunk)


def refresh_derived_contract_tables(connection: Any) -> None:
    connection.execute(text(_enriched_view_sql()))
    connection.execute(text(f"TRUNCATE TABLE {STATE_SUMMARY_FQTN} RESTART IDENTITY"))
    connection.execute(
        text(
            f"""
            INSERT INTO {STATE_SUMMARY_FQTN} (
                fiscal_year,
                recipient_state_code,
                federal_account_symbol,
                funding_agency_name,
                awarding_agency_name,
                contract_category_guess,
                total_transaction_obligated_amount,
                transaction_count,
                unique_award_count,
                refreshed_at
            )
            SELECT
                fiscal_year,
                COALESCE(normalized_recipient_state, recipient_state_code) AS recipient_state_code,
                COALESCE(normalized_federal_account_symbol, federal_account_symbol) AS federal_account_symbol,
                funding_agency_name,
                awarding_agency_name,
                contract_category_guess,
                COALESCE(SUM(transaction_obligated_amount), 0) AS total_transaction_obligated_amount,
                COUNT(*) AS transaction_count,
                COUNT(DISTINCT COALESCE(generated_unique_award_id, contract_award_unique_key, award_id_piid))
                    AS unique_award_count,
                NOW()
            FROM {ENRICHED_VIEW_FQTN}
            GROUP BY
                fiscal_year,
                COALESCE(normalized_recipient_state, recipient_state_code),
                COALESCE(normalized_federal_account_symbol, federal_account_symbol),
                funding_agency_name,
                awarding_agency_name,
                contract_category_guess
            """
        )
    )

    connection.execute(text(f"TRUNCATE TABLE {ACCOUNT_INVENTORY_FQTN}"))
    connection.execute(
        text(
            f"""
            WITH account_expanded AS (
                SELECT
                    NULLIF(BTRIM(account_symbol), '') AS federal_account_symbol,
                    treasury_account_symbol,
                    appropriation_type,
                    fiscal_year,
                    transaction_obligated_amount,
                    COALESCE(generated_unique_award_id, contract_award_unique_key, award_id_piid) AS award_key
                FROM {RAW_TABLE_FQTN}
                CROSS JOIN LATERAL regexp_split_to_table(
                    COALESCE(normalized_federal_account_symbol, federal_account_symbol, ''),
                    ';'
                ) AS account_symbol
            )
            INSERT INTO {ACCOUNT_INVENTORY_FQTN} (
                federal_account_symbol,
                treasury_account_symbol,
                appropriation_type,
                first_fiscal_year,
                last_fiscal_year,
                total_transaction_obligated_amount,
                transaction_count,
                unique_award_count,
                refreshed_at
            )
            SELECT
                federal_account_symbol,
                NULLIF(
                    string_agg(DISTINCT NULLIF(BTRIM(treasury_account_symbol), ''), '; '),
                    ''
                ) AS treasury_account_symbol,
                MIN(appropriation_type) FILTER (WHERE appropriation_type IS NOT NULL) AS appropriation_type,
                MIN(fiscal_year) AS first_fiscal_year,
                MAX(fiscal_year) AS last_fiscal_year,
                COALESCE(SUM(transaction_obligated_amount), 0) AS total_transaction_obligated_amount,
                COUNT(*) AS transaction_count,
                COUNT(DISTINCT award_key) AS unique_award_count,
                NOW()
            FROM account_expanded
            WHERE federal_account_symbol IS NOT NULL
            GROUP BY federal_account_symbol
            """
        )
    )


def _fetch_rows(connection: Any, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(text(sql), params).mappings().all()]


def build_db_summary(
    connection: Any,
    *,
    validation_summary: dict[str, Any],
    files_processed: list[str],
    total_rows_loaded: int,
    file_stats: dict[str, FileParseStats],
    status: str,
) -> dict[str, Any]:
    totals_by_fiscal_year = _fetch_rows(
        connection,
        f"""
        SELECT
            fiscal_year,
            COALESCE(SUM(transaction_obligated_amount), 0) AS total_transaction_obligated_amount
        FROM {RAW_TABLE_FQTN}
        GROUP BY fiscal_year
        ORDER BY fiscal_year
        """,
    )
    totals_by_state = _fetch_rows(
        connection,
        f"""
        SELECT
            COALESCE(normalized_recipient_state, recipient_state_code) AS recipient_state_code,
            COALESCE(SUM(transaction_obligated_amount), 0) AS total_transaction_obligated_amount
        FROM {RAW_TABLE_FQTN}
        GROUP BY COALESCE(normalized_recipient_state, recipient_state_code)
        ORDER BY COALESCE(normalized_recipient_state, recipient_state_code)
        """,
    )
    account_symbols = _fetch_rows(
        connection,
        f"""
        SELECT federal_account_symbol
        FROM {ACCOUNT_INVENTORY_FQTN}
        ORDER BY federal_account_symbol
        """,
    )
    funding_agencies = _fetch_rows(
        connection,
        f"""
        SELECT DISTINCT funding_agency_name
        FROM {RAW_TABLE_FQTN}
        WHERE funding_agency_name IS NOT NULL
        ORDER BY funding_agency_name
        """,
    )
    awarding_agencies = _fetch_rows(
        connection,
        f"""
        SELECT DISTINCT awarding_agency_name
        FROM {RAW_TABLE_FQTN}
        WHERE awarding_agency_name IS NOT NULL
        ORDER BY awarding_agency_name
        """,
    )
    category_counts = _fetch_rows(
        connection,
        f"""
        SELECT
            contract_category_guess,
            COUNT(*) AS transaction_count,
            COALESCE(SUM(transaction_obligated_amount), 0) AS total_transaction_obligated_amount
        FROM {ENRICHED_VIEW_FQTN}
        GROUP BY contract_category_guess
        ORDER BY contract_category_guess
        """,
    )
    min_max = _fetch_rows(
        connection,
        f"""
        SELECT MIN(fiscal_year) AS min_fiscal_year, MAX(fiscal_year) AS max_fiscal_year
        FROM {RAW_TABLE_FQTN}
        """,
    )[0]
    likely_profile_relevant = _fetch_rows(
        connection,
        f"""
        SELECT COALESCE(SUM(transaction_obligated_amount), 0) AS likely_profile_relevant_total_amount
        FROM {ENRICHED_VIEW_FQTN}
        WHERE likely_profile_relevant
        """,
    )[0]

    return {
        "status": status,
        "schema": USASPENDING_SCHEMA,
        "files_discovered": validation_summary["files_discovered"],
        "matching_files": validation_summary["matching_files"],
        "skipped_nonmatching_files": validation_summary["skipped_nonmatching_files"],
        "files_processed": files_processed,
        "total_rows_loaded": total_rows_loaded,
        "min_fiscal_year": min_max["min_fiscal_year"],
        "max_fiscal_year": min_max["max_fiscal_year"],
        "total_obligations_by_fiscal_year": totals_by_fiscal_year,
        "total_obligations_by_recipient_state": totals_by_state,
        "distinct_federal_account_symbols_observed": [
            row["federal_account_symbol"] for row in account_symbols
        ],
        "distinct_funding_agencies_observed": [row["funding_agency_name"] for row in funding_agencies],
        "distinct_awarding_agencies_observed": [row["awarding_agency_name"] for row in awarding_agencies],
        "category_guess_counts": category_counts,
        "likely_profile_relevant_total_amount": likely_profile_relevant[
            "likely_profile_relevant_total_amount"
        ],
        "header_discrepancies": validation_summary["header_discrepancies"],
        "file_level_anomalies": [
            {
                "filename": filename,
                "total_csv_rows": stats.total_csv_rows,
                "loaded_rows": stats.loaded_rows,
                "blank_rows": stats.blank_rows,
                "anomalies": stats.anomalies,
            }
            for filename, stats in sorted(file_stats.items())
        ],
    }


def write_summary_file(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_serialize_json_value(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def print_summary(summary: dict[str, Any]) -> None:
    print(json.dumps(_serialize_json_value(summary), indent=2, sort_keys=True))


def _store_ingestion_run(
    connection: Any,
    *,
    input_dir: Path,
    options: dict[str, Any],
    summary: dict[str, Any],
    status: str,
) -> None:
    connection.execute(
        INGESTION_RUNS_TABLE.insert().values(
            pipeline_name="contracts_prime_transactions",
            input_dir=str(input_dir),
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            status=status,
            files_discovered=len(summary.get("files_discovered", [])),
            files_matched=len(summary.get("matching_files", [])),
            rows_loaded=summary.get("total_rows_loaded", 0) or 0,
            options_json=_serialize_json_value(options),
            summary_json=_serialize_json_value(summary),
        )
    )


def main() -> None:
    args = parse_args()
    input_dir = _resolve_input_dir(args.input_dir)
    summary_path = _resolve_summary_path(input_dir, args.summary_path)

    files = discover_csv_files(input_dir, limit_files=args.limit_files)
    structures = [inspect_contract_csv(path) for path in files]
    validation_summary = validate_csv_headers(structures)

    summary_base = {
        "status": "started",
        "schema": USASPENDING_SCHEMA,
        "input_dir": str(input_dir),
        "files_discovered": [path.name for path in files],
        "matching_files": validation_summary["matching_files"],
        "skipped_nonmatching_files": validation_summary["skipped_nonmatching_files"],
        "header_discrepancies": validation_summary["header_discrepancies"],
    }

    if validation_summary["has_incompatible_matching_headers"]:
        summary_base["status"] = "failed_header_validation"
        write_summary_file(summary_path, summary_base)
        raise RuntimeError(
            "Contract CSV header validation failed. Matching transaction files have incompatible header sets."
        )

    matching_structures = [
        structure for structure in structures if structure.is_matching_contract_transaction
    ]
    files_processed = [structure.path.name for structure in matching_structures]

    file_stats: dict[str, FileParseStats] = {}
    all_records_for_dry_run: list[dict[str, Any]] = []

    if args.verbose:
        for structure in structures:
            kind = "matching_contract_transaction" if structure.is_matching_contract_transaction else "skipped_nonmatching_csv"
            print(
                f"{structure.path.name}: {kind} cols={len(structure.header_row)} "
                f"encoding={structure.encoding}"
            )

    if args.dry_run:
        for structure in matching_structures:
            records, stats, _encoding = parse_contract_csv_file(
                structure.path,
                inspection=structure,
            )
            file_stats[structure.path.name] = stats
            all_records_for_dry_run.extend(records)
        summary = build_summary_snapshot(
            all_records_for_dry_run,
            validation_summary=validation_summary,
            file_stats=file_stats,
            files_processed=files_processed,
        )
        write_summary_file(summary_path, summary)
        print_summary(summary)
        return

    engine = create_engine(args.db_url, future=True)
    options_payload = {
        "truncate": args.truncate,
        "drop_and_recreate": args.drop_and_recreate,
        "dry_run": args.dry_run,
        "limit_files": args.limit_files,
        "rebuild_summaries": args.rebuild_summaries,
    }

    try:
        total_rows_loaded = 0
        with engine.begin() as connection:
            create_schema_objects(connection, drop_and_recreate=args.drop_and_recreate)
            bootstrap_contract_category_rules(connection)
            if args.truncate:
                truncate_contract_tables(connection)

            for structure in matching_structures:
                records, stats, _encoding = parse_contract_csv_file(
                    structure.path,
                    inspection=structure,
                )
                file_stats[structure.path.name] = stats
                replace_file_rows(
                    connection,
                    source_filename=structure.path.name,
                    rows=records,
                    chunksize=args.chunksize,
                )
                total_rows_loaded += len(records)

            if args.rebuild_summaries:
                refresh_derived_contract_tables(connection)
            else:
                connection.execute(text(_enriched_view_sql()))

            summary = build_db_summary(
                connection,
                validation_summary=validation_summary,
                files_processed=files_processed,
                total_rows_loaded=total_rows_loaded,
                file_stats=file_stats,
                status="succeeded",
            )
            _store_ingestion_run(
                connection,
                input_dir=input_dir,
                options=options_payload,
                summary=summary,
                status="succeeded",
            )

        write_summary_file(summary_path, summary)
        print_summary(summary)
    except Exception as exc:
        failed_summary = {
            **summary_base,
            "status": "failed",
            "error": str(exc),
            "file_level_anomalies": [
                {
                    "filename": filename,
                    "total_csv_rows": stats.total_csv_rows,
                    "loaded_rows": stats.loaded_rows,
                    "blank_rows": stats.blank_rows,
                    "anomalies": stats.anomalies,
                }
                for filename, stats in sorted(file_stats.items())
            ],
        }
        write_summary_file(summary_path, failed_summary)
        try:
            with engine.begin() as connection:
                create_schema_objects(connection, drop_and_recreate=False)
                _store_ingestion_run(
                    connection,
                    input_dir=input_dir,
                    options=options_payload,
                    summary=failed_summary,
                    status="failed",
                )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
