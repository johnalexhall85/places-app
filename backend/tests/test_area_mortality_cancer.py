"""Unit tests for NCI cancer mortality parsing, classification, lifecycle, and read API."""
import copy
import csv
import io
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot import cancer_mortality, cancer_mortality_api, cancer_mortality_cli, lookup
from app.area_pilot.cancer_mortality import (
    CI_HIGH_COLUMN, CI_LOW_COLUMN, COUNT_COLUMN, LEGACY_CT_COUNTIES, RATE_COLUMN,
    boundary_without_source, classify, load_registry, observation_values, parse_csv,
    parse_value, range_problems, retrieve, semantic_sha,
)
from app.area_pilot.source import same_label_revision
from app.demo_access.middleware import _is_public_path

CONFIG = load_registry()
ALL_COUNTY_SPEC = CONFIG['source_files'][0]
ALL_STATE_SPEC = CONFIG['source_files'][1]
LUNG_COUNTY_SPEC = CONFIG['source_files'][2]
LUNG_STATE_SPEC = CONFIG['source_files'][3]
COLORECTAL_COUNTY_SPEC = CONFIG['source_files'][4]
COLORECTAL_STATE_SPEC = CONFIG['source_files'][5]

HP_BY_PREFIX = {'all': '122.7', 'lung': '25.1', 'colorectal': '8.9'}


def make_header(source_level, prefix='all'):
    hp = HP_BY_PREFIX[prefix]
    if source_level == 'County':
        return [
            'County', 'FIPS', '2023 Rural-Urban Continuum Codes([rural urban note])',
            f'Met Healthy People Objective of {hp}?', RATE_COLUMN, CI_LOW_COLUMN, CI_HIGH_COLUMN,
            'CI*Rank([rank note])', 'Lower CI (CI*Rank)', 'Upper CI (CI*Rank)', COUNT_COLUMN,
            'Recent Trend', 'Recent 5-Year Trend ([trend note]) in Death Rates',
            'Lower 95% Confidence Interval', 'Upper 95% Confidence Interval',
        ]
    return [
        'State', 'FIPS', f'Met Healthy People Objective of {hp}?', RATE_COLUMN, CI_LOW_COLUMN,
        CI_HIGH_COLUMN, 'CI*Rank([rank note])', 'Lower CI (CI*Rank)', 'Upper CI (CI*Rank)',
        COUNT_COLUMN, 'Recent Trend', 'Recent 5-Year Trend ([trend note]) in Death Rates',
        'Lower 95% Confidence Interval', 'Upper 95% Confidence Interval',
    ]


def make_row(source_level='County', area='Durham County, North Carolina', fips='37063',
             rate='132.6 ', ci_low='127.2', ci_high=' 138.2', count='468'):
    if source_level == 'County':
        return [
            area, fips, 'Urban', 'No', rate, ci_low, ci_high,
            '4', '3', '5', count, 'falling', '-1.2', '-1.8', '-0.6',
        ]
    return [
        area, fips, 'No', rate, ci_low, ci_high,
        '4', '3', '5', count, 'falling', '-1.2', '-1.8', '-0.6',
    ]


