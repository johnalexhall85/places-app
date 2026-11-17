import json
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from app.mcp_server import tools, measures, places, cache
from app.mcp_server.envelope import build, fit_rows, size_bytes, value_row
from app.mcp_server.config import MAX_BYTES, ORDER_WARNING, WITHHELD_TOPIC_WARNING


class Session:
    def close(self):
        self.closed = True


@pytest.fixture
def stub(monkeypatch):
    cache._CACHE.clear()
    session = Session()
    monkeypatch.setattr(tools.db_module, 'SessionLocal', lambda: session)
    monkeypatch.setattr(tools.lookup, 'active_releases', lambda db: {})
    monkeypatch.setattr(tools.lookup, 'measure_periods', lambda db, product, measure_id: [
        {'period': '2023', 'current': True, 'available': True, 'note': None,
         'boundary_vintage': None, 'release_id': 'rid'}])
    return monkeypatch, session


def product():
    return {'product': 'places', 'dataset_id': 'ds', 'name': 'PLACES pilot', 'publisher': 'CDC',
            'landing_page': 'https://example.org', 'limitations': ['Modeled estimate.'],
            'release': {'release_id': 'rid', 'source_release_id': '2025', 'published_at': '2026-01-01T00:00:00+00:00'}}


def row(value=14.9, status='available', geoid='37145'):
    return {'product': 'places', 'measure_id': 'diabetes_crudeprev', 'label': 'Diabetes',
            'level': 'county', 'geoid': geoid, 'value': value, 'unit': 'percent', 'storage_scale': None,
            'status': status, 'status_text': 'Published value' if value is not None else 'Not published',
            'uncertainty': {'kind': 'ci95', 'low': 12.7, 'high': 17.2}, 'period': '2023',
            'population': 'adults', 'value_type': 'crude_prevalence', 'boundary_vintage': 'TIGER 2023',
            'release_id': 'rid', 'notes': {}, 'source_credit': None}


def catalog():
    p = product()
    q = dict(p, product='ahrf', name='AHRF', dataset_id='private')
    m = {'product': 'places', 'measure_id': 'diabetes_crudeprev', 'label': 'Diabetes',
         'product_name': 'PLACES pilot', 'publisher': 'CDC', 'levels': ['county', 'tract'],
         'period': '2023', 'population': 'adults', 'unit': 'percent', 'definition': 'Diagnosed diabetes'}
    return {'products': [p, q], 'measures': [m, dict(m, product='ahrf', measure_id='private', label='Private')]}


def test_envelope_citation_and_value_projection():
    p = product()
    value = value_row(row(), p, p['release'], 'Person')
    assert set(value) == {'measure_key', 'label', 'area', 'value', 'unit', 'storage_scale', 'status',
                          'status_text', 'uncertainty', 'period', 'population', 'value_type',
                          'boundary_vintage', 'release_id', 'notes', 'note', 'source_credit', 'citation'}
    assert value['citation'] == 'Source: CDC · PLACES pilot · 2023 · release 2025'
    envelope = build({'values': [value]}, [p])
    assert envelope.sources[0]['release_id'] == 'rid'
    assert 'Modeled estimate.' in envelope.interpretation_rules


def test_public_only_search_details_and_values(stub):
    monkeypatch, session = stub
    monkeypatch.setattr(tools.lookup, 'catalog', lambda db: catalog())
    monkeypatch.setattr(tools.lookup, 'area_info', lambda *args: [{'geoid': '37145', 'name': 'Person'}])
    monkeypatch.setattr(tools.lookup, 'area_values', lambda *args, **kwargs: {'values': [row(), dict(row(), product='ahrf', measure_id='private')]})
    result = tools.search_measures(query='private')
    assert result.data['measures'] == []
    result = tools.get_measure_details(['places:diabetes_crudeprev'])
    assert 'ahrf' not in result.model_dump_json().lower()
    assert result.data['measures'][0]['measure_key'] == 'places:diabetes_crudeprev'
    assert result.data['measures'][0]['product'] == 'places'
    assert result.data['measures'][0]['measure_id'] == 'diabetes_crudeprev'
    result = tools.get_area_values('county', ['37145'], ['places:diabetes_crudeprev'])
    assert len(result.data['values']) == 1
    assert 'ahrf' not in result.model_dump_json().lower()
    for call in (lambda: tools.get_measure_details(['ahrf:private']),
                 lambda: tools.get_area_values('county', ['37145'], ['ahrf:private']),
                 lambda: tools.get_measure_across_areas('ahrf:private', 'county', 'AL')):
        with pytest.raises(ToolError, match='not available through the public server'):
            call()
    assert session.closed


