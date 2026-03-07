from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.db_fqtn import cdc_funding_table
from app.db_schemas import CDC_FUNDING_SCHEMA

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_CHUNKSIZE = 1000

PRIME_FILENAME = "Assistance_PrimeAwardSummaries_2026-03-07_H14M24S59_1.csv"
SUBAWARD_FILENAME = "Assistance_Subawards_2026-03-07_H14M25S36_1.csv"

PRIME_TABLE = cdc_funding_table("prime_awards")
SUBAWARD_TABLE = cdc_funding_table("subawards")
PRIME_STATE_SUMMARY_TABLE = cdc_funding_table("prime_state_summary")
PRIME_COUNTY_SUMMARY_TABLE = cdc_funding_table("prime_county_summary")
SUBAWARD_STATE_SUMMARY_TABLE = cdc_funding_table("subaward_state_summary")
SUBAWARD_COUNTY_SUMMARY_TABLE = cdc_funding_table("subaward_county_summary")

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


def _chunks(items: list[dict[str, Any]], chunk_size: int) -> Iterable[list[dict[str, Any]]]:
    for idx in range(0, len(items), chunk_size):
        yield items[idx : idx + chunk_size]


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


def _read_prime_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Prime award CSV not found: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for source_row in reader:
            raw_row = {
                str(key): _clean_text(value)
                for key, value in (source_row or {}).items()
                if key is not None
            }

            unique_key = _clean_text(raw_row.get("assistance_award_unique_key"))
            if unique_key is None:
                continue

            cfda_numbers_and_titles = _clean_text(raw_row.get("cfda_numbers_and_titles"))
            cfda_program_num, cfda_program_title = _extract_cfda_program(cfda_numbers_and_titles)
            recipient_state_code = _normalize_state_code(raw_row.get("recipient_state_code"))
            recipient_county_fips = _normalize_fips(
                raw_row.get("prime_award_summary_recipient_county_fips_code"),
                length=5,
            )

            row_payload = {
                "unique_key": unique_key,
                "fain": _clean_text(raw_row.get("award_id_fain")),
                "uri": _clean_text(raw_row.get("award_id_uri")),
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
                "award_latest_action_date": _parse_date(raw_row.get("award_latest_action_date")),
                "award_latest_action_date_fiscal_year": _parse_int(
                    raw_row.get("award_latest_action_date_fiscal_year")
                ),
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
                ),
                "raw": raw_row,
            }
            rows.append(row_payload)

    return rows


def _read_subaward_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Subaward CSV not found: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for source_row in reader:
            raw_row = {
                str(key): _clean_text(value)
                for key, value in (source_row or {}).items()
                if key is not None
            }

            prime_award_unique_key = _clean_text(raw_row.get("prime_award_unique_key"))
            if prime_award_unique_key is None:
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

            row_payload = {
                "prime_award_unique_key": prime_award_unique_key,
                "prime_award_fain": _clean_text(raw_row.get("prime_award_fain")),
                "subaward_number": _clean_text(raw_row.get("subaward_number")),
                "subaward_amount": _parse_decimal(raw_row.get("subaward_amount")),
                "subaward_action_date": _parse_date(raw_row.get("subaward_action_date")),
                "subaward_action_date_fiscal_year": _parse_int(
                    raw_row.get("subaward_action_date_fiscal_year")
                ),
                "subawardee_name": _clean_text(raw_row.get("subawardee_name")),
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
                ),
                "raw": raw_row,
            }
            rows.append(row_payload)

    return rows


def _ensure_target_tables(connection: Any) -> None:
    required_tables = [
        PRIME_TABLE,
        SUBAWARD_TABLE,
        PRIME_STATE_SUMMARY_TABLE,
        PRIME_COUNTY_SUMMARY_TABLE,
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
            raw,
            searchable_text
        ) VALUES (
            :prime_award_unique_key,
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
            CAST(:raw AS jsonb),
            :searchable_text
        )
        ON CONFLICT ON CONSTRAINT uq_cdc_subawards_row
        DO UPDATE SET
            prime_award_fain = EXCLUDED.prime_award_fain,
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