def write_nci_csv(path, spec, rows, title=None, footnotes=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = make_header(spec['source_level'], spec['file_prefix'])
    report_title = title if title is not None else spec['expected_title']
    buf = io.StringIO()
    report_heading = (
        'Death Rate Report for United States by County'
        if spec['source_level'] == 'County' else 'Death Rate Report by State'
    )
    buf.write(f'{report_heading}\n\n"{report_title}"\n\n')
    buf.write('"All Races (includes Hispanic), Both Sexes, All Ages"\n\nSorted by Rate\n\n')
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    if footnotes:
        buf.write('\n"* Data has been suppressed to ensure confidentiality."\n')
        buf.write('"Data for United States does not include Puerto Rico."\n')
        buf.write('"Notes with latin-1 char: \xe9 and \u2013"\n'.encode('latin-1', errors='replace').decode('latin-1'))
    path.write_bytes(buf.getvalue().encode('latin-1'))
    return path


def make_record(source_level='County', prefix='all', **kwargs):
    return dict(zip(make_header(source_level, prefix), make_row(source_level=source_level, **kwargs)))


# ---------------------------------------------------------------- registry & contract

def test_registry_matches_nci_cancer_mortality_contract():
    assert CONFIG['dataset_id'] == 'nci_cancer_mortality_2020_2024'
    assert CONFIG['short_name'] == 'NCI cancer deaths'
    assert CONFIG['observation_period'] == '2020–2024'
    assert CONFIG['value_type'] == 'age_adjusted_rate'
    assert CONFIG['geographies'] == ['state', 'county']
    assert CONFIG['aggregation_method'] == 'none'
    assert not CONFIG['refresh_policy']['auto_publish']
    assert [m['measure_id'] for m in CONFIG['measures']] == [
        'cancer_death_rate_all', 'cancer_death_rate_lung', 'cancer_death_rate_colorectal',
    ]
    assert [m['label'] for m in CONFIG['measures']] == [
        'Cancer death rate, all sites (per 100,000, age-adjusted)',
        'Lung and bronchus cancer death rate (per 100,000, age-adjusted)',
        'Colon and rectum cancer death rate (per 100,000, age-adjusted)',
    ]
    assert all(
        m['population'] == 'All ages, both sexes (2000 U.S. standard population)'
        for m in CONFIG['measures']
    )
    assert len(CONFIG['source_files']) == 6
    assert not any(
        s['filename'].startswith(('breast_female', 'prostate')) for s in CONFIG['source_files']
    )
    assert len(CONFIG['limitations']) == 3
    assert cancer_mortality_api.LIMITATIONS == CONFIG['limitations']
    assert cancer_mortality_api.STATUS_TEXT == {
        'suppressed': 'Suppressed by NCI (fewer than 16 deaths in 2020–2024)',
    }
    comp = lookup.comparability('nci_cancer_mortality')
    assert comp['state_marker_levels'] == ['county']
    assert comp['national_marker_levels'] == ['state', 'county']
    assert comp['shared_axis_rule'] == 'same_product_measure_and_release_only'


# ---------------------------------------------------------------- parsing

def test_parse_value_handles_available_suppressed_and_rejects_bad_or_non_positive():
    measure = CONFIG['measures'][0]
    assert parse_value('132.6', '127.2', '138.2', measure) == (
        Decimal('132.6'), Decimal('127.2'), Decimal('138.2'), 'available',
    )
    assert parse_value('*', '*', '*', measure) == (None, None, None, 'suppressed')
    for bad in (
        ('', '', ''),
        ('N/A', '10', '20'),
        ('~', '~', '~'),
        ('0', '0', '1'),
        ('0.0', '0.0', '0.5'),
        ('-5.2', '-6.0', '-4.0'),
        ('*', '10', '20'),
        ('132.6', '*', '138.2'),
        ('132.6', '140.0', '138.2'),
        ('132.6', '120.0', '130.0'),
    ):
        with pytest.raises(ValueError):
            parse_value(*bad, measure)
    assert range_problems(Decimal('132.6'), measure) == []
    assert range_problems(Decimal('0'), measure) == ['outside_documented_scale']


def test_parse_csv_latin1_preamble_footnotes_suppressed_national_and_errors(tmp_path):
    county_rows = [
        make_row('County', 'United States', '00000', '143.2 ', '143', ' 143.4', '609828'),
        make_row('County', 'Durham County, North Carolina', '37063', '132.6 ', '127.2', ' 138.2', '468'),
        make_row('County', 'Aleutians East Borough, Alaska', '02013', '*', '*', '*', '3 or fewer'),
        make_row('County', 'Fairfield County, Connecticut', '09001', '116.5 ', '113.8', ' 119.3', '1473'),
        make_row('County', 'Do\xf1a Ana County, New Mexico', '35013', '128.4 ', '121.0', ' 136.1', '330'),
    ]
    path = write_nci_csv(tmp_path / 'all_county.csv', ALL_COUNTY_SPEC, county_rows)
    records, stats = parse_csv(path, ALL_COUNTY_SPEC, CONFIG)
    assert stats['data_rows'] == 5
    assert stats['suppressed_rows'] == 1
    assert stats['check_values'] == {
        'national': {'value': '143.2', 'ci_low': '143', 'ci_high': '143.4'},
        '37063': {'value': '132.6', 'ci_low': '127.2', 'ci_high': '138.2'},
    }
    assert records[('all_county.csv', 'County', '37063', '2020–2024')][COUNT_COLUMN] == '468'
    assert records[('all_county.csv', 'County', '02013', '2020–2024')][COUNT_COLUMN] == '3 or fewer'

    durham_obs = observation_values(
        records[('all_county.csv', 'County', '37063', '2020–2024')], 'all_county.csv', CONFIG,
    )
    assert durham_obs[0]['value'] == Decimal('132.6')
    assert durham_obs[0]['ci_low'] == Decimal('127.2')
    assert durham_obs[0]['ci_high'] == Decimal('138.2')
    assert durham_obs[0]['status'] == 'available'
    assert durham_obs[0]['value_type'] == 'age_adjusted_rate'

    sup_obs = observation_values(
        records[('all_county.csv', 'County', '02013', '2020–2024')], 'all_county.csv', CONFIG,
    )
    assert sup_obs[0]['value'] is None
    assert sup_obs[0]['ci_low'] is None and sup_obs[0]['ci_high'] is None
    assert sup_obs[0]['status'] == 'suppressed'
    assert sup_obs[0]['source_value'] == '*'

    # Bad title line, bad token, zero rate, duplicate FIPS stop parsing.
    with pytest.raises(ValueError, match='title line'):
        parse_csv(
            write_nci_csv(tmp_path / 'wrong_title.csv', ALL_COUNTY_SPEC, county_rows[:1],
                          title='All Cancer Sites, 2019-2023'),
            ALL_COUNTY_SPEC, CONFIG,
        )
    with pytest.raises(ValueError, match='Undocumented'):
        parse_csv(
            write_nci_csv(tmp_path / 'bad_tok.csv', ALL_COUNTY_SPEC, [make_row(rate='N/A')]),
            ALL_COUNTY_SPEC, CONFIG,
        )
    with pytest.raises(ValueError, match='Non-positive'):
        parse_csv(
            write_nci_csv(tmp_path / 'zero.csv', ALL_COUNTY_SPEC, [make_row(rate='0', ci_low='0', ci_high='1')]),
            ALL_COUNTY_SPEC, CONFIG,
        )
    with pytest.raises(ValueError, match='Duplicate'):
        parse_csv(
            write_nci_csv(tmp_path / 'dup.csv', ALL_COUNTY_SPEC, [make_row(), make_row()]),
            ALL_COUNTY_SPEC, CONFIG,
        )


def test_retrieve_skip_fetch_ignores_breast_and_prostate_and_mocked_fetch(tmp_path, monkeypatch):
    for spec in CONFIG['source_files']:
        nat = spec['check_values']['national']
        rows = [make_row(spec['source_level'], 'United States', '00000',
                         nat['value'], nat['ci_low'], nat['ci_high'], '1000')]
        if '37063' in spec['check_values']:
            d = spec['check_values']['37063']
            rows.append(make_row('County', 'Durham County, North Carolina', '37063',
                                 d['value'], d['ci_low'], d['ci_high'], '100'))
        else:
            rows.append(make_row('State', 'North Carolina', '37000', '151.9', '150.9', '152.8', '20558'))
        write_nci_csv(tmp_path / spec['filename'], spec, rows)
    # Extra archived files that must NOT be staged or published.
    (tmp_path / 'breast_female_county.csv').write_text('ignored', encoding='latin-1')
    (tmp_path / 'prostate_county.csv').write_text('ignored', encoding='latin-1')

    records, stats, files, prov = retrieve(CONFIG, tmp_path, skip_fetch=True)
    assert len(files) == 6
    assert len(records) == 12
    assert not any('breast' in k[0] or 'prostate' in k[0] for k in records)
    assert all(len(f['sha256']) == 64 and f['byte_count'] > 0 for f in files)
    assert prov['skip_fetch'] is True

    fetched = []
    def fake_get(url, target, limit):
        fetched.append((url, target.name))
        target.write_text('stub', encoding='latin-1')
        return {'content-length': '4'}
    monkeypatch.setattr(cancer_mortality, '_bounded_get', fake_get)
    monkeypatch.setattr('app.area_pilot.operations.disk_guard', lambda *_a, **_k: None)
    f_files, _ = cancer_mortality.fetch(CONFIG, tmp_path / 'dl')
    assert len(f_files) == 6
    assert all('statecancerprofiles.cancer.gov/deathrates/index.php' in u for u, _ in fetched)


# ---------------------------------------------------------------- geography & validation

def test_classify_national_state_county_legacy_ct_pr_aggregate_and_dedup_us():
    records = {
        ('all_state.csv', 'State', '00000', '2020–2024'): make_record(
            'State', 'all', area='United States', fips='00000', rate='143.2', ci_low='143', ci_high='143.4',
        ),
        ('all_state.csv', 'State', '37000', '2020–2024'): make_record(
            'State', 'all', area='North Carolina', fips='37000', rate='151.9', ci_low='150.9', ci_high='152.8',
        ),
        ('all_state.csv', 'State', '02900', '2020–2024'): make_record(
            'State', 'all', area='Alaska', fips='02900', rate='148.1', ci_low='144', ci_high='152.4',
        ),
        ('all_state.csv', 'State', '11001', '2020–2024'): make_record(
            'State', 'all', area='District of Columbia', fips='11001', rate='139.8', ci_low='135.8', ci_high='143.8',
        ),
        ('all_county.csv', 'County', '00000', '2020–2024'): make_record(
            'County', 'all', area='United States', fips='00000', rate='143.2', ci_low='143', ci_high='143.4',
        ),
        ('all_county.csv', 'County', '37063', '2020–2024'): make_record(
            'County', 'all', area='Durham County, North Carolina', fips='37063',
            rate='132.6', ci_low='127.2', ci_high='138.2',
        ),
        ('all_county.csv', 'County', '09001', '2020–2024'): make_record(
            'County', 'all', area='Fairfield County, Connecticut', fips='09001',
            rate='116.5', ci_low='113.8', ci_high='119.3',
        ),
        ('all_county.csv', 'County', '51917', '2020–2024'): make_record(
            'County', 'all', area='Bedford City and County, Virginia', fips='51917',
            rate='148.0', ci_low='138.0', ci_high='158.0',
        ),
        ('all_county.csv', 'County', '72001', '2020–2024'): make_record(
            'County', 'all', area='Puerto Rico', fips='72001',
            rate='98.6', ci_low='97.4', ci_high='99.8',
        ),
    }
    classified, issues = classify(records, {'37', '09', '02', '11', '72'}, {'37063', '09110', '11001', '72001'}, CONFIG)
    assert issues['unexplained'] == []
    assert issues['duplicate_geoids'] == []
    assert classified[('all_state.csv', 'State', '00000', '2020–2024')]['boundary_status'] == 'national_reference'
    assert classified[('all_state.csv', 'State', '00000', '2020–2024')]['geoid'] == 'US'
    assert (
        classified[('all_county.csv', 'County', '00000', '2020–2024')]['exclusion_reason']
        == 'duplicate_national_row_in_county_file'
    )
    assert classified[('all_state.csv', 'State', '37000', '2020–2024')]['boundary_status'] == 'matched'
    assert classified[('all_state.csv', 'State', '37000', '2020–2024')]['geoid'] == '37'
    # Contract Amendment 1: NCI's state-file codes for AK and DC publish at state level.
    assert classified[('all_state.csv', 'State', '02900', '2020–2024')]['geoid'] == '02'
    assert classified[('all_state.csv', 'State', '11001', '2020–2024')]['geoid'] == '11'
    assert classified[('all_state.csv', 'State', '11001', '2020–2024')]['boundary_status'] == 'matched'
    assert classified[('all_county.csv', 'County', '37063', '2020–2024')]['boundary_status'] == 'matched'
    assert (
        classified[('all_county.csv', 'County', '09001', '2020–2024')]['exclusion_reason']
        == 'legacy_connecticut_county_code'
    )
    assert classified[('all_county.csv', 'County', '51917', '2020–2024')]['exclusion_reason'] == 'no_2024_boundary'
    assert (
        classified[('all_county.csv', 'County', '72001', '2020–2024')]['exclusion_reason']
        == 'puerto_rico_territory_aggregate_not_county'
    )
    assert len(LEGACY_CT_COUNTIES) == 8

    expected = cancer_mortality_cli.expected_observations(records, classified, CONFIG)
    assert set(expected) == {
        ('national', 'US', 'cancer_death_rate_all', '2020–2024'),
        ('state', '37', 'cancer_death_rate_all', '2020–2024'),
        ('state', '02', 'cancer_death_rate_all', '2020–2024'),
        ('state', '11', 'cancer_death_rate_all', '2020–2024'),
        ('county', '37063', 'cancer_death_rate_all', '2020–2024'),
    }
    assert expected[('county', '37063', 'cancer_death_rate_all', '2020–2024')][:3] == (
        Decimal('132.6'), Decimal('127.2'), Decimal('138.2'),
    )

    uncovered, coverage = boundary_without_source(classified, {'37', '09'}, {'37063', '09110'}, CONFIG)
    assert uncovered == {
        'state:09': 'no_source_row',
        'county:09110': 'connecticut_planning_region_not_in_source',
    }
    assert coverage['counts']['county|connecticut_planning_region_not_in_source'] == 1


def test_validate_counts_and_checks_enforces_contract_counts_and_checks():
    good_stats = {
        'files': {
            spec['filename']: {
                'data_rows': spec['expected_data_rows'],
                'suppressed_rows': spec['expected_suppressed_rows'],
                'check_values': copy.deepcopy(spec['check_values']),
            }
            for spec in CONFIG['source_files']
        }
    }
    assert cancer_mortality_cli.validate_counts_and_checks(good_stats, CONFIG)[:3] == (True, True, True)

    bad_counts = copy.deepcopy(good_stats)
    bad_counts['files']['all_county.csv']['data_rows'] = 3143
    assert cancer_mortality_cli.validate_counts_and_checks(bad_counts, CONFIG)[:3] == (False, True, True)

    bad_sup = copy.deepcopy(good_stats)
    bad_sup['files']['lung_county.csv']['suppressed_rows'] = 417
    assert cancer_mortality_cli.validate_counts_and_checks(bad_sup, CONFIG)[:3] == (True, False, True)

    bad_check = copy.deepcopy(good_stats)
    bad_check['files']['all_county.csv']['check_values']['37063']['value'] = '132.9'
    assert cancer_mortality_cli.validate_counts_and_checks(bad_check, CONFIG)[:3] == (True, True, False)

    bad_nat = copy.deepcopy(good_stats)
    bad_nat['files']['all_state.csv']['check_values']['national']['value'] = '143.9'
    assert cancer_mortality_cli.validate_counts_and_checks(bad_nat, CONFIG)[:3] == (True, True, False)


# ---------------------------------------------------------------- lifecycle guards

def test_semantic_sha_is_order_independent_and_detects_revisions():
    a = {
        ('all_state.csv', 'State', '37000', '2020–2024'): make_record(
            'State', 'all', area='North Carolina', fips='37000', rate='151.9', ci_low='150.9', ci_high='152.8',
        ),
        ('lung_state.csv', 'State', '37000', '2020–2024'): make_record(
            'State', 'lung', area='North Carolina', fips='37000', rate='35.0', ci_low='34.5', ci_high='35.5',
        ),
    }
    b = dict(reversed(list(a.items())))
    assert semantic_sha(a) == semantic_sha(b)
    revised = dict(a) | {
        ('all_state.csv', 'State', '37000', '2020–2024'): make_record(
            'State', 'all', area='North Carolina', fips='37000', rate='152.0', ci_low='150.9', ci_high='152.8',
        ),
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
        raise RuntimeError('NCI cancer download failed after 3 attempts')
    engine = Recorder()
    _, report = cancer_mortality_cli.fetch_stage(engine, CONFIG, directory=tmp_path, retrieved=broken)
    assert report == {'status': 'held', 'hold_reason': 'NCI cancer download failed after 3 attempts'}
    assert not any('active_release' in s for s in engine.statements)

    held = Recorder({
        'dataset_id': CONFIG['dataset_id'], 'status': 'held', 'report': {'hold_reason': 'validation_failed'},
    })
    with pytest.raises(ValueError, match='not ready'):
        cancer_mortality_cli.publish(held, CONFIG, 'c', 'a', 'b', 'c')
    with pytest.raises(ValueError, match='not an eligible'):
        cancer_mortality_cli.release_reviewed_hold(held, CONFIG, 'c', 'a', 'b', 'c', 'reviewed')
    ready = Recorder({
        'dataset_id': CONFIG['dataset_id'], 'status': 'ready',
        'semantic_sha256': 'x', 'schema_sha256': 'y', 'metadata_sha256': 'z',
    })
    with pytest.raises(ValueError, match='reviewed checksums'):
        cancer_mortality_cli.publish(ready, CONFIG, 'c', 'x', 'y', 'other')
    with pytest.raises(ValueError, match='retained published'):
        cancer_mortality_cli.set_pointer(Recorder(), CONFIG, 'rollback', 'not-published')


# ---------------------------------------------------------------- read API & lookup

class PublishedDB:
    def execute(self, *_):
        return SimpleNamespace(scalar_one_or_none=lambda: 'published')


def test_selection_supports_state_and_county_and_explains_missing_tracts():
    measure = CONFIG['measures'][0]
    for geography in ('state', 'county'):
        assert cancer_mortality_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
            '2020–2024', measure['population'], 'age_adjusted_rate', geography,
        )[1] == measure
    with pytest.raises(HTTPException) as error:
        cancer_mortality_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
            '2020–2024', measure['population'], 'age_adjusted_rate', 'tract',
        )
    assert error.value.status_code == 400 and 'no tract' in error.value.detail
    with pytest.raises(HTTPException) as error:
        cancer_mortality_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
            '2020–2024', measure['population'], 'wrong_type', 'county',
        )
    assert error.value.status_code == 400
    for path in ('/area/catalog', '/area/map', '/area/legend', '/area/table'):
        assert not _is_public_path(path)


