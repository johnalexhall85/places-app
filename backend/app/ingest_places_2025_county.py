import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text

MAX_CHUNK_SIZE = 1000
DEFAULT_DICT_PATH = "../data/PLACES_and_500_Cities__Data_Dictionary_20260215.csv"


def get_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(db_url, future=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest PLACES county CSV into dim_county/dim_measure/fact_estimate_county."
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to county release CSV.",
    )
    parser.add_argument(
        "--dict",
        dest="dict_path",
        default=DEFAULT_DICT_PATH,
        help=f"Optional data dictionary CSV path (default: {DEFAULT_DICT_PATH}).",
    )
    parser.add_argument(
        "--release-label",
        required=True,
        help="Release provenance label, e.g. 2023_release_20260219.",
    )
    parser.add_argument(
        "--filter-year",
        type=int,
        default=None,
        help="Optional estimate year filter. If set, only CSV rows with Year == filter-year are ingested.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help=(
            "DEPRECATED legacy year override input. "
            "Blocked by default unless --force-override-year is provided."
        ),
    )
    parser.add_argument(
        "--force-override-year",
        action="store_true",
        help=(
            "Safety bypass for deprecated --year handling. "
            "Use only if you intentionally want --year interpreted as --filter-year."
        ),
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=MAX_CHUNK_SIZE,
        help=f"Chunk size for to_sql bulk operations (max {MAX_CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run transforms and print counts only. Do not write to DB.",
    )
    return parser.parse_args()


def validate_input_path(path_value: str, label: str) -> Path:
    path = Path(path_value).expanduser()
    if path.name.endswith(":Zone.Identifier"):
        raise ValueError(f"{label} cannot be a Windows Zone.Identifier file: {path}")
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    if not path.is_file():
        raise ValueError(f"{label} is not a file: {path}")
    return path

def read_places_csv(csv_path: str) -> pd.DataFrame:
    """
    Read county CSV with delimiter auto-detection.
    Use python engine to avoid parser issues in mixed release files.
    """
    df = pd.read_csv(
        csv_path,
        sep=None,
        quotechar='"',
        dtype=str,
        engine="python",
    )
    # strip BOM / whitespace from headers
    df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
    return df


