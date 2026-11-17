"""Tests for the CDC PLACES county and tract history parser."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.area_pilot.history.parsers import load_parser
from app.area_pilot.history.parsers import places as places_parser
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.history.rows import part_digest, row_problems

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures' / 'history' / 'places'
RELEASES = ('2020', '2021', '2022', '2023', '2024')


@pytest.fixture
def config():
    return load_history_registry('places')


@pytest.fixture
def files():
    return {
        f'places{rel}_{lvl}': FIXTURE_DIR / f'places{rel}_{lvl}.csv'
        for rel in RELEASES
        for lvl in ('county', 'tract')
    }


def test_contract_and_parts_stability(config, files):
    module = load_parser('places')
    assert module is places_parser
    assert module.SCHEMA_VERSION == '1'

    ev1, ev2 = {}, {}
    parts1 = list(module.parse(config, files, ev1))
    parts2 = list(module.parse(config, files, ev2))

    names1 = [name for name, _ in parts1]
    assert names1 == [
        'r2020_county',
        'r2020_tract',
        'r2021_county',
        'r2021_tract',
        'r2022_county',
        'r2022_tract',
        'r2023_county',
        'r2023_tract',
        'r2024_county',
        'r2024_tract',
    ]
    assert len(names1) == len(set(names1))
    assert parts1 == parts2
    assert ev1 == ev2
    for (_, rows1), (_, rows2) in zip(parts1, parts2):
        assert part_digest(rows1) == part_digest(rows2)


def test_exact_counts_per_measure_period_level_and_row_problems(config, files):
    evidence = {}
    parts = dict(places_parser.parse(config, files, evidence))

    expected_part_counts = {
        'r2020_county': 121,     # 11 counties (8 CT + 3 DE) * 11 measures
        'r2020_tract': 11462,    # 1042 tracts * 11 measures
        'r2021_county': 132,     # 11 counties * 12 measures
        'r2021_tract': 12504,    # 1042 tracts * 12 measures
        'r2022_county': 132,     # 11 counties * 12 measures
        'r2022_tract': 12504,    # 1042 tracts * 12 measures
        'r2023_county': 132,     # 11 counties * 12 measures
        'r2023_tract': 12504,    # 1042 tracts * 12 measures
        'r2024_county': 144,     # 12 counties (9 CT planning regions + 3 DE) * 12 measures
        'r2024_tract': 13596,    # 1133 tracts * 12 measures
    }
    assert {k: len(v) for k, v in parts.items()} == expected_part_counts
    assert evidence['emitted_rows'] == expected_part_counts
    assert evidence['emitted_total'] == sum(expected_part_counts.values())
    assert evidence['county_2020_tract_map_count'] == 11
    assert evidence['county_2020_mapped_rows'] == 121
    assert evidence['county_2020_mapped_unique_counties'] == 11

    counts = Counter()
    for rows in parts.values():
        for row in rows:
            assert row_problems(row, config) == []
            assert row.uncertainty_kind == 'ci95'
            assert row.moe is None
            counts[(row.measure_id, row.period, row.level)] += 1

    # Verify exact row counts for all 59 declared (measure, period) pairs across county and tract
    declared_pairs = [
        (m['measure_id'], p['period'], p['locator']['release'])
        for m in config['measures']
        for p in m['periods']
        if p.get('available', True)
    ]
    assert len(declared_pairs) == 59
    for mid, period, release in declared_pairs:
        if release == '2024':
            assert counts[(mid, period, 'county')] == 12
            assert counts[(mid, period, 'tract')] == 1133
        else:
            assert counts[(mid, period, 'county')] == 11
            assert counts[(mid, period, 'tract')] == 1042


def test_hand_checked_values_dental_dedup_and_boundary_vintages(config, files):
    evidence = {}
    parts = dict(places_parser.parse(config, files, evidence))
    by_key = {row.key: row for rows in parts.values() for row in rows}

    # 1. Fairfield, CT 2018 ACCESS2 = 10.0 (8.5-11.6), from 2020 release, mapped to 09001
    r_fairfield = by_key[('county', '09001', 'access2_crudeprev', '2018')]
    assert r_fairfield.value == Decimal('10.0')
    assert r_fairfield.low == Decimal('8.5')
    assert r_fairfield.high == Decimal('11.6')
    assert r_fairfield.status == 'available'
    assert r_fairfield.source_value == '10.0'
    assert r_fairfield.boundary_vintage == '2020'
    assert r_fairfield in parts['r2020_county']

    # 2. Tract value from 2020 release: 09001010101 BPHIGH 2017 = 32.0 (30.5-33.6)
    r_tract_2017 = by_key[('tract', '09001010101', 'bphigh_crudeprev', '2017')]
    assert r_tract_2017.value == Decimal('32.0')
    assert r_tract_2017.low == Decimal('30.5')
    assert r_tract_2017.high == Decimal('33.6')
    assert r_tract_2017.status == 'available'
    assert r_tract_2017.source_value == '32.0'
    assert r_tract_2017.boundary_vintage == '2019'

    # 3. dental_crudeprev 2020 comes from the 2023 release, and 2022 release's DENTAL:2020 rows are skipped and counted
    r_dental_2020 = by_key[('county', '09001', 'dental_crudeprev', '2020')]
    assert r_dental_2020 in parts['r2023_county']
    assert all(r.measure_id != 'dental_crudeprev' for r in parts['r2022_county'])
    assert all(r.measure_id != 'dental_crudeprev' for r in parts['r2022_tract'])
    assert evidence['skipped_duplicate_data_years']['places2022_county'] == {'DENTAL:2020': 11}
    assert evidence['skipped_duplicate_data_years']['places2022_tract'] == {'DENTAL:2020': 1042}
    assert evidence['skipped_duplicate_data_years']['places2020_county'] == {'DENTAL:2018': 11}
    assert evidence['skipped_duplicate_data_years']['places2021_county'] == {'BPHIGH:2019': 11}
    assert evidence['skipped_duplicate_data_years']['places2023_county'] == {'BPHIGH:2021': 11}
    assert evidence['skipped_duplicate_data_years']['places2024_county'] == {'DENTAL:2022': 12}

    # 4. Boundary vintages: 2024-release CT county row (09110...) gets 2024; 2023-release row (09001) gets 2020; its tracts get 2019
    r_ct_2024 = by_key[('county', '09110', 'diabetes_crudeprev', '2022')]
    assert r_ct_2024.boundary_vintage == '2024'
    assert r_ct_2024 in parts['r2024_county']

    r_ct_2023 = by_key[('county', '09001', 'copd_crudeprev', '2021')]
    assert r_ct_2023.value == Decimal('5.1')
    assert r_ct_2023.low == Decimal('4.1')
    assert r_ct_2023.high == Decimal('6.3')
    assert r_ct_2023.boundary_vintage == '2020'
    assert r_ct_2023 in parts['r2023_county']

    r_tract_2023 = by_key[('tract', '09001020800', 'stroke_crudeprev', '2021')]
    assert r_tract_2023.value == Decimal('2.2')
    assert r_tract_2023.low == Decimal('1.9')
    assert r_tract_2023.high == Decimal('2.5')
    assert r_tract_2023.boundary_vintage == '2019'
    assert r_tract_2023 in parts['r2023_tract']


def test_suppressed_missing_true_zero_and_dropped_us_row(config, files, tmp_path):
    # Modify a copy of places2021_county.csv to test suppressed, missing, true_zero, and a dropped US row
    lines = files['places2021_county'].read_text(encoding='utf-8-sig').splitlines()
    modified = [lines[0]]
    for idx, line in enumerate(lines[1:], start=1):
        cols = line.split(',')
        if idx == 1:
            # Blank with footnote -> suppressed (2019,CT,Tolland,STROKE,CrdPrv,...,09013)
            cols[5] = ''
            cols[6] = ''
            cols[7] = ''
            cols[8] = '*'
            cols[9] = 'Suppressed'
        elif idx == 2:
            # Blank without footnote -> missing (2019,DE,Sussex,DEPRESSION,CrdPrv,...,10005)
            cols[5] = ''
            cols[6] = ''
            cols[7] = ''
            cols[8] = ''
            cols[9] = ''
        elif idx == 3:
            # 0 -> true_zero (2019,CT,Windham,OBESITY,CrdPrv,...,09015)
            cols[5] = '0'
            cols[6] = '0'
            cols[7] = '0.5'
        modified.append(','.join(cols))
    # Add a US national summary row (locationid='59', stateabbr='US')
    modified.append('2019,US,United States,STROKE,CrdPrv,3.1,3.0,3.2,,,59')

    custom_path = tmp_path / 'places2021_county_custom.csv'
    custom_path.write_text('\n'.join(modified) + '\n', encoding='utf-8')

    ev = {}
    parts = dict(places_parser.parse(config, {**files, 'places2021_county': custom_path}, ev))
    by_key = {r.key: r for r in parts['r2021_county']}

    r_sup = by_key[('county', '09013', 'stroke_crudeprev', '2019')]
    assert r_sup.value is None
    assert r_sup.low is None and r_sup.high is None
    assert r_sup.status == 'suppressed'
    assert r_sup.source_value == ''
    assert row_problems(r_sup, config) == []

    r_miss = by_key[('county', '10005', 'depression_crudeprev', '2019')]
    assert r_miss.value is None
    assert r_miss.low is None and r_miss.high is None
    assert r_miss.status == 'missing'
    assert r_miss.source_value == ''
    assert row_problems(r_miss, config) == []

    r_zero = by_key[('county', '09015', 'obesity_crudeprev', '2019')]
    assert r_zero.value == Decimal('0')
    assert r_zero.low == Decimal('0') and r_zero.high == Decimal('0.5')
    assert r_zero.status == 'true_zero'
    assert r_zero.source_value == '0'
    assert row_problems(r_zero, config) == []

    assert ev['dropped_non_target_locations']['places2021_county'] == {'national_us': 1}


def test_ambiguous_county_ci_outside_value_changed_header_and_bad_dtype_raise(config, files, tmp_path):
    # 1. Ambiguous county name in 2020 tract file raises with the name listed
    tract_lines = files['places2020_tract'].read_text(encoding='utf-8-sig').splitlines()
    # Add a tract row mapping ('CT', 'Fairfield') to a second countyfips ('09099')
    ambig_tract = tmp_path / 'places2020_tract_ambig.csv'
    ambig_row = '2018,CT,09099010101,ACCESS2,CrdPrv,5.9,4.8,7.4,,,09099010101,09099,Fairfield'
    ambig_tract.write_text('\n'.join([*tract_lines, ambig_row]) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Ambiguous 2020 PLACES county names.*Fairfield'):
        list(places_parser.parse(config, {**files, 'places2020_tract': ambig_tract}, {}))

    # 2. Unmapped county name in 2020 county file raises with the name listed
    cnty_lines = files['places2020_county'].read_text(encoding='utf-8-sig').splitlines()
    unmapped_cnty = tmp_path / 'places2020_county_unmapped.csv'
    unmapped_row = '2018,CT,NonexistentCounty,ACCESS2,CrdPrv,10.0,8.5,11.6,,'
    unmapped_cnty.write_text('\n'.join([*cnty_lines, unmapped_row]) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Unmapped 2020 PLACES county names.*CT:NonexistentCounty'):
        list(places_parser.parse(config, {**files, 'places2020_county': unmapped_cnty}, {}))

    # 3. CI outside value raises
    bad_ci_cnty = tmp_path / 'places2021_county_bad_ci.csv'
    c21_lines = files['places2021_county'].read_text(encoding='utf-8-sig').splitlines()
    bad_ci_row = '2019,CT,Tolland,STROKE,CrdPrv,5.0,2.2,2.8,,,09013'
    bad_ci_cnty.write_text('\n'.join([c21_lines[0], bad_ci_row, *c21_lines[2:]]) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='does not bracket value'):
        list(places_parser.parse(config, {**files, 'places2021_county': bad_ci_cnty}, {}))

    # 4. CI on a blank value raises
    blank_ci_cnty = tmp_path / 'places2021_county_blank_ci.csv'
    blank_ci_row = '2019,CT,Tolland,STROKE,CrdPrv,,2.2,2.8,*,,09013'
    blank_ci_cnty.write_text('\n'.join([c21_lines[0], blank_ci_row, *c21_lines[2:]]) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='blank value has confidence limit'):
        list(places_parser.parse(config, {**files, 'places2021_county': blank_ci_cnty}, {}))

    # 5. Changed header raises
    bad_hdr_cnty = tmp_path / 'places2021_county_bad_hdr.csv'
    bad_hdr_cnty.write_text(
        '\n'.join([c21_lines[0].replace('measureid', 'measure_id'), *c21_lines[1:]]) + '\n',
        encoding='utf-8',
    )
    with pytest.raises(ValueError, match='CSV header'):
        list(places_parser.parse(config, {**files, 'places2021_county': bad_hdr_cnty}, {}))

    # 6. Non-CrdPrv datavaluetypeid raises
    bad_dtype_cnty = tmp_path / 'places2021_county_bad_dtype.csv'
    bad_dtype_row = c21_lines[1].replace(',CrdPrv,', ',AgeAdjPrv,')
    bad_dtype_cnty.write_text('\n'.join([c21_lines[0], bad_dtype_row, *c21_lines[2:]]) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='datavaluetypeid'):
        list(places_parser.parse(config, {**files, 'places2021_county': bad_dtype_cnty}, {}))
