"""CMS Original Medicare Geographic Variation (OM GV) public use file: retrieval and validation.

Scope is deliberately bounded: the latest observation year in the file, the published
"All" age level (dictionary label "All Beneficiaries"), five published measures, and the
national, state, and county rows exactly as CMS publishes them. Nothing is aggregated, rescaled,
or reverse-engineered from suppressed cells. National values are kept for reference only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import requests

from app.area_pilot.source import digest

MAX_CATALOG = 64 * 1024**2
MAX_CSV = 200 * 1024**2
MAX_PDF = 10 * 1024**2
MAX_JSON = 2 * 1024**2
MAX_SELECTED_ROWS = 10_000
USER_AGENT = 'CHIP-area-ingest/1.0'
NUMBER = re.compile(r'^-?[0-9]+(\.[0-9]+)?$')
MEASURE_IDS = ['om_beneficiaries', 'std_payment_per_capita', 'ip_stays_per_1000', 'er_visits_per_1000',
               'readmission_rate']
LEVELS = {'National': 'national', 'State': 'state', 'County': 'county'}
RANGES = {'count': (Decimal(0), Decimal(10**9)), 'currency': (Decimal(0), Decimal(10**6)),
          'per_1000': (Decimal(0), Decimal(10_000)), 'proportion': (Decimal(0), Decimal(1))}


def load_registry():
    path = Path(__file__).with_name('registry') / 'cms_om_gv.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    ids = [m['measure_id'] for m in config['measures']]
    if (ids != MEASURE_IDS or config['geographies'] != ['state', 'county'] or
            config['aggregation_method'] != 'none' or config['refresh_policy']['auto_publish'] or
            config['age_level'] != 'All'):
        raise ValueError('CMS OM GV registry contract changed')
    for measure in config['measures']:
        if measure['kind'] not in RANGES or set(measure['legend_breaks']) != {'state', 'county'}:
            raise ValueError(f'CMS OM GV measure {measure["measure_id"]} is incomplete')
        if any(key in measure for key in ('ci_low', 'ci_high', 'moe', 'source_ci_field')):
            raise ValueError('CMS OM GV publishes no uncertainty fields')
    return config


# ---------------------------------------------------------------- retrieval

def _bounded_get(url, target, limit, params=None, attempts=3):
    """Stream to a temporary file with timeouts, a byte cap, and bounded retries."""
    temporary = target.with_name(target.name + '.part')
    last = None
    for attempt in range(attempts):
        try:
            size = 0
            with requests.get(url, params=params, stream=True, timeout=(10, 120), allow_redirects=True,
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
                            raise ValueError(f'CMS response exceeds {limit} bytes: {url}')
                        output.write(chunk)
            if size == 0:
                raise ValueError(f'CMS response was empty: {url}')
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
    raise RuntimeError(f'CMS download failed after {attempts} attempts: {url}') from last


def file_evidence(path, url, role, http_headers=None):
    sha = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            sha.update(block)
    return {'role': role, 'path': str(Path(path).resolve()), 'url': url, 'sha256': sha.hexdigest(),
            'byte_count': Path(path).stat().st_size, 'retrieved_at': datetime.now(timezone.utc),
            'http': http_headers or {}}


def comparable(text_value):
    """Whitespace-free, quote-normalized, case-folded text; PDF extraction splits words unpredictably."""
    value = text_value.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    return re.sub(r'\s+', '', value).casefold()


def verify_phrases(text_value, phrases, role):
    haystack = comparable(text_value)
    missing = [phrase for phrase in phrases if comparable(phrase) not in haystack]
    if missing:
        raise ValueError(f'CMS OM GV {role} definitions changed: {missing[:2]}')
    return len(phrases)


def pdf_text(path):
    from pypdf import PdfReader  # deferred: only needed during ingestion

    return '\n'.join(page.extract_text() or '' for page in PdfReader(str(path)).pages)


def catalog_entry(catalog, config):
    """Return the one latest catalog record for the configured CMS dataset series."""
    spec = config['catalog']
    matches = [item for item in catalog.get('dataset', [])
               if any(series.get('@id') == spec['series_identifier'] for series in item.get('inSeries', []))
               and str(item.get('title', '')).startswith(spec['title_prefix'])]
    if len(matches) != 1:
        raise ValueError(f'CMS catalog has {len(matches)} records for the OM GV series; expected 1')
    item = matches[0]
    csvs = [d.get('downloadURL') for d in item.get('distribution', []) if d.get('mediaType') == 'text/csv']
    temporal = item.get('temporal') or [{}]
    return {'title': item['title'], 'modified': item.get('modified'), 'description': item.get('description', ''),
            'temporal_start': temporal[0].get('startDate'), 'temporal_end': temporal[0].get('endDate'),
            'dictionary_url': (item.get('describedBy') or {}).get('downloadURL'),
            'methods_urls': item.get('references') or [], 'csv_urls': csvs,
            'access_level': item.get('accessLevel'), 'accrual': item.get('accrualPeriodicity')}


def check_catalog(entry, config):
    spec = config['catalog']
    year = int(str(entry['temporal_end'] or '0000')[:4])
    if year != config['observation_year']:
        raise ValueError(f'CMS catalog now ends in {year}; registry is pinned to {config["observation_year"]}. '
                         'Review definitions and update the registry.')
    if entry['csv_urls'] != [spec['csv_url']]:
        raise ValueError('CMS OM GV CSV distribution URL changed; review the registry')
    if entry['dictionary_url'] != spec['dictionary_url'] or spec['methods_url'] not in entry['methods_urls']:
        raise ValueError('CMS OM GV dictionary or methods URL changed; review the registry')
    if entry['access_level'] != 'public':
        raise ValueError('CMS OM GV catalog access level is not public')


# ---------------------------------------------------------------- parsing

def header_sha(header):
    return digest(header)


def parse_csv(path, config):
    """One streaming pass. Keep only latest-year All-age rows; count everything else."""
    year = str(config['observation_year'])
    years, ages, total = {}, {}, 0
    records = {}
    with Path(path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.reader(source)
        header = next(reader, None)
        if header is None or len(header) != config['expected_column_count']:
            raise ValueError('CMS OM GV CSV column count differs from reviewed schema')
        if header[:5] != config['source_dimensions']:
            raise ValueError('CMS OM GV CSV dimension columns changed')
        if config['expected_header_sha256'] and header_sha(header) != config['expected_header_sha256']:
            raise ValueError('CMS OM GV CSV header differs from reviewed schema')
        missing = [m['source_field'] for m in config['measures'] if m['source_field'] not in header]
        if missing:
            raise ValueError(f'CMS OM GV measure fields missing: {missing}')
        for values in reader:
            total += 1
            if len(values) != len(header):
                raise ValueError(f'CMS OM GV row {total} has {len(values)} columns')
            row_year = values[0]
            if not re.fullmatch(r'[0-9]{4}', row_year):
                raise ValueError(f'CMS OM GV row {total} has a malformed YEAR')
            years[row_year] = years.get(row_year, 0) + 1
            if row_year != year:
                continue
            level, desc, code, age = values[1], values[2], values[3], values[4]
            ages[(level, age)] = ages.get((level, age), 0) + 1
            if age != config['age_level']:
                continue
            key = (level, code, desc)
            if key in records:
                raise ValueError(f'Duplicate CMS OM GV geography key: {key}')
            records[key] = dict(zip(header, values))
            if len(records) > MAX_SELECTED_ROWS:
                raise ValueError('CMS OM GV selected-row limit exceeded')
    latest = max(years) if years else None
    return records, {'header': header, 'header_sha256': header_sha(header), 'total_rows': total,
                     'year_counts': dict(sorted(years.items())), 'latest_year': latest,
                     'selected_year_age_counts': {f'{k[0]}|{k[1]}': v for k, v in sorted(ages.items())}}


def parse_value(raw, measure, token='*'):
    """Return (Decimal|None, status). '*' is CMS suppression; blank is kept as missing."""
    value = raw.strip()
    if value == token:
        return None, 'suppressed'
    if value == '':
        return None, 'missing'
    if not NUMBER.fullmatch(value):
        raise ValueError(f'Undocumented CMS value token in {measure["source_field"]}: {value[:20]!r}')
    number = Decimal(value)
    return number, 'true_zero' if number == 0 else 'available'


def range_problems(number, measure):
    low, high = RANGES[measure['kind']]
    problems = []
    if not low <= number <= high:
        problems.append('outside_documented_scale')
    if measure['kind'] == 'count':
        if number != number.to_integral_value():
            problems.append('non_integer_count')
        if 0 < number < measure.get('min_published', 0):
            problems.append('below_suppression_threshold')
    return problems


def observation_values(record, config):
    result = []
    for measure in config['measures']:
        raw = record[measure['source_field']]
        value, status = parse_value(raw, measure, config['suppression_token'])
        result.append({'measure': measure, 'value': value, 'status': status, 'source_value': raw})
    return result


def semantic_sha(records):
    return digest([[level, code, desc, records[(level, code, desc)]] for level, code, desc in sorted(records)])


def scale_evidence(records, config):
    national = [row for (level, _, _), row in records.items() if level == 'National']
    if len(national) != 1:
        return {'passed': False, 'reason': 'national All row missing or repeated'}
    rows = []
    for item in config['scale_evidence']:
        rows.append({**item, 'csv_value': national[0][item['field']],
                     'matches': national[0][item['field']] == item['national_all_value']})
    readmission = national[0]['ACUTE_HOSP_READMSN_PCT']
    proportion = NUMBER.fullmatch(readmission) is not None and Decimal(0) < Decimal(readmission) < Decimal(1)
    return {'passed': all(r['matches'] for r in rows) and proportion, 'evidence': rows,
            'national_readmission_value': readmission, 'readmission_is_0_1_proportion': proportion}


# ---------------------------------------------------------------- geography

def _exclusion_for(level, code, desc, config):
    for rule in config['expected_source_exclusions']:
        if rule['level'] != level:
            continue
        if 'code' in rule and rule['code'] == code and rule['desc'] == desc:
            return rule['reason']
        if 'code_pattern' in rule and re.search(rule['code_pattern'], code) and re.search(rule['desc_pattern'], desc):
            return rule['reason']
    return None


def classify(records, state_geoids, county_geoids, config):
    """Exact code joins. Every unmatched source row must be a documented exclusion."""
    classified, unexplained = {}, []
    boundaries = {'state': set(state_geoids), 'county': set(county_geoids)}
    for key in sorted(records):
        source_level, code, desc = key
        level = LEVELS.get(source_level)
        item = {'source_level': source_level, 'level': level, 'source_code': code, 'source_desc': desc,
                'geoid': None, 'boundary_status': 'source_only', 'exclusion_reason': None}
        if level == 'national':
            if code != '':
                item['exclusion_reason'] = 'unexplained'
                unexplained.append(key)
            else:
                item.update(geoid='US', boundary_status='national_reference')
        elif level is None:
            item['exclusion_reason'] = 'unexplained'
            unexplained.append(key)
        else:
            width = 2 if level == 'state' else 5
            reason = _exclusion_for(source_level, code, desc, config)
            if reason:
                item['exclusion_reason'] = reason
            elif re.fullmatch(f'[0-9]{{{width}}}', code) and code in boundaries[level]:
                item.update(geoid=code, boundary_status='matched')
            else:
                item['exclusion_reason'] = 'unexplained'
                unexplained.append(key)
        classified[key] = item
    counts = {}
    for item in classified.values():
        if item['boundary_status'] == 'source_only':
            counts[(item['source_level'], item['exclusion_reason'])] = counts.get(
                (item['source_level'], item['exclusion_reason']), 0) + 1
    mismatched = []
    for rule in config['expected_source_exclusions']:
        expected = rule.get('expected_count', 1)
        if 'code' in rule:
            present = any(k == (rule['level'], rule['code'], rule['desc']) for k in records)
            if not present:
                mismatched.append(f"{rule['level']}|{rule['code']}|{rule['desc']} absent")
        elif counts.get((rule['level'], rule['reason']), 0) < expected:
            mismatched.append(f"{rule['level']}|{rule['reason']} fewer than {expected}")
    for (level, reason), observed in counts.items():
        if reason == 'unexplained':
            continue
        allowed = sum(rule.get('expected_count', 1) for rule in config['expected_source_exclusions']
                      if rule['level'] == level and rule['reason'] == reason)
        if observed != allowed:
            mismatched.append(f'{level}|{reason}: {observed} observed, {allowed} expected')
    matched = {}
    for item in classified.values():
        if item['boundary_status'] == 'matched':
            matched.setdefault(item['level'], []).append(item['geoid'])
    duplicates = sorted({f'{lvl}:{g}' for lvl, ids in matched.items() for g in ids if ids.count(g) > 1})
    return classified, {'unexplained': unexplained, 'exclusion_count_mismatch': mismatched,
                        'duplicate_geoids': duplicates}


def boundary_without_source(classified, state_geoids, county_geoids, config):
    """Boundary areas with no CMS row at that level; each must match a documented reason."""
    matched = {(i['level'], i['geoid']) for i in classified.values() if i['boundary_status'] == 'matched'}
    result, unexplained, counts = {}, [], {}
    for level, geoids in (('state', state_geoids), ('county', county_geoids)):
        for geoid in sorted(set(geoids)):
            if (level, geoid) in matched:
                continue
            rule = next((r for r in config['expected_boundary_without_source']
                         if r['level'] == level and re.fullmatch(r['code_pattern'], geoid)), None)
            reason = rule['reason'] if rule else 'unexplained'
            result[f'{level}:{geoid}'] = reason
            counts[reason] = counts.get(reason, 0) + 1
            if rule is None:
                unexplained.append(f'{level}:{geoid}')
    mismatched = [f"{r['reason']}: {counts.get(r['reason'], 0)} observed, {r['expected_count']} expected"
                  for r in config['expected_boundary_without_source']
                  if counts.get(r['reason'], 0) != r['expected_count']]
    return result, {'unexplained': unexplained, 'count_mismatch': mismatched, 'counts': counts}


# ---------------------------------------------------------------- independent API cross-check

def api_cross_check(config, records, directory):
    """Compare the CSV with CMS's own data API for row totals and a fixed set of cells."""
    spec = config['catalog']
    files, results = [], {}
    total_path = directory / 'api_stats_total.json'
    files.append(file_evidence(total_path, spec['api_stats_url'], 'api_stats_total',
                               _bounded_get(spec['api_stats_url'], total_path, MAX_JSON)))
    selected_params = {'filter[YEAR]': str(config['observation_year']), 'filter[BENE_AGE_LVL]': config['age_level']}
    selected_path = directory / 'api_stats_selected.json'
    files.append(file_evidence(selected_path, spec['api_stats_url'], 'api_stats_selected',
                               _bounded_get(spec['api_stats_url'], selected_path, MAX_JSON, selected_params)))
    results['api_total_rows'] = json.loads(total_path.read_text())['total_rows']
    results['api_selected_rows'] = json.loads(selected_path.read_text())['found_rows']
    columns = ','.join(config['source_dimensions'] + [m['source_field'] for m in config['measures']])
    cells = []
    for code in config.get('api_sample_codes', []):
        params = dict(selected_params) | {'column': columns}
        params |= {'filter[BENE_GEO_LVL]': 'National'} if code == 'US' else {'filter[BENE_GEO_CD]': code}
        path = directory / f'api_sample_{code}.json'
        files.append(file_evidence(path, spec['api_data_url'], f'api_sample_{code}',
                                   _bounded_get(spec['api_data_url'], path, MAX_JSON, params)))
        rows = json.loads(path.read_text())
        for api_row in rows:
            key = (api_row['BENE_GEO_LVL'], api_row['BENE_GEO_CD'], api_row['BENE_GEO_DESC'])
            csv_row = records.get(key)
            cells.append({'key': list(key), 'matches': csv_row is not None and all(
                csv_row[m['source_field']] == api_row[m['source_field']] for m in config['measures'])})
        if not rows:
            cells.append({'key': [code], 'matches': False})
    results['cells'] = cells
    results['passed'] = (results['api_selected_rows'] == len(records) and bool(cells) and
                         all(c['matches'] for c in cells))
    return results, files


