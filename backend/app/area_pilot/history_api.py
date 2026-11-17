"""Map, legend, and table reads for earlier periods, plus the catalog ``periods`` list.

A request whose period is a declared earlier period of a product with a history registry is
served here from ``observation_history`` and that period's own boundary vintage. Current-period
requests never reach this module, so the current maps and every profile read are unchanged.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import text

from app.area_pilot import legend_breaks
from app.area_pilot.history.registry import load_history_registry, products
from app.geometry_sql import fitted_geom

S = 'area_pilot'
CAP = 5000
COLOURS_NOTE = ('Colour classes are computed for this year only. The same colour can mean a different value '
                'in another year, so compare values, not colours.')
VINTAGE_LABEL = {'2024': 'TIGER/Line 2024', '2020': 'TIGER/Line 2020 (Connecticut former counties)',
                 '2019': 'TIGER/Line 2019 tracts (2010 Census basis)'}
ID_ALIAS = {'cdc_places_county_2025_pilot': {'county': 'county_fips', 'tract': 'tract_fips'}}


@lru_cache(maxsize=None)
def _by_dataset() -> dict:
    return {load_history_registry(p)['current_dataset_id']: p for p in products()}


def config_for(dataset_id: str) -> dict | None:
    product = _by_dataset().get(dataset_id)
    return load_history_registry(product) if product else None


def is_history_request(dataset_id: str, measure_id: str, period: str) -> bool:
    config = config_for(dataset_id)
    if not config:
        return False
    entry = config['_index'].get((measure_id, period))
    return bool(entry) and entry[0]['current_period'] != period


def active_release(db, config) -> dict | None:
    row = db.execute(text(f'''SELECT r.id,r.source_release_id,r.published_at FROM {S}.active_release a
        JOIN {S}.release r ON r.id=a.release_id WHERE a.dataset_id=:dataset AND r.status='published' '''),
        {'dataset': config['dataset_id']}).mappings().one_or_none()
    return dict(row) if row else None


def periods_for(config: dict | None, measure: dict, current_release_id, history_release) -> list[dict]:
    """Current period first, then each declared earlier period, newest first."""
    result = [{'period': measure.get('observation_period'), 'current': True, 'available': True,
               'release_id': current_release_id, 'note': None, 'boundary_vintage': None}]
    if not config:
        return result
    entry = next((m for m in config['measures'] if m['measure_id'] == measure.get('measure_id')), None)
    if entry is None:
        return result
    for spec in sorted(entry['periods'], key=lambda p: p['period'], reverse=True):
        # Declared periods are listed, disabled, until the history release is published.
        available = bool(history_release) and spec.get('available', True)
        result.append({'period': spec['period'], 'current': False, 'available': available,
                       'release_id': str(history_release['id']) if available else None,
                       'note': spec['note'] if history_release else 'Not yet published in CHIP.',
                       'levels': entry.get('levels', config['levels']),
                       'boundary_vintage': {lvl: VINTAGE_LABEL[v] for lvl, v in spec['boundary_vintage'].items()}})
    return result


def attach_periods(db, payload: dict) -> dict:
    """Add ``periods`` to every catalog measure and ``history_release`` to the catalog."""
    config = config_for(payload.get('dataset_id', ''))
    history = active_release(db, config) if config else None
    for measure in payload.get('measures', []):
        measure['periods'] = periods_for(config, measure, payload.get('active_release_id'), history)
    payload['history_release'] = ({'id': str(history['id']), 'source_release_id': history['source_release_id'],
                                   'published_at': history['published_at'].isoformat() if history['published_at'] else None}
                                  if history else None)
    payload['history_colour_note'] = COLOURS_NOTE
    return payload


def _current_measure(dataset_id: str, measure_id: str) -> dict:
    """The current registry entry (unit, kind, fixed legend breaks), via the lookup product spec."""
    from app.area_pilot.lookup import SPECS
    for spec in SPECS:
        current = spec.load()
        if current['dataset_id'] == dataset_id:
            return next((m for m in current['measures'] if m['measure_id'] == measure_id), {}) | {
                '_unit': current.get('unit'), '_config': current}
    return {}


def selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography):
    config = config_for(dataset_id)
    entry = config and config['_index'].get((measure_id, period))
    if not entry or not entry[1].get('available', True):
        raise HTTPException(400, 'This measure is not published for that period')
    measure, spec = entry
    if geography not in measure.get('levels', config['levels']):
        raise HTTPException(400, f'No {geography} values are published for this measure in {period}')
    if population != spec.get('population', measure['population']) or value_type != measure['value_type']:
        raise HTTPException(400, 'Measure, period, or population is unavailable')
    status = db.execute(text(f'SELECT status FROM {S}.release WHERE id=:id AND dataset_id=:dataset'),
                        {'id': release_id, 'dataset': config['dataset_id']}).scalar_one_or_none()
    if status != 'published':
        raise HTTPException(404, 'Published history release not found')
    return config, measure, spec


def _boundary_sql(level: str, vintage: str) -> str:
    if level == 'state' or vintage == '2024':
        return f"(SELECT geoid,name,geom FROM {S}.acs_boundary_2024 WHERE level=:level)"
    return f"(SELECT geoid,name,geom FROM {S}.history_boundary WHERE vintage=:vintage AND level=:level)"


def _common(config, level, vintage) -> str:
    join = 'LEFT JOIN' if config.get('absent_status') else 'JOIN'
    return f'''FROM {_boundary_sql(level, vintage)} b {join} {S}.observation_history o
        ON o.geoid=b.geoid AND o.release_id=:release AND o.measure_id=:measure AND o.observation_period=:period
        AND o.level=:level AND o.population=:population AND o.value_type=:value_type
        WHERE b.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
        AND ST_Intersects(b.geom, ST_MakeEnvelope(:west,:south,:east,:north,4326))'''


def _status_sql(config) -> str:
    absent = config.get('absent_status')
    if not absent:
        return 'o.status'
    cases = ''.join(f" WHEN b.geoid LIKE '{prefix}%' THEN '{status}'"
                    for prefix, status in config.get('absent_status_by_prefix', {}).items()
                    if prefix.isdigit() and status.isidentifier())
    return f"COALESCE(o.status, CASE{cases} ELSE '{absent}' END)" if cases else f"COALESCE(o.status,'{absent}')"


def _num(value):
    return float(value) if value is not None else None


def _base(db, config, measure, spec, p, geography, bbox, dataset_id):
    current = _current_measure(dataset_id, measure['measure_id'])
    breaks = current.get('legend_breaks')
    if isinstance(breaks, dict):
        breaks = breaks.get(geography)
    vintage = spec['boundary_vintage'][geography]
    return {'dataset_id': dataset_id, 'history_dataset_id': config['dataset_id'], 'history': True,
            'release_id': str(p['release']), 'measure_id': measure['measure_id'], 'period': p['period'],
            'population': p['population'], 'value_type': p['value_type'], 'geography': geography,
            'unit': current.get('unit') or current.get('_unit'), 'bbox': bbox, 'note': spec['note'],
            'boundary_vintage': VINTAGE_LABEL[vintage], 'legend_breaks': breaks,
            'colour_note': COLOURS_NOTE, 'uncertainty_kind': measure.get('uncertainty_kind',
                                                                          config.get('uncertainty_kind', 'none'))}


def _params(release_id, measure_id, period, population, value_type, geography, bounds, vintage):
    return dict(release=release_id, measure=measure_id, period=period, population=population,
                value_type=value_type, level=geography, vintage=vintage, **bounds)


def _prepare(db, dataset_id, release_id, measure_id, period, population, value_type, geography, bounds):
    config, measure, spec = selection(db, dataset_id, release_id, measure_id, period, population, value_type, geography)
    p = _params(release_id, measure_id, period, population, value_type, geography, bounds,
                spec['boundary_vintage'][geography])
    common = _common(config, geography, p['vintage'])
    count = db.execute(text('SELECT count(*) ' + common), p).scalar_one()
    if count > CAP:
        raise HTTPException(413, f'Viewport contains more than {CAP} {geography} areas. Zoom in or narrow the viewport.')
    return config, measure, spec, p, common, count


def _fields(r, period, measure_id, alias):
    item = {'geography_id': r['geoid'], 'name': r['name'], 'value': _num(r['value']), 'ci_low': _num(r['low']),
            'ci_high': _num(r['high']), 'moe': _num(r['moe']), 'status': r['status'],
            'source_value': r['source_value'], 'observation_period': period, 'measure_id': measure_id}
    if alias:
        item[alias] = r['geoid']
    return item


def map_data(db, dataset_id, release_id, measure_id, period, population, value_type, geography, bounds, bbox, simplify):
    config, measure, spec, p, common, count = _prepare(db, dataset_id, release_id, measure_id, period,
                                                       population, value_type, geography, bounds)
    rows = db.execute(text(f'''SELECT b.geoid,b.name,ST_AsGeoJSON({fitted_geom('b.geom')})::json AS geometry,
        o.value,o.low,o.high,o.moe,o.source_value,{_status_sql(config)} AS status {common} ORDER BY b.geoid'''),
        p | {'simplify': simplify}).mappings().all()
    alias = ID_ALIAS.get(dataset_id, {}).get(geography)
    features = [{'type': 'Feature', 'geometry': r['geometry'],
                 'properties': _fields(r, period, measure_id, alias)} for r in rows]
    if len(features) != count:
        raise HTTPException(409, 'Viewport changed during map retrieval; retry the request')
    return _base(db, config, measure, spec, p, geography, bbox, dataset_id) | {
        'type': 'FeatureCollection', 'features': features, 'count': count, 'complete': True, 'simplify': simplify}


def legend(db, dataset_id, release_id, measure_id, period, population, value_type, geography, bounds, bbox):
    config, measure, spec, p, common, _ = _prepare(db, dataset_id, release_id, measure_id, period,
                                                   population, value_type, geography, bounds)
    stats = db.execute(text(f'''SELECT {_status_sql(config)} AS status,count(*) AS n,min(o.value) AS low,
        max(o.value) AS high {common} GROUP BY 1 ORDER BY 1'''), p).mappings().all()
    unmatched = db.execute(text(f'''SELECT count(*) FROM {S}.observation_history o
        WHERE o.release_id=:release AND o.measure_id=:measure AND o.observation_period=:period AND o.level=:level
        AND NOT EXISTS (SELECT 1 FROM {_boundary_sql(geography, p['vintage'])} b WHERE b.geoid=o.geoid)'''),
        p).scalar_one()
    base = _base(db, config, measure, spec, p, geography, bbox, dataset_id)
    return base | {'statuses': [{'status': r['status'], 'n': r['n'], 'low': _num(r['low']), 'high': _num(r['high'])}
                                for r in stats],
                   'published_without_boundary': unmatched,
                   **legend_breaks.legend_fields(db, f'{S}.observation_history', p, by_level=True)}


def table(db, dataset_id, release_id, measure_id, period, population, value_type, geography, bounds, bbox,
          limit, offset):
    config, measure, spec, p, common, count = _prepare(db, dataset_id, release_id, measure_id, period,
                                                       population, value_type, geography, bounds)
    rows = db.execute(text(f'''SELECT b.geoid,b.name,o.value,o.low,o.high,o.moe,o.source_value,
        {_status_sql(config)} AS status {common} ORDER BY b.geoid LIMIT :limit OFFSET :offset'''),
        p | {'limit': limit, 'offset': offset}).mappings().all()
    alias = ID_ALIAS.get(dataset_id, {}).get(geography)
    return _base(db, config, measure, spec, p, geography, bbox, dataset_id) | {
        'total': count, 'limit': limit, 'offset': offset,
        'rows': [_fields(r, period, measure_id, alias) for r in rows]}
