"""EPA AirData annual AQI-by-county history parser (years 2020-2024)."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import re
import struct
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

from app.area_pilot.epa_aqi import (
    extract_member,
    load_registry,
    map_counties,
    observation_values,
    parse_site_listing,
    safe_member,
    validate_row,
)
from app.area_pilot.history.rows import HistoryRow, make_row, row_problems, to_decimal

SCHEMA_VERSION = '1'
COUNTY_DBF_REQUIRED = {'GEOID', 'STATEFP', 'NAME', 'NAMELSAD', 'LSAD'}
STATE_DBF_REQUIRED = {'STATEFP', 'NAME'}


def _header_sha(header: list[str]) -> str:
    return hashlib.sha256('|'.join(header).encode('utf-8')).hexdigest()


def _read_dbf_attributes_from_zip(zip_path: Path, required_fields: set[str], role: str) -> list[dict[str, str]]:
    """Read shapefile .dbf attribute rows in memory from a TIGER ZIP archive."""
    with zipfile.ZipFile(zip_path) as archive:
        dbf_names = [n for n in archive.namelist() if n.lower().endswith('.dbf')]
        if len(dbf_names) != 1:
            raise ValueError(f'Expected exactly one .dbf member in {role} ({zip_path.name}), got {dbf_names}')
        cpg_names = [n for n in archive.namelist() if n.lower().endswith('.cpg')]
        encoding = 'utf-8'
        if cpg_names:
            cpg = archive.read(cpg_names[0]).decode('ascii', errors='ignore').strip()
            if cpg:
                encoding = cpg
        data = archive.read(dbf_names[0])

    if len(data) < 32:
        raise ValueError(f'Malformed .dbf header in {role}')
    num_records, header_len, record_len = struct.unpack('<4xIHH20x', data[:32])
    fields: list[tuple[str, int]] = []
    pos = 32
    while pos < header_len - 1 and data[pos] != 0x0D:
        raw_name = data[pos:pos + 11].split(b'\x00', 1)[0].decode('ascii', errors='replace')
        field_len = data[pos + 16]
        fields.append((raw_name, field_len))
        pos += 32

    field_names = {name for name, _ in fields}
    missing = sorted(required_fields - field_names)
    if missing:
        raise ValueError(f'TIGER {role} .dbf is missing required fields: {missing}')

    rows: list[dict[str, str]] = []
    offset = header_len
    for _ in range(num_records):
        rec = data[offset:offset + record_len]
        offset += record_len
        if not rec or rec[0] == 0x2A:
            continue
        fpos = 1
        row: dict[str, str] = {}
        for name, flen in fields:
            row[name] = rec[fpos:fpos + flen].decode(encoding).strip()
            fpos += flen
        rows.append(row)
    if not rows:
        raise ValueError(f'TIGER {role} .dbf contained no attribute records')
    return rows


def _load_tiger_lookups(county_zip: Path, state_zip: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Build TIGER 2020 county and TIGER 2024 state lookups in memory."""
    county_rows = _read_dbf_attributes_from_zip(county_zip, COUNTY_DBF_REQUIRED, 'tiger_county_2020')
    state_rows = _read_dbf_attributes_from_zip(state_zip, STATE_DBF_REQUIRED, 'tiger_state_2024')
    counties = [
        {
            'geoid': str(r['GEOID']),
            'statefp': str(r['STATEFP']),
            'name': str(r['NAME']),
            'namelsad': str(r['NAMELSAD']),
            'lsad': str(r['LSAD']),
        }
        for r in county_rows
    ]
    states = {str(r['STATEFP']): str(r['NAME']) for r in state_rows}
    return counties, states


