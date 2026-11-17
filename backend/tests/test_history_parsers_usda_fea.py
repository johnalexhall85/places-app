"""Tests for the USDA ERS Food Environment Atlas history parser."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.area_pilot.history.parsers import load_parser
from app.area_pilot.history.parsers import usda_fea as usda_fea_parser
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.history.rows import MAX_SCALE, part_digest, row_problems

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures' / 'history' / 'usda_fea'
VALUES_CSV = FIXTURE_DIR / 'StateAndCountyData_sample.csv'
VARIABLES_CSV = FIXTURE_DIR / 'VariableList.csv'
DECLARED_PERIODS = ('2013', '2015', '2016', '2017')


def _expected_dec(raw: str) -> Decimal:
    d = Decimal(raw)
    return d.quantize(Decimal(10) ** -MAX_SCALE) if d.as_tuple().exponent < -MAX_SCALE else d


@pytest.fixture
def config():
    return load_history_registry('usda_fea')


@pytest.fixture
def files():
    return {'values_csv': VALUES_CSV, 'variables_csv': VARIABLES_CSV}


def test_contract_and_parts_stability(config, files):
    module = load_parser('usda_fea')
    assert module is usda_fea_parser
    assert module.SCHEMA_VERSION == '1'

    ev1, ev2 = {}, {}
    parts1 = list(module.parse(config, files, ev1))
    parts2 = list(module.parse(config, files, ev2))

    names1 = [name for name, _ in parts1]
    assert names1 == [f'period_{p}' for p in DECLARED_PERIODS]
    assert len(names1) == len(set(names1))
    assert parts1 == parts2
    assert ev1 == ev2
    for (_, rows1), (_, rows2) in zip(parts1, parts2):
        assert part_digest(rows1) == part_digest(rows2)


def test_exact_counts_and_row_problems(config, files):
    evidence = {}
    parts = dict(usda_fea_parser.parse(config, files, evidence))

    assert set(parts) == {f'period_{p}' for p in DECLARED_PERIODS}
    assert len(parts['period_2013']) == 11
    assert len(parts['period_2015']) == 18
    assert len(parts['period_2016']) == 9
    assert len(parts['period_2017']) == 9

    counts = Counter()
    for rows in parts.values():
        for row in rows:
            assert row_problems(row, config) == []
            assert row.boundary_vintage == '2020'
            counts[(row.measure_id, row.period, row.level)] += 1

    assert counts == {
        ('farmers_markets_per_1000', '2013', 'county'): 11,
        ('low_income_low_access_pct', '2015', 'county'): 9,
        ('no_car_low_access_households_pct', '2015', 'county'): 9,
        ('wic_stores_per_1000', '2016', 'county'): 9,
        ('snap_stores_per_1000', '2017', 'county'): 9,
    }


def test_hand_checked_values_sentinels_and_historical_counties(config, files, tmp_path):
    parts = dict(usda_fea_parser.parse(config, files, {}))
    by_key = {row.key: row for rows in parts.values() for row in rows}

    # 1. Available value: 01001 AL Autauga PCT_LACCESS_LOWI15 (2015)
    r1 = by_key[('county', '01001', 'low_income_low_access_pct', '2015')]
    assert r1.value == _expected_dec('12.52614498')
    assert r1.status == 'available'
    assert r1.source_value == '12.52614498'

    # 2. Valdez-Cordova 02261 emitted as published across all 5 measures
    r_vc_fm = by_key[('county', '02261', 'farmers_markets_per_1000', '2013')]
    assert r_vc_fm.value == _expected_dec('0.306873977')
    assert r_vc_fm.status == 'available'
    assert r_vc_fm.source_value == '0.306873977'
    assert by_key[('county', '02261', 'low_income_low_access_pct', '2015')].value == _expected_dec('15.31539822')
    assert by_key[('county', '02261', 'no_car_low_access_households_pct', '2015')].value == _expected_dec('4.587210655')
    assert by_key[('county', '02261', 'wic_stores_per_1000', '2016')].value == _expected_dec('0.420079815')
    assert by_key[('county', '02261', 'snap_stores_per_1000', '2017')].value == _expected_dec('1.535891356')

    # 3. Shannon 46113 (-9999 not_available) and Oglala Lakota 46102 (-8888 did_not_exist) emitted as published
    r_shannon = by_key[('county', '46113', 'farmers_markets_per_1000', '2013')]
    assert r_shannon.value is None
    assert r_shannon.status == 'not_available'
    assert r_shannon.source_value == '-9999'

    r_oglala_fm = by_key[('county', '46102', 'farmers_markets_per_1000', '2013')]
    assert r_oglala_fm.value is None
    assert r_oglala_fm.status == 'did_not_exist'
    assert r_oglala_fm.source_value == '-8888'

    r_oglala_lowi = by_key[('county', '46102', 'low_income_low_access_pct', '2015')]
    assert r_oglala_lowi.value == _expected_dec('62.11082458')
    assert r_oglala_lowi.status == 'available'
    assert r_oglala_lowi.source_value == '62.11082458'

    # 4. True zero: 48301 TX Loving FMRKTPTH13 = 0 -> status 'true_zero'
    r_zero = by_key[('county', '48301', 'farmers_markets_per_1000', '2013')]
    assert r_zero.value == Decimal('0')
    assert r_zero.status == 'true_zero'
    assert r_zero.source_value == '0'

    # 5. 'N/A' and '' blank sentinels map to 'not_available' with value None
    lines = VALUES_CSV.read_text(encoding='utf-8-sig').splitlines()
    extra_lines = lines + [
        '01005,AL,Barbour,WICSPTH16,N/A',
        '01007,AL,Bibb,WICSPTH16,',
    ]
    custom_csv = tmp_path / 'values_sentinels.csv'
    custom_csv.write_text('\n'.join(extra_lines) + '\n', encoding='utf-8-sig')
    custom_parts = dict(usda_fea_parser.parse(config, {'values_csv': custom_csv, 'variables_csv': VARIABLES_CSV}, {}))
    custom_by_key = {row.key: row for rows in custom_parts.values() for row in rows}

    r_na = custom_by_key[('county', '01005', 'wic_stores_per_1000', '2016')]
    assert r_na.value is None
    assert r_na.status == 'not_available'
    assert r_na.source_value == 'N/A'

    r_blank = custom_by_key[('county', '01007', 'wic_stores_per_1000', '2016')]
    assert r_blank.value is None
    assert r_blank.status == 'not_available'
    assert r_blank.source_value == ''


def test_ignored_variables_fips_padding_exclusions_and_duplicates(config, files, tmp_path):
    evidence = {}
    list(usda_fea_parser.parse(config, files, evidence))

    assert evidence['total_rows'] == 112
    # Current-year codes and two unrelated codes (LACCESS_POP15, PCH_SNAPSPTH_17_23) are ignored
    assert evidence['ignored_variables'] == {
        'FMRKTPTH18': 11,
        'LACCESS_POP15': 9,
        'PCH_SNAPSPTH_17_23': 9,
        'PCT_LACCESS_HHNV19': 9,
        'PCT_LACCESS_LOWI19': 9,
        'SNAPSPTH23': 9,
        'WICSPTH22': 9,
    }
    assert evidence['padded_fips_total'] == 0
    assert evidence['excluded_rows'] == {}

    # Test 4-digit FIPS padding and state/national FIPS ending in 000 exclusion
    lines = VALUES_CSV.read_text(encoding='utf-8-sig').splitlines()
    # Replace '01001,AL,Autauga,SNAPSPTH17,0.804746805' with 4-digit '1001' and add state/national 000 rows
    patched = [
        line.replace('01001,AL,Autauga,SNAPSPTH17,', '1001,AL,Autauga,SNAPSPTH17,')
        for line in lines
    ] + [
        '01000,AL,Alabama,SNAPSPTH17,0.95',
        '1000,AL,Alabama,WICSPTH16,0.12',
        '00000,US,United States,FMRKTPTH13,0.03',
    ]
    patched_csv = tmp_path / 'patched.csv'
    patched_csv.write_text('\n'.join(patched) + '\n', encoding='utf-8-sig')

    ev_patched = {}
    parts_patched = dict(
        usda_fea_parser.parse(config, {'values_csv': patched_csv, 'variables_csv': VARIABLES_CSV}, ev_patched)
    )
    by_key = {row.key: row for rows in parts_patched.values() for row in rows}
    assert ('county', '01001', 'snap_stores_per_1000', '2017') in by_key
    assert all(not row.geoid.endswith('000') for rows in parts_patched.values() for row in rows)
    assert ev_patched['padded_fips_total'] == 2
    assert ev_patched['padded_fips_by_period'] == {'2016': 1, '2017': 1}
    assert ev_patched['excluded_rows'] == {
        '2013': {'state_or_national_fips_000': 1},
        '2016': {'state_or_national_fips_000': 1},
        '2017': {'state_or_national_fips_000': 1},
    }

    # Any other non-5-digit FIPS raises ValueError
    bad_fips_csv = tmp_path / 'bad_fips.csv'
    bad_fips_csv.write_text('\n'.join(lines + ['N/A,AK,Aleutian Islands Area,FMRKTPTH13,-8888']) + '\n', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='non-5-digit FIPS'):
        list(usda_fea_parser.parse(config, {'values_csv': bad_fips_csv, 'variables_csv': VARIABLES_CSV}, {}))

    # Duplicate (FIPS, Variable_Code) raises ValueError
    dup_csv = tmp_path / 'dup.csv'
    dup_csv.write_text('\n'.join(lines + ['01001,AL,Autauga,SNAPSPTH17,0.804746805']) + '\n', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='Duplicate USDA FEA'):
        list(usda_fea_parser.parse(config, {'values_csv': dup_csv, 'variables_csv': VARIABLES_CSV}, {}))


def test_changed_header_or_variable_definition_raises(config, tmp_path):
    val_lines = VALUES_CSV.read_text(encoding='utf-8-sig').splitlines()
    var_lines = VARIABLES_CSV.read_text(encoding='utf-8-sig').splitlines()

    # 1. Changed values_csv header
    bad_val_csv = tmp_path / 'bad_val_header.csv'
    bad_val_csv.write_text('\n'.join(['FIPS,State,County,Variable,Value'] + val_lines[1:]) + '\n', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='StateAndCountyData.csv header'):
        list(usda_fea_parser.parse(config, {'values_csv': bad_val_csv, 'variables_csv': VARIABLES_CSV}, {}))

    # 2. Changed VariableList.csv header
    bad_var_header_csv = tmp_path / 'bad_var_header.csv'
    bad_var_header_csv.write_text(
        '\n'.join([var_lines[0].replace('Variable_Code', 'Var_Code')] + var_lines[1:]) + '\n',
        encoding='utf-8-sig',
    )
    with pytest.raises(ValueError, match='VariableList.csv header'):
        list(usda_fea_parser.parse(config, {'values_csv': VALUES_CSV, 'variables_csv': bad_var_header_csv}, {}))

    # 3. Changed Variable_Name in VariableList.csv for a declared locator
    bad_var_name_csv = tmp_path / 'bad_var_name.csv'
    bad_var_name_csv.write_text(
        '\n'.join(
            line.replace('SNAP-authorized stores/1,000 pop, 2017', 'SNAP stores per 1,000, 2017')
            for line in var_lines
        ) + '\n',
        encoding='utf-8-sig',
    )
    with pytest.raises(ValueError, match='VariableList.csv name for'):
        list(usda_fea_parser.parse(config, {'values_csv': VALUES_CSV, 'variables_csv': bad_var_name_csv}, {}))
