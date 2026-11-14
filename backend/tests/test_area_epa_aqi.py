import io
import zipfile
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot import epa_aqi_api, epa_aqi_cli
from app.area_pilot.epa_aqi import (classify, load_registry, map_counties, observation_values, parse_csv,
                                    parse_file_list, safe_member, select_completed_year, semantic_sha,
                                    validate_row)
from app.area_pilot.source import same_label_revision
from app.demo_access.middleware import _is_public_path

CONFIG = load_registry()
HEADER = CONFIG['expected_header']


def row(state='Alabama', county='Baldwin', year=2025, days=355, good=268, moderate=87, usg=0, unhealthy=0,
        very=0, hazardous=0, high=87, p90=55, median=42, pollutants=(0, 0, 136, 219, 0)):
    values = [state, county, year, days, good, moderate, usg, unhealthy, very, hazardous, high, p90, median, *pollutants]
    return {field: str(value) for field, value in zip(HEADER, values)}


def write_csv(path, rows):
    lines = [','.join(f'"{h}"' for h in HEADER)]
    lines += [','.join(f'"{r[h]}"' if h in ('State', 'County') else r[h] for h in HEADER) for r in rows]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


# ---------------------------------------------------------------- source semantics

def test_registry_measures_are_the_five_published_fields_without_intervals():
    fields = [m['source_field'] for m in CONFIG['measures']]
    assert fields == ['Median AQI', '90th Percentile AQI', 'Max AQI', 'Days with AQI', 'Good Days']
    assert not CONFIG['refresh_policy']['auto_publish']
    p90 = next(m for m in CONFIG['measures'] if m['measure_id'] == 'p90_aqi')
    assert 'not a confidence interval' in p90['statistic_note']
    interval_fields = {'source_ci_field', 'ci_low', 'ci_high', 'moe', 'moe_field'}
    assert all(not interval_fields & set(m) for m in CONFIG['measures'])


def test_parse_valid_row_and_zero_good_days_is_true_zero(tmp_path):
    zero = row(county='Smoky', days=10, good=0, moderate=10, high=90, p90=80, median=60,
               pollutants=(0, 0, 0, 10, 0))
    records = parse_csv(write_csv(tmp_path / 'a.csv', [row(), zero]), CONFIG, 2025)
    assert len(records) == 2
    values = {v['measure']['measure_id']: v for v in observation_values(records[('Alabama', 'Smoky')], CONFIG)}
    assert values['good_days']['value'] == 0 and values['good_days']['status'] == 'true_zero'
    assert values['median_aqi']['status'] == 'available'
    # Reporting days travel with every measure as context.
    assert {v['days_with_aqi'] for v in values.values()} == {10}


def test_beyond_index_maximum_is_kept_and_flagged():
    high = row(days=365, good=200, moderate=150, usg=10, unhealthy=3, very=1, hazardous=1, high=2122,
               p90=123, median=70, pollutants=(0, 0, 200, 72, 93))
    validate_row(high, CONFIG, 2025)
    values = {v['measure']['measure_id']: v for v in observation_values(high, CONFIG)}
    assert values['max_aqi']['value'] == 2122
    assert values['max_aqi']['value_note'] == 'above_500_beyond_aqi_scale'
    assert values['p90_aqi']['value_note'] is None


@pytest.mark.parametrize('changes, message', [
    ({'Year': '2026'}, 'differs from selected year'),
    ({'Days with AQI': '366', 'Good Days': '279'}, 'calendar length'),
    ({'Good Days': '269'}, 'sum to Days'),
    ({'Median AQI': '60'}, 'ordering'),
    ({'Days PM2.5': '300'}, 'Main-pollutant'),
    ({'Max AQI': '120'}, 'category day counts'),
    ({'Median AQI': ''}, 'Undocumented blank'),
    ({'Max AQI': '8.5'}, 'Non-integer'),
])
def test_validation_rejects_inconsistent_rows(changes, message):
    with pytest.raises(ValueError, match=message):
        validate_row(row() | changes, CONFIG, 2025)


