"""HRSA Health Center Service Delivery and Look-Alike Sites: retrieval, validation, location policy.

This is a current point directory, not an area observation product. Each row is one HRSA BPHC
site (``BPHC Assigned Number``); the parent organization (``Health Center Number`` / ``Health
Center Name``) is carried as an attribute and never merged with the site. Rows are never
deduplicated by address or coordinates.

Location policy (see the registry ``location_policy``): coordinates are stored exactly as HRSA
published them and are only displayed when no suppression or quality rule applies. Nothing is
geocoded, and no city/ZIP/county centroid is ever substituted for a missing site location.
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
MAX_XLSX = 2 * 1024**2
MAX_CSV = 64 * 1024**2
USER_AGENT = 'CHIP-area-ingest/1.0'

MAPPED = 'mapped'
LOCATION_STATUSES = ('mapped', 'suppressed_source_policy', 'no_published_coordinates', 'invalid_coordinates',
                     'approximate_shared_coordinate', 'coarse_coordinate',
                     'published_county_not_in_boundary_layer', 'outside_published_county')
BOUNDARY_CHECKS = ('within_published_county', 'outside_chip_boundary_layer', 'not_applicable')


def load_registry():
    path = Path(__file__).with_name('registry') / 'hrsa_hc_sites.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    if config['refresh_policy']['auto_publish'] or config['product_kind'] != 'point_site_directory':
        raise ValueError('HRSA site registry contract changed')
    header = config['expected_header']
    fields = [config['site_id_field'], config['snapshot_field'], *config['exposed_attributes'].values(),
              *(c['source_field'] for c in config['classifications'].values()), *config['display_vocabularies']]
    if any(field not in header for field in fields):
        raise ValueError('HRSA site registry names a field outside the reviewed header')
    for name, block in config['classifications'].items():
        codes = [v['code'] for v in block['values']]
        sources = [v['source'] for v in block['values']]
        if len(codes) != len(set(codes)) or len(sources) != len(set(sources)) or not any(v['default'] for v in block['values']):
            raise ValueError(f'HRSA site classification {name} is invalid')
    return config


# ---------------------------------------------------------------- retrieval

def download(url, target, limit, attempts=3):
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
                           if k.lower() in ('last-modified', 'etag', 'content-length', 'content-type', 'content-encoding')}
                with temporary.open('wb') as output:
                    for chunk in response.iter_content(256 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(f'HRSA response exceeds {limit} bytes: {url}')
                        output.write(chunk)
            if size == 0:
                raise ValueError(f'HRSA response was empty: {url}')
            # Content-Length counts encoded bytes; it can only be compared when the body was not compressed.
            if ('content-encoding' not in headers and headers.get('content-length', '').isdigit()
                    and int(headers['content-length']) != size):
                raise ValueError(f'HRSA response length differs from Content-Length: {url}')
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
    raise RuntimeError(f'HRSA download failed after {attempts} attempts: {url}') from last


def verify_pages(download_html, topic_html, config):
    """Confirm the official links, usage terms, suppression note, and the topic-page refresh notice."""
    missing_links = [link for link in config['download_page_links'] if link not in download_html]
    if missing_links:
        raise ValueError(f'HRSA download page no longer links the site files: {missing_links}')
    text = page_text(download_html)
    missing = [phrase for phrase in config['download_page_phrases'] if phrase not in text]
    if missing:
        raise ValueError(f'HRSA download page terms or suppression note changed: {[m[:60] for m in missing]}')
    topic = page_text(topic_html)
    missing = [phrase for phrase in config['topic_page_phrases'] if phrase not in topic]
    if missing:
        raise ValueError(f'HRSA health center topic description changed: {[m[:60] for m in missing]}')
    anchor = topic.find(config['topic_page_phrases'][-1])
    match = re.search(r'Updated:\s*(\d{1,2}/\d{1,2}/\d{4})\s*Refresh Cycle:\s*(\w+)', topic[anchor:anchor + 600])
    return {'topic_updated': datetime.strptime(match.group(1), '%m/%d/%Y').date().isoformat() if match else None,
            'topic_refresh_cycle': match.group(2) if match else None,
            'usage_terms_verified': True, 'domestic_violence_suppression_note_verified': True}


def parse_metadata(path, config):
    """Read the official data dictionary and check every CSV column, phrase, and restriction."""
    import openpyxl  # deferred: only needed during ingestion

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if config['metadata_sheet'] not in workbook.sheetnames:
        raise ValueError('HRSA metadata sheet name changed')
    rows = [tuple('' if v is None else str(v) for v in row)
            for row in workbook[config['metadata_sheet']].iter_rows(values_only=True)]
    workbook.close()
    header = list(rows[0][:len(config['metadata_header'])])
    if header != config['metadata_header']:
        raise ValueError('HRSA metadata header changed')
    attributes = {}
    for row in rows[1:]:
        if not row[0]:
            continue
        if row[0] in attributes:
            raise ValueError(f'HRSA metadata repeats attribute {row[0]}')
        attributes[row[0]] = dict(zip(header, row))
    columns = [c for c in config['expected_header'] if c]
    undocumented = [c for c in columns if c not in attributes]
    if undocumented or set(attributes) - set(columns):
        raise ValueError(f'HRSA metadata and CSV columns differ: {undocumented or sorted(set(attributes) - set(columns))}')
    for attribute, phrase in config['metadata_phrases'].items():
        if phrase not in attributes[attribute]['Definition']:
            raise ValueError(f'HRSA metadata definition changed for {attribute}')
    exposed = set(config['exposed_attributes'].values()) | {c['source_field'] for c in config['classifications'].values()}
    exposed |= {config['site_id_field'], config['snapshot_field'],
                'Geocoding Artifact Address Primary X Coordinate', 'Geocoding Artifact Address Primary Y Coordinate'}
    restricted = sorted(a for a, item in attributes.items() if item['Data Restriction'] != 'Public')
    if exposed & set(restricted):
        raise ValueError(f'Exposed HRSA attribute is not Public: {sorted(exposed & set(restricted))}')
    return {'attributes': attributes, 'restricted_attributes': restricted,
            'digest': digest([[a, attributes[a]['Physical Column Name'], attributes[a]['Data Restriction'],
                               attributes[a]['Definition'], attributes[a]['Valid Values']] for a in sorted(attributes)])}


def parse_csv(path, config):
    """Return source rows in file order. The reviewed header (with its trailing empty column) is exact."""
    header = config['expected_header']
    rows = []
    with Path(path).open(newline='', encoding='utf-8', errors='strict') as source:
        reader = csv.reader(source)
        first = next(reader, None)
        if first and first[0].startswith('﻿'):
            first[0] = first[0][1:]
        if first != header:
            raise ValueError('HRSA site CSV header differs from reviewed schema')
        named = len(header) - 1  # the header ends with a comma; data rows carry 55 values
        for line_number, values in enumerate(reader, start=2):
            if len(values) == len(header) and values[-1] == '':
                values = values[:-1]
            if len(values) != named:
                raise ValueError(f'HRSA site CSV line {line_number} has {len(values)} columns, expected {named}')
            rows.append(dict(zip(header[:-1], values)))
            if len(rows) > config['expected_source_rows']['max']:
                raise ValueError('HRSA site row limit exceeded')
    return rows


# ---------------------------------------------------------------- validation

def classification_code(row, config, name):
    block = config['classifications'][name]
    return next((v['code'] for v in block['values'] if v['source'] == row[block['source_field']]), None)


def snapshot_date(rows, config):
    values = Counter(row[config['snapshot_field']] for row in rows)
    if len(values) != 1:
        return None, dict(values)
    raw = next(iter(values))
    try:
        return datetime.strptime(raw, config['snapshot_format']).date(), dict(values)
    except ValueError:
        return None, dict(values)


def validate_rows(rows, config):
    """Return (checks, issues). Blocking checks prevent staging; others hold a staged candidate."""
    id_field = config['site_id_field']
    pattern = re.compile(config['site_id_pattern'])
    ids = Counter(row[id_field] for row in rows)
    duplicates = sorted(k for k, v in ids.items() if v > 1)
    malformed = sorted(row[id_field] for row in rows if not pattern.fullmatch(row[id_field]))
    conflicting = []
    for row in rows:
        match = pattern.fullmatch(row[id_field])
        rule = config['program_consistency'].get(match.group(1)) if match else None
        if rule and (row['Health Center Type'] != rule['program']
                     or not row['Health Center Number'].startswith(rule['health_center_number_prefix'])):
            conflicting.append(row[id_field])
    unreviewed = {}
    for name, block in config['classifications'].items():
        values = sorted({row[block['source_field']] for row in rows} - {v['source'] for v in block['values']})
        if values:
            unreviewed[block['source_field']] = values
    for field, allowed in config['display_vocabularies'].items():
        values = sorted({row[field] for row in rows} - set(allowed))
        if values:
            unreviewed[field] = values
    statuses = sorted({row['Site Status Description'] for row in rows} - set(config['status_values']))
    if statuses:
        unreviewed['Site Status Description'] = statuses
    snapshot, snapshot_values = snapshot_date(rows, config)
    bounds = config['expected_source_rows']
    checks = {
        'source_row_bounds': bounds['min'] <= len(rows) <= bounds['max'],
        'site_ids_valid_unique': not duplicates and not malformed,
        'site_program_consistency': not conflicting,
        'classification_vocabulary': not unreviewed,
        'single_snapshot_date': snapshot is not None,
    }
    issues = {'duplicate_site_ids': duplicates[:50], 'duplicate_site_id_count': len(duplicates),
              'malformed_site_ids': malformed[:50], 'conflicting_site_program': conflicting[:50],
              'conflicting_site_program_count': len(conflicting), 'unreviewed_values': unreviewed,
              'snapshot_values': snapshot_values if snapshot is None else None}
    return checks, issues, snapshot


# ---------------------------------------------------------------- coordinates and location policy

def decimals(raw):
    number = Decimal(raw).normalize()
    return max(0, -number.as_tuple().exponent)


def parse_coordinate_pair(row):
    """Return (lon, lat, decimals, reason) from the published strings; never repairs a value."""
    raw_x = row['Geocoding Artifact Address Primary X Coordinate'].strip()
    raw_y = row['Geocoding Artifact Address Primary Y Coordinate'].strip()
    if not raw_x and not raw_y:
        return None, None, None, 'no_published_coordinates'
    if not raw_x or not raw_y:
        return None, None, None, 'invalid_coordinates'
    try:
        lon, lat = Decimal(raw_x), Decimal(raw_y)
    except InvalidOperation:
        return None, None, None, 'invalid_coordinates'
    if (not lon.is_finite() or not lat.is_finite() or not -180 <= lon <= 180 or not -90 <= lat <= 90
            or (lon == 0 and lat == 0)):
        return None, None, None, 'invalid_coordinates'
    return lon, lat, min(decimals(raw_x), decimals(raw_y)), None


def _norm(value):
    return re.sub(r'[^a-z0-9]', '', (value or '').casefold())


def suppressed_setting(row, config):
    return row['Health Center Service Delivery Site Location Setting Description'] in config['location_policy']['suppressed_settings']


def provisional_locations(rows, config):
    """Apply every row-level and shared-coordinate rule. Boundary checks are applied afterwards."""
    result = {}
    groups = defaultdict(list)
    for row in rows:
        site = row[config['site_id_field']]
        if suppressed_setting(row, config):
            result[site] = {'status': 'suppressed_source_policy', 'lon': None, 'lat': None, 'decimals': None}
            continue
        lon, lat, places, reason = parse_coordinate_pair(row)
        if reason:
            result[site] = {'status': reason, 'lon': None, 'lat': None, 'decimals': None}
            continue
        result[site] = {'status': MAPPED, 'lon': lon, 'lat': lat, 'decimals': places}
        groups[(lon, lat)].append(row)
    for (lon, lat), members in groups.items():
        if len(members) < 2:
            continue
        cities = {_norm(m['Site City']) for m in members}
        streets = {_norm(m['Site Address']) for m in members}
        coarse_shared = min(result[m[config['site_id_field']]]['decimals'] for m in members) <= 3
        if len(cities) > 1 or (coarse_shared and len(streets) > 1):
            for m in members:
                result[m[config['site_id_field']]]['status'] = 'approximate_shared_coordinate'
    for item in result.values():
        if item['status'] == MAPPED and item['decimals'] <= 2:
            item['status'] = 'coarse_coordinate'
    return result


def apply_boundary(rows, provisional, boundary, layer_states, config):
    """Combine provisional statuses with the DB point-in-published-county result.

    ``boundary`` maps site_id -> True/False (point intersects the 2024 county equal to its published
    FIPS) for every provisionally mapped site whose FIPS is in the layer. ``layer_states`` holds the
    state FIPS codes the CHIP 2024 county layer covers.
    """
    final = {}
    for row in rows:
        site = row[config['site_id_field']]
        item = dict(provisional[site])
        item['boundary_check'] = 'not_applicable'
        if item['status'] == MAPPED:
            state = row['State FIPS Code'].strip()
            if site in boundary:
                if boundary[site]:
                    item['boundary_check'] = 'within_published_county'
                else:
                    item['status'] = 'outside_published_county'
            elif state in layer_states:
                item['status'] = 'published_county_not_in_boundary_layer'
            else:
                item['boundary_check'] = 'outside_chip_boundary_layer'
        if item['status'] != MAPPED:
            item.update(lon=None, lat=None)
        item['exclusion_reason'] = None if item['status'] == MAPPED else item['status']
        final[site] = item
    return final


def public_attributes(row, config, status):
    """Documented, Public attributes only. Suppressed records lose address, ZIP, and phone."""
    attributes = {key: row[field].strip() or None for key, field in config['exposed_attributes'].items()}
    if status == 'suppressed_source_policy':
        for key in config['suppressed_location_fields']:
            attributes[key] = None
    return attributes


def site_record_sha(row, config):
    values = [row[c] for c in config['expected_header'] if c and c != config['snapshot_field']]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def semantic_sha(rows, config):
    """All published columns except the HRSA processing date, ordered by site ID."""
    key = config['site_id_field']
    return digest([[c for c in (row[h] for h in config['expected_header'] if h and h != config['snapshot_field'])]
                   for row in sorted(rows, key=lambda r: r[key])])


def keyset_sha(rows, config):
    return digest(sorted(row[config['site_id_field']] for row in rows))


def location_digest(final):
    return digest([[site, item['status'], item['boundary_check']] for site, item in sorted(final.items())])


def summarize(rows, final, config):
    eligible = set(config['eligible_statuses'])
    count = lambda pred: sum(1 for row in rows if pred(row))  # noqa: E731
    sid = config['site_id_field']
    by_status = Counter(final[row[sid]]['status'] for row in rows)
    default_codes = {name: {v['code'] for v in block['values'] if v['default']}
                     for name, block in config['classifications'].items()}

    def default_filter(row):
        return all(classification_code(row, config, name) in codes for name, codes in default_codes.items())
    return {
        'source_rows': len(rows),
        'eligible_status_rows': count(lambda r: r['Site Status Description'] in eligible),
        'location_status_counts': dict(sorted(by_status.items())),
        'mapped': by_status[MAPPED],
        'not_mapped': len(rows) - by_status[MAPPED],
        'boundary_check_counts': dict(Counter(final[r[sid]]['boundary_check'] for r in rows
                                              if final[r[sid]]['status'] == MAPPED)),
        'default_filter_rows': count(lambda r: r['Site Status Description'] in eligible and default_filter(r)),
        'default_filter_mapped': count(lambda r: r['Site Status Description'] in eligible and default_filter(r)
                                       and final[r[sid]]['status'] == MAPPED),
        'classification_counts': {block['source_field']: dict(Counter(r[block['source_field']] for r in rows))
                                  for block in config['classifications'].values()},
        'site_status_counts': dict(Counter(r['Site Status Description'] for r in rows)),
        'distinct_health_center_numbers': len({r['Health Center Number'] for r in rows}),
        'distinct_organization_names': len({r['Health Center Name'] for r in rows}),
        'colocated_mapped_coordinate_groups': sum(1 for n in Counter((final[r[sid]]['lon'], final[r[sid]]['lat'])
                                                                       for r in rows if final[r[sid]]['status'] == MAPPED).values() if n > 1),
    }


# ---------------------------------------------------------------- end-to-end retrieval

def retrieve(config, directory):
    """Archive every official input and return parsed rows, file evidence, and provenance."""
    from app.area_pilot.operations import disk_guard

    directory.mkdir(parents=True, exist_ok=True)
    disk_guard(directory, 2 * MAX_PAGE + MAX_XLSX + MAX_CSV)
    urls = config['source_urls']
    files, headers = [], {}
    for role, limit, name in (('download_page', MAX_PAGE, 'data_download.html'),
                              ('topic_page', MAX_PAGE, 'health_centers_topic.html'),
                              ('metadata_xlsx', MAX_XLSX, urls['metadata_xlsx'].rsplit('/', 1)[-1]),
                              ('sites_csv', MAX_CSV, urls['sites_csv'].rsplit('/', 1)[-1])):
        path = directory / name
        headers[role] = download(urls[role], path, limit)
        files.append(file_evidence(path, urls[role], role, headers[role]))
    pages = verify_pages((directory / 'data_download.html').read_text(encoding='utf-8', errors='replace'),
                         (directory / 'health_centers_topic.html').read_text(encoding='utf-8', errors='replace'), config)
    metadata = parse_metadata(directory / urls['metadata_xlsx'].rsplit('/', 1)[-1], config)
    rows = parse_csv(directory / urls['sites_csv'].rsplit('/', 1)[-1], config)
    provenance = {'http': headers, 'pages': pages, 'metadata_digest': metadata['digest'],
                  'restricted_attributes': metadata['restricted_attributes'],
                  'retrieved_at': datetime.now(timezone.utc).isoformat()}
    return rows, files, provenance, metadata
