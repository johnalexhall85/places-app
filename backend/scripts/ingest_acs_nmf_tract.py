import argparse
import os
import re
import time
from pathlib import Path
from typing import Iterator

import pandas as pd
from sqlalchemy import create_engine, text

from _schema_imports import acs_table

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"

# Safe vs Postgres 65,535 parameter limit
BATCH_SIZE = 500

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "year_window": ("Year", "Year_Window"),
    "state_abbr": ("StateAbbr", "State_Abbr"),
    "location_id": ("LocationID", "LocationId", "TractFIPS", "TractFips"),
    "location_name": ("LocationDesc", "LocationName", "TractName"),
    "category_id": ("CategoryID", "CategoryId"),
    "category": ("Category",),
    "measure_id": ("MeasureID", "MeasureId"),
    "measure": ("Measure",),
    "data_value_type_id": ("DataValueTypeID", "Data_Value_TypeID", "DataValueTypeId"),
    "data_value_type": ("Data_Value_Type", "DataValueType"),
    "data_value_unit": ("Data_Value_Unit", "DataValueUnit"),
    "data_value": ("Data_Value", "DataValue"),
    "moe": ("MOE", "MoE"),
    "total_population": ("TotalPopulation", "Total_Population"),
    "geolocation": ("Geolocation", "GeoLocation"),
}

REQUIRED_KEYS = (
    "year_window",
    "state_abbr",
    "location_id",
    "location_name",
    "category_id",
    "category",
    "measure_id",
    "measure",
    "data_value_type_id",
    "data_value_type",
    "data_value",
    "moe",
    "total_population",
)

POINT_WKT_RE = re.compile(
    r"^\s*POINT\s*\(\s*([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*\)\s*$",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest ACS non-medical factor tract estimates into acs_nmf_tract_estimates."
    )
    parser.add_argument("--csv", required=True, help="Path to ACS NMF tract CSV file.")
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL or local places default.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate acs_nmf_tract_estimates before ingest.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=50000,
        help="CSV chunk size.",
    )
    return parser.parse_args()


def clean_text_series(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .replace({"": None, "nan": None, "None": None, "<NA>": None})
    )


def to_nullable_float(series: pd.Series) -> pd.Series:
    cleaned = clean_text_series(series).str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned, errors="coerce")


def to_nullable_int(series: pd.Series) -> pd.Series:
    return to_nullable_float(series).astype("Int64")


def to_point_ewkt(series: pd.Series) -> pd.Series:
    values = clean_text_series(series)

    def convert(value: object) -> str | None:
        if value is None:
            return None
        match = POINT_WKT_RE.match(str(value))
        if not match:
            return None
        lon = float(match.group(1))
        lat = float(match.group(2))
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return None
        return f"SRID=4326;POINT({lon} {lat})"

    return values.apply(convert)


def resolve_column(df: pd.DataFrame, key: str) -> str | None:
    aliases = COLUMN_ALIASES.get(key, ())
    for alias in aliases:
        if alias in df.columns:
            return alias
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(column).strip().lstrip("\ufeff") for column in df.columns]

    missing_required = [key for key in REQUIRED_KEYS if resolve_column(df, key) is None]
    if missing_required:
        raise RuntimeError("CSV missing required columns for: " f"{', '.join(missing_required)}")

    return df


