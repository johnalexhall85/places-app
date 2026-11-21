"""NCI/CDC State Cancer Profiles death rates (2020–2024): retrieval and parsing.

Publishes only the six all-sites, lung and bronchus, and colon and rectum county/state exports
(``<site>_county.csv`` and ``<site>_state.csv``), encoded in latin-1, exactly as NCI releases them.
Female breast and prostate exports are never staged or published. Nothing is aggregated, combined,
rescaled, or crosswalked. National values are stored for reference only.
"""
from __future__ import annotations

import csv
import json
import re
from decimal import Decimal
from pathlib import Path

from app.area_pilot.hds_mortality import (
    LEGACY_CT_COUNTIES, MAX_CSV, NUMBER, _bounded_get, file_evidence,
    header_sha, range_problems, semantic_sha,
)

MAX_DATA_ROWS_PER_FILE = 5_000
MEASURE_IDS = ['cancer_death_rate_all', 'cancer_death_rate_lung', 'cancer_death_rate_colorectal']
EXCLUDED_PREFIXES = ('breast_female', 'prostate')
NCI_STATE_FILE_CODES = {'02900': 'Alaska', '11001': 'District of Columbia', '72001': 'Puerto Rico'}
RATE_COLUMN = 'Age-Adjusted Death Rate([rate note]) - deaths per 100,000'
CI_LOW_COLUMN = 'Lower CI (Rate)'
CI_HIGH_COLUMN = 'Upper CI (Rate)'
COUNT_COLUMN = 'Average Annual Count'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'nci_scp_mortality_2024'


