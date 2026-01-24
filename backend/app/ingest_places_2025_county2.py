import os
import sys
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text


def get_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(db_url, future=True)


def get_csv_path() -> str:
    """
    Order of precedence:
      1) PLACES_2025_CSV env var (absolute path recommended)
      2) backend/data/<file>.csv
      3) ../data/<file>.csv (project root data folder)
    """
    env_path = os.getenv("PLACES_2025_CSV")
    if env_path:
        return env_path

    # common fallbacks
    here = os.path.dirname(os.path.abspath(__file__))  # backend/app
    backend_root = os.path.dirname(here)               # backend
    candidate_1 = os.path.join(backend_root, "data", "PLACES__Local_Data_for_Better_Health,_County_Data,_2025_release_20260121.csv")
    candidate_2 = os.path.join(os.path.dirname(backend_root), "data", "PLACES__Local_Data_for_Better_Health,_County_Data,_2025_release_20260121.csv")

    if os.path.exists(candidate_1):
        return candidate_1
    if os.path.exists(candidate_2):
        return candidate_2

    raise FileNotFoundError(
        "Could not locate PLACES county CSV.\n"
        "Set PLACES_2025_CSV to the full path of the CSV."
    )

def read_places_csv(csv_path: str) -> pd.DataFrame:
    """
    PLACES 2025 release you showed is semicolon-delimited and quoted.
    Use python engine to avoid weird parser errors from 'C engine' when data is messy.
    """
    df = pd.read_csv(
        csv_path,
        sep=";",
        quotechar='"',
        dtype=str,
        engine="python",
    )
    # strip BOM / whitespace from headers
    df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
    return df


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

    if rename_map:
        df = df.rename(columns=rename_map)

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
    county_cols = [
        "LocationID",
        "StateAbbr",
        "StateDesc",
        "LocationName",
        "TotalPopulation",
        "TotalPop18plus",
        "Geolocation",
    ]
    counties = df[county_cols].drop_duplicates(subset=["LocationID"]).copy()

    # numeric cleanup
    if "TotalPopulation" in counties.columns:
        counties["TotalPopulation"] = commas_to_int(counties["TotalPopulation"])
    if "TotalPop18plus" in counties.columns:
        counties["TotalPop18plus"] = commas_to_int(counties["TotalPop18plus"])

    # EWKT for PostGIS from "POINT (lon lat)"
    def to_ewkt(val: Optional[str]) -> Optional[str]:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        v = str(val).strip()
        if not v or v.lower() == "nan":
            return None
        # Expect "POINT (-87.8 41.8)"
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

def main():
    csv_path = get_csv_path()
    print(f"Loading CSV: {csv_path}")

    df = read_places_csv(csv_path)
    df = normalize_columns(df)

    # Required columns for this ingestion path
    required = [
        "Year",
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
        "TotalPop18plus",
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
            chunksize=5000,
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
            chunksize=5000,
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
            chunksize=10000,
        )

        # Join tmp facts to dim_measure to get measure_dim_id
        # Then upsert into fact table by unique(year, location_id, measure_dim_id)
        conn.execute(text("""
            INSERT INTO fact_estimate_county (
                year, location_id, measure_dim_id,
                data_value, low_confidence_limit, high_confidence_limit,
                footnote_symbol, footnote
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
            FROM tmp_fact_estimate_county f
            JOIN dim_measure m
              ON m.measure_id = f.measure_id
             AND m.data_value_type_id = f.data_value_type_id
            ON CONFLICT (year, location_id, measure_dim_id) DO UPDATE SET
                data_value = EXCLUDED.data_value,
                low_confidence_limit = EXCLUDED.low_confidence_limit,
                high_confidence_limit = EXCLUDED.high_confidence_limit,
                footnote_symbol = EXCLUDED.footnote_symbol,
                footnote = EXCLUDED.footnote;
        """))

    print("Done.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}\n", file=sys.stderr)
        raise

