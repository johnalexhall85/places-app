from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.cdc_funding import source_ingest
from app.db import DEFAULT_DB_URL
from app.db_schemas import CDC_FUNDING_SCHEMA

logger = logging.getLogger(__name__)

ZERO_MONEY = Decimal("0.00")
MONEY_QUANT = Decimal("0.01")
IGNORED_METADATA_COLUMNS = {"data_status", "as_of_period"}


class CdcFundingOutlayBackfillError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackfillTableSpec:
    file_type: str
    key_columns: tuple[str, ...]
    outlay_columns: tuple[str, ...]

    @property
    def csv_spec(self) -> source_ingest.CsvSpec:
        return source_ingest.CSV_SPECS_BY_TYPE[self.file_type]

    @property
    def table_name(self) -> str:
        return self.csv_spec.table_name


BACKFILL_TABLES = (
    BackfillTableSpec(
        "account_annual",
        ("fiscal_year", "grant_or_contract", "emergency", "federal_account_symbol"),
        ("gross_outlay_amount_fyb_to_period_end",),
    ),
    BackfillTableSpec(
        "account_monthly",
        ("fiscal_year", "submission_period", "grant_or_contract", "emergency", "federal_account_symbol"),
        ("numeric_outlay_rows", "gross_outlay_amount_fyb_to_period_end"),
    ),
    BackfillTableSpec(
        "account_quarterly",
        ("fiscal_year", "fiscal_quarter", "grant_or_contract", "emergency", "federal_account_symbol"),
        ("numeric_outlay_rows", "gross_outlay_amount_fyb_to_period_end"),
    ),
    BackfillTableSpec(
        "category_comparison",
        ("fiscal_year", "category"),
        ("usaspending_outlays",),
    ),
    BackfillTableSpec(
        "category_monthly",
        ("fiscal_year", "submission_period", "category"),
        ("numeric_outlay_rows", "gross_outlay_amount_fyb_to_period_end"),
    ),
    BackfillTableSpec(
        "category_quarterly",
        ("fiscal_year", "fiscal_quarter", "category"),
        ("numeric_outlay_rows", "gross_outlay_amount_fyb_to_period_end"),
    ),
    BackfillTableSpec(
        "unmapped_accounts",
        ("fiscal_year", "grant_or_contract", "emergency", "federal_account_symbol"),
        ("gross_outlay_amount_fyb_to_period_end",),
    ),
)


@dataclass
class CsvData:
    path: Path
    checksum: str
    file_size_bytes: int
    columns: tuple[str, ...]
    rows: list[dict[str, Any]]


@dataclass
class SourcePair:
    spec: BackfillTableSpec
    original: CsvData
    updated: CsvData
    ignored_added_columns: tuple[str, ...]


@dataclass
class TablePlan:
    fiscal_year: int
    pair: SourcePair
    updates: list[dict[str, Any]]
    existing_null_fields: int
    existing_matching_fields: int
    existing_conflicting_fields: int
    missing_schema_columns: tuple[str, ...]
    non_outlay_fingerprint: str
    source_value_counts: dict[str, int]

    @property
    def rows_updated(self) -> int:
        return len(self.updates)

    @property
    def fields_updated(self) -> int:
        return sum(len(update["values"]) for update in self.updates)

    def report(self) -> dict[str, Any]:
        return {
            "original_file": self.pair.original.path.name,
            "updated_file": self.pair.updated.path.name,
            "original_sha256": self.pair.original.checksum,
            "updated_sha256": self.pair.updated.checksum,
            "original_file_size_bytes": self.pair.original.file_size_bytes,
            "updated_file_size_bytes": self.pair.updated.file_size_bytes,
            "original_row_count": len(self.pair.original.rows),
            "updated_row_count": len(self.pair.updated.rows),
            "natural_key_match": True,
            "non_outlay_comparison": "matched",
            "database_row_match": True,
            "ignored_added_metadata_columns": list(self.pair.ignored_added_columns),
            "outlay_columns": list(self.pair.spec.outlay_columns),
            "missing_schema_columns": list(self.missing_schema_columns),
            "existing_null_outlay_fields": self.existing_null_fields,
            "existing_matching_outlay_fields": self.existing_matching_fields,
            "existing_conflicting_outlay_fields": self.existing_conflicting_fields,
            "rows_updated": self.rows_updated,
            "fields_updated": self.fields_updated,
            "source_value_counts": self.source_value_counts,
            "non_outlay_fingerprint": self.non_outlay_fingerprint,
        }


