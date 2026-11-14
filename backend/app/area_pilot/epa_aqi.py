"""EPA AirData annual AQI-by-county reader, validator, and documented county-name mapping.

The national annual file identifies counties only by EPA state and county names. County
GEOIDs are assigned from the archived, checksum-verified TIGER/Line 2024 county file using
the deterministic rules in ``map_counties``; no fuzzy or similarity matching is used.
"""
from __future__ import annotations

import calendar
import csv
import hashlib
import html
import io
import json
import os
import re
import time
import unicodedata
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

import requests

from app.area_pilot.source import digest

REPO_ROOT = Path(__file__).resolve().parents[3]
MAX_ARCHIVE = 5 * 1024**2
MAX_MEMBER = 20 * 1024**2
MAX_PAGE = 4 * 1024**2
MAX_PDF = 10 * 1024**2
MAX_ROWS = 5000
MAX_PLAUSIBLE_AQI = 10_000
USER_AGENT = 'CHIP-area-ingest/1.0'


def load_registry():
    path = Path(__file__).with_name('registry') / 'epa_aqi_county_2025.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    ids = [m['measure_id'] for m in config['measures']]
    if (ids != ['median_aqi', 'p90_aqi', 'max_aqi', 'days_with_aqi', 'good_days'] or
            config['geographies'] != ['county'] or config['aggregation_method'] != 'none' or
            config['refresh_policy']['auto_publish']):
        raise ValueError('EPA AQI registry contract changed')
    if any(m['source_field'] not in config['expected_header'] for m in config['measures']):
        raise ValueError('EPA AQI registry measure field is not in the reviewed header')
    return config


# ---------------------------------------------------------------- retrieval

def _bounded_get(url, target, limit, attempts=3):
    """Download to a temporary file with timeouts, a byte cap, and bounded retries."""
    temporary = target.with_name(target.name + '.part')
    last = None
    for attempt in range(attempts):
        try:
            size = 0
            with requests.get(url, stream=True, timeout=(10, 60), allow_redirects=True,
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
                            raise ValueError(f'EPA response exceeds {limit} bytes: {url}')
                        output.write(chunk)
            if size == 0:
                raise ValueError(f'EPA response was empty: {url}')
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
    raise RuntimeError(f'EPA download failed after {attempts} attempts: {url}') from last


def file_evidence(path, url, role, http_headers=None):
    sha = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            sha.update(block)
    return {'role': role, 'path': str(Path(path).resolve()), 'url': url, 'sha256': sha.hexdigest(),
            'byte_count': Path(path).stat().st_size, 'retrieved_at': datetime.now(timezone.utc),
            'http': http_headers or {}}


def page_text(raw_html):
    cleaned = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', raw_html)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', cleaned))).strip()


def verify_documentation(text_value, config):
    missing = [phrase for phrase in config['documentation_phrases'] if phrase not in text_value]
    if missing:
        raise ValueError(f'EPA AQI documentation definitions changed: {missing[:2]}')
    return {phrase: True for phrase in config['documentation_phrases']}


def parse_file_list(text_value, pattern):
    """Return {year: {'rows', 'size_kb', 'created'}} for annual county AQI files."""
    reader = csv.DictReader(io.StringIO(text_value))
    if reader.fieldnames != ['Filename', 'Rows', 'Size', 'Created']:
        raise ValueError('EPA file_list.csv header changed')
    regex = re.compile('^' + pattern + '$')
    result = {}
    for row in reader:
        match = regex.match(row['Filename'] or '')
        if match:
            year = int(match.group(1))
            if year in result:
                raise ValueError('EPA file list repeats a county AQI year')
            result[year] = {'filename': row['Filename'], 'rows': int(row['Rows']),
                            'size_kb': int(row['Size']), 'created': date.fromisoformat(row['Created'])}
    if not result:
        raise ValueError('EPA file list has no annual county AQI files')
    return result


def select_completed_year(listing, today, preliminary_until='05-01'):
    """Latest calendar year that has ended; never the current partial year.

    The returned dict also states whether the file was generated after EPA's documented
    preliminary period (May 1 of the following year). That is a necessary condition for review,
    not a claim that the data are final or that monitoring coverage is complete.
    """
    completed = [year for year in listing if year < today.year]
    if not completed:
        raise ValueError('No completed calendar-year county AQI file is listed')
    year = max(completed)
    month, day = (int(part) for part in preliminary_until.split('-'))
    cutoff = date(year + 1, month, day)
    skipped = sorted(y for y in listing if y >= today.year)
    return {'year': year, 'file': listing[year], 'skipped_current_or_future_years': skipped,
            'preliminary_cutoff': cutoff.isoformat(),
            'built_after_preliminary_cutoff': listing[year]['created'] >= cutoff}


