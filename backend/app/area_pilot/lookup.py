"""Single-place reads of published shared products, for profiles, comparisons, and briefings.

The map API (`router.py`) answers viewport requests. This module answers "what is published for
these areas?" across every shared area product, using only each product's active published release.

Rules it keeps:

* Values are returned exactly as stored. Nothing is aggregated, averaged, ranked, or rescaled, and no
  value is inferred for a level a product does not publish.
* Each row carries its own measure, period, population, unit, uncertainty, release, and source.
* An area with no stored row gets an explicit read-time status that matches the product's map API
  (`no_reported_value`, `not_published`, `not_covered`, ...) or `not_in_release`; it is never zero.

The return shapes are the contract in docs/beta/DATA_CONTRACT.md. Change them only together.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import text

from app.area_pilot import (acs_api, acs_profile_api, ahrf_api, brfss_api, clh_api, cms_gv_api, cms_nursing_homes_api, epa_aqi_api,
                            hrsa_sites_api, tri_api, usda_fea_api)
from app.area_pilot.registry import load_registry as load_places_registry

S = 'area_pilot'
LEVELS = {'state': 2, 'county': 5, 'tract': 11, 'cd': 4}
# Every area CHIP can name: 2024 TIGER states, counties, tracts, and 119th Congress districts.
BOUNDARY = f'''(SELECT level,geoid,name,geom FROM {S}.acs_boundary_2024
  UNION ALL SELECT 'cd',geoid,name,geom FROM {S}.cd_boundary_119)'''
SLIVER = 0.001   # ignore county/district overlaps below 0.1% of the smaller area (shared edges)
MAX_GEOIDS = 200
FACILITY_ROW_CAP = 200
NOT_IN_RELEASE = 'not_in_release'

STATUS_TEXT = {
    'available': 'Published value',
    'true_zero': 'Published zero',
    'missing': 'Missing in the source file',
    'not_published': 'Not published by the source for this area',
    'suppressed': 'Suppressed by the source',
    'open_ended': 'Open-ended estimate (see annotation)',
    'not_applicable': 'Not applicable',
    'no_reported_value': 'No value reported (no monitor reported to EPA; not a statement about air quality)',
    'not_available': 'Not available (USDA -9999 or N/A)',
    'did_not_exist': 'County did not exist in that year (USDA -8888)',
    'boundary_not_comparable': 'Not published on this boundary (Connecticut planning region)',
    'not_covered': 'Outside the source coverage',
    'not_in_source': 'Not in the source file',
    NOT_IN_RELEASE: 'No row for this area in the published release',
}


class LookupError_(ValueError):
    """Invalid request (unknown level, malformed GEOID, too many areas)."""


@dataclass(frozen=True)
class Spec:
    key: str
    load: Callable[[], dict]
    tables: dict[str, tuple[str, str, str | None]]   # level -> (table, geoid column, level column)
    extra: tuple[str, ...]
    uncertainty: str                                  # 'ci95' | 'moe90' | 'none'
    api: Any


def _fea_missing(geoid: str, level: str) -> str:
    if geoid.startswith('72'):
        return 'not_covered'
    if re.fullmatch(r'091[1-9]0', geoid):
        return 'boundary_not_comparable'
    return 'not_in_source'


SPECS: tuple[Spec, ...] = (
    Spec('places', lambda: load_places_registry('tract'),
         {'county': ('observation', 'county_fips', None), 'tract': ('observation_tract', 'tract_fips', None)},
         ('ci_low', 'ci_high'), 'ci95', None),
    Spec('acs', acs_api.load_registry,
         {lvl: ('observation_acs', 'geoid', 'level') for lvl in ('state', 'county', 'tract')},
         ('moe', 'estimate_annotation', 'moe_annotation', 'moe_confidence'), 'moe90', acs_api),
    Spec('acs_profile', acs_profile_api.load_registry,
         {lvl: ('observation_acs_profile', 'geoid', 'level') for lvl in ('state', 'county', 'tract', 'cd')},
         ('moe', 'estimate_annotation', 'moe_annotation', 'moe_confidence'), 'moe90', acs_profile_api),
    Spec('brfss', brfss_api.load_registry, {'state': ('observation_brfss', 'geoid', None)},
         ('ci_low', 'ci_high', 'sample_size'), 'ci95', brfss_api),
    Spec('ahrf', ahrf_api.load_registry, {'county': ('observation_ahrf', 'geoid', None)},
         ('source_code',), 'none', ahrf_api),
    Spec('clh', clh_api.load_registry,
         {lvl: ('observation_clh', 'geoid', 'level') for lvl in ('county', 'tract')},
         ('source_code',), 'none', clh_api),
    Spec('cms_gv', cms_gv_api.load_registry,
         {lvl: ('observation_cms_gv', 'geoid', 'geo_level') for lvl in ('state', 'county')},
         ('source_value', 'source_desc'), 'none', cms_gv_api),
    Spec('epa_aqi', epa_aqi_api.load_registry, {'county': ('observation_epa_aqi', 'geoid', None)},
         ('days_with_aqi', 'value_note'), 'none', epa_aqi_api),
    Spec('usda_fea', usda_fea_api.load_registry, {'county': ('observation_usda_fea', 'geoid', None)},
         ('source_value', 'value_note'), 'none', usda_fea_api),
)
MISSING_STATUS: dict[str, Callable[[str, str], str]] = {
    # CDC's file has no row for a state and year it has no result for (Kentucky and Pennsylvania, 2023).
    'brfss': lambda geoid, level: brfss_api.NOT_PUBLISHED,
    'cms_gv': lambda geoid, level: cms_gv_api.NOT_PUBLISHED,
    'epa_aqi': lambda geoid, level: epa_aqi_api.NO_VALUE,
    'usda_fea': _fea_missing,
}


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value) if value.as_tuple().exponent >= 0 else float(value)
    return value


def _check(level: str, geoids: list[str]) -> list[str]:
    if level not in LEVELS:
        raise LookupError_(f'Unsupported level {level!r}; use state, county, tract, or cd')
    unique = list(dict.fromkeys(str(g).strip() for g in geoids))
    if not unique or len(unique) > MAX_GEOIDS:
        raise LookupError_(f'Provide between 1 and {MAX_GEOIDS} GEOIDs')
    for geoid in unique:
        if not re.fullmatch(rf'\d{{{LEVELS[level]}}}', geoid):
            raise LookupError_(f'{geoid!r} is not a {LEVELS[level]}-digit {level} GEOID')
    return unique


def _boundary_vintage(config: dict, level: str, spec_key: str | None = None):
    if spec_key == 'places' and level == 'county':
        config = load_places_registry('county')   # county rows join 2023 county shapes, not the tract vintage
    vintage = config.get('boundary_vintage') or (config.get('boundary') or {}).get('vintage')
    return vintage.get(level) if isinstance(vintage, dict) else vintage


def _measure_levels(spec: Spec, config: dict, measure: dict) -> list[str]:
    declared = measure.get('geographies') or config.get('geographies') or list(spec.tables)
    return [lvl for lvl in spec.tables if lvl in declared]


# AHRF's user guide states that AMA, ADA, and AHA data are subject to copyright. The credit travels with every
# value so pages and exports name the owner beside HRSA. It is attribution, not a statement of permission.
_AHRF = "as published in HRSA's Area Health Resources Files"
SOURCE_CREDITS = {
    ('ahrf', 'phys_nf_prim_care_pc_exc_rsdt_23'):
        f'Underlying data: AMA Physician Professional Data, © American Medical Association, {_AHRF}.',
    ('ahrf', 'md_nf_psych_all_pc_23'):
        f'Underlying data: AMA Physician Professional Data, © American Medical Association, {_AHRF}.',
    ('ahrf', 'dent_nf_fed_proflly_activ_23'):
        f'Underlying data: ADA Masterfile, © American Dental Association, {_AHRF}.',
    ('ahrf', 'hosp_23'):
        f'Underlying data: AHA Annual Survey of Hospitals, © American Hospital Association, {_AHRF}.',
    ('ahrf', 'hosp_beds_23'):
        f'Underlying data: AHA Annual Survey of Hospitals, © American Hospital Association, {_AHRF}.',
}


def _pairs() -> dict[tuple[str, str], dict]:
    """PLACES county/tract measures and the BRFSS state measure that asks the same question, both ways.

    The pairing is declared per measure in the BRFSS registry (`places_measure_id`). A BRFSS state
    figure is a direct survey estimate and a PLACES figure is modeled from that survey: a pair is
    context for the reader, never an input to a calculation.
    """
    pairs = {}
    for measure in brfss_api.load_registry()['measures']:
        if measure.get('places_measure_id'):
            pairs[('brfss', measure['measure_id'])] = {'product': 'places', 'measure_id': measure['places_measure_id']}
            pairs[('places', measure['places_measure_id'])] = {'product': 'brfss', 'measure_id': measure['measure_id']}
    return pairs


def _measure_meta(spec: Spec, config: dict, measure: dict) -> dict:
    source = measure.get('source')
    return {
        'product': spec.key, 'dataset_id': config['dataset_id'],
        'product_name': config.get('short_name') or config['name'], 'publisher': config['publisher'],
        'landing_page': config.get('landing_page'),
        'measure_id': measure['measure_id'], 'label': measure['label'],
        'unit': measure.get('unit') or config.get('unit'),
        'kind': measure.get('kind'), 'storage_scale': measure.get('storage_scale'),
        'category': measure.get('category') or measure.get('subcategory'),
        'period': measure['observation_period'], 'population': measure['population'],
        'value_type': config['value_type'], 'levels': _measure_levels(spec, config, measure),
        'uncertainty_kind': spec.uncertainty,
        'definition': measure.get('official_definition') or measure.get('official_label'),
        'denominator': measure.get('denominator'), 'interpretation': measure.get('interpretation'),
        'underlying_source': source if isinstance(source, str) else None,
        'source_credit': SOURCE_CREDITS.get((spec.key, measure['measure_id'])),
        'paired_measure': _pairs().get((spec.key, measure['measure_id'])),
    }


def _limitations(spec: Spec) -> list[str]:
    value = getattr(spec.api, 'LIMITATIONS', None)
    return list(value() if callable(value) else value or [])


def active_releases(db) -> dict[str, dict]:
    """Active published release per dataset_id, including the three point products."""
    rows = db.execute(text(f'''SELECT a.dataset_id,r.id,r.source_release_id,r.published_at
        FROM {S}.active_release a JOIN {S}.release r ON r.id=a.release_id
        WHERE r.status='published' ''')).mappings().all()
    return {r['dataset_id']: {'release_id': str(r['id']), 'source_release_id': r['source_release_id'],
                              'published_at': r['published_at'].isoformat() if r['published_at'] else None}
            for r in rows}


def catalog(db) -> dict:
    """Every measure a profile may show, with its product, levels, and active release."""
    releases = active_releases(db)
    products, measures = [], []
    for spec in SPECS:
        config = spec.load()
        release = releases.get(config['dataset_id'])
        products.append({
            'product': spec.key, 'dataset_id': config['dataset_id'],
            'name': config.get('short_name') or config['name'], 'publisher': config['publisher'],
            'landing_page': config.get('landing_page'), 'levels': list(spec.tables),
            'published': release is not None, 'release': release,
            'limitations': _limitations(spec),
        })
        for measure in config['measures']:
            measures.append(_measure_meta(spec, config, measure) | {'published': release is not None})
    return {'products': products, 'measures': measures, 'status_text': STATUS_TEXT}


OUTLINE_TOLERANCE = {'state': 0.02, 'county': 0.004, 'cd': 0.004, 'tract': 0.0005}   # degrees


def area_info(db, level: str, geoids: list[str], geometry: bool = False) -> list[dict]:
    """Name, parent areas, bounding box, and a point inside each area. Unknown GEOIDs are omitted.

    States, counties, and tracts use the 2024 TIGER boundaries; `cd` uses the 119th Congress districts.
    With `geometry=True` each record also carries `geometry`, a simplified GeoJSON outline for drawing
    a selection on a map. It is a display shape, not the stored boundary.
    """
    geoids = _check(level, geoids)
    outline = (',ST_AsGeoJSON(ST_SimplifyPreserveTopology(b.geom,:tolerance),5)::json AS geometry'
               if geometry else '')
    rows = db.execute(text(f'''SELECT b.geoid,b.name,ST_XMin(b.geom) AS west,ST_YMin(b.geom) AS south,
        ST_XMax(b.geom) AS east,ST_YMax(b.geom) AS north,
        ST_X(ST_PointOnSurface(b.geom)) AS lon,ST_Y(ST_PointOnSurface(b.geom)) AS lat,
        s.name AS state_name,c.name AS county_name{outline}
        FROM {BOUNDARY} b
        LEFT JOIN {S}.acs_boundary_2024 s ON s.level='state' AND s.geoid=left(b.geoid,2)
        LEFT JOIN {S}.acs_boundary_2024 c ON c.level='county' AND b.level='tract' AND c.geoid=left(b.geoid,5)
        WHERE b.level=:level AND b.geoid = ANY(:geoids) ORDER BY b.geoid'''),
        {'level': level, 'geoids': geoids} | ({'tolerance': OUTLINE_TOLERANCE[level]} if geometry else {})).mappings().all()
    return [({'geometry': r['geometry']} if geometry else {}) | {'level': level, 'geoid': r['geoid'], 'name': r['name'],
             'state_geoid': r['geoid'][:2], 'state_name': r['state_name'],
             'county_geoid': r['geoid'][:5] if level == 'tract' else (r['geoid'] if level == 'county' else None),
             'county_name': r['county_name'] if level == 'tract' else (r['name'] if level == 'county' else None),
             'bbox': [float(r['west']), float(r['south']), float(r['east']), float(r['north'])],
             'point': [float(r['lon']), float(r['lat'])],
             'boundary_vintage': '119th Congress (TIGER/Line 2024)' if level == 'cd' else 'TIGER/Line 2024'} for r in rows]


def _row(meta: dict, level: str, geoid: str, release: dict, config: dict, row, spec: Spec) -> dict:
    stored = row is not None
    status = row['status'] if stored else MISSING_STATUS.get(spec.key, lambda g, l: NOT_IN_RELEASE)(geoid, level)
    value = _num(row['value']) if stored else None
    if meta['kind'] == 'count' and isinstance(value, float) and value.is_integer():
        value = int(value)
    uncertainty = {'kind': spec.uncertainty}
    if spec.uncertainty == 'ci95':
        uncertainty |= {'low': _num(row['ci_low']) if stored else None, 'high': _num(row['ci_high']) if stored else None,
                        'label': '95% confidence interval'}
    elif spec.uncertainty == 'moe90':
        uncertainty |= {'moe': _num(row['moe']) if stored else None,
                        'label': f"{(row['moe_confidence'] if stored and row['moe_confidence'] else 90)}% margin of error"}
        if stored and row['moe'] is None and row['moe_annotation'] == '*****':
            uncertainty['label'] = 'No sampling margin: the estimate is controlled to official population totals'
    else:
        uncertainty |= {'label': 'No uncertainty published'}
    notes = {name: _num(row[name]) for name in spec.extra
             if stored and name not in ('ci_low', 'ci_high', 'moe', 'moe_confidence') and row[name] is not None}
    return {k: meta[k] for k in ('product', 'dataset_id', 'measure_id', 'label', 'unit', 'kind', 'storage_scale',
                                 'period', 'population', 'value_type', 'source_credit')} | {
        'level': level, 'geoid': geoid, 'value': value, 'status': status,
        'status_text': (getattr(spec.api, 'STATUS_TEXT', None) or {}).get(status) or STATUS_TEXT.get(status, status),
        'stored': stored,
        'uncertainty': uncertainty, 'notes': notes,
        'release_id': release['release_id'], 'source_release_id': release['source_release_id'],
        'boundary_vintage': _boundary_vintage(config, level, spec.key),
    }


def area_values(db, level: str, geoids: list[str], products: list[str] | None = None,
                measure_ids: list[str] | None = None) -> dict:
    """Published values for the given areas at exactly `level`.

    One row per (area, measure) for every measure published at that level, in registry order.
    Measures that a product does not publish at `level` are not returned (see `catalog`).
    """
    geoids = _check(level, geoids)
    releases = active_releases(db)
    values, used = [], {}
    for spec in SPECS:
        if (products and spec.key not in products) or level not in spec.tables:
            continue
        config = spec.load()
        release = releases.get(config['dataset_id'])
        if release is None:
            continue
        table, key, level_col = spec.tables[level]
        columns = ','.join(('measure_id', 'observation_period', 'population', 'value_type', 'value', 'status') + spec.extra)
        where = f'release_id=:release AND {key} = ANY(:geoids)' + (f' AND {level_col}=:level' if level_col else '')
        stored = {(r['geoid'], r['measure_id'], r['observation_period'], r['population'], r['value_type']): r
                  for r in db.execute(text(f'SELECT {key} AS geoid,{columns} FROM {S}.{table} WHERE {where}'),
                                      {'release': release['release_id'], 'geoids': geoids, 'level': level}).mappings()}
        for measure in config['measures']:
            if measure_ids and measure['measure_id'] not in measure_ids:
                continue
            meta = _measure_meta(spec, config, measure)
            if level not in meta['levels']:
                continue
            for geoid in geoids:
                row = stored.get((geoid, meta['measure_id'], meta['period'], meta['population'], meta['value_type']))
                values.append(_row(meta, level, geoid, release, config, row, spec))
        used[config['dataset_id']] = release
    return {'level': level, 'geoids': geoids, 'values': values, 'releases': used}


def national_reference(db) -> list[dict]:
    """National values that a source itself publishes (currently CMS Original Medicare GV only)."""
    spec = next(s for s in SPECS if s.key == 'cms_gv')
    config = spec.load()
    release = active_releases(db).get(config['dataset_id'])
    if release is None:
        return []
    rows = {r['measure_id']: r for r in db.execute(text(f'''SELECT measure_id,observation_period,population,value_type,
        value,status,source_value,source_desc FROM {S}.observation_cms_gv
        WHERE release_id=:release AND geo_level='national' AND geoid='US' '''), {'release': release['release_id']}).mappings()}
    out = []
    for measure in config['measures']:
        row = rows.get(measure['measure_id'])
        if row is not None:
            out.append(_row(_measure_meta(spec, config, measure), 'national', 'US', release, config, row, spec))
    return out


def county_tract_values(db, county_geoid: str, product: str, measure_id: str) -> dict:
    """All tract rows of one measure inside one county, for within-county patterns. No geometry.

    Tracts are matched by GEOID prefix in the product's own tract vintage; values are the published
    tract estimates and are not combined into a county figure.
    """
    (county_geoid,) = _check('county', [county_geoid])
    spec = next((s for s in SPECS if s.key == product), None)
    if spec is None or 'tract' not in spec.tables:
        raise LookupError_(f'{product!r} publishes no tract values')
    config = spec.load()
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    meta = _measure_meta(spec, config, measure) if measure else None
    if meta is None or 'tract' not in meta['levels']:
        raise LookupError_(f'{measure_id!r} is not published for tracts')
    release = active_releases(db).get(config['dataset_id'])
    if release is None:
        return {'county_geoid': county_geoid, 'measure': meta, 'values': [], 'release': None}
    table, key, level_col = spec.tables['tract']
    columns = ','.join(('value', 'status') + spec.extra)
    rows = db.execute(text(f'''SELECT {key} AS geoid,{columns} FROM {S}.{table}
        WHERE release_id=:release AND {key} LIKE :prefix AND measure_id=:measure AND observation_period=:period
        AND population=:population AND value_type=:value_type {"AND " + level_col + "='tract'" if level_col else ""}
        ORDER BY {key}'''), {'release': release['release_id'], 'prefix': county_geoid + '%', 'measure': measure_id,
                             'period': meta['period'], 'population': meta['population'],
                             'value_type': meta['value_type']}).mappings().all()
    return {'county_geoid': county_geoid, 'measure': meta, 'release': release,
            'values': [_row(meta, 'tract', r['geoid'], release, config, r, spec) for r in rows]}


WITHIN_PARENT = {'state': None, 'county': 'state', 'cd': 'state', 'tract': 'county'}


def measure_values_within(db, product: str, measure_id: str, level: str, parent_geoid: str | None = None,
                          period: str | None = None) -> dict:
    """One measure for every area at `level` inside a parent: all states, the counties or districts
    of one state, or the tracts of one county.

    The area list is the union of the CHIP boundaries inside the parent and the areas the release
    has rows for, so an area without a row comes back with the product's read-time status (never
    dropped and never zero), and source-only areas such as Connecticut's former counties are kept,
    with `name` None when no current boundary carries them. Rows have the `area_values` shape plus
    `name`, in GEOID order. Nothing is sorted by value, aggregated, or ranked here.
    `period` (optional) selects an earlier published period; None or the current period reads as before.
    """
    if period is not None:
        spec_ = next((s for s in SPECS if s.key == product), None)
        current_ = spec_.load() if spec_ else None
        measure_ = current_ and next((m for m in current_['measures'] if m['measure_id'] == measure_id), None)
        if measure_ and measure_['observation_period'] != period:
            return history_values_within(db, product, measure_id, level, parent_geoid, period)
    if level not in WITHIN_PARENT:
        raise LookupError_(f'Unsupported level {level!r}; use state, county, tract, or cd')
    parent_level = WITHIN_PARENT[level]
    if parent_level is None:
        if parent_geoid:
            raise LookupError_('State values are listed for the whole country; omit the parent GEOID')
        prefix = ''
    else:
        if not parent_geoid:
            raise LookupError_(f'{level} values are listed within one {parent_level}; provide its GEOID')
        (prefix,) = _check(parent_level, [parent_geoid])
    spec = next((s for s in SPECS if s.key == product), None)
    if spec is None:
        raise LookupError_(f'Unknown product {product!r}')
    config = spec.load()
    measure = next((m for m in config['measures'] if m['measure_id'] == measure_id), None)
    if measure is None:
        raise LookupError_(f'{product}:{measure_id} is not a CHIP measure')
    meta = _measure_meta(spec, config, measure)
    if level not in meta['levels']:
        raise LookupError_(f'{product}:{measure_id} is not published for {level}; '
                           f'it is published for {", ".join(meta["levels"]) or "no level"}')
    out = {'product': product, 'measure': meta, 'level': level, 'parent_level': parent_level,
           'parent_geoid': parent_geoid or None}
    release = active_releases(db).get(config['dataset_id'])
    if release is None:
        return out | {'release': None, 'values': []}
    names = {r['geoid']: r['name'] for r in db.execute(text(f'''SELECT geoid,name FROM {BOUNDARY} b
        WHERE level=:level AND geoid LIKE :prefix ORDER BY geoid'''),
        {'level': level, 'prefix': prefix + '%'}).mappings()}
    table, key, level_col = spec.tables[level]
    columns = ','.join(('value', 'status') + spec.extra)
    stored = {r['geoid']: r for r in db.execute(text(f'''SELECT {key} AS geoid,{columns}
        FROM {S}.{table} WHERE release_id=:release AND {key} LIKE :prefix AND measure_id=:measure AND observation_period=:period
        AND population=:population AND value_type=:value_type {"AND " + level_col + "=:level" if level_col else ""}'''),
        {'release': release['release_id'], 'prefix': prefix + '%', 'measure': measure_id, 'level': level,
         'period': meta['period'], 'population': meta['population'], 'value_type': meta['value_type']}).mappings()}
    values = [_row(meta, level, geoid, release, config, stored.get(geoid), spec) | {'name': names.get(geoid)}
              for geoid in sorted(set(names) | set(stored))]
    return out | {'release': release, 'values': values}


# --- facilities -----------------------------------------------------------------------------

_AREA = f'(SELECT geom FROM {BOUNDARY} area WHERE level=:level AND geoid=:geoid)'


def _facility_block(db, dataset_id, releases, count_sql, rows_sql, params, shape, method, limitations):
    release = releases.get(dataset_id)
    if release is None:
        return {'dataset_id': dataset_id, 'published': False, 'count': None, 'rows': [], 'truncated': False,
                'release': None, 'method': method, 'limitations': limitations}
    p = params | {'release': release['release_id'], 'cap': FACILITY_ROW_CAP}
    count = db.execute(text(count_sql), p).scalar_one()
    rows = [shape(r) for r in db.execute(text(rows_sql + ' LIMIT :cap'), p).mappings()]
    return {'dataset_id': dataset_id, 'published': True, 'count': count, 'rows': rows,
            'truncated': count > len(rows), 'release': release, 'method': method, 'limitations': limitations}


def area_facilities(db, level: str, geoid: str) -> dict:
    """Facilities from the three published point products located inside one state, county, or district.

    Counts are of mapped records only, the same records the map overlays draw. They are an
    inventory of listed sites, not a measure of capacity, access, exposure, or quality.
    """
    if level not in ('state', 'county', 'cd'):
        raise LookupError_('Facilities are listed for a state, county, or congressional district')
    (geoid,) = _check(level, [geoid])
    releases = active_releases(db)
    params = {'level': level, 'geoid': geoid}
    inside = f'ST_Contains({_AREA}, {{alias}}.geom)'

    hrsa_config = hrsa_sites_api.load_registry()
    hrsa_labels = hrsa_sites_api.labels(hrsa_config)
    defaults = hrsa_sites_api.parse_filters(hrsa_config, {})
    hrsa_where = f"FROM {S}.site_hrsa s WHERE s.release_id=:release AND s.location_status='mapped' AND s.eligible AND " + inside.format(alias='s')
    health_centers = _facility_block(
        db, hrsa_config['dataset_id'], releases, 'SELECT count(*) ' + hrsa_where,
        f'''SELECT s.site_id,s.site_name,s.organization_name,s.program_code,s.site_type_code,s.location_type_code,
            s.setting_code,s.city,s.state_abbr,ST_X(s.geom) AS lon,ST_Y(s.geom) AS lat {hrsa_where}
            ORDER BY s.site_name,s.site_id''', params,
        lambda r: {'site_id': r['site_id'], 'name': r['site_name'], 'organization': r['organization_name'],
                   'program': hrsa_labels['program'].get(r['program_code'], r['program_code']),
                   'site_type': hrsa_labels['site_type'].get(r['site_type_code'], r['site_type_code']),
                   'location_type': hrsa_labels['location_type'].get(r['location_type_code'], r['location_type_code']),
                   'setting': hrsa_labels['setting'].get(r['setting_code'], r['setting_code']),
                   'in_default_map_view': all(r[f'{name}_code'] in defaults[name] for name in hrsa_sites_api.FILTERS),
                   'city': r['city'], 'state': r['state_abbr'], 'point': [float(r['lon']), float(r['lat'])]},
        'Mapped, eligible HRSA sites whose published coordinates fall inside the area boundary (2024 TIGER, or 119th Congress district).',
        ['Sites without usable published coordinates, and locations HRSA suppresses, are not counted.',
         'A site listing is not a service area, capacity, or travel-time measure.'])

    nh_config = cms_nursing_homes_api.load_registry()
    nh_where = f"FROM {S}.cms_nursing_home n WHERE n.release_id=:release AND n.location_status='mapped' AND " + inside.format(alias='n')
    nursing_homes = _facility_block(
        db, cms_nursing_homes_api.PRODUCT, releases, 'SELECT count(*) ' + nh_where,
        f'''SELECT n.ccn,n.provider_name,n.city,n.state_abbr,n.provider_type,n.ownership_type,n.certified_beds,
            n.overall_rating,n.rating_footnotes,ST_X(n.geom) AS lon,ST_Y(n.geom) AS lat {nh_where}
            ORDER BY n.provider_name,n.ccn''', params,
        lambda r: {'ccn': r['ccn'], 'name': r['provider_name'], 'city': r['city'], 'state': r['state_abbr'],
                   'provider_type': r['provider_type'], 'ownership_type': r['ownership_type'],
                   'certified_beds': r['certified_beds'], 'overall_rating': r['overall_rating'],
                   'rating_footnotes': r['rating_footnotes'], 'point': [float(r['lon']), float(r['lat'])]},
        'CMS nursing homes whose published address coordinates fall inside the area boundary (2024 TIGER, or 119th Congress district).',
        ['Facilities with ZIP-based coordinates (CMS geocoding footnote) are not counted.',
         'Certified beds are not vacancies. Star ratings are not averaged and are not a live care assessment.',
         'A missing overall rating means unrated, not zero.'])
    nursing_homes['name'] = nh_config['name']

    tri_config = tri_api.load_registry()
    tri_where = (f"FROM {S}.tri_facility f WHERE f.release_id=:release AND f.location_status='mapped' AND "
                 + ('f.derived_county_geoid=:geoid' if level == 'county' else inside.format(alias='f')))
    tri = _facility_block(
        db, tri_config['dataset_id'], releases, 'SELECT count(*) ' + tri_where,
        f'''SELECT f.facility_id,f.facility_name,f.city,f.state_abbr,f.sector_codes,f.chemical_count,f.report_count,
            ST_X(f.geom) AS lon,ST_Y(f.geom) AS lat {tri_where} ORDER BY f.facility_name,f.facility_id''', params,
        lambda r: {'facility_id': r['facility_id'], 'name': r['facility_name'], 'city': r['city'],
                   'state': r['state_abbr'], 'sector_codes': r['sector_codes'],
                   'reported_chemicals': r['chemical_count'], 'forms': r['report_count'],
                   'point': [float(r['lon']), float(r['lat'])]},
        'EPA TRI reporting facilities whose coordinates fall inside the area boundary '
        '(county: the spatially derived county stored at publication).',
        ['Reporting to TRI does not mean a release occurred, a violation, a health risk, or current operation.',
         'Facilities below reporting thresholds or outside covered sectors do not appear; absence is not absence of pollution.'])

    health_centers['name'] = hrsa_config['name']
    tri['name'] = tri_config['name']
    return {'level': level, 'geoid': geoid, 'row_cap': FACILITY_ROW_CAP,
            'health_centers': health_centers, 'nursing_homes': nursing_homes, 'tri_facilities': tri}


# --- congressional districts ---------------------------------------------------------------

_OVERLAP = f'''SELECT c.geoid AS county_geoid,c.name AS county_name,s.name AS state_name,
    d.geoid AS district_geoid,d.name AS district_name,
    ST_Area(ST_Intersection(c.geom,d.geom)::geography) AS shared,
    ST_Area(c.geom::geography) AS county_area,ST_Area(d.geom::geography) AS district_area
    FROM {S}.cd_boundary_119 d JOIN {S}.acs_boundary_2024 c ON c.level='county'
      AND left(c.geoid,2)=d.state_fips AND c.geom && d.geom AND ST_Intersects(c.geom,d.geom)
    LEFT JOIN {S}.acs_boundary_2024 s ON s.level='state' AND s.geoid=d.state_fips'''
OVERLAP_NOTE = ('Shares are of total land and water area from the official boundaries. They are not population '
                'shares, and a county value is context for the district, never a district estimate.')


def _overlaps(db, where, params, order):
    out = []
    for r in db.execute(text(f'{_OVERLAP} WHERE {where}'), params).mappings():
        shared, county_area, district_area = float(r['shared']), float(r['county_area']), float(r['district_area'])
        if shared < SLIVER * min(county_area, district_area):
            continue
        county_share = shared / county_area
        out.append({'county_geoid': r['county_geoid'], 'county_name': r['county_name'], 'state_name': r['state_name'],
                    'district_geoid': r['district_geoid'], 'district_name': r['district_name'],
                    'county_area_share_in_district': round(min(county_share, 1.0), 4),
                    'district_area_share_in_county': round(min(shared / district_area, 1.0), 4),
                    'county_wholly_in_district': county_share >= 1 - SLIVER})
    return sorted(out, key=lambda item: item[order])


def district_counties(db, district_geoid: str) -> dict:
    """Counties whose 2024 boundary overlaps one 119th Congress district."""
    (district_geoid,) = _check('cd', [district_geoid])
    return {'district_geoid': district_geoid, 'note': OVERLAP_NOTE,
            'counties': _overlaps(db, 'd.geoid=:geoid', {'geoid': district_geoid}, 'county_geoid')}


def county_districts(db, county_geoid: str) -> dict:
    """119th Congress districts that overlap one county."""
    (county_geoid,) = _check('county', [county_geoid])
    return {'county_geoid': county_geoid, 'note': OVERLAP_NOTE,
            'districts': _overlaps(db, 'c.geoid=:geoid', {'geoid': county_geoid}, 'district_geoid')}


def state_districts(db, state_geoid: str) -> list[dict]:
    """All 119th Congress districts of one state (for search and navigation)."""
    (state_geoid,) = _check('state', [state_geoid])
    return [dict(r) for r in db.execute(text(f'''SELECT geoid,name,district_code FROM {S}.cd_boundary_119
        WHERE state_fips=:state ORDER BY geoid'''), {'state': state_geoid}).mappings()]


def state_counties(db, state_geoid: str) -> list[dict]:
    """All counties of one state on the 2024 TIGER boundaries (for navigation). No values."""
    (state_geoid,) = _check('state', [state_geoid])
    return [dict(r) for r in db.execute(text(f"""SELECT geoid,name FROM {S}.acs_boundary_2024
        WHERE level='county' AND left(geoid,2)=:state ORDER BY name,geoid"""), {'state': state_geoid}).mappings()]


def states(db) -> list[dict]:
    """Every state-level area CHIP can name (50 states, DC, Puerto Rico), for search."""
    return [dict(r) for r in db.execute(text(f"""SELECT geoid,name FROM {S}.acs_boundary_2024
        WHERE level='state' ORDER BY name""")).mappings()]


def state_survey_companions(db, state_geoid: str) -> dict:
    """BRFSS state survey rows keyed by the PLACES measure each one pairs with.

    For a county or tract profile: `companions[places_measure_id]` is the state's own BRFSS row
    (value, 95% confidence interval, status, period, release), or a `not_published` row when CDC
    has no result for that state and year. PLACES measures without a pair are absent.
    """
    (state_geoid,) = _check('state', [state_geoid])
    result = area_values(db, 'state', [state_geoid], products=['brfss'])
    pairs = _pairs()
    companions = {}
    for row in result['values']:
        pair = pairs.get(('brfss', row['measure_id']))
        if pair:
            companions[pair['measure_id']] = row
    return {'state_geoid': state_geoid, 'companions': companions, 'releases': result['releases'],
            'note': ('State survey estimate (BRFSS). The county or tract figure is modeled from the same survey; '
                     'the state figure is context, not a benchmark for ranking.')}


def brfss_medians(db) -> list[dict]:
    """CDC's published "All States and DC (median)" row per BRFSS measure.

    A median of state values, not a national estimate, and published without a confidence interval.
    """
    spec = next(s for s in SPECS if s.key == 'brfss')
    config = spec.load()
    release = active_releases(db).get(config['dataset_id'])
    if release is None:
        return []
    rows = {r['measure_id']: r for r in db.execute(text(f"""SELECT measure_id,value,sample_size,status
        FROM {S}.observation_brfss WHERE release_id=:release AND geoid='98' AND location_kind='median'"""),
        {'release': release['release_id']}).mappings()}
    out = []
    for measure in config['measures']:
        row = rows.get(measure['measure_id'])
        if row is not None:
            meta = _measure_meta(spec, config, measure)
            out.append({k: meta[k] for k in ('product', 'dataset_id', 'measure_id', 'label', 'unit', 'kind', 'period',
                                             'population', 'value_type', 'paired_measure')} | {
                'reference_kind': 'median_of_states_and_dc', 'reference_label': config['median_locations']['98'],
                'value': _num(row['value']), 'status': row['status'], 'jurisdictions': row['sample_size'],
                'uncertainty': {'kind': 'none', 'label': 'CDC publishes this median without a confidence interval'},
                'release_id': release['release_id'], 'source_release_id': release['source_release_id']})
    return out


# --- earlier periods (history releases) --------------------------------------------------------
# Profiles never call these. Each history value carries its own period, release, boundary vintage,
# and comparability note; nothing here combines periods or computes a change.

def _history(spec_key: str):
    from app.area_pilot.history_api import active_release, config_for
    spec = next((s for s in SPECS if s.key == spec_key), None)
    if spec is None:
        raise LookupError_(f'Unknown product {spec_key!r}')
    current = spec.load()
    return spec, current, config_for(current['dataset_id']), active_release


def measure_periods(db, product: str, measure_id: str) -> list[dict]:
    """Every published period of one measure, current first, then earlier periods newest first."""
    from app.area_pilot.history_api import active_release, periods_for
    spec, current, hconfig, _ = _history(product)
    measure = next((m for m in current['measures'] if m['measure_id'] == measure_id), None)
    if measure is None:
        raise LookupError_(f'{product}:{measure_id} is not a CHIP measure')
    release = active_releases(db).get(current['dataset_id'])
    history = active_release(db, hconfig) if hconfig else None
    return periods_for(hconfig, measure, release['release_id'] if release else None, history)


def _history_period(db, product: str, measure_id: str, period: str):
    """(spec, current config, history config, measure meta for that period, period spec, history release)."""
    from app.area_pilot.history_api import active_release
    spec, current, hconfig, _ = _history(product)
    measure = next((m for m in current['measures'] if m['measure_id'] == measure_id), None)
    if measure is None:
        raise LookupError_(f'{product}:{measure_id} is not a CHIP measure')
    entry = hconfig and hconfig['_index'].get((measure_id, period))
    if not entry or not entry[1].get('available', True):
        published = [p['period'] for p in measure_periods(db, product, measure_id) if p['available']]
        raise LookupError_(f'{product}:{measure_id} is not published for {period!r}; '
                           f'published periods: {", ".join(published)}')
    release = active_release(db, hconfig)
    if release is None:
        raise LookupError_(f'Earlier periods of {product} are not published yet')
    hmeasure, pspec = entry
    meta = _measure_meta(spec, current, measure) | {
        'period': period, 'population': pspec.get('population', hmeasure['population']),
        'value_type': hmeasure['value_type'], 'levels': hmeasure.get('levels', hconfig['levels'])}
    rel = {'release_id': str(release['id']), 'source_release_id': release['source_release_id']}
    return spec, current, hconfig, meta, pspec, rel


def _history_row(meta, level, geoid, release, hconfig, pspec, row, spec):
    from app.area_pilot.history_api import VINTAGE_LABEL
    adapted = None
    if row is not None:
        adapted = {'value': row['value'], 'status': row['status'], 'ci_low': row['low'], 'ci_high': row['high'],
                   'moe': row['moe'], 'moe_confidence': None, 'moe_annotation': None} | {n: None for n in spec.extra
                                                                                           if n not in ('ci_low', 'ci_high', 'moe')}
    out = _row(meta, level, geoid, release, {}, adapted, spec)
    if row is None and hconfig.get('absent_status'):
        status = next((s for p, s in hconfig.get('absent_status_by_prefix', {}).items() if geoid.startswith(p)),
                      hconfig['absent_status'])
        out |= {'status': status, 'status_text': (getattr(spec.api, 'STATUS_TEXT', None) or {}).get(status)
                or STATUS_TEXT.get(status, status)}
    return out | {'boundary_vintage': VINTAGE_LABEL[pspec['boundary_vintage'][level]], 'note': pspec['note'],
                  'current_period': False}


def _history_names(db, level: str, vintage: str, prefix: str = '', geoids: list[str] | None = None) -> dict:
    from app.area_pilot.history_api import _boundary_sql
    where = ' AND b.geoid = ANY(:geoids)' if geoids is not None else ' AND b.geoid LIKE :prefix'
    return {r['geoid']: r['name'] for r in db.execute(text(f'''SELECT b.geoid,b.name
        FROM {_boundary_sql(level, vintage)} b WHERE true{where}'''),
        {'level': level, 'vintage': vintage, 'prefix': prefix + '%', 'geoids': geoids}).mappings()}


def area_values_for_period(db, level: str, geoids: list[str], period: str, measure_keys: list[tuple[str, str]]) -> dict:
    """Values of the given (product, measure_id) pairs for one period. The current period is read
    exactly as `area_values` reads it; an earlier period comes from that product's history release.
    Pairs with nothing published for `period` or `level` are listed in `unavailable` with a reason."""
    geoids = _check(level, geoids)
    values, releases, unavailable = [], {}, []
    for product, measure_id in measure_keys:
        spec = next((s for s in SPECS if s.key == product), None)
        if spec is None:
            raise LookupError_(f'Unknown product {product!r}')
        current = spec.load()
        measure = next((m for m in current['measures'] if m['measure_id'] == measure_id), None)
        if measure is None:
            raise LookupError_(f'{product}:{measure_id} is not a CHIP measure')
        if measure['observation_period'] == period:
            result = area_values(db, level, geoids, [product], [measure_id])
            values += [v | {'current_period': True, 'note': None} for v in result['values']]
            releases |= result['releases']
            if not result['values']:
                unavailable.append({'product': product, 'measure_id': measure_id,
                                    'reason': f'not published for {level}'})
            continue
        try:
            spec, current, hconfig, meta, pspec, release = _history_period(db, product, measure_id, period)
        except LookupError_ as exc:
            unavailable.append({'product': product, 'measure_id': measure_id, 'reason': str(exc)})
            continue
        if level not in meta['levels']:
            unavailable.append({'product': product, 'measure_id': measure_id,
                                'reason': f'not published for {level} in {period}'})
            continue
        rows = {r['geoid']: r for r in db.execute(text(f'''SELECT geoid,value,status,low,high,moe
            FROM {S}.observation_history WHERE release_id=:release AND level=:level AND measure_id=:measure
            AND observation_period=:period AND geoid = ANY(:geoids)'''),
            {'release': release['release_id'], 'level': level, 'measure': measure_id, 'period': period,
             'geoids': geoids}).mappings()}
        for geoid in geoids:
            values.append(_history_row(meta, level, geoid, release, hconfig, pspec, rows.get(geoid), spec))
        releases[hconfig['dataset_id']] = release
    return {'level': level, 'geoids': geoids, 'period': period, 'values': values, 'releases': releases,
            'unavailable': unavailable}


def history_values_within(db, product: str, measure_id: str, level: str, parent_geoid: str | None,
                          period: str) -> dict:
    """`measure_values_within` for an earlier period, on that period's own boundaries."""
    parent_level = WITHIN_PARENT.get(level, 'invalid')
    if parent_level == 'invalid':
        raise LookupError_(f'Unsupported level {level!r}; use state, county, or tract')
    if level == 'cd':
        raise LookupError_('Congressional districts have no earlier periods in CHIP: older Congresses had different districts')
    if parent_level is None:
        if parent_geoid:
            raise LookupError_('State values are listed for the whole country; omit the parent GEOID')
        prefix = ''
    else:
        if not parent_geoid:
            raise LookupError_(f'{level} values are listed within one {parent_level}; provide its GEOID')
        (prefix,) = _check(parent_level, [parent_geoid])
    spec, current, hconfig, meta, pspec, release = _history_period(db, product, measure_id, period)
    if level not in meta['levels']:
        raise LookupError_(f'{product}:{measure_id} is not published for {level} in {period}')
    vintage = pspec['boundary_vintage'][level]
    names = _history_names(db, level, vintage, prefix)
    stored = {r['geoid']: r for r in db.execute(text(f'''SELECT geoid,value,status,low,high,moe
        FROM {S}.observation_history WHERE release_id=:release AND level=:level AND measure_id=:measure
        AND observation_period=:period AND geoid LIKE :prefix'''),
        {'release': release['release_id'], 'level': level, 'measure': measure_id, 'period': period,
         'prefix': prefix + '%'}).mappings()}
    geoids = sorted(set(names) | set(stored)) if hconfig.get('absent_status') else sorted(stored)
    values = [_history_row(meta, level, g, release, hconfig, pspec, stored.get(g), spec) | {'name': names.get(g)}
              for g in geoids]
    return {'product': product, 'measure': meta | {'note': pspec['note']}, 'level': level,
            'parent_level': parent_level, 'parent_geoid': parent_geoid or None, 'release': release, 'values': values}


def area_measure_series(db, level: str, geoid: str, product: str, measure_id: str) -> dict:
    """One measure for one area in every published period, oldest first. Values are side by side as
    published; periods can differ in method or boundaries (see each row's `note`). No change is computed."""
    (geoid,) = _check(level, [geoid])
    periods = measure_periods(db, product, measure_id)
    series, unavailable = [], []
    for item in sorted(periods, key=lambda p: p['period']):
        if not item['available']:
            unavailable.append({'period': item['period'], 'reason': item['note'] or 'not published'})
            continue
        result = area_values_for_period(db, level, [geoid], item['period'], [(product, measure_id)])
        if result['values']:
            series.extend(result['values'])
        else:
            unavailable.extend({'period': item['period'], 'reason': u['reason']} for u in result['unavailable'])
    return {'level': level, 'geoid': geoid, 'product': product, 'measure_id': measure_id,
            'series': series, 'unavailable_periods': unavailable}