def _refresh_summary_tables(connection: Any) -> None:
    connection.execute(text(f"TRUNCATE TABLE {PRIME_STATE_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {PRIME_COUNTY_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {SUBAWARD_STATE_SUMMARY_TABLE}"))
    connection.execute(text(f"TRUNCATE TABLE {SUBAWARD_COUNTY_SUMMARY_TABLE}"))

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

    connection.execute(
        text(
            f"""
            INSERT INTO {SUBAWARD_STATE_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                fiscal_year,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                total_funding_amount,
                total_obligated_amount,
                total_outlayed_amount,
                award_count,
                total_subaward_amount,
                subaward_count
            )
            SELECT
                s.subawardee_state_code AS geography_id,
                MAX(s.subawardee_state_name) AS geography_name,
                s.subaward_action_date_fiscal_year AS fiscal_year,
                s.prime_award_awarding_sub_agency_name AS awarding_sub_agency_name,
                s.prime_award_funding_sub_agency_name AS funding_sub_agency_name,
                s.prime_award_awarding_office_name AS awarding_office_name,
                s.prime_award_funding_office_name AS funding_office_name,
                COALESCE(SUM(s.subaward_amount), 0) AS total_funding_amount,
                COALESCE(SUM(s.subaward_amount), 0) AS total_obligated_amount,
                COALESCE(SUM(s.subaward_amount), 0) AS total_outlayed_amount,
                COUNT(DISTINCT s.prime_award_unique_key)::integer AS award_count,
                COALESCE(SUM(s.subaward_amount), 0) AS total_subaward_amount,
                COUNT(*)::integer AS subaward_count
            FROM {SUBAWARD_TABLE} AS s
            WHERE s.subawardee_state_code IS NOT NULL
            GROUP BY
                s.subawardee_state_code,
                s.subaward_action_date_fiscal_year,
                s.prime_award_awarding_sub_agency_name,
                s.prime_award_funding_sub_agency_name,
                s.prime_award_awarding_office_name,
                s.prime_award_funding_office_name
            """
        )
    )

    connection.execute(
        text(
            f"""
            INSERT INTO {SUBAWARD_COUNTY_SUMMARY_TABLE} (
                geography_id,
                geography_name,
                state_code,
                fiscal_year,
                awarding_sub_agency_name,
                funding_sub_agency_name,
                awarding_office_name,
                funding_office_name,
                total_funding_amount,
                total_obligated_amount,
                total_outlayed_amount,
                award_count,
                total_subaward_amount,
                subaward_count
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
                COALESCE(SUM(s.subaward_amount), 0) AS total_funding_amount,
                COALESCE(SUM(s.subaward_amount), 0) AS total_obligated_amount,
                COALESCE(SUM(s.subaward_amount), 0) AS total_outlayed_amount,
                COUNT(DISTINCT s.prime_award_unique_key)::integer AS award_count,
                COALESCE(SUM(s.subaward_amount), 0) AS total_subaward_amount,
                COUNT(*)::integer AS subaward_count
            FROM {SUBAWARD_TABLE} AS s
            WHERE s.subawardee_county_fips IS NOT NULL
            GROUP BY
                s.subawardee_county_fips,
                s.subaward_action_date_fiscal_year,
                s.prime_award_awarding_sub_agency_name,
                s.prime_award_funding_sub_agency_name,
                s.prime_award_awarding_office_name,
                s.prime_award_funding_office_name
            """
        )
    )


def ingest(
    *,
    db_url: str,
    prime_path: Path,
    subaward_path: Path,
    chunksize: int,
) -> dict[str, Any]:
    prime_rows = _read_prime_rows(prime_path)
    subaward_rows = _read_subaward_rows(subaward_path)

    started_at = time.perf_counter()
    engine = create_engine(db_url)
    with engine.begin() as connection:
        _ensure_target_tables(connection)
        prime_upserts = _upsert_prime_rows(connection, prime_rows, chunksize)
        subaward_upserts = _upsert_subaward_rows(connection, subaward_rows, chunksize)
        _refresh_summary_tables(connection)

    elapsed_seconds = round(time.perf_counter() - started_at, 3)
    return {
        "schema": CDC_FUNDING_SCHEMA,
        "prime_source_path": str(prime_path),
        "subaward_source_path": str(subaward_path),
        "prime_rows_read": len(prime_rows),
        "subaward_rows_read": len(subaward_rows),
        "prime_rows_upserted": prime_upserts,
        "subaward_rows_upserted": subaward_upserts,
        "elapsed_seconds": elapsed_seconds,
    }


def main() -> None:
    args = parse_args()
    data_dir = _resolve_data_dir(args.data_dir)
    prime_path = _resolve_path(explicit=args.prime_path, data_dir=data_dir, filename=PRIME_FILENAME)
    subaward_path = _resolve_path(
        explicit=args.subaward_path,
        data_dir=data_dir,
        filename=SUBAWARD_FILENAME,
    )

    summary = ingest(
        db_url=args.db_url,
        prime_path=prime_path,
        subaward_path=subaward_path,
        chunksize=max(1, int(args.chunksize)),
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