def safe_member(archive, expected_name):
    infos = archive.infolist()
    total = 0
    for info in infos:
        name = PurePosixPath(info.filename)
        if (name.is_absolute() or '..' in name.parts or '\\' in info.filename or
                info.flag_bits & 1 or info.file_size > MAX_MEMBER or
                ((info.external_attr >> 16) & 0o170000) == 0o120000):
            raise ValueError('Unsafe EPA AQI ZIP member')
        total += info.file_size
        if total > MAX_MEMBER:
            raise ValueError('EPA AQI ZIP expands beyond limit')
    if [info.filename for info in infos] != [expected_name]:
        raise ValueError('EPA AQI ZIP must contain exactly the expected CSV member')
    return infos[0]


def extract_member(zip_path, expected_name, directory):
    with zipfile.ZipFile(zip_path) as archive:
        info = safe_member(archive, expected_name)
        target = directory / expected_name
        temporary = target.with_name(target.name + '.part')
        with archive.open(info) as source, temporary.open('wb') as output:
            copied = 0
            for block in iter(lambda: source.read(256 * 1024), b''):
                copied += len(block)
                if copied > MAX_MEMBER:
                    raise ValueError('EPA AQI member exceeds extraction limit')
                output.write(block)
        if copied != info.file_size:
            temporary.unlink(missing_ok=True)
            raise ValueError('Incomplete EPA AQI extraction')
        os.replace(temporary, target)
        return target


# ---------------------------------------------------------------- parsing and validation

def parse_int(raw, field):
    value = (raw or '').strip()
    if value == '':
        # Blanks are not documented for these fields in the annual file; never guess a value.
        raise ValueError(f'Undocumented blank in EPA field {field}')
    if not re.fullmatch(r'[0-9]+', value):
        raise ValueError(f'Non-integer EPA value in {field}: {value[:20]!r}')
    return int(value)


def days_in_year(year):
    return 366 if calendar.isleap(year) else 365


def validate_row(row, config, year):
    """Return integer fields after checking documented ranges and internal consistency."""
    numbers = {field: parse_int(row[field], field) for field in config['expected_header'][2:]}
    if numbers['Year'] != year:
        raise ValueError(f'EPA row year {numbers["Year"]} differs from selected year {year}')
    reporting = numbers['Days with AQI']
    if not 1 <= reporting <= days_in_year(year):
        raise ValueError('Days with AQI outside 1..calendar length')
    if sum(numbers[f] for f in config['category_fields']) != reporting:
        raise ValueError('AQI category days do not sum to Days with AQI')
    if numbers['Good Days'] > reporting:
        raise ValueError('Good Days exceed Days with AQI')
    if sum(numbers[f] for f in config['main_pollutant_fields']) > reporting:
        raise ValueError('Main-pollutant days exceed Days with AQI')
    median, p90, high = numbers['Median AQI'], numbers['90th Percentile AQI'], numbers['Max AQI']
    if not median <= p90 <= high:
        raise ValueError('AQI median/90th percentile/maximum ordering failed')
    if high > MAX_PLAUSIBLE_AQI:
        raise ValueError('Max AQI exceeds bounded plausibility limit')
    # Official category bounds: 0-50, 51-100, 101-150, 151-200, 201-300, 301+.
    top = next(i for i, upper in enumerate((50, 100, 150, 200, 300, None)) if upper is None or high <= upper)
    counts = [numbers[f] for f in config['category_fields']]
    if counts[top] < 1 or any(counts[top + 1:]):
        raise ValueError('Max AQI is inconsistent with AQI category day counts')
    return numbers


def parse_csv(path, config, year):
    with Path(path).open(newline='', encoding='utf-8') as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != config['expected_header']:
            raise ValueError('EPA AQI CSV header differs from reviewed schema')
        records = {}
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError('EPA AQI CSV row has an unexpected column count')
            key = (row['State'], row['County'])
            if key in records:
                raise ValueError(f'Duplicate EPA state/county/year key: {key}')
            validate_row(row, config, year)
            records[key] = dict(row)
            if len(records) > MAX_ROWS:
                raise ValueError('EPA AQI row limit exceeded')
    return records


def observation_values(record, config):
    """Five published values for one source row; zero stays a true reported zero."""
    reporting = int(record['Days with AQI'])
    result = []
    for measure in config['measures']:
        value = int(record[measure['source_field']])
        note = None
        if measure['kind'] == 'aqi_index' and value > 500:
            note = 'above_500_beyond_aqi_scale'
        result.append({'measure': measure, 'value': value,
                       'status': 'true_zero' if value == 0 else 'available',
                       'days_with_aqi': reporting, 'value_note': note})
    return result


def semantic_sha(records):
    return digest([[state, county, records[(state, county)]] for state, county in sorted(records)])


# ---------------------------------------------------------------- county identifiers

