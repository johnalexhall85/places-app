import json
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from app.mcp_server import tools, measures, places, cache
from app.mcp_server.envelope import build, fit_rows, size_bytes, value_row
from app.mcp_server.config import MAX_BYTES, ORDER_WARNING


class Session:
    def close(self):
        self.closed = True


@pytest.fixture
def stub(monkeypatch):
    cache._CACHE.clear()
    session = Session()
    monkeypatch.setattr(tools.db_module, 'SessionLocal', lambda: session)
    monkeypatch.setattr(tools.lookup, 'active_releases', lambda db: {})
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
                          'boundary_vintage', 'release_id', 'notes', 'source_credit', 'citation'}
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
