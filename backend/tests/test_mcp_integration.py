"""Staging-only contract checks and one real Streamable HTTP client call."""
import asyncio
import json
import os
import socket
import subprocess
import time
from urllib.request import urlopen

import pytest
from mcp import Client
from app.db import SessionLocal
from app.area_pilot import lookup
from app.mcp_server import tools
from app.mcp_server.config import MAX_BYTES, ORDER_WARNING, WITHHELD_TOPIC_WARNING
from app.mcp_server.envelope import size_bytes


@pytest.fixture(scope='module')
def staging():
    db = SessionLocal()
    try:
        releases = lookup.active_releases(db)
        if not releases:
            pytest.skip('places_staging has no published releases')
    except Exception as exc:
        pytest.skip(f'places_staging unreachable: {type(exc).__name__}')
    finally:
        db.close()
    return True


def test_person_and_alabama(staging):
    person = tools.get_area_values('county', ['37145'], ['places:diabetes_crudeprev'])
    v = person.data['values'][0]
    assert v['value'] == 14.9 and v['uncertainty']['kind'] == 'ci95'
    assert (v['uncertainty']['low'], v['uncertainty']['high']) == (12.7, 17.2)
    assert (v['period'], v['population']) == ('2023', 'adults')
    assert v['area']['name'] == 'Person' and v['citation'].startswith('Source: Centers for Disease Control')
    al = tools.get_measure_across_areas('places:diabetes_crudeprev', 'county', 'AL', limit=5)
    assert al.data['total_areas'] == 67 and len(al.data['without_value']) == 0
    assert al.data['with_value'][0]['area']['geoid'] == '01001'
    assert al.data['with_value'][0]['value'] == 13.3
    sorted_al = tools.get_measure_across_areas('places:diabetes_crudeprev', 'county', 'AL', 'value_desc', 5)
    assert len(sorted_al.data['with_value']) == 5 and ORDER_WARNING in sorted_al.warnings


def test_missing_statuses_and_large_tract(staging):
    tx = tools.get_measure_across_areas('places:diabetes_crudeprev', 'county', '48', limit=5)
    assert tx.data['total_areas'] == 254
    assert len(tx.data['without_value']) == 1
    assert tx.data['without_value'][0]['status'] == 'not_in_release'
    aqi = tools.get_measure_across_areas('epa_aqi:median_aqi', 'county', '01', limit=20)
    assert aqi.data['total_areas'] == 67
    assert len(aqi.data['with_value']) == 15 and len(aqi.data['without_value']) == 52
    assert all(r['status'] == 'no_reported_value' for r in aqi.data['without_value'])
    brfss = tools.get_measure_across_areas('brfss:diabetes', 'state', limit=60)
    assert brfss.data['total_areas'] == 56 and len(brfss.data['without_value']) == 2
    assert {r['area']['name'] for r in brfss.data['without_value']} == {'Kentucky', 'Pennsylvania'}
    tracts = tools.get_measure_across_areas('acs:B19013_001E', 'tract', '06037', limit=300)
    assert tracts.data['total_areas'] == 2498
    assert len(tracts.data['without_value']) == 42
    assert {r['status'] for r in tracts.data['without_value']} == {'missing'}
    assert size_bytes(tracts) <= MAX_BYTES
    with SessionLocal() as db:
        published = lookup.measure_values_within(db, 'acs', 'B19013_001E', 'tract', '06037')['values']
    assert sum(r['status'] == 'available' for r in published) == 2440
    assert sum(r['status'] == 'open_ended' for r in published) == 16


def test_search_context_and_sources(staging):
    district = tools.find_places('WV-1')
    assert district.data['matches'][0]['geoid'] == '5401'
    assert district.data['matches'][0]['display_name'] == 'West Virginia 1st congressional district (119th Congress)'
    topic = tools.search_measures()
    assert 'ahrf' not in json.dumps(topic.data).lower()
    assert WITHHELD_TOPIC_WARNING in topic.warnings
    sources = tools.list_data_sources()
    assert len(sources.data['products']) == 8
    assert {p['product'] for p in sources.data['products']}.isdisjoint({'ahrf'})
    context = tools.get_area_context('county', '37145')
    assert len(context.data['facilities']['health_centers']['examples']) <= 10


def test_all_texas_counties_fit_client_size(staging):
    for sort in ('geoid', 'value_desc', 'value_asc'):
        result = tools.get_measure_across_areas('places:diabetes_crudeprev', 'county', '48', sort, 300)
        data = result.data
        assert data['total_areas'] == 254
        assert len(data['with_value']) == 253 and len(data['without_value']) == 1
        assert data['truncated'] is False
        assert size_bytes(result) <= MAX_BYTES
        assert size_bytes(result) == len(json.dumps(result.model_dump(mode='json'),
                                                 separators=(',', ':'), ensure_ascii=False).encode('utf-8'))
        assert data['measure']['uncertainty_kind'] == 'ci95'
        assert data['measure']['uncertainty_label'] == '95% confidence interval'
        assert all(set(r) <= {'area', 'value', 'status', 'status_text', 'uncertainty', 'notes', 'position'}
                   for r in data['with_value'])
        assert all(('position' in r) == (sort != 'geoid') for r in data['with_value'])