def prepare_chunk(df: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_columns(df)

    output = pd.DataFrame()
    output["year_window"] = clean_text_series(normalized[resolve_column(normalized, "year_window")])
    output["state_abbr"] = clean_text_series(normalized[resolve_column(normalized, "state_abbr")]).str.upper()
    output["location_id"] = (
        clean_text_series(normalized[resolve_column(normalized, "location_id")])
        .str.replace(r"[^0-9]", "", regex=True)
        .str.zfill(11)
    )
    output["location_name"] = clean_text_series(normalized[resolve_column(normalized, "location_name")])
    output["category_id"] = clean_text_series(normalized[resolve_column(normalized, "category_id")])
    output["category"] = clean_text_series(normalized[resolve_column(normalized, "category")])
    output["measure_id"] = clean_text_series(normalized[resolve_column(normalized, "measure_id")])
    output["measure"] = clean_text_series(normalized[resolve_column(normalized, "measure")])
    output["data_value_type_id"] = clean_text_series(normalized[resolve_column(normalized, "data_value_type_id")])
    output["data_value_type"] = clean_text_series(normalized[resolve_column(normalized, "data_value_type")])

    data_value_unit_column = resolve_column(normalized, "data_value_unit")
    output["data_value_unit"] = (
        clean_text_series(normalized[data_value_unit_column]) if data_value_unit_column else None
    )

    output["data_value"] = to_nullable_float(normalized[resolve_column(normalized, "data_value")])
    output["moe"] = to_nullable_float(normalized[resolve_column(normalized, "moe")])
    output["total_population"] = to_nullable_int(normalized[resolve_column(normalized, "total_population")])

    geolocation_column = resolve_column(normalized, "geolocation")
    if geolocation_column:
        output["geolocation_ewkt"] = to_point_ewkt(normalized[geolocation_column])
    else:
        output["geolocation_ewkt"] = None

    valid_required = (
        output["year_window"].notna()
        & output["state_abbr"].str.fullmatch(r"[A-Z]{2}", na=False)
        & output["location_id"].str.fullmatch(r"\d{11}", na=False)
        & output["location_name"].notna()
        & output["category_id"].notna()
        & output["category"].notna()
        & output["measure_id"].notna()
        & output["measure"].notna()
        & output["data_value_type_id"].notna()
        & output["data_value_type"].notna()
    )

    output = output[valid_required].copy()

    for column in (
        "location_name",
        "category_id",
        "category",
        "measure_id",
        "measure",
        "data_value_type_id",
        "data_value_type",
    ):
        output = output[output[column].str.len() > 0]

    output = output.where(pd.notna(output), None)
    return output


def iter_csv_chunks(csv_path: Path, chunksize: int) -> Iterator[pd.DataFrame]:
    yield from pd.read_csv(csv_path, dtype=str, chunksize=chunksize)


def ensure_target_table_exists(connection) -> None:
    row = (
        connection.execute(
            text("SELECT to_regclass(:table_name) AS exists"),
            {"table_name": acs_table("acs_nmf_tract_estimates")},
        )
        .mappings()
        .one()
    )
    if row["exists"] is None:
        raise RuntimeError(
            "Table acs_nmf_tract_estimates does not exist. Run migrations before ingesting."
        )


def ingest(csv_path: Path, db_url: str, truncate: bool, chunksize: int) -> None:
    engine = create_engine(db_url, future=True)
    staging_table = "tmp_acs_nmf_tract_ingest"

    started = time.perf_counter()
    total_rows = 0
    total_valid_rows = 0
    total_upserted = 0
    chunk_number = 0

    # Create staging table once
    with engine.begin() as connection:
        ensure_target_table_exists(connection)
        if truncate:
            connection.execute(text("TRUNCATE TABLE acs_nmf_tract_estimates"))

        connection.execute(text(f"DROP TABLE IF EXISTS {staging_table}"))
        connection.execute(
            text(
                f"""
                CREATE TABLE {staging_table} (
                    year_window text,
                    state_abbr text,
                    location_id text,
                    location_name text,
                    category_id text,
                    category text,
                    measure_id text,
                    measure text,
                    data_value_type_id text,
                    data_value_type text,
                    data_value_unit text,
                    data_value double precision,
                    moe double precision,
                    total_population integer,
                    geolocation_ewkt text
                )
                """
            )
        )

    insert_staging_sql = text(
        f"""
        INSERT INTO {staging_table} (
            year_window,
            state_abbr,
            location_id,
            location_name,
            category_id,
            category,
            measure_id,
            measure,
            data_value_type_id,
            data_value_type,
            data_value_unit,
            data_value,
            moe,
            total_population,
            geolocation_ewkt
        ) VALUES (
            :year_window,
            :state_abbr,
            :location_id,
            :location_name,
            :category_id,
            :category,
            :measure_id,
            :measure,
            :data_value_type_id,
            :data_value_type,
            :data_value_unit,
            :data_value,
            :moe,
            :total_population,
            :geolocation_ewkt
        )
        """
    )

    for raw_chunk in iter_csv_chunks(csv_path, chunksize):
        chunk_number += 1
        total_rows += len(raw_chunk)

        prepared = prepare_chunk(raw_chunk)
        if prepared.empty:
            print(f"Chunk {chunk_number}: no valid rows, skipped.")
            continue

        total_valid_rows += len(prepared)

        with engine.begin() as connection:
            # 1) Insert into staging in safe batches (executemany)
            rows = prepared.to_dict(orient="records")
            for i in range(0, len(rows), BATCH_SIZE):
                connection.execute(insert_staging_sql, rows[i : i + BATCH_SIZE])

            # 2) Upsert from staging into target table
            result = connection.execute(
                text(
                    f"""
                    INSERT INTO acs_nmf_tract_estimates (
                        year_window,
                        state_abbr,
                        location_id,
                        location_name,
                        category_id,
                        category,
                        measure_id,
                        measure,
                        data_value_type_id,
                        data_value_type,
                        data_value_unit,
                        data_value,
                        moe,
                        total_population,
                        geolocation
                    )
                    SELECT
                        t.year_window,
                        t.state_abbr,
                        t.location_id,
                        t.location_name,
                        t.category_id,
                        t.category,
                        t.measure_id,
                        t.measure,
                        t.data_value_type_id,
                        t.data_value_type,
                        t.data_value_unit,
                        t.data_value,
                        t.moe,
                        t.total_population,
                        CASE
                            WHEN t.geolocation_ewkt IS NULL THEN NULL
                            ELSE ST_GeomFromEWKT(t.geolocation_ewkt)
                        END AS geolocation
                    FROM {staging_table} AS t
                    ON CONFLICT (
                        year_window,
                        location_id,
                        measure_id,
                        data_value_type_id
                    ) DO UPDATE SET
                        state_abbr = EXCLUDED.state_abbr,
                        location_name = EXCLUDED.location_name,
                        category_id = EXCLUDED.category_id,
                        category = EXCLUDED.category,
                        measure = EXCLUDED.measure,
                        data_value_type = EXCLUDED.data_value_type,
                        data_value_unit = EXCLUDED.data_value_unit,
                        data_value = EXCLUDED.data_value,
                        moe = EXCLUDED.moe,
                        total_population = EXCLUDED.total_population,
                        geolocation = EXCLUDED.geolocation
                    """
                )
            )

            upserted = int(result.rowcount or 0)
            total_upserted += upserted

            # 3) Clear staging for next chunk
            connection.execute(text(f"TRUNCATE TABLE {staging_table}"))

        print(f"Chunk {chunk_number}: raw={len(raw_chunk)} valid={len(prepared)} upserted={upserted}")

    # Drop staging table
    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {staging_table}"))

    elapsed = time.perf_counter() - started
    print("Ingestion complete")
    print(f"  csv: {csv_path}")
    print(f"  rows_read: {total_rows}")
    print(f"  rows_valid: {total_valid_rows}")
    print(f"  rows_upserted: {total_upserted}")
    print(f"  elapsed_seconds: {elapsed:.2f}")


def main() -> None:
    args = parse_args()

    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.exists() or not csv_path.is_file():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    db_url = args.db_url or os.getenv("DATABASE_URL", DEFAULT_DB_URL)

    ingest(
        csv_path=csv_path,
        db_url=db_url,
        truncate=args.truncate,
        chunksize=args.chunksize,
    )


if __name__ == "__main__":
    main()
