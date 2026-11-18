import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from docx import Document
from openpyxl import load_workbook

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/render.py'


def fixture(subawards=True):
    def person(name,state,fain,amount,other):
        return {'award_unique_key':f'A_{fain}','fain':fain,'uei':'U'+fain,'recipient_name':name,
          'name_variants':[name],'address':{'line1':None,'city':'Town','state':state,'zip':None,'county':None},
          'congressional_district':None,'recipient_class':None,'recipient_type':None,'metro_status':None,
          'business_types':[],'project_title':None,'abstract':None,'cfda':{'number':'93.001','title':'Example'},
          'funding_office':None,'period_of_performance':{'start':'2021-01-01','end':'2022-12-31'},
          'totals':{'best_available':amount,'best_available_basis':'account'},
          'fiscal_years':[{'fiscal_year':2021,'account_obligation':amount,'award_obligation':None,'taggs_amount':None}],
          'usaspending_url':f'https://www.usaspending.gov/award/A_{fain}/',
          'other_awards':{'count':1 if other else 0,'total':other,'top10_total':other,
            'top':[{'rank':1,'award_number':'O1','amount':other,'opdiv':'CDC','aln':'93001','aln_title':'Example','fon':'OTHER','first_fiscal_year':2020,'last_fiscal_year':2021,'award_title':'Other'}] if other else []},
          'subawards':{'subawardee_count':1,'action_count':1,'reported_amount':50} if fain=='A1' and subawards else None}
    people=[person('Alpha','AL','A1',100,25),person('Beta','AL','A2',None,0),person('Gamma','CA','A3',200,0)]
    sub={'summary':{'distinct_subawardees':1,'actions':1,'raw_records':1,'duplicates_removed':0,'reported_amount':50,'primes_with_subawards':1},
      'by_fiscal_year':[{'fiscal_year':2021,'actions':1,'subawardees':1,'reported_amount':50}],
      'by_state':[{'state':'AL','subawardees':1}],
      'subawardees':[{'uei':'S1','name':'Sub A','address':{'city':'Town','state':'AL'},'congressional_district':None,'prime_fains':['A1'],'prime_recipients':['Alpha'],'action_count':1,'reported_amount':50,'first_action_date':'2021-05-01','last_action_date':'2021-05-01'}],
      'actions':[{'prime_fain':'A1','prime_recipient':'Alpha','subaward_number':'SA1','action_date':'2021-05-01','fiscal_year':2021,'amount':50,'subawardee_uei':'S1','subawardee_name':'Sub A','description':None,'sam_report_ids':['1'],'usaspending_url':None}]} if subawards else None
    return {'schema_version':'chip.nofo_recipient_profile.v1','build':{'build_id':7,'method_version':'nofo-v1'},
      'sources':[{'id':'usaspending_account','citation':'Source: USAspending.gov · File C · FY2021'}],
      'nofo':{'fon_display':'CDC-RFA-EX21-0001','awarding_agency':'CDC','awarding_offices':[],
        'cfda':[{'number':'93.001','title':'Example','award_count':3}],
        'period_of_performance':{'start_min':'2021-01-01','end_max':'2022-12-31'},
        'recipient_count':3,'best_available_total':300,'fiscal_years':[{'fiscal_year':2021,'account_obligation':300,'is_complete':True}]},
      'aggregates':{'by_state':[{'state':'AL','recipients':2},{'state':'CA','recipients':1}],
        'by_recipient_class':[],'by_recipient_type':[],'by_metro':[],
        'other_awards_by_opdiv':[{'opdiv':'CDC','total':25}],
        'other_awards_by_aln':[{'aln':'93001','total':25}],
        'top_recipients_by_other_awards':[], 'other_awards_top10_total':25,'other_award_rows':1,'recipients_without_other_awards':2},
      'recipients':people,'subawards':sub,'caveats':['Missing values are not zero.']}


def run(tmp_path,data):
    tmp_path.mkdir(parents=True,exist_ok=True)
    src=tmp_path/'data.json';src.write_text(json.dumps(data),encoding='utf-8')
    env=dict(os.environ,MPLCONFIGDIR=str(tmp_path/'mpl'))
    return subprocess.run([sys.executable,str(SCRIPT),'--dataset',str(src),'--out',str(tmp_path/'out'),'--prepared','2026-11-18'],capture_output=True,text=True,env=env)


def test_both_variants(tmp_path):
    for include in (True,False):
        d=fixture(include);result=run(tmp_path/d['nofo']['fon_display']/str(include),d)
        assert result.returncode==0,result.stderr
        meta=json.loads(result.stdout);assert meta['recipients']==3
        doc=Document(meta['docx']);heads=[p.text for p in doc.paragraphs if p.style and p.style.name.startswith('Heading')]
        assert 'Executive Summary' in heads and 'Alabama' in heads and 'California' in heads
        assert ('Sub-awardees' in heads)==include
        text='\n'.join(c.text for t in doc.tables for row in t.rows for c in row.cells)
        assert 'KEY FINDINGS' in text and 'About the Public Data Observatory' in text
        assert '—' in text and '$0' not in text
        wb=load_workbook(meta['xlsx']);names=wb.sheetnames
        assert names[:6]==['About','Recipient Summary','Funding by FY','FY Comparison','Other HHS Awards','Portfolio Analysis']
        assert ('Sub-awardees' in names)==include and ('Sub-award Actions' in names)==include
        assert wb['Funding by FY']['E5'].data_type=='f'
        assert wb['Recipient Summary']['L2'].data_type=='n'
        assert wb['Recipient Summary']['R2'].hyperlink is not None


def test_bad_schema_and_missing_key(tmp_path):
    d=fixture();d['schema_version']='wrong'
    result=run(tmp_path/'bad1',d);assert result.returncode and 'schema_version' in result.stderr
    d=fixture();del d['nofo']['fiscal_years']
    result=run(tmp_path/'bad2',d);assert result.returncode and 'Missing required nofo key' in result.stderr
