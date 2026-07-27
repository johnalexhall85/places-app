from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.db import DEFAULT_DB_URL
from app.db_schemas import CDC_FUNDING_SCHEMA

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 2000
REQUIRED_AUDIT_COUNT = 6
STATUS_VALIDATING = "validating"
STATUS_LOADING = "loading"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


def normalize_header(value: str) -> str:
    normalized = value.strip().replace("&", " and ")
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", normalized)
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").lower()
    return re.sub(r"_+", "_", normalized)


AWARD_HEADERS = [
    "Grant or Contract",
    "owning_agency_name",
    "reporting_agency_name",
    "submission_period",
    "federal_account_symbol",
    "federal_account_name",
    "program_activity_reporting_key",
    "agency_identifier_name",
    "budget_function",
    "budget_subfunction",
    "program_activity_code",
    "program_activity_name",
    "object_class_code",
    "object_class_name",
    "direct_or_reimbursable_funding_source",
    "disaster_emergency_fund_code",
    "disaster_emergency_fund_name",
    "transaction_obligated_amount",
    "gross_outlay_amount_FYB_to_period_end",
    "USSGL487200_downward_adj_prior_year_prepaid_undeliv_order_oblig",
    "USSGL497200_downward_adj_of_prior_year_paid_deliv_orders_oblig",
    "award_unique_key",
    "award_id_piid",
    "parent_award_id_piid",
    "award_id_fain",
    "award_id_uri",
    "award_base_action_date",
    "award_base_action_date_fiscal_year",
    "award_latest_action_date",
    "award_latest_action_date_fiscal_year",
    "period_of_performance_start_date",
    "period_of_performance_current_end_date",
    "ordering_period_end_date",
    "award_type_code",
    "award_type",
    "idv_type_code",
    "idv_type",
    "prime_award_base_transaction_description",
    "awarding_agency_code",
    "awarding_agency_name",
    "awarding_subagency_code",
    "awarding_subagency_name",
    "awarding_office_code",
    "awarding_office_name",
    "funding_agency_code",
    "funding_agency_name",
    "funding_sub_agency_code",
    "funding_sub_agency_name",
    "funding_office_code",
    "funding_office_name",
    "recipient_uei",
    "recipient_duns",
    "recipient_name",
    "recipient_name_raw",
    "recipient_parent_uei",
    "recipient_parent_duns",
    "recipient_parent_name",
    "recipient_parent_name_raw",
    "recipient_country",
    "recipient_state",
    "recipient_county",
    "recipient_city",
    "prime_award_summary_recipient_cd_original",
    "prime_award_summary_recipient_cd_current",
    "recipient_zip_code",
    "primary_place_of_performance_country",
    "primary_place_of_performance_state",
    "primary_place_of_performance_county",
    "prime_award_summary_place_of_performance_cd_original",
    "prime_award_summary_place_of_performance_cd_current",
    "primary_place_of_performance_zip_code",
    "cfda_number",
    "cfda_title",
    "product_or_service_code",
    "product_or_service_code_description",
    "naics_code",
    "naics_description",
    "national_interest_action_code",
    "national_interest_action",
    "usaspending_permalink",
    "last_modified_date",
    "Emergency",
]


@dataclass(frozen=True)
class CsvSpec:
    file_type: str
    filename: str
    table_name: str
    headers: list[str]
    alternate_filenames: tuple[str, ...] = ()
    alternate_headers: dict[str, list[str]] = field(default_factory=dict)

    @property
    def db_columns(self) -> list[str]:
        return [normalize_header(header) for header in self.headers]

    @property
    def filename_templates(self) -> tuple[str, ...]:
        return (self.filename, *self.alternate_filenames)

    def matching_headers(self, actual_headers: list[str]) -> list[str]:
        if actual_headers == self.headers:
            return self.headers
        for headers in self.alternate_headers.values():
            if actual_headers == headers:
                return headers
        return self.headers


