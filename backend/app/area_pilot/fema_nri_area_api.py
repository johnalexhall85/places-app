"""FEMA National Risk Index (NRI) v1.20 read model: published state, county, and tract values.

Every 2024 boundary state, county, or tract in the viewport is returned. Measures published only
at county and tract levels are rejected at the state level; CHIP never derives state values from
counties. Blank cells and state percentiles whose paired score is blank are stored as
``not_available`` with a NULL value, never zero. FEMA's rating labels are returned beside values.
"""
from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot.fema_nri_area import load_registry
from app.geometry_sql import fitted_geom

S = 'area_pilot'
CAP = 5000
TRACT_CAP = 5000
NOT_IN_RELEASE = 'not_in_release'
STATUS_TEXT = {
    'not_available': 'Not published by FEMA for this area',
}
LIMITATIONS = [
    "These are FEMA's scores, percentiles, and dollar estimates for natural-hazard risk. "
    'They are not forecasts, and they say nothing about any one property.',
    'A score is a national percentile among areas at the same level. '
    'A state percentile compares an area only with others in its state.',
    "Expected annual loss is FEMA's modeled average dollars per year, not a count of past losses.",
    "NRI's social vulnerability and resilience components come from other sources (CDC SVI and HVRI BRIC) "
    "and are not CHIP's SVI release.",
    "CHIP publishes FEMA's values as released. It does not average, combine, or re-rank them, "
    'and does not derive state values.',
    'Version v1.20 (December 2025). FEMA retired the NRI web application, and the data is distributed '
    "through OpenFEMA and FEMA's Resilience Analysis and Planning Tool (RAPT).",
    "FEMA's v1.20 file repeats the national risk score in its risk state-percentile field for every "
    'county and tract, so CHIP does not show a within-state percentile for the overall risk score.',
]
COMMON = f'''FROM {S}.acs_boundary_2024 b
 LEFT JOIN {S}.observation_fema_nri o ON o.geoid=b.geoid AND o.geo_level=b.level AND o.release_id=:release
  AND o.measure_id=:measure AND o.observation_period=:period AND o.population=:population
  AND o.value_type=:value_type
 WHERE b.level=:level
 AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
 AND ST_Intersects(b.geom,ST_MakeEnvelope(:west,:south,:east,:north,4326))'''
FIELDS = (f'''b.geoid AS geography_id,b.name,o.value,o.source_value,'''
          f'''COALESCE(o.status,'{NOT_IN_RELEASE}') AS status,o.rating''')


def status_text_for(status, rating=None):
    if status == 'not_available':
        base = STATUS_TEXT['not_available']
        return f'{base} ({rating})' if rating else base
    return STATUS_TEXT.get(status)


