"""CMS Nursing Home Provider Information: official archive, validation, and typed point rows."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

from app.area_pilot.epa_aqi import file_evidence
from app.area_pilot.hrsa_sites import download
from app.area_pilot.operations import disk_guard
from app.area_pilot.source import digest

PRODUCT = 'cms_nursing_home_provider_info'
MAX_CSV = 64 * 1024**2
MAX_PDF = 8 * 1024**2
MAX_META = 1024**2
CCN = 'CMS Certification Number (CCN)'
RATING_COLUMNS = ('Overall Rating', 'Health Inspection Rating', 'Staffing Rating', 'QM Rating')
RATING_FOOTNOTES = tuple(f'{name} Footnote' for name in RATING_COLUMNS)


def load_registry():
    path = Path(__file__).with_name('registry') / 'cms_nursing_homes.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    if config['dataset_id'] != PRODUCT or config['refresh_policy']['auto_publish']:
        raise ValueError('CMS nursing home registry contract changed')
    return config


def official_csv_url(metadata, config):
    if metadata.get('identifier') != '4pq5-n9py' or metadata.get('accessLevel') != 'public':
        raise ValueError('CMS dataset metadata identity or public access changed')
    if 'one row per nursing home' not in metadata.get('description', '').lower():
        raise ValueError('CMS source grain description changed')
    distributions = metadata.get('distribution') or []
    urls = [item.get('downloadURL') for item in distributions if item.get('mediaType') == 'text/csv'
            and item.get('describedBy') == config['dictionary_url']]
    if len(urls) != 1 or urlparse(urls[0]).netloc != 'data.cms.gov' or not urls[0].endswith('.csv'):
        raise ValueError('CMS official CSV distribution changed or is ambiguous')
    for name in ('modified', 'released'):
        date.fromisoformat(metadata[name])
    return urls[0]


def parse_dictionary(path):
    reader = PdfReader(str(path))
    if len(reader.pages) < 25 or len(reader.pages) > 100:
        raise ValueError('CMS data dictionary page count changed')
    text = '\n'.join(page.extract_text() for page in reader.pages)
    phrases = ('Provider Information file variables', 'Number of Federally Certified Beds',
               'Overall Rating (1-5)', 'Health Inspection Rating (1-5)',
               'Quality Measure (QM) Rating (1-5)', 'Staffing Rating (1-5)',
               'Footnote Codes used in Nursing Home data tables',
               'coordinates are based on the facility’s zip',
               'Processing Date', 'Date the data was retrieved')
    missing = [phrase for phrase in phrases if phrase not in text]
    if missing:
        raise ValueError(f'CMS dictionary definitions changed: {missing}')
    return {'pages': len(reader.pages), 'verified_phrases': len(phrases)}


def parse_csv(path, config):
    rows = []
    with Path(path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != config['expected_header']:
            raise ValueError('CMS Provider Information header changed')
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f'CMS CSV line {line} differs from header width')
            rows.append(row)
            if len(rows) > config['expected_source_rows']['max']:
                raise ValueError('CMS source row cap exceeded')
    return rows


def _integer(raw, low, high, label):
    if raw == '':
        return None
    if not re.fullmatch(r'[0-9]+', raw) or not low <= int(raw) <= high:
        raise ValueError(f'Invalid {label}: {raw}')
    return int(raw)


def location(row):
    lat_raw, lon_raw = row['Latitude'].strip(), row['Longitude'].strip()
    footnote = row['Geocoding Footnote'].strip()
    if footnote == '22':
        return 'zip_based_coordinate', None, None
    if footnote:
        raise ValueError(f'Unreviewed geocoding footnote: {footnote}')
    if not lat_raw and not lon_raw:
        return 'no_published_coordinates', None, None
    if not lat_raw or not lon_raw:
        return 'invalid_coordinates', None, None
    try:
        lat, lon = Decimal(lat_raw), Decimal(lon_raw)
    except InvalidOperation:
        return 'invalid_coordinates', None, None
    if not lat.is_finite() or not lon.is_finite() or not -90 <= lat <= 90 or not -180 <= lon <= 180 or (lat == 0 and lon == 0):
        return 'invalid_coordinates', None, None
    return 'mapped', lon, lat


def typed(row, config):
    ccn = row[CCN]
    if not re.fullmatch(r'[0-9A-Za-z]{6}', ccn):
        raise ValueError(f'Invalid CMS CCN: {ccn}')
    if not row['Provider Name'].strip() or not re.fullmatch(r'[A-Z]{2}', row['State']):
        raise ValueError(f'Missing provider name or invalid state: {ccn}')
    beds = _integer(row['Number of Certified Beds'], 0, 100000, 'certified beds')
    ratings = [_integer(row[field], 1, 5, field) for field in RATING_COLUMNS]
    footnotes = {}
    for name, field in zip(('overall', 'health_inspection', 'staffing', 'quality_measure'), RATING_FOOTNOTES):
        code = row[field].strip()
        if code and code not in config['footnotes']:
            raise ValueError(f'Unreviewed CMS rating footnote {code}: {ccn}')
        footnotes[name] = {'code': code or None, 'explanation': config['footnotes'].get(code)}
    if any(value is None and footnotes[name]['code'] is None for name, value in zip(footnotes, ratings)):
        raise ValueError(f'Unexplained missing CMS rating: {ccn}')
    status, lon, lat = location(row)
    return {'ccn': ccn, 'sha': digest(row), 'name': row['Provider Name'],
            'address': row['Provider Address'] or None, 'city': row['City/Town'] or None,
            'state': row['State'], 'zip': row['ZIP Code'] or None, 'county': row['County/Parish'] or None,
            'provider_type': row['Provider Type'], 'ownership_type': row['Ownership Type'],
            'beds': beds, 'overall': ratings[0], 'health': ratings[1], 'staffing': ratings[2], 'qm': ratings[3],
            'footnotes': footnotes, 'geocoding_footnote': row['Geocoding Footnote'] or None,
            'processing_date': date.fromisoformat(row['Processing Date']),
            'source_latitude': row['Latitude'] or None, 'source_longitude': row['Longitude'] or None,
            'location_status': status, 'lon': str(lon) if lon is not None and status == 'mapped' else None,
            'lat': str(lat) if lat is not None and status == 'mapped' else None}


def validate(rows, config):
    ids = Counter(row[CCN] for row in rows)
    duplicate_ids = sorted(key for key, count in ids.items() if count > 1)
    malformed_ids = sorted(key for key in ids if not re.fullmatch(r'[0-9A-Za-z]{6}', key))
    dates = Counter(row['Processing Date'] for row in rows)
    checks = {'source_row_bounds': config['expected_source_rows']['min'] <= len(rows) <= config['expected_source_rows']['max'],
              'ccn_valid_unique': not duplicate_ids and not malformed_ids,
              'single_processing_date': len(dates) == 1}
    issue = {'duplicate_ccns': duplicate_ids[:30], 'duplicate_count': len(duplicate_ids),
             'malformed_ccns': malformed_ids[:30], 'processing_dates': dict(dates)}
    records = []
    if checks['ccn_valid_unique'] and checks['single_processing_date']:
        for row in rows:
            try:
                records.append(typed(row, config))
            except (ValueError, KeyError) as exc:
                issue.setdefault('invalid_rows', []).append({'ccn': row[CCN], 'reason': str(exc)})
                if len(issue['invalid_rows']) >= 30:
                    break
    checks['typed_values_and_footnotes'] = len(records) == len(rows)
    if checks['single_processing_date']:
        try:
            date.fromisoformat(next(iter(dates)))
        except ValueError:
            checks['single_processing_date'] = False
    return checks, issue, records


def summarize(rows, records):
    status = Counter(item['location_status'] for item in records)
    states = Counter(item['state'] for item in records)
    return {'source': len(rows), 'mapped': status['mapped'], 'unmapped': len(rows)-status['mapped'],
            'excluded': status['zip_based_coordinate'], 'location_status_counts': dict(status),
            'state_counts': dict(sorted(states.items())),
            'unrated_overall': sum(item['overall'] is None for item in records),
            'missing_ratings': {name: sum(item[name] is None for item in records)
                                for name in ('overall','health','staffing','qm')},
            'missing_beds': sum(item['beds'] is None for item in records),
            'colocated_coordinate_groups': sum(n > 1 for n in Counter((item['lon'],item['lat']) for item in records
                                                              if item['location_status']=='mapped').values())}


def retrieve(config, directory):
    directory.mkdir(parents=True, exist_ok=True)
    disk_guard(directory, MAX_CSV + MAX_PDF + 2*MAX_META)
    metadata_path = directory / 'dataset_metadata.json'
    metadata_headers = download(config['metadata_url'], metadata_path, MAX_META)
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    csv_url = official_csv_url(metadata, config)
    roles = [('metadata', config['metadata_url'], metadata_path, metadata_headers)]
    count_url = 'https://data.cms.gov/provider-data/api/1/datastore/query/4pq5-n9py/0?results=false&schema=false&count=true'
    count_path = directory / 'api_count.json'
    count_headers = download(count_url, count_path, MAX_META)
    roles.append(('api_count', count_url, count_path, count_headers))
    for role, url, path, limit in [('dictionary_pdf', config['dictionary_url'], directory / 'NH_Data_Dictionary.pdf', MAX_PDF),
                                   ('provider_csv', csv_url, directory / Path(urlparse(csv_url).path).name, MAX_CSV)]:
        headers = download(url, path, limit)
        roles.append((role, url, path, headers))
    parse_dictionary(roles[2][2])
    rows = parse_csv(roles[3][2], config)
    if json.loads(count_path.read_text(encoding='utf-8')).get('count') != len(rows):
        raise ValueError('Official full CSV row count differs from CMS API count')
    files = [file_evidence(path, url, role, headers) for role, url, path, headers in roles]
    return rows, metadata, files, {'retrieved_at': datetime.now(timezone.utc).isoformat(),
                                   'csv_url': csv_url, 'http': {role: headers for role, _, _, headers in roles}}