def test_cms_history_series_and_former_connecticut_counties(staging):
    series = tools.get_measure_over_time('county', '37145', 'cms_gv:std_payment_per_capita')
    assert [r['period'] for r in series.data['series']] == ['2019', '2020', '2021', '2022', '2023', '2024']
    assert series.data['series'][0]['note']
    assert series.data['series'][-1]['note'] is None
    assert any('boundary vintage differs' in w for w in series.warnings)
    assert {s['dataset_id'] for s in series.sources} == {
        'cms_om_geographic_variation', 'cms_om_geographic_variation:history'}
    assert size_bytes(series) <= MAX_BYTES
    ct = tools.get_measure_across_areas('cms_gv:readmission_rate', 'county', '09', period='2020')
    assert ct.data['total_areas'] == 8
    assert [r['area']['geoid'] for r in ct.data['with_value']] == [
        '09001', '09003', '09005', '09007', '09009', '09011', '09013', '09015']
    assert ct.data['measure']['note'] and ct.data['measure']['period'] == '2020'
    assert ct.sources[0]['dataset_id'].endswith(':history')


def test_unpublished_brfss_history_is_explained(staging):
    result = tools.get_area_values('state', ['54'], ['brfss:diabetes'], period='1999')
    assert result.data['values'] == [] and result.sources == []
    assert 'published periods: 2023' in result.warnings[0]
    published = tools.get_area_values('state', ['54'], ['brfss:diabetes'], period='2021')
    assert [v['period'] for v in published.data['values']] == ['2021']
    details = tools.get_measure_details(['cms_gv:std_payment_per_capita'])
    periods = details.data['measures'][0]['periods']
    assert periods[0]['period'] == '2024' and periods[0]['current']
    assert [p['period'] for p in periods if p['available']] == ['2024', '2023', '2022', '2021', '2020', '2019']
    search = tools.search_measures(query='std_payment_per_capita')
    assert search.data['measures'][0]['periods'] == ['2024', '2023', '2022', '2021', '2020', '2019']
    district = tools.get_measure_over_time('cd', '5401', 'acs_profile:total_population')
    assert len(district.data['series']) == 1
    assert district.data['unavailable_periods'] == []
    assert any('districts have no earlier periods' in w for w in district.warnings)


def test_http_client(staging):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(['.venv-mcp/bin/uvicorn', 'app.mcp_server.app:app', '--host', '127.0.0.1', '--port', str(port)],
                               cwd=os.path.dirname(os.path.dirname(__file__)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            if process.poll() is not None:
                pytest.fail('uvicorn exited before /healthz was ready')
            try:
                with urlopen(f'http://127.0.0.1:{port}/healthz', timeout=0.2) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            pytest.fail('uvicorn did not become ready')

        async def call():
            async with Client(f'http://127.0.0.1:{port}/mcp') as client:
                listed = await client.list_tools()
                assert len(listed.tools) == 14
                assert all(tool.output_schema and tool.annotations.read_only_hint is True
                           and tool.annotations.destructive_hint is False
                           and tool.annotations.idempotent_hint is True
                           and tool.annotations.open_world_hint is False for tool in listed.tools)
                result = await client.call_tool('get_measure_across_areas', {
                    'measure_key': 'places:diabetes_crudeprev', 'level': 'county',
                    'within': 'AL', 'sort': 'value_desc', 'limit': 5})
                assert not result.is_error
                assert result.structured_content is not None
                data = result.structured_content['data']
                assert len(data['with_value']) == 5
                assert ORDER_WARNING in result.structured_content['warnings']
                assert len(json.dumps(result.structured_content, separators=(',', ':'),
                                      ensure_ascii=False).encode('utf-8')) <= MAX_BYTES
                texas = await client.call_tool('get_measure_across_areas', {
                    'measure_key': 'places:diabetes_crudeprev', 'level': 'county',
                    'within': 'TX', 'sort': 'value_desc', 'limit': 300})
                assert not texas.is_error
                tx_data = texas.structured_content['data']
                assert tx_data['total_areas'] == 254
                assert len(tx_data['with_value']) == 253
                assert len(tx_data['without_value']) == 1
                assert tx_data['truncated'] is False
                assert len(json.dumps(texas.structured_content, separators=(',', ':'),
                                      ensure_ascii=False).encode('utf-8')) <= MAX_BYTES
        asyncio.run(call())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_funding_download_route(monkeypatch):
    import gzip
    from starlette.testclient import TestClient
    from app.mcp_server import app as mcp_app
    from app.funding_report.lookup import FundingLookupError, UnsupportedNOFOError
    class Session:
        def __enter__(self): return self
        def __exit__(self,*args): pass
    monkeypatch.setattr(mcp_app.db_module,'SessionLocal',lambda:Session())
    def resolve(db,key):
        if key=='unknown': raise FundingLookupError('Unknown CDC NOFO')
        if key=='hrsa': raise UnsupportedNOFOError('HRSA; only CDC NOFOs are supported')
        return {'nofo_key':'PS212102'}
    monkeypatch.setattr(mcp_app.funding_lookup,'resolve_nofo',resolve)
    monkeypatch.setattr(mcp_app.funding_lookup,'active_build',lambda db:{'build_id':9})
    monkeypatch.setattr(mcp_app.funding_lookup,'nofo_dataset',lambda db,key,flag:{'schema_version':'chip.nofo_recipient_profile.v1','subawards':{} if flag else None})
    mcp_app._DATASET_CACHE.clear()
    with TestClient(mcp_app.app) as client:
        result=client.get('/funding/nofo/PS21-2102.json?subawards=1')
        assert result.status_code==200
        assert result.headers['content-encoding']=='gzip'
        assert result.headers['cache-control']=='public, max-age=3600'
        assert result.headers['etag']=='"9-PS212102-1"'
        assert result.json()['subawards']=={}
        assert client.get('/funding/nofo/PS21-2102.json?subawards=1',headers={'If-None-Match':result.headers['etag']}).status_code==304
        assert client.get('/funding/nofo/unknown.json').status_code==404
        assert client.get('/funding/nofo/hrsa.json').status_code==422
        assert client.get('/funding/nofo/PS21-2102.json?subawards=bad').status_code==422
