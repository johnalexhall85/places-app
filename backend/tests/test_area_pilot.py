from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import hashlib
import json
import pytest
from fastapi import HTTPException
from app.area_pilot.registry import load_registry
from app.area_pilot.source import SourceClient, digest, normalize_record, parse_observation, semantic_digest
from app.area_pilot.router import bounds, CAP, TRACT_CAP, ensure_cap


def test_semantic_digest_ignores_json_order_and_numeric_format():
    columns = [{'fieldName':'countyfips','dataTypeName':'text'}, {'fieldName':'value','dataTypeName':'number'}]
    first = [{'countyfips':'01003','value':'1.0'}, {'countyfips':'01001','value':'0.00'}]
    second = [{'value':'0','countyfips':'01001'}, {'value':'1.00','countyfips':'01003'}]
    assert semantic_digest(first, columns) == semantic_digest(second, columns)
    second[0]['value'] = '2'
    assert semantic_digest(first, columns) != semantic_digest(second, columns)


def test_measure_period_ci_and_unavailable_states():
    measures = {m['measure_id']:m for m in load_registry()['measures']}
    assert measures['dental_crudeprev']['observation_period'] == '2022'
    assert measures['access2_crudeprev']['observation_period'] == '2023'
    dental = {'stateabbr':'CA','dental_crudeprev':'0','dental_crude95ci':'(0, 1)'}
    assert parse_observation(dental, measures['dental_crudeprev']) == (Decimal(0), Decimal(0), Decimal(1), 'available')
    assert parse_observation({'stateabbr':'KY'}, measures['access2_crudeprev'])[-1] == 'not_published'
    with pytest.raises(ValueError): parse_observation({'stateabbr':'CA','dental_crudeprev':'10','dental_crude95ci':'(11, 12)'}, measures['dental_crudeprev'])


def test_keyset_pagination_and_changed_revision_hold(tmp_path, monkeypatch):
    monkeypatch.setattr('app.area_pilot.source.PAGE_SIZE', 2)
    config = load_registry() | {'expected_county_count':3, 'expected_schema_sha256':'x'*64}
    columns = [{'fieldName':'countyfips','name':'County FIPS','dataTypeName':'text','description':None},
               {'fieldName':'stateabbr','name':'State','dataTypeName':'text','description':None}]
    config['expected_schema_sha256'] = digest(columns)
    config['measures'] = []
    pages = [
        [{'countyfips':'01001','stateabbr':'AL'},{'countyfips':'01003','stateabbr':'AL'}],
        [{'countyfips':'01005','stateabbr':'AL'}],
    ]
    client = SourceClient(config, tmp_path, pause=0)
    snapshots = [dict(revision={'rowsUpdatedAt':1},columns=columns,keys=['01001','01003','01005'],count=3),
                 dict(revision={'rowsUpdatedAt':2},columns=columns,keys=['01001','01003','01005'],count=3)]
    client.snapshot = lambda role: snapshots.pop(0)
    seen = []
    def get(url, params, role):
        seen.append(params)
        return pages.pop(0)
    client.get = get
    before, after, rows, stable = client.fetch()
    assert not stable
    assert [r['countyfips'] for r in rows] == before['keys']
    assert seen[1]['$where'] == "countyfips > '01003'"


def test_bbox_and_cap_are_explicit():
    assert bounds('-180,-10,180,75')['east'] == 180
    with pytest.raises(HTTPException): bounds('0,0,0,1')
    class DB:
        def execute(self, *_): return SimpleNamespace(scalar_one=lambda: CAP + 1)
    with pytest.raises(HTTPException) as error: ensure_cap(DB(), {})
    assert error.value.status_code == 413


def test_original_bytes_are_hashed_and_checkpoint_tampering_is_rejected(tmp_path):
    content = b'[ { "countyfips": "01001" } ]'
    class Response:
        def __init__(self): self.content = content
        def raise_for_status(self): pass
        def json(self): return json.loads(self.content)
    client = SourceClient(load_registry(), tmp_path, pause=0)
    client.session.get = lambda *_, **__: Response()
    assert client.get('https://example.invalid/source', {'$limit':1}, 'page_000')[0]['countyfips'] == '01001'
    saved = client.files[0]
    assert saved['sha256'] == hashlib.sha256(content).hexdigest()
    client.resume_pages = True
    assert client.get('https://example.invalid/source', {'$limit':1}, 'page_000')[0]['countyfips'] == '01001'
    Path(saved['path']).write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='Checkpoint checksum'):
        client.get('https://example.invalid/source', {'$limit':1}, 'page_000')


def test_tract_registry_has_distinct_periods_and_ci_fields():
    tract = load_registry('tract')
    assert tract['source_key_field'] == 'tractfips'
    assert tract['expected_tract_count'] == 83522
    assert tract['expected_unavailable_tract_count'] == 4707
    measures = {m['measure_id']:m for m in tract['measures']}
    assert (measures['dental_crudeprev']['observation_period'], measures['dental_crudeprev']['source_ci_field']) == ('2022','dental_crude95ci')
    assert (measures['access2_crudeprev']['observation_period'], measures['access2_crudeprev']['source_ci_field']) == ('2023','access2_crude95ci')
    assert measures['access2_crudeprev']['documented_unavailable_states'] == ['KY','PA']


def test_tract_retrieval_rejects_equal_count_with_changed_key(tmp_path, monkeypatch):
    monkeypatch.setattr('app.area_pilot.source.PAGE_SIZE', 2)
    columns = [{'fieldName':'tractfips','name':'Tract FIPS','dataTypeName':'text','description':None}]
    config = load_registry('tract') | {'expected_tract_count':3,'expected_schema_sha256':digest(columns),'measures':[]}
    client = SourceClient(config,tmp_path,pause=0)
    snapshots = [dict(revision={'rowsUpdatedAt':1},columns=columns,keys=['01001000100','01001000200','01001000300'],count=3),
                 dict(revision={'rowsUpdatedAt':1},columns=columns,keys=['01001000100','01001000200','01001000400'],count=3)]
    client.snapshot = lambda role: snapshots.pop(0)
    pages = [[{'tractfips':'01001000100'},{'tractfips':'01001000200'}],[{'tractfips':'01001000300'}]]
    client.get = lambda url,params,role: pages.pop(0)
    before,after,records,stable = client.fetch()
    assert len(records) == before['count'] == after['count']
    assert not stable
    assert before['keys'] != after['keys']


def test_tract_result_cap_is_bounded_and_explicit():
    class DB:
        def execute(self, sql, params):
            assert 'LIMIT :cap_limit' in str(sql)
            assert params['cap_limit'] == TRACT_CAP + 1
            return SimpleNamespace(scalar_one=lambda: TRACT_CAP + 1)
    with pytest.raises(HTTPException) as error:
        ensure_cap(DB(), {}, 'tract')
    assert error.value.status_code == 413
    assert 'Zoom in' in error.value.detail