def test_viewport_cap_returns_413():
    class DB:
        def execute(self, *_):
            return SimpleNamespace(scalar_one=lambda: cancer_mortality_api.CAP + 1)
    with pytest.raises(HTTPException) as error:
        cancer_mortality_api.ensure_cap(DB(), {})
    assert error.value.status_code == 413


def test_api_metadata_ci_quantile_legend_national_ref_and_lookup_spec():
    class Result:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows
        def __iter__(self): return iter(self.rows)
        def one(self): return self.rows[0]
        def one_or_none(self): return self.rows[0] if self.rows else None

    rows = [
        {'geography_id': '37063', 'name': 'Durham', 'value': Decimal('132.6'),
         'ci_low': Decimal('127.2'), 'ci_high': Decimal('138.2'),
         'source_value': '132.6', 'status': 'available'},
        {'geography_id': '02013', 'name': 'Aleutians East', 'value': None,
         'ci_low': None, 'ci_high': None, 'source_value': '*', 'status': 'suppressed'},
        {'geography_id': '09110', 'name': 'Capitol Planning Region', 'value': None,
         'ci_low': None, 'ci_high': None, 'source_value': None, 'status': 'not_in_release'},
    ]

    class DB:
        def execute(self, sql, params):
            query = str(sql)
            if "geo_level='national'" in query:
                return Result([{
                    'value': Decimal('143.2'), 'ci_low': Decimal('143'), 'ci_high': Decimal('143.4'),
                    'source_value': '143.2', 'status': 'available',
                }])
            if 'percentile_cont' in query:
                assert 'geo_level=:level' in query and 'ST_MakeEnvelope' not in query
                return Result([{'n': 3070, 'cuts': [Decimal('135.0'), Decimal('150.0'), Decimal('165.0'), Decimal('180.0')]}])
            assert 'LEFT JOIN area_pilot.observation_nci_cancer_mortality' in query and 'b.level=:level' in query
            if 'GROUP BY' in query:
                return Result([
                    {'status': 'available', 'n': 1, 'low': Decimal('132.6'), 'high': Decimal('132.6')},
                    {'status': 'not_in_release', 'n': 1, 'low': None, 'high': None},
                    {'status': 'suppressed', 'n': 1, 'low': None, 'high': None},
                ])
            out = [dict(r) for r in rows]
            if 'ST_AsGeoJSON' in query:
                for item in out:
                    item['geometry'] = {'type': 'Polygon', 'coordinates': []}
            return Result(out)

    measure = CONFIG['measures'][0]
    base = cancer_mortality_api.metadata(CONFIG, measure, 'rel-nci', 'county', '-180,-90,180,90')
    assert base['value_type'] == 'age_adjusted_rate'
    assert base['period'] == '2020–2024'
    assert base['population'] == 'All ages, both sexes (2000 U.S. standard population)'
    assert base['uncertainty'] == '95% confidence interval'
    assert base['uncertainty_kind'] == 'ci95'

    p = {'release': 'rel-nci', 'measure': 'cancer_death_rate_all', 'period': '2020–2024',
         'population': measure['population'], 'value_type': 'age_adjusted_rate', 'level': 'county'}
    mapped = cancer_mortality_api.map_data(DB(), p, 3, base, 0.04)
    table = cancer_mortality_api.table(DB(), p, base, 3, 100, 0)
    legend = cancer_mortality_api.legend(DB(), p, base)

    props = [f['properties'] for f in mapped['features']]
    assert [(x['value'], x['ci_low'], x['ci_high'], x['status']) for x in props] == [
        (r['value'], r['ci_low'], r['ci_high'], r['status']) for r in table['rows']
    ]
    assert props[0]['value'] == 132.6 and props[0]['ci_low'] == 127.2 and props[0]['ci_high'] == 138.2
    assert props[1]['status'] == 'suppressed' and props[1]['value'] is None and props[1]['ci_low'] is None
    assert props[1]['status_text'] == 'Suppressed by NCI (fewer than 16 deaths in 2020–2024)'
    assert props[2]['status'] == 'not_in_release' and props[2]['value'] is None
    assert sum(s['n'] for s in legend['statuses']) == mapped['count'] == table['total'] == 3
    assert legend['national_reference']['value'] == 143.2
    assert legend['national_reference']['ci_low'] == 143.0
    assert legend['national_reference']['ci_high'] == 143.4
    assert legend['quantile_breaks'] == [135.0, 150.0, 165.0, 180.0]
    assert legend['quantile_basis'] == 'quintiles_of_published_values_in_release'
    assert legend['limitations'] == CONFIG['limitations']

    spec = next(s for s in lookup.SPECS if s.key == 'nci_cancer_mortality')
    assert spec.tables == {
        'state': ('observation_nci_cancer_mortality', 'geoid', 'geo_level'),
        'county': ('observation_nci_cancer_mortality', 'geoid', 'geo_level'),
    }
    assert spec.extra == ('source_value', 'ci_low', 'ci_high') and spec.uncertainty == 'ci95'
    assert lookup.MISSING_STATUS['nci_cancer_mortality']('09110', 'county') == lookup.NOT_IN_RELEASE
    assert not any(k[0] == 'nci_cancer_mortality' for k in lookup.SOURCE_CREDITS)

    class LookupDB:
        def execute(self, statement, params=None):
            sql = str(statement)
            if 'active_release' in sql:
                return Result([{
                    'dataset_id': CONFIG['dataset_id'], 'id': 'rel-nci',
                    'source_release_id': CONFIG['source_release_id'], 'published_at': None,
                }])
            if "geo_level='national'" in sql:
                return Result([{
                    'measure_id': 'cancer_death_rate_all', 'observation_period': '2020–2024',
                    'population': measure['population'], 'value_type': 'age_adjusted_rate',
                    'value': Decimal('143.2'), 'ci_low': Decimal('143'), 'ci_high': Decimal('143.4'),
                    'status': 'available', 'source_value': '143.2',
                }])
            if 'observation_nci_cancer_mortality' in sql:
                return Result([
                    {'geoid': '37063', 'measure_id': 'cancer_death_rate_all', 'observation_period': '2020–2024',
                     'population': measure['population'], 'value_type': 'age_adjusted_rate',
                     'value': Decimal('132.6'), 'ci_low': Decimal('127.2'), 'ci_high': Decimal('138.2'),
                     'status': 'available', 'source_value': '132.6'},
                    {'geoid': '02013', 'measure_id': 'cancer_death_rate_all', 'observation_period': '2020–2024',
                     'population': measure['population'], 'value_type': 'age_adjusted_rate',
                     'value': None, 'ci_low': None, 'ci_high': None,
                     'status': 'suppressed', 'source_value': '*'},
                ])
            return Result([])

    vals = lookup.area_values(
        LookupDB(), 'county', ['37063', '02013', '09110'],
        products=['nci_cancer_mortality'], measure_ids=['cancer_death_rate_all'],
    )['values']
    by_geo = {v['geoid']: v for v in vals}
    assert by_geo['37063']['value'] == 132.6
    assert by_geo['37063']['uncertainty'] == {
        'kind': 'ci95', 'low': 127.2, 'high': 138.2, 'label': '95% confidence interval',
    }
    assert by_geo['02013']['status'] == 'suppressed'
    assert by_geo['02013']['uncertainty'] == {
        'kind': 'ci95', 'low': None, 'high': None, 'label': '95% confidence interval',
    }
    assert by_geo['02013']['status_text'] == 'Suppressed by NCI (fewer than 16 deaths in 2020–2024)'
    assert by_geo['09110']['status'] == lookup.NOT_IN_RELEASE and by_geo['09110']['value'] is None

    nat = [r for r in lookup.national_reference(LookupDB()) if r['product'] == 'nci_cancer_mortality']
    assert len(nat) == 1 and nat[0]['geoid'] == 'US' and nat[0]['value'] == 143.2
    assert nat[0]['uncertainty']['low'] == 143 and nat[0]['uncertainty']['high'] == 143.4
