"""Unit tests for the USDA Food Environment Atlas shared-pipeline product (no network, no database)."""
import copy
import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.area_pilot import usda_fea as u
from app.area_pilot import usda_fea_api as api
from app.area_pilot import usda_fea_cli as cli

CONFIG = u.load_registry()
BY_ID = {m['measure_id']: m for m in CONFIG['measures']}


def test_registry_contract_and_periods():
    assert [m['variable_code'] for m in CONFIG['measures']] == [
        'PCT_LACCESS_LOWI19', 'SNAPSPTH23', 'WICSPTH22', 'FMRKTPTH18', 'PCT_LACCESS_HHNV19']
    assert {m['measure_id']: m['observation_period'] for m in CONFIG['measures']} == {
        'low_income_low_access_pct': '2019', 'snap_stores_per_1000': '2023', 'wic_stores_per_1000': '2022',
        'farmers_markets_per_1000': '2018', 'no_car_low_access_households_pct': '2019'}
    # Observation periods differ from the release label and from each other; nothing is labelled 2025.
    assert all('2025' not in m['observation_period'] for m in CONFIG['measures'])
    assert CONFIG['geographies'] == ['county'] and CONFIG['refresh_policy']['auto_publish'] is False
    assert 'GROCPTH20' in CONFIG['excluded_targets']
    # The low-income measure is labelled with its true denominator: all residents, not low-income residents.
    assert BY_ID['low_income_low_access_pct']['population'] == 'total county population'
    assert 'food desert' not in BY_ID['low_income_low_access_pct']['label'].lower()


def test_registry_rejects_auto_publish(tmp_path, monkeypatch):
    bad = copy.deepcopy(CONFIG)
    bad['refresh_policy']['auto_publish'] = True
    (tmp_path / 'registry').mkdir()
    (tmp_path / 'registry' / 'usda_fea_2025.json').write_text(json.dumps(bad))
    monkeypatch.setattr(u, '__file__', str(tmp_path / 'usda_fea.py'))
    with pytest.raises(ValueError, match='contract changed'):
        u.load_registry()


@pytest.mark.parametrize('raw,status,value', [
    ('-9999', 'not_available', None), ('N/A', 'not_available', None), ('', 'not_available', None),
    ('-8888', 'did_not_exist', None), ('0', 'true_zero', Decimal('0')), ('0.000', 'true_zero', Decimal('0')),
    ('3.018337965', 'available', Decimal('3.018337965'))])
def test_sentinels_distinct_from_zero(raw, status, value):
    got_value, got_status = u.classify_value(raw, BY_ID['low_income_low_access_pct'], CONFIG)
    assert got_status == status and got_value == value


@pytest.mark.parametrize('raw', ['-1', '101', 'abc', '1,000', '-9998'])
def test_undocumented_or_out_of_range_values_fail(raw):
    with pytest.raises(ValueError):
        u.classify_value(raw, BY_ID['low_income_low_access_pct'], CONFIG)


def lookup_rows(**changes):
    rows = {}
    for m in CONFIG['measures']:
        rows[m['variable_code']] = {'Variable_Name': m['variable_name'], 'Category_Name': m['category'],
                                    'Category_Code': 'X', 'Subcategory_Name': m['subcategory'],
                                    'Variable_Code': m['variable_code'], 'Units': m['source_units']}
    for code, row in changes.items():
        rows[code].update(row)
    return rows


def test_variable_lookup_must_match_registry():
    assert len(u.verify_variables(lookup_rows(), CONFIG)) == 5
    with pytest.raises(ValueError, match='changed for SNAPSPTH23'):
        u.verify_variables(lookup_rows(SNAPSPTH23={'Variable_Name': 'SNAP-authorized stores/1,000 pop, 2024'}), CONFIG)
    with pytest.raises(ValueError, match='changed for WICSPTH22'):
        u.verify_variables(lookup_rows(WICSPTH22={'Units': 'Count'}), CONFIG)
    starred = lookup_rows()
    starred['FMRKTPTH18']['Variable_Name'] += '*'
    with pytest.raises(ValueError):
        u.verify_variables(starred, CONFIG)
    missing = lookup_rows(); missing.pop('PCT_LACCESS_HHNV19')
    with pytest.raises(ValueError, match='lacks PCT_LACCESS_HHNV19'):
        u.verify_variables(missing, CONFIG)


DOWNLOADS = '''<h2>Current Version</h2><p>Food Environment Atlas .csv Files
<a href="/media/5570/food-environment-atlas-csv-files.zip?v=40916">Download</a> (ZIP) Last Updated 7/30/2025</p>
<h2>Archived Versions|August 2020</h2><a href="/media/5559/2020-food-environment-atlas-csv-files.zip?v=1">x</a>'''


