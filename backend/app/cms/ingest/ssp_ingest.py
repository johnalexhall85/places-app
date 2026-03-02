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
DEFAULT_CHUNKSIZE = 5000
BATCH_SIZE = 2000

SUPPRESSION_TOKENS = {"*", ".", "NA", "N/A", "SUPP", "SUPPRESSED"}
NULL_TOKENS = {"", "NULL", "NONE", "NAN"}

MEASURE_ENROLLMENT_RE = re.compile(
    r"^(?P<measure_id>.+)_(?P<enrollment_type>ESRD|DIS|AGDU|AGND)$"
)

SSP_MEASURE_DIM_TABLE = cms_table("ssp_measure_dim")
SSP_FACT_TABLE = cms_table("ssp_fact")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Ingest CMS SSP County FFS PUF into {CMS_SCHEMA} schema tables."
    )
    parser.add_argument("--path", required=True, help="Path to CMS SSP CSV file.")
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
    parser.add_argument(
        "--assign-window",
        choices=["calendar", "offset"],
        default=None,
        help="Optional assignment window override. If omitted, inferred from filename/column.",
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


def _normalize_year(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _normalize_state_fips(value: object) -> str | None:
    digits = re.sub(r"[^0-9]", "", str(value or "").strip())
    if not digits or len(digits) > 2:
        return None
    normalized = digits.zfill(2)
    return normalized if re.fullmatch(r"\d{2}", normalized) else None


def _normalize_county_id3(value: object) -> str | None:
    digits = re.sub(r"[^0-9]", "", str(value or "").strip())
    if not digits or len(digits) > 3:
        return None
    normalized = digits.zfill(3)
    return normalized if re.fullmatch(r"\d{3}", normalized) else None


def _normalize_county_fips(value: object) -> str | None:
    digits = re.sub(r"[^0-9]", "", str(value or "").strip())
    if not digits or len(digits) > 5:
        return None
    normalized = digits.zfill(5)
    return normalized if re.fullmatch(r"\d{5}", normalized) else None


def _normalize_county_fips_from_parts(state_id: object, county_id: object) -> str | None:
    state_fips = _normalize_state_fips(state_id)
    county_code = _normalize_county_id3(county_id)
    if state_fips is None or county_code is None:
        return None
    return f"{state_fips}{county_code}"


def _normalize_assign_window(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if "offset" in normalized:
        return "offset"
    if "calendar" in normalized:
        return "calendar"
    return None


def _infer_assign_window(path: Path) -> str:
    lowered = path.name.lower()
    if "offset" in lowered:
        return "offset"
    if "calendar" in lowered:
        return "calendar"
    return "offset"


def _infer_domain(measure_id: str) -> str | None:
    token = str(measure_id or "").split("_", 1)[0].strip()
    return token or None


def _infer_unit(measure_id: str) -> str | None:
    cleaned = str(measure_id or "").upper()
    if "PER_CAPITA" in cleaned:
        return "usd"
    if "SCORE" in cleaned:
        return "score"
    if "PERSON_YEARS" in cleaned:
        return "person_years"
    return None


def _resolve_county_fips_columns(columns: list[str]) -> tuple[str, str | None]:
    direct_candidates = (
        "COUNTY_FIPS",
        "COUNTYFIPS",
        "STATE_COUNTY_FIPS",
        "STATE_COUNTYFIPS",
        "FIPS",
        "GEOID",
        "GEO_ID",
    )
    for candidate in direct_candidates:
        if candidate in columns:
            return candidate, None

    state_candidates = ("STATE_ID", "STATE_FIPS", "STATEFP")
    county_candidates = ("COUNTY_ID", "COUNTY_CODE", "COUNTYFP", "COUNTY")
    for state_col in state_candidates:
        if state_col not in columns:
            continue
        for county_col in county_candidates:
            if county_col in columns:
                return state_col, county_col

    raise RuntimeError(
        "Unable to identify county FIPS source columns. "
        "Expected COUNTY_FIPS/FIPS-style column or STATE_ID+COUNTY_ID pair."
    )


def _resolve_enrollment_type_column(columns: list[str]) -> str | None:
    for candidate in ("ENROLLMENT_TYPE", "ENROLL_TYPE", "BENE_TYPE", "POP_TYPE"):
        if candidate in columns:
            return candidate
    return None


def _resolve_assign_window_column(columns: list[str]) -> str | None:
    for candidate in ("ASSIGN_WINDOW", "ASSIGNMENT_WINDOW", "WINDOW_TYPE", "WINDOW"):
        if candidate in columns:
            return candidate
    return None


def _ensure_target_tables(connection) -> None:
    for table_name in ("ssp_measure_dim", "ssp_fact"):
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
    measure_ids: Iterable[str],
) -> tuple[int, int]:
    rows = [
        {
            "measure_id": measure_id,
            "label": measure_id,
            "description": None,
            "unit": _infer_unit(measure_id),
            "domain": _infer_domain(measure_id),
            "source": "CMS SSP County FFS PUF",
        }
        for measure_id in sorted(set(measure_ids))
    ]

    stmt = text(
        f"""
        INSERT INTO {SSP_MEASURE_DIM_TABLE} (
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
            label = COALESCE(NULLIF({SSP_MEASURE_DIM_TABLE}.label, ''), EXCLUDED.label),
            description = COALESCE({SSP_MEASURE_DIM_TABLE}.description, EXCLUDED.description),
            unit = COALESCE({SSP_MEASURE_DIM_TABLE}.unit, EXCLUDED.unit),
            domain = COALESCE({SSP_MEASURE_DIM_TABLE}.domain, EXCLUDED.domain),
            source = COALESCE({SSP_MEASURE_DIM_TABLE}.source, EXCLUDED.source)
        RETURNING (xmax = 0) AS inserted
        """
    )
    return _execute_upsert_with_counts(connection, stmt, rows)


def _upsert_fact_rows(connection, rows: list[dict[str, object]]) -> tuple[int, int]:
    stmt = text(
        f"""
        INSERT INTO {SSP_FACT_TABLE} (
            year,
            county_fips,
            enrollment_type,
            assign_window,
            measure_id,
            value,
            is_suppressed
        ) VALUES (
            :year,
            :county_fips,
            :enrollment_type,
            :assign_window,
            :measure_id,
            :value,
            :is_suppressed
        )
        ON CONFLICT (year, county_fips, enrollment_type, assign_window, measure_id)
        DO UPDATE SET
            value = EXCLUDED.value,
            is_suppressed = EXCLUDED.is_suppressed
        RETURNING (xmax = 0) AS inserted
        """
    )
    return _execute_upsert_with_counts(connection, stmt, rows)


def ingest(csv_path: Path, db_url: str, chunksize: int, assign_window: str | None) -> None:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    inferred_assign_window = _infer_assign_window(csv_path)
    fallback_assign_window = assign_window or inferred_assign_window
    started = time.perf_counter()
    engine = create_engine(db_url, future=True)

    total_source_rows = 0
    total_valid_rows = 0
    total_invalid_county_fips = 0
    total_fact_rows = 0
    total_blank_cells = 0
    total_suppressed_cells = 0
    total_non_numeric_cells = 0
    total_measure_inserted = 0
    total_measure_updated = 0
    total_fact_inserted = 0
    total_fact_updated = 0

    year_column: str | None = None
    county_col_1: str | None = None
    county_col_2: str | None = None
    enrollment_col: str | None = None
    assign_window_col: str | None = None
    measure_columns: list[str] | None = None

    with engine.begin() as connection:
        _ensure_target_tables(connection)

    for chunk_idx, raw_chunk in enumerate(
        pd.read_csv(csv_path, dtype=str, chunksize=chunksize, low_memory=False),
        start=1,
    ):
        total_source_rows += len(raw_chunk)
        chunk = _normalize_headers(raw_chunk)
        columns = list(chunk.columns)

        if year_column is None:
            year_column = "YEAR" if "YEAR" in columns else None
            if year_column is None:
                raise RuntimeError("SSP CSV is missing required YEAR column.")

            county_col_1, county_col_2 = _resolve_county_fips_columns(columns)
            enrollment_col = _resolve_enrollment_type_column(columns)
            assign_window_col = _resolve_assign_window_column(columns)

            excluded = {
                year_column,
                county_col_1,
                "STATE_NAME",
                "COUNTY_NAME",
                "STATE_ID",
                "COUNTY_ID",
            }
            if county_col_2 is not None:
                excluded.add(county_col_2)
            if enrollment_col is not None:
                excluded.add(enrollment_col)
            if assign_window_col is not None:
                excluded.add(assign_window_col)

            measure_columns = [column for column in columns if column not in excluded]
            if not measure_columns:
                raise RuntimeError("No SSP measure columns found in CSV.")

            provisional_measure_ids: list[str] = []
            for measure_column in measure_columns:
                matched = MEASURE_ENROLLMENT_RE.match(measure_column)
                provisional_measure_ids.append(
                    matched.group("measure_id") if matched is not None else measure_column
                )

            with engine.begin() as connection:
                inserted, updated = _upsert_measure_dim_rows(connection, provisional_measure_ids)
                total_measure_inserted += inserted
                total_measure_updated += updated
        else:
            expected = {year_column, county_col_1, *(measure_columns or [])}
            if county_col_2 is not None:
                expected.add(county_col_2)
            if enrollment_col is not None:
                expected.add(enrollment_col)
            if assign_window_col is not None:
                expected.add(assign_window_col)
            missing = [column for column in expected if column not in columns]
            if missing:
                raise RuntimeError(
                    f"CSV schema changed during ingest; missing columns: {', '.join(sorted(missing))}"
                )

        assert year_column is not None
        assert county_col_1 is not None
        assert measure_columns is not None

        base = pd.DataFrame(index=chunk.index)
        base["year"] = _normalize_year(chunk[year_column])
        if county_col_2 is None:
            base["county_fips"] = chunk[county_col_1].apply(_normalize_county_fips)
        else:
            base["county_fips"] = [
                _normalize_county_fips_from_parts(state_id, county_id)
                for state_id, county_id in zip(
                    chunk[county_col_1],
                    chunk[county_col_2],
                    strict=False,
                )
            ]

        if enrollment_col is not None:
            enrollment_series = _clean_text_series(chunk[enrollment_col]).fillna("all")
            base["enrollment_type"] = enrollment_series.str.lower()
        else:
            base["enrollment_type"] = None

        if assign_window_col is not None:
            assign_series = chunk[assign_window_col].apply(_normalize_assign_window)
            base["assign_window"] = assign_series.fillna(fallback_assign_window)
        else:
            base["assign_window"] = fallback_assign_window

        invalid_county_mask = pd.Series(base["county_fips"]).isna()
        total_invalid_county_fips += int(invalid_county_mask.sum())

        valid_base_mask = (
            base["year"].notna()
            & base["county_fips"].notna()
            & pd.Series(base["assign_window"]).isin(["calendar", "offset"])
        )
        if not valid_base_mask.any():
            print(f"Chunk {chunk_idx}: no valid county rows, skipped")
            continue

        valid_base = base.loc[valid_base_mask].copy()
        valid_base["year"] = valid_base["year"].astype(int)
        valid_base["enrollment_type"] = valid_base["enrollment_type"].fillna("all")
        total_valid_rows += int(len(valid_base))

        fact_wide = chunk.loc[valid_base_mask, measure_columns].copy()
        fact_wide.insert(0, "year", valid_base["year"].to_numpy())
        fact_wide.insert(1, "county_fips", valid_base["county_fips"].to_numpy())
        fact_wide.insert(2, "enrollment_type", valid_base["enrollment_type"].to_numpy())
        fact_wide.insert(3, "assign_window", valid_base["assign_window"].to_numpy())

        melted = fact_wide.melt(
            id_vars=["year", "county_fips", "enrollment_type", "assign_window"],
            value_vars=measure_columns,
            var_name="raw_measure_id",
            value_name="raw_value",
        )

        parsed_measure = melted["raw_measure_id"].str.extract(MEASURE_ENROLLMENT_RE)
        has_suffix = parsed_measure["measure_id"].notna()
        melted["measure_id"] = parsed_measure["measure_id"].where(
            has_suffix,
            melted["raw_measure_id"],
        )
        if enrollment_col is None:
            melted["enrollment_type"] = parsed_measure["enrollment_type"].str.lower().where(
                has_suffix,
                melted["enrollment_type"].fillna("all"),
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
            [
                "year",
                "county_fips",
                "enrollment_type",
                "assign_window",
                "measure_id",
                "value",
                "is_suppressed",
            ],
        ].copy()
        fact_rows_df = fact_rows_df.where(pd.notna(fact_rows_df), None)

        total_suppressed_cells += int(suppressed_mask.sum())
        total_blank_cells += int(blank_mask.sum())
        total_non_numeric_cells += int(non_numeric_unsuppressed_mask.sum())

        fact_rows = fact_rows_df.to_dict(orient="records")
        total_fact_rows += len(fact_rows)

        with engine.begin() as connection:
            fact_inserted, fact_updated = _upsert_fact_rows(connection, fact_rows)
            total_fact_inserted += fact_inserted
            total_fact_updated += fact_updated

        print(
            f"Chunk {chunk_idx}: source_rows={len(raw_chunk)} valid_county_rows={len(valid_base)} "
            f"fact_rows={len(fact_rows)} suppressed={int(suppressed_mask.sum())} "
            f"blank={int(blank_mask.sum())} non_numeric={int(non_numeric_unsuppressed_mask.sum())}"
        )

    elapsed = time.perf_counter() - started
    print("SSP ingest complete")
    print(f"  schema: {CMS_SCHEMA}")
    print(f"  assign_window fallback: {fallback_assign_window}")
    print(f"  source rows read: {total_source_rows}")
    print(f"  valid county rows: {total_valid_rows}")
    print(f"  invalid county_fips rows: {total_invalid_county_fips}")
    print(f"  fact rows staged: {total_fact_rows}")
    print(f"  suppressed cells: {total_suppressed_cells}")
    print(f"  blank cells (stored as NULL, is_suppressed=false): {total_blank_cells}")
    print(f"  non-numeric cells (stored as NULL, is_suppressed=false): {total_non_numeric_cells}")
    print(
        f"  ssp_measure_dim inserted: {total_measure_inserted}, "
        f"updated: {total_measure_updated}"
    )
    print(f"  ssp_fact inserted: {total_fact_inserted}, updated: {total_fact_updated}")
    print(f"  elapsed seconds: {elapsed:.2f}")


def main() -> None:
    args = parse_args()
    ingest(
        Path(args.path).expanduser().resolve(),
        args.db_url,
        args.chunksize,
        args.assign_window,
    )


if __name__ == "__main__":
    main()
