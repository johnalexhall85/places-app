"""Unit tests for FEMA NRI v1.20 ZIP parsing, status rules, classification, lifecycle, API, and MCP."""
import copy
import zipfile
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot import fema_nri_area, fema_nri_area_api, fema_nri_area_cli, lookup
from app.area_pilot.fema_nri_area import (boundary_without_source, classify, fetch, load_registry,
                                          observation_values, parse_value, parse_zip, range_problems,
                                          retrieve, selected_fields_for_level, semantic_sha)
from app.area_pilot.source import same_label_revision
from app.demo_access.middleware import _is_public_path
from app.mcp_server import config as mcp_config

CONFIG = load_registry()
STATE_HEADER = ['OID_', 'NRI_ID', 'STATE', 'STATEABBRV', 'STATEFIPS', 'EAL_SCORE', 'EAL_RATNG', 'EAL_VALT', 'EXTRA_COL', 'NRI_VER']
COUNTY_HEADER = [
    'OID_', 'NRI_ID', 'STATE', 'STATEABBRV', 'STATEFIPS', 'COUNTY', 'COUNTYTYPE', 'COUNTYFIPS', 'STCOFIPS',
    'RISK_SCORE', 'RISK_RATNG', 'RISK_SPCTL', 'EAL_SCORE', 'EAL_RATNG', 'EAL_SPCTL', 'EAL_VALT',
    'SOVI_SCORE', 'SOVI_RATNG', 'SOVI_SPCTL', 'RESL_SCORE', 'RESL_RATNG', 'RESL_SPCTL', 'CRF_VALUE',
    'UNUSED_HAZARD_COL', 'NRI_VER',
]
TRACT_HEADER = [
    'OID_', 'NRI_ID', 'STATE', 'STATEABBRV', 'STATEFIPS', 'COUNTY', 'COUNTYTYPE', 'COUNTYFIPS', 'STCOFIPS',
    'TRACT', 'TRACTFIPS',
    'RISK_SCORE', 'RISK_RATNG', 'RISK_SPCTL', 'EAL_SCORE', 'EAL_RATNG', 'EAL_SPCTL', 'EAL_VALT',
    'SOVI_SCORE', 'SOVI_RATNG', 'SOVI_SPCTL', 'RESL_SCORE', 'RESL_RATNG', 'RESL_SPCTL', 'CRF_VALUE',
    'UNUSED_HAZARD_COL', 'NRI_VER',
]


def make_test_config():
    cfg = copy.deepcopy(CONFIG)
    for lvl, hdr in (('state', STATE_HEADER), ('county', COUNTY_HEADER), ('tract', TRACT_HEADER)):
        cfg['source_archives'][lvl]['sha256'] = ''
        cfg['source_archives'][lvl]['expected_column_count'] = len(hdr)
        cfg['source_archives'][lvl]['expected_header_sha256'] = ''
    return cfg


TEST = make_test_config()


def write_zip(path, csv_name, header, rows):
    lines = [','.join(header), *(','.join(f'"{c}"' if ',' in c else c for c in r) for r in rows)]
    content = '\n'.join(lines) + '\n'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(csv_name, content.encode('utf-8-sig'))
    return path


def state_row(fips='01', score='62.500000000000000', rating='Relatively Moderate', valt='2505515599.08429', ver='December 2025'):
    return ['1', f'S{fips}', 'Alabama', 'AL', fips, score, rating, valt, 'ignored', ver]


def county_row(fips='01001', risk='57.569974', risk_r='Relatively Low', risk_sp='57.569974',
               eal='59.870049', eal_r='Relatively Low', eal_sp='56.716418', valt='19756570.05085',
               sovi='38.040712', sovi_r='Relatively Low', sovi_sp='9.701493',
               resl='55.120865', resl_r='Relatively Moderate', resl_sp='76.119403',
               crf='1.038181', ver='December 2025'):
    return ['1', f'C{fips}', 'Alabama', 'AL', fips[:2], 'Autauga', 'County', fips[2:], fips,
            risk, risk_r, risk_sp, eal, eal_r, eal_sp, valt,
            sovi, sovi_r, sovi_sp, resl, resl_r, resl_sp, crf, 'ignored', ver]


