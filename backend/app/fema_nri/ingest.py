from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

from app.db_fqtn import fema_nri_table
from app.db_schemas import FEMA_NRI_SCHEMA

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_DATASET_KEY = "fema_nri_december_2025"
DEFAULT_SOURCE_NAME = "FEMA National Risk Index"
DEFAULT_VINTAGE = "December 2025"
DEFAULT_NOTES = (
    "FEMA National Risk Index is intended for planning and broad comparison; "
    "it is not a substitute for local engineering-grade risk assessment."
)

COUNTY_TABLE = fema_nri_table("nri_county")
TRACT_TABLE = fema_nri_table("nri_tract")
DATASET_META_TABLE = fema_nri_table("dataset_meta")

COUNTY_STAGE = f"{FEMA_NRI_SCHEMA}.stage_nri_county"
TRACT_STAGE = f"{FEMA_NRI_SCHEMA}.stage_nri_tract"

DEFAULT_COUNTY_RELATIVE = Path("NRI_GDB_Counties") / "NRI_GDB_Counties.gdb"
DEFAULT_TRACT_RELATIVE = Path("NRI_GDB_CensusTracts") / "NRI_GDB_CensusTracts.gdb"


@dataclass
class LayerInfo:
    layer_name: str
    geometry_type: str | None
    feature_count: int | None
    crs_wkt: str | None


@dataclass
class LoadSummary:
    stage_count: int
    target_count: int
    invalid_geom_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest FEMA National Risk Index county + tract layers from FileGDB into "
            f"schema {FEMA_NRI_SCHEMA}."
        )
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL env var or local default).",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory containing FEMA NRI GDB folders (default: repo/data).",
    )
    parser.add_argument(
        "--county-gdb",
        default=None,
        help="Explicit path to county GDB file (default: data/NRI_GDB_Counties/NRI_GDB_Counties.gdb).",
    )
    parser.add_argument(
        "--tract-gdb",
        default=None,
        help="Explicit path to tract GDB file (default: data/NRI_GDB_CensusTracts/NRI_GDB_CensusTracts.gdb).",
    )
    parser.add_argument(
        "--county-layer",
        default=None,
        help="Optional county layer name override (default prefers NRI_Counties).",
    )
    parser.add_argument(
        "--tract-layer",
        default=None,
        help="Optional tract layer name override (default prefers NRI_CensusTracts).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Truncate target FEMA tables before loading (clean replace).",
    )
    parser.add_argument(
        "--keep-stage",
        action="store_true",
        help="Keep stage tables after ingestion for debugging.",
    )
    return parser.parse_args()


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


def _resolve_gdb_path(*, explicit: str | None, data_dir: Path, relative_default: Path) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (data_dir / relative_default).resolve()


