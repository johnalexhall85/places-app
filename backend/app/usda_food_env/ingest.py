from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.db_fqtn import usda_food_env_table
from app.db_schemas import USDA_FOOD_ENV_SCHEMA

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_CHUNKSIZE = 2500

DEFAULT_DATASET_KEY = "food_environment_atlas_2025"
DEFAULT_SOURCE_NAME = "USDA Food Environment Atlas"
DEFAULT_VINTAGE = "July 2025"

VALUES_FILENAME = "StateAndCountyData.csv"
VARIABLE_LIST_FILENAME = "VariableList.csv"
README_FILENAME = "ReadMeFile2025.txt"

MISSING_TOKENS = {"", "na", "n/a", "-9999", "-8888"}
LEVEL_COLUMNS = [
    "level",
    "geography_level",
    "geo_level",
    "spatial_level",
    "geography",
    "area_level",
]
MAPPED_COLUMNS = ["mapped", "is_mapped", "map", "show_on_map"]

STATE_ABBR_TO_FIPS = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "DC": "11",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
    "PR": "72",
}

STATE_FIPS_TO_NAME = {
    "01": "Alabama",
    "02": "Alaska",
    "04": "Arizona",
    "05": "Arkansas",
    "06": "California",
    "08": "Colorado",
    "09": "Connecticut",
    "10": "Delaware",
    "11": "District of Columbia",
    "12": "Florida",
    "13": "Georgia",
    "15": "Hawaii",
    "16": "Idaho",
    "17": "Illinois",
    "18": "Indiana",
    "19": "Iowa",
    "20": "Kansas",
    "21": "Kentucky",
    "22": "Louisiana",
    "23": "Maine",
    "24": "Maryland",
    "25": "Massachusetts",
    "26": "Michigan",
    "27": "Minnesota",
    "28": "Mississippi",
    "29": "Missouri",
    "30": "Montana",
    "31": "Nebraska",
    "32": "Nevada",
    "33": "New Hampshire",
    "34": "New Jersey",
    "35": "New Mexico",
    "36": "New York",
    "37": "North Carolina",
    "38": "North Dakota",
    "39": "Ohio",
    "40": "Oklahoma",
    "41": "Oregon",
    "42": "Pennsylvania",
    "44": "Rhode Island",
    "45": "South Carolina",
    "46": "South Dakota",
    "47": "Tennessee",
    "48": "Texas",
    "49": "Utah",
    "50": "Vermont",
    "51": "Virginia",
    "53": "Washington",
    "54": "West Virginia",
    "55": "Wisconsin",
    "56": "Wyoming",
    "72": "Puerto Rico",
}

VARIABLE_LOOKUP_TABLE = usda_food_env_table("variable_lookup")
COUNTY_VALUES_TABLE = usda_food_env_table("county_values")
STATE_VALUES_TABLE = usda_food_env_table("state_values")
DATASET_META_TABLE = usda_food_env_table("dataset_meta")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Ingest USDA Food Environment Atlas 2025 into schema {USDA_FOOD_ENV_SCHEMA}."
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL env var or local default).",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory containing USDA Food Environment files.",
    )
    parser.add_argument(
        "--values-path",
        default=None,
        help=f"Optional explicit path to {VALUES_FILENAME}.",
    )
    parser.add_argument(
        "--variable-list-path",
        default=None,
        help=f"Optional explicit path to {VARIABLE_LIST_FILENAME}.",
    )
    parser.add_argument(
        "--readme-path",
        default=None,
        help=f"Optional explicit path to {README_FILENAME}.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNKSIZE,
        help=f"Upsert batch size (default: {DEFAULT_CHUNKSIZE}).",
    )
    return parser.parse_args()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _normalize_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _is_missing(value: Any) -> bool:
    cleaned = _clean_text(value)
    if cleaned is None:
        return True
    return cleaned.lower() in MISSING_TOKENS


def _normalize_geoid_5(value: Any) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    digits = re.sub(r"[^0-9]", "", cleaned)
    if not digits or len(digits) > 5:
        return None
    normalized = digits.zfill(5)
    return normalized if re.fullmatch(r"\d{5}", normalized) else None