CSV_SPECS = [
    CsvSpec(
        "awards",
        "FY{fiscal_year}_CDC_awards_clean.csv",
        "cdc_funding_awards",
        AWARD_HEADERS,
    ),
    CsvSpec(
        "account_annual",
        "FY{fiscal_year}_CDC_account_summary.csv",
        "cdc_funding_account_annual",
        [
            "fiscal_year",
            "grant_or_contract",
            "emergency",
            "federal_account_symbol",
            "federal_account_name",
            "row_count",
            "numeric_obligation_rows",
            "transaction_obligated_amount",
            "gross_outlay_amount_FYB_to_period_end",
        ],
    ),
    CsvSpec(
        "account_monthly",
        "FY{fiscal_year}_CDC_monthly_account_summary.csv",
        "cdc_funding_account_monthly",
        [
            "fiscal_year",
            "submission_period",
            "fiscal_quarter",
            "period_label",
            "grant_or_contract",
            "emergency",
            "federal_account_symbol",
            "federal_account_name",
            "row_count",
            "numeric_obligation_rows",
            "transaction_obligated_amount",
            "numeric_outlay_rows",
            "gross_outlay_amount_FYB_to_period_end",
        ],
    ),
    CsvSpec(
        "account_quarterly",
        "FY{fiscal_year}_CDC_quarterly_account_summary.csv",
        "cdc_funding_account_quarterly",
        [
            "fiscal_year",
            "fiscal_quarter",
            "grant_or_contract",
            "emergency",
            "federal_account_symbol",
            "federal_account_name",
            "row_count",
            "numeric_obligation_rows",
            "transaction_obligated_amount",
            "numeric_outlay_rows",
            "gross_outlay_amount_FYB_to_period_end",
        ],
    ),
    CsvSpec(
        "category_comparison",
        "FY{fiscal_year}_CFP_category_comparison.csv",
        "cdc_funding_category_comparison",
        [
            "fiscal_year",
            "category",
            "mapping_status",
            "reference_detail_rows",
            "mapped_account_rows",
            "cfp_obligations",
            "usaspending_obligations",
            "usaspending_outlays",
            "difference_usaspending_minus_cfp",
            "percent_difference",
        ],
        alternate_filenames=("FY{fiscal_year}_category_summary.csv",),
        alternate_headers={
            "category_summary.csv": [
                "fiscal_year",
                "category",
                "mapping_status",
                "mapped_account_rows",
                "usaspending_obligations",
                "usaspending_outlays",
                "methodology_note",
            ],
            "category_summary_2026.csv": [
                "fiscal_year",
                "data_status",
                "as_of_period",
                "category",
                "mapping_status",
                "mapped_account_rows",
                "usaspending_obligations",
                "usaspending_outlays",
                "methodology_note",
            ],
        },
    ),
    CsvSpec(
        "category_monthly",
        "FY{fiscal_year}_CFP_category_monthly.csv",
        "cdc_funding_category_monthly",
        [
            "fiscal_year",
            "submission_period",
            "fiscal_quarter",
            "period_label",
            "category",
            "row_count",
            "numeric_obligation_rows",
            "transaction_obligated_amount",
            "numeric_outlay_rows",
            "gross_outlay_amount_FYB_to_period_end",
        ],
    ),
    CsvSpec(
        "category_quarterly",
        "FY{fiscal_year}_CFP_category_quarterly.csv",
        "cdc_funding_category_quarterly",
        [
            "fiscal_year",
            "fiscal_quarter",
            "category",
            "row_count",
            "numeric_obligation_rows",
            "transaction_obligated_amount",
            "numeric_outlay_rows",
            "gross_outlay_amount_FYB_to_period_end",
        ],
    ),
    CsvSpec(
        "category_mapping",
        "FY{fiscal_year}_CFP_mapping_detail.csv",
        "cdc_funding_category_mapping",
        [
            "fiscal_year",
            "category",
            "mapping_status",
            "grant_or_contract",
            "emergency",
            "federal_account_symbol",
            "federal_account_name",
            "transaction_obligated_amount",
            "row_count",
            "name_matches_expectation",
            "notes",
        ],
        alternate_filenames=("FY{fiscal_year}_category_mapping_detail.csv",),
        alternate_headers={
            "category_mapping_detail.csv": [
                "fiscal_year",
                "category",
                "mapping_status",
                "grant_or_contract",
                "emergency",
                "federal_account_symbol",
                "expected_account_name",
                "actual_account_name",
                "account_name_match",
                "transaction_obligated_amount",
                "notes",
            ],
        },
    ),
    CsvSpec(
        "unmapped_accounts",
        "FY{fiscal_year}_CFP_unmapped_accounts.csv",
        "cdc_funding_unmapped_accounts",
        [
            "fiscal_year",
            "grant_or_contract",
            "emergency",
            "federal_account_symbol",
            "federal_account_name",
            "row_count",
            "numeric_obligation_rows",
            "transaction_obligated_amount",
            "gross_outlay_amount_FYB_to_period_end",
            "reason",
        ],
        alternate_filenames=("FY{fiscal_year}_category_unmapped_accounts.csv",),
    ),
]

AUDIT_FILES = [
    "FY{fiscal_year}_CFP_comparison_audit.json",
    "FY{fiscal_year}_CFP_reference_validation.json",
    "FY{fiscal_year}_period_reference_validation.json",
    "FY{fiscal_year}_period_summary_audit.json",
    "FY{fiscal_year}_pipeline_audit.json",
    "FY{fiscal_year}_reference_validation.json",
]

AUDIT_FILE_GROUPS = [
    (
        "category_summary_audit",
        ("FY{fiscal_year}_CFP_comparison_audit.json", "FY{fiscal_year}_category_summary_audit.json"),
    ),
    (
        "category_reference_validation",
        ("FY{fiscal_year}_CFP_reference_validation.json", "FY{fiscal_year}_category_reference_validation.json"),
    ),
    ("period_reference_validation", ("FY{fiscal_year}_period_reference_validation.json",)),
    ("period_summary_audit", ("FY{fiscal_year}_period_summary_audit.json",)),
    ("pipeline_audit", ("FY{fiscal_year}_pipeline_audit.json",)),
    ("reference_validation", ("FY{fiscal_year}_reference_validation.json",)),
]

CSV_SPECS_BY_TYPE = {spec.file_type: spec for spec in CSV_SPECS}
CSV_SPECS_BY_FILENAME_TEMPLATE = {spec.filename: spec for spec in CSV_SPECS}

MONEY_COLUMNS = {
    "transaction_obligated_amount",
    "gross_outlay_amount_fyb_to_period_end",
    "ussgl487200_downward_adj_prior_year_prepaid_undeliv_order_oblig",
    "ussgl497200_downward_adj_of_prior_year_paid_deliv_orders_oblig",
    "cfp_obligations",
    "usaspending_obligations",
    "usaspending_outlays",
    "difference_usaspending_minus_cfp",
}
PERCENT_COLUMNS = {"percent_difference"}
DATE_COLUMNS = {
    "award_base_action_date",
    "award_latest_action_date",
    "period_of_performance_start_date",
    "period_of_performance_current_end_date",
    "ordering_period_end_date",
    "last_modified_date",
}
INT_COLUMNS = {
    "fiscal_year",
    "award_base_action_date_fiscal_year",
    "award_latest_action_date_fiscal_year",
    "row_count",
    "numeric_obligation_rows",
    "numeric_outlay_rows",
    "reference_detail_rows",
    "mapped_account_rows",
}
BOOL_COLUMNS = {"name_matches_expectation", "account_name_match"}

