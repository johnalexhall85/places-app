"""EPA Toxics Release Inventory (TRI) reporting facilities: retrieval, validation, location policy.

Grain: the source file has one row per TRI form submission (Form R or Form A), keyed by
``DOC_CTRL_NUM``. CHIP keeps every submission (raw staging plus a report read model) and derives
one facility per published ``TRIFD`` and one facility-chemical relationship per (TRIFD, TRI
chemical ID). Several forms for the same facility and chemical are distinct submissions (for
example partial-facility forms with different NAICS codes); none is selected or dropped.

No release quantity is read into the read model, summed, or displayed. Facilities are never merged
by address or coordinates, and no location is geocoded or substituted.

Parsing streams the CSV row by row. Only compact per-report fields are held in memory; the raw
rows are re-streamed from the archived file when staging and reviewing.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

from app.area_pilot.epa_aqi import file_evidence, page_text
from app.area_pilot.source import digest

MAX_PAGE = 4 * 1024**2
MAX_PDF = 16 * 1024**2
MAX_CSV = 512 * 1024**2
USER_AGENT = 'CHIP-area-ingest/1.0'
CSV_FIELD_LIMIT = 1024 * 1024

MAPPED = 'mapped'
LOCATION_STATUSES = ('mapped', 'no_published_coordinates', 'invalid_coordinates', 'coarse_coordinate')
BOUNDARY_CHECKS = ('within_published_state', 'outside_published_state', 'outside_chip_boundary_layer', 'not_applicable')


def load_registry():
    path = Path(__file__).with_name('registry') / 'epa_tri_facilities.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    if config['refresh_policy']['auto_publish'] or config['product_kind'] != 'point_facility_reports':
        raise ValueError('TRI registry contract changed')
    header = config['expected_header']
    if len(header) != len(set(header)) or any(field not in header for field in config['fields'].values()):
        raise ValueError('TRI registry names a field outside the reviewed header')
    for group in ('facility_fields', 'report_level_facility_fields', 'chemical_fields'):
        if any(name not in config['fields'] for name in config[group]):
            raise ValueError(f'TRI registry {group} names an unknown field')
    codes = [s['code'] for s in config['industry_sectors']]
    if len(codes) != len(set(codes)) or str(config['reporting_year']) not in config['source_urls']['basic_csv']:
        raise ValueError('TRI registry sector list or reporting year is inconsistent')
    return config


# ---------------------------------------------------------------- retrieval

def download(url, target, limit, attempts=3):
    """Stream to a temporary file with timeouts, a byte cap, and bounded retries."""
    temporary = target.with_name(target.name + '.part')
    last = None
    for attempt in range(attempts):
        try:
            size = 0
            with requests.get(url, stream=True, timeout=(10, 300), allow_redirects=True,
                              headers={'User-Agent': USER_AGENT}) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError(f'Unexpected HTTP {response.status_code} for {url}')
                headers = {k.lower(): v for k, v in response.headers.items()
                           if k.lower() in ('last-modified', 'etag', 'content-length', 'content-type',
                                            'content-encoding', 'content-disposition')}
                with temporary.open('wb') as output:
                    for chunk in response.iter_content(256 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(f'EPA TRI response exceeds {limit} bytes: {url}')
                        output.write(chunk)
            if size == 0:
                raise ValueError(f'EPA TRI response was empty: {url}')
            if ('content-encoding' not in headers and headers.get('content-length', '').isdigit()
                    and int(headers['content-length']) != size):
                raise ValueError(f'EPA TRI response length differs from Content-Length: {url}')
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
    raise RuntimeError(f'EPA TRI download failed after {attempts} attempts: {url}') from last


def _plain(value):
    """Whitespace- and typographic-quote-normalized text for phrase comparison."""
    value = value.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    return re.sub(r'\s+', ' ', value).strip()


def verify_basic_page(raw_html, config):
    """Confirm the download template, documentation link, revision note, year list, and processing date."""
    if config['basic_page_template'] not in raw_html:
        raise ValueError('EPA TRI basic-files download URL template changed')
    missing = [link for link in config['basic_page_links'] if link not in raw_html]
    if missing:
        raise ValueError(f'EPA TRI basic-files page no longer links the documentation: {missing}')
    text = _plain(page_text(raw_html))
    missing = [p for p in config['basic_page_phrases'] if _plain(p) not in text]
    if missing:
        raise ValueError(f'EPA TRI basic-files page wording changed: {[m[:60] for m in missing]}')
    match = re.search(config['processed_as_of_pattern'], text)
    if not match:
        raise ValueError('EPA TRI processing date ("processed as of") not found')
    processed = datetime.strptime(match.group(1), '%B %d, %Y').date()
    select = re.search(r'Select year\s+((?:\d{4}\s+)+)', text)
    years = sorted({int(y) for y in select.group(1).split()}) if select else []
    year = config['reporting_year']
    if year not in years:
        raise ValueError(f'EPA TRI basic-files page no longer lists reporting year {year}')
    updated = re.search(r'Last updated on ([A-Z][a-z]+ \d{1,2}, \d{4})', text)
    return {'processed_as_of': processed.isoformat(), 'listed_years': [years[0], years[-1]] if years else [],
            'newer_year_listed': max(years) > year,
            'page_last_updated': datetime.strptime(updated.group(1), '%B %d, %Y').date().isoformat() if updated else None}


def verify_documentation(path, config):
    import pypdf  # deferred: only needed during ingestion

    reader = pypdf.PdfReader(str(path))
    text = _plain(' '.join(page.extract_text() or '' for page in reader.pages))
    missing = [p for p in config['documentation_phrases'] if _plain(p) not in text]
    if missing:
        raise ValueError(f'EPA TRI documentation definitions changed: {[m[:60] for m in missing]}')
    edition = re.search(r'Updated for RY ?(\d{4})', text)
    return {'pages': len(reader.pages), 'updated_for_reporting_year': int(edition.group(1)) if edition else None,
            'phrases_verified': len(config['documentation_phrases'])}


# ---------------------------------------------------------------- streaming CSV

def iter_rows(path, config):
    """Yield (line_number, values) with the exact reviewed header and column count."""
    header = config['expected_header']
    csv.field_size_limit(CSV_FIELD_LIMIT)
    with Path(path).open(newline='', encoding='utf-8', errors='strict') as source:
        reader = csv.reader(source)
        first = next(reader, None)
        if first and first[0].startswith('﻿'):
            first[0] = first[0][1:]
        if first != header:
            raise ValueError('EPA TRI CSV header differs from the reviewed schema')
        for values in reader:
            if len(values) != len(header):
                raise ValueError(f'EPA TRI CSV line {reader.line_num} has {len(values)} columns, expected {len(header)}')
            yield reader.line_num, values


def row_sha(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class Profile:
    """Compact, single-pass accumulation of everything validation and staging need (no quantities)."""

    def __init__(self, config):
        self.config = config
        header = config['expected_header']
        self.i = {name: header.index(field) for name, field in config['fields'].items()}
        self.reports = []           # compact per-report tuples
        self.row_hashes = {}        # doc_ctrl_num -> sha of the full raw row
        self.facility = {}          # facility_id -> facility attribute tuple from first report
        self.facility_conflicts = defaultdict(set)
        self.chemicals = {}         # chemical_id -> chemical attribute tuple
        self.chemical_names = defaultdict(set)
        self.chemical_conflicts = defaultdict(set)
        self.duplicate_docs = []
        self.malformed = Counter()
        self.years = Counter()
        self.vocab = {name: Counter() for name in config['vocabularies']}
        self.sectors = Counter()
        self.line_count = 0

    def add(self, line, values):
        c, i = self.config, self.i
        get = lambda name: values[i[name]]  # noqa: E731
        doc = get('doc_ctrl_num')
        self.line_count += 1
        if self.line_count > c['expected_report_rows']['max']:
            raise ValueError('EPA TRI report row limit exceeded')
        if doc in self.row_hashes:
            self.duplicate_docs.append(doc)
        self.row_hashes[doc] = row_sha(values)
        fid, chem = get('facility_id'), get('chemical_id')
        if not re.fullmatch(c['facility_id_pattern'], fid):
            self.malformed['facility_id'] += 1
        if not re.fullmatch(c['doc_ctrl_num_pattern'], doc) or doc[2:4] != c['doc_ctrl_year_digits']:
            self.malformed['doc_ctrl_num'] += 1
        if not re.fullmatch(c['chemical_id_pattern'], chem):
            self.malformed['chemical_id'] += 1
        self.years[get('year')] += 1
        for name in self.vocab:
            self.vocab[name][get(name)] += 1
        self.sectors[(get('industry_sector_code'), get('industry_sector'))] += 1
        facility = tuple(get(name) for name in c['facility_fields'])
        previous = self.facility.setdefault(fid, facility)
        if previous != facility:
            for name, a, b in zip(c['facility_fields'], previous, facility):
                if a != b:
                    self.facility_conflicts[fid].add(name)
        chemical = tuple(get(name) for name in c['chemical_fields'])
        known = self.chemicals.setdefault(chem, chemical)
        if known != chemical:
            for name, a, b in zip(c['chemical_fields'], known, chemical):
                if a != b:
                    self.chemical_conflicts[chem].add(name)
        self.chemical_names[chem].add(get('chemical'))
        self.reports.append((doc, fid, chem, get('chemical'), get('form_type'), get('industry_sector_code'),
                             get('industry_sector'), get('primary_naics'), get('elemental_metal_included'), line))


def profile_csv(path, config):
    profile = Profile(config)
    for line, values in iter_rows(path, config):
        profile.add(line, values)
    return profile


# ---------------------------------------------------------------- validation

def validate(profile, config):
    """Return (checks, issues). Blocking checks prevent staging; others hold a staged candidate."""
    year = str(config['reporting_year'])
    sector_labels = {s['code']: s['label'] for s in config['industry_sectors']}
    unreviewed = {}
    for name, allowed in config['vocabularies'].items():
        extra = sorted(set(profile.vocab[name]) - set(allowed))
        if extra:
            unreviewed[name] = extra[:20]
    bad_sectors = sorted(f'{code}|{label}' for code, label in profile.sectors if sector_labels.get(code) != label)
    if bad_sectors:
        unreviewed['industry_sector'] = bad_sectors[:20]
    bounds, fac_bounds = config['expected_report_rows'], config['expected_facilities']
    pairs = Counter((r[1], r[2]) for r in profile.reports)
    checks = {
        'reporting_year': set(profile.years) == {year},
        'report_keys_valid_unique': not profile.duplicate_docs and not profile.malformed['doc_ctrl_num'],
        'facility_and_chemical_ids_valid': not profile.malformed['facility_id'] and not profile.malformed['chemical_id'],
        'report_row_bounds': bounds['min'] <= len(profile.reports) <= bounds['max'],
        'facility_count_bounds': fac_bounds['min'] <= len(profile.facility) <= fac_bounds['max'],
        'facility_attributes_consistent': not profile.facility_conflicts,
        'chemical_attributes_consistent': not profile.chemical_conflicts,
        'reviewed_vocabularies': not unreviewed,
    }
    issues = {
        'reporting_years': dict(profile.years), 'duplicate_doc_ctrl_nums': profile.duplicate_docs[:50],
        'malformed': dict(profile.malformed),
        'facility_conflicts': {k: sorted(v) for k, v in sorted(profile.facility_conflicts.items())[:50]},
        'facility_conflict_count': len(profile.facility_conflicts),
        'chemical_conflicts': {k: sorted(v) for k, v in sorted(profile.chemical_conflicts.items())[:50]},
        'unreviewed_values': unreviewed,
        'multi_form_facility_chemical_pairs': sum(1 for n in pairs.values() if n > 1),
    }
    return checks, issues


# ---------------------------------------------------------------- coordinates and location policy

def decimals(raw):
    return len(raw.split('.', 1)[1]) if '.' in raw else 0


def parse_coordinates(lat_raw, lon_raw):
    """Return (lon, lat, decimals, status) from the published strings; never repairs a value."""
    lat_raw, lon_raw = lat_raw.strip(), lon_raw.strip()
    if not lat_raw and not lon_raw:
        return None, None, None, 'no_published_coordinates'
    if not lat_raw or not lon_raw:
        return None, None, None, 'invalid_coordinates'
    try:
        lat, lon = Decimal(lat_raw), Decimal(lon_raw)
    except InvalidOperation:
        return None, None, None, 'invalid_coordinates'
    if (not lat.is_finite() or not lon.is_finite() or not -90 <= lat <= 90 or not -180 <= lon <= 180
            or (lat == 0 and lon == 0)):
        return None, None, None, 'invalid_coordinates'
    places = min(decimals(lat_raw), decimals(lon_raw))
    if places <= 2:
        return None, None, places, 'coarse_coordinate'
    return lon, lat, places, MAPPED


def facility_locations(profile, config):
    """Location status for every facility (boundary checks are applied afterwards)."""
    names = config['facility_fields']
    lat_i, lon_i = names.index('latitude'), names.index('longitude')
    result = {}
    for fid, attrs in profile.facility.items():
        lon, lat, places, status = parse_coordinates(attrs[lat_i], attrs[lon_i])
        result[fid] = {'status': status, 'lon': lon, 'lat': lat, 'decimals': places}
    return result


def apply_boundary(locations, derived, profile, config):
    """Combine location statuses with the DB point-in-county result.

    ``derived`` maps facility_id -> derived county GEOID for mapped facilities that intersect a CHIP
    2024 county. A state mismatch is recorded, never used to exclude the point.
    """
    state_i = config['facility_fields'].index('state')
    final = {}
    for fid, item in locations.items():
        item = dict(item)
        geoid = derived.get(fid)
        item['derived_county_geoid'] = geoid
        if item['status'] != MAPPED:
            item['boundary_check'] = 'not_applicable'
        elif geoid is None:
            item['boundary_check'] = 'outside_chip_boundary_layer'
        elif config['state_fips'].get(profile.facility[fid][state_i]) == geoid[:2]:
            item['boundary_check'] = 'within_published_state'
        else:
            item['boundary_check'] = 'outside_published_state'
        item['exclusion_reason'] = None if item['status'] == MAPPED else item['status']
        final[fid] = item
    return final


# ---------------------------------------------------------------- read-model construction

def facility_attributes(profile, fid, config):
    attrs = dict(zip(config['facility_fields'], profile.facility[fid]))
    return {key: (value.strip() or None) for key, value in attrs.items()}


def build_relationships(profile):
    """Per-facility report aggregates and per (facility, chemical) relationships. No quantities."""
    facilities = defaultdict(lambda: {'reports': 0, 'forms': Counter(), 'sectors': set(), 'naics': set(), 'chemicals': set()})
    pairs = defaultdict(lambda: {'reports': 0, 'forms': set(), 'names': set()})
    chemicals = defaultdict(lambda: {'reports': 0, 'facilities': set(), 'forms': Counter()})
    for doc, fid, chem, name, form, sector, _label, naics, _metal, _line in profile.reports:
        f = facilities[fid]
        f['reports'] += 1
        f['forms'][form] += 1
        f['sectors'].add(sector)
        if naics:
            f['naics'].add(naics)
        f['chemicals'].add(chem)
        p = pairs[(fid, chem)]
        p['reports'] += 1
        p['forms'].add(form)
        p['names'].add(name)
        c = chemicals[chem]
        c['reports'] += 1
        c['facilities'].add(fid)
        c['forms'][form] += 1
    return facilities, pairs, chemicals


def facility_record_sha(profile, fid, config, facilities, pairs):
    f = facilities[fid]
    payload = [list(profile.facility[fid]), sorted(f['sectors']), sorted(f['naics']),
               sorted([chem, sorted(pairs[(fid, chem)]['forms']), pairs[(fid, chem)]['reports']] for chem in f['chemicals'])]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def semantic_sha(profile):
    """Every published column of every form, keyed and ordered by DOC_CTRL_NUM (order-independent)."""
    return digest(sorted(profile.row_hashes.items()))


def keyset_sha(profile):
    return digest(sorted(profile.row_hashes))


def location_digest(final):
    return digest([[fid, item['status'], item['boundary_check'], item['derived_county_geoid']]
                   for fid, item in sorted(final.items())])


def summarize(profile, final, facilities, pairs, chemicals):
    by_status = Counter(item['status'] for item in final.values())
    forms = Counter(r[4] for r in profile.reports)
    form_sets = Counter(tuple(sorted(f['forms'])) for f in facilities.values())
    colocated = Counter((item['lon'], item['lat']) for item in final.values() if item['status'] == MAPPED)
    return {
        'source_reports': len(profile.reports),
        'distinct_facilities': len(profile.facility),
        'distinct_chemical_ids': len(profile.chemicals),
        'facility_chemical_relationships': len(pairs),
        'multi_form_facility_chemical_pairs': sum(1 for p in pairs.values() if p['reports'] > 1),
        'form_type_reports': dict(sorted(forms.items())),
        'facilities_by_form_types': {'+'.join(k): v for k, v in sorted(form_sets.items())},
        'location_status_counts': dict(sorted(by_status.items())),
        'mapped': by_status[MAPPED],
        'not_mapped': len(final) - by_status[MAPPED],
        'boundary_check_counts': dict(sorted(Counter(i['boundary_check'] for i in final.values()
                                                     if i['status'] == MAPPED).items())),
        'colocated_coordinate_groups': sum(1 for n in colocated.values() if n > 1),
        'facilities_in_colocated_groups': sum(n for n in colocated.values() if n > 1),
        'max_facilities_at_one_coordinate': max(colocated.values(), default=0),
        'multi_sector_facilities': sum(1 for f in facilities.values() if len(f['sectors']) > 1),
        'chemical_ids_with_multiple_names': sum(1 for names in profile.chemical_names.values() if len(names) > 1),
        'facilities_without_frs_id': sum(1 for fid in profile.facility
                                         if not profile.facility[fid][0].strip()),
    }


# ---------------------------------------------------------------- end-to-end retrieval

def retrieve(config, directory):
    """Archive every official input and return the profile, file evidence, and provenance."""
    from app.area_pilot.operations import disk_guard

    directory.mkdir(parents=True, exist_ok=True)
    disk_guard(directory, MAX_PAGE + MAX_PDF + MAX_CSV)
    urls = config['source_urls']
    year = config['reporting_year']
    files, headers = [], {}
    for role, limit, name in (('basic_page', MAX_PAGE, 'tri_basic_data_files.html'),
                              ('documentation_pdf', MAX_PDF, urls['documentation_pdf'].rsplit('/', 1)[-1]),
                              ('basic_csv', MAX_CSV, f'{year}_us.csv')):
        path = directory / name
        headers[role] = download(urls[role], path, limit)
        files.append(file_evidence(path, urls[role], role, headers[role]))
    page = verify_basic_page((directory / 'tri_basic_data_files.html').read_text(encoding='utf-8', errors='replace'), config)
    documentation = verify_documentation(directory / urls['documentation_pdf'].rsplit('/', 1)[-1], config)
    csv_path = directory / f'{year}_us.csv'
    profile = profile_csv(csv_path, config)
    provenance = {'http': headers, 'page': page, 'documentation': documentation,
                  'retrieved_at': datetime.now(timezone.utc).isoformat(), 'csv_path': str(csv_path.resolve())}
    return profile, files, provenance