def fold(value):
    decomposed = unicodedata.normalize('NFKD', value)
    stripped = ''.join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', stripped).strip().casefold()


CITY_PAREN = re.compile(r'^(.*\S)\s*\(city\)$', re.IGNORECASE)


def parse_site_listing(path, config, wanted):
    """EPA's own (State Name, County Name) -> State Code + County Code, for wanted pairs only."""
    codes = {}
    with Path(path).open(newline='', encoding='utf-8') as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or any(f not in reader.fieldnames for f in config['site_listing_fields']):
            raise ValueError('EPA site listing lacks State/County code or name fields')
        for row in reader:
            key = (row['State Name'], row['County Name'])
            if key not in wanted:
                continue
            state, county = row['State Code'], row['County Code']
            if not (re.fullmatch(r'[0-9]{2}', state) and re.fullmatch(r'[0-9]{3}', county)):
                raise ValueError(f'EPA site listing has a malformed code for {key}')
            codes.setdefault(key, set()).add(state + county)
    return codes


def load_lookup(config):
    """Read TIGER 2024 county and state attributes from the archived, checksum-pinned ZIPs."""
    import geopandas as gpd  # deferred: heavy import only needed during ingestion

    boundary = config['boundary']
    files = []
    tables = {}
    for role, key in (('name_lookup_county', 'name_lookup'), ('name_lookup_state', 'state_lookup')):
        path = REPO_ROOT / boundary[f'{key}_archive']
        evidence = file_evidence(path, boundary[f'{key}_url'], role)
        if evidence['sha256'] != boundary[f'{key}_sha256']:
            raise ValueError(f'Archived TIGER {role} checksum differs from registry')
        files.append(evidence)
        tables[role] = gpd.read_file(f'zip://{path}', ignore_geometry=True)
    counties = [{'geoid': str(r.GEOID), 'statefp': str(r.STATEFP), 'name': str(r.NAME),
                 'namelsad': str(r.NAMELSAD), 'lsad': str(r.LSAD)}
                for r in tables['name_lookup_county'].itertuples()]
    states = {str(r.STATEFP): str(r.NAME) for r in tables['name_lookup_state'].itertuples()}
    return counties, states, files


def name_rule(source_county, tiger, same_state, city_lsad):
    """Return the rule under which an EPA county name agrees with its TIGER county, else None.

      namelsad         folded EPA name equals folded NAMELSAD ('X (City)' is read as 'X city')
      unique_name      folded EPA name equals folded NAME, unique within the state
      county_not_city  NAME is shared only by this county and independent cities (LSAD 25)
                       and the EPA name has no city suffix
    Folding is Unicode accent removal, whitespace trim/collapse, and case folding only.
    """
    source = fold(source_county)
    paren = CITY_PAREN.match(source_county.strip())
    lsad_form = fold(paren.group(1) + ' city') if paren else source
    if fold(tiger['namelsad']) == lsad_form:
        return 'namelsad'
    if paren or fold(tiger['name']) != source:
        return None
    named = [c for c in same_state if fold(c['name']) == source]
    if len(named) == 1:
        return 'unique_name'
    others = [c for c in named if c['geoid'] != tiger['geoid']]
    if tiger['lsad'] != city_lsad and others and all(c['lsad'] == city_lsad for c in others):
        return 'county_not_city'
    return None


def map_counties(records, site_codes, counties, states, config):
    """Assign each source row EPA's published county code and cross-check it against TIGER 2024."""
    by_geoid = {c['geoid']: c for c in counties}
    by_state = {}
    for county in counties:
        by_state.setdefault(county['statefp'], []).append(county)
    state_variants = {k: v['statefp'] for k, v in config['reviewed_state_variants'].items()}
    variants = {(v['state'], v['county']): v for v in config['reviewed_name_variants']}
    city_lsad = config['boundary']['independent_city_lsad']
    results, used = {}, set()
    for key in sorted(records):
        state, county = key
        evidence = {'source_state': state, 'source_county': county, 'epa_code': None, 'geoid': None,
                    'method': None, 'tiger_namelsad': None, 'accent_folded': False}
        found = site_codes.get(key, set())
        if len(found) != 1:
            evidence['method'] = 'no_unique_epa_code' if found else 'no_epa_code'
            results[key] = evidence
            continue
        code = next(iter(found))
        evidence['epa_code'] = code
        tiger = by_geoid.get(code)
        if tiger is None:
            evidence['method'] = 'epa_code_not_in_tiger_2024'
            results[key] = evidence
            continue
        state_ok = (fold(states.get(code[:2], '')) == fold(state) or state_variants.get(state) == code[:2])
        rule = name_rule(county, tiger, by_state[tiger['statefp']], city_lsad) if state_ok else None
        variant = variants.get(key)
        if rule is None and variant and variant['geoid'] == code and variant['tiger_namelsad'] == tiger['namelsad']:
            rule = 'reviewed_variant'
            used.add(key)
        evidence.update(tiger_namelsad=tiger['namelsad'])
        if rule:
            evidence.update(geoid=code, method=rule,
                            accent_folded=rule != 'reviewed_variant' and county.strip().casefold() not in
                            (tiger['name'].casefold(), tiger['namelsad'].casefold()) and
                            fold(county) in (fold(tiger['name']), fold(tiger['namelsad'])))
        else:
            evidence['method'] = 'state_name_disagreement' if not state_ok else 'name_disagreement'
        results[key] = evidence
    unused = sorted(set(variants) - used)
    return results, unused