def load_registry():
    path = Path(__file__).with_name('registry') / 'nci_cancer_mortality_2020_2024.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    ids = [m['measure_id'] for m in config['measures']]
    if (ids != MEASURE_IDS or config['geographies'] != ['state', 'county'] or
            config['aggregation_method'] != 'none' or config['refresh_policy']['auto_publish'] or
            config['observation_period'] != '2020–2024' or config['value_type'] != 'age_adjusted_rate'):
        raise ValueError('NCI cancer mortality registry contract changed')
    if len(config.get('source_files') or []) != 6:
        raise ValueError('NCI cancer mortality registry must declare exactly six source files')
    for spec in config['source_files']:
        if any(spec['filename'].startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            raise ValueError(f'Excluded NCI cancer file must not be configured: {spec["filename"]}')
    for measure in config['measures']:
        if measure['kind'] != 'rate_per_100k' or measure.get('geographies') != ['state', 'county']:
            raise ValueError(f'NCI cancer mortality measure {measure["measure_id"]} is incomplete')
        if not measure.get('source_ci_low_field') or not measure.get('source_ci_high_field'):
            raise ValueError(f'NCI cancer mortality measure {measure["measure_id"]} requires CI fields')
    return config


def required_roles(config):
    return {item['role'] for item in config['source_files']}


def measure_by_file(config):
    by_id = {m['measure_id']: m for m in config['measures']}
    return {spec['filename']: by_id[spec['measure_id']] for spec in config['source_files']}


def spec_by_file(config):
    return {spec['filename']: spec for spec in config['source_files']}


# ---------------------------------------------------------------- retrieval

def fetch(config, directory=ROOT):
    """Download the six NCI State Cancer Profiles CSVs into ``directory`` and record SHA-256."""
    from app.area_pilot.operations import disk_guard

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    disk_guard(directory, 6 * MAX_CSV)
    files, headers = [], {}
    for spec in config['source_files']:
        target = directory / spec['filename']
        headers[spec['role']] = _bounded_get(spec['url'], target, MAX_CSV)
        files.append(file_evidence(target, spec['url'], spec['role'], headers[spec['role']]))
    return files, headers


# ---------------------------------------------------------------- parsing

def parse_value(raw, ci_low_raw='*', ci_high_raw='*', measure=None, token='*'):
    """Return (value, ci_low, ci_high, status). Positive rate + 95% CI -> available; '*' -> suppressed."""
    label = measure['measure_id'] if isinstance(measure, dict) else str(measure or RATE_COLUMN)
    val = str(raw if raw is not None else '').strip()
    lo = str(ci_low_raw if ci_low_raw is not None else '').strip()
    hi = str(ci_high_raw if ci_high_raw is not None else '').strip()
    if val == token:
        if lo != token or hi != token:
            raise ValueError(
                f'Suppressed NCI cancer row in {label} has non-suppressed CI: {lo!r}/{hi!r}'
            )
        return None, None, None, 'suppressed'
    if not NUMBER.fullmatch(val):
        raise ValueError(f'Undocumented NCI cancer value token in {label}: {val[:20]!r}')
    number = Decimal(val)
    if number <= 0:
        raise ValueError(f'Non-positive NCI cancer mortality rate in {label}: {val[:20]!r}')
    if not NUMBER.fullmatch(lo) or not NUMBER.fullmatch(hi):
        raise ValueError(f'Undocumented NCI cancer CI token in {label}: {lo[:20]!r}/{hi[:20]!r}')
    low, high = Decimal(lo), Decimal(hi)
    if low < 0 or not (low <= number <= high):
        raise ValueError(
            f'Invalid NCI cancer CI bounds in {label}: value={number}, ci=({low}, {high})'
        )
    return number, low, high, 'available'


def observation_values(record, source_file, config):
    measure = measure_by_file(config)[source_file]
    raw = str(record[measure['source_field']]).strip()
    lo_raw = str(record[measure['source_ci_low_field']]).strip()
    hi_raw = str(record[measure['source_ci_high_field']]).strip()
    value, ci_low, ci_high, status = parse_value(
        raw, lo_raw, hi_raw, measure, token=config.get('suppression_token', '*'),
    )
    return [{
        'measure': measure,
        'value': value,
        'ci_low': ci_low,
        'ci_high': ci_high,
        'status': status,
        'source_value': raw,
        'value_type': config['value_type'],
    }]


def _clean_preamble_line(line):
    stripped = line.strip()
    if not stripped:
        return ''
    parsed = next(csv.reader([stripped]), [])
    return parsed[0].strip() if len(parsed) == 1 else stripped


def parse_csv(path, source_spec, config):
    """Parse one latin-1 NCI cancer CSV: verify title, header, data rows until first blank line."""
    source_file = source_spec['filename']
    source_level = source_spec['source_level']
    measure = measure_by_file(config)[source_file]
    period = config['observation_period']
    expected_title = source_spec['expected_title']
    token = config.get('suppression_token', '*')
    header_prefix = f'{source_level},FIPS'

    lines = Path(path).read_text(encoding='latin-1').splitlines()
    header_idx = next((i for i, line in enumerate(lines) if line.startswith(header_prefix)), None)
    if header_idx is None:
        raise ValueError(
            f'NCI cancer CSV header starting {header_prefix!r} not found in {source_file}'
        )
    preamble = [_clean_preamble_line(line) for line in lines[:header_idx] if line.strip()]
    if expected_title not in preamble:
        raise ValueError(
            f'NCI cancer CSV title line mismatch in {source_file}: '
            f'expected {expected_title!r}, found {preamble[:4]!r}'
        )

    header = next(csv.reader([lines[header_idx]]))
    if source_spec.get('expected_column_count') and len(header) != source_spec['expected_column_count']:
        raise ValueError(f'NCI cancer CSV column count differs from reviewed schema: {source_file}')
    if (source_spec.get('expected_header_sha256') and
            header_sha(header) != source_spec['expected_header_sha256']):
        raise ValueError(f'NCI cancer CSV header differs from reviewed schema: {source_file}')

    required = (
        source_level, 'FIPS', measure['source_field'],
        measure['source_ci_low_field'], measure['source_ci_high_field'], COUNT_COLUMN,
    )
    missing_cols = [col for col in required if col not in header]
    if missing_cols:
        raise ValueError(f'NCI cancer CSV missing required columns in {source_file}: {missing_cols}')
    idx = {name: header.index(name) for name in required}

    records, data_rows, suppressed_rows, check_values = {}, 0, 0, {}
    for line in lines[header_idx + 1:]:
        if not line.strip():
            break
        data_rows += 1
        values = next(csv.reader([line]))
        if len(values) != len(header):
            raise ValueError(
                f'NCI cancer {source_file} row {data_rows} has {len(values)} columns; '
                f'expected {len(header)}'
            )
        fips = values[idx['FIPS']].strip()
        raw_val = values[idx[measure['source_field']]].strip()
        raw_lo = values[idx[measure['source_ci_low_field']]].strip()
        raw_hi = values[idx[measure['source_ci_high_field']]].strip()
        _, _, _, status = parse_value(raw_val, raw_lo, raw_hi, measure, token=token)

        key = (source_file, source_level, fips, period)
        if key in records:
            raise ValueError(f'Duplicate NCI cancer geography key: {key}')
        records[key] = dict(zip(header, values))
        if status == 'suppressed':
            suppressed_rows += 1
        if fips == '00000':
            check_values['national'] = {'value': raw_val, 'ci_low': raw_lo, 'ci_high': raw_hi}
        elif fips in (source_spec.get('check_values') or {}):
            check_values[fips] = {'value': raw_val, 'ci_low': raw_lo, 'ci_high': raw_hi}
        if data_rows > MAX_DATA_ROWS_PER_FILE:
            raise ValueError(f'NCI cancer selected-row limit exceeded in {source_file}')

    if data_rows == 0:
        raise ValueError(f'NCI cancer CSV has no data rows: {source_file}')

    return records, {
        'source_file': source_file,
        'source_level': source_level,
        'measure_id': measure['measure_id'],
        'title': expected_title,
        'header_sha256': header_sha(header),
        'data_rows': data_rows,
        'suppressed_rows': suppressed_rows,
        'check_values': check_values,
    }


# ---------------------------------------------------------------- geography

def classify(records, state_geoids, county_geoids, config=None):
    """Exact FIPS joins to 2024 TIGER states/counties; 00000 -> US, SS000 -> state, else county."""
    cfg = config or load_registry()
    by_file = measure_by_file(cfg)
    boundaries = {'state': set(state_geoids), 'county': set(county_geoids)}

    state_national_measures = {
        (by_file[sf]['measure_id'], sp)
        for sf, sl, code, sp in records
        if sl == 'State' and code == '00000' and sf in by_file
    }

    classified, unexplained, source_only_counts = {}, [], {}
    for key in sorted(records):
        source_file, source_level, code, source_period = key
        measure_id = by_file[source_file]['measure_id'] if source_file in by_file else source_file
        item = {
            'source_file': source_file,
            'source_level': source_level,
            'source_code': code,
            'source_period': source_period,
            'level': None,
            'geoid': None,
            'boundary_status': 'source_only',
            'exclusion_reason': None,
        }
        if not re.fullmatch(r'[0-9]{5}', code):
            item['exclusion_reason'] = 'malformed_fips'
            unexplained.append(key)
        elif code == '00000':
            if source_level == 'County' and (measure_id, source_period) in state_national_measures:
                item['exclusion_reason'] = 'duplicate_national_row_in_county_file'
            else:
                item.update(level='national', geoid='US', boundary_status='national_reference')
        elif source_level == 'State':
            if code.endswith('000'):
                state_geoid = code[:2]
                if state_geoid in boundaries['state']:
                    item.update(level='state', geoid=state_geoid, boundary_status='matched')
                else:
                    item['exclusion_reason'] = 'no_2024_boundary'
            elif NCI_STATE_FILE_CODES.get(code) == (records[key].get('State') or '').strip():
                # NCI state files encode AK as 02900, DC as 11001, and PR as 72001 (contract Amendment 1).
                # These are NCI's codes for the whole state, so they publish at state level only.
                state_geoid = code[:2]
                if state_geoid in boundaries['state']:
                    item.update(level='state', geoid=state_geoid, boundary_status='matched')
                else:
                    item['exclusion_reason'] = 'no_2024_boundary'
            else:
                item['exclusion_reason'] = 'no_2024_boundary'
        elif source_level == 'County':
            if code in LEGACY_CT_COUNTIES:
                item['exclusion_reason'] = 'legacy_connecticut_county_code'
            elif code == '72001' and (records[key].get('County') or '').strip() == 'Puerto Rico':
                item['exclusion_reason'] = 'puerto_rico_territory_aggregate_not_county'
            elif code.endswith('000'):
                item['exclusion_reason'] = 'no_2024_boundary'
            elif code in boundaries['county']:
                item.update(level='county', geoid=code, boundary_status='matched')
            else:
                item['exclusion_reason'] = 'no_2024_boundary'
        else:
            item['exclusion_reason'] = 'unknown_level'
            unexplained.append(key)

        if item['boundary_status'] == 'source_only':
            bucket = (source_file, source_level, item['exclusion_reason'])
            source_only_counts[bucket] = source_only_counts.get(bucket, 0) + 1
        classified[key] = item

    matched = {}
    for item in classified.values():
        if item['boundary_status'] in ('matched', 'national_reference'):
            mid = by_file[item['source_file']]['measure_id'] if item['source_file'] in by_file else item['source_file']
            matched.setdefault((mid, item['level']), []).append(item['geoid'])
    duplicates = sorted({
        f'{mid}:{lvl}:{geoid}'
        for (mid, lvl), ids in matched.items()
        for geoid in ids if ids.count(geoid) > 1
    })
    return classified, {
        'unexplained': unexplained,
        'source_only_counts': {
            f'{k[0]}|{k[1]}|{k[2]}': v for k, v in sorted(source_only_counts.items())
        },
        'duplicate_geoids': duplicates,
    }


def boundary_without_source(classified, state_geoids, county_geoids, config=None):
    """2024 boundary states/counties absent from one or more NCI cancer measures."""
    cfg = config or load_registry()
    by_file = measure_by_file(cfg)
    by_measure = {}
    for item in classified.values():
        if item['boundary_status'] == 'matched':
            mid = by_file[item['source_file']]['measure_id'] if item['source_file'] in by_file else item['source_file']
            by_measure.setdefault(mid, set()).add((item['level'], item['geoid']))
    matched = set.intersection(*by_measure.values()) if by_measure else set()
    result, counts = {}, {}
    for level, geoids in (('state', state_geoids), ('county', county_geoids)):
        for geoid in sorted(set(geoids)):
            if (level, geoid) in matched:
                continue
            if level == 'county' and re.fullmatch(r'091[1-9]0', geoid):
                reason = 'connecticut_planning_region_not_in_source'
            else:
                reason = 'no_source_row'
            result[f'{level}:{geoid}'] = reason
            counts[f'{level}|{reason}'] = counts.get(f'{level}|{reason}', 0) + 1
    return result, {'counts': counts}


def retrieve(config, directory=ROOT, skip_fetch=False):
    """Fetch (unless ``skip_fetch``) and parse the six NCI cancer mortality CSVs."""
    directory = Path(directory)
    if skip_fetch:
        files, headers = [], {}
        for spec in config['source_files']:
            target = directory / spec['filename']
            if not target.is_file():
                raise ValueError(f'Archived NCI cancer CSV not found: {target}')
            files.append(file_evidence(target, spec['url'], spec['role']))
    else:
        files, headers = fetch(config, directory)

    records, file_stats, header_shas = {}, {}, {}
    for spec in config['source_files']:
        path = directory / spec['filename']
        parsed, stats = parse_csv(path, spec, config)
        records.update(parsed)
        file_stats[spec['filename']] = stats
        header_shas[spec['filename']] = stats['header_sha256']

    stats = {'header_sha256': header_shas, 'files': file_stats}
    provenance = {'skip_fetch': skip_fetch, 'http': headers, 'csv_stats': stats}
    return records, stats, files, provenance


__all__ = [
    'CI_HIGH_COLUMN', 'CI_LOW_COLUMN', 'COUNT_COLUMN', 'EXCLUDED_PREFIXES', 'LEGACY_CT_COUNTIES',
    'MAX_CSV', 'MAX_DATA_ROWS_PER_FILE', 'MEASURE_IDS', 'NUMBER', 'RATE_COLUMN', 'ROOT',
    'boundary_without_source', 'classify', 'fetch', 'file_evidence', 'header_sha', 'load_registry',
    'measure_by_file', 'observation_values', 'parse_csv', 'parse_value', 'range_problems',
    'required_roles', 'retrieve', 'semantic_sha', 'spec_by_file',
]
