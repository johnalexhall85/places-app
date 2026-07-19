#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_ROOT = REPO_ROOT / "data" / "usaspending" / "chipfunding"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "backend" / "data_profiles" / "usaspending_funding_file_profile.json"
DEFAULT_CHUNKSIZE = 50_000
DEFAULT_SAMPLE_ROWS = 100_000
EXPECTED_FISCAL_YEARS = [f"fy{year}" for year in range(19, 27)]
ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

FILE_TYPE_ASSISTANCE_PRIME = "assistance_prime_transactions"
FILE_TYPE_ASSISTANCE_SUBAWARDS = "assistance_subawards"
FILE_TYPE_CONTRACTS_PRIME = "contracts_prime_transactions"
FILE_TYPE_CONTRACTS_SUBAWARDS = "contracts_subawards"
FILE_TYPE_UNKNOWN = "unknown"
PRIME_FILE_TYPES = {FILE_TYPE_ASSISTANCE_PRIME, FILE_TYPE_CONTRACTS_PRIME}

CDC_FUNDING_AGENCY_NAME = "department of health and human services"
CDC_FUNDING_SUB_AGENCY_NAME = "centers for disease control and prevention"

BASE_PRIME_REQUIRED_COLUMNS = [
    "federal_action_obligation",
    "action_date_fiscal_year",
    "funding_agency_name",
    "funding_sub_agency_name",
    "primary_place_of_performance_state_code",
    "primary_place_of_performance_county_name",
    "prime_award_transaction_place_of_performance_county_fips_code",
    "recipient_state_code",
    "recipient_county_name",
    "prime_award_transaction_recipient_county_fips_code",
    "federal_accounts_funding_this_award",
    "treasury_accounts_funding_this_award",
    "transaction_description",
    "usaspending_permalink",
]

ASSISTANCE_PRIME_REQUIRED_COLUMNS = [
    "cfda_number",
    "cfda_title",
    "assistance_type_code",
    "assistance_type_description",
]

CONTRACT_PRIME_REQUIRED_COLUMNS = [
    "award_type_code",
    "award_type",
    "naics_code",
    "naics_description",
    "product_or_service_code",
    "product_or_service_code_description",
    "national_interest_action_code",
    "national_interest_action",
]

FIELD_GROUP_PATTERNS: dict[str, tuple[str, ...]] = {
    "likely_transaction_id_fields": ("transaction_unique_key", "transaction_number", "transaction_id"),
    "likely_award_id_fields": (
        "award_unique_key",
        "award_id",
        "award_fain",
        "award_uri",
        "award_piid",
        "generated_unique_award_id",
        "prime_award_unique_key",
        "prime_award_fain",
        "prime_award_piid",
    ),
    "likely_amount_fields": ("amount", "obligation", "obligated", "outlay", "outlayed", "funding"),
    "likely_positive_obligation_field": ("federal_action_obligation",),
    "likely_fiscal_year_fields": ("fiscal_year",),
    "likely_action_date_fields": ("action_date", "period_of_performance", "start_date", "end_date"),
    "likely_recipient_geography_fields": (
        "recipient_state",
        "recipient_county",
        "recipient_city",
        "recipient_zip",
        "recipient_country",
        "awardee_county",
        "awardee_state",
    ),
    "likely_place_of_performance_geography_fields": (
        "place_of_performance",
        "performance_state",
        "performance_county",
        "performance_city",
        "performance_zip",
        "performance_country",
    ),
    "likely_funding_agency_subagency_fields": ("funding_agency", "funding_sub_agency"),
    "likely_awarding_agency_subagency_fields": ("awarding_agency", "awarding_sub_agency"),
    "likely_federal_account_fields": ("federal_account",),
    "likely_treasury_account_fields": ("treasury_account",),
    "likely_assistance_listing_fields": ("cfda", "assistance_listing"),
    "likely_award_type_fields": ("award_type", "assistance_type", "contract_award_type", "subaward_type"),
    "likely_recipient_type_business_type_fields": (
        "recipient_type",
        "recipient_business",
        "business_types",
        "business_categories",
        "organization_type",
    ),
    "likely_covid_emergency_iija_supplemental_fields": (
        "covid",
        "iija",
        "supplemental",
        "emergency",
        "disaster_emergency",
    ),
}