def _build_adapter_config_and_plan(
    config: dict,
) -> tuple[dict, dict[str, str], dict[str, list[tuple[dict, dict, str]]]]:
    if '_index' not in config:
        config['_index'] = {
            (m['measure_id'], p['period']): (m, p)
            for m in config.get('measures', [])
            for p in m.get('periods', [])
        }
    selection = config.get('selection') or {}
    for key in ('expected_header', 'reviewed_state_variants', 'reviewed_name_variants', 'independent_city_lsad'):
        if key not in selection:
            raise ValueError(f'EPA AQI history registry is missing selection.{key}')

    current_registry = load_registry()
    adapter_config = copy.deepcopy(current_registry)
    adapter_config['expected_header'] = list(selection['expected_header'])
    adapter_config['reviewed_state_variants'] = copy.deepcopy(selection['reviewed_state_variants'])
    adapter_config['reviewed_name_variants'] = copy.deepcopy(selection['reviewed_name_variants'])
    adapter_config['boundary'] = dict(
        adapter_config['boundary'],
        independent_city_lsad=selection['independent_city_lsad'],
    )
    if 'site_listing_member' in selection:
        adapter_config['site_listing_member'] = selection['site_listing_member']
    if 'site_listing_fields' in selection:
        adapter_config['site_listing_fields'] = list(selection['site_listing_fields'])

    current_measures = {m['measure_id']: m for m in current_registry['measures']}
    expected_members_by_year: dict[str, str] = {}
    declared_by_year: dict[str, list[tuple[dict, dict, str]]] = defaultdict(list)

    for measure in config.get('measures', []):
        mid = measure.get('measure_id')
        if mid not in current_measures:
            raise ValueError(f'EPA AQI history measure {mid!r} is not in the current EPA AQI registry')
        current_measure = current_measures[mid]
        allowed_levels = measure.get('levels', config.get('levels', []))
        if allowed_levels != ['county']:
            raise ValueError(f'EPA AQI history measure {mid} must declare county level only, got {allowed_levels!r}')

        for spec in measure.get('periods', []):
            if not spec.get('available', True):
                continue
            period = str(spec.get('period', ''))
            locator = spec.get('locator') or {}
            loc_year = str(locator.get('year', ''))
            member = locator.get('member')
            source_field = locator.get('source_field')
            if not re.fullmatch(r'[0-9]{4}', period) or loc_year != period or not member or not source_field:
                raise ValueError(f'EPA AQI measure {mid} period {period!r} has invalid locator: {locator!r}')
            if source_field != current_measure['source_field']:
                raise ValueError(
                    f'EPA AQI measure {mid} period {period} source_field {source_field!r} '
                    f'differs from current registry {current_measure["source_field"]!r}'
                )
            if period in expected_members_by_year and expected_members_by_year[period] != member:
                raise ValueError(
                    f'EPA AQI period {period} declares conflicting ZIP members: '
                    f'{expected_members_by_year[period]!r} vs {member!r}'
                )
            expected_members_by_year[period] = member
            declared_by_year[period].append((measure, spec, source_field))

    if not declared_by_year:
        raise ValueError('EPA AQI history registry declares no available periods')
    return adapter_config, expected_members_by_year, dict(declared_by_year)


def _exclusion_reason(
    state: str,
    county: str,
    epa_code: str | None,
    exclusions: list[dict],
) -> str | None:
    for item in exclusions:
        if item.get('state') == state and item.get('county') == county:
            if 'epa_code' in item and epa_code is not None and item['epa_code'] != epa_code:
                raise ValueError(
                    f'EPA AQI exclusion ({state!r}, {county!r}) expected epa_code {item["epa_code"]!r}, got {epa_code!r}'
                )
            return item['reason']
    # Also match state-level non-US / excluded territory jurisdictions (Mexico 80xxx, USVI 78xxx)
    # when the state is listed in selection.exclusions and aqs_sites.csv confirms its prefix.
    if epa_code and len(epa_code) == 5 and epa_code[:2] in ('78', '80'):
        for item in exclusions:
            if item.get('state') == state:
                return item['reason']
    return None


def _read_county_zip_records(zip_path: Path, expected_member: str, adapter_config: dict, year: int) -> dict[tuple[str, str], dict]:
    with zipfile.ZipFile(zip_path) as archive:
        info = safe_member(archive, expected_member)
        raw_text = archive.read(info).decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(raw_text))
    if reader.fieldnames != adapter_config['expected_header']:
        raise ValueError(
            f'EPA AQI CSV header in {expected_member} {reader.fieldnames!r} '
            f'differs from expected {adapter_config["expected_header"]!r}'
        )
    records: dict[tuple[str, str], dict] = {}
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f'EPA AQI CSV {expected_member} row has an unexpected column count')
        key = (row['State'], row['County'])
        if key in records:
            raise ValueError(f'Duplicate EPA state/county key in {year}: {key}')
        validate_row(row, adapter_config, year)
        records[key] = dict(row)
    if not records:
        raise ValueError(f'EPA AQI CSV {expected_member} has no rows')
    return records


