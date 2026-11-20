"""FEMA National Risk Index (NRI) v1.20: archive verification, streaming ZIP parsing, and validation.

Reads the three browser-archived OpenFEMA ZIPs (`NRI_Table_States.zip`, `NRI_Table_Counties.zip`,
`NRI_Table_CensusTracts.zip`) directly via ``zipfile`` without extracting to disk. Stages only the
identifiers and selected fields into ``stage_fema_nri.record``. Never downloads from fema.gov.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path, PurePosixPath

from app.area_pilot import epa_aqi
from app.area_pilot.source import digest

ROOT = Path(__file__).resolve().parents[3] / 'data' / 'ingest' / 'fema_nri_v120'
LEVELS = ('state', 'county', 'tract')
FIPS_WIDTH = {'state': 2, 'county': 5, 'tract': 11}
MAX_ROWS = {'state': 100, 'county': 5_000, 'tract': 100_000}
NUMBER = re.compile(r'^-?[0-9]+(\.[0-9]+)?$')
MEASURE_IDS = [
    'risk_score', 'risk_spctl', 'eal_score', 'eal_spctl', 'eal_valt',
    'sovi_score', 'sovi_spctl', 'resl_score', 'resl_spctl', 'crf_value',
]
RANGES = {
    'score': (Decimal('0'), Decimal('100')),
    'percentile': (Decimal('0'), Decimal('100')),
    'currency': (Decimal('0'), Decimal('1000000000000')),
    'factor': (Decimal('0'), Decimal('10')),
}
DIRECTIONS = {'higher_worse', 'higher_better'}
QUANT = Decimal('0.0001')
LEGACY_CT_COUNTIES = {'09001', '09003', '09005', '09007', '09009', '09011', '09013', '09015'}
TERRITORY_PREFIXES = {'60', '66', '69', '78'}


def load_registry():
    path = Path(__file__).with_name('registry') / 'fema_nri_v120.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    ids = [m['measure_id'] for m in config['measures']]
    if (ids != MEASURE_IDS or config['geographies'] != ['state', 'county', 'tract'] or
            config['aggregation_method'] != 'none' or config['refresh_policy']['auto_publish'] or
            config['value_type'] != 'fema_nri_published'):
        raise ValueError('FEMA NRI registry contract changed')
    for measure in config['measures']:
        levels = measure.get('geographies') or []
        if (measure['kind'] not in RANGES or measure.get('direction') not in DIRECTIONS or
                not levels or set(measure['legend_breaks']) != set(levels)):
            raise ValueError(f'FEMA NRI measure {measure["measure_id"]} is incomplete')
        if any(key in measure for key in ('ci_low', 'ci_high', 'moe', 'source_ci_field')):
            raise ValueError('FEMA NRI publishes no uncertainty fields')
    return config


def measures_for_level(config, level):
    return [m for m in config['measures'] if level in m['geographies']]


def selected_fields_for_level(config, level):
    """Identifiers plus selected measure and rating fields staged into ``record``."""
    archive = config['source_archives'][level]
    fields = list(archive['identifier_fields'])
    for measure in measures_for_level(config, level):
        for col in (measure['source_field'], measure.get('rating_field'), measure.get('paired_score_field')):
            if col and col not in fields:
                fields.append(col)
    return fields


def required_roles():
    return {f'nri_{level}_zip' for level in LEVELS}


def file_evidence(path, url, role, http_headers=None):
    return epa_aqi.file_evidence(path, url, role, http_headers)


# ---------------------------------------------------------------- archive verification (never downloads)

def fetch(config, directory=ROOT):
    """Verify the three archived FEMA NRI ZIPs on disk and record their SHA-256 hashes. Never downloads."""
    directory = Path(directory)
    files = []
    missing = []
    for level in LEVELS:
        archive = config['source_archives'][level]
        target = directory / archive['zip']
        if not target.is_file():
            missing.append(str(target))
            continue
        evidence = file_evidence(target, config['source_urls'][level], f'nri_{level}_zip')
        expected_sha = archive.get('sha256')
        if expected_sha and evidence['sha256'] != expected_sha:
            raise ValueError(
                f'FEMA NRI {level} archive SHA-256 mismatch for {target.name}: '
                f'got {evidence["sha256"]}, expected {expected_sha}')
        files.append(evidence)
    if missing:
        raise ValueError(
            'Missing archived FEMA NRI ZIP file(s): ' + ', '.join(missing) +
            '. fema.gov refuses scripted downloads; download the v1.20 ZIPs in a browser into '
            f'{directory} and re-run.')
    return files


# ---------------------------------------------------------------- parsing

def header_sha(header):
    return digest(header)


def _safe_zip_member(archive, expected_name):
    names = {info.filename: info for info in archive.infolist()}
    if expected_name not in names:
        raise ValueError(f'FEMA NRI ZIP is missing expected CSV member {expected_name!r}')
    info = names[expected_name]
    path = PurePosixPath(info.filename)
    if (path.is_absolute() or '..' in path.parts or '\\' in info.filename or len(path.parts) != 1 or
            info.flag_bits & 1 or ((info.external_attr >> 16) & 0o170000) == 0o120000):
        raise ValueError(f'Unsafe FEMA NRI ZIP member: {info.filename!r}')
    return info


def parse_value(raw, measure, paired_score_raw=None):
    """Return (Decimal|None, status) per CONTRACT §2.

    - Blank cell -> (None, 'not_available').
    - *_SPCTL whose paired *_SCORE is blank -> (None, 'not_available') (source_value keeps FEMA's cell, e.g. 0).
    - Negative number or undocumented token -> ValueError.
    - Exactly 0 otherwise -> (Decimal('0.0000'), 'true_zero').
    - Positive number -> (quantized Numeric(20,4) Decimal, 'available').
    """
    field = measure['source_field'] if isinstance(measure, dict) else str(measure or 'value')
    value = str(raw).strip()
    if paired_score_raw is not None and str(paired_score_raw).strip() == '':
        if value != '' and not NUMBER.fullmatch(value):
            raise ValueError(f'Undocumented FEMA NRI value token in {field}: {value[:24]!r}')
        return None, 'not_available'
    if value == '':
        return None, 'not_available'
    if not NUMBER.fullmatch(value):
        raise ValueError(f'Undocumented FEMA NRI value token in {field}: {value[:24]!r}')
    number = Decimal(value)
    if number < Decimal(0):
        raise ValueError(f'Negative FEMA NRI value in {field}: {value[:24]!r}')
    if number == 0:
        return Decimal('0.0000'), 'true_zero'
    quantized = number.quantize(QUANT, rounding=ROUND_HALF_UP)
    if quantized == 0:
        raise ValueError(f'Positive FEMA NRI value rounds to zero at Numeric(20,4) in {field}: {value[:24]!r}')
    return quantized, 'available'


def range_problems(number, measure):
    low, high = RANGES[measure['kind']]
    problems = []
    if not low <= number <= high:
        problems.append('outside_documented_scale')
    return problems


def observation_values(record, level, config):
    result = []
    for measure in measures_for_level(config, level):
        raw = record[measure['source_field']]
        paired_field = measure.get('paired_score_field')
        paired_raw = record[paired_field] if paired_field else None
        value, status = parse_value(raw, measure, paired_score_raw=paired_raw)
        rating_field = measure.get('rating_field')
        rating = (record[rating_field].strip() or None) if rating_field else None
        result.append({
            'measure': measure, 'value': value, 'status': status,
            'source_value': raw, 'rating': rating,
        })
    return result


def parse_zip(zip_path, level, config):
    """Stream one FEMA NRI CSV directly from its ZIP without extracting to disk."""
    if level not in LEVELS:
        raise ValueError(f'Unsupported FEMA NRI level: {level!r}')
    archive_spec = config['source_archives'][level]
    csv_name = archive_spec['csv']
    fips_field = archive_spec['fips_field']
    selected_fields = selected_fields_for_level(config, level)
    expected_nri_ver = config.get('expected_nri_ver')
    records, total = {}, 0
    with zipfile.ZipFile(zip_path) as zf:
        info = _safe_zip_member(zf, csv_name)
        with zf.open(info, 'r') as binary:
            reader = csv.reader(io.TextIOWrapper(binary, encoding='utf-8-sig', newline=''))
            header = next(reader, None)
            if header is None:
                raise ValueError(f'FEMA NRI {level} CSV is empty: {zip_path}')
            if archive_spec.get('expected_column_count') and len(header) != archive_spec['expected_column_count']:
                raise ValueError(f'FEMA NRI {level} CSV column count differs from reviewed schema')
            if archive_spec.get('expected_header_sha256') and header_sha(header) != archive_spec['expected_header_sha256']:
                raise ValueError(f'FEMA NRI {level} CSV header differs from reviewed schema')
            missing = [col for col in selected_fields if col not in header]
            if missing:
                raise ValueError(f'FEMA NRI {level} CSV missing required fields: {missing}')
            indices = {col: header.index(col) for col in selected_fields}
            fips_idx = indices[fips_field]
            ver_idx = indices.get('NRI_VER')
            level_measures = measures_for_level(config, level)
            for values in reader:
                total += 1
                if len(values) != len(header):
                    raise ValueError(f'FEMA NRI {level} row {total} has {len(values)} columns')
                fips = values[fips_idx].strip()
                if not fips:
                    raise ValueError(f'FEMA NRI {level} row {total} has blank {fips_field}')
                if expected_nri_ver and ver_idx is not None:
                    row_ver = values[ver_idx].strip()
                    if row_ver != expected_nri_ver:
                        raise ValueError(
                            f'FEMA NRI {level} row {total} has NRI_VER={row_ver!r}; expected {expected_nri_ver!r}')
                key = (level, fips)
                if key in records:
                    raise ValueError(f'Duplicate FEMA NRI geography key: {key}')
                staged_record = {col: values[idx] for col, idx in indices.items()}
                # Validate every measure cell during parsing so bad tokens or negatives fail immediately.
                for measure in level_measures:
                    paired = measure.get('paired_score_field')
                    parse_value(staged_record[measure['source_field']], measure,
                                paired_score_raw=staged_record[paired] if paired else None)
                records[key] = staged_record
                if len(records) > MAX_ROWS[level]:
                    raise ValueError(f'FEMA NRI {level} row limit exceeded')
    return records, {
        'level': level, 'zip': Path(zip_path).name, 'csv': csv_name,
        'column_count': len(header), 'header_sha256': header_sha(header), 'row_count': total,
    }


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
    if level == 'county' and fips[:5] in LEGACY_CT_COUNTIES:
        return 'legacy_connecticut_county_code'
    if fips[:2] in TERRITORY_PREFIXES:
        return 'territory_outside_chip_2024_boundary_layer'
    return 'no_matching_2024_boundary'


def classify(records, state_geoids, county_geoids, tract_geoids, config=None):
    """Exact FIPS joins against CHIP's 2024 TIGER boundaries. Unmatched rows become source_only."""
    classified = {}
    boundaries = {'state': set(state_geoids), 'county': set(county_geoids), 'tract': set(tract_geoids)}
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


def boundary_without_source(classified, state_geoids, county_geoids, tract_geoids, config=None):
    """2024 boundary areas with no FEMA NRI row at that level."""
    matched = {(i['level'], i['geoid']) for i in classified.values() if i['boundary_status'] == 'matched'}
    result, counts = {}, {}
    for level, geoids in (('state', state_geoids), ('county', county_geoids), ('tract', tract_geoids)):
        for geoid in sorted(set(geoids)):
            if (level, geoid) in matched:
                continue
            reason = 'no_fema_nri_row'
            result[f'{level}:{geoid}'] = reason
            counts[f'{level}|{reason}'] = counts.get(f'{level}|{reason}', 0) + 1
    return result, {'counts': counts}


def retrieve(config, directory=ROOT):
    """Verify the three archived ZIPs and stream-parse them without unzipping to disk."""
    directory = Path(directory)
    files = fetch(config, directory)
    records = {}
    header_shas, row_counts = {}, {}
    for level in LEVELS:
        zip_path = directory / config['source_archives'][level]['zip']
        level_records, level_stats = parse_zip(zip_path, level, config)
        records.update(level_records)
        header_shas[level] = level_stats['header_sha256']
        row_counts[level] = level_stats['row_count']
    stats = {'header_sha256': header_shas, 'row_counts': row_counts}
    provenance = {'archive_only': True, 'csv_stats': stats}
    return records, stats, files, provenance
