"""Unit tests for CDC/ATSDR SVI 2022 parsing (US + state-ranked), classification, lifecycle, and API."""
import copy
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot import lookup, svi, svi_api, svi_cli
from app.area_pilot.source import same_label_revision
from app.area_pilot.svi import (boundary_without_source, classify, load_registry, observation_values,
                                parse_csv, parse_state_csvs, parse_value, range_problems, retrieve,
                                semantic_sha, state_file_map, state_file_url)
from app.demo_access.middleware import _is_public_path

CONFIG = load_registry()
US_FIELDS = ['RPL_THEMES', 'RPL_THEME1', 'RPL_THEME2', 'RPL_THEME3', 'RPL_THEME4']
HEADER = ['ST', 'STATE', 'ST_ABBR', 'STCNTY', 'COUNTY', 'FIPS', 'LOCATION'] + US_FIELDS
TEST_STATES = [
    {'name': 'Alabama', 'fips': '01', 'abbr': 'AL'},
    {'name': 'Connecticut', 'fips': '09', 'abbr': 'CT'},
    {'name': 'NorthCarolina', 'fips': '37', 'abbr': 'NC'},
]
TEST = copy.deepcopy(CONFIG) | {
    'expected_column_count': len(HEADER),
    'expected_header_sha256': '',
    'state_files': TEST_STATES,
}


def row(fips='01001', values=('0.5432', '0.4100', '0.6200', '0.3300', '0.7800'),
        st='01', state='Alabama', abbr='AL', county='Autauga County', location='Autauga County, Alabama'):
    return [st, state, abbr, fips[:5], county, fips, location, *values]


