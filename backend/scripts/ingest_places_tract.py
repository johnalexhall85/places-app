import argparse
import csv
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Iterator

import pandas as pd
from geoalchemy2 import Geometry, WKTElement
from sqlalchemy import BigInteger, Column, Float, Integer, MetaData, String, Table, Text, create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from _schema_imports import PLACES_SCHEMA


MAX_CHUNK_SIZE = 1000
DEFAULT_DICT_PATH = "../data/PLACES_and_500_Cities__Data_Dictionary_20260215.csv"
SCRIPT_DIR = Path(__file__).resolve().parent
TRACT_ESTIMATE_COLUMNS = [
    "year",
    "locationid",
    "measure_id",
    "data_value_type_id",
    "state_abbr",
    "state_desc",
    "county_name",
    "county_fips",
    "location_name",
    "data_source",
    "category",
    "category_id",
    "measure",
    "data_value_unit",
    "data_value_type",
    "data_value",
    "low_confidence_limit",
    "high_confidence_limit",
    "total_population",
    "total_pop_18_plus",
    "short_question_text",
    "geolocation",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest PLACES census tract estimates into tract_estimates, "
            "preserving estimate year from CSV Year."
        )
    )
    parser.add_argument("--csv", required=True, help="Path to tract CSV.")
    parser.add_argument(
        "--dict",
        dest="dict_path",
        default=DEFAULT_DICT_PATH,
        help=f"Optional data dictionary CSV path (default: {DEFAULT_DICT_PATH}).",
    )
    parser.add_argument(
        "--release-label",
        required=True,
        help="Release provenance label, e.g. 2024_release_20260219.",
    )
    parser.add_argument(
        "--filter-year",
        type=int,
        default=None,
        help="Optional estimate year filter; only rows with CSV Year == filter-year are ingested.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=MAX_CHUNK_SIZE,
        help=f"Chunk size for CSV and DB writes (max {MAX_CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and transform only. Do not write facts/ledger to DB.",
    )
    return parser.parse_args()


def validate_input_path(path_value: str, label: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute() and not path.exists():
        script_relative = (SCRIPT_DIR / path).resolve()
        if script_relative.exists():
            path = script_relative
    if path.name.endswith(":Zone.Identifier"):
        raise ValueError(f"{label} cannot be a Windows Zone.Identifier file: {path}")
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    if not path.is_file():
        raise ValueError(f"{label} is not a file: {path}")
    return path


def resolve_db_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    return db_url


def detect_delimiter(csv_path: Path) -> str:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(65536)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def iter_csv_chunks(
    csv_path: Path,
    *,
    delimiter: str,
    chunk_size: int,
) -> Iterator[pd.DataFrame]:
    yield from pd.read_csv(
        csv_path,
        sep=delimiter,
        dtype=str,
        chunksize=chunk_size,
        engine="python",
    )


def detect_year_column(df: pd.DataFrame) -> str:
    matches = [column for column in df.columns if str(column).strip().lower() == "year"]
    if not matches:
        raise RuntimeError("CSV missing required Year column (case-insensitive match).")
    if len(matches) > 1:
        raise RuntimeError(f"CSV has multiple Year-like columns: {matches}")
    return matches[0]


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(column).strip().lstrip("\ufeff") for column in df.columns]

    def normalized_token(value: str) -> str:
        return "".join(ch for ch in str(value).lower() if ch.isalnum())

    def add_alias_rename(
        rename_map: dict[str, str],
        columns: list[str],
        *,
        canonical: str,
        aliases: list[str],
    ) -> None:
        if canonical in columns:
            return
        by_token: dict[str, str] = {normalized_token(col): col for col in columns}
        for alias in aliases:
            match = by_token.get(normalized_token(alias))
            if match and match != canonical:
                rename_map[match] = canonical
                return

    rename_map: dict[str, str] = {}
    year_col = detect_year_column(df)
    if year_col != "Year":
        rename_map[year_col] = "Year"

    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="LocationID",
        aliases=["LocationId", "locationid", "location_id"],
    )
    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="MeasureID",
        aliases=["MeasureId", "measureid", "measure_id"],
    )
    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="Data_Value_TypeID",
        aliases=["DataValueTypeID", "data_value_type_id", "datavaluetypeid"],
    )
    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="Data_Value",
        aliases=["DataValue", "data_value", "datavalue"],
    )
    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="Low_Confidence_Limit",
        aliases=["LowConfidenceLimit", "low_confidence_limit", "lowconfidencelimit"],
    )
    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="High_Confidence_Limit",
        aliases=["HighConfidenceLimit", "high_confidence_limit", "highconfidencelimit"],
    )
    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="Data_Value_Footnote_Symbol",
        aliases=["FootnoteSymbol", "data_value_footnote_symbol"],
    )
    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="Data_Value_Footnote",
        aliases=["Footnote", "data_value_footnote"],
    )
    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="Data_Value_Unit",
        aliases=["DataValueUnit", "data_value_unit"],
    )
    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="Data_Value_Type",
        aliases=["DataValueType", "data_value_type"],
    )
    add_alias_rename(
        rename_map,
        list(df.columns),
        canonical="TotalPop18Plus",
        aliases=["TotalPop18plus", "totalpop18plus", "total_pop_18_plus"],
    )

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
        "Data_Value_Footnote_Symbol",
        "Data_Value_Footnote",
        "Low_Confidence_Limit",
        "High_Confidence_Limit",
        "TotalPopulation",
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
        .replace({"": None, "nan": None, "None": None, "NA": None, "N/A": None})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def to_nullable_int(series: pd.Series) -> pd.Series:
    return to_nullable_float(series).astype("Int64")


