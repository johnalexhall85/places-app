"""EPA annual county AQI read model on the shared release pointer and 2024 county shapes.

Every 2024 boundary county in the viewport is returned. Counties without an EPA source row are
labelled ``no_reported_value`` at read time; no zero or placeholder observation is stored.
"""
from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot.epa_aqi import load_registry

S = 'area_pilot'
CAP = 5000
NO_VALUE = 'no_reported_value'
COMMON = f'''FROM {S}.acs_boundary_2024 b
 LEFT JOIN {S}.observation_epa_aqi o ON o.geoid=b.geoid AND o.release_id=:release
  AND o.measure_id=:measure AND o.observation_period=:period AND o.population=:population
  AND o.value_type=:value_type
 WHERE b.level='county'
 AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
 AND ST_Intersects(b.geom,ST_MakeEnvelope(:west,:south,:east,:north,4326))'''
FIELDS = f'''b.geoid AS geography_id,b.name,o.value,COALESCE(o.status,'{NO_VALUE}') AS status,
 o.days_with_aqi,o.value_note,o.source_state,o.source_county'''

LIMITATIONS = [
    'Annual historical AQI summary for one calendar year; not current or forecast conditions.',
    'Coverage reflects where monitors reported to EPA AQS; most counties have no monitor.',
    'No reported value means no county summary was published, not that the air was clean.',
    'Days with AQI varies by county; counts of Good days should be read against it.',
    'Values reflect the pollutants each county measures; many counties measure only some pollutants.',
]


def catalog(db):
    config = load_registry()
    active = db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r
        ON r.id=a.release_id WHERE a.dataset_id=:dataset AND r.status='published' '''),
        {'dataset': config['dataset_id']}).scalar_one_or_none()
    releases = db.execute(text(f'''SELECT id,source_release_id,semantic_sha256,schema_sha256,metadata_sha256,published_at
        FROM {S}.release WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC'''),
        {'dataset': config['dataset_id']}).mappings().all()
    return {key: config[key] for key in ('dataset_id', 'name', 'publisher', 'landing_page', 'report_page',
            'source_release_id', 'observation_year', 'geographies', 'aggregation_method', 'value_type', 'measures')} | {
        'boundary_vintage': config['boundary']['vintage'], 'source_url': config['landing_page'],
        'missing_semantics': ('Counties absent from the EPA file are shown as no reported value. '
                              'Zero is a reported zero. No blanks are expected in published fields.'),
        'uncertainty': 'No confidence interval or margin of error is published; the 90th percentile is a distribution statistic.',
        'limitations': LIMITATIONS,
        'active_release_id': str(active) if active else None,
        'published_releases': [{**dict(r), 'id': str(r['id'])} for r in releases]}


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = load_registry()
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if dataset_id != config['dataset_id'] or measure is None:
        raise HTTPException(404, 'EPA AQI selection not found')
    if (period, population, value_type, geography) != (
            measure['observation_period'], measure['population'], config['value_type'], 'county'):
        raise HTTPException(400, 'EPA AQI is published for counties only, for the listed year and universe')
    status = db.execute(text(f'SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'),
                        {'release': release_id, 'dataset': dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published EPA AQI release not found')
    return config, measure


def ensure_cap(db, p):
    count = db.execute(text('SELECT count(*) FROM (SELECT 1 ' + COMMON + ' LIMIT :cap_limit) bounded'),
                       p | {'cap_limit': CAP + 1}).scalar_one()
    if count > CAP:
        raise HTTPException(413, 'Viewport contains more than 5,000 counties. Narrow the viewport.')
    return count


def metadata(config, measure, release_id, bbox):
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id), 'measure_id': measure['measure_id'],
            'period': measure['observation_period'], 'population': measure['population'],
            'value_type': config['value_type'], 'geography': 'county', 'unit': measure['unit'],
            'kind': measure['kind'], 'legend_breaks': measure['legend_breaks'],
            'statistic_note': measure['statistic_note'],
            'uncertainty': 'not published', 'boundary_vintage': config['boundary']['vintage'], 'bbox': bbox}


def value_fields(row, base):
    return {'value': int(row['value']) if row['value'] is not None else None, 'status': row['status'],
            'days_with_aqi': int(row['days_with_aqi']) if row['days_with_aqi'] is not None else None,
            'value_note': row['value_note'],
            'source_name': f"{row['source_county'].strip()}, {row['source_state']}" if row['source_state'] else None,
            'observation_period': base['period'], 'measure_id': base['measure_id'], 'uncertainty': 'not published'}


def map_data(db, p, count, base, simplify):
    rows = db.execute(text(f'''SELECT {FIELDS},
        ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom,:simplify))::json AS geometry
        {COMMON} ORDER BY b.geoid'''), p | {'simplify': simplify}).mappings().all()
    if len(rows) != count:
        raise HTTPException(409, 'Viewport changed during EPA AQI map retrieval; retry')
    return base | {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': r['geometry'], 'properties': {
            'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)}} for r in rows],
        'count': count, 'complete': True, 'simplify': simplify}


def legend(db, p, base):
    rows = db.execute(text(f'''SELECT COALESCE(o.status,'{NO_VALUE}') AS status,count(*) AS n,
        min(o.value) AS low,max(o.value) AS high,min(o.days_with_aqi) AS days_low,max(o.days_with_aqi) AS days_high
        {COMMON} GROUP BY 1 ORDER BY 1'''), p).mappings().all()
    as_int = lambda v: int(v) if v is not None else None  # noqa: E731
    return base | {'limitations': LIMITATIONS, 'statuses': [
        {'status': r['status'], 'n': r['n'], 'low': as_int(r['low']), 'high': as_int(r['high']),
         'days_low': as_int(r['days_low']), 'days_high': as_int(r['days_high'])} for r in rows]}


def table(db, p, base, count, limit, offset):
    rows = db.execute(text(f'''SELECT {FIELDS} {COMMON} ORDER BY b.geoid LIMIT :limit OFFSET :offset'''),
                      p | {'limit': limit, 'offset': offset}).mappings().all()
    return base | {'total': count, 'limit': limit, 'offset': offset, 'rows': [
        {'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)} for r in rows]}