def infer_fiscal_year(path: Path) -> str | None:
    for part in path.parts:
        if re.fullmatch(r"fy\d{2}", part.lower()):
            return part.lower()
    match = re.search(r"\bfy(\d{2})\b", path.name.lower())
    return f"fy{match.group(1)}" if match else None


def infer_file_type(filename: str) -> str:
    normalized = filename.lower()
    if "assistance" in normalized and "primetransactions" in normalized:
        return FILE_TYPE_ASSISTANCE_PRIME
    if "assistance" in normalized and "subawards" in normalized:
        return FILE_TYPE_ASSISTANCE_SUBAWARDS
    if "contracts" in normalized and "primetransactions" in normalized:
        return FILE_TYPE_CONTRACTS_PRIME
    if "contracts" in normalized and "subawards" in normalized:
        return FILE_TYPE_CONTRACTS_SUBAWARDS
    return FILE_TYPE_UNKNOWN


def read_csv_header(path: Path) -> tuple[list[str], str]:
    last_error: Exception | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return next(csv.reader(handle)), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
        except StopIteration:
            return [], encoding
    if last_error is not None:
        raise last_error
    return [], ENCODING_CANDIDATES[0]


def discover_csv_files(input_root: Path) -> list[Path]:
    if not input_root.exists():
        return []
    return sorted(path for path in input_root.glob("fy*/*.csv") if path.is_file())


def detect_field_groups(columns: list[str]) -> dict[str, list[str]]:
    detected: dict[str, list[str]] = {}
    for group_name, patterns in FIELD_GROUP_PATTERNS.items():
        matches = [
            column
            for column in columns
            if any(pattern in column.lower() for pattern in patterns)
        ]
        detected[group_name] = matches
    return detected


def required_columns_for_file_type(file_type: str) -> list[str]:
    if file_type == FILE_TYPE_ASSISTANCE_PRIME:
        return BASE_PRIME_REQUIRED_COLUMNS + ASSISTANCE_PRIME_REQUIRED_COLUMNS
    if file_type == FILE_TYPE_CONTRACTS_PRIME:
        return BASE_PRIME_REQUIRED_COLUMNS + CONTRACT_PRIME_REQUIRED_COLUMNS
    return []


def _is_blank_series(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().eq("")


def _numeric_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.fillna("")
        .astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
    )
    negative_parentheses = cleaned.str.match(r"^\(.+\)$", na=False)
    cleaned = cleaned.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    values = pd.to_numeric(cleaned, errors="coerce")
    values[negative_parentheses & values.notna()] = -values[negative_parentheses & values.notna()].abs()
    return values


def _text_series(chunk: pd.DataFrame, column: str) -> pd.Series:
    if column not in chunk.columns:
        return pd.Series([""] * len(chunk), index=chunk.index)
    return chunk[column].fillna("").astype(str).str.strip()


def _available_columns(columns: list[str], wanted: set[str]) -> list[str]:
    return [column for column in columns if column in wanted]