def test_topics_strip_restricted_keys():
    content = json.dumps(measures.topics())
    assert 'ahrf' not in content.lower()
    assert all(not k.startswith('ahrf:') for t in measures.topics() for k in t['measure_keys'])


def test_sorted_ties_and_missing_never_cut(stub):
    monkeypatch, _ = stub
    monkeypatch.setattr(tools.lookup, 'catalog', lambda db: catalog())
    monkeypatch.setattr(tools.lookup, 'states', lambda db: [{'geoid': '01', 'name': 'Alabama'}])
    rows = [dict(row(value=v, geoid=g), name=g) for g, v in [('01001', 7), ('01003', 9), ('01005', 9), ('01007', None)]]
    monkeypatch.setattr(tools.lookup, 'measure_values_within', lambda *args: {'values': rows})
    out = tools.get_measure_across_areas('places:diabetes_crudeprev', 'county', 'AL', 'value_desc', 2)
    assert [(r['area']['geoid'], r['position']) for r in out.data['with_value']] == [('01003', 1), ('01005', 1)]
    assert out.data['without_value'][0]['area']['geoid'] == '01007'
    assert out.data['truncated'] is True
    assert ORDER_WARNING in out.warnings
    assert all('position' not in r for r in out.data['without_value'])
    assert out.data['measure']['citation'].startswith('Source: CDC')
    assert out.data['measure']['boundary_vintage'] == 'TIGER 2023'
    assert 'measure_key' not in out.data['with_value'][0]
    assert 'notes' not in out.data['with_value'][0]
    assert tools.get_measure_across_areas('places:diabetes_crudeprev', 'county', 'AL', 'geoid', 10).data['with_value'][0].get('position') is None


def test_row_cap_and_actionable_errors(stub):
    monkeypatch, _ = stub
    monkeypatch.setattr(tools.lookup, 'catalog', lambda db: catalog())
    many = [dict(catalog()['measures'][0], measure_id=f'm{i}') for i in range(20)]
    monkeypatch.setattr(tools.lookup, 'catalog', lambda db: {'products': catalog()['products'], 'measures': many})
    with pytest.raises(ToolError, match='narrow the measures or areas'):
        tools.get_area_values('county', [f'{i:05d}' for i in range(25)])
    with pytest.raises(ToolError, match='find_places'):
        tools.get_area_values('county', ['bad'])
    with pytest.raises(ToolError, match='search_measures'):
        tools.get_measure_details(['x:y'])


def test_size_limit_preserves_missing_rows():
    result = build({'with_value': [{'text': 'x' * 1000} for _ in range(100)],
                    'without_value': [{'status': 'missing', 'geoid': '001'}], 'truncated': False})
    fit_rows(result, 'with_value')
    assert size_bytes(result) <= MAX_BYTES
    assert result.data['truncated']
    assert result.data['without_value'] == [{'status': 'missing', 'geoid': '001'}]


def test_size_uses_client_json_serialization():
    result = build({'text': 'é<>&'})
    expected = len(json.dumps(result.model_dump(mode='json'), separators=(',', ':'),
                              ensure_ascii=False).encode('utf-8'))
    assert size_bytes(result) == expected


def test_unpublished_level_and_metadata_source(stub):
    monkeypatch, _ = stub
    monkeypatch.setattr(tools.lookup, 'catalog', lambda db: catalog())
    monkeypatch.setattr(tools.lookup, 'area_info', lambda *args: [{'geoid': '01', 'name': 'Alabama'}])
    values = tools.get_area_values('state', ['01'], ['places:diabetes_crudeprev'])
    assert values.data['values'] == [] and values.sources == []
    assert 'published for county, tract' in values.warnings[0]
    monkeypatch.setattr(tools.lookup, 'measure_values_within', lambda *args: {'values': []})
    monkeypatch.setattr(tools.lookup, 'states', lambda db: [{'geoid': '01', 'name': 'Alabama'}])
    across = tools.get_measure_across_areas('places:diabetes_crudeprev', 'county', 'AL')
    assert across.data['with_value'] == []
    assert across.data['measure']['release_id'] == 'rid'
    assert [s['product'] for s in across.sources] == ['places']
    with pytest.raises(ToolError, match='published for county, tract'):
        tools.get_measure_across_areas('places:diabetes_crudeprev', 'state')


