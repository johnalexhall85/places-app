"""CDC/ATSDR Social Vulnerability Index (SVI) 2022: retrieval, parsing, and validation.

Only the five US-wide percentile ranks (RPL_THEMES and RPL_THEME1-RPL_THEME4) are published,
for counties and census tracts exactly as CDC/ATSDR releases them. CDC's -999 sentinel is
stored with status ``not_available`` and a NULL value, never zero. Nothing is re-ranked,
averaged, or combined across themes, years, or levels.
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
MAX_ROWS = {'county': 5_000, 'tract': 100_000}
USER_AGENT = 'CHIP-area-ingest/1.0'
NUMBER = re.compile(r'^-?[0-9]+(\.[0-9]+)?$')
MEASURE_IDS = ['rpl_themes', 'rpl_theme1', 'rpl_theme2', 'rpl_theme3', 'rpl_theme4']
LEVELS = ('county', 'tract')
FIPS_WIDTH = {'county': 5, 'tract': 11}
EXPECTED_BREAKS = [0.25, 0.5, 0.75]
LEGACY_CT_COUNTIES = {'09001', '09003', '09005', '09007', '09009', '09011', '09013', '09015'}
ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'cdc_svi_2022'


def load_registry():
    path = Path(__file__).with_name('registry') / 'cdc_svi_2022.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    ids = [m['measure_id'] for m in config['measures']]
    if (ids != MEASURE_IDS or config['geographies'] != ['county', 'tract'] or
            config['aggregation_method'] != 'none' or config['refresh_policy']['auto_publish'] or
            config['value_type'] != 'percentile_rank'):
        raise ValueError('CDC SVI registry contract changed')
    for measure in config['measures']:
        if measure['kind'] != 'percentile_rank' or set(measure['legend_breaks']) != {'county', 'tract'}:
            raise ValueError(f'CDC SVI measure {measure["measure_id"]} is incomplete')
        if any(measure['legend_breaks'][lvl] != EXPECTED_BREAKS for lvl in LEVELS):
            raise ValueError(f'CDC SVI measure {measure["measure_id"]} legend breaks changed')
        if any(key in measure for key in ('ci_low', 'ci_high', 'moe', 'source_ci_field')):
            raise ValueError('CDC SVI publishes no uncertainty fields')
    return config


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
                            raise ValueError(f'CDC SVI response exceeds {limit} bytes: {url}')
                        output.write(chunk)
            if size == 0:
                raise ValueError(f'CDC SVI response was empty: {url}')
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
    raise RuntimeError(f'CDC SVI download failed after {attempts} attempts: {url}') from last


def file_evidence(path, url, role, http_headers=None):
    return epa_aqi.file_evidence(path, url, role, http_headers)


def fetch(config, directory=ROOT):
    """Download the two contract CSVs into ``directory`` and record SHA-256 evidence."""
    from app.area_pilot.operations import disk_guard

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    disk_guard(directory, 2 * MAX_CSV)
    files, headers = [], {}
    for level in LEVELS:
        url = config['source_urls'][level]
        target = directory / config['source_filenames'][level]
        role = f'svi_{level}_csv'
        headers[role] = _bounded_get(url, target, MAX_CSV)
        files.append(file_evidence(target, url, role, headers[role]))
    return files, headers


# ---------------------------------------------------------------- parsing

def header_sha(header):
    return digest(header)


def parse_value(raw, measure=None):
    """Return (Decimal|None, status). -999 -> not_available; 0 -> true_zero; (0,1] -> available."""
    field = measure['source_field'] if isinstance(measure, dict) else str(measure or 'value')
    value = str(raw).strip()
    if not NUMBER.fullmatch(value):
        raise ValueError(f'Undocumented CDC SVI value token in {field}: {value[:20]!r}')
    number = Decimal(value)
    if number == Decimal(-999):
        return None, 'not_available'
    if number < Decimal(0) or number > Decimal(1):
        raise ValueError(f'CDC SVI value outside [0, 1] in {field}: {value[:20]!r}')
    if number == 0:
        return Decimal(0), 'true_zero'
    return number, 'available'


def range_problems(number, measure=None):
    problems = []
    if not Decimal(0) <= number <= Decimal(1):
        problems.append('outside_documented_scale')
    return problems


def observation_values(record, config):
    result = []
    for measure in config['measures']:
        raw = record[measure['source_field']]
        value, status = parse_value(raw, measure)
        result.append({'measure': measure, 'value': value, 'status': status, 'source_value': raw})
    return result


def parse_csv(path, level, config):
    """Stream one SVI CSV with utf-8-sig encoding; validate schema, keys, and measure values."""
    if level not in LEVELS:
        raise ValueError(f'Unsupported CDC SVI level: {level!r}')
    records, total = {}, 0
    with Path(path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.reader(source)
        header = next(reader, None)
        if header is None:
            raise ValueError(f'CDC SVI {level} CSV is empty')
        if config.get('expected_column_count') and len(header) != config['expected_column_count']:
            raise ValueError(f'CDC SVI {level} CSV column count differs from reviewed schema')
        if 'FIPS' not in header:
            raise ValueError(f'CDC SVI {level} CSV is missing FIPS column')
        if config.get('expected_header_sha256') and header_sha(header) != config['expected_header_sha256']:
            raise ValueError(f'CDC SVI {level} CSV header differs from reviewed schema')
        missing = [m['source_field'] for m in config['measures'] if m['source_field'] not in header]
        if missing:
            raise ValueError(f'CDC SVI {level} measure fields missing: {missing}')
        fips_idx = header.index('FIPS')
        measure_indices = [(m, header.index(m['source_field'])) for m in config['measures']]
        for values in reader:
            total += 1
            if len(values) != len(header):
                raise ValueError(f'CDC SVI {level} row {total} has {len(values)} columns')
            fips = values[fips_idx].strip()
            if not fips:
                raise ValueError(f'CDC SVI {level} row {total} has blank FIPS')
            key = (level, fips)
            if key in records:
                raise ValueError(f'Duplicate CDC SVI geography key: {key}')
            for measure, idx in measure_indices:
                parse_value(values[idx], measure)
            records[key] = dict(zip(header, values))
            if len(records) > MAX_ROWS[level]:
                raise ValueError(f'CDC SVI {level} row limit exceeded')
    return records, {'level': level, 'header': header, 'header_sha256': header_sha(header), 'row_count': total}


def semantic_sha(records):
    """Order-independent SHA-256 across all staged rows without holding one giant JSON string."""
    sha = hashlib.sha256()
    sha.update(b'[')
    first = True
    for level, fips in sorted(records):
        if not first:
            sha.update(b',')
        first = False
        chunk = json.dumps([level, fips, records[(level, fips)]], sort_keys=True, separators=(',', ':'))
        sha.update(chunk.encode('utf-8'))
    sha.update(b']')
    return sha.hexdigest()


# ---------------------------------------------------------------- geography

def _source_only_reason(level, fips):
    width = FIPS_WIDTH[level]
    if not re.fullmatch(rf'[0-9]{{{width}}}', fips):
        return 'malformed_fips'
    if fips[:5] in LEGACY_CT_COUNTIES:
        return 'legacy_connecticut_county_code'
    if fips[:2] in {'60', '66', '69', '78'}:
        return 'territory_outside_chip_2024_boundary_layer'
    return 'no_matching_2024_boundary'


def classify(records, county_geoids, tract_geoids, config=None):
    """Exact FIPS joins against CHIP's 2024 TIGER boundaries. Unmatched rows become source_only."""
    classified = {}
    boundaries = {'county': set(county_geoids), 'tract': set(tract_geoids)}
    source_only_counts = {}
    for key in sorted(records):
        source_level, fips = key
        width = FIPS_WIDTH.get(source_level)
        if width and re.fullmatch(rf'[0-9]{{{width}}}', fips) and fips in boundaries[source_level]:
            classified[key] = {
                'source_level': source_level, 'source_fips': fips, 'level': source_level,
                'geoid': fips, 'boundary_status': 'matched', 'exclusion_reason': None,
            }
        else:
            reason = _source_only_reason(source_level, fips) if source_level in FIPS_WIDTH else 'unknown_level'
            classified[key] = {
                'source_level': source_level, 'source_fips': fips, 'level': None,
                'geoid': None, 'boundary_status': 'source_only', 'exclusion_reason': reason,
            }
            source_only_counts[(source_level, reason)] = source_only_counts.get((source_level, reason), 0) + 1
    matched = {}
    for item in classified.values():
        if item['boundary_status'] == 'matched':
            matched.setdefault(item['level'], []).append(item['geoid'])
    duplicates = sorted({f'{lvl}:{g}' for lvl, ids in matched.items() for g in ids if ids.count(g) > 1})
    return classified, {
        'source_only_counts': {f'{k[0]}|{k[1]}': v for k, v in sorted(source_only_counts.items())},
        'duplicate_geoids': duplicates,
    }


