"""Tests for the CMS Original Medicare Geographic Variation (OM GV) history parser."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.area_pilot.history.parsers import load_parser
from app.area_pilot.history.parsers import cms_gv as cms_gv_parser
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.history.rows import part_digest, row_problems

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'history' / 'cms_gv' / 'om_gv_sample.csv'
DECLARED_YEARS = ('2019', '2020', '2021', '2022', '2023')
MEASURES = (
    'om_beneficiaries',
    'std_payment_per_capita',
    'ip_stays_per_1000',
    'er_visits_per_1000',
    'readmission_rate',
)


@pytest.fixture
def config():
    return load_history_registry('cms_gv')


def test_contract_and_parts_stability(config):
    module = load_parser('cms_gv')
    assert module is cms_gv_parser
    assert module.SCHEMA_VERSION == '1'

    ev1, ev2 = {}, {}
    parts1 = list(module.parse(config, {'gv_csv': FIXTURE}, ev1))
    parts2 = list(module.parse(config, {'gv_csv': FIXTURE}, ev2))

    names1 = [name for name, _ in parts1]
    assert names1 == [f'year_{y}' for y in DECLARED_YEARS]
    assert len(names1) == len(set(names1))
    assert parts1 == parts2
    assert ev1 == ev2
    for (_, rows1), (_, rows2) in zip(parts1, parts2):
        assert part_digest(rows1) == part_digest(rows2)


def test_exact_counts_and_row_problems(config):
    evidence = {}
    parts = dict(cms_gv_parser.parse(config, {'gv_csv': FIXTURE}, evidence))

    assert set(parts) == {f'year_{y}' for y in DECLARED_YEARS}
    counts = Counter()
    for part_name, rows in parts.items():
        assert len(rows) == 45, f'{part_name} expected 45 rows'
        for row in rows:
            assert row_problems(row, config) == []
            counts[(row.measure_id, row.period, row.level)] += 1

    for measure_id in MEASURES:
        for period in DECLARED_YEARS:
            assert counts[(measure_id, period, 'state')] == 4
            assert counts[(measure_id, period, 'county')] == 5


def test_hand_checked_values_and_suppressed_missing_cells(config, tmp_path):
    parts = dict(cms_gv_parser.parse(config, {'gv_csv': FIXTURE}, {}))
    by_key = {row.key: row for rows in parts.values() for row in rows}

    # 1. 2019 AL state (01) Original Medicare beneficiaries
    r1 = by_key[('state', '01', 'om_beneficiaries', '2019')]
    assert r1.value == Decimal('534585')
    assert r1.status == 'available'
    assert r1.source_value == '534585'

    # 2. 2020 NY-New York county (36061) standardized payment per capita
    r2 = by_key[('county', '36061', 'std_payment_per_capita', '2020')]
    assert r2.value == Decimal('10242.07')
    assert r2.status == 'available'
    assert r2.source_value == '10242.07'

    # 3. 2021 CT-Fairfield county (09001) readmission rate
    r3 = by_key[('county', '09001', 'readmission_rate', '2021')]
    assert r3.value == Decimal('0.1813')
    assert r3.status == 'available'
    assert r3.source_value == '0.1813'

    # 4. 2023 PR state (72) ER visits per 1,000
    r4 = by_key[('state', '72', 'er_visits_per_1000', '2023')]
    assert r4.value == Decimal('378.818')
    assert r4.status == 'available'
    assert r4.source_value == '378.818'

    # 5. Suppressed ('*'), missing (''), and true_zero ('0') cells from the fixture
    # Copy the suppressed AL-UNKNOWN row from the fixture as a kept county code (01005),
    # and set one cell on 01001 in 2019 to blank ('') and one to '0'.
    raw_text = FIXTURE.read_text(encoding='utf-8-sig')
    lines = raw_text.splitlines()
    header = lines[0].split(',')
    idx_pymt = header.index('TOT_MDCR_STDZD_PYMT_PC')
    idx_ip = header.index('IP_CVRD_STAYS_PER_1000_BENES')

    modified_lines = [lines[0]]
    for line in lines[1:]:
        cols = line.split(',')
        if cols[0] == '2019' and cols[1] == 'County' and cols[3] == '01000':
            # Keep the original 01000 row AND add a kept county 01005 with the fixture's '*' cells
            modified_lines.append(line)
            suppressed_cols = list(cols)
            suppressed_cols[2] = 'AL-SampleSuppressed'
            suppressed_cols[3] = '01005'
            modified_lines.append(','.join(suppressed_cols))
        elif cols[0] == '2019' and cols[1] == 'County' and cols[3] == '01001':
            cols[idx_pymt] = ''
            cols[idx_ip] = '0'
            modified_lines.append(','.join(cols))
        else:
            modified_lines.append(line)

    custom_csv = tmp_path / 'om_gv_cells.csv'
    custom_csv.write_text('\n'.join(modified_lines) + '\n', encoding='utf-8-sig')

    custom_parts = dict(cms_gv_parser.parse(config, {'gv_csv': custom_csv}, {}))
    custom_by_key = {row.key: row for rows in custom_parts.values() for row in rows}

    sup_row = custom_by_key[('county', '01005', 'om_beneficiaries', '2019')]
    assert sup_row.value is None
    assert sup_row.status == 'suppressed'
    assert sup_row.source_value == '*'
    assert row_problems(sup_row, config) == []

    miss_row = custom_by_key[('county', '01001', 'std_payment_per_capita', '2019')]
    assert miss_row.value is None
    assert miss_row.status == 'missing'
    assert miss_row.source_value == ''
    assert row_problems(miss_row, config) == []

    zero_row = custom_by_key[('county', '01001', 'ip_stays_per_1000', '2019')]
    assert zero_row.value == Decimal('0')
    assert zero_row.status == 'true_zero'
    assert zero_row.source_value == '0'
    assert row_problems(zero_row, config) == []


def test_connecticut_boundary_vintages(config):
    parts = dict(cms_gv_parser.parse(config, {'gv_csv': FIXTURE}, {}))
    by_key = {row.key: row for rows in parts.values() for row in rows}

    # Old CT county 09001 in 2019-2021 gets county boundary vintage 2020
    for yr in ('2019', '2020', '2021'):
        assert by_key[('county', '09001', 'om_beneficiaries', yr)].boundary_vintage == '2020'
        assert by_key[('county', '09003', 'om_beneficiaries', yr)].boundary_vintage == '2020'
        assert by_key[('state', '09', 'om_beneficiaries', yr)].boundary_vintage == '2024'

    # CT planning regions 09110 and 09120 in 2022-2023 get county boundary vintage 2024
    for yr in ('2022', '2023'):
        assert by_key[('county', '09110', 'om_beneficiaries', yr)].boundary_vintage == '2024'
        assert by_key[('county', '09120', 'om_beneficiaries', yr)].boundary_vintage == '2024'
        assert by_key[('state', '09', 'om_beneficiaries', yr)].boundary_vintage == '2024'


def test_exclusions_and_non_selected_rows_in_evidence(config, tmp_path):
    evidence = {}
    parts = dict(cms_gv_parser.parse(config, {'gv_csv': FIXTURE}, evidence))
    geoids = {(r.level, r.geoid) for rows in parts.values() for r in rows}

    # Excluded geographies and National are never emitted
    assert ('state', '78') not in geoids
    assert ('county', '78010') not in geoids
    assert ('county', '01000') not in geoids
    assert all(r.level in ('state', 'county') for rows in parts.values() for r in rows)

    assert evidence['total_rows'] == 112
    assert evidence['ignored_years'] == {'2018': 16, '2024': 16}
    assert evidence['age_counts'] == {'<65': 7, 'All': 105}
    for yr in DECLARED_YEARS:
        assert evidence['ignored_age_by_year'][yr] == {'<65': 1}
        assert evidence['national_rows'][yr] == 1
        assert evidence['excluded_rows'][yr] == {
            'non_fips_state_aggregate': 2,
            'territory_outside_chip_2024_boundary_layer': 2,
            'unknown_county_of_residence': 1,
        }

    # Any other non-FIPS / unexplained code raises ValueError
    bad_csv = tmp_path / 'bad_code.csv'
    lines = FIXTURE.read_text(encoding='utf-8-sig').splitlines()
    bad_row = lines[18].split(',')  # 2019,State,AL,01,All,...
    bad_row[2] = 'XX'
    bad_row[3] = '999'
    bad_csv.write_text('\n'.join(lines + [','.join(bad_row)]) + '\n', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='non-FIPS'):
        list(cms_gv_parser.parse(config, {'gv_csv': bad_csv}, {}))


def test_changed_header_raises(config, tmp_path):
    lines = FIXTURE.read_text(encoding='utf-8-sig').splitlines()

    # Changed dimension column
    bad_dim_csv = tmp_path / 'bad_dim.csv'
    bad_dim_header = lines[0].replace('BENE_GEO_CD', 'GEO_CODE', 1)
    bad_dim_csv.write_text('\n'.join([bad_dim_header] + lines[1:]) + '\n', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='dimension columns'):
        list(cms_gv_parser.parse(config, {'gv_csv': bad_dim_csv}, {}))

    # Changed measure source_field column
    bad_measure_csv = tmp_path / 'bad_measure.csv'
    bad_measure_header = lines[0].replace('BENES_OM_CNT', 'BENES_OM_COUNT_RENAMED', 1)
    bad_measure_csv.write_text('\n'.join([bad_measure_header] + lines[1:]) + '\n', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='missing measure fields'):
        list(cms_gv_parser.parse(config, {'gv_csv': bad_measure_csv}, {}))
