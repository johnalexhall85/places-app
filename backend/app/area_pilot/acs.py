"""Bounded Census ACS 5-year B19013 retrieval and statistical parsing."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.area_pilot.source import digest

FIELDS = ('NAME', 'B19013_001E', 'B19013_001M', 'B19013_001EA', 'B19013_001MA')
SENTINELS = {
    '-666666666': '-', '-999999999': 'N', '-888888888': '(X)',
}
MOE_SENTINELS = {
    '-222222222': '**', '-333333333': '***', '-555555555': '*****',
    '-888888888': '(X)', '-999999999': 'N',
}
LEVEL_LENGTH = {'state': 2, 'county': 5, 'tract': 11}


def load_registry():
    path = Path(__file__).with_name('registry') / 'acs_2024_b19013.json'
    config = json.loads(path.read_text())
    assert config['geographies'] == ['state', 'county', 'tract']
    assert config['aggregation_method'] == 'none' and config['moe_confidence'] == 90
    return config


def census_api_key():
    direct = os.getenv('CENSUS_API_KEY')
    if direct:
        return direct.strip()
    path = Path(os.getenv('CENSUS_API_KEY_FILE', '/home/john/.config/places/census-api-key'))
    if not path.exists():
        return None
    if path.stat().st_mode & 0o077:
        raise RuntimeError('Census API key file permissions must be 600')
    return path.read_text().strip() or None


def parse_number(raw, annotation, sentinels, field):
    annotation = annotation or None
    if raw is None or raw == '':
        if annotation is None:
            return None, None
        raise ValueError(f'{field}: annotation without a published numeric or sentinel code')
    try:
        number = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError(f'{field}: invalid numeric field') from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f'{field}: nonfinite or fractional value')
    canonical = str(int(number))
    if canonical in sentinels:
        if annotation != sentinels[canonical]:
            raise ValueError(f'{field}: sentinel annotation mismatch')
        return None, canonical
    if number < 0:
        raise ValueError(f'{field}: unrecognized negative source code')
    if annotation and not (field == 'estimate' and re.fullmatch(r'[0-9,]+[+-]', annotation)):
        raise ValueError(f'{field}: unexpected annotation')
    return int(number), None


def parse_observation(row):
    value, estimate_code = parse_number(row['B19013_001E'], row['B19013_001EA'], SENTINELS, 'estimate')
    moe, moe_code = parse_number(row['B19013_001M'], row['B19013_001MA'], MOE_SENTINELS, 'moe')
    if value is None:
        if moe is not None:
            raise ValueError('MOE with unavailable estimate')
        status = {'-666666666': 'missing', '-999999999': 'suppressed', '-888888888': 'not_applicable'}[estimate_code] if estimate_code else 'missing'
    else:
        status = 'open_ended' if row['B19013_001EA'] else ('true_zero' if value == 0 else 'available')
        if moe is None and moe_code is None:
            raise ValueError('Unexplained absent MOE')
    return {'value': value, 'moe': moe, 'estimate_annotation': row['B19013_001EA'] or None,
            'moe_annotation': row['B19013_001MA'] or None, 'status': status, 'moe_confidence': 90}


def geography_id(row, level):
    parts = {'state': ('state',), 'county': ('state', 'county'),
             'tract': ('state', 'county', 'tract')}[level]
    key = ''.join(row[part] for part in parts)
    if len(key) != LEVEL_LENGTH[level] or not key.isdigit():
        raise ValueError(f'Invalid {level} geography key')
    return key


def parse_response(payload, level, state=None):
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], list):
        raise ValueError('Invalid or empty Census response')
    expected = set(FIELDS) | set({'state': ('state',), 'county': ('state', 'county'),
                                  'tract': ('state', 'county', 'tract')}[level])
    header = payload[0]
    if len(header) != len(expected) or set(header) != expected:
        raise ValueError('Census response header changed')
    records = {}
    for values in payload[1:]:
        if not isinstance(values, list) or len(values) != len(header):
            raise ValueError('Malformed Census row')
        row = dict(zip(header, values))
        key = geography_id(row, level)
        if state is not None and row['state'] != state:
            raise ValueError('Census partition returned a different state')
        if key in records:
            raise ValueError('Duplicate Census geography key')
        parse_observation(row)
        records[key] = row
    return records


def semantic_sha(records):
    return digest([(level, key, {field: row.get(field) for field in sorted(row)})
                   for (level, key), row in sorted(records.items())])


class CensusClient:
    def __init__(self, config, directory: Path, api_key=None, pause=.15):
        self.config, self.directory = config, Path(directory)
        self.api_key = api_key if api_key is not None else census_api_key()
        self.pause = pause
        self.files = []
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        retry = Retry(total=4, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                      respect_retry_after_header=True)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))

    def get(self, url, params, role, require_key=False):
        if require_key and not self.api_key:
            raise RuntimeError('CENSUS_API_KEY is not configured')
        safe_params = params
        actual_params = list(params.items()) if isinstance(params, dict) else list(params)
        if require_key:
            actual_params.append(('key', self.api_key))
        try:
            response = self.session.get(url, params=actual_params, timeout=(10, 90))
            if response.status_code != 200:
                raise RuntimeError(f'Census request {role} returned HTTP {response.status_code}')
            content = response.content
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ValueError('Non-JSON Census payload')
        except (requests.RequestException, ValueError) as exc:
            # requests errors may include the complete URL and API key.
            raise RuntimeError(f'Census request {role} failed ({type(exc).__name__})') from None
        sha = hashlib.sha256(content).hexdigest()
        path = self.directory / f'{len(self.files):03d}_{role}_{sha[:16]}.json'
        temporary = path.with_suffix('.part')
        temporary.write_bytes(content)
        temporary.replace(path)
        from urllib.parse import urlencode
        redacted_url = f'{url}?{urlencode(safe_params)}' if safe_params else url
        self.files.append({'role': role, 'path': str(path), 'url': redacted_url,
                           'sha256': sha, 'byte_count': len(content), 'retrieved_at': datetime.now(timezone.utc)})
        time.sleep(self.pause)
        return payload

    def metadata(self, role):
        base = self.config['source_api']
        group = self.get(base + '/groups/B19013.json', {}, role + '_group')
        geography = self.get(base + '/geography.json', {}, role + '_geography')
        variables = group.get('variables', {})
        expected = set(self.config['source_variable_ids'])
        if not expected <= variables.keys() or any(variables[v].get('universe') != 'Households' for v in expected):
            raise ValueError('Official B19013 definition or universe changed')
        if any('2024 inflation-adjusted dollars' not in variables[v].get('label', '') for v in expected):
            raise ValueError('Official dollar year changed')
        levels = {(item.get('geoLevelDisplay'), item.get('referenceDate')) for item in geography.get('fips', [])}
        if not {('040', '2024-01-01'), ('050', '2024-01-01'), ('140', '2024-01-01')} <= levels:
            raise ValueError('Official geographic support changed')
        return {'variables': {key: variables[key] for key in sorted(expected)}, 'geography': sorted(levels),
                'raw_group_sha256': self.files[-2]['sha256'], 'raw_geography_sha256': self.files[-1]['sha256']}

    def fetch(self):
        # A newer 5-year endpoint requires a release-selection decision.
        newer = self.session.get('https://api.census.gov/data/2025/acs/acs5.json', timeout=(10, 30))
        if newer.status_code == 200:
            raise RuntimeError('A newer ACS 5-year product exists; hold for release selection')
        if newer.status_code != 404:
            raise RuntimeError('Could not verify latest ACS 5-year product')
        before = self.metadata('before')
        records = {}
        states = set(self.config['supported_state_fips'])
        query = {'get': ','.join(FIELDS), 'for': 'state:*'}
        state_rows = parse_response(self.get(self.config['source_api'], query, 'states', True), 'state')
        if set(state_rows) != states:
            raise ValueError('State and Puerto Rico source coverage changed')
        records.update({('state', key): row for key, row in state_rows.items()})
        for state in sorted(states):
            for level in ('county', 'tract'):
                query = [('get', ','.join(FIELDS)), ('for', f'{level}:*'), ('in', f'state:{state}')]
                if level == 'tract':
                    query.append(('in', 'county:*'))
                part = parse_response(self.get(self.config['source_api'], query, f'{level}_{state}', True), level, state)
                if not part:
                    raise ValueError(f'Empty {level} partition for {state}')
                records.update({(level, key): row for key, row in part.items()})
        after = self.metadata('after')
        stable = before == after
        return before, after, records, stable
