from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ResourceClosedError

from app.db_fqtn import cms_table
from app.db_schemas import CMS_SCHEMA

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_CHUNKSIZE = 1000
BATCH_SIZE = 2000

REQUIRED_DIM_COLUMNS = (
    "YEAR",
    "BENE_GEO_LVL",
    "BENE_GEO_DESC",
    "BENE_GEO_CD",
    "BENE_AGE_LVL",
)

SUPPRESSION_TOKENS = {"*", ".", "NA", "N/A", "SUPP", "SUPPRESSED"}
NULL_TOKENS = {"", "NULL", "NONE", "NAN"}

GEO_DIM_TABLE = cms_table("geo_dim")
GV_MEASURE_DIM_TABLE = cms_table("gv_measure_dim")
GV_FACT_TABLE = cms_table("gv_fact")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            f"Ingest CMS Geographic Variation PUF into {CMS_SCHEMA} schema tables."
        )
    )
    parser.add_argument("--path", required=True, help="Path to CMS GV CSV file.")
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL env var or local default).",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"CSV chunk size (default: {DEFAULT_CHUNKSIZE}).",
    )
    return parser.parse_args()


def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(col).strip().lstrip("\ufeff").upper() for col in normalized.columns]
    return normalized


def _clean_text_series(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .replace({"": None, "nan": None, "None": None, "<NA>": None})
    )


def _normalize_geo_level(value: object) -> str | None:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"national", "state", "county"}:
        return cleaned
    return None


def _normalize_geo_code(value: object, geo_level: str | None) -> str | None:
    if geo_level is None:
        return None

    raw = str(value or "").strip()
    if geo_level == "national":
        return raw if raw else "US"

    digits = re.sub(r"[^0-9]", "", raw)
    if geo_level == "state":
        if not digits or len(digits) > 2:
            return None
        return digits.zfill(2)

    if geo_level == "county":
        if not digits or len(digits) > 5:
            return None
        return digits.zfill(5)

    return None


def _derive_state_fips(geo_level: str, geo_code: str) -> str | None:
    if geo_level == "state" and re.fullmatch(r"\d{2}", geo_code):
        return geo_code
    if geo_level == "county" and re.fullmatch(r"\d{5}", geo_code):
        return geo_code[:2]
    return None


def _derive_county_fips(geo_level: str, geo_code: str) -> str | None:
    if geo_level == "county" and re.fullmatch(r"\d{5}", geo_code):
        return geo_code
    return None


def _infer_domain(measure_id: str) -> str | None:
    token = str(measure_id or "").strip().split("_", 1)[0]
    return token or None


def _infer_unit(measure_id: str) -> str | None:
    cleaned = str(measure_id or "").upper()
    if cleaned.endswith("_PCT") or cleaned.endswith("_RATE"):
        return "rate"
    if cleaned.endswith("_AMT"):
        return "usd"
    if cleaned.endswith("_CNT"):
        return "count"
    return None


def _ensure_target_tables(connection) -> None:
    required_tables = ("geo_dim", "gv_measure_dim", "gv_fact")
    for table_name in required_tables:
        exists = connection.execute(
            text("SELECT to_regclass(:name) AS exists"),
            {"name": cms_table(table_name)},
        ).scalar()
        if exists is None:
            raise RuntimeError(
                f"Missing table {cms_table(table_name)}. "
                "Run alembic upgrade head before ingestion."
            )


def _execute_upsert_with_counts(
    connection,
    statement,
    rows: list[dict[str, object]],
) -> tuple[int, int]:
    if not rows:
        return (0, 0)

    inserted_total = 0
    updated_total = 0

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        result = connection.execute(statement, batch)
        try:
            inserted_flags = [bool(flag) for flag in result.scalars().all()]
            if inserted_flags:
                inserted = sum(1 for flag in inserted_flags if flag)
                updated = len(inserted_flags) - inserted
            else:
                affected = int(result.rowcount or 0)
                inserted = max(affected, 0)
                updated = 0
        except ResourceClosedError:
            affected = int(result.rowcount or 0)
            inserted = max(affected, 0)
            updated = 0

        inserted_total += inserted
        updated_total += updated

    return inserted_total, updated_total


