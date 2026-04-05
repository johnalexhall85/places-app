from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.budget.models import CdcBudgetSourceRegistryRaw, CdcBudgetTrackerRaw
from app.db_fqtn import budget_table
from app.db_schemas import BUDGET_SCHEMA

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_SHEET_NAME = "BUDGET DATA"
DEFAULT_SOURCE_REGISTRY_SHEET = "SOURCE REGISTRY"
DEFAULT_BATCH_SIZE = 500
HEADER_SCAN_ROWS = 10
MILLIONS_QUANTIZER = Decimal("0.000001")
DOLLARS_QUANTIZER = Decimal("0.01")
COLUMN_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")

BUDGET_TRACKER_COLUMNS = [
    "unique_id",
    "record_id",
    "fiscal_year",
    "agency",
    "sub_agency",
    "program",
    "sub_program",
    "sub_program_2",
    "sub_program_3",
    "budget_source",
    "budget_stage",
    "granularity",
    "amount_millions",
    "funding_type",
    "program_status",
    "is_non_add",
    "notes",
    "source_id",
    "source_page",
    "date_entered",
    "entered_by",
    "verified",
    "crosswalk_note",
]
SOURCE_REGISTRY_COLUMNS = [
    "source_id",
    "document_name",
    "source_type",
    "fiscal_year",
    "agency",
    "release_date",
    "url",
    "granularity_available",
    "notes",
]
BUDGET_TRACKER_TEXT_COLUMNS = {
    "unique_id",
    "agency",
    "sub_agency",
    "program",
    "sub_program",
    "sub_program_2",
    "sub_program_3",
    "budget_source",
    "budget_stage",
    "granularity",
    "funding_type",
    "program_status",
    "is_non_add",
    "notes",
    "source_id",
    "entered_by",
    "verified",
    "crosswalk_note",
}
SOURCE_REGISTRY_TEXT_COLUMNS = {
    "source_id",
    "document_name",
    "source_type",
    "agency",
    "url",
    "granularity_available",
    "notes",
}

TRACKER_TABLE = CdcBudgetTrackerRaw.__table__
SOURCE_REGISTRY_TABLE = CdcBudgetSourceRegistryRaw.__table__
TRACKER_TABLE_FQTN = budget_table("cdc_budget_tracker_raw")
SOURCE_REGISTRY_TABLE_FQTN = budget_table("cdc_budget_source_registry_raw")


@dataclass
class SheetLoad:
    dataframe: pd.DataFrame
    header_row_index: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class IngestResult:
    sheet_name: str
    total_rows_read: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    deactivated: int = 0
    warnings: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Ingest HHS Budget Tracker workbook sheets into schema {BUDGET_SCHEMA}.",
    )
    parser.add_argument("--xlsx", required=True, help="Path to the HHS Budget Tracker workbook.")
    parser.add_argument(
        "--sheet-name",
        default=DEFAULT_SHEET_NAME,
        help=f"Workbook sheet to ingest into {TRACKER_TABLE_FQTN}.",
    )
    parser.add_argument(
        "--source-file-label",
        default=None,
        help="Optional label stored in source_file. Defaults to the workbook basename.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate target raw tables before loading the workbook snapshot.",
    )
    parser.add_argument(
        "--upsert",
        dest="upsert",
        action="store_true",
        default=True,
        help="Use PostgreSQL upsert semantics (default behavior).",
    )
    parser.add_argument(
        "--no-upsert",
        dest="upsert",
        action="store_false",
        help="Disable upsert semantics and require inserts only.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Insert/update batch size (default: {DEFAULT_BATCH_SIZE}).",
    )
    return parser.parse_args()


def _normalize_column_name(value: Any) -> str:
    normalized = COLUMN_NORMALIZE_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return normalized


def _clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text_value = str(value).strip()
    return text_value or None


def _coerce_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    candidate = cleaned.replace(",", "")
    if re.fullmatch(r"[-+]?\d+", candidate):
        return int(candidate)
    if re.fullmatch(r"[-+]?\d+\.0+", candidate):
        return int(candidate.split(".", 1)[0])
    return None


def _coerce_decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, Decimal):
        decimal_value = value
    else:
        cleaned = _clean_text(value)
        if cleaned is None:
            return None
        try:
            decimal_value = Decimal(cleaned.replace(",", ""))
        except InvalidOperation:
            return None
    return decimal_value.quantize(MILLIONS_QUANTIZER, rounding=ROUND_HALF_UP)


