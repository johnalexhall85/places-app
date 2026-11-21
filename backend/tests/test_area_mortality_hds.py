"""Unit tests for CDC heart disease and stroke mortality parsing, classification, lifecycle, and API."""
import copy
import csv
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot import hds_mortality, hds_mortality_api, hds_mortality_cli, lookup
from app.area_pilot.hds_mortality import (
    LEGACY_CT_COUNTIES, boundary_without_source, classify, load_registry,
    normalize_code, observation_values, parse_csv, parse_value, range_problems,
    retrieve, semantic_sha,
)
from app.area_pilot.source import same_label_revision
from app.demo_access.middleware import _is_public_path

CONFIG = load_registry()
HEADER = [
    'Year', 'LocationAbbr', 'LocationDesc', 'GeographicLevel', 'DataSource', 'Class', 'Topic',
    'Data_Value', 'Data_Value_Unit', 'Data_Value_Type', 'Data_Value_Footnote_Symbol',
    'Data_Value_Footnote', 'StratificationCategory1', 'Stratification1', 'StratificationCategory2',
    'Stratification2', 'TopicID', 'LocationID', 'Y_lat', 'X_lon',
]
HEART_SPEC = CONFIG['source_files'][0]
STROKE_SPEC = CONFIG['source_files'][1]
COUNTY_VT = CONFIG['value_type_by_level']['county']
STATE_VT = CONFIG['value_type_by_level']['state']


def make_row(year='2023', abbr='NC', desc='Durham County', level='County', value='227.2',
             value_type=None, sym='', footnote='', strat1='Overall', strat2='Overall',
             location_id='37063', topic='Heart Disease Mortality', topic_id='T2'):
    vt = value_type if value_type is not None else (COUNTY_VT if level == 'County' else STATE_VT)
    return [
        year, abbr, desc, level, 'NVSS', 'Cardiovascular Diseases', topic,
        value, 'per 100,000 population', vt, sym, footnote,
        'Sex', strat1, 'Race/Ethnicity', strat2, topic_id, location_id, '36.0', '-78.9',
    ]