def _upsert_measure_dim_rows(
    connection,
    measure_columns: Iterable[str],
) -> tuple[int, int]:
    rows = [
        {
            "measure_id": measure_id,
            "label": measure_id,
            "description": None,
            "unit": _infer_unit(measure_id),
            "domain": _infer_domain(measure_id),
            "source": "CMS FFS GV PUF",
        }
        for measure_id in measure_columns
    ]

    stmt = text(
        f"""
        INSERT INTO {GV_MEASURE_DIM_TABLE} (
            measure_id,
            label,
            description,
            unit,
            domain,
            source
        ) VALUES (
            :measure_id,
            :label,
            :description,
            :unit,
            :domain,
            :source
        )
        ON CONFLICT (measure_id)
        DO UPDATE SET
            label = COALESCE(NULLIF({GV_MEASURE_DIM_TABLE}.label, ''), EXCLUDED.label),
            description = COALESCE({GV_MEASURE_DIM_TABLE}.description, EXCLUDED.description),
            unit = COALESCE({GV_MEASURE_DIM_TABLE}.unit, EXCLUDED.unit),
            domain = COALESCE({GV_MEASURE_DIM_TABLE}.domain, EXCLUDED.domain),
            source = COALESCE({GV_MEASURE_DIM_TABLE}.source, EXCLUDED.source)
        RETURNING (xmax = 0) AS inserted
        """
    )
    return _execute_upsert_with_counts(connection, stmt, rows)


def _upsert_geo_dim_rows(connection, rows: list[dict[str, object]]) -> tuple[int, int]:
    stmt = text(
        f"""
        INSERT INTO {GEO_DIM_TABLE} (
            geo_level,
            geo_code,
            geo_name,
            state_fips,
            county_fips
        ) VALUES (
            :geo_level,
            :geo_code,
            :geo_name,
            :state_fips,
            :county_fips
        )
        ON CONFLICT (geo_level, geo_code)
        DO UPDATE SET
            geo_name = EXCLUDED.geo_name,
            state_fips = EXCLUDED.state_fips,
            county_fips = EXCLUDED.county_fips
        RETURNING (xmax = 0) AS inserted
        """
    )
    return _execute_upsert_with_counts(connection, stmt, rows)


def _upsert_fact_rows(connection, rows: list[dict[str, object]]) -> tuple[int, int]:
    stmt = text(
        f"""
        INSERT INTO {GV_FACT_TABLE} (
            year,
            geo_level,
            geo_code,
            age_level,
            measure_id,
            value,
            is_suppressed
        ) VALUES (
            :year,
            :geo_level,
            :geo_code,
            :age_level,
            :measure_id,
            :value,
            :is_suppressed
        )
        ON CONFLICT (year, geo_level, geo_code, age_level, measure_id)
        DO UPDATE SET
            value = EXCLUDED.value,
            is_suppressed = EXCLUDED.is_suppressed
        RETURNING (xmax = 0) AS inserted
        """
    )
    return _execute_upsert_with_counts(connection, stmt, rows)


