from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.cdc_funding.appropriation import (
    APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL,
    APPROPRIATION_CLASSIFIER_VERSION,
    APPROPRIATION_TYPE_UNKNOWN,
    classify_official_emergency_code,
)
from app.db_fqtn import cdc_funding_table, places_table
from app.db_schemas import CDC_FUNDING_SCHEMA

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_CHUNKSIZE = 1000
CDC_MIN_FISCAL_YEAR = 2000
CDC_MAX_FISCAL_YEAR = 2100
DISCOVERY_GLOB_BY_RECORD_TYPE = {
    "prime_award": "Assistance_PrimeAwardSummaries_*.csv",
    "prime_transaction": "Assistance_PrimeTransactions_*.csv",
    "subaward": "Assistance_Subawards_*.csv",
}
_FILENAME_FY_PATTERNS = (
    re.compile(r"(?i)(?:^|[^A-Za-z0-9])FY[_\-\s]?(?P<yy>\d{2}|20\d{2})(?:[^A-Za-z0-9]|$)"),
    re.compile(
        r"(?i)(?:^|[^A-Za-z0-9])fiscal[_\-\s]?year[_\-\s]?(?P<year>20\d{2})(?:[^A-Za-z0-9]|$)"
    ),
)

PRIME_FILENAME = "Assistance_PrimeAwardSummaries_2026-03-07_H14M24S59_1.csv"
PRIME_TRANSACTIONS_FILENAME = "Assistance_PrimeTransactions_2026-03-07_H14M31S18_1.csv"
SUBAWARD_FILENAME = "Assistance_Subawards_2026-03-07_H14M29S16_1.csv"

PRIME_TABLE = cdc_funding_table("prime_awards")
PRIME_TRANSACTIONS_TABLE = cdc_funding_table("prime_transactions")
SUBAWARD_TABLE = cdc_funding_table("subawards")
PRIME_STATE_SUMMARY_TABLE = cdc_funding_table("prime_state_summary")
PRIME_COUNTY_SUMMARY_TABLE = cdc_funding_table("prime_county_summary")
PRIME_TX_STATE_SUMMARY_TABLE = cdc_funding_table("prime_transaction_state_summary")
PRIME_TX_COUNTY_SUMMARY_TABLE = cdc_funding_table("prime_transaction_county_summary")
PRIME_TX_COUNTY_ALLOCATED_SUMMARY_TABLE = cdc_funding_table(
    "prime_transaction_county_summary_allocated"
)
PRIME_TX_NATIONAL_SUMMARY_TABLE = cdc_funding_table("prime_transaction_national_summary")
SUBAWARD_STATE_SUMMARY_TABLE = cdc_funding_table("subaward_state_summary")
SUBAWARD_COUNTY_SUMMARY_TABLE = cdc_funding_table("subaward_county_summary")
SUBAWARD_NATIONAL_SUMMARY_TABLE = cdc_funding_table("subaward_national_summary")
AWARD_SCOPE_CLASSIFICATION_TABLE = cdc_funding_table("award_scope_classification")
APPROPRIATION_CLASSIFICATION_TABLE = cdc_funding_table("appropriation_classification")
COUNTY_DIM_TABLE = places_table("dim_county")
POPULATION_VIEW_TABLE = places_table("v_geography_population")

SCOPE_CLASSIFIER_VERSION = "v1"
SCOPE_CLASS_DEFAULT_ALLOCATION_METHOD = "total_population"

STATEWIDE_SCORE_THRESHOLD = 6
LOCAL_SCORE_THRESHOLD = 4
MULTI_STATE_SCORE_THRESHOLD = 5
MULTI_COUNTY_SCORE_THRESHOLD = 4

STATE_HEALTH_AGENCY_PATTERNS = (
    re.compile(r"\bstate of\b", re.IGNORECASE),
    re.compile(r"\bdepartment of health\b", re.IGNORECASE),
    re.compile(r"\bdept(?:artment)? of health\b", re.IGNORECASE),
    re.compile(r"\bdepartment of public health\b", re.IGNORECASE),
    re.compile(r"\bdepartment of human services\b", re.IGNORECASE),
)

LOCAL_RECIPIENT_PATTERNS = (
    re.compile(r"\bcounty\b", re.IGNORECASE),
    re.compile(r"\bcity of\b", re.IGNORECASE),
    re.compile(r"\bmunicipal\b", re.IGNORECASE),
    re.compile(r"\bparish\b", re.IGNORECASE),
)

MULTI_STATE_RECIPIENT_PATTERNS = (
    re.compile(r"\bnational\b", re.IGNORECASE),
    re.compile(r"\binterstate\b", re.IGNORECASE),
    re.compile(r"\bmulti[\s-]?state\b", re.IGNORECASE),
    re.compile(r"\bconsortium\b", re.IGNORECASE),
)

STATEWIDE_DESC_CLUES = (
    "statewide",
    "across the state",
    "state program",
    "state public health system",
)

STATE_CAPACITY_CLUES = (
    "state capacity",
    "state infrastructure",
    "statewide infrastructure",
    "public health infrastructure",
)

LOCAL_DESC_CLUES = (
    "county",
    "city",
    "district",
    "local",
    "community-based",
    "municipal",
    "parish",
)

MULTI_STATE_DESC_CLUES = (
    "regional",
    "multi-state",
    "interstate",
    "national",
    "consortium",
    "network",
)

MULTI_COUNTY_DESC_CLUES = (
    "multi-county",
    "multiple counties",
    "across counties",
)

BLOCK_GRANT_CLUES = ("block grant",)

NULL_TOKENS = {
    "",
    "na",
    "n/a",
    "null",
    "none",
    "nan",
    "sai unavailable",
    "sai not available",
}

CFDA_ENTRY_RE = re.compile(r"(?P<num>\d{2}\.\d{3})\s*[:\-]\s*(?P<title>.+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Ingest CDC assistance funding CSVs into schema {CDC_FUNDING_SCHEMA}."
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL env var or local default).",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory containing CDC spending files (defaults to data/spending/cdc).",
    )
    parser.add_argument(
        "--prime-path",
        default=None,
        help=f"Optional explicit path to {PRIME_FILENAME}.",
    )
    parser.add_argument(
        "--transaction-path",
        default=None,
        help=f"Optional explicit path to {PRIME_TRANSACTIONS_FILENAME}.",
    )
    parser.add_argument(
        "--subaward-path",
        default=None,
        help=f"Optional explicit path to {SUBAWARD_FILENAME}.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"Upsert batch size (default: {DEFAULT_CHUNKSIZE}).",
    )
    parser.add_argument(
        "--fiscal-year",
        "--year",
        dest="fiscal_years",
        action="append",
        type=int,
        default=[],
        help=(
            "Optional fiscal year to ingest (repeatable). "
            "When omitted, all discovered fiscal years are ingested."
        ),
    )
    parser.add_argument(
        "--fiscal-year-range",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        default=None,
        help="Optional inclusive fiscal year range to ingest (for example: --fiscal-year-range 2020 2026).",
    )
    parser.add_argument(
        "--list-discovered",
        action="store_true",
        help="List discovered CDC funding files and inferred fiscal years, then exit.",
    )
    return parser.parse_args()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    if token.lower() in NULL_TOKENS:
        return None
    return token or None


def _normalize_state_code(value: Any) -> str | None:
    token = _clean_text(value)
    if token is None:
        return None
    letters = re.sub(r"[^A-Za-z]", "", token).upper()
    if len(letters) == 2:
        return letters
    return None


def _normalize_fips(value: Any, *, length: int) -> str | None:
    token = _clean_text(value)
    if token is None:
        return None
    digits = re.sub(r"[^0-9]", "", token)
    if not digits or len(digits) > length:
        return None
    normalized = digits.zfill(length)
    if not re.fullmatch(rf"\d{{{length}}}", normalized):
        return None
    return normalized


def _parse_int(value: Any) -> int | None:
    token = _clean_text(value)
    if token is None:
        return None
    try:
        parsed = int(token)
    except ValueError:
        return None
    return parsed


def _parse_decimal(value: Any) -> Decimal | None:
    token = _clean_text(value)
    if token is None:
        return None
    compact = token.replace(",", "")
    try:
        parsed = Decimal(compact)
    except InvalidOperation:
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _parse_date(value: Any) -> date | None:
    token = _clean_text(value)
    if token is None:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_fiscal_year(value: Any) -> int | None:
    parsed = _parse_int(value)
    if parsed is None:
        return None
    if parsed < CDC_MIN_FISCAL_YEAR or parsed > CDC_MAX_FISCAL_YEAR:
        return None
    return parsed


def _infer_fiscal_year_from_date(value: Any) -> int | None:
    parsed = _parse_date(value)
    if parsed is None:
        return None
    # Federal FY starts on Oct 1.
    return parsed.year + 1 if parsed.month >= 10 else parsed.year


def _normalize_requested_fiscal_years(
    *,
    fiscal_years: list[int] | None,
    fiscal_year_range: tuple[int, int] | None,
) -> set[int] | None:
    years: set[int] = set()
    for value in fiscal_years or []:
        normalized = _normalize_fiscal_year(value)
        if normalized is None:
            raise ValueError(f"Invalid fiscal year: {value}")
        years.add(normalized)

    if fiscal_year_range:
        start = _normalize_fiscal_year(fiscal_year_range[0])
        end = _normalize_fiscal_year(fiscal_year_range[1])
        if start is None or end is None:
            raise ValueError(f"Invalid fiscal year range: {fiscal_year_range}")
        if start > end:
            start, end = end, start
        years.update(range(start, end + 1))

    return years or None


def _filename_fiscal_years(path: Path) -> set[int]:
    years: set[int] = set()
    name = path.name
    for pattern in _FILENAME_FY_PATTERNS:
        for match in pattern.finditer(name):
            token = match.groupdict().get("year") or match.groupdict().get("yy")
            if token is None:
                continue
            if len(token) == 2:
                token = f"20{token}"
            normalized = _normalize_fiscal_year(token)
            if normalized is not None:
                years.add(normalized)
    return years


