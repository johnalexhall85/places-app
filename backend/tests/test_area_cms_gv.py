import copy
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot import cms_gv_api, cms_gv_cli
from app.area_pilot.cms_gv import (boundary_without_source, catalog_entry, check_catalog, classify, load_registry,
                                   observation_values, parse_csv, parse_value, range_problems, scale_evidence,
                                   semantic_sha, verify_phrases)
from app.area_pilot.source import same_label_revision
from app.demo_access.middleware import _is_public_path

CONFIG = load_registry()
FIELDS = [m['source_field'] for m in CONFIG['measures']]
HEADER = CONFIG['source_dimensions'] + FIELDS + ['BENE_FEML_PCT']
TEST = copy.deepcopy(CONFIG) | {'expected_column_count': len(HEADER), 'expected_header_sha256': ''}


def line(year='2024', level='County', desc='AL-Autauga', code='01001', age='All',
         values=('4000', '12527.77', '230.5', '600.25', '0.2069'), female='0.546'):
    return [year, level, desc, code, age, *values, female]


def write(path, rows, header=HEADER):
    path.write_text('\n'.join(','.join(r) for r in [header, *rows]) + '\n', encoding='utf-8')
    return path


def record(level='County', desc='AL-Autauga', code='01001', values=('4000', '12527.77', '230.5', '600.25', '0.2069'),
           female='0.546'):
    return dict(zip(HEADER, line(level=level, desc=desc, code=code, values=values, female=female)))


# ---------------------------------------------------------------- registry and documentation

def test_registry_is_five_published_fields_without_uncertainty_or_auto_publish():
    assert FIELDS == ['BENES_OM_CNT', 'TOT_MDCR_STDZD_PYMT_PC', 'IP_CVRD_STAYS_PER_1000_BENES',
                      'ER_VISITS_PER_1000_BENES', 'ACUTE_HOSP_READMSN_PCT']
    assert CONFIG['age_level'] == 'All' and CONFIG['age_level_label'] == 'All Beneficiaries'
    assert not CONFIG['refresh_policy']['auto_publish'] and CONFIG['aggregation_method'] == 'none'
    readmission = CONFIG['measures'][-1]
    assert readmission['storage_scale'] == 'proportion_0_1' and 'not beneficiaries' in readmission['denominator']
    payment = CONFIG['measures'][1]
    assert 'not adjusted for inflation' in payment['interpretation']
    assert 'risk-adjusted' in payment['interpretation'] and 'does not adjust' in payment['interpretation']
    assert all('Original Medicare' in m['population'] for m in CONFIG['measures'])


def test_phrase_check_ignores_pdf_whitespace_but_detects_changed_definitions():
    text = 'Number of Hospital Inpatient covered\nstays per 1,000 OM benefici aries.'
    assert verify_phrases(text, ['Number of Hospital Inpatient covered stays per 1,000 OM beneficiaries.'], 'x') == 1
    with pytest.raises(ValueError, match='definitions changed'):
        verify_phrases(text, ['per 1,000 Medicare enrollees'], 'dictionary')


def catalog(end='2024-12-31', csv=None, dictionary=None):
    spec = CONFIG['catalog']
    return {'dataset': [{'title': spec['title_prefix'] + '2024-01-01', 'modified': '2026-05-15',
                         'inSeries': [{'@id': spec['series_identifier']}], 'accessLevel': 'public',
                         'temporal': [{'startDate': '2024-01-01', 'endDate': end}],
                         'describedBy': {'downloadURL': dictionary or spec['dictionary_url']},
                         'references': [spec['methods_url']],
                         'distribution': [{'mediaType': 'text/csv', 'downloadURL': csv or spec['csv_url']}]},
                        {'title': 'Medicare Advantage Geographic Variation', 'inSeries': []}]}


def test_catalog_new_year_or_changed_distribution_holds_for_registry_review():
    check_catalog(catalog_entry(catalog(), CONFIG), CONFIG)
    with pytest.raises(ValueError, match='now ends in 2025'):
        check_catalog(catalog_entry(catalog(end='2025-12-31'), CONFIG), CONFIG)
    with pytest.raises(ValueError, match='CSV distribution URL changed'):
        check_catalog(catalog_entry(catalog(csv='https://example.invalid/new.csv'), CONFIG), CONFIG)
    with pytest.raises(ValueError, match='dictionary or methods'):
        check_catalog(catalog_entry(catalog(dictionary='https://example.invalid/d.pdf'), CONFIG), CONFIG)


# ---------------------------------------------------------------- parsing, year and age selection