def _quote_pg_value(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _to_ogr_pg_dsn(db_url: str) -> str:
    parsed = make_url(db_url)
    backend = parsed.get_backend_name()
    if backend != "postgresql":
        raise RuntimeError(f"Unsupported backend for ogr2ogr target: {backend}")

    pieces: list[str] = []
    if parsed.host:
        pieces.append(f"host={_quote_pg_value(parsed.host)}")
    if parsed.port:
        pieces.append(f"port={_quote_pg_value(parsed.port)}")
    if parsed.database:
        pieces.append(f"dbname={_quote_pg_value(parsed.database)}")
    if parsed.username:
        pieces.append(f"user={_quote_pg_value(parsed.username)}")
    if parsed.password:
        pieces.append(f"password={_quote_pg_value(parsed.password)}")

    if not any(piece.startswith("dbname=") for piece in pieces):
        raise RuntimeError("Database name is required in --db-url for ogr2ogr ingestion.")

    return "PG:" + " ".join(pieces)


def _list_gdb_layers(gdb_path: Path) -> list[str]:
    try:
        import fiona
    except ModuleNotFoundError as exc:
        raise RuntimeError("fiona is required for FEMA GDB discovery.") from exc

    return list(fiona.listlayers(str(gdb_path)))


def _inspect_layer(gdb_path: Path, layer_name: str) -> LayerInfo:
    try:
        import fiona
    except ModuleNotFoundError as exc:
        raise RuntimeError("fiona is required for FEMA GDB inspection.") from exc

    with fiona.open(str(gdb_path), layer=layer_name) as src:
        geometry_type = src.schema.get("geometry") if isinstance(src.schema, dict) else None
        try:
            feature_count = len(src)
        except Exception:
            feature_count = None

        crs_wkt = None
        if getattr(src, "crs_wkt", None):
            crs_wkt = str(src.crs_wkt)
        elif getattr(src, "crs", None):
            crs_wkt = str(src.crs)

    return LayerInfo(
        layer_name=layer_name,
        geometry_type=geometry_type,
        feature_count=feature_count,
        crs_wkt=crs_wkt,
    )


def _pick_layer(gdb_path: Path, requested_layer: str | None, preferred: list[str]) -> LayerInfo:
    layers = _list_gdb_layers(gdb_path)
    if not layers:
        raise RuntimeError(f"No layers found in {gdb_path}")

    if requested_layer:
        if requested_layer not in layers:
            raise RuntimeError(
                f"Layer {requested_layer!r} not found in {gdb_path}. Available: {', '.join(layers)}"
            )
        return _inspect_layer(gdb_path, requested_layer)

    for candidate in preferred:
        if candidate in layers:
            return _inspect_layer(gdb_path, candidate)

    for layer_name in layers:
        info = _inspect_layer(gdb_path, layer_name)
        geom = str(info.geometry_type or "").strip().lower()
        if geom and geom != "none":
            return info

    return _inspect_layer(gdb_path, layers[0])


def _run_ogr2ogr(*, ogr_pg_dsn: str, gdb_path: Path, layer_name: str, target_table: str) -> None:
    cmd = [
        "ogr2ogr",
        "-f",
        "PostgreSQL",
        ogr_pg_dsn,
        str(gdb_path),
        layer_name,
        "-nln",
        target_table,
        "-overwrite",
        "-nlt",
        "PROMOTE_TO_MULTI",
        "-lco",
        "GEOMETRY_NAME=geom",
        "-lco",
        "FID=ogc_fid",
        "-lco",
        "LAUNDER=NO",
        "-t_srs",
        "EPSG:4326",
        "-makevalid",
        "-dim",
        "XY",
    ]
    print(f"[ogr2ogr] {' '.join(shlex.quote(part) for part in cmd)}")
    subprocess.run(cmd, check=True)


def _ensure_schema(connection: Connection) -> None:
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {FEMA_NRI_SCHEMA}"))


def _table_exists(connection: Connection, table_name: str) -> bool:
    return connection.execute(
        text("SELECT to_regclass(:name)"),
        {"name": table_name},
    ).scalar_one() is not None


def _ensure_target_tables(connection: Connection) -> None:
    expected_tables = (COUNTY_TABLE, TRACT_TABLE, DATASET_META_TABLE)
    missing = [name for name in expected_tables if not _table_exists(connection, name)]
    if not missing:
        return
    missing_text = ", ".join(missing)
    raise RuntimeError(
        "Missing FEMA NRI target tables. "
        f"Missing: {missing_text}. "
        "Run database migrations first (for example: "
        "'cd backend && ./.venv/bin/alembic upgrade head')."
    )


def _stage_columns(connection: Connection, stage_table: str) -> dict[str, str]:
    schema_name, table_name = stage_table.split(".", 1)
    rows = connection.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema_name
              AND table_name = :table_name
            ORDER BY ordinal_position
            """
        ),
        {"schema_name": schema_name, "table_name": table_name},
    ).mappings().all()

    if not rows:
        raise RuntimeError(f"No columns found for stage table {stage_table}")

    return {str(row["column_name"]).upper(): str(row["column_name"]) for row in rows}


def _q(identifier: str) -> str:
    escaped = str(identifier).replace('"', '""')
    return f'"{escaped}"'


def _find_stage_col(columns: dict[str, str], *candidates: str) -> str | None:
    for candidate in candidates:
        key = str(candidate).upper()
        if key in columns:
            return columns[key]
    return None


def _expr_text(alias: str, column_name: str | None) -> str | None:
    if not column_name:
        return None
    return f"{alias}.{_q(column_name)}::text"


def _coalesce_text(expressions: list[str]) -> str:
    if not expressions:
        return "''"
    return "COALESCE(" + ", ".join(expressions + ["''"]) + ")"


def _count_stage_rows(connection: Connection, stage_table: str) -> int:
    return int(connection.execute(text(f"SELECT COUNT(*) FROM {stage_table}")).scalar_one())


def _count_invalid_keys(connection: Connection, stage_table: str, key_expr: str, pattern: str) -> int:
    return int(
        connection.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM {stage_table} AS s
                WHERE ({key_expr}) IS NULL
                   OR ({key_expr}) !~ :pattern
                """
            ),
            {"pattern": pattern},
        ).scalar_one()
    )