def test_open_ended_value_and_varying_boundary(stub):
    monkeypatch, _ = stub
    monkeypatch.setattr(tools.lookup, 'catalog', lambda db: catalog())
    monkeypatch.setattr(tools.lookup, 'states', lambda db: [{'geoid': '01', 'name': 'Alabama'}])
    rows = [dict(row(value=8, status='open_ended', geoid='01001'), name='Autauga'),
            dict(row(value=None, geoid='01003'), name='Baldwin', boundary_vintage='TIGER 2024')]
    monkeypatch.setattr(tools.lookup, 'measure_values_within', lambda *args: {'values': rows})
    out = tools.get_measure_across_areas('places:diabetes_crudeprev', 'county', 'AL')
    assert len(out.data['with_value']) == len(out.data['without_value']) == 1
    assert out.data['with_value'][0]['status'] == 'open_ended'
    assert 'boundary_vintage' not in out.data['measure']
    assert [r['boundary_vintage'] for r in out.data['with_value'] + out.data['without_value']] == ['TIGER 2023', 'TIGER 2024']


def test_withheld_topic_and_search_explanations(stub):
    monkeypatch, _ = stub
    private = [dict(catalog()['measures'][0], product='ahrf', measure_id=measure_id,
                    label=label, definition=label, product_name='HRSA AHRF')
               for measure_id, label in [('physicians', 'Primary care physicians'),
                                         ('hospitals', 'Hospital beds'),
                                         ('dentists', 'Professionally active dentists'),
                                         ('psychiatrists', 'Psychiatrists in patient care')]]
    c = catalog()
    c['measures'].extend(private)
    monkeypatch.setattr(tools.lookup, 'catalog', lambda db: c)
    browse = tools.search_measures()
    assert WITHHELD_TOPIC_WARNING in browse.warnings
    assert all(t['slug'] != 'health-care-resources' for t in browse.data['topics'])
    for call in (lambda: tools.search_measures(topic='health-care-resources'),
                 lambda: tools.get_area_values('county', ['37145'], topic='health-care-resources')):
        with pytest.raises(ToolError, match='Health care resources') as exc:
            call()
        assert 'HRSA AHRF' in str(exc.value)
        assert 'Unknown topic' not in str(exc.value)
    for query in ('primary care doctors', 'hospital beds', 'dentists', 'psychiatrists'):
        result = tools.search_measures(query=query)
        assert result.data['measures'] == []
        assert any('HRSA AHRF' in warning for warning in result.warnings)


def test_district_parser():
    states = [{'geoid': '54', 'name': 'West Virginia'}, {'geoid': '37', 'name': 'North Carolina'},
              {'geoid': '02', 'name': 'Alaska'}]
    for query, geoid, number in [('WV-1', '54', 1), ('WV-01', '54', 1),
                                  ('West Virginia 1st', '54', 1), ('NC district 4', '37', 4),
                                  ('AK at-large', '02', 0)]:
        state, actual = places.parse_district(query, states)
        assert (state['geoid'], actual) == (geoid, number)
    assert places.parse_district('not a district', states) is None


def test_cache_changes_with_active_release(stub):
    monkeypatch, _ = stub
    calls = []
    fingerprint = {'release': 'one'}
    monkeypatch.setattr(tools.lookup, 'active_releases', lambda db: fingerprint.copy())
    monkeypatch.setattr(tools.lookup, 'states', lambda db: calls.append(1) or [{'geoid': '01', 'name': 'Alabama'}])
    monkeypatch.setattr(places, 'search_counties', lambda **kwargs: [])
    tools.find_places('AL', levels=['state'])
    tools.find_places('AL', levels=['state'])
    assert len(calls) == 1
    fingerprint['release'] = 'two'
    tools.find_places('AL', levels=['state'])
    assert len(calls) == 2


def test_lookup_error_preserved_and_unexpected_error_sanitized(stub):
    monkeypatch, _ = stub
    monkeypatch.setattr(tools.lookup, 'states', lambda db: (_ for _ in ()).throw(tools.lookup.LookupError_('Use a valid state')))
    with pytest.raises(ToolError, match='Use a valid state'):
        tools.find_places('AL')
    monkeypatch.setattr(tools.lookup, 'states', lambda db: (_ for _ in ()).throw(RuntimeError('SQL secret detail')))
    with pytest.raises(ToolError, match='^Internal error; please retry or narrow the request$') as exc:
        tools.find_places('AL')
    assert 'SQL secret detail' not in str(exc.value)


