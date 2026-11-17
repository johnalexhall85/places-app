"""Tests for the Census ACS 5-year median household income (B19013) history parser."""
from __future__ import annotations

import copy
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.area_pilot.history.parsers import acs as acs_parser
from app.area_pilot.history.parsers import load_parser
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.history.rows import part_digest, row_problems

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures' / 'history' / 'acs'
VINTAGES = ('2019', '2023')
PERIOD_BY_VINTAGE = {'2019': '2015–2019', '2023': '2019–2023'}
STATES = ('09', '11')


@pytest.fixture
def config():
    base = copy.deepcopy(load_history_registry('acs'))
    base['state_fips'] = list(STATES)
    keep_roles = {f'acs{v}_{lvl}' for v in VINTAGES for lvl in ('state', 'county', 'tract')}
    base['sources'] = [s for s in base['sources'] if s['role'] in keep_roles]
    for measure in base['measures']:
        measure['periods'] = [
            p for p in measure['periods'] if (p.get('locator') or {}).get('vintage') in VINTAGES
        ]
    base['_index'] = {
        (m['measure_id'], p['period']): (m, p)
        for m in base['measures']
        for p in m['periods']
    }
    return base


@pytest.fixture
def files():
    result = {}
    for v in VINTAGES:
        result[f'acs{v}_state'] = FIXTURE_DIR / f'acs{v}_state.json'
        for st in STATES:
            result[f'acs{v}_county_{st}'] = FIXTURE_DIR / f'acs{v}_county_{st}.json'
            result[f'acs{v}_tract_{st}'] = FIXTURE_DIR / f'acs{v}_tract_{st}.json'
    return result


def test_contract_and_parts_stability(config, files):
    module = load_parser('acs')
    assert module is acs_parser
    assert module.SCHEMA_VERSION == '1'

    ev1, ev2 = {}, {}
    parts1 = list(module.parse(config, files, ev1))
    parts2 = list(module.parse(config, files, ev2))

    names1 = [name for name, _ in parts1]
    assert names1 == [
        'v2019_state',
        'v2019_county',
        'v2019_tract',
        'v2023_state',
        'v2023_county',
        'v2023_tract',
    ]
    assert len(names1) == len(set(names1))
    assert parts1 == parts2
    assert ev1 == ev2
    for (_, rows1), (_, rows2) in zip(parts1, parts2):
        assert part_digest(rows1) == part_digest(rows2)


def test_exact_counts_evidence_and_row_problems(config, files):
    evidence = {}
    parts = dict(acs_parser.parse(config, files, evidence))

    expected_part_counts = {
        'v2019_state': 52,
        'v2019_county': 9,     # 8 CT former counties + 1 DC
        'v2019_tract': 1012,   # 833 CT + 179 DC
        'v2023_state': 52,
        'v2023_county': 10,    # 9 CT planning regions + 1 DC
        'v2023_tract': 1090,   # 884 CT + 206 DC
    }
    assert {k: len(v) for k, v in parts.items()} == expected_part_counts
    assert evidence['emitted_rows'] == expected_part_counts
    assert evidence['emitted_total'] == sum(expected_part_counts.values())
    assert evidence['row_counts'] == {
        '2019': {'state': 52, 'county': 9, 'tract': 1012},
        '2023': {'state': 52, 'county': 10, 'tract': 1090},
    }
    assert evidence['status_counts'] == {
        '2019': {
            'state': {'available': 52},
            'county': {'available': 9},
            'tract': {'available': 989, 'missing': 13, 'open_ended': 10},
        },
        '2023': {
            'state': {'available': 52},
            'county': {'available': 10},
            'tract': {'available': 1034, 'missing': 19, 'open_ended': 37},
        },
    }
    assert evidence['open_ended_rows'] == {
        '2019': {'state': 0, 'county': 0, 'tract': 10},
        '2023': {'state': 0, 'county': 0, 'tract': 37},
    }

    counts = Counter()
    for rows in parts.values():
        for row in rows:
            assert row_problems(row, config) == []
            assert row.measure_id == 'B19013_001E'
            assert row.uncertainty_kind == 'moe90'
            assert row.low is None and row.high is None
            counts[(row.period, row.level)] += 1

    assert counts[('2015–2019', 'state')] == 52
    assert counts[('2015–2019', 'county')] == 9
    assert counts[('2015–2019', 'tract')] == 1012
    assert counts[('2019–2023', 'state')] == 52
    assert counts[('2019–2023', 'county')] == 10
    assert counts[('2019–2023', 'tract')] == 1090


