"""Ingest CDC/ATSDR SVI 2022 county + tract estimates.

Usage:
  python -m backend.scripts.ingest_svi_2022 --year 2022
  python -m backend.scripts.ingest_svi_2022 --year 2022 --only-mvp
  python -m backend.scripts.ingest_svi_2022 --year 2022 --db-url "$DATABASE_URL"

Notes:
  - Ingests county data from `data/SVI_2022_US_county.csv`
  - Ingests tract data from `data/SVI_2022_US.csv`
  - Excludes non-tract rows from the tract file (including county/ZCTA-like IDs)
  - Safe to rerun (idempotent ON CONFLICT upserts)
"""

from __future__ import annotations

import argparse
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import create_engine, text

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_YEAR = 2022
DEFAULT_CHUNKSIZE = 5000
BATCH_SIZE = 1500

MVP_MEASURES = [
    "RPL_THEMES",
    "RPL_THEME1",
    "RPL_THEME2",
    "RPL_THEME3",
    "RPL_THEME4",
]
MEASURE_PREFIXES = ("RPL_", "EPL_", "EP_", "F_", "E_")

THEME_SUFFIXES: dict[str, set[str]] = {
    "theme1": {"POV150", "UNEMP", "HBURD", "NOHSDP", "UNINSUR"},
    "theme2": {"AGE65", "AGE17", "DISABL", "SNGPNT", "LIMENG"},
    "theme3": {"MINRTY"},
    "theme4": {"MUNIT", "MOBILE", "CROWD", "NOVEH", "GROUPQ"},
}

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_COUNTY_CSV = PROJECT_ROOT / "data" / "SVI_2022_US_county.csv"
DEFAULT_TRACT_CSV = PROJECT_ROOT / "data" / "SVI_2022_US.csv"


@dataclass
class IngestSummary:
    geography_level: str
    csv_path: Path
    measures_selected: int = 0
    measures_upserted: int = 0
    source_rows: int = 0
    valid_geo_rows: int = 0
    estimate_rows_staged: int = 0
    estimate_rows_upserted: int = 0
    skipped_zcta_or_nontract_rows: int = 0
    skipped_invalid_fips_rows: int = 0
    missing_values_set_null: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest SVI 2022 county + tract estimates.")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR, help="SVI year (default: 2022).")
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL or local places default.",
    )
    parser.add_argument(
        "--county-csv",
        default=str(DEFAULT_COUNTY_CSV),
        help=f"Path to SVI county CSV (default: {DEFAULT_COUNTY_CSV}).",
    )
    parser.add_argument(
        "--tract-csv",
        default=str(DEFAULT_TRACT_CSV),
        help=f"Path to SVI tract CSV (default: {DEFAULT_TRACT_CSV}).",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"CSV chunk size (default: {DEFAULT_CHUNKSIZE}).",
    )
    parser.add_argument(
        "--only-mvp",
        action="store_true",
        help="Only ingest RPL_THEMES and RPL_THEME1-4.",
    )
    return parser.parse_args()


def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(col).strip().lstrip("\ufeff").upper() for col in normalized.columns]
    return normalized


def _to_nullable_float(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .replace({"": None, "nan": None, "None": None, "<NA>": None})
        .str.replace(",", "", regex=False)
    )
    sentinel_mask = cleaned.str.fullmatch(r"-999(?:\.0+)?", na=False)
    cleaned = cleaned.mask(sentinel_mask, None)
    return pd.to_numeric(cleaned, errors="coerce")


def _resolve_fips_column(columns: Iterable[str]) -> str:
    normalized = {str(column).upper(): str(column).upper() for column in columns}
    for candidate in ("FIPS", "GEOID", "GEO_ID"):
        if candidate in normalized:
            return candidate
    raise RuntimeError("CSV is missing required FIPS/GEOID column.")


