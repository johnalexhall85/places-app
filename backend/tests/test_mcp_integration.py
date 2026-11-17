"""Staging-only contract checks and one real Streamable HTTP client call."""
import asyncio
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
from app.mcp_server.config import ORDER_WARNING
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
    assert size_bytes(tracts) <= 60_000
    with SessionLocal() as db:
        published = lookup.measure_values_within(db, 'acs', 'B19013_001E', 'tract', '06037')['values']
    assert sum(r['status'] == 'available' for r in published) == 2440
    assert sum(r['status'] == 'open_ended' for r in published) == 16


def test_search_context_and_sources(staging):
    district = tools.find_places('WV-1')
    assert district.data['matches'][0]['geoid'] == '5401'
    assert district.data['matches'][0]['display_name'] == 'West Virginia 1st congressional district (119th Congress)'
    topic = tools.search_measures()
    assert 'ahrf' not in topic.model_dump_json().lower()
    sources = tools.list_data_sources()
    assert len(sources.data['products']) == 8
    assert {p['product'] for p in sources.data['products']}.isdisjoint({'ahrf'})
    context = tools.get_area_context('county', '37145')
    assert len(context.data['facilities']['health_centers']['examples']) <= 10


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
                assert len(listed.tools) == 7
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
        asyncio.run(call())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