def boundary_without_source(classified, county_geoids, tract_geoids, config=None):
    """2024 boundary areas with no SVI row at that level (e.g., Puerto Rico)."""
    matched = {(i['level'], i['geoid']) for i in classified.values() if i['boundary_status'] == 'matched'}
    result, counts = {}, {}
    for level, geoids in (('county', county_geoids), ('tract', tract_geoids)):
        for geoid in sorted(set(geoids)):
            if (level, geoid) in matched:
                continue
            reason = 'puerto_rico_outside_cdc_svi_us_file' if geoid.startswith('72') else 'no_svi_row'
            result[f'{level}:{geoid}'] = reason
            counts[f'{level}|{reason}'] = counts.get(f'{level}|{reason}', 0) + 1
    return result, {'counts': counts}


def retrieve(config, directory=ROOT, skip_fetch=False):
    """Fetch (unless ``skip_fetch``) and parse both SVI CSVs; return records, stats, files, provenance."""
    directory = Path(directory)
    if skip_fetch:
        files, headers = [], {}
        for level in LEVELS:
            target = directory / config['source_filenames'][level]
            if not target.is_file():
                raise ValueError(f'Archived CDC SVI {level} CSV not found: {target}')
            files.append(file_evidence(target, config['source_urls'][level], f'svi_{level}_csv'))
    else:
        files, headers = fetch(config, directory)
    records = {}
    header_shas, row_counts = {}, {}
    for level in LEVELS:
        path = directory / config['source_filenames'][level]
        level_records, level_stats = parse_csv(path, level, config)
        records.update(level_records)
        header_shas[level] = level_stats['header_sha256']
        row_counts[level] = level_stats['row_count']
    stats = {'header_sha256': header_shas, 'row_counts': row_counts}
    provenance = {'skip_fetch': skip_fetch, 'http': headers, 'csv_stats': stats}
    return records, stats, files, provenance
