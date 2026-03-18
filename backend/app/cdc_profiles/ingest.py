from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, text

from app.db import DEFAULT_DB_URL
from app.db_fqtn import cdc_profiles_table
from app.db_schemas import CDC_PROFILES_SCHEMA
from app.recon.normalization import METHODOLOGY_VERSION

RAW_PROFILE_ROWS_TABLE = cdc_profiles_table("raw_profile_rows")
STATE_YEAR_TOTALS_TABLE = cdc_profiles_table("state_year_totals")
METHODOLOGY_DOCUMENTS_TABLE = cdc_profiles_table("methodology_documents")

SUPPORTED_FISCAL_YEARS = {2020, 2021, 2022, 2023}
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
NULL_TOKENS = {"", "na", "n/a", "null", "none"}

STATE_NAME_TO_CODE = {
    "alabama": "AL",
    "alaska": "AK",
    "american samoa": "AS",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "district of columbia (dc)": "DC",
    "district of columbia, district of columbia": "DC",
    "florida": "FL",
    "federated states of micronesia": "FM",
    "georgia": "GA",
    "guam": "GU",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "marshall islands": "MH",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "northern mariana islands": "MP",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "puerto rico": "PR",
    "republic of palau": "PW",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virgin islands": "VI",
    "u.s. virgin islands": "VI",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}

DOCUMENT_TYPE_BY_PREFIX = {
    "about the data": "about_the_data",
    "faqs": "faqs",
    "user tips": "user_tips",
    "whats new": "whats_new",
}


@dataclass(frozen=True)
class DiscoveredProfileFile:
    fiscal_year: int
    path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Ingest CDC Funding Profiles CSVs into schema {CDC_PROFILES_SCHEMA}.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory containing CDC Funding Profiles CSV/PDF files (defaults to data/cdcfundingprofiles).",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=1000,
        help="Insert batch size for raw-row loads (default: 1000).",
    )
    parser.add_argument(
        "--truncate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Truncate CDC profile tables before loading (default: true).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and summarize inputs without writing to the database.",
    )
    parser.add_argument(
        "--list-discovered",
        action="store_true",
        help="List discovered CSV/PDF files and exit.",
    )
    return parser.parse_args()


def _resolve_data_dir(explicit_data_dir: str | None) -> Path:
    if explicit_data_dir:
        return Path(explicit_data_dir).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[3]
    return (repo_root / "data" / "cdcfundingprofiles").resolve()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).replace("\ufeff", "").strip()
    token = re.sub(r"\s+", " ", token)
    if token.lower() in NULL_TOKENS:
        return None
    return token or None


def _clean_key(value: str) -> str:
    token = str(value or "").replace("\ufeff", "").strip().lower()
    token = re.sub(r"[^a-z0-9]+", "_", token)
    return token.strip("_")


def _extract_year_from_name(path: Path) -> int | None:
    match = re.search(r"(20\d{2})", path.name)
    if not match:
        return None
    year = int(match.group(1))
    return year if year in SUPPORTED_FISCAL_YEARS else None


def discover_profile_csv_files(data_dir: Path) -> list[DiscoveredProfileFile]:
    if not data_dir.exists():
        raise FileNotFoundError(f"CDC Funding Profiles directory does not exist: {data_dir}")
    discovered: list[DiscoveredProfileFile] = []
    for path in sorted(data_dir.glob("*CSV Data.csv")):
        fiscal_year = _extract_year_from_name(path)
        if fiscal_year is None:
            continue
        discovered.append(DiscoveredProfileFile(fiscal_year=fiscal_year, path=path.resolve()))
    if not discovered:
        raise FileNotFoundError(f"No CDC Funding Profiles CSV files found in {data_dir}")
    return discovered


def discover_methodology_documents(data_dir: Path) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(data_dir.glob("*.pdf")):
        fiscal_year = _extract_year_from_name(path)
        if fiscal_year is None:
            continue
        prefix = path.stem.rsplit(" ", 1)[0].strip().lower()
        document_type = DOCUMENT_TYPE_BY_PREFIX.get(prefix)
        if document_type is None:
            continue
        stat = path.stat()
        documents.append(
            {
                "fiscal_year": fiscal_year,
                "document_type": document_type,
                "source_file_name": path.name,
                "source_path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "file_size_bytes": int(stat.st_size),
                "methodology_version": METHODOLOGY_VERSION,
            }
        )
    return documents


def _read_csv_dict_rows(path: Path) -> tuple[list[dict[str, str]], str]:
    last_error: Exception | None = None
    for encoding in ENCODINGS:
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                return [dict(row) for row in reader], encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Unable to decode CDC Funding Profiles CSV {path}: {last_error}")


