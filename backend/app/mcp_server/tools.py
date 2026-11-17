"""Seven read-only MCP operations; all database reads use the approved lookup layer."""
import json
import logging
import re
import time
from datetime import datetime, timezone
from mcp.server.mcpserver.exceptions import ToolError
from app import db as db_module
from app.area_pilot import lookup
from . import cache, measures, places
from .config import FACILITY_PRODUCTS, LEVELS, MAX_BYTES, MAX_ROWS, ORDER_WARNING, PUBLIC_PRODUCTS, WITHHELD_TOPIC_WARNING
from .envelope import Envelope, build, compact_value_row, fit_rows, size_bytes, value_row, citation

log = logging.getLogger(__name__)

FACILITY_PUBLISHERS = {
    'health_centers': 'Health Resources and Services Administration',
    'nursing_homes': 'Centers for Medicare & Medicaid Services',
    'tri_facilities': 'Environmental Protection Agency',
}


def _facility_sources(blocks):
    sources = []
    for key in FACILITY_PRODUCTS:
        block = blocks[key]
        release = block.get('release')
        if not block.get('published') or not release:
            continue
        sources.append({'dataset_id': block['dataset_id'], 'product': key,
                        'product_name': block['name'], 'publisher': FACILITY_PUBLISHERS[key],
                        'release_id': release.get('release_id'),
                        'source_release_id': release.get('source_release_id'),
                        'published_at': release.get('published_at'), 'landing_page': None})
    return sources


def _facility_rules(response, blocks):
    for key in FACILITY_PRODUCTS:
        if blocks[key].get('published'):
            response.interpretation_rules.extend(rule for rule in blocks[key]['limitations']
                                                 if rule not in response.interpretation_rules)


def _validate_level(level):
    if level not in LEVELS:
        raise ToolError('Unknown level; use state, county, tract, or cd')


def _validate_geoid(level, geoid):
    if not isinstance(geoid, str) or not re.fullmatch(rf'\d{{{LEVELS[level]}}}', geoid):
        raise ToolError(f'Use find_places to look up the {LEVELS[level]}-digit {level} GEOID')


def _measure_key(key):
    if not isinstance(key, str) or ':' not in key:
        raise ToolError('Use search_measures to find a measure key such as places:diabetes_crudeprev')
    product, measure_id = key.split(':', 1)
    if product == 'ahrf':
        raise ToolError('AHRF is not available through the public server; use search_measures for public measures')
    if product not in PUBLIC_PRODUCTS:
        raise ToolError('Unknown product; use search_measures to find a public measure key')
    if not measure_id:
        raise ToolError('Use search_measures to find a complete measure key')
    return product, measure_id


def _catalog(db):
    return lookup.catalog(db)


def _products(catalog):
    return {p['product']: p for p in catalog['products'] if p['product'] in PUBLIC_PRODUCTS}


def _measure(catalog, key):
    product, measure_id = _measure_key(key)
    found = next((m for m in catalog['measures'] if m['product'] == product and m['measure_id'] == measure_id), None)
    return found


def _used(catalog, keys):
    products = _products(catalog)
    return [products[p] for p in sorted(set(keys)) if p in products]


def _topics_for(key):
    return measures.topic_map().get(key, [])


def _run(name, args, work):
    start = time.monotonic()
    cached = False
    error = None
    rows = 0
    session = db_module.SessionLocal()
    try:
        fingerprint = lookup.active_releases(session)
        key = cache.key(name, args, fingerprint)
        result = cache.get(key)
        if result is None:
            result = work(session)
            cache.put(key, result)
        else:
            cached = True
        data = result.data
        rows = sum(len(data[k]) for k in ('values', 'with_value', 'without_value', 'matches', 'measures') if isinstance(data.get(k), list))
        return result
    except (ToolError, lookup.LookupError_) as exc:
        error = type(exc).__name__
        if isinstance(exc, lookup.LookupError_):
            raise ToolError(str(exc)) from exc
        raise
    except Exception as exc:
        error = type(exc).__name__
        log.exception('MCP tool failed: %s', name)
        raise ToolError('Internal error; please retry or narrow the request') from exc
    finally:
        session.close()
        print(json.dumps({'ts': datetime.now(timezone.utc).isoformat(), 'tool': name,
                          'arguments': json.dumps(args, default=str)[:500],
                          'duration_ms': round((time.monotonic() - start) * 1000, 2),
                          'row_count': rows, 'cached': cached, 'error_class': error}), flush=True)


