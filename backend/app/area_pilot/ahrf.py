"""Pinned, selective reader for HRSA's AHRF county CSV and dictionary ZIPs."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import openpyxl
import requests

from app.area_pilot.source import digest

MAX_ARCHIVE = 80 * 1024**2
MAX_MEMBER = 45 * 1024**2
MAX_EXTRACTED = 100 * 1024**2
MAX_ROWS = 4000
ZIP_FILES = ('AHRF2025hp.csv', 'AHRF2025hf.csv')


def load_registry():
    path = Path(__file__).with_name('registry') / 'ahrf_2024_2025.json'
    config = json.loads(path.read_text())
    if len(config['measures']) != 5 or config['geographies'] != ['county'] or config['refresh_policy']['auto_publish']:
        raise ValueError('AHRF registry contract changed')
    return config


def parse_count(raw):
    """A blank AHRF cell means unreported; zero is an actual reported zero."""
    value = raw.strip()
    if not value:
        return None, 'missing', ''
    if not re.fullmatch(r'[0-9]+', value):
        raise ValueError(f'Unexpected AHRF count code: {value[:30]!r}')
    number = int(value)
    if number > 100_000_000:
        raise ValueError('AHRF count exceeds bounded plausible range')
    return number, 'true_zero' if number == 0 else 'available', None


def safe_members(archive):
    total = 0
    names = set()
    for info in archive.infolist():
        name = PurePosixPath(info.filename)
        if (name.is_absolute() or '..' in name.parts or '\\' in info.filename or
                info.file_size > MAX_MEMBER or info.flag_bits & 1 or info.filename in names or
                ((info.external_attr >> 16) & 0o170000) == 0o120000):
            raise ValueError('Unsafe AHRF ZIP member')
        names.add(info.filename)
        total += info.file_size
        if total > MAX_EXTRACTED:
            raise ValueError('AHRF ZIP expands beyond limit')
    return archive.infolist()


def archive_member(archive, suffix):
    matches = [i for i in safe_members(archive) if i.filename.endswith('/' + suffix)]
    if len(matches) != 1:
        raise ValueError(f'AHRF archive must contain exactly one {suffix}')
    return matches[0]


def select_member(archive, suffix, directory):
    info = archive_member(archive, suffix)
    target = directory / suffix
    with archive.open(info) as source, target.open('wb') as dest:
        shutil.copyfileobj(source, dest, 1024 * 1024)
    if target.stat().st_size != info.file_size:
        raise ValueError('Incomplete AHRF extraction')
    return target


def selected_dictionary(archive, config):
    crosswalk = archive_member(archive, 'AHRFCrosswalk2025.xlsx')
    technical = archive_member(archive, 'AHRF 2024-2025 Technical Documentation.xlsx')
    with archive.open(crosswalk) as source:
        workbook = openpyxl.load_workbook(io.BytesIO(source.read()), read_only=True, data_only=True)
    indexed = {str(row[1]).strip(): row for row in list(workbook.active.values)[1:] if row[1]}
    with archive.open(technical) as source:
        workbook = openpyxl.load_workbook(io.BytesIO(source.read()), read_only=True, data_only=True)
    tech = {str(row[0]).strip(): row for row in workbook.active.values if row[0]}
    result = {}
    for measure in config['measures']:
        key = measure['measure_id']
        if key not in indexed or key not in tech:
            raise ValueError(f'AHRF dictionary lacks {key}')
        cross, detail = indexed[key], tech[key]
        label, characteristics, source = (str(detail[i] or '').strip() for i in (3, 4, 5))
        expected = (measure['official_label'], measure['characteristics'], measure['source'])
        if (label, characteristics, source) != expected or int(detail[2]) != int(measure['observation_period']):
            raise ValueError(f'AHRF selected definition changed: {key}')
        if str(cross[2]).strip() != label or str(cross[3] or '').strip() != characteristics:
            raise ValueError(f'AHRF crosswalk definition changed: {key}')
        result[key] = {'field_number': cross[0], 'label': label, 'characteristics': characteristics,
                       'year': int(detail[2]), 'original_source': source, 'category': str(detail[1]).strip()}
    return result


def parse_selected_files(paths, config):
    records = {}
    expected = {name: [m['measure_id'] for m in config['measures'] if m['source_file'] == name]
                for name in ZIP_FILES}
    keysets = []
    headers = {}
    for filename in ZIP_FILES:
        with paths[filename].open(newline='', encoding='utf-8-sig') as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError('AHRF CSV has duplicate or absent header')
            fields = ['fips_st_cnty', *expected[filename]]
            if any(field not in reader.fieldnames for field in fields):
                raise ValueError(f'AHRF CSV lacks selected fields in {filename}')
            headers[filename] = fields
            seen = set()
            for row in reader:
                geoid = row['fips_st_cnty']
                if not re.fullmatch(r'[0-9]{5}', geoid) or geoid in seen:
                    raise ValueError(f'Invalid or duplicate AHRF county FIPS: {geoid!r}')
                seen.add(geoid)
                if filename == ZIP_FILES[0]:
                    records[geoid] = {'fips_st_cnty': geoid}
                for field in expected[filename]:
                    parse_count(row[field])
                    records.setdefault(geoid, {'fips_st_cnty': geoid})[field] = row[field].strip()
                if len(seen) > MAX_ROWS:
                    raise ValueError('AHRF row limit exceeded')
            keysets.append(seen)
    if keysets[0] != keysets[1] or len(keysets[0]) != config['expected_source_rows']:
        raise ValueError('AHRF selected file coverage changed')
    return records, headers


def download(url, target):
    if shutil.disk_usage(target.parent).free < 6 * 1024**3:
        raise RuntimeError('Insufficient free disk for AHRF archive')
    temporary = target.with_suffix(target.suffix + '.part')
    last = None
    for attempt in range(3):
        try:
            size = 0
            with requests.get(url, stream=True, timeout=(10, 90), allow_redirects=True) as response:
                response.raise_for_status()
                with temporary.open('wb') as output:
                    for chunk in response.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_ARCHIVE:
                            raise ValueError('AHRF archive exceeds download limit')
                        output.write(chunk)
            os.replace(temporary, target)
            return
        except (requests.RequestException, OSError) as exc:
            last = exc
            temporary.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError('AHRF download failed after bounded retries') from last


def file_evidence(path, url, role):
    sha = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            sha.update(block)
    return {'role': role, 'path': str(path.resolve()), 'url': url,
            'sha256': sha.hexdigest(), 'byte_count': path.stat().st_size,
            'retrieved_at': datetime.now(timezone.utc)}


def retrieve(config, directory):
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    catalog_url = 'https://data.hrsa.gov/data/download?data=AHRF'
    catalog_path = directory / 'hrsa_ahrf_download_catalog.html'
    last = None
    for attempt in range(3):
        try:
            response = requests.get(catalog_url, timeout=(10, 30))
            response.raise_for_status()
            if len(response.content) > 2 * 1024**2:
                raise ValueError('HRSA catalog response exceeds limit')
            catalog_path.write_bytes(response.content)
            break
        except requests.RequestException as exc:
            last = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    if not catalog_path.is_file():
        raise RuntimeError('HRSA release catalog unavailable') from last
    files.append(file_evidence(catalog_path, catalog_url, 'release_catalog'))
    releases = re.findall(r'AHRF_(20\d\d-20\d\d)_CSV\.zip', catalog_path.read_text())
    if not releases or max(releases) != '2024-2025':
        raise ValueError('AHRF latest county release differs from pinned 2024-2025 release')
    paths_by_role = {}
    for role, key in [('county_csv_zip', 'source_data_url'), ('technical_documentation_zip', 'source_documentation_url')]:
        url = config[key]
        target = directory / url.rsplit('/', 1)[-1]
        download(url, target)
        paths_by_role[role] = target
        files.append(file_evidence(target, url, role))
    documentation_evidence = next(item for item in files if item['role'] == 'technical_documentation_zip')
    with zipfile.ZipFile(paths_by_role['technical_documentation_zip']) as documentation:
        dictionary = selected_dictionary(documentation, config)
        if documentation_evidence['sha256'] != config['documentation_sha256']:
            raise ValueError('AHRF technical documentation ZIP changed; review and update registry')
    with zipfile.ZipFile(paths_by_role['county_csv_zip']) as archive:
        paths = {name: select_member(archive, name, directory) for name in ZIP_FILES}
        for name, path in paths.items():
            files.append(file_evidence(path, config['source_data_url'] + '#' + name, name))
    records, headers = parse_selected_files(paths, config)
    return records, dictionary, headers, files


def semantic_sha(records):
    return digest([(geoid, records[geoid]) for geoid in sorted(records)])