def test_leap_year_allows_366_reporting_days_only_in_leap_years():
    leap = row(year=2024, days=366, good=279, moderate=87, pollutants=(0, 0, 147, 219, 0))
    validate_row(leap, CONFIG, 2024)
    with pytest.raises(ValueError, match='calendar length'):
        validate_row(leap | {'Year': '2025'}, CONFIG, 2025)


def test_schema_change_and_duplicate_keys_are_rejected(tmp_path):
    path = write_csv(tmp_path / 'dup.csv', [row(), row()])
    with pytest.raises(ValueError, match='Duplicate'):
        parse_csv(path, CONFIG, 2025)
    renamed = tmp_path / 'renamed.csv'
    renamed.write_text(path.read_text().replace('Median AQI', 'AQI Median'))
    with pytest.raises(ValueError, match='header'):
        parse_csv(renamed, CONFIG, 2025)


# ---------------------------------------------------------------- calendar-year selection

FILE_LIST = '''Filename,Rows,Size,Created
annual_aqi_by_county_2026.zip,827,15,2026-06-25
annual_aqi_by_county_2025.zip,985,20,2026-06-25
annual_aqi_by_county_2024.zip,997,20,2026-06-25
daily_aqi_by_county_2025.zip,323653,1556,2026-06-25
'''


def test_selects_latest_completed_year_not_current_partial_year():
    listing = parse_file_list(FILE_LIST, CONFIG['file_pattern'])
    chosen = select_completed_year(listing, date(2026, 11, 14))
    assert chosen['year'] == 2025
    assert chosen['skipped_current_or_future_years'] == [2026]
    assert chosen['built_after_preliminary_cutoff'] is True
    assert chosen['file']['rows'] == 985


def test_file_built_before_may_cutoff_is_flagged_preliminary():
    listing = parse_file_list(FILE_LIST.replace('2025.zip,985,20,2026-06-25', '2025.zip,985,20,2026-03-01'),
                              CONFIG['file_pattern'])
    assert select_completed_year(listing, date(2026, 11, 14))['built_after_preliminary_cutoff'] is False
    only_current = parse_file_list('Filename,Rows,Size,Created\nannual_aqi_by_county_2026.zip,1,1,2026-06-25\n',
                                   CONFIG['file_pattern'])
    with pytest.raises(ValueError, match='No completed'):
        select_completed_year(only_current, date(2026, 11, 14))


def test_zip_member_must_be_exact_and_safe():
    for names in (['../annual_aqi_by_county_2025.csv'], ['annual_aqi_by_county_2025.csv', 'extra.csv']):
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, 'w') as archive:
            for name in names:
                archive.writestr(name, 'x')
        with zipfile.ZipFile(io.BytesIO(memory.getvalue())) as archive:
            with pytest.raises(ValueError):
                safe_member(archive, 'annual_aqi_by_county_2025.csv')


# ---------------------------------------------------------------- county identifiers

COUNTIES = [
    {'geoid': '24005', 'statefp': '24', 'name': 'Baltimore', 'namelsad': 'Baltimore County', 'lsad': '06'},
    {'geoid': '24510', 'statefp': '24', 'name': 'Baltimore', 'namelsad': 'Baltimore city', 'lsad': '25'},
    {'geoid': '24001', 'statefp': '24', 'name': 'Allegany', 'namelsad': 'Allegany County', 'lsad': '06'},
    {'geoid': '35013', 'statefp': '35', 'name': 'Doña Ana', 'namelsad': 'Doña Ana County', 'lsad': '06'},
    {'geoid': '51036', 'statefp': '51', 'name': 'Charles City', 'namelsad': 'Charles City County', 'lsad': '06'},
    {'geoid': '51520', 'statefp': '51', 'name': 'Bristol', 'namelsad': 'Bristol city', 'lsad': '25'},
    {'geoid': '09110', 'statefp': '09', 'name': 'Capitol', 'namelsad': 'Capitol Planning Region', 'lsad': 'PL'},
]
STATES = {'24': 'Maryland', '35': 'New Mexico', '51': 'Virginia', '09': 'Connecticut'}


