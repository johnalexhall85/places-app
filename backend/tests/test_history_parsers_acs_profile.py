"""Tests for the Census ACS 5-year community characteristics (subject tables) history parser."""
from __future__ import annotations

import copy
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.area_pilot.history.parsers import acs_profile as acs_profile_parser
from app.area_pilot.history.parsers import load_parser
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.history.rows import part_digest, row_problems

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures' / 'history' / 'acs_profile'
VINTAGES = ('2019', '2023')
STATES = ('09', '11')
MEASURES = (
    'total_population',
    'poverty_pct',
    'age_65_plus_pct',
    'age_under_18_pct',
    'disability_pct',
    'uninsured_pct',
    'limited_english_pct',
)


@pytest.fixture
def config():
    base = copy.deepcopy(load_history_registry('acs_profile'))
    base['state_fips'] = list(STATES)
    keep_roles = {f'acsp{v}_{lvl}' for v in VINTAGES for lvl in ('state', 'county', 'tract')}
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
        result[f'acsp{v}_state'] = FIXTURE_DIR / f'acsp{v}_state.json'
        for st in STATES:
            result[f'acsp{v}_county_{st}'] = FIXTURE_DIR / f'acsp{v}_county_{st}.json'
            result[f'acsp{v}_tract_{st}'] = FIXTURE_DIR / f'acsp{v}_tract_{st}.json'
    return result


def test_contract_and_parts_stability(config, files):
    module = load_parser('acs_profile')
    assert module is acs_profile_parser
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


def test_exact_counts_per_measure_period_level_and_row_problems(config, files):
    evidence = {}
    parts = dict(acs_profile_parser.parse(config, files, evidence))

    expected_part_counts = {
        'v2019_state': 52 * 7,      # 364
        'v2019_county': 9 * 7,      # 63 (8 CT + 1 DC)
        'v2019_tract': 1012 * 7,    # 7084 (833 CT + 179 DC)
        'v2023_state': 52 * 7,      # 364
        'v2023_county': 10 * 7,     # 70 (9 CT + 1 DC)
        'v2023_tract': 1090 * 7,    # 7630 (884 CT + 206 DC)
    }
    assert {k: len(v) for k, v in parts.items()} == expected_part_counts
    assert evidence['emitted_rows'] == expected_part_counts
    assert evidence['emitted_total'] == sum(expected_part_counts.values())
    assert evidence['geography_counts'] == {
        '2019': {'state': 52, 'county': 9, 'tract': 1012},
        '2023': {'state': 52, 'county': 10, 'tract': 1090},
    }
    assert evidence['status_counts'] == {
        '2019': {
            'state': {'available': 364},
            'county': {'available': 63},
            'tract': {'available': 7003, 'missing': 39, 'true_zero': 42},
        },
        '2023': {
            'state': {'available': 364},
            'county': {'available': 70},
            'tract': {'available': 7505, 'missing': 57, 'true_zero': 68},
        },
    }

    counts = Counter()
    for rows in parts.values():
        for row in rows:
            assert row_problems(row, config) == []
            assert row.uncertainty_kind == 'moe90'
            assert row.low is None and row.high is None
            counts[(row.measure_id, row.period, row.level)] += 1

    for mid in MEASURES:
        assert counts[(mid, '2015–2019', 'state')] == 52
        assert counts[(mid, '2015–2019', 'county')] == 9
        assert counts[(mid, '2015–2019', 'tract')] == 1012
        assert counts[(mid, '2019–2023', 'state')] == 52
        assert counts[(mid, '2019–2023', 'county')] == 10
        assert counts[(mid, '2019–2023', 'tract')] == 1090


