"""Unit tests for the ACS community-characteristics product (no network, no database)."""
from decimal import Decimal

import pytest

from app.area_pilot import acs_profile as a
from app.area_pilot.source import digest

CONFIG = a.load_registry()
BY_ID = {m['measure_id']: m for m in CONFIG['measures']}


def row(level='county', **overrides):
    base = {'NAME': 'Example'}
    for m in CONFIG['measures']:
        v = m['variable']
        base |= {v + 'E': '1000' if m['kind'] == 'count' else '12.5', v + 'M': '50' if m['kind'] == 'count' else '1.5',
                 v + 'EA': None, v + 'MA': None}
    base |= {'state': '01'} | ({'county': '055'} if level in ('county', 'tract') else {}) | (
        {'tract': '000200'} if level == 'tract' else {}) | ({'congressional district': '03'} if level == 'cd' else {})
    return base | overrides


def payload(level, *rows):
    header = list(rows[0])
    return [header] + [[r[h] for h in header] for r in rows]


def test_registry_is_pinned_and_measures_are_published_values_only():
    assert CONFIG['aggregation_method'] == 'none' and CONFIG['geographies'] == ['state', 'county', 'tract', 'cd']
    assert len(CONFIG['measures']) == 7 and digest(CONFIG['source_variables']) == CONFIG['source_variables_sha256']
    assert BY_ID['poverty_pct']['variable'] == 'S1701_C03_001' and BY_ID['poverty_pct']['population'].startswith('population for whom poverty')
    assert BY_ID['uninsured_pct']['population'] == 'civilian noninstitutionalized population'
    assert len(a.fields(CONFIG)) == 1 + 7 * 4 <= 50   # Census API variable limit


def test_percent_count_and_zero():
    r = row()
    assert a.parse_observation(r, BY_ID['poverty_pct']) == {'value': Decimal('12.5'), 'moe': Decimal('1.5'),
        'estimate_annotation': None, 'moe_annotation': None, 'status': 'available', 'moe_confidence': 90}
    assert a.parse_observation(r, BY_ID['total_population'])['value'] == Decimal(1000)
    zero = a.parse_observation(row(S1701_C03_001E='0.0', S1701_C03_001M='2.1'), BY_ID['poverty_pct'])
    assert zero['status'] == 'true_zero' and zero['value'] == 0


def test_census_codes_stay_distinct_from_zero():
    missing = a.parse_observation(row(S1701_C03_001E='-666666666.0', S1701_C03_001M='-222222222.0',
                                      S1701_C03_001EA='-', S1701_C03_001MA='**'), BY_ID['poverty_pct'])
    assert (missing['value'], missing['moe'], missing['status']) == (None, None, 'missing')
    assert (missing['estimate_annotation'], missing['moe_annotation']) == ('-', '**')
    suppressed = a.parse_observation(row(S1810_C03_001E='-999999999', S1810_C03_001M='-999999999',
                                         S1810_C03_001EA='N', S1810_C03_001MA='N'), BY_ID['disability_pct'])
    assert suppressed['status'] == 'suppressed'
    controlled = a.parse_observation(row(S0101_C01_001E='681294', S0101_C01_001M='-555555555', S0101_C01_001MA='*****'),
                                     BY_ID['total_population'])
    assert controlled['status'] == 'available' and controlled['moe'] is None and controlled['moe_annotation'] == '*****'


@pytest.mark.parametrize('overrides', [
    {'S1701_C03_001E': '-666666666.0', 'S1701_C03_001M': '-222222222.0', 'S1701_C03_001EA': 'N', 'S1701_C03_001MA': '**'},  # code/annotation mismatch
    {'S1701_C03_001E': '-5'},                               # unknown negative code
    {'S1701_C03_001E': '101.0'},                            # impossible percentage
    {'S1701_C03_001E': '12.5', 'S1701_C03_001M': None},     # margin missing without a Census code
    {'S1701_C03_001E': None},                               # estimate missing without a Census code
    {'S0101_C01_001E': '1000.5'},                           # fractional count
    {'S1701_C03_001E': '12.5', 'S1701_C03_001EA': 'x'},     # unexpected annotation
    {'S1701_C03_001E': '-666666666.0', 'S1701_C03_001EA': '-', 'S1701_C03_001M': '3.0'},  # margin for unavailable estimate
])
def test_unexplained_cells_are_rejected(overrides):
    r = row(**overrides)
    with pytest.raises(ValueError):
        for m in CONFIG['measures']:
            a.parse_observation(r, m)


def test_response_validation_and_district_exclusions():
    records, excluded = a.parse_response(payload('cd', row('cd'), row('cd', **{'congressional district': '00'}),
                                                 row('cd', **{'congressional district': 'ZZ', 'NAME': 'not defined'})),
                                         'cd', CONFIG, '01')
    assert sorted(records) == ['0100', '0103'] and list(excluded) == ['01ZZ']
    with pytest.raises(ValueError): a.parse_response(payload('cd', row('cd'), row('cd')), 'cd', CONFIG, '01')            # duplicate
    with pytest.raises(ValueError): a.parse_response(payload('cd', row('cd', **{'congressional district': 'AB'})), 'cd', CONFIG, '01')
    with pytest.raises(ValueError): a.parse_response(payload('county', row()), 'county', CONFIG, '02')                   # wrong state
    short = row(); short.pop('S1601_C06_001MA')
    with pytest.raises(ValueError): a.parse_response(payload('county', short), 'county', CONFIG, '01')                   # header changed
    tract, _ = a.parse_response(payload('tract', row('tract')), 'tract', CONFIG, '01')
    assert list(tract) == ['01055000200']


def test_semantic_digest_is_order_independent_and_value_sensitive():
    one = {('county', '01055'): row(), ('state', '01'): row('state')}
    two = dict(reversed(list(one.items())))
    assert a.semantic_sha(one) == a.semantic_sha(two)
    changed = {**one, ('county', '01055'): row(S1701_C03_001E='12.6')}
    assert a.semantic_sha(one) != a.semantic_sha(changed)


def test_api_selection_rejects_unpublished_combinations():
    from fastapi import HTTPException
    from app.area_pilot import acs_profile_api as api

    class Db:
        def execute(self, *args, **kwargs):
            class R:
                def scalar_one_or_none(self_inner): return 'published'
            return R()
    m = BY_ID['poverty_pct']
    ok = api.selection(Db(), CONFIG['dataset_id'], 'r', 'poverty_pct', m['observation_period'], m['population'], CONFIG['value_type'], 'cd')
    assert ok[1]['measure_id'] == 'poverty_pct'
    for bad in ({'geography': 'place'}, {'period': '2024'}, {'population': 'total population'}, {'value_type': 'x'}, {'measure_id': 'nope'}):
        args = {'measure_id': 'poverty_pct', 'period': m['observation_period'], 'population': m['population'],
                'value_type': CONFIG['value_type'], 'geography': 'county'} | bad
        with pytest.raises(HTTPException):
            api.selection(Db(), CONFIG['dataset_id'], 'r', args['measure_id'], args['period'], args['population'], args['value_type'], args['geography'])
    meta = api.metadata(CONFIG, BY_ID['total_population'], 'r', 'cd', '0,0,1,1')
    assert meta['legend_breaks'] == BY_ID['total_population']['legend_breaks']['cd'] and meta['boundary_vintage'].startswith('119th Congress')