def _coerce_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    parsed = pd.to_datetime(cleaned, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _serialize_hash_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _build_row_hash(record: Mapping[str, Any], business_columns: Iterable[str]) -> str:
    payload = {
        column: _serialize_hash_value(record.get(column))
        for column in business_columns
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _find_header_row_index(
    preview: pd.DataFrame,
    *,
    expected_columns: list[str],
    required_columns: set[str],
) -> int | None:
    expected_set = set(expected_columns)
    for row_index in preview.index:
        row_values = {
            _normalize_column_name(value)
            for value in preview.loc[row_index].tolist()
            if _clean_text(value) is not None
        }
        if required_columns.issubset(row_values) and len(expected_set.intersection(row_values)) >= len(required_columns):
            return int(row_index)
    return None


def _load_sheet(
    workbook_path: Path,
    *,
    sheet_name: str,
    expected_columns: list[str],
    required_columns: set[str],
    fail_if_missing: bool,
) -> SheetLoad | None:
    try:
        preview = pd.read_excel(
            workbook_path,
            sheet_name=sheet_name,
            header=None,
            nrows=HEADER_SCAN_ROWS,
            dtype=object,
            engine="openpyxl",
        )
    except ValueError as exc:
        if fail_if_missing:
            raise RuntimeError(f"Worksheet {sheet_name!r} is missing from {workbook_path}.") from exc
        return None

    header_row_index = _find_header_row_index(
        preview,
        expected_columns=expected_columns,
        required_columns=required_columns,
    )
    if header_row_index is None:
        message = f"Could not detect a valid header row in worksheet {sheet_name!r}."
        if fail_if_missing:
            raise RuntimeError(message)
        return None

    dataframe = pd.read_excel(
        workbook_path,
        sheet_name=sheet_name,
        header=header_row_index,
        dtype=object,
        engine="openpyxl",
    )
    dataframe = dataframe.rename(columns=lambda value: _normalize_column_name(value))
    dataframe = dataframe.dropna(how="all").reset_index(drop=True)

    available_columns = set(dataframe.columns)
    missing_required = sorted(required_columns - available_columns)
    if missing_required:
        raise RuntimeError(
            f"Worksheet {sheet_name!r} is missing required columns: {', '.join(missing_required)}."
        )

    warnings: list[str] = []
    missing_optional = [column for column in expected_columns if column not in available_columns and column not in required_columns]
    if missing_optional:
        warnings.append(
            f"Worksheet {sheet_name!r} is missing optional columns: {', '.join(missing_optional)}. They will load as NULL."
        )
        for column in missing_optional:
            dataframe[column] = None

    return SheetLoad(
        dataframe=dataframe[expected_columns].copy(),
        header_row_index=header_row_index,
        warnings=warnings,
    )


def _coerce_budget_tracker_row(raw_row: Mapping[str, Any]) -> dict[str, Any] | None:
    record: dict[str, Any] = {}
    for column in BUDGET_TRACKER_COLUMNS:
        value = raw_row.get(column)
        if column in BUDGET_TRACKER_TEXT_COLUMNS:
            record[column] = _clean_text(value)
        elif column in {"record_id", "fiscal_year", "source_page"}:
            record[column] = _coerce_int(value)
        elif column == "amount_millions":
            record[column] = _coerce_decimal(value)
        elif column == "date_entered":
            record[column] = _coerce_date(value)
        else:
            record[column] = value

    if record["unique_id"] is None:
        return None

    amount_millions = record["amount_millions"]
    record["amount_dollars"] = (
        (amount_millions * Decimal("1000000")).quantize(DOLLARS_QUANTIZER, rounding=ROUND_HALF_UP)
        if amount_millions is not None
        else None
    )
    record["row_hash"] = _build_row_hash(record, BUDGET_TRACKER_COLUMNS)
    return record


def _coerce_source_registry_row(raw_row: Mapping[str, Any]) -> dict[str, Any] | None:
    record: dict[str, Any] = {}
    for column in SOURCE_REGISTRY_COLUMNS:
        value = raw_row.get(column)
        if column in SOURCE_REGISTRY_TEXT_COLUMNS:
            record[column] = _clean_text(value)
        elif column == "fiscal_year":
            record[column] = _coerce_int(value)
        elif column == "release_date":
            record[column] = _coerce_date(value)
        else:
            record[column] = value

    if record["source_id"] is None:
        return None

    record["row_hash"] = _build_row_hash(record, SOURCE_REGISTRY_COLUMNS)
    return record


def _chunked(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(rows), size):
        yield rows[index:index + size]


def _dedupe_rows(
    rows: list[dict[str, Any]],
    *,
    key_column: str,
    warnings: list[str],
    sheet_name: str,
) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for row in rows:
        row_key = str(row[key_column])
        if row_key in deduped:
            duplicates.add(row_key)
        deduped[row_key] = row

    if duplicates:
        sample = ", ".join(sorted(duplicates)[:10])
        warnings.append(
            f"Worksheet {sheet_name!r} contains duplicate {key_column} values. Keeping the last occurrence for {len(duplicates)} key(s): {sample}"
        )

    return list(deduped.values())


def _existing_rows_by_key(
    connection: Connection,
    *,
    table,
    key_column: str,
    source_file: str,
    source_sheet: str,
) -> dict[str, tuple[str, bool | None]]:
    columns = [table.c[key_column], table.c.row_hash]
    if "is_active" in table.c:
        columns.append(table.c.is_active)
    rows = connection.execute(
        select(*columns).where(
            table.c.source_file == source_file,
            table.c.source_sheet == source_sheet,
        )
    )

    existing: dict[str, tuple[str, bool | None]] = {}
    for row in rows:
        key_value = str(row[0])
        is_active = row[2] if len(row) > 2 else None
        existing[key_value] = (row[1], is_active)
    return existing


def _upsert_rows(
    connection: Connection,
    *,
    table,
    rows: list[dict[str, Any]],
    unique_columns: list[str],
    batch_size: int,
) -> None:
    if not rows:
        return

    update_columns = [column for column in rows[0].keys() if column not in unique_columns]
    for batch in _chunked(rows, batch_size):
        insert_stmt = pg_insert(table).values(batch)
        connection.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[table.c[column] for column in unique_columns],
                set_={column: getattr(insert_stmt.excluded, column) for column in update_columns},
            )
        )