def tract_row(fips='01001020100', risk='16.48532', risk_r='Very Low', risk_sp='16.48532',
              eal='13.86429', eal_r='Very Low', eal_sp='6.75958', valt='615505.33384',
              sovi='56.01256', sovi_r='Relatively Moderate', sovi_sp='37.29993',
              resl='41.91447', resl_r='Relatively Moderate', resl_sp='43.00626',
              crf='1.18968', ver='December 2025'):
    return ['1', f'T{fips}', 'Alabama', 'AL', fips[:2], 'Autauga', 'County', fips[2:5], fips[:5], fips[5:], fips,
            risk, risk_r, risk_sp, eal, eal_r, eal_sp, valt,
            sovi, sovi_r, sovi_sp, resl, resl_r, resl_sp, crf, 'ignored', ver]


# ---------------------------------------------------------------- registry & MCP contract

def test_registry_and_mcp_contract():
    assert CONFIG['dataset_id'] == 'fema_nri_v120'
    assert CONFIG['geographies'] == ['state', 'county', 'tract']
    assert CONFIG['observation_period'] == 'NRI v1.20 (December 2025)'
    assert not CONFIG['refresh_policy']['auto_publish'] and CONFIG['aggregation_method'] == 'none'
    by_id = {m['measure_id']: m for m in CONFIG['measures']}
    assert list(by_id) == fema_nri_area.MEASURE_IDS
    assert by_id['eal_score']['geographies'] == ['state', 'county', 'tract']
    assert by_id['eal_valt']['geographies'] == ['state', 'county', 'tract']
    for mid in ('risk_score', 'risk_spctl', 'eal_spctl', 'sovi_score', 'sovi_spctl', 'resl_score', 'resl_spctl', 'crf_value'):
        assert by_id[mid]['geographies'] == ['county', 'tract']
    assert by_id['resl_score']['direction'] == 'higher_better'
    assert by_id['resl_spctl']['direction'] == 'higher_better'
    assert by_id['risk_score']['direction'] == 'higher_worse'
    assert by_id['eal_valt']['legend_breaks']['state'] != by_id['eal_valt']['legend_breaks']['county']
    assert by_id['eal_valt']['legend_breaks']['county'] != by_id['eal_valt']['legend_breaks']['tract']
    assert len(CONFIG['limitations']) == 6
    assert fema_nri_area_api.LIMITATIONS == CONFIG['limitations']

    comp = lookup.comparability('fema_nri')
    assert comp['state_marker_levels'] == [] and comp['national_marker_levels'] == []
    assert comp['shared_axis_rule'] == 'same_product_measure_and_level_only'

    assert 'fema_nri' in mcp_config.PUBLIC_PRODUCTS
    assert any('higher community resilience is better' in r for r in mcp_config.RULES)
    assert any('State-ranked SVI values compare areas only within one state.' in r for r in mcp_config.RULES)


# ---------------------------------------------------------------- parsing & status mapping

def test_parse_value_status_rules_including_paired_blank_spctl():
    by_id = {m['measure_id']: m for m in CONFIG['measures']}
    assert parse_value('', by_id['risk_score']) == (None, 'not_available')
    assert parse_value('0', by_id['eal_valt']) == (Decimal('0.0000'), 'true_zero')
    assert parse_value('0.000000000000000', by_id['eal_valt']) == (Decimal('0.0000'), 'true_zero')
    # Paired *_SCORE blank forces *_SPCTL=0 to not_available!
    assert parse_value('0.000000000000000', by_id['sovi_spctl'], paired_score_raw='') == (None, 'not_available')
    assert parse_value('0', by_id['resl_spctl'], paired_score_raw='') == (None, 'not_available')
    assert parse_value('', by_id['risk_spctl'], paired_score_raw='') == (None, 'not_available')
    # Rounding to Numeric(20, 4) matches PostgreSQL ROUND_HALF_UP.
    assert parse_value('19756570.050850827', by_id['eal_valt']) == (Decimal('19756570.0509'), 'available')
    assert parse_value('62.500000000000000', by_id['eal_score']) == (Decimal('62.5000'), 'available')
    for bad in ('-1', '-0.01', 'NA', 'null', '*', '1e5'):
        with pytest.raises(ValueError):
            parse_value(bad, by_id['risk_score'])
    assert range_problems(Decimal('100.0000'), by_id['risk_score']) == []
    assert range_problems(Decimal('101.0000'), by_id['risk_score']) == ['outside_documented_scale']


