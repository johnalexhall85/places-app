import argparse
import os
from pathlib import Path
from typing import Iterator

import pandas as pd
from sqlalchemy import create_engine, text


DEFAULT_CSV_NAME = (
    "PLACES__Local_Data_for_Better_Health,_Census_Tract_Data,_2025_release_20260215.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest PLACES 2025 census tract estimates into PostGIS."
    )
    parser.add_argument(
        "--csv-path",
        default=None,
        help="Path to the tract CSV. Defaults to project data folder.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL env variable.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=120000,
        help="CSV chunk size (rows per batch).",
    )
    return parser.parse_args()


def resolve_csv_path(csv_path_arg: str | None) -> Path:
    if csv_path_arg:
        path = Path(csv_path_arg).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {path}")
        return path

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent
    default_path = project_root / "data" / DEFAULT_CSV_NAME
    if not default_path.exists():
        raise FileNotFoundError(
            "Could not locate tract CSV. Provide --csv-path or place it at "
            f"{default_path}"
        )
    return default_path


def resolve_db_url(db_url_arg: str | None) -> str:
    db_url = db_url_arg or os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set and --db-url was not provided.")
    return db_url


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    if "MeasureId" in df.columns and "MeasureID" not in df.columns:
        rename_map["MeasureId"] = "MeasureID"
    if "DataValueTypeID" in df.columns and "Data_Value_TypeID" not in df.columns:
        rename_map["DataValueTypeID"] = "Data_Value_TypeID"
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def assert_required_columns(df: pd.DataFrame) -> None:
    required = [
        "Year",
        "StateAbbr",
        "StateDesc",
        "CountyName",
        "CountyFIPS",
        "LocationName",
        "DataSource",
        "Category",
        "CategoryID",
        "Measure",
        "MeasureID",
        "Data_Value_Unit",
        "Data_Value_Type",
        "Data_Value_TypeID",
        "Data_Value",
        "Low_Confidence_Limit",
        "High_Confidence_Limit",
        "TotalPopulation",
        "TotalPop18plus",
        "Geolocation",
        "LocationID",
        "Short_Question_Text",
    ]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise RuntimeError(f"CSV missing expected columns: {missing}")


