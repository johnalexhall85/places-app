"""USDA Food Environment Atlas county read model on the shared release pointer and 2024 county shapes.

County only: USDA publishes no state value for the selected measures, so none is derived. Every 2024
boundary county in the viewport is returned. Counties without a USDA row are labelled at read time
(Puerto Rico: outside Atlas coverage; Connecticut planning regions: not published for the period).
"""
from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot.usda_fea import load_registry
from app.geometry_sql import fitted_geom

S = 'area_pilot'
CAP = 5000
COMMON = f'''FROM {S}.acs_boundary_2024 b
 LEFT JOIN {S}.observation_usda_fea o ON o.geoid=b.geoid AND o.release_id=:release
  AND o.measure_id=:measure AND o.observation_period=:period AND o.population=:population
  AND o.value_type=:value_type
 WHERE b.level='county'
 AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
 AND ST_Intersects(b.geom,ST_MakeEnvelope(:west,:south,:east,:north,4326))'''
# Read-time labels for boundary counties with no USDA row; validation guarantees no other case is published.
STATUS = '''CASE WHEN o.geoid IS NOT NULL THEN o.status
 WHEN b.geoid ~ '^72' THEN 'not_covered'
 WHEN b.geoid ~ '^091[1-9]0$' THEN 'boundary_not_comparable'
 ELSE 'not_in_source' END'''
FIELDS = f'''b.geoid AS geography_id,b.name,o.value,o.source_value,{STATUS} AS status,o.value_note,
 o.source_state,o.source_county'''

LIMITATIONS = [
    'Each measure has its own observation year (2018–2023); they are not one snapshot and not current conditions.',
    'County values only. USDA publishes no state value for these measures, and CHIP does not add or average counties.',
    'Low access is distance to a supermarket or large grocery store. It is not a food-desert designation and does not measure diet quality.',
    'Authorized SNAP or WIC retailers and listed farmers’ markets show program participation and directory listings, not the foods sold, and are not a current store directory.',
    'Connecticut values exist only for its eight former counties and cannot be shown on the 2024 planning-region boundaries. Puerto Rico is outside the Atlas.',
    '-9999 or N/A (not available) and -8888 (county did not exist in that year) are shown separately from zero.',
]
STATUS_TEXT = {
    'available': 'Published value', 'true_zero': 'Published zero',
    'not_available': 'Not available (USDA -9999 or N/A)', 'did_not_exist': 'County did not exist in that year (USDA -8888)',
    'boundary_not_comparable': 'Not published on this boundary (Connecticut planning region)',
    'not_covered': 'Outside Atlas coverage (Puerto Rico)',
}


def catalog(db):
    config = load_registry()
    active = db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r
        ON r.id=a.release_id WHERE a.dataset_id=:dataset AND r.status='published' '''),
        {'dataset': config['dataset_id']}).scalar_one_or_none()
    releases = db.execute(text(f'''SELECT id,source_release_id,semantic_sha256,schema_sha256,metadata_sha256,published_at
        FROM {S}.release WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC'''),
        {'dataset': config['dataset_id']}).mappings().all()
    measures = [{k: m[k] for k in ('measure_id', 'variable_code', 'variable_name', 'label', 'observation_period',
                                   'kind', 'unit', 'population', 'denominator', 'official_definition',
                                   'contributing_sources', 'interpretation', 'source_boundary_basis', 'legend_breaks')}
                | {'geographies': ['county']} for m in config['measures']]
    return {key: config[key] for key in ('dataset_id', 'name', 'short_name', 'publisher', 'landing_page',
            'source_release_id', 'release_label', 'geographies', 'aggregation_method', 'value_type', 'state_values')} | {
        'measures': measures, 'boundary_vintage': config['boundary']['vintage'],
        'boundary_note': config['boundary']['source_vintage_note'], 'source_url': config['landing_page'],
        'documentation_url': config['source_urls']['documentation'],
        'missing_semantics': STATUS_TEXT, 'uncertainty': 'No confidence interval or margin of error is published.',
        'limitations': LIMITATIONS, 'excluded_targets': config['excluded_targets'],
        'active_release_id': str(active) if active else None,
        'published_releases': [{**dict(r), 'id': str(r['id'])} for r in releases]}


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = load_registry()
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if dataset_id != config['dataset_id'] or measure is None:
        raise HTTPException(404, 'USDA Food Environment Atlas selection not found')
    if geography != 'county':
        raise HTTPException(400, 'USDA publishes these Food Environment Atlas measures for counties only; '
                                 'no state or tract value exists and none is derived.')
    if (period, population, value_type) != (measure['observation_period'], measure['population'], config['value_type']):
        raise HTTPException(400, 'Period, population, or value type does not match this USDA measure')
    status = db.execute(text(f'SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'),
                        {'release': release_id, 'dataset': dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published USDA Food Environment Atlas release not found')
    return config, measure


def ensure_cap(db, p):
    count = db.execute(text('SELECT count(*) FROM (SELECT 1 ' + COMMON + ' LIMIT :cap_limit) bounded'),
                       p | {'cap_limit': CAP + 1}).scalar_one()
    if count > CAP:
        raise HTTPException(413, 'Viewport contains more than 5,000 counties. Narrow the viewport.')
    return count


def metadata(config, measure, release_id, bbox):
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id), 'measure_id': measure['measure_id'],
            'variable_code': measure['variable_code'], 'period': measure['observation_period'],
            'population': measure['population'], 'value_type': config['value_type'], 'geography': 'county',
            'unit': measure['unit'], 'kind': measure['kind'], 'legend_breaks': measure['legend_breaks'],
            'uncertainty': 'not published', 'boundary_vintage': config['boundary']['vintage'], 'bbox': bbox}


def _number(value):
    return float(value) if value is not None else None


def value_fields(row, base):
    return {'value': _number(row['value']), 'source_value': row['source_value'], 'status': row['status'],
            'value_note': row['value_note'],
            'source_name': f"{row['source_county']}, {row['source_state']}" if row['source_state'] else None,
            'observation_period': base['period'], 'measure_id': base['measure_id'], 'uncertainty': 'not published'}


def map_data(db, p, count, base, simplify):
    rows = db.execute(text(f'''SELECT {FIELDS},
        ST_AsGeoJSON({fitted_geom('b.geom')})::json AS geometry
        {COMMON} ORDER BY b.geoid'''), p | {'simplify': simplify}).mappings().all()
    if len(rows) != count:
        raise HTTPException(409, 'Viewport changed during USDA map retrieval; retry')
    return base | {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': r['geometry'], 'properties': {
            'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)}} for r in rows],
        'count': count, 'complete': True, 'simplify': simplify}


def legend(db, p, base):
    rows = db.execute(text(f'''SELECT {STATUS} AS status,count(*) AS n,min(o.value) AS low,max(o.value) AS high
        {COMMON} GROUP BY 1 ORDER BY 1'''), p).mappings().all()
    return base | {'limitations': LIMITATIONS, 'status_text': STATUS_TEXT, 'statuses': [
        {'status': r['status'], 'n': r['n'], 'low': _number(r['low']), 'high': _number(r['high'])} for r in rows]}


def table(db, p, base, count, limit, offset):
    rows = db.execute(text(f'''SELECT {FIELDS} {COMMON} ORDER BY b.geoid LIMIT :limit OFFSET :offset'''),
                      p | {'limit': limit, 'offset': offset}).mappings().all()
    return base | {'total': count, 'limit': limit, 'offset': offset, 'rows': [
        {'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)} for r in rows]}