def find_places(query: str, levels: list[str] | None = None, limit: int = 10) -> Envelope:
    def work(db):
        if not isinstance(query, str) or not query.strip():
            raise ToolError('Provide a place name, abbreviation, or FIPS code')
        if not 1 <= limit <= 25:
            raise ToolError('Use a limit between 1 and 25')
        if levels is not None and (not levels or any(l not in ('state', 'county', 'cd') for l in levels)):
            raise ToolError('Use levels state, county, or cd')
        matches = places.find(db, query, levels, limit)
        return build({'matches': matches}, warnings=[] if matches else ['No place matched; try a FIPS code.'])
    return _run('find_places', locals_args(query=query, levels=levels, limit=limit), work)


def search_measures(query: str | None = None, topic: str | None = None, level: str | None = None, limit: int = 25) -> Envelope:
    def work(db):
        if level is not None:
            _validate_level(level)
        if not 1 <= limit <= 50:
            raise ToolError('Use a limit between 1 and 50')
        catalog = _catalog(db)
        data = measures.search(catalog, query, topic, level, limit)
        used = [key.split(':')[0] for key in (m['measure_key'] for m in data['measures'])]
        warnings = []
        if query is None and topic is None and level is None:
            warnings.append(WITHHELD_TOPIC_WARNING)
        elif not data['measures'] and measures.withheld_query_match(catalog, query, level):
            warnings.append('HRSA AHRF measures are on the CHIP website but not available through this public server.')
        return build(data, _used(catalog, used), warnings)
    return _run('search_measures', locals_args(query=query, topic=topic, level=level, limit=limit), work)


def get_measure_details(measure_keys: list[str]) -> Envelope:
    def work(db):
        if not measure_keys or len(measure_keys) > 20:
            raise ToolError('Provide between 1 and 20 measure keys from search_measures')
        catalog = _catalog(db)
        products = _products(catalog)
        found, warnings = [], []
        for key in dict.fromkeys(measure_keys):
            m = _measure(catalog, key)
            if m is None:
                warnings.append(f'Unknown measure key {key}; use search_measures')
                continue
            product = products[m['product']]
            paired = m.get('paired_measure')
            paired_key = f"{paired['product']}:{paired['measure_id']}" if paired and paired['product'] in PUBLIC_PRODUCTS else None
            found.append({**m, 'measure_key': key, 'paired_measure': paired_key, 'topics': _topics_for(key),
                          'limitations': product['limitations'], 'active_release': product['release']})
        return build({'measures': found}, _used(catalog, [m['measure_key'].split(':')[0] for m in found]), warnings)
    return _run('get_measure_details', locals_args(measure_keys=measure_keys), work)


def get_area_values(level: str, geoids: list[str], measure_keys: list[str] | None = None, topic: str | None = None) -> Envelope:
    def work(db):
        _validate_level(level)
        if not geoids or len(geoids) > 25:
            raise ToolError('Provide 1 to 25 areas; use find_places to look up GEOIDs')
        for geoid in geoids:
            _validate_geoid(level, geoid)
        if measure_keys is not None and topic is not None:
            raise ToolError('Choose measure_keys or topic, then retry')
        if measure_keys is not None and (not measure_keys or len(measure_keys) > 40):
            raise ToolError('Provide 1 to 40 measure keys; use search_measures to narrow the request')
        catalog = _catalog(db)
        all_measures = [m for m in catalog['measures'] if m['product'] in PUBLIC_PRODUCTS]
        if topic is not None:
            if topic == 'health-care-resources':
                raise ToolError(WITHHELD_TOPIC_WARNING)
            t = next((t for t in measures.topics() if t['slug'] == topic), None)
            if t is None:
                raise ToolError('Unknown topic; use search_measures with no arguments to list topics')
            selected = t['measure_keys']
        elif measure_keys is not None:
            selected = list(dict.fromkeys(measure_keys))
        else:
            selected = [f"{m['product']}:{m['measure_id']}" for m in all_measures]
        warnings, valid = [], []
        for key in selected:
            m = _measure(catalog, key)
            if m is None:
                warnings.append(f'Unknown measure key {key}; use search_measures')
            elif level not in m['levels']:
                warnings.append(f"{key} is not published for {level}; published for {', '.join(m['levels'])}")
            else:
                valid.append(m)
        if len(set(geoids)) * len(valid) > MAX_ROWS:
            raise ToolError('More than 400 value rows; narrow the measures or areas')
        requested = {f"{m['product']}:{m['measure_id']}" for m in valid}
        products = sorted({m['product'] for m in valid})
        ids = sorted({m['measure_id'] for m in valid})
        result = lookup.area_values(db, level, geoids, products=products, measure_ids=ids) if valid else {'values': []}
        result_rows = [r for r in result['values'] if f"{r['product']}:{r['measure_id']}" in requested and r['product'] in PUBLIC_PRODUCTS]
        names = {r['geoid']: r['name'] for r in lookup.area_info(db, level, geoids)}
        pdata = _products(catalog)
        values = [value_row(r, pdata[r['product']], pdata[r['product']]['release'], names.get(r['geoid'])) for r in result_rows]
        used = _used(catalog, [r['product'] for r in result_rows])
        response = build({'level': level, 'areas': [{'geoid': g, 'name': names.get(g)} for g in dict.fromkeys(geoids)],
                          'values': values}, used, warnings)
        return fit_rows(response, 'values')
    return _run('get_area_values', locals_args(level=level, geoids=geoids, measure_keys=measure_keys, topic=topic), work)