def write_csv(path, rows, header=HEADER, bom=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = 'utf-8-sig' if bom else 'utf-8'
    with path.open('w', newline='', encoding=encoding) as out:
        writer = csv.writer(out)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def make_record(**kwargs):
    return dict(zip(HEADER, make_row(**kwargs)))


# ---------------------------------------------------------------- registry & contract

def test_registry_matches_hds_mortality_contract():
    assert CONFIG['dataset_id'] == 'cdc_hds_mortality_2022_2024'
    assert CONFIG['observation_year'] == 2023
    assert CONFIG['observation_period'] == '2022–2024'
    assert CONFIG['geographies'] == ['state', 'county']
    assert CONFIG['aggregation_method'] == 'none'
    assert not CONFIG['refresh_policy']['auto_publish']
    assert [m['measure_id'] for m in CONFIG['measures']] == ['heart_disease_death_rate', 'stroke_death_rate']
    assert CONFIG['measures'][0]['label'] == (
        'Heart disease death rate, adults 35 and older (per 100,000, age-adjusted)'
    )
    assert CONFIG['measures'][1]['label'] == (
        'Stroke death rate, adults 35 and older (per 100,000, age-adjusted)'
    )
    assert CONFIG['value_type_by_level'] == {
        'national': 'Age-adjusted, 3-year Average Rate',
        'state': 'Age-adjusted, 3-year Average Rate',
        'county': 'Age-adjusted, Spatially Smoothed, 3-year Average Rate',
    }
    assert all(m['population'] == 'Adults aged 35 and older' for m in CONFIG['measures'])
    assert len(CONFIG['limitations']) == 4
    assert hds_mortality_api.LIMITATIONS == CONFIG['limitations']
    assert hds_mortality_api.STATUS_TEXT == {
        'suppressed': 'Insufficient data (CDC Heart Disease and Stroke Atlas)',
    }
    comp = lookup.comparability('cdc_hds_mortality')
    assert comp['state_marker_levels'] == ['county']
    assert comp['national_marker_levels'] == ['state', 'county']
    assert comp['shared_axis_rule'] == 'same_product_measure_and_release_only'


# ---------------------------------------------------------------- parsing

def test_parse_value_handles_available_suppressed_and_rejects_bad_or_non_positive():
    measure = CONFIG['measures'][0]
    assert parse_value('227.2', '', '', measure) == (Decimal('227.2'), 'available')
    assert parse_value('', '~', 'Insufficient Data', measure) == (None, 'suppressed')
    for bad_val, sym, note in (
        ('', '', ''),
        ('', '*', 'Suppressed'),
        ('NA', '', ''),
        ('~', '~', 'Insufficient Data'),
        ('0', '', ''),
        ('0.0', '', ''),
        ('-12.5', '', ''),
    ):
        with pytest.raises(ValueError):
            parse_value(bad_val, sym, note, measure)
    assert range_problems(Decimal('227.2'), measure) == []
    assert range_problems(Decimal('0'), measure) == ['outside_documented_scale']


def test_parse_csv_overall_stratified_suppressed_national_padding_and_errors(tmp_path):
    rows = [
        # Kept: Overall/Overall county, state (needs padding), national, suppressed county, legacy CT county
        make_row(level='County', abbr='NC', desc='Durham County', location_id='37063', value='227.2'),
        make_row(level='County', abbr='AK', desc='Bristol Bay', location_id='2060', value='',
                 sym='~', footnote='Insufficient Data'),
        make_row(level='County', abbr='CT', desc='Fairfield County', location_id='09001', value='',
                 sym='~', footnote='Insufficient Data'),
        make_row(level='State', abbr='AL', desc='Alabama', location_id='1', value='410.5'),
        make_row(level='Nation', abbr='US', desc='United States', location_id='0', value='315.3'),
        # Skipped: stratified rows (sex and race/ethnicity)
        make_row(level='County', abbr='NC', desc='Durham County', location_id='37063', value='290.0',
                 strat1='Male', strat2='Overall'),
        make_row(level='County', abbr='NC', desc='Durham County', location_id='37063', value='180.0',
                 strat1='Overall', strat2='Black'),
    ]
    path = write_csv(tmp_path / 'mri7-5jtw.csv', rows, bom=True)
    records, stats = parse_csv(path, HEART_SPEC, CONFIG)
    assert stats['total_rows'] == 7
    assert stats['kept_rows'] == 5
    assert stats['level_counts'] == {'County': 3, 'Nation': 1, 'State': 1}
    assert stats['suppressed_counties'] == 2
    assert stats['check_values'] == {'37063': '227.2', 'national': '315.3'}

    assert ('mri7-5jtw.csv', 'County', '37063', '2022–2024') in records
    assert ('mri7-5jtw.csv', 'County', '02060', '2022–2024') in records
    assert ('mri7-5jtw.csv', 'County', '09001', '2022–2024') in records
    assert ('mri7-5jtw.csv', 'State', '01', '2022–2024') in records
    assert ('mri7-5jtw.csv', 'Nation', '0', '2022–2024') in records

    durham_obs = observation_values(records[('mri7-5jtw.csv', 'County', '37063', '2022–2024')], 'mri7-5jtw.csv', CONFIG)
    assert durham_obs[0]['value'] == Decimal('227.2')
    assert durham_obs[0]['status'] == 'available'
    assert durham_obs[0]['value_type'] == COUNTY_VT

    sup_obs = observation_values(records[('mri7-5jtw.csv', 'County', '02060', '2022–2024')], 'mri7-5jtw.csv', CONFIG)
    assert sup_obs[0]['value'] is None
    assert sup_obs[0]['status'] == 'suppressed'
    assert sup_obs[0]['source_value'] == '~'

    us_obs = observation_values(records[('mri7-5jtw.csv', 'Nation', '0', '2022–2024')], 'mri7-5jtw.csv', CONFIG)
    assert us_obs[0]['value'] == Decimal('315.3')
    assert us_obs[0]['value_type'] == STATE_VT

    # Bad token, zero rate, duplicate key, wrong year, and wrong Data_Value_Type stop parsing.
    with pytest.raises(ValueError, match='Undocumented'):
        parse_csv(write_csv(tmp_path / 'bad.csv', [make_row(value='N/A')]), HEART_SPEC, CONFIG)
    with pytest.raises(ValueError, match='Non-positive'):
        parse_csv(write_csv(tmp_path / 'zero.csv', [make_row(value='0')]), HEART_SPEC, CONFIG)
    with pytest.raises(ValueError, match='Duplicate'):
        parse_csv(write_csv(tmp_path / 'dup.csv', [make_row(), make_row()]), HEART_SPEC, CONFIG)
    with pytest.raises(ValueError, match='Year'):
        parse_csv(write_csv(tmp_path / 'yr.csv', [make_row(year='2022')]), HEART_SPEC, CONFIG)
    with pytest.raises(ValueError, match='Data_Value_Type'):
        parse_csv(write_csv(tmp_path / 'vt.csv', [make_row(level='County', value_type=STATE_VT)]), HEART_SPEC, CONFIG)


def test_normalize_code_pads_states_and_counties():
    assert normalize_code('State', '1') == '01'
    assert normalize_code('State', '37') == '37'
    assert normalize_code('County', '2060') == '02060'
    assert normalize_code('County', '37063') == '37063'
    assert normalize_code('Nation', '0') == '0'


def test_retrieve_skip_fetch_and_mocked_fetch_records_sha256(tmp_path, monkeypatch):
    write_csv(tmp_path / 'mri7-5jtw.csv', [
        make_row(level='Nation', abbr='US', desc='United States', location_id='0', value='315.3'),
        make_row(level='County', abbr='NC', desc='Durham County', location_id='37063', value='227.2'),
    ])
    write_csv(tmp_path / 'y5ii-knwc.csv', [
        make_row(level='Nation', abbr='US', desc='United States', location_id='0', value='75.9',
                 topic='Stroke Mortality', topic_id='T6'),
        make_row(level='County', abbr='NC', desc='Durham County', location_id='37063', value='71.2',
                 topic='Stroke Mortality', topic_id='T6'),
    ])
    records, stats, files, prov = retrieve(CONFIG, tmp_path, skip_fetch=True)
    assert len(records) == 4
    assert {f['role'] for f in files} == {'hds_heart_disease_csv', 'hds_stroke_csv'}
    assert all(len(f['sha256']) == 64 and f['byte_count'] > 0 for f in files)
    assert prov['skip_fetch'] is True
    assert stats['files']['mri7-5jtw.csv']['check_values'] == {'national': '315.3', '37063': '227.2'}
    assert stats['files']['y5ii-knwc.csv']['check_values'] == {'national': '75.9', '37063': '71.2'}

    fetched = []
    def fake_get(url, target, limit):
        fetched.append((url, target.name))
        target.write_text('stub', encoding='utf-8')
        return {'content-length': '4'}
    monkeypatch.setattr(hds_mortality, '_bounded_get', fake_get)
    monkeypatch.setattr('app.area_pilot.operations.disk_guard', lambda *_a, **_k: None)
    f_files, _ = hds_mortality.fetch(CONFIG, tmp_path / 'dl')
    assert len(f_files) == 2
    assert ('https://data.cdc.gov/api/views/mri7-5jtw/rows.csv?accessType=DOWNLOAD', 'mri7-5jtw.csv') in fetched
    assert ('https://data.cdc.gov/api/views/y5ii-knwc/rows.csv?accessType=DOWNLOAD', 'y5ii-knwc.csv') in fetched


# ---------------------------------------------------------------- geography & validation

def test_classify_exact_boundaries_legacy_ct_territories_and_national():
    records = {
        ('mri7-5jtw.csv', 'Nation', '0', '2022–2024'): make_record(level='Nation', location_id='0', value='315.3'),
        ('mri7-5jtw.csv', 'State', '37', '2022–2024'): make_record(level='State', location_id='37', value='280.1'),
        ('mri7-5jtw.csv', 'State', '66', '2022–2024'): make_record(level='State', location_id='66', value='350.0'),
        ('mri7-5jtw.csv', 'County', '37063', '2022–2024'): make_record(level='County', location_id='37063', value='227.2'),
        ('mri7-5jtw.csv', 'County', '09001', '2022–2024'): make_record(
            level='County', location_id='09001', value='', sym='~', footnote='Insufficient Data'
        ),
        ('mri7-5jtw.csv', 'County', '02261', '2022–2024'): make_record(
            level='County', location_id='02261', value='', sym='~', footnote='Insufficient Data'
        ),
    }
    classified, issues = classify(records, {'37', '09'}, {'37063', '09110'}, CONFIG)
    assert issues['unexplained'] == []
    assert issues['duplicate_geoids'] == []
    assert classified[('mri7-5jtw.csv', 'Nation', '0', '2022–2024')]['boundary_status'] == 'national_reference'
    assert classified[('mri7-5jtw.csv', 'Nation', '0', '2022–2024')]['geoid'] == 'US'
    assert classified[('mri7-5jtw.csv', 'State', '37', '2022–2024')]['boundary_status'] == 'matched'
    assert classified[('mri7-5jtw.csv', 'State', '66', '2022–2024')]['boundary_status'] == 'source_only'
    assert classified[('mri7-5jtw.csv', 'State', '66', '2022–2024')]['exclusion_reason'] == 'no_2024_boundary'
    assert classified[('mri7-5jtw.csv', 'County', '37063', '2022–2024')]['boundary_status'] == 'matched'
    assert classified[('mri7-5jtw.csv', 'County', '09001', '2022–2024')]['boundary_status'] == 'source_only'
    assert (
        classified[('mri7-5jtw.csv', 'County', '09001', '2022–2024')]['exclusion_reason']
        == 'legacy_connecticut_county_code'
    )
    assert classified[('mri7-5jtw.csv', 'County', '02261', '2022–2024')]['exclusion_reason'] == 'no_2024_boundary'
    assert len(LEGACY_CT_COUNTIES) == 8

    expected = hds_mortality_cli.expected_observations(records, classified, CONFIG)
    assert set(expected) == {
        ('national', 'US', 'heart_disease_death_rate', '2022–2024'),
        ('state', '37', 'heart_disease_death_rate', '2022–2024'),
        ('county', '37063', 'heart_disease_death_rate', '2022–2024'),
    }

    uncovered, coverage = boundary_without_source(classified, {'37', '09'}, {'37063', '09110'}, CONFIG)
    assert uncovered == {
        'state:09': 'no_source_row',
        'county:09110': 'connecticut_planning_region_not_in_source',
    }
    assert coverage['counts']['county|connecticut_planning_region_not_in_source'] == 1


def test_validate_counts_and_checks_enforces_contract_counts_and_check_values():
    good_stats = {
        'files': {
            'mri7-5jtw.csv': {
                'level_counts': {'Nation': 1, 'State': 56, 'County': 3226},
                'suppressed_counties': 16,
                'check_values': {'national': '315.3', '37063': '227.2'},
            },
            'y5ii-knwc.csv': {
                'level_counts': {'Nation': 1, 'State': 56, 'County': 3226},
                'suppressed_counties': 20,
                'check_values': {'national': '75.9', '37063': '71.2'},
            },
        }
    }
    assert hds_mortality_cli.validate_counts_and_checks(good_stats, CONFIG)[:3] == (True, True, True)

    bad_counts = copy.deepcopy(good_stats)
    bad_counts['files']['mri7-5jtw.csv']['level_counts']['County'] = 3225
    assert hds_mortality_cli.validate_counts_and_checks(bad_counts, CONFIG)[:3] == (False, True, True)

    bad_sup = copy.deepcopy(good_stats)
    bad_sup['files']['y5ii-knwc.csv']['suppressed_counties'] = 19
    assert hds_mortality_cli.validate_counts_and_checks(bad_sup, CONFIG)[:3] == (True, False, True)

    bad_check = copy.deepcopy(good_stats)
    bad_check['files']['mri7-5jtw.csv']['check_values']['37063'] = '227.9'
    assert hds_mortality_cli.validate_counts_and_checks(bad_check, CONFIG)[:3] == (True, True, False)


# ---------------------------------------------------------------- lifecycle guards

def test_semantic_sha_is_order_independent_and_detects_revisions():
    a = {
        ('mri7-5jtw.csv', 'State', '37', '2022–2024'): make_record(level='State', location_id='37', value='280.1'),
        ('y5ii-knwc.csv', 'State', '37', '2022–2024'): make_record(level='State', location_id='37', value='72.4'),
    }
    b = dict(reversed(list(a.items())))
    assert semantic_sha(a) == semantic_sha(b)
    revised = dict(a) | {
        ('mri7-5jtw.csv', 'State', '37', '2022–2024'): make_record(level='State', location_id='37', value='280.2')
    }
    assert semantic_sha(revised) != semantic_sha(a)
    assert same_label_revision(
        {'source_release_id': CONFIG['source_release_id'], 'semantic_sha256': semantic_sha(a)},
        CONFIG['source_release_id'], semantic_sha(revised),
    )


class Recorder:
    def __init__(self, release_row=None):
        self.statements, self.release_row = [], release_row

    def execute(self, sql, params=None):
        self.statements.append(str(sql))
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(one=lambda: self.release_row, one_or_none=lambda: None),
            scalar_one=lambda: 0, scalar_one_or_none=lambda: None,
        )

    def begin(self):
        conn = self

        class Context:
            def __enter__(self): return conn
            def __exit__(self, *_): return False

        return Context()


