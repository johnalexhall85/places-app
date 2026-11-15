"""Unit tests for the single-place read module. Database rows are stubbed; SQL is exercised on staging."""
from decimal import Decimal

import pytest

from app.area_pilot import lookup


class Result:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return self
    def all(self): return self.rows
    def __iter__(self): return iter(self.rows)
    def scalar_one(self): return self.rows


class FakeDb:
    """Answers by the table named in the SQL."""
    def __init__(self, tables, releases=None):
        self.tables, self.calls = tables, []
        self.releases = releases
    def execute(self, statement, params=None):
        sql = str(statement); self.calls.append((sql, params))
        if 'active_release' in sql:
            return Result(self.releases if self.releases is not None else [
                {'dataset_id': spec.load()['dataset_id'], 'id': f'rel-{spec.key}',
                 'source_release_id': f'label-{spec.key}', 'published_at': None} for spec in lookup.SPECS])
        for name, rows in self.tables.items():
            if f'area_pilot.{name} ' in sql:
                return Result(rows)
        return Result([])


def measure(spec_key, index=0):
    spec = next(s for s in lookup.SPECS if s.key == spec_key)
    config = spec.load()
    return lookup._measure_meta(spec, config, config['measures'][index])


def stored(meta, geoid, **extra):
    return {'geoid': geoid, 'measure_id': meta['measure_id'], 'observation_period': meta['period'],
            'population': meta['population'], 'value_type': meta['value_type'], 'value': Decimal('1'),
            'status': 'available'} | extra


def test_geoid_validation():
    with pytest.raises(lookup.LookupError_): lookup._check('place', ['01055'])
    with pytest.raises(lookup.LookupError_): lookup._check('county', ['1055'])
    with pytest.raises(lookup.LookupError_): lookup._check('county', [])
    with pytest.raises(lookup.LookupError_): lookup._check('county', [f'{i:05d}' for i in range(lookup.MAX_GEOIDS + 1)])
    assert lookup._check('county', ['01055', ' 01055', '01073']) == ['01055', '01073']


def test_numbers_keep_stored_precision():
    assert lookup._num(Decimal('54563')) == 54563 and isinstance(lookup._num(Decimal('54563')), int)
    assert lookup._num(Decimal('0.1863')) == 0.1863
    assert lookup._num(None) is None


def test_catalog_lists_every_registry_measure_and_levels():
    catalog = lookup.catalog(FakeDb({}))
    expected = sum(len(spec.load()['measures']) for spec in lookup.SPECS)
    assert len(catalog['measures']) == expected
    by_id = {(m['product'], m['measure_id']): m for m in catalog['measures']}
    assert by_id[('clh', 'CCBP_SOGS_RATE')]['levels'] == ['county']
    assert by_id[('clh', 'ACS_PCT_HU_NO_VEH')]['levels'] == ['county', 'tract']
    assert by_id[('acs', 'B19013_001E')]['levels'] == ['state', 'county', 'tract']
    assert by_id[('usda_fea', 'snap_stores_per_1000')]['levels'] == ['county']
    assert all(p['published'] for p in catalog['products'])


def test_unpublished_product_is_omitted_from_values_and_flagged_in_catalog():
    db = FakeDb({}, releases=[])
    assert lookup.area_values(db, 'county', ['01055'])['values'] == []
    assert not any(p['published'] for p in lookup.catalog(db)['products'])


def test_area_without_row_gets_product_read_time_status_never_zero():
    rows = lookup.area_values(FakeDb({}), 'county', ['01055', '72001', '09110'])['values']
    status = {(r['product'], r['geoid']): r for r in rows}
    assert status[('epa_aqi', '01055')]['status'] == 'no_reported_value'
    assert status[('cms_gv', '72001')]['status'] == 'not_published'
    assert status[('usda_fea', '72001')]['status'] == 'not_covered'
    assert status[('usda_fea', '09110')]['status'] == 'boundary_not_comparable'
    assert status[('usda_fea', '01055')]['status'] == 'not_in_source'
    assert status[('places', '01055')]['status'] == lookup.NOT_IN_RELEASE
    assert all(r['value'] is None and r['stored'] is False for r in rows)