def mapped(pairs, codes, config=CONFIG):
    records = {pair: row(*pair) for pair in pairs}
    return map_counties(records, codes, COUNTIES, STATES, config)


def test_epa_codes_are_cross_checked_with_documented_name_rules():
    pairs = {('Maryland', 'Baltimore'): '24005', ('Maryland', 'Baltimore (City)'): '24510',
             ('Maryland', 'Allegany'): '24001', ('New Mexico', 'Dona Ana'): '35013',
             ('Virginia', 'Bristol City'): '51520'}
    result, unused = mapped(list(pairs), {k: {v} for k, v in pairs.items()})
    assert {k: v['geoid'] for k, v in result.items()} == pairs
    assert result[('Maryland', 'Baltimore')]['method'] == 'county_not_city'
    assert result[('Maryland', 'Baltimore (City)')]['method'] == 'namelsad'
    assert result[('New Mexico', 'Dona Ana')]['accent_folded'] is True
    assert result[('Maryland', 'Allegany')]['method'] == 'unique_name'
    # The source-registry variants are not used by this synthetic subset.
    assert ('Virginia', 'Charles') in unused


def test_reviewed_variant_is_accepted_only_for_its_registered_code():
    result, _ = mapped([('Virginia', 'Charles')], {('Virginia', 'Charles'): {'51036'}})
    assert result[('Virginia', 'Charles')]['method'] == 'reviewed_variant'
    wrong, _ = mapped([('Virginia', 'Charles')], {('Virginia', 'Charles'): {'51520'}})
    assert wrong[('Virginia', 'Charles')]['geoid'] is None
    assert wrong[('Virginia', 'Charles')]['method'] == 'name_disagreement'


def test_no_fuzzy_assignment_and_ambiguous_codes_hold():
    near, _ = mapped([('Maryland', 'Alegany')], {('Maryland', 'Alegany'): {'24001'}})
    assert near[('Maryland', 'Alegany')]['geoid'] is None
    two, _ = mapped([('Maryland', 'Allegany')], {('Maryland', 'Allegany'): {'24001', '24005'}})
    assert two[('Maryland', 'Allegany')]['method'] == 'no_unique_epa_code'
    none, _ = mapped([('Maryland', 'Allegany')], {})
    assert none[('Maryland', 'Allegany')]['method'] == 'no_epa_code'


def test_connecticut_legacy_county_is_a_listed_exclusion_not_reassigned():
    pairs = [('Connecticut', 'Fairfield'), ('Maryland', 'Allegany')]
    result, _ = mapped(pairs, {pairs[0]: {'09001'}, pairs[1]: {'24001'}})
    assert result[pairs[0]]['method'] == 'epa_code_not_in_tiger_2024' and result[pairs[0]]['geoid'] is None
    records = {pair: row(*pair) for pair in pairs}
    classified, issues = classify(records, result, {'24001', '09110'}, CONFIG)
    assert classified[pairs[0]]['boundary_status'] == 'source_only'
    assert classified[pairs[0]]['exclusion_reason'] == 'legacy_ct_county_no_compatible_2024_boundary'
    assert classified[pairs[1]]['boundary_status'] == 'matched'
    assert issues['unexplained'] == []
    # Registry exclusions absent from this synthetic file are reported, never silently ignored.
    assert ('Country Of Mexico', 'SONORA') in issues['expected_exclusions_absent']