def test_parse_zip_reads_in_memory_stages_selected_fields_only_and_handles_ratings(tmp_path):
    s_zip = write_zip(tmp_path / 'NRI_Table_States.zip', 'NRI_Table_States.csv', STATE_HEADER, [state_row('01')])
    c_zip = write_zip(tmp_path / 'NRI_Table_Counties.zip', 'NRI_Table_Counties.csv', COUNTY_HEADER, [
        county_row('01001'),
        county_row('72001', risk='', risk_r='Insufficient Data', risk_sp='',
                   sovi='', sovi_r='Data Unavailable', sovi_sp='0.000000000000000',
                   resl='', resl_r='Data Unavailable', resl_sp='0.000000000000000', crf=''),
    ])
    t_zip = write_zip(tmp_path / 'NRI_Table_CensusTracts.zip', 'NRI_Table_CensusTracts.csv', TRACT_HEADER, [
        tract_row('01001020100', risk='0.0214', risk_r='', valt='0.000000000000000', eal_r='No Expected Annual Losses'),
    ])

    records, stats, files, prov = retrieve(TEST, tmp_path)
    # No CSVs extracted to disk!
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        'NRI_Table_CensusTracts.zip', 'NRI_Table_Counties.zip', 'NRI_Table_States.zip']
    assert prov['archive_only'] is True
    assert stats['row_counts'] == {'state': 1, 'county': 2, 'tract': 1}
    assert {f['role'] for f in files} == {'nri_state_zip', 'nri_county_zip', 'nri_tract_zip'}
    # Only identifiers + selected fields are staged in record (EXTRA_COL / UNUSED_HAZARD_COL excluded).
    assert set(records[('state', '01')]) == set(selected_fields_for_level(TEST, 'state'))
    assert 'EXTRA_COL' not in records[('state', '01')]
    assert 'UNUSED_HAZARD_COL' not in records[('county', '01001')]

    # Check Puerto Rico county where SOVI/RESL scores are blank and SPCTL is 0.
    pr_obs = {v['measure']['measure_id']: v for v in observation_values(records[('county', '72001')], 'county', TEST)}
    assert pr_obs['risk_score']['status'] == 'not_available' and pr_obs['risk_score']['value'] is None
    assert pr_obs['risk_score']['rating'] == 'Insufficient Data'
    assert pr_obs['sovi_spctl']['status'] == 'not_available' and pr_obs['sovi_spctl']['value'] is None
    assert pr_obs['sovi_spctl']['source_value'] == '0.000000000000000'
    assert pr_obs['resl_spctl']['status'] == 'not_available' and pr_obs['resl_spctl']['value'] is None
    assert pr_obs['resl_spctl']['source_value'] == '0.000000000000000'
    assert pr_obs['sovi_score']['rating'] == 'Data Unavailable'
    assert pr_obs['eal_score']['status'] == 'available' and pr_obs['eal_score']['rating'] == 'Relatively Low'

    # Check tract with true_zero EAL_VALT and blank RISK_RATNG -> rating None.
    t_obs = {v['measure']['measure_id']: v for v in observation_values(records[('tract', '01001020100')], 'tract', TEST)}
    assert t_obs['eal_valt']['status'] == 'true_zero' and t_obs['eal_valt']['value'] == Decimal('0.0000')
    assert t_obs['eal_score']['rating'] == 'No Expected Annual Losses'
    assert t_obs['risk_score']['rating'] is None

    # Wrong NRI_VER or missing ZIP raises clearly.
    bad_zip = write_zip(tmp_path / 'bad_ver.zip', 'NRI_Table_States.csv', STATE_HEADER, [state_row('01', ver='March 2023')])
    with pytest.raises(ValueError, match='NRI_VER'):
        parse_zip(bad_zip, 'state', TEST)
    with pytest.raises(ValueError, match='Missing archived FEMA NRI ZIP'):
        fetch(TEST, tmp_path / 'empty_dir')
    # SHA-256 mismatch check.
    strict_cfg = copy.deepcopy(TEST)
    strict_cfg['source_archives']['state']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        fetch(strict_cfg, tmp_path)
    assert s_zip.is_file() and c_zip.is_file() and t_zip.is_file()