def test_uncertainty_kinds_stay_distinct():
    places, acs, ahrf = measure('places'), measure('acs'), measure('ahrf')
    db = FakeDb({
        'observation': [stored(places, '01055', value=Decimal('54.7'), ci_low=Decimal('50.6'), ci_high=Decimal('58.6'))],
        'observation_acs': [stored(acs, '01055', value=Decimal('54563'), moe=Decimal('2653'), estimate_annotation=None,
                                   moe_annotation=None, moe_confidence=90)],
        'observation_ahrf': [stored(ahrf, '01055', value=Decimal('0'), status='true_zero', source_code='01055')],
    })
    rows = {(r['product'], r['measure_id']): r for r in lookup.area_values(db, 'county', ['01055'])['values']}
    p = rows[('places', places['measure_id'])]
    assert p['value'] == 54.7 and p['uncertainty'] == {'kind': 'ci95', 'low': 50.6, 'high': 58.6, 'label': '95% confidence interval'}
    a = rows[('acs', acs['measure_id'])]
    assert a['value'] == 54563 and a['uncertainty'] == {'kind': 'moe90', 'moe': 2653, 'label': '90% margin of error'}
    h = rows[('ahrf', ahrf['measure_id'])]
    assert h['value'] == 0 and h['status'] == 'true_zero' and h['uncertainty']['kind'] == 'none'
    assert p['release_id'] == 'rel-places' and a['source_release_id'] == 'label-acs'


def test_level_filter_returns_only_products_published_at_that_level():
    state = {r['product'] for r in lookup.area_values(FakeDb({}), 'state', ['01'])['values']}
    tract = {r['product'] for r in lookup.area_values(FakeDb({}), 'tract', ['01055000100'])['values']}
    assert state == {'acs', 'acs_profile', 'cms_gv'}
    assert tract == {'places', 'acs', 'acs_profile', 'clh'}
    district = {r['product'] for r in lookup.area_values(FakeDb({}), 'cd', ['0103'])['values']}
    assert district == {'acs_profile'}   # no other product publishes district values; none is derived
    tract_measures = {r['measure_id'] for r in lookup.area_values(FakeDb({}), 'tract', ['01055000100'], products=['clh'])['values']}
    assert 'CCBP_SOGS_RATE' not in tract_measures and len(tract_measures) == 3


def test_tract_pattern_rejects_county_only_measures():
    with pytest.raises(lookup.LookupError_): lookup.county_tract_values(FakeDb({}), '01055', 'ahrf', 'hosp_23')
    with pytest.raises(lookup.LookupError_): lookup.county_tract_values(FakeDb({}), '01055', 'clh', 'CCBP_SOGS_RATE')


def test_district_geoid_is_four_digits():
    assert lookup._check('cd', ['0103']) == ['0103']
    with pytest.raises(lookup.LookupError_): lookup._check('cd', ['01ZZ'])
    with pytest.raises(lookup.LookupError_): lookup.district_counties(FakeDb({}), '01055')


def test_controlled_population_total_has_no_margin_and_says_why():
    meta = measure('acs_profile')
    db = FakeDb({'observation_acs_profile': [stored(meta, '01055', value=Decimal('103436'), moe=None, estimate_annotation=None,
                                                    moe_annotation='*****', moe_confidence=90)]})
    row = lookup.area_values(db, 'county', ['01055'], products=['acs_profile'], measure_ids=[meta['measure_id']])['values'][0]
    assert row['value'] == 103436 and row['uncertainty']['moe'] is None
    assert 'controlled' in row['uncertainty']['label'] and row['notes'] == {'moe_annotation': '*****'}


def test_facilities_only_for_state_or_county():
    with pytest.raises(lookup.LookupError_): lookup.area_facilities(FakeDb({}), 'tract', '01055000100')