def parse_fiscal_years(value: str) -> list[int]:
    years: set[int] = set()
    for token in value.split(","):
        part = token.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            try:
                start = int(start_text)
                end = int(end_text)
            except ValueError as exc:
                raise argparse.ArgumentTypeError(f"Invalid fiscal-year range {part!r}") from exc
            if start > end:
                raise argparse.ArgumentTypeError(f"Invalid descending fiscal-year range {part!r}")
            years.update(range(start, end + 1))
        else:
            try:
                years.add(int(part))
            except ValueError as exc:
                raise argparse.ArgumentTypeError(f"Invalid fiscal year {part!r}") from exc
    if not years:
        raise argparse.ArgumentTypeError("At least one fiscal year is required")
    return sorted(years)


def _natural_key(spec: BackfillTableSpec, row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(column) for column in spec.key_columns)


def _format_key(spec: BackfillTableSpec, key: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(spec.key_columns, key, strict=True))


def _read_csv(path: Path, fiscal_year: int, spec: BackfillTableSpec) -> CsvData:
    if not path.exists():
        raise CdcFundingOutlayBackfillError(f"Missing required source file: {path}")
    rows: list[dict[str, Any]] = []
    keys: set[tuple[Any, ...]] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        raw_headers = reader.fieldnames or []
        columns = tuple(source_ingest.normalize_header(header) for header in raw_headers)
        if len(columns) != len(set(columns)):
            raise CdcFundingOutlayBackfillError(
                f"{path.name} contains duplicate normalized column names"
            )
        for row_number, raw_row in enumerate(reader, start=2):
            try:
                row = {
                    source_ingest.normalize_header(header): source_ingest.parse_cell(
                        source_ingest.normalize_header(header),
                        raw_row[header],
                    )
                    for header in raw_headers
                }
            except source_ingest.CdcFundingImportError as exc:
                raise CdcFundingOutlayBackfillError(
                    f"{path.name} row {row_number}: {exc}"
                ) from exc
            if row.get("fiscal_year") != fiscal_year:
                raise CdcFundingOutlayBackfillError(
                    f"{path.name} row {row_number}: expected fiscal_year {fiscal_year}, "
                    f"got {row.get('fiscal_year')}"
                )
            key = _natural_key(spec, row)
            if any(value is None for value in key):
                raise CdcFundingOutlayBackfillError(
                    f"{path.name} row {row_number}: blank natural key {_format_key(spec, key)}"
                )
            if key in keys:
                raise CdcFundingOutlayBackfillError(
                    f"{path.name} row {row_number}: duplicate natural key {_format_key(spec, key)}"
                )
            keys.add(key)
            rows.append(row)
    return CsvData(
        path=path,
        checksum=source_ingest.file_sha256(path),
        file_size_bytes=path.stat().st_size,
        columns=columns,
        rows=rows,
    )


def _compare_value(column: str, left: Any, right: Any) -> bool:
    if column in source_ingest.MONEY_COLUMNS or column in source_ingest.PERCENT_COLUMNS:
        if left is None or right is None:
            return left is None and right is None
        return Decimal(left) == Decimal(right)
    return left == right


def _resolve_matching_paths(
    original_dir: Path,
    updated_dir: Path,
    spec: BackfillTableSpec,
    fiscal_year: int,
) -> tuple[Path, Path]:
    updated_path = source_ingest.resolve_csv_path(updated_dir, spec.csv_spec, fiscal_year)
    original_path = original_dir / updated_path.name
    if not original_path.exists():
        raise CdcFundingOutlayBackfillError(
            f"No original file with matching base filename for {updated_path.name}: {original_path}"
        )
    return original_path, updated_path


