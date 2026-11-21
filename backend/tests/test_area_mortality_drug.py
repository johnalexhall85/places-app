"""Unit tests for NCHS drug poisoning mortality parsing, classification, lifecycle, and read API."""
import copy
import csv
import io
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot import drug_poisoning, drug_poisoning_api, drug_poisoning_cli, lookup
from app.area_pilot.drug_poisoning import (
    LEGACY_CT_COUNTIES, REQUIRED_COLUMNS, boundary_without_source, classify, load_registry,
    normalize_code, observation_values, parse_csv, parse_value, range_problems, retrieve,
    semantic_sha,
)
from app.area_pilot.source import same_label_revision
from app.demo_access.middleware import _is_public_path

CONFIG = load_registry()
SOURCE_SPEC = CONFIG['source_files'][0]
HEADER = list(REQUIRED_COLUMNS)


def make_row(fips='37063', year='2021', state='North Carolina', fips_state='37',
             county='Durham County, NC', population='326126', rate='23.87115',
             std_dev='0.92794', ci_low='22.12165', ci_high='25.75957',
             urban_rural='Medium Metro', division='5'):
    return [
        fips, year, state, fips_state, county, population,
        rate, std_dev, ci_low, ci_high, urban_rural, division,
    ]


def make_record(**kwargs):
    return dict(zip(HEADER, make_row(**kwargs)))


