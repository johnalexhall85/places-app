"""Read-only MCP operations; database reads use approved lookup layers."""
import json
import logging
import re
import time
from datetime import datetime, timezone
from mcp.server.mcpserver.exceptions import ToolError
from app import db as db_module
from app.area_pilot import lookup
from app.funding_report import lookup as funding_lookup
from app.state_funding import lookup as state_funding_lookup
from app.state_funding.grant_history import GrantNotFound
from . import cache, measures, places
from .config import FACILITY_PRODUCTS, LEVELS, MAX_BYTES, MAX_ROWS, ORDER_WARNING, PUBLIC_PRODUCTS, WITHHELD_TOPIC_WARNING, public_base_url
from .envelope import Envelope, build, compact_value_row, fit_rows, size_bytes, value_row, citation, source

log = logging.getLogger(__name__)

FUNDING_RULES = (
    'Obligations are USAspending federal account (File C) obligations unless a row says otherwise; award-level and TAGGS amounts are shown for comparison and can differ.',
    'Sub-award amounts are reported by prime recipients and are not additional federal funding; never add them to prime obligations.',
    'Other federal awards are HHS awards recorded in TAGGS for the same UEI; they are not a complete federal funding portfolio.',
    'State the data-through date of each source and say when a fiscal year is not complete.',
    'Do not rank recipients by merit or describe funding as good or bad; report amounts, periods, and sources.',
)

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


def _periods(db, measure):
    return lookup.measure_periods(db, measure['product'], measure['measure_id'])


def _published_periods(db, measure):
    return [p['period'] for p in _periods(db, measure) if p['available']]


def _row_release(row, product, releases):
    current = product['release']
    if row['release_id'] == current['release_id']:
        return current, product['dataset_id']
    history_id = f"{product['dataset_id']}:history"
    history = releases.get(history_id)
    if history and row['release_id'] == history['release_id']:
        return history, history_id
    raise ToolError('Published release metadata is unavailable; please retry')


def _row_sources(rows, products, releases):
    found = {}
    for row in rows:
        product = products[row['product']]
        release, dataset_id = _row_release(row, product, releases)
        found[(dataset_id, release['release_id'])] = source(product, release, dataset_id)
    return list(found.values())


def _sources_for_visible_rows(response, collection):
    release_ids = {row['release_id'] for row in response.data[collection]}
    response.sources = [item for item in response.sources if item['release_id'] in release_ids]
    return response


def _run(name, args, work, funding=False, state_funding=False):
    start = time.monotonic()
    cached = False
    error = None
    rows = 0
    session = db_module.SessionLocal()
    try:
        if state_funding:
            fingerprint = state_funding_lookup.build_fingerprint(session, include_profiles=funding)
        else:
            fingerprint = (funding_lookup.active_build(session) or {}).get('build_id') if funding else lookup.active_releases(session)
        key = cache.key(name, args, fingerprint)
        result = cache.get(key)
        if result is None:
            result = work(session)
            cache.put(key, result)
        else:
            cached = True
        data = result.data
        rows = sum(len(data[k]) for k in ('values', 'with_value', 'without_value', 'series', 'matches', 'measures') if isinstance(data.get(k), list))
        return result
    except (ToolError, lookup.LookupError_, funding_lookup.FundingLookupError, GrantNotFound) as exc:
        error = type(exc).__name__
        if isinstance(exc, (lookup.LookupError_, funding_lookup.FundingLookupError, GrantNotFound)):
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
        for item in data['measures']:
            measure = _measure(catalog, item['measure_key'])
            item['periods'] = [p['period'] for p in _periods(db, measure) if p['available']]
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
                          'limitations': product['limitations'], 'active_release': product['release'],
                          'periods': _periods(db, m)})
        return build({'measures': found}, _used(catalog, [m['measure_key'].split(':')[0] for m in found]), warnings)
    return _run('get_measure_details', locals_args(measure_keys=measure_keys), work)


