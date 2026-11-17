"""Tests for the EPA AirData annual AQI-by-county history parser."""
from __future__ import annotations

import copy
import csv
import io
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.area_pilot.history.parsers import epa_aqi as epa_aqi_parser
from app.area_pilot.history.parsers import load_parser
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.history.rows import part_digest, row_problems

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures' / 'history' / 'epa_aqi'
DECLARED_YEARS = ('2021', '2024')
MEASURES = ('median_aqi', 'p90_aqi', 'max_aqi', 'days_with_aqi', 'good_days')


@pytest.fixture
def config():
    base = copy.deepcopy(load_history_registry('epa_aqi'))
    keep_roles = {'county_zip_2021', 'county_zip_2024', 'site_listing_zip', 'tiger_county_2020', 'tiger_state_2024'}
    base['sources'] = [s for s in base['sources'] if s['role'] in keep_roles]
    for measure in base['measures']:
        measure['periods'] = [p for p in measure['periods'] if p['period'] in DECLARED_YEARS]
    base['_index'] = {
        (m['measure_id'], p['period']): (m, p)
        for m in base['measures']
        for p in m['periods']
    }
    return base


@pytest.fixture
def files():
    return {
        'county_zip_2021': FIXTURE_DIR / 'annual_aqi_by_county_2021.zip',
        'county_zip_2024': FIXTURE_DIR / 'annual_aqi_by_county_2024.zip',
        'site_listing_zip': FIXTURE_DIR / 'aqs_sites.zip',
        'tiger_county_2020': FIXTURE_DIR / 'tl_2020_us_county_attrs.zip',
        'tiger_state_2024': FIXTURE_DIR / 'tl_2024_us_state_attrs.zip',
    }


def _rewrite_zip_csv(src_zip: Path, dst_zip: Path, member_name: str, transform_fn) -> None:
    with zipfile.ZipFile(src_zip) as archive:
        orig_member = archive.namelist()[0]
        text = archive.read(orig_member).decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = list(reader.fieldnames or [])
    rows = [ dict(r) for r in reader ]
    fieldnames, rows = transform_fn(fieldnames, rows)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    with zipfile.ZipFile(dst_zip, 'w', compression=zipfile.ZIP_DEFLATED) as out_zf:
        out_zf.writestr(member_name, buf.getvalue().encode('utf-8'))


def test_contract_and_parts_stability(config, files):
    module = load_parser('epa_aqi')
    assert module is epa_aqi_parser
    assert module.SCHEMA_VERSION == '1'

    ev1, ev2 = {}, {}
    parts1 = list(module.parse(config, files, ev1))
    parts2 = list(module.parse(config, files, ev2))

    names1 = [name for name, _ in parts1]
    assert names1 == ['year_2021', 'year_2024']
    assert len(names1) == len(set(names1))
    assert parts1 == parts2
    assert ev1 == ev2
    for (_, rows1), (_, rows2) in zip(parts1, parts2):
        assert part_digest(rows1) == part_digest(rows2)


def test_exact_counts_ct_09001_exclusions_and_row_problems(config, files):
    evidence = {}
    parts = dict(epa_aqi_parser.parse(config, files, evidence))

    assert set(parts) == {'year_2021', 'year_2024'}
    assert len(parts['year_2021']) == 5005  # 1,001 counties * 5 measures
    assert len(parts['year_2024']) == 4975  # 995 counties * 5 measures
    assert evidence['source_row_counts'] == {'2021': 1005, '2024': 997}
    assert evidence['kept_counties_by_year'] == {'2021': 1001, '2024': 995}
    assert evidence['excluded_rows'] == {
        '2021': {
            'non_us_jurisdiction': 2,
            'territory_outside_chip_2024_boundary_layer': 2,
        },
        '2024': {
            'non_us_jurisdiction': 1,
            'territory_outside_chip_2024_boundary_layer': 1,
        },
    }

    counts = Counter()
    geoids_by_year = {'2021': set(), '2024': set()}
    for rows in parts.values():
        for row in rows:
            assert row_problems(row, config) == []
            assert row.level == 'county'
            assert row.boundary_vintage == '2020'
            counts[(row.measure_id, row.period, row.level)] += 1
            geoids_by_year[row.period].add(row.geoid)

    for measure_id in MEASURES:
        assert counts[(measure_id, '2021', 'county')] == 1001
        assert counts[(measure_id, '2024', 'county')] == 995

    # Connecticut's 09001 (Fairfield) appears in both 2021 and 2024
    assert '09001' in geoids_by_year['2021']
    assert '09001' in geoids_by_year['2024']

    # Sonora / Mexico (80xxx) and USVI (78xxx) rows are dropped and never emitted
    for yr in DECLARED_YEARS:
        assert all(not g.startswith(('78', '80')) for g in geoids_by_year[yr])