def write_drug_csv(path, rows, bom=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow(HEADER)
    writer.writerows(rows)
    encoding = 'utf-8-sig' if bom else 'utf-8'
    path.write_bytes(buf.getvalue().encode(encoding))
    return path


# ---------------------------------------------------------------- registry & contract

def test_registry_matches_nchs_drug_poisoning_contract():
    assert CONFIG['dataset_id'] == 'nchs_drug_poisoning_2021'
    assert CONFIG['short_name'] == 'NCHS drug poisoning deaths (modelled)'
    assert CONFIG['observation_period'] == '2021'
    assert CONFIG['observation_year'] == 2021
    assert CONFIG['value_type'] == 'model_based_age_adjusted_rate'
    assert CONFIG['geographies'] == ['county']
    assert CONFIG['aggregation_method'] == 'none'
    assert CONFIG['uncertainty'] == "95% interval from NCHS's model"
    assert not CONFIG['refresh_policy']['auto_publish']
    assert CONFIG['staged_years'] == [str(yr) for yr in range(2003, 2022)]
    assert [m['measure_id'] for m in CONFIG['measures']] == ['drug_poisoning_death_rate']
    assert CONFIG['measures'][0]['label'] == (
        'Drug poisoning death rate, model-based (per 100,000, age-adjusted)'
    )
    assert CONFIG['measures'][0]['population'] == 'All ages (2000 U.S. standard population)'
    assert len(CONFIG['source_files']) == 1
    assert len(CONFIG['limitations']) == 4
    assert drug_poisoning_api.LIMITATIONS == CONFIG['limitations']
    assert drug_poisoning_api.UNCERTAINTY_LABEL == "95% interval from NCHS's model"

    comp = lookup.comparability('nchs_drug_poisoning')
    assert comp['state_marker_levels'] == []
    assert comp['national_marker_levels'] == []
    assert comp['shared_axis_rule'] == 'same_product_measure_and_release_only'


# ---------------------------------------------------------------- parsing

def test_normalize_code_and_parse_value_edge_cases():
    assert normalize_code('1001') == '01001'
    assert normalize_code(' 9001 ') == '09001'
    assert normalize_code('37063') == '37063'
    assert normalize_code('BAD') == 'BAD'

    measure = CONFIG['measures'][0]
    assert parse_value('23.87115', '22.12165', '25.75957', measure) == (
        Decimal('23.87115'), Decimal('22.12165'), Decimal('25.75957'), 'available',
    )
    # Blank, suppressed tokens, undocumented tokens, zero, negative, and invalid CIs all stop the run.
    for bad in (
        ('', '22.1', '25.7'),
        ('*', '*', '*'),
        ('~', '~', '~'),
        ('Suppressed', '22.1', '25.7'),
        ('N/A', '22.1', '25.7'),
        ('0', '0', '1'),
        ('0.0', '0.0', '0.5'),
        ('-1.5', '-2.0', '-1.0'),
        ('23.87115', '', '25.75957'),
        ('23.87115', '22.12165', ''),
        ('23.87115', '25.0', '25.75957'),
        ('23.87115', '20.0', '22.0'),
        ('23.87115', '-1.0', '25.75957'),
    ):
        with pytest.raises(ValueError):
            parse_value(*bad, measure)
    assert range_problems(Decimal('23.87115'), measure) == []
    assert range_problems(Decimal('0'), measure) == ['outside_documented_scale']


def test_parse_csv_utf8_sig_zero_pads_stages_all_years_and_rejects_bad_2021(tmp_path):
    rows = [
        make_row(fips='1001', year='2003', state='Alabama', fips_state='1',
                 county='Autauga County, AL', rate='6.10000', ci_low='5.00000', ci_high='7.50000'),
        make_row(fips='1001', year='2021', state='Alabama', fips_state='1',
                 county='Autauga County, AL', rate='14.20000', ci_low='11.80000', ci_high='17.00000'),
        make_row(fips='37063', year='2020', rate='21.00000', ci_low='19.50000', ci_high='22.60000'),
        make_row(fips='37063', year='2021', rate='23.87115', ci_low='22.12165', ci_high='25.75957'),
        make_row(fips='9001', year='2021', state='Connecticut', fips_state='9',
                 county='Fairfield County, CT', rate='25.10000', ci_low='23.10000', ci_high='27.20000'),
    ]
    path = write_drug_csv(tmp_path / 'rpvx-m2md.csv', rows, bom=True)
    records, stats = parse_csv(path, SOURCE_SPEC, CONFIG)
    assert stats['total_rows'] == 5
    assert stats['year_counts'] == {'2003': 1, '2020': 1, '2021': 3}
    assert stats['publish_period_rows'] == 3
    assert stats['check_values'] == {
        '37063': {'value': '23.87115', 'ci_low': '22.12165', 'ci_high': '25.75957'},
    }
    assert ('rpvx-m2md.csv', 'County', '01001', '2003') in records
    assert ('rpvx-m2md.csv', 'County', '01001', '2021') in records
    assert ('rpvx-m2md.csv', 'County', '09001', '2021') in records

    durham_obs = observation_values(
        records[('rpvx-m2md.csv', 'County', '37063', '2021')], 'rpvx-m2md.csv', CONFIG,
    )
    assert durham_obs[0]['value'] == Decimal('23.87115')
    assert durham_obs[0]['ci_low'] == Decimal('22.12165')
    assert durham_obs[0]['ci_high'] == Decimal('25.75957')
    assert durham_obs[0]['status'] == 'available'
    assert durham_obs[0]['value_type'] == 'model_based_age_adjusted_rate'

    # Blank, suppressed marker, bad token, zero rate, unexpected year, and duplicates stop parsing.
    with pytest.raises(ValueError, match='Blank'):
        parse_csv(write_drug_csv(tmp_path / 'blank.csv', [make_row(rate='')]), SOURCE_SPEC, CONFIG)
    with pytest.raises(ValueError, match='Undocumented'):
        parse_csv(write_drug_csv(tmp_path / 'sup.csv', [make_row(rate='*')]), SOURCE_SPEC, CONFIG)
    with pytest.raises(ValueError, match='Undocumented'):
        parse_csv(write_drug_csv(tmp_path / 'bad.csv', [make_row(rate='N/A')]), SOURCE_SPEC, CONFIG)
    with pytest.raises(ValueError, match='Non-positive'):
        parse_csv(
            write_drug_csv(tmp_path / 'zero.csv', [make_row(rate='0', ci_low='0', ci_high='1')]),
            SOURCE_SPEC, CONFIG,
        )
    with pytest.raises(ValueError, match='Unexpected.*Year'):
        parse_csv(write_drug_csv(tmp_path / 'yr.csv', [make_row(year='2022')]), SOURCE_SPEC, CONFIG)
    with pytest.raises(ValueError, match='Duplicate'):
        parse_csv(write_drug_csv(tmp_path / 'dup.csv', [make_row(), make_row()]), SOURCE_SPEC, CONFIG)


def test_retrieve_skip_fetch_and_mocked_fetch(tmp_path, monkeypatch):
    write_drug_csv(tmp_path / 'rpvx-m2md.csv', [make_row(fips='37063', year='2021')])
    records, stats, files, prov = retrieve(CONFIG, tmp_path, skip_fetch=True)
    assert len(files) == 1
    assert len(records) == 1
    assert len(files[0]['sha256']) == 64 and files[0]['byte_count'] > 0
    assert prov['skip_fetch'] is True

    fetched = []
    def fake_get(url, target, limit):
        fetched.append((url, target.name))
        target.write_text('stub', encoding='utf-8')
        return {'content-length': '4'}
    monkeypatch.setattr(drug_poisoning, '_bounded_get', fake_get)
    monkeypatch.setattr('app.area_pilot.operations.disk_guard', lambda *_a, **_k: None)
    f_files, _ = drug_poisoning.fetch(CONFIG, tmp_path / 'dl')
    assert len(f_files) == 1
    assert fetched == [(SOURCE_SPEC['url'], 'rpvx-m2md.csv')]


# ---------------------------------------------------------------- geography & validation

def test_classify_stages_all_years_publishes_2021_only_and_handles_legacy_ct():
    records = {
        ('rpvx-m2md.csv', 'County', '37063', '2020'): make_record(fips='37063', year='2020', rate='21.0', ci_low='19.5', ci_high='22.6'),
        ('rpvx-m2md.csv', 'County', '37063', '2021'): make_record(fips='37063', year='2021'),
        ('rpvx-m2md.csv', 'County', '01001', '2021'): make_record(fips='1001', year='2021', rate='14.2', ci_low='11.8', ci_high='17.0'),
        ('rpvx-m2md.csv', 'County', '09001', '2021'): make_record(fips='9001', year='2021', rate='25.1', ci_low='23.1', ci_high='27.2'),
        ('rpvx-m2md.csv', 'County', '46113', '2021'): make_record(fips='46113', year='2021', rate='18.0', ci_low='15.0', ci_high='21.5'),
    }
    classified, issues = classify(records, {'37063', '01001', '09110', '72001'}, CONFIG)
    assert issues['unexplained'] == []
    assert issues['duplicate_geoids'] == []
    assert classified[('rpvx-m2md.csv', 'County', '37063', '2020')]['boundary_status'] == 'matched'
    assert classified[('rpvx-m2md.csv', 'County', '37063', '2021')]['boundary_status'] == 'matched'
    assert classified[('rpvx-m2md.csv', 'County', '01001', '2021')]['boundary_status'] == 'matched'
    assert (
        classified[('rpvx-m2md.csv', 'County', '09001', '2021')]['exclusion_reason']
        == 'legacy_connecticut_county_code'
    )
    assert classified[('rpvx-m2md.csv', 'County', '46113', '2021')]['exclusion_reason'] == 'no_2024_boundary'
    assert len(LEGACY_CT_COUNTIES) == 8

    # Observations publish 2021 matched counties ONLY (2020 remains staged only).
    expected = drug_poisoning_cli.expected_observations(records, classified, CONFIG)
    assert set(expected) == {
        ('county', '37063', 'drug_poisoning_death_rate', '2021'),
        ('county', '01001', 'drug_poisoning_death_rate', '2021'),
    }
    assert expected[('county', '37063', 'drug_poisoning_death_rate', '2021')][:3] == (
        Decimal('23.87115'), Decimal('22.12165'), Decimal('25.75957'),
    )

    uncovered, coverage = boundary_without_source(classified, {'37063', '01001', '09110', '72001'}, CONFIG)
    assert uncovered == {
        'county:09110': 'connecticut_planning_region_not_in_source',
        'county:72001': 'no_source_row',
    }
    assert coverage['counts'] == {
        'county|connecticut_planning_region_not_in_source': 1,
        'county|no_source_row': 1,
    }


def test_validate_counts_and_checks_enforces_contract_counts_years_and_durham():
    good_stats = {
        'files': {
            'rpvx-m2md.csv': {
                'total_rows': 59584,
                'year_counts': {str(yr): 3136 for yr in range(2003, 2022)},
                'check_values': copy.deepcopy(SOURCE_SPEC['check_values']),
            }
        }
    }
    assert drug_poisoning_cli.validate_counts_and_checks(good_stats, CONFIG)[:3] == (True, True, True)

    bad_total = copy.deepcopy(good_stats)
    bad_total['files']['rpvx-m2md.csv']['total_rows'] = 59583
    assert drug_poisoning_cli.validate_counts_and_checks(bad_total, CONFIG)[:3] == (False, True, True)

    bad_year_count = copy.deepcopy(good_stats)
    bad_year_count['files']['rpvx-m2md.csv']['year_counts']['2021'] = 3135
    assert drug_poisoning_cli.validate_counts_and_checks(bad_year_count, CONFIG)[:3] == (False, True, True)

    missing_year = copy.deepcopy(good_stats)
    del missing_year['files']['rpvx-m2md.csv']['year_counts']['2003']
    assert drug_poisoning_cli.validate_counts_and_checks(missing_year, CONFIG)[:3] == (False, False, True)

    bad_durham = copy.deepcopy(good_stats)
    bad_durham['files']['rpvx-m2md.csv']['check_values']['37063']['value'] = '24.00000'
    assert drug_poisoning_cli.validate_counts_and_checks(bad_durham, CONFIG)[:3] == (True, True, False)


# ---------------------------------------------------------------- lifecycle guards

def test_semantic_sha_is_order_independent_and_detects_revisions():
    a = {
        ('rpvx-m2md.csv', 'County', '37063', '2021'): make_record(fips='37063', year='2021'),
        ('rpvx-m2md.csv', 'County', '01001', '2021'): make_record(fips='1001', year='2021', rate='14.2', ci_low='11.8', ci_high='17.0'),
    }
    b = dict(reversed(list(a.items())))
    assert semantic_sha(a) == semantic_sha(b)
    revised = dict(a) | {
        ('rpvx-m2md.csv', 'County', '37063', '2021'): make_record(fips='37063', year='2021', rate='24.00000'),
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
        raise RuntimeError('NCHS download failed after 3 attempts')
    engine = Recorder()
    _, report = drug_poisoning_cli.fetch_stage(engine, CONFIG, directory=tmp_path, retrieved=broken)
    assert report == {'status': 'held', 'hold_reason': 'NCHS download failed after 3 attempts'}
    assert not any('active_release' in s for s in engine.statements)

    held = Recorder({
        'dataset_id': CONFIG['dataset_id'], 'status': 'held', 'report': {'hold_reason': 'validation_failed'},
    })
    with pytest.raises(ValueError, match='not ready'):
        drug_poisoning_cli.publish(held, CONFIG, 'c', 'a', 'b', 'c')
    with pytest.raises(ValueError, match='not an eligible'):
        drug_poisoning_cli.release_reviewed_hold(held, CONFIG, 'c', 'a', 'b', 'c', 'reviewed')
    ready = Recorder({
        'dataset_id': CONFIG['dataset_id'], 'status': 'ready',
        'semantic_sha256': 'x', 'schema_sha256': 'y', 'metadata_sha256': 'z',
    })
    with pytest.raises(ValueError, match='reviewed checksums'):
        drug_poisoning_cli.publish(ready, CONFIG, 'c', 'x', 'y', 'other')
    with pytest.raises(ValueError, match='retained published'):
        drug_poisoning_cli.set_pointer(Recorder(), CONFIG, 'rollback', 'not-published')


# ---------------------------------------------------------------- read API & lookup

class PublishedDB:
    def execute(self, *_):
        return SimpleNamespace(scalar_one_or_none=lambda: 'published')


def test_selection_supports_county_only_and_explains_missing_state_and_tract():
    measure = CONFIG['measures'][0]
    assert drug_poisoning_api.selection(
        PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
        '2021', measure['population'], 'model_based_age_adjusted_rate', 'county',
    )[1] == measure

    with pytest.raises(HTTPException) as error:
        drug_poisoning_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
            '2021', measure['population'], 'model_based_age_adjusted_rate', 'tract',
        )
    assert error.value.status_code == 400 and 'no tract' in error.value.detail

    with pytest.raises(HTTPException) as error:
        drug_poisoning_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
            '2021', measure['population'], 'model_based_age_adjusted_rate', 'state',
        )
    assert error.value.status_code == 400 and 'counties only' in error.value.detail

    with pytest.raises(HTTPException) as error:
        drug_poisoning_api.selection(
            PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'],
            '2021', measure['population'], 'wrong_type', 'county',
        )
    assert error.value.status_code == 400

    for path in ('/area/catalog', '/area/map', '/area/legend', '/area/table'):
        assert not _is_public_path(path)