# ---------------------------------------------------------------- classification & lifecycle

def test_classify_and_expected_observations():
    records = {
        ('state', '01'): dict(zip(STATE_HEADER, state_row('01'))),
        ('state', '60'): dict(zip(STATE_HEADER, state_row('60'))),
        ('county', '09110'): dict(zip(COUNTY_HEADER, county_row('09110'))),
        ('county', '60010'): dict(zip(COUNTY_HEADER, county_row('60010'))),
        ('tract', '09110500100'): dict(zip(TRACT_HEADER, tract_row('09110500100'))),
        ('tract', '60010950100'): dict(zip(TRACT_HEADER, tract_row('60010950100'))),
    }
    classified, issues = classify(records, {'01', '09'}, {'09110'}, {'09110500100'}, TEST)
    assert issues['duplicate_geoids'] == []
    assert classified[('state', '01')]['boundary_status'] == 'matched'
    assert classified[('state', '60')]['boundary_status'] == 'source_only'
    assert classified[('state', '60')]['exclusion_reason'] == 'territory_outside_chip_2024_boundary_layer'
    assert classified[('county', '09110')]['boundary_status'] == 'matched'
    assert classified[('county', '60010')]['boundary_status'] == 'source_only'
    assert classified[('tract', '09110500100')]['boundary_status'] == 'matched'
    assert classified[('tract', '60010950100')]['boundary_status'] == 'source_only'

    expected = fema_nri_area_cli.expected_observations(records, classified, TEST)
    # 1 matched state * 2 measures + 1 matched county * 10 measures + 1 matched tract * 10 measures = 22
    assert len(expected) == 22
    assert ('state', '01', 'eal_score') in expected
    assert ('state', '01', 'eal_valt') in expected
    assert ('state', '01', 'risk_score') not in expected

    uncovered, _ = boundary_without_source(classified, {'01', '09'}, {'09110'}, {'09110500100'}, TEST)
    assert uncovered == {'state:09': 'no_fema_nri_row'}

    assert semantic_sha(records) == semantic_sha(dict(reversed(list(records.items()))))
    assert same_label_revision(
        {'source_release_id': CONFIG['source_release_id'], 'semantic_sha256': 'aaa'},
        CONFIG['source_release_id'], 'bbb')


class Recorder:
    def __init__(self, release_row=None):
        self.statements, self.release_row = [], release_row

    def execute(self, sql, params=None):
        self.statements.append(str(sql))
        return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: self.release_row, one_or_none=lambda: None),
                               scalar_one=lambda: 0, scalar_one_or_none=lambda: None)

    def begin(self):
        conn = self
        class Context:
            def __enter__(self): return conn
            def __exit__(self, *_): return False
        return Context()


def test_failed_retrieval_and_held_candidates_never_touch_active_pointer(tmp_path):
    engine = Recorder()
    _, report = fema_nri_area_cli.fetch_stage(engine, CONFIG, directory=tmp_path)
    assert report['status'] == 'held' and 'Missing archived FEMA NRI ZIP' in report['hold_reason']
    assert not any('active_release' in s for s in engine.statements)

    held = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'held', 'report': {'hold_reason': 'validation_failed'}})
    with pytest.raises(ValueError, match='not ready'):
        fema_nri_area_cli.publish(held, CONFIG, 'c', 'a', 'b', 'c')
    ready = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'ready', 'semantic_sha256': 'x',
                      'schema_sha256': 'y', 'metadata_sha256': 'z'})
    with pytest.raises(ValueError, match='reviewed checksums'):
        fema_nri_area_cli.publish(ready, CONFIG, 'c', 'x', 'y', 'other')
    with pytest.raises(ValueError, match='retained published'):
        fema_nri_area_cli.set_pointer(Recorder(), CONFIG, 'rollback', 'not-published')


# ---------------------------------------------------------------- read API & lookup

class PublishedDB:
    def execute(self, *_):
        return SimpleNamespace(scalar_one_or_none=lambda: 'published')