def to_nullable_float(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace({"": None, "nan": None, "None": None})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def to_nullable_int(series: pd.Series) -> pd.Series:
    return to_nullable_float(series).astype("Int64")


def to_point_ewkt(series: pd.Series) -> pd.Series:
    values = (
        series.astype(str)
        .str.strip()
        .replace({"": None, "nan": None, "None": None})
    )
    return values.apply(
        lambda value: None
        if value is None
        else (
            f"SRID=4326;{value}"
            if value.upper().startswith("POINT")
            else None
        )
    )


def prepare_chunk(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_columns(df)
    assert_required_columns(df)

    prepared = pd.DataFrame()
    prepared["year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    prepared["locationid"] = df["LocationID"].astype(str).str.strip()
    prepared["measure_id"] = df["MeasureID"].astype(str).str.strip()
    prepared["data_value_type_id"] = df["Data_Value_TypeID"].astype(str).str.strip()
    prepared["state_abbr"] = df["StateAbbr"].astype(str).str.upper().str.strip()
    prepared["state_desc"] = df["StateDesc"].astype(str).str.strip()
    prepared["county_name"] = df["CountyName"].astype(str).str.strip()
    prepared["county_fips"] = df["CountyFIPS"].astype(str).str.zfill(5).str.strip()
    prepared["location_name"] = df["LocationName"].astype(str).str.strip()
    prepared["data_source"] = df["DataSource"].astype(str).str.strip()
    prepared["category"] = df["Category"].astype(str).str.strip()
    prepared["category_id"] = df["CategoryID"].astype(str).str.strip()
    prepared["measure"] = df["Measure"].astype(str).str.strip()
    prepared["data_value_unit"] = df["Data_Value_Unit"].astype(str).str.strip()
    prepared["data_value_type"] = df["Data_Value_Type"].astype(str).str.strip()
    prepared["data_value"] = to_nullable_float(df["Data_Value"])
    prepared["low_confidence_limit"] = to_nullable_float(df["Low_Confidence_Limit"])
    prepared["high_confidence_limit"] = to_nullable_float(df["High_Confidence_Limit"])
    prepared["total_population"] = to_nullable_int(df["TotalPopulation"])
    prepared["total_pop_18_plus"] = to_nullable_int(df["TotalPop18plus"])
    prepared["short_question_text"] = df["Short_Question_Text"].astype(str).str.strip()
    prepared["geolocation_ewkt"] = to_point_ewkt(df["Geolocation"])

    prepared = prepared[
        prepared["locationid"].str.fullmatch(r"\d{11}", na=False)
        & prepared["county_fips"].str.fullmatch(r"\d{5}", na=False)
        & prepared["year"].notna()
        & (prepared["measure_id"] != "")
        & (prepared["data_value_type_id"] != "")
    ].copy()

    prepared["year"] = prepared["year"].astype(int)
    return prepared


def iter_csv_chunks(csv_path: Path, chunksize: int) -> Iterator[pd.DataFrame]:
    yield from pd.read_csv(csv_path, dtype=str, chunksize=chunksize)


def ingest(csv_path: Path, db_url: str, chunksize: int) -> None:
    engine = create_engine(db_url, future=True)
    staging_table = "tmp_tract_estimates_ingest"

    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {staging_table}"))
        connection.execute(
            text(
                f"""
                CREATE TABLE {staging_table} (
                    year int,
                    locationid text,
                    measure_id text,
                    data_value_type_id text,
                    state_abbr text,
                    state_desc text,
                    county_name text,
                    county_fips text,
                    location_name text,
                    data_source text,
                    category text,
                    category_id text,
                    measure text,
                    data_value_unit text,
                    data_value_type text,
                    data_value double precision,
                    low_confidence_limit double precision,
                    high_confidence_limit double precision,
                    total_population bigint,
                    total_pop_18_plus bigint,
                    short_question_text text,
                    geolocation_ewkt text
                )
                """
            )
        )

    total_rows = 0
    total_upserted = 0
    chunk_number = 0

    for raw_chunk in iter_csv_chunks(csv_path, chunksize):
        chunk_number += 1
        total_rows += len(raw_chunk)
        chunk = prepare_chunk(raw_chunk)
        if chunk.empty:
            print(f"Chunk {chunk_number}: no valid rows, skipping.")
            continue

        with engine.begin() as connection:
            chunk.to_sql(
                staging_table,
                connection,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=5000,
            )

            connection.execute(
                text(
                    f"""
                    INSERT INTO tract_estimates (
                        year,
                        locationid,
                        measure_id,
                        data_value_type_id,
                        state_abbr,
                        state_desc,
                        county_name,
                        county_fips,
                        location_name,
                        data_source,
                        category,
                        category_id,
                        measure,
                        data_value_unit,
                        data_value_type,
                        data_value,
                        low_confidence_limit,
                        high_confidence_limit,
                        total_population,
                        total_pop_18_plus,
                        short_question_text,
                        geolocation
                    )
                    SELECT
                        t.year,
                        t.locationid,
                        t.measure_id,
                        t.data_value_type_id,
                        t.state_abbr,
                        t.state_desc,
                        t.county_name,
                        t.county_fips,
                        t.location_name,
                        t.data_source,
                        t.category,
                        t.category_id,
                        t.measure,
                        t.data_value_unit,
                        t.data_value_type,
                        t.data_value,
                        t.low_confidence_limit,
                        t.high_confidence_limit,
                        t.total_population,
                        t.total_pop_18_plus,
                        t.short_question_text,
                        CASE
                            WHEN t.geolocation_ewkt IS NULL THEN NULL
                            ELSE ST_GeomFromEWKT(t.geolocation_ewkt)::geometry(Point,4326)
                        END AS geolocation
                    FROM {staging_table} AS t
                    ON CONFLICT (year, locationid, measure_id, data_value_type_id)
                    DO UPDATE SET
                        state_abbr = EXCLUDED.state_abbr,
                        state_desc = EXCLUDED.state_desc,
                        county_name = EXCLUDED.county_name,
                        county_fips = EXCLUDED.county_fips,
                        location_name = EXCLUDED.location_name,
                        data_source = EXCLUDED.data_source,
                        category = EXCLUDED.category,
                        category_id = EXCLUDED.category_id,
                        measure = EXCLUDED.measure,
                        data_value_unit = EXCLUDED.data_value_unit,
                        data_value_type = EXCLUDED.data_value_type,
                        data_value = EXCLUDED.data_value,
                        low_confidence_limit = EXCLUDED.low_confidence_limit,
                        high_confidence_limit = EXCLUDED.high_confidence_limit,
                        total_population = EXCLUDED.total_population,
                        total_pop_18_plus = EXCLUDED.total_pop_18_plus,
                        short_question_text = EXCLUDED.short_question_text,
                        geolocation = EXCLUDED.geolocation
                    """
                )
            )

            inserted_count = connection.execute(
                text(f"SELECT COUNT(*) FROM {staging_table}")
            ).scalar_one()
            total_upserted += int(inserted_count)

            connection.execute(text(f"TRUNCATE TABLE {staging_table}"))

        print(
            f"Chunk {chunk_number}: processed {len(raw_chunk)} rows, "
            f"upserted {len(chunk)} cleaned rows."
        )

    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {staging_table}"))

    print(f"Done. Read {total_rows} CSV rows and upserted {total_upserted} rows.")


def main() -> None:
    args = parse_args()
    csv_path = resolve_csv_path(args.csv_path)
    db_url = resolve_db_url(args.db_url)

    print(f"Using CSV: {csv_path}")
    ingest(csv_path=csv_path, db_url=db_url, chunksize=args.chunksize)


if __name__ == "__main__":
    main()