def sample_prime_statistics(
    path: Path,
    columns: list[str],
    *,
    encoding: str,
    chunksize: int,
    sample_rows: int,
) -> tuple[dict[str, int], int | None, str | None]:
    wanted = {
        "federal_action_obligation",
        "funding_agency_name",
        "funding_sub_agency_name",
        "prime_award_transaction_place_of_performance_county_fips_code",
        "prime_award_transaction_recipient_county_fips_code",
        "recipient_county_name",
        "recipient_state_code",
        "primary_place_of_performance_county_name",
        "primary_place_of_performance_state_code",
        "obligated_amount_from_COVID-19_supplementals_for_overall_award",
        "obligated_amount_from_IIJA_supplemental_for_overall_award",
    }
    supplemental_columns = {
        column
        for column in columns
        if "obligated_amount" in column.lower()
        and any(token in column.lower() for token in ("covid", "iija", "supplemental"))
    }
    wanted.update(supplemental_columns)
    usecols = _available_columns(columns, wanted) or columns[:1]

    stats = {
        "sampled_rows": 0,
        "positive_federal_action_obligation_rows": 0,
        "non_positive_federal_action_obligation_rows": 0,
        "non_hhs_cdc_funding_agency_subagency_rows": 0,
        "missing_place_of_performance_county_fips_rows": 0,
        "missing_recipient_county_fips_rows": 0,
        "missing_place_of_performance_but_recipient_geography_available_rows": 0,
        "covid_supplemental_obligated_amount_positive_rows": 0,
        "iija_supplemental_obligated_amount_positive_rows": 0,
    }
    row_count = 0
    error: str | None = None

    try:
        reader = pd.read_csv(
            path,
            dtype=str,
            chunksize=chunksize,
            low_memory=False,
            encoding=encoding,
            usecols=usecols,
        )
        for chunk in reader:
            chunk_rows = len(chunk)
            row_count += chunk_rows
            remaining_sample_rows = max(sample_rows - stats["sampled_rows"], 0)
            if remaining_sample_rows <= 0:
                continue
            sample = chunk.head(remaining_sample_rows)
            stats["sampled_rows"] += len(sample)

            obligation = _numeric_series(_text_series(sample, "federal_action_obligation"))
            stats["positive_federal_action_obligation_rows"] += int((obligation > 0).sum())
            stats["non_positive_federal_action_obligation_rows"] += int((obligation <= 0).sum())

            agency = _text_series(sample, "funding_agency_name").str.lower()
            subagency = _text_series(sample, "funding_sub_agency_name").str.lower()
            agency_mismatch = (agency != CDC_FUNDING_AGENCY_NAME) | (subagency != CDC_FUNDING_SUB_AGENCY_NAME)
            stats["non_hhs_cdc_funding_agency_subagency_rows"] += int(agency_mismatch.sum())

            pop_fips_blank = _is_blank_series(
                _text_series(sample, "prime_award_transaction_place_of_performance_county_fips_code")
            )
            recipient_fips_blank = _is_blank_series(
                _text_series(sample, "prime_award_transaction_recipient_county_fips_code")
            )
            stats["missing_place_of_performance_county_fips_rows"] += int(pop_fips_blank.sum())
            stats["missing_recipient_county_fips_rows"] += int(recipient_fips_blank.sum())

            recipient_geo_available = ~recipient_fips_blank | ~_is_blank_series(
                _text_series(sample, "recipient_county_name")
            ) | ~_is_blank_series(_text_series(sample, "recipient_state_code"))
            stats["missing_place_of_performance_but_recipient_geography_available_rows"] += int(
                (pop_fips_blank & recipient_geo_available).sum()
            )

            covid_column = "obligated_amount_from_COVID-19_supplementals_for_overall_award"
            iija_column = "obligated_amount_from_IIJA_supplemental_for_overall_award"
            stats["covid_supplemental_obligated_amount_positive_rows"] += int(
                (_numeric_series(_text_series(sample, covid_column)) > 0).sum()
            )
            stats["iija_supplemental_obligated_amount_positive_rows"] += int(
                (_numeric_series(_text_series(sample, iija_column)) > 0).sum()
            )
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        return stats, row_count if row_count else None, error

    return stats, row_count, error


def count_csv_rows(
    path: Path,
    columns: list[str],
    *,
    encoding: str,
    chunksize: int,
) -> tuple[int | None, str | None]:
    usecols = columns[:1]
    row_count = 0
    try:
        reader = pd.read_csv(
            path,
            dtype=str,
            chunksize=chunksize,
            low_memory=False,
            encoding=encoding,
            usecols=usecols,
        )
        for chunk in reader:
            row_count += len(chunk)
    except Exception as exc:  # noqa: BLE001
        return row_count if row_count else None, f"{type(exc).__name__}: {exc}"
    return row_count, None