def catalog(db):
    config = load_registry()
    active = db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r
        ON r.id=a.release_id WHERE a.dataset_id=:dataset AND r.status='published' '''),
        {'dataset': config['dataset_id']}).scalar_one_or_none()
    releases = db.execute(text(f'''SELECT id,source_release_id,semantic_sha256,schema_sha256,metadata_sha256,published_at
        FROM {S}.release WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC'''),
        {'dataset': config['dataset_id']}).mappings().all()
    return {key: config[key] for key in ('dataset_id', 'name', 'short_name', 'publisher', 'landing_page',
            'source_release_id', 'observation_year', 'observation_period', 'geographies', 'aggregation_method',
            'value_type', 'boundary_vintage', 'measures')} | {
        'source_url': config['landing_page'],
        'missing_semantics': ('Blank FEMA cells and state percentiles whose paired score is blank are stored as '
                              'not_available ("Not published by FEMA for this area") with a NULL value, never zero. '
                              'Where FEMA supplies a rating label (such as "Insufficient Data" or "Data Unavailable"), '
                              'it is shown beside the status. Zero is a published zero (e.g., "No Expected Annual Losses").'),
        'uncertainty': 'No confidence interval or margin of error is published.',
        'status_text': STATUS_TEXT,
        'limitations': LIMITATIONS,
        'active_release_id': str(active) if active else None,
        'published_releases': [{**dict(r), 'id': str(r['id'])} for r in releases]}


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = load_registry()
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if dataset_id != config['dataset_id'] or measure is None:
        raise HTTPException(404, 'FEMA NRI v1.20 selection not found')
    if geography not in measure['geographies']:
        raise HTTPException(
            400,
            f'FEMA NRI {measure_id} is not published at the {geography} level; '
            f'published levels: {", ".join(measure["geographies"])}',
        )
    if (period, population, value_type) != (measure['observation_period'], measure['population'], config['value_type']):
        raise HTTPException(400, 'FEMA NRI v1.20 selection period, population, or value_type does not match the catalog')
    status = db.execute(text(f'SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'),
                        {'release': release_id, 'dataset': dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published FEMA NRI v1.20 release not found')
    return config, measure


def ensure_cap(db, p):
    cap = TRACT_CAP if p.get('level') == 'tract' else CAP
    count = db.execute(text('SELECT count(*) FROM (SELECT 1 ' + COMMON + ' LIMIT :cap_limit) bounded'),
                       p | {'cap_limit': cap + 1}).scalar_one()
    if count > cap:
        level = p.get('level', 'area')
        raise HTTPException(413, f'Viewport contains more than {cap:,} {level} areas. Zoom in or narrow the viewport.')
    return count


def metadata(config, measure, release_id, geography, bbox):
    return {
        'dataset_id': config['dataset_id'], 'release_id': str(release_id), 'measure_id': measure['measure_id'],
        'period': measure['observation_period'], 'population': measure['population'],
        'value_type': config['value_type'], 'geography': geography, 'unit': measure['unit'],
        'kind': measure['kind'], 'storage_scale': measure['storage_scale'],
        'direction': measure['direction'], 'direction_note': measure['direction_note'],
        'has_rating': bool(measure.get('rating_field')),
        'geographies': measure['geographies'],
        'legend_breaks': measure['legend_breaks'][geography], 'denominator': measure['denominator'],
        'uncertainty': 'not published', 'boundary_vintage': config['boundary_vintage'][geography], 'bbox': bbox,
    }


def number(value):
    return float(value) if value is not None else None


def value_fields(row, base):
    rating = row.get('rating')
    fields = {
        'value': number(row['value']), 'source_value': row['source_value'], 'status': row['status'],
        'rating': rating, 'observation_period': base['period'], 'measure_id': base['measure_id'],
        'uncertainty': 'not published',
    }
    text_label = status_text_for(row['status'], rating)
    if text_label:
        fields['status_text'] = text_label
    return fields


def map_data(db, p, count, base, simplify):
    rows = db.execute(text(f'''SELECT {FIELDS},
        ST_AsGeoJSON({fitted_geom('b.geom')})::json AS geometry
        {COMMON} ORDER BY b.geoid'''), p | {'simplify': simplify}).mappings().all()
    if len(rows) != count:
        raise HTTPException(409, 'Viewport changed during FEMA NRI map retrieval; retry')
    return base | {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': r['geometry'], 'properties': {
            'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)}} for r in rows],
        'count': count, 'complete': True, 'simplify': simplify}


def legend(db, p, base):
    rows = db.execute(text(f'''SELECT COALESCE(o.status,'{NOT_IN_RELEASE}') AS status,count(*) AS n,
        min(o.value) AS low,max(o.value) AS high {COMMON} GROUP BY 1 ORDER BY 1'''), p).mappings().all()
    return base | {'limitations': LIMITATIONS, 'statuses': [
        {'status': r['status'], 'n': r['n'], 'low': number(r['low']), 'high': number(r['high'])}
        | ({'status_text': STATUS_TEXT[r['status']]} if r['status'] in STATUS_TEXT else {})
        for r in rows]}


def table(db, p, base, count, limit, offset):
    rows = db.execute(text(f'''SELECT {FIELDS} {COMMON} ORDER BY b.geoid LIMIT :limit OFFSET :offset'''),
                      p | {'limit': limit, 'offset': offset}).mappings().all()
    return base | {'total': count, 'limit': limit, 'offset': offset, 'rows': [
        {'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)} for r in rows]}