def to_tract_estimates_df(df: pd.DataFrame) -> pd.DataFrame:
    # df has PLACES canonical columns (Year, LocationID, MeasureID, Data_Value_TypeID, etc.)
    def col_or_empty(name: str) -> pd.Series:
        if name in df.columns:
            return df[name]
        return pd.Series([None] * len(df), index=df.index, dtype="object")

    out = pd.DataFrame(
        {
            "year": pd.to_numeric(df["Year"], errors="coerce").astype("Int64"),
            "locationid": df["LocationID"].astype(str).str.strip().str.zfill(11),
            "measure_id": df["MeasureID"].astype(str),
            "data_value_type_id": df["Data_Value_TypeID"].astype(str),
            "state_abbr": col_or_empty("StateAbbr"),
            "state_desc": col_or_empty("StateDesc"),
            "county_name": col_or_empty("CountyName"),
            "county_fips": col_or_empty("CountyFIPS"),
            "location_name": col_or_empty("LocationName"),
            "data_source": col_or_empty("DataSource"),
            "category": col_or_empty("Category"),
            "category_id": col_or_empty("CategoryID"),
            "measure": col_or_empty("Measure"),
            "data_value_unit": col_or_empty("Data_Value_Unit"),
            "data_value_type": col_or_empty("Data_Value_Type"),
            "data_value": pd.to_numeric(col_or_empty("Data_Value"), errors="coerce"),
            "low_confidence_limit": pd.to_numeric(col_or_empty("Low_Confidence_Limit"), errors="coerce"),
            "high_confidence_limit": pd.to_numeric(col_or_empty("High_Confidence_Limit"), errors="coerce"),
            "total_population": to_nullable_int(col_or_empty("TotalPopulation")),
            "total_pop_18_plus": to_nullable_int(col_or_empty("TotalPop18Plus")),
            "short_question_text": col_or_empty("Short_Question_Text"),
        }
    )

    # geometry: df["Geolocation"] contains EWKT "SRID=4326;POINT (...)"
    def ewkt_to_geom(v: object) -> WKTElement | None:
        if v is None:
            return None
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return None
        if s.upper().startswith("SRID=4326;"):
            s = s.split(";", 1)[1].strip()
        if not s.upper().startswith("POINT"):
            return None
        return WKTElement(s, srid=4326)

    out["geolocation"] = df["Geolocation"].map(ewkt_to_geom)

    # drop rows with missing PK fields
    out = out.dropna(subset=["year", "locationid", "measure_id", "data_value_type_id"])
    out["year"] = out["year"].astype(int)
    return out


