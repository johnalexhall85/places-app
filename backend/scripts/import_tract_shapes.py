import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy import create_engine, text


TIGER_YEAR = 2020
ZIP_PATTERN = re.compile(r"^tl_2020_(\d{2})_tract\.zip$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import TIGER/Line 2020 tract shapes into PostGIS."
    )
    parser.add_argument(
        "--state",
        action="append",
        dest="states",
        default=[],
        help="2-digit state FIPS. Repeat for multiple states.",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Directory with TIGER tract ZIP files (default: data/shapes/tracts).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL env variable.",
    )
    parser.add_argument(
        "--force-geopandas",
        action="store_true",
        help="Skip ogr2ogr path and always use geopandas/fiona.",
    )
    return parser.parse_args()


def normalize_state_fips(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) == 1:
        cleaned = f"0{cleaned}"
    if len(cleaned) != 2 or not cleaned.isdigit():
        raise ValueError(f"Invalid state FIPS: {value}")
    return cleaned


def resolve_input_dir(path_arg: str | None) -> Path:
    if path_arg:
        input_dir = Path(path_arg).expanduser().resolve()
    else:
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent.parent
        input_dir = project_root / "data" / "shapes" / "tracts"
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    return input_dir


def resolve_db_url(db_url_arg: str | None) -> str:
    db_url = db_url_arg or os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set and --db-url was not provided.")
    return db_url


def parse_state_from_zip(zip_path: Path) -> str:
    match = ZIP_PATTERN.match(zip_path.name)
    if not match:
        raise ValueError(f"Unexpected ZIP filename: {zip_path.name}")
    return match.group(1)


def collect_zip_paths(input_dir: Path, states: list[str]) -> list[Path]:
    candidates = sorted(input_dir.glob("tl_2020_*_tract.zip"))
    if not candidates:
        raise FileNotFoundError(
            f"No TIGER tract ZIP files found in {input_dir}. Run download_tiger_tracts.py first."
        )

    if not states:
        return candidates

    wanted = set(states)
    filtered = [path for path in candidates if parse_state_from_zip(path) in wanted]
    missing = sorted(wanted - {parse_state_from_zip(path) for path in filtered})
    if missing:
        raise FileNotFoundError(
            "Missing ZIP files for state(s): "
            f"{', '.join(missing)} in {input_dir}"
        )
    return filtered


def ensure_target_table_exists(db_url: str) -> None:
    engine = create_engine(db_url, future=True)
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT to_regclass('public.tract_shapes') AS exists")
        ).mappings().one()["exists"]
    if exists is None:
        raise RuntimeError(
            "tract_shapes table is missing. Run Alembic migrations first."
        )


def to_multipolygon(geometry):
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(geometry, Polygon):
        return MultiPolygon([geometry])
    return geometry


