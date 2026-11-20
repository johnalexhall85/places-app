"""Grant history grouping and the staging HTTP contract."""

import csv
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal
from app.state_funding import grant_history as gh
from app.state_funding import lookup
from app.state_funding.router import router


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


def _row(fy, state, award, amount, supplemental=False):
    return dict(fiscal_year=fy, state=state, award_unique_key=award, federal_account_symbol='075-1',
        federal_account_name='Account', is_supplemental=supplemental, amount=amount,
        award_id=award, recipient_name=award, recipient_uei=award, is_state_government=False,
        project_title='Project', cfda_number='93.939', cfda_title='Listing', usaspending_url=None,
        category_code='A', category_name='Category', basis='cdc_operating_plan')


@pytest.mark.parametrize('positive,expected,note', [(True, 2026, None), (False, 2026, True)])
def test_latest_year_split_state_past_and_recipient_type(monkeypatch, positive, expected, note):
    rows = [_row(2025, 'NY', 'none', 1 if positive else -1),
            _row(2025, 'NC', 'past', 20 if positive else -20),
            _row(2025, 'CA', 'split', 30 if positive else -30),
            _row(2026, 'CA', 'split', 7 if positive else -7),
            _row(2026, 'TX', 'split', 5 if positive else -5)]
    monkeypatch.setattr(gh, '_resolve', lambda db, key: {
        'nofo_key': 'TEST', 'fon_display': 'CDC-RFA-TEST', 'fon_variants': []})
    monkeypatch.setattr(gh, 'build_info', lambda db: {
        'build_id': 1, 'sources': {'periods': {'2025': 'FY2025 P12', '2026': 'FY2026 P12'}}})
    monkeypatch.setattr(gh, 'run', lambda db, sql, params=None: Rows([] if 'nofo_title' in sql else rows))
    monkeypatch.setattr(gh.funding_lookup, 'active_build', lambda db: {'build_id': 2})
    monkeypatch.setattr(gh.funding_lookup, 'award_profiles', lambda db, key: {
        'split': {'recipient_name': 'Current', 'uei': 'U1', 'address': {'city': 'City'},
                  'recipient_class': 'State Government', 'business_types': ['Business'],
                  'period_of_performance': {}, 'funding_office': None},
        'past': {'recipient_name': 'Past', 'uei': 'U2', 'address': {},
                 'business_types': ['Nonprofit', 'Other'], 'period_of_performance': {},
                 'funding_office': None},
    })
    monkeypatch.setattr(gh.funding_lookup, 'award_subaward_summaries', lambda db, key: {})
    data = gh.grant_history(None, 'TEST')
    assert data['latest_fy'] == expected
    assert bool(data['latest_fy_note']) == bool(note)
    if positive:
        split = [a for a in data['awards'] if a['award_unique_key'] == 'split']
        assert {a['state']: a['latest_fy_amount']['total'] for a in split} == {'CA': 7, 'TX': 5}
        assert all(a['split_state'] for a in split)
        past = next(a for a in data['awards'] if a['award_unique_key'] == 'past')
        assert past['state'] == 'NC' and past['latest_fy_amount'] is None
        assert split[0]['recipient_type_source'] == 'taggs_recipient_class'
        assert past['recipient_type'] == 'Nonprofit; Other'
        assert past['recipient_type_source'] == 'usaspending_business_types'
        no_profile = next(a for a in data['awards'] if a['award_unique_key'] == 'none')
        assert no_profile['recipient_type'] == 'Not stated'
        assert no_profile['recipient_type_source'] == 'none'
        assert no_profile['subawards'] is None
        assert sum(s['latest_fy_total'] or 0 for s in data['by_state']) == data['totals']['latest_fy']['total']


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def staging():
    try:
        with SessionLocal() as db:
            if db.execute(text('select current_database()')).scalar() != 'places_staging' or not lookup.build_info(db):
                pytest.skip('active places_staging build required')
    except Exception as exc:
        pytest.skip(f'staging unreachable: {type(exc).__name__}')


def test_staging_grant_api_csv_and_state_search():
    staging()
    response = client.get('/state-funding/v1/grants/CDC-RFA-PS21-2102')
    assert response.status_code == 200
    data = response.json()
    assert data['latest_fy'] == 2026
    assert data['totals']['latest_fy']['total'] == 10166689.0
    assert sum(s['latest_fy_total'] or 0 for s in data['by_state']) == data['totals']['latest_fy']['total']
    award = data['awards'][0]
    detail = client.get(f"/state-funding/v1/grants/PS212102/awards/{award['award_unique_key']}")
    assert detail.status_code == 200
    assert detail.json()['history']
    csv_response = client.get('/state-funding/v1/grants/CDC-RFA-PS21-2102.csv')
    assert csv_response.status_code == 200
    assert 'chip-cdc-grant-CDC-RFA-PS21-2102.csv' in csv_response.headers['content-disposition']
    lines = csv_response.text.splitlines()
    assert lines[0].startswith('# Source: USAspending')
    listed = list(csv.DictReader(io.StringIO('\n'.join(lines[1:]))))
    assert len(listed) == len(data['awards'])
    assert 'FY2026_total' in listed[0] and 'subawardee_count' in listed[0]
    unknown = client.get('/state-funding/v1/grants/CDC-RFA-PS21-9999')
    assert unknown.status_code == 404
    assert 'suggestions' in unknown.json()
    state = client.get('/state-funding/v1/states/CA/grants',
                       params={'fy': 2026, 'q': 'CDC-RFA-PS21-2102', 'page_size': 100})
    assert state.status_code == 200
    assert state.json()['total_rows'] > 0
    assert all(gh.funding_lookup.nofo_key(r['fon']) == 'PS212102' for r in state.json()['rows'])