def retrieve(config, directory):
    """Archive catalog, CSV, dictionary, methods paper, and API evidence; return parsed selection."""
    from app.area_pilot.operations import disk_guard

    directory.mkdir(parents=True, exist_ok=True)
    disk_guard(directory, MAX_CATALOG + MAX_CSV + 2 * MAX_PDF + 10 * MAX_JSON)
    spec = config['catalog']
    files, headers = [], {}
    catalog_path = directory / 'data.json'
    headers['catalog'] = _bounded_get(spec['url'], catalog_path, MAX_CATALOG)
    files.append(file_evidence(catalog_path, spec['url'], 'catalog', headers['catalog']))
    entry = catalog_entry(json.loads(catalog_path.read_text(encoding='utf-8')), config)
    check_catalog(entry, config)
    verify_phrases(entry['description'], config['documentation_phrases']['catalog'], 'catalog')
    for role, url, name, limit in (('resources', spec['resources_url'], 'dataset_resources.json', MAX_JSON),
                                   ('dictionary_pdf', spec['dictionary_url'], 'data_dictionary.pdf', MAX_PDF),
                                   ('methods_pdf', spec['methods_url'], 'methods_paper.pdf', MAX_PDF),
                                   ('gv_csv', spec['csv_url'], 'om_gv_puf.csv', MAX_CSV)):
        path = directory / name
        headers[role] = _bounded_get(url, path, limit)
        files.append(file_evidence(path, url, role, headers[role]))
    resources = json.loads((directory / 'dataset_resources.json').read_text())['data']
    listed = {item['downloadURL']: item.get('fileSize') for item in resources}
    csv_size = (directory / 'om_gv_puf.csv').stat().st_size
    if listed.get(spec['csv_url']) != csv_size:
        raise ValueError('CMS OM GV CSV size differs from the dataset-resources listing')
    verify_phrases(pdf_text(directory / 'data_dictionary.pdf'), config['documentation_phrases']['dictionary'],
                   'dictionary')
    verify_phrases(pdf_text(directory / 'methods_paper.pdf'), config['documentation_phrases']['methods'], 'methods')
    records, stats = parse_csv(directory / 'om_gv_puf.csv', config)
    if stats['latest_year'] != str(config['observation_year']):
        raise ValueError(f'Latest CMS OM GV year is {stats["latest_year"]}; registry is pinned to '
                         f'{config["observation_year"]}. Review definitions and update the registry.')
    api, api_files = api_cross_check(config, records, directory)
    files += api_files
    provenance = {'catalog_entry': {k: v for k, v in entry.items() if k != 'description'},
                  'catalog_description': entry['description'], 'http': headers,
                  'csv_stats': {k: v for k, v in stats.items() if k != 'header'}, 'api_cross_check': api,
                  'definitions_verified': {k: len(v) for k, v in config['documentation_phrases'].items()}}
    return records, stats, files, provenance