def _parse_amount(value: Any) -> Decimal | None:
    token = _clean_text(value)
    if token is None:
        return None
    normalized = token.replace("$", "").replace(",", "").strip()
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = f"-{normalized[1:-1].strip()}"
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def normalize_state_name(value: Any) -> tuple[str | None, str | None]:
    token = _clean_text(value)
    if token is None:
        return None, None
    normalized_name = re.sub(r"\s+", " ", token).strip()
    lookup = normalized_name.lower()
    return normalized_name, STATE_NAME_TO_CODE.get(lookup)


def _first_present(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key in row:
            value = _clean_text(row.get(key))
            if value is not None:
                return value
    return None


def parse_profile_csv_file(path: Path, *, fiscal_year: int) -> tuple[list[dict[str, Any]], str]:
    source_rows, encoding = _read_csv_dict_rows(path)
    parsed_rows: list[dict[str, Any]] = []
    for row_number, raw_row in enumerate(source_rows, start=2):
        normalized_row = {_clean_key(key): value for key, value in raw_row.items()}
        amount = _parse_amount(normalized_row.get("amount"))
        if amount is None:
            continue
        state_name, state_code = normalize_state_name(
            _first_present(normalized_row, "state")
        )
        parsed_rows.append(
            {
                "fiscal_year": fiscal_year,
                "source_file_name": path.name,
                "source_row_number": row_number,
                "project_number": _first_present(normalized_row, "project_number"),
                "reference_number": _first_present(normalized_row, "reference_number"),
                "nofo_number": _first_present(normalized_row, "nofo_number"),
                "nofo_title": _first_present(normalized_row, "nofo_title"),
                "funding_opportunity_title": _first_present(
                    normalized_row,
                    "funding_opportunity_title",
                    "grantee_project_title",
                ),
                "project_title": _first_present(
                    normalized_row,
                    "funding_opportunity_title",
                    "grantee_project_title",
                ),
                "amount": amount,
                "category": _first_present(normalized_row, "category"),
                "subcategory": _first_present(normalized_row, "sub_category"),
                "grantee_name": _first_present(normalized_row, "grantee_name", "granteename"),
                "address": _first_present(normalized_row, "primary_address", "address"),
                "city": _first_present(normalized_row, "city"),
                "county": _first_present(normalized_row, "county"),
                "state_name": state_name,
                "state_code": state_code,
                "zipcode": _first_present(normalized_row, "zipcode", "zip_code"),
                "congressional_district": _first_present(normalized_row, "congressional_district"),
                "geography": _first_present(normalized_row, "geography"),
                "grantee_type": _first_present(normalized_row, "granttypedesc", "grantee_type"),
                "covid_flag": _first_present(normalized_row, "covid_funding", "covid_funds"),
                "raw": normalized_row,
            }
        )
    return parsed_rows, encoding


def build_state_year_totals(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        fiscal_year = int(row["fiscal_year"])
        state_code = _clean_text(row.get("state_code"))
        if state_code is None:
            continue
        key = (fiscal_year, state_code)
        if key not in totals:
            totals[key] = {
                "fiscal_year": fiscal_year,
                "state_code": state_code,
                "state_name": row.get("state_name"),
                "amount": Decimal("0"),
                "row_count": 0,
                "methodology_version": METHODOLOGY_VERSION,
            }
        totals[key]["amount"] += Decimal(row.get("amount") or 0)
        totals[key]["row_count"] += 1
    return sorted(
        totals.values(),
        key=lambda item: (int(item["fiscal_year"]), str(item["state_code"])),
    )


def _chunked(rows: list[dict[str, Any]], chunk_size: int) -> Iterable[list[dict[str, Any]]]:
    for idx in range(0, len(rows), max(1, chunk_size)):
        yield rows[idx : idx + max(1, chunk_size)]


def ingest(
    *,
    db_url: str,
    data_dir: Path,
    chunk_size: int = 1000,
    truncate: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    discovered_csvs = discover_profile_csv_files(data_dir)
    documents = discover_methodology_documents(data_dir)

    all_rows: list[dict[str, Any]] = []
    encodings_by_file: dict[str, str] = {}
    for entry in discovered_csvs:
        parsed_rows, encoding = parse_profile_csv_file(entry.path, fiscal_year=entry.fiscal_year)
        all_rows.extend(parsed_rows)
        encodings_by_file[entry.path.name] = encoding

    state_year_totals = build_state_year_totals(all_rows)

    summary = {
        "data_dir": str(data_dir),
        "files": [
            {
                "fiscal_year": entry.fiscal_year,
                "path": str(entry.path),
                "encoding": encodings_by_file.get(entry.path.name),
            }
            for entry in discovered_csvs
        ],
        "methodology_documents": documents,
        "raw_row_count": len(all_rows),
        "state_year_total_count": len(state_year_totals),
        "methodology_version": METHODOLOGY_VERSION,
        "fiscal_years": sorted({row["fiscal_year"] for row in all_rows}),
    }
    if dry_run:
        return summary

    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {CDC_PROFILES_SCHEMA}"))
        if truncate:
            connection.execute(text(f"TRUNCATE TABLE {METHODOLOGY_DOCUMENTS_TABLE} RESTART IDENTITY"))
            connection.execute(text(f"TRUNCATE TABLE {STATE_YEAR_TOTALS_TABLE} RESTART IDENTITY"))
            connection.execute(text(f"TRUNCATE TABLE {RAW_PROFILE_ROWS_TABLE} RESTART IDENTITY"))

        raw_insert = text(
            f"""
            INSERT INTO {RAW_PROFILE_ROWS_TABLE} (
                fiscal_year,
                source_file_name,
                source_row_number,
                project_number,
                reference_number,
                nofo_number,
                nofo_title,
                funding_opportunity_title,
                project_title,
                amount,
                category,
                subcategory,
                grantee_name,
                address,
                city,
                county,
                state_name,
                state_code,
                zipcode,
                congressional_district,
                geography,
                grantee_type,
                covid_flag,
                raw
            ) VALUES (
                :fiscal_year,
                :source_file_name,
                :source_row_number,
                :project_number,
                :reference_number,
                :nofo_number,
                :nofo_title,
                :funding_opportunity_title,
                :project_title,
                :amount,
                :category,
                :subcategory,
                :grantee_name,
                :address,
                :city,
                :county,
                :state_name,
                :state_code,
                :zipcode,
                :congressional_district,
                :geography,
                :grantee_type,
                :covid_flag,
                CAST(:raw AS jsonb)
            )
            ON CONFLICT ON CONSTRAINT uq_cdc_profile_raw_row_source
            DO UPDATE SET
                funding_opportunity_title = EXCLUDED.funding_opportunity_title,
                amount = EXCLUDED.amount,
                category = EXCLUDED.category,
                subcategory = EXCLUDED.subcategory,
                grantee_name = EXCLUDED.grantee_name,
                state_name = EXCLUDED.state_name,
                state_code = EXCLUDED.state_code,
                raw = EXCLUDED.raw
            """
        )
        for batch in _chunked(all_rows, chunk_size):
            payload = [
                {
                    **row,
                    "raw": json.dumps(row["raw"]),
                }
                for row in batch
            ]
            connection.execute(raw_insert, payload)

        totals_insert = text(
            f"""
            INSERT INTO {STATE_YEAR_TOTALS_TABLE} (
                fiscal_year,
                state_code,
                state_name,
                amount,
                row_count,
                methodology_version
            ) VALUES (
                :fiscal_year,
                :state_code,
                :state_name,
                :amount,
                :row_count,
                :methodology_version
            )
            ON CONFLICT ON CONSTRAINT uq_cdc_profile_state_year_total
            DO UPDATE SET
                state_name = EXCLUDED.state_name,
                amount = EXCLUDED.amount,
                row_count = EXCLUDED.row_count,
                methodology_version = EXCLUDED.methodology_version,
                refreshed_at = now()
            """
        )
        if state_year_totals:
            connection.execute(totals_insert, state_year_totals)

        docs_insert = text(
            f"""
            INSERT INTO {METHODOLOGY_DOCUMENTS_TABLE} (
                fiscal_year,
                document_type,
                source_file_name,
                source_path,
                sha256,
                file_size_bytes,
                methodology_version
            ) VALUES (
                :fiscal_year,
                :document_type,
                :source_file_name,
                :source_path,
                :sha256,
                :file_size_bytes,
                :methodology_version
            )
            ON CONFLICT ON CONSTRAINT uq_cdc_profile_methodology_doc
            DO UPDATE SET
                source_path = EXCLUDED.source_path,
                sha256 = EXCLUDED.sha256,
                file_size_bytes = EXCLUDED.file_size_bytes,
                methodology_version = EXCLUDED.methodology_version
            """
        )
        if documents:
            connection.execute(docs_insert, documents)

    return summary


def main() -> None:
    args = parse_args()
    data_dir = _resolve_data_dir(args.data_dir)
    discovered = discover_profile_csv_files(data_dir)
    documents = discover_methodology_documents(data_dir)

    if args.list_discovered:
        print(
            json.dumps(
                {
                    "data_dir": str(data_dir),
                    "csv_files": [
                        {"fiscal_year": item.fiscal_year, "path": str(item.path)}
                        for item in discovered
                    ],
                    "methodology_documents": documents,
                },
                indent=2,
            )
        )
        return

    summary = ingest(
        db_url=args.db_url,
        data_dir=data_dir,
        chunk_size=args.chunksize,
        truncate=bool(args.truncate),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