def sql_upsert_from_stage(engine, stage_table: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                INSERT INTO tract_shapes (
                    geoid11,
                    statefp,
                    countyfp,
                    tractce,
                    name,
                    geom
                )
                SELECT
                    LPAD(s.geoid11::text, 11, '0') AS geoid11,
                    LPAD(s.statefp::text, 2, '0') AS statefp,
                    LPAD(s.countyfp::text, 3, '0') AS countyfp,
                    LPAD(s.tractce::text, 6, '0') AS tractce,
                    NULLIF(s.name::text, '') AS name,
                    ST_Multi(
                        CASE
                            WHEN ST_SRID(s.geom) = 4326 THEN s.geom
                            WHEN ST_SRID(s.geom) = 0 THEN ST_SetSRID(s.geom, 4326)
                            ELSE ST_Transform(s.geom, 4326)
                        END
                    )::geometry(MultiPolygon,4326) AS geom
                FROM {stage_table} AS s
                WHERE s.geoid11 IS NOT NULL
                    AND s.geom IS NOT NULL
                ON CONFLICT (geoid11) DO UPDATE SET
                    statefp = EXCLUDED.statefp,
                    countyfp = EXCLUDED.countyfp,
                    tractce = EXCLUDED.tractce,
                    name = EXCLUDED.name,
                    geom = EXCLUDED.geom
                """
            )
        )
        connection.execute(text(f"DROP TABLE IF EXISTS {stage_table}"))


def stage_row_count(engine, stage_table: str) -> int:
    with engine.connect() as connection:
        table_exists = connection.execute(
            text("SELECT to_regclass(:table_name) AS exists"),
            {"table_name": f"public.{stage_table}"},
        ).mappings().one()["exists"]
        if table_exists is None:
            return 0
        return int(
            connection.execute(text(f"SELECT COUNT(*) FROM {stage_table}")).scalar_one()
        )


def db_url_to_ogr_pg(db_url: str) -> str:
    parsed = urlparse(db_url)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError(f"Unsupported DB URL scheme for ogr2ogr: {parsed.scheme}")

    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    dbname = (parsed.path or "").lstrip("/")
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")

    if not dbname:
        raise ValueError("Database name missing from DATABASE_URL.")

    return (
        f"PG:host={host} port={port} dbname={dbname} "
        f"user={user} password={password}"
    )


def import_with_ogr2ogr(zip_paths: list[Path], db_url: str, stage_table: str) -> None:
    ogr_connection = db_url_to_ogr_pg(db_url)
    created = False

    for zip_path in zip_paths:
        statefp = parse_state_from_zip(zip_path)
        layer = f"tl_{TIGER_YEAR}_{statefp}_tract"
        sql = (
            f"SELECT GEOID AS geoid11, STATEFP AS statefp, COUNTYFP AS countyfp, "
            f"TRACTCE AS tractce, NAMELSAD AS name FROM {layer}"
        )

        command = [
            "ogr2ogr",
            "-f",
            "PostgreSQL",
            ogr_connection,
            f"/vsizip/{zip_path}",
            "-sql",
            sql,
            "-dialect",
            "SQLite",
            "-nln",
            stage_table,
            "-t_srs",
            "EPSG:4326",
            "-nlt",
            "MULTIPOLYGON",
            "-lco",
            "GEOMETRY_NAME=geom",
        ]
        if created:
            command.append("-append")
        else:
            command.append("-overwrite")
            created = True

        print(f"Importing {zip_path.name} via ogr2ogr...")
        subprocess.run(command, check=True)


def import_with_geopandas(zip_paths: list[Path], engine, stage_table: str) -> None:
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise RuntimeError(
            "geopandas is required for --force-geopandas or when ogr2ogr is unavailable."
        ) from exc

    first_batch = True

    for zip_path in zip_paths:
        print(f"Importing {zip_path.name} via geopandas...")
        gdf = gpd.read_file(f"zip://{zip_path}")
        if gdf.empty:
            continue

        if gdf.crs is None:
            gdf = gdf.set_crs(epsg=4269)
        gdf = gdf.to_crs(epsg=4326)

        name_column = "NAMELSAD" if "NAMELSAD" in gdf.columns else "NAME"

        gdf["GEOID"] = gdf["GEOID"].astype(str).str.zfill(11)
        gdf["STATEFP"] = gdf["STATEFP"].astype(str).str.zfill(2)
        gdf["COUNTYFP"] = gdf["COUNTYFP"].astype(str).str.zfill(3)
        gdf["TRACTCE"] = gdf["TRACTCE"].astype(str).str.zfill(6)

        gdf = gdf.rename(
            columns={
                "GEOID": "geoid11",
                "STATEFP": "statefp",
                "COUNTYFP": "countyfp",
                "TRACTCE": "tractce",
                name_column: "name",
                "geometry": "geom",
            }
        ).set_geometry("geom")

        gdf["geom"] = gdf["geom"].apply(to_multipolygon)
        gdf = gdf[["geoid11", "statefp", "countyfp", "tractce", "name", "geom"]]

        gdf.to_postgis(
            stage_table,
            engine,
            if_exists="replace" if first_batch else "append",
            index=False,
        )
        first_batch = False


def main() -> None:
    args = parse_args()
    states = [normalize_state_fips(state) for state in args.states]
    input_dir = resolve_input_dir(args.input_dir)
    db_url = resolve_db_url(args.db_url)
    zip_paths = collect_zip_paths(input_dir=input_dir, states=states)

    ensure_target_table_exists(db_url)
    engine = create_engine(db_url, future=True)
    stage_table = "tmp_tract_shapes_import"

    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {stage_table}"))

    ogr2ogr_available = shutil.which("ogr2ogr") is not None and not args.force_geopandas
    if ogr2ogr_available:
        import_with_ogr2ogr(zip_paths=zip_paths, db_url=db_url, stage_table=stage_table)
    else:
        import_with_geopandas(zip_paths=zip_paths, engine=engine, stage_table=stage_table)

    row_count = stage_row_count(engine=engine, stage_table=stage_table)
    if row_count == 0:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {stage_table}"))
        raise RuntimeError("No tract features were loaded into staging table.")

    sql_upsert_from_stage(engine=engine, stage_table=stage_table)
    print(f"Done. Imported {len(zip_paths)} TIGER tract ZIP files into tract_shapes.")


if __name__ == "__main__":
    main()