def test_current_csv_link_and_release_change():
    assert u.current_csv_link(DOWNLOADS) == ('/media/5570/food-environment-atlas-csv-files.zip?v=40916', '7/30/2025')
    newer = DOWNLOADS.replace('v=40916', 'v=50000').replace('7/30/2025', '6/1/2027')
    assert u.current_csv_link(newer) != (CONFIG['release_markers']['csv_zip_href'],
                                         CONFIG['release_markers']['csv_last_updated'])
    with pytest.raises(ValueError, match='not unique'):
        u.current_csv_link(DOWNLOADS.replace('</p>', '<a href="/media/1/other-csv-files.zip">y</a></p>', 1))


def test_documentation_phrases_tolerate_quote_style_only():
    phrase = CONFIG['documentation_phrases']['downloads_page']
    assert u.verify_phrases('x “No data” fields are referenced with N/A or with -9999. Counties that didn’t '
                            'exist in a particular year are referenced with -8888. y', phrase, 'p') == 1
    with pytest.raises(ValueError, match='wording changed'):
        u.verify_phrases('Missing values are blank.', phrase, 'p')


def make_zip(path, members, symlink=None):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)
            archive.writestr(info, 'target')


def test_safe_zip_extraction(tmp_path):
    good = {n: 'x' for n in CONFIG['expected_members']}
    make_zip(tmp_path / 'ok.zip', good)
    out = tmp_path / 'out'; out.mkdir()
    assert set(u.extract_members(tmp_path / 'ok.zip', CONFIG['expected_members'], out)) == set(good)
    for bad, kwargs in ((dict(good, **{'../evil.csv': 'x'}), {}), (dict(good, **{'sub/a.csv': 'x'}), {}),
                        (dict(good, extra='x'), {}), (good, {'symlink': 'link'})):
        make_zip(tmp_path / 'bad.zip', bad, **kwargs)
        with pytest.raises(ValueError):
            u.extract_members(tmp_path / 'bad.zip', CONFIG['expected_members'], out)
    make_zip(tmp_path / 'bomb.zip', dict(good, **{'StateAndCountyData.csv': '0' * 5_000_000}))
    with pytest.raises(ValueError, match='compression ratio'):
        u.extract_members(tmp_path / 'bomb.zip', CONFIG['expected_members'], out)


def values_file(tmp_path, rows, header='FIPS,State,County,Variable_Code,Value'):
    path = tmp_path / 'values.csv'
    path.write_text('﻿' + header + '\n' + '\n'.join(rows) + '\n', encoding='utf-8')
    return path


def test_parse_values_keeps_fips_text_and_selected_variables(tmp_path):
    path = values_file(tmp_path, ['01001,AL,Autauga,PCT_LACCESS_LOWI19,13.02099800',
                                  '01001,AL,Autauga,GROC20,4',
                                  'N/A,AK,Kenai Peninsula Area,FMRKTPTH18,-8888',
                                  'N/A,AK,Juneau Area,FMRKTPTH18,-8888'])
    selected, stats = u.parse_values(path, CONFIG)
    assert stats == {'rows': 4, 'variables': 3, 'non_fips_rows': 2, 'duplicate_keys_all_variables': 0}
    assert selected[('01001', 'PCT_LACCESS_LOWI19')]['value'] == '13.02099800'
    assert ('N/A|AK|Juneau Area', 'FMRKTPTH18') in selected
    with pytest.raises(ValueError, match='Duplicate'):
        u.parse_values(values_file(tmp_path, ['01001,AL,A,SNAPSPTH23,1', '01001,AL,A,SNAPSPTH23,2']), CONFIG)
    with pytest.raises(ValueError, match='header changed'):
        u.parse_values(values_file(tmp_path, ['x'], header='FIPS,State,Variable_Code,Value'), CONFIG)
    with pytest.raises(ValueError, match='columns'):
        u.parse_values(values_file(tmp_path, ['01001,AL,A,SNAPSPTH23,1,extra']), CONFIG)


def small_config():
    config = copy.deepcopy(CONFIG)
    config['expected_source_only'] = [
        {'fips': ['09001'], 'measures': u.MEASURE_IDS, 'reason': 'legacy_ct_county_no_compatible_2024_boundary'},
        {'no_fips_state': 'AK', 'counties': ['Kenai Peninsula Area'], 'measures': ['farmers_markets_per_1000'],
         'reason': 'no_fips_alaska_agricultural_area', 'expected_value': '-8888'}]
    for rule in config['expected_boundary_only']:
        rule['expected_count'] = 1
    return config


def selected_rows(extra=()):
    rows = {}
    for m in CONFIG['measures']:
        code = m['variable_code']
        for fips, county, value in (('01001', 'Autauga', '0'), ('01003', 'Baldwin', '-9999'),
                                    ('09001', 'Fairfield', '3.0')):
            rows[(fips, code)] = {'fips': fips, 'state': 'AL' if fips < '02' else 'CT', 'county': county,
                                  'variable_code': code, 'value': value}
    rows[('09110', 'FMRKTPTH18')] = {'fips': '09110', 'state': 'CT', 'county': 'Capitol',
                                     'variable_code': 'FMRKTPTH18', 'value': '-8888'}
    rows[('N/A|AK|Kenai Peninsula Area', 'FMRKTPTH18')] = {'fips': 'N/A', 'state': 'AK',
                                                           'county': 'Kenai Peninsula Area',
                                                           'variable_code': 'FMRKTPTH18', 'value': '-8888'}
    for key, row in extra:
        rows[key] = row
    return rows