def _validate_source_pair(
    original: CsvData,
    updated: CsvData,
    spec: BackfillTableSpec,
) -> SourcePair:
    original_columns = set(original.columns)
    updated_columns = set(updated.columns)
    missing_original = sorted(original_columns - updated_columns)
    if missing_original:
        raise CdcFundingOutlayBackfillError(
            f"{updated.path.name} removed original column(s): {', '.join(missing_original)}"
        )
    missing_outlays = sorted(set(spec.outlay_columns) - updated_columns)
    if missing_outlays:
        raise CdcFundingOutlayBackfillError(
            f"{updated.path.name} is missing required outlay column(s): {', '.join(missing_outlays)}"
        )
    added = updated_columns - original_columns
    allowed_added = set(spec.outlay_columns) | IGNORED_METADATA_COLUMNS
    unexpected_added = sorted(added - allowed_added)
    if unexpected_added:
        raise CdcFundingOutlayBackfillError(
            f"{updated.path.name} added unexpected non-outlay column(s): "
            f"{', '.join(unexpected_added)}"
        )

    original_by_key = {_natural_key(spec, row): row for row in original.rows}
    updated_by_key = {_natural_key(spec, row): row for row in updated.rows}
    if set(original_by_key) != set(updated_by_key):
        original_only = sorted(set(original_by_key) - set(updated_by_key), key=str)
        updated_only = sorted(set(updated_by_key) - set(original_by_key), key=str)
        raise CdcFundingOutlayBackfillError(
            f"{updated.path.name} natural-key set changed; "
            f"original-only={[_format_key(spec, key) for key in original_only[:5]]}; "
            f"updated-only={[_format_key(spec, key) for key in updated_only[:5]]}"
        )
    if len(original.rows) != len(updated.rows):
        raise CdcFundingOutlayBackfillError(
            f"{updated.path.name} row count changed from {len(original.rows)} "
            f"to {len(updated.rows)}"
        )

    for key, original_row in original_by_key.items():
        updated_row = updated_by_key[key]
        for column in original.columns:
            if not _compare_value(column, original_row.get(column), updated_row.get(column)):
                raise CdcFundingOutlayBackfillError(
                    f"Original source value changed: file={updated.path.name} "
                    f"key={_format_key(spec, key)} column={column} "
                    f"original={original_row.get(column)!r} updated={updated_row.get(column)!r}"
                )
    return SourcePair(
        spec=spec,
        original=original,
        updated=updated,
        ignored_added_columns=tuple(sorted(added & IGNORED_METADATA_COLUMNS)),
    )


def load_source_year(
    original_root: Path,
    updated_root: Path,
    fiscal_year: int,
) -> dict[str, SourcePair]:
    original_dir = original_root / f"FY{fiscal_year}"
    updated_dir = updated_root / f"FY{fiscal_year}"
    if not original_dir.is_dir():
        raise CdcFundingOutlayBackfillError(
            f"Missing original fiscal-year folder: {original_dir}"
        )
    if not updated_dir.is_dir():
        raise CdcFundingOutlayBackfillError(
            f"Missing updated fiscal-year folder: {updated_dir}"
        )
    pairs: dict[str, SourcePair] = {}
    for spec in BACKFILL_TABLES:
        original_path, updated_path = _resolve_matching_paths(
            original_dir,
            updated_dir,
            spec,
            fiscal_year,
        )
        pairs[spec.file_type] = _validate_source_pair(
            _read_csv(original_path, fiscal_year, spec),
            _read_csv(updated_path, fiscal_year, spec),
            spec,
        )
    return pairs


def _decimal_total(rows: Iterable[dict[str, Any]], column: str) -> Decimal:
    return sum(
        (value for row in rows if (value := row.get(column)) is not None),
        ZERO_MONEY,
    ).quantize(MONEY_QUANT)


def _latest_period(rows: list[dict[str, Any]]) -> str:
    periods = {str(row.get("submission_period") or "") for row in rows}
    valid = {period for period in periods if re.fullmatch(r"FY\d{4}P\d{2}", period)}
    if valid != periods or not valid:
        raise CdcFundingOutlayBackfillError(
            f"Unable to identify latest submission period from {sorted(periods)}"
        )
    return max(valid, key=lambda period: int(period[-2:]))


def _latest_quarter(rows: list[dict[str, Any]]) -> str:
    quarters = {str(row.get("fiscal_quarter") or "") for row in rows}
    if not quarters or any(quarter not in {"Q1", "Q2", "Q3", "Q4"} for quarter in quarters):
        raise CdcFundingOutlayBackfillError(
            f"Unable to identify latest quarter from {sorted(quarters)}"
        )
    return max(quarters, key=lambda quarter: int(quarter[1:]))


