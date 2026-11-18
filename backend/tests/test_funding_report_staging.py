import pytest
from app.db import SessionLocal
from app.funding_report import lookup


@pytest.fixture(scope='module')
def staging():
    with SessionLocal() as session:
        if lookup.active_build(session) is None:
            pytest.skip('No active funding_report build on staging')
    return True


def test_ps21_2102_dataset(staging):
    with SessionLocal() as session:
        d=lookup.nofo_dataset(session,'CDC-RFA-PS21-2102',False)
    assert d['schema_version']=='chip.nofo_recipient_profile.v1'
    assert set(d)=={'schema_version','build','sources','nofo','aggregates','recipients','subawards','caveats'}
    assert len(d['recipients'])==97
    assert d['nofo']['recipient_count']==97
    by_year={x['fiscal_year']:x['account_obligation'] for x in d['nofo']['fiscal_years']}
    assert [round(by_year[y]) for y in range(2021,2026)]==[42395995,49347654,52613214,42395995,42395995]
    assert abs(by_year[2026]-10166689)<2
    assert all(set(p)>= {'award_unique_key','fain','uei','recipient_name','address','totals','fiscal_years','other_awards','subawards'} for p in d['recipients'])
    by_source={x['id']:x for x in d['sources']}
    assert by_source['usaspending_account']['data_through']=='FY2026 P12'
    assert by_source['taggs']['data_through'] is None
    assert by_source['taggs']['loaded_at'] and 'loaded ' in by_source['taggs']['citation']
    assert 'unknown' not in ' '.join(d['caveats']).lower()
    assert any('awards first made after that date' in x for x in d['caveats'])


def test_reference_diagnostics(staging):
    with SessionLocal() as session:
        ps=lookup.nofo_dataset(session,'PS21-2102')
        ce=lookup.nofo_dataset(session,'CE23-2301',True)
    a=ps['aggregates']
    hrsa=next((x for x in a['other_awards_by_opdiv'] if x['opdiv']=='HRSA'),None)
    print('PS21 other top10',a['other_awards_top10_total'],'rows',a['other_award_rows'],'HRSA',hrsa)
    print('CE23 subawards',ce['subawards']['summary'])
    assert a['other_award_rows']==sum(len(p['other_awards']['top']) for p in ps['recipients'])
    assert hrsa['awards']==sum(x['opdiv']=='HRSA' for p in ps['recipients'] for x in p['other_awards']['top'])
    assert ce['subawards']['summary']['distinct_subawardees']==5
    assert ce['subawards']['summary']['actions']==14
    assert abs(ce['subawards']['summary']['reported_amount']-2181204.61)<0.01