def write_csv(path, rows, header=HEADER, bom=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = 'utf-8-sig' if bom else 'utf-8'
    lines = [','.join(header), *(','.join(f'"{c}"' if ',' in c else c for c in r) for r in rows)]
    path.write_text('\n'.join(lines) + '\n', encoding=encoding)
    return path


def record(fips='01001', values=('0.5432', '0.4100', '0.6200', '0.3300', '0.7800'),
           st='01', state='Alabama', abbr='AL'):
    return dict(zip(HEADER, row(fips=fips, values=values, st=st, state=state, abbr=abbr)))


# ---------------------------------------------------------------- registry & contract

def test_registry_matches_svi_2022_contract():
    assert CONFIG['dataset_id'] == 'cdc_svi_2022'
    assert CONFIG['value_type'] == 'percentile_rank'
    assert CONFIG['geographies'] == ['county', 'tract']
    assert CONFIG['observation_period'] == '2018–2022'
    assert not CONFIG['refresh_policy']['auto_publish'] and CONFIG['aggregation_method'] == 'none'
    assert [m['measure_id'] for m in CONFIG['measures']] == [
        'rpl_themes', 'rpl_theme1', 'rpl_theme2', 'rpl_theme3', 'rpl_theme4',
        'rpl_themes_state', 'rpl_theme1_state', 'rpl_theme2_state', 'rpl_theme3_state', 'rpl_theme4_state',
    ]
    assert CONFIG['expected_source_rows'] == {
        'us': {'county': 3144, 'tract': 84120},
        'state': {'county': 3144, 'tract': 84120},
    }
    by_name = state_file_map(CONFIG)
    assert len(by_name) == 51
    assert by_name['NorthCarolina'] == {'name': 'NorthCarolina', 'fips': '37', 'abbr': 'NC'}
    assert by_name['DistrictofColumbia'] == {'name': 'DistrictofColumbia', 'fips': '11', 'abbr': 'DC'}
    assert state_file_url(CONFIG, 'NorthCarolina', 'county') == (
        'https://svi.cdc.gov/Documents/Data/2022/csv/states_counties/NorthCarolina_county.csv')
    assert state_file_url(CONFIG, 'DistrictofColumbia', 'tract') == (
        'https://svi.cdc.gov/Documents/Data/2022/csv/states/DistrictofColumbia.csv')
    for measure in CONFIG['measures']:
        assert measure['legend_breaks'] == {'county': [0.25, 0.5, 0.75], 'tract': [0.25, 0.5, 0.75]}
        assert measure['observation_period'] == '2018–2022'
        if measure['measure_id'].endswith('_state'):
            assert measure['source_scope'] == 'state'
            assert '(rank within state)' in measure['label']
            assert measure['population_by_level'] == {
                'county': 'Rank among counties in the same state',
                'tract': 'Rank among census tracts in the same state',
            }
        else:
            assert measure['source_scope'] == 'us'
            assert measure['population_by_level'] == {
                'county': 'Rank among all U.S. counties',
                'tract': 'Rank among all U.S. census tracts',
            }
    assert len(CONFIG['limitations']) == 7
    assert svi_api.LIMITATIONS == CONFIG['limitations']
    assert svi_api.STATUS_TEXT['not_available'] == 'Not ranked by CDC (−999 in the source file)'
    comp = lookup.comparability('cdc_svi')
    assert comp['state_marker_levels'] == [] and comp['national_marker_levels'] == []
    assert comp['shared_axis_rule'] == 'same_product_level_and_release_only'


# ---------------------------------------------------------------- parsing

def test_parse_value_handles_sentinel_zero_available_bad_token_and_out_of_range():
    measure = CONFIG['measures'][0]
    assert parse_value('-999', measure) == (None, 'not_available')
    assert parse_value('-999.0', measure) == (None, 'not_available')
    assert parse_value('0', measure) == (Decimal('0'), 'true_zero')
    assert parse_value('0.0', measure) == (Decimal('0'), 'true_zero')
    assert parse_value('0.0001', measure) == (Decimal('0.0001'), 'available')
    assert parse_value('1', measure) == (Decimal('1'), 'available')
    assert parse_value('1.0', measure) == (Decimal('1.0'), 'available')
    for token in ('NA', '', '*', 'null', '1e-2', '.'):
        with pytest.raises(ValueError, match='Undocumented CDC SVI value token'):
            parse_value(token, measure)
    for bad in ('-0.0001', '-1', '-998', '-999.1', '1.0001', '2', '100'):
        with pytest.raises(ValueError, match='outside'):
            parse_value(bad, measure)
    assert range_problems(Decimal('0.5'), measure) == []
    assert range_problems(Decimal('1.5'), measure) == ['outside_documented_scale']


def test_parse_csv_utf8_sig_minus999_zero_ct_planning_region_and_errors(tmp_path):
    rows = [
        row(fips='09110', values=('0.2500', '0.1000', '0.3000', '0.4000', '0.5000'),
            st='09', state='Connecticut', abbr='CT', county='Capitol Planning Region',
            location='Capitol Planning Region, Connecticut'),
        row(fips='01001', values=('0', '0.0', '0.5', '0.75', '1.0')),
    ]
    records, stats = parse_csv(write_csv(tmp_path / 'county.csv', rows, bom=True), 'county', TEST)
    assert stats['row_count'] == 2
    assert set(records) == {('us', 'county', '09110'), ('us', 'county', '01001')}
    obs_zero = {v['measure']['measure_id']: v for v in observation_values(records[('us', 'county', '01001')], TEST, 'us')}
    assert set(obs_zero) == {'rpl_themes', 'rpl_theme1', 'rpl_theme2', 'rpl_theme3', 'rpl_theme4'}
    assert obs_zero['rpl_themes']['status'] == 'true_zero' and obs_zero['rpl_themes']['value'] == Decimal(0)
    assert obs_zero['rpl_theme1']['status'] == 'true_zero' and obs_zero['rpl_theme1']['value'] == Decimal(0)
    assert obs_zero['rpl_theme4']['status'] == 'available' and obs_zero['rpl_theme4']['value'] == Decimal('1.0')

    tract_rows = [
        row(fips='09110500100', values=('-999.0', '-999', '0.0', '0.5000', '0.9999'),
            st='09', state='Connecticut', abbr='CT', county='Capitol Planning Region',
            location='Census Tract 5001; Capitol Planning Region; Connecticut'),
    ]
    t_records, _ = parse_csv(write_csv(tmp_path / 'tract.csv', tract_rows, bom=True), 'tract', TEST)
    obs_tract = {v['measure']['measure_id']: v for v in observation_values(t_records[('us', 'tract', '09110500100')], TEST, 'us')}
    assert obs_tract['rpl_themes']['status'] == 'not_available' and obs_tract['rpl_themes']['value'] is None
    assert obs_tract['rpl_themes']['source_value'] == '-999.0'
    assert obs_tract['rpl_theme1']['status'] == 'not_available' and obs_tract['rpl_theme1']['value'] is None
    assert obs_tract['rpl_theme2']['status'] == 'true_zero' and obs_tract['rpl_theme2']['value'] == Decimal(0)

    # Bad token and out-of-range values stop parsing.
    with pytest.raises(ValueError, match='Undocumented CDC SVI value token'):
        parse_csv(write_csv(tmp_path / 'bad_token.csv', [row(values=('NA', '0.1', '0.2', '0.3', '0.4'))]), 'county', TEST)
    with pytest.raises(ValueError, match='outside'):
        parse_csv(write_csv(tmp_path / 'oor.csv', [row(values=('1.25', '0.1', '0.2', '0.3', '0.4'))]), 'county', TEST)
    with pytest.raises(ValueError, match='Duplicate'):
        parse_csv(write_csv(tmp_path / 'dup.csv', [row(), row()]), 'county', TEST)
    with pytest.raises(ValueError, match='column count'):
        parse_csv(write_csv(tmp_path / 'cols.csv', [row()], HEADER + ['EXTRA']), 'county', TEST)


def test_parse_state_csvs_validates_st_abbr_and_rejects_cross_file_duplicate_fips(tmp_path):
    state_dir = tmp_path / 'state'
    write_csv(state_dir / 'Alabama_county.csv', [row(fips='01001', st='01', state='Alabama', abbr='AL')])
    write_csv(state_dir / 'Connecticut_county.csv', [
        row(fips='09110', st='09', state='Connecticut', abbr='CT', county='Capitol Planning Region')])
    write_csv(state_dir / 'NorthCarolina_county.csv', [
        row(fips='37063', values=('0.5960', '0.5000', '0.4000', '0.6000', '0.7000'),
            st='37', state='North Carolina', abbr='NC', county='Durham County')])

    records, stats = parse_state_csvs(tmp_path, 'county', TEST)
    assert stats['row_count'] == 3
    assert set(records) == {('state', 'county', '01001'), ('state', 'county', '09110'), ('state', 'county', '37063')}
    obs_state = {v['measure']['measure_id']: v for v in observation_values(records[('state', 'county', '37063')], TEST, 'state')}
    assert set(obs_state) == {
        'rpl_themes_state', 'rpl_theme1_state', 'rpl_theme2_state', 'rpl_theme3_state', 'rpl_theme4_state'}
    assert obs_state['rpl_themes_state']['value'] == Decimal('0.5960')

    # Wrong ST_ABBR inside a state file stops parsing.
    write_csv(state_dir / 'NorthCarolina_county.csv', [
        row(fips='37063', st='37', state='North Carolina', abbr='SC', county='Durham County')])
    with pytest.raises(ValueError, match='ST_ABBR'):
        parse_state_csvs(tmp_path, 'county', TEST)

    # Duplicate FIPS across two state files fails even if state codes were spoofed to match.
    dup_cfg = copy.deepcopy(TEST) | {
        'state_files': [
            {'name': 'Alabama', 'fips': '01', 'abbr': 'AL'},
            {'name': 'AlabamaCopy', 'fips': '01', 'abbr': 'AL'},
        ]
    }
    write_csv(state_dir / 'AlabamaCopy_county.csv', [row(fips='01001', st='01', state='Alabama', abbr='AL')])
    with pytest.raises(ValueError, match='multiple state'):
        parse_state_csvs(tmp_path, 'county', dup_cfg)


def test_retrieve_skip_fetch_and_fetch_urls_cover_us_and_state_files(tmp_path, monkeypatch):
    write_csv(tmp_path / TEST['source_filenames']['county'], [
        row(fips='01001', st='01', state='Alabama', abbr='AL'),
        row(fips='09110', st='09', state='Connecticut', abbr='CT'),
        row(fips='37063', values=('0.6860', '0.5', '0.5', '0.5', '0.5'), st='37', state='North Carolina', abbr='NC'),
    ])
    write_csv(tmp_path / TEST['source_filenames']['tract'], [
        row(fips='01001020100', st='01', state='Alabama', abbr='AL'),
        row(fips='09110500100', st='09', state='Connecticut', abbr='CT'),
        row(fips='37063000101', st='37', state='North Carolina', abbr='NC'),
    ])
    for entry, cfips, tfips in (
        (TEST_STATES[0], '01001', '01001020100'),
        (TEST_STATES[1], '09110', '09110500100'),
        (TEST_STATES[2], '37063', '37063000101'),
    ):
        write_csv(tmp_path / 'state' / f'{entry["name"]}_county.csv',
                  [row(fips=cfips, st=entry['fips'], state=entry['name'], abbr=entry['abbr'])])
        write_csv(tmp_path / 'state' / f'{entry["name"]}.csv',
                  [row(fips=tfips, st=entry['fips'], state=entry['name'], abbr=entry['abbr'])])

    records, stats, files, prov = retrieve(TEST, tmp_path, skip_fetch=True)
    assert stats['row_counts'] == {'us': {'county': 3, 'tract': 3}, 'state': {'county': 3, 'tract': 3}}
    assert len(records) == 12
    assert len(files) == 2 + 2 * len(TEST_STATES)
    assert {f['role'] for f in files} == svi.required_roles(TEST)
    assert all(len(f['sha256']) == 64 and f['byte_count'] > 0 for f in files)
    assert prov['skip_fetch'] is True

    # Verify fetch() hits both US and state URL patterns (mocked, no network calls).
    fetched_urls = []
    def fake_get(url, target, limit):
        fetched_urls.append((url, target.name))
        target.write_text('stub', encoding='utf-8')
        return {'content-length': '4'}
    monkeypatch.setattr(svi, '_bounded_get', fake_get)
    monkeypatch.setattr('app.area_pilot.operations.disk_guard', lambda *_a, **_k: None)
    f_files, _ = svi.fetch(TEST, tmp_path / 'dl')
    assert len(f_files) == 2 + 2 * len(TEST_STATES)
    assert ('https://svi.cdc.gov/Documents/Data/2022/csv/states_counties/NorthCarolina_county.csv',
            'NorthCarolina_county.csv') in fetched_urls
    assert ('https://svi.cdc.gov/Documents/Data/2022/csv/states/NorthCarolina.csv',
            'NorthCarolina.csv') in fetched_urls


# ---------------------------------------------------------------- geography classification

def test_classify_matches_2024_boundaries_both_scopes_and_marks_source_only():
    records = {
        ('us', 'county', '01001'): record('01001'),
        ('state', 'county', '01001'): record('01001', values=('0.2200', '0.1', '0.2', '0.3', '0.4')),
        ('us', 'county', '09110'): record('09110', st='09', state='Connecticut', abbr='CT'),
        ('state', 'county', '09110'): record('09110', st='09', state='Connecticut', abbr='CT'),
        ('us', 'county', '09001'): record('09001', st='09', state='Connecticut', abbr='CT'),
        ('us', 'tract', '09110500100'): record('09110500100', st='09', state='Connecticut', abbr='CT'),
        ('state', 'tract', '09110500100'): record('09110500100', st='09', state='Connecticut', abbr='CT'),
        ('us', 'tract', '99999999999'): record('99999999999'),
    }
    classified, issues = classify(records, {'01001', '09110', '72001'}, {'09110500100', '72001956300'}, TEST)
    assert issues['duplicate_geoids'] == []
    assert classified[('us', 'county', '01001')]['boundary_status'] == 'matched'
    assert classified[('state', 'county', '01001')]['boundary_status'] == 'matched'
    assert classified[('us', 'county', '09001')]['boundary_status'] == 'source_only'
    assert classified[('us', 'county', '09001')]['exclusion_reason'] == 'legacy_connecticut_county_code'
    assert classified[('us', 'tract', '99999999999')]['boundary_status'] == 'source_only'
    assert classified[('us', 'tract', '99999999999')]['exclusion_reason'] == 'no_matching_2024_boundary'

    expected = svi_cli.expected_observations(records, classified, TEST)
    # 2 matched counties * 10 measures + 1 matched tract * 10 measures = 30
    assert len(expected) == 30
    assert expected[('county', '01001', 'rpl_themes')][0] == Decimal('0.5432')
    assert expected[('county', '01001', 'rpl_themes_state')][0] == Decimal('0.2200')

    uncovered, coverage = boundary_without_source(classified, {'01001', '09110', '72001'}, {'09110500100', '72001956300'}, TEST)
    assert uncovered == {
        'county:72001': 'puerto_rico_outside_cdc_svi_us_file',
        'tract:72001956300': 'puerto_rico_outside_cdc_svi_us_file',
    }
    assert coverage['counts'] == {
        'county|puerto_rico_outside_cdc_svi_us_file': 1,
        'tract|puerto_rico_outside_cdc_svi_us_file': 1,
    }


# ---------------------------------------------------------------- lifecycle guards

def test_semantic_sha_is_order_independent_and_detects_revisions():
    a = {('us', 'county', '01001'): record('01001'), ('state', 'county', '01001'): record('01001')}
    b = dict(reversed(list(a.items())))
    assert semantic_sha(a) == semantic_sha(b)
    revised = dict(a) | {('state', 'county', '01001'): record('01001') | {'RPL_THEMES': '0.9999'}}
    assert semantic_sha(revised) != semantic_sha(a)
    assert same_label_revision({'source_release_id': CONFIG['source_release_id'], 'semantic_sha256': semantic_sha(a)},
                               CONFIG['source_release_id'], semantic_sha(revised))


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
    def broken(_directory):
        raise RuntimeError('CDC SVI download failed after 3 attempts')
    engine = Recorder()
    _, report = svi_cli.fetch_stage(engine, CONFIG, directory=tmp_path, retrieved=broken)
    assert report == {'status': 'held', 'hold_reason': 'CDC SVI download failed after 3 attempts'}
    assert not any('active_release' in s for s in engine.statements)

    held = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'held', 'report': {'hold_reason': 'validation_failed'}})
    with pytest.raises(ValueError, match='not ready'):
        svi_cli.publish(held, CONFIG, 'c', 'a', 'b', 'c')
    with pytest.raises(ValueError, match='not an eligible'):
        svi_cli.release_reviewed_hold(held, CONFIG, 'c', 'a', 'b', 'c', 'reviewed')
    ready = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'ready', 'semantic_sha256': 'x',
                      'schema_sha256': 'y', 'metadata_sha256': 'z'})
    with pytest.raises(ValueError, match='reviewed checksums'):
        svi_cli.publish(ready, CONFIG, 'c', 'x', 'y', 'other')
    with pytest.raises(ValueError, match='retained published'):
        svi_cli.set_pointer(Recorder(), CONFIG, 'rollback', 'not-published')


