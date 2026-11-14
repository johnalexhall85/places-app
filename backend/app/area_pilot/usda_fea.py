"""USDA ERS Food Environment Atlas: retrieval, safe extraction, parsing, and validation.

Only five reviewed county variables are published. Values are kept exactly as USDA wrote them;
-9999/N/A (not available) and -8888 (county did not exist in the referenced year) stay distinct
from each other and from a numeric zero. FIPS codes are always text. Nothing is aggregated,
recalculated, or reassigned across boundary vintages.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

import requests

from app.area_pilot.source import digest

MAX_PAGE = 4 * 1024**2
MAX_ARCHIVE = 32 * 1024**2
MAX_MEMBER = 96 * 1024**2
MAX_EXPANDED = 128 * 1024**2
MAX_ROWS = 1_500_000
USER_AGENT = 'CHIP-area-ingest/1.0'
MEASURE_IDS = ['low_income_low_access_pct', 'snap_stores_per_1000', 'wic_stores_per_1000',
               'farmers_markets_per_1000', 'no_car_low_access_households_pct']
NUMBER = re.compile(r'^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$')
FIPS = re.compile(r'^[0-9]{5}$')


def load_registry():
    path = Path(__file__).with_name('registry') / 'usda_fea_2025.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    if ([m['measure_id'] for m in config['measures']] != MEASURE_IDS or config['geographies'] != ['county'] or
            config['aggregation_method'] != 'none' or config['refresh_policy']['auto_publish']):
        raise ValueError('USDA Food Environment Atlas registry contract changed')
    codes = [m['variable_code'] for m in config['measures']]
    if len(set(codes)) != len(codes):
        raise ValueError('USDA FEA registry repeats a variable')
    for measure in config['measures']:
        if not measure['variable_name'].endswith(', ' + measure['observation_period']):
            raise ValueError(f'USDA FEA period does not match variable name: {measure["variable_code"]}')
    return config


# ---------------------------------------------------------------- retrieval

def _bounded_get(url, target, limit, attempts=3):
    """Download to a temporary file with timeouts, a byte cap, and bounded retries."""
    temporary = target.with_name(target.name + '.part')
    last = None
    for attempt in range(attempts):
        try:
            size = 0
            with requests.get(url, stream=True, timeout=(10, 90), allow_redirects=True,
                              headers={'User-Agent': USER_AGENT}) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError(f'Unexpected HTTP {response.status_code} for {url}')
                headers = {k.lower(): v for k, v in response.headers.items()
                           if k.lower() in ('last-modified', 'etag', 'content-length', 'content-type')}
                with temporary.open('wb') as output:
                    for chunk in response.iter_content(256 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(f'USDA response exceeds {limit} bytes: {url}')
                        output.write(chunk)
            if size == 0:
                raise ValueError(f'USDA response was empty: {url}')
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
    raise RuntimeError(f'USDA download failed after {attempts} attempts: {url}') from last


def sha256_file(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def file_evidence(path, url, role, http_headers=None):
    return {'role': role, 'path': str(Path(path).resolve()), 'url': url, 'sha256': sha256_file(path),
            'byte_count': Path(path).stat().st_size, 'retrieved_at': datetime.now(timezone.utc),
            'http': http_headers or {}}


def page_text(raw_html):
    cleaned = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', raw_html)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', cleaned))).strip()


def _normalize_quotes(text_value):
    return text_value.replace('“', '"').replace('”', '"')


def verify_phrases(text_value, phrases, label):
    normalized = _normalize_quotes(re.sub(r'\s+', ' ', text_value))
    missing = [p for p in phrases if _normalize_quotes(p) not in normalized]
    if missing:
        raise ValueError(f'USDA FEA {label} wording changed: {missing[:2]}')
    return len(phrases)


def page_updated(text_value):
    match = re.search(r'Updated: ([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})', text_value)
    return match.group(1) if match else None


def current_csv_link(raw_html):
    """Return (href, last-updated) for the "Current Version" CSV ZIP on the downloads page."""
    current = raw_html.find('Current Version')
    archived = raw_html.find('Archived Versions', current)
    if current < 0 or archived < 0:
        raise ValueError('USDA FEA downloads page no longer has a Current Version section')
    section = raw_html[current:archived]
    links = re.findall(r'href="(/media/[0-9]+/[^"]*csv-files\.zip(?:\?v=[0-9]+)?)"', section)
    if len(links) != 1:
        raise ValueError(f'USDA FEA current CSV ZIP link is not unique: {links}')
    after = page_text(section[section.find(links[0]):])
    updated = re.search(r'Last Updated ([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})', after)
    return html.unescape(links[0]), updated.group(1) if updated else None


def safe_members(archive, expected):
    infos = archive.infolist()
    total = 0
    for info in infos:
        name = PurePosixPath(info.filename)
        if (name.is_absolute() or '..' in name.parts or '\\' in info.filename or len(name.parts) != 1 or
                info.flag_bits & 1 or info.file_size > MAX_MEMBER or
                ((info.external_attr >> 16) & 0o170000) == 0o120000):
            raise ValueError(f'Unsafe USDA FEA ZIP member: {info.filename[:80]!r}')
        if info.compress_size and info.file_size / info.compress_size > 200:
            raise ValueError('USDA FEA ZIP member compression ratio is implausible')
        total += info.file_size
        if total > MAX_EXPANDED:
            raise ValueError('USDA FEA ZIP expands beyond limit')
    if sorted(info.filename for info in infos) != sorted(expected):
        raise ValueError(f'USDA FEA ZIP members changed: {[i.filename for i in infos]}')
    return infos


def extract_members(zip_path, expected, directory):
    from app.area_pilot.operations import disk_guard

    result = {}
    with zipfile.ZipFile(zip_path) as archive:
        infos = safe_members(archive, expected)
        disk_guard(directory, sum(info.file_size for info in infos))
        for info in infos:
            target = directory / info.filename
            temporary = target.with_name(target.name + '.part')
            copied = 0
            try:
                with archive.open(info) as source, temporary.open('wb') as output:
                    for block in iter(lambda: source.read(256 * 1024), b''):
                        copied += len(block)
                        if copied > MAX_MEMBER:
                            raise ValueError('USDA FEA member exceeds extraction limit')
                        output.write(block)
                if copied != info.file_size:
                    raise ValueError('Incomplete USDA FEA extraction')
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            os.replace(temporary, target)
            result[info.filename] = {'path': target, 'zip_timestamp': '%04d-%02d-%02dT%02d:%02d:%02d' % info.date_time,
                                     'bytes': info.file_size}
    return result


# ---------------------------------------------------------------- parsing

def parse_variable_list(path, config):
    with Path(path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != config['expected_variable_header']:
            raise ValueError('USDA FEA VariableList.csv header changed')
        rows = {}
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError('USDA FEA VariableList.csv row has an unexpected column count')
            code = row['Variable_Code'].strip()
            if code in rows:
                raise ValueError(f'USDA FEA variable list repeats {code}')
            rows[code] = dict(row)
    return rows


def verify_variables(variables, config):
    """Registry measures must match the published variable lookup exactly and be county-level."""
    result = {}
    for measure in config['measures']:
        row = variables.get(measure['variable_code'])
        if row is None:
            raise ValueError(f'USDA FEA variable lookup lacks {measure["variable_code"]}')
        expected = {'Variable_Name': measure['variable_name'], 'Category_Name': measure['category'],
                    'Subcategory_Name': measure['subcategory'], 'Units': measure['source_units']}
        actual = {key: row[key].strip() for key in expected}
        if actual != expected:
            raise ValueError(f'USDA FEA variable lookup changed for {measure["variable_code"]}: {actual}')
        if '*' in row['Variable_Name']:
            raise ValueError(f'USDA FEA marks {measure["variable_code"]} as a State-level measure')
        result[measure['variable_code']] = row
    return result


def source_key(fips, state, county):
    """FIPS as text; rows without a FIPS code are keyed by their published state and name."""
    return fips if FIPS.match(fips) else f'{fips}|{state}|{county}'


def parse_values(path, config):
    """Stream the long-format file once and keep only the reviewed variables (bounded)."""
    wanted = {m['variable_code'] for m in config['measures']}
    stats = {'rows': 0, 'variables': set(), 'non_fips_rows': 0, 'duplicate_keys_all_variables': 0}
    selected, seen = {}, set()
    with Path(path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.reader(source)
        header = next(reader, None)
        if header != config['expected_values_header']:
            raise ValueError('USDA FEA StateAndCountyData.csv header changed')
        for row in reader:
            stats['rows'] += 1
            if stats['rows'] > MAX_ROWS:
                raise ValueError('USDA FEA row limit exceeded')
            if len(row) != 5:
                raise ValueError(f'USDA FEA row {stats["rows"]} has {len(row)} columns')
            fips, state, county, code, value = (cell.strip() for cell in row)
            stats['variables'].add(code)
            if not FIPS.match(fips):
                stats['non_fips_rows'] += 1
            key = (fips, code) if FIPS.match(fips) else (source_key(fips, state, county), code)
            if key in seen:
                stats['duplicate_keys_all_variables'] += 1
            seen.add(key)
            if code not in wanted:
                continue
            item = (source_key(fips, state, county), code)
            if item in selected:
                raise ValueError(f'Duplicate USDA FEA county/variable key: {item}')
            selected[item] = {'fips': fips, 'state': state, 'county': county, 'variable_code': code, 'value': value}
    stats['variables'] = len(stats['variables'])
    return selected, stats


def classify_value(raw, measure, config):
    """Return (Decimal|None, status). Sentinels never become numbers; zero is a true zero."""
    if raw in config['sentinels']:
        return None, config['sentinels'][raw]
    if not NUMBER.match(raw):
        raise ValueError(f'Undocumented USDA FEA value for {measure["variable_code"]}: {raw[:20]!r}')
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f'Unparseable USDA FEA value: {raw[:20]!r}') from exc
    low, high = measure['plausible_range']
    if not Decimal(str(low)) <= value <= Decimal(str(high)):
        raise ValueError(f'USDA FEA {measure["variable_code"]} value outside {low}..{high}: {raw}')
    return value, 'true_zero' if value == 0 else 'available'


def semantic_sha(selected, variables):
    rows = [[k[0], k[1], v['state'], v['county'], v['value']] for k, v in sorted(selected.items())]
    lookup = [[code, variables[code]] for code in sorted(variables)]
    return digest({'values': rows, 'variables': lookup})


# ---------------------------------------------------------------- geography

def _expected_source_only(config):
    """{(measure_id, source_key): (reason, expected_value_or_None)} from the registry."""
    result = {}
    for rule in config['expected_source_only']:
        if 'no_fips_state' in rule:
            keys = [source_key('N/A', rule['no_fips_state'], c) for c in rule['counties']]
        else:
            keys = rule['fips'] if isinstance(rule['fips'], list) else [rule['fips']]
        for measure_id in rule['measures']:
            for key in keys:
                if (measure_id, key) in result:
                    raise ValueError(f'USDA FEA registry lists {key} twice for {measure_id}')
                result[(measure_id, key)] = (rule['reason'], rule.get('expected_value'))
    return result


def boundary_only_rule(config, measure_id, geoid):
    for rule in config['expected_boundary_only']:
        if (rule['measures'] == 'all' or measure_id in rule['measures']) and re.match(rule['pattern'], geoid):
            return rule
    return None


def value_note(config, measure_id, geoid):
    for rule in config['documented_value_notes']:
        if measure_id in rule['measures'] and geoid in rule['fips']:
            return rule['note']
    return None


def classify(selected, boundary_geoids, config):
    """Join each selected row to an exact 2024 county or to a registry-listed exception."""
    expected = _expected_source_only(config)
    by_code = {m['variable_code']: m for m in config['measures']}
    classified, unexplained, value_mismatch = {}, [], []
    for (key, code), row in sorted(selected.items()):
        measure = by_code[code]
        rule = expected.get((measure['measure_id'], key))
        item = {'measure_id': measure['measure_id'], 'source_key': key, **row}
        if rule:
            item.update(boundary_status='source_only', exclusion_reason=rule[0], geoid=None)
            if rule[1] is not None and row['value'] != rule[1]:
                value_mismatch.append([measure['measure_id'], key, row['value']])
        elif FIPS.match(row['fips']) and row['fips'] in boundary_geoids:
            item.update(boundary_status='matched', exclusion_reason=None, geoid=row['fips'])
        else:
            item.update(boundary_status='source_only', exclusion_reason='unexplained', geoid=None)
            unexplained.append([measure['measure_id'], key])
        classified[(key, code)] = item
    present = {(i['measure_id'], i['source_key']) for i in classified.values()}
    absent = sorted([list(k) for k in set(expected) - present])
    boundary_only, unexplained_boundary, rule_counts = {}, [], {}
    for measure in config['measures']:
        matched = {i['geoid'] for i in classified.values()
                   if i['measure_id'] == measure['measure_id'] and i['boundary_status'] == 'matched'}
        counts = {}
        for geoid in sorted(boundary_geoids - matched):
            rule = boundary_only_rule(config, measure['measure_id'], geoid)
            if rule is None:
                unexplained_boundary.append([measure['measure_id'], geoid])
            else:
                counts[rule['reason']] = counts.get(rule['reason'], 0) + 1
        boundary_only[measure['measure_id']] = counts
        for rule in config['expected_boundary_only']:
            if rule['measures'] == 'all' or measure['measure_id'] in rule['measures']:
                if counts.get(rule['reason'], 0) != rule['expected_count']:
                    rule_counts[f'{measure["measure_id"]}|{rule["reason"]}'] = counts.get(rule['reason'], 0)
    return classified, {'unexplained': unexplained, 'expected_absent': absent, 'value_mismatch': value_mismatch,
                        'boundary_only': boundary_only, 'unexplained_boundary': unexplained_boundary,
                        'boundary_rule_count_mismatch': rule_counts}


# ---------------------------------------------------------------- orchestration

def retrieve(config, directory):
    """Archive every official input; return selected rows, variable lookup, stats, files, provenance."""
    from app.area_pilot.operations import disk_guard

    directory.mkdir(parents=True, exist_ok=True)
    disk_guard(directory, 3 * MAX_PAGE + MAX_ARCHIVE + MAX_EXPANDED)
    urls = config['source_urls']
    files, headers, texts, updated = [], {}, {}, {}
    for role, name in (('landing_page', 'food-environment-atlas.html'),
                       ('downloads_page', 'data-access-and-documentation-downloads.html'),
                       ('documentation', 'documentation.html')):
        path = directory / name
        headers[role] = _bounded_get(urls[role], path, MAX_PAGE)
        files.append(file_evidence(path, urls[role], role, headers[role]))
        raw = path.read_text(encoding='utf-8', errors='replace')
        texts[role] = raw
        updated[role] = page_updated(page_text(raw))
    href, last_updated = current_csv_link(texts['downloads_page'])
    markers = config['release_markers']
    if (href, last_updated) != (markers['csv_zip_href'], markers['csv_last_updated']):
        raise ValueError(f'USDA FEA current CSV release changed: {href} last updated {last_updated}. '
                         'Review the new release and update the registry.')
    verify_phrases(page_text(texts['downloads_page']), config['documentation_phrases']['downloads_page'], 'downloads page')
    verify_phrases(page_text(texts['documentation']), config['documentation_phrases']['documentation'], 'documentation')
    zip_path = directory / 'food-environment-atlas-csv-files.zip'
    headers['csv_zip'] = _bounded_get(urls['csv_zip'], zip_path, MAX_ARCHIVE)
    files.append(file_evidence(zip_path, urls['csv_zip'], 'csv_zip', headers['csv_zip']))
    members = extract_members(zip_path, config['expected_members'], directory)
    for name, role in ((config['values_member'], 'values_csv'), (config['variables_member'], 'variable_list_csv'),
                       (config['readme_member'], 'readme')):
        files.append(file_evidence(members[name]['path'], urls['csv_zip'] + '#' + name, role))
    readme = members[config['readme_member']]['path'].read_text(encoding='utf-8-sig', errors='replace')
    verify_phrases(readme, config['documentation_phrases']['readme'] + [markers['readme_release_sentence']], 'readme')
    variables = verify_variables(parse_variable_list(members[config['variables_member']]['path'], config), config)
    selected, stats = parse_values(members[config['values_member']]['path'], config)
    provenance = {'csv_zip_href': href, 'csv_last_updated': last_updated, 'page_updated': updated, 'http': headers,
                  'zip_members': {k: {'zip_timestamp': v['zip_timestamp'], 'bytes': v['bytes']}
                                  for k, v in members.items()},
                  'raw_values_sha256': next(f['sha256'] for f in files if f['role'] == 'values_csv'),
                  'retrieved_at': datetime.now(timezone.utc).isoformat()}
    return selected, variables, stats, files, provenance