def test_latest_year_all_ages_only_and_age_strata_are_counted_not_combined(tmp_path):
    rows = [line(year='2023'), line(), line(age='<65', values=('500', '1', '1', '1', '0.1')),
            line(age='>=65', values=('3500', '1', '1', '1', '0.1')),
            line(level='National', desc='National', code='', values=('27732177', '12553.26', '224.8391',
                                                                         '590.5484', '0.1807'))]
    records, stats = parse_csv(write(tmp_path / 'gv.csv', rows), TEST)
    assert stats['latest_year'] == '2024' and stats['year_counts'] == {'2023': 1, '2024': 4}
    assert set(records) == {('County', '01001', 'AL-Autauga'), ('National', '', 'National')}
    assert records[('County', '01001', 'AL-Autauga')]['BENES_OM_CNT'] == '4000'  # not 4000+500+3500
    assert stats['selected_year_age_counts'] == {'County|<65': 1, 'County|>=65': 1, 'County|All': 1, 'National|All': 1}


def test_leading_zeros_duplicate_keys_and_schema_changes(tmp_path):
    records, _ = parse_csv(write(tmp_path / 'a.csv', [line(code='01001')]), TEST)
    assert ('County', '01001', 'AL-Autauga') in records
    with pytest.raises(ValueError, match='Duplicate'):
        parse_csv(write(tmp_path / 'b.csv', [line(), line()]), TEST)
    with pytest.raises(ValueError, match='column count'):
        parse_csv(write(tmp_path / 'c.csv', [line()], HEADER + ['EXTRA']), TEST)
    renamed = [h.replace('BENE_AGE_LVL', 'AGE') for h in HEADER]
    with pytest.raises(ValueError, match='dimension columns'):
        parse_csv(write(tmp_path / 'd.csv', [line()], renamed), TEST)
    with pytest.raises(ValueError, match='header differs'):
        parse_csv(write(tmp_path / 'e.csv', [line()]), TEST | {'expected_header_sha256': 'f' * 64})


def test_suppressed_missing_true_zero_and_undocumented_tokens_stay_distinct():
    measure = CONFIG['measures'][-1]
    assert parse_value('*', measure) == (None, 'suppressed')
    assert parse_value('', measure) == (None, 'missing')
    assert parse_value('0', measure) == (Decimal(0), 'true_zero')
    assert parse_value('0.1807', measure) == (Decimal('0.1807'), 'available')
    for token in ('NA', '<11', '1e3', '.'):
        with pytest.raises(ValueError, match='Undocumented'):
            parse_value(token, measure)
    values = {v['measure']['measure_id']: v for v in observation_values(
        record(values=('*', '*', '*', '*', '*')), CONFIG)}
    assert {v['status'] for v in values.values()} == {'suppressed'}
    assert all(v['value'] is None and v['source_value'] == '*' for v in values.values())


def test_scales_are_checked_not_rescaled():
    proportion, count = CONFIG['measures'][-1], CONFIG['measures'][0]
    assert range_problems(Decimal('0.18'), proportion) == []
    assert range_problems(Decimal('18.07'), proportion) == ['outside_documented_scale']
    assert range_problems(Decimal('7'), count) == ['below_suppression_threshold']
    assert range_problems(Decimal('11.5'), count) == ['non_integer_count']
    values = {v['measure']['measure_id']: v for v in observation_values(record(), CONFIG)}
    assert values['readmission_rate']['value'] == Decimal('0.2069')  # stored as published, 0-1


def test_percentage_scale_evidence_requires_documented_national_values():
    national = record('National', 'National', '', ('27732177', '12553.26', '224.8391', '590.5484', '0.1807'))
    assert scale_evidence({('National', '', 'National'): national}, CONFIG)['passed'] is True
    rescaled = national | {'BENE_FEML_PCT': '54.6'}
    assert scale_evidence({('National', '', 'National'): rescaled}, CONFIG)['passed'] is False
    percent_readmission = national | {'ACUTE_HOSP_READMSN_PCT': '18.07'}
    assert scale_evidence({('National', '', 'National'): percent_readmission}, CONFIG)['passed'] is False


# ---------------------------------------------------------------- geography

def geography_records():
    keys = [('National', '', 'National'), ('State', '01', 'AL'), ('State', '09', 'CT'), ('State', '72', 'PR'),
            ('State', '78', 'VI'), ('State', '', 'Territory'), ('State', '', 'ZZ'),
            ('County', '01001', 'AL-Autauga'), ('County', '09110', 'CT-Capitol'),
            ('County', '01000', 'AL-UNKNOWN'), ('County', '78010', 'VI-St. Croix')]
    return {key: record(*key) for key in keys}


SMALL = copy.deepcopy(CONFIG)
for rule in SMALL['expected_source_exclusions']:
    if 'expected_count' in rule:
        rule['expected_count'] = 1
