"""ACS community-characteristics read model: published state, county, tract, and district estimates.

Each request names one level; nothing is derived from another level. District requests join the
119th Congress boundaries; the other levels join the 2024 TIGER boundaries shared with ACS income.
"""
from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot.acs_profile import LEVELS, STATUS_TEXT, load_registry
from app.geometry_sql import fitted_geom

S = 'area_pilot'
CAP = 5000
BOUNDARY = f'''(SELECT level,geoid,name,geom FROM {S}.acs_boundary_2024
  UNION ALL SELECT 'cd',geoid,name,geom FROM {S}.cd_boundary_119)'''
COMMON = f'''FROM {S}.observation_acs_profile o JOIN {BOUNDARY} b ON b.level=o.level AND b.geoid=o.geoid
 WHERE o.release_id=:release AND o.level=:level AND o.measure_id=:measure
  AND o.observation_period=:period AND o.population=:population AND o.value_type=:value_type
  AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
  AND ST_Intersects(b.geom,ST_MakeEnvelope(:west,:south,:east,:north,4326))'''
FIELDS = 'o.geoid AS geography_id,b.name,o.value,o.moe,o.estimate_annotation,o.moe_annotation,o.status'


def LIMITATIONS():
    return load_registry()['limitations']


def catalog(db):
    config = load_registry()
    active = db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r
        ON r.id=a.release_id WHERE a.dataset_id=:dataset AND r.status='published' '''),
        {'dataset': config['dataset_id']}).scalar_one_or_none()
    releases = db.execute(text(f'''SELECT id,source_release_id,semantic_sha256,schema_sha256,metadata_sha256,published_at
        FROM {S}.release WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC'''),
        {'dataset': config['dataset_id']}).mappings().all()
    return {'dataset_id': config['dataset_id'], 'name': config['name'], 'short_name': config['short_name'],
            'publisher': config['publisher'], 'landing_page': config['landing_page'],
            'active_release_id': str(active) if active else None,
            'releases': [{**dict(r), 'id': str(r['id'])} for r in releases],
            'geographies': config['geographies'], 'boundary_vintage': config['boundary_vintage'],
            'value_type': config['value_type'], 'aggregation_method': config['aggregation_method'],
            'uncertainty': config['uncertainty'], 'missing_semantics': STATUS_TEXT,
            'limitations': config['limitations'], 'measures': config['measures']}


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = load_registry()
    if dataset_id != config['dataset_id']:
        raise HTTPException(404, 'Dataset not found')
    if geography not in LEVELS:
        raise HTTPException(400, 'Geography must be state, county, tract, or cd (congressional district)')
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if (measure is None or period != measure['observation_period'] or population != measure['population']
            or value_type != config['value_type']):
        raise HTTPException(400, 'Measure, period, population, or value type is unavailable')
    status = db.execute(text(f'SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'),
                        {'release': release_id, 'dataset': dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published release not found')
    return config, measure


def ensure_cap(db, p):
    count = db.execute(text('SELECT count(*) FROM (SELECT 1 ' + COMMON + ' LIMIT :cap_limit) bounded'),
                       p | {'cap_limit': CAP + 1}).scalar_one()
    if count > CAP:
        raise HTTPException(413, f'Viewport contains more than {CAP:,} areas. Zoom in or narrow the viewport.')
    return count


def metadata(config, measure, release_id, geography, bbox):
    breaks = measure['legend_breaks']
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id), 'measure_id': measure['measure_id'],
            'label': measure['label'], 'period': measure['observation_period'], 'population': measure['population'],
            'value_type': config['value_type'], 'geography': geography, 'unit': measure['unit'], 'kind': measure['kind'],
            'boundary_vintage': config['boundary_vintage'][geography], 'moe_confidence': config['moe_confidence'],
            'legend_breaks': breaks[geography] if isinstance(breaks, dict) else breaks,
            'official_definition': measure['official_definition'], 'interpretation': measure['interpretation'],
            'bbox': bbox}


def _number(value):
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def value_fields(row, base):
    return {'value': _number(row['value']), 'moe': _number(row['moe']), 'status': row['status'],
            'status_text': STATUS_TEXT.get(row['status'], row['status']),
            'estimate_annotation': row['estimate_annotation'], 'moe_annotation': row['moe_annotation'],
            'observation_period': base['period'], 'measure_id': base['measure_id']}


def map_data(db, p, count, base, simplify):
    rows = db.execute(text(f'''SELECT {FIELDS},
        ST_AsGeoJSON({fitted_geom('b.geom')})::json AS geometry
        {COMMON} ORDER BY o.geoid'''), p | {'simplify': simplify}).mappings().all()
    if len(rows) != count:
        raise HTTPException(409, 'Viewport changed during map retrieval; retry the request')
    return base | {'type': 'FeatureCollection', 'count': count, 'complete': True, 'simplify': simplify, 'features': [
        {'type': 'Feature', 'geometry': r['geometry'], 'properties': {
            'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)}} for r in rows]}


def legend(db, p, base):
    rows = db.execute(text(f'''SELECT o.status,count(*) AS n,min(o.value) AS low,max(o.value) AS high
        {COMMON} GROUP BY o.status ORDER BY o.status'''), p).mappings().all()
    return base | {'limitations': LIMITATIONS(), 'status_text': STATUS_TEXT, 'statuses': [
        {'status': r['status'], 'n': r['n'], 'low': _number(r['low']), 'high': _number(r['high'])} for r in rows]}


def table(db, p, base, count, limit, offset):
    rows = db.execute(text(f'{"SELECT " + FIELDS} {COMMON} ORDER BY o.geoid LIMIT :limit OFFSET :offset'),
                      p | {'limit': limit, 'offset': offset}).mappings().all()
    return base | {'total': count, 'limit': limit, 'offset': offset, 'rows': [
        {'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)} for r in rows]}
