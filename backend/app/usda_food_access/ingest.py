from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.db_fqtn import usda_food_access_table
from app.db_schemas import USDA_FOOD_ACCESS_SCHEMA

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_CHUNKSIZE = 2500
DEFAULT_DATASET_KEY = "food_access_atlas"
DEFAULT_VINTAGE = "2019"
DEFAULT_SOURCE_NAME = "USDA Food Access Research Atlas"
DEFAULT_SOURCE_URL = "https://www.ers.usda.gov/data-products/food-access-research-atlas/"

FOOD_ACCESS_FILENAME = "Food Access Research Atlas.csv"
VARIABLE_LOOKUP_FILENAME = "VariableLookup.csv"
README_FILENAME = "ReadMe.csv"

NULL_TOKENS = {"", "na", "n/a", "null", "none", "nan", "<na>"}

CURATED_FIELD_SPECS: dict[str, dict[str, Any]] = {
    "LowIncomeTracts": {
        "column": "low_income_tracts",
        "kind": "int",
        "aliases": ["LowIncomeTracts"],
    },
    "PovertyRate": {
        "column": "poverty_rate",
        "kind": "float",
        "aliases": ["PovertyRate"],
    },
    "MedianFamilyIncome": {
        "column": "median_family_income",
        "kind": "float",
        "aliases": ["MedianFamilyIncome"],
    },
    "LA1and10": {
        "column": "la1and10",
        "kind": "float",
        "aliases": ["LA1and10"],
    },
    "LAhalfand10": {
        "column": "lahalfand10",
        "kind": "float",
        "aliases": ["LAhalfand10", "LAHalfAnd10", "LA05and10"],
    },
    "LA1and20": {
        "column": "la1and20",
        "kind": "float",
        "aliases": ["LA1and20"],
    },
    "LILATracts_1And10": {
        "column": "lilatracts_1and10",
        "kind": "int",
        "aliases": ["LILATracts_1And10"],
    },
    "LILATracts_halfAnd10": {
        "column": "lilatracts_halfand10",
        "kind": "int",
        "aliases": ["LILATracts_halfAnd10", "LILATracts_HalfAnd10"],
    },
    "LILATracts_1And20": {
        "column": "lilatracts_1and20",
        "kind": "int",
        "aliases": ["LILATracts_1And20"],
    },
    "LILATracts_Vehicle": {
        "column": "lilatracts_vehicle",
        "kind": "int",
        "aliases": ["LILATracts_Vehicle"],
    },
    "LAPOP1_10": {
        "column": "lapop1_10",
        "kind": "float",
        "aliases": ["LAPOP1_10"],
    },
    "LAPOP05_10": {
        "column": "lapop05_10",
        "kind": "float",
        "aliases": ["LAPOP05_10", "LAPOPHalf_10", "LAPOPHALF_10"],
    },
    "LAPOP1_20": {
        "column": "lapop1_20",
        "kind": "float",
        "aliases": ["LAPOP1_20"],
    },
    "LALOWI1_10": {
        "column": "lalowi1_10",
        "kind": "float",
        "aliases": ["LALOWI1_10"],
    },
    "LALOWI05_10": {
        "column": "lalowi05_10",
        "kind": "float",
        "aliases": ["LALOWI05_10", "LALOWIHalf_10", "LALOWIHALF_10"],
    },
    "LALOWI1_20": {
        "column": "lalowi1_20",
        "kind": "float",
        "aliases": ["LALOWI1_20"],
    },
}

TRACT_ATLAS_TABLE = usda_food_access_table("tract_atlas")
VARIABLE_LOOKUP_TABLE = usda_food_access_table("variable_lookup")
DATASET_META_TABLE = usda_food_access_table("dataset_meta")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            f"Ingest USDA Food Access Research Atlas into schema {USDA_FOOD_ACCESS_SCHEMA}."
        )
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL env var or local default).",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory containing USDA Food Access files.",
    )
    parser.add_argument(
        "--food-access-path",
        default=None,
        help=f"Optional explicit path to {FOOD_ACCESS_FILENAME}.",
    )
    parser.add_argument(
        "--variable-lookup-path",
        default=None,
        help=f"Optional explicit path to {VARIABLE_LOOKUP_FILENAME}.",
    )
    parser.add_argument(
        "--readme-path",
        default=None,
        help=f"Optional explicit path to {README_FILENAME}.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"Upsert batch size (default: {DEFAULT_CHUNKSIZE}).",
    )
    return parser.parse_args()


