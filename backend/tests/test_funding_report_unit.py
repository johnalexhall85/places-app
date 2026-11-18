from app.funding_report.keys import nofo_key
from app.funding_report.method import best_available, caveats, dedupe_subawards, district


def test_nofo_key():
    assert nofo_key('CDC-RFA-PS21-2102') == nofo_key('PS21-2102') == nofo_key('ps 21 2102') == 'PS212102'
    assert nofo_key(None) is None
    assert nofo_key('---') is None


def test_best_available_basis_including_real_zero():
    assert best_available(0, 20, 30, True, True, True) == (0.0, 'account')
    assert best_available(None, 20, 30, False, True, True) == (20.0, 'award')
    assert best_available(None, None, 30, False, False, True) == (30.0, 'taggs')
    assert best_available(None, None, None) == (None, None)


def test_district_source_order():
    assert district('CA-12','CA-11','CA-10') == ('CA-12','usaspending_current')
    assert district(None,'CA-11','CA-10') == ('CA-11','usaspending_original')
    assert district(None,None,'CA-10') == ('CA-10','taggs')
    assert district(None,None,None) == (None,None)


def test_subaward_semantic_deduplication():
    a={'prime_fain':'P','subaward_number':'S','action_date':'2023-01-01','subawardee_uei':'U',
       'amount':100,'description':'Work','sam_report_ids':['1']}
    b=dict(a,sam_report_ids=['2'])
    c=dict(a,amount=200)
    rows=dedupe_subawards([a,b,c])
    assert len(rows)==2
    assert rows[0]['sam_report_ids']==['1','2']
    assert rows[0]['raw_records']==2


def test_caveats_include_source_dates_and_incomplete_fy():
    rows=caveats([{'publisher':'USAspending.gov','product':'File C','data_through':'FY2026 P12'}],[2027])
    assert any('not additional federal funding' in x for x in rows)
    assert any('not a complete federal portfolio' in x for x in rows)
    assert any('FY2026 P12' in x for x in rows)
    assert any('2027 is not complete' in x for x in rows)