def test_failed_retrieval_and_held_candidates_never_touch_active_pointer(tmp_path):
    def broken(_directory):
        raise RuntimeError('CDC HDS download failed after 3 attempts')
    engine = Recorder()
    _, report = hds_mortality_cli.fetch_stage(engine, CONFIG, directory=tmp_path, retrieved=broken)
    assert report == {'status': 'held', 'hold_reason': 'CDC HDS download failed after 3 attempts'}
    assert not any('active_release' in s for s in engine.statements)

    held = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'held', 'report': {'hold_reason': 'validation_failed'}})
    with pytest.raises(ValueError, match='not ready'):
        hds_mortality_cli.publish(held, CONFIG, 'c', 'a', 'b', 'c')
    with pytest.raises(ValueError, match='not an eligible'):
        hds_mortality_cli.release_reviewed_hold(held, CONFIG, 'c', 'a', 'b', 'c', 'reviewed')
    ready = Recorder({
        'dataset_id': CONFIG['dataset_id'], 'status': 'ready',
        'semantic_sha256': 'x', 'schema_sha256': 'y', 'metadata_sha256': 'z',
    })
    with pytest.raises(ValueError, match='reviewed checksums'):
        hds_mortality_cli.publish(ready, CONFIG, 'c', 'x', 'y', 'other')
    with pytest.raises(ValueError, match='retained published'):
        hds_mortality_cli.set_pointer(Recorder(), CONFIG, 'rollback', 'not-published')