def _count_duplicate_keys(connection: Connection, stage_table: str, key_expr: str) -> int:
    return int(
        connection.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT {key_expr} AS key_value
                    FROM {stage_table} AS s
                    GROUP BY {key_expr}
                    HAVING COUNT(*) > 1
                ) AS dup
                """
            )
        ).scalar_one()
    )


def _load_county_from_stage(connection: Connection, *, replace: bool) -> LoadSummary:
    stage_table = COUNTY_STAGE
    target_table = COUNTY_TABLE
    columns = _stage_columns(connection, stage_table)

    statefips_col = _find_stage_col(columns, "STATEFIPS")
    countyfips_col = _find_stage_col(columns, "COUNTYFIPS")
    stcofips_col = _find_stage_col(columns, "STCOFIPS")
    stateabbr_col = _find_stage_col(columns, "STATEABBR")
    statename_col = _find_stage_col(columns, "STATENAME")
    countyname_col = _find_stage_col(columns, "COUNTY")
    nri_id_col = _find_stage_col(columns, "NRI_ID")

    county_key_candidates: list[str] = []
    stco_expr = _expr_text("s", stcofips_col)
    if stco_expr:
        county_key_candidates.append(stco_expr)

    state_expr = _expr_text("s", statefips_col)
    county_expr = _expr_text("s", countyfips_col)
    if state_expr and county_expr:
        county_key_candidates.append(f"({state_expr} || {county_expr})")

    county_key_source = _coalesce_text(county_key_candidates)
    county_geoid_expr = f"LPAD(REGEXP_REPLACE({county_key_source}, '[^0-9]', '', 'g'), 5, '0')"

    invalid_keys = _count_invalid_keys(connection, stage_table, county_geoid_expr, r"^\d{5}$")
    duplicate_keys = _count_duplicate_keys(connection, stage_table, county_geoid_expr)
    if invalid_keys > 0:
        raise RuntimeError(f"County stage contains {invalid_keys} rows with invalid county GEOIDs.")
    if duplicate_keys > 0:
        raise RuntimeError(f"County stage contains {duplicate_keys} duplicate county GEOIDs.")

    state_abbr_expr = _expr_text("s", stateabbr_col) or "NULL"
    state_name_expr = _expr_text("s", statename_col) or "NULL"
    county_name_expr = _expr_text("s", countyname_col) or "NULL"
    nri_id_expr = _expr_text("s", nri_id_col) or "NULL"

    stage_count = _count_stage_rows(connection, stage_table)

    if replace:
        connection.execute(text(f"TRUNCATE TABLE {target_table}"))

    upsert_clause = ""
    if not replace:
        upsert_clause = (
            "ON CONFLICT (county_geoid) DO UPDATE SET "
            "nri_id = EXCLUDED.nri_id, "
            "state_fips = EXCLUDED.state_fips, "
            "county_fips = EXCLUDED.county_fips, "
            "state_abbr = EXCLUDED.state_abbr, "
            "state_name = EXCLUDED.state_name, "
            "county_name = EXCLUDED.county_name, "
            "geom = EXCLUDED.geom, "
            "raw = EXCLUDED.raw, "
            "updated_at = now()"
        )

    connection.execute(
        text(
            f"""
            WITH normalized AS (
                SELECT
                    {county_geoid_expr} AS county_geoid,
                    SUBSTRING({county_geoid_expr} FROM 1 FOR 2) AS state_fips,
                    SUBSTRING({county_geoid_expr} FROM 3 FOR 3) AS county_fips,
                    NULLIF(TRIM({state_abbr_expr}), '') AS state_abbr,
                    NULLIF(TRIM({state_name_expr}), '') AS state_name,
                    NULLIF(TRIM({county_name_expr}), '') AS county_name,
                    NULLIF(TRIM({nri_id_expr}), '') AS nri_id,
                    ST_Multi(
                        ST_CollectionExtract(
                            ST_MakeValid(
                                COALESCE(s.geom, ST_GeomFromText('MULTIPOLYGON EMPTY', 4326))
                            ),
                            3
                        )
                    ) AS geom,
                    (to_jsonb(s) - 'geom' - 'ogc_fid') AS raw
                FROM {stage_table} AS s
            )
            INSERT INTO {target_table} (
                county_geoid,
                nri_id,
                state_fips,
                county_fips,
                state_abbr,
                state_name,
                county_name,
                geom,
                raw
            )
            SELECT
                county_geoid,
                nri_id,
                state_fips,
                county_fips,
                state_abbr,
                state_name,
                county_name,
                geom,
                raw
            FROM normalized
            {upsert_clause}
            """
        )
    )

    target_count = int(connection.execute(text(f"SELECT COUNT(*) FROM {target_table}")).scalar_one())
    invalid_geom_count = int(
        connection.execute(
            text(f"SELECT COUNT(*) FROM {target_table} WHERE geom IS NULL OR NOT ST_IsValid(geom)")
        ).scalar_one()
    )

    return LoadSummary(
        stage_count=stage_count,
        target_count=target_count,
        invalid_geom_count=invalid_geom_count,
    )


def _load_tract_from_stage(connection: Connection, *, replace: bool) -> LoadSummary:
    stage_table = TRACT_STAGE
    target_table = TRACT_TABLE
    columns = _stage_columns(connection, stage_table)

    statefips_col = _find_stage_col(columns, "STATEFIPS")
    countyfips_col = _find_stage_col(columns, "COUNTYFIPS")
    stcofips_col = _find_stage_col(columns, "STCOFIPS")
    tractfips_col = _find_stage_col(columns, "TRACTFIPS")
    tract_col = _find_stage_col(columns, "TRACT")

    stateabbr_col = _find_stage_col(columns, "STATEABBR")
    statename_col = _find_stage_col(columns, "STATENAME")
    countyname_col = _find_stage_col(columns, "COUNTY")
    tractname_col = _find_stage_col(columns, "TRACTNAME")
    nri_id_col = _find_stage_col(columns, "NRI_ID")

    tract_key_candidates: list[str] = []
    tractfips_expr = _expr_text("s", tractfips_col)
    if tractfips_expr:
        tract_key_candidates.append(tractfips_expr)

    stco_expr = _expr_text("s", stcofips_col)
    tract_code_expr = _expr_text("s", tract_col)
    if stco_expr and tract_code_expr:
        tract_key_candidates.append(f"({stco_expr} || {tract_code_expr})")

    state_expr = _expr_text("s", statefips_col)
    county_expr = _expr_text("s", countyfips_col)
    if state_expr and county_expr and tract_code_expr:
        tract_key_candidates.append(f"({state_expr} || {county_expr} || {tract_code_expr})")

    tract_key_source = _coalesce_text(tract_key_candidates)
    tract_geoid_expr = f"LPAD(REGEXP_REPLACE({tract_key_source}, '[^0-9]', '', 'g'), 11, '0')"

    invalid_keys = _count_invalid_keys(connection, stage_table, tract_geoid_expr, r"^\d{11}$")
    duplicate_keys = _count_duplicate_keys(connection, stage_table, tract_geoid_expr)
    if invalid_keys > 0:
        raise RuntimeError(f"Tract stage contains {invalid_keys} rows with invalid tract GEOIDs.")
    if duplicate_keys > 0:
        raise RuntimeError(f"Tract stage contains {duplicate_keys} duplicate tract GEOIDs.")

    state_abbr_expr = _expr_text("s", stateabbr_col) or "NULL"
    state_name_expr = _expr_text("s", statename_col) or "NULL"
    county_name_expr = _expr_text("s", countyname_col) or "NULL"
    tract_name_expr = _expr_text("s", tractname_col) or "NULL"
    tract_code_source = _expr_text("s", tract_col) or f"SUBSTRING({tract_geoid_expr} FROM 6 FOR 6)"
    nri_id_expr = _expr_text("s", nri_id_col) or "NULL"

    stage_count = _count_stage_rows(connection, stage_table)

    if replace:
        connection.execute(text(f"TRUNCATE TABLE {target_table}"))

    upsert_clause = ""
    if not replace:
        upsert_clause = (
            "ON CONFLICT (tract_geoid) DO UPDATE SET "
            "nri_id = EXCLUDED.nri_id, "
            "state_fips = EXCLUDED.state_fips, "
            "county_fips = EXCLUDED.county_fips, "
            "county_geoid = EXCLUDED.county_geoid, "
            "tract_code = EXCLUDED.tract_code, "
            "state_abbr = EXCLUDED.state_abbr, "
            "state_name = EXCLUDED.state_name, "
            "county_name = EXCLUDED.county_name, "
            "tract_name = EXCLUDED.tract_name, "
            "geom = EXCLUDED.geom, "
            "raw = EXCLUDED.raw, "
            "updated_at = now()"
        )

    connection.execute(
        text(
            f"""
            WITH normalized AS (
                SELECT
                    {tract_geoid_expr} AS tract_geoid,
                    SUBSTRING({tract_geoid_expr} FROM 1 FOR 2) AS state_fips,
                    SUBSTRING({tract_geoid_expr} FROM 3 FOR 3) AS county_fips,
                    SUBSTRING({tract_geoid_expr} FROM 1 FOR 5) AS county_geoid,
                    LPAD(REGEXP_REPLACE(COALESCE({tract_code_source}, ''), '[^0-9]', '', 'g'), 6, '0') AS tract_code,
                    NULLIF(TRIM({state_abbr_expr}), '') AS state_abbr,
                    NULLIF(TRIM({state_name_expr}), '') AS state_name,
                    NULLIF(TRIM({county_name_expr}), '') AS county_name,
                    NULLIF(TRIM({tract_name_expr}), '') AS tract_name,
                    NULLIF(TRIM({nri_id_expr}), '') AS nri_id,
                    ST_Multi(
                        ST_CollectionExtract(
                            ST_MakeValid(
                                COALESCE(s.geom, ST_GeomFromText('MULTIPOLYGON EMPTY', 4326))
                            ),
                            3
                        )
                    ) AS geom,
                    (to_jsonb(s) - 'geom' - 'ogc_fid') AS raw
                FROM {stage_table} AS s
            )
            INSERT INTO {target_table} (
                tract_geoid,
                nri_id,
                state_fips,
                county_fips,
                county_geoid,
                tract_code,
                state_abbr,
                state_name,
                county_name,
                tract_name,
                geom,
                raw
            )
            SELECT
                tract_geoid,
                nri_id,
                state_fips,
                county_fips,
                county_geoid,
                tract_code,
                state_abbr,
                state_name,
                county_name,
                tract_name,
                geom,
                raw
            FROM normalized
            {upsert_clause}
            """
        )
    )

    target_count = int(connection.execute(text(f"SELECT COUNT(*) FROM {target_table}")).scalar_one())
    invalid_geom_count = int(
        connection.execute(
            text(f"SELECT COUNT(*) FROM {target_table} WHERE geom IS NULL OR NOT ST_IsValid(geom)")
        ).scalar_one()
    )

    return LoadSummary(
        stage_count=stage_count,
        target_count=target_count,
        invalid_geom_count=invalid_geom_count,
    )


def _upsert_dataset_meta(
    connection: Connection,
    *,
    county_stage_count: int,
    tract_stage_count: int,
    county_row_count: int,
    tract_row_count: int,
) -> None:
    connection.execute(
        text(
            f"""
            INSERT INTO {DATASET_META_TABLE} (
                dataset_key,
                source_name,
                vintage,
                notes,
                county_feature_count,
                tract_feature_count,
                county_row_count,
                tract_row_count,
                ingested_at
            )
            VALUES (
                :dataset_key,
                :source_name,
                :vintage,
                :notes,
                :county_feature_count,
                :tract_feature_count,
                :county_row_count,
                :tract_row_count,
                now()
            )
            ON CONFLICT (dataset_key) DO UPDATE SET
                source_name = EXCLUDED.source_name,
                vintage = EXCLUDED.vintage,
                notes = EXCLUDED.notes,
                county_feature_count = EXCLUDED.county_feature_count,
                tract_feature_count = EXCLUDED.tract_feature_count,
                county_row_count = EXCLUDED.county_row_count,
                tract_row_count = EXCLUDED.tract_row_count,
                ingested_at = now()
            """
        ),
        {
            "dataset_key": DEFAULT_DATASET_KEY,
            "source_name": DEFAULT_SOURCE_NAME,
            "vintage": DEFAULT_VINTAGE,
            "notes": DEFAULT_NOTES,
            "county_feature_count": county_stage_count,
            "tract_feature_count": tract_stage_count,
            "county_row_count": county_row_count,
            "tract_row_count": tract_row_count,
        },
    )


def _drop_stage_tables(connection: Connection) -> None:
    connection.execute(text(f"DROP TABLE IF EXISTS {COUNTY_STAGE}"))
    connection.execute(text(f"DROP TABLE IF EXISTS {TRACT_STAGE}"))


def ingest_fema_nri(
    *,
    db_url: str,
    county_gdb_path: Path,
    tract_gdb_path: Path,
    county_layer: str | None,
    tract_layer: str | None,
    replace: bool,
    keep_stage: bool,
) -> dict[str, Any]:
    if not county_gdb_path.exists():
        raise FileNotFoundError(f"County GDB not found: {county_gdb_path}")
    if not tract_gdb_path.exists():
        raise FileNotFoundError(f"Tract GDB not found: {tract_gdb_path}")

    county_layer_info = _pick_layer(
        county_gdb_path,
        county_layer,
        preferred=["NRI_Counties"],
    )
    tract_layer_info = _pick_layer(
        tract_gdb_path,
        tract_layer,
        preferred=["NRI_CensusTracts"],
    )

    print("[discover] county layer:", county_layer_info)
    print("[discover] tract layer:", tract_layer_info)

    ogr_pg_dsn = _to_ogr_pg_dsn(db_url)
    engine = create_engine(db_url, pool_pre_ping=True)

    started = time.time()

    with engine.begin() as connection:
        _ensure_schema(connection)
        _ensure_target_tables(connection)

    _run_ogr2ogr(
        ogr_pg_dsn=ogr_pg_dsn,
        gdb_path=county_gdb_path,
        layer_name=county_layer_info.layer_name,
        target_table=COUNTY_STAGE,
    )
    _run_ogr2ogr(
        ogr_pg_dsn=ogr_pg_dsn,
        gdb_path=tract_gdb_path,
        layer_name=tract_layer_info.layer_name,
        target_table=TRACT_STAGE,
    )

    with engine.begin() as connection:
        county_summary = _load_county_from_stage(connection, replace=replace)
        tract_summary = _load_tract_from_stage(connection, replace=replace)
        _upsert_dataset_meta(
            connection,
            county_stage_count=county_summary.stage_count,
            tract_stage_count=tract_summary.stage_count,
            county_row_count=county_summary.target_count,
            tract_row_count=tract_summary.target_count,
        )

        if not keep_stage:
            _drop_stage_tables(connection)

    elapsed = time.time() - started

    summary = {
        "dataset_key": DEFAULT_DATASET_KEY,
        "source": DEFAULT_SOURCE_NAME,
        "vintage": DEFAULT_VINTAGE,
        "ingested_at": datetime.utcnow().isoformat() + "Z",
        "replace": bool(replace),
        "county": {
            "gdb": str(county_gdb_path),
            "layer": county_layer_info.layer_name,
            "geometry_type": county_layer_info.geometry_type,
            "feature_count_source": county_summary.stage_count,
            "row_count_loaded": county_summary.target_count,
            "invalid_geometries_after_load": county_summary.invalid_geom_count,
        },
        "tract": {
            "gdb": str(tract_gdb_path),
            "layer": tract_layer_info.layer_name,
            "geometry_type": tract_layer_info.geometry_type,
            "feature_count_source": tract_summary.stage_count,
            "row_count_loaded": tract_summary.target_count,
            "invalid_geometries_after_load": tract_summary.invalid_geom_count,
        },
        "elapsed_seconds": round(elapsed, 2),
    }

    return summary


def main() -> None:
    args = parse_args()

    data_dir = _resolve_data_dir(args.data_dir)
    county_gdb = _resolve_gdb_path(
        explicit=args.county_gdb,
        data_dir=data_dir,
        relative_default=DEFAULT_COUNTY_RELATIVE,
    )
    tract_gdb = _resolve_gdb_path(
        explicit=args.tract_gdb,
        data_dir=data_dir,
        relative_default=DEFAULT_TRACT_RELATIVE,
    )

    print(f"[run] FEMA county gdb: {county_gdb}")
    print(f"[run] FEMA tract gdb: {tract_gdb}")

    try:
        summary = ingest_fema_nri(
            db_url=args.db_url,
            county_gdb_path=county_gdb,
            tract_gdb_path=tract_gdb,
            county_layer=args.county_layer,
            tract_layer=args.tract_layer,
            replace=bool(args.replace),
            keep_stage=bool(args.keep_stage),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"[error] {exc}") from exc

    print("[done] FEMA NRI ingestion complete")
    for section, value in summary.items():
        print(f"  {section}: {value}")


if __name__ == "__main__":
    main()
