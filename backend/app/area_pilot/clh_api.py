"""Curated CLH read model using shared release pointers and existing 2024 boundaries."""
from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot import legend_breaks

from app.area_pilot.clh import load_registry
from app.geometry_sql import fitted_geom

S = 'area_pilot'
CAP = 5000
COMMON = f'''FROM {S}.observation_clh o JOIN {S}.acs_boundary_2024 b
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
    releases = db.execute(text(f'''SELECT id,source_release_id,semantic_sha256,schema_sha256,
        metadata_sha256,published_at FROM {S}.release WHERE dataset_id=:dataset
        AND status='published' ORDER BY published_at DESC'''),
        {'dataset': config['dataset_id']}).mappings().all()
    return {key: config[key] for key in ('dataset_id','name','publisher','distributor','landing_page',
        'source_release_id','boundary_vintage','geographies','aggregation_method','value_type','measures')} | {
        'source_url': config['landing_page'],
        'missing_semantics': 'Blank CLH cell is missing; numeric zero is reported zero. CCBP blanks may represent zero or fewer than three establishments.',
        'uncertainty': 'No MOE or confidence interval supplied in CLH',
        'active_release_id': str(active) if active else None,
        'published_releases': [{**dict(row), 'id': str(row['id'])} for row in releases]}


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = load_registry()
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if dataset_id != config['dataset_id'] or measure is None:
        raise HTTPException(404, 'CLH selection not found')
    if (period != measure['observation_period'] or population != measure['population'] or
            value_type != config['value_type'] or geography not in measure['geographies']):
        raise HTTPException(400, 'CLH measure, period, universe, or geography unavailable')
    status = db.execute(text(f'''SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'''),
                        {'release': release_id, 'dataset': dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published CLH release not found')
    return config, measure


def ensure_cap(db, params):
    count = db.execute(text('SELECT count(*) FROM (SELECT 1 ' + COMMON + ' LIMIT :cap_limit) bounded'),
                       params | {'cap_limit': CAP + 1}).scalar_one()
    if count > CAP:
        raise HTTPException(413, f'Viewport contains more than {CAP:,} areas. Zoom in or narrow the viewport.')
    return count


def metadata(config, measure, release_id, geography, bbox):
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id),
            'measure_id': measure['measure_id'], 'period': measure['observation_period'],
            'population': measure['population'], 'value_type': config['value_type'],
            'geography': geography, 'unit': measure['unit'], 'source': measure['source'],
            'uncertainty': 'not supplied', 'boundary_vintage': config['boundary_vintage'][geography],
            'bbox': bbox}


def value_fields(row, base):
    return {'value': float(row['value']) if row['value'] is not None else None,
            'status': row['status'], 'source_code': row['source_code'],
            'observation_period': base['period'], 'measure_id': base['measure_id'],
            'uncertainty': 'not supplied'}


def map_data(db, params, count, base, simplify):
    rows = db.execute(text(f'''SELECT o.geoid AS geography_id,b.name,
        ST_AsGeoJSON({fitted_geom('b.geom')})::json AS geometry,
        o.value,o.status,o.source_code {COMMON} ORDER BY o.geoid'''),
        params | {'simplify': simplify}).mappings().all()
    if len(rows) != count:
        raise HTTPException(409, 'Viewport changed during CLH map retrieval; retry')
    return base | {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': row['geometry'], 'properties': {
            'geography_id': row['geography_id'], 'name': row['name'], **value_fields(row, base)}}
        for row in rows], 'count': count, 'complete': True, 'simplify': simplify}


def legend(db, params, base):
    rows = db.execute(text(f'''SELECT status,count(*) AS n,min(value) AS low,max(value) AS high
        {COMMON} GROUP BY status ORDER BY status'''), params).mappings().all()
    return base | {'statuses': [{**dict(row), 'low': float(row['low']) if row['low'] is not None else None,
                                  'high': float(row['high']) if row['high'] is not None else None}
                                 for row in rows],
                   **legend_breaks.legend_fields(db, f'{S}.observation_clh', params, True)}


def table(db, params, base, count, limit, offset):
    rows = db.execute(text(f'''SELECT o.geoid AS geography_id,b.name,o.value,o.status,o.source_code
        {COMMON} ORDER BY o.geoid LIMIT :limit OFFSET :offset'''),
        params | {'limit': limit, 'offset': offset}).mappings().all()
    return base | {'total': count, 'limit': limit, 'offset': offset, 'rows': [
        {'geography_id': row['geography_id'], 'name': row['name'], **value_fields(row, base)}
        for row in rows]}