def build_prepared_chunk(
    raw_chunk: pd.DataFrame,
    *,
    filter_year: int | None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    chunk = normalize_columns(raw_chunk)
    assert_required_columns(chunk)

    year_series = pd.to_numeric(
        chunk["Year"].astype(str).str.strip(),
        errors="coerce",
    ).astype("Int64")
    valid_year_mask = year_series.notna()
    dropped_invalid_year = int((~valid_year_mask).sum())

    chunk = chunk.loc[valid_year_mask].copy()
    year_series = year_series.loc[valid_year_mask].astype(int)

    year_counts_before_filter = Counter(year_series.tolist())

    if filter_year is not None:
        filter_mask = year_series == filter_year
        chunk = chunk.loc[filter_mask].copy()
        year_series = year_series.loc[filter_mask]

    year_counts_after_filter = Counter(year_series.tolist())
    prepared = to_tract_estimates_df(chunk)

    valid_row_mask = (
        prepared["locationid"].str.fullmatch(r"\d{11}", na=False)
        & prepared["county_fips"].str.fullmatch(r"\d{5}", na=False)
        & prepared["year"].notna()
        & (prepared["measure_id"] != "")
        & (prepared["data_value_type_id"] != "")
    )
    prepared = prepared.loc[valid_row_mask].copy()
    prepared["year"] = prepared["year"].astype(int)

    year_counts_prepared = Counter(prepared["year"].tolist())
    stats: dict[str, object] = {
        "raw_rows": int(len(raw_chunk)),
        "dropped_invalid_year_rows": dropped_invalid_year,
        "rows_after_year_filter": int(len(chunk)),
        "prepared_rows": int(len(prepared)),
        "year_counts_before_filter": year_counts_before_filter,
        "year_counts_after_filter": year_counts_after_filter,
        "year_counts_prepared": year_counts_prepared,
    }
    return prepared, stats


def build_measure_rows(prepared: pd.DataFrame) -> pd.DataFrame:
    if prepared.empty:
        return pd.DataFrame(
            columns=[
                "category_id",
                "category",
                "measure_id",
                "measure",
                "data_value_type_id",
                "data_value_type",
                "unit",
                "short_question_text",
            ]
        )
    measures = prepared[
        [
            "category_id",
            "category",
            "measure_id",
            "measure",
            "data_value_type_id",
            "data_value_type",
            "data_value_unit",
            "short_question_text",
        ]
    ].copy()
    measures = measures.rename(columns={"data_value_unit": "unit"})
    measures = measures.drop_duplicates(subset=["measure_id", "data_value_type_id"])
    return measures


def build_tract_rows(prepared: pd.DataFrame) -> pd.DataFrame:
    if prepared.empty:
        return pd.DataFrame(
            columns=[
                "locationid",
                "state_abbr",
                "state_desc",
                "county_name",
                "county_fips",
                "location_name",
                "total_population",
                "total_pop_18_plus",
                "geolocation",
            ]
        )
    return prepared[
        [
            "locationid",
            "state_abbr",
            "state_desc",
            "county_name",
            "county_fips",
            "location_name",
            "total_population",
            "total_pop_18_plus",
            "geolocation",
        ]
    ].drop_duplicates(subset=["locationid"])


def dataframe_to_records(dataframe: pd.DataFrame, columns: list[str]) -> list[dict[str, object]]:
    safe = dataframe.reindex(columns=columns).copy()
    # Preserve Python objects like WKTElement and allow None (instead of NaN) for nullable fields.
    safe = safe.astype(object).where(pd.notna(safe), None)
    records = safe.to_dict(orient="records")
    if records:
        sample_keys = list(records[0].keys())
        if sample_keys != columns:
            raise RuntimeError(
                f"Invalid record keys. Expected {columns}, got {sample_keys}"
            )
        bad_keys = [key for key in sample_keys if re.search(r"_m\\d+$", str(key))]
        if bad_keys:
            raise RuntimeError(
                f"Flattened/suffixed payload keys detected: {bad_keys}"
            )
    return records


def execute_records_in_batches(
    connection,
    insert_sql: str,
    records: list[dict[str, object]],
    *,
    chunk_size: int,
    debug_facts_payload: bool = False,
) -> None:
    if not records:
        return
    for start in range(0, len(records), chunk_size):
        batch = records[start : start + chunk_size]
        if not batch:
            continue
        if debug_facts_payload:
            print("FACT PAYLOAD SAMPLE KEYS:", list(batch[0].keys()))
            print("FACT PAYLOAD LEN:", len(batch))
        connection.execute(text(insert_sql), batch)


def upsert_dim_measure(connection, measures: pd.DataFrame, chunk_size: int) -> None:
    if measures.empty:
        return

    connection.execute(
        text(
            """
            CREATE TEMP TABLE tmp_dim_measure_tract_ingest (
                category_id text,
                category text,
                measure_id text,
                measure text,
                data_value_type_id text,
                data_value_type text,
                unit text,
                short_question_text text
            ) ON COMMIT DROP;
            """
        )
    )
    measure_columns = [
        "category_id",
        "category",
        "measure_id",
        "measure",
        "data_value_type_id",
        "data_value_type",
        "unit",
        "short_question_text",
    ]
    measure_records = dataframe_to_records(measures, measure_columns)
    execute_records_in_batches(
        connection,
        """
        INSERT INTO tmp_dim_measure_tract_ingest (
            category_id,
            category,
            measure_id,
            measure,
            data_value_type_id,
            data_value_type,
            unit,
            short_question_text
        )
        VALUES (
            :category_id,
            :category,
            :measure_id,
            :measure,
            :data_value_type_id,
            :data_value_type,
            :unit,
            :short_question_text
        );
        """,
        measure_records,
        chunk_size=chunk_size,
    )
    connection.execute(
        text(
            """
            INSERT INTO dim_measure (
                category_id,
                category,
                measure_id,
                measure,
                data_value_type_id,
                data_value_type,
                unit,
                short_question_text
            )
            SELECT
                t.category_id,
                t.category,
                t.measure_id,
                t.measure,
                t.data_value_type_id,
                t.data_value_type,
                t.unit,
                t.short_question_text
            FROM tmp_dim_measure_tract_ingest AS t
            ON CONFLICT (measure_id, data_value_type_id) DO UPDATE SET
                category_id = EXCLUDED.category_id,
                category = EXCLUDED.category,
                measure = EXCLUDED.measure,
                data_value_type = EXCLUDED.data_value_type,
                unit = EXCLUDED.unit,
                short_question_text = EXCLUDED.short_question_text;
            """
        )
    )


def upsert_tract_estimates(
    connection,
    fact_records: list[dict[str, object]],
) -> None:
    if not fact_records:
        return

    tract_estimates = Table(
        "tract_estimates",
        MetaData(schema=PLACES_SCHEMA),
        Column("year", Integer, primary_key=True),
        Column("locationid", String, primary_key=True),
        Column("measure_id", String, primary_key=True),
        Column("data_value_type_id", String, primary_key=True),
        Column("state_abbr", String),
        Column("state_desc", Text),
        Column("county_name", Text),
        Column("county_fips", String),
        Column("location_name", Text),
        Column("data_source", Text),
        Column("category", Text),
        Column("category_id", String),
        Column("measure", Text),
        Column("data_value_unit", Text),
        Column("data_value_type", Text),
        Column("data_value", Float),
        Column("low_confidence_limit", Float),
        Column("high_confidence_limit", Float),
        Column("total_population", BigInteger),
        Column("total_pop_18_plus", BigInteger),
        Column("short_question_text", Text),
        Column("geolocation", Geometry(geometry_type="POINT", srid=4326)),
        schema=PLACES_SCHEMA,
    )
    insert_stmt = pg_insert(tract_estimates)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["year", "locationid", "measure_id", "data_value_type_id"],
        set_={
            "state_abbr": insert_stmt.excluded.state_abbr,
            "state_desc": insert_stmt.excluded.state_desc,
            "county_name": insert_stmt.excluded.county_name,
            "county_fips": insert_stmt.excluded.county_fips,
            "location_name": insert_stmt.excluded.location_name,
            "data_source": insert_stmt.excluded.data_source,
            "category": insert_stmt.excluded.category,
            "category_id": insert_stmt.excluded.category_id,
            "measure": insert_stmt.excluded.measure,
            "data_value_unit": insert_stmt.excluded.data_value_unit,
            "data_value_type": insert_stmt.excluded.data_value_type,
            "data_value": insert_stmt.excluded.data_value,
            "low_confidence_limit": insert_stmt.excluded.low_confidence_limit,
            "high_confidence_limit": insert_stmt.excluded.high_confidence_limit,
            "total_population": insert_stmt.excluded.total_population,
            "total_pop_18_plus": insert_stmt.excluded.total_pop_18_plus,
            "short_question_text": insert_stmt.excluded.short_question_text,
            "geolocation": insert_stmt.excluded.geolocation,
        },
    )
    connection.execute(upsert_stmt, fact_records)