def test_hand_checked_values_open_ended_missing_and_boundary_vintages(config, files, tmp_path):
    parts = dict(acs_parser.parse(config, files, {}))
    by_key = {row.key: row for rows in parts.values() for row in rows}

    # 1. Connecticut 2019 county 09001 gets boundary vintage 2020
    ct_2019 = by_key[('county', '09001', 'B19013_001E', '2015–2019')]
    assert ct_2019.value == Decimal('95645')
    assert ct_2019.moe == Decimal('1039')
    assert ct_2019.status == 'available'
    assert ct_2019.source_value == '95645'
    assert ct_2019.boundary_vintage == '2020'

    # 2. Connecticut 2023 planning region 09110 gets boundary vintage 2024
    ct_2023 = by_key[('county', '09110', 'B19013_001E', '2019–2023')]
    assert ct_2023.value == Decimal('91541')
    assert ct_2023.moe == Decimal('1111')
    assert ct_2023.status == 'available'
    assert ct_2023.source_value == '91541'
    assert ct_2023.boundary_vintage == '2024'

    # 3. Open-ended tract row from fixture (09001010102 in 2015–2019: 250001 / -333333333 / 250,000+ / ***)
    open_row = by_key[('tract', '09001010102', 'B19013_001E', '2015–2019')]
    assert open_row.value == Decimal('250001')
    assert open_row.moe is None
    assert open_row.status == 'open_ended'
    assert open_row.source_value == '250001|250,000+'
    assert open_row.boundary_vintage == '2019'

    # 4. Missing/sentinel tract row from fixture (09001211100 in 2015–2019: -666666666 / -222222222 / - / **)
    miss_row = by_key[('tract', '09001211100', 'B19013_001E', '2015–2019')]
    assert miss_row.value is None
    assert miss_row.moe is None
    assert miss_row.status == 'missing'
    assert miss_row.source_value == '-666666666|-'
    assert miss_row.boundary_vintage == '2019'

    # 5. DC 2019 tracts get vintage 2019; 2023 tracts get vintage 2024
    dc_tract_2019 = by_key[('tract', '11001000100', 'B19013_001E', '2015–2019')]
    assert dc_tract_2019.boundary_vintage == '2019'
    assert dc_tract_2019.status == 'available'

    dc_tract_2023 = by_key[('tract', '11001000101', 'B19013_001E', '2019–2023')]
    assert dc_tract_2023.value == Decimal('135708')
    assert dc_tract_2023.moe == Decimal('43153')
    assert dc_tract_2023.boundary_vintage == '2024'

    # 6. Suppressed (-999999999|N) and true_zero (0) rows in a modified copy
    payload = json.loads(files['acs2019_county_11'].read_text(encoding='utf-8'))
    payload[1] = ['-999999999', '-999999999', 'N', 'N', '11', '001']
    payload.append(['0', '100', None, None, '11', '003'])
    custom_path = tmp_path / 'acs2019_county_11_custom.json'
    custom_path.write_text(json.dumps(payload), encoding='utf-8')

    custom_parts = dict(acs_parser.parse(config, {**files, 'acs2019_county_11': custom_path}, {}))
    custom_by_key = {r.key: r for rows in custom_parts.values() for r in rows}

    sup_row = custom_by_key[('county', '11001', 'B19013_001E', '2015–2019')]
    assert sup_row.value is None
    assert sup_row.moe is None
    assert sup_row.status == 'suppressed'
    assert sup_row.source_value == '-999999999|N'
    assert row_problems(sup_row, config) == []

    zero_row = custom_by_key[('county', '11003', 'B19013_001E', '2015–2019')]
    assert zero_row.value == Decimal('0')
    assert zero_row.moe == Decimal('100')
    assert zero_row.status == 'true_zero'
    assert zero_row.source_value == '0'
    assert row_problems(zero_row, config) == []


def test_missing_header_column_missing_role_and_outside_state_raise(config, files, tmp_path):
    # 1. Response whose header lacks B19013_001MA raises
    payload = json.loads(files['acs2019_county_11'].read_text(encoding='utf-8'))
    bad_payload = [
        ['B19013_001E', 'B19013_001M', 'B19013_001EA', 'state', 'county'],
        ['86420', '1008', None, '11', '001'],
    ]
    bad_hdr = tmp_path / 'bad_header.json'
    bad_hdr.write_text(json.dumps(bad_payload), encoding='utf-8')
    with pytest.raises(ValueError, match='Census response header changed'):
        list(acs_parser.parse(config, {**files, 'acs2019_county_11': bad_hdr}, {}))

    # 2. Missing role raises
    incomplete_files = {k: v for k, v in files.items() if k != 'acs2023_tract_09'}
    with pytest.raises(ValueError, match='Missing required ACS source file roles'):
        list(acs_parser.parse(config, incomplete_files, {}))

    # 3. Extra role for a state outside state_fips raises
    with pytest.raises(ValueError, match='Unexpected ACS source file roles'):
        list(acs_parser.parse(config, {**files, 'acs2019_county_25': files['acs2019_county_11']}, {}))

    # 4. County/tract response containing a row for a state outside its partition / state_fips raises
    wrong_state_payload = copy.deepcopy(payload)
    wrong_state_payload[1][4] = '25'
    wrong_state_path = tmp_path / 'wrong_state_county.json'
    wrong_state_path.write_text(json.dumps(wrong_state_payload), encoding='utf-8')
    with pytest.raises(ValueError, match='Census partition returned a different state'):
        list(acs_parser.parse(config, {**files, 'acs2019_county_11': wrong_state_path}, {}))

    # 5. State response containing a state outside state_fips raises
    state_payload = json.loads(files['acs2019_state'].read_text(encoding='utf-8'))
    state_payload_bad = [*state_payload, ['50000', '500', None, None, '78']]
    bad_state_path = tmp_path / 'bad_state.json'
    bad_state_path.write_text(json.dumps(state_payload_bad), encoding='utf-8')
    with pytest.raises(ValueError, match='outside supported state_fips'):
        list(acs_parser.parse(config, {**files, 'acs2019_state': bad_state_path}, {}))
