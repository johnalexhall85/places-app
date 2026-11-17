"""Older TIGER/Line boundaries for history periods, kept apart from acs_boundary_2024.

Vintage '2020': TIGER 2020 counties (old Connecticut counties) and tracts (2020 Census basis).
Vintage '2019': TIGER 2019 tracts (2010 Census basis), for ACS 2015-2019 and older PLACES/CLH tracts.
Vintage '2024' rows are read from acs_boundary_2024 and never copied.

Run: python -m app.area_pilot.history.boundaries [--vintage 2020|2019]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import geopandas as gpd
from shapely.geometry import MultiPolygon
from sqlalchemy import create_engine, text

from app.area_pilot.history.fetch import HISTORY_ROOT, USER_AGENT, sha256_file
from app.area_pilot.registry import REGISTRY_DIR
from app.db import DATABASE_URL

S = 'area_pilot'
LENGTH = {'county': 5, 'tract': 11}


def state_fips() -> list[str]:
    config = json.loads((REGISTRY_DIR / 'acs_2024_b19013.json').read_text(encoding='utf-8'))
    return list(config['supported_state_fips'])


def sources(vintage: str):
    if vintage == '2020':
        yield 'county', 'us', 'https://www2.census.gov/geo/tiger/TIGER2020/COUNTY/tl_2020_us_county.zip'
        for state in state_fips():
            yield 'tract', state, f'https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_{state}_tract.zip'
    elif vintage == '2019':
        for state in state_fips():
            yield 'tract', state, f'https://www2.census.gov/geo/tiger/TIGER2019/TRACT/tl_2019_{state}_tract.zip'
    else:
        raise ValueError('History boundary vintage must be 2020 or 2019')


def _download(url: str, path: Path) -> None:
    import requests
    if path.exists():
        return
    response = requests.get(url, timeout=(15, 300), headers={'User-Agent': USER_AGENT})
    response.raise_for_status()
    temporary = path.with_suffix('.part')
    temporary.write_bytes(response.content)
    temporary.replace(path)


def load(engine, vintage: str, directory: Path | None = None) -> list[dict]:
    directory = directory or HISTORY_ROOT / 'boundaries' / f'tiger{vintage}'
    directory.mkdir(parents=True, exist_ok=True)
    supported, report = set(state_fips()), []
    for level, partition, url in sources(vintage):
        path = directory / url.rsplit('/', 1)[-1]
        _download(url, path)
        content_hash = sha256_file(path)
        shapes = gpd.read_file(f'zip://{path}')
        if not {'GEOID', 'NAME', 'geometry'} <= set(shapes.columns):
            raise ValueError(f'Boundary {vintage}/{level}/{partition} schema changed')
        rows, keys = [], set()          # NAD83 coordinates stored as 4326, exactly as acs_boundary_2024
        for item in shapes.itertuples():
            key = str(item.GEOID)
            if key[:2] not in supported:
                continue
            if len(key) != LENGTH[level] or not key.isdigit() or key in keys:
                raise ValueError(f'Boundary {vintage}/{level}/{partition} has invalid or duplicate GEOID {key}')
            if level == 'tract' and key[:2] != partition:
                raise ValueError(f'Boundary tract partition {partition} returned another state')
            geometry = item.geometry
            if geometry is None or geometry.is_empty or not geometry.is_valid:
                raise ValueError(f'Boundary {vintage}/{level}/{key} has invalid geometry')
            if geometry.geom_type == 'Polygon':
                geometry = MultiPolygon([geometry])
            keys.add(key)
            rows.append({'vintage': vintage, 'level': level, 'geoid': key, 'name': str(item.NAME),
                         'sha': content_hash, 'geom': geometry.wkb})
        if not rows:
            raise ValueError(f'Boundary {vintage}/{level}/{partition} was empty')
        with engine.begin() as conn:
            where = '' if partition == 'us' else ' AND left(geoid,2)=:partition'
            existing = dict(conn.execute(text(f'''SELECT geoid,source_sha256 FROM {S}.history_boundary
                WHERE vintage=:vintage AND level=:level{where}'''),
                {'vintage': vintage, 'level': level, 'partition': partition}).all())
            if existing:
                if set(existing) != keys or set(existing.values()) != {content_hash}:
                    raise ValueError(f'Stored {vintage}/{level}/{partition} boundary differs from the official archive')
                status = 'verified'
            else:
                for start in range(0, len(rows), 500):
                    conn.execute(text(f'''INSERT INTO {S}.history_boundary (vintage,level,geoid,name,source_sha256,geom)
                        VALUES (:vintage,:level,:geoid,:name,:sha,ST_Multi(ST_GeomFromWKB(:geom,4326)))'''),
                        rows[start:start + 500])
                status = 'loaded'
        report.append({'vintage': vintage, 'level': level, 'partition': partition, 'url': url,
                       'sha256': content_hash, 'areas': len(rows), 'status': status})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db-url', default=os.getenv('DATABASE_URL', DATABASE_URL))
    parser.add_argument('--vintage', choices=('2020', '2019'), action='append', required=True)
    args = parser.parse_args()
    engine = create_engine(args.db_url, pool_pre_ping=True)
    for vintage in args.vintage:
        report = load(engine, vintage)
        totals = {}
        for item in report:
            totals[item['level']] = totals.get(item['level'], 0) + item['areas']
        print(json.dumps({'vintage': vintage, 'files': len(report), 'areas': totals,
                          'statuses': sorted({i['status'] for i in report})}))


if __name__ == '__main__':
    main()
