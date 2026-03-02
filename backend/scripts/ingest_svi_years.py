#!/usr/bin/env python3
"""Ingest CDC/ATSDR SVI county + tract estimates across multiple years.

Usage examples:
  python backend/scripts/ingest_svi_years.py --years 2018 2020 --level both
  python backend/scripts/ingest_svi_years.py --years 2018 2020 2022 --level tract
  python backend/scripts/ingest_svi_years.py --years 2018 2020 --level county --data-dir /data
  python backend/scripts/ingest_svi_years.py --years 2018 2020 --db-url "$DATABASE_URL"
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

from _schema_imports import svi_table

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_CHUNKSIZE = 5000
DEFAULT_YEARS = [2018, 2020]
SUPPORTED_YEARS = {2018, 2020, 2022}
BATCH_SIZE = 1500

MEASURE_PREFIXES = ("RPL_", "EPL_", "EP_", "F_", "E_")

THEME_SUFFIXES: dict[str, set[str]] = {
    "theme1": {"POV150", "UNEMP", "HBURD", "NOHSDP", "UNINSUR", "POV", "PCI"},
    "theme2": {"AGE65", "AGE17", "DISABL", "SNGPNT", "LIMENG"},
    "theme3": {"MINRTY"},
    "theme4": {"MUNIT", "MOBILE", "CROWD", "NOVEH", "GROUPQ"},
}

# 2018 uses POV naming where 2020+ uses POV150. Alias to canonical IDs so
# frontend indicator IDs stay stable across years.
YEAR_COLUMN_ALIASES: dict[int, dict[str, str]] = {
    2018: {
        "E_POV": "E_POV150",
        "M_POV": "M_POV150",
        "EP_POV": "EP_POV150",
        "MP_POV": "MP_POV150",
        "EPL_POV": "EPL_POV150",
        "F_POV": "F_POV150",
    },
}

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


@dataclass
class IngestSummary:
    year: int
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
    parser = argparse.ArgumentParser(description="Ingest SVI county/tract data for multiple years.")
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=DEFAULT_YEARS,
        help="SVI years to ingest (default: 2018 2020).",
    )
    parser.add_argument(
        "--level",
        choices=("county", "tract", "both"),
        default="both",
        help="Geography level to ingest (default: both).",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Directory containing SVI CSV files (default: {DEFAULT_DATA_DIR}).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL or local places default.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"CSV chunk size (default: {DEFAULT_CHUNKSIZE}).",
    )
    return parser.parse_args()


def _normalize_headers(df: pd.DataFrame, *, year: int) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(col).strip().lstrip("\ufeff").upper() for col in normalized.columns]

    aliases = YEAR_COLUMN_ALIASES.get(year, {})
    if not aliases:
        return normalized

    for source_col, target_col in aliases.items():
        if source_col not in normalized.columns:
            continue
        if target_col in normalized.columns:
            source_values = normalized[source_col].astype(str).str.strip()
            target_values = normalized[target_col].astype(str).str.strip()
            use_source = target_values.eq("") | target_values.str.lower().eq("nan")
            normalized.loc[use_source, target_col] = normalized.loc[use_source, source_col]
            normalized = normalized.drop(columns=[source_col])
            continue
        normalized = normalized.rename(columns={source_col: target_col})
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


def _discover_measure_columns(columns: list[str]) -> list[str]:
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


def _assert_schema(df: pd.DataFrame) -> tuple[str, list[str]]:
    columns = list(df.columns)
    fips_column = _resolve_fips_column(columns)

    missing_required = [key for key in ("RPL_THEMES", "RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4") if key not in columns]
    if missing_required:
        raise RuntimeError(
            "CSV missing required SVI theme rank columns: "
            + ", ".join(missing_required)
        )

    measure_columns = _discover_measure_columns(columns)
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
            connection.execute(
                text("SELECT to_regclass(:table_name) AS exists"),
                {"table_name": svi_table(table_name)},
            )
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
    melted["year"] = int(year)
    melted["value"] = _to_nullable_float(melted["raw_value"])
    summary.missing_values_set_null += int(melted["value"].isna().sum())
    melted = melted.drop(columns=["raw_value"])
    melted = melted.where(pd.notna(melted), None)
    summary.estimate_rows_staged += int(len(melted))
    return melted[["geoid", "measure_id", "year", "value"]]


def _resolve_csv_path(*, data_dir: Path, year: int, geography_level: str) -> Path:
    if geography_level == "county":
        file_name = f"SVI_{year}_US_county.csv"
    else:
        file_name = f"SVI_{year}_US.csv"
    path = data_dir / file_name
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV for year={year}, level={geography_level}: {path}")
    return path


def _ingest_geography(
    engine,
    *,
    csv_path: Path,
    year: int,
    chunksize: int,
    geography_level: str,
    estimate_table: str,
    staging_table: str,
) -> IngestSummary:
    summary = IngestSummary(year=year, geography_level=geography_level, csv_path=csv_path)

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
        chunk = _normalize_headers(raw_chunk, year=year)
        summary.source_rows += int(len(chunk))

        if fips_column is None or measure_columns is None:
            fips_column, measure_columns = _assert_schema(chunk)
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
                f"[{year} {geography_level}] chunk {chunk_number}: raw={len(chunk)} valid_geo=0 staged=0"
            )
            continue

        rows = long_chunk.to_dict(orient="records")
        with engine.begin() as connection:
            for index in range(0, len(rows), BATCH_SIZE):
                connection.execute(insert_staging_sql, rows[index : index + BATCH_SIZE])

        print(
            f"[{year} {geography_level}] chunk {chunk_number}: raw={len(chunk)} "
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


def _validate_year_summary(connection, *, year: int, geography_level: str, table_name: str) -> None:
    range_row = connection.execute(
        text(
            f"""
            SELECT
                MIN(value) FILTER (WHERE value IS NOT NULL) AS min_value,
                MAX(value) FILTER (WHERE value IS NOT NULL) AS max_value,
                COUNT(*) FILTER (WHERE year IS NULL) AS null_year_count
            FROM {table_name}
            WHERE year = :year
              AND measure_id = 'RPL_THEMES'
            """
        ),
        {"year": year},
    ).mappings().one()

    if geography_level == "county":
        sample_row = connection.execute(
            text(
                f"""
                SELECT geoid, value
                FROM {table_name}
                WHERE year = :year
                  AND measure_id = 'RPL_THEMES'
                  AND geoid = '01117'
                LIMIT 1
                """
            ),
            {"year": year},
        ).mappings().one_or_none()
    else:
        sample_row = connection.execute(
            text(
                f"""
                SELECT geoid, value
                FROM {table_name}
                WHERE year = :year
                  AND measure_id = 'RPL_THEMES'
                  AND geoid LIKE '01117%'
                ORDER BY geoid
                LIMIT 1
                """
            ),
            {"year": year},
        ).mappings().one_or_none()

    sample_geoid = sample_row["geoid"] if sample_row else None
    sample_value = sample_row["value"] if sample_row else None

    print(
        f"[validate {year} {geography_level}] "
        f"RPL_THEMES range=({range_row['min_value']}, {range_row['max_value']}), "
        f"null_year_count={range_row['null_year_count']}, "
        f"sample_geoid={sample_geoid}, sample_value={sample_value}"
    )


def _print_summary(summaries: list[IngestSummary], *, elapsed_seconds: float) -> None:
    print("\nSVI multi-year ingestion complete")
    for summary in summaries:
        print(f"  [{summary.year} {summary.geography_level}] csv={summary.csv_path}")
        print(f"    measures_selected={summary.measures_selected}")
        print(f"    measures_inserted_updated={summary.measures_upserted}")
        print(f"    source_rows={summary.source_rows}")
        print(f"    valid_geography_rows={summary.valid_geo_rows}")
        print(f"    estimate_rows_staged={summary.estimate_rows_staged}")
        print(f"    estimate_rows_inserted_updated={summary.estimate_rows_upserted}")
        print(f"    skipped_zcta_or_nontract_rows={summary.skipped_zcta_or_nontract_rows}")
        print(f"    skipped_invalid_fips_rows={summary.skipped_invalid_fips_rows}")
        print(f"    missing_values_set_null={summary.missing_values_set_null}")
    print(f"  elapsed_seconds={elapsed_seconds:.2f}")


def main() -> None:
    args = parse_args()

    requested_years = [int(year) for year in args.years]
    if not requested_years:
        raise RuntimeError("At least one year must be supplied via --years.")
    unsupported = sorted({year for year in requested_years if year not in SUPPORTED_YEARS})
    if unsupported:
        raise RuntimeError(
            f"Unsupported year(s): {unsupported}. Supported years: {sorted(SUPPORTED_YEARS)}"
        )

    data_dir = Path(args.data_dir).expanduser().resolve()
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    geography_levels = ["county", "tract"] if args.level == "both" else [args.level]
    db_url = args.db_url or os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    engine = create_engine(db_url, future=True)

    started = time.perf_counter()
    with engine.begin() as connection:
        _ensure_tables_exist(connection)

    summaries: list[IngestSummary] = []
    for year in requested_years:
        for geography_level in geography_levels:
            csv_path = _resolve_csv_path(data_dir=data_dir, year=year, geography_level=geography_level)
            estimate_table = (
                "svi_estimates_county" if geography_level == "county" else "svi_estimates_tract"
            )
            staging_table = f"tmp_svi_{geography_level}_{year}_ingest"

            summary = _ingest_geography(
                engine,
                csv_path=csv_path,
                year=year,
                chunksize=int(args.chunksize),
                geography_level=geography_level,
                estimate_table=estimate_table,
                staging_table=staging_table,
            )
            summaries.append(summary)

            with engine.begin() as connection:
                _validate_year_summary(
                    connection,
                    year=year,
                    geography_level=geography_level,
                    table_name=estimate_table,
                )

    elapsed = time.perf_counter() - started
    _print_summary(summaries, elapsed_seconds=elapsed)


if __name__ == "__main__":
    main()