def _discover_measure_columns(columns: list[str], only_mvp: bool) -> list[str]:
    if only_mvp:
        return [measure for measure in MVP_MEASURES if measure in columns]
    selected = [
        column
        for column in columns
        if any(column.startswith(prefix) for prefix in MEASURE_PREFIXES)
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for column in selected:
        if column in seen:
            continue
        seen.add(column)
        deduped.append(column)
    return deduped


def _assert_schema(df: pd.DataFrame, *, only_mvp: bool) -> tuple[str, list[str]]:
    columns = list(df.columns)
    fips_column = _resolve_fips_column(columns)

    missing_mvp = [measure for measure in MVP_MEASURES if measure not in columns]
    if missing_mvp:
        raise RuntimeError(f"CSV missing required MVP measure columns: {', '.join(missing_mvp)}")

    measure_columns = _discover_measure_columns(columns, only_mvp=only_mvp)
    if not measure_columns:
        raise RuntimeError("No SVI measure columns were detected from the CSV schema.")
    return fips_column, measure_columns


def _value_type_for_measure(measure_id: str) -> str:
    if measure_id.startswith(("RPL_", "EPL_")):
        return "percentile"
    if measure_id.startswith("EP_"):
        return "percentage"
    if measure_id.startswith("F_"):
        return "flag"
    if measure_id.startswith("E_"):
        return "estimate"
    return "adjunct"


def _theme_for_measure(measure_id: str) -> str | None:
    if measure_id in {"RPL_THEMES", "SPL_THEMES", "F_TOTAL"}:
        return "overall"

    theme_match = re.search(r"THEME([1-4])$", measure_id)
    if theme_match:
        return f"theme{theme_match.group(1)}"

    suffix = measure_id.split("_", 1)[1] if "_" in measure_id else measure_id
    for theme, suffixes in THEME_SUFFIXES.items():
        if suffix in suffixes:
            return theme
    return None


def _measure_name(measure_id: str) -> str:
    return measure_id.replace("_", " ")


def _build_measure_rows(
    measure_columns: list[str],
    *,
    geography_level: str,
    year: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for measure_id in measure_columns:
        rows.append(
            {
                "measure_id": measure_id,
                "name": _measure_name(measure_id),
                "description": None,
                "theme": _theme_for_measure(measure_id),
                "value_type": _value_type_for_measure(measure_id),
                "year": year,
                "geography_level": geography_level,
            }
        )
    return rows


def _ensure_tables_exist(connection) -> None:
    for table_name in ("svi_measures", "svi_estimates_county", "svi_estimates_tract"):
        row = (
            connection.execute(text(f"SELECT to_regclass('public.{table_name}') AS exists"))
            .mappings()
            .one()
        )
        if row["exists"] is None:
            raise RuntimeError(f"Table {table_name} does not exist. Run alembic migrations first.")


def _upsert_measures(connection, measure_rows: list[dict[str, object]]) -> int:
    if not measure_rows:
        return 0
    upsert_sql = text(
        """
        INSERT INTO svi_measures (
            measure_id,
            name,
            description,
            theme,
            value_type,
            year,
            geography_level
        ) VALUES (
            :measure_id,
            :name,
            :description,
            :theme,
            :value_type,
            :year,
            :geography_level
        )
        ON CONFLICT (measure_id, year, geography_level)
        DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            theme = EXCLUDED.theme,
            value_type = EXCLUDED.value_type
        """
    )
    total = 0
    for index in range(0, len(measure_rows), BATCH_SIZE):
        batch = measure_rows[index : index + BATCH_SIZE]
        result = connection.execute(upsert_sql, batch)
        total += int(result.rowcount or 0)
    return total


def _prepare_long_chunk(
    chunk: pd.DataFrame,
    *,
    geography_level: str,
    fips_column: str,
    measure_columns: list[str],
    year: int,
    summary: IngestSummary,
) -> pd.DataFrame:
    raw_fips = chunk[fips_column].fillna("").astype(str).str.strip()
    digits = raw_fips.str.replace(r"[^0-9]", "", regex=True)
    raw_len = digits.str.len()

    if geography_level == "county":
        geoid = digits.str.zfill(5)
        valid_mask = geoid.str.fullmatch(r"\d{5}", na=False)
        summary.skipped_invalid_fips_rows += int((~valid_mask).sum())
    else:
        geoid = digits.str.zfill(11)
        zcta_or_nontract_mask = (raw_len <= 5) & (raw_len > 0)
        valid_mask = geoid.str.fullmatch(r"\d{11}", na=False) & (raw_len > 5)
        invalid_mask = (~valid_mask) & (~zcta_or_nontract_mask)

        summary.skipped_zcta_or_nontract_rows += int(zcta_or_nontract_mask.sum())
        summary.skipped_invalid_fips_rows += int(invalid_mask.sum())

    if not valid_mask.any():
        return pd.DataFrame(columns=["geoid", "measure_id", "year", "value"])

    valid_wide = chunk.loc[valid_mask, measure_columns].copy()
    valid_wide.insert(0, "geoid", geoid.loc[valid_mask].values)
    summary.valid_geo_rows += int(len(valid_wide))

    melted = valid_wide.melt(
        id_vars=["geoid"],
        value_vars=measure_columns,
        var_name="measure_id",
        value_name="raw_value",
    )
    melted["year"] = year
    melted["value"] = _to_nullable_float(melted["raw_value"])
    summary.missing_values_set_null += int(melted["value"].isna().sum())
    melted = melted.drop(columns=["raw_value"])
    melted = melted.where(pd.notna(melted), None)
    summary.estimate_rows_staged += int(len(melted))
    return melted[["geoid", "measure_id", "year", "value"]]


def _ingest_geography(
    engine,
    *,
    csv_path: Path,
    year: int,
    chunksize: int,
    only_mvp: bool,
    geography_level: str,
    estimate_table: str,
    staging_table: str,
) -> IngestSummary:
    summary = IngestSummary(geography_level=geography_level, csv_path=csv_path)

    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {staging_table}"))
        connection.execute(
            text(
                f"""
                CREATE TABLE {staging_table} (
                    geoid text NOT NULL,
                    measure_id text NOT NULL,
                    year int NOT NULL,
                    value double precision NULL
                )
                """
            )
        )

    insert_staging_sql = text(
        f"""
        INSERT INTO {staging_table} (
            geoid,
            measure_id,
            year,
            value
        ) VALUES (
            :geoid,
            :measure_id,
            :year,
            :value
        )
        """
    )

    fips_column: str | None = None
    measure_columns: list[str] | None = None

    for chunk_number, raw_chunk in enumerate(pd.read_csv(csv_path, dtype=str, chunksize=chunksize), start=1):
        chunk = _normalize_headers(raw_chunk)
        summary.source_rows += int(len(chunk))

        if fips_column is None or measure_columns is None:
            fips_column, measure_columns = _assert_schema(chunk, only_mvp=only_mvp)
            summary.measures_selected = len(measure_columns)

            measure_rows = _build_measure_rows(
                measure_columns,
                geography_level=geography_level,
                year=year,
            )
            with engine.begin() as connection:
                summary.measures_upserted = _upsert_measures(connection, measure_rows)
        else:
            expected_columns = [fips_column, *measure_columns]
            missing_columns = [column for column in expected_columns if column not in chunk.columns]
            if missing_columns:
                raise RuntimeError(
                    f"CSV schema changed during ingest; missing columns: {', '.join(missing_columns)}"
                )

        long_chunk = _prepare_long_chunk(
            chunk,
            geography_level=geography_level,
            fips_column=fips_column,
            measure_columns=measure_columns,
            year=year,
            summary=summary,
        )
        if long_chunk.empty:
            print(
                f"[{geography_level}] chunk {chunk_number}: raw={len(chunk)} valid_geo=0 staged=0"
            )
            continue

        rows = long_chunk.to_dict(orient="records")
        with engine.begin() as connection:
            for index in range(0, len(rows), BATCH_SIZE):
                connection.execute(insert_staging_sql, rows[index : index + BATCH_SIZE])

        print(
            f"[{geography_level}] chunk {chunk_number}: raw={len(chunk)} "
            f"valid_geo={long_chunk['geoid'].nunique()} staged={len(rows)}"
        )

    if fips_column is None or measure_columns is None:
        raise RuntimeError(f"No rows read from CSV: {csv_path}")

    with engine.begin() as connection:
        result = connection.execute(
            text(
                f"""
                INSERT INTO {estimate_table} (
                    geoid,
                    measure_id,
                    year,
                    value
                )
                SELECT
                    s.geoid,
                    s.measure_id,
                    s.year,
                    s.value
                FROM {staging_table} AS s
                ON CONFLICT (geoid, measure_id, year)
                DO UPDATE SET
                    value = EXCLUDED.value
                """
            )
        )
        summary.estimate_rows_upserted = int(result.rowcount or 0)
        connection.execute(text(f"DROP TABLE IF EXISTS {staging_table}"))

    return summary


def _print_summary(summaries: list[IngestSummary], *, elapsed_seconds: float) -> None:
    print("\nSVI ingestion complete")
    for summary in summaries:
        print(f"  [{summary.geography_level}] csv={summary.csv_path}")
        print(f"    measures_selected={summary.measures_selected}")
        print(f"    measures_inserted_updated={summary.measures_upserted}")
        print(f"    source_rows={summary.source_rows}")
        print(f"    valid_geography_rows={summary.valid_geo_rows}")
        print(f"    estimate_rows_inserted_updated={summary.estimate_rows_upserted}")
        print(f"    skipped_zcta_or_nontract_rows={summary.skipped_zcta_or_nontract_rows}")
        print(f"    skipped_invalid_fips_rows={summary.skipped_invalid_fips_rows}")
        print("    skipped_missing_values_rows=0")
        print(f"    missing_values_set_null={summary.missing_values_set_null}")
    print(f"  elapsed_seconds={elapsed_seconds:.2f}")


def main() -> None:
    args = parse_args()

    year = int(args.year)
    if year <= 0:
        raise RuntimeError("--year must be a positive integer.")

    county_csv = Path(args.county_csv).expanduser().resolve()
    tract_csv = Path(args.tract_csv).expanduser().resolve()
    if not county_csv.exists():
        raise FileNotFoundError(f"County CSV not found: {county_csv}")
    if not tract_csv.exists():
        raise FileNotFoundError(f"Tract CSV not found: {tract_csv}")

    db_url = args.db_url or os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    engine = create_engine(db_url, future=True)

    started = time.perf_counter()
    with engine.begin() as connection:
        _ensure_tables_exist(connection)

    county_summary = _ingest_geography(
        engine,
        csv_path=county_csv,
        year=year,
        chunksize=args.chunksize,
        only_mvp=args.only_mvp,
        geography_level="county",
        estimate_table="svi_estimates_county",
        staging_table="tmp_svi_county_ingest",
    )

    tract_summary = _ingest_geography(
        engine,
        csv_path=tract_csv,
        year=year,
        chunksize=args.chunksize,
        only_mvp=args.only_mvp,
        geography_level="tract",
        estimate_table="svi_estimates_tract",
        staging_table="tmp_svi_tract_ingest",
    )

    elapsed = time.perf_counter() - started
    _print_summary([county_summary, tract_summary], elapsed_seconds=elapsed)


if __name__ == "__main__":
    main()
