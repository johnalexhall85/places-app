"""Official Socrata snapshot retrieval and deterministic normalization."""
from __future__ import annotations
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

FIPS = re.compile(r'^\d{5}$')
CI = re.compile(r'^\s*\(\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*\)\s*$')
PAGE_SIZE = 1000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def same_label_revision(previous, source_release_id, semantic_sha256):
    return bool(previous and previous['source_release_id'] == source_release_id
                and previous['semantic_sha256'] != semantic_sha256)


def schema_columns(metadata):
    return sorted(({k: column.get(k) for k in ('fieldName','name','dataTypeName','description')}
                   for column in metadata['columns'] if column.get('fieldName')),
                  key=lambda column: column['fieldName'])


def revision(metadata):
    return {key: metadata.get(key) for key in ('id','rowsUpdatedAt','viewLastModified','publicationDate')}


def normalize_record(record, columns):
    result = {}
    for column in columns:
        field = column['fieldName']
        value = record.get(field)
        if value in (None, ''):
            result[field] = None
        elif column['dataTypeName'] in ('number', 'money', 'percent'):
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError(f'Nonfinite numeric field {field}')
            result[field] = format(number.normalize(), 'f') if number else '0'
        else:
            result[field] = value
    unexpected = set(record) - {column['fieldName'] for column in columns}
    if unexpected:
        raise ValueError(f'Unexpected source fields: {sorted(unexpected)}')
    return result


def semantic_digest(records, columns, key_field='countyfips'):
    return digest([normalize_record(row, columns) for row in sorted(records, key=lambda row: row[key_field])])


def measure_set_digest(config):
    """Identity of the published measure set, independent of the source bytes.

    Source digests alone cannot tell a wider registry from the one already published: the PLACES
    file is the same, only the columns CHIP turns into observations differ. A candidate is a
    duplicate only when both the source content and this digest match.
    """
    return digest([[m['measure_id'], m['observation_period'], m['population'], m['source_value_field'],
                    m['source_ci_field'], sorted(m.get('documented_unavailable_states', []))]
                   for m in sorted(config['measures'], key=lambda m: m['measure_id'])] + [config['value_type']])


# Releases published before the measure set was recorded carried exactly these two measures.
LEGACY_MEASURE_SET_SHA256 = measure_set_digest({'value_type': 'crude_prevalence', 'measures': [
    {'measure_id': 'dental_crudeprev', 'observation_period': '2022', 'population': 'adults',
     'source_value_field': 'dental_crudeprev', 'source_ci_field': 'dental_crude95ci'},
    {'measure_id': 'access2_crudeprev', 'observation_period': '2023', 'population': 'adults aged 18-64',
     'source_value_field': 'access2_crudeprev', 'source_ci_field': 'access2_crude95ci',
     'documented_unavailable_states': ['KY', 'PA']}]})


def check_measure_set(row, config, args):
    """A candidate that records its measure set is approved only against that exact, current set."""
    recorded = row['report'].get('measure_set_sha256')
    if recorded is None:
        return
    if recorded != measure_set_digest(config):
        raise ValueError('Registry measure set changed since the candidate was staged')
    if getattr(args, 'measure_set_sha256', None) != recorded:
        raise ValueError('Candidate measure set differs from the reviewed value (--measure-set-sha256)')


def parse_observation(row, measure):
    raw = row.get(measure['source_value_field'])
    ci = row.get(measure['source_ci_field'])
    state = row['stateabbr']
    unavailable = state in measure.get('documented_unavailable_states', [])
    if unavailable:
        if raw not in (None, '') or ci not in (None, ''):
            raise ValueError(f'Unexpected published value in unavailable state {state}')
        return None, None, None, 'not_published'
    if raw in (None, ''):
        if ci not in (None, ''):
            raise ValueError('CI exists without value')
        return None, None, None, 'missing'
    if str(raw).strip() in ('*', '***', 'Suppressed'):
        return None, None, None, 'suppressed'
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError(f'Invalid prevalence {raw}') from exc
    match = CI.fullmatch(str(ci or ''))
    if not match:
        raise ValueError(f'Invalid CI {ci}')
    low, high = (Decimal(v) for v in match.groups())
    if not all(v.is_finite() and 0 <= v <= 100 for v in (value, low, high)) or not low <= value <= high:
        raise ValueError(f'Prevalence or CI outside valid range: {value}, {low}, {high}')
    return value, low, high, 'available'


