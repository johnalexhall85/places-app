from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text


MAX_CHUNK_SIZE = 1000
DEFAULT_SAMPLE_CHUNKS = (1, 10, 100)
MISSING_TOKENS = {"", "na", "n/a", "nan", "none", "null"}


@dataclass(frozen=True)
class FieldSpec:
    db_field: str
    table: str
    required: bool
    canonical_csv: str
    aliases: tuple[str, ...] = ()
    numeric: bool = False
    integer: bool = False


FIELD_SPECS: tuple[FieldSpec, ...] = (
    # fact_estimate_county
    FieldSpec("year", "fact_estimate_county", True, "Year", numeric=True, integer=True),
    FieldSpec(
        "location_id",
        "fact_estimate_county",
        True,
        "LocationID",
        aliases=("locationid", "Location_Id"),
    ),
    FieldSpec(
        "measure_id",
        "fact_estimate_county",
        True,
        "MeasureID",
        aliases=("MeasureId", "measure_id"),
    ),
    FieldSpec(
        "data_value_type_id",
        "fact_estimate_county",
        True,
        "Data_Value_TypeID",
        aliases=("DataValueTypeID", "data_value_type_id", "Data_Value_Type_Id"),
    ),
    FieldSpec(
        "data_value",
        "fact_estimate_county",
        False,
        "Data_Value",
        aliases=("DataValue", "data_value"),
        numeric=True,
    ),
    FieldSpec(
        "low_confidence_limit",
        "fact_estimate_county",
        False,
        "Low_Confidence_Limit",
        aliases=("LowConfidenceLimit", "low_confidence_limit"),
        numeric=True,
    ),
    FieldSpec(
        "high_confidence_limit",
        "fact_estimate_county",
        False,
        "High_Confidence_Limit",
        aliases=("HighConfidenceLimit", "high_confidence_limit"),
        numeric=True,
    ),
    FieldSpec(
        "footnote_symbol",
        "fact_estimate_county",
        False,
        "Data_Value_Footnote_Symbol",
        aliases=("FootnoteSymbol", "data_value_footnote_symbol"),
    ),
    FieldSpec(
        "footnote",
        "fact_estimate_county",
        False,
        "Data_Value_Footnote",
        aliases=("Footnote", "data_value_footnote"),
    ),
    # dim_county
    FieldSpec("state_abbr", "dim_county", True, "StateAbbr", aliases=("state_abbr",)),
    FieldSpec("state_desc", "dim_county", True, "StateDesc", aliases=("state_desc",)),
    FieldSpec(
        "county_name",
        "dim_county",
        True,
        "LocationName",
        aliases=("CountyName", "county_name"),
    ),
    FieldSpec(
        "total_population",
        "dim_county",
        False,
        "TotalPopulation",
        aliases=("total_population",),
        numeric=True,
        integer=True,
    ),
    FieldSpec(
        "total_pop_18_plus",
        "dim_county",
        False,
        "TotalPop18plus",
        aliases=("total_pop_18_plus", "TotalPop18Plus"),
        numeric=True,
        integer=True,
    ),
    FieldSpec(
        "geolocation",
        "dim_county",
        False,
        "Geolocation",
        aliases=("GeoLocation", "geolocation"),
    ),
    # dim_measure
    FieldSpec(
        "category_id",
        "dim_measure",
        True,
        "CategoryID",
        aliases=("category_id",),
    ),
    FieldSpec("category", "dim_measure", True, "Category", aliases=("category",)),
    FieldSpec("measure", "dim_measure", True, "Measure", aliases=("measure",)),
    FieldSpec(
        "data_value_type",
        "dim_measure",
        True,
        "Data_Value_Type",
        aliases=("DataValueType", "data_value_type"),
    ),
    FieldSpec(
        "unit",
        "dim_measure",
        False,
        "Data_Value_Unit",
        aliases=("DataValueUnit", "unit"),
    ),
    FieldSpec(
        "short_question_text",
        "dim_measure",
        False,
        "Short_Question_Text",
        aliases=("short_question_text", "ShortQuestionText"),
    ),
)


NUMERIC_DB_FIELDS = tuple(spec.db_field for spec in FIELD_SPECS if spec.numeric)
REQUIRED_DB_FIELDS = tuple(spec.db_field for spec in FIELD_SPECS if spec.required)
DB_FIELD_TO_SPEC = {spec.db_field: spec for spec in FIELD_SPECS}