def profile_csv_file(path: Path, *, chunksize: int, sample_rows: int) -> dict[str, Any]:
    fiscal_year = infer_fiscal_year(path)
    file_type = infer_file_type(path.name)
    warnings: list[str] = []

    try:
        columns, encoding = read_csv_header(path)
    except Exception as exc:  # noqa: BLE001
        return {
            "file_path": str(path),
            "file_name": path.name,
            "inferred_fiscal_year": fiscal_year,
            "inferred_file_type": file_type,
            "file_size_bytes": path.stat().st_size if path.exists() else None,
            "row_count": None,
            "column_count": None,
            "columns": [],
            "encoding": None,
            "detected_field_groups": {},
            "required_columns": required_columns_for_file_type(file_type),
            "missing_required_columns": required_columns_for_file_type(file_type),
            "sample_statistics": None,
            "warnings": [f"Could not read CSV header: {type(exc).__name__}: {exc}"],
            "read_error": f"{type(exc).__name__}: {exc}",
        }

    if not columns:
        warnings.append("CSV header is empty.")

    duplicate_columns = sorted(column for column, count in Counter(columns).items() if count > 1)
    if duplicate_columns:
        warnings.append(f"Duplicate columns detected: {', '.join(duplicate_columns)}")

    required_columns = required_columns_for_file_type(file_type)
    missing_required_columns = [column for column in required_columns if column not in columns]
    if missing_required_columns:
        warnings.append(f"Missing required columns: {', '.join(missing_required_columns)}")

    row_count: int | None
    read_error: str | None
    sample_statistics: dict[str, int] | None = None
    if file_type in PRIME_FILE_TYPES:
        sample_statistics, row_count, read_error = sample_prime_statistics(
            path,
            columns,
            encoding=encoding,
            chunksize=chunksize,
            sample_rows=sample_rows,
        )
    else:
        row_count, read_error = count_csv_rows(path, columns, encoding=encoding, chunksize=chunksize)

    if read_error:
        warnings.append(f"CSV chunk scan failed: {read_error}")

    return {
        "file_path": str(path),
        "file_name": path.name,
        "inferred_fiscal_year": fiscal_year,
        "inferred_file_type": file_type,
        "file_size_bytes": path.stat().st_size,
        "row_count": row_count,
        "column_count": len(columns),
        "columns": columns,
        "encoding": encoding,
        "detected_field_groups": detect_field_groups(columns),
        "required_columns": required_columns,
        "missing_required_columns": missing_required_columns,
        "sample_statistics": sample_statistics,
        "warnings": warnings,
        "read_error": read_error,
    }