def _normalize_state_fips(value: Any) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    digits = re.sub(r"[^0-9]", "", cleaned)
    if not digits or len(digits) > 2:
        return None
    normalized = digits.zfill(2)
    return normalized if re.fullmatch(r"\d{2}", normalized) else None


def _parse_year_bounds(text_value: str | None) -> tuple[int | None, int | None]:
    if not text_value:
        return (None, None)
    matches = [int(token) for token in re.findall(r"\b(19\d{2}|20\d{2})\b", text_value)]
    if not matches:
        return (None, None)
    return (min(matches), max(matches))


def _resolve_data_dir(explicit_data_dir: str | None) -> Path:
    if explicit_data_dir:
        return Path(explicit_data_dir).expanduser().resolve()

    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        repo_root / "data",
        repo_root / "backend" / "data",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_path(*, explicit: str | None, data_dir: Path, filename: str) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (data_dir / filename).resolve()


def _chunks(items: list[dict[str, Any]], chunk_size: int) -> Iterable[list[dict[str, Any]]]:
    for idx in range(0, len(items), chunk_size):
        yield items[idx : idx + chunk_size]


def _resolve_column(row: dict[str, Any], *names: str) -> str | None:
    tokens = {_normalize_token(name): name for name in row.keys()}
    for name in names:
        matched = tokens.get(_normalize_token(name))
        if matched is not None:
            return matched
    return None


def _resolve_level(row: dict[str, Any], *, variable_name: str, var_name: str) -> str:
    for key in row.keys():
        if _normalize_token(key) in LEVEL_COLUMNS:
            value = str(row.get(key) or "").strip().lower()
            if "state" in value:
                return "state"
            if "county" in value:
                return "county"

    if "*" in variable_name or "*" in var_name:
        return "state"
    return "county"


def _resolve_is_mapped(row: dict[str, Any]) -> bool:
    for key in row.keys():
        if _normalize_token(key) in MAPPED_COLUMNS:
            token = str(row.get(key) or "").strip().lower()
            if token in {"0", "false", "no", "n"}:
                return False
            if token in {"1", "true", "yes", "y"}:
                return True
    return True