# ---------------------------------------------------------------- read API & lookup

class PublishedDB:
    def execute(self, *_):
        return SimpleNamespace(scalar_one_or_none=lambda: 'published')


def test_selection_supports_us_and_state_measures_and_rejects_state_geography():
    for idx in (0, 5):
        measure = CONFIG['measures'][idx]
        for geography in ('county', 'tract'):
            assert svi_api.selection(PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
                                     measure['observation_period'], measure['population'],
                                     CONFIG['value_type'], geography)[1] == measure
    measure = CONFIG['measures'][0]
    with pytest.raises(HTTPException) as error:
        svi_api.selection(PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
                          measure['observation_period'], measure['population'], CONFIG['value_type'], 'state')
    assert error.value.status_code == 400 and 'no state' in error.value.detail
    with pytest.raises(HTTPException) as error:
        svi_api.selection(PublishedDB(), CONFIG['dataset_id'], 'r', 'unknown',
                          measure['observation_period'], measure['population'], CONFIG['value_type'], 'county')
    assert error.value.status_code == 404
    for path in ('/area/catalog', '/area/map', '/area/legend', '/area/table'):
        assert not _is_public_path(path)


def test_viewport_cap_returns_413_for_county_and_tract():
    class DB:
        def execute(self, *_):
            return SimpleNamespace(scalar_one=lambda: svi_api.TRACT_CAP + 1)
    for level in ('county', 'tract'):
        with pytest.raises(HTTPException) as error:
            svi_api.ensure_cap(DB(), {'level': level})
        assert error.value.status_code == 413


