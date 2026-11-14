"""CMS Original Medicare Geographic Variation read model: published state and county values only.

Every 2024 boundary state or county in the viewport is returned. Areas without a CMS row at that
level (DC and Puerto Rico counties) are labelled ``not_published`` at read time. The national value
is returned as a separate reference, never as a map feature. No tract values exist.
"""
from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot.cms_gv import load_registry

S = 'area_pilot'
CAP = 5000
NOT_PUBLISHED = 'not_published'
COMMON = f'''FROM {S}.acs_boundary_2024 b
 LEFT JOIN {S}.observation_cms_gv o ON o.geoid=b.geoid AND o.geo_level=b.level AND o.release_id=:release
  AND o.measure_id=:measure AND o.observation_period=:period AND o.population=:population
  AND o.value_type=:value_type
 WHERE b.level=:level
 AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
 AND ST_Intersects(b.geom,ST_MakeEnvelope(:west,:south,:east,:north,4326))'''
FIELDS = f'''b.geoid AS geography_id,b.name,o.value,o.source_value,COALESCE(o.status,'{NOT_PUBLISHED}') AS status,
 o.source_desc'''

LIMITATIONS = [
    'Original Medicare (fee-for-service) beneficiaries with Part A and Part B only. Medicare Advantage enrollees, '
    'people with only Part A or only Part B, and people not on Medicare are excluded.',
    'All ages: people under 65 who qualify through disability or ESRD and people 65 and older. Not an age 65+ measure.',
    'Utilization and spending describe this beneficiary population, not all residents of the area.',
    'Standardized payments remove geographic payment-rate differences. They are not adjusted for inflation, and '
    'CMS states they are not adjusted for health status.',
    'CMS suppresses values when fewer than 11 beneficiaries or users are counted. Suppressed values are not estimated.',
    'State and county values are published separately by CMS. CHIP does not add counties into states.',
    'No tract, ZIP, or sub-county values are published.',
    'No confidence interval or margin of error is published.',
]


def catalog(db):
    config = load_registry()
    active = db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r
        ON r.id=a.release_id WHERE a.dataset_id=:dataset AND r.status='published' '''),
        {'dataset': config['dataset_id']}).scalar_one_or_none()
    releases = db.execute(text(f'''SELECT id,source_release_id,semantic_sha256,schema_sha256,metadata_sha256,published_at
        FROM {S}.release WHERE dataset_id=:dataset AND status='published' ORDER BY published_at DESC'''),
        {'dataset': config['dataset_id']}).mappings().all()
    return {key: config[key] for key in ('dataset_id', 'name', 'short_name', 'publisher', 'landing_page',
            'source_release_id', 'observation_year', 'age_level', 'age_level_label', 'population_label',
            'geographies', 'state_to_county_zoom', 'aggregation_method', 'value_type', 'measures',
            'documentation_conflicts')} | {
        'boundary_vintage': config['boundary']['vintage'], 'source_url': config['landing_page'],
        'missing_semantics': ('Suppressed (CMS "*", fewer than 11) and missing values are distinct statuses. '
                              'Not published means CMS has no row for that area at that level. '
                              'Zero is a reported zero.'),
        'tract_note': 'CMS publishes this product for the nation, states, and counties only. No tract estimates exist.',
        'uncertainty': 'No confidence interval or margin of error is published.',
        'legacy_note': ('Separate from the legacy "CMS Medicare FFS (legacy import)" option on the main map, '
                        'which reads older cms.gv_* tables without a release pointer.'),
        'limitations': LIMITATIONS,
        'active_release_id': str(active) if active else None,
        'published_releases': [{**dict(r), 'id': str(r['id'])} for r in releases]}


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = load_registry()
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if dataset_id != config['dataset_id'] or measure is None:
        raise HTTPException(404, 'CMS Original Medicare GV selection not found')
    if geography == 'tract':
        raise HTTPException(400, 'CMS Original Medicare GV has no tract estimates; state and county values are available')
    if (period, population, value_type) != (measure['observation_period'], measure['population'], config['value_type']) \
            or geography not in config['geographies']:
        raise HTTPException(400, 'CMS Original Medicare GV is published for states and counties, for the listed year and population')
    status = db.execute(text(f'SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'),
                        {'release': release_id, 'dataset': dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published CMS Original Medicare GV release not found')
    return config, measure


def ensure_cap(db, p):
    count = db.execute(text('SELECT count(*) FROM (SELECT 1 ' + COMMON + ' LIMIT :cap_limit) bounded'),
                       p | {'cap_limit': CAP + 1}).scalar_one()
    if count > CAP:
        raise HTTPException(413, 'Viewport contains more than 5,000 areas. Narrow the viewport.')
    return count


def metadata(config, measure, release_id, geography, bbox):
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id), 'measure_id': measure['measure_id'],
            'period': measure['observation_period'], 'population': measure['population'],
            'value_type': config['value_type'], 'geography': geography, 'unit': measure['unit'],
            'kind': measure['kind'], 'storage_scale': measure['storage_scale'],
            'legend_breaks': measure['legend_breaks'][geography], 'denominator': measure['denominator'],
            'uncertainty': 'not published', 'boundary_vintage': config['boundary']['vintage'], 'bbox': bbox}


def number(value):
    return float(value) if value is not None else None


def value_fields(row, base):
    return {'value': number(row['value']), 'source_value': row['source_value'], 'status': row['status'],
            'source_name': row['source_desc'], 'observation_period': base['period'],
            'measure_id': base['measure_id'], 'uncertainty': 'not published'}


def map_data(db, p, count, base, simplify):
    rows = db.execute(text(f'''SELECT {FIELDS},
        ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom,:simplify))::json AS geometry
        {COMMON} ORDER BY b.geoid'''), p | {'simplify': simplify}).mappings().all()
    if len(rows) != count:
        raise HTTPException(409, 'Viewport changed during CMS map retrieval; retry')
    return base | {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': r['geometry'], 'properties': {
            'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)}} for r in rows],
        'count': count, 'complete': True, 'simplify': simplify}


def national_reference(db, p):
    row = db.execute(text(f'''SELECT value,source_value,status FROM {S}.observation_cms_gv
        WHERE release_id=:release AND measure_id=:measure AND geo_level='national' AND geoid='US'
        AND observation_period=:period AND population=:population AND value_type=:value_type'''),
        p).mappings().one_or_none()
    if row is None:
        return None
    return {'value': number(row['value']), 'source_value': row['source_value'], 'status': row['status'],
            'note': 'CMS-published national value, shown for reference only; not computed by CHIP.'}


def legend(db, p, base):
    rows = db.execute(text(f'''SELECT COALESCE(o.status,'{NOT_PUBLISHED}') AS status,count(*) AS n,
        min(o.value) AS low,max(o.value) AS high {COMMON} GROUP BY 1 ORDER BY 1'''), p).mappings().all()
    return base | {'limitations': LIMITATIONS, 'national_reference': national_reference(db, p), 'statuses': [
        {'status': r['status'], 'n': r['n'], 'low': number(r['low']), 'high': number(r['high'])} for r in rows]}


def table(db, p, base, count, limit, offset):
    rows = db.execute(text(f'''SELECT {FIELDS} {COMMON} ORDER BY b.geoid LIMIT :limit OFFSET :offset'''),
                      p | {'limit': limit, 'offset': offset}).mappings().all()
    return base | {'total': count, 'limit': limit, 'offset': offset, 'rows': [
        {'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)} for r in rows]}
