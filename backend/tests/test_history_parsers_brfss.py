"""Tests for the CDC BRFSS state prevalence history parser."""
from __future__ import annotations

import csv
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.area_pilot.history.parsers import brfss as brfss_parser
from app.area_pilot.history.parsers import load_parser
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.history.rows import part_digest, row_problems

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'history' / 'brfss' / 'brfss_2017_2022.csv'
DECLARED_YEARS = ('2017', '2018', '2019', '2020', '2021', '2022')
EXPECTED_STATES_PER_YEAR = {
    '2017': 52,
    '2018': 52,
    '2019': 51,  # NJ (34) not published by CDC in 2019
    '2020': 52,
    '2021': 51,  # FL (12) not published by CDC in 2021
    '2022': 52,
}


@pytest.fixture
def config():
    return load_history_registry('brfss')


def test_contract_and_parts_stability(config):
    module = load_parser('brfss')
    assert module is brfss_parser
    assert module.SCHEMA_VERSION == '1'

    ev1, ev2 = {}, {}
    parts1 = list(module.parse(config, {'brfss_csv': FIXTURE}, ev1))
    parts2 = list(module.parse(config, {'brfss_csv': FIXTURE}, ev2))

    names1 = [name for name, _ in parts1]
    assert names1 == [f'year_{y}' for y in DECLARED_YEARS]
    assert len(names1) == len(set(names1))
    assert parts1 == parts2
    assert ev1 == ev2
    for (_, rows1), (_, rows2) in zip(parts1, parts2):
        assert part_digest(rows1) == part_digest(rows2)


def test_exact_counts_exclusions_and_row_problems(config):
    evidence = {}
    parts = dict(brfss_parser.parse(config, {'brfss_csv': FIXTURE}, evidence))

    assert set(parts) == {f'year_{y}' for y in DECLARED_YEARS}
    assert evidence['total_rows'] == 4786
    assert evidence['emitted_total'] == 4488
    assert evidence['dropped_totals'] == {'median': 174, 'source_only': 124}
    assert evidence['dropped_locations'] == {
        '2017': {'median': 2, 'source_only': 1},
        '2018': {'median': 30, 'source_only': 15},
        '2019': {'median': 34, 'source_only': 17},
        '2020': {'median': 34, 'source_only': 17},
        '2021': {'median': 38, 'source_only': 38},
        '2022': {'median': 36, 'source_only': 36},
    }
    assert evidence['emitted_rows'] == {
        '2017': 52,
        '2018': 780,
        '2019': 867,
        '2020': 884,
        '2021': 969,
        '2022': 936,
    }

    counts = Counter()
    geoids_seen = set()
    for rows in parts.values():
        for row in rows:
            assert row_problems(row, config) == []
            assert row.level == 'state'
            assert row.uncertainty_kind == 'ci95'
            assert row.boundary_vintage == '2024'
            counts[(row.measure_id, row.period, row.level)] += 1
            geoids_seen.add(row.geoid)

    # Median (98, 99) and territory source_only (66, 78) are never stored
    assert geoids_seen.isdisjoint({'66', '78', '98', '99'})

    # Exact row count per declared (measure, period, level): 87 measure-years
    declared_pairs = [
        (m['measure_id'], p['period'])
        for m in config['measures']
        for p in m['periods']
        if p.get('available', True)
    ]
    assert len(declared_pairs) == 87
    for measure_id, period in declared_pairs:
        assert counts[(measure_id, period, 'state')] == EXPECTED_STATES_PER_YEAR[period]