FY2023_EXPECTED = {
    "rows": {
        "awards": 146293,
        "account_annual": 72,
        "account_monthly": 701,
        "account_quarterly": 262,
        "category_comparison": 17,
        "category_monthly": 165,
        "category_quarterly": 60,
        "category_mapping": 19,
        "unmapped_accounts": 55,
        "audits": 6,
    },
    "award_grants": 86826,
    "award_contracts": 59467,
    "award_emergency": 35627,
    "award_non_emergency": 110666,
    "award_numeric_obligation_rows": 15972,
    "award_obligations": Decimal("18654414464.47"),
    "annual_obligations": Decimal("18654414464.47"),
    "mapped_category_obligations": Decimal("15319611532.00"),
    "unmapped_obligations": Decimal("3334802932.47"),
    "mapped_plus_unmapped": Decimal("18654414464.47"),
    "cfp_reference_total": Decimal("15164515008.00"),
    "mapping_reconciliation_difference": Decimal("0.00"),
    "quarters": {
        "Q1": Decimal("4509072828.31"),
        "Q2": Decimal("2633431434.13"),
        "Q3": Decimal("6085957664.86"),
        "Q4": Decimal("5425952537.17"),
    },
    "reference_categories": 17,
    "mapped_categories": 15,
    "no_match_categories": 2,
    "mapping_rows": 19,
    "matched_account_summary_rows": 17,
    "unmapped_account_summary_rows": 55,
    "duplicate_mapped_account_summary_keys": 0,
    "account_name_mismatches": 0,
    "no_match_category_names": {
        "Childhood Obesity Demonstration Project",
        "Health Reform - Toxic Substances & Environmental Public Health",
    },
}


@dataclass
class FileManifest:
    file_name: str
    file_type: str
    path: Path
    file_size_bytes: int
    sha256: str
    row_count: int | None = None
    passed: bool | None = None
    audit_payload: dict[str, Any] | None = None


@dataclass
class ValidationResult:
    fiscal_year: int
    source_dir: Path
    files: list[FileManifest]
    row_counts: dict[str, int] = field(default_factory=dict)
    award_counts: dict[str, int] = field(default_factory=dict)
    totals: dict[str, Decimal] = field(default_factory=dict)
    quarter_totals: dict[str, Decimal] = field(default_factory=dict)
    category_controls: dict[str, Any] = field(default_factory=dict)
    audit_controls: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def manifest_json(self) -> dict[str, Any]:
        return {
            "fiscal_year": self.fiscal_year,
            "source_dir": str(self.source_dir),
            "files": [
                {
                    "file_name": file.file_name,
                    "file_type": file.file_type,
                    "file_size_bytes": file.file_size_bytes,
                    "sha256": file.sha256,
                    "row_count": file.row_count,
                    "passed": file.passed,
                }
                for file in self.files
            ],
            "row_counts": self.row_counts,
            "award_counts": self.award_counts,
            "totals": {key: str(value) for key, value in self.totals.items()},
            "quarter_totals": {key: str(value) for key, value in self.quarter_totals.items()},
            "category_controls": self.category_controls,
            "audit_controls": self.audit_controls,
            "checks": self.checks,
        }


class CdcFundingImportError(RuntimeError):
    pass


def parse_amount(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    cleaned = value.strip().replace("$", "").replace(",", "")
    if cleaned == "":
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation as exc:
        raise CdcFundingImportError(f"Invalid decimal value {value!r}") from exc
    return -parsed if negative else parsed


def parse_outlay_amount(value: str | None) -> Decimal | None:
    if value is None or value.strip() == "":
        return None
    cleaned = value.strip()
    if not re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d{1,2})?", cleaned):
        raise CdcFundingImportError(
            f"Invalid outlay decimal value {value!r}; expected an unformatted "
            "value with at most two decimal places"
        )
    return Decimal(cleaned)


def parse_date(value: str | None) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CdcFundingImportError(f"Invalid ISO date value {value!r}") from exc


def parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise CdcFundingImportError(f"Invalid integer value {value!r}") from exc


def parse_outlay_count(value: str | None) -> int | None:
    parsed = parse_int(value)
    if parsed is not None and parsed < 0:
        raise CdcFundingImportError(
            f"Invalid negative numeric_outlay_rows value {value!r}"
        )
    return parsed


def parse_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "t", "1", "yes", "y"}:
        return True
    if lowered in {"false", "f", "0", "no", "n"}:
        return False
    raise CdcFundingImportError(f"Invalid boolean value {value!r}")


def parse_cell(column: str, value: str | None) -> Any:
    if value == "":
        return None
    if column in {
        "gross_outlay_amount_fyb_to_period_end",
        "usaspending_outlays",
    }:
        return parse_outlay_amount(value)
    if column == "numeric_outlay_rows":
        return parse_outlay_count(value)
    if column in MONEY_COLUMNS or column in PERCENT_COLUMNS:
        return parse_amount(value)
    if column in DATE_COLUMNS:
        return parse_date(value)
    if column in INT_COLUMNS:
        return parse_int(value)
    if column in BOOL_COLUMNS:
        return parse_bool(value)
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_csv_path(source_dir: Path, spec: CsvSpec, fiscal_year: int) -> Path:
    return source_dir / spec.filename.format(fiscal_year=fiscal_year)