def _normalize_lookup_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _clean_cell(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if cleaned.lower() in NULL_TOKENS:
        return None
    return cleaned


def _clean_row_dict(row: dict[str, Any]) -> dict[str, str | None]:
    cleaned: dict[str, str | None] = {}
    for key, value in row.items():
        if key is None:
            continue
        cleaned[str(key)] = _clean_cell(value)
    return cleaned


def _to_nullable_int(value: Any) -> int | None:
    cleaned = _clean_cell(value)
    if cleaned is None:
        return None
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _to_nullable_float(value: Any) -> float | None:
    cleaned = _clean_cell(value)
    if cleaned is None:
        return None
    cleaned = cleaned.replace(",", "")
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _normalize_geoid(value: Any) -> str | None:
    cleaned = _clean_cell(value)
    if cleaned is None:
        return None

    if re.fullmatch(r"\d+", cleaned):
        digits = cleaned
    else:
        digits = None
        try:
            parsed = Decimal(cleaned)
            if parsed.is_finite() and parsed == parsed.to_integral_value():
                digits = str(int(parsed))
        except InvalidOperation:
            digits = None
        if digits is None:
            digits = re.sub(r"[^0-9]", "", cleaned)

    if not digits or len(digits) > 11:
        return None

    normalized = digits.zfill(11)
    if not re.fullmatch(r"\d{11}", normalized):
        return None
    return normalized


def _resolve_data_dir(explicit_data_dir: str | None) -> Path:
    if explicit_data_dir:
        return Path(explicit_data_dir).expanduser().resolve()

    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        repo_root / "data",
        repo_root / "backend" / "data",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_csv_path(*, explicit: str | None, data_dir: Path, filename: str) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (data_dir / filename).resolve()


def _resolve_lookup_columns(fieldnames: list[str] | None) -> tuple[str, str | None, str | None]:
    if not fieldnames:
        raise RuntimeError("VariableLookup CSV has no header row.")

    by_token = {_normalize_lookup_token(field): field for field in fieldnames if field}

    def pick(*tokens: str) -> str | None:
        for token in tokens:
            column = by_token.get(token)
            if column:
                return column
        return None

    field_column = pick("field", "variable", "variablename", "column", "columnname")
    if field_column is None:
        raise RuntimeError(
            "VariableLookup CSV must include a field/variable column. "
            f"Found columns: {fieldnames}"
        )

    long_name_column = pick("longname", "longfieldname", "label", "title", "name")
    description_column = pick(
        "description",
        "definition",
        "notes",
        "note",
        "longdescription",
    )
    return (field_column, long_name_column, description_column)


def _read_variable_lookup_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Variable lookup CSV not found: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        field_column, long_name_column, description_column = _resolve_lookup_columns(
            reader.fieldnames
        )

        for row in reader:
            field_value = _clean_cell(row.get(field_column))
            if not field_value:
                continue
            long_name_value = _clean_cell(row.get(long_name_column)) if long_name_column else None
            description_value = (
                _clean_cell(row.get(description_column)) if description_column else None
            )
            rows.append(
                {
                    "field": field_value,
                    "long_name": long_name_value,
                    "description": description_value,
                }
            )

    # keep the last row on duplicate field keys for deterministic upserts
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped[str(row["field"]) ] = row
    return list(deduped.values())


def _first_present(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in row and _clean_cell(row.get(key)) is not None:
            return row.get(key)
    return None


def _build_tract_upsert_row(cleaned_row: dict[str, Any], geoid: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "geoid": geoid,
        "state": _clean_cell(_first_present(cleaned_row, ["State", "STATE", "state"])),
        "county": _clean_cell(_first_present(cleaned_row, ["County", "COUNTY", "county"])),
        "urban": _to_nullable_int(_first_present(cleaned_row, ["Urban", "URBAN", "urban"])),
        "pop2010": _to_nullable_int(
            _first_present(cleaned_row, ["Pop2010", "POP2010", "pop2010"])
        ),
        "raw_json": json.dumps(cleaned_row, separators=(",", ":"), ensure_ascii=True),
    }

    for spec in CURATED_FIELD_SPECS.values():
        source_value = _first_present(cleaned_row, spec["aliases"])
        if spec["kind"] == "int":
            payload[spec["column"]] = _to_nullable_int(source_value)
        else:
            payload[spec["column"]] = _to_nullable_float(source_value)

    return payload


def _read_readme_notes(path: Path) -> str | None:
    if not path.exists():
        return None

    lines: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            line = " ".join([str(item).strip() for item in row if str(item).strip()])
            if not line:
                continue
            lines.append(line)
            if len(lines) >= 6:
                break

    if not lines:
        return None
    return " | ".join(lines)


def _ensure_target_tables(connection) -> None:
    for table_name in ("tract_atlas", "variable_lookup", "dataset_meta"):
        exists = connection.execute(
            text("SELECT to_regclass(:table_name) AS exists"),
            {"table_name": usda_food_access_table(table_name)},
        ).scalar()
        if exists is None:
            raise RuntimeError(
                f"Missing table {usda_food_access_table(table_name)}. "
                "Run alembic upgrade head before ingestion."
            )


def _upsert_variable_lookup_rows(connection, rows: list[dict[str, Any]], batch_size: int) -> int:
    if not rows:
        return 0

    statement = text(
        f"""
        INSERT INTO {VARIABLE_LOOKUP_TABLE} (
            field,
            long_name,
            description
        ) VALUES (
            :field,
            :long_name,
            :description
        )
        ON CONFLICT (field)
        DO UPDATE SET
            long_name = EXCLUDED.long_name,
            description = EXCLUDED.description
        """
    )

    total = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        result = connection.execute(statement, batch)
        total += int(result.rowcount or 0)
    return total


def _upsert_tract_rows(connection, rows: list[dict[str, Any]], batch_size: int) -> int:
    if not rows:
        return 0

    statement = text(
        f"""
        INSERT INTO {TRACT_ATLAS_TABLE} (
            geoid,
            state,
            county,
            urban,
            pop2010,
            low_income_tracts,
            poverty_rate,
            median_family_income,
            la1and10,
            lahalfand10,
            la1and20,
            lilatracts_1and10,
            lilatracts_halfand10,
            lilatracts_1and20,
            lilatracts_vehicle,
            lapop1_10,
            lapop05_10,
            lapop1_20,
            lalowi1_10,
            lalowi05_10,
            lalowi1_20,
            raw,
            updated_at
        ) VALUES (
            :geoid,
            :state,
            :county,
            :urban,
            :pop2010,
            :low_income_tracts,
            :poverty_rate,
            :median_family_income,
            :la1and10,
            :lahalfand10,
            :la1and20,
            :lilatracts_1and10,
            :lilatracts_halfand10,
            :lilatracts_1and20,
            :lilatracts_vehicle,
            :lapop1_10,
            :lapop05_10,
            :lapop1_20,
            :lalowi1_10,
            :lalowi05_10,
            :lalowi1_20,
            (:raw_json)::jsonb,
            now()
        )
        ON CONFLICT (geoid)
        DO UPDATE SET
            state = EXCLUDED.state,
            county = EXCLUDED.county,
            urban = EXCLUDED.urban,
            pop2010 = EXCLUDED.pop2010,
            low_income_tracts = EXCLUDED.low_income_tracts,
            poverty_rate = EXCLUDED.poverty_rate,
            median_family_income = EXCLUDED.median_family_income,
            la1and10 = EXCLUDED.la1and10,
            lahalfand10 = EXCLUDED.lahalfand10,
            la1and20 = EXCLUDED.la1and20,
            lilatracts_1and10 = EXCLUDED.lilatracts_1and10,
            lilatracts_halfand10 = EXCLUDED.lilatracts_halfand10,
            lilatracts_1and20 = EXCLUDED.lilatracts_1and20,
            lilatracts_vehicle = EXCLUDED.lilatracts_vehicle,
            lapop1_10 = EXCLUDED.lapop1_10,
            lapop05_10 = EXCLUDED.lapop05_10,
            lapop1_20 = EXCLUDED.lapop1_20,
            lalowi1_10 = EXCLUDED.lalowi1_10,
            lalowi05_10 = EXCLUDED.lalowi05_10,
            lalowi1_20 = EXCLUDED.lalowi1_20,
            raw = EXCLUDED.raw,
            updated_at = now()
        """
    )

    total = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        result = connection.execute(statement, batch)
        total += int(result.rowcount or 0)
    return total


def _upsert_dataset_meta(
    connection,
    *,
    row_count: int,
    notes: str | None,
    source_url: str,
) -> None:
    statement = text(
        f"""
        INSERT INTO {DATASET_META_TABLE} (
            dataset_key,
            source_name,
            source_url,
            notes,
            vintage,
            ingested_at,
            row_count
        ) VALUES (
            :dataset_key,
            :source_name,
            :source_url,
            :notes,
            :vintage,
            :ingested_at,
            :row_count
        )
        ON CONFLICT (dataset_key)
        DO UPDATE SET
            source_name = EXCLUDED.source_name,
            source_url = EXCLUDED.source_url,
            notes = EXCLUDED.notes,
            vintage = EXCLUDED.vintage,
            ingested_at = EXCLUDED.ingested_at,
            row_count = EXCLUDED.row_count
        """
    )
    connection.execute(
        statement,
        {
            "dataset_key": DEFAULT_DATASET_KEY,
            "source_name": DEFAULT_SOURCE_NAME,
            "source_url": source_url,
            "notes": notes,
            "vintage": DEFAULT_VINTAGE,
            "ingested_at": datetime.utcnow(),
            "row_count": int(row_count),
        },
    )


def ingest(
    *,
    db_url: str,
    food_access_path: Path,
    variable_lookup_path: Path,
    readme_path: Path,
    chunksize: int,
) -> None:
    if not food_access_path.exists():
        raise FileNotFoundError(f"Food access CSV not found: {food_access_path}")

    engine = create_engine(db_url, future=True)
    started = time.perf_counter()

    with engine.begin() as connection:
        _ensure_target_tables(connection)

    lookup_rows = _read_variable_lookup_rows(variable_lookup_path)
    with engine.begin() as connection:
        lookup_upserts = _upsert_variable_lookup_rows(connection, lookup_rows, chunksize)

    staged_rows = 0
    source_rows = 0
    skipped_rows = 0
    buffered_rows: list[dict[str, Any]] = []

    with food_access_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "CensusTract" not in reader.fieldnames:
            raise RuntimeError(
                f"{food_access_path.name} must include the CensusTract column. "
                f"Found columns: {reader.fieldnames}"
            )

        for raw_row in reader:
            source_rows += 1
            cleaned = _clean_row_dict(raw_row)
            geoid = _normalize_geoid(cleaned.get("CensusTract"))
            if geoid is None:
                skipped_rows += 1
                continue

            buffered_rows.append(_build_tract_upsert_row(cleaned, geoid))
            if len(buffered_rows) >= chunksize:
                with engine.begin() as connection:
                    staged_rows += _upsert_tract_rows(connection, buffered_rows, chunksize)
                buffered_rows = []

    if buffered_rows:
        with engine.begin() as connection:
            staged_rows += _upsert_tract_rows(connection, buffered_rows, chunksize)

    readme_notes = _read_readme_notes(readme_path)
    with engine.begin() as connection:
        _upsert_dataset_meta(
            connection,
            row_count=source_rows - skipped_rows,
            notes=readme_notes,
            source_url=DEFAULT_SOURCE_URL,
        )

    elapsed = time.perf_counter() - started
    print(
        "USDA Food Access ingest complete:",
        json.dumps(
            {
                "food_access_path": str(food_access_path),
                "variable_lookup_path": str(variable_lookup_path),
                "readme_path": str(readme_path),
                "source_rows": source_rows,
                "skipped_rows": skipped_rows,
                "lookup_rows": len(lookup_rows),
                "lookup_upserts": lookup_upserts,
                "tract_upserts": staged_rows,
                "row_count_meta": source_rows - skipped_rows,
                "seconds": round(elapsed, 2),
            },
            indent=2,
        ),
    )


def main() -> None:
    args = parse_args()
    if args.chunksize < 1:
        raise SystemExit("--chunksize must be >= 1")

    data_dir = _resolve_data_dir(args.data_dir)
    food_access_path = _resolve_csv_path(
        explicit=args.food_access_path,
        data_dir=data_dir,
        filename=FOOD_ACCESS_FILENAME,
    )
    variable_lookup_path = _resolve_csv_path(
        explicit=args.variable_lookup_path,
        data_dir=data_dir,
        filename=VARIABLE_LOOKUP_FILENAME,
    )
    readme_path = _resolve_csv_path(
        explicit=args.readme_path,
        data_dir=data_dir,
        filename=README_FILENAME,
    )

    ingest(
        db_url=args.db_url,
        food_access_path=food_access_path,
        variable_lookup_path=variable_lookup_path,
        readme_path=readme_path,
        chunksize=int(args.chunksize),
    )


if __name__ == "__main__":
    main()