def detect_year_column(df: pd.DataFrame) -> str:
    matches = [col for col in df.columns if col.strip().lower() == "year"]
    if not matches:
        raise RuntimeError("CSV is missing a Year column (case-insensitive check).")
    if len(matches) > 1:
        raise RuntimeError(f"CSV has multiple Year-like columns: {matches}")
    return matches[0]


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Unify known column name variants into one canonical set used by the loader.
    """
    rename_map = {}

    # Common variants we’ve seen in your runs
    if "MeasureId" in df.columns and "MeasureID" not in df.columns:
        rename_map["MeasureId"] = "MeasureID"

    if "DataValueTypeID" in df.columns and "Data_Value_TypeID" not in df.columns:
        rename_map["DataValueTypeID"] = "Data_Value_TypeID"

    if "Data_Value_TypeID" not in df.columns and "Data_Value_TypeID" in df.columns:
        # (no-op, but left here for clarity)
        pass

    # Some scripts/users rename these; normalize if present
    if "FootnoteSymbol" in df.columns and "Data_Value_Footnote_Symbol" not in df.columns:
        rename_map["FootnoteSymbol"] = "Data_Value_Footnote_Symbol"

    if "Footnote" in df.columns and "Data_Value_Footnote" not in df.columns:
        rename_map["Footnote"] = "Data_Value_Footnote"

    # 2020 file typo
    if "Geolocatioin" in df.columns and "Geolocation" not in df.columns:
        rename_map["Geolocatioin"] = "Geolocation"

    if rename_map:
        df = df.rename(columns=rename_map)

    return df


def normalize_county_name(value: object) -> str:
    if value is None:
        return ""
    name = str(value).strip().lower()
    name = re.sub(r"\s+", " ", name)
    name = name.replace(".", "")
    for suffix in (
        " county",
        " parish",
        " borough",
        " census area",
        " municipality",
        " city and borough",
        " city",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
            break
    return name


def build_locationid_lookup_from_csv(reference_csv: Path) -> dict[tuple[str, str], str]:
    try:
        sample = pd.read_csv(
            str(reference_csv),
            sep=None,
            quotechar='"',
            dtype=str,
            engine="python",
            nrows=1,
        )
    except Exception:
        return {}
    sample.columns = [c.strip().lstrip("\ufeff") for c in sample.columns]
    sample = normalize_columns(sample)
    if not {"StateAbbr", "LocationName", "LocationID"}.issubset(sample.columns):
        return {}

    lookup: dict[tuple[str, str], str] = {}
    chunks = pd.read_csv(
        str(reference_csv),
        sep=None,
        quotechar='"',
        dtype=str,
        engine="python",
        chunksize=1000,
    )
    for chunk in chunks:
        chunk.columns = [c.strip().lstrip("\ufeff") for c in chunk.columns]
        chunk = normalize_columns(chunk)
        if not {"StateAbbr", "LocationName", "LocationID"}.issubset(chunk.columns):
            continue
        c = chunk[["StateAbbr", "LocationName", "LocationID"]].copy()
        c["StateAbbr"] = c["StateAbbr"].astype(str).str.strip().str.upper()
        c["LocationName"] = c["LocationName"].astype(str).str.strip()
        c["LocationID"] = c["LocationID"].astype(str).str.strip()
        c = c[c["LocationID"].str.len() == 5]
        c = c[c["LocationName"] != ""]
        for _, row in c.iterrows():
            key_exact = (row["StateAbbr"], row["LocationName"].lower())
            key_norm = (row["StateAbbr"], normalize_county_name(row["LocationName"]))
            lookup.setdefault(key_exact, row["LocationID"])
            lookup.setdefault(key_norm, row["LocationID"])
    return lookup


def infer_location_id(df: pd.DataFrame, csv_file: Path) -> pd.DataFrame:
    if "LocationID" in df.columns:
        return df
    if "StateAbbr" not in df.columns or "LocationName" not in df.columns:
        return df

    data_dir = csv_file.parent
    reference_candidates = [
        data_dir / "PLACES__Local_Data_for_Better_Health,_County_Data_2024_release_20260219.csv",
        data_dir / "PLACES__Local_Data_for_Better_Health,_County_Data_2023_release_20260219.csv",
        data_dir / "PLACES__Local_Data_for_Better_Health,_County_Data_2022_release_20260219.csv",
        data_dir / "PLACES__Local_Data_for_Better_Health,_County_Data_2021_release_20260219.csv",
    ]

    lookup: dict[tuple[str, str], str] = {}
    for candidate in reference_candidates:
        if candidate.exists() and candidate.is_file() and candidate != csv_file:
            lookup.update(build_locationid_lookup_from_csv(candidate))
            if lookup:
                break

    if not lookup:
        print("Warning: could not infer LocationID (no usable reference county CSV found).")
        df["LocationID"] = pd.NA
        return df

    state = df["StateAbbr"].astype(str).str.strip().str.upper()
    name = df["LocationName"].astype(str).str.strip()
    exact = [
        lookup.get((st, nm.lower()))
        for st, nm in zip(state, name)
    ]
    norm = [
        lookup.get((st, normalize_county_name(nm)))
        for st, nm in zip(state, name)
    ]
    inferred = [ex if ex is not None else no for ex, no in zip(exact, norm)]
    df = df.copy()
    df["LocationID"] = inferred
    matched = int(pd.Series(inferred).notna().sum())
    print(f"Inferred LocationID for {matched}/{len(df)} rows from reference county CSV.")
    return df


def assert_required(df: pd.DataFrame, required: list[str]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"CSV missing expected columns: {missing}\n"
            f"Available: {list(df.columns)}"
        )


def commas_to_int(series: pd.Series) -> pd.Series:
    # Handles values like "5,087,072"
    s = series.astype(str).str.replace(",", "", regex=False)
    s = s.replace({"nan": None, "None": None, "": None})
    return pd.to_numeric(s, errors="coerce").astype("Int64")

def build_counties(df: pd.DataFrame) -> pd.DataFrame:
    counties = df[
        [
            "LocationID",
            "StateAbbr",
            "StateDesc",
            "LocationName",
            "TotalPopulation",
            "Geolocation",
        ]
    ].copy()
    if "TotalPop18plus" in df.columns:
        counties["TotalPop18plus"] = df["TotalPop18plus"]
    else:
        counties["TotalPop18plus"] = pd.NA

    # Keep only real counties (5-digit FIPS) with a real name
    counties["LocationID"] = counties["LocationID"].astype(str).str.strip()
    counties["LocationName"] = counties["LocationName"].astype(str).str.strip()

    counties = counties[
        (counties["LocationID"].str.len() == 5) &
        (counties["LocationName"] != "") &
        (counties["LocationName"].str.lower() != "nan")
    ].drop_duplicates(subset=["LocationID"]).copy()

    # numeric cleanup
    counties["TotalPopulation"] = commas_to_int(counties["TotalPopulation"])
    counties["TotalPop18plus"] = commas_to_int(counties["TotalPop18plus"])

    # EWKT for PostGIS from "POINT (lon lat)"
    def to_ewkt(val: Optional[str]) -> Optional[str]:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        v = str(val).strip()
        if not v or v.lower() == "nan":
            return None
        return f"SRID=4326;{v}"

    counties["geom_ewkt"] = counties["Geolocation"].apply(to_ewkt)
    return counties



def build_measures(df: pd.DataFrame) -> pd.DataFrame:
    # minimal measure dimension (deduped)
    measure_cols = [
        "CategoryID",
        "Category",
        "MeasureID",
        "Measure",
        "Data_Value_TypeID",
        "Data_Value_Type",
        "Data_Value_Unit",
        "Short_Question_Text",
    ]
    measures = df[measure_cols].drop_duplicates(
        subset=["MeasureID", "Data_Value_TypeID"]
    ).copy()

    # map to dim_measure column names
    measures = measures.rename(columns={
        "CategoryID": "category_id",
        "Category": "category",
        "MeasureID": "measure_id",
        "Measure": "measure",
        "Data_Value_TypeID": "data_value_type_id",
        "Data_Value_Type": "data_value_type",
        "Data_Value_Unit": "unit",
        "Short_Question_Text": "short_question_text",
    })

    return measures

def build_facts(df: pd.DataFrame) -> pd.DataFrame:
    fact_cols = [
        "Year",
        "LocationID",
        "MeasureID",
        "Data_Value_TypeID",
        "Data_Value",
        "Low_Confidence_Limit",
        "High_Confidence_Limit",
        "Data_Value_Footnote_Symbol",
        "Data_Value_Footnote",
    ]
    facts = df[fact_cols].copy()
    
    # Keep only real counties (5-digit FIPS)
    facts["LocationID"] = facts["LocationID"].astype(str).str.strip()
    facts = facts[facts["LocationID"].str.len() == 5].copy()


    # numeric conversions
    facts["Year"] = pd.to_numeric(facts["Year"], errors="coerce").astype("Int64")
    for col in ["Data_Value", "Low_Confidence_Limit", "High_Confidence_Limit"]:
        facts[col] = pd.to_numeric(facts[col], errors="coerce")

    # Rename to canonical names used in SQL insert
    facts = facts.rename(columns={
        "LocationID": "location_id",
        "MeasureID": "measure_id",
        "Data_Value_TypeID": "data_value_type_id",
        "Data_Value": "data_value",
        "Low_Confidence_Limit": "low_confidence_limit",
        "High_Confidence_Limit": "high_confidence_limit",
        "Data_Value_Footnote_Symbol": "footnote_symbol",
        "Data_Value_Footnote": "footnote",
        "Year": "year",
    })

    return facts


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
        f"Design A county ingest; filter_year={filter_year}"
        if filter_year is not None
        else "Design A county ingest; filter_year=None"
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
                'county',
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

def ingest_county_places(
    csv_path: str,
    dict_path: str | None,
    release_label: str,
    filter_year: int | None = None,
    chunk_size: int = MAX_CHUNK_SIZE,
    dry_run: bool = False,
) -> None:
    if chunk_size > MAX_CHUNK_SIZE:
        raise ValueError(f"--chunk-size cannot exceed {MAX_CHUNK_SIZE}")
    if chunk_size <= 0:
        raise ValueError("--chunk-size must be > 0")
    if filter_year is not None and filter_year <= 0:
        raise ValueError("--filter-year must be a positive integer")
    if not release_label.strip():
        raise ValueError("--release-label is required")

    csv_file = validate_input_path(csv_path, "CSV")
    dict_file: Path | None = None
    if dict_path:
        dict_file = validate_input_path(dict_path, "Dictionary CSV")

    print(f"Loading CSV: {csv_file}")
    if dict_file:
        print(f"Using dictionary: {dict_file}")
    print(f"Release label: {release_label}")
    print(f"Filter year: {filter_year if filter_year is not None else 'None'}")
    print(f"Chunk size: {chunk_size}")
    print(f"Dry run: {dry_run}")

    df = read_places_csv(str(csv_file))
    df = normalize_columns(df)
    df = infer_location_id(df, csv_file)

    year_col = detect_year_column(df)
    parsed_years = pd.to_numeric(
        df[year_col].astype(str).str.strip(),
        errors="coerce",
    ).astype("Int64")
    valid_year_mask = parsed_years.notna()
    dropped_null_year = int((~valid_year_mask).sum())
    if dropped_null_year:
        print(f"Dropping rows with null/non-numeric Year: {dropped_null_year}")
    df = df.loc[valid_year_mask].copy()
    parsed_years = parsed_years.loc[valid_year_mask].astype(int)
    df["Year"] = parsed_years

    distinct_years = sorted(df["Year"].dropna().astype(int).unique().tolist())
    print(f"CSV distinct Year values (estimate years): {distinct_years}")
    print(
        "Rows per CSV Year (before filter): "
        f"{dict(sorted(df['Year'].value_counts().to_dict().items()))}"
    )

    if filter_year is not None:
        before_filter = len(df)
        df = df[df["Year"] == filter_year].copy()
        print(
            f"Rows after --filter-year={filter_year}: {len(df)} "
            f"(from {before_filter})"
        )
        if df.empty:
            raise RuntimeError(f"No rows remain after --filter-year={filter_year}")
        print(
            "Rows per CSV Year (after filter): "
            f"{dict(sorted(df['Year'].value_counts().to_dict().items()))}"
        )

    required = [
        "StateAbbr",
        "StateDesc",
        "LocationName",
        "CategoryID",
        "Category",
        "MeasureID",
        "Measure",
        "Data_Value_TypeID",
        "Data_Value_Type",
        "Data_Value",
        "Low_Confidence_Limit",
        "High_Confidence_Limit",
        "TotalPopulation",
        "LocationID",
        "Short_Question_Text",
        "Geolocation",
        "Data_Value_Unit",
        "Data_Value_Footnote_Symbol",
        "Data_Value_Footnote",
    ]
    assert_required(df, required)

    counties = build_counties(df)
    measures = build_measures(df)
    facts = build_facts(df)
    years_present = sorted(
        pd.to_numeric(facts["year"], errors="coerce")
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )
    facts_year_counts = dict(
        sorted(
            facts["year"]
            .dropna()
            .astype(int)
            .value_counts()
            .to_dict()
            .items()
        )
    )

    print(
        f"Prepared rows -> dim_county: {len(counties)}, "
        f"dim_measure: {len(measures)}, facts: {len(facts)}"
    )
    print(f"Prepared facts rows per estimate year: {facts_year_counts}")
    if dry_run:
        print("Dry-run enabled. No database writes performed.")
        return

    engine = get_engine()

    with engine.begin() as conn:
        # -------------------------
        # 1) Upsert dim_county
        # -------------------------
        print(f"Upserting dim_county: {len(counties)} rows")

        conn.execute(text("""
            CREATE TEMP TABLE tmp_dim_county (
                location_id text,
                state_abbr text,
                state_desc text,
                county_name text,
                total_population bigint,
                total_pop_18_plus bigint,
                geom_ewkt text
            ) ON COMMIT DROP;
        """))

        counties_for_copy = counties.rename(columns={
            "LocationID": "location_id",
            "StateAbbr": "state_abbr",
            "StateDesc": "state_desc",
            "LocationName": "county_name",
            "TotalPopulation": "total_population",
            "TotalPop18plus": "total_pop_18_plus",
        })[
            ["location_id", "state_abbr", "state_desc", "county_name", "total_population", "total_pop_18_plus", "geom_ewkt"]
        ]

        counties_for_copy.to_sql(
            "tmp_dim_county",
            conn,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=chunk_size,
        )

        conn.execute(text("""
            INSERT INTO dim_county (location_id, state_abbr, state_desc, county_name, total_population, total_pop_18_plus, geom)
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
            FROM tmp_dim_county t
            ON CONFLICT (location_id) DO UPDATE SET
                state_abbr = EXCLUDED.state_abbr,
                state_desc = EXCLUDED.state_desc,
                county_name = EXCLUDED.county_name,
                total_population = EXCLUDED.total_population,
                total_pop_18_plus = EXCLUDED.total_pop_18_plus,
                geom = EXCLUDED.geom;
        """))

        # -------------------------
        # 2) Upsert dim_measure
        # -------------------------
        print(f"Upserting dim_measure: {len(measures)} rows")

        conn.execute(text("""
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
        """))

        measures.to_sql(
            "tmp_dim_measure",
            conn,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=chunk_size,
        )

        conn.execute(text("""
            INSERT INTO dim_measure (
                category_id, category, measure_id, measure,
                data_value_type_id, data_value_type, unit, short_question_text
            )
            SELECT
                t.category_id, t.category, t.measure_id, t.measure,
                t.data_value_type_id, t.data_value_type, t.unit, t.short_question_text
            FROM tmp_dim_measure t
            ON CONFLICT (measure_id, data_value_type_id) DO UPDATE SET
                category_id = EXCLUDED.category_id,
                category = EXCLUDED.category,
                measure = EXCLUDED.measure,
                data_value_type = EXCLUDED.data_value_type,
                unit = EXCLUDED.unit,
                short_question_text = EXCLUDED.short_question_text;
        """))

        # -------------------------
        # 3) Insert facts
        # -------------------------
        print(f"Inserting facts: {len(facts)} rows")

        conn.execute(text("""
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
        """))

        facts.to_sql(
            "tmp_fact_estimate_county",
            conn,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=chunk_size,
        )

        # Join tmp facts to dim_measure to get measure_dim_id.
        # Deduplicate by final conflict key so one INSERT statement never proposes
        # the same (year, location_id, measure_dim_id) more than once.
        duplicate_fact_keys = conn.execute(
            text(
                """
                WITH measure_lookup AS (
                    SELECT measure_id, data_value_type_id, MIN(id) AS id
                    FROM dim_measure
                    GROUP BY measure_id, data_value_type_id
                )
                SELECT COUNT(*)
                FROM (
                    SELECT
                        f.year,
                        f.location_id,
                        ml.id AS measure_dim_id
                    FROM tmp_fact_estimate_county f
                    JOIN measure_lookup ml
                      ON ml.measure_id = f.measure_id
                     AND ml.data_value_type_id = f.data_value_type_id
                    GROUP BY f.year, f.location_id, ml.id
                    HAVING COUNT(*) > 1
                ) AS dup_keys;
                """
            )
        ).scalar_one()
        if duplicate_fact_keys:
            print(
                "Warning: deduplicating "
                f"{duplicate_fact_keys} duplicate fact keys before upsert."
            )

        conn.execute(text("""
            WITH measure_lookup AS (
                SELECT measure_id, data_value_type_id, MIN(id) AS id
                FROM dim_measure
                GROUP BY measure_id, data_value_type_id
            ),
            joined AS (
                SELECT
                    f.year,
                    f.location_id,
                    ml.id AS measure_dim_id,
                    f.data_value,
                    f.low_confidence_limit,
                    f.high_confidence_limit,
                    f.footnote_symbol,
                    f.footnote,
                    ROW_NUMBER() OVER (
                        PARTITION BY f.year, f.location_id, ml.id
                        ORDER BY
                            (f.data_value IS NOT NULL) DESC,
                            (f.high_confidence_limit IS NOT NULL) DESC,
                            (f.low_confidence_limit IS NOT NULL) DESC,
                            f.footnote_symbol NULLS LAST,
                            f.footnote NULLS LAST
                    ) AS rn
                FROM tmp_fact_estimate_county f
                JOIN measure_lookup ml
                  ON ml.measure_id = f.measure_id
                 AND ml.data_value_type_id = f.data_value_type_id
            )
            INSERT INTO fact_estimate_county (
                year, location_id, measure_dim_id,
                data_value, low_confidence_limit, high_confidence_limit,
                footnote_symbol, footnote
            )
            SELECT
                j.year,
                j.location_id,
                j.measure_dim_id,
                j.data_value,
                j.low_confidence_limit,
                j.high_confidence_limit,
                j.footnote_symbol,
                j.footnote
            FROM joined j
            WHERE j.rn = 1
            ON CONFLICT (year, location_id, measure_dim_id) DO UPDATE SET
                data_value = EXCLUDED.data_value,
                low_confidence_limit = EXCLUDED.low_confidence_limit,
                high_confidence_limit = EXCLUDED.high_confidence_limit,
                footnote_symbol = EXCLUDED.footnote_symbol,
                footnote = EXCLUDED.footnote;
        """))

        record_release_provenance(
            conn,
            release_label=release_label,
            source_file=csv_file.name,
            years_present=years_present,
            row_count=len(facts),
            filter_year=filter_year,
        )

    print("Done.")
    print("Provenance recorded in etl_places_release.")

def main():
    args = parse_args()
    effective_filter_year = args.filter_year
    if args.year is not None:
        if not args.force_override_year:
            raise SystemExit(
                "Refusing deprecated --year without --force-override-year.\n"
                "PLACES file naming (e.g., '2024 release') is not the same as estimate Year values "
                "stored in fact_estimate_county.year.\n"
                "Use --filter-year to limit estimate years, or pass --force-override-year only if "
                "you intentionally want legacy --year treated as --filter-year."
            )
        print(
            "Deprecation warning: --year is deprecated. "
            "Because --force-override-year was provided, treating "
            f"--year={args.year} as --filter-year.",
            file=sys.stderr,
        )
        if effective_filter_year is None:
            effective_filter_year = args.year

    ingest_county_places(
        csv_path=args.csv,
        dict_path=args.dict_path,
        release_label=args.release_label,
        filter_year=effective_filter_year,
        chunk_size=args.chunk_size,
        dry_run=args.dry_run,
    )

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}\n", file=sys.stderr)
        raise

# Example command for 2023 release ingestion:
# export DATABASE_URL="postgresql+psycopg://places:places@localhost:5432/places"
# python app/ingest_places_2025_county.py --release-label 2023_release_20260219 --csv ../data/PLACES__Local_Data_for_Better_Health,_County_Data_2023_release_20260219.csv --dict ../data/PLACES_and_500_Cities__Data_Dictionary_20260215.csv
# Optional estimate-year filter (recommended way to scope ingests):
# python app/ingest_places_2025_county.py --release-label 2023_release_20260219 --csv ../data/PLACES__Local_Data_for_Better_Health,_County_Data_2023_release_20260219.csv --dict ../data/PLACES_and_500_Cities__Data_Dictionary_20260215.csv --filter-year 2021
