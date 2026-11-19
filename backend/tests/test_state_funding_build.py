"""Read model selection and staging reconciliation."""
from decimal import Decimal
import pytest
from sqlalchemy import text
from app.db import SessionLocal
from app.state_funding.build import grant_name, is_state_government, state_code
from app.state_funding import lookup, build as build_module


def test_grant_name_priority():
    assert grant_name('Gov NOFO','CDC NOFO','TAGGS','Listing','Description','ID') == ('Gov NOFO','grants_gov_nofo_title')
    assert grant_name('', 'CDC NOFO','TAGGS','Listing','Description','ID') == ('CDC NOFO','cdc_funding_profiles_nofo_title')
    assert grant_name(None,None,'TAGGS','Listing','Description','ID') == ('TAGGS','taggs_award_title')
    assert grant_name(None,None,None,'Listing','Description','ID') == ('Listing','assistance_listing_title')
    assert grant_name(None,None,None,None,'Description','ID') == ('Description','award_description')


def test_unattributed_state_code():
    assert state_code(None)=="__"
    assert state_code("  ")=="__"
    assert state_code(" al ")=="AL"


def test_state_government_tri_state():
    assert is_state_government(None) is None
    assert is_state_government(['LOCAL GOVERNMENT']) is False
    assert is_state_government(['LOCAL GOVERNMENT','State Government']) is True
    assert is_state_government(['f'],contract=True) is False
    assert is_state_government(['f','t'],contract=True) is True


def test_build_refuses_live_by_default(monkeypatch):
    monkeypatch.setattr(build_module, 'DATABASE_URL', 'postgresql+psycopg://user:unused@localhost/places')
    with pytest.raises(RuntimeError, match='Refusing state funding build'):
        build_module.build()


def test_staging_reconciliation():
    try:
        with SessionLocal() as db:
            if db.execute(text('select current_database()')).scalar() != 'places_staging':
                pytest.skip('staging only')
            info=lookup.build_info(db)
            if not info:
                pytest.skip('no active state funding build')
            year=2026
            source=db.execute(text('select sum(transaction_obligated_amount) from cdc_funding.cdc_funding_awards where fiscal_year=:fy'),{'fy':year}).scalar()
            target=db.execute(text('select sum(amount) from state_funding.obligation where build_id=:id and fiscal_year=:fy'),{'id':info['build_id'],'fy':year}).scalar()
            assert abs(source-target) <= Decimal('.01')
            unattributed_source=db.execute(text("select sum(transaction_obligated_amount) from cdc_funding.cdc_funding_awards where fiscal_year=:fy and nullif(trim(recipient_state),'') is null"),{'fy':year}).scalar()
            unattributed_target=db.execute(text("select sum(amount) from state_funding.obligation where build_id=:id and fiscal_year=:fy and state='__'"),{'id':info['build_id'],'fy':year}).scalar()
            assert abs(unattributed_source-unattributed_target)<=Decimal('.01')
            filters={'funding_type':'all','award_type':'all','account':None,'recipient_type':'all'}
            summary=lookup.summary(db,'AL',year,filters,info)
            grants=lookup.grants(db,'AL',year,filters,info)
            assert abs(summary['totals']['total']-sum(a['total'] for a in summary['by_account']))<=.01
            assert abs(summary['totals']['total']-grants['sum_total'])<=.01
    except Exception as error:
        if 'connection' in str(error).lower():
            pytest.skip('staging unavailable')
        raise