def _is_supported_source_csv(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() != ".csv":
        return False
    # Skip Windows ADS metadata files committed from ZIP exports.
    if path.name.endswith(":Zone.Identifier"):
        return False
    return True


def discover_source_files(data_dir: Path) -> dict[str, list[dict[str, Any]]]:
    discovered: dict[str, list[dict[str, Any]]] = {
        "prime_award": [],
        "prime_transaction": [],
        "subaward": [],
    }
    for record_type, pattern in DISCOVERY_GLOB_BY_RECORD_TYPE.items():
        for path in sorted(data_dir.rglob(pattern)):
            if not _is_supported_source_csv(path):
                continue
            discovered[record_type].append(
                {
                    "path": path.resolve(),
                    "filename_fiscal_years": sorted(_filename_fiscal_years(path)),
                }
            )
    return discovered


def _validate_required_columns(
    *,
    path: Path,
    header_columns: list[str] | None,
    required_columns: dict[str, tuple[str, ...]],
) -> None:
    header = {str(column).strip() for column in (header_columns or []) if column is not None}
    missing: list[str] = []
    for logical_name, aliases in required_columns.items():
        if not any(alias in header for alias in aliases):
            missing.append(f"{logical_name} ({', '.join(aliases)})")
    if missing:
        missing_text = "; ".join(missing)
        raise ValueError(
            f"CSV {path} is missing required column(s): {missing_text}. "
            "Check USAspending export schema mapping."
        )


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            value = row.get(key)
            cleaned = _clean_text(value)
            if cleaned is not None:
                return cleaned
    return None


def _extract_cfda_program(value: Any) -> tuple[str | None, str | None]:
    token = _clean_text(value)
    if token is None:
        return (None, None)

    for chunk in re.split(r"\s*[;|]\s*", token):
        match = CFDA_ENTRY_RE.match(chunk.strip())
        if match:
            num = _clean_text(match.group("num"))
            title = _clean_text(match.group("title"))
            return (num, title)

    fallback_match = re.search(r"\b\d{2}\.\d{3}\b", token)
    if fallback_match:
        return (fallback_match.group(0), token)
    return (None, token)


def _build_searchable_text(*parts: Any) -> str:
    output: list[str] = []
    for part in parts:
        token = _clean_text(part)
        if token is None:
            continue
        output.append(token)
    return " | ".join(output)


def _normalize_match_text(value: Any) -> str:
    token = _clean_text(value)
    if token is None:
        return ""
    return re.sub(r"\s+", " ", token).strip().lower()


def _merge_match_text(*parts: Any) -> str:
    tokens = [_normalize_match_text(part) for part in parts]
    return " | ".join(token for token in tokens if token)


def _contains_any_clue(haystack: str, clues: tuple[str, ...]) -> bool:
    if not haystack:
        return False
    return any(clue in haystack for clue in clues)


def _matches_any_pattern(haystack: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    if not haystack:
        return False
    return any(pattern.search(haystack) for pattern in patterns)


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _classify_award_scope(
    *,
    recipient_name: Any,
    assistance_type_description: Any,
    recipient_state_code: Any,
    recipient_county_fips: Any,
    transaction_descriptions: Any,
    transaction_base_descriptions: Any,
    transaction_cfda_titles: Any,
    prime_award_base_transaction_description: Any,
    cfda_program_title: Any,
) -> dict[str, Any]:
    recipient_text = _normalize_match_text(recipient_name)
    description_text = _merge_match_text(
        transaction_descriptions,
        transaction_base_descriptions,
        prime_award_base_transaction_description,
        transaction_cfda_titles,
        cfda_program_title,
    )
    program_text = _merge_match_text(cfda_program_title, transaction_cfda_titles, assistance_type_description)

    statewide_score = 0
    local_score = 0
    multi_state_score = 0
    multi_county_score = 0
    reasons: list[str] = []

    if _matches_any_pattern(recipient_text, STATE_HEALTH_AGENCY_PATTERNS):
        statewide_score += 4
        _append_reason(reasons, "STATE_HEALTH_AGENCY")

    if _matches_any_pattern(recipient_text, LOCAL_RECIPIENT_PATTERNS):
        local_score += 3
        _append_reason(reasons, "RECIPIENT_LOCAL_ENTITY")

    if _matches_any_pattern(recipient_text, MULTI_STATE_RECIPIENT_PATTERNS):
        multi_state_score += 4
        _append_reason(reasons, "RECIPIENT_MULTI_STATE_ENTITY")

    if _contains_any_clue(description_text, STATEWIDE_DESC_CLUES):
        statewide_score += 5
        _append_reason(reasons, "DESC_STATEWIDE")

    if _contains_any_clue(description_text, STATE_CAPACITY_CLUES):
        statewide_score += 2
        _append_reason(reasons, "DESC_STATE_CAPACITY")

    if _contains_any_clue(description_text, LOCAL_DESC_CLUES):
        local_score += 3
        _append_reason(reasons, "DESC_LOCAL")

    if _contains_any_clue(description_text, MULTI_STATE_DESC_CLUES):
        multi_state_score += 5
        _append_reason(reasons, "DESC_REGIONAL")

    if _contains_any_clue(description_text, MULTI_COUNTY_DESC_CLUES):
        multi_county_score += 4
        _append_reason(reasons, "DESC_MULTI_COUNTY")

    if _contains_any_clue(program_text, BLOCK_GRANT_CLUES):
        statewide_score += 3
        _append_reason(reasons, "PROGRAM_BLOCK_GRANT")

    normalized_state_code = _normalize_state_code(recipient_state_code)
    normalized_county_fips = _normalize_fips(recipient_county_fips, length=5)

    if normalized_state_code and not normalized_county_fips:
        statewide_score += 2
        _append_reason(reasons, "COUNTY_MISSING_STATE_PRESENT")
    if normalized_county_fips:
        local_score += 2
        _append_reason(reasons, "COUNTY_PRESENT")
    if not normalized_state_code and not normalized_county_fips:
        _append_reason(reasons, "GEOGRAPHY_MISSING")

    class_scores = {
        "statewide": statewide_score,
        "local_county": local_score,
        "multi_county": multi_county_score,
        "multi_state": multi_state_score,
    }

    # Explicit thresholds keep this deterministic and easy to tune:
    # - statewide: score >= 6 and not overridden by stronger local/regional cues
    # - local_county: score >= 4
    # - multi_state: score >= 5 (takes precedence over statewide/local)
    # - multi_county: score >= 4 when explicit multi-county language is present
    if (
        multi_state_score >= MULTI_STATE_SCORE_THRESHOLD
        and multi_state_score >= statewide_score
        and multi_state_score >= local_score
        and multi_state_score >= multi_county_score
    ):
        scope_classification = "multi_state"
    elif (
        multi_county_score >= MULTI_COUNTY_SCORE_THRESHOLD
        and multi_county_score >= local_score
        and multi_state_score < MULTI_STATE_SCORE_THRESHOLD
    ):
        scope_classification = "multi_county"
    elif (
        statewide_score >= STATEWIDE_SCORE_THRESHOLD
        and statewide_score >= (local_score + 1)
        and multi_state_score < MULTI_STATE_SCORE_THRESHOLD
    ):
        scope_classification = "statewide"
    elif local_score >= LOCAL_SCORE_THRESHOLD and local_score >= statewide_score:
        scope_classification = "local_county"
    else:
        scope_classification = "unknown"
        if not reasons:
            _append_reason(reasons, "NO_STRONG_SIGNALS")

    sorted_scores = sorted(class_scores.values(), reverse=True)
    top_score = sorted_scores[0] if sorted_scores else 0
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0
    score_margin = top_score - second_score

    if scope_classification == "unknown":
        scope_confidence = "low"
    elif top_score >= 9 and score_margin >= 3:
        scope_confidence = "high"
    elif top_score >= 6 and score_margin >= 2:
        scope_confidence = "medium"
    else:
        scope_confidence = "low"

    if scope_classification == "unknown" and top_score == 0:
        scope_score = 0
    else:
        scope_score = class_scores.get(scope_classification, top_score)

    return {
        "scope_classification": scope_classification,
        "scope_score": int(scope_score),
        "scope_confidence": scope_confidence,
        "reason_codes": reasons,
        "is_allocatable_to_counties": scope_classification == "statewide",
        "allocation_method_default": (
            SCOPE_CLASS_DEFAULT_ALLOCATION_METHOD
            if scope_classification == "statewide"
            else None
        ),
        "classifier_version": SCOPE_CLASSIFIER_VERSION,
    }


def _chunks(items: list[dict[str, Any]], chunk_size: int) -> Iterable[list[dict[str, Any]]]:
    for idx in range(0, len(items), chunk_size):
        yield items[idx : idx + chunk_size]


def _with_source_metadata(
    row_payload: dict[str, Any],
    *,
    source_path: Path,
    import_batch_id: str | None,
    import_started_at: datetime | None,
) -> dict[str, Any]:
    return {
        **row_payload,
        "source_file_name": source_path.name,
        "source_import_batch_id": import_batch_id,
        "source_imported_at": import_started_at,
    }


def _make_subaward_unique_key(
    *,
    prime_award_unique_key: str | None,
    subaward_number: str | None,
    subaward_action_date: date | None,
    subawardee_name: str | None,
    subaward_amount: Decimal | None,
) -> str:
    action_date_token = subaward_action_date.isoformat() if subaward_action_date else ""
    amount_token = str(subaward_amount) if subaward_amount is not None else ""
    return "|".join(
        [
            prime_award_unique_key or "",
            subaward_number or "",
            action_date_token,
            subawardee_name or "",
            amount_token,
        ]
    )


def _resolve_data_dir(explicit_data_dir: str | None) -> Path:
    if explicit_data_dir:
        return Path(explicit_data_dir).expanduser().resolve()

    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        repo_root / "data" / "spending" / "cdc",
        repo_root / "backend" / "data" / "spending" / "cdc",
        repo_root / "data",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_path(*, explicit: str | None, data_dir: Path, filename: str) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (data_dir / filename).resolve()


def _read_prime_rows(
    path: Path,
    *,
    allowed_fiscal_years: set[int] | None = None,
    import_batch_id: str | None = None,
    import_started_at: datetime | None = None,
    filename_fiscal_years: set[int] | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Prime award CSV not found: {path}")

    file_fiscal_years = set(filename_fiscal_years or _filename_fiscal_years(path))
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_required_columns(
            path=path,
            header_columns=reader.fieldnames,
            required_columns={
                "assistance_award_unique_key": (
                    "assistance_award_unique_key",
                    "prime_award_unique_key",
                ),
            },
        )
        for source_row in reader:
            raw_row = {
                str(key): _clean_text(value)
                for key, value in (source_row or {}).items()
                if key is not None
            }

            unique_key = _first_present(
                raw_row,
                "assistance_award_unique_key",
                "prime_award_unique_key",
            )
            if unique_key is None:
                continue

            cfda_numbers_and_titles = _clean_text(raw_row.get("cfda_numbers_and_titles"))
            cfda_program_num, cfda_program_title = _extract_cfda_program(cfda_numbers_and_titles)
            award_latest_action_date = _parse_date(
                _first_present(
                    raw_row,
                    "award_latest_action_date",
                    "prime_award_latest_action_date",
                )
            )
            award_latest_action_date_fiscal_year = _normalize_fiscal_year(
                _first_present(
                    raw_row,
                    "award_latest_action_date_fiscal_year",
                    "prime_award_latest_action_date_fiscal_year",
                )
            )
            if award_latest_action_date_fiscal_year is None:
                award_latest_action_date_fiscal_year = _infer_fiscal_year_from_date(award_latest_action_date)
            if award_latest_action_date_fiscal_year is None and len(file_fiscal_years) == 1:
                award_latest_action_date_fiscal_year = next(iter(file_fiscal_years))
            if (
                allowed_fiscal_years is not None
                and award_latest_action_date_fiscal_year is not None
                and award_latest_action_date_fiscal_year not in allowed_fiscal_years
            ):
                continue
            if (
                allowed_fiscal_years is not None
                and award_latest_action_date_fiscal_year is None
            ):
                continue

            recipient_state_code = _normalize_state_code(raw_row.get("recipient_state_code"))
            recipient_county_fips = _normalize_fips(
                _first_present(
                    raw_row,
                    "prime_award_summary_recipient_county_fips_code",
                    "recipient_county_fips_code",
                ),
                length=5,
            )
            emergency_classification = classify_official_emergency_code(
                _first_present(
                    raw_row,
                    "disaster_emergency_fund_codes",
                    "prime_award_disaster_emergency_fund_codes",
                )
            )

            row_payload = {
                "unique_key": unique_key,
                "fain": _first_present(raw_row, "award_id_fain", "prime_award_fain"),
                "uri": _first_present(raw_row, "award_id_uri", "prime_award_award_id_uri"),
                "recipient_name": _clean_text(raw_row.get("recipient_name")),
                "recipient_state_code": recipient_state_code,
                "recipient_state_name": _clean_text(raw_row.get("recipient_state_name")),
                "recipient_county_name": _clean_text(raw_row.get("recipient_county_name")),
                "recipient_county_fips": recipient_county_fips,
                "primary_place_of_performance_state_name": _clean_text(
                    raw_row.get("primary_place_of_performance_state_name")
                ),
                "primary_place_of_performance_county_name": _clean_text(
                    raw_row.get("primary_place_of_performance_county_name")
                ),
                "primary_place_of_performance_county_fips": _normalize_fips(
                    raw_row.get("prime_award_summary_place_of_performance_county_fips_code"),
                    length=5,
                ),
                "assistance_type_description": _clean_text(raw_row.get("assistance_type_description")),
                "total_funding_amount": _parse_decimal(raw_row.get("total_funding_amount")),
                "total_obligated_amount": _parse_decimal(raw_row.get("total_obligated_amount")),
                "total_outlayed_amount": _parse_decimal(raw_row.get("total_outlayed_amount")),
                "award_base_action_date": _parse_date(raw_row.get("award_base_action_date")),
                "award_latest_action_date": award_latest_action_date,
                "award_latest_action_date_fiscal_year": award_latest_action_date_fiscal_year,
                "awarding_sub_agency_name": _clean_text(raw_row.get("awarding_sub_agency_name")),
                "funding_sub_agency_name": _clean_text(raw_row.get("funding_sub_agency_name")),
                "awarding_office_name": _clean_text(raw_row.get("awarding_office_name")),
                "funding_office_name": _clean_text(raw_row.get("funding_office_name")),
                "cfda_program_num": cfda_program_num,
                "cfda_program_title": cfda_program_title,
                "cfda_numbers_and_titles": cfda_numbers_and_titles,
                "prime_award_base_transaction_description": _clean_text(
                    raw_row.get("prime_award_base_transaction_description")
                ),
                "usaspending_permalink": _clean_text(raw_row.get("usaspending_permalink")),
                "recipient_state_fips_code": _normalize_fips(
                    raw_row.get("prime_award_summary_recipient_state_fips_code"),
                    length=2,
                ),
                "disaster_emergency_fund_codes_raw": emergency_classification["raw_emergency_code"],
                "appropriation_type": emergency_classification["appropriation_type"],
                "appropriation_subtype": emergency_classification["appropriation_subtype"],
                "appropriation_reason_code": emergency_classification["appropriation_reason_code"],
                "appropriation_classification_source": emergency_classification["classification_source"],
                "appropriation_classifier_version": emergency_classification["classifier_version"],
                "searchable_text": _build_searchable_text(
                    unique_key,
                    raw_row.get("award_id_fain"),
                    raw_row.get("award_id_uri"),
                    raw_row.get("recipient_name"),
                    raw_row.get("recipient_county_name"),
                    raw_row.get("recipient_state_code"),
                    raw_row.get("recipient_state_name"),
                    raw_row.get("assistance_type_description"),
                    raw_row.get("awarding_sub_agency_name"),
                    raw_row.get("funding_sub_agency_name"),
                    raw_row.get("awarding_office_name"),
                    raw_row.get("funding_office_name"),
                    cfda_numbers_and_titles,
                    raw_row.get("prime_award_base_transaction_description"),
                    emergency_classification["raw_emergency_code"],
                ),
                "raw": raw_row,
            }
            rows.append(
                _with_source_metadata(
                    row_payload,
                    source_path=path,
                    import_batch_id=import_batch_id,
                    import_started_at=import_started_at,
                )
            )

    return rows


def _read_prime_transaction_rows(
    path: Path,
    *,
    allowed_fiscal_years: set[int] | None = None,
    import_batch_id: str | None = None,
    import_started_at: datetime | None = None,
    filename_fiscal_years: set[int] | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Prime transaction CSV not found: {path}")

    file_fiscal_years = set(filename_fiscal_years or _filename_fiscal_years(path))
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_required_columns(
            path=path,
            header_columns=reader.fieldnames,
            required_columns={
                "assistance_transaction_unique_key": ("assistance_transaction_unique_key",),
            },
        )
        for source_row in reader:
            raw_row = {
                str(key): _clean_text(value)
                for key, value in (source_row or {}).items()
                if key is not None
            }

            assistance_transaction_unique_key = _clean_text(
                raw_row.get("assistance_transaction_unique_key")
            )
            if assistance_transaction_unique_key is None:
                continue

            action_date = _parse_date(raw_row.get("action_date"))
            action_date_fiscal_year = _normalize_fiscal_year(raw_row.get("action_date_fiscal_year"))
            if action_date_fiscal_year is None:
                action_date_fiscal_year = _infer_fiscal_year_from_date(action_date)
            if action_date_fiscal_year is None and len(file_fiscal_years) == 1:
                action_date_fiscal_year = next(iter(file_fiscal_years))
            if (
                allowed_fiscal_years is not None
                and action_date_fiscal_year is not None
                and action_date_fiscal_year not in allowed_fiscal_years
            ):
                continue
            if (
                allowed_fiscal_years is not None
                and action_date_fiscal_year is None
            ):
                continue

            assistance_award_unique_key = _clean_text(raw_row.get("assistance_award_unique_key"))
            emergency_classification = classify_official_emergency_code(
                _first_present(
                    raw_row,
                    "disaster_emergency_fund_codes_for_overall_award",
                    "disaster_emergency_fund_codes",
                )
            )

            row_payload = {
                "assistance_transaction_unique_key": assistance_transaction_unique_key,
                "assistance_award_unique_key": assistance_award_unique_key,
                "award_id_fain": _clean_text(raw_row.get("award_id_fain")),
                "modification_number": _clean_text(raw_row.get("modification_number")),
                "award_id_uri": _clean_text(raw_row.get("award_id_uri")),
                "federal_action_obligation": _parse_decimal(raw_row.get("federal_action_obligation")),
                "total_obligated_amount": _parse_decimal(raw_row.get("total_obligated_amount")),
                "total_outlayed_amount_for_overall_award": _parse_decimal(
                    raw_row.get("total_outlayed_amount_for_overall_award")
                ),
                "action_date": action_date,
                "action_date_fiscal_year": action_date_fiscal_year,
                "awarding_sub_agency_name": _clean_text(raw_row.get("awarding_sub_agency_name")),
                "funding_sub_agency_name": _clean_text(raw_row.get("funding_sub_agency_name")),
                "awarding_office_name": _clean_text(raw_row.get("awarding_office_name")),
                "funding_office_name": _clean_text(raw_row.get("funding_office_name")),
                "recipient_name": _clean_text(raw_row.get("recipient_name")),
                "recipient_city_name": _clean_text(raw_row.get("recipient_city_name")),
                "recipient_county_name": _clean_text(raw_row.get("recipient_county_name")),
                "prime_award_transaction_recipient_county_fips_code": _normalize_fips(
                    raw_row.get("prime_award_transaction_recipient_county_fips_code"),
                    length=5,
                ),
                "recipient_state_code": _normalize_state_code(raw_row.get("recipient_state_code")),
                "recipient_state_name": _clean_text(raw_row.get("recipient_state_name")),
                "primary_place_of_performance_county_name": _clean_text(
                    raw_row.get("primary_place_of_performance_county_name")
                ),
                "prime_award_transaction_place_of_performance_county_fips_code": _normalize_fips(
                    raw_row.get("prime_award_transaction_place_of_performance_county_fips_code"),
                    length=5,
                ),
                "primary_place_of_performance_state_name": _clean_text(
                    raw_row.get("primary_place_of_performance_state_name")
                ),
                "assistance_type_description": _clean_text(raw_row.get("assistance_type_description")),
                "transaction_description": _clean_text(raw_row.get("transaction_description")),
                "prime_award_base_transaction_description": _clean_text(
                    raw_row.get("prime_award_base_transaction_description")
                ),
                "cfda_number": _clean_text(raw_row.get("cfda_number")),
                "cfda_title": _clean_text(raw_row.get("cfda_title")),
                "usaspending_permalink": _clean_text(raw_row.get("usaspending_permalink")),
                "disaster_emergency_fund_codes_raw": emergency_classification["raw_emergency_code"],
                "appropriation_type": emergency_classification["appropriation_type"],
                "appropriation_subtype": emergency_classification["appropriation_subtype"],
                "appropriation_reason_code": emergency_classification["appropriation_reason_code"],
                "appropriation_classification_source": emergency_classification["classification_source"],
                "appropriation_classifier_version": emergency_classification["classifier_version"],
                "searchable_text": _build_searchable_text(
                    assistance_transaction_unique_key,
                    assistance_award_unique_key,
                    raw_row.get("award_id_fain"),
                    raw_row.get("award_id_uri"),
                    raw_row.get("recipient_name"),
                    raw_row.get("recipient_city_name"),
                    raw_row.get("recipient_county_name"),
                    raw_row.get("recipient_state_code"),
                    raw_row.get("recipient_state_name"),
                    raw_row.get("assistance_type_description"),
                    raw_row.get("awarding_sub_agency_name"),
                    raw_row.get("funding_sub_agency_name"),
                    raw_row.get("awarding_office_name"),
                    raw_row.get("funding_office_name"),
                    raw_row.get("transaction_description"),
                    raw_row.get("prime_award_base_transaction_description"),
                    raw_row.get("cfda_number"),
                    raw_row.get("cfda_title"),
                    emergency_classification["raw_emergency_code"],
                ),
                "raw": raw_row,
            }
            rows.append(
                _with_source_metadata(
                    row_payload,
                    source_path=path,
                    import_batch_id=import_batch_id,
                    import_started_at=import_started_at,
                )
            )

    return rows


def _read_subaward_rows(
    path: Path,
    *,
    allowed_fiscal_years: set[int] | None = None,
    import_batch_id: str | None = None,
    import_started_at: datetime | None = None,
    filename_fiscal_years: set[int] | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Subaward CSV not found: {path}")

    file_fiscal_years = set(filename_fiscal_years or _filename_fiscal_years(path))
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_required_columns(
            path=path,
            header_columns=reader.fieldnames,
            required_columns={
                "prime_award_unique_key": ("prime_award_unique_key",),
            },
        )
        for source_row in reader:
            raw_row = {
                str(key): _clean_text(value)
                for key, value in (source_row or {}).items()
                if key is not None
            }

            prime_award_unique_key = _clean_text(raw_row.get("prime_award_unique_key"))
            if prime_award_unique_key is None:
                continue

            subaward_action_date = _parse_date(raw_row.get("subaward_action_date"))
            subaward_action_date_fiscal_year = _normalize_fiscal_year(
                _first_present(
                    raw_row,
                    "subaward_action_date_fiscal_year",
                    "prime_award_latest_action_date_fiscal_year",
                )
            )
            if subaward_action_date_fiscal_year is None:
                subaward_action_date_fiscal_year = _infer_fiscal_year_from_date(subaward_action_date)
            if subaward_action_date_fiscal_year is None and len(file_fiscal_years) == 1:
                subaward_action_date_fiscal_year = next(iter(file_fiscal_years))
            if (
                allowed_fiscal_years is not None
                and subaward_action_date_fiscal_year is not None
                and subaward_action_date_fiscal_year not in allowed_fiscal_years
            ):
                continue
            if (
                allowed_fiscal_years is not None
                and subaward_action_date_fiscal_year is None
            ):
                continue

            subawardee_state_code = _normalize_state_code(raw_row.get("subawardee_state_code"))
            subawardee_county_fips = _normalize_fips(
                _first_present(
                    raw_row,
                    "subawardee_county_fips_code",
                    "subawardee_county_fips",
                ),
                length=5,
            )
            emergency_classification = classify_official_emergency_code(
                _first_present(
                    raw_row,
                    "prime_award_disaster_emergency_fund_codes",
                    "disaster_emergency_fund_codes",
                )
            )
            subaward_number = _clean_text(raw_row.get("subaward_number"))
            subaward_amount = _parse_decimal(raw_row.get("subaward_amount"))
            subawardee_name = _clean_text(raw_row.get("subawardee_name"))

            row_payload = {
                "prime_award_unique_key": prime_award_unique_key,
                # Deterministic key supports idempotent reruns across overlapping year exports.
                "subaward_unique_key": _make_subaward_unique_key(
                    prime_award_unique_key=prime_award_unique_key,
                    subaward_number=subaward_number,
                    subaward_action_date=subaward_action_date,
                    subawardee_name=subawardee_name,
                    subaward_amount=subaward_amount,
                ),
                "prime_award_fain": _clean_text(raw_row.get("prime_award_fain")),
                "subaward_number": subaward_number,
                "subaward_amount": subaward_amount,
                "subaward_action_date": subaward_action_date,
                "subaward_action_date_fiscal_year": subaward_action_date_fiscal_year,
                "subawardee_name": subawardee_name,
                "subawardee_state_code": subawardee_state_code,
                "subawardee_state_name": _clean_text(raw_row.get("subawardee_state_name")),
                "subawardee_city_name": _clean_text(raw_row.get("subawardee_city_name")),
                "subawardee_county_fips": subawardee_county_fips,
                "subaward_primary_place_of_performance_state_code": _normalize_state_code(
                    raw_row.get("subaward_primary_place_of_performance_state_code")
                ),
                "subaward_primary_place_of_performance_state_name": _clean_text(
                    raw_row.get("subaward_primary_place_of_performance_state_name")
                ),
                "subaward_description": _clean_text(raw_row.get("subaward_description")),
                "prime_award_awarding_sub_agency_name": _clean_text(
                    raw_row.get("prime_award_awarding_sub_agency_name")
                ),
                "prime_award_funding_sub_agency_name": _clean_text(
                    raw_row.get("prime_award_funding_sub_agency_name")
                ),
                "prime_award_awarding_office_name": _clean_text(
                    raw_row.get("prime_award_awarding_office_name")
                ),
                "prime_award_funding_office_name": _clean_text(
                    raw_row.get("prime_award_funding_office_name")
                ),
                "prime_award_base_transaction_description": _clean_text(
                    raw_row.get("prime_award_base_transaction_description")
                ),
                "usaspending_permalink": _clean_text(raw_row.get("usaspending_permalink")),
                "prime_award_amount": _parse_decimal(raw_row.get("prime_award_amount")),
                "prime_award_total_outlayed_amount": _parse_decimal(
                    raw_row.get("prime_award_total_outlayed_amount")
                ),
                "prime_award_disaster_emergency_fund_codes_raw": emergency_classification[
                    "raw_emergency_code"
                ],
                "appropriation_type": emergency_classification["appropriation_type"],
                "appropriation_subtype": emergency_classification["appropriation_subtype"],
                "appropriation_reason_code": emergency_classification["appropriation_reason_code"],
                "appropriation_classification_source": emergency_classification["classification_source"],
                "appropriation_classifier_version": emergency_classification["classifier_version"],
                "searchable_text": _build_searchable_text(
                    prime_award_unique_key,
                    raw_row.get("prime_award_fain"),
                    raw_row.get("subaward_number"),
                    raw_row.get("subawardee_name"),
                    raw_row.get("subawardee_city_name"),
                    raw_row.get("subawardee_state_code"),
                    raw_row.get("subawardee_state_name"),
                    raw_row.get("prime_award_awarding_sub_agency_name"),
                    raw_row.get("prime_award_funding_sub_agency_name"),
                    raw_row.get("prime_award_awarding_office_name"),
                    raw_row.get("prime_award_funding_office_name"),
                    raw_row.get("subaward_description"),
                    raw_row.get("prime_award_base_transaction_description"),
                    emergency_classification["raw_emergency_code"],
                ),
                "raw": raw_row,
            }
            rows.append(
                _with_source_metadata(
                    row_payload,
                    source_path=path,
                    import_batch_id=import_batch_id,
                    import_started_at=import_started_at,
                )
            )

    return rows


def _ensure_target_tables(connection: Any) -> None:
    required_tables = [
        PRIME_TABLE,
        PRIME_TRANSACTIONS_TABLE,
        SUBAWARD_TABLE,
        AWARD_SCOPE_CLASSIFICATION_TABLE,
        APPROPRIATION_CLASSIFICATION_TABLE,
        PRIME_STATE_SUMMARY_TABLE,
        PRIME_COUNTY_SUMMARY_TABLE,
        PRIME_TX_STATE_SUMMARY_TABLE,
        PRIME_TX_COUNTY_SUMMARY_TABLE,
        PRIME_TX_COUNTY_ALLOCATED_SUMMARY_TABLE,
        SUBAWARD_STATE_SUMMARY_TABLE,
        SUBAWARD_COUNTY_SUMMARY_TABLE,
    ]
    for table_name in required_tables:
        row = connection.execute(
            text("SELECT to_regclass(:table_name) AS exists"),
            {"table_name": table_name},
        ).mappings().one()
        if row["exists"] is None:
            raise RuntimeError(
                f"Required table {table_name} is missing. Run migrations before ingestion."
            )


def _upsert_prime_rows(connection: Any, rows: list[dict[str, Any]], chunk_size: int) -> int:
    if not rows:
        return 0

    statement = text(
        f"""
        INSERT INTO {PRIME_TABLE} (
            unique_key,
            fain,
            uri,
            recipient_name,
            recipient_state_code,
            recipient_state_name,
            recipient_county_name,
            recipient_county_fips,
            primary_place_of_performance_state_name,
            primary_place_of_performance_county_name,
            primary_place_of_performance_county_fips,
            assistance_type_description,
            total_funding_amount,
            total_obligated_amount,
            total_outlayed_amount,
            award_base_action_date,
            award_latest_action_date,
            award_latest_action_date_fiscal_year,
            awarding_sub_agency_name,
            funding_sub_agency_name,
            awarding_office_name,
            funding_office_name,
            cfda_program_num,
            cfda_program_title,
            cfda_numbers_and_titles,
            prime_award_base_transaction_description,
            usaspending_permalink,
            recipient_state_fips_code,
            disaster_emergency_fund_codes_raw,
            appropriation_type,
            appropriation_subtype,
            appropriation_reason_code,
            appropriation_classification_source,
            appropriation_classifier_version,
            source_file_name,
            source_import_batch_id,
            source_imported_at,
            raw,
            searchable_text
        ) VALUES (
            :unique_key,
            :fain,
            :uri,
            :recipient_name,
            :recipient_state_code,
            :recipient_state_name,
            :recipient_county_name,
            :recipient_county_fips,
            :primary_place_of_performance_state_name,
            :primary_place_of_performance_county_name,
            :primary_place_of_performance_county_fips,
            :assistance_type_description,
            :total_funding_amount,
            :total_obligated_amount,
            :total_outlayed_amount,
            :award_base_action_date,
            :award_latest_action_date,
            :award_latest_action_date_fiscal_year,
            :awarding_sub_agency_name,
            :funding_sub_agency_name,
            :awarding_office_name,
            :funding_office_name,
            :cfda_program_num,
            :cfda_program_title,
            :cfda_numbers_and_titles,
            :prime_award_base_transaction_description,
            :usaspending_permalink,
            :recipient_state_fips_code,
            :disaster_emergency_fund_codes_raw,
            :appropriation_type,
            :appropriation_subtype,
            :appropriation_reason_code,
            :appropriation_classification_source,
            :appropriation_classifier_version,
            :source_file_name,
            :source_import_batch_id,
            :source_imported_at,
            CAST(:raw AS jsonb),
            :searchable_text
        )
        ON CONFLICT (unique_key)
        DO UPDATE SET
            fain = EXCLUDED.fain,
            uri = EXCLUDED.uri,
            recipient_name = EXCLUDED.recipient_name,
            recipient_state_code = EXCLUDED.recipient_state_code,
            recipient_state_name = EXCLUDED.recipient_state_name,
            recipient_county_name = EXCLUDED.recipient_county_name,
            recipient_county_fips = EXCLUDED.recipient_county_fips,
            primary_place_of_performance_state_name = EXCLUDED.primary_place_of_performance_state_name,
            primary_place_of_performance_county_name = EXCLUDED.primary_place_of_performance_county_name,
            primary_place_of_performance_county_fips = EXCLUDED.primary_place_of_performance_county_fips,
            assistance_type_description = EXCLUDED.assistance_type_description,
            total_funding_amount = EXCLUDED.total_funding_amount,
            total_obligated_amount = EXCLUDED.total_obligated_amount,
            total_outlayed_amount = EXCLUDED.total_outlayed_amount,
            award_base_action_date = EXCLUDED.award_base_action_date,
            award_latest_action_date = EXCLUDED.award_latest_action_date,
            award_latest_action_date_fiscal_year = EXCLUDED.award_latest_action_date_fiscal_year,
            awarding_sub_agency_name = EXCLUDED.awarding_sub_agency_name,
            funding_sub_agency_name = EXCLUDED.funding_sub_agency_name,
            awarding_office_name = EXCLUDED.awarding_office_name,
            funding_office_name = EXCLUDED.funding_office_name,
            cfda_program_num = EXCLUDED.cfda_program_num,
            cfda_program_title = EXCLUDED.cfda_program_title,
            cfda_numbers_and_titles = EXCLUDED.cfda_numbers_and_titles,
            prime_award_base_transaction_description = EXCLUDED.prime_award_base_transaction_description,
            usaspending_permalink = EXCLUDED.usaspending_permalink,
            recipient_state_fips_code = EXCLUDED.recipient_state_fips_code,
            disaster_emergency_fund_codes_raw = EXCLUDED.disaster_emergency_fund_codes_raw,
            appropriation_type = EXCLUDED.appropriation_type,
            appropriation_subtype = EXCLUDED.appropriation_subtype,
            appropriation_reason_code = EXCLUDED.appropriation_reason_code,
            appropriation_classification_source = EXCLUDED.appropriation_classification_source,
            appropriation_classifier_version = EXCLUDED.appropriation_classifier_version,
            source_file_name = EXCLUDED.source_file_name,
            source_import_batch_id = EXCLUDED.source_import_batch_id,
            source_imported_at = EXCLUDED.source_imported_at,
            raw = EXCLUDED.raw,
            searchable_text = EXCLUDED.searchable_text,
            updated_at = now()
        """
    )

    total = 0
    for chunk in _chunks(rows, chunk_size):
        payload = [
            {
                **row,
                "raw": json.dumps(row.get("raw") or {}, ensure_ascii=False),
            }
            for row in chunk
        ]
        result = connection.execute(statement, payload)
        total += int(result.rowcount or 0)
    return total


def _upsert_prime_transaction_rows(connection: Any, rows: list[dict[str, Any]], chunk_size: int) -> int:
    if not rows:
        return 0

    statement = text(
        f"""
        INSERT INTO {PRIME_TRANSACTIONS_TABLE} (
            assistance_transaction_unique_key,
            assistance_award_unique_key,
            award_id_fain,
            modification_number,
            award_id_uri,
            federal_action_obligation,
            total_obligated_amount,
            total_outlayed_amount_for_overall_award,
            action_date,
            action_date_fiscal_year,
            awarding_sub_agency_name,
            funding_sub_agency_name,
            awarding_office_name,
            funding_office_name,
            recipient_name,
            recipient_city_name,
            recipient_county_name,
            prime_award_transaction_recipient_county_fips_code,
            recipient_state_code,
            recipient_state_name,
            primary_place_of_performance_county_name,
            prime_award_transaction_place_of_performance_county_fips_code,
            primary_place_of_performance_state_name,
            assistance_type_description,
            transaction_description,
            prime_award_base_transaction_description,
            cfda_number,
            cfda_title,
            usaspending_permalink,
            disaster_emergency_fund_codes_raw,
            appropriation_type,
            appropriation_subtype,
            appropriation_reason_code,
            appropriation_classification_source,
            appropriation_classifier_version,
            source_file_name,
            source_import_batch_id,
            source_imported_at,
            raw,
            searchable_text
        ) VALUES (
            :assistance_transaction_unique_key,
            :assistance_award_unique_key,
            :award_id_fain,
            :modification_number,
            :award_id_uri,
            :federal_action_obligation,
            :total_obligated_amount,
            :total_outlayed_amount_for_overall_award,
            :action_date,
            :action_date_fiscal_year,
            :awarding_sub_agency_name,
            :funding_sub_agency_name,
            :awarding_office_name,
            :funding_office_name,
            :recipient_name,
            :recipient_city_name,
            :recipient_county_name,
            :prime_award_transaction_recipient_county_fips_code,
            :recipient_state_code,
            :recipient_state_name,
            :primary_place_of_performance_county_name,
            :prime_award_transaction_place_of_performance_county_fips_code,
            :primary_place_of_performance_state_name,
            :assistance_type_description,
            :transaction_description,
            :prime_award_base_transaction_description,
            :cfda_number,
            :cfda_title,
            :usaspending_permalink,
            :disaster_emergency_fund_codes_raw,
            :appropriation_type,
            :appropriation_subtype,
            :appropriation_reason_code,
            :appropriation_classification_source,
            :appropriation_classifier_version,
            :source_file_name,
            :source_import_batch_id,
            :source_imported_at,
            CAST(:raw AS jsonb),
            :searchable_text
        )
        ON CONFLICT ON CONSTRAINT uq_cdc_prime_transactions_assistance_transaction_unique_key
        DO UPDATE SET
            assistance_award_unique_key = EXCLUDED.assistance_award_unique_key,
            award_id_fain = EXCLUDED.award_id_fain,
            modification_number = EXCLUDED.modification_number,
            award_id_uri = EXCLUDED.award_id_uri,
            federal_action_obligation = EXCLUDED.federal_action_obligation,
            total_obligated_amount = EXCLUDED.total_obligated_amount,
            total_outlayed_amount_for_overall_award = EXCLUDED.total_outlayed_amount_for_overall_award,
            action_date = EXCLUDED.action_date,
            action_date_fiscal_year = EXCLUDED.action_date_fiscal_year,
            awarding_sub_agency_name = EXCLUDED.awarding_sub_agency_name,
            funding_sub_agency_name = EXCLUDED.funding_sub_agency_name,
            awarding_office_name = EXCLUDED.awarding_office_name,
            funding_office_name = EXCLUDED.funding_office_name,
            recipient_name = EXCLUDED.recipient_name,
            recipient_city_name = EXCLUDED.recipient_city_name,
            recipient_county_name = EXCLUDED.recipient_county_name,
            prime_award_transaction_recipient_county_fips_code = EXCLUDED.prime_award_transaction_recipient_county_fips_code,
            recipient_state_code = EXCLUDED.recipient_state_code,
            recipient_state_name = EXCLUDED.recipient_state_name,
            primary_place_of_performance_county_name = EXCLUDED.primary_place_of_performance_county_name,
            prime_award_transaction_place_of_performance_county_fips_code = EXCLUDED.prime_award_transaction_place_of_performance_county_fips_code,
            primary_place_of_performance_state_name = EXCLUDED.primary_place_of_performance_state_name,
            assistance_type_description = EXCLUDED.assistance_type_description,
            transaction_description = EXCLUDED.transaction_description,
            prime_award_base_transaction_description = EXCLUDED.prime_award_base_transaction_description,
            cfda_number = EXCLUDED.cfda_number,
            cfda_title = EXCLUDED.cfda_title,
            usaspending_permalink = EXCLUDED.usaspending_permalink,
            disaster_emergency_fund_codes_raw = EXCLUDED.disaster_emergency_fund_codes_raw,
            appropriation_type = EXCLUDED.appropriation_type,
            appropriation_subtype = EXCLUDED.appropriation_subtype,
            appropriation_reason_code = EXCLUDED.appropriation_reason_code,
            appropriation_classification_source = EXCLUDED.appropriation_classification_source,
            appropriation_classifier_version = EXCLUDED.appropriation_classifier_version,
            source_file_name = EXCLUDED.source_file_name,
            source_import_batch_id = EXCLUDED.source_import_batch_id,
            source_imported_at = EXCLUDED.source_imported_at,
            raw = EXCLUDED.raw,
            searchable_text = EXCLUDED.searchable_text,
            updated_at = now()
        """
    )

    total = 0
    for chunk in _chunks(rows, chunk_size):
        payload = [
            {
                **row,
                "raw": json.dumps(row.get("raw") or {}, ensure_ascii=False),
            }
            for row in chunk
        ]
        result = connection.execute(statement, payload)
        total += int(result.rowcount or 0)
    return total


def _upsert_subaward_rows(connection: Any, rows: list[dict[str, Any]], chunk_size: int) -> int:
    if not rows:
        return 0

    statement = text(
        f"""
        INSERT INTO {SUBAWARD_TABLE} (
            prime_award_unique_key,
            subaward_unique_key,
            prime_award_fain,
            subaward_number,
            subaward_amount,
            subaward_action_date,
            subaward_action_date_fiscal_year,
            subawardee_name,
            subawardee_state_code,
            subawardee_state_name,
            subawardee_city_name,
            subawardee_county_fips,
            subaward_primary_place_of_performance_state_code,
            subaward_primary_place_of_performance_state_name,
            subaward_description,
            prime_award_awarding_sub_agency_name,
            prime_award_funding_sub_agency_name,
            prime_award_awarding_office_name,
            prime_award_funding_office_name,
            prime_award_base_transaction_description,
            usaspending_permalink,
            prime_award_amount,
            prime_award_total_outlayed_amount,
            prime_award_disaster_emergency_fund_codes_raw,
            appropriation_type,
            appropriation_subtype,
            appropriation_reason_code,
            appropriation_classification_source,
            appropriation_classifier_version,
            source_file_name,
            source_import_batch_id,
            source_imported_at,
            raw,
            searchable_text
        ) VALUES (
            :prime_award_unique_key,
            :subaward_unique_key,
            :prime_award_fain,
            :subaward_number,
            :subaward_amount,
            :subaward_action_date,
            :subaward_action_date_fiscal_year,
            :subawardee_name,
            :subawardee_state_code,
            :subawardee_state_name,
            :subawardee_city_name,
            :subawardee_county_fips,
            :subaward_primary_place_of_performance_state_code,
            :subaward_primary_place_of_performance_state_name,
            :subaward_description,
            :prime_award_awarding_sub_agency_name,
            :prime_award_funding_sub_agency_name,
            :prime_award_awarding_office_name,
            :prime_award_funding_office_name,
            :prime_award_base_transaction_description,
            :usaspending_permalink,
            :prime_award_amount,
            :prime_award_total_outlayed_amount,
            :prime_award_disaster_emergency_fund_codes_raw,
            :appropriation_type,
            :appropriation_subtype,
            :appropriation_reason_code,
            :appropriation_classification_source,
            :appropriation_classifier_version,
            :source_file_name,
            :source_import_batch_id,
            :source_imported_at,
            CAST(:raw AS jsonb),
            :searchable_text
        )
        ON CONFLICT ON CONSTRAINT uq_cdc_subawards_unique_key
        DO UPDATE SET
            prime_award_unique_key = EXCLUDED.prime_award_unique_key,
            prime_award_fain = EXCLUDED.prime_award_fain,
            subaward_number = EXCLUDED.subaward_number,
            subaward_amount = EXCLUDED.subaward_amount,
            subaward_action_date = EXCLUDED.subaward_action_date,
            subaward_action_date_fiscal_year = EXCLUDED.subaward_action_date_fiscal_year,
            subawardee_name = EXCLUDED.subawardee_name,
            subawardee_state_code = EXCLUDED.subawardee_state_code,
            subawardee_state_name = EXCLUDED.subawardee_state_name,
            subawardee_city_name = EXCLUDED.subawardee_city_name,
            subawardee_county_fips = EXCLUDED.subawardee_county_fips,
            subaward_primary_place_of_performance_state_code = EXCLUDED.subaward_primary_place_of_performance_state_code,
            subaward_primary_place_of_performance_state_name = EXCLUDED.subaward_primary_place_of_performance_state_name,
            subaward_description = EXCLUDED.subaward_description,
            prime_award_awarding_sub_agency_name = EXCLUDED.prime_award_awarding_sub_agency_name,
            prime_award_funding_sub_agency_name = EXCLUDED.prime_award_funding_sub_agency_name,
            prime_award_awarding_office_name = EXCLUDED.prime_award_awarding_office_name,
            prime_award_funding_office_name = EXCLUDED.prime_award_funding_office_name,
            prime_award_base_transaction_description = EXCLUDED.prime_award_base_transaction_description,
            usaspending_permalink = EXCLUDED.usaspending_permalink,
            prime_award_amount = EXCLUDED.prime_award_amount,
            prime_award_total_outlayed_amount = EXCLUDED.prime_award_total_outlayed_amount,
            prime_award_disaster_emergency_fund_codes_raw = EXCLUDED.prime_award_disaster_emergency_fund_codes_raw,
            appropriation_type = EXCLUDED.appropriation_type,
            appropriation_subtype = EXCLUDED.appropriation_subtype,
            appropriation_reason_code = EXCLUDED.appropriation_reason_code,
            appropriation_classification_source = EXCLUDED.appropriation_classification_source,
            appropriation_classifier_version = EXCLUDED.appropriation_classifier_version,
            source_file_name = EXCLUDED.source_file_name,
            source_import_batch_id = EXCLUDED.source_import_batch_id,
            source_imported_at = EXCLUDED.source_imported_at,
            raw = EXCLUDED.raw,
            searchable_text = EXCLUDED.searchable_text,
            updated_at = now()
        """
    )

    total = 0
    for chunk in _chunks(rows, chunk_size):
        payload = [
            {
                **row,
                "raw": json.dumps(row.get("raw") or {}, ensure_ascii=False),
            }
            for row in chunk
        ]
        result = connection.execute(statement, payload)
        total += int(result.rowcount or 0)
    return total


def _refresh_award_scope_classification(connection: Any, chunk_size: int = DEFAULT_CHUNKSIZE) -> None:
    connection.execute(text(f"TRUNCATE TABLE {AWARD_SCOPE_CLASSIFICATION_TABLE}"))

    source_rows = connection.execute(
        text(
            f"""
            WITH tx_agg AS (
                SELECT
                    tx.assistance_award_unique_key,
                    MAX(tx.award_id_fain) AS award_id_fain,
                    MAX(tx.recipient_name) AS recipient_name,
                    MAX(tx.recipient_state_code) AS recipient_state_code,
                    MAX(tx.prime_award_transaction_recipient_county_fips_code) AS recipient_county_fips,
                    MAX(tx.assistance_type_description) AS assistance_type_description,
                    STRING_AGG(DISTINCT NULLIF(tx.transaction_description, ''), ' | ') AS tx_descriptions,
                    STRING_AGG(
                        DISTINCT NULLIF(tx.prime_award_base_transaction_description, ''),
                        ' | '
                    ) AS tx_base_descriptions,
                    STRING_AGG(DISTINCT NULLIF(tx.cfda_title, ''), ' | ') AS tx_cfda_titles
                FROM {PRIME_TRANSACTIONS_TABLE} AS tx
                WHERE tx.assistance_award_unique_key IS NOT NULL
                GROUP BY tx.assistance_award_unique_key
            )
            SELECT
                COALESCE(p.unique_key, tx.assistance_award_unique_key) AS assistance_award_unique_key,
                COALESCE(p.fain, tx.award_id_fain) AS award_id_fain,
                COALESCE(NULLIF(tx.recipient_name, ''), p.recipient_name) AS recipient_name,
                COALESCE(tx.assistance_type_description, p.assistance_type_description)
                    AS assistance_type_description,
                COALESCE(tx.recipient_state_code, p.recipient_state_code) AS recipient_state_code,
                COALESCE(tx.recipient_county_fips, p.recipient_county_fips) AS recipient_county_fips,
                p.cfda_program_title,
                p.prime_award_base_transaction_description,
                tx.tx_descriptions,
                tx.tx_base_descriptions,
                tx.tx_cfda_titles
            FROM {PRIME_TABLE} AS p
            FULL OUTER JOIN tx_agg AS tx
                ON tx.assistance_award_unique_key = p.unique_key
            WHERE COALESCE(p.unique_key, tx.assistance_award_unique_key) IS NOT NULL
            """
        )
    ).mappings()

    insert_statement = text(
        f"""
        INSERT INTO {AWARD_SCOPE_CLASSIFICATION_TABLE} (
            assistance_award_unique_key,
            award_id_fain,
            scope_classification,
            scope_score,
            scope_confidence,
            reason_codes,
            is_allocatable_to_counties,
            allocation_method_default,
            classifier_version
        ) VALUES (
            :assistance_award_unique_key,
            :award_id_fain,
            :scope_classification,
            :scope_score,
            :scope_confidence,
            CAST(:reason_codes AS jsonb),
            :is_allocatable_to_counties,
            :allocation_method_default,
            :classifier_version
        )
        """
    )

    payload: list[dict[str, Any]] = []
    for row in source_rows:
        scope = _classify_award_scope(
            recipient_name=row.get("recipient_name"),
            assistance_type_description=row.get("assistance_type_description"),
            recipient_state_code=row.get("recipient_state_code"),
            recipient_county_fips=row.get("recipient_county_fips"),
            transaction_descriptions=row.get("tx_descriptions"),
            transaction_base_descriptions=row.get("tx_base_descriptions"),
            transaction_cfda_titles=row.get("tx_cfda_titles"),
            prime_award_base_transaction_description=row.get("prime_award_base_transaction_description"),
            cfda_program_title=row.get("cfda_program_title"),
        )
        payload.append(
            {
                "assistance_award_unique_key": row.get("assistance_award_unique_key"),
                "award_id_fain": row.get("award_id_fain"),
                "scope_classification": scope["scope_classification"],
                "scope_score": scope["scope_score"],
                "scope_confidence": scope["scope_confidence"],
                "reason_codes": json.dumps(scope["reason_codes"], ensure_ascii=False),
                "is_allocatable_to_counties": scope["is_allocatable_to_counties"],
                "allocation_method_default": scope["allocation_method_default"],
                "classifier_version": scope["classifier_version"],
            }
        )
        if len(payload) >= max(1, int(chunk_size)):
            connection.execute(insert_statement, payload)
            payload = []

    if payload:
        connection.execute(insert_statement, payload)


def _refresh_appropriation_classification(connection: Any) -> None:
    connection.execute(text(f"TRUNCATE TABLE {APPROPRIATION_CLASSIFICATION_TABLE}"))

    connection.execute(
        text(
            f"""
            INSERT INTO {APPROPRIATION_CLASSIFICATION_TABLE} (
                record_type,
                record_id,
                assistance_award_unique_key,
                award_id_fain,
                raw_emergency_code,
                appropriation_type,
                appropriation_subtype,
                appropriation_reason_code,
                classification_source,
                classifier_version
            )
            SELECT
                'prime_transaction' AS record_type,
                tx.assistance_transaction_unique_key AS record_id,
                tx.assistance_award_unique_key,
                tx.award_id_fain,
                tx.disaster_emergency_fund_codes_raw AS raw_emergency_code,
                COALESCE(tx.appropriation_type, :unknown_type) AS appropriation_type,
                tx.appropriation_subtype,
                tx.appropriation_reason_code,
                COALESCE(
                    tx.appropriation_classification_source,
                    :official_source
                ) AS classification_source,
                COALESCE(
                    tx.appropriation_classifier_version,
                    :classifier_version
                ) AS classifier_version
            FROM {PRIME_TRANSACTIONS_TABLE} AS tx
            WHERE tx.assistance_transaction_unique_key IS NOT NULL
            """
        ),
        {
            "unknown_type": APPROPRIATION_TYPE_UNKNOWN,
            "official_source": APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL,
            "classifier_version": APPROPRIATION_CLASSIFIER_VERSION,
        },
    )

    connection.execute(
        text(
            f"""
            INSERT INTO {APPROPRIATION_CLASSIFICATION_TABLE} (
                record_type,
                record_id,
                assistance_award_unique_key,
                award_id_fain,
                raw_emergency_code,
                appropriation_type,
                appropriation_subtype,
                appropriation_reason_code,
                classification_source,
                classifier_version
            )
            SELECT
                'subaward' AS record_type,
                s.id::text AS record_id,
                s.prime_award_unique_key AS assistance_award_unique_key,
                s.prime_award_fain AS award_id_fain,
                s.prime_award_disaster_emergency_fund_codes_raw AS raw_emergency_code,
                COALESCE(s.appropriation_type, :unknown_type) AS appropriation_type,
                s.appropriation_subtype,
                s.appropriation_reason_code,
                COALESCE(
                    s.appropriation_classification_source,
                    :official_source
                ) AS classification_source,
                COALESCE(
                    s.appropriation_classifier_version,
                    :classifier_version
                ) AS classifier_version
            FROM {SUBAWARD_TABLE} AS s
            """
        ),
        {
            "unknown_type": APPROPRIATION_TYPE_UNKNOWN,
            "official_source": APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL,
            "classifier_version": APPROPRIATION_CLASSIFIER_VERSION,
        },
    )

    connection.execute(
        text(
            f"""
            INSERT INTO {APPROPRIATION_CLASSIFICATION_TABLE} (
                record_type,
                record_id,
                assistance_award_unique_key,
                award_id_fain,
                raw_emergency_code,
                appropriation_type,
                appropriation_subtype,
                appropriation_reason_code,
                classification_source,
                classifier_version
            )
            SELECT
                'prime_award' AS record_type,
                p.unique_key AS record_id,
                p.unique_key AS assistance_award_unique_key,
                p.fain AS award_id_fain,
                p.disaster_emergency_fund_codes_raw AS raw_emergency_code,
                COALESCE(p.appropriation_type, :unknown_type) AS appropriation_type,
                p.appropriation_subtype,
                p.appropriation_reason_code,
                COALESCE(
                    p.appropriation_classification_source,
                    :official_source
                ) AS classification_source,
                COALESCE(
                    p.appropriation_classifier_version,
                    :classifier_version
                ) AS classifier_version
            FROM {PRIME_TABLE} AS p
            WHERE p.unique_key IS NOT NULL
            """
        ),
        {
            "unknown_type": APPROPRIATION_TYPE_UNKNOWN,
            "official_source": APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL,
            "classifier_version": APPROPRIATION_CLASSIFIER_VERSION,
        },
    )


def _refresh_summary_tables(connection: Any) -> None:
    connection.execute(text(f"TRUNCATE TABLE {PRIME_STATE_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {PRIME_COUNTY_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {PRIME_TX_STATE_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {PRIME_TX_COUNTY_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {PRIME_TX_COUNTY_ALLOCATED_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {PRIME_TX_NATIONAL_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {SUBAWARD_STATE_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {SUBAWARD_COUNTY_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {SUBAWARD_NATIONAL_SUMMARY_TABLE}"))

    connection.execute(
        text(
            f"""
            INSERT INTO {PRIME_STATE_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                fiscal_year,
                assistance_type_description,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                total_funding_amount,
                total_obligated_amount,
                total_outlayed_amount,
                award_count
            )
            SELECT
                p.recipient_state_code AS geography_id,
                MAX(p.recipient_state_name) AS geography_name,
                p.award_latest_action_date_fiscal_year AS fiscal_year,
                p.assistance_type_description,
                p.awarding_sub_agency_name,
                p.funding_sub_agency_name,
                p.awarding_office_name,
                p.funding_office_name,
                COALESCE(SUM(p.total_funding_amount), 0) AS total_funding_amount,
                COALESCE(SUM(p.total_obligated_amount), 0) AS total_obligated_amount,
                COALESCE(SUM(p.total_outlayed_amount), 0) AS total_outlayed_amount,
                COUNT(*)::integer AS award_count
            FROM {PRIME_TABLE} AS p
            WHERE p.recipient_state_code IS NOT NULL
            GROUP BY
                p.recipient_state_code,
                p.award_latest_action_date_fiscal_year,
                p.assistance_type_description,
                p.awarding_sub_agency_name,
                p.funding_sub_agency_name,
                p.awarding_office_name,
                p.funding_office_name
            """
        )
    )

    connection.execute(
        text(
            f"""
            INSERT INTO {PRIME_COUNTY_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                state_code,
                fiscal_year,
                assistance_type_description,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                total_funding_amount,
                total_obligated_amount,
                total_outlayed_amount,
                award_count
            )
            SELECT
                p.recipient_county_fips AS geography_id,
                MAX(p.recipient_county_name) AS geography_name,
                MAX(p.recipient_state_code) AS state_code,
                p.award_latest_action_date_fiscal_year AS fiscal_year,
                p.assistance_type_description,
                p.awarding_sub_agency_name,
                p.funding_sub_agency_name,
                p.awarding_office_name,
                p.funding_office_name,
                COALESCE(SUM(p.total_funding_amount), 0) AS total_funding_amount,
                COALESCE(SUM(p.total_obligated_amount), 0) AS total_obligated_amount,
                COALESCE(SUM(p.total_outlayed_amount), 0) AS total_outlayed_amount,
                COUNT(*)::integer AS award_count
            FROM {PRIME_TABLE} AS p
            WHERE p.recipient_county_fips IS NOT NULL
            GROUP BY
                p.recipient_county_fips,
                p.award_latest_action_date_fiscal_year,
                p.assistance_type_description,
                p.awarding_sub_agency_name,
                p.funding_sub_agency_name,
                p.awarding_office_name,
                p.funding_office_name
            """
        )
    )

    # Annual outlays are estimated from per-award cumulative snapshots by taking
    # transaction-to-transaction deltas ordered within each award.
    connection.execute(
        text(
            f"""
            WITH tx_ordered AS (
                SELECT
                    t.*,
                    LAG(t.total_outlayed_amount_for_overall_award) OVER (
                        PARTITION BY COALESCE(
                            t.assistance_award_unique_key,
                            t.assistance_transaction_unique_key
                        )
                        ORDER BY
                            t.action_date NULLS FIRST,
                            COALESCE(t.modification_number, ''),
                            t.assistance_transaction_unique_key
                    ) AS prior_total_outlayed_amount_for_overall_award
                FROM {PRIME_TRANSACTIONS_TABLE} AS t
                WHERE t.action_date_fiscal_year IS NOT NULL
            ),
            tx_enriched AS (
                SELECT
                    tx.assistance_transaction_unique_key,
                    tx.assistance_award_unique_key,
                    tx.action_date_fiscal_year AS fiscal_year,
                    tx.assistance_type_description,
                    tx.awarding_sub_agency_name,
                    tx.funding_sub_agency_name,
                    tx.awarding_office_name,
                    tx.funding_office_name,
                    COALESCE(tx.appropriation_type, 'unknown') AS appropriation_type,
                    tx.federal_action_obligation,
                    COALESCE(tx.recipient_state_code, p.recipient_state_code) AS resolved_state_code,
                    COALESCE(NULLIF(tx.recipient_state_name, ''), p.recipient_state_name) AS resolved_state_name,
                    COALESCE(
                        tx.prime_award_transaction_recipient_county_fips_code,
                        p.recipient_county_fips
                    ) AS resolved_county_fips,
                    COALESCE(NULLIF(tx.recipient_county_name, ''), p.recipient_county_name) AS resolved_county_name,
                    CASE
                        WHEN tx.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                        WHEN tx.prior_total_outlayed_amount_for_overall_award IS NULL
                            THEN tx.total_outlayed_amount_for_overall_award
                        ELSE tx.total_outlayed_amount_for_overall_award
                            - tx.prior_total_outlayed_amount_for_overall_award
                    END AS estimated_outlay_delta
                FROM tx_ordered AS tx
                LEFT JOIN {PRIME_TABLE} AS p
                    ON p.unique_key = tx.assistance_award_unique_key
            ),
            state_population AS (
                SELECT
                    population.state_abbr,
                    population.population
                FROM {POPULATION_VIEW_TABLE} AS population
                WHERE population.geography_type = 'state'
            )
            INSERT INTO {PRIME_TX_STATE_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                fiscal_year,
                assistance_type_description,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                appropriation_type,
                population,
                fy_obligated_amount,
                fy_outlayed_amount_estimated,
                total_funding_amount,
                transaction_count,
                distinct_award_count,
                funding_per_capita,
                fy_obligated_per_capita,
                fy_outlayed_amount_estimated_per_capita
            )
            SELECT
                tx.resolved_state_code AS geography_id,
                MAX(tx.resolved_state_name) AS geography_name,
                tx.fiscal_year,
                tx.assistance_type_description,
                tx.awarding_sub_agency_name,
                tx.funding_sub_agency_name,
                tx.awarding_office_name,
                tx.funding_office_name,
                tx.appropriation_type,
                MAX(state_population.population) AS population,
                COALESCE(SUM(tx.federal_action_obligation), 0) AS fy_obligated_amount,
                COALESCE(SUM(tx.estimated_outlay_delta), 0) AS fy_outlayed_amount_estimated,
                COALESCE(SUM(tx.federal_action_obligation), 0) AS total_funding_amount,
                COUNT(*)::integer AS transaction_count,
                COUNT(DISTINCT tx.assistance_award_unique_key)::integer AS distinct_award_count,
                CASE
                    WHEN MAX(state_population.population) IS NULL OR MAX(state_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(tx.federal_action_obligation), 0)
                        / NULLIF(MAX(state_population.population), 0)
                END AS funding_per_capita,
                CASE
                    WHEN MAX(state_population.population) IS NULL OR MAX(state_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(tx.federal_action_obligation), 0)
                        / NULLIF(MAX(state_population.population), 0)
                END AS fy_obligated_per_capita,
                CASE
                    WHEN MAX(state_population.population) IS NULL OR MAX(state_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(tx.estimated_outlay_delta), 0)
                        / NULLIF(MAX(state_population.population), 0)
                END AS fy_outlayed_amount_estimated_per_capita
            FROM tx_enriched AS tx
            LEFT JOIN state_population
                ON state_population.state_abbr = tx.resolved_state_code
            WHERE tx.resolved_state_code IS NOT NULL
            GROUP BY
                tx.resolved_state_code,
                tx.fiscal_year,
                tx.assistance_type_description,
                tx.awarding_sub_agency_name,
                tx.funding_sub_agency_name,
                tx.awarding_office_name,
                tx.funding_office_name,
                tx.appropriation_type
            """
        )
    )

    # Recipient-location county summary (truth-preserving default mode).
    connection.execute(
        text(
            f"""
            WITH tx_ordered AS (
                SELECT
                    t.*,
                    LAG(t.total_outlayed_amount_for_overall_award) OVER (
                        PARTITION BY COALESCE(
                            t.assistance_award_unique_key,
                            t.assistance_transaction_unique_key
                        )
                        ORDER BY
                            t.action_date NULLS FIRST,
                            COALESCE(t.modification_number, ''),
                            t.assistance_transaction_unique_key
                    ) AS prior_total_outlayed_amount_for_overall_award
                FROM {PRIME_TRANSACTIONS_TABLE} AS t
                WHERE t.action_date_fiscal_year IS NOT NULL
            ),
            tx_enriched AS (
                SELECT
                    tx.assistance_award_unique_key,
                    tx.action_date_fiscal_year AS fiscal_year,
                    tx.assistance_type_description,
                    tx.awarding_sub_agency_name,
                    tx.funding_sub_agency_name,
                    tx.awarding_office_name,
                    tx.funding_office_name,
                    COALESCE(tx.appropriation_type, 'unknown') AS appropriation_type,
                    tx.federal_action_obligation,
                    COALESCE(tx.recipient_state_code, p.recipient_state_code) AS resolved_state_code,
                    COALESCE(NULLIF(tx.recipient_state_name, ''), p.recipient_state_name) AS resolved_state_name,
                    COALESCE(
                        tx.prime_award_transaction_recipient_county_fips_code,
                        p.recipient_county_fips
                    ) AS resolved_county_fips,
                    COALESCE(NULLIF(tx.recipient_county_name, ''), p.recipient_county_name) AS resolved_county_name,
                    CASE
                        WHEN tx.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                        WHEN tx.prior_total_outlayed_amount_for_overall_award IS NULL
                            THEN tx.total_outlayed_amount_for_overall_award
                        ELSE tx.total_outlayed_amount_for_overall_award
                            - tx.prior_total_outlayed_amount_for_overall_award
                    END AS estimated_outlay_delta
                FROM tx_ordered AS tx
                LEFT JOIN {PRIME_TABLE} AS p
                    ON p.unique_key = tx.assistance_award_unique_key
            ),
            county_population AS (
                SELECT
                    population.geography_id AS county_fips,
                    population.population
                FROM {POPULATION_VIEW_TABLE} AS population
                WHERE population.geography_type = 'county'
            )
            INSERT INTO {PRIME_TX_COUNTY_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                state_code,
                fiscal_year,
                assistance_type_description,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                appropriation_type,
                population,
                fy_obligated_amount,
                fy_outlayed_amount_estimated,
                total_funding_amount,
                transaction_count,
                distinct_award_count,
                funding_per_capita,
                fy_obligated_per_capita,
                fy_outlayed_amount_estimated_per_capita
            )
            SELECT
                tx.resolved_county_fips AS geography_id,
                MAX(tx.resolved_county_name) AS geography_name,
                MAX(tx.resolved_state_code) AS state_code,
                tx.fiscal_year,
                tx.assistance_type_description,
                tx.awarding_sub_agency_name,
                tx.funding_sub_agency_name,
                tx.awarding_office_name,
                tx.funding_office_name,
                tx.appropriation_type,
                MAX(county_population.population) AS population,
                COALESCE(SUM(tx.federal_action_obligation), 0) AS fy_obligated_amount,
                COALESCE(SUM(tx.estimated_outlay_delta), 0) AS fy_outlayed_amount_estimated,
                COALESCE(SUM(tx.federal_action_obligation), 0) AS total_funding_amount,
                COUNT(*)::integer AS transaction_count,
                COUNT(DISTINCT tx.assistance_award_unique_key)::integer AS distinct_award_count,
                CASE
                    WHEN MAX(county_population.population) IS NULL OR MAX(county_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(tx.federal_action_obligation), 0)
                        / NULLIF(MAX(county_population.population), 0)
                END AS funding_per_capita,
                CASE
                    WHEN MAX(county_population.population) IS NULL OR MAX(county_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(tx.federal_action_obligation), 0)
                        / NULLIF(MAX(county_population.population), 0)
                END AS fy_obligated_per_capita,
                CASE
                    WHEN MAX(county_population.population) IS NULL OR MAX(county_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(tx.estimated_outlay_delta), 0)
                        / NULLIF(MAX(county_population.population), 0)
                END AS fy_outlayed_amount_estimated_per_capita
            FROM tx_enriched AS tx
            LEFT JOIN county_population
                ON county_population.county_fips = tx.resolved_county_fips
            WHERE tx.resolved_county_fips IS NOT NULL
            GROUP BY
                tx.resolved_county_fips,
                tx.fiscal_year,
                tx.assistance_type_description,
                tx.awarding_sub_agency_name,
                tx.funding_sub_agency_name,
                tx.awarding_office_name,
                tx.funding_office_name,
                tx.appropriation_type
            """
        )
    )

    connection.execute(
        text(
            f"""
            WITH tx_ordered AS (
                SELECT
                    t.*,
                    LAG(t.total_outlayed_amount_for_overall_award) OVER (
                        PARTITION BY COALESCE(
                            t.assistance_award_unique_key,
                            t.assistance_transaction_unique_key
                        )
                        ORDER BY
                            t.action_date NULLS FIRST,
                            COALESCE(t.modification_number, ''),
                            t.assistance_transaction_unique_key
                    ) AS prior_total_outlayed_amount_for_overall_award
                FROM {PRIME_TRANSACTIONS_TABLE} AS t
                WHERE t.action_date_fiscal_year IS NOT NULL
            ),
            tx_enriched AS (
                SELECT
                    tx.assistance_transaction_unique_key,
                    tx.assistance_award_unique_key,
                    tx.action_date_fiscal_year AS fiscal_year,
                    tx.assistance_type_description,
                    tx.awarding_sub_agency_name,
                    tx.funding_sub_agency_name,
                    tx.awarding_office_name,
                    tx.funding_office_name,
                    COALESCE(tx.appropriation_type, 'unknown') AS appropriation_type,
                    tx.federal_action_obligation,
                    COALESCE(tx.recipient_state_code, p.recipient_state_code) AS resolved_state_code,
                    COALESCE(NULLIF(tx.recipient_state_name, ''), p.recipient_state_name) AS resolved_state_name,
                    COALESCE(
                        tx.prime_award_transaction_recipient_county_fips_code,
                        p.recipient_county_fips
                    ) AS resolved_county_fips,
                    COALESCE(NULLIF(tx.recipient_county_name, ''), p.recipient_county_name) AS resolved_county_name,
                    CASE
                        WHEN tx.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                        WHEN tx.prior_total_outlayed_amount_for_overall_award IS NULL
                            THEN tx.total_outlayed_amount_for_overall_award
                        ELSE tx.total_outlayed_amount_for_overall_award
                            - tx.prior_total_outlayed_amount_for_overall_award
                    END AS estimated_outlay_delta,
                    COALESCE(cls.scope_classification, 'unknown') AS scope_classification,
                    COALESCE(cls.is_allocatable_to_counties, false) AS is_allocatable_to_counties
                FROM tx_ordered AS tx
                LEFT JOIN {PRIME_TABLE} AS p
                    ON p.unique_key = tx.assistance_award_unique_key
                LEFT JOIN {AWARD_SCOPE_CLASSIFICATION_TABLE} AS cls
                    ON cls.assistance_award_unique_key = tx.assistance_award_unique_key
            ),
            state_county_weights AS (
                SELECT
                    county.location_id AS county_fips,
                    county.state_abbr AS state_code,
                    county.county_name,
                    county.total_population::numeric AS county_population,
                    SUM(county.total_population::numeric) OVER (
                        PARTITION BY county.state_abbr
                    ) AS state_population
                FROM {COUNTY_DIM_TABLE} AS county
                WHERE county.location_id ~ '^[0-9]{{5}}$'
                  AND county.state_abbr IS NOT NULL
                  AND county.total_population IS NOT NULL
                  AND county.total_population > 0
            ),
            direct_tx AS (
                SELECT
                    tx.resolved_county_fips AS geography_id,
                    tx.resolved_county_name AS geography_name,
                    tx.resolved_state_code AS state_code,
                    tx.fiscal_year,
                    tx.assistance_type_description,
                    tx.awarding_sub_agency_name,
                    tx.funding_sub_agency_name,
                    tx.awarding_office_name,
                    tx.funding_office_name,
                    tx.appropriation_type,
                    tx.federal_action_obligation AS fy_obligated_amount,
                    tx.estimated_outlay_delta AS fy_outlayed_amount_estimated,
                    1::numeric AS tx_count_share,
                    tx.assistance_award_unique_key
                FROM tx_enriched AS tx
                WHERE tx.resolved_county_fips IS NOT NULL
                  AND tx.scope_classification <> 'statewide'
            ),
            statewide_tx AS (
                SELECT
                    tx.assistance_transaction_unique_key,
                    tx.assistance_award_unique_key,
                    tx.fiscal_year,
                    tx.assistance_type_description,
                    tx.awarding_sub_agency_name,
                    tx.funding_sub_agency_name,
                    tx.awarding_office_name,
                    tx.funding_office_name,
                    tx.appropriation_type,
                    tx.federal_action_obligation,
                    tx.estimated_outlay_delta,
                    tx.resolved_state_code AS state_code
                FROM tx_enriched AS tx
                WHERE tx.resolved_state_code IS NOT NULL
                  AND tx.scope_classification = 'statewide'
                  AND tx.is_allocatable_to_counties = true
            ),
            allocated_tx AS (
                SELECT
                    weights.county_fips AS geography_id,
                    weights.county_name AS geography_name,
                    statewide.state_code,
                    statewide.fiscal_year,
                    statewide.assistance_type_description,
                    statewide.awarding_sub_agency_name,
                    statewide.funding_sub_agency_name,
                    statewide.awarding_office_name,
                    statewide.funding_office_name,
                    statewide.appropriation_type,
                    COALESCE(statewide.federal_action_obligation, 0)
                        * (weights.county_population / NULLIF(weights.state_population, 0))
                        AS fy_obligated_amount,
                    COALESCE(statewide.estimated_outlay_delta, 0)
                        * (weights.county_population / NULLIF(weights.state_population, 0))
                        AS fy_outlayed_amount_estimated,
                    (weights.county_population / NULLIF(weights.state_population, 0))::numeric
                        AS tx_count_share,
                    statewide.assistance_award_unique_key
                FROM statewide_tx AS statewide
                JOIN state_county_weights AS weights
                    ON weights.state_code = statewide.state_code
            ),
            direct_awards AS (
                SELECT DISTINCT
                    direct.geography_id,
                    direct.geography_name,
                    direct.state_code,
                    direct.fiscal_year,
                    direct.assistance_type_description,
                    direct.awarding_sub_agency_name,
                    direct.funding_sub_agency_name,
                    direct.awarding_office_name,
                    direct.funding_office_name,
                    direct.appropriation_type,
                    direct.assistance_award_unique_key
                FROM direct_tx AS direct
                WHERE direct.assistance_award_unique_key IS NOT NULL
            ),
            statewide_awards AS (
                SELECT DISTINCT
                    statewide.assistance_award_unique_key,
                    statewide.fiscal_year,
                    statewide.assistance_type_description,
                    statewide.awarding_sub_agency_name,
                    statewide.funding_sub_agency_name,
                    statewide.awarding_office_name,
                    statewide.funding_office_name,
                    statewide.appropriation_type,
                    statewide.state_code
                FROM statewide_tx AS statewide
                WHERE statewide.assistance_award_unique_key IS NOT NULL
            ),
            allocated_awards AS (
                SELECT
                    weights.county_fips AS geography_id,
                    weights.county_name AS geography_name,
                    awards.state_code,
                    awards.fiscal_year,
                    awards.assistance_type_description,
                    awards.awarding_sub_agency_name,
                    awards.funding_sub_agency_name,
                    awards.awarding_office_name,
                    awards.funding_office_name,
                    awards.appropriation_type,
                    (weights.county_population / NULLIF(weights.state_population, 0))::numeric
                        AS award_count_share
                FROM statewide_awards AS awards
                JOIN state_county_weights AS weights
                    ON weights.state_code = awards.state_code
            ),
            county_contributions AS (
                SELECT
                    direct.geography_id,
                    direct.geography_name,
                    direct.state_code,
                    direct.fiscal_year,
                    direct.assistance_type_description,
                    direct.awarding_sub_agency_name,
                    direct.funding_sub_agency_name,
                    direct.awarding_office_name,
                    direct.funding_office_name,
                    direct.appropriation_type,
                    direct.fy_obligated_amount,
                    direct.fy_outlayed_amount_estimated,
                    direct.tx_count_share,
                    0::numeric AS award_count_share
                FROM direct_tx AS direct
                UNION ALL
                SELECT
                    allocated.geography_id,
                    allocated.geography_name,
                    allocated.state_code,
                    allocated.fiscal_year,
                    allocated.assistance_type_description,
                    allocated.awarding_sub_agency_name,
                    allocated.funding_sub_agency_name,
                    allocated.awarding_office_name,
                    allocated.funding_office_name,
                    allocated.appropriation_type,
                    allocated.fy_obligated_amount,
                    allocated.fy_outlayed_amount_estimated,
                    allocated.tx_count_share,
                    0::numeric AS award_count_share
                FROM allocated_tx AS allocated
                UNION ALL
                SELECT
                    direct_awards.geography_id,
                    direct_awards.geography_name,
                    direct_awards.state_code,
                    direct_awards.fiscal_year,
                    direct_awards.assistance_type_description,
                    direct_awards.awarding_sub_agency_name,
                    direct_awards.funding_sub_agency_name,
                    direct_awards.awarding_office_name,
                    direct_awards.funding_office_name,
                    direct_awards.appropriation_type,
                    0::numeric AS fy_obligated_amount,
                    0::numeric AS fy_outlayed_amount_estimated,
                    0::numeric AS tx_count_share,
                    1::numeric AS award_count_share
                FROM direct_awards
                UNION ALL
                SELECT
                    allocated_awards.geography_id,
                    allocated_awards.geography_name,
                    allocated_awards.state_code,
                    allocated_awards.fiscal_year,
                    allocated_awards.assistance_type_description,
                    allocated_awards.awarding_sub_agency_name,
                    allocated_awards.funding_sub_agency_name,
                    allocated_awards.awarding_office_name,
                    allocated_awards.funding_office_name,
                    allocated_awards.appropriation_type,
                    0::numeric AS fy_obligated_amount,
                    0::numeric AS fy_outlayed_amount_estimated,
                    0::numeric AS tx_count_share,
                    allocated_awards.award_count_share
                FROM allocated_awards
            )
            INSERT INTO {PRIME_TX_COUNTY_ALLOCATED_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                state_code,
                fiscal_year,
                assistance_type_description,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                appropriation_type,
                population,
                fy_obligated_amount,
                fy_outlayed_amount_estimated,
                total_funding_amount,
                transaction_count,
                distinct_award_count,
                funding_per_capita,
                fy_obligated_per_capita,
                fy_outlayed_amount_estimated_per_capita
            )
            SELECT
                contribution.geography_id,
                MAX(contribution.geography_name) AS geography_name,
                MAX(contribution.state_code) AS state_code,
                contribution.fiscal_year,
                contribution.assistance_type_description,
                contribution.awarding_sub_agency_name,
                contribution.funding_sub_agency_name,
                contribution.awarding_office_name,
                contribution.funding_office_name,
                contribution.appropriation_type,
                MAX(state_county_weights.county_population) AS population,
                COALESCE(SUM(contribution.fy_obligated_amount), 0) AS fy_obligated_amount,
                COALESCE(SUM(contribution.fy_outlayed_amount_estimated), 0) AS fy_outlayed_amount_estimated,
                COALESCE(SUM(contribution.fy_obligated_amount), 0) AS total_funding_amount,
                GREATEST(0, ROUND(COALESCE(SUM(contribution.tx_count_share), 0)))::integer
                    AS transaction_count,
                GREATEST(0, ROUND(COALESCE(SUM(contribution.award_count_share), 0)))::integer
                    AS distinct_award_count,
                CASE
                    WHEN MAX(state_county_weights.county_population) IS NULL
                        OR MAX(state_county_weights.county_population) = 0 THEN NULL
                    ELSE COALESCE(SUM(contribution.fy_obligated_amount), 0)
                        / NULLIF(MAX(state_county_weights.county_population), 0)
                END AS funding_per_capita,
                CASE
                    WHEN MAX(state_county_weights.county_population) IS NULL
                        OR MAX(state_county_weights.county_population) = 0 THEN NULL
                    ELSE COALESCE(SUM(contribution.fy_obligated_amount), 0)
                        / NULLIF(MAX(state_county_weights.county_population), 0)
                END AS fy_obligated_per_capita,
                CASE
                    WHEN MAX(state_county_weights.county_population) IS NULL
                        OR MAX(state_county_weights.county_population) = 0 THEN NULL
                    ELSE COALESCE(SUM(contribution.fy_outlayed_amount_estimated), 0)
                        / NULLIF(MAX(state_county_weights.county_population), 0)
                END AS fy_outlayed_amount_estimated_per_capita
            FROM county_contributions AS contribution
            LEFT JOIN state_county_weights
                ON state_county_weights.county_fips = contribution.geography_id
            WHERE contribution.geography_id IS NOT NULL
            GROUP BY
                contribution.geography_id,
                contribution.fiscal_year,
                contribution.assistance_type_description,
                contribution.awarding_sub_agency_name,
                contribution.funding_sub_agency_name,
                contribution.awarding_office_name,
                contribution.funding_office_name,
                contribution.appropriation_type
            """
        )
    )

    connection.execute(
        text(
            f"""
            WITH state_population AS (
                SELECT
                    population.state_abbr,
                    population.population
                FROM {POPULATION_VIEW_TABLE} AS population
                WHERE population.geography_type = 'state'
            )
            INSERT INTO {SUBAWARD_STATE_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                fiscal_year,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                appropriation_type,
                population,
                total_funding_amount,
                total_obligated_amount,
                total_outlayed_amount,
                award_count,
                total_subaward_amount,
                subaward_count,
                funding_per_capita,
                total_subaward_per_capita
            )
            SELECT
                s.subawardee_state_code AS geography_id,
                MAX(s.subawardee_state_name) AS geography_name,
                s.subaward_action_date_fiscal_year AS fiscal_year,
                s.prime_award_awarding_sub_agency_name AS awarding_sub_agency_name,
                s.prime_award_funding_sub_agency_name AS funding_sub_agency_name,
                s.prime_award_awarding_office_name AS awarding_office_name,
                s.prime_award_funding_office_name AS funding_office_name,
                COALESCE(s.appropriation_type, 'unknown') AS appropriation_type,
                MAX(state_population.population) AS population,
                COALESCE(SUM(s.subaward_amount), 0) AS total_funding_amount,
                COALESCE(SUM(s.subaward_amount), 0) AS total_obligated_amount,
                COALESCE(SUM(s.subaward_amount), 0) AS total_outlayed_amount,
                COUNT(DISTINCT s.prime_award_unique_key)::integer AS award_count,
                COALESCE(SUM(s.subaward_amount), 0) AS total_subaward_amount,
                COUNT(*)::integer AS subaward_count,
                CASE
                    WHEN MAX(state_population.population) IS NULL OR MAX(state_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(s.subaward_amount), 0)
                        / NULLIF(MAX(state_population.population), 0)
                END AS funding_per_capita,
                CASE
                    WHEN MAX(state_population.population) IS NULL OR MAX(state_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(s.subaward_amount), 0)
                        / NULLIF(MAX(state_population.population), 0)
                END AS total_subaward_per_capita
            FROM {SUBAWARD_TABLE} AS s
            LEFT JOIN state_population
                ON state_population.state_abbr = s.subawardee_state_code
            WHERE s.subawardee_state_code IS NOT NULL
            GROUP BY
                s.subawardee_state_code,
                s.subaward_action_date_fiscal_year,
                s.prime_award_awarding_sub_agency_name,
                s.prime_award_funding_sub_agency_name,
                s.prime_award_awarding_office_name,
                s.prime_award_funding_office_name,
                COALESCE(s.appropriation_type, 'unknown')
            """
        )
    )

    connection.execute(
        text(
            f"""
            WITH county_population AS (
                SELECT
                    population.geography_id AS county_fips,
                    population.population
                FROM {POPULATION_VIEW_TABLE} AS population
                WHERE population.geography_type = 'county'
            )
            INSERT INTO {SUBAWARD_COUNTY_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                state_code,
                fiscal_year,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                appropriation_type,
                population,
                total_funding_amount,
                total_obligated_amount,
                total_outlayed_amount,
                award_count,
                total_subaward_amount,
                subaward_count,
                funding_per_capita,
                total_subaward_per_capita
            )
            SELECT
                s.subawardee_county_fips AS geography_id,
                NULL::text AS geography_name,
                MAX(s.subawardee_state_code) AS state_code,
                s.subaward_action_date_fiscal_year AS fiscal_year,
                s.prime_award_awarding_sub_agency_name AS awarding_sub_agency_name,
                s.prime_award_funding_sub_agency_name AS funding_sub_agency_name,
                s.prime_award_awarding_office_name AS awarding_office_name,
                s.prime_award_funding_office_name AS funding_office_name,
                COALESCE(s.appropriation_type, 'unknown') AS appropriation_type,
                MAX(county_population.population) AS population,
                COALESCE(SUM(s.subaward_amount), 0) AS total_funding_amount,
                COALESCE(SUM(s.subaward_amount), 0) AS total_obligated_amount,
                COALESCE(SUM(s.subaward_amount), 0) AS total_outlayed_amount,
                COUNT(DISTINCT s.prime_award_unique_key)::integer AS award_count,
                COALESCE(SUM(s.subaward_amount), 0) AS total_subaward_amount,
                COUNT(*)::integer AS subaward_count,
                CASE
                    WHEN MAX(county_population.population) IS NULL OR MAX(county_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(s.subaward_amount), 0)
                        / NULLIF(MAX(county_population.population), 0)
                END AS funding_per_capita,
                CASE
                    WHEN MAX(county_population.population) IS NULL OR MAX(county_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(s.subaward_amount), 0)
                        / NULLIF(MAX(county_population.population), 0)
                END AS total_subaward_per_capita
            FROM {SUBAWARD_TABLE} AS s
            LEFT JOIN county_population
                ON county_population.county_fips = s.subawardee_county_fips
            WHERE s.subawardee_county_fips IS NOT NULL
            GROUP BY
                s.subawardee_county_fips,
                s.subaward_action_date_fiscal_year,
                s.prime_award_awarding_sub_agency_name,
                s.prime_award_funding_sub_agency_name,
                s.prime_award_awarding_office_name,
                s.prime_award_funding_office_name,
                COALESCE(s.appropriation_type, 'unknown')
            """
        )
    )

    connection.execute(
        text(
            f"""
            WITH tx_ordered AS (
                SELECT
                    t.*,
                    LAG(t.total_outlayed_amount_for_overall_award) OVER (
                        PARTITION BY COALESCE(
                            t.assistance_award_unique_key,
                            t.assistance_transaction_unique_key
                        )
                        ORDER BY
                            t.action_date NULLS FIRST,
                            COALESCE(t.modification_number, ''),
                            t.assistance_transaction_unique_key
                    ) AS prior_total_outlayed_amount_for_overall_award
                FROM {PRIME_TRANSACTIONS_TABLE} AS t
                WHERE t.action_date_fiscal_year IS NOT NULL
            ),
            tx_enriched AS (
                SELECT
                    tx.assistance_award_unique_key,
                    tx.action_date_fiscal_year AS fiscal_year,
                    tx.assistance_type_description,
                    tx.awarding_sub_agency_name,
                    tx.funding_sub_agency_name,
                    tx.awarding_office_name,
                    tx.funding_office_name,
                    COALESCE(tx.appropriation_type, 'unknown') AS appropriation_type,
                    tx.federal_action_obligation,
                    CASE
                        WHEN tx.total_outlayed_amount_for_overall_award IS NULL THEN NULL
                        WHEN tx.prior_total_outlayed_amount_for_overall_award IS NULL
                            THEN tx.total_outlayed_amount_for_overall_award
                        ELSE tx.total_outlayed_amount_for_overall_award
                            - tx.prior_total_outlayed_amount_for_overall_award
                    END AS estimated_outlay_delta
                FROM tx_ordered AS tx
            ),
            national_population AS (
                SELECT population.population
                FROM {POPULATION_VIEW_TABLE} AS population
                WHERE population.geography_type = 'nation'
                  AND population.geography_id = 'US'
                LIMIT 1
            )
            INSERT INTO {PRIME_TX_NATIONAL_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                fiscal_year,
                assistance_type_description,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                appropriation_type,
                population,
                fy_obligated_amount,
                fy_outlayed_amount_estimated,
                total_funding_amount,
                transaction_count,
                distinct_award_count,
                funding_per_capita,
                fy_obligated_per_capita,
                fy_outlayed_amount_estimated_per_capita
            )
            SELECT
                'US'::text AS geography_id,
                'United States'::text AS geography_name,
                tx.fiscal_year,
                tx.assistance_type_description,
                tx.awarding_sub_agency_name,
                tx.funding_sub_agency_name,
                tx.awarding_office_name,
                tx.funding_office_name,
                tx.appropriation_type,
                MAX(national_population.population) AS population,
                COALESCE(SUM(tx.federal_action_obligation), 0) AS fy_obligated_amount,
                COALESCE(SUM(tx.estimated_outlay_delta), 0) AS fy_outlayed_amount_estimated,
                COALESCE(SUM(tx.federal_action_obligation), 0) AS total_funding_amount,
                COUNT(*)::integer AS transaction_count,
                COUNT(DISTINCT tx.assistance_award_unique_key)::integer AS distinct_award_count,
                CASE
                    WHEN MAX(national_population.population) IS NULL OR MAX(national_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(tx.federal_action_obligation), 0)
                        / NULLIF(MAX(national_population.population), 0)
                END AS funding_per_capita,
                CASE
                    WHEN MAX(national_population.population) IS NULL OR MAX(national_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(tx.federal_action_obligation), 0)
                        / NULLIF(MAX(national_population.population), 0)
                END AS fy_obligated_per_capita,
                CASE
                    WHEN MAX(national_population.population) IS NULL OR MAX(national_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(tx.estimated_outlay_delta), 0)
                        / NULLIF(MAX(national_population.population), 0)
                END AS fy_outlayed_amount_estimated_per_capita
            FROM tx_enriched AS tx
            LEFT JOIN national_population
                ON TRUE
            GROUP BY
                tx.fiscal_year,
                tx.assistance_type_description,
                tx.awarding_sub_agency_name,
                tx.funding_sub_agency_name,
                tx.awarding_office_name,
                tx.funding_office_name,
                tx.appropriation_type
            """
        )
    )

    connection.execute(
        text(
            f"""
            WITH national_population AS (
                SELECT population.population
                FROM {POPULATION_VIEW_TABLE} AS population
                WHERE population.geography_type = 'nation'
                  AND population.geography_id = 'US'
                LIMIT 1
            )
            INSERT INTO {SUBAWARD_NATIONAL_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                fiscal_year,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                appropriation_type,
                population,
                total_funding_amount,
                total_obligated_amount,
                total_outlayed_amount,
                award_count,
                total_subaward_amount,
                subaward_count,
                funding_per_capita,
                total_subaward_per_capita
            )
            SELECT
                'US'::text AS geography_id,
                'United States'::text AS geography_name,
                s.subaward_action_date_fiscal_year AS fiscal_year,
                s.prime_award_awarding_sub_agency_name AS awarding_sub_agency_name,
                s.prime_award_funding_sub_agency_name AS funding_sub_agency_name,
                s.prime_award_awarding_office_name AS awarding_office_name,
                s.prime_award_funding_office_name AS funding_office_name,
                COALESCE(s.appropriation_type, 'unknown') AS appropriation_type,
                MAX(national_population.population) AS population,
                COALESCE(SUM(s.subaward_amount), 0) AS total_funding_amount,
                COALESCE(SUM(s.subaward_amount), 0) AS total_obligated_amount,
                COALESCE(SUM(s.subaward_amount), 0) AS total_outlayed_amount,
                COUNT(DISTINCT s.prime_award_unique_key)::integer AS award_count,
                COALESCE(SUM(s.subaward_amount), 0) AS total_subaward_amount,
                COUNT(*)::integer AS subaward_count,
                CASE
                    WHEN MAX(national_population.population) IS NULL OR MAX(national_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(s.subaward_amount), 0)
                        / NULLIF(MAX(national_population.population), 0)
                END AS funding_per_capita,
                CASE
                    WHEN MAX(national_population.population) IS NULL OR MAX(national_population.population) = 0 THEN NULL
                    ELSE COALESCE(SUM(s.subaward_amount), 0)
                        / NULLIF(MAX(national_population.population), 0)
                END AS total_subaward_per_capita
            FROM {SUBAWARD_TABLE} AS s
            LEFT JOIN national_population
                ON TRUE
            GROUP BY
                s.subaward_action_date_fiscal_year,
                s.prime_award_awarding_sub_agency_name,
                s.prime_award_funding_sub_agency_name,
                s.prime_award_awarding_office_name,
                s.prime_award_funding_office_name,
                COALESCE(s.appropriation_type, 'unknown')
            """
        )
    )


def _normalize_source_entry(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    return {
        "path": resolved,
        "filename_fiscal_years": sorted(_filename_fiscal_years(resolved)),
    }


def _filter_sources_for_requested_years(
    *,
    sources: list[dict[str, Any]],
    requested_fiscal_years: set[int] | None,
) -> list[dict[str, Any]]:
    if requested_fiscal_years is None:
        return sources
    filtered: list[dict[str, Any]] = []
    for source in sources:
        filename_years = {
            int(year)
            for year in source.get("filename_fiscal_years", [])
            if _normalize_fiscal_year(year) is not None
        }
        if filename_years and filename_years.isdisjoint(requested_fiscal_years):
            continue
        filtered.append(source)
    return filtered


def _load_rows_for_sources(
    *,
    sources: list[dict[str, Any]],
    reader: Any,
    fiscal_year_field: str,
    requested_fiscal_years: set[int] | None,
    import_batch_id: str,
    import_started_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    source_summaries: list[dict[str, Any]] = []
    for source in sources:
        source_path = Path(source["path"])
        filename_fiscal_years = {
            int(year)
            for year in source.get("filename_fiscal_years", [])
            if _normalize_fiscal_year(year) is not None
        }
        source_rows = reader(
            source_path,
            allowed_fiscal_years=requested_fiscal_years,
            import_batch_id=import_batch_id,
            import_started_at=import_started_at,
            filename_fiscal_years=filename_fiscal_years,
        )
        row_years = sorted(
            {
                int(year)
                for year in (
                    row.get(fiscal_year_field)
                    for row in source_rows
                )
                if _normalize_fiscal_year(year) is not None
            }
        )
        source_summaries.append(
            {
                "path": str(source_path),
                "filename_fiscal_years": sorted(filename_fiscal_years),
                "row_fiscal_years": row_years,
                "row_count": len(source_rows),
            }
        )
        rows.extend(source_rows)
    return rows, source_summaries


def ingest_from_sources(
    *,
    db_url: str,
    prime_sources: list[dict[str, Any]],
    transaction_sources: list[dict[str, Any]],
    subaward_sources: list[dict[str, Any]],
    chunksize: int,
    requested_fiscal_years: set[int] | None = None,
) -> dict[str, Any]:
    import_batch_id = uuid.uuid4().hex
    import_started_at = datetime.utcnow()
    prime_rows, prime_source_summaries = _load_rows_for_sources(
        sources=prime_sources,
        reader=_read_prime_rows,
        fiscal_year_field="award_latest_action_date_fiscal_year",
        requested_fiscal_years=requested_fiscal_years,
        import_batch_id=import_batch_id,
        import_started_at=import_started_at,
    )
    transaction_rows, transaction_source_summaries = _load_rows_for_sources(
        sources=transaction_sources,
        reader=_read_prime_transaction_rows,
        fiscal_year_field="action_date_fiscal_year",
        requested_fiscal_years=requested_fiscal_years,
        import_batch_id=import_batch_id,
        import_started_at=import_started_at,
    )
    subaward_rows, subaward_source_summaries = _load_rows_for_sources(
        sources=subaward_sources,
        reader=_read_subaward_rows,
        fiscal_year_field="subaward_action_date_fiscal_year",
        requested_fiscal_years=requested_fiscal_years,
        import_batch_id=import_batch_id,
        import_started_at=import_started_at,
    )

    started_at = time.perf_counter()
    engine = create_engine(db_url)
    with engine.begin() as connection:
        _ensure_target_tables(connection)
        prime_upserts = _upsert_prime_rows(connection, prime_rows, chunksize)
        transaction_upserts = _upsert_prime_transaction_rows(connection, transaction_rows, chunksize)
        subaward_upserts = _upsert_subaward_rows(connection, subaward_rows, chunksize)
        _refresh_award_scope_classification(connection, chunk_size=chunksize)
        _refresh_appropriation_classification(connection)
        _refresh_summary_tables(connection)

    elapsed_seconds = round(time.perf_counter() - started_at, 3)
    return {
        "schema": CDC_FUNDING_SCHEMA,
        "import_batch_id": import_batch_id,
        "import_started_at": import_started_at.isoformat(),
        "requested_fiscal_years": sorted(requested_fiscal_years) if requested_fiscal_years else None,
        "prime_source_files": prime_source_summaries,
        "transaction_source_files": transaction_source_summaries,
        "subaward_source_files": subaward_source_summaries,
        "prime_rows_read": len(prime_rows),
        "transaction_rows_read": len(transaction_rows),
        "subaward_rows_read": len(subaward_rows),
        "prime_rows_upserted": prime_upserts,
        "transaction_rows_upserted": transaction_upserts,
        "subaward_rows_upserted": subaward_upserts,
        "elapsed_seconds": elapsed_seconds,
    }


def ingest(
    *,
    db_url: str,
    prime_path: Path,
    transaction_path: Path,
    subaward_path: Path,
    chunksize: int,
) -> dict[str, Any]:
    return ingest_from_sources(
        db_url=db_url,
        prime_sources=[_normalize_source_entry(prime_path)],
        transaction_sources=[_normalize_source_entry(transaction_path)],
        subaward_sources=[_normalize_source_entry(subaward_path)],
        chunksize=chunksize,
        requested_fiscal_years=None,
    )


def main() -> None:
    args = parse_args()
    data_dir = _resolve_data_dir(args.data_dir)

    requested_fiscal_years = _normalize_requested_fiscal_years(
        fiscal_years=list(args.fiscal_years or []),
        fiscal_year_range=tuple(args.fiscal_year_range) if args.fiscal_year_range else None,
    )
    explicit_mode = bool(args.prime_path or args.transaction_path or args.subaward_path)
    if explicit_mode:
        prime_sources = [
            _normalize_source_entry(
                _resolve_path(explicit=args.prime_path, data_dir=data_dir, filename=PRIME_FILENAME)
            )
        ]
        transaction_sources = [
            _normalize_source_entry(
                _resolve_path(
                    explicit=args.transaction_path,
                    data_dir=data_dir,
                    filename=PRIME_TRANSACTIONS_FILENAME,
                )
            )
        ]
        subaward_sources = [
            _normalize_source_entry(
                _resolve_path(
                    explicit=args.subaward_path,
                    data_dir=data_dir,
                    filename=SUBAWARD_FILENAME,
                )
            )
        ]
    else:
        discovered = discover_source_files(data_dir)
        prime_sources = _filter_sources_for_requested_years(
            sources=discovered["prime_award"],
            requested_fiscal_years=requested_fiscal_years,
        )
        transaction_sources = _filter_sources_for_requested_years(
            sources=discovered["prime_transaction"],
            requested_fiscal_years=requested_fiscal_years,
        )
        subaward_sources = _filter_sources_for_requested_years(
            sources=discovered["subaward"],
            requested_fiscal_years=requested_fiscal_years,
        )

        if args.list_discovered:
            print(
                json.dumps(
                    {
                        "data_dir": str(data_dir),
                        "requested_fiscal_years": sorted(requested_fiscal_years) if requested_fiscal_years else None,
                        "prime_award_files": prime_sources,
                        "prime_transaction_files": transaction_sources,
                        "subaward_files": subaward_sources,
                    },
                    indent=2,
                    default=str,
                )
            )
            return

    if not prime_sources:
        raise FileNotFoundError(
            f"No prime award source files found in {data_dir} for selected fiscal-year filters."
        )
    if not transaction_sources:
        raise FileNotFoundError(
            f"No prime transaction source files found in {data_dir} for selected fiscal-year filters."
        )
    if not subaward_sources:
        raise FileNotFoundError(
            f"No subaward source files found in {data_dir} for selected fiscal-year filters."
        )

    summary = ingest_from_sources(
        db_url=args.db_url,
        prime_sources=prime_sources,
        transaction_sources=transaction_sources,
        subaward_sources=subaward_sources,
        chunksize=max(1, int(args.chunksize)),
        requested_fiscal_years=requested_fiscal_years,
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
