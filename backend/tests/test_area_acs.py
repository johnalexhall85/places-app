import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot.acs import (CensusClient, FIELDS, load_registry, parse_observation,
                                parse_response, semantic_sha)
from app.area_pilot import acs_api
from app.area_pilot import acs_cli


def row(**changes):
    result = {'NAME': 'Area', 'B19013_001E': '0', 'B19013_001M': '5',
              'B19013_001EA': None, 'B19013_001MA': None,
              'state': '09', 'county': '110', 'tract': '000100'}
    return result | changes


def test_acs_zero_missing_open_ended_and_90_percent_moe():
    assert parse_observation(row()) == {'value': 0, 'moe': 5, 'estimate_annotation': None,
                                        'moe_annotation': None, 'status': 'true_zero', 'moe_confidence': 90}
    missing = parse_observation(row(B19013_001E='-666666666', B19013_001EA='-',
                                    B19013_001M='-222222222', B19013_001MA='**'))
    assert missing['value'] is None and missing['moe'] is None and missing['status'] == 'missing'
    open_ended = parse_observation(row(B19013_001E='250001', B19013_001EA='250,000+',
                                       B19013_001M='-333333333', B19013_001MA='***'))
    assert open_ended['status'] == 'open_ended' and open_ended['moe'] is None
    assert open_ended['estimate_annotation'] == '250,000+'
    with pytest.raises(ValueError, match='sentinel annotation mismatch'):
        parse_observation(row(B19013_001E='-666666666', B19013_001EA=None))
    with pytest.raises(ValueError, match='unrecognized negative'):
        parse_observation(row(B19013_001E='-1'))
    with pytest.raises(ValueError, match='Unexplained absent MOE'):
        parse_observation(row(B19013_001M=None))


def test_census_header_partition_duplicate_and_semantic_digest():
    first = row()
    second = row(tract='000200', B19013_001E='10')
    header = list(first)
    assert list(parse_response([header, list(first.values()), list(second.values())], 'tract', '09')) == [
        '09110000100', '09110000200']
    assert semantic_sha({('tract', '09110000100'): first, ('tract', '09110000200'): second}) == \
           semantic_sha({('tract', '09110000200'): dict(reversed(list(second.items()))),
                         ('tract', '09110000100'): first})
    with pytest.raises(ValueError, match='header'):
        parse_response([header[:-1], list(first.values())[:-1]], 'tract', '09')
    with pytest.raises(ValueError, match='Duplicate'):
        parse_response([header, list(first.values()), list(first.values())], 'tract', '09')
    with pytest.raises(ValueError, match='different state'):
        parse_response([header, list(first.values())], 'tract', '72')


def test_census_client_redacts_key_from_archive_and_errors(tmp_path):
    client = CensusClient(load_registry(), tmp_path, api_key='unit-secret', pause=0)
    class Response:
        status_code = 200
        content = b'[["NAME"],["Area"]]'
        def json(self): return json.loads(self.content)
    client.session.get = lambda *args, **kwargs: Response()
    client.get('https://api.census.gov/example', {'get': 'NAME'}, 'sample', True)
    assert 'unit-secret' not in str(client.files)
    assert 'unit-secret' not in Path(client.files[0]['path']).read_text()
    class ErrorResponse:
        status_code = 403
    client.session.get = lambda *args, **kwargs: ErrorResponse()
    with pytest.raises(RuntimeError) as error:
        client.get('https://api.census.gov/example', {}, 'forbidden', True)
    assert 'unit-secret' not in str(error.value)


def test_acs_selection_and_explicit_cap():
    config = load_registry()
    class DB:
        def execute(self, sql, params):
            if 'SELECT status' in str(sql):
                return SimpleNamespace(scalar_one_or_none=lambda: 'published')
            return SimpleNamespace(scalar_one=lambda: 5001)
    selected = acs_api.selection(DB(), config['dataset_id'], 'release-a', 'B19013_001E',
                                 '2020–2024', 'households', 'median_household_income', 'state')
    assert selected['moe_confidence'] == 90
    with pytest.raises(HTTPException):
        acs_api.selection(DB(), config['dataset_id'], 'release-a', 'B19013_001E',
                          '2024', 'households', 'median_household_income', 'county')
    with pytest.raises(HTTPException) as error:
        acs_api.ensure_cap(DB(), {})
    assert error.value.status_code == 413


def test_held_acs_candidate_cannot_change_active_pointer(monkeypatch):
    statements = []
    class Conn:
        def execute(self, sql, params=None):
            statements.append(str(sql))
            return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: {'status': 'held'}))
    class Context:
        def __enter__(self): return Conn()
        def __exit__(self, *_): return False
    class Engine:
        def begin(self): return Context()
    monkeypatch.setattr(acs_cli, 'review', lambda *args, **kwargs: {'status': 'held'})
    with pytest.raises(ValueError, match='not ready'):
        acs_cli.publish(Engine(), 'held-id', 'a', 'b', 'c', load_registry())
    assert not any('INSERT INTO area_pilot.active_release' in statement for statement in statements)
