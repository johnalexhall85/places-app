import argparse
import io
import tempfile
from pathlib import Path
import zipfile

import geopandas as gpd
import requests
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import create_engine, text

DEFAULT_SOURCE_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2023/COUNTY/tl_2023_us_county.zip"
)


def download_zip(url: str) -> bytes:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def extract_shapefile(zip_bytes: bytes, destination: str) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        archive.extractall(destination)
        for name in archive.namelist():
            if name.lower().endswith(".shp"):
                return str((Path(destination) / name))
    raise FileNotFoundError("No .shp file found in the ZIP archive.")


def load_boundaries(db_url: str, source_url: str) -> None:
    zip_bytes = download_zip(source_url)

    with tempfile.TemporaryDirectory() as temp_dir:
        shp_path = extract_shapefile(zip_bytes, temp_dir)
        gdf = gpd.read_file(shp_path)

        if gdf.crs is None:
            gdf = gdf.set_crs(epsg=4269)
        gdf = gdf.to_crs(epsg=4326)

        gdf["STATEFP"] = gdf["STATEFP"].astype(str).str.zfill(2)
        gdf["COUNTYFP"] = gdf["COUNTYFP"].astype(str).str.zfill(3)
        gdf["location_id"] = gdf["STATEFP"] + gdf["COUNTYFP"]

        gdf = gdf.rename(
            columns={
                "GEOID": "geoid",
                "NAME": "name",
                "STATEFP": "statefp",
                "COUNTYFP": "countyfp",
                "geometry": "geom",
            }
        ).set_geometry("geom")

        gdf["geom"] = gdf["geom"].apply(
            lambda geom: MultiPolygon([geom]) if isinstance(geom, Polygon) else geom
        )

        gdf = gdf[["location_id", "geoid", "name", "statefp", "countyfp", "geom"]]

        engine = create_engine(db_url)
        temp_table = "tmp_dim_county_boundary"

        gdf.to_postgis(temp_table, engine, if_exists="replace", index=False)

        upsert_sql = text(
            """
            INSERT INTO dim_county_boundary (
                location_id,
                geoid,
                name,
                statefp,
                countyfp,
                geom
            )
            SELECT
                location_id,
                geoid,
                name,
                statefp,
                countyfp,
                geom
            FROM tmp_dim_county_boundary
            ON CONFLICT (location_id) DO UPDATE
            SET geoid = EXCLUDED.geoid,
                name = EXCLUDED.name,
                statefp = EXCLUDED.statefp,
                countyfp = EXCLUDED.countyfp,
                geom = EXCLUDED.geom
            """
        )
        ensure_state_table_sql = text(
            """
            CREATE TABLE IF NOT EXISTS dim_state_boundary (
                state_fips VARCHAR(2) PRIMARY KEY,
                state_abbr VARCHAR(2) NOT NULL,
                state_name TEXT NOT NULL,
                geom geometry(MULTIPOLYGON, 4326) NOT NULL
            )
            """
        )
        upsert_state_sql = text(
            """
            INSERT INTO dim_state_boundary (
                state_fips,
                state_abbr,
                state_name,
                geom
            )
            SELECT
                b.statefp AS state_fips,
                COALESCE(MAX(c.state_abbr), b.statefp) AS state_abbr,
                COALESCE(MAX(c.state_desc), b.statefp) AS state_name,
                ST_Multi(ST_UnaryUnion(ST_Collect(b.geom)))::geometry(MULTIPOLYGON, 4326) AS geom
            FROM dim_county_boundary AS b
            LEFT JOIN dim_county AS c
              ON c.location_id = b.location_id
            WHERE b.geom IS NOT NULL
            GROUP BY b.statefp
            ON CONFLICT (state_fips) DO UPDATE
            SET state_abbr = EXCLUDED.state_abbr,
                state_name = EXCLUDED.state_name,
                geom = EXCLUDED.geom
            """
        )
        ensure_state_geom_idx_sql = text(
            """
            CREATE INDEX IF NOT EXISTS dim_state_boundary_geom_gist_idx
              ON dim_state_boundary
              USING GIST (geom)
            """
        )
        ensure_state_abbr_idx_sql = text(
            """
            CREATE INDEX IF NOT EXISTS dim_state_boundary_state_abbr_idx
              ON dim_state_boundary (state_abbr)
            """
        )

        with engine.begin() as connection:
            connection.execute(upsert_sql)
            connection.execute(ensure_state_table_sql)
            connection.execute(upsert_state_sql)
            connection.execute(ensure_state_geom_idx_sql)
            connection.execute(ensure_state_abbr_idx_sql)
            connection.execute(text(f"DROP TABLE IF EXISTS {temp_table}"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load US county boundary polygons into PostGIS."
    )
    parser.add_argument("--db-url", required=True, help="Database URL for PostGIS.")
    parser.add_argument(
        "--source-url",
        default=DEFAULT_SOURCE_URL,
        help="TIGER/Line county ZIP URL.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_boundaries(args.db_url, args.source_url)


if __name__ == "__main__":
    main()