def ingest(csv_path: Path, db_url: str, chunksize: int) -> None:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    started = time.perf_counter()
    engine = create_engine(db_url, future=True)

    total_source_rows = 0
    total_valid_base_rows = 0
    total_fact_rows = 0
    total_blank_cells = 0
    total_suppressed_cells = 0
    total_non_numeric_cells = 0

    total_geo_inserted = 0
    total_geo_updated = 0
    total_measure_inserted = 0
    total_measure_updated = 0
    total_fact_inserted = 0
    total_fact_updated = 0

    measure_columns: list[str] | None = None

    with engine.begin() as connection:
        _ensure_target_tables(connection)

    for chunk_idx, raw_chunk in enumerate(
        pd.read_csv(csv_path, dtype=str, chunksize=chunksize, low_memory=False),
        start=1,
    ):
        total_source_rows += len(raw_chunk)
        chunk = _normalize_headers(raw_chunk)

        missing_columns = [column for column in REQUIRED_DIM_COLUMNS if column not in chunk.columns]
        if missing_columns:
            raise RuntimeError(
                f"Chunk {chunk_idx} is missing required columns: {', '.join(missing_columns)}"
            )

        if measure_columns is None:
            measure_columns = [column for column in chunk.columns if column not in REQUIRED_DIM_COLUMNS]
            if not measure_columns:
                raise RuntimeError("No GV measure columns found after dimension columns.")
            with engine.begin() as connection:
                inserted, updated = _upsert_measure_dim_rows(connection, measure_columns)
                total_measure_inserted += inserted
                total_measure_updated += updated

        base = pd.DataFrame(index=chunk.index)
        base["year"] = pd.to_numeric(chunk["YEAR"], errors="coerce")
        base["geo_level"] = chunk["BENE_GEO_LVL"].apply(_normalize_geo_level)
        base["geo_code"] = [
            _normalize_geo_code(code, level)
            for code, level in zip(chunk["BENE_GEO_CD"], base["geo_level"], strict=False)
        ]
        base["geo_name"] = _clean_text_series(chunk["BENE_GEO_DESC"])
        base["age_level"] = _clean_text_series(chunk["BENE_AGE_LVL"])

        valid_base_mask = (
            base["year"].notna()
            & base["geo_level"].notna()
            & base["geo_code"].notna()
            & base["age_level"].notna()
        )
        if not valid_base_mask.any():
            print(f"Chunk {chunk_idx}: no valid dimension rows, skipped")
            continue

        valid_base = base.loc[valid_base_mask].copy()
        valid_base["year"] = valid_base["year"].astype(int)
        valid_base["geo_name"] = valid_base["geo_name"].fillna(valid_base["geo_code"])
        total_valid_base_rows += int(len(valid_base))

        geo_rows_df = valid_base[["geo_level", "geo_code", "geo_name"]].drop_duplicates().copy()
        geo_rows_df["state_fips"] = [
            _derive_state_fips(level, code)
            for level, code in zip(geo_rows_df["geo_level"], geo_rows_df["geo_code"], strict=False)
        ]
        geo_rows_df["county_fips"] = [
            _derive_county_fips(level, code)
            for level, code in zip(geo_rows_df["geo_level"], geo_rows_df["geo_code"], strict=False)
        ]
        geo_rows_df = geo_rows_df.where(pd.notna(geo_rows_df), None)
        geo_rows = geo_rows_df.to_dict(orient="records")

        fact_wide = chunk.loc[valid_base_mask, measure_columns].copy()
        fact_wide.insert(0, "year", valid_base["year"].to_numpy())
        fact_wide.insert(1, "geo_level", valid_base["geo_level"].to_numpy())
        fact_wide.insert(2, "geo_code", valid_base["geo_code"].to_numpy())
        fact_wide.insert(3, "age_level", valid_base["age_level"].to_numpy())

        melted = fact_wide.melt(
            id_vars=["year", "geo_level", "geo_code", "age_level"],
            value_vars=measure_columns,
            var_name="measure_id",
            value_name="raw_value",
        )

        raw_value = _clean_text_series(melted["raw_value"]).fillna("")
        raw_upper = raw_value.str.upper()
        suppressed_mask = (
            raw_upper.isin(SUPPRESSION_TOKENS)
            | raw_value.str.fullmatch(r"<\s*\d+(?:\.\d+)?", na=False)
        )
        blank_mask = raw_upper.isin(NULL_TOKENS)

        numeric_value = pd.to_numeric(
            raw_value.mask(suppressed_mask | blank_mask, None),
            errors="coerce",
        )
        non_numeric_unsuppressed_mask = (~suppressed_mask) & (~blank_mask) & numeric_value.isna()

        melted["value"] = numeric_value
        melted["is_suppressed"] = suppressed_mask.astype(bool)

        keep_mask = suppressed_mask | blank_mask | non_numeric_unsuppressed_mask | melted["value"].notna()
        fact_rows_df = melted.loc[
            keep_mask,
            ["year", "geo_level", "geo_code", "age_level", "measure_id", "value", "is_suppressed"],
        ].copy()
        fact_rows_df = fact_rows_df.where(pd.notna(fact_rows_df), None)

        total_suppressed_cells += int(suppressed_mask.sum())
        total_blank_cells += int(blank_mask.sum())
        total_non_numeric_cells += int(non_numeric_unsuppressed_mask.sum())

        fact_rows = fact_rows_df.to_dict(orient="records")
        total_fact_rows += len(fact_rows)

        with engine.begin() as connection:
            geo_inserted, geo_updated = _upsert_geo_dim_rows(connection, geo_rows)
            fact_inserted, fact_updated = _upsert_fact_rows(connection, fact_rows)
            total_geo_inserted += geo_inserted
            total_geo_updated += geo_updated
            total_fact_inserted += fact_inserted
            total_fact_updated += fact_updated

        print(
            f"Chunk {chunk_idx}: source_rows={len(raw_chunk)} valid_geo_rows={len(valid_base)} "
            f"fact_rows={len(fact_rows)} suppressed={int(suppressed_mask.sum())} "
            f"blank={int(blank_mask.sum())} non_numeric={int(non_numeric_unsuppressed_mask.sum())}"
        )

    elapsed = time.perf_counter() - started
    print("GV ingest complete")
    print(f"  schema: {CMS_SCHEMA}")
    print(f"  source rows read: {total_source_rows}")
    print(f"  valid dimension rows: {total_valid_base_rows}")
    print(f"  fact rows staged: {total_fact_rows}")
    print(f"  suppressed cells: {total_suppressed_cells}")
    print(f"  blank cells (stored as NULL, is_suppressed=false): {total_blank_cells}")
    print(f"  non-numeric cells (stored as NULL, is_suppressed=false): {total_non_numeric_cells}")
    print(f"  geo_dim inserted: {total_geo_inserted}, updated: {total_geo_updated}")
    print(
        f"  gv_measure_dim inserted: {total_measure_inserted}, "
        f"updated: {total_measure_updated}"
    )
    print(f"  gv_fact inserted: {total_fact_inserted}, updated: {total_fact_updated}")
    print(f"  elapsed seconds: {elapsed:.2f}")


def main() -> None:
    args = parse_args()
    ingest(Path(args.path).expanduser().resolve(), args.db_url, args.chunksize)


if __name__ == "__main__":
    main()