def get_measure_across_areas(measure_key: str, level: str, within: str | None = None,
                             sort: str = 'geoid', limit: int = 25) -> Envelope:
    def work(db):
        _validate_level(level)
        product, measure_id = _measure_key(measure_key)
        if sort not in ('geoid', 'value_desc', 'value_asc'):
            raise ToolError('Use sort geoid, value_desc, or value_asc')
        if not 1 <= limit <= 300:
            raise ToolError('Use a limit between 1 and 300')
        if level == 'state':
            if within:
                raise ToolError('For state values omit within')
            parent = {'level': None, 'geoid': None, 'name': None}
            parent_geoid = None
        elif level in ('county', 'cd'):
            if not within:
                raise ToolError('Provide within as a state name or 2-digit GEOID; use find_places')
            state = places.resolve_state(db, within)
            parent_geoid = state['geoid']
            parent = {'level': 'state', 'geoid': parent_geoid, 'name': state['name']}
        else:
            _validate_geoid('county', within)
            parent_geoid = within
            info = lookup.area_info(db, 'county', [within])
            parent = {'level': 'county', 'geoid': within, 'name': info[0]['name'] if info else None}
        catalog = _catalog(db)
        m = _measure(catalog, measure_key)
        if m is None:
            raise ToolError('Unknown measure key; use search_measures')
        if level not in m['levels']:
            raise ToolError(f"This measure is published for {', '.join(m['levels'])}; use one of those levels")
        result = lookup.measure_values_within(db, product, measure_id, level, parent_geoid)
        pdata = _products(catalog)[product]
        release = pdata['release']
        rows = result['values']
        with_value = [r for r in rows if r['value'] is not None]
        without_value = [r for r in rows if r['value'] is None]
        if sort == 'value_desc':
            with_value.sort(key=lambda r: (-r['value'], r['geoid']))
        elif sort == 'value_asc':
            with_value.sort(key=lambda r: (r['value'], r['geoid']))
        else:
            with_value.sort(key=lambda r: r['geoid'])
        positions = {}
        if sort != 'geoid':
            order_values = sorted((r['value'] for r in with_value), reverse=sort == 'value_desc')
            for index, value in enumerate(order_values, 1):
                positions.setdefault(value, index)
        vintages = {r.get('boundary_vintage') for r in rows}
        shared_boundary = len(vintages) <= 1
        uncertainty_labels = {r['uncertainty'].get('label') for r in rows if isinstance(r.get('uncertainty'), dict)}
        shared_uncertainty_label = next(iter(uncertainty_labels)) if len(uncertainty_labels) == 1 else None
        uncertainty_kinds = {r['uncertainty'].get('kind') for r in rows if isinstance(r.get('uncertainty'), dict)}
        shared_uncertainty_kind = next(iter(uncertainty_kinds)) if len(uncertainty_kinds) == 1 else None
        numbered = [compact_value_row(row, row.get('name'), positions.get(row['value']), not shared_boundary,
                                      shared_uncertainty_label, shared_uncertainty_kind)
                    for row in with_value]
        missing = [compact_value_row(r, r.get('name'), include_boundary=not shared_boundary,
                                     shared_uncertainty_label=shared_uncertainty_label,
                                     shared_uncertainty_kind=shared_uncertainty_kind)
                   for r in sorted(without_value, key=lambda r: r['geoid'])]
        clipped = len(numbered) > limit
        warnings = [ORDER_WARNING] if sort != 'geoid' else []
        if clipped:
            warnings.append(f'Showing {limit} of {len(numbered)} areas with values.')
        representative = rows[0] if rows else m
        compact = {k: representative.get(k) for k in ('label', 'unit', 'storage_scale', 'period',
                                                       'population', 'value_type', 'release_id')}
        compact['release_id'] = compact['release_id'] or release.get('release_id')
        compact['measure_key'] = measure_key
        compact['citation'] = citation(pdata, representative.get('period'), release)
        if shared_uncertainty_label is not None:
            compact['uncertainty_label'] = shared_uncertainty_label
        if shared_uncertainty_kind is not None:
            compact['uncertainty_kind'] = shared_uncertainty_kind
        if shared_boundary:
            compact['boundary_vintage'] = next(iter(vintages)) if vintages else m.get('boundary_vintage')
        response = build({'measure': compact, 'parent': parent, 'total_areas': len(rows),
                          'with_value': numbered[:limit], 'without_value': missing, 'truncated': clipped},
                         [pdata], warnings)
        while True:
            before = len(response.data['with_value'])
            response.warnings = [w for w in response.warnings if not w.startswith('Showing ')]
            if before < len(with_value):
                response.warnings.append(f'Showing {before} of {len(with_value)} areas with values.')
            fit_rows(response, 'with_value')
            if len(response.data['with_value']) == before:
                break
        return response
    return _run('get_measure_across_areas', locals_args(measure_key=measure_key, level=level, within=within, sort=sort, limit=limit), work)