BOUNDARY = {'01001', '01003', '09110', '72001'}


def test_classify_documented_boundary_exceptions():
    config = small_config()
    classified, issues = u.classify(selected_rows(), BOUNDARY, config)
    assert not any(issues[k] for k in ('unexplained', 'expected_absent', 'value_mismatch', 'unexplained_boundary',
                                       'boundary_rule_count_mismatch'))
    assert classified[('09001', 'SNAPSPTH23')]['exclusion_reason'] == 'legacy_ct_county_no_compatible_2024_boundary'
    assert classified[('09110', 'FMRKTPTH18')]['boundary_status'] == 'matched'
    assert issues['boundary_only']['snap_stores_per_1000'] == {
        'ct_planning_region_not_published_for_period': 1, 'puerto_rico_outside_atlas_coverage': 1}
    assert issues['boundary_only']['farmers_markets_per_1000'] == {'puerto_rico_outside_atlas_coverage': 1}
    rows = cli.observations_for(config, classified)
    fm = {r['geoid']: r for r in rows if r['measure'] == 'farmers_markets_per_1000'}
    assert fm['09110']['status'] == 'did_not_exist'
    assert fm['09110']['note'] == 'ct_planning_region_created_2022_after_period'
    assert fm['01001']['status'] == 'true_zero' and fm['01003']['status'] == 'not_available'
    assert all(len(r['geoid']) == 5 and isinstance(r['geoid'], str) for r in rows)


def test_classify_holds_unexplained_rows_and_boundaries():
    config = small_config()
    stray = (('01005', 'SNAPSPTH23'), {'fips': '01005', 'state': 'AL', 'county': 'Barbour',
                                       'variable_code': 'SNAPSPTH23', 'value': '1'})
    _, issues = u.classify(selected_rows([stray]), BOUNDARY, config)
    assert issues['unexplained'] == [['snap_stores_per_1000', '01005']]
    _, issues = u.classify(selected_rows(), BOUNDARY | {'01007'}, config)
    assert ['snap_stores_per_1000', '01007'] in issues['unexplained_boundary']
    rows = selected_rows(); rows.pop(('09001', 'WICSPTH22'))
    _, issues = u.classify(rows, BOUNDARY, config)
    assert ['wic_stores_per_1000', '09001'] in issues['expected_absent']
    rows = selected_rows(); rows[('N/A|AK|Kenai Peninsula Area', 'FMRKTPTH18')]['value'] = '0.5'
    _, issues = u.classify(rows, BOUNDARY, config)
    assert issues['value_mismatch']


def test_semantic_checksum_tracks_values_and_lookup():
    rows, lookup = selected_rows(), lookup_rows()
    base = u.semantic_sha(rows, lookup)
    assert base == u.semantic_sha(copy.deepcopy(rows), copy.deepcopy(lookup))
    changed = copy.deepcopy(rows); changed[('01001', 'SNAPSPTH23')]['value'] = '0.1'
    assert u.semantic_sha(changed, lookup) != base
    assert u.semantic_sha(rows, lookup_rows(SNAPSPTH23={'Units': 'Count'})) != base


class FakeDB:
    def __init__(self, status):
        self.status = status

    def execute(self, *_args, **_kwargs):
        return self

    def scalar_one_or_none(self):
        return self.status


def test_api_selection_rejects_state_and_mismatched_period():
    m = BY_ID['wic_stores_per_1000']
    args = (CONFIG['dataset_id'], 'r', m['measure_id'], m['observation_period'], m['population'], CONFIG['value_type'])
    assert api.selection(FakeDB('published'), *args, 'county')[1] == m
    for geography in ('state', 'tract'):
        with pytest.raises(HTTPException) as error:
            api.selection(FakeDB('published'), *args, geography)
        assert error.value.status_code == 400 and 'counties only' in error.value.detail
    with pytest.raises(HTTPException) as error:
        api.selection(FakeDB('published'), *args[:3], '2025', *args[4:], 'county')
    assert error.value.status_code == 400
    with pytest.raises(HTTPException) as error:
        api.selection(FakeDB('held'), *args, 'county')
    assert error.value.status_code == 404


def test_catalog_metadata_exposes_periods_definitions_and_units():
    class CatalogDB:
        def execute(self, statement, params):
            return self
        def scalar_one_or_none(self):
            return 'rid'
        def mappings(self):
            return self
        def all(self):
            return []
    data = api.catalog(CatalogDB())
    assert data['geographies'] == ['county'] and data['active_release_id'] == 'rid'
    assert all(m['observation_period'] and m['unit'] and m['official_definition'] and m['denominator']
               for m in data['measures'])
    assert 'did_not_exist' in data['missing_semantics'] and 'not_available' in data['missing_semantics']