COUNTY_DIM_FIELDS = [
    "location_id",
    "state_abbr",
    "state_desc",
    "county_name",
    "total_population",
    "total_pop_18_plus",
    "geolocation_ewkt",
]
MEASURE_DIM_FIELDS = [
    "category_id",
    "category",
    "measure_id",
    "measure",
    "data_value_type_id",
    "data_value_type",
    "unit",
    "short_question_text",
]
FACT_FIELDS = [
    "year",
    "location_id",
    "measure_id",
    "data_value_type_id",
    "data_value",
    "low_confidence_limit",
    "high_confidence_limit",
    "footnote_symbol",
    "footnote",
]


def normalize_column_name(value: str) -> str:
    if value is None:
        return ""
    cleaned = str(value).lstrip("\ufeff").strip().lower()
    return re.sub(r"[^a-z0-9]+", "", cleaned)


def clean_text_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .replace({r"^\s*$": pd.NA}, regex=True)
        .replace(
            {
                "nan": pd.NA,
                "NaN": pd.NA,
                "None": pd.NA,
                "none": pd.NA,
                "NULL": pd.NA,
                "null": pd.NA,
                "N/A": pd.NA,
                "n/a": pd.NA,
                "NA": pd.NA,
                "na": pd.NA,
            }
        )
    )
    return cleaned