def _ensure_table_exists(connection: Connection, fqtn: str) -> None:
    if connection.execute(text("SELECT to_regclass(:table_name)"), {"table_name": fqtn}).scalar_one() is None:
        raise RuntimeError(
            f"Required table {fqtn} is missing. Run `cd backend && ./.venv/bin/alembic upgrade head` first."
        )


def _truncate_table(connection: Connection, fqtn: str) -> None:
    connection.execute(text(f"TRUNCATE TABLE {fqtn} RESTART IDENTITY"))


def _prepare_tracker_rows(
    dataframe: pd.DataFrame,
    *,
    source_file: str,
    source_sheet: str,
    ingest_batch_id: uuid.UUID,
    result: IngestResult,
) -> list[dict[str, Any]]:
    duplicate_mask = dataframe["unique_id"].map(_clean_text).duplicated(keep=False)
    if bool(duplicate_mask.any()):
        duplicate_count = int(duplicate_mask.sum())
        result.warnings.append(
            f"Worksheet {source_sheet!r} contains {duplicate_count} row(s) participating in duplicate unique_id values."
        )

    rows: list[dict[str, Any]] = []
    for row_number, raw_row in enumerate(dataframe.to_dict(orient="records"), start=1):
        coerced = _coerce_budget_tracker_row(raw_row)
        if coerced is None:
            result.failed += 1
            result.warnings.append(
                f"Skipped row {row_number} in worksheet {source_sheet!r} because unique_id is blank after trimming."
            )
            continue

        rows.append(
            {
                "source_file": source_file,
                "source_sheet": source_sheet,
                "ingest_batch_id": ingest_batch_id,
                "unique_id": coerced["unique_id"],
                "record_id": coerced["record_id"],
                "fiscal_year": coerced["fiscal_year"],
                "agency": coerced["agency"],
                "sub_agency": coerced["sub_agency"],
                "program": coerced["program"],
                "sub_program": coerced["sub_program"],
                "sub_program_2": coerced["sub_program_2"],
                "sub_program_3": coerced["sub_program_3"],
                "budget_source": coerced["budget_source"],
                "budget_stage": coerced["budget_stage"],
                "granularity": coerced["granularity"],
                "amount_millions": coerced["amount_millions"],
                "funding_type": coerced["funding_type"],
                "program_status": coerced["program_status"],
                "is_non_add": coerced["is_non_add"],
                "notes": coerced["notes"],
                "source_id": coerced["source_id"],
                "source_page": coerced["source_page"],
                "date_entered": coerced["date_entered"],
                "entered_by": coerced["entered_by"],
                "verified": coerced["verified"],
                "crosswalk_note": coerced["crosswalk_note"],
                "amount_dollars": coerced["amount_dollars"],
                "row_hash": coerced["row_hash"],
                "is_active": True,
            }
        )

    return _dedupe_rows(rows, key_column="unique_id", warnings=result.warnings, sheet_name=source_sheet)


