"""ACS 2020–2024 5-year subject-table community characteristics: retrieval, parsing, district boundaries.

An independent shared product (its own registry, tables, and release pointer). It reads the Census
Bureau's own published counts and percentages with their 90% margins for states, counties, tracts,
and 119th Congress districts. Nothing is derived, combined, or re-based. The published B19013
median-income product (`acs.py`) is separate and unchanged.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

from app.area_pilot.acs import CensusClient
from app.area_pilot.source import digest

S = 'area_pilot'
LEVELS = ('state', 'county', 'tract', 'cd')
LEVEL_LENGTH = {'state': 2, 'county': 5, 'tract': 11, 'cd': 4}
GEO_PARTS = {'state': ('state',), 'county': ('state', 'county'), 'tract': ('state', 'county', 'tract'),
             'cd': ('state', 'congressional district')}
ESTIMATE_SENTINELS = {'-666666666': '-', '-999999999': 'N', '-888888888': '(X)'}
MOE_SENTINELS = {'-222222222': '**', '-333333333': '***', '-555555555': '*****', '-888888888': '(X)', '-999999999': 'N'}
ESTIMATE_STATUS = {'-666666666': 'missing', '-999999999': 'suppressed', '-888888888': 'not_applicable'}
STATUS_TEXT = {
    'available': 'Published estimate', 'true_zero': 'Published zero',
    'missing': 'No estimate: too few sample observations (Census "-")',
    'suppressed': 'Not displayed by the Census Bureau (Census "N")',
    'not_applicable': 'Not applicable (Census "(X)")',
}


def load_registry():
    config = json.loads((Path(__file__).with_name('registry') / 'acs_2024_profile.json').read_text(encoding='utf-8'))
    if config['geographies'] != list(LEVELS) or config['aggregation_method'] != 'none' or config['moe_confidence'] != 90:
        raise ValueError('ACS community registry contract is invalid')
    ids = [m['measure_id'] for m in config['measures']]
    variables = [m['variable'] for m in config['measures']]
    if len(ids) != len(set(ids)) or len(variables) != len(set(variables)):
        raise ValueError('ACS community measures must be unique')
    for measure in config['measures']:
        if measure['kind'] not in ('count', 'percent'):
            raise ValueError(f"{measure['measure_id']}: unsupported kind")
        for suffix in ('E', 'M'):
            if measure['variable'] + suffix not in config['source_variables']:
                raise ValueError(f"{measure['measure_id']}: source variable metadata missing")
    if digest(config['source_variables']) != config['source_variables_sha256']:
        raise ValueError('Registry source variable metadata differs from its reviewed checksum')
    return config


def fields(config):
    return ('NAME',) + tuple(m['variable'] + suffix for m in config['measures'] for suffix in ('E', 'M', 'EA', 'MA'))


def _number(raw, annotation, sentinels, field, integral):
    """Return (value, sentinel code). Sentinels arrive as '-666666666' or '-666666666.0'."""
    annotation = annotation or None
    if raw is None or raw == '':
        if annotation is None:
            return None, None
        raise ValueError(f'{field}: annotation without a published numeric or sentinel code')
    try:
        number = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError(f'{field}: invalid numeric field') from exc
    if not number.is_finite():
        raise ValueError(f'{field}: nonfinite value')
    if number == number.to_integral_value() and str(int(number)) in sentinels:
        code = str(int(number))
        if annotation != sentinels[code]:
            raise ValueError(f'{field}: sentinel annotation mismatch')
        return None, code
    if number < 0:
        raise ValueError(f'{field}: unrecognized negative source code')
    if annotation:
        raise ValueError(f'{field}: unexpected annotation {annotation!r}')
    if integral:
        if number != number.to_integral_value():
            raise ValueError(f'{field}: fractional count')
        return Decimal(int(number)), None
    return number, None


def parse_observation(row, measure):
    variable, integral = measure['variable'], measure['kind'] == 'count'
    estimate_annotation, moe_annotation = row[variable + 'EA'] or None, row[variable + 'MA'] or None
    value, estimate_code = _number(row[variable + 'E'], estimate_annotation, ESTIMATE_SENTINELS, f'{variable} estimate', integral)
    moe, moe_code = _number(row[variable + 'M'], moe_annotation, MOE_SENTINELS, f'{variable} margin', integral)
    if value is None:
        if estimate_code is None:
            raise ValueError(f'{variable}: estimate absent without a Census code')
        if moe is not None:
            raise ValueError(f'{variable}: margin published for an unavailable estimate')
        status = ESTIMATE_STATUS[estimate_code]
    else:
        if measure['kind'] == 'percent' and value > 100:
            raise ValueError(f'{variable}: percentage above 100')
        if moe is None and moe_code is None:
            raise ValueError(f'{variable}: unexplained absent margin')
        status = 'true_zero' if value == 0 else 'available'
    return {'value': value, 'moe': moe, 'estimate_annotation': estimate_annotation,
            'moe_annotation': moe_annotation, 'status': status, 'moe_confidence': 90}


def geography_id(row, level):
    return ''.join(row[part] for part in GEO_PARTS[level])


def parse_response(payload, level, config, state=None):
    """Validate one API partition. Returns (records, excluded) keyed by GEOID."""
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], list):
        raise ValueError('Invalid or empty Census response')
    header = payload[0]
    expected = set(fields(config)) | set(GEO_PARTS[level])
    if len(header) != len(expected) or set(header) != expected:
        raise ValueError('Census response header changed')
    records, excluded = {}, {}
    excluded_codes = config['cd']['excluded_codes']
    for values in payload[1:]:
        if not isinstance(values, list) or len(values) != len(header):
            raise ValueError('Malformed Census row')
        row = dict(zip(header, values))
        if state is not None and row['state'] != state:
            raise ValueError('Census partition returned a different state')
        key = geography_id(row, level)
        if level == 'cd' and row['congressional district'] in excluded_codes:
            if key in excluded:
                raise ValueError('Duplicate excluded district row')
            excluded[key] = row
            continue
        if len(key) != LEVEL_LENGTH[level] or not key.isdigit():
            raise ValueError(f'Invalid {level} geography key {key!r}')
        if key in records:
            raise ValueError('Duplicate Census geography key')
        for measure in config['measures']:
            parse_observation(row, measure)
        records[key] = row
    return records, excluded


def semantic_sha(records):
    return digest([(level, key, {field: row.get(field) for field in sorted(row)})
                   for (level, key), row in sorted(records.items())])


class ProfileClient(CensusClient):
    """Reuses the reviewed Census transport (retries, byte archive, key redaction) for subject tables."""

    def metadata(self, role):
        base = self.config['source_api']
        tables = sorted({m['source_table'] for m in self.config['measures']})
        variables, raw = {}, {}
        for table in tables:
            group = self.get(f'{base}/groups/{table}.json', {}, f'{role}_group_{table}').get('variables', {})
            raw[table] = self.files[-1]['sha256']
            for name in self.config['source_variables']:
                if name.split('_')[0] == table:
                    if name not in group:
                        raise ValueError(f'Official variable {name} is no longer published')
                    variables[name] = {'label': group[name].get('label'), 'concept': group[name].get('concept')}
        if variables != self.config['source_variables']:
            raise ValueError('Official variable label or concept changed')
        geography = self.get(base + '/geography.json', {}, role + '_geography')
        levels = sorted([item.get('geoLevelDisplay'), item.get('referenceDate')] for item in geography.get('fips', []))
        if not all(required in levels for required in self.config['required_geography_levels']):
            raise ValueError('Official geographic support changed')
        return {'variables': variables, 'geography': levels, 'raw_group_sha256': raw,
                'raw_geography_sha256': self.files[-1]['sha256']}

    def fetch(self):
        newer = self.session.get('https://api.census.gov/data/2025/acs/acs5/subject.json', timeout=(10, 30))
        if newer.status_code == 200:
            raise RuntimeError('A newer ACS 5-year product exists; hold for release selection')
        if newer.status_code != 404:
            raise RuntimeError('Could not verify latest ACS 5-year product')
        before = self.metadata('before')
        config, api = self.config, self.config['source_api']
        get = ','.join(fields(config))
        states = set(config['supported_state_fips'])
        records, excluded = {}, {}
        state_rows, _ = parse_response(self.get(api, {'get': get, 'for': 'state:*'}, 'states', True), 'state', config)
        if set(state_rows) != states:
            raise ValueError('State and Puerto Rico source coverage changed')
        records.update({('state', key): row for key, row in state_rows.items()})
        for state in sorted(states):
            for level, target in (('county', 'county:*'), ('tract', 'tract:*'), ('cd', 'congressional district:*')):
                query = [('get', get), ('for', target), ('in', f'state:{state}')]
                if level == 'tract':
                    query.append(('in', 'county:*'))
                part, skipped = parse_response(self.get(api, query, f'{level}_{state}', True), level, config, state)
                if not part:
                    raise ValueError(f'Empty {level} partition for {state}')
                records.update({(level, key): row for key, row in part.items()})
                excluded.update({(level, key): row for key, row in skipped.items()})
        after = self.metadata('after')
        return before, after, records, excluded, before == after


def cd_boundary_sources(config):
    for state in config['supported_state_fips']:
        yield state, config['cd']['boundary_url_template'].format(state=state)


def load_cd_boundaries(engine, config, directory: Path):
    """Load official TIGER/Line 2024 119th Congress district shapes, one archive per state. Idempotent."""
    import geopandas as gpd
    from sqlalchemy import text

    directory.mkdir(parents=True, exist_ok=True)
    excluded_codes, source_files, rows = set(config['cd']['excluded_codes']), [], []
    for state, url in cd_boundary_sources(config):
        path = directory / url.rsplit('/', 1)[-1]
        if not path.exists():
            try:
                response = requests.get(url, timeout=(10, 120))
                response.raise_for_status()
            except requests.RequestException as exc:
                raise RuntimeError(f'District boundary {state} download failed ({type(exc).__name__})') from None
            temporary = path.with_suffix('.part')
            temporary.write_bytes(response.content)
            temporary.replace(path)
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        shapes = gpd.read_file(f'zip://{path}')
        if not {'STATEFP', 'CD119FP', 'GEOID', 'NAMELSAD', 'geometry'} <= set(shapes.columns):
            raise ValueError(f'District boundary {state} schema changed')
        kept = 0
        for item in shapes.itertuples():
            if str(item.CD119FP) in excluded_codes:
                continue
            key = str(item.GEOID)
            if not re.fullmatch(r'\d{4}', key) or key[:2] != state or key != str(item.STATEFP) + str(item.CD119FP):
                raise ValueError(f'District boundary {state} has an invalid GEOID {key!r}')
            if item.geometry is None or item.geometry.is_empty or not item.geometry.is_valid:
                raise ValueError(f'District boundary {key} has invalid geometry')
            rows.append({'geoid': key, 'state': state, 'code': str(item.CD119FP), 'name': str(item.NAMELSAD),
                         'sha': content_hash, 'geom': item.geometry.wkb})
            kept += 1
        if not kept:
            raise ValueError(f'District boundary {state} was empty')
        source_files.append({'role': f'tiger2024_cd119_{state}', 'path': str(path), 'url': url, 'sha256': content_hash,
                             'byte_count': path.stat().st_size, 'retrieved_at': datetime.now(timezone.utc)})
    keys = [row['geoid'] for row in rows]
    if len(keys) != len(set(keys)) or len(keys) != config['cd']['expected_count']:
        raise ValueError(f'Expected {config["cd"]["expected_count"]} districts, found {len(keys)}')
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:dataset))'), {'dataset': config['dataset_id']})
        existing = dict(conn.execute(text(f'SELECT geoid,source_sha256 FROM {S}.cd_boundary_119')).all())
        if existing:
            if existing != {row['geoid']: row['sha'] for row in rows}:
                raise ValueError('Stored district boundaries differ from the official archives')
        else:
            conn.execute(text(f'''INSERT INTO {S}.cd_boundary_119 (geoid,state_fips,district_code,name,source_sha256,geom)
                VALUES (:geoid,:state,:code,:name,:sha,ST_Multi(ST_GeomFromWKB(:geom,4326)))'''), rows)
    return source_files