def test_hand_checked_values_ci_copd_2018_and_not_available(config, tmp_path):
    parts = dict(brfss_parser.parse(config, {'brfss_csv': FIXTURE}, {}))
    by_key = {row.key: row for rows in parts.values() for row in rows}

    # 1. 2022 Alaska (02) depression with 95% CI check
    r_ak_dep = by_key[('state', '02', 'depression', '2022')]
    assert r_ak_dep.value == Decimal('20.3')
    assert r_ak_dep.low == Decimal('18.9')
    assert r_ak_dep.high == Decimal('21.7')
    assert r_ak_dep.status == 'available'
    assert r_ak_dep.source_value == '20.3'

    # 2. 2018 Alabama (01) COPD uses question_id CHCCOPD1
    copd_measure = next(m for m in config['measures'] if m['measure_id'] == 'copd')
    copd_2018_spec = next(p for p in copd_measure['periods'] if p['period'] == '2018')
    assert copd_2018_spec['locator'] == {'question_id': 'CHCCOPD1', 'response_id': 'RESP046'}

    r_al_copd_2018 = by_key[('state', '01', 'copd', '2018')]
    assert r_al_copd_2018.value == Decimal('10.3')
    assert r_al_copd_2018.low == Decimal('9.4')
    assert r_al_copd_2018.high == Decimal('11.2')
    assert r_al_copd_2018.status == 'available'
    assert r_al_copd_2018.source_value == '10.3'

    # 3. 2017 Kentucky (21) high blood pressure (_RFHYPE5) and 2020 Pennsylvania (42) dental visit (_DENVST3)
    r_ky_hbp = by_key[('state', '21', 'high_blood_pressure', '2017')]
    assert r_ky_hbp.value == Decimal('39.4')
    assert r_ky_hbp.low == Decimal('37.7')
    assert r_ky_hbp.high == Decimal('41.0')
    assert r_ky_hbp.status == 'available'

    r_pa_dent = by_key[('state', '42', 'dental_visit', '2020')]
    assert r_pa_dent.value == Decimal('68.1')
    assert r_pa_dent.low == Decimal('66.5')
    assert r_pa_dent.high == Decimal('69.8')
    assert r_pa_dent.status == 'available'

    # 4. In the fixture, the 12 CDC '*' footnoted not_available rows are on GU (66) and VI (78).
    # Verify that when Kentucky (21) or Pennsylvania (42) is footnoted '*' with blank data_value/CIs
    # (matching the fixture's '*' rows such as 2022 GU CVDSTRK3), it emits status='not_available' and value=None.
    with FIXTURE.open(newline='', encoding='utf-8-sig') as src:
        reader = csv.DictReader(src)
        fieldnames = list(reader.fieldnames or [])
        all_rows = list(reader)

    assert sum(1 for r in all_rows if r['data_value'] == '' and r['data_value_footnote_symbol'] == '*') == 12

    custom_csv = tmp_path / 'brfss_ky_pa_na.csv'
    with custom_csv.open('w', newline='', encoding='utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_rows:
            if r['year'] == '2022' and r['locationid'] in ('21', '42') and r['questionid'] == 'CVDSTRK3':
                r = dict(
                    r,
                    sample_size='',
                    data_value='',
                    confidence_limit_low='',
                    confidence_limit_high='',
                    data_value_footnote_symbol='*',
                    data_value_footnote='Prevents calculation of reliable prevalence estimate',
                )
            writer.writerow(r)

    ev_na = {}
    parts_na = dict(brfss_parser.parse(config, {'brfss_csv': custom_csv}, ev_na))
    by_key_na = {row.key: row for rows in parts_na.values() for row in rows}
    for st in ('21', '42'):
        r_na = by_key_na[('state', st, 'stroke', '2022')]
        assert r_na.value is None
        assert r_na.low is None
        assert r_na.high is None
        assert r_na.status == 'not_available'
        assert r_na.source_value == ''
        assert row_problems(r_na, config) == []
    assert ev_na['status_counts']['2022'] == {'available': 934, 'not_available': 2}


def test_question_text_change_header_change_or_unmatched_row_raises(config, tmp_path):
    with FIXTURE.open(newline='', encoding='utf-8-sig') as src:
        reader = csv.DictReader(src)
        fieldnames = list(reader.fieldnames or [])
        all_rows = list(reader)

    # 1. Question-text change in an older year stops the parser and raises ValueError
    bad_q_csv = tmp_path / 'bad_question.csv'
    with bad_q_csv.open('w', newline='', encoding='utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        for idx, r in enumerate(all_rows):
            if idx == 0:
                r = dict(r, question='Changed CDC question wording?')
            writer.writerow(r)
    with pytest.raises(ValueError, match='source question is'):
        list(brfss_parser.parse(config, {'brfss_csv': bad_q_csv}, {}))

    # 2. Changed CSV header raises ValueError
    bad_hdr_csv = tmp_path / 'bad_header.csv'
    bad_fieldnames = ['survey_year' if f == 'year' else f for f in fieldnames]
    with bad_hdr_csv.open('w', newline='', encoding='utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=bad_fieldnames)
        writer.writeheader()
    with pytest.raises(ValueError, match='BRFSS CSV header'):
        list(brfss_parser.parse(config, {'brfss_csv': bad_hdr_csv}, {}))

    # 3. Unmatched (year, question_id, response_id) row raises ValueError
    unmatched_csv = tmp_path / 'unmatched.csv'
    with unmatched_csv.open('w', newline='', encoding='utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
        writer.writerow(dict(all_rows[0], questionid='UNDECLARED_Q'))
    with pytest.raises(ValueError, match='does not match any declared'):
        list(brfss_parser.parse(config, {'brfss_csv': unmatched_csv}, {}))

    # 4. Non-Overall break_out row raises ValueError via parse_observation
    bad_bo_csv = tmp_path / 'bad_breakout.csv'
    with bad_bo_csv.open('w', newline='', encoding='utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        for idx, r in enumerate(all_rows):
            if idx == 0:
                r = dict(r, break_out='18-24')
            writer.writerow(r)
    with pytest.raises(ValueError, match='source break_out'):
        list(brfss_parser.parse(config, {'brfss_csv': bad_bo_csv}, {}))

    # 5. Duplicate (measure, year, location) raises ValueError
    dup_csv = tmp_path / 'dup.csv'
    with dup_csv.open('w', newline='', encoding='utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
        writer.writerow(all_rows[0])
    with pytest.raises(ValueError, match='Duplicate BRFSS'):
        list(brfss_parser.parse(config, {'brfss_csv': dup_csv}, {}))