SMALL['expected_boundary_without_source'] = [
    {'level': 'county', 'code_pattern': '^11001$', 'reason': 'cms_publishes_dc_at_state_level_only', 'expected_count': 1},
    {'level': 'county', 'code_pattern': '^72[0-9]{3}$', 'reason': 'cms_publishes_puerto_rico_at_state_level_only',
     'expected_count': 1}]
STATES, COUNTIES = {'01', '09', '11', '72'}, {'01001', '09110', '11001', '72001'}


def test_exact_joins_national_reference_and_documented_exclusions():
    classified, issues = classify(geography_records(), STATES, COUNTIES, SMALL)
    assert issues == {'unexplained': [], 'exclusion_count_mismatch': [], 'duplicate_geoids': []}
    status = {k: (v['boundary_status'], v['geoid'], v['exclusion_reason']) for k, v in classified.items()}
    assert status[('National', '', 'National')] == ('national_reference', 'US', None)
    assert status[('State', '72', 'PR')] == ('matched', '72', None)
    assert status[('County', '09110', 'CT-Capitol')] == ('matched', '09110', None)
    assert status[('State', '78', 'VI')][2] == 'territory_outside_chip_2024_boundary_layer'
    assert status[('State', '', 'ZZ')][2] == 'non_fips_state_aggregate'
    assert status[('County', '01000', 'AL-UNKNOWN')][2] == 'unknown_county_of_residence'
    uncovered, coverage = boundary_without_source(classified, STATES, COUNTIES, SMALL)
    assert uncovered == {'state:11': 'unexplained', 'county:11001': 'cms_publishes_dc_at_state_level_only',
                         'county:72001': 'cms_publishes_puerto_rico_at_state_level_only'}
    assert coverage['unexplained'] == ['state:11']


def test_unlisted_codes_and_legacy_connecticut_counties_are_unexplained_holds():
    records = geography_records() | {('County', '09001', 'CT-Fairfield'): record('County', 'CT-Fairfield', '09001'),
                                     ('County', '01003', 'AL-Baldwin'): record('County', 'AL-Baldwin', '01003')}
    _, issues = classify(records, STATES, COUNTIES, SMALL)
    assert issues['unexplained'] == [('County', '01003', 'AL-Baldwin'), ('County', '09001', 'CT-Fairfield')]
    missing = {k: v for k, v in geography_records().items() if k != ('County', '01000', 'AL-UNKNOWN')}
    _, issues = classify(missing, STATES, COUNTIES, SMALL)
    assert issues['exclusion_count_mismatch'] == ['County|unknown_county_of_residence fewer than 1']


# ---------------------------------------------------------------- lifecycle

def test_semantic_checksum_is_order_independent_and_detects_revisions():
    a = geography_records()
    b = dict(reversed(list(a.items())))
    assert semantic_sha(a) == semantic_sha(b)
    revised = dict(a) | {('State', '01', 'AL'): record('State', 'AL', '01') | {'BENES_OM_CNT': '4001'}}
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


def test_failed_retrieval_holds_candidate_and_never_touches_active_pointer(tmp_path):
    def broken(_directory):
        raise RuntimeError('CMS download failed after 3 attempts')
    engine = Recorder()
    _, report = cms_gv_cli.fetch_stage(engine, CONFIG, directory=tmp_path, retrieved=broken)
    assert report == {'status': 'held', 'hold_reason': 'CMS download failed after 3 attempts'}
    assert not any('active_release' in s for s in engine.statements)


def test_held_or_mismatched_candidates_cannot_publish():
    held = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'held', 'report': {'hold_reason': 'geography_mismatch'}})
    with pytest.raises(ValueError, match='not ready'):
        cms_gv_cli.publish(held, CONFIG, 'c', 'a', 'b', 'c')
    with pytest.raises(ValueError, match='not an eligible'):
        cms_gv_cli.release_reviewed_hold(held, CONFIG, 'c', 'a', 'b', 'c', 'reviewed')
    ready = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'ready', 'semantic_sha256': 'x',
                      'schema_sha256': 'y', 'metadata_sha256': 'z'})
    with pytest.raises(ValueError, match='reviewed checksums'):
        cms_gv_cli.publish(ready, CONFIG, 'c', 'x', 'y', 'other')
    other = Recorder({'dataset_id': 'epa_airdata_aqi_county_2025', 'status': 'ready'})
    with pytest.raises(ValueError, match='not ready'):
        cms_gv_cli.publish(other, CONFIG, 'c', 'x', 'y', 'z')
    for engine in (held, ready, other):
        assert not any('INSERT INTO area_pilot.active_release' in s for s in engine.statements)
    with pytest.raises(ValueError, match='retained published'):
        cms_gv_cli.set_pointer(Recorder(), CONFIG, 'rollback', 'not-published')