# ---------------------------------------------------------------- read API & lookup

class PublishedDB:
    def execute(self, *_):
        return SimpleNamespace(scalar_one_or_none=lambda: 'published')


def test_selection_supports_state_and_county_and_explains_missing_tracts():
    measure = CONFIG['measures'][0]
    for geography in ('state', 'county'):
        vt = CONFIG['value_type_by_level'][geography]
        assert hds_mortality_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
            '2022–2024', measure['population'], vt, geography,
        )[1] == measure
    with pytest.raises(HTTPException) as error:
        hds_mortality_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
            '2022–2024', measure['population'], COUNTY_VT, 'tract',
        )
    assert error.value.status_code == 400 and 'no tract' in error.value.detail
    with pytest.raises(HTTPException) as error:
        hds_mortality_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
            '2022–2024', measure['population'], STATE_VT, 'county',
        )
    assert error.value.status_code == 400
    for path in ('/area/catalog', '/area/map', '/area/legend', '/area/table'):
        assert not _is_public_path(path)


def test_viewport_cap_returns_413():
    class DB:
        def execute(self, *_):
            return SimpleNamespace(scalar_one=lambda: hds_mortality_api.CAP + 1)
    with pytest.raises(HTTPException) as error:
        hds_mortality_api.ensure_cap(DB(), {})
    assert error.value.status_code == 413


