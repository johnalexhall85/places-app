"""NCHS Drug Poisoning Mortality by County (model-based): retrieval and parsing.

Stages every 2003–2021 row from NCHS's ``rpvx-m2md.csv`` export (``utf-8-sig``) so a later
history task can reuse the staged archive. Publishes 2021 county-level observations only,
exactly as NCHS releases them, with 95% intervals from NCHS's model. Nothing is aggregated,
combined, rescaled, or crosswalked. There are no state or national rows in this file.
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

MAX_ROWS_PER_FILE = 100_000
MEASURE_IDS = ['drug_poisoning_death_rate']
RATE_COLUMN = 'Model-based Death Rate'
CI_LOW_COLUMN = 'Lower Confidence Limit'
CI_HIGH_COLUMN = 'Upper Confidence Limit'
SOURCE_LEVEL = 'County'
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'nchs_drug_poisoning_county'
REQUIRED_COLUMNS = (
    'FIPS', 'Year', 'State', 'FIPS State', 'County', 'Population',
    RATE_COLUMN, 'Standard Deviation', CI_LOW_COLUMN, CI_HIGH_COLUMN,
    'Urban/Rural Category', 'Census Division',
)


def load_registry():
    path = Path(__file__).with_name('registry') / 'nchs_drug_poisoning_2021.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    ids = [m['measure_id'] for m in config['measures']]
    if (ids != MEASURE_IDS or config['geographies'] != ['county'] or
            config['aggregation_method'] != 'none' or config['refresh_policy']['auto_publish'] or
            config['observation_period'] != '2021' or
            config['value_type'] != 'model_based_age_adjusted_rate'):
        raise ValueError('NCHS drug poisoning registry contract changed')
    if len(config.get('source_files') or []) != 1:
        raise ValueError('NCHS drug poisoning registry must declare exactly one source file')
    for measure in config['measures']:
        if measure['kind'] != 'rate_per_100k' or measure.get('geographies') != ['county']:
            raise ValueError(f'NCHS drug poisoning measure {measure["measure_id"]} is incomplete')
        if not measure.get('source_ci_low_field') or not measure.get('source_ci_high_field'):
            raise ValueError(f'NCHS drug poisoning measure {measure["measure_id"]} requires CI fields')
    return config


def required_roles(config):
    return {item['role'] for item in config['source_files']}


def measure_by_file(config):
    return {m['source_file']: m for m in config['measures']}


# ---------------------------------------------------------------- retrieval

def fetch(config, directory=ROOT):
    """Download the data.cdc.gov NCHS drug poisoning CSV into ``directory`` and record SHA-256."""
    from app.area_pilot.operations import disk_guard

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    disk_guard(directory, 2 * MAX_CSV)
    files, headers = [], {}
    for spec in config['source_files']:
        target = directory / spec['filename']
        headers[spec['role']] = _bounded_get(spec['url'], target, MAX_CSV)
        files.append(file_evidence(target, spec['url'], spec['role'], headers[spec['role']]))
    return files, headers


# ---------------------------------------------------------------- parsing

def normalize_code(raw_code):
    """Zero-pad county FIPS to 5 digits when numeric and at most 5 digits."""
    code = str(raw_code or '').strip()
    if code.isdigit() and len(code) <= 5:
        return code.zfill(5)
    return code


def parse_value(raw, ci_low_raw='', ci_high_raw='', measure=None):
    """Return (value, ci_low, ci_high, 'available'). Blank, suppressed, bad, or <=0 stops the run."""
    label = measure['measure_id'] if isinstance(measure, dict) else str(measure or RATE_COLUMN)
    val = str(raw if raw is not None else '').strip()
    lo = str(ci_low_raw if ci_low_raw is not None else '').strip()
    hi = str(ci_high_raw if ci_high_raw is not None else '').strip()
    if val == '':
        raise ValueError(f'Blank NCHS drug poisoning value in {label}')
    if not NUMBER.fullmatch(val):
        raise ValueError(f'Undocumented NCHS drug poisoning value token in {label}: {val[:20]!r}')
    number = Decimal(val)
    if number <= 0:
        raise ValueError(f'Non-positive NCHS drug poisoning rate in {label}: {val[:20]!r}')
    if lo == '' or hi == '':
        raise ValueError(f'Blank NCHS drug poisoning CI bound in {label}: {lo!r}/{hi!r}')
    if not NUMBER.fullmatch(lo) or not NUMBER.fullmatch(hi):
        raise ValueError(f'Undocumented NCHS drug poisoning CI token in {label}: {lo[:20]!r}/{hi[:20]!r}')
    low, high = Decimal(lo), Decimal(hi)
    if low < 0 or not (low <= number <= high):
        raise ValueError(
            f'Invalid NCHS drug poisoning CI bounds in {label}: value={number}, ci=({low}, {high})'
        )
    return number, low, high, 'available'


def observation_values(record, source_file, config):
    measure = measure_by_file(config)[source_file]
    raw = str(record[measure['source_field']]).strip()
    lo_raw = str(record[measure['source_ci_low_field']]).strip()
    hi_raw = str(record[measure['source_ci_high_field']]).strip()
    value, ci_low, ci_high, status = parse_value(raw, lo_raw, hi_raw, measure)
    return [{
        'measure': measure,
        'value': value,
        'ci_low': ci_low,
        'ci_high': ci_high,
        'status': status,
        'source_value': raw,
        'value_type': config['value_type'],
    }]


def parse_csv(path, source_spec, config):
    """Stream rpvx-m2md.csv (utf-8-sig); stage every 2003–2021 row, validate 2021 strictly."""
    source_file = source_spec['filename']
    measure = measure_by_file(config)[source_file]
    expected_years = set(config['staged_years'])
    publish_period = str(config['observation_period'])

    records, total = {}, 0
    year_counts, check_values = {}, {}

    with Path(path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.reader(source)
        header = next(reader, None)
        if header is None:
            raise ValueError(f'NCHS drug poisoning CSV is empty: {path}')
        if config.get('expected_column_count') and len(header) != config['expected_column_count']:
            raise ValueError(f'NCHS drug poisoning CSV column count differs from reviewed schema: {source_file}')
        if config.get('expected_header_sha256') and header_sha(header) != config['expected_header_sha256']:
            raise ValueError(f'NCHS drug poisoning CSV header differs from reviewed schema: {source_file}')
        missing_cols = [col for col in REQUIRED_COLUMNS if col not in header]
        if missing_cols:
            raise ValueError(f'NCHS drug poisoning CSV missing required columns in {source_file}: {missing_cols}')
        idx = {name: header.index(name) for name in REQUIRED_COLUMNS}

        for values in reader:
            total += 1
            if len(values) != len(header):
                raise ValueError(f'NCHS drug poisoning {source_file} row {total} has {len(values)} columns')
            row_year = values[idx['Year']].strip()
            if row_year not in expected_years:
                raise ValueError(
                    f'Unexpected NCHS drug poisoning Year in {source_file} row {total}: {row_year!r}'
                )
            source_code = normalize_code(values[idx['FIPS']])
            raw_val = values[idx[measure['source_field']]].strip()
            raw_lo = values[idx[measure['source_ci_low_field']]].strip()
            raw_hi = values[idx[measure['source_ci_high_field']]].strip()
            if row_year == publish_period:
                parse_value(raw_val, raw_lo, raw_hi, measure)

            key = (source_file, SOURCE_LEVEL, source_code, row_year)
            if key in records:
                raise ValueError(f'Duplicate NCHS drug poisoning geography/year key: {key}')
            records[key] = dict(zip(header, values))
            year_counts[row_year] = year_counts.get(row_year, 0) + 1
            if row_year == publish_period and source_code in (source_spec.get('check_values') or {}):
                check_values[source_code] = {'value': raw_val, 'ci_low': raw_lo, 'ci_high': raw_hi}
            if total > MAX_ROWS_PER_FILE:
                raise ValueError(f'NCHS drug poisoning row limit exceeded in {source_file}')

    if total == 0:
        raise ValueError(f'NCHS drug poisoning CSV has no data rows: {source_file}')

    return records, {
        'source_file': source_file,
        'measure_id': measure['measure_id'],
        'header_sha256': header_sha(header),
        'total_rows': total,
        'year_counts': dict(sorted(year_counts.items())),
        'publish_period': publish_period,
        'publish_period_rows': year_counts.get(publish_period, 0),
        'check_values': check_values,
    }


# ---------------------------------------------------------------- geography

def classify(records, county_geoids, config=None):
    """Exact 5-digit FIPS joins to 2024 TIGER counties across all staged years (no national/state rows)."""
    counties = set(county_geoids)
    classified, unexplained, source_only_counts = {}, [], {}

    for key in sorted(records):
        source_file, source_level, code, source_period = key
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
        if source_level != SOURCE_LEVEL:
            item['exclusion_reason'] = 'unknown_level'
            unexplained.append(key)
        elif code in LEGACY_CT_COUNTIES:
            item['exclusion_reason'] = 'legacy_connecticut_county_code'
        elif re.fullmatch(r'[0-9]{5}', code) and code in counties:
            item.update(level='county', geoid=code, boundary_status='matched')
        elif re.fullmatch(r'[0-9]{5}', code):
            item['exclusion_reason'] = 'no_2024_boundary'
        else:
            item['exclusion_reason'] = 'malformed_fips'
            unexplained.append(key)

        if item['boundary_status'] == 'source_only':
            bucket = (source_file, source_period, item['exclusion_reason'])
            source_only_counts[bucket] = source_only_counts.get(bucket, 0) + 1
        classified[key] = item

    matched = {}
    for item in classified.values():
        if item['boundary_status'] == 'matched':
            matched.setdefault((item['source_file'], item['source_period']), []).append(item['geoid'])
    duplicates = sorted({
        f'{fname}:{period}:{geoid}'
        for (fname, period), ids in matched.items()
        for geoid in ids if ids.count(geoid) > 1
    })
    return classified, {
        'unexplained': unexplained,
        'source_only_counts': {
            f'{k[0]}|{k[1]}|{k[2]}': v for k, v in sorted(source_only_counts.items())
        },
        'duplicate_geoids': duplicates,
    }


def boundary_without_source(classified, county_geoids, config=None):
    """2024 boundary counties absent from the published observation year (2021)."""
    cfg = config or load_registry()
    publish_period = str(cfg['observation_period'])
    matched = {
        item['geoid']
        for item in classified.values()
        if item['boundary_status'] == 'matched' and item['source_period'] == publish_period
    }
    result, counts = {}, {}
    for geoid in sorted(set(county_geoids)):
        if geoid in matched:
            continue
        if re.fullmatch(r'091[1-9]0', geoid):
            reason = 'connecticut_planning_region_not_in_source'
        else:
            reason = 'no_source_row'
        result[f'county:{geoid}'] = reason
        counts[f'county|{reason}'] = counts.get(f'county|{reason}', 0) + 1
    return result, {'counts': counts}


def retrieve(config, directory=ROOT, skip_fetch=False):
    """Fetch (unless ``skip_fetch``) and parse the NCHS drug poisoning CSV."""
    directory = Path(directory)
    if skip_fetch:
        files, headers = [], {}
        for spec in config['source_files']:
            target = directory / spec['filename']
            if not target.is_file():
                raise ValueError(f'Archived NCHS drug poisoning CSV not found: {target}')
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
    'CI_HIGH_COLUMN', 'CI_LOW_COLUMN', 'LEGACY_CT_COUNTIES', 'MAX_CSV', 'MAX_ROWS_PER_FILE',
    'MEASURE_IDS', 'NUMBER', 'RATE_COLUMN', 'REQUIRED_COLUMNS', 'ROOT', 'SOURCE_LEVEL',
    'boundary_without_source', 'classify', 'fetch', 'file_evidence', 'header_sha', 'load_registry',
    'measure_by_file', 'normalize_code', 'observation_values', 'parse_csv', 'parse_value',
    'range_problems', 'required_roles', 'retrieve', 'semantic_sha',
]