def test_api_metadata_map_legend_table_parity_and_lookup_spec():
    class Result:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows
    rows = [
        {'geography_id': '09110500100', 'name': 'Census Tract 5001', 'value': Decimal('0.6421'),
         'source_value': '0.6421', 'status': 'available'},
        {'geography_id': '09110500200', 'name': 'Census Tract 5002', 'value': Decimal('0'),
         'source_value': '0.0', 'status': 'true_zero'},
        {'geography_id': '09110980000', 'name': 'Census Tract 9800', 'value': None,
         'source_value': '-999.0', 'status': 'not_available'},
        {'geography_id': '72001956300', 'name': 'Census Tract 9563', 'value': None,
         'source_value': None, 'status': 'not_in_release'},
    ]
    class DB:
        def execute(self, sql, params):
            query = str(sql)
            assert 'LEFT JOIN area_pilot.observation_cdc_svi' in query and 'b.level=:level' in query
            if 'GROUP BY' in query:
                return Result([
                    {'status': 'available', 'n': 1, 'low': Decimal('0.6421'), 'high': Decimal('0.6421')},
                    {'status': 'not_available', 'n': 1, 'low': None, 'high': None},
                    {'status': 'not_in_release', 'n': 1, 'low': None, 'high': None},
                    {'status': 'true_zero', 'n': 1, 'low': Decimal('0'), 'high': Decimal('0')},
                ])
            out = [dict(r) for r in rows]
            if 'ST_AsGeoJSON' in query:
                for item in out:
                    item['geometry'] = {'type': 'Polygon', 'coordinates': []}
            return Result(out)

    measure = CONFIG['measures'][0]
    state_measure = CONFIG['measures'][5]
    base = svi_api.metadata(CONFIG, measure, 'rel-svi', 'tract', '-73,41,-72,42')
    assert base['legend_breaks'] == [0.25, 0.5, 0.75]
    assert base['population_label'] == 'Rank among all U.S. census tracts'
    assert base['source_scope'] == 'us'
    state_county_meta = svi_api.metadata(CONFIG, state_measure, 'rel-svi', 'county', '-73,41,-72,42')
    assert state_county_meta['population_label'] == 'Rank among counties in the same state'
    assert state_county_meta['source_scope'] == 'state'
    state_tract_meta = svi_api.metadata(CONFIG, state_measure, 'rel-svi', 'tract', '-73,41,-72,42')
    assert state_tract_meta['population_label'] == 'Rank among census tracts in the same state'

    mapped = svi_api.map_data(DB(), {'level': 'tract'}, 4, base, 0.01)
    table = svi_api.table(DB(), {'level': 'tract'}, base, 4, 100, 0)
    legend = svi_api.legend(DB(), {'level': 'tract'}, base)
    props = [f['properties'] for f in mapped['features']]
    assert [(p['value'], p['status']) for p in props] == [(r['value'], r['status']) for r in table['rows']]
    assert props[2]['status'] == 'not_available' and props[2]['value'] is None
    assert props[2]['status_text'] == 'Not ranked by CDC (−999 in the source file)'
    assert props[3]['status'] == 'not_in_release' and props[3]['value'] is None
    assert sum(s['n'] for s in legend['statuses']) == mapped['count'] == table['total'] == 4
    assert legend['limitations'] == CONFIG['limitations']

    # Verify lookup.SPECS and MISSING_STATUS wiring for cdc_svi.
    spec = next(s for s in lookup.SPECS if s.key == 'cdc_svi')
    assert spec.tables == {'county': ('observation_cdc_svi', 'geoid', 'geo_level'),
                           'tract': ('observation_cdc_svi', 'geoid', 'geo_level')}
    assert spec.extra == ('source_value',) and spec.uncertainty == 'none'
    assert lookup.MISSING_STATUS['cdc_svi']('72001', 'county') == lookup.NOT_IN_RELEASE
    assert not any(k[0] == 'cdc_svi' for k in lookup.SOURCE_CREDITS)
    meta = lookup._measure_meta(spec, CONFIG, measure)
    row_na = lookup._row(meta, 'tract', '09110980000',
                         {'release_id': 'r', 'source_release_id': 's'}, CONFIG,
                         {'value': None, 'status': 'not_available', 'source_value': '-999.0'}, spec)
    assert row_na['status_text'] == 'Not ranked by CDC (−999 in the source file)'
    assert row_na['uncertainty'] == {'kind': 'none', 'label': 'No uncertainty published'}
    row_missing = lookup._row(meta, 'county', '72001',
                              {'release_id': 'r', 'source_release_id': 's'}, CONFIG, None, spec)
    assert row_missing['status'] == lookup.NOT_IN_RELEASE and row_missing['value'] is None