def test_api_metadata_quantile_legend_national_ref_and_lookup_spec():
    class Result:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows
        def __iter__(self): return iter(self.rows)
        def one(self): return self.rows[0]
        def one_or_none(self): return self.rows[0] if self.rows else None

    rows = [
        {'geography_id': '37063', 'name': 'Durham', 'value': Decimal('227.2'),
         'source_value': '227.2', 'status': 'available'},
        {'geography_id': '02060', 'name': 'Bristol Bay', 'value': None,
         'source_value': '~', 'status': 'suppressed'},
        {'geography_id': '09110', 'name': 'Capitol Planning Region', 'value': None,
         'source_value': None, 'status': 'not_in_release'},
    ]

    class DB:
        def execute(self, sql, params):
            query = str(sql)
            if "geo_level='national'" in query:
                assert params['value_type'] == STATE_VT
                return Result([{'value': Decimal('315.3'), 'source_value': '315.3', 'status': 'available'}])
            if 'percentile_cont' in query:
                assert 'geo_level=:level' in query and 'ST_MakeEnvelope' not in query
                return Result([{'n': 3200, 'cuts': [Decimal('260.0'), Decimal('310.0'), Decimal('360.0'), Decimal('420.0')]}])
            assert 'LEFT JOIN area_pilot.observation_cdc_hds_mortality' in query and 'b.level=:level' in query
            if 'GROUP BY' in query:
                return Result([
                    {'status': 'available', 'n': 1, 'low': Decimal('227.2'), 'high': Decimal('227.2')},
                    {'status': 'not_in_release', 'n': 1, 'low': None, 'high': None},
                    {'status': 'suppressed', 'n': 1, 'low': None, 'high': None},
                ])
            out = [dict(r) for r in rows]
            if 'ST_AsGeoJSON' in query:
                for item in out:
                    item['geometry'] = {'type': 'Polygon', 'coordinates': []}
            return Result(out)

    measure = CONFIG['measures'][0]
    base = hds_mortality_api.metadata(CONFIG, measure, 'rel-hds', 'county', '-180,-90,180,90')
    assert base['value_type'] == COUNTY_VT
    assert base['period'] == '2022–2024'
    assert base['population'] == 'Adults aged 35 and older'
    assert base['uncertainty'] == 'not published'
    assert 'legend_breaks' not in base

    p = {'release': 'rel-hds', 'measure': 'heart_disease_death_rate', 'period': '2022–2024',
         'population': 'Adults aged 35 and older', 'value_type': COUNTY_VT, 'level': 'county'}
    mapped = hds_mortality_api.map_data(DB(), p, 3, base, 0.04)
    table = hds_mortality_api.table(DB(), p, base, 3, 100, 0)
    legend = hds_mortality_api.legend(DB(), p, base)

    props = [f['properties'] for f in mapped['features']]
    assert [(x['value'], x['status']) for x in props] == [(r['value'], r['status']) for r in table['rows']]
    assert props[0]['value'] == 227.2
    assert props[1]['status'] == 'suppressed' and props[1]['value'] is None
    assert props[1]['status_text'] == 'Insufficient data (CDC Heart Disease and Stroke Atlas)'
    assert props[2]['status'] == 'not_in_release' and props[2]['value'] is None
    assert sum(s['n'] for s in legend['statuses']) == mapped['count'] == table['total'] == 3
    assert legend['national_reference']['value'] == 315.3
    assert legend['quantile_breaks'] == [260.0, 310.0, 360.0, 420.0]
    assert legend['quantile_basis'] == 'quintiles_of_published_values_in_release'
    assert legend['limitations'] == CONFIG['limitations']

    # Verify lookup.SPECS, MISSING_STATUS, no SOURCE_CREDITS, and level-specific value_type support.
    spec = next(s for s in lookup.SPECS if s.key == 'cdc_hds_mortality')
    assert spec.tables == {
        'state': ('observation_cdc_hds_mortality', 'geoid', 'geo_level'),
        'county': ('observation_cdc_hds_mortality', 'geoid', 'geo_level'),
    }
    assert spec.extra == ('source_value',) and spec.uncertainty == 'none'
    assert lookup.MISSING_STATUS['cdc_hds_mortality']('09110', 'county') == lookup.NOT_IN_RELEASE
    assert not any(k[0] == 'cdc_hds_mortality' for k in lookup.SOURCE_CREDITS)

    class LookupDB:
        def execute(self, statement, params=None):
            sql = str(statement)
            if 'active_release' in sql:
                return Result([{
                    'dataset_id': CONFIG['dataset_id'], 'id': 'rel-hds',
                    'source_release_id': CONFIG['source_release_id'], 'published_at': None,
                }])
            if "geo_level='national'" in sql:
                return Result([{
                    'measure_id': 'heart_disease_death_rate', 'observation_period': '2022–2024',
                    'population': 'Adults aged 35 and older', 'value_type': STATE_VT,
                    'value': Decimal('315.3'), 'status': 'available', 'source_value': '315.3',
                }])
            if 'observation_cdc_hds_mortality' in sql:
                return Result([
                    {'geoid': '37063', 'measure_id': 'heart_disease_death_rate', 'observation_period': '2022–2024',
                     'population': 'Adults aged 35 and older', 'value_type': COUNTY_VT,
                     'value': Decimal('227.2'), 'status': 'available', 'source_value': '227.2'},
                    {'geoid': '02060', 'measure_id': 'heart_disease_death_rate', 'observation_period': '2022–2024',
                     'population': 'Adults aged 35 and older', 'value_type': COUNTY_VT,
                     'value': None, 'status': 'suppressed', 'source_value': '~'},
                ])
            return Result([])

    vals = lookup.area_values(
        LookupDB(), 'county', ['37063', '02060', '09110'],
        products=['cdc_hds_mortality'], measure_ids=['heart_disease_death_rate'],
    )['values']
    by_geo = {v['geoid']: v for v in vals}
    assert by_geo['37063']['value'] == 227.2 and by_geo['37063']['value_type'] == COUNTY_VT
    assert by_geo['02060']['status'] == 'suppressed'
    assert by_geo['02060']['status_text'] == 'Insufficient data (CDC Heart Disease and Stroke Atlas)'
    assert by_geo['09110']['status'] == lookup.NOT_IN_RELEASE and by_geo['09110']['value'] is None

    nat = [r for r in lookup.national_reference(LookupDB()) if r['product'] == 'cdc_hds_mortality']
    assert len(nat) == 1 and nat[0]['geoid'] == 'US' and nat[0]['value'] == 315.3
