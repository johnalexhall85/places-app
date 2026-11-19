"""HTTP endpoints for CDC state funding profiles."""
import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from app.db import get_db
from . import lookup

router=APIRouter(prefix='/state-funding/v1',tags=['state-funding'])


def context(db,code,fy,funding_type,award_type,account,recipient_type):
    code=code.upper()
    build=lookup.build_info(db)
    if not re.fullmatch(r'[A-Z]{2}',code) or code=='__' or not build or not lookup.state_exists(db,code,build['build_id']):
        raise HTTPException(404,'State not found')
    years=lookup.fiscal_years(db)
    fy=fy if fy is not None else years['default']
    if fy not in years['fiscal_years']:
        raise HTTPException(422,'Fiscal year is not in this build')
    if account and not lookup.run(db,"""SELECT 1 FROM state_funding.obligation
        WHERE build_id=:id AND state=:code AND fiscal_year=:fy AND federal_account_symbol=:account LIMIT 1""",
        {'id':build['build_id'],'code':code,'fy':fy,'account':account}).first():
        raise HTTPException(422,'Federal account is not available for this state and fiscal year')
    filters={'funding_type':funding_type,'award_type':award_type,'account':account,'recipient_type':recipient_type}
    return code,fy,filters,build


@router.get('/fiscal-years')
def fiscal_years(db:Session=Depends(get_db)):
    return lookup.fiscal_years(db)


@router.get('/states/{code}/summary')
def summary(code:str,fy:int|None=Query(None,ge=2021,le=2026),
            funding_type:str=Query('all',pattern='^(all|regular|supplemental)$'),
            award_type:str=Query('all',pattern='^(all|grant|contract)$'),account:str|None=None,
            recipient_type:str=Query('all',pattern='^(all|state_government)$'),db:Session=Depends(get_db)):
    code,fy,filters,build=context(db,code,fy,funding_type,award_type,account,recipient_type)
    return lookup.summary(db,code,fy,filters,build)


@router.get('/states/{code}/grants')
def grants(code:str,fy:int|None=Query(None,ge=2021,le=2026),
           funding_type:str=Query('all',pattern='^(all|regular|supplemental)$'),
           award_type:str=Query('all',pattern='^(all|grant|contract)$'),account:str|None=None,
           recipient_type:str=Query('all',pattern='^(all|state_government)$'),q:str='',
           sort:str=Query('amount',pattern='^(amount|name|recipient)$'),
           dir:str=Query('desc',pattern='^(asc|desc)$'),page:int=Query(1,ge=1),
           page_size:int=Query(25),db:Session=Depends(get_db)):
    if page_size not in (25,50,100):
        raise HTTPException(422,'page_size must be 25, 50, or 100')
    code,fy,filters,build=context(db,code,fy,funding_type,award_type,account,recipient_type)
    return lookup.grants(db,code,fy,filters,build,q=q,sort=sort,direction=dir,page=page,page_size=page_size)


@router.get('/states/{code}/grants.csv')
def grants_csv(code:str,fy:int|None=Query(None,ge=2021,le=2026),
           funding_type:str=Query('all',pattern='^(all|regular|supplemental)$'),
           award_type:str=Query('all',pattern='^(all|grant|contract)$'),account:str|None=None,
           recipient_type:str=Query('all',pattern='^(all|state_government)$'),q:str='',
           sort:str=Query('amount',pattern='^(amount|name|recipient)$'),
           dir:str=Query('desc',pattern='^(asc|desc)$'),db:Session=Depends(get_db)):
    code,fy,filters,build=context(db,code,fy,funding_type,award_type,account,recipient_type)
    data=lookup.grants(db,code,fy,filters,build,q=q,sort=sort,direction=dir,all_rows=True)
    output=io.StringIO()
    output.write('# '+data['citation']+'\n')
    fields=['award_unique_key','award_id','award_type','grant_name','name_source','project_title','description','recipient_name','recipient_uei','is_state_government','fon','cfda_number','cfda_title','accounts','regular','supplemental','total','usaspending_url']
    writer=csv.DictWriter(output,fieldnames=fields)
    writer.writeheader()
    for row in data['rows']:
        writer.writerow(row|{'accounts':'; '.join(a['symbol']+' '+a['name'] for a in row['accounts'])})
    return Response(output.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="chip-cdc-funding-{code}-FY{fy}.csv"'})
