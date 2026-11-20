"""CDC/ATSDR SVI 2022 read model: published US-wide county and tract percentile ranks only.

Every 2024 boundary county or tract in the viewport is returned. Areas with no SVI row
(such as Puerto Rico) are labelled ``not_in_release`` at read time. CDC's -999 sentinel
is stored as status ``not_available`` with a NULL value, never zero.
"""
from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot.svi import load_registry
from app.geometry_sql import fitted_geom

S = 'area_pilot'
CAP = 5000
TRACT_CAP = 5000
NOT_IN_RELEASE = 'not_in_release'
STATUS_TEXT = {
    'not_available': 'Not ranked by CDC (−999 in the source file)',
}
LIMITATIONS = [
    "These are CDC/ATSDR's percentile ranks among all U.S. counties, or among all U.S. tracts. "
    'They are not rates, and they do not measure risk for any one person.',
    'The ranks compare areas within one SVI release. Do not compare them with ranks from other SVI years, '
    'or with state-ranked SVI files.',
    "CHIP publishes CDC's ranks as released. It does not re-rank, average, or combine themes.",
    'The ranks are built on ACS 2018–2022 estimates, which have margins of error. '
    'CDC publishes no uncertainty for the ranks.',
    'A county rank and a tract rank come from separate rankings, so they are not comparable.',
]
COMMON = f'''FROM {S}.acs_boundary_2024 b
 LEFT JOIN {S}.observation_cdc_svi o ON o.geoid=b.geoid AND o.geo_level=b.level AND o.release_id=:release
  AND o.measure_id=:measure AND o.observation_period=:period AND o.population=:population
  AND o.value_type=:value_type
 WHERE b.level=:level
 AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
 AND ST_Intersects(b.geom,ST_MakeEnvelope(:west,:south,:east,:north,4326))'''
FIELDS = f'''b.geoid AS geography_id,b.name,o.value,o.source_value,COALESCE(o.status,'{NOT_IN_RELEASE}') AS status'''


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
            'value_type', 'unit', 'population_by_level', 'population_note', 'boundary_vintage', 'measures')} | {
        'source_url': config['landing_page'],
        'missing_semantics': ('CDC -999 cells are stored as not_available ("Not ranked by CDC (−999 in the source file)") '
                              'with a NULL value, never zero. Areas with no row in the SVI release (such as Puerto Rico) '
                              'are labelled not_in_release. Zero is a published rank of 0.'),
        'uncertainty': 'No confidence interval or margin of error is published.',
        'status_text': STATUS_TEXT,
        'limitations': LIMITATIONS,
        'active_release_id': str(active) if active else None,
        'published_releases': [{**dict(r), 'id': str(r['id'])} for r in releases]}


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = load_registry()
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if dataset_id != config['dataset_id'] or measure is None:
        raise HTTPException(404, 'CDC SVI 2022 selection not found')
    if geography == 'state':
        raise HTTPException(400, 'CDC SVI 2022 has no state ranks; county and tract percentile ranks are available')
    if (period, population, value_type) != (measure['observation_period'], measure['population'], config['value_type']) \
            or geography not in config['geographies']:
        raise HTTPException(400, 'CDC SVI 2022 is published for counties and tracts, for the listed period and population')
    status = db.execute(text(f'SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'),
                        {'release': release_id, 'dataset': dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published CDC SVI 2022 release not found')
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
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id), 'measure_id': measure['measure_id'],
            'period': measure['observation_period'], 'population': measure['population'],
            'population_label': config['population_by_level'][geography],
            'value_type': config['value_type'], 'geography': geography, 'unit': measure['unit'],
            'kind': measure['kind'], 'storage_scale': measure['storage_scale'],
            'legend_breaks': measure['legend_breaks'][geography], 'denominator': measure['denominator'],
            'uncertainty': 'not published', 'boundary_vintage': config['boundary_vintage'][geography], 'bbox': bbox}


def number(value):
    return float(value) if value is not None else None


def value_fields(row, base):
    fields = {'value': number(row['value']), 'source_value': row['source_value'], 'status': row['status'],
              'observation_period': base['period'], 'measure_id': base['measure_id'],
              'uncertainty': 'not published'}
    if row['status'] in STATUS_TEXT:
        fields['status_text'] = STATUS_TEXT[row['status']]
    return fields


def map_data(db, p, count, base, simplify):
    rows = db.execute(text(f'''SELECT {FIELDS},
        ST_AsGeoJSON({fitted_geom('b.geom')})::json AS geometry
        {COMMON} ORDER BY b.geoid'''), p | {'simplify': simplify}).mappings().all()
    if len(rows) != count:
        raise HTTPException(409, 'Viewport changed during CDC SVI map retrieval; retry')
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