def get_area_values(level: str, geoids: list[str], measure_keys: list[str] | None = None,
                    topic: str | None = None, period: str | None = None) -> Envelope:
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
            elif period is not None and period not in (published := _published_periods(db, m)):
                warnings.append(f"{key} is not published for {period}; published periods: {', '.join(published)}")
            else:
                valid.append(m)
        if len(set(geoids)) * len(valid) > MAX_ROWS:
            raise ToolError('More than 400 value rows; narrow the measures or areas')
        requested = {f"{m['product']}:{m['measure_id']}" for m in valid}
        products = sorted({m['product'] for m in valid})
        ids = sorted({m['measure_id'] for m in valid})
        if not valid:
            result = {'values': [], 'unavailable': []}
        elif period is not None:
            result = lookup.area_values_for_period(db, level, geoids, period,
                                                   [(m['product'], m['measure_id']) for m in valid])
        else:
            result = lookup.area_values(db, level, geoids, products=products, measure_ids=ids)
        for item in result.get('unavailable', []):
            m = _measure(catalog, f"{item['product']}:{item['measure_id']}")
            warnings.append(f"{item['product']}:{item['measure_id']} is unavailable for {period}: {item['reason']}; published periods: {', '.join(_published_periods(db, m))}")
        result_rows = [r for r in result['values'] if f"{r['product']}:{r['measure_id']}" in requested and r['product'] in PUBLIC_PRODUCTS]
        names = {r['geoid']: r['name'] for r in lookup.area_info(db, level, geoids)}
        pdata = _products(catalog)
        releases = lookup.active_releases(db) if result_rows else {}
        values = [value_row(r, pdata[r['product']], _row_release(r, pdata[r['product']], releases)[0],
                            names.get(r['geoid'])) for r in result_rows]
        used = _used(catalog, [r['product'] for r in result_rows])
        response = build({'level': level, 'areas': [{'geoid': g, 'name': names.get(g)} for g in dict.fromkeys(geoids)],
                          'values': values}, used, warnings)
        response.sources = _row_sources(result_rows, pdata, releases)
        return _sources_for_visible_rows(fit_rows(response, 'values'), 'values')
    return _run('get_area_values', locals_args(level=level, geoids=geoids, measure_keys=measure_keys, topic=topic, period=period), work)


def get_measure_across_areas(measure_key: str, level: str, within: str | None = None,
                             sort: str = 'geoid', limit: int = 25, period: str | None = None) -> Envelope:
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
        if period is not None and period != m['period'] and level == 'cd':
            raise ToolError('Congressional districts have no earlier periods in CHIP: older Congresses had different districts.')
        if level not in m['levels']:
            raise ToolError(f"This measure is published for {', '.join(m['levels'])}; use one of those levels")
        if period is not None and period not in (published := _published_periods(db, m)):
            raise ToolError(f"{measure_key} is not published for {period}; published periods: {', '.join(published)}")
        result = (lookup.measure_values_within(db, product, measure_id, level, parent_geoid, period=period)
                  if period is not None else lookup.measure_values_within(db, product, measure_id, level, parent_geoid))
        pdata = _products(catalog)[product]
        rows = result['values']
        releases = lookup.active_releases(db) if rows else {}
        release = _row_release(rows[0], pdata, releases)[0] if rows else pdata['release']
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
        compact['note'] = representative.get('note')
        if shared_uncertainty_label is not None:
            compact['uncertainty_label'] = shared_uncertainty_label
        if shared_uncertainty_kind is not None:
            compact['uncertainty_kind'] = shared_uncertainty_kind
        if shared_boundary:
            compact['boundary_vintage'] = next(iter(vintages)) if vintages else m.get('boundary_vintage')
        response = build({'measure': compact, 'parent': parent, 'total_areas': len(rows),
                          'with_value': numbered[:limit], 'without_value': missing, 'truncated': clipped},
                         [pdata], warnings)
        if rows:
            response.sources = _row_sources(rows, {product: pdata}, releases)
        while True:
            before = len(response.data['with_value'])
            response.warnings = [w for w in response.warnings if not w.startswith('Showing ')]
            if before < len(with_value):
                response.warnings.append(f'Showing {before} of {len(with_value)} areas with values.')
            fit_rows(response, 'with_value')
            if len(response.data['with_value']) == before:
                break
        return response
    return _run('get_measure_across_areas', locals_args(measure_key=measure_key, level=level, within=within, sort=sort, limit=limit, period=period), work)