def test_viewport_cap_returns_413():
    class DB:
        def execute(self, *_):
            return SimpleNamespace(scalar_one=lambda: drug_poisoning_api.CAP + 1)
    with pytest.raises(HTTPException) as error:
        drug_poisoning_api.ensure_cap(DB(), {})
    assert error.value.status_code == 413


def test_api_metadata_ci_quantile_legend_and_lookup_spec():
    class Result:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows
        def __iter__(self): return iter(self.rows)
        def one(self): return self.rows[0]
        def one_or_none(self): return self.rows[0] if self.rows else None

    rows = [
        {'geography_id': '37063', 'name': 'Durham', 'value': Decimal('23.87115'),
         'ci_low': Decimal('22.12165'), 'ci_high': Decimal('25.75957'),
         'source_value': '23.87115', 'status': 'available'},
        {'geography_id': '09110', 'name': 'Capitol Planning Region', 'value': None,
         'ci_low': None, 'ci_high': None, 'source_value': None, 'status': 'not_in_release'},
    ]

    class DB:
        def execute(self, sql, params):
            query = str(sql)
            if 'percentile_cont' in query:
                assert 'geo_level=:level' in query and 'ST_MakeEnvelope' not in query
                return Result([{'n': 3115, 'cuts': [Decimal('18.0'), Decimal('24.0'), Decimal('31.0'), Decimal('40.0')]}])
            assert 'LEFT JOIN area_pilot.observation_nchs_drug_poisoning' in query and 'b.level=:level' in query
            if 'GROUP BY' in query:
                return Result([
                    {'status': 'available', 'n': 1, 'low': Decimal('23.87115'), 'high': Decimal('23.87115')},
                    {'status': 'not_in_release', 'n': 1, 'low': None, 'high': None},
                ])
            out = [dict(r) for r in rows]
            if 'ST_AsGeoJSON' in query:
                for item in out:
                    item['geometry'] = {'type': 'Polygon', 'coordinates': []}
            return Result(out)

    measure = CONFIG['measures'][0]
    base = drug_poisoning_api.metadata(CONFIG, measure, 'rel-nchs', 'county', '-180,-90,180,90')
    assert base['value_type'] == 'model_based_age_adjusted_rate'
    assert base['period'] == '2021'
    assert base['population'] == 'All ages (2000 U.S. standard population)'
    assert base['uncertainty'] == "95% interval from NCHS's model"
    assert base['uncertainty_kind'] == 'ci95'

    p = {'release': 'rel-nchs', 'measure': 'drug_poisoning_death_rate', 'period': '2021',
         'population': measure['population'], 'value_type': 'model_based_age_adjusted_rate', 'level': 'county'}
    mapped = drug_poisoning_api.map_data(DB(), p, 2, base, 0.04)
    table = drug_poisoning_api.table(DB(), p, base, 2, 100, 0)
    legend = drug_poisoning_api.legend(DB(), p, base)

    props = [f['properties'] for f in mapped['features']]
    assert [(x['value'], x['ci_low'], x['ci_high'], x['status']) for x in props] == [
        (r['value'], r['ci_low'], r['ci_high'], r['status']) for r in table['rows']
    ]
    assert props[0]['value'] == 23.87115
    assert props[0]['ci_low'] == 22.12165
    assert props[0]['ci_high'] == 25.75957
    assert props[0]['uncertainty'] == "95% interval from NCHS's model"
    assert props[1]['status'] == 'not_in_release' and props[1]['value'] is None
    assert sum(s['n'] for s in legend['statuses']) == mapped['count'] == table['total'] == 2
    assert legend['national_reference'] is None
    assert legend['quantile_breaks'] == [18.0, 24.0, 31.0, 40.0]
    assert legend['quantile_basis'] == 'quintiles_of_published_values_in_release'
    assert legend['limitations'] == CONFIG['limitations']

    spec = next(s for s in lookup.SPECS if s.key == 'nchs_drug_poisoning')
    assert spec.tables == {'county': ('observation_nchs_drug_poisoning', 'geoid', 'geo_level')}
    assert spec.extra == ('source_value', 'ci_low', 'ci_high') and spec.uncertainty == 'ci95'
    assert lookup.MISSING_STATUS['nchs_drug_poisoning']('09110', 'county') == lookup.NOT_IN_RELEASE
    assert not any(k[0] == 'nchs_drug_poisoning' for k in lookup.SOURCE_CREDITS)

    class LookupDB:
        def execute(self, statement, params=None):
            sql = str(statement)
            if 'active_release' in sql:
                return Result([{
                    'dataset_id': CONFIG['dataset_id'], 'id': 'rel-nchs',
                    'source_release_id': CONFIG['source_release_id'], 'published_at': None,
                }])
            if 'observation_nchs_drug_poisoning' in sql:
                return Result([
                    {'geoid': '37063', 'measure_id': 'drug_poisoning_death_rate', 'observation_period': '2021',
                     'population': measure['population'], 'value_type': 'model_based_age_adjusted_rate',
                     'value': Decimal('23.87115'), 'ci_low': Decimal('22.12165'), 'ci_high': Decimal('25.75957'),
                     'status': 'available', 'source_value': '23.87115'},
                ])
            return Result([])

    vals = lookup.area_values(
        LookupDB(), 'county', ['37063', '09110'],
        products=['nchs_drug_poisoning'], measure_ids=['drug_poisoning_death_rate'],
    )['values']
    by_geo = {v['geoid']: v for v in vals}
    assert by_geo['37063']['value'] == 23.87115
    assert by_geo['37063']['uncertainty'] == {
        'kind': 'ci95', 'low': 22.12165, 'high': 25.75957, 'label': "95% interval from NCHS's model",
    }
    assert by_geo['09110']['status'] == lookup.NOT_IN_RELEASE and by_geo['09110']['value'] is None
    assert by_geo['09110']['uncertainty'] == {
        'kind': 'ci95', 'low': None, 'high': None, 'label': "95% interval from NCHS's model",
    }

    nat = [r for r in lookup.national_reference(LookupDB()) if r['product'] == 'nchs_drug_poisoning']
    assert nat == []