def get_area_context(level: str, geoid: str) -> Envelope:
    def work(db):
        _validate_level(level)
        _validate_geoid(level, geoid)
        info = lookup.area_info(db, level, [geoid])
        if not info:
            raise ToolError('No current boundary carries this GEOID; use find_places to find an area')
        area = info[0]
        if level == 'state':
            related = {'counties': lookup.state_counties(db, geoid), 'districts': lookup.state_districts(db, geoid)}
        elif level == 'county':
            related = lookup.county_districts(db, geoid)
        elif level == 'cd':
            related = lookup.district_counties(db, geoid)
        else:
            related = {'county': {'geoid': area['county_geoid'], 'name': area['county_name']}}
        facilities = {}
        blocks = None
        if level in ('state', 'county', 'cd'):
            blocks = lookup.area_facilities(db, level, geoid)
            for key in FACILITY_PRODUCTS:
                block = blocks[key]
                extras = ('program', 'site_type') if key == 'health_centers' else (('provider_type', 'overall_rating') if key == 'nursing_homes' else ('sector_codes',))
                examples = [{k: row.get(k) for k in ('name', 'city', *extras)} for row in block['rows'][:10]]
                facilities[key] = {k: block.get(k) for k in ('name', 'count', 'published', 'release', 'method', 'limitations')} | {'examples': examples}
        response = build({'area': area, 'related': related, 'facilities': facilities})
        if blocks is not None:
            response.sources.extend(_facility_sources(blocks))
            _facility_rules(response, blocks)
        if size_bytes(response) > MAX_BYTES:
            raise ToolError('Area context exceeds the size limit; choose a county or district')
        return response
    return _run('get_area_context', locals_args(level=level, geoid=geoid), work)


def list_data_sources() -> Envelope:
    def work(db):
        catalog = _catalog(db)
        products, ms = measures.public_catalog(catalog)
        counts = {p['product']: sum(m['product'] == p['product'] for m in ms) for p in products}
        public = [{k: p.get(k) for k in ('name', 'publisher', 'levels', 'release', 'limitations', 'landing_page')} |
                  {'product': p['product'], 'measure_count': counts[p['product']]} for p in products]
        blocks = lookup.area_facilities(db, 'state', '01')
        facility = [{field: blocks[key].get(field) for field in ('name', 'release', 'published')} | {'product': key} for key in FACILITY_PRODUCTS]
        response = build({'products': public, 'facility_products': facility,
                      'excluded': [{'product': 'ahrf', 'reason': "Pending the source agency's answer on redistribution; available on the CHIP website."}],
                      'status_glossary': lookup.STATUS_TEXT, 'levels': list(LEVELS),
                      'notes': ['One published period per measure; no time series.',
                                'Area context uses TIGER/Line 2024 boundaries and 119th Congress districts; '
                                'each value row gives its source boundary_vintage, which may differ.']}, products)
        response.sources.extend(_facility_sources(blocks))
        _facility_rules(response, blocks)
        return response
    return _run('list_data_sources', {}, work)


def locals_args(**kwargs):
    return kwargs
