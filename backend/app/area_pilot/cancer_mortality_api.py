"""NCI/CDC cancer mortality read model: published state and county rates with 95% intervals.

Every 2024 boundary state or county in the viewport is returned. Areas with no row in the release
(such as Connecticut's nine planning regions) are labelled ``not_in_release`` at read time.
Suppressed cells (fewer than 16 deaths in 2020–2024) are stored with status ``suppressed`` and
NULL value and interval, never zero. The national rate is returned as a separate reference.
"""
from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot import legend_breaks
from app.area_pilot.cancer_mortality import load_registry
from app.area_pilot.hds_mortality_api import CAP, NOT_IN_RELEASE, number
from app.geometry_sql import fitted_geom

S = 'area_pilot'
STATUS_TEXT = {
    'suppressed': 'Suppressed by NCI (fewer than 16 deaths in 2020–2024)',
}
COMMON = f'''FROM {S}.acs_boundary_2024 b
 LEFT JOIN {S}.observation_nci_cancer_mortality o ON o.geoid=b.geoid AND o.geo_level=b.level
  AND o.release_id=:release AND o.measure_id=:measure AND o.observation_period=:period
  AND o.population=:population AND o.value_type=:value_type
 WHERE b.level=:level
 AND b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
 AND ST_Intersects(b.geom,ST_MakeEnvelope(:west,:south,:east,:north,4326))'''
FIELDS = (
    f'''b.geoid AS geography_id,b.name,o.value,o.ci_low,o.ci_high,o.source_value,'''
    f'''COALESCE(o.status,'{NOT_IN_RELEASE}') AS status'''
)

LIMITATIONS = [
    "These are NCI's age-adjusted death rates for 2020–2024, with 95% confidence intervals. "
    'They are deaths, not new cases.',
    'Rates based on few deaths are suppressed by NCI. A suppressed county did not have zero deaths.',
    'Connecticut values are for its former counties and are not shown on the 2024 planning-region boundaries.',
]


def catalog(db):
    config = load_registry()
    active = db.execute(text(f'''SELECT a.release_id FROM {S}.active_release a JOIN {S}.release r
        ON r.id=a.release_id WHERE a.dataset_id=:dataset AND r.status='published' '''),
        {'dataset': config['dataset_id']}).scalar_one_or_none()
    releases = db.execute(text(f'''SELECT id,source_release_id,semantic_sha256,schema_sha256,
        metadata_sha256,published_at FROM {S}.release WHERE dataset_id=:dataset AND status='published'
        ORDER BY published_at DESC'''),
        {'dataset': config['dataset_id']}).mappings().all()
    return {
        key: config[key] for key in (
            'dataset_id', 'name', 'short_name', 'publisher', 'landing_page',
            'source_release_id', 'observation_period', 'population_label',
            'geographies', 'state_to_county_zoom', 'aggregation_method', 'value_type',
            'unit', 'uncertainty', 'measures',
        )
    } | {
        'boundary_vintage': config['boundary']['vintage'],
        'source_url': config['landing_page'],
        'missing_semantics': (
            'Suppressed cells ("*" in NCI files, fewer than 16 deaths in 2020–2024) are stored as '
            'suppressed with NULL value and NULL 95% confidence interval, never zero. '
            'Areas with no row in the release (such as Connecticut planning regions) are labelled not_in_release.'
        ),
        'tract_note': (
            'NCI State Cancer Profiles publishes these rates for the nation, states, and counties only. '
            'No tract estimates exist.'
        ),
        'status_text': STATUS_TEXT,
        'limitations': LIMITATIONS,
        'active_release_id': str(active) if active else None,
        'published_releases': [{**dict(r), 'id': str(r['id'])} for r in releases],
    }


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = load_registry()
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if dataset_id != config['dataset_id'] or measure is None:
        raise HTTPException(404, 'NCI cancer mortality selection not found')
    if geography == 'tract':
        raise HTTPException(
            400,
            'NCI cancer mortality has no tract estimates; state and county values are available',
        )
    if geography not in config['geographies']:
        raise HTTPException(
            400,
            'NCI cancer mortality is published for states and counties only',
        )
    if (period, population, value_type) != (
            measure['observation_period'], measure['population'], config['value_type']):
        raise HTTPException(
            400,
            'NCI cancer mortality selection period, population, or value_type does not match the catalog',
        )
    status = db.execute(text(f'SELECT status FROM {S}.release WHERE id=:release AND dataset_id=:dataset'),
                        {'release': release_id, 'dataset': dataset_id}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published NCI cancer mortality release not found')
    return config, measure


def ensure_cap(db, p):
    count = db.execute(text('SELECT count(*) FROM (SELECT 1 ' + COMMON + ' LIMIT :cap_limit) bounded'),
                       p | {'cap_limit': CAP + 1}).scalar_one()
    if count > CAP:
        raise HTTPException(413, 'Viewport contains more than 5,000 areas. Narrow the viewport.')
    return count


def metadata(config, measure, release_id, geography, bbox):
    return {
        'dataset_id': config['dataset_id'],
        'release_id': str(release_id),
        'measure_id': measure['measure_id'],
        'period': measure['observation_period'],
        'population': measure['population'],
        'value_type': config['value_type'],
        'geography': geography,
        'unit': measure['unit'],
        'kind': measure['kind'],
        'storage_scale': measure['storage_scale'],
        'denominator': measure['denominator'],
        'uncertainty': '95% confidence interval',
        'uncertainty_kind': 'ci95',
        'boundary_vintage': config['boundary']['vintage'],
        'bbox': bbox,
    }


def value_fields(row, base):
    fields = {
        'value': number(row['value']),
        'ci_low': number(row['ci_low']),
        'ci_high': number(row['ci_high']),
        'source_value': row['source_value'],
        'status': row['status'],
        'observation_period': base['period'],
        'measure_id': base['measure_id'],
        'value_type': base['value_type'],
        'uncertainty': '95% confidence interval',
    }
    if row['status'] in STATUS_TEXT:
        fields['status_text'] = STATUS_TEXT[row['status']]
    return fields


def map_data(db, p, count, base, simplify):
    rows = db.execute(text(f'''SELECT {FIELDS},
        ST_AsGeoJSON({fitted_geom('b.geom')})::json AS geometry
        {COMMON} ORDER BY b.geoid'''), p | {'simplify': simplify}).mappings().all()
    if len(rows) != count:
        raise HTTPException(409, 'Viewport changed during NCI cancer mortality map retrieval; retry')
    return base | {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'geometry': r['geometry'],
                'properties': {
                    'geography_id': r['geography_id'],
                    'name': r['name'],
                    **value_fields(r, base),
                },
            }
            for r in rows
        ],
        'count': count,
        'complete': True,
        'simplify': simplify,
    }


