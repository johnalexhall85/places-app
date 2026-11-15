"""BRFSS state prevalence read model: CDC's published state survey estimates.

State geography only. Every state boundary is returned; a state with no row in the release is
shown as not published (CDC has no result for that state and year), never as zero or missing data.
Territories without a CHIP boundary and CDC's median rows are returned beside the table, not mapped.
"""
from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot.brfss import NOT_PUBLISHED, STATUS_TEXT, load_registry

S = 'area_pilot'
COMMON = f'''FROM {S}.acs_boundary_2024 b LEFT JOIN {S}.observation_brfss o
   ON o.geoid=b.geoid AND o.release_id=:release AND o.measure_id=:measure
  AND o.observation_period=:period AND o.population=:population AND o.value_type=:value_type
 WHERE b.level='state' AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
  AND ST_Intersects(b.geom,ST_MakeEnvelope(:west,:south,:east,:north,4326))'''
FIELDS = (f"b.geoid AS geography_id,b.name,o.value,o.ci_low,o.ci_high,o.sample_size,"
          f"COALESCE(o.status,'{NOT_PUBLISHED}') AS status")


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
            'source_url': config['source_dataset_page'],
            'active_release_id': str(active) if active else None,
            'releases': [{**dict(r), 'id': str(r['id'])} for r in releases],
            'geographies': config['geographies'], 'boundary_vintage': config['boundary_vintage'],
            'value_type': config['value_type'], 'aggregation_method': config['aggregation_method'],
            'uncertainty': config['uncertainty'], 'missing_semantics': STATUS_TEXT,
            'median_locations': config['median_locations'], 'source_only_locations': config['source_only_locations'],
            'limitations': config['limitations'], 'measures': config['measures']}


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = load_registry()
    if dataset_id != config['dataset_id']:
        raise HTTPException(404, 'Dataset not found')
    if geography != 'state':
        raise HTTPException(400, 'BRFSS estimates are published for states only')
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if (measure is None or period != measure['observation_period'] or population != measure['population']
            or value_type != config['value_type']):
        raise HTTPException(400, 'Measure, period, population, or value type is unavailable')
    status = db.execute(text(f'SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'),
                        {'release': release_id, 'dataset': dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published release not found')
    return config, measure


def metadata(config, measure, release_id, bbox):
    return {'dataset_id': config['dataset_id'], 'release_id': str(release_id), 'measure_id': measure['measure_id'],
            'label': measure['label'], 'period': measure['observation_period'], 'population': measure['population'],
            'value_type': config['value_type'], 'geography': 'state', 'unit': measure['unit'], 'kind': measure['kind'],
            'boundary_vintage': config['boundary_vintage']['state'], 'uncertainty_kind': 'ci95',
            'legend_breaks': measure['legend_breaks'], 'official_definition': measure['official_definition'],
            'interpretation': measure['interpretation'], 'places_measure_id': measure.get('places_measure_id'),
            'bbox': bbox}


def _number(value):
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def value_fields(row, base):
    return {'value': _number(row['value']), 'ci_low': _number(row['ci_low']), 'ci_high': _number(row['ci_high']),
            'sample_size': row['sample_size'], 'status': row['status'],
            'status_text': STATUS_TEXT.get(row['status'], row['status']),
            'observation_period': base['period'], 'measure_id': base['measure_id']}


def count(db, p):
    return db.execute(text('SELECT count(*) ' + COMMON), p).scalar_one()


def map_data(db, p, base, simplify):
    rows = db.execute(text(f'''SELECT {FIELDS},
        ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom,:simplify))::json AS geometry
        {COMMON} ORDER BY b.geoid'''), p | {'simplify': simplify}).mappings().all()
    return base | {'type': 'FeatureCollection', 'count': len(rows), 'complete': True, 'simplify': simplify, 'features': [
        {'type': 'Feature', 'geometry': r['geometry'], 'properties': {
            'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)}} for r in rows]}


def legend(db, p, base):
    rows = db.execute(text(f'''SELECT COALESCE(o.status,'{NOT_PUBLISHED}') AS status,count(*) AS n,
        min(o.value) AS low,max(o.value) AS high {COMMON} GROUP BY 1 ORDER BY 1'''), p).mappings().all()
    return base | {'limitations': LIMITATIONS(), 'status_text': STATUS_TEXT, 'statuses': [
        {'status': r['status'], 'n': r['n'], 'low': _number(r['low']), 'high': _number(r['high'])} for r in rows]}


def reference_rows(db, p, base, config):
    """CDC's median rows and territories that CHIP cannot map, for the selected measure. Not viewport-filtered."""
    rows = db.execute(text(f'''SELECT geoid,value,ci_low,ci_high,sample_size,status,location_kind
        FROM {S}.observation_brfss WHERE release_id=:release AND measure_id=:measure
         AND location_kind IN ('median','source_only') ORDER BY location_kind,geoid'''),
        {'release': p['release'], 'measure': p['measure']}).mappings().all()
    names = config['median_locations'] | config['source_only_locations']
    out = {'median': [], 'source_only': []}
    for r in rows:
        item = {'geography_id': r['geoid'], 'name': names[r['geoid']], **value_fields(r, base)}
        if r['location_kind'] == 'median':
            # For a median row CDC's sample-size column holds the number of jurisdictions, not respondents.
            item['jurisdictions'] = item.pop('sample_size')
            item['note'] = 'Median of the listed jurisdictions as published by CDC; not a national estimate; no confidence interval.'
        out[r['location_kind']].append(item)
    return out


def table(db, p, base, limit, offset, config):
    total = count(db, p)
    rows = db.execute(text(f'SELECT {FIELDS} {COMMON} ORDER BY b.geoid LIMIT :limit OFFSET :offset'),
                      p | {'limit': limit, 'offset': offset}).mappings().all()
    return base | {'total': total, 'limit': limit, 'offset': offset, 'rows': [
        {'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)} for r in rows],
        'reference': reference_rows(db, p, base, config)}