def get_measure_over_time(level: str, geoid: str, measure_key: str) -> Envelope:
    def work(db):
        _validate_level(level)
        _validate_geoid(level, geoid)
        product, measure_id = _measure_key(measure_key)
        catalog = _catalog(db)
        measure = _measure(catalog, measure_key)
        if measure is None:
            raise ToolError('Unknown measure key; use search_measures')
        if level not in measure['levels']:
            raise ToolError(f"This measure is published for {', '.join(measure['levels'])}; use one of those levels")
        result = lookup.area_measure_series(db, level, geoid, product, measure_id)
        rows = result['series']
        if level == 'cd':
            rows = [r for r in rows if r['period'] == measure['period']]
        releases = lookup.active_releases(db) if rows else {}
        pdata = _products(catalog)[product]
        info = lookup.area_info(db, level, [geoid])
        name = info[0]['name'] if info else None
        values = [value_row(r, pdata, _row_release(r, pdata, releases)[0], name) for r in rows]
        shared = {k: measure.get(k) for k in ('label', 'unit', 'storage_scale')}
        for field in ('population', 'value_type'):
            if not rows or all(r.get(field) == rows[0].get(field) for r in rows):
                shared[field] = rows[0].get(field) if rows else measure.get(field)
        shared['measure_key'] = measure_key
        warnings = ['Values are shown as published for each period; earlier periods can differ in method or boundaries, and CHIP computes no change.']
        if len({r.get('boundary_vintage') for r in rows}) > 1:
            warnings.append('The boundary vintage differs between periods; compare the published areas with care.')
        if level == 'cd':
            warnings.append('Congressional districts have no earlier periods in CHIP: older Congresses had different districts.')
        response = build({'area': {'level': level, 'geoid': geoid, 'name': name},
                          'measure': shared, 'series': values,
                          'unavailable_periods': result['unavailable_periods'] if level != 'cd' else []},
                         [pdata] if rows else [], warnings)
        response.sources = _row_sources(rows, {product: pdata}, releases)
        return _sources_for_visible_rows(fit_rows(response, 'series'), 'series')
    return _run('get_measure_over_time', locals_args(level=level, geoid=geoid, measure_key=measure_key), work)


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
        period_notes = []
        for p in products:
            periods = {period['period'] for m in ms if m['product'] == p['product']
                       for period in _periods(db, m) if period['available']}
            if periods:
                first, last = min(periods), max(periods)
                span = ', '.join(sorted(periods)) if any('–' in p for p in periods) else first if first == last else f'{first}–{last}'
                period_notes.append(f"{p['name']}: {span}")
        response = build({'products': public, 'facility_products': facility,
                      'excluded': [{'product': 'ahrf', 'reason': "Pending the source agency's answer on redistribution; available on the CHIP website."}],
                      'status_glossary': lookup.STATUS_TEXT, 'levels': list(LEVELS),
                      'notes': period_notes + [
                                'Area context uses TIGER/Line 2024 boundaries and 119th Congress districts; '
                                'each value row gives its source boundary_vintage, which may differ.']}, products)
        response.sources.extend(_facility_sources(blocks))
        _facility_rules(response, blocks)
        return response
    return _run('list_data_sources', {}, work)


def _funding_envelope(data, sources, caveats):
    result = Envelope(data=data, sources=sources, interpretation_rules=list(FUNDING_RULES), warnings=list(caveats))
    if size_bytes(result) > MAX_BYTES:
        if isinstance(data.get('recipients'), list):
            fit_rows(result, 'recipients')
        else:
            raise ToolError('Funding response exceeds the size limit; use the dataset_url from get_nofo_overview.')
    return result


def _dataset_url(key, include_subawards):
    return f"{public_base_url()}/funding/nofo/{key}.json?subawards={int(include_subawards)}"


def get_nofo_overview(nofo: str, include_subawards: bool = False) -> Envelope:
    """CDC NOFO totals, recipient aggregates, source dates, and full dataset URL."""
    def work(db):
        overview = funding_lookup.nofo_overview(db, nofo, include_subawards)
        overview['dataset_url'] = _dataset_url(overview['nofo']['nofo_key'], include_subawards)
        sources = overview.pop('sources')
        caveats = overview['caveats']
        return _funding_envelope(overview, sources, caveats)
    return _run('get_nofo_overview', locals_args(nofo=nofo, include_subawards=include_subawards), work, funding=True)


def list_nofo_recipients(nofo: str, offset: int = 0, limit: int = 50) -> Envelope:
    """Compact recipients for one CDC NOFO, ordered by state and name."""
    def work(db):
        dataset = funding_lookup.nofo_dataset(db, nofo, False)
        result = funding_lookup.list_recipients(db, nofo, offset, limit)
        result['dataset_url'] = _dataset_url(result['nofo_key'], False)
        return _funding_envelope(result, dataset['sources'], dataset['caveats'])
    return _run('list_nofo_recipients', locals_args(nofo=nofo, offset=offset, limit=limit), work, funding=True)