def _summary_by_fiscal_year(files: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for fiscal_year in sorted({file["inferred_fiscal_year"] for file in files if file["inferred_fiscal_year"]}):
        fiscal_year_files = [file for file in files if file["inferred_fiscal_year"] == fiscal_year]
        by_type: dict[str, Any] = {}
        for file_type in sorted({file["inferred_file_type"] for file in fiscal_year_files}):
            typed_files = [file for file in fiscal_year_files if file["inferred_file_type"] == file_type]
            by_type[file_type] = {
                "file_count": len(typed_files),
                "row_count": sum(file["row_count"] or 0 for file in typed_files),
                "column_counts": sorted({file["column_count"] for file in typed_files if file["column_count"]}),
                "files": [file["file_name"] for file in typed_files],
            }
        summary[fiscal_year] = {
            "file_count": len(fiscal_year_files),
            "row_count": sum(file["row_count"] or 0 for file in fiscal_year_files),
            "file_types": by_type,
        }
    return summary


def _summary_by_file_type(files: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for file_type in sorted({file["inferred_file_type"] for file in files}):
        typed_files = [file for file in files if file["inferred_file_type"] == file_type]
        summary[file_type] = {
            "file_count": len(typed_files),
            "row_count": sum(file["row_count"] or 0 for file in typed_files),
            "fiscal_years": sorted({file["inferred_fiscal_year"] for file in typed_files if file["inferred_fiscal_year"]}),
            "column_counts": sorted({file["column_count"] for file in typed_files if file["column_count"]}),
            "files_with_warnings": [file["file_name"] for file in typed_files if file["warnings"]],
        }
    return summary


def _cross_year_column_consistency(files: list[dict[str, Any]]) -> dict[str, Any]:
    consistency: dict[str, Any] = {}
    for file_type in sorted({file["inferred_file_type"] for file in files}):
        typed_files = [file for file in files if file["inferred_file_type"] == file_type and file["columns"]]
        if not typed_files:
            consistency[file_type] = {
                "file_count": 0,
                "column_counts": [],
                "common_column_count": 0,
                "union_column_count": 0,
                "differing_columns": [],
                "missing_columns_by_file": {},
            }
            continue
        column_sets = [set(file["columns"]) for file in typed_files]
        common_columns = set.intersection(*column_sets)
        union_columns = set.union(*column_sets)
        missing_by_file = {
            file["file_name"]: sorted(union_columns - set(file["columns"]))
            for file in typed_files
            if union_columns - set(file["columns"])
        }
        consistency[file_type] = {
            "file_count": len(typed_files),
            "column_counts": sorted({file["column_count"] for file in typed_files if file["column_count"]}),
            "common_column_count": len(common_columns),
            "union_column_count": len(union_columns),
            "differing_columns": sorted(union_columns - common_columns),
            "missing_columns_by_file": missing_by_file,
        }
    return consistency


def _build_concerns(files: list[dict[str, Any]]) -> list[str]:
    concerns: list[str] = []
    detected_years = sorted({file["inferred_fiscal_year"] for file in files if file["inferred_fiscal_year"]})
    missing_years = [year for year in EXPECTED_FISCAL_YEARS if year not in detected_years]
    if missing_years:
        concerns.append(f"Missing expected fiscal-year folders/files for: {', '.join(missing_years)}.")

    for fiscal_year in EXPECTED_FISCAL_YEARS:
        fiscal_files = [file for file in files if file["inferred_fiscal_year"] == fiscal_year]
        types = Counter(file["inferred_file_type"] for file in fiscal_files)
        missing_types = [
            file_type
            for file_type in (
                FILE_TYPE_ASSISTANCE_PRIME,
                FILE_TYPE_ASSISTANCE_SUBAWARDS,
                FILE_TYPE_CONTRACTS_PRIME,
                FILE_TYPE_CONTRACTS_SUBAWARDS,
            )
            if types[file_type] != 1
        ]
        if fiscal_files and missing_types:
            concerns.append(f"{fiscal_year} does not have exactly one file for: {', '.join(missing_types)}.")

    for file in files:
        if file["missing_required_columns"]:
            concerns.append(
                f"{file['inferred_fiscal_year']} {file['inferred_file_type']} is missing required columns: "
                f"{', '.join(file['missing_required_columns'])}."
            )
        if file["read_error"]:
            concerns.append(f"{file['file_name']} could not be fully scanned: {file['read_error']}.")

    prime_files = [file for file in files if file["inferred_file_type"] in PRIME_FILE_TYPES]
    for file in prime_files:
        stats = file.get("sample_statistics") or {}
        sampled_rows = stats.get("sampled_rows") or 0
        if not sampled_rows:
            continue
        pop_missing = stats.get("missing_place_of_performance_county_fips_rows", 0)
        recipient_available = stats.get("missing_place_of_performance_but_recipient_geography_available_rows", 0)
        if pop_missing:
            pct = math.floor((pop_missing / sampled_rows) * 1000) / 10
            concerns.append(
                f"{file['inferred_fiscal_year']} {file['inferred_file_type']} sample has {pop_missing:,} "
                f"rows ({pct}%) missing place-of-performance county FIPS; {recipient_available:,} have recipient "
                "geography available for fallback."
            )
        if stats.get("non_hhs_cdc_funding_agency_subagency_rows", 0):
            concerns.append(
                f"{file['inferred_fiscal_year']} {file['inferred_file_type']} sample has "
                f"{stats['non_hhs_cdc_funding_agency_subagency_rows']:,} rows outside HHS/CDC funding scope."
            )

    supplemental_missing = [
        file["file_name"]
        for file in prime_files
        if "obligated_amount_from_COVID-19_supplementals_for_overall_award" not in file["columns"]
        or "obligated_amount_from_IIJA_supplemental_for_overall_award" not in file["columns"]
    ]
    if supplemental_missing:
        concerns.append(
            "Some prime files are missing expected COVID/IIJA supplemental obligation columns: "
            + ", ".join(supplemental_missing)
            + "."
        )

    return concerns


def _recommended_next_schema() -> dict[str, Any]:
    return {
        "cdc_usaspending_prime_transaction_raw": {
            "purpose": "Preserve source prime transaction rows with lineage before canonical map filtering.",
            "important_columns": [
                "source_file",
                "source_fiscal_year_folder",
                "source_file_type",
                "raw_row_number",
                "transaction_unique_key",
                "award_unique_key",
                "raw_payload_jsonb",
                "ingested_at",
            ],
        },
        "cdc_usaspending_map_transaction": {
            "purpose": "Canonical transaction-level table for the CDC funding map.",
            "important_columns": [
                "source_raw_id",
                "fiscal_year",
                "funding_mechanism",
                "federal_action_obligation",
                "is_positive_obligation",
                "is_hhs_cdc_funded",
                "include_by_default",
                "has_covid_supplemental_obligation",
                "has_iija_supplemental_obligation",
                "supplemental_obligated_amount_total",
                "geography_source",
                "county_fips",
                "state_fips",
                "state_code",
                "county_name",
                "recipient_county_fips",
                "place_of_performance_county_fips",
                "transaction_description",
                "usaspending_permalink",
            ],
        },
        "future_optional_tables": [
            "cdc_usaspending_contract_transaction",
            "cdc_usaspending_subaward_raw",
            "cdc_usaspending_award_summary",
        ],
        "recommended_indexes": [
            "fiscal_year",
            "funding_mechanism",
            "county_fips",
            "federal_action_obligation",
            "has_covid_supplemental_obligation",
            "has_iija_supplemental_obligation",
            "source_file",
        ],
    }


def build_report(
    *,
    input_root: Path,
    output_path: Path,
    chunksize: int,
    sample_rows: int,
) -> dict[str, Any]:
    files = [
        profile_csv_file(path, chunksize=chunksize, sample_rows=sample_rows)
        for path in discover_csv_files(input_root)
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(input_root),
        "output_path": str(output_path),
        "expected_fiscal_years": EXPECTED_FISCAL_YEARS,
        "detected_fiscal_years": sorted({file["inferred_fiscal_year"] for file in files if file["inferred_fiscal_year"]}),
        "files": files,
        "summary_by_fiscal_year": _summary_by_fiscal_year(files),
        "summary_by_file_type": _summary_by_file_type(files),
        "cross_year_column_consistency": _cross_year_column_consistency(files),
        "concerns": _build_concerns(files),
        "recommended_next_schema": _recommended_next_schema(),
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_summary(report: dict[str, Any]) -> None:
    print("USAspending funding file profile")
    print(f"Input root: {report['input_root']}")
    print(f"Output path: {report['output_path']}")
    print(f"Detected files: {len(report['files'])}")
    print()
    for fiscal_year in report["expected_fiscal_years"]:
        fiscal_summary = report["summary_by_fiscal_year"].get(fiscal_year)
        if not fiscal_summary:
            print(f"{fiscal_year}: no files detected")
            continue
        print(f"{fiscal_year}: {fiscal_summary['file_count']} files, {fiscal_summary['row_count']:,} rows")
        for file_type, type_summary in sorted(fiscal_summary["file_types"].items()):
            column_counts = ",".join(str(count) for count in type_summary["column_counts"]) or "unknown"
            print(
                f"  {file_type}: {type_summary['file_count']} file(s), "
                f"{type_summary['row_count']:,} rows, columns={column_counts}"
            )
    if report["concerns"]:
        print()
        print("Concerns:")
        for concern in report["concerns"][:20]:
            print(f"  - {concern}")
        if len(report["concerns"]) > 20:
            print(f"  - ... {len(report['concerns']) - 20} more concern(s) in JSON report")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile raw USAspending CDC funding CSV exports.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--chunksize", type=int, default=DEFAULT_CHUNKSIZE)
    parser.add_argument("--sample-rows", type=int, default=DEFAULT_SAMPLE_ROWS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    report = build_report(
        input_root=args.input_root.expanduser().resolve(),
        output_path=args.output_path.expanduser().resolve(),
        chunksize=args.chunksize,
        sample_rows=args.sample_rows,
    )
    write_report(report, args.output_path.expanduser().resolve())
    print_summary(report)
    return report


if __name__ == "__main__":
    main()
