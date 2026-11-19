"""Tests for CMS OM GV history parser national row extraction (parse_national)."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.area_pilot.history.parsers import cms_gv as cms_gv_parser
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.history.rows import part_digest

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'history' / 'cms_gv' / 'om_gv_sample.csv'
DECLARED_YEARS = ('2019', '2020', '2021', '2022', '2023')
MEASURES = (
    'om_beneficiaries',
    'std_payment_per_capita',
    'ip_stays_per_1000',
    'er_visits_per_1000',
    'readmission_rate',
)
EXPECTED_KEYS = {'measure_id', 'period', 'level', 'geoid', 'value', 'status', 'source_value'}

# Baseline parse() part digests captured before adding parse_national()
BASELINE_PARSE_DIGESTS = {
    'year_2019': '19b5999a587a29297e02eb9846220473fc5fca8ad89c3ceb0214d480a96b8282',
    'year_2020': 'caae2a33195c4ea35dbd961e2eb4ff15c96501744a371092ab4b00169bbef96f',
    'year_2021': '509f064b4f28763ea647a88b1d9b4cf1e0db28262d5eb8a8741ef5b0cd3667da',
    'year_2022': '237c5f10b7daff50e158fc1d211678af073eede0b881c68d11530014df1eacf3',
    'year_2023': '2437f880505475d2a119e22ba78cc56563e4b74264914de0862cdb8f1a8396e4',
}


@pytest.fixture
def config():
    return load_history_registry('cms_gv')


def test_deterministic_runs_and_sort_order(config):
    ev1, ev2 = {}, {}
    rows1 = cms_gv_parser.parse_national(config, {'gv_csv': FIXTURE}, ev1)
    rows2 = cms_gv_parser.parse_national(config, {'gv_csv': FIXTURE}, ev2)

    assert rows1 == rows2
    assert ev1 == ev2
    assert [
        (r['period'], r['measure_id']) for r in rows1
    ] == sorted((r['period'], r['measure_id']) for r in rows1)


def test_exact_counts_schema_and_evidence(config):
    evidence = {'existing_key': 'preserved'}
    rows = cms_gv_parser.parse_national(config, {'gv_csv': FIXTURE}, evidence)

    assert len(rows) == len(DECLARED_YEARS) * len(MEASURES)
    assert evidence['existing_key'] == 'preserved'
    assert evidence['national_emitted'] == {y: 5 for y in DECLARED_YEARS}

    by_year = Counter(r['period'] for r in rows)
    assert set(by_year) == set(DECLARED_YEARS)
    for year in DECLARED_YEARS:
        assert by_year[year] == 5

    seen_pairs = set()
    for row in rows:
        assert set(row.keys()) == EXPECTED_KEYS
        assert row['level'] == 'national'
        assert row['geoid'] == 'US'
        assert row['measure_id'] in MEASURES
        assert row['period'] in DECLARED_YEARS
        seen_pairs.add((row['period'], row['measure_id']))
        if row['measure_id'] == 'readmission_rate':
            assert Decimal('0') < row['value'] < Decimal('1')

    assert len(seen_pairs) == 25


def test_hand_checked_values_match_fixture_text(config):
    rows = cms_gv_parser.parse_national(config, {'gv_csv': FIXTURE}, {})
    by_key = {(r['period'], r['measure_id']): r for r in rows}

    # Exact values from om_gv_sample.csv 2019 National All row
    expected_2019 = {
        'om_beneficiaries': ('33172250', Decimal('33172250')),
        'std_payment_per_capita': ('10403.81', Decimal('10403.81')),
        'ip_stays_per_1000': ('261.5235', Decimal('261.5235')),
        'er_visits_per_1000': ('661.9618', Decimal('661.9618')),
        'readmission_rate': ('0.1812', Decimal('0.1812')),
    }
    for measure_id, (raw_text, dec_val) in expected_2019.items():
        row = by_key[('2019', measure_id)]
        assert row['value'] == dec_val
        assert isinstance(row['value'], Decimal)
        assert row['status'] == 'available'
        assert row['source_value'] == raw_text
        assert row['level'] == 'national'
        assert row['geoid'] == 'US'


def test_suppressed_blank_and_zero_national_values(config, tmp_path):
    lines = FIXTURE.read_text(encoding='utf-8-sig').splitlines()
    header = lines[0].split(',')
    idx_benes = header.index('BENES_OM_CNT')
    idx_pymt = header.index('TOT_MDCR_STDZD_PYMT_PC')
    idx_ip = header.index('IP_CVRD_STAYS_PER_1000_BENES')

    modified = [lines[0]]
    for line in lines[1:]:
        cols = line.split(',')
        if cols[0] == '2020' and cols[1] == 'National' and cols[4] == 'All':
            cols[idx_benes] = '*'
            cols[idx_pymt] = ''
            cols[idx_ip] = '0'
            modified.append(','.join(cols))
        else:
            modified.append(line)

    custom_csv = tmp_path / 'om_gv_national_statuses.csv'
    custom_csv.write_text('\n'.join(modified) + '\n', encoding='utf-8-sig')

    rows = cms_gv_parser.parse_national(config, {'gv_csv': custom_csv}, {})
    by_key = {(r['period'], r['measure_id']): r for r in rows}

    sup = by_key[('2020', 'om_beneficiaries')]
    assert sup['value'] is None
    assert sup['status'] == 'suppressed'
    assert sup['source_value'] == '*'

    miss = by_key[('2020', 'std_payment_per_capita')]
    assert miss['value'] is None
    assert miss['status'] == 'missing'
    assert miss['source_value'] == ''

    zero = by_key[('2020', 'ip_stays_per_1000')]
    assert zero['value'] == Decimal('0')
    assert zero['status'] == 'true_zero'
    assert zero['source_value'] == '0'


def test_missing_national_row_raises(config, tmp_path):
    lines = FIXTURE.read_text(encoding='utf-8-sig').splitlines()
    kept = [lines[0]] + [
        line for line in lines[1:]
        if not (line.startswith('2021,National,'))
    ]
    missing_csv = tmp_path / 'om_gv_missing_national.csv'
    missing_csv.write_text('\n'.join(kept) + '\n', encoding='utf-8-sig')

    with pytest.raises(ValueError, match='2021'):
        cms_gv_parser.parse_national(config, {'gv_csv': missing_csv}, {})


def test_duplicate_national_row_raises_and_non_all_age_ignored(config, tmp_path):
    lines = FIXTURE.read_text(encoding='utf-8-sig').splitlines()
    nat_2022 = next(line for line in lines[1:] if line.startswith('2022,National,'))

    # Exact duplicate National All row raises ValueError
    dup_csv = tmp_path / 'om_gv_dup_national.csv'
    dup_csv.write_text('\n'.join(lines + [nat_2022]) + '\n', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='2022'):
        cms_gv_parser.parse_national(config, {'gv_csv': dup_csv}, {})

    # Duplicate National All row with a different BENE_GEO_DESC also raises ValueError
    cols = nat_2022.split(',')
    cols[2] = 'United States'
    dup_desc_csv = tmp_path / 'om_gv_dup_national_desc.csv'
    dup_desc_csv.write_text('\n'.join(lines + [','.join(cols)]) + '\n', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='2022'):
        cms_gv_parser.parse_national(config, {'gv_csv': dup_desc_csv}, {})

    # Non-All age National row (<65) is ignored and does not trigger duplicate error
    age_cols = nat_2022.split(',')
    age_cols[4] = '<65'
    age_csv = tmp_path / 'om_gv_national_age.csv'
    age_csv.write_text('\n'.join(lines + [','.join(age_cols)]) + '\n', encoding='utf-8-sig')
    ev = {}
    rows = cms_gv_parser.parse_national(config, {'gv_csv': age_csv}, ev)
    assert len(rows) == 25
    assert ev['national_emitted'] == {y: 5 for y in DECLARED_YEARS}


def test_header_and_national_code_checks(config, tmp_path):
    lines = FIXTURE.read_text(encoding='utf-8-sig').splitlines()

    bad_dim_csv = tmp_path / 'bad_dim.csv'
    bad_dim_csv.write_text(
        '\n'.join([lines[0].replace('BENE_GEO_CD', 'GEO_CODE', 1)] + lines[1:]) + '\n',
        encoding='utf-8-sig',
    )
    with pytest.raises(ValueError, match='dimension columns'):
        cms_gv_parser.parse_national(config, {'gv_csv': bad_dim_csv}, {})

    bad_code_lines = [lines[0]]
    for line in lines[1:]:
        cols = line.split(',')
        if cols[0] == '2023' and cols[1] == 'National' and cols[4] == 'All':
            cols[3] = 'US'
            bad_code_lines.append(','.join(cols))
        else:
            bad_code_lines.append(line)
    bad_code_csv = tmp_path / 'bad_code.csv'
    bad_code_csv.write_text('\n'.join(bad_code_lines) + '\n', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='unexpected code'):
        cms_gv_parser.parse_national(config, {'gv_csv': bad_code_csv}, {})


def test_existing_parse_part_digests_unchanged(config):
    parts = dict(cms_gv_parser.parse(config, {'gv_csv': FIXTURE}, {}))
    assert {name: part_digest(rows) for name, rows in parts.items()} == BASELINE_PARSE_DIGESTS
