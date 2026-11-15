"""ACS read model using the shared release pointer and area API selection."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot import legend_breaks

from app.area_pilot.acs import load_registry

S = 'area_pilot'
CAP = 5000
COMMON = f'''FROM {S}.observation_acs o JOIN {S}.acs_boundary_2024 b
  ON b.level=o.level AND b.geoid=o.geoid
 WHERE o.release_id=:release AND o.level=:level AND o.measure_id=:measure
  AND o.observation_period=:period AND o.population=:population AND o.value_type=:value_type
  AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
  AND ST_Intersects(b.geom,ST_MakeEnvelope(:west,:south,:east,:north,4326))'''


def catalog(db):
    config = load_registry()
    active = db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r
        ON r.id=a.release_id WHERE a.dataset_id=:dataset AND r.status='published' '''),
        {'dataset': config['dataset_id']}).scalar_one_or_none()
    releases = db.execute(text(f'''SELECT id,source_release_id,semantic_sha256,schema_sha256,metadata_sha256,published_at
        FROM {S}.release WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC'''),
        {'dataset': config['dataset_id']}).mappings().all()
    return {key: config[key] for key in ('dataset_id','name','publisher','landing_page','product',
            'observation_period','dollar_year','boundary_vintage','geographies','aggregation_method',
            'value_type','unit','moe_confidence','measures','unsupported_territories')} | {
            'active_release_id': str(active) if active else None,
            'published_releases': [{**dict(row), 'id': str(row['id'])} for row in releases]}


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = load_registry()
    if dataset_id != config['dataset_id']:
        raise HTTPException(404, 'ACS dataset not found')
    if (measure_id, period, population, value_type) != ('B19013_001E', '2020–2024', 'households', 'median_household_income'):
        raise HTTPException(400, 'ACS selection is unavailable')
    if geography not in config['geographies']:
        raise HTTPException(400, 'ACS geography is unavailable')
    status = db.execute(text(f'''SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'''),
                        {'release': release_id, 'dataset': dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published ACS release not found')
    return config


def ensure_cap(db, p):
    count = db.execute(text('SELECT count(*) FROM (SELECT 1 ' + COMMON + ' LIMIT :cap_limit) bounded'),
                       p | {'cap_limit': CAP + 1}).scalar_one()
    if count > CAP:
        raise HTTPException(413, f'Viewport contains more than {CAP} areas. Zoom in or narrow the viewport.')
    return count


def metadata(config, release_id, measure_id, period, population, value_type, geography, bbox):
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id),
            'measure_id': measure_id, 'period': period, 'population': population,
            'value_type': value_type, 'geography': geography, 'unit': config['unit'],
            'product': config['product'], 'dollar_year': config['dollar_year'],
            'moe_confidence': config['moe_confidence'], 'boundary_vintage': config['boundary_vintage'][geography],
            'bbox': bbox}


def value_fields(row):
    return {'value': int(row['value']) if row['value'] is not None else None,
            'moe': int(row['moe']) if row['moe'] is not None else None,
            'estimate_annotation': row['estimate_annotation'],
            'moe_annotation': row['moe_annotation'], 'moe_confidence': 90,
            'status': row['status']}


def map_data(db, config, p, count, base, simplify):
    rows = db.execute(text(f'''SELECT o.geoid AS geography_id,b.name,
        ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom,:simplify))::json AS geometry,
        o.value,o.moe,o.estimate_annotation,o.moe_annotation,o.status
        {COMMON} ORDER BY o.geoid'''), p | {'simplify': simplify}).mappings().all()
    if len(rows) != count:
        raise HTTPException(409, 'Viewport changed during ACS map retrieval; retry')
    return base | {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': row['geometry'],
         'properties': {'geography_id': row['geography_id'], 'name': row['name'],
                        **value_fields(row), 'observation_period': base['period'],
                        'measure_id': base['measure_id']}} for row in rows],
        'count': count, 'complete': True, 'simplify': simplify}


def legend(db, p, base):
    rows = db.execute(text(f'''SELECT status,count(*) AS n,min(value) AS low,max(value) AS high
        {COMMON} GROUP BY status ORDER BY status'''), p).mappings().all()
    return base | {'statuses': [{**dict(row), 'low': int(row['low']) if row['low'] is not None else None,
                                 'high': int(row['high']) if row['high'] is not None else None} for row in rows],
                   **legend_breaks.legend_fields(db, f'{S}.observation_acs', p, True)}


def table(db, p, base, count, limit, offset):
    rows = db.execute(text(f'''SELECT o.geoid AS geography_id,b.name,o.value,o.moe,
        o.estimate_annotation,o.moe_annotation,o.status
        {COMMON} ORDER BY o.geoid LIMIT :limit OFFSET :offset'''),
        p | {'limit': limit, 'offset': offset}).mappings().all()
    return base | {'total': count, 'limit': limit, 'offset': offset,
                   'rows': [{'geography_id': row['geography_id'], 'name': row['name'],
                             **value_fields(row), 'observation_period': base['period'],
                             'measure_id': base['measure_id']} for row in rows]}