# ---------------------------------------------------------------- read API

class PublishedDB:
    def execute(self, *_):
        return SimpleNamespace(scalar_one_or_none=lambda: 'published')


def test_selection_supports_state_and_county_and_explains_missing_tracts():
    measure = CONFIG['measures'][0]
    for geography in ('state', 'county'):
        assert cms_gv_api.selection(PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'], '2024',
                                    measure['population'], CONFIG['value_type'], geography)[1] == measure
    with pytest.raises(HTTPException) as error:
        cms_gv_api.selection(PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'], '2024',
                             measure['population'], CONFIG['value_type'], 'tract')
    assert error.value.status_code == 400 and 'no tract' in error.value.detail
    for period, population in (('2023', measure['population']), ('2024', 'Beneficiaries 65 or older')):
        with pytest.raises(HTTPException) as error:
            cms_gv_api.selection(PublishedDB(), CONFIG['dataset_id'], 'r', measure['measure_id'], period,
                                 population, CONFIG['value_type'], 'county')
        assert error.value.status_code == 400
    for path in ('/area/catalog', '/area/map', '/area/legend', '/area/table',
                 '/api/area/catalog', '/api/area/map', '/api/area/legend', '/api/area/table'):
        assert not _is_public_path(path)


def test_viewport_cap_returns_413():
    class DB:
        def execute(self, *_):
            return SimpleNamespace(scalar_one=lambda: cms_gv_api.CAP + 1)
    with pytest.raises(HTTPException) as error:
        cms_gv_api.ensure_cap(DB(), {})
    assert error.value.status_code == 413


def test_map_legend_table_parity_with_suppressed_not_published_and_national_reference():
    class Result:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows
        def one_or_none(self): return self.rows[0] if self.rows else None
    rows = [{'geography_id': '01001', 'name': 'Autauga', 'value': Decimal('0.2069'), 'source_value': '0.2069',
             'status': 'available', 'source_desc': 'AL-Autauga'},
            {'geography_id': '02013', 'name': 'Aleutians East', 'value': None, 'source_value': '*',
             'status': 'suppressed', 'source_desc': 'AK-Aleutians East'},
            {'geography_id': '11001', 'name': 'District of Columbia', 'value': None, 'source_value': None,
             'status': 'not_published', 'source_desc': None}]
    class DB:
        def execute(self, sql, params):
            query = str(sql)
            if "geo_level='national'" in query:
                return Result([{'value': Decimal('0.1807'), 'source_value': '0.1807', 'status': 'available'}])
            assert 'LEFT JOIN area_pilot.observation_cms_gv' in query and 'b.level=:level' in query
            if 'GROUP BY' in query:
                return Result([{'status': 'available', 'n': 1, 'low': Decimal('0.2069'), 'high': Decimal('0.2069')},
                               {'status': 'not_published', 'n': 1, 'low': None, 'high': None},
                               {'status': 'suppressed', 'n': 1, 'low': None, 'high': None}])
            out = [dict(r) for r in rows]
            if 'ST_AsGeoJSON' in query:
                for item in out:
                    item['geometry'] = {'type': 'Polygon', 'coordinates': []}
            return Result(out)
    measure = CONFIG['measures'][-1]
    base = cms_gv_api.metadata(CONFIG, measure, 'release', 'county', '-180,-90,180,90')
    mapped = cms_gv_api.map_data(DB(), {}, 3, base, 0.04)
    table = cms_gv_api.table(DB(), {}, base, 3, 100, 0)
    legend = cms_gv_api.legend(DB(), {}, base)
    props = [f['properties'] for f in mapped['features']]
    assert [(p['value'], p['status']) for p in props] == [(r['value'], r['status']) for r in table['rows']]
    assert props[0]['value'] == 0.2069 and props[1]['source_value'] == '*' and props[2]['status'] == 'not_published'
    assert sum(s['n'] for s in legend['statuses']) == mapped['count'] == table['total'] == 3
    assert legend['national_reference']['value'] == 0.1807
    assert 'US' not in [p['geography_id'] for p in props]
    assert base['legend_breaks'] == measure['legend_breaks']['county'] and base['storage_scale'] == 'proportion_0_1'
    state = cms_gv_api.metadata(CONFIG, CONFIG['measures'][0], 'release', 'state', '-180,-90,180,90')
    assert state['legend_breaks'] == [100000, 250000, 500000, 1000000]
    assert any('Medicare Advantage' in item for item in legend['limitations'])