def classify(records, mapping, boundary_geoids, config):
    """Matched rows join exact 2024 boundaries; everything else must be a registry-listed exclusion."""
    expected = {(item['state'], item['county']): item['reason'] for item in config['expected_exclusions']}
    classified, unexplained = {}, []
    for key in sorted(records):
        item = dict(mapping[key])
        if key in expected:
            item.update(boundary_status='source_only', exclusion_reason=expected[key])
        elif item['geoid'] and item['geoid'] in boundary_geoids:
            item.update(boundary_status='matched', exclusion_reason=None)
        else:
            item.update(boundary_status='source_only', exclusion_reason='unexplained')
            unexplained.append(key)
        classified[key] = item
    geoids = [item['geoid'] for item in classified.values() if item['boundary_status'] == 'matched']
    duplicates = sorted({g for g in geoids if geoids.count(g) > 1})
    missing_expected = sorted(set(expected) - set(records))
    return classified, {'unexplained': unexplained, 'duplicate_geoids': duplicates,
                        'expected_exclusions_absent': missing_expected}


def retrieve(config, directory, today=None):
    """Archive every official input and return parsed records, site codes, and provenance."""
    from app.area_pilot.operations import disk_guard

    directory.mkdir(parents=True, exist_ok=True)
    disk_guard(directory, 2 * MAX_ARCHIVE + 2 * MAX_MEMBER + 2 * MAX_PAGE + MAX_PDF)
    urls = config['source_urls']
    files, headers = [], {}
    for role, limit, name in (('download_page', MAX_PAGE, 'download_files.html'),
                              ('file_list', MAX_PAGE, 'file_list.csv'),
                              ('documentation', MAX_PAGE, 'about_airdata_reports.html'),
                              ('pm25_advisory', MAX_PDF, 'Data_Advisory_PM25_88101_Pregen_Files.pdf')):
        path = directory / name
        headers[role] = _bounded_get(urls[role], path, limit)
        files.append(file_evidence(path, urls[role], role, headers[role]))
    listing = parse_file_list((directory / 'file_list.csv').read_text(encoding='utf-8'), config['file_pattern'])
    selection = select_completed_year(listing, today or datetime.now(timezone.utc).date(),
                                      config['preliminary_until'])
    page = (directory / 'download_files.html').read_text(encoding='utf-8', errors='replace')
    if selection['file']['filename'] not in page:
        raise ValueError('Selected county AQI file is not linked from the download page')
    if selection['year'] != config['observation_year']:
        raise ValueError(f'Latest completed AQI year is {selection["year"]}; registry is pinned to '
                         f'{config["observation_year"]}. Review definitions and update the registry.')
    if not selection['built_after_preliminary_cutoff']:
        raise ValueError('Selected AQI file was generated before EPA preliminary cutoff')
    verify_documentation(
        page_text((directory / 'about_airdata_reports.html').read_text(encoding='utf-8', errors='replace')), config)
    members = {}
    for role, member_name in (('county_zip', config['expected_member']),
                              ('site_listing_zip', config['site_listing_member'])):
        zip_path = directory / urls[role].rsplit('/', 1)[-1]
        headers[role] = _bounded_get(urls[role], zip_path, MAX_ARCHIVE)
        files.append(file_evidence(zip_path, urls[role], role, headers[role]))
        members[role] = extract_member(zip_path, member_name, directory)
        files.append(file_evidence(members[role], urls[role] + '#' + member_name,
                                   role.replace('_zip', '_csv')))
    records = parse_csv(members['county_zip'], config, selection['year'])
    if len(records) != selection['file']['rows']:
        raise ValueError('EPA AQI row count differs from file_list.csv')
    if len(records) != config['expected_source_rows']:
        raise ValueError('EPA AQI row count differs from reviewed registry')
    site_codes = parse_site_listing(members['site_listing_zip'], config, set(records))
    provenance = {'selection': {**selection, 'file': {**selection['file'],
                                                      'created': selection['file']['created'].isoformat()}},
                  'http': headers, 'definitions_verified': list(config['documentation_phrases'])}
    return records, site_codes, files, provenance