def national_reference(db, p):
    row = db.execute(text(f'''SELECT value,ci_low,ci_high,source_value,status
        FROM {S}.observation_nci_cancer_mortality
        WHERE release_id=:release AND measure_id=:measure AND geo_level='national' AND geoid='US'
        AND observation_period=:period AND population=:population AND value_type=:value_type'''),
        {
            'release': p['release'],
            'measure': p['measure'],
            'period': p['period'],
            'population': p['population'],
            'value_type': p['value_type'],
        }).mappings().one_or_none()
    if row is None:
        return None
    return {
        'value': number(row['value']),
        'ci_low': number(row['ci_low']),
        'ci_high': number(row['ci_high']),
        'source_value': row['source_value'],
        'status': row['status'],
        'note': 'NCI-published national value, shown for reference only; not computed by CHIP.',
    }


def quantile_breaks(db, p):
    """Release-wide quintile cut points for one level (never mixing national into state)."""
    row = db.execute(text(f'''SELECT count(*) AS n,
        percentile_cont(ARRAY[0.2,0.4,0.6,0.8]) WITHIN GROUP (ORDER BY value) AS cuts
        FROM {S}.observation_nci_cancer_mortality
        WHERE release_id=:release AND measure_id=:measure AND observation_period=:period
        AND population=:population AND value_type=:value_type AND geo_level=:level
        AND value IS NOT NULL AND status IN ('available','true_zero')'''),
        {key: p[key] for key in legend_breaks.KEYS if key in p}).mappings().one()
    if not row['n'] or row['n'] < 5 or row['cuts'] is None:
        return None
    return [float(cut) for cut in row['cuts']]


def legend(db, p, base):
    rows = db.execute(text(f'''SELECT COALESCE(o.status,'{NOT_IN_RELEASE}') AS status,count(*) AS n,
        min(o.value) AS low,max(o.value) AS high {COMMON} GROUP BY 1 ORDER BY 1'''), p).mappings().all()
    return base | {
        'limitations': LIMITATIONS,
        'national_reference': national_reference(db, p),
        'quantile_breaks': quantile_breaks(db, p),
        'quantile_basis': legend_breaks.BASIS,
        'statuses': [
            {'status': r['status'], 'n': r['n'], 'low': number(r['low']), 'high': number(r['high'])}
            | ({'status_text': STATUS_TEXT[r['status']]} if r['status'] in STATUS_TEXT else {})
            for r in rows
        ],
    }


def table(db, p, base, count, limit, offset):
    rows = db.execute(text(f'''SELECT {FIELDS} {COMMON} ORDER BY b.geoid LIMIT :limit OFFSET :offset'''),
                      p | {'limit': limit, 'offset': offset}).mappings().all()
    return base | {
        'total': count,
        'limit': limit,
        'offset': offset,
        'rows': [
            {'geography_id': r['geography_id'], 'name': r['name'], **value_fields(r, base)}
            for r in rows
        ],
    }