def test_selection_enforces_measure_levels():
    by_id = {m['measure_id']: m for m in CONFIG['measures']}
    for lvl in ('state', 'county', 'tract'):
        m = by_id['eal_score']
        assert fema_nri_area_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', m['measure_id'],
            m['observation_period'], m['population'], CONFIG['value_type'], lvl)[1] == m
    # risk_score has no state level -> 400
    m = by_id['risk_score']
    with pytest.raises(HTTPException) as err:
        fema_nri_area_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', m['measure_id'],
            m['observation_period'], m['population'], CONFIG['value_type'], 'state')
    assert err.value.status_code == 400 and 'not published at the state level' in err.value.detail
    for path in ('/area/catalog', '/area/map', '/area/legend', '/area/table'):
        assert not _is_public_path(path)


def test_api_map_legend_table_ratings_direction_and_lookup_spec():
    class Result:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows
    rows = [
        {'geography_id': '01001', 'name': 'Autauga', 'value': Decimal('57.5700'),
         'source_value': '57.569974', 'status': 'available', 'rating': 'Relatively Low'},
        {'geography_id': '72001', 'name': 'Adjuntas', 'value': None,
         'source_value': '', 'status': 'not_available', 'rating': 'Insufficient Data'},
    ]
    class DB:
        def execute(self, sql, params):
            query = str(sql)
            assert 'LEFT JOIN area_pilot.observation_fema_nri' in query
            if 'GROUP BY' in query:
                return Result([
                    {'status': 'available', 'n': 1, 'low': Decimal('57.5700'), 'high': Decimal('57.5700')},
                    {'status': 'not_available', 'n': 1, 'low': None, 'high': None},
                ])
            assert 'o.rating' in query
            out = [dict(r) for r in rows]
            if 'ST_AsGeoJSON' in query:
                for item in out:
                    item['geometry'] = {'type': 'Polygon', 'coordinates': []}
            return Result(out)

    by_id = {m['measure_id']: m for m in CONFIG['measures']}
    base = fema_nri_area_api.metadata(CONFIG, by_id['risk_score'], 'rel-nri', 'county', '-87,32,-86,33')
    assert base['direction'] == 'higher_worse' and base['has_rating'] is True
    resl_meta = fema_nri_area_api.metadata(CONFIG, by_id['resl_score'], 'rel-nri', 'county', '-87,32,-86,33')
    assert resl_meta['direction'] == 'higher_better' and 'better' in resl_meta['direction_note'].lower()

    mapped = fema_nri_area_api.map_data(DB(), {'level': 'county'}, 2, base, 0.01)
    table = fema_nri_area_api.table(DB(), {'level': 'county'}, base, 2, 100, 0)
    legend = fema_nri_area_api.legend(DB(), {'level': 'county'}, base)
    props = [f['properties'] for f in mapped['features']]
    assert props[0]['rating'] == 'Relatively Low' and table['rows'][0]['rating'] == 'Relatively Low'
    assert props[1]['rating'] == 'Insufficient Data'
    assert props[1]['status_text'] == 'Not published by FEMA for this area (Insufficient Data)'
    assert sum(s['n'] for s in legend['statuses']) == 2
    assert legend['limitations'] == CONFIG['limitations']

    # Verify lookup.SPECS wiring for fema_nri including rating in extra and status_text.
    spec = next(s for s in lookup.SPECS if s.key == 'fema_nri')
    assert spec.extra == ('source_value', 'rating') and spec.uncertainty == 'none'
    assert set(spec.tables) == {'state', 'county', 'tract'}
    meta_eal = lookup._measure_meta(spec, CONFIG, by_id['eal_score'])
    meta_risk = lookup._measure_meta(spec, CONFIG, by_id['risk_score'])
    assert meta_eal['levels'] == ['state', 'county', 'tract']
    assert meta_risk['levels'] == ['county', 'tract']
    row_ok = lookup._row(meta_risk, 'county', '01001', {'release_id': 'r', 'source_release_id': 's'}, CONFIG,
                         {'value': Decimal('57.5700'), 'status': 'available', 'source_value': '57.569974', 'rating': 'Relatively Low'}, spec)
    assert row_ok['notes']['rating'] == 'Relatively Low'
    row_na = lookup._row(meta_risk, 'county', '72001', {'release_id': 'r', 'source_release_id': 's'}, CONFIG,
                         {'value': None, 'status': 'not_available', 'source_value': '', 'rating': 'Insufficient Data'}, spec)
    assert row_na['notes']['rating'] == 'Insufficient Data'
    assert row_na['status_text'] == 'Not published by FEMA for this area (Insufficient Data)'
