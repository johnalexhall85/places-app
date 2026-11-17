"""Tests for the HRSA Area Health Resources Files (AHRF) county history parser."""
from __future__ import annotations

import copy
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.area_pilot.history.parsers import ahrf as ahrf_parser
from app.area_pilot.history.parsers import load_parser
from app.area_pilot.history.registry import load_history_registry
from app.area_pilot.history.rows import part_digest, row_problems

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures' / 'history' / 'ahrf'
MEASURES = (
    'phys_nf_prim_care_pc_exc_rsdt_23',
    'dent_nf_fed_proflly_activ_23',
    'md_nf_psych_all_pc_23',
    'hosp_23',
    'hosp_beds_23',
)


def _build_ahrf_zip(dst_zip: Path, *, asc_bytes: bytes | None = None, sas_bytes: bytes | None = None) -> Path:
    if asc_bytes is None:
        asc_bytes = (FIXTURE_DIR / 'ahrf2022_sample.asc').read_bytes()
    if sas_bytes is None:
        sas_bytes = (FIXTURE_DIR / 'AHRF2021-2022.sas').read_bytes()
    with zipfile.ZipFile(dst_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('DATA/ahrf2022.asc', asc_bytes)
        zf.writestr('DOC/AHRF2021-2022.sas', sas_bytes)
    return dst_zip


@pytest.fixture
def config():
    return load_history_registry('ahrf')


@pytest.fixture
def files(tmp_path):
    zip_path = _build_ahrf_zip(tmp_path / 'AHRF_2021-2022.ZIP')
    return {
        'current_hp': FIXTURE_DIR / 'AHRF2025hp_sample.csv',
        'current_hf': FIXTURE_DIR / 'AHRF2025hf_sample.csv',
        'ahrf2122_zip': zip_path,
    }


def test_contract_and_parts_stability(config, files):
    module = load_parser('ahrf')
    assert module is ahrf_parser
    assert module.SCHEMA_VERSION == '1'

    ev1, ev2 = {}, {}
    parts1 = list(module.parse(config, files, ev1))
    parts2 = list(module.parse(config, files, ev2))

    names1 = [name for name, _ in parts1]
    assert names1 == [
        'current_2022',
        'ahrf2122_2015',
        'ahrf2122_2017',
        'ahrf2122_2018',
        'ahrf2122_2019',
        'ahrf2122_2020',
    ]
    assert len(names1) == len(set(names1))
    assert parts1 == parts2
    assert ev1 == ev2
    for (_, rows1), (_, rows2) in zip(parts1, parts2):
        assert part_digest(rows1) == part_digest(rows2)


def test_exact_counts_and_row_problems(config, files):
    evidence = {}
    parts = dict(ahrf_parser.parse(config, files, evidence))

    expected_part_counts = {
        'current_2022': 50,      # 10 counties * 5 measures
        'ahrf2122_2015': 30,     # 10 counties * 3 measures (psych, hosp, hosp_beds)
        'ahrf2122_2017': 20,     # 10 counties * 2 measures (phys, dent)
        'ahrf2122_2018': 20,     # 10 counties * 2 measures (phys, dent)
        'ahrf2122_2019': 20,     # 10 counties * 2 measures (phys, dent)
        'ahrf2122_2020': 50,     # 10 counties * 5 measures
    }
    assert {k: len(v) for k, v in parts.items()} == expected_part_counts
    assert evidence['emitted_rows'] == expected_part_counts
    assert evidence['emitted_total'] == 190
    assert evidence['current_2022']['kept_counties'] == 10
    assert evidence['ahrf2122']['kept_counties'] == 10
    assert evidence['ahrf2122']['sas_dot_missing_by_year'] == {
        '2015': 6,
        '2017': 4,
        '2018': 4,
        '2019': 4,
        '2020': 10,
    }

    counts = Counter()
    for rows in parts.values():
        for row in rows:
            assert row_problems(row, config) == []
            assert row.level == 'county'
            assert row.uncertainty_kind == 'none'
            assert row.low is None and row.high is None and row.moe is None
            counts[(row.measure_id, row.period, row.level)] += 1

    for m in config['measures']:
        mid = m['measure_id']
        for p in m['periods']:
            assert counts[(mid, p['period'], 'county')] == 10


def test_hand_checked_fixed_width_and_csv_values_ct_vintages_and_missing(config, files):
    parts = dict(ahrf_parser.parse(config, files, {}))
    by_key = {row.key: row for rows in parts.values() for row in rows}

    asc_lines = (FIXTURE_DIR / 'ahrf2022_sample.asc').read_text(encoding='latin-1').splitlines()
    lines_by_fips = {line[1:6]: line for line in asc_lines}

    # 1. Hand-checked fixed-width value #1: Connecticut 09001 in 2020 for primary care physicians (f1467520 @567, width 4)
    loc_phys_2020 = config['_index'][('phys_nf_prim_care_pc_exc_rsdt_23', '2020')][1]['locator']
    raw_phys_09001 = lines_by_fips['09001'][
        loc_phys_2020['start'] - 1 : loc_phys_2020['start'] - 1 + loc_phys_2020['width']
    ]
    assert raw_phys_09001 == '0918'
    r_phys_09001 = by_key[('county', '09001', 'phys_nf_prim_care_pc_exc_rsdt_23', '2020')]
    assert r_phys_09001.value == Decimal(int(raw_phys_09001.strip())) == Decimal('918')
    assert r_phys_09001.status == 'available'
    assert r_phys_09001.source_value == '0918'
    assert r_phys_09001.boundary_vintage == '2020'

    # 2. Hand-checked fixed-width value #2: Kanawha County, WV 54039 in 2015 for hospital beds (f0892115 @12719, width 6)
    loc_beds_2015 = config['_index'][('hosp_beds_23', '2015')][1]['locator']
    raw_beds_54039 = lines_by_fips['54039'][
        loc_beds_2015['start'] - 1 : loc_beds_2015['start'] - 1 + loc_beds_2015['width']
    ]
    assert raw_beds_54039 == '001284'
    r_beds_54039 = by_key[('county', '54039', 'hosp_beds_23', '2015')]
    assert r_beds_54039.value == Decimal(int(raw_beds_54039.strip())) == Decimal('1284')
    assert r_beds_54039.status == 'available'
    assert r_beds_54039.source_value == '001284'
    assert r_beds_54039.boundary_vintage == '2020'

    # 3. Current CSV values and Connecticut 09110 vintage 2024 + blank cell becoming missing
    r_ct_09110 = by_key[('county', '09110', 'phys_nf_prim_care_pc_exc_rsdt_23', '2022')]
    assert r_ct_09110.value is None
    assert r_ct_09110.status == 'missing'
    assert r_ct_09110.source_value == ''
    assert r_ct_09110.boundary_vintage == '2024'

    # Current CSV ignores *_23 columns (e.g. 01001 has phys_23=22, phys_22=25)
    r_01001_2022 = by_key[('county', '01001', 'phys_nf_prim_care_pc_exc_rsdt_23', '2022')]
    assert r_01001_2022.value == Decimal('25')
    assert r_01001_2022.status == 'available'
    assert r_01001_2022.source_value == '25'
    assert r_01001_2022.boundary_vintage == '2024'

    # True zero in CSV (02063 md_nf_psych_all_pc_22 = 0) and in ASCII (01001 md_nf_psych_all_pc 2015 = 0000)
    r_zero_csv = by_key[('county', '02063', 'md_nf_psych_all_pc_23', '2022')]
    assert r_zero_csv.value == Decimal('0')
    assert r_zero_csv.status == 'true_zero'
    assert r_zero_csv.source_value == '0'

    r_zero_asc = by_key[('county', '01001', 'md_nf_psych_all_pc_23', '2015')]
    assert r_zero_asc.value == Decimal('0')
    assert r_zero_asc.status == 'true_zero'
    assert r_zero_asc.source_value == '0000'


def test_blank_fixed_width_cell_and_dropped_000_fips(config, files, tmp_path):
    # Modify a copy of the ASCII and CSV files:
    # - Add a state/US row ending in 000 ('01000') to both CSVs and the ASCII file
    # - Replace one fixed-width field on 01001 with all spaces ('    ') so a blank fixed-width cell becomes missing
    asc_text = (FIXTURE_DIR / 'ahrf2022_sample.asc').read_text(encoding='latin-1')
    asc_lines = asc_text.splitlines()
    line0 = asc_lines[0]
    # Replace f1467520 (@567, width 4) with 4 spaces
    line0_blank = line0[:566] + '    ' + line0[570:]
    # Create a state total line with FIPS '01000' at @2 width 5
    line_000 = line0[:1] + '01000' + line0[6:]
    custom_asc = ('\n'.join([line0_blank, *asc_lines[1:], line_000]) + '\n').encode('latin-1')

    custom_zip = _build_ahrf_zip(tmp_path / 'custom_ahrf.zip', asc_bytes=custom_asc)

    hp_text = (FIXTURE_DIR / 'AHRF2025hp_sample.csv').read_text(encoding='utf-8-sig')
    hf_text = (FIXTURE_DIR / 'AHRF2025hf_sample.csv').read_text(encoding='utf-8-sig')
    custom_hp = tmp_path / 'hp.csv'
    custom_hf = tmp_path / 'hf.csv'
    custom_hp.write_text(hp_text.strip() + '\n01000,100,99,50,10\n', encoding='utf-8')
    custom_hf.write_text(hf_text.strip() + '\n01000,10,500,10\n', encoding='utf-8')

    ev = {}
    parts = dict(
        ahrf_parser.parse(
            config,
            {'current_hp': custom_hp, 'current_hf': custom_hf, 'ahrf2122_zip': custom_zip},
            ev,
        )
    )
    by_key = {r.key: r for rows in parts.values() for r in rows}

    # 01000 is dropped everywhere and counted in evidence
    assert all(r.geoid != '01000' for rows in parts.values() for r in rows)
    assert ev['current_2022']['dropped_state_or_us_000'] == {'current_hp': 1, 'current_hf': 1}
    assert ev['ahrf2122']['dropped_state_or_us_000'] == 1

    # Blank fixed-width cell on 01001 in 2020 becomes missing
    r_blank = by_key[('county', '01001', 'phys_nf_prim_care_pc_exc_rsdt_23', '2020')]
    assert r_blank.value is None
    assert r_blank.status == 'missing'
    assert r_blank.source_value == ''
    assert row_problems(r_blank, config) == []


def test_shifted_start_changed_sas_label_and_changed_csv_header_raise(config, files, tmp_path):
    # 1. Deliberately shifted start in config raises
    shifted_cfg = copy.deepcopy(config)
    shifted_cfg['measures'][0]['periods'][1]['locator']['start'] = 568  # was 567
    with pytest.raises(ValueError, match=r'AHRF SAS layout for f1467520 is \(@567, 4\.\), expected \(@568, 4\.\)'):
        list(ahrf_parser.parse(shifted_cfg, files, {}))

    # 2. Changed label in a copy of the .sas raises
    sas_text = (FIXTURE_DIR / 'AHRF2021-2022.sas').read_text(encoding='latin-1')
    bad_sas = sas_text.replace('Phys,Primary Care, Patient Care', 'Phys,Primary Care,CHANGED LABEL', 1).encode('latin-1')
    bad_sas_zip = _build_ahrf_zip(tmp_path / 'bad_sas.zip', sas_bytes=bad_sas)
    with pytest.raises(ValueError, match='AHRF SAS layout comment for f1467520'):
        list(ahrf_parser.parse(config, {**files, 'ahrf2122_zip': bad_sas_zip}, {}))

    # 3. Changed CSV header raises
    hp_text = (FIXTURE_DIR / 'AHRF2025hp_sample.csv').read_text(encoding='utf-8-sig')
    bad_hp = tmp_path / 'bad_hp.csv'
    bad_hp.write_text(hp_text.replace('dent_nf_fed_proflly_activ_22', 'dent_renamed_22', 1), encoding='utf-8')
    with pytest.raises(ValueError, match='missing required columns'):
        list(ahrf_parser.parse(config, {**files, 'current_hp': bad_hp}, {}))
