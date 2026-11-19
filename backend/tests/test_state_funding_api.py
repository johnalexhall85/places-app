"""State funding HTTP validation and export."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.db import SessionLocal
from app.state_funding.router import router
from app.state_funding import lookup

app=FastAPI()
app.include_router(router)
client=TestClient(app)


def test_bad_filters_422():
    assert client.get('/state-funding/v1/states/AL/summary?funding_type=wrong').status_code==422
    assert client.get('/state-funding/v1/states/AL/grants?page_size=17').status_code==422
    assert client.get('/state-funding/v1/states/AL/summary?account=bad').status_code in (404,422)


def test_unknown_state_404():
    assert client.get('/state-funding/v1/states/ZZ/summary').status_code==404
    assert client.get('/state-funding/v1/states/__/summary').status_code==404


def test_staging_csv_and_search():
    with SessionLocal() as db:
        if db.execute(text('select current_database()')).scalar()!='places_staging':
            pytest.skip('staging only')
        if not lookup.build_info(db):
            pytest.skip('no active build')
    response=client.get('/state-funding/v1/states/AL/grants.csv?fy=2026')
    assert response.status_code==200
    lines=response.text.splitlines()
    assert lines[0].startswith('# Source: USAspending')
    assert 'award_unique_key' in lines[1] and 'accounts' in lines[1]
    listed=client.get('/state-funding/v1/states/AL/grants?fy=2026').json()
    if not listed['rows']:
        pytest.skip('no Alabama grants in FY2026')
    row=listed['rows'][0]
    terms=f"{row['award_id']} {row['recipient_name'].split()[0]}"
    found=client.get('/state-funding/v1/states/AL/grants',params={'fy':2026,'q':terms})
    assert found.status_code==200
    assert any(r['award_unique_key']==row['award_unique_key'] for r in found.json()['rows'])
    absent=client.get('/state-funding/v1/states/AL/grants',params={'fy':2026,'q':terms+' impossibleword123'})
    assert absent.json()['total_rows']==0