def get_recipient_funding(nofo: str, recipient: str) -> Envelope:
    """One full recipient profile by exact UEI, FAIN, award key, or unique name."""
    def work(db):
        profile = funding_lookup.recipient_profile(db, nofo, recipient)
        dataset = funding_lookup.nofo_dataset(db, nofo, False)
        return _funding_envelope({'recipient':profile,'nofo_key':dataset['nofo']['nofo_key'],
                                   'dataset_url':_dataset_url(dataset['nofo']['nofo_key'], True)},
                                  dataset['sources'], dataset['caveats'])
    return _run('get_recipient_funding', locals_args(nofo=nofo, recipient=recipient), work, funding=True)


STATE_FUNDING_RULES = [FUNDING_RULES[i] for i in (0, 1, 3, 4)] + [
    "A recipient's state is the state USAspending records for the recipient, not where services are delivered.",
    "Supplemental means dollars with a non-regular Disaster Emergency Fund Code; it can be negative "
    "when earlier emergency money was reduced. Award actions are not labelled supplemental.",
    "Contracts are counted in the contractor's state; the default is grants only.",
    "Budget categories follow the top-level lines of CDC's FY 2026 Operating Plan; "
    "amounts are not split between categories.",
]


def _state_context(db, state, fiscal_year, funding_type, award_type, category, recipient_type):
    try:
        code = state_funding_lookup.resolve_state(state)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    for label, value, choices in (
        ('funding_type', funding_type, ('all', 'regular', 'supplemental')),
        ('award_type', award_type, ('all', 'grant', 'contract')),
        ('recipient_type', recipient_type, ('all', 'state_government')),
    ):
        if value not in choices:
            raise ToolError(f"Unknown {label}; use {', '.join(choices)}.")
    build_info = state_funding_lookup.build_info(db)
    if not build_info or not state_funding_lookup.state_exists(db, code, build_info['build_id']):
        raise ToolError('Unknown state in the active build; use a state with CDC funding rows.')
    years = state_funding_lookup.fiscal_years(db)
    fy = fiscal_year if fiscal_year is not None else years['default']
    if fy not in years['fiscal_years']:
        raise ToolError(f"Unknown fiscal year; use {', '.join(map(str, years['fiscal_years']))}.")
    filters = {'funding_type': funding_type, 'award_type': award_type,
               'category': category, 'recipient_type': recipient_type}
    if category:
        base_filters = filters | {'category': None}
        available = state_funding_lookup.summary(db, code, fy, base_filters, build_info)['categories_available']
        if category not in {row['code'] for row in available}:
            raise ToolError('Unknown category for this state and year; use ' +
                            ', '.join(row['code'] for row in available) + '.')
    return code, fy, filters, build_info, years


def _state_sources(build_info, period, grant=False):
    sources = [
        {'publisher': 'USAspending', 'dataset': 'Award financial (File C), CDC',
         'period': period, 'citation': f'Source: USAspending · Award financial (File C), CDC · {period}'},
        {'publisher': 'Grants.gov', 'dataset': 'NOFO titles',
         'citation': 'Source: Grants.gov · funding opportunity titles'},
    ]
    if grant:
        sources.append({'publisher': 'HHS TAGGS', 'dataset': 'award recipient profiles',
                        'citation': 'Source: HHS TAGGS · CDC award recipient profiles'})
    return sources


def _state_envelope(data, build_info, period, grant=False):
    response = Envelope(data=data, sources=_state_sources(build_info, period, grant),
                        interpretation_rules=STATE_FUNDING_RULES)
    if size_bytes(response) > MAX_BYTES:
        if 'awards' in data:
            # Keep the per-award history, then remove optional identity fields if needed.
            for award in data['awards']:
                for field in ('subawards', 'city', 'project_title', 'usaspending_url', 'recipient_uei',
                              'recipient_type_source', 'is_state_government', 'all_years_total', 'first_fy',
                              'award_id', 'split_state', 'last_fy'):
                    award.pop(field, None)
            if size_bytes(response) > MAX_BYTES:
                fit_rows(response, 'awards', 'Size cap reached; continue at next_offset or filter by state.')
                response.data['next_offset'] = response.data['offset'] + len(response.data['awards'])
        else:
            fit_rows(response, 'rows', 'Size cap reached; continue at next_offset or narrow filters.')
            response.data['next_offset'] = response.data['offset'] + len(response.data['rows'])
        while size_bytes(response) > MAX_BYTES and (response.data.get('awards') or response.data.get('rows')):
            collection = 'awards' if 'awards' in response.data else 'rows'
            response.data[collection].pop()
            response.data['next_offset'] -= 1
    return response