def test_hand_checked_values_and_true_zero(config, files, tmp_path):
    parts = dict(epa_aqi_parser.parse(config, files, {}))
    by_key = {row.key: row for rows in parts.values() for row in rows}

    # 1. Connecticut Fairfield (09001) in 2021 and 2024
    r_ct_2021 = by_key[('county', '09001', 'median_aqi', '2021')]
    assert r_ct_2021.value == Decimal('46')
    assert r_ct_2021.status == 'available'
    assert r_ct_2021.source_value == '46'
    assert by_key[('county', '09001', 'p90_aqi', '2021')].value == Decimal('74')
    assert by_key[('county', '09001', 'max_aqi', '2021')].value == Decimal('185')
    assert by_key[('county', '09001', 'days_with_aqi', '2021')].value == Decimal('363')
    assert by_key[('county', '09001', 'good_days', '2021')].value == Decimal('225')

    r_ct_2024 = by_key[('county', '09001', 'median_aqi', '2024')]
    assert r_ct_2024.value == Decimal('42')
    assert r_ct_2024.status == 'available'
    assert r_ct_2024.source_value == '42'
    assert by_key[('county', '09001', 'days_with_aqi', '2024')].value == Decimal('366')

    # 2. Alabama Baldwin (01003) in 2021 and 2024
    r_al_2021 = by_key[('county', '01003', 'median_aqi', '2021')]
    assert r_al_2021.value == Decimal('37')
    assert r_al_2021.status == 'available'
    assert r_al_2021.source_value == '37'

    r_al_2024 = by_key[('county', '01003', 'median_aqi', '2024')]
    assert r_al_2024.value == Decimal('40')
    assert r_al_2024.status == 'available'
    assert r_al_2024.source_value == '40'

    # 3. A zero cell (e.g. Good Days = 0 when all days are Moderate) produces status='true_zero'
    def set_zero_good_days(fieldnames, rows):
        for r in rows:
            if r['State'] == 'Alabama' and r['County'] == 'Baldwin':
                r['Good Days'] = '0'
                r['Moderate Days'] = r['Days with AQI']
                r['Median AQI'] = '55'
                r['90th Percentile AQI'] = '60'
                r['Max AQI'] = '90'
        return fieldnames, rows

    z2024 = tmp_path / 'annual_aqi_by_county_2024_zero.zip'
    _rewrite_zip_csv(files['county_zip_2024'], z2024, 'annual_aqi_by_county_2024.csv', set_zero_good_days)
    parts_z = dict(epa_aqi_parser.parse(config, {**files, 'county_zip_2024': z2024}, {}))
    by_key_z = {row.key: row for rows in parts_z.values() for row in rows}
    r_zero = by_key_z[('county', '01003', 'good_days', '2024')]
    assert r_zero.value == Decimal('0')
    assert r_zero.status == 'true_zero'
    assert r_zero.source_value == '0'
    assert row_problems(r_zero, config) == []


def test_missing_or_renamed_member_changed_header_and_unmapped_county_raise(config, files, tmp_path):
    # 1. Renamed member inside county ZIP raises ValueError
    renamed_zip = tmp_path / 'renamed_member.zip'
    _rewrite_zip_csv(
        files['county_zip_2024'],
        renamed_zip,
        'wrong_name_2024.csv',
        lambda fieldnames, rows: (fieldnames, rows),
    )
    with pytest.raises(ValueError, match='expected CSV member'):
        list(epa_aqi_parser.parse(config, {**files, 'county_zip_2024': renamed_zip}, {}))

    # 2. Empty ZIP (missing member) raises ValueError
    empty_zip = tmp_path / 'empty.zip'
    with zipfile.ZipFile(empty_zip, 'w'):
        pass
    with pytest.raises(ValueError, match='expected CSV member'):
        list(epa_aqi_parser.parse(config, {**files, 'county_zip_2024': empty_zip}, {}))

    # 3. Changed CSV header raises ValueError
    bad_hdr_zip = tmp_path / 'bad_header.zip'
    _rewrite_zip_csv(
        files['county_zip_2024'],
        bad_hdr_zip,
        'annual_aqi_by_county_2024.csv',
        lambda fieldnames, rows: (
            ['Median_AQI_Renamed' if f == 'Median AQI' else f for f in fieldnames],
            [{('Median_AQI_Renamed' if k == 'Median AQI' else k): v for k, v in r.items()} for r in rows],
        ),
    )
    with pytest.raises(ValueError, match='CSV header'):
        list(epa_aqi_parser.parse(config, {**files, 'county_zip_2024': bad_hdr_zip}, {}))

    # 4. Unmapped county name not on the exclusion list raises ValueError naming (State, County) and method
    unmapped_zip = tmp_path / 'unmapped.zip'

    def add_unmapped(fieldnames, rows):
        bad = dict(rows[0], State='Alabama', County='Unmapped Fictional County')
        return fieldnames, rows + [bad]

    _rewrite_zip_csv(files['county_zip_2024'], unmapped_zip, 'annual_aqi_by_county_2024.csv', add_unmapped)
    with pytest.raises(ValueError, match=r"Unmapped EPA AQI counties in 2024: \('Alabama', 'Unmapped Fictional County'\): method='no_epa_code'"):
        list(epa_aqi_parser.parse(config, {**files, 'county_zip_2024': unmapped_zip}, {}))