def _load_variable_metadata(variable_list_path: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not variable_list_path.exists():
        raise FileNotFoundError(f"Variable list file not found: {variable_list_path}")

    rows: list[dict[str, Any]] = []
    level_by_var: dict[str, str] = {}

    with variable_list_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, source_row in enumerate(reader, start=1):
            raw_row = {
                str(key): _clean_text(value)
                for key, value in (source_row or {}).items()
                if key is not None
            }

            variable_name_key = _resolve_column(raw_row, "Variable_Name", "Variable Name")
            variable_code_key = _resolve_column(raw_row, "Variable_Code", "Variable Code", "var_name")
            category_key = _resolve_column(raw_row, "Category_Name", "Category Name", "category")
            unit_key = _resolve_column(raw_row, "Units", "Unit")
            description_key = _resolve_column(raw_row, "Description", "Definition")

            variable_name_raw = _clean_text(raw_row.get(variable_name_key)) if variable_name_key else None
            var_name = _clean_text(raw_row.get(variable_code_key)) if variable_code_key else None

            if not var_name:
                continue

            display_name = (variable_name_raw or var_name).replace("*", "").strip()
            description = (
                _clean_text(raw_row.get(description_key))
                if description_key
                else None
            )
            if description is None:
                description = display_name

            unit = _clean_text(raw_row.get(unit_key)) if unit_key else None
            category = _clean_text(raw_row.get(category_key)) if category_key else None
            year_start, year_end = _parse_year_bounds(variable_name_raw or display_name)
            level = _resolve_level(raw_row, variable_name=variable_name_raw or "", var_name=var_name)
            is_mapped = _resolve_is_mapped(raw_row)

            row_payload = {
                "var_name": var_name,
                "display_name": display_name or var_name,
                "description": description,
                "category": category,
                "level": level,
                "unit": unit,
                "year_start": year_start,
                "year_end": year_end,
                "is_mapped": is_mapped,
                "sort_order": index,
                "raw": raw_row,
            }
            rows.append(row_payload)
            level_by_var[var_name] = level

    return rows, level_by_var


def _merge_state_value(current_value: str | None, next_value: str | None) -> str | None:
    if current_value is None:
        return next_value
    if _is_missing(current_value) and next_value is not None and not _is_missing(next_value):
        return next_value
    return current_value


def _load_value_rows(
    values_path: Path,
    *,
    level_by_var: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    if not values_path.exists():
        raise FileNotFoundError(f"State/county values file not found: {values_path}")

    county_by_geoid: dict[str, dict[str, Any]] = {}
    state_by_fips: dict[str, dict[str, Any]] = {}
    input_row_count = 0

    with values_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for source_row in reader:
            input_row_count += 1
            row = {str(key): _clean_text(value) for key, value in (source_row or {}).items() if key is not None}

            raw_fips = row.get("FIPS")
            state_abbr = _clean_text(row.get("State"))
            county_name = _clean_text(row.get("County"))
            var_name = _clean_text(row.get("Variable_Code"))
            raw_value = _clean_text(row.get("Value"))

            if not var_name:
                continue

            geoid = _normalize_geoid_5(raw_fips)
            state_fips = geoid[:2] if geoid else None
            if state_fips is None and state_abbr:
                state_fips = STATE_ABBR_TO_FIPS.get(state_abbr.upper())
            state_name = STATE_FIPS_TO_NAME.get(state_fips) if state_fips else None
            level = level_by_var.get(var_name, "county")

            if geoid:
                county_row = county_by_geoid.get(geoid)
                if county_row is None:
                    county_row = {
                        "geoid": geoid,
                        "state_fips": geoid[:2],
                        "county_fips": geoid[2:],
                        "state_abbr": state_abbr.upper() if state_abbr else None,
                        "county_name": county_name,
                        "state_name": state_name,
                        "raw": {},
                    }
                    county_by_geoid[geoid] = county_row

                county_row["state_abbr"] = county_row["state_abbr"] or (state_abbr.upper() if state_abbr else None)
                county_row["county_name"] = county_row["county_name"] or county_name
                county_row["state_name"] = county_row["state_name"] or state_name
                county_row["raw"][var_name] = raw_value

            if level == "state" and state_fips:
                state_row = state_by_fips.get(state_fips)
                if state_row is None:
                    state_row = {
                        "state_fips": state_fips,
                        "state_abbr": state_abbr.upper() if state_abbr else None,
                        "state_name": state_name,
                        "raw": {},
                    }
                    state_by_fips[state_fips] = state_row

                state_row["state_abbr"] = state_row["state_abbr"] or (state_abbr.upper() if state_abbr else None)
                state_row["state_name"] = state_row["state_name"] or state_name
                existing_value = state_row["raw"].get(var_name)
                state_row["raw"][var_name] = _merge_state_value(existing_value, raw_value)

    county_rows = list(county_by_geoid.values())
    county_rows.sort(key=lambda item: item["geoid"])

    state_rows = list(state_by_fips.values())
    state_rows.sort(key=lambda item: item["state_fips"])

    return county_rows, state_rows, input_row_count


def _read_notes(readme_path: Path | None) -> str | None:
    if readme_path is None or not readme_path.exists():
        return None
    text_value = readme_path.read_text(encoding="utf-8", errors="replace").strip()
    return text_value or None


def _ensure_target_tables(connection) -> None:
    for table_name in (
        "variable_lookup",
        "county_values",
        "state_values",
        "dataset_meta",
    ):
        row = connection.execute(
            text("SELECT to_regclass(:table_name) AS table_name"),
            {"table_name": usda_food_env_table(table_name)},
        ).mappings().one()
        if row["table_name"] is None:
            raise RuntimeError(
                f"Missing table {usda_food_env_table(table_name)}. "
                "Run alembic upgrade head before ingestion."
            )


def _upsert_variable_rows(connection, rows: list[dict[str, Any]], chunk_size: int) -> int:
    if not rows:
        return 0

    stmt = text(
        f"""
        INSERT INTO {VARIABLE_LOOKUP_TABLE} (
            var_name,
            display_name,
            description,
            category,
            level,
            unit,
            year_start,
            year_end,
            is_mapped,
            sort_order,
            raw
        ) VALUES (
            :var_name,
            :display_name,
            :description,
            :category,
            :level,
            :unit,
            :year_start,
            :year_end,
            :is_mapped,
            :sort_order,
            CAST(:raw_json AS jsonb)
        )
        ON CONFLICT (var_name)
        DO UPDATE SET
            display_name = EXCLUDED.display_name,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            level = EXCLUDED.level,
            unit = EXCLUDED.unit,
            year_start = EXCLUDED.year_start,
            year_end = EXCLUDED.year_end,
            is_mapped = EXCLUDED.is_mapped,
            sort_order = EXCLUDED.sort_order,
            raw = EXCLUDED.raw
        """
    )

    inserted = 0
    for batch in _chunks(rows, chunk_size):
        payload = [
            {
                "var_name": row["var_name"],
                "display_name": row.get("display_name"),
                "description": row.get("description"),
                "category": row.get("category"),
                "level": row.get("level"),
                "unit": row.get("unit"),
                "year_start": row.get("year_start"),
                "year_end": row.get("year_end"),
                "is_mapped": bool(row.get("is_mapped", True)),
                "sort_order": row.get("sort_order"),
                "raw_json": json.dumps(row.get("raw") or {}, ensure_ascii=True, separators=(",", ":")),
            }
            for row in batch
        ]
        connection.execute(stmt, payload)
        inserted += len(payload)
    return inserted


def _upsert_county_rows(connection, rows: list[dict[str, Any]], chunk_size: int) -> int:
    if not rows:
        return 0

    stmt = text(
        f"""
        INSERT INTO {COUNTY_VALUES_TABLE} (
            geoid,
            state_fips,
            county_fips,
            state_abbr,
            county_name,
            state_name,
            raw
        ) VALUES (
            :geoid,
            :state_fips,
            :county_fips,
            :state_abbr,
            :county_name,
            :state_name,
            CAST(:raw_json AS jsonb)
        )
        ON CONFLICT (geoid)
        DO UPDATE SET
            state_fips = EXCLUDED.state_fips,
            county_fips = EXCLUDED.county_fips,
            state_abbr = EXCLUDED.state_abbr,
            county_name = EXCLUDED.county_name,
            state_name = EXCLUDED.state_name,
            raw = EXCLUDED.raw,
            updated_at = now()
        """
    )

    inserted = 0
    for batch in _chunks(rows, chunk_size):
        payload = [
            {
                "geoid": row["geoid"],
                "state_fips": row["state_fips"],
                "county_fips": row["county_fips"],
                "state_abbr": row.get("state_abbr"),
                "county_name": row.get("county_name"),
                "state_name": row.get("state_name"),
                "raw_json": json.dumps(row.get("raw") or {}, ensure_ascii=True, separators=(",", ":")),
            }
            for row in batch
        ]
        connection.execute(stmt, payload)
        inserted += len(payload)
    return inserted


def _upsert_state_rows(connection, rows: list[dict[str, Any]], chunk_size: int) -> int:
    if not rows:
        return 0

    stmt = text(
        f"""
        INSERT INTO {STATE_VALUES_TABLE} (
            state_fips,
            state_abbr,
            state_name,
            raw
        ) VALUES (
            :state_fips,
            :state_abbr,
            :state_name,
            CAST(:raw_json AS jsonb)
        )
        ON CONFLICT (state_fips)
        DO UPDATE SET
            state_abbr = EXCLUDED.state_abbr,
            state_name = EXCLUDED.state_name,
            raw = EXCLUDED.raw,
            updated_at = now()
        """
    )

    inserted = 0
    for batch in _chunks(rows, chunk_size):
        payload = [
            {
                "state_fips": row["state_fips"],
                "state_abbr": row.get("state_abbr"),
                "state_name": row.get("state_name"),
                "raw_json": json.dumps(row.get("raw") or {}, ensure_ascii=True, separators=(",", ":")),
            }
            for row in batch
        ]
        connection.execute(stmt, payload)
        inserted += len(payload)
    return inserted


def _upsert_dataset_meta(
    connection,
    *,
    row_count_county: int,
    row_count_state: int,
    notes: str | None,
) -> None:
    connection.execute(
        text(
            f"""
            INSERT INTO {DATASET_META_TABLE} (
                dataset_key,
                source_name,
                vintage,
                notes,
                ingested_at,
                row_count_county,
                row_count_state
            ) VALUES (
                :dataset_key,
                :source_name,
                :vintage,
                :notes,
                :ingested_at,
                :row_count_county,
                :row_count_state
            )
            ON CONFLICT (dataset_key)
            DO UPDATE SET
                source_name = EXCLUDED.source_name,
                vintage = EXCLUDED.vintage,
                notes = EXCLUDED.notes,
                ingested_at = EXCLUDED.ingested_at,
                row_count_county = EXCLUDED.row_count_county,
                row_count_state = EXCLUDED.row_count_state
            """
        ),
        {
            "dataset_key": DEFAULT_DATASET_KEY,
            "source_name": DEFAULT_SOURCE_NAME,
            "vintage": DEFAULT_VINTAGE,
            "notes": notes,
            "ingested_at": datetime.utcnow(),
            "row_count_county": int(row_count_county),
            "row_count_state": int(row_count_state),
        },
    )


def ingest(
    *,
    db_url: str,
    values_path: Path,
    variable_list_path: Path,
    readme_path: Path | None,
    chunksize: int,
) -> dict[str, Any]:
    if chunksize < 1:
        raise ValueError("chunksize must be >= 1")

    started_at = time.perf_counter()

    variable_rows, level_by_var = _load_variable_metadata(variable_list_path)
    county_rows, state_rows, input_row_count = _load_value_rows(
        values_path,
        level_by_var=level_by_var,
    )
    notes = _read_notes(readme_path)

    engine = create_engine(db_url)
    with engine.begin() as connection:
        _ensure_target_tables(connection)

        variable_count = _upsert_variable_rows(connection, variable_rows, chunksize)
        county_count = _upsert_county_rows(connection, county_rows, chunksize)
        state_count = _upsert_state_rows(connection, state_rows, chunksize)
        _upsert_dataset_meta(
            connection,
            row_count_county=county_count,
            row_count_state=state_count,
            notes=notes,
        )

    elapsed = time.perf_counter() - started_at
    return {
        "schema": USDA_FOOD_ENV_SCHEMA,
        "dataset_key": DEFAULT_DATASET_KEY,
        "variables_upserted": variable_count,
        "county_rows_upserted": county_count,
        "state_rows_upserted": state_count,
        "input_rows_processed": input_row_count,
        "elapsed_seconds": round(elapsed, 3),
        "values_path": str(values_path),
        "variable_list_path": str(variable_list_path),
        "readme_path": str(readme_path) if readme_path else None,
    }


def main() -> None:
    args = parse_args()
    data_dir = _resolve_data_dir(args.data_dir)

    values_path = _resolve_path(explicit=args.values_path, data_dir=data_dir, filename=VALUES_FILENAME)
    variable_list_path = _resolve_path(
        explicit=args.variable_list_path,
        data_dir=data_dir,
        filename=VARIABLE_LIST_FILENAME,
    )

    readme_path: Path | None
    if args.readme_path:
        readme_path = Path(args.readme_path).expanduser().resolve()
    else:
        candidate = _resolve_path(explicit=None, data_dir=data_dir, filename=README_FILENAME)
        readme_path = candidate if candidate.exists() else None

    summary = ingest(
        db_url=args.db_url,
        values_path=values_path,
        variable_list_path=variable_list_path,
        readme_path=readme_path,
        chunksize=args.chunksize,
    )

    print("USDA Food Environment ingest complete:")
    for key, value in summary.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