def test_period_selection_and_unpublished_period(stub):
    monkeypatch, _ = stub
    monkeypatch.setattr(tools.lookup, 'catalog', lambda db: catalog())
    monkeypatch.setattr(tools.lookup, 'area_info', lambda *args: [{'geoid': '37145', 'name': 'Person'}])
    monkeypatch.setattr(tools.lookup, 'states', lambda db: [{'geoid': '37', 'name': 'North Carolina'}])
    periods = [{'period': '2023', 'available': True, 'current': True},
               {'period': '2022', 'available': True, 'current': False},
               {'period': '2021', 'available': False, 'current': False}]
    monkeypatch.setattr(tools.lookup, 'measure_periods', lambda *args: periods)
    history_release = {'release_id': 'old', 'source_release_id': 'older', 'published_at': '2026-01-01'}
    monkeypatch.setattr(tools.lookup, 'active_releases', lambda db: {'ds:history': history_release})
    calls = []
    monkeypatch.setattr(tools.lookup, 'area_values', lambda *a, **kw: calls.append('current') or {'values': [row()]})
    older = dict(row(), period='2022', release_id='old', note='Earlier method', boundary_vintage='TIGER 2020')
    monkeypatch.setattr(tools.lookup, 'area_values_for_period', lambda *a: calls.append('history') or {'values': [older], 'unavailable': []})
    monkeypatch.setattr(tools.lookup, 'measure_values_within', lambda *a, **kw: calls.append(kw.get('period')) or {'values': [dict(older, name='Person')]})
    assert tools.get_area_values('county', ['37145'], ['places:diabetes_crudeprev']).data['values'][0]['note'] is None
    historical = tools.get_area_values('county', ['37145'], ['places:diabetes_crudeprev'], period='2022')
    assert historical.data['values'][0]['citation'].endswith('release older')
    assert historical.sources[0]['dataset_id'] == 'ds:history'
    assert calls[:2] == ['current', 'history']
    absent = tools.get_area_values('county', ['37145'], ['places:diabetes_crudeprev'], period='2021')
    assert absent.data['values'] == [] and '2023, 2022' in absent.warnings[0]
    across = tools.get_measure_across_areas('places:diabetes_crudeprev', 'county', '37', period='2022')
    assert across.data['measure']['note'] == 'Earlier method'
    assert across.data['measure']['citation'].endswith('release older')
    assert 'note' not in across.data['with_value'][0]
    assert calls[-1] == '2022'
    with pytest.raises(ToolError, match='2023, 2022'):
        tools.get_measure_across_areas('places:diabetes_crudeprev', 'county', '37', period='2021')
    with pytest.raises(ToolError, match='Congressional districts have no earlier periods'):
        tools.get_measure_across_areas('places:diabetes_crudeprev', 'cd', '37', period='2022')


def test_series_order_sources_and_boundary_warning(stub):
    monkeypatch, _ = stub
    monkeypatch.setattr(tools.lookup, 'catalog', lambda db: catalog())
    monkeypatch.setattr(tools.lookup, 'area_info', lambda *args: [{'geoid': '37145', 'name': 'Person'}])
    monkeypatch.setattr(tools.lookup, 'active_releases', lambda db: {'ds:history': {
        'release_id': 'old', 'source_release_id': 'older', 'published_at': '2026-01-01'}})
    old = dict(row(), period='2022', release_id='old', note='Old boundary', boundary_vintage='TIGER 2020')
    monkeypatch.setattr(tools.lookup, 'area_measure_series', lambda *args: {
        'series': [old, row()], 'unavailable_periods': [{'period': '2021', 'reason': 'not published'}]})
    result = tools.get_measure_over_time('county', '37145', 'places:diabetes_crudeprev')
    assert [r['period'] for r in result.data['series']] == ['2022', '2023']
    assert result.data['series'][0]['note'] == 'Old boundary'
    assert {s['dataset_id'] for s in result.sources} == {'ds', 'ds:history'}
    assert any('boundary vintage differs' in w for w in result.warnings)
    assert result.data['unavailable_periods'][0]['period'] == '2021'
    with pytest.raises(ToolError, match='not available through the public server'):
        tools.get_measure_over_time('county', '37145', 'ahrf:private')


def test_long_series_stays_within_size_cap(stub):
    monkeypatch, _ = stub
    monkeypatch.setattr(tools.lookup, 'catalog', lambda db: catalog())
    monkeypatch.setattr(tools.lookup, 'area_info', lambda *args: [{'geoid': '37145', 'name': 'Person'}])
    rows = [dict(row(), period=str(i), notes={'large': 'x' * 1000}) for i in range(100)]
    monkeypatch.setattr(tools.lookup, 'area_measure_series', lambda *args: {'series': rows, 'unavailable_periods': []})
    result = tools.get_measure_over_time('county', '37145', 'places:diabetes_crudeprev')
    assert result.data['truncated'] is True
    assert len(result.data['series']) < len(rows)
    assert size_bytes(result) <= MAX_BYTES