def resolve_csv_path(source_dir: Path, spec: CsvSpec, fiscal_year: int) -> Path:
    for template in spec.filename_templates:
        path = source_dir / template.format(fiscal_year=fiscal_year)
        if path.exists():
            return path
    return expected_csv_path(source_dir, spec, fiscal_year)


def expected_audit_path(source_dir: Path, template: str, fiscal_year: int) -> Path:
    return source_dir / template.format(fiscal_year=fiscal_year)


def resolve_audit_path(source_dir: Path, templates: tuple[str, ...], fiscal_year: int) -> Path:
    for template in templates:
        path = expected_audit_path(source_dir, template, fiscal_year)
        if path.exists():
            return path
    return expected_audit_path(source_dir, templates[0], fiscal_year)


def validate_headers(file_name: str, actual: list[str], expected: list[str]) -> None:
    if actual == expected:
        return
    missing = [header for header in expected if header not in actual]
    unexpected = [header for header in actual if header not in expected]
    reordered = not missing and not unexpected and actual != expected
    details = []
    if missing:
        details.append(f"missing={missing}")
    if unexpected:
        details.append(f"unexpected={unexpected}")
    if reordered:
        details.append("columns are present but reordered")
    raise CdcFundingImportError(f"Header validation failed for {file_name}: {'; '.join(details)}")


def _validate_csv_file(path: Path, spec: CsvSpec, fiscal_year: int) -> tuple[int, Counter[str], Decimal]:
    row_count = 0
    award_counts: Counter[str] = Counter()
    obligation_total = Decimal("0.00")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = spec.matching_headers(reader.fieldnames or [])
        validate_headers(path.name, reader.fieldnames or [], headers)
        for row in reader:
            row_count += 1
            normalized_row = {normalize_header(key): parse_cell(normalize_header(key), value) for key, value in row.items()}
            row_year = normalized_row.get("fiscal_year")
            if row_year is not None and row_year != fiscal_year:
                raise CdcFundingImportError(
                    f"{path.name} row {row_count}: expected fiscal_year {fiscal_year}, got {row_year}"
                )
            if spec.file_type == "awards":
                period = str(normalized_row.get("submission_period") or "")
                if period and not period.startswith(f"FY{fiscal_year}"):
                    raise CdcFundingImportError(
                        f"{path.name} row {row_count}: submission_period {period!r} is not FY{fiscal_year}"
                    )
                if normalized_row.get("grant_or_contract") == "Grant":
                    award_counts["grants"] += 1
                if normalized_row.get("grant_or_contract") == "Contract":
                    award_counts["contracts"] += 1
                if normalized_row.get("emergency") == "Emergency":
                    award_counts["emergency"] += 1
                if normalized_row.get("emergency") == "NonEmergency":
                    award_counts["non_emergency"] += 1
                amount = normalized_row.get("transaction_obligated_amount")
                if amount is not None:
                    award_counts["numeric_obligation_rows"] += 1
                    obligation_total += amount
    return row_count, award_counts, obligation_total


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validation_checks_pass(payload: dict[str, Any]) -> bool:
    if payload.get("passed") is False:
        return False
    checks = payload.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict) and check.get("passed") is False:
                return False
    return True


def _audit_type(file_name: str, fiscal_year: int) -> str:
    prefix = f"FY{fiscal_year}_"
    stem = file_name.removesuffix(".json")
    return stem[len(prefix) :] if stem.startswith(prefix) else stem


def _add_check(result: ValidationResult, name: str, expected: Any, actual: Any) -> None:
    passed = expected == actual
    check = {
        "name": name,
        "expected": str(expected),
        "actual": str(actual),
        "passed": passed,
    }
    if isinstance(expected, Decimal) and isinstance(actual, Decimal):
        check["difference"] = str(actual - expected)
    result.checks.append(check)
    if not passed:
        raise CdcFundingImportError(
            f"Acceptance control failed for {name}: expected {expected}, actual {actual}"
        )


def validate_source_files(source_dir: Path, fiscal_year: int) -> ValidationResult:
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.exists():
        raise CdcFundingImportError(f"Source directory does not exist: {source_dir}")

    manifests: list[FileManifest] = []
    result = ValidationResult(fiscal_year=fiscal_year, source_dir=source_dir, files=manifests)

    missing: list[str] = []
    for spec in CSV_SPECS:
        path = resolve_csv_path(source_dir, spec, fiscal_year)
        if not path.exists():
            expected_names = [template.format(fiscal_year=fiscal_year) for template in spec.filename_templates]
            missing.append(" or ".join(expected_names))
    for _audit_type_name, templates in AUDIT_FILE_GROUPS:
        path = resolve_audit_path(source_dir, templates, fiscal_year)
        if not path.exists():
            expected_names = [template.format(fiscal_year=fiscal_year) for template in templates]
            missing.append(" or ".join(expected_names))
    if missing:
        raise CdcFundingImportError(f"Missing required CDC funding file(s): {', '.join(missing)}")

    for spec in CSV_SPECS:
        path = resolve_csv_path(source_dir, spec, fiscal_year)
        row_count, award_counts, obligation_total = _validate_csv_file(path, spec, fiscal_year)
        result.row_counts[spec.file_type] = row_count
        if spec.file_type == "awards":
            result.award_counts = dict(award_counts)
            result.totals["award_obligations"] = obligation_total
        manifests.append(
            FileManifest(
                file_name=path.name,
                file_type=spec.file_type,
                path=path,
                file_size_bytes=path.stat().st_size,
                sha256=file_sha256(path),
                row_count=row_count,
            )
        )

    for _audit_type_name, templates in AUDIT_FILE_GROUPS:
        path = resolve_audit_path(source_dir, templates, fiscal_year)
        payload = _load_json(path)
        payload_year = payload.get("fiscal_year")
        if payload_year is not None and int(payload_year) != fiscal_year:
            raise CdcFundingImportError(
                f"{path.name}: expected fiscal_year {fiscal_year}, got {payload_year}"
            )
        passed = payload.get("passed") if "passed" in payload else None
        if not _validation_checks_pass(payload):
            raise CdcFundingImportError(f"{path.name}: audit validation did not pass")
        manifests.append(
            FileManifest(
                file_name=path.name,
                file_type=_audit_type(path.name, fiscal_year),
                path=path,
                file_size_bytes=path.stat().st_size,
                sha256=file_sha256(path),
                row_count=None,
                passed=passed,
                audit_payload=payload,
            )
        )
    result.row_counts["audits"] = REQUIRED_AUDIT_COUNT

    _compute_file_reconciliations(result)
    if fiscal_year == 2023:
        _validate_fy2023(result)
    return result