def test_unlisted_unmatched_row_is_unexplained_and_duplicate_geoids_are_reported():
    pairs = [('Maryland', 'Allegany'), ('Maryland', 'Alegany')]
    mapping = {pairs[0]: {'geoid': '24001', 'method': 'unique_name', 'epa_code': '24001'},
               pairs[1]: {'geoid': None, 'method': 'name_disagreement', 'epa_code': '24001'}}
    classified, issues = classify({p: row(*p) for p in pairs}, mapping, {'24001'}, CONFIG)
    assert issues['unexplained'] == [pairs[1]]
    dup = {p: {'geoid': '24001', 'method': 'unique_name', 'epa_code': '24001'} for p in pairs}
    _, issues = classify({p: row(*p) for p in pairs}, dup, {'24001'}, CONFIG)
    assert issues['duplicate_geoids'] == ['24001']


# ---------------------------------------------------------------- lifecycle

def test_semantic_checksum_is_order_independent_and_content_sensitive():
    a = {('A', 'x'): row('A', 'x'), ('B', 'y'): row('B', 'y')}
    b = dict(reversed(list(a.items())))
    assert semantic_sha(a) == semantic_sha(b)
    changed = {**a, ('A', 'x'): row('A', 'x') | {'Median AQI': '43'}}
    assert semantic_sha(changed) != semantic_sha(a)
    assert same_label_revision({'source_release_id': CONFIG['source_release_id'], 'semantic_sha256': semantic_sha(a)},
                               CONFIG['source_release_id'], semantic_sha(changed))


class Recorder:
    def __init__(self, release_row=None, scalar=0):
        self.statements, self.release_row, self.scalar = [], release_row, scalar

    def execute(self, sql, params=None):
        self.statements.append(str(sql))
        return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: self.release_row,
                                                                one_or_none=lambda: None),
                               scalar_one=lambda: self.scalar, scalar_one_or_none=lambda: None)

    def begin(self):
        conn = self
        class Context:
            def __enter__(self): return conn
            def __exit__(self, *_): return False
        return Context()


def test_failed_retrieval_holds_candidate_and_never_touches_active_pointer(tmp_path, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError('EPA download failed after 3 attempts')
    monkeypatch.setattr(epa_aqi_cli, 'retrieve', broken)
    engine = Recorder()
    _, report = epa_aqi_cli.fetch_stage(engine, CONFIG, directory=tmp_path)
    assert report == {'status': 'held', 'hold_reason': 'EPA download failed after 3 attempts'}
    assert any("'held'" in s for s in engine.statements)
    assert not any('active_release' in s for s in engine.statements)


def test_held_candidate_cannot_publish_and_unexplained_hold_cannot_be_released():
    held = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'held', 'report': {'hold_reason': 'identifier_mismatch'}})
    with pytest.raises(ValueError, match='not ready'):
        epa_aqi_cli.publish(held, CONFIG, 'candidate', 'a', 'b', 'c')
    with pytest.raises(ValueError, match='not an eligible'):
        epa_aqi_cli.release_reviewed_hold(held, CONFIG, 'candidate', 'a', 'b', 'c', 'reviewed')
    assert not any('INSERT INTO area_pilot.active_release' in s or 'SET status' in s for s in held.statements)


def test_ready_candidate_with_wrong_checksums_cannot_publish():
    ready = Recorder({'dataset_id': CONFIG['dataset_id'], 'status': 'ready', 'semantic_sha256': 'x',
                      'schema_sha256': 'y', 'metadata_sha256': 'z'})
    with pytest.raises(ValueError, match='reviewed checksums'):
        epa_aqi_cli.publish(ready, CONFIG, 'candidate', 'x', 'y', 'other')
    assert not any('active_release' in s for s in ready.statements)


def test_rollback_requires_retained_published_release():
    engine = Recorder()
    with pytest.raises(ValueError, match='retained published'):
        epa_aqi_cli.set_pointer(engine, CONFIG, 'rollback', 'not-published')
    assert not any('INSERT INTO area_pilot.active_release' in s for s in engine.statements)