class SourceClient:
    def __init__(self, config, directory: Path, pause=0.12):
        self.config, self.directory, self.pause = config, directory, pause
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        retry = Retry(total=5, backoff_factor=1, status_forcelist=[429,500,502,503,504], respect_retry_after_header=True)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.files = []
        self.checkpoint_path = self.directory / 'checkpoint.json'
        self.checkpoint = json.loads(self.checkpoint_path.read_text()) if self.checkpoint_path.exists() else {}
        self.resume_pages = False

    @property
    def key_field(self):
        return self.config.get('source_key_field', 'countyfips')

    @property
    def expected_count(self):
        return self.config.get('expected_tract_count', self.config.get('expected_county_count'))

    def get(self, url, params, role):
        full_url = f'{url}?{urlencode(params)}' if params else url
        saved = self.checkpoint.get('pages', {}).get(role) if self.resume_pages and role.startswith('page_') else None
        if saved and saved['url'] == full_url:
            content = Path(saved['path']).read_bytes()
            if hashlib.sha256(content).hexdigest() != saved['sha256']:
                raise ValueError(f'Checkpoint checksum failed for {role}')
            self.files.append({**saved, 'retrieved_at':datetime.fromisoformat(saved['retrieved_at'])})
            return json.loads(content)
        response = self.session.get(url, params=params, timeout=(10, 90))
        response.raise_for_status()
        content = response.content
        sha = hashlib.sha256(content).hexdigest()
        path = self.directory / f'{len(self.files):03d}_{role}_{sha[:16]}.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(content)
        temporary.replace(path)
        self.files.append({'role': role, 'path': str(path), 'url': full_url, 'sha256': sha,
                           'byte_count': len(content), 'retrieved_at': datetime.now(timezone.utc)})
        if role.startswith('page_'):
            self.checkpoint.setdefault('pages', {})[role] = {**self.files[-1], 'retrieved_at':self.files[-1]['retrieved_at'].isoformat()}
            temporary_manifest = self.checkpoint_path.with_suffix('.tmp')
            temporary_manifest.write_text(json.dumps(self.checkpoint, sort_keys=True))
            temporary_manifest.replace(self.checkpoint_path)
        time.sleep(self.pause)
        return response.json()

    def snapshot(self, role):
        metadata = self.get(self.config['source_metadata_api'], {}, f'{role}_metadata')
        field = self.key_field
        count = self.get(self.config['source_api'], {'$select':f'count(*) as n,count(distinct {field}) as distinct_key'}, f'{role}_count')[0]
        total = int(count['n'])
        key_list = []
        last = None
        while len(key_list) < total:
            params = {'$select':field, '$order':f'{field} ASC', '$limit':PAGE_SIZE}
            if last:
                params['$where'] = f"{field} > '{last}'"
            keys = self.get(self.config['source_api'], params, f'{role}_keys_{len(key_list)//PAGE_SIZE:03d}')
            page_keys = [row.get(field) for row in keys]
            if not page_keys or page_keys != sorted(set(page_keys)) or (last and page_keys[0] <= last):
                raise ValueError('Source key page ordering or uniqueness failed')
            key_list.extend(page_keys)
            last = page_keys[-1]
            if len(key_list) > total:
                raise ValueError('Source key pages exceeded count')
        if len(key_list) != total or len(set(key_list)) != len(key_list) or len(key_list) != int(count['distinct_key']):
            raise ValueError('Source key list/count/distinct mismatch')
        pattern = re.compile(r'^\d{11}$') if field == 'tractfips' else FIPS
        if any(not pattern.fullmatch(key) for key in key_list):
            raise ValueError(f'Invalid {field}')
        return {'revision': revision(metadata), 'columns': schema_columns(metadata), 'keys': key_list,
                'count': total, 'metadata': metadata}

    def fetch(self):
        before = self.snapshot('before')
        if before['count'] != self.expected_count:
            raise ValueError(f'Unexpected source {self.key_field} count')
        if digest(before['columns']) != self.config['expected_schema_sha256']:
            raise ValueError('Official schema differs from reviewed registry')
        definitions = {c['fieldName']: c for c in before['columns']}
        for measure in self.config['measures']:
            field = measure['source_value_field']
            if measure['source_definition_contains'] not in (definitions[field]['description'] or ''):
                raise ValueError(f'Official definition changed for {field}')
            if measure['source_ci_field'] not in definitions:
                raise ValueError(f'Missing CI field for {field}')
        signature = digest({'revision':before['revision'],'columns':before['columns'],'keys':before['keys']})
        # Source metadata and keys cannot prove that values in a cached page are unchanged.
        # Retain interrupted files for review, but restart all data pages on a new attempt.
        self.resume_pages = False
        if not self.resume_pages:
            self.checkpoint = {'signature':signature,'pages':{}}
            temporary_manifest = self.checkpoint_path.with_suffix('.tmp')
            temporary_manifest.write_text(json.dumps(self.checkpoint, sort_keys=True))
            temporary_manifest.replace(self.checkpoint_path)
        records = []
        last = None
        while True:
            params = {'$order':f'{self.key_field} ASC', '$limit':PAGE_SIZE}
            if last:
                params['$where'] = f"{self.key_field} > '{last}'"
            page = self.get(self.config['source_api'], params, f'page_{len(records)//PAGE_SIZE:03d}')
            if not isinstance(page, list) or not page or len(page) > PAGE_SIZE:
                raise ValueError('Empty or invalid source page')
            page_keys = [row.get(self.key_field) for row in page]
            if page_keys != sorted(set(page_keys)) or (last and page_keys[0] <= last):
                raise ValueError('Page ordering or uniqueness failed')
            records.extend(page)
            last = page_keys[-1]
            if len(records) > before['count']:
                raise ValueError('Retrieved more records than source key count')
            if len(records) == before['count'] or len(page) < PAGE_SIZE:
                break
        after = self.snapshot('after')
        retrieved_keys = [row[self.key_field] for row in records]
        stable = (before['revision'] == after['revision'] and before['columns'] == after['columns']
                  and before['keys'] == after['keys'] == retrieved_keys)
        return before, after, records, stable