def _audit_payload(source_dir: Path, fiscal_year: int, names: tuple[str, ...]) -> dict[str, Any]:
    for template in names:
        path = source_dir / template.format(fiscal_year=fiscal_year)
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
    raise CdcFundingOutlayBackfillError(
        "Missing outlay audit: "
        + " or ".join(template.format(fiscal_year=fiscal_year) for template in names)
    )


def _assert_money(label: str, actual: Decimal, expected: Decimal) -> None:
    if actual != expected:
        raise CdcFundingOutlayBackfillError(
            f"Outlay reconciliation failed for {label}: "
            f"expected {expected:.2f}, actual {actual:.2f}"
        )


def validate_source_reconciliation(
    updated_root: Path,
    fiscal_year: int,
    pairs: dict[str, SourcePair],
) -> dict[str, str]:
    rows = {file_type: pair.updated.rows for file_type, pair in pairs.items()}
    annual = _decimal_total(
        rows["account_annual"],
        "gross_outlay_amount_fyb_to_period_end",
    )
    mapped = _decimal_total(rows["category_comparison"], "usaspending_outlays")
    unmapped = _decimal_total(
        rows["unmapped_accounts"],
        "gross_outlay_amount_fyb_to_period_end",
    )
    _assert_money(f"FY{fiscal_year} mapped plus unmapped", mapped + unmapped, annual)

    latest_period = _latest_period(rows["account_monthly"])
    latest_quarter = _latest_quarter(rows["account_quarterly"])
    account_monthly = _decimal_total(
        [row for row in rows["account_monthly"] if row["submission_period"] == latest_period],
        "gross_outlay_amount_fyb_to_period_end",
    )
    account_quarterly = _decimal_total(
        [row for row in rows["account_quarterly"] if row["fiscal_quarter"] == latest_quarter],
        "gross_outlay_amount_fyb_to_period_end",
    )
    category_monthly = _decimal_total(
        [row for row in rows["category_monthly"] if row["submission_period"] == latest_period],
        "gross_outlay_amount_fyb_to_period_end",
    )
    category_quarterly = _decimal_total(
        [row for row in rows["category_quarterly"] if row["fiscal_quarter"] == latest_quarter],
        "gross_outlay_amount_fyb_to_period_end",
    )
    _assert_money(f"FY{fiscal_year} latest account monthly", account_monthly, annual)
    _assert_money(f"FY{fiscal_year} latest account quarterly", account_quarterly, annual)
    _assert_money(f"FY{fiscal_year} latest category monthly", category_monthly, mapped)
    _assert_money(f"FY{fiscal_year} latest category quarterly", category_quarterly, mapped)

    source_dir = updated_root / f"FY{fiscal_year}"
    period_audit = _audit_payload(
        source_dir,
        fiscal_year,
        ("FY{fiscal_year}_period_summary_audit.json",),
    )
    category_audit = _audit_payload(
        source_dir,
        fiscal_year,
        (
            "FY{fiscal_year}_CFP_comparison_audit.json",
            "FY{fiscal_year}_category_summary_audit.json",
        ),
    )
    audit_values = {
        "period annual": (annual, period_audit.get("annual_outlay_total")),
        "period mapped": (mapped, period_audit.get("mapped_category_outlay_total")),
        "category annual": (
            annual,
            category_audit.get("totals", {}).get("all_usaspending_summary_outlays"),
        ),
        "category mapped": (
            mapped,
            category_audit.get("totals", {}).get("mapped_usaspending_outlays"),
        ),
        "category unmapped": (
            unmapped,
            category_audit.get("totals", {}).get("unmapped_usaspending_outlays"),
        ),
    }
    for label, (actual, raw_expected) in audit_values.items():
        try:
            expected = source_ingest.parse_outlay_amount(raw_expected)
        except source_ingest.CdcFundingImportError as exc:
            raise CdcFundingOutlayBackfillError(
                f"Invalid FY{fiscal_year} audit value for {label}: {raw_expected!r}"
            ) from exc
        if expected is None:
            raise CdcFundingOutlayBackfillError(
                f"Missing FY{fiscal_year} audit value for {label}"
            )
        _assert_money(f"FY{fiscal_year} {label}", actual, expected)
    return {
        "annual_outlays": f"{annual:.2f}",
        "mapped_outlays": f"{mapped:.2f}",
        "unmapped_outlays": f"{unmapped:.2f}",
        "reconciliation_difference": f"{mapped + unmapped - annual:.2f}",
        "latest_submission_period": latest_period,
        "latest_quarter": latest_quarter,
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _fingerprint(rows: list[dict[str, Any]], columns: Iterable[str]) -> str:
    payload = [
        {column: _json_value(row.get(column)) for column in columns}
        for row in sorted(rows, key=lambda row: int(row["id"]))
    ]
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_value_counts(pair: SourcePair) -> dict[str, int]:
    counts = {"null": 0, "zero": 0, "positive": 0, "negative": 0}
    for row in pair.updated.rows:
        for column in pair.spec.outlay_columns:
            value = row.get(column)
            if value is None:
                counts["null"] += 1
            elif value == 0:
                counts["zero"] += 1
            elif value > 0:
                counts["positive"] += 1
            else:
                counts["negative"] += 1
    return counts


def build_table_plan(
    connection: Connection,
    fiscal_year: int,
    pair: SourcePair,
    *,
    dry_run: bool,
    replace_existing_outlays: bool,
) -> TablePlan:
    metadata = sa.MetaData()
    table = sa.Table(
        pair.spec.table_name,
        metadata,
        schema=CDC_FUNDING_SCHEMA,
        autoload_with=connection,
    )
    table_columns = set(table.c.keys())
    missing_schema = tuple(sorted(set(pair.spec.outlay_columns) - table_columns))
    if missing_schema and not dry_run:
        raise CdcFundingOutlayBackfillError(
            f"{pair.spec.table_name} is missing outlay column(s): "
            f"{', '.join(missing_schema)}; run the migration first"
        )
    db_rows = [
        dict(row)
        for row in connection.execute(
            sa.select(table).where(table.c.fiscal_year == fiscal_year).order_by(table.c.id)
        ).mappings()
    ]
    db_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in db_rows:
        key = _natural_key(pair.spec, row)
        if key in db_by_key:
            raise CdcFundingOutlayBackfillError(
                f"{pair.spec.table_name} has duplicate database key "
                f"{_format_key(pair.spec, key)}"
            )
        db_by_key[key] = row
    original_by_key = {
        _natural_key(pair.spec, row): row for row in pair.original.rows
    }
    if set(db_by_key) != set(original_by_key):
        source_only = sorted(set(original_by_key) - set(db_by_key), key=str)
        db_only = sorted(set(db_by_key) - set(original_by_key), key=str)
        raise CdcFundingOutlayBackfillError(
            f"FY{fiscal_year} {pair.spec.table_name} database/source key mismatch; "
            f"source-only={[_format_key(pair.spec, key) for key in source_only[:5]]}; "
            f"database-only={[_format_key(pair.spec, key) for key in db_only[:5]]}"
        )

    db_compare_columns = [
        column
        for column in pair.original.columns
        if column not in pair.spec.outlay_columns
        and column not in IGNORED_METADATA_COLUMNS
    ]
    for key, original_row in original_by_key.items():
        db_row = db_by_key[key]
        for column in db_compare_columns:
            if column not in table_columns:
                raise CdcFundingOutlayBackfillError(
                    f"{pair.spec.table_name} is missing original database column {column}"
                )
            if not _compare_value(column, original_row.get(column), db_row.get(column)):
                raise CdcFundingOutlayBackfillError(
                    f"Database no longer matches original source: fiscal_year={fiscal_year} "
                    f"file={pair.original.path.name} key={_format_key(pair.spec, key)} "
                    f"column={column} database={db_row.get(column)!r} "
                    f"original={original_row.get(column)!r}"
                )

    updated_by_key = {
        _natural_key(pair.spec, row): row for row in pair.updated.rows
    }
    updates: list[dict[str, Any]] = []
    existing_null = 0
    existing_matching = 0
    existing_conflicting = 0
    conflicts: list[dict[str, Any]] = []
    for key, updated_row in updated_by_key.items():
        db_row = db_by_key[key]
        values: dict[str, Any] = {}
        for column in pair.spec.outlay_columns:
            source_value = updated_row.get(column)
            db_value = db_row.get(column) if column in table_columns else None
            if db_value is None:
                existing_null += 1
            if _compare_value(column, source_value, db_value):
                existing_matching += 1
                continue
            if db_value is not None and not replace_existing_outlays:
                existing_conflicting += 1
                conflicts.append(
                    {
                        "key": _format_key(pair.spec, key),
                        "column": column,
                        "database": _json_value(db_value),
                        "source": _json_value(source_value),
                    }
                )
                continue
            values[column] = source_value
        if values:
            updates.append({"id": db_row["id"], "values": values})
    if conflicts:
        first = conflicts[0]
        raise CdcFundingOutlayBackfillError(
            f"Conflicting existing outlay value: fiscal_year={fiscal_year} "
            f"file={pair.updated.path.name} key={first['key']} "
            f"column={first['column']} database={first['database']!r} "
            f"source={first['source']!r}; use --replace-existing-outlays after review"
        )

    fingerprint_columns = [
        column for column in table.c.keys() if column not in pair.spec.outlay_columns
    ]
    return TablePlan(
        fiscal_year=fiscal_year,
        pair=pair,
        updates=updates,
        existing_null_fields=existing_null,
        existing_matching_fields=existing_matching,
        existing_conflicting_fields=existing_conflicting,
        missing_schema_columns=missing_schema,
        non_outlay_fingerprint=_fingerprint(db_rows, fingerprint_columns),
        source_value_counts=_source_value_counts(pair),
    )


def _apply_plan(connection: Connection, plan: TablePlan) -> None:
    if not plan.updates:
        return
    metadata = sa.MetaData()
    table = sa.Table(
        plan.pair.spec.table_name,
        metadata,
        schema=CDC_FUNDING_SCHEMA,
        autoload_with=connection,
    )
    for update in plan.updates:
        result = connection.execute(
            table.update().where(table.c.id == update["id"]).values(**update["values"])
        )
        if result.rowcount != 1:
            raise CdcFundingOutlayBackfillError(
                f"Expected one {plan.pair.spec.table_name} update for id={update['id']}, "
                f"got {result.rowcount}"
            )


def _record_provenance(
    connection: Connection,
    source_root: Path,
    fiscal_year: int,
    plans: list[TablePlan],
    reconciliation: dict[str, str],
) -> int:
    manifest = {
        "operation": "outlay_backfill",
        "source_root": str(source_root),
        "fiscal_year": fiscal_year,
        "tables": {
            plan.pair.spec.file_type: plan.report()
            for plan in plans
        },
        "reconciliation": reconciliation,
    }
    run_id = int(
        connection.execute(
            text(
                f"""
                INSERT INTO {CDC_FUNDING_SCHEMA}.cdc_funding_import_runs
                    (fiscal_year, source_directory, import_status, import_mode,
                     started_at, completed_at, elapsed_seconds, manifest,
                     created_at, updated_at)
                VALUES
                    (:fiscal_year, :source_directory, 'completed', 'outlay_backfill',
                     now(), now(), 0, CAST(:manifest AS jsonb), now(), now())
                RETURNING id
                """
            ),
            {
                "fiscal_year": fiscal_year,
                "source_directory": str(source_root / f"FY{fiscal_year}"),
                "manifest": json.dumps(manifest),
            },
        ).scalar_one()
    )
    existing_checksums = {
        (row.file_name, row.sha256_checksum)
        for row in connection.execute(
            text(
                f"""
                SELECT file_name, sha256_checksum
                  FROM {CDC_FUNDING_SCHEMA}.cdc_funding_import_files
                 WHERE fiscal_year = :fiscal_year
                """
            ),
            {"fiscal_year": fiscal_year},
        )
    }
    for plan in plans:
        updated = plan.pair.updated
        if (updated.path.name, updated.checksum) in existing_checksums:
            continue
        connection.execute(
            text(
                f"""
                INSERT INTO {CDC_FUNDING_SCHEMA}.cdc_funding_import_files
                    (import_run_id, fiscal_year, file_name, file_type,
                     file_size_bytes, sha256_checksum, expected_row_count,
                     loaded_row_count, load_status, validation_details, created_at)
                VALUES
                    (:run_id, :fiscal_year, :file_name, :file_type,
                     :file_size_bytes, :checksum, :row_count,
                     :row_count, 'completed', CAST(:details AS jsonb), now())
                """
            ),
            {
                "run_id": run_id,
                "fiscal_year": fiscal_year,
                "file_name": updated.path.name,
                "file_type": f"outlay_backfill:{plan.pair.spec.file_type}",
                "file_size_bytes": updated.file_size_bytes,
                "checksum": updated.checksum,
                "row_count": len(updated.rows),
                "details": json.dumps(
                    {
                        "original_sha256": plan.pair.original.checksum,
                        "natural_keys_matched": True,
                        "original_values_matched": True,
                        "database_rows_matched_original": True,
                        "rows_updated": plan.rows_updated,
                        "fields_updated": plan.fields_updated,
                    }
                ),
            },
        )
    return run_id


def run_backfill(
    *,
    engine: Engine,
    original_root: Path,
    updated_root: Path,
    fiscal_years: list[int],
    dry_run: bool = False,
    replace_existing_outlays: bool = False,
) -> dict[str, Any]:
    original_root = original_root.expanduser().resolve()
    updated_root = updated_root.expanduser().resolve()
    pairs_by_year: dict[int, dict[str, SourcePair]] = {}
    reconciliations: dict[int, dict[str, str]] = {}
    for fiscal_year in fiscal_years:
        pairs_by_year[fiscal_year] = load_source_year(
            original_root,
            updated_root,
            fiscal_year,
        )
        reconciliations[fiscal_year] = validate_source_reconciliation(
            updated_root,
            fiscal_year,
            pairs_by_year[fiscal_year],
        )

    context = engine.connect() if dry_run else engine.begin()
    with context as connection:
        plans_by_year: dict[int, list[TablePlan]] = {}
        for fiscal_year in fiscal_years:
            plans_by_year[fiscal_year] = [
                build_table_plan(
                    connection,
                    fiscal_year,
                    pairs_by_year[fiscal_year][spec.file_type],
                    dry_run=dry_run,
                    replace_existing_outlays=replace_existing_outlays,
                )
                for spec in BACKFILL_TABLES
            ]
        report: dict[str, Any] = {
            "status": "dry_run" if dry_run else "completed",
            "dry_run": dry_run,
            "original_root": str(original_root),
            "updated_root": str(updated_root),
            "fiscal_years": fiscal_years,
            "years": {
                str(fiscal_year): {
                    "original_folder_found": True,
                    "updated_folder_found": True,
                    "tables": {
                        plan.pair.spec.file_type: plan.report()
                        for plan in plans_by_year[fiscal_year]
                    },
                    "reconciliation": reconciliations[fiscal_year],
                }
                for fiscal_year in fiscal_years
            },
        }
        if dry_run:
            return report

        total_fields = sum(
            plan.fields_updated
            for plans in plans_by_year.values()
            for plan in plans
        )
        if total_fields == 0:
            report["status"] = "skipped"
            report["total_rows_updated"] = 0
            report["total_fields_updated"] = 0
            return report

        for plans in plans_by_year.values():
            for plan in plans:
                _apply_plan(connection, plan)
        for fiscal_year, plans in plans_by_year.items():
            for before in plans:
                after = build_table_plan(
                    connection,
                    fiscal_year,
                    before.pair,
                    dry_run=False,
                    replace_existing_outlays=False,
                )
                if after.updates:
                    raise CdcFundingOutlayBackfillError(
                        f"Post-update outlay verification failed for FY{fiscal_year} "
                        f"{before.pair.spec.table_name}"
                    )
                if after.non_outlay_fingerprint != before.non_outlay_fingerprint:
                    raise CdcFundingOutlayBackfillError(
                        f"Non-outlay fingerprint changed for FY{fiscal_year} "
                        f"{before.pair.spec.table_name}"
                    )
            report["years"][str(fiscal_year)]["import_run_id"] = _record_provenance(
                connection,
                updated_root,
                fiscal_year,
                plans,
                reconciliations[fiscal_year],
            )
        report["total_rows_updated"] = sum(
            plan.rows_updated
            for plans in plans_by_year.values()
            for plan in plans
        )
        report["total_fields_updated"] = total_fields
        return report


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill CDC funding summary outlays without replacing source rows."
    )
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--original-root", type=Path, required=True)
    parser.add_argument("--updated-root", type=Path, required=True)
    parser.add_argument("--fiscal-years", type=parse_fiscal_years, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace-existing-outlays", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_argument_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    engine = sa.create_engine(args.db_url, pool_pre_ping=True, future=True)
    result = run_backfill(
        engine=engine,
        original_root=args.original_root,
        updated_root=args.updated_root,
        fiscal_years=args.fiscal_years,
        dry_run=args.dry_run,
        replace_existing_outlays=args.replace_existing_outlays,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