# ---------------------------------------------------------------- read API

def test_selection_rejects_state_tract_and_other_years_and_routes_are_authenticated():
    class DB:
        def execute(self, *_):
            return SimpleNamespace(scalar_one_or_none=lambda: 'published')
    measure = CONFIG['measures'][0]
    assert epa_aqi_api.selection(DB(), CONFIG['dataset_id'], 'r', measure['measure_id'], '2025',
                                 measure['population'], CONFIG['value_type'], 'county')[1] == measure
    for period, geography in (('2025', 'tract'), ('2025', 'state'), ('2026', 'county')):
        with pytest.raises(HTTPException) as error:
            epa_aqi_api.selection(DB(), CONFIG['dataset_id'], 'r', measure['measure_id'], period,
                                  measure['population'], CONFIG['value_type'], geography)
        assert error.value.status_code == 400
    for path in ('/area/catalog', '/area/map', '/area/legend', '/area/table',
                 '/api/area/catalog', '/api/area/map', '/api/area/legend', '/api/area/table'):
        assert not _is_public_path(path)


def test_viewport_cap_returns_413():
    class DB:
        def execute(self, *_):
            return SimpleNamespace(scalar_one=lambda: epa_aqi_api.CAP + 1)
    with pytest.raises(HTTPException) as error:
        epa_aqi_api.ensure_cap(DB(), {})
    assert error.value.status_code == 413


def test_map_legend_table_parity_with_county_without_source_observation():
    class Result:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows
    observed = {'geography_id': '01003', 'name': 'Baldwin', 'value': 0, 'status': 'true_zero',
                'days_with_aqi': 355, 'value_note': None, 'source_state': 'Alabama', 'source_county': 'Baldwin'}
    absent = {'geography_id': '01001', 'name': 'Autauga', 'value': None, 'status': 'no_reported_value',
              'days_with_aqi': None, 'value_note': None, 'source_state': None, 'source_county': None}
    class DB:
        def execute(self, sql, params):
            query = str(sql)
            assert 'LEFT JOIN area_pilot.observation_epa_aqi' in query and 'acs_boundary_2024' in query
            if 'GROUP BY' in query:
                return Result([{'status': 'no_reported_value', 'n': 1, 'low': None, 'high': None,
                                'days_low': None, 'days_high': None},
                               {'status': 'true_zero', 'n': 1, 'low': 0, 'high': 0, 'days_low': 355, 'days_high': 355}])
            rows = [dict(absent), dict(observed)]
            if 'ST_AsGeoJSON' in query:
                for item in rows:
                    item['geometry'] = {'type': 'Polygon', 'coordinates': []}
            return Result(rows)
    measure = next(m for m in CONFIG['measures'] if m['measure_id'] == 'good_days')
    base = epa_aqi_api.metadata(CONFIG, measure, 'release', '-88,30,-87,32')
    mapped = epa_aqi_api.map_data(DB(), {}, 2, base, 0.04)
    table = epa_aqi_api.table(DB(), {}, base, 2, 100, 0)
    legend = epa_aqi_api.legend(DB(), {}, base)
    props = [f['properties'] for f in mapped['features']]
    assert [(p['value'], p['status'], p['days_with_aqi']) for p in props] == \
           [(r['value'], r['status'], r['days_with_aqi']) for r in table['rows']]
    assert props[0]['status'] == 'no_reported_value' and props[0]['value'] is None
    assert props[1]['value'] == 0 and props[1]['status'] == 'true_zero' and props[1]['days_with_aqi'] == 355
    assert props[1]['source_name'] == 'Baldwin, Alabama'
    assert sum(item['n'] for item in legend['statuses']) == mapped['count'] == table['total'] == 2
    assert base['uncertainty'] == 'not published' and 'ci_low' not in props[1]
    assert any('not that the air was clean' in text for text in legend['limitations'])