def _prepare_source_registry_rows(
    dataframe: pd.DataFrame,
    *,
    source_file: str,
    source_sheet: str,
    ingest_batch_id: uuid.UUID,
    result: IngestResult,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_number, raw_row in enumerate(dataframe.to_dict(orient="records"), start=1):
        coerced = _coerce_source_registry_row(raw_row)
        if coerced is None:
            result.failed += 1
            result.warnings.append(
                f"Skipped row {row_number} in worksheet {source_sheet!r} because source_id is blank after trimming."
            )
            continue

        rows.append(
            {
                "source_file": source_file,
                "source_sheet": source_sheet,
                "ingest_batch_id": ingest_batch_id,
                "source_id": coerced["source_id"],
                "document_name": coerced["document_name"],
                "source_type": coerced["source_type"],
                "fiscal_year": coerced["fiscal_year"],
                "agency": coerced["agency"],
                "release_date": coerced["release_date"],
                "url": coerced["url"],
                "granularity_available": coerced["granularity_available"],
                "notes": coerced["notes"],
                "row_hash": coerced["row_hash"],
            }
        )

    return _dedupe_rows(rows, key_column="source_id", warnings=result.warnings, sheet_name=source_sheet)


def _ingest_rows(
    connection: Connection,
    *,
    table,
    rows: list[dict[str, Any]],
    key_column: str,
    unique_columns: list[str],
    source_file: str,
    source_sheet: str,
    batch_size: int,
    result: IngestResult,
    sync_is_active: bool,
    ingest_batch_id: uuid.UUID,
    upsert: bool,
) -> None:
    existing = _existing_rows_by_key(
        connection,
        table=table,
        key_column=key_column,
        source_file=source_file,
        source_sheet=source_sheet,
    )

    rows_to_write: list[dict[str, Any]] = []
    for row in rows:
        row_key = str(row[key_column])
        existing_row = existing.get(row_key)
        if existing_row is None:
            result.inserted += 1
            rows_to_write.append(row)
            continue

        existing_hash, existing_is_active = existing_row
        if existing_hash != row["row_hash"] or (sync_is_active and existing_is_active is not True):
            result.updated += 1
            rows_to_write.append(row)
        else:
            result.skipped += 1

    if upsert:
        _upsert_rows(
            connection,
            table=table,
            rows=rows_to_write,
            unique_columns=unique_columns,
            batch_size=batch_size,
        )
    elif rows_to_write:
        for batch in _chunked(rows_to_write, batch_size):
            connection.execute(table.insert(), batch)

    if sync_is_active and rows:
        active_keys = [row[key_column] for row in rows]
        deactivate_stmt = (
            table.update()
            .where(table.c.source_file == source_file)
            .where(table.c.source_sheet == source_sheet)
            .where(~table.c[key_column].in_(active_keys))
            .where(table.c.is_active.is_(True))
            .values(is_active=False, ingest_batch_id=ingest_batch_id, ingested_at=func.now())
        )
        result.deactivated = connection.execute(deactivate_stmt).rowcount or 0


def _print_result(result: IngestResult) -> None:
    print(f"{result.sheet_name}:")
    print(f"  total rows read: {result.total_rows_read}")
    print(f"  inserted: {result.inserted}")
    print(f"  updated: {result.updated}")
    print(f"  skipped/unchanged: {result.skipped}")
    print(f"  failed: {result.failed}")
    if result.deactivated:
        print(f"  deactivated: {result.deactivated}")
    for warning in result.warnings:
        print(f"  warning: {warning}")


def ingest_budget_tracker(
    *,
    connection: Connection,
    workbook_path: Path,
    sheet_name: str,
    source_file: str,
    batch_size: int,
    truncate: bool,
    upsert: bool,
) -> IngestResult:
    _ensure_table_exists(connection, TRACKER_TABLE_FQTN)
    if truncate:
        _truncate_table(connection, TRACKER_TABLE_FQTN)

    sheet = _load_sheet(
        workbook_path,
        sheet_name=sheet_name,
        expected_columns=BUDGET_TRACKER_COLUMNS,
        required_columns={"unique_id"},
        fail_if_missing=True,
    )
    assert sheet is not None

    result = IngestResult(sheet_name=sheet_name, total_rows_read=len(sheet.dataframe), warnings=list(sheet.warnings))
    ingest_batch_id = uuid.uuid4()
    rows = _prepare_tracker_rows(
        sheet.dataframe,
        source_file=source_file,
        source_sheet=sheet_name,
        ingest_batch_id=ingest_batch_id,
        result=result,
    )
    _ingest_rows(
        connection,
        table=TRACKER_TABLE,
        rows=rows,
        key_column="unique_id",
        unique_columns=["source_file", "source_sheet", "unique_id"],
        source_file=source_file,
        source_sheet=sheet_name,
        batch_size=batch_size,
        result=result,
        sync_is_active=True,
        ingest_batch_id=ingest_batch_id,
        upsert=upsert,
    )
    return result


def ingest_source_registry(
    *,
    connection: Connection,
    workbook_path: Path,
    source_file: str,
    batch_size: int,
    truncate: bool,
    upsert: bool,
) -> IngestResult | None:
    _ensure_table_exists(connection, SOURCE_REGISTRY_TABLE_FQTN)
    sheet = _load_sheet(
        workbook_path,
        sheet_name=DEFAULT_SOURCE_REGISTRY_SHEET,
        expected_columns=SOURCE_REGISTRY_COLUMNS,
        required_columns={"source_id"},
        fail_if_missing=False,
    )
    if sheet is None:
        return None

    if truncate:
        _truncate_table(connection, SOURCE_REGISTRY_TABLE_FQTN)

    result = IngestResult(
        sheet_name=DEFAULT_SOURCE_REGISTRY_SHEET,
        total_rows_read=len(sheet.dataframe),
        warnings=list(sheet.warnings),
    )
    ingest_batch_id = uuid.uuid4()
    rows = _prepare_source_registry_rows(
        sheet.dataframe,
        source_file=source_file,
        source_sheet=DEFAULT_SOURCE_REGISTRY_SHEET,
        ingest_batch_id=ingest_batch_id,
        result=result,
    )
    _ingest_rows(
        connection,
        table=SOURCE_REGISTRY_TABLE,
        rows=rows,
        key_column="source_id",
        unique_columns=["source_file", "source_sheet", "source_id"],
        source_file=source_file,
        source_sheet=DEFAULT_SOURCE_REGISTRY_SHEET,
        batch_size=batch_size,
        result=result,
        sync_is_active=False,
        ingest_batch_id=ingest_batch_id,
        upsert=upsert,
    )
    return result


def main() -> None:
    args = parse_args()
    workbook_path = Path(args.xlsx).expanduser().resolve()
    if not workbook_path.exists():
        raise SystemExit(f"Workbook not found: {workbook_path}")

    source_file = args.source_file_label or workbook_path.name
    engine = create_engine(args.db_url, pool_pre_ping=True)

    print(f"Workbook: {workbook_path}")
    print(f"Source file label: {source_file}")
    print(f"Primary sheet: {args.sheet_name}")

    with engine.begin() as connection:
        tracker_result = ingest_budget_tracker(
            connection=connection,
            workbook_path=workbook_path,
            sheet_name=args.sheet_name,
            source_file=source_file,
            batch_size=args.batch_size,
            truncate=args.truncate,
            upsert=args.upsert,
        )
    _print_result(tracker_result)

    source_registry_result: IngestResult | None = None
    try:
        with engine.begin() as connection:
            source_registry_result = ingest_source_registry(
                connection=connection,
                workbook_path=workbook_path,
                source_file=source_file,
                batch_size=args.batch_size,
                truncate=args.truncate,
                upsert=args.upsert,
            )
    except Exception as exc:
        print(f"SOURCE REGISTRY: warning: skipped optional ingest because {exc}")

    if source_registry_result is not None:
        _print_result(source_registry_result)
