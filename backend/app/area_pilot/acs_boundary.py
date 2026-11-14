"""Isolated official 2024 TIGER geometry for ACS 2020–2024 area reads."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import requests
from sqlalchemy import text

from app.area_pilot.acs import LEVEL_LENGTH

S = 'area_pilot'


def boundary_sources(config):
    states = config['supported_state_fips']
    yield 'state', 'us', 'https://www2.census.gov/geo/tiger/TIGER2024/STATE/tl_2024_us_state.zip'
    yield 'county', 'us', 'https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip'
    for state in states:
        yield 'tract', state, f'https://www2.census.gov/geo/tiger/TIGER2024/TRACT/tl_2024_{state}_tract.zip'


def load_boundaries(engine, config, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    source_files = []
    supported = set(config['supported_state_fips'])
    for level, partition, url in boundary_sources(config):
        path = directory / url.rsplit('/', 1)[-1]
        if not path.exists():
            try:
                response = requests.get(url, timeout=(10, 120))
                response.raise_for_status()
            except requests.RequestException as exc:
                raise RuntimeError(f'Boundary {level}/{partition} download failed ({type(exc).__name__})') from None
            temporary = path.with_suffix('.part')
            temporary.write_bytes(response.content)
            temporary.replace(path)
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        shapes = gpd.read_file(f'zip://{path}')
        if not {'GEOID', 'NAME', 'geometry'} <= set(shapes.columns):
            raise ValueError(f'Boundary {level}/{partition} schema changed')
        rows = []
        keys = set()
        for item in shapes.itertuples():
            key = str(item.GEOID)
            if key[:2] not in supported:
                continue
            if len(key) != LEVEL_LENGTH[level] or not key.isdigit() or key in keys:
                raise ValueError(f'Boundary {level}/{partition} has invalid or duplicate GEOID')
            if level == 'tract' and key[:2] != partition:
                raise ValueError(f'Boundary tract partition {partition} returned another state')
            if item.geometry is None or item.geometry.is_empty or not item.geometry.is_valid:
                raise ValueError(f'Boundary {level}/{partition} has invalid geometry')
            keys.add(key)
            rows.append({'level': level, 'geoid': key, 'name': str(item.NAME),
                         'sha': content_hash, 'geom': item.geometry.wkb})
        if not rows:
            raise ValueError(f'Boundary {level}/{partition} was empty')
        with engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
            existing = dict(conn.execute(text(f'''SELECT geoid,source_sha256 FROM {S}.acs_boundary_2024
                WHERE level=:level AND left(geoid,2)=:partition'''),
                {'level': level, 'partition': partition}).all()) if partition != 'us' else dict(conn.execute(
                    text(f'SELECT geoid,source_sha256 FROM {S}.acs_boundary_2024 WHERE level=:level'),
                    {'level': level}).all())
            if existing:
                if set(existing) != keys or set(existing.values()) != {content_hash}:
                    raise ValueError(f'Stored {level}/{partition} boundary differs from official archive')
            else:
                for start in range(0, len(rows), 500):
                    conn.execute(text(f'''INSERT INTO {S}.acs_boundary_2024
                        (level,geoid,name,source_sha256,geom)
                        VALUES (:level,:geoid,:name,:sha,ST_Multi(ST_GeomFromWKB(:geom,4326)))'''),
                        rows[start:start + 500])
        source_files.append({'role': f'tiger2024_{level}_{partition}', 'path': str(path),
                             'url': url, 'sha256': content_hash, 'byte_count': path.stat().st_size,
                             'retrieved_at': datetime.now(timezone.utc)})
    return source_files