def parse_numeric_series(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    lowered = cleaned.str.lower()
    missing_mask = lowered.isin(MISSING_TOKENS)
    parsed = pd.to_numeric(cleaned.mask(missing_mask, pd.NA), errors="coerce")
    failure_mask = (~missing_mask) & parsed.isna()
    return parsed, missing_mask, failure_mask


def detect_encoding(path: Path) -> str:
    with path.open("rb") as handle:
        prefix = handle.read(4)
    if prefix.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if prefix.startswith(b"\xff\xfe") or prefix.startswith(b"\xfe\xff"):
        return "utf-16"

    with path.open("rb") as handle:
        sample = handle.read(65536)
    try:
        sample.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def detect_delimiter(path: Path, encoding: str) -> str:
    with path.open("r", encoding=encoding, newline="") as handle:
        sample = handle.read(65536)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def iter_csv_chunks(
    csv_path: Path,
    *,
    encoding: str,
    delimiter: str,
    chunksize: int = MAX_CHUNK_SIZE,
):
    if chunksize > MAX_CHUNK_SIZE:
        raise ValueError(f"chunksize cannot exceed {MAX_CHUNK_SIZE}")
    yield from pd.read_csv(
        csv_path,
        dtype=str,
        sep=delimiter,
        encoding=encoding,
        chunksize=chunksize,
        engine="python",
    )


def load_dictionary_summary(dict_path: Path) -> dict[str, Any]:
    if not dict_path.exists():
        return {
            "exists": False,
            "path": str(dict_path),
            "encoding": None,
            "delimiter": None,
            "row_count": 0,
            "columns": [],
            "measure_id_count": 0,
            "measure_ids": set(),
        }

    encoding = detect_encoding(dict_path)
    delimiter = detect_delimiter(dict_path, encoding)

    row_count = 0
    columns: list[str] = []
    measure_ids: set[str] = set()
    measure_id_col: str | None = None

    for chunk in iter_csv_chunks(
        dict_path,
        encoding=encoding,
        delimiter=delimiter,
        chunksize=MAX_CHUNK_SIZE,
    ):
        row_count += len(chunk)
        if not columns:
            columns = [str(c) for c in chunk.columns]
            normalized = {normalize_column_name(c): c for c in columns}
            measure_id_col = normalized.get("measureid")
        if measure_id_col and measure_id_col in chunk.columns:
            values = clean_text_series(chunk[measure_id_col]).dropna().astype(str)
            measure_ids.update(values.tolist())

    return {
        "exists": True,
        "path": str(dict_path),
        "encoding": encoding,
        "delimiter": delimiter,
        "row_count": row_count,
        "columns": columns,
        "measure_id_count": len(measure_ids),
        "measure_ids": measure_ids,
    }


def _candidate_names_for_field(spec: FieldSpec, dictionary_columns: list[str]) -> list[str]:
    names = [spec.canonical_csv, *spec.aliases]
    dict_normalized = {normalize_column_name(col): col for col in dictionary_columns}

    # Tie mapping hints to dictionary wording where applicable.
    if spec.db_field == "measure_id" and "measureid" in dict_normalized:
        names.append(dict_normalized["measureid"])
    if spec.db_field == "category_id" and "categoryid" in dict_normalized:
        names.append(dict_normalized["categoryid"])
    if spec.db_field == "category" and "categoryname" in dict_normalized:
        names.append(dict_normalized["categoryname"])
    if spec.db_field == "measure" and "measurefullname" in dict_normalized:
        names.append(dict_normalized["measurefullname"])

    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        normalized = normalize_column_name(name)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def build_column_mapping(raw_columns: list[str], dictionary_columns: list[str]) -> dict[str, Any]:
    normalized_to_raw: dict[str, list[str]] = defaultdict(list)
    trim_issues: list[str] = []

    for raw in raw_columns:
        if raw != str(raw).strip() or str(raw).startswith("\ufeff"):
            trim_issues.append(raw)
        normalized_to_raw[normalize_column_name(raw)].append(raw)

    duplicate_normalized = {
        normalized: values
        for normalized, values in normalized_to_raw.items()
        if len(values) > 1
    }

    db_to_csv: dict[str, str | None] = {}
    mapping_reasons: dict[str, str] = {}
    ambiguous_mapping: dict[str, list[str]] = {}
    used_raw_columns: set[str] = set()

    for spec in FIELD_SPECS:
        mapped_column: str | None = None
        reason = "not found"
        for candidate_norm in _candidate_names_for_field(spec, dictionary_columns):
            raw_matches = normalized_to_raw.get(candidate_norm, [])
            if raw_matches:
                mapped_column = raw_matches[0]
                used_raw_columns.add(mapped_column)
                if len(raw_matches) > 1:
                    ambiguous_mapping[spec.db_field] = raw_matches
                    reason = (
                        f"matched normalized '{candidate_norm}' with duplicates; "
                        f"using first: {mapped_column}"
                    )
                else:
                    reason = f"matched normalized '{candidate_norm}'"
                break
        db_to_csv[spec.db_field] = mapped_column
        mapping_reasons[spec.db_field] = reason

    csv_to_db: dict[str, list[str]] = defaultdict(list)
    for db_field, raw_col in db_to_csv.items():
        if raw_col:
            csv_to_db[raw_col].append(db_field)

    missing_required = [
        spec.db_field
        for spec in FIELD_SPECS
        if spec.required and not db_to_csv.get(spec.db_field)
    ]

    ignored_columns = [col for col in raw_columns if col not in used_raw_columns]

    return {
        "db_to_csv": db_to_csv,
        "csv_to_db": dict(csv_to_db),
        "mapping_reasons": mapping_reasons,
        "missing_required": missing_required,
        "ignored_columns": ignored_columns,
        "trim_issues": trim_issues,
        "duplicate_normalized": duplicate_normalized,
    }


def _series_or_missing(chunk: pd.DataFrame, mapped_column: str | None) -> pd.Series:
    if mapped_column and mapped_column in chunk.columns:
        return chunk[mapped_column]
    return pd.Series([pd.NA] * len(chunk), index=chunk.index, dtype="object")


def normalize_chunk(chunk: pd.DataFrame, db_to_csv: dict[str, str | None]) -> pd.DataFrame:
    normalized = pd.DataFrame(index=chunk.index)

    for spec in FIELD_SPECS:
        source = _series_or_missing(chunk, db_to_csv.get(spec.db_field))
        if spec.numeric:
            parsed, _, _ = parse_numeric_series(source)
            if spec.integer:
                normalized[spec.db_field] = parsed.astype("Int64")
            else:
                normalized[spec.db_field] = parsed
        else:
            normalized[spec.db_field] = clean_text_series(source)

    normalized["state_abbr"] = clean_text_series(normalized["state_abbr"]).str.upper()
    normalized["location_id"] = clean_text_series(normalized["location_id"])
    normalized["measure_id"] = clean_text_series(normalized["measure_id"])
    normalized["data_value_type_id"] = clean_text_series(normalized["data_value_type_id"])
    normalized["county_name"] = clean_text_series(normalized["county_name"])

    geolocation = clean_text_series(normalized["geolocation"])
    normalized["geolocation_ewkt"] = geolocation.apply(
        lambda value: None
        if value is pd.NA or value is None
        else (f"SRID=4326;{value}" if str(value).upper().startswith("POINT") else None)
    )

    return normalized


def filter_ingest_ready_rows(normalized: pd.DataFrame) -> pd.DataFrame:
    mask = (
        normalized["year"].notna()
        & normalized["location_id"].str.fullmatch(r"\d{5}", na=False)
        & normalized["state_abbr"].notna()
        & normalized["state_desc"].notna()
        & normalized["county_name"].notna()
        & normalized["measure_id"].notna()
        & normalized["data_value_type_id"].notna()
        & normalized["category_id"].notna()
        & normalized["category"].notna()
        & normalized["measure"].notna()
        & normalized["data_value_type"].notna()
    )

    prepared = normalized.loc[mask].copy()
    prepared["year"] = prepared["year"].astype(int)
    return prepared


def build_ingest_frames(prepared: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    counties = (
        prepared[COUNTY_DIM_FIELDS]
        .drop_duplicates(subset=["location_id"])
        .reset_index(drop=True)
    )
    measures = (
        prepared[MEASURE_DIM_FIELDS]
        .drop_duplicates(subset=["measure_id", "data_value_type_id"])
        .reset_index(drop=True)
    )
    facts = prepared[FACT_FIELDS].reset_index(drop=True)
    return counties, measures, facts


def _dataframe_for_sql(dataframe: pd.DataFrame) -> pd.DataFrame:
    return dataframe.astype(object).where(pd.notna(dataframe), None)


def _upsert_counties(conn, counties: pd.DataFrame) -> None:
    if counties.empty:
        return

    conn.execute(
        text(
            """
            CREATE TEMP TABLE tmp_dim_county (
                location_id text,
                state_abbr text,
                state_desc text,
                county_name text,
                total_population bigint,
                total_pop_18_plus bigint,
                geom_ewkt text
            ) ON COMMIT DROP;
            """
        )
    )
    _dataframe_for_sql(counties).to_sql(
        "tmp_dim_county",
        conn,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=MAX_CHUNK_SIZE,
    )
    conn.execute(
        text(
            """
            INSERT INTO dim_county (
                location_id,
                state_abbr,
                state_desc,
                county_name,
                total_population,
                total_pop_18_plus,
                geom
            )
            SELECT
                t.location_id,
                t.state_abbr,
                t.state_desc,
                t.county_name,
                t.total_population,
                t.total_pop_18_plus,
                CASE
                    WHEN t.geom_ewkt IS NULL THEN NULL
                    ELSE ST_GeomFromEWKT(t.geom_ewkt)::geometry(Point,4326)
                END
            FROM tmp_dim_county AS t
            ON CONFLICT (location_id) DO UPDATE SET
                state_abbr = EXCLUDED.state_abbr,
                state_desc = EXCLUDED.state_desc,
                county_name = EXCLUDED.county_name,
                total_population = EXCLUDED.total_population,
                total_pop_18_plus = EXCLUDED.total_pop_18_plus,
                geom = EXCLUDED.geom;
            """
        )
    )


def _upsert_measures(conn, measures: pd.DataFrame) -> None:
    if measures.empty:
        return

    conn.execute(
        text(
            """
            CREATE TEMP TABLE tmp_dim_measure (
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
    _dataframe_for_sql(measures).to_sql(
        "tmp_dim_measure",
        conn,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=MAX_CHUNK_SIZE,
    )
    conn.execute(
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
            FROM tmp_dim_measure AS t
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


def _upsert_facts(conn, facts: pd.DataFrame) -> None:
    if facts.empty:
        return

    conn.execute(
        text(
            """
            CREATE TEMP TABLE tmp_fact_estimate_county (
                year int,
                location_id text,
                measure_id text,
                data_value_type_id text,
                data_value double precision,
                low_confidence_limit double precision,
                high_confidence_limit double precision,
                footnote_symbol text,
                footnote text
            ) ON COMMIT DROP;
            """
        )
    )
    _dataframe_for_sql(facts).to_sql(
        "tmp_fact_estimate_county",
        conn,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=MAX_CHUNK_SIZE,
    )
    conn.execute(
        text(
            """
            INSERT INTO fact_estimate_county (
                year,
                location_id,
                measure_dim_id,
                data_value,
                low_confidence_limit,
                high_confidence_limit,
                footnote_symbol,
                footnote
            )
            SELECT
                f.year,
                f.location_id,
                m.id AS measure_dim_id,
                f.data_value,
                f.low_confidence_limit,
                f.high_confidence_limit,
                f.footnote_symbol,
                f.footnote
            FROM tmp_fact_estimate_county AS f
            JOIN dim_measure AS m
              ON m.measure_id = f.measure_id
             AND m.data_value_type_id = f.data_value_type_id
            ON CONFLICT (year, location_id, measure_dim_id) DO UPDATE SET
                data_value = EXCLUDED.data_value,
                low_confidence_limit = EXCLUDED.low_confidence_limit,
                high_confidence_limit = EXCLUDED.high_confidence_limit,
                footnote_symbol = EXCLUDED.footnote_symbol,
                footnote = EXCLUDED.footnote;
            """
        )
    )


def run_county_ingestion(
    csv_path: Path,
    *,
    encoding: str,
    delimiter: str,
    db_to_csv: dict[str, str | None],
    chunksize: int = MAX_CHUNK_SIZE,
) -> dict[str, Any]:
    if chunksize > MAX_CHUNK_SIZE:
        raise ValueError(f"chunksize cannot exceed {MAX_CHUNK_SIZE}")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")

    engine = create_engine(db_url, future=True)
    summary = {
        "chunks_read": 0,
        "rows_read": 0,
        "rows_ingest_ready": 0,
        "dim_county_rows_upserted": 0,
        "dim_measure_rows_upserted": 0,
        "fact_rows_upserted": 0,
    }

    for chunk_index, raw_chunk in enumerate(
        iter_csv_chunks(
            csv_path,
            encoding=encoding,
            delimiter=delimiter,
            chunksize=chunksize,
        ),
        start=1,
    ):
        normalized = normalize_chunk(raw_chunk, db_to_csv)
        prepared = filter_ingest_ready_rows(normalized)
        counties, measures, facts = build_ingest_frames(prepared)

        with engine.begin() as conn:
            _upsert_counties(conn, counties)
            _upsert_measures(conn, measures)
            _upsert_facts(conn, facts)

        summary["chunks_read"] = chunk_index
        summary["rows_read"] += len(raw_chunk)
        summary["rows_ingest_ready"] += len(prepared)
        summary["dim_county_rows_upserted"] += len(counties)
        summary["dim_measure_rows_upserted"] += len(measures)
        summary["fact_rows_upserted"] += len(facts)

        print(
            f"write chunk {chunk_index}: raw={len(raw_chunk)} "
            f"ingest_ready={len(prepared)} county={len(counties)} "
            f"measure={len(measures)} fact={len(facts)}"
        )

    return summary


def _safe_value(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)
    if pd.isna(value):
        return None
    return value


def _sample_record(row: pd.Series) -> dict[str, Any]:
    record = {col: _safe_value(row[col]) for col in row.index if col != "geolocation_ewkt"}
    record["fact_unique_key"] = (
        f"{record.get('year')}|{record.get('location_id')}|"
        f"{record.get('measure_id')}|{record.get('data_value_type_id')}"
    )
    record["measure_unique_key"] = (
        f"{record.get('measure_id')}|{record.get('data_value_type_id')}"
    )
    return record


def run_preflight(
    *,
    csv_path: Path,
    dict_path: Path,
    expected_year: int,
    sample_rows: int,
) -> dict[str, Any]:
    csv_size_bytes = csv_path.stat().st_size
    csv_encoding = detect_encoding(csv_path)
    csv_delimiter = detect_delimiter(csv_path, csv_encoding)
    dictionary = load_dictionary_summary(dict_path)

    summary: dict[str, Any] = {
        "status": "ok",
        "csv": {
            "path": str(csv_path),
            "size_bytes": csv_size_bytes,
            "size_mb": round(csv_size_bytes / (1024 * 1024), 2),
            "encoding": csv_encoding,
            "delimiter": csv_delimiter,
            "chunksize": MAX_CHUNK_SIZE,
            "total_rows": 0,
        },
        "data_dictionary": {
            "path": dictionary["path"],
            "exists": dictionary["exists"],
            "encoding": dictionary["encoding"],
            "delimiter": dictionary["delimiter"],
            "row_count": dictionary["row_count"],
            "columns": dictionary["columns"],
            "measure_id_count": dictionary["measure_id_count"],
        },
        "column_report": {},
        "mapping_report": {},
        "year_report": {
            "expected_year": expected_year,
            "year_column_present": False,
            "distinct_years": [],
            "all_rows_match_expected_year": None,
        },
        "geography_report": {
            "location_type_columns": {},
            "location_id_length_counts": {},
            "location_id_non_digit_count": 0,
            "county_only_by_location_id_length": None,
        },
        "type_coercion_report": {},
        "samples": {
            "sample_rows_limit": sample_rows,
            "first_normalized_rows": [],
            "later_chunk_rows": [],
        },
        "dictionary_validation": {
            "csv_measure_id_count": 0,
            "measure_ids_missing_from_dictionary_count": 0,
            "measure_ids_missing_from_dictionary_sample": [],
        },
        "db_model_report": {
            "table": "fact_estimate_county",
            "fact_fields": FACT_FIELDS,
            "dimension_fields": {
                "dim_county": COUNTY_DIM_FIELDS,
                "dim_measure": MEASURE_DIM_FIELDS,
            },
            "unique_keys": {
                "dim_measure": ["measure_id", "data_value_type_id"],
                "fact_estimate_county": ["year", "location_id", "measure_dim_id"],
                "fact_natural_key_before_measure_join": [
                    "year",
                    "location_id",
                    "measure_id",
                    "data_value_type_id",
                ],
            },
        },
    }

    mapping: dict[str, Any] | None = None
    numeric_stats = {
        db_field: {"rows": 0, "missing": 0, "non_missing": 0, "parse_failures": 0}
        for db_field in NUMERIC_DB_FIELDS
    }
    year_counter: Counter[int] = Counter()
    location_id_lengths: Counter[int] = Counter()
    location_id_non_digit_count = 0
    location_type_values: dict[str, set[str]] = defaultdict(set)
    csv_measure_ids: set[str] = set()
    later_chunk_index_to_row: dict[int, dict[str, Any]] = {}

    for chunk_index, chunk in enumerate(
        iter_csv_chunks(
            csv_path,
            encoding=csv_encoding,
            delimiter=csv_delimiter,
            chunksize=MAX_CHUNK_SIZE,
        ),
        start=1,
    ):
        summary["csv"]["total_rows"] += len(chunk)

        if mapping is None:
            raw_columns = [str(c) for c in chunk.columns]
            mapping = build_column_mapping(raw_columns, dictionary["columns"])
            normalized_columns = [normalize_column_name(c) for c in raw_columns]
            summary["column_report"] = {
                "raw_columns": raw_columns,
                "normalized_columns": normalized_columns,
                "suspicious": {
                    "trim_issues": mapping["trim_issues"],
                    "duplicate_names_after_normalization": mapping["duplicate_normalized"],
                },
            }
            summary["mapping_report"] = {
                "db_field_to_csv_column": mapping["db_to_csv"],
                "csv_column_to_db_fields": mapping["csv_to_db"],
                "mapping_reasons": mapping["mapping_reasons"],
                "required_db_fields": [
                    {
                        "db_field": spec.db_field,
                        "table": spec.table,
                        "required": spec.required,
                        "mapped_csv_column": mapping["db_to_csv"].get(spec.db_field),
                    }
                    for spec in FIELD_SPECS
                ],
                "missing_required_db_fields": mapping["missing_required"],
                "ignored_csv_columns": mapping["ignored_columns"],
            }

        assert mapping is not None

        normalized = normalize_chunk(chunk, mapping["db_to_csv"])
        prepared = filter_ingest_ready_rows(normalized)

        for db_field in NUMERIC_DB_FIELDS:
            source_col = mapping["db_to_csv"].get(db_field)
            raw_series = _series_or_missing(chunk, source_col)
            _, missing_mask, failure_mask = parse_numeric_series(raw_series)
            stats = numeric_stats[db_field]
            stats["rows"] += len(raw_series)
            stats["missing"] += int(missing_mask.sum())
            stats["non_missing"] += int((~missing_mask).sum())
            stats["parse_failures"] += int(failure_mask.sum())

        if mapping["db_to_csv"].get("year"):
            summary["year_report"]["year_column_present"] = True
            years = normalized["year"].dropna().astype(int)
            year_counter.update(years.tolist())

        location_ids = clean_text_series(normalized["location_id"]).dropna().astype(str)
        if not location_ids.empty:
            location_id_lengths.update(location_ids.str.len().tolist())
            location_id_non_digit_count += int((~location_ids.str.fullmatch(r"\d+")).sum())

        for raw_col in chunk.columns:
            normalized_col = normalize_column_name(str(raw_col))
            if normalized_col in {
                "locationtype",
                "locationtypeid",
                "geographiclevel",
                "geographylevel",
                "geographictype",
                "locationdesc",
            }:
                values = clean_text_series(chunk[raw_col]).dropna().astype(str)
                for value in values.head(MAX_CHUNK_SIZE):
                    if len(location_type_values[raw_col]) < 25:
                        location_type_values[raw_col].add(value)

        measure_ids = clean_text_series(normalized["measure_id"]).dropna().astype(str)
        csv_measure_ids.update(measure_ids.tolist())

        current_samples = summary["samples"]["first_normalized_rows"]
        needed = sample_rows - len(current_samples)
        if needed > 0 and not prepared.empty:
            for _, row in prepared.head(needed).iterrows():
                current_samples.append(_sample_record(row))

        if chunk_index in DEFAULT_SAMPLE_CHUNKS and chunk_index not in later_chunk_index_to_row:
            source_row = prepared.iloc[0] if not prepared.empty else normalized.iloc[0]
            later_chunk_index_to_row[chunk_index] = _sample_record(source_row)

    if mapping is None:
        raise RuntimeError("CSV appears to be empty; no header/rows were read.")

    distinct_years = sorted(year_counter.keys())
    summary["year_report"]["distinct_years"] = distinct_years
    if distinct_years:
        summary["year_report"]["all_rows_match_expected_year"] = (
            len(distinct_years) == 1 and distinct_years[0] == expected_year
        )
    else:
        summary["year_report"]["all_rows_match_expected_year"] = False

    summary["geography_report"]["location_type_columns"] = {
        key: sorted(values) for key, values in location_type_values.items()
    }
    summary["geography_report"]["location_id_length_counts"] = {
        str(length): count for length, count in sorted(location_id_lengths.items())
    }
    summary["geography_report"]["location_id_non_digit_count"] = location_id_non_digit_count
    total_with_location_id = sum(location_id_lengths.values())
    if total_with_location_id > 0:
        summary["geography_report"]["county_only_by_location_id_length"] = (
            set(location_id_lengths.keys()) == {5}
            and location_id_non_digit_count == 0
        )

    type_report: dict[str, Any] = {}
    warnings: list[str] = []
    for db_field, stats in numeric_stats.items():
        non_missing = stats["non_missing"]
        failure_rate = (
            (stats["parse_failures"] / non_missing) if non_missing else 0.0
        )
        type_report[db_field] = {
            "parse_as": "int" if DB_FIELD_TO_SPEC[db_field].integer else "float",
            "rows_seen": stats["rows"],
            "missing_values": stats["missing"],
            "non_missing_values": non_missing,
            "parse_failures": stats["parse_failures"],
            "parse_failure_rate": round(failure_rate, 6),
            "missing_tokens_handled_as_null": sorted(MISSING_TOKENS),
        }
        if failure_rate > 0.01:
            warnings.append(
                f"{db_field} parse failure rate {failure_rate:.2%} exceeds 1%"
            )
    type_report["warnings"] = warnings
    summary["type_coercion_report"] = type_report

    summary["samples"]["later_chunk_rows"] = [
        {"chunk_index": idx, "row": later_chunk_index_to_row[idx]}
        for idx in DEFAULT_SAMPLE_CHUNKS
        if idx in later_chunk_index_to_row
    ]

    missing_measure_ids = set()
    if dictionary["measure_ids"]:
        missing_measure_ids = csv_measure_ids - dictionary["measure_ids"]
    summary["dictionary_validation"] = {
        "csv_measure_id_count": len(csv_measure_ids),
        "measure_ids_missing_from_dictionary_count": len(missing_measure_ids),
        "measure_ids_missing_from_dictionary_sample": sorted(list(missing_measure_ids))[:25],
    }

    if mapping["missing_required"]:
        summary["status"] = "error"
        summary["error"] = (
            "Critical required fields are missing from CSV mapping: "
            + ", ".join(mapping["missing_required"])
        )

    summary["mapping"] = mapping
    return summary


def print_preflight_text(summary: dict[str, Any]) -> None:
    csv_info = summary["csv"]
    print("=== A) CSV BASICS ===")
    print(f"file: {csv_info['path']}")
    print(f"size_bytes: {csv_info['size_bytes']} (size_mb={csv_info['size_mb']})")
    print(f"encoding: {csv_info['encoding']}")
    print(f"delimiter: {repr(csv_info['delimiter'])}")
    print(f"chunksize: {csv_info['chunksize']}")
    print(f"total_rows: {csv_info['total_rows']}")
    year_report = summary["year_report"]
    print(f"year_column_present: {year_report['year_column_present']}")
    print(f"distinct_years: {year_report['distinct_years']}")
    print(
        "all_rows_match_expected_year"
        f" ({year_report['expected_year']}): {year_report['all_rows_match_expected_year']}"
    )
    geo = summary["geography_report"]
    print(f"location_type_columns_distinct_values: {geo['location_type_columns']}")
    print(f"location_id_length_counts: {geo['location_id_length_counts']}")
    print(f"location_id_non_digit_count: {geo['location_id_non_digit_count']}")
    print(f"county_only_by_location_id_length: {geo['county_only_by_location_id_length']}")

    print("\n=== B) COLUMN REPORT ===")
    columns = summary["column_report"]
    print("raw_columns:")
    for column in columns.get("raw_columns", []):
        print(f"  - {column}")
    print("normalized_columns:")
    for column in columns.get("normalized_columns", []):
        print(f"  - {column}")
    suspicious = columns.get("suspicious", {})
    print(f"suspicious_trim_issues: {suspicious.get('trim_issues', [])}")
    print(
        "duplicate_names_after_normalization: "
        f"{suspicious.get('duplicate_names_after_normalization', {})}"
    )

    print("\n=== C) MAPPING REPORT ===")
    mapping = summary["mapping_report"]
    print("required_db_fields:")
    for item in mapping.get("required_db_fields", []):
        req_label = "required" if item["required"] else "optional"
        mapped = item["mapped_csv_column"] if item["mapped_csv_column"] else "MISSING"
        print(f"  - {item['db_field']} ({item['table']}, {req_label}) -> {mapped}")
    print(f"missing_required_db_fields: {mapping.get('missing_required_db_fields', [])}")
    print("csv_column_to_db_fields:")
    for csv_col, db_fields in mapping.get("csv_column_to_db_fields", {}).items():
        print(f"  - {csv_col} -> {db_fields}")
    print(f"ignored_csv_columns: {mapping.get('ignored_csv_columns', [])}")

    print("\n=== D) TYPE COERCION PREVIEW ===")
    type_report = summary["type_coercion_report"]
    for db_field in NUMERIC_DB_FIELDS:
        stats = type_report.get(db_field, {})
        if not stats:
            continue
        print(
            f"  - {db_field}: parse_as={stats['parse_as']} "
            f"rows={stats['rows_seen']} missing={stats['missing_values']} "
            f"non_missing={stats['non_missing_values']} "
            f"failures={stats['parse_failures']} "
            f"failure_rate={stats['parse_failure_rate']:.2%}"
        )
    if type_report.get("warnings"):
        print("warnings:")
        for warning in type_report["warnings"]:
            print(f"  - {warning}")
    else:
        print("warnings: []")
    print(f"missing_tokens_handled_as_null: {sorted(MISSING_TOKENS)}")

    print("\n=== E) SAMPLE ROWS ===")
    print("first_normalized_rows:")
    for row in summary["samples"]["first_normalized_rows"]:
        print(f"  - {json.dumps(row, default=str)}")
    print("later_chunk_rows:")
    for item in summary["samples"]["later_chunk_rows"]:
        print(f"  - chunk={item['chunk_index']} row={json.dumps(item['row'], default=str)}")

    print("\n=== DICTIONARY VALIDATION ===")
    dictionary_info = summary["data_dictionary"]
    print(f"dictionary_path: {dictionary_info['path']}")
    print(f"dictionary_exists: {dictionary_info['exists']}")
    print(f"dictionary_row_count: {dictionary_info['row_count']}")
    print(f"dictionary_measure_id_count: {dictionary_info['measure_id_count']}")
    dict_validation = summary["dictionary_validation"]
    print(f"csv_measure_id_count: {dict_validation['csv_measure_id_count']}")
    print(
        "measure_ids_missing_from_dictionary_count: "
        f"{dict_validation['measure_ids_missing_from_dictionary_count']}"
    )
    print(
        "measure_ids_missing_from_dictionary_sample: "
        f"{dict_validation['measure_ids_missing_from_dictionary_sample']}"
    )