def _read_csv_rows(source_dir: Path, spec: CsvSpec, fiscal_year: int) -> list[dict[str, Any]]:
    path = resolve_csv_path(source_dir, spec, fiscal_year)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = spec.matching_headers(reader.fieldnames or [])
        validate_headers(path.name, reader.fieldnames or [], headers)
        for row in reader:
            rows.append({normalize_header(key): parse_cell(normalize_header(key), value) for key, value in row.items()})
    return rows


def _sum(rows: list[dict[str, Any]], column: str = "transaction_obligated_amount") -> Decimal:
    total = Decimal("0.00")
    for row in rows:
        value = row.get(column)
        if value is not None:
            total += value
    return total


def _compute_file_reconciliations(result: ValidationResult) -> None:
    source_dir = result.source_dir
    fiscal_year = result.fiscal_year
    annual = _read_csv_rows(source_dir, CSV_SPECS_BY_TYPE["account_annual"], fiscal_year)
    quarterly = _read_csv_rows(source_dir, CSV_SPECS_BY_TYPE["account_quarterly"], fiscal_year)
    comparison = _read_csv_rows(source_dir, CSV_SPECS_BY_TYPE["category_comparison"], fiscal_year)
    mapping = _read_csv_rows(source_dir, CSV_SPECS_BY_TYPE["category_mapping"], fiscal_year)
    unmapped = _read_csv_rows(source_dir, CSV_SPECS_BY_TYPE["unmapped_accounts"], fiscal_year)

    result.totals["annual_obligations"] = _sum(annual)
    result.totals["mapped_category_obligations"] = _sum(mapping)
    result.totals["unmapped_obligations"] = _sum(unmapped)
    result.totals["mapped_plus_unmapped"] = (
        result.totals["mapped_category_obligations"] + result.totals["unmapped_obligations"]
    )
    result.totals["cfp_reference_total"] = _sum(comparison, "cfp_obligations")
    result.totals["mapping_reconciliation_difference"] = (
        result.totals["mapped_plus_unmapped"] - result.totals["annual_obligations"]
    )
    result.quarter_totals = {
        quarter: _sum([row for row in quarterly if row.get("fiscal_quarter") == quarter])
        for quarter in ("Q1", "Q2", "Q3", "Q4")
    }
    result.category_controls = {
        "reference_categories": len({row.get("category") for row in comparison}),
        "mapped_categories": sum(1 for row in comparison if row.get("mapping_status") == "Mapped"),
        "no_match_categories": sum(1 for row in comparison if row.get("mapping_status") == "No match"),
        "mapping_rows": len(mapping),
        "matched_account_summary_rows": sum(1 for row in mapping if row.get("mapping_status") == "Mapped"),
        "unmapped_account_summary_rows": len(unmapped),
        "duplicate_mapped_account_summary_keys": _duplicate_mapping_keys(mapping),
        "account_name_mismatches": sum(1 for row in mapping if row.get("name_matches_expectation") is False),
        "no_match_category_names": sorted(
            row.get("category") for row in comparison if row.get("mapping_status") == "No match"
        ),
    }
    result.audit_controls = {
        "audit_files": REQUIRED_AUDIT_COUNT,
        "passed_validation_files": sum(1 for file in result.files if file.file_name.endswith(".json") and file.passed is True),
        "validation_files_without_passed": sum(
            1 for file in result.files if file.file_name.endswith(".json") and file.passed is None
        ),
    }


def _duplicate_mapping_keys(rows: list[dict[str, Any]]) -> int:
    keys = Counter()
    for row in rows:
        if row.get("mapping_status") != "Mapped":
            continue
        key = (
            row.get("grant_or_contract"),
            row.get("emergency"),
            row.get("federal_account_symbol"),
        )
        keys[key] += 1
    return sum(1 for count in keys.values() if count > 1)


