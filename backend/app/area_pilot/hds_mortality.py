"""CDC Interactive Atlas of Heart Disease and Stroke mortality (2022–2024): retrieval and parsing.

Publishes only the Overall/Overall rows from CDC's heart disease (``mri7-5jtw.csv``) and stroke
(``y5ii-knwc.csv``) mortality exports for the nation, states, and counties, exactly as CDC releases
them. County rates are spatially smoothed by CDC; state and national rates are not smoothed.
Nothing is aggregated, combined, rescaled, or crosswalked. National values are reference only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
from decimal import Decimal
from pathlib import Path

import requests

from app.area_pilot import epa_aqi
from app.area_pilot.source import digest

MAX_CSV = 200 * 1024**2
MAX_SELECTED_ROWS_PER_FILE = 5_000
USER_AGENT = 'CHIP-area-ingest/1.0'
NUMBER = re.compile(r'^-?[0-9]+(\.[0-9]+)?$')
MEASURE_IDS = ['heart_disease_death_rate', 'stroke_death_rate']
LEVELS = {'Nation': 'national', 'State': 'state', 'County': 'county'}
LEGACY_CT_COUNTIES = {'09001', '09003', '09005', '09007', '09009', '09011', '09013', '09015'}
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'cdc_hds_mortality_2024'
REQUIRED_COLUMNS = (
    'Year', 'GeographicLevel', 'LocationID', 'Data_Value', 'Data_Value_Type',
    'Data_Value_Footnote_Symbol', 'Data_Value_Footnote', 'Stratification1', 'Stratification2',
)


def load_registry():
    path = Path(__file__).with_name('registry') / 'cdc_hds_mortality_2022_2024.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    ids = [m['measure_id'] for m in config['measures']]
    if (ids != MEASURE_IDS or config['geographies'] != ['state', 'county'] or
            config['aggregation_method'] != 'none' or config['refresh_policy']['auto_publish'] or
            config['observation_period'] != '2022–2024'):
        raise ValueError('CDC HDS mortality registry contract changed')
    if set(config.get('value_type_by_level') or {}) != {'national', 'state', 'county'}:
        raise ValueError('CDC HDS mortality registry value_type_by_level is incomplete')
    for measure in config['measures']:
        if measure['kind'] != 'rate_per_100k' or measure.get('geographies') != ['state', 'county']:
            raise ValueError(f'CDC HDS mortality measure {measure["measure_id"]} is incomplete')
        if any(key in measure for key in ('ci_low', 'ci_high', 'moe', 'source_ci_field')):
            raise ValueError('CDC HDS mortality publishes no uncertainty fields')
    return config


def required_roles(config):
    return {item['role'] for item in config['source_files']}


def measure_by_file(config):
    return {m['source_file']: m for m in config['measures']}


# ---------------------------------------------------------------- retrieval

def _bounded_get(url, target, limit, attempts=3):
    """Stream to a temporary file with timeouts, a byte cap, and bounded retries."""
    temporary = target.with_name(target.name + '.part')
    last = None
    for attempt in range(attempts):
        try:
            size = 0
            with requests.get(url, stream=True, timeout=(10, 120), allow_redirects=True,
                              headers={'User-Agent': USER_AGENT}) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError(f'Unexpected HTTP {response.status_code} for {url}')
                headers = {k.lower(): v for k, v in response.headers.items()
                           if k.lower() in ('last-modified', 'etag', 'content-length', 'content-type')}
                with temporary.open('wb') as output:
                    for chunk in response.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(f'CDC HDS response exceeds {limit} bytes: {url}')
                        output.write(chunk)
            if size == 0:
                raise ValueError(f'CDC HDS response was empty: {url}')
            os.replace(temporary, target)
            return headers
        except (requests.RequestException, OSError) as exc:
            last = exc
            temporary.unlink(missing_ok=True)
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
        except ValueError:
            temporary.unlink(missing_ok=True)
            raise
    raise RuntimeError(f'CDC HDS download failed after {attempts} attempts: {url}') from last


def file_evidence(path, url, role, http_headers=None):
    return epa_aqi.file_evidence(path, url, role, http_headers)


def fetch(config, directory=ROOT):
    """Download the two CDC HDS CSVs into ``directory`` and record SHA-256 evidence."""
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

def header_sha(header):
    return digest(header)


def normalize_code(source_level, raw_code):
    """Pad LocationID to 2 digits for states and 5 for counties; keep Nation code as '0'."""
    code = str(raw_code or '').strip()
    if source_level == 'State' and code.isdigit() and len(code) <= 2:
        return code.zfill(2)
    if source_level == 'County' and code.isdigit() and len(code) <= 5:
        return code.zfill(5)
    return code


def parse_value(raw, footnote_symbol='', footnote='', measure=None, symbol='~',
                expected_footnote='Insufficient Data'):
    """Return (Decimal|None, status). Positive number -> available; blank + '~' -> suppressed."""
    label = measure['measure_id'] if isinstance(measure, dict) else str(measure or 'Data_Value')
    value = str(raw if raw is not None else '').strip()
    sym = str(footnote_symbol if footnote_symbol is not None else '').strip()
    note = str(footnote if footnote is not None else '').strip()
    if value == '':
        if sym == symbol and (note == '' or note == expected_footnote):
            return None, 'suppressed'
        raise ValueError(
            f'Unexpected blank CDC HDS value in {label} with footnote {sym!r}/{note!r}'
        )
    if not NUMBER.fullmatch(value):
        raise ValueError(f'Undocumented CDC HDS value token in {label}: {value[:20]!r}')
    number = Decimal(value)
    if number <= 0:
        raise ValueError(f'Non-positive CDC HDS mortality rate in {label}: {value[:20]!r}')
    return number, 'available'


def range_problems(number, measure=None):
    problems = []
    if number <= 0 or number > Decimal(100_000):
        problems.append('outside_documented_scale')
    return problems


def observation_values(record, source_file, config):
    measure = measure_by_file(config)[source_file]
    raw = str(record['Data_Value']).strip()
    sym = str(record.get('Data_Value_Footnote_Symbol') or '').strip()
    note = str(record.get('Data_Value_Footnote') or '').strip()
    value, status = parse_value(
        raw, sym, note, measure,
        symbol=config.get('suppression_symbol', '~'),
        expected_footnote=config.get('suppression_footnote', 'Insufficient Data'),
    )
    source_value = raw if raw != '' else sym
    return [{
        'measure': measure,
        'value': value,
        'status': status,
        'source_value': source_value,
        'value_type': str(record['Data_Value_Type']).strip(),
    }]


def parse_csv(path, source_spec, config):
    """Stream one CDC HDS CSV with utf-8-sig; keep only Overall/Overall rows."""
    source_file = source_spec['filename']
    measure = measure_by_file(config)[source_file]
    expected_year = str(config['observation_year'])
    period = config['observation_period']
    value_types = config['value_type_by_level']
    sym_token = config.get('suppression_symbol', '~')
    note_token = config.get('suppression_footnote', 'Insufficient Data')

    records, total, kept = {}, 0, 0
    level_counts, suppressed_by_level, check_values = {}, {}, {}

    with Path(path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.reader(source)
        header = next(reader, None)
        if header is None:
            raise ValueError(f'CDC HDS CSV is empty: {path}')
        if config.get('expected_column_count') and len(header) != config['expected_column_count']:
            raise ValueError(f'CDC HDS CSV column count differs from reviewed schema: {source_file}')
        if config.get('expected_header_sha256') and header_sha(header) != config['expected_header_sha256']:
            raise ValueError(f'CDC HDS CSV header differs from reviewed schema: {source_file}')
        missing_cols = [col for col in REQUIRED_COLUMNS if col not in header]
        if missing_cols:
            raise ValueError(f'CDC HDS CSV missing required columns in {source_file}: {missing_cols}')
        idx = {name: header.index(name) for name in REQUIRED_COLUMNS}

        for values in reader:
            total += 1
            if len(values) != len(header):
                raise ValueError(f'CDC HDS {source_file} row {total} has {len(values)} columns')
            if values[idx['Stratification1']].strip() != 'Overall':
                continue
            if values[idx['Stratification2']].strip() != 'Overall':
                continue

            row_year = values[idx['Year']].strip()
            if row_year != expected_year:
                raise ValueError(
                    f'CDC HDS {source_file} row {total} has Year={row_year!r}; expected {expected_year!r}'
                )
            source_level = values[idx['GeographicLevel']].strip()
            if source_level not in LEVELS:
                raise ValueError(f'Unexpected CDC HDS GeographicLevel in {source_file}: {source_level!r}')
            chip_level = LEVELS[source_level]
            row_value_type = values[idx['Data_Value_Type']].strip()
            if row_value_type != value_types[chip_level]:
                raise ValueError(
                    f'Unexpected CDC HDS Data_Value_Type for {source_level} in {source_file}: '
                    f'{row_value_type!r}; expected {value_types[chip_level]!r}'
                )

            source_code = normalize_code(source_level, values[idx['LocationID']])
            raw_val = values[idx['Data_Value']]
            _, status = parse_value(
                raw_val,
                values[idx['Data_Value_Footnote_Symbol']],
                values[idx['Data_Value_Footnote']],
                measure,
                symbol=sym_token,
                expected_footnote=note_token,
            )

            key = (source_file, source_level, source_code, period)
            if key in records:
                raise ValueError(f'Duplicate CDC HDS geography key: {key}')
            records[key] = dict(zip(header, values))
            kept += 1
            level_counts[source_level] = level_counts.get(source_level, 0) + 1
            if status == 'suppressed':
                suppressed_by_level[source_level] = suppressed_by_level.get(source_level, 0) + 1
            if source_level == 'Nation' and source_code == '0':
                check_values['national'] = raw_val.strip()
            elif source_level == 'County' and source_code in (source_spec.get('check_values') or {}):
                check_values[source_code] = raw_val.strip()
            if kept > MAX_SELECTED_ROWS_PER_FILE:
                raise ValueError(f'CDC HDS selected-row limit exceeded in {source_file}')

    return records, {
        'source_file': source_file,
        'measure_id': measure['measure_id'],
        'header_sha256': header_sha(header),
        'total_rows': total,
        'kept_rows': kept,
        'level_counts': dict(sorted(level_counts.items())),
        'suppressed_by_level': dict(sorted(suppressed_by_level.items())),
        'suppressed_counties': suppressed_by_level.get('County', 0),
        'check_values': check_values,
    }


def semantic_sha(records):
    """Order-independent SHA-256 across all staged rows."""
    sha = hashlib.sha256()
    sha.update(b'[')
    first = True
    for source_file, source_level, source_code, source_period in sorted(records):
        if not first:
            sha.update(b',')
        first = False
        chunk = json.dumps(
            [source_file, source_level, source_code, source_period,
             records[(source_file, source_level, source_code, source_period)]],
            sort_keys=True, separators=(',', ':'),
        )
        sha.update(chunk.encode('utf-8'))
    sha.update(b']')
    return sha.hexdigest()


# ---------------------------------------------------------------- geography

def classify(records, state_geoids, county_geoids, config=None):
    """Exact FIPS joins to 2024 TIGER states/counties; Nation -> national_reference."""
    classified, unexplained, source_only_counts = {}, [], {}
    boundaries = {'state': set(state_geoids), 'county': set(county_geoids)}

    for key in sorted(records):
        source_file, source_level, code, source_period = key
        level = LEVELS.get(source_level)
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
        if level == 'national':
            if code == '0':
                item.update(level='national', geoid='US', boundary_status='national_reference')
            else:
                item['exclusion_reason'] = 'malformed_fips'
                unexplained.append(key)
        elif level == 'state':
            if re.fullmatch(r'[0-9]{2}', code) and code in boundaries['state']:
                item.update(level='state', geoid=code, boundary_status='matched')
            elif re.fullmatch(r'[0-9]{2}', code):
                item['exclusion_reason'] = 'no_2024_boundary'
            else:
                item['exclusion_reason'] = 'malformed_fips'
                unexplained.append(key)
        elif level == 'county':
            if code in LEGACY_CT_COUNTIES:
                item['exclusion_reason'] = 'legacy_connecticut_county_code'
            elif re.fullmatch(r'[0-9]{5}', code) and code in boundaries['county']:
                item.update(level='county', geoid=code, boundary_status='matched')
            elif re.fullmatch(r'[0-9]{5}', code):
                item['exclusion_reason'] = 'no_2024_boundary'
            else:
                item['exclusion_reason'] = 'malformed_fips'
                unexplained.append(key)
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
            matched.setdefault((item['source_file'], item['level']), []).append(item['geoid'])
    duplicates = sorted({
        f'{fname}:{lvl}:{geoid}'
        for (fname, lvl), ids in matched.items()
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
    """2024 boundary states/counties absent from one or more HDS source files."""
    by_file = {}
    for item in classified.values():
        if item['boundary_status'] == 'matched':
            by_file.setdefault(item['source_file'], set()).add((item['level'], item['geoid']))
    matched = set.intersection(*by_file.values()) if by_file else set()
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
    """Fetch (unless ``skip_fetch``) and parse both CDC HDS CSVs."""
    directory = Path(directory)
    if skip_fetch:
        files, headers = [], {}
        for spec in config['source_files']:
            target = directory / spec['filename']
            if not target.is_file():
                raise ValueError(f'Archived CDC HDS CSV not found: {target}')
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
