"""BRFSS state prevalence: registry contract, source-row validation, digests, and pairing with PLACES."""
import copy

import pytest

from app.area_pilot import brfss, lookup
from app.area_pilot.registry import load_registry as load_places_registry

CONFIG = brfss.load_registry()
DIABETES = next(m for m in CONFIG['measures'] if m['measure_id'] == 'diabetes')


def source_row(measure=DIABETES, **changes):
    row = {'year': measure['observation_period'], 'locationabbr': 'NC', 'locationdesc': 'North Carolina',
           'class': measure['source_class'], 'topic': measure['source_topic'], 'question': measure['source_question'],
           'response': measure['response'], 'break_out': 'Overall', 'break_out_category': 'Overall',
           'sample_size': '577', 'data_value': '12.4', 'confidence_limit_low': '11.0', 'confidence_limit_high': '13.8',
           'data_value_unit': '%', 'data_value_type': 'Crude Prevalence', 'datasource': 'BRFSS', 'locationid': '37',
           'questionid': measure['question_id'], 'responseid': measure['response_id']}
    return row | changes


def test_registry_has_thirteen_places_pairs_and_seven_state_only_measures():
    paired = [m for m in CONFIG['measures'] if m['places_measure_id']]
    assert len(CONFIG['measures']) == 20 and len(paired) == 13
    places = {m['measure_id']: m for m in load_places_registry('tract')['measures']}
    assert {m['places_measure_id'] for m in paired} == set(places)
    for measure in paired:   # a pair describes the same year and the same population
        assert measure['observation_period'] == places[measure['places_measure_id']]['observation_period']
        assert measure['population'] == places[measure['places_measure_id']]['population']


def test_selection_is_one_overall_response_per_measure():
    where = brfss.where_clause(CONFIG)
    assert where.startswith("break_out='Overall' AND (") and where.count(' OR ') == 19
    assert "(year='2022' AND questionid='_DENVST3' AND responseid='RESP046')" in where
    assert len(brfss.expected_keys(CONFIG)) == 19 * 54 + 56


def test_kentucky_and_pennsylvania_are_absent_only_in_2023():
    assert not {'21', '42'} & set(CONFIG['expected_locations']['2023'])
    assert {'21', '42'} <= set(CONFIG['expected_locations']['2022'])
    assert all(m.get('documented_unavailable_states') == ['KY', 'PA']
               for m in CONFIG['measures'] if m['observation_period'] == '2023')


def test_published_value_keeps_cdc_limits_and_response_count():
    parsed = brfss.parse_observation(source_row(), DIABETES, CONFIG)
    assert (str(parsed['value']), str(parsed['ci_low']), str(parsed['ci_high'])) == ('12.4', '11.0', '13.8')
    assert parsed['sample_size'] == 577 and parsed['status'] == 'available' and parsed['location_kind'] == 'state'


def test_median_row_has_no_interval_and_is_not_a_state():
    row = source_row(locationid='98', locationabbr='UW', data_value='11.5', sample_size='49',
                     confidence_limit_low=None, confidence_limit_high=None, data_value_footnote_symbol='**')
    parsed = brfss.parse_observation(row, DIABETES, CONFIG)
    assert parsed['location_kind'] == 'median' and parsed['ci_low'] is None and str(parsed['value']) == '11.5'
    with pytest.raises(ValueError):   # a median without CDC's footnote is not the documented form
        brfss.parse_observation(row | {'data_value_footnote_symbol': None}, DIABETES, CONFIG)


def test_territory_without_boundary_is_source_only():
    parsed = brfss.parse_observation(source_row(locationid='66', locationabbr='GU'), DIABETES, CONFIG)
    assert parsed['location_kind'] == 'source_only'


def test_unavailable_value_needs_the_cdc_footnote():
    blank = source_row(data_value=None, confidence_limit_low=None, confidence_limit_high=None)
    with pytest.raises(ValueError):
        brfss.parse_observation(blank, DIABETES, CONFIG)
    parsed = brfss.parse_observation(blank | {'data_value_footnote_symbol': '*'}, DIABETES, CONFIG)
    assert parsed['status'] == 'not_available' and parsed['value'] is None


@pytest.mark.parametrize('changes', [
    {'response': 'No'}, {'break_out': 'Male'}, {'data_value_type': 'Age-adjusted Prevalence'},
    {'question': 'A reworded question'}, {'locationid': '21', 'locationabbr': 'KY'},
    {'locationid': '37', 'locationabbr': 'SC'}, {'data_value': '14.0'}, {'data_value': '101'},
    {'confidence_limit_low': None}, {'sample_size': '5.5'}, {'data_value_footnote_symbol': '*'},
])
def test_rows_that_differ_from_the_reviewed_source_are_rejected(changes):
    with pytest.raises(ValueError):
        brfss.parse_observation(source_row(**changes), DIABETES, CONFIG)


def test_parse_rows_rejects_duplicates_and_rows_outside_the_selection():
    columns = [{'fieldName': name, 'dataTypeName': 'number' if name in ('year', 'sample_size', 'data_value',
                'confidence_limit_low', 'confidence_limit_high') else 'text'} for name in source_row()]
    records = brfss.parse_rows([source_row()], CONFIG, columns)
    assert list(records) == [('diabetes', '37')] and records[('diabetes', '37')]['data_value'] == '12.4'
    with pytest.raises(ValueError):
        brfss.parse_rows([source_row(), source_row()], CONFIG, columns)
    with pytest.raises(ValueError):
        brfss.parse_rows([source_row(responseid='RESP054')], CONFIG, columns)


def test_digests_follow_content_and_measure_set_not_source_timestamps():
    columns = [{'fieldName': 'year', 'dataTypeName': 'number'}]
    base = brfss.metadata_payload(CONFIG, columns)
    assert 'rowsUpdatedAt' not in str(base)
    changed = copy.deepcopy(CONFIG)
    changed['measures'][0]['places_measure_id'] = None
    assert brfss.metadata_payload(changed, columns) != base
    one = {('diabetes', '37'): {'data_value': '12.4'}}
    assert brfss.semantic_sha(one) != brfss.semantic_sha({('diabetes', '37'): {'data_value': '12.5'}})


def test_lookup_exposes_brfss_at_state_level_with_pairs_both_ways():
    spec = next(s for s in lookup.SPECS if s.key == 'brfss')
    assert list(spec.tables) == ['state'] and spec.uncertainty == 'ci95'
    assert lookup.MISSING_STATUS['brfss']('21', 'state') == 'not_published'
    pairs = lookup._pairs()
    assert pairs[('places', 'diabetes_crudeprev')] == {'product': 'brfss', 'measure_id': 'diabetes'}
    assert pairs[('brfss', 'uninsured_18_64')] == {'product': 'places', 'measure_id': 'access2_crudeprev'}
    assert ('brfss', 'binge_drinking') not in pairs
    meta = lookup._measure_meta(spec, CONFIG, DIABETES)
    assert meta['levels'] == ['state'] and meta['source_credit'] is None
    assert meta['paired_measure'] == {'product': 'places', 'measure_id': 'diabetes_crudeprev'}