def _validate_fy2023(result: ValidationResult) -> None:
    expected = FY2023_EXPECTED
    for file_type, row_count in expected["rows"].items():
        _add_check(result, f"{file_type} row count", row_count, result.row_counts.get(file_type))
    _add_check(result, "award Grant rows", expected["award_grants"], result.award_counts.get("grants", 0))
    _add_check(result, "award Contract rows", expected["award_contracts"], result.award_counts.get("contracts", 0))
    _add_check(result, "award Emergency rows", expected["award_emergency"], result.award_counts.get("emergency", 0))
    _add_check(
        result,
        "award NonEmergency rows",
        expected["award_non_emergency"],
        result.award_counts.get("non_emergency", 0),
    )
    _add_check(
        result,
        "award numeric obligation rows",
        expected["award_numeric_obligation_rows"],
        result.award_counts.get("numeric_obligation_rows", 0),
    )
    for key in (
        "award_obligations",
        "annual_obligations",
        "mapped_category_obligations",
        "unmapped_obligations",
        "mapped_plus_unmapped",
        "cfp_reference_total",
        "mapping_reconciliation_difference",
    ):
        _add_check(result, key, expected[key], result.totals[key])
    for quarter, quarter_total in expected["quarters"].items():
        _add_check(result, f"{quarter} obligations", quarter_total, result.quarter_totals[quarter])
    _add_check(result, "quarter total sum", expected["annual_obligations"], sum(result.quarter_totals.values(), Decimal("0.00")))
    for key in (
        "reference_categories",
        "mapped_categories",
        "no_match_categories",
        "mapping_rows",
        "matched_account_summary_rows",
        "unmapped_account_summary_rows",
        "duplicate_mapped_account_summary_keys",
        "account_name_mismatches",
    ):
        _add_check(result, key, expected[key], result.category_controls[key])
    _add_check(
        result,
        "no-match category names",
        sorted(expected["no_match_category_names"]),
        result.category_controls["no_match_category_names"],
    )


def _table(name: str, metadata: sa.MetaData, connection: Connection) -> sa.Table:
    return sa.Table(name, metadata, schema=CDC_FUNDING_SCHEMA, autoload_with=connection)


def _insert_import_run(
    connection: Connection,
    *,
    fiscal_year: int,
    source_dir: Path,
    status: str,
    mode: str,
    manifest: dict[str, Any],
    error_message: str | None = None,
) -> int:
    row = connection.execute(
        text(
            f"""
            INSERT INTO {CDC_FUNDING_SCHEMA}.cdc_funding_import_runs
                (fiscal_year, source_directory, import_status, import_mode, started_at,
                 manifest, error_message)
            VALUES
                (:fiscal_year, :source_directory, :import_status, :import_mode, now(),
                 CAST(:manifest AS jsonb), :error_message)
            RETURNING id
            """
        ),
        {
            "fiscal_year": fiscal_year,
            "source_directory": str(source_dir),
            "import_status": status,
            "import_mode": mode,
            "manifest": json.dumps(manifest),
            "error_message": error_message,
        },
    ).one()
    return int(row.id)


def _update_import_run(
    connection: Connection,
    import_run_id: int,
    *,
    status: str,
    started_monotonic: float,
    manifest: dict[str, Any],
    error_message: str | None = None,
) -> None:
    connection.execute(
        text(
            f"""
            UPDATE {CDC_FUNDING_SCHEMA}.cdc_funding_import_runs
               SET import_status = :status,
                   completed_at = now(),
                   elapsed_seconds = :elapsed_seconds,
                   manifest = CAST(:manifest AS jsonb),
                   error_message = :error_message,
                   updated_at = now()
             WHERE id = :id
            """
        ),
        {
            "id": import_run_id,
            "status": status,
            "elapsed_seconds": Decimal(str(round(time.monotonic() - started_monotonic, 3))),
            "manifest": json.dumps(manifest),
            "error_message": error_message,
        },
    )


def _existing_completed_manifest(connection: Connection, fiscal_year: int) -> dict[str, str] | None:
    rows = connection.execute(
        text(
            f"""
            SELECT file_name, sha256_checksum
              FROM {CDC_FUNDING_SCHEMA}.cdc_funding_import_files AS file
              JOIN {CDC_FUNDING_SCHEMA}.cdc_funding_import_runs AS run
                ON run.id = file.import_run_id
             WHERE run.fiscal_year = :fiscal_year
               AND run.import_status = :status
            """
        ),
        {"fiscal_year": fiscal_year, "status": STATUS_COMPLETED},
    ).all()
    if not rows:
        return None
    return {row.file_name: row.sha256_checksum for row in rows}


def _check_idempotence(
    connection: Connection,
    validation: ValidationResult,
    *,
    replace_fiscal_year: bool,
) -> str:
    existing = _existing_completed_manifest(connection, validation.fiscal_year)
    if not existing:
        return "load"
    incoming = {file.file_name: file.sha256 for file in validation.files}
    if existing == incoming:
        return STATUS_SKIPPED
    if not replace_fiscal_year:
        changed = sorted(
            file_name
            for file_name, checksum in incoming.items()
            if existing.get(file_name) != checksum
        )
        raise CdcFundingImportError(
            "Fiscal year already exists with different file checksums; rerun with "
            f"--replace-fiscal-year. Changed/new files: {', '.join(changed)}"
        )
    return "replace"


def _delete_fiscal_year(connection: Connection, fiscal_year: int) -> None:
    for table_name in (
        "cdc_funding_awards",
        "cdc_funding_account_annual",
        "cdc_funding_account_monthly",
        "cdc_funding_account_quarterly",
        "cdc_funding_category_comparison",
        "cdc_funding_category_monthly",
        "cdc_funding_category_quarterly",
        "cdc_funding_category_mapping",
        "cdc_funding_unmapped_accounts",
        "cdc_funding_audits",
        "cdc_funding_import_files",
        "cdc_funding_import_runs",
    ):
        connection.execute(
            text(f"DELETE FROM {CDC_FUNDING_SCHEMA}.{table_name} WHERE fiscal_year = :fiscal_year"),
            {"fiscal_year": fiscal_year},
        )