def test_hand_checked_values_missing_zero_and_boundary_vintages(config, files):
    parts = dict(acs_profile_parser.parse(config, files, {}))
    by_key = {row.key: row for rows in parts.values() for row in rows}

    # 1. County hand-checked values with MOE: Fairfield County, CT (09001) in 2015–2019
    r_cnty_pov = by_key[('county', '09001', 'poverty_pct', '2015–2019')]
    assert r_cnty_pov.value == Decimal('8.9')
    assert r_cnty_pov.moe == Decimal('0.4')
    assert r_cnty_pov.status == 'available'
    assert r_cnty_pov.source_value == '8.9'
    assert r_cnty_pov.boundary_vintage == '2020'

    # Controlled count estimate on 09001 has sentinel MOE -555555555 (*****) -> moe is None
    r_cnty_pop = by_key[('county', '09001', 'total_population', '2015–2019')]
    assert r_cnty_pop.value == Decimal('943926')
    assert r_cnty_pop.moe is None
    assert r_cnty_pop.status == 'available'
    assert r_cnty_pop.source_value == '943926'
    assert r_cnty_pop.boundary_vintage == '2020'

    # 2. Tract hand-checked values with MOE: DC tract 11001000101 in 2019–2023
    r_tract = by_key[('tract', '11001000101', 'poverty_pct', '2019–2023')]
    assert r_tract.value == Decimal('3.1')
    assert r_tract.moe == Decimal('3.3')
    assert r_tract.status == 'available'
    assert r_tract.source_value == '3.1'
    assert r_tract.boundary_vintage == '2024'

    r_tract_pop = by_key[('tract', '11001000101', 'total_population', '2019–2023')]
    assert r_tract_pop.value == Decimal('1181')
    assert r_tract_pop.moe == Decimal('205')
    assert r_tract_pop.status == 'available'
    assert r_tract_pop.source_value == '1181'

    # 3. Missing and true_zero cells from fixture: CT tract 09009990000 in 2015–2019
    r_zero = by_key[('tract', '09009990000', 'total_population', '2015–2019')]
    assert r_zero.value == Decimal('0')
    assert r_zero.moe == Decimal('12')
    assert r_zero.status == 'true_zero'
    assert r_zero.source_value == '0'
    assert r_zero.boundary_vintage == '2019'

    r_miss = by_key[('tract', '09009990000', 'poverty_pct', '2015–2019')]
    assert r_miss.value is None
    assert r_miss.moe is None
    assert r_miss.status == 'missing'
    assert r_miss.source_value == '-666666666.0|-'
    assert r_miss.boundary_vintage == '2019'

    # 4. Connecticut 2023 planning region 09110 gets boundary vintage 2024
    ct_2023 = by_key[('county', '09110', 'poverty_pct', '2019–2023')]
    assert ct_2023.boundary_vintage == '2024'
    assert ct_2023.status == 'available'


def test_variable_mismatch_changed_header_and_missing_role_raise(config, files, tmp_path):
    # 1. Locator variable mismatch against current registry raises
    bad_loc_cfg = copy.deepcopy(config)
    bad_loc_cfg['measures'][1]['periods'][0]['locator']['variable'] = 'S1701_C99_999'
    with pytest.raises(ValueError, match='locator variable'):
        list(acs_profile_parser.parse(bad_loc_cfg, files, {}))

    # 2. Measure variable mismatch against current registry raises
    bad_var_cfg = copy.deepcopy(config)
    bad_var_cfg['measures'][1]['variable'] = 'S1701_C99_999'
    with pytest.raises(ValueError, match='differs from current measure variable'):
        list(acs_profile_parser.parse(bad_var_cfg, files, {}))

    # 3. Missing role raises
    incomplete_files = {k: v for k, v in files.items() if k != 'acsp2019_county_09'}
    with pytest.raises(ValueError, match='Missing required ACS profile source file roles'):
        list(acs_profile_parser.parse(config, incomplete_files, {}))

    # 4. Changed response header raises
    payload = json.loads(files['acsp2019_county_11'].read_text(encoding='utf-8'))
    payload[0] = [c if c != 'S1701_C03_001MA' else 'S1701_C03_001MA_BAD' for c in payload[0]]
    bad_hdr = tmp_path / 'bad_acsp_header.json'
    bad_hdr.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError, match='Census response header changed'):
        list(acs_profile_parser.parse(config, {**files, 'acsp2019_county_11': bad_hdr}, {}))
