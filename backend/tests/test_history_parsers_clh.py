"""Tests for the AHRQ Community-Level Health (CLH) v2.0 history parser."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

import openpyxl
import pytest

from app.area_pilot.history.parsers import clh as clh_parser
from app.area_pilot.history.parsers import load_parser
from app.area_pilot.history.rows import part_digest, row_problems

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures' / 'history' / 'clh'
REGISTRY_DIR = Path(__file__).resolve().parents[1] / 'app' / 'area_pilot' / 'registry' / 'history'
ACS_MEASURES = (
    'ACS_PCT_HH_BROADBAND_ANY',
    'ACS_PCT_HU_NO_VEH',
    'ACS_PCT_RENTER_HU_COST_30PCT',
)
CCBP_MEASURES = (
    'CCBP_SOGS_RATE',
    'CCBP_FCRSC_RATE',
)
ALL_MEASURES = (*ACS_MEASURES, *CCBP_MEASURES)


@pytest.fixture
def config():
    path = REGISTRY_DIR / 'clh.json'
    if not path.is_file():
        path = REGISTRY_DIR / 'clh.json.draft'
    with path.open(encoding='utf-8') as handle:
        cfg = json.load(handle)
    cfg['_index'] = {
        (m['measure_id'], p['period']): (m, p)
        for m in cfg['measures']
        for p in m['periods']
    }
    return cfg


@pytest.fixture
def files():
    return {
        'clh2018_county': FIXTURE_DIR / 'clh_2018_county_sample.xlsx',
        'clh2022_county': FIXTURE_DIR / 'clh_2022_county_sample.xlsx',
    }


def _build_workbook(
    dst: Path,
    *,
    sheet_names: tuple[str, str] = ('Layout', 'Data'),
    layout_rows: list[tuple] | None = None,
    data_headers: list[str] | None = None,
    data_rows: list[list] | None = None,
) -> Path:
    wb = openpyxl.Workbook()
    ws_layout = wb.active
    ws_layout.title = sheet_names[0]
    default_layout = [
        ('name', 'label', 'type', 'length', 'format'),
        ('ACS_PCT_HH_BROADBAND_ANY', 'Percentage of households with broadband of any type', 'num', 8, '6.2'),
        ('ACS_PCT_HU_NO_VEH', 'Percentage of housing units with no vehicle available', 'num', 8, '6.2'),
        (
            'ACS_PCT_RENTER_HU_COST_30PCT',
            'Percentage of renter-occupied housing units with rent equal to 30 percent or more of household income',
            'num',
            8,
            '6.2',
        ),
        (
            'CCBP_SOGS_RATE',
            'Total number of supermarkets and other grocery (except convenience) stores per 1,000 people',
            'num',
            8,
            '12.2',
        ),
        (
            'CCBP_FCRSC_RATE',
            'Total number of fitness centers and recreational sports centers per 1,000 people',
            'num',
            8,
            '12.2',
        ),
        ('UNSELECTED_VAR', 'Unselected extra column', 'num', 8, '6.2'),
    ]
    for r in layout_rows if layout_rows is not None else default_layout:
        ws_layout.append(list(r))

    ws_data = wb.create_sheet(sheet_names[1])
    hdrs = data_headers if data_headers is not None else [
        'YEAR',
        'COUNTYFIPS',
        'ACS_PCT_HH_BROADBAND_ANY',
        'ACS_PCT_HU_NO_VEH',
        'ACS_PCT_RENTER_HU_COST_30PCT',
        'CCBP_SOGS_RATE',
        'CCBP_FCRSC_RATE',
        'UNSELECTED_VAR',
    ]
    ws_data.append(hdrs)
    rows = data_rows if data_rows is not None else [
        [2018, '09001', 87.09, 7.66, 55.17, 0.23, 0.25, 999.0],
        [2018, '10001', 83.34, 6.52, 54.62, 0.15, 0.12, 888.0],
    ]
    for r in rows:
        ws_data.append(list(r))

    wb.save(dst)
    wb.close()
    return dst


def test_contract_and_parts_stability(config, files):
    module = load_parser('clh')
    assert module is clh_parser
    assert module.SCHEMA_VERSION == '1'

    ev1, ev2 = {}, {}
    parts1 = list(module.parse(config, files, ev1))
    parts2 = list(module.parse(config, files, ev2))

    names1 = [name for name, _ in parts1]
    assert names1 == ['y2018_county', 'y2022_county']
    assert len(names1) == len(set(names1))
    assert parts1 == parts2
    assert ev1 == ev2
    for (_, rows1), (_, rows2) in zip(parts1, parts2):
        assert part_digest(rows1) == part_digest(rows2)


def test_exact_counts_per_measure_period_level_and_row_problems(config, files):
    evidence = {}
    parts = dict(clh_parser.parse(config, files, evidence))

    assert set(parts) == {'y2018_county', 'y2022_county'}
    assert len(parts['y2018_county']) == 55   # 11 counties (8 CT + 3 DE) * 5 measures
    assert len(parts['y2022_county']) == 100  # 20 rows (8 former CT + 9 planning regions + 3 DE) * 5 measures
    assert evidence['source_row_counts'] == {'clh2018_county': 11, 'clh2022_county': 20}
    assert evidence['dropped_territory_rows'] == {'clh2018_county': 0, 'clh2022_county': 0}
    assert evidence['status_counts'] == {
        'y2018_county': {'available': 55},
        'y2022_county': {'available': 60, 'missing': 40},
    }
    assert evidence['emitted_rows'] == {'y2018_county': 55, 'y2022_county': 100}
    assert evidence['emitted_total'] == 155

    counts = Counter()
    status_by_measure_period = Counter()
    for rows in parts.values():
        for row in rows:
            assert row_problems(row, config) == []
            assert row.level == 'county'
            assert row.uncertainty_kind == 'none'
            assert row.low is None and row.high is None and row.moe is None
            counts[(row.measure_id, row.period, row.level)] += 1
            status_by_measure_period[(row.measure_id, row.period, row.status)] += 1

    for mid in ACS_MEASURES:
        assert counts[(mid, '2014–2018', 'county')] == 11
        assert status_by_measure_period[(mid, '2014–2018', 'available')] == 11
        assert counts[(mid, '2018–2022', 'county')] == 20
        assert status_by_measure_period[(mid, '2018–2022', 'available')] == 12
        assert status_by_measure_period[(mid, '2018–2022', 'missing')] == 8

    for mid in CCBP_MEASURES:
        assert counts[(mid, '2018', 'county')] == 11
        assert status_by_measure_period[(mid, '2018', 'available')] == 11
        assert counts[(mid, '2022', 'county')] == 20
        assert status_by_measure_period[(mid, '2022', 'available')] == 12
        assert status_by_measure_period[(mid, '2022', 'missing')] == 8


def test_hand_checked_values_ct_vintages_and_missing_former_counties(config, files):
    parts = dict(clh_parser.parse(config, files, {}))
    by_key = {row.key: row for rows in parts.values() for row in rows}

    # 1. Hand-checked 2022 CT planning region 09110: ACS_PCT_HU_NO_VEH = 9.51, vintage 2024
    r_09110 = by_key[('county', '09110', 'ACS_PCT_HU_NO_VEH', '2018–2022')]
    assert r_09110.value == Decimal('9.51')
    assert r_09110.status == 'available'
    assert r_09110.source_value == '9.51'
    assert r_09110.boundary_vintage == '2024'

    # 2. Hand-checked 2018 Delaware county (10001 Kent County, DE): vintage 2020
    r_de_acs = by_key[('county', '10001', 'ACS_PCT_HH_BROADBAND_ANY', '2014–2018')]
    assert r_de_acs.value == Decimal('83.34')
    assert r_de_acs.status == 'available'
    assert r_de_acs.source_value == '83.34'
    assert r_de_acs.boundary_vintage == '2020'

    r_de_ccbp = by_key[('county', '10001', 'CCBP_SOGS_RATE', '2018')]
    assert r_de_ccbp.value == Decimal('0.15')
    assert r_de_ccbp.status == 'available'
    assert r_de_ccbp.source_value == '0.15'
    assert r_de_ccbp.boundary_vintage == '2020'

    # 3. 2018 Connecticut 09001 row gets vintage 2020
    r_2018_09001 = by_key[('county', '09001', 'ACS_PCT_HU_NO_VEH', '2014–2018')]
    assert r_2018_09001.value == Decimal('7.66')
    assert r_2018_09001.status == 'available'
    assert r_2018_09001.source_value == '7.66'
    assert r_2018_09001.boundary_vintage == '2020'

    # 4. 2022 former Connecticut county (09001..09015) is stored as missing with vintage 2024
    for old_ct in ('09001', '09003', '09005', '09007', '09009', '09011', '09013', '09015'):
        r_miss_acs = by_key[('county', old_ct, 'ACS_PCT_HU_NO_VEH', '2018–2022')]
        assert r_miss_acs.value is None
        assert r_miss_acs.status == 'missing'
        assert r_miss_acs.source_value == ''
        assert r_miss_acs.boundary_vintage == '2024'

        r_miss_ccbp = by_key[('county', old_ct, 'CCBP_SOGS_RATE', '2022')]
        assert r_miss_ccbp.value is None
        assert r_miss_ccbp.status == 'missing'
        assert r_miss_ccbp.source_value == ''
        assert r_miss_ccbp.boundary_vintage == '2024'


def test_ccbp_measures_produce_no_tract_rows_and_territories_dropped(config, tmp_path):
    # Build a 2018 county and 2018 tract workbook including territory prefixes (60, 66, 69, 78) and a true_zero cell
    county_xlsx = _build_workbook(
        tmp_path / 'clh_2018_county.xlsx',
        data_rows=[
            [2018, '09001', 87.09, 0.0, 55.17, 0.23, 0.25, 123.0],
            [2018, '60010', 50.0, 10.0, 30.0, 0.1, 0.1, 1.0],
            [2018, '66010', None, None, None, None, None, None],
            [2018, '69110', 60.0, 12.0, 40.0, 0.2, 0.1, 2.0],
            [2018, '78010', 70.0, 15.0, 45.0, 0.3, 0.2, 3.0],
        ],
    )
    tract_xlsx = _build_workbook(
        tmp_path / 'clh_2018_tract.xlsx',
        data_headers=[
            'YEAR',
            'COUNTYFIPS',
            'TRACTFIPS',
            'ACS_PCT_HH_BROADBAND_ANY',
            'ACS_PCT_HU_NO_VEH',
            'ACS_PCT_RENTER_HU_COST_30PCT',
            'CCBP_SOGS_RATE',
            'CCBP_FCRSC_RATE',
            'UNSELECTED_VAR',
        ],
        data_rows=[
            [2018, '09001', '09001010101', 91.25, 4.12, 42.5, 0.99, 0.88, 50.0],
            [2018, '10001', '10001040100', 84.5, None, 49.0, 0.77, 0.66, 60.0],
            [2018, '60050', '60050951203', None, None, None, None, None, None],
            [2018, '66010', '66010950300', 75.0, 8.0, 35.0, 0.1, 0.1, 10.0],
            [2018, '69110', '69110000200', 65.0, 9.0, 38.0, 0.1, 0.1, 10.0],
            [2018, '78010', '78010970100', 72.0, 11.0, 41.0, 0.1, 0.1, 10.0],
        ],
    )

    evidence = {}
    parts = dict(
        clh_parser.parse(
            config,
            {'clh2018_county': county_xlsx, 'clh2018_tract': tract_xlsx},
            evidence,
        )
    )

    assert set(parts) == {'y2018_county', 'y2018_tract'}
    # County: 1 kept county * 5 measures = 5 rows; 4 territories dropped
    assert len(parts['y2018_county']) == 5
    # Tract: 2 kept tracts * 3 ACS measures = 6 rows; 0 CCBP tract rows; 4 territories dropped
    assert len(parts['y2018_tract']) == 6
    assert all(r.measure_id in ACS_MEASURES for r in parts['y2018_tract'])
    assert all(r.measure_id not in CCBP_MEASURES for r in parts['y2018_tract'])
    assert all(r.boundary_vintage == '2019' for r in parts['y2018_tract'])
    assert all(row_problems(r, config) == [] for rows in parts.values() for r in rows)

    assert evidence['dropped_territory_rows'] == {'clh2018_county': 4, 'clh2018_tract': 4}
    assert evidence['dropped_territories_by_prefix'] == {
        'clh2018_county': {'60': 1, '66': 1, '69': 1, '78': 1},
        'clh2018_tract': {'60': 1, '66': 1, '69': 1, '78': 1},
    }

    by_key = {r.key: r for rows in parts.values() for r in rows}
    r_zero = by_key[('county', '09001', 'ACS_PCT_HU_NO_VEH', '2014–2018')]
    assert r_zero.value == Decimal('0')
    assert r_zero.status == 'true_zero'
    assert r_zero.source_value == '0'


def test_layout_change_wrong_year_bad_header_formula_and_tract_mismatch_raise(config, tmp_path):
    # 1. Layout label change raises
    bad_label_xlsx = _build_workbook(
        tmp_path / 'bad_label.xlsx',
        layout_rows=[
            ('name', 'label', 'type', 'length', 'format'),
            ('ACS_PCT_HH_BROADBAND_ANY', 'CHANGED LABEL', 'num', 8, '6.2'),
            ('ACS_PCT_HU_NO_VEH', 'Percentage of housing units with no vehicle available', 'num', 8, '6.2'),
            (
                'ACS_PCT_RENTER_HU_COST_30PCT',
                'Percentage of renter-occupied housing units with rent equal to 30 percent or more of household income',
                'num',
                8,
                '6.2',
            ),
            (
                'CCBP_SOGS_RATE',
                'Total number of supermarkets and other grocery (except convenience) stores per 1,000 people',
                'num',
                8,
                '12.2',
            ),
            (
                'CCBP_FCRSC_RATE',
                'Total number of fitness centers and recreational sports centers per 1,000 people',
                'num',
                8,
                '12.2',
            ),
        ],
    )
    with pytest.raises(ValueError, match='layout changed: ACS_PCT_HH_BROADBAND_ANY'):
        list(clh_parser.parse(config, {'clh2018_county': bad_label_xlsx}, {}))

    # 2. Wrong YEAR raises
    wrong_year_xlsx = _build_workbook(
        tmp_path / 'wrong_year.xlsx',
        data_rows=[[2019, '09001', 87.09, 7.66, 55.17, 0.23, 0.25, 1.0]],
    )
    with pytest.raises(ValueError, match='Invalid CLH clh2018_county year or GEOID'):
        list(clh_parser.parse(config, {'clh2018_county': wrong_year_xlsx}, {}))

    # 3. Changed or duplicate Data header raises
    bad_hdr_xlsx = _build_workbook(
        tmp_path / 'bad_hdr.xlsx',
        data_headers=[
            'YEAR',
            'COUNTYFIPS',
            'ACS_PCT_HH_BROADBAND_ANY_RENAMED',
            'ACS_PCT_HU_NO_VEH',
            'ACS_PCT_RENTER_HU_COST_30PCT',
            'CCBP_SOGS_RATE',
            'CCBP_FCRSC_RATE',
            'UNSELECTED_VAR',
        ],
    )
    with pytest.raises(ValueError, match='Data headers invalid'):
        list(clh_parser.parse(config, {'clh2018_county': bad_hdr_xlsx}, {}))

    # 4. Formula cell raises
    formula_xlsx = _build_workbook(
        tmp_path / 'formula.xlsx',
        data_rows=[[2018, '09001', '=80+7.09', 7.66, 55.17, 0.23, 0.25, 1.0]],
    )
    with pytest.raises(ValueError, match='Formula in CLH'):
        list(clh_parser.parse(config, {'clh2018_county': formula_xlsx}, {}))

    # 5. Tract COUNTYFIPS != TRACTFIPS[:5] raises
    bad_tract_xlsx = _build_workbook(
        tmp_path / 'bad_tract.xlsx',
        data_headers=[
            'YEAR',
            'COUNTYFIPS',
            'TRACTFIPS',
            'ACS_PCT_HH_BROADBAND_ANY',
            'ACS_PCT_HU_NO_VEH',
            'ACS_PCT_RENTER_HU_COST_30PCT',
        ],
        data_rows=[[2018, '09003', '09001010101', 91.25, 4.12, 42.5]],
    )
    with pytest.raises(ValueError, match='tract parent county mismatch'):
        list(clh_parser.parse(config, {'clh2018_tract': bad_tract_xlsx}, {}))

    # 6. Duplicate GEOID raises
    dup_geoid_xlsx = _build_workbook(
        tmp_path / 'dup_geoid.xlsx',
        data_rows=[
            [2018, '09001', 87.09, 7.66, 55.17, 0.23, 0.25, 1.0],
            [2018, '09001', 87.09, 7.66, 55.17, 0.23, 0.25, 1.0],
        ],
    )
    with pytest.raises(ValueError, match='Duplicate CLH clh2018_county county GEOID: 09001'):
        list(clh_parser.parse(config, {'clh2018_county': dup_geoid_xlsx}, {}))