def _insert_import_files(connection: Connection, import_run_id: int, validation: ValidationResult) -> None:
    metadata = sa.MetaData()
    table = _table("cdc_funding_import_files", metadata, connection)
    rows = [
        {
            "import_run_id": import_run_id,
            "fiscal_year": validation.fiscal_year,
            "file_name": file.file_name,
            "file_type": file.file_type,
            "file_size_bytes": file.file_size_bytes,
            "sha256_checksum": file.sha256,
            "expected_row_count": file.row_count,
            "loaded_row_count": file.row_count,
            "load_status": STATUS_COMPLETED,
            "validation_details": {"passed": file.passed, "row_count": file.row_count},
            "error_details": None,
        }
        for file in validation.files
    ]
    connection.execute(table.insert(), rows)


def _iter_csv_load_rows(spec: CsvSpec, path: Path, fiscal_year: int, import_run_id: int):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = spec.matching_headers(reader.fieldnames or [])
        validate_headers(path.name, reader.fieldnames or [], headers)
        for source_row_number, row in enumerate(reader, start=2):
            parsed = {
                normalize_header(header): parse_cell(normalize_header(header), row[header])
                for header in headers
            }
            parsed.update(
                {
                    "import_run_id": import_run_id,
                    "source_file_name": path.name,
                    "source_row_number": source_row_number,
                    "ingested_at": datetime.now(timezone.utc),
                }
            )
            if spec.file_type == "awards":
                parsed["fiscal_year"] = fiscal_year
            yield parsed


def _load_csv(connection: Connection, spec: CsvSpec, validation: ValidationResult, import_run_id: int) -> int:
    metadata = sa.MetaData()
    table = _table(spec.table_name, metadata, connection)
    path = resolve_csv_path(validation.source_dir, spec, validation.fiscal_year)
    chunk: list[dict[str, Any]] = []
    loaded = 0
    for row in _iter_csv_load_rows(spec, path, validation.fiscal_year, import_run_id):
        chunk.append(row)
        if len(chunk) >= DEFAULT_CHUNK_SIZE:
            connection.execute(table.insert(), chunk)
            loaded += len(chunk)
            chunk.clear()
    if chunk:
        connection.execute(table.insert(), chunk)
        loaded += len(chunk)
    return loaded


def _load_audits(connection: Connection, validation: ValidationResult, import_run_id: int) -> int:
    metadata = sa.MetaData()
    table = _table("cdc_funding_audits", metadata, connection)
    rows = []
    for file in validation.files:
        if not file.file_name.endswith(".json"):
            continue
        rows.append(
            {
                "fiscal_year": validation.fiscal_year,
                "import_run_id": import_run_id,
                "audit_type": file.file_type,
                "source_file_name": file.file_name,
                "sha256_checksum": file.sha256,
                "passed": file.passed,
                "payload": file.audit_payload,
                "ingested_at": datetime.now(timezone.utc),
            }
        )
    connection.execute(table.insert(), rows)
    return len(rows)


def _db_scalar_decimal(connection: Connection, sql: str, params: dict[str, Any]) -> Decimal:
    value = connection.execute(text(sql), params).scalar()
    return Decimal(value or 0).quantize(Decimal("0.01"))


def post_load_reconciliation(connection: Connection, fiscal_year: int) -> dict[str, Any]:
    params = {"fiscal_year": fiscal_year}
    rows = {}
    for file_type, spec in CSV_SPECS_BY_TYPE.items():
        rows[file_type] = connection.execute(
            text(f"SELECT count(*) FROM {CDC_FUNDING_SCHEMA}.{spec.table_name} WHERE fiscal_year = :fiscal_year"),
            params,
        ).scalar_one()
    rows["audits"] = connection.execute(
        text(f"SELECT count(*) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_audits WHERE fiscal_year = :fiscal_year"),
        params,
    ).scalar_one()
    totals = {
        "award_obligations": _db_scalar_decimal(
            connection,
            f"SELECT sum(transaction_obligated_amount) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_awards WHERE fiscal_year = :fiscal_year",
            params,
        ),
        "annual_obligations": _db_scalar_decimal(
            connection,
            f"SELECT sum(transaction_obligated_amount) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_account_annual WHERE fiscal_year = :fiscal_year",
            params,
        ),
        "mapped_category_obligations": _db_scalar_decimal(
            connection,
            f"SELECT sum(transaction_obligated_amount) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_category_mapping WHERE fiscal_year = :fiscal_year",
            params,
        ),
        "unmapped_obligations": _db_scalar_decimal(
            connection,
            f"SELECT sum(transaction_obligated_amount) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_unmapped_accounts WHERE fiscal_year = :fiscal_year",
            params,
        ),
        "cfp_reference_total": _db_scalar_decimal(
            connection,
            f"SELECT sum(cfp_obligations) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_category_comparison WHERE fiscal_year = :fiscal_year",
            params,
        ),
    }
    totals["mapped_plus_unmapped"] = totals["mapped_category_obligations"] + totals["unmapped_obligations"]
    totals["mapping_reconciliation_difference"] = totals["mapped_plus_unmapped"] - totals["annual_obligations"]
    quarter_rows = connection.execute(
        text(
            f"""
            SELECT fiscal_quarter, sum(transaction_obligated_amount) AS total
              FROM {CDC_FUNDING_SCHEMA}.cdc_funding_account_quarterly
             WHERE fiscal_year = :fiscal_year
             GROUP BY fiscal_quarter
            """
        ),
        params,
    ).all()
    quarters = {row.fiscal_quarter: Decimal(row.total).quantize(Decimal("0.01")) for row in quarter_rows}
    award_counts = dict(
        connection.execute(
            text(
                f"""
                SELECT 'grants' AS key, count(*) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_awards
                 WHERE fiscal_year = :fiscal_year AND grant_or_contract = 'Grant'
                UNION ALL
                SELECT 'contracts', count(*) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_awards
                 WHERE fiscal_year = :fiscal_year AND grant_or_contract = 'Contract'
                UNION ALL
                SELECT 'emergency', count(*) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_awards
                 WHERE fiscal_year = :fiscal_year AND emergency = 'Emergency'
                UNION ALL
                SELECT 'non_emergency', count(*) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_awards
                 WHERE fiscal_year = :fiscal_year AND emergency = 'NonEmergency'
                UNION ALL
                SELECT 'numeric_obligation_rows', count(*) FROM {CDC_FUNDING_SCHEMA}.cdc_funding_awards
                 WHERE fiscal_year = :fiscal_year AND transaction_obligated_amount IS NOT NULL
                """
            ),
            params,
        ).all()
    )
    return {"rows": rows, "totals": totals, "quarters": quarters, "award_counts": award_counts}