def parse(config: dict, files: dict[str, Path], evidence: dict) -> Iterator[tuple[str, list[HistoryRow]]]:
    """Parse archived EPA AirData annual county AQI ZIPs into per-year HistoryRow parts."""
    adapter_config, expected_members_by_year, declared_by_year = _build_adapter_config_and_plan(config)
    selection = config['selection']
    exclusions = selection.get('exclusions', [])
    site_member = adapter_config.get('site_listing_member', 'aqs_sites.csv')

    required_roles = ['site_listing_zip', 'tiger_county_2020', 'tiger_state_2024'] + [
        f'county_zip_{yr}' for yr in sorted(declared_by_year)
    ]
    for role in required_roles:
        if role not in files:
            raise ValueError(f'Missing required source file role {role!r}')

    counties, states = _load_tiger_lookups(
        Path(files['tiger_county_2020']),
        Path(files['tiger_state_2024']),
    )

    records_by_year: dict[str, dict[tuple[str, str], dict]] = {}
    all_wanted: set[tuple[str, str]] = set()
    for year in sorted(declared_by_year):
        role = f'county_zip_{year}'
        records = _read_county_zip_records(
            Path(files[role]),
            expected_members_by_year[year],
            adapter_config,
            int(year),
        )
        records_by_year[year] = records
        all_wanted.update(records)

    with tempfile.TemporaryDirectory() as tmp_dir:
        site_csv_path = extract_member(Path(files['site_listing_zip']), site_member, Path(tmp_dir))
        site_codes = parse_site_listing(site_csv_path, adapter_config, all_wanted)

    source_row_counts: dict[str, int] = {}
    kept_counties_by_year: dict[str, int] = {}
    excluded_rows: dict[str, Counter[str]] = defaultdict(Counter)
    excluded_details: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    mapping_methods: dict[str, Counter[str]] = defaultdict(Counter)
    rows_by_year: dict[str, list[HistoryRow]] = {yr: [] for yr in declared_by_year}

    for year in sorted(declared_by_year):
        records = records_by_year[year]
        source_row_counts[year] = len(records)
        mapped, _unused = map_counties(records, site_codes, counties, states, adapter_config)

        unmapped_errors: list[str] = []
        seen_geoids: set[str] = set()
        for key in sorted(records):
            state, county = key
            info = mapped[key]
            reason = _exclusion_reason(state, county, info.get('epa_code'), exclusions)
            if reason is not None:
                excluded_rows[year][reason] += 1
                excluded_details[year].append({
                    'state': state,
                    'county': county,
                    'epa_code': info.get('epa_code'),
                    'reason': reason,
                })
                continue

            geoid = info.get('geoid')
            if not geoid:
                unmapped_errors.append(f'({state!r}, {county!r}): method={info.get("method")!r}')
                continue

            if geoid in seen_geoids:
                raise ValueError(f'Duplicate EPA AQI county GEOID {geoid} in {year}')
            seen_geoids.add(geoid)
            mapping_methods[year][info['method']] += 1

            record = records[key]
            obs_by_measure = {
                item['measure']['measure_id']: item for item in observation_values(record, adapter_config)
            }
            for measure, _spec, source_field in declared_by_year[year]:
                mid = measure['measure_id']
                obs = obs_by_measure[mid]
                raw = record[source_field].strip()
                val = to_decimal(raw)
                row = make_row(
                    config,
                    mid,
                    year,
                    'county',
                    geoid,
                    value=val,
                    status=obs['status'],
                    source_value=raw,
                )
                problems = row_problems(row, config)
                if problems:
                    raise ValueError(f'EPA AQI row {row.key} failed row contract: {problems}')
                rows_by_year[year].append(row)

        if unmapped_errors:
            raise ValueError(
                f'Unmapped EPA AQI counties in {year}: ' + '; '.join(unmapped_errors)
            )
        kept_counties_by_year[year] = len(seen_geoids)

    evidence.clear()
    evidence.update({
        'header_sha256': _header_sha(adapter_config['expected_header']),
        'column_count': len(adapter_config['expected_header']),
        'tiger_county_2020_count': len(counties),
        'tiger_state_2024_count': len(states),
        'source_row_counts': source_row_counts,
        'kept_counties_by_year': kept_counties_by_year,
        'mapping_methods': {
            yr: dict(sorted(counts.items())) for yr, counts in sorted(mapping_methods.items())
        },
        'excluded_rows': {
            yr: dict(sorted(counts.items())) for yr, counts in sorted(excluded_rows.items())
        },
        'excluded_details': dict(sorted(excluded_details.items())),
        'emitted_rows': {yr: len(rows_by_year[yr]) for yr in sorted(rows_by_year)},
    })

    for year in sorted(rows_by_year):
        yield f'year_{year}', sorted(rows_by_year[year], key=lambda r: r.key)