def ensure_etl_places_release_table(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS etl_places_release (
                id bigserial PRIMARY KEY,
                geography text NOT NULL,
                release_label text NOT NULL,
                source_file text NOT NULL,
                years_present jsonb NOT NULL,
                row_count bigint NOT NULL,
                notes text,
                ingested_at timestamptz NOT NULL DEFAULT now()
            );
            """
        )
    )
    # Backward-compatible guard in case an older shape of this table already exists.
    connection.execute(
        text(
            """
            ALTER TABLE etl_places_release
            ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_etl_places_release_geo_label_file
            ON etl_places_release (geography, release_label, source_file);
            """
        )
    )


def record_release_provenance(
    connection,
    *,
    release_label: str,
    source_file: str,
    years_present: list[int],
    row_count: int,
    filter_year: int | None,
) -> None:
    ensure_etl_places_release_table(connection)
    notes = (
        f"filter_year={filter_year}" if filter_year is not None else "filter_year=None"
    )
    connection.execute(
        text(
            """
            INSERT INTO etl_places_release (
                geography,
                release_label,
                source_file,
                years_present,
                row_count,
                notes
            )
            VALUES (
                'tract',
                :release_label,
                :source_file,
                CAST(:years_present AS jsonb),
                :row_count,
                :notes
            )
            ON CONFLICT (geography, release_label, source_file)
            DO UPDATE SET
                years_present = EXCLUDED.years_present,
                row_count = EXCLUDED.row_count,
                notes = EXCLUDED.notes,
                ingested_at = now();
            """
        ),
        {
            "release_label": release_label,
            "source_file": source_file,
            "years_present": json.dumps(years_present),
            "row_count": row_count,
            "notes": notes,
        },
    )


def ingest_places_tract(
    *,
    csv_path: Path,
    dict_path: Path,
    release_label: str,
    filter_year: int | None,
    chunk_size: int,
    dry_run: bool,
) -> None:
    if chunk_size > MAX_CHUNK_SIZE:
        raise ValueError(f"--chunk-size cannot exceed {MAX_CHUNK_SIZE}")
    if chunk_size <= 0:
        raise ValueError("--chunk-size must be > 0")
    if filter_year is not None and filter_year <= 0:
        raise ValueError("--filter-year must be a positive integer")
    if not release_label.strip():
        raise ValueError("--release-label is required")

    delimiter = detect_delimiter(csv_path)
    print(f"Using CSV: {csv_path}")
    print(f"Using dictionary: {dict_path}")
    print(f"Release label: {release_label}")
    print(f"Filter year: {filter_year if filter_year is not None else 'None'}")
    print(f"Chunk size: {chunk_size}")
    print(f"Dry run: {dry_run}")
    print(f"Detected delimiter: {repr(delimiter)}")

    engine = None if dry_run else create_engine(resolve_db_url(), future=True)

    total_rows = 0
    total_rows_after_filter = 0
    total_invalid_year_rows = 0
    total_facts_rows = 0
    total_upsert_attempts = 0

    all_year_counts = Counter()
    filtered_year_counts = Counter()
    prepared_year_counts = Counter()

    unique_tract_ids: set[str] = set()
    unique_measure_keys: set[tuple[str, str]] = set()

    for chunk_index, raw_chunk in enumerate(
        iter_csv_chunks(csv_path, delimiter=delimiter, chunk_size=chunk_size),
        start=1,
    ):
        prepared, stats = build_prepared_chunk(raw_chunk, filter_year=filter_year)
        tract_rows = build_tract_rows(prepared)
        measure_rows = build_measure_rows(prepared)

        total_rows += int(stats["raw_rows"])
        total_invalid_year_rows += int(stats["dropped_invalid_year_rows"])
        total_rows_after_filter += int(stats["rows_after_year_filter"])
        total_facts_rows += int(stats["prepared_rows"])
        total_upsert_attempts += int(stats["prepared_rows"])
        all_year_counts.update(stats["year_counts_before_filter"])
        filtered_year_counts.update(stats["year_counts_after_filter"])
        prepared_year_counts.update(stats["year_counts_prepared"])

        unique_tract_ids.update(tract_rows["locationid"].dropna().astype(str).tolist())
        unique_measure_keys.update(
            list(
                zip(
                    measure_rows["measure_id"].astype(str),
                    measure_rows["data_value_type_id"].astype(str),
                )
            )
        )

        if not dry_run and engine is not None and not prepared.empty:
            records = dataframe_to_records(prepared, TRACT_ESTIMATE_COLUMNS)
            if len(records) > chunk_size:
                raise RuntimeError(
                    f"records payload exceeded chunk_size: {len(records)} > {chunk_size}"
                )
            if chunk_index == 1 and records:
                print(
                    "PAYLOAD_LEN",
                    len(records),
                    "PAYLOAD_KEYS_SAMPLE",
                    list(records[0].keys()),
                )
                print(type(records[0]["geolocation"]), records[0]["geolocation"])
                print(
                    records[0]["total_population"],
                    type(records[0]["total_population"]),
                )
            with engine.begin() as connection:
                upsert_dim_measure(connection, measure_rows, chunk_size)
                upsert_tract_estimates(connection, records)

        chunk_years = dict(sorted(stats["year_counts_after_filter"].items()))
        print(
            f"Chunk {chunk_index}: raw={len(raw_chunk)} "
            f"after_year_filter={stats['rows_after_year_filter']} "
            f"prepared_facts={stats['prepared_rows']} "
            f"year_counts={chunk_years}"
        )

    distinct_years = sorted(all_year_counts.keys())
    years_after_filter = sorted(filtered_year_counts.keys())
    years_prepared = sorted(prepared_year_counts.keys())

    print("\nSummary:")
    print(f"  CSV rows read: {total_rows}")
    print(f"  Rows dropped due to invalid Year: {total_invalid_year_rows}")
    print(f"  Rows after year filter: {total_rows_after_filter}")
    print(f"  Distinct CSV Year values: {distinct_years}")
    print(f"  Rows per CSV Year (before filter): {dict(sorted(all_year_counts.items()))}")
    if filter_year is not None:
        print(f"  Rows per CSV Year (after --filter-year): {dict(sorted(filtered_year_counts.items()))}")
    print(f"  Prepared dim_tract-equivalent rows: {len(unique_tract_ids)}")
    print(f"  Prepared dim_measure rows: {len(unique_measure_keys)}")
    print(f"  Prepared facts rows: {total_facts_rows}")
    print(f"  Rows per year prepared for facts: {dict(sorted(prepared_year_counts.items()))}")
    print(f"  Total inserted/updated attempts: {total_upsert_attempts}")

    if not dry_run and engine is not None:
        with engine.begin() as connection:
            record_release_provenance(
                connection,
                release_label=release_label,
                source_file=csv_path.name,
                years_present=years_after_filter or years_prepared,
                row_count=total_facts_rows,
                filter_year=filter_year,
            )
        print("  Provenance recorded in etl_places_release.")
    else:
        print("  Dry-run: no DB writes and no provenance ledger write.")

    print("\n# Example commands:")
    print('# export DATABASE_URL="postgresql+psycopg://places:places@localhost:5432/places"')
    print(
        "# python scripts/ingest_places_tract.py "
        "--release-label 2024_release_20260219 "
        "--csv ../data/PLACES__Local_Data_for_Better_Health,_Census_Tract_Data_2024_release_20260219.csv "
        "--dict ../data/PLACES_and_500_Cities__Data_Dictionary_20260215.csv"
    )
    print(
        "# python scripts/ingest_places_tract.py "
        "--release-label 2024_release_20260219 "
        "--csv ../data/PLACES__Local_Data_for_Better_Health,_Census_Tract_Data_2024_release_20260219.csv "
        "--dict ../data/PLACES_and_500_Cities__Data_Dictionary_20260215.csv "
        "--filter-year 2022"
    )
    print("\n# Verification snippets:")
    print('# psql "$PSQL_URL" -c "SELECT year, COUNT(*) FROM tract_estimates GROUP BY year ORDER BY year;"')
    print('# psql "$PSQL_URL" -c "SELECT COUNT(DISTINCT locationid) FROM tract_estimates;"')
    print(
        '# psql "$PSQL_URL" -c "SELECT f.year, m.measure_id, COUNT(*) '
        'FROM tract_estimates f JOIN dim_measure m '
        'ON m.measure_id=f.measure_id AND m.data_value_type_id=f.data_value_type_id '
        'GROUP BY f.year, m.measure_id ORDER BY f.year, COUNT(*) DESC LIMIT 20;"'
    )


def main() -> None:
    args = parse_args()
    csv_path = validate_input_path(args.csv, "CSV")
    dict_path = validate_input_path(args.dict_path, "Dictionary CSV")
    ingest_places_tract(
        csv_path=csv_path,
        dict_path=dict_path,
        release_label=args.release_label,
        filter_year=args.filter_year,
        chunk_size=args.chunk_size,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