def get_state_funding(state: str, fiscal_year: int | None = None, funding_type: str = 'all',
                      award_type: str = 'grant', category: str | None = None,
                      recipient_type: str = 'all') -> Envelope:
    """CDC state funding summary by exact budget category, with a File C citation."""
    args = locals_args(state=state, fiscal_year=fiscal_year, funding_type=funding_type,
                      award_type=award_type, category=category, recipient_type=recipient_type)
    def work(db):
        code, fy, filters, build_info, years = _state_context(db, **args)
        data = state_funding_lookup.summary(db, code, fy, filters, build_info)
        data['fiscal_years_available'] = years['fiscal_years']
        return _state_envelope(data, build_info, data['period'])
    return _run('get_state_funding', args, work, state_funding=True)


def list_state_grants(state: str, fiscal_year: int | None = None, query: str | None = None,
                      funding_type: str = 'all', award_type: str = 'grant', category: str | None = None,
                      recipient_type: str = 'all', sort: str = 'amount', direction: str = 'desc',
                      offset: int = 0, limit: int = 25) -> Envelope:
    """A page of CDC awards to recipients in a state, with all-match totals."""
    if sort not in ('amount', 'name', 'recipient', 'category'):
        raise ToolError('Unknown sort; use amount, name, recipient, or category.')
    if direction not in ('asc', 'desc'):
        raise ToolError('Unknown direction; use asc or desc.')
    if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ToolError('Use offset 0 or greater and limit between 1 and 100.')
    args = locals_args(state=state, fiscal_year=fiscal_year, query=query, funding_type=funding_type,
                      award_type=award_type, category=category, recipient_type=recipient_type,
                      sort=sort, direction=direction, offset=offset, limit=limit)
    def work(db):
        code, fy, filters, build_info, years = _state_context(
            db, state, fiscal_year, funding_type, award_type, category, recipient_type)
        data = state_funding_lookup.grants(db, code, fy, filters, build_info, q=query or '',
            sort=sort, direction=direction, page_size=limit, offset=offset)
        fields = ('award_unique_key', 'award_id', 'grant_name', 'name_source', 'fon', 'recipient_name',
                  'is_state_government', 'categories', 'regular', 'supplemental', 'total',
                  'description', 'usaspending_url')
        data['rows'] = [{key: row[key] for key in fields} for row in data['rows']]
        for row in data['rows']:
            row['categories'] = [c['name'] for c in row['categories']]
            description = row.get('description') or ''
            if len(description) > 300:
                row['description'] = description[:301].rsplit(' ', 1)[0] or description[:300]
        data['offset'] = offset
        data['limit'] = limit
        data['state'] = {'code': code, 'name': state_funding_lookup.state_name(code)}
        data['fiscal_years_available'] = years['fiscal_years']
        period = (build_info['sources'] or {}).get('periods', {}).get(str(fy), f'FY{fy}')
        data['period'] = period
        return _state_envelope(data, build_info, period)
    return _run('list_state_grants', args, work, state_funding=True)


def get_grant_history(nofo: str, state: str | None = None, include_past: bool = True,
                      offset: int = 0, limit: int = 50) -> Envelope:
    """One CDC NOFO's funded fiscal years, state totals, and a page of award histories."""
    if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ToolError('Use offset 0 or greater and limit between 1 and 100.')
    args = locals_args(nofo=nofo, state=state, include_past=include_past, offset=offset, limit=limit)
    def work(db):
        data = state_funding_lookup.grant_history(db, nofo)
        code = None
        if state is not None:
            try:
                code = state_funding_lookup.resolve_state(state)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
        awards = [a for a in data['awards'] if (code is None or a['state'] == code)
                  and (include_past or a['is_current'])]
        response_data = {key: data[key] for key in ('nofo', 'latest_fy', 'latest_fy_period',
            'totals', 'by_fiscal_year', 'by_state', 'citation', 'build')}
        response_data['awards'] = awards[offset:offset + limit]
        response_data['total_rows'] = len(awards)
        response_data['offset'] = offset
        response_data['limit'] = limit
        response_data['recipient_profile_tool'] = 'get_recipient_funding(nofo, recipient)'
        return _state_envelope(response_data, state_funding_lookup.build_info(db), data['latest_fy_period'], True)
    return _run('get_grant_history', args, work, funding=True, state_funding=True)


def locals_args(**kwargs):
    return kwargs