def _validate_post_load_fy2023(summary: dict[str, Any]) -> None:
    expected = FY2023_EXPECTED
    for file_type, row_count in expected["rows"].items():
        if summary["rows"].get(file_type) != row_count:
            raise CdcFundingImportError(
                f"Post-load row count failed for {file_type}: expected {row_count}, actual {summary['rows'].get(file_type)}"
            )
    award_map = {
        "grants": "award_grants",
        "contracts": "award_contracts",
        "emergency": "award_emergency",
        "non_emergency": "award_non_emergency",
        "numeric_obligation_rows": "award_numeric_obligation_rows",
    }
    for actual_key, expected_key in award_map.items():
        if summary["award_counts"].get(actual_key) != expected[expected_key]:
            raise CdcFundingImportError(
                f"Post-load award count failed for {actual_key}: expected {expected[expected_key]}, "
                f"actual {summary['award_counts'].get(actual_key)}"
            )
    for key, expected_value in expected.items():
        if key in summary["totals"] and summary["totals"][key] != expected_value:
            raise CdcFundingImportError(
                f"Post-load total failed for {key}: expected {expected_value}, actual {summary['totals'][key]}"
            )
    for quarter, expected_value in expected["quarters"].items():
        if summary["quarters"].get(quarter) != expected_value:
            raise CdcFundingImportError(
                f"Post-load quarter failed for {quarter}: expected {expected_value}, actual {summary['quarters'].get(quarter)}"
            )


def run_import(
    *,
    engine: Engine,
    fiscal_year: int,
    source_dir: Path,
    dry_run: bool = False,
    replace_fiscal_year: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    validation = validate_source_files(source_dir, fiscal_year)
    if dry_run:
        return {
            "status": "dry_run",
            "manifest": validation.manifest_json,
            "message": "Dry run passed; no database changes made.",
        }

    try:
        with engine.begin() as connection:
            action = _check_idempotence(connection, validation, replace_fiscal_year=replace_fiscal_year)
            if action == STATUS_SKIPPED:
                run_id = _insert_import_run(
                    connection,
                    fiscal_year=fiscal_year,
                    source_dir=validation.source_dir,
                    status=STATUS_SKIPPED,
                    mode="replace" if replace_fiscal_year else "append",
                    manifest=validation.manifest_json,
                )
                _update_import_run(
                    connection,
                    run_id,
                    status=STATUS_SKIPPED,
                    started_monotonic=started,
                    manifest=validation.manifest_json,
                )
                return {
                    "status": STATUS_SKIPPED,
                    "import_run_id": run_id,
                    "manifest": validation.manifest_json,
                    "message": "Dataset already current; no source rows inserted.",
                }
            if action == "replace":
                _delete_fiscal_year(connection, fiscal_year)

            import_run_id = _insert_import_run(
                connection,
                fiscal_year=fiscal_year,
                source_dir=validation.source_dir,
                status=STATUS_LOADING,
                mode="replace" if replace_fiscal_year else "append",
                manifest=validation.manifest_json,
            )
            loaded = {}
            for spec in CSV_SPECS:
                loaded[spec.file_type] = _load_csv(connection, spec, validation, import_run_id)
            loaded["audits"] = _load_audits(connection, validation, import_run_id)
            _insert_import_files(connection, import_run_id, validation)

            db_summary = post_load_reconciliation(connection, fiscal_year)
            if fiscal_year == 2023:
                _validate_post_load_fy2023(db_summary)
            manifest = validation.manifest_json | {"loaded_rows": loaded, "post_load": _json_safe(db_summary)}
            _update_import_run(
                connection,
                import_run_id,
                status=STATUS_COMPLETED,
                started_monotonic=started,
                manifest=manifest,
            )
            return {
                "status": STATUS_COMPLETED,
                "import_run_id": import_run_id,
                "manifest": manifest,
                "loaded_rows": loaded,
                "post_load": db_summary,
            }
    except Exception as exc:
        try:
            with engine.begin() as connection:
                _insert_import_run(
                    connection,
                    fiscal_year=fiscal_year,
                    source_dir=validation.source_dir,
                    status=STATUS_FAILED,
                    mode="replace" if replace_fiscal_year else "append",
                    manifest=validation.manifest_json,
                    error_message=str(exc),
                )
        except Exception:
            logger.exception("Unable to persist failed CDC funding import run")
        raise


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load verified CDC funding source-of-truth files.")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--fiscal-year", type=int, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace-fiscal-year", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_argument_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    engine = sa.create_engine(args.db_url, pool_pre_ping=True, future=True)
    result = run_import(
        engine=engine,
        fiscal_year=args.fiscal_year,
        source_dir=args.source_dir,
        dry_run=args.dry_run,
        replace_fiscal_year=args.replace_fiscal_year,
    )
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
