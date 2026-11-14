"""Selective, bounded-memory reader for AHRQ CLH v2.0 XLSX files."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import requests

from app.area_pilot.source import digest

REGISTRY = Path(__file__).with_name('registry') / 'clh_2023.json'
MAX_BYTES = {'landing': 2_000_000, 'codebook': 2_000_000, 'documentation': 12_000_000,
             'county': 20_000_000, 'tract': 180_000_000}
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122 Safari/537.36'


def load_registry():
    config = json.loads(REGISTRY.read_text())
    if (len(config['measures']) != 5 or config['geographies'] != ['county', 'tract'] or
            config['refresh_policy']['auto_publish'] or config['aggregation_method'] != 'none'):
        raise ValueError('CLH registry contract changed')
    if len({m['measure_id'] for m in config['measures']}) != 5:
        raise ValueError('Duplicate CLH measures')
    return config


def file_evidence(path, url, role):
    sha = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            sha.update(block)
    return {'role': role, 'path': str(path.resolve()), 'url': url,
            'sha256': sha.hexdigest(), 'byte_count': path.stat().st_size,
            'retrieved_at': datetime.now(timezone.utc)}


def download(url, target, role):
    if shutil.disk_usage(target.parent).free < 4 * 1024**3:
        raise RuntimeError('Insufficient disk headroom for CLH XLSX')
    temporary = target.with_suffix(target.suffix + '.part')
    for attempt in range(3):
        try:
            size = 0
            with requests.get(url, headers={'User-Agent': USER_AGENT,
                    'Referer': 'https://www.ahrq.gov/data/innovations/clh-data.html'},
                    stream=role != 'landing', timeout=(15, 120)) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise requests.RequestException(f'Incomplete CLH {role} response status')
                with temporary.open('wb') as handle:
                    blocks = [response.content] if role == 'landing' else response.iter_content(1024 * 1024)
                    for block in blocks:
                        size += len(block)
                        if size > MAX_BYTES[role]:
                            raise ValueError('CLH download exceeds role size limit')
                        handle.write(block)
            if size < (1000 if role == 'landing' else 100_000):
                raise requests.RequestException(f'Incomplete CLH {role} response')
            os.replace(temporary, target)
            return
        except (requests.RequestException, OSError):
            temporary.unlink(missing_ok=True)
            if attempt == 2:
                raise RuntimeError(f'CLH {role} download failed') from None
            time.sleep(2 ** attempt)


def retrieve(config, directory):
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    for role, url in config['source_urls'].items():
        path = directory / url.rsplit('/', 1)[-1]
        download(url, path, role)
        files.append(file_evidence(path, url, role))
        if role == 'landing':
            page = path.read_text(errors='replace')
            if ('September 2025' not in page or
                    'clh_2023_county_2_0.xlsx' not in page or
                    'clh_2023_tract_2_0.xlsx' not in page or
                    re.search(r'clh_202[4-9]_(?:county|tract)', page, re.I)):
                raise ValueError('AHRQ CLH release landing page differs from pinned September 2025 v2.0')
    return files


def verify_codebook(path, config):
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        expected = {'county': 'County', 'tract': 'Tract'}
        for level, sheet in expected.items():
            rows = workbook[sheet].iter_rows(values_only=True)
            header = next(rows)
            if header[:5] != ('Domain', 'Topic', 'Variable Name', 'Variable Label', 'Data Source'):
                raise ValueError(f'CLH {sheet} codebook headers changed')
            definitions = {row[2]: row for row in rows if row[2]}
            for measure in config['measures']:
                if level not in measure['geographies']:
                    if measure['measure_id'] in definitions:
                        raise ValueError(f'{measure["measure_id"]} unexpectedly documented at {level}')
                    continue
                row = definitions.get(measure['measure_id'])
                if not row or (row[3], row[4], row[5]) != (
                        measure['official_label'], 'ACS' if measure['measure_id'].startswith('ACS_') else 'CCBP', 'num'):
                    raise ValueError(f'CLH {sheet} definition changed: {measure["measure_id"]}')
        summary = {}
        for level, sheet in [('county', 'County Summary'), ('tract', 'Tract Summary')]:
            rows = list(workbook[sheet].iter_rows(values_only=True, max_row=800))
            summary[level] = {row[0]: {'nonmissing': row[3], 'missing': row[4],
                'minimum': row[5], 'maximum': row[6]} for row in rows[1:] if row[0]}
        return summary
    finally:
        workbook.close()


def parse_value(raw, unit):
    if raw is None or raw == '':
        return None, 'missing', None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f'Invalid CLH numeric cell: {str(raw)[:32]!r}')
    value = float(raw)
    if not (0 <= value <= (100 if unit == '%' else 1000)):
        raise ValueError(f'CLH value out of range: {value}')
    return value, 'true_zero' if value == 0 else 'available', None


def parse_file(path, level, config):
    """Read only the published Data rows and selected cells; never load an XLSX sheet into memory."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        if workbook.sheetnames != ['Layout', 'Data']:
            raise ValueError(f'CLH {level} workbook worksheets changed')
        expected = [m for m in config['measures'] if level in m['geographies']]
        id_field = 'COUNTYFIPS' if level == 'county' else 'TRACTFIPS'
        layout = {row[0]: row for row in workbook['Layout'].iter_rows(min_row=2,
                  max_row=700, values_only=True) if row[0]}
        for measure in expected:
            row = layout.get(measure['measure_id'])
            if not row or row[1] != measure['official_label'] or row[2] != 'num':
                raise ValueError(f'CLH {level} layout changed: {measure["measure_id"]}')
        data = workbook['Data']
        headers = [cell.value for cell in next(data.iter_rows(min_row=1, max_row=1))]
        if len(headers) != len(set(headers)) or 'YEAR' not in headers or id_field not in headers:
            raise ValueError(f'CLH {level} Data headers invalid')
        positions = {name: headers.index(name) for name in ['YEAR', id_field,
                     *(['COUNTYFIPS'] if level == 'tract' else []),
                     *(m['measure_id'] for m in expected)]}
        records = {}
        max_row = config['expected_source_rows'][level] + 1
        for row in data.iter_rows(min_row=2, max_row=max_row):
            year = row[positions['YEAR']]
            geoid_cell = row[positions[id_field]]
            geoid = geoid_cell.value
            if year.data_type == 'f' or year.value != 2023 or geoid_cell.data_type != 's' or not isinstance(geoid, str) or not re.fullmatch(r'\d{5}' if level == 'county' else r'\d{11}', geoid):
                raise ValueError(f'Invalid CLH {level} year or GEOID: {geoid!r}')
            if geoid in records:
                raise ValueError(f'Duplicate CLH {level} GEOID: {geoid}')
            if level == 'tract' and row[positions['COUNTYFIPS']].value != geoid[:5]:
                raise ValueError(f'CLH tract parent county mismatch: {geoid}')
            values = {}
            for measure in expected:
                cell = row[positions[measure['measure_id']]]
                if cell.data_type == 'f':
                    raise ValueError(f'Formula in CLH {level} selected cell: {geoid}')
                parse_value(cell.value, measure['unit'])
                values[measure['measure_id']] = cell.value
            records[geoid] = values
        if len(records) != config['expected_source_rows'][level]:
            raise ValueError(f'CLH {level} source row count changed: {len(records)}')
        return records, {'sheet': 'Data', 'headers': list(positions),
                         'positions': positions, 'source_rows': len(records)}
    finally:
        workbook.close()


def semantic_sha(records):
    return digest([(level, geoid, records[level][geoid])
                   for level in sorted(records) for geoid in sorted(records[level])])
