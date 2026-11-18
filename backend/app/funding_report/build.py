"""Rebuild the CDC funding report snapshot from source tables.

All source scans, joins, and monetary aggregates are set-based. Python projects the
resulting grouped rows into the versioned JSON contract.
"""
import argparse
from collections import defaultdict, Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.db import DATABASE_URL
from .method import best_available, district

KEY = "regexp_replace(upper(regexp_replace(coalesce(%s,''), '[^A-Za-z0-9]', '', 'g')), '^CDCRFA', '')"


def clean(value):
    return str(value).strip() if value is not None and str(value).strip() else None


def money(value):
    return float(value) if value is not None else None


def date(value):
    return str(value)[:10] if value else None


def first(*values):
    return next((clean(v) for v in values if clean(v)), None)


def longest(*values):
    found = [clean(v) for v in values if clean(v)]
    return max(found, key=len) if found else None


def abstract_without_title(description, title):
    description = clean(description)
    title = clean(title)
    if description and title:
        prefix = title + ' - '
        if description[:len(prefix)].casefold() == prefix.casefold():
            return clean(description[len(prefix):])
    return description


def preferred_cfda(rows, taggs_aln):
    """Pick the listing with the greatest award-level obligation."""
    taggs = clean(taggs_aln)
    if taggs and '.' not in taggs and len(taggs) == 5:
        taggs = taggs[:2] + '.' + taggs[2:]
    if not rows:
        return taggs, None
    selected = min(rows, key=lambda row: (-row['amount'], row['number'] != taggs, row['number']))
    return selected['number'], selected['title']


def query(session, sql, params=None):
    return session.execute(text(sql), params or {})


def stage(session):
    query(session, f"""CREATE TEMP TABLE fr_prime ON COMMIT DROP AS
        SELECT id, raw_record AS r, NULLIF(raw_record->>'assistance_award_unique_key','') AS auk,
          NULLIF(raw_record->>'award_id_fain','') AS fain,
          NULLIF({KEY % "raw_record->>'funding_opportunity_number'"},'') AS nofo_key,
          NULLIF(raw_record->>'action_date_fiscal_year','')::int AS fy,
          NULLIF(regexp_replace(coalesce(raw_record->>'federal_action_obligation',''),'[,$]','','g'),'')::numeric AS amount
        FROM cdc_funding.raw_usaspending_assistance_prime_transactions
        WHERE raw_record->>'assistance_award_unique_key' <> ''""")
    query(session, 'CREATE INDEX ON fr_prime (auk)')
    query(session, 'CREATE INDEX ON fr_prime (fain)')
    query(session, 'CREATE INDEX ON fr_prime (nofo_key)')
    query(session, f"""CREATE TEMP TABLE fr_fon ON COMMIT DROP AS
      SELECT nofo_key, fon, SUM(n) AS n, bool_or(cdc) AS cdc, max(opdiv) FILTER (WHERE NOT cdc) AS opdiv
      FROM (
        SELECT nofo_key, r->>'funding_opportunity_number' AS fon, count(*) AS n, true AS cdc, null::text AS opdiv
          FROM fr_prime WHERE nofo_key IS NOT NULL GROUP BY 1,2
        UNION ALL
        SELECT NULLIF({KEY % 'fon'},'') AS nofo_key, fon, count(*) AS n, opdiv='CDC' AS cdc, opdiv
          FROM taggs.raw_awards WHERE fon IS NOT NULL AND trim(fon) <> '' GROUP BY 1,2,4,5
      ) x WHERE nofo_key IS NOT NULL GROUP BY 1,2""")
    query(session, 'CREATE INDEX ON fr_fon (nofo_key)')
    query(session, f"""CREATE TEMP TABLE fr_cdc_fon_award ON COMMIT DROP AS
      SELECT DISTINCT NULLIF({KEY % 'fon'},'') AS nofo_key, award_number AS fain
      FROM taggs.raw_awards WHERE opdiv='CDC' AND fon IS NOT NULL AND trim(fon)<>''
        AND award_number IS NOT NULL""")
    query(session, 'CREATE INDEX ON fr_cdc_fon_award (fain)')
    query(session, """CREATE TEMP TABLE fr_prime_award ON COMMIT DROP AS
      SELECT DISTINCT auk,fain FROM fr_prime WHERE auk IS NOT NULL AND fain IS NOT NULL""")
    query(session, 'CREATE INDEX ON fr_prime_award (fain)')
    query(session, """CREATE TEMP TABLE fr_account_award ON COMMIT DROP AS
      SELECT DISTINCT award_unique_key AS auk,award_id_fain AS fain
      FROM cdc_funding.cdc_funding_awards WHERE award_id_fain IN (SELECT fain FROM fr_cdc_fon_award)
        AND award_unique_key IS NOT NULL""")
    query(session, 'CREATE INDEX ON fr_account_award (fain)')
    query(session, """CREATE TEMP TABLE fr_link ON COMMIT DROP AS
      SELECT DISTINCT nofo_key,auk,fain FROM (
        SELECT nofo_key,auk,fain FROM fr_prime WHERE nofo_key IS NOT NULL AND fain IS NOT NULL
        UNION ALL
        SELECT t.nofo_key,p.auk,p.fain FROM fr_cdc_fon_award t JOIN fr_prime_award p USING (fain)
        UNION ALL
        SELECT t.nofo_key,a.auk,a.fain FROM fr_cdc_fon_award t JOIN fr_account_award a USING (fain)
      ) l WHERE nofo_key IS NOT NULL AND auk IS NOT NULL""")
    query(session, 'CREATE INDEX ON fr_link (auk)')
    query(session, 'CREATE INDEX ON fr_link (fain)')
    query(session, 'CREATE INDEX ON fr_link (nofo_key)')
    query(session, """CREATE TEMP TABLE fr_account ON COMMIT DROP AS
      SELECT award_unique_key AS auk, fiscal_year AS fy, sum(transaction_obligated_amount) AS amount
      FROM cdc_funding.cdc_funding_awards WHERE award_unique_key IN (SELECT auk FROM fr_link)
      GROUP BY 1,2""")
    query(session, 'CREATE INDEX ON fr_account (auk)')
    query(session, """CREATE TEMP TABLE fr_award ON COMMIT DROP AS
      SELECT auk, fy, sum(amount) AS amount FROM fr_prime
      WHERE auk IN (SELECT auk FROM fr_link) AND fy IS NOT NULL GROUP BY 1,2""")
    query(session, 'CREATE INDEX ON fr_award (auk)')
    query(session, f"""CREATE TEMP TABLE fr_taggs ON COMMIT DROP AS
      SELECT award_number AS fain, NULLIF({KEY % 'fon'},'') AS nofo_key,
        funding_fiscal_year AS fy, sum(sum_of_actions) AS amount
      FROM taggs.raw_awards WHERE opdiv='CDC' AND award_number IN (SELECT fain FROM fr_link)
      GROUP BY 1,2,3""")
    query(session, 'CREATE INDEX ON fr_taggs (fain, nofo_key)')
    query(session, """CREATE TEMP TABLE fr_prime_latest ON COMMIT DROP AS
      SELECT DISTINCT ON (auk) auk, r FROM fr_prime WHERE auk IN (SELECT auk FROM fr_link)
      ORDER BY auk, (r->>'action_date') DESC NULLS LAST, id DESC""")
    query(session, 'CREATE INDEX ON fr_prime_latest (auk)')
    query(session, """CREATE TEMP TABLE fr_account_latest ON COMMIT DROP AS
      SELECT DISTINCT ON (award_unique_key) award_unique_key AS auk, recipient_name, recipient_uei,
        recipient_state, recipient_city, recipient_county, recipient_zip_code, recipient_parent_uei,
        recipient_parent_name, prime_award_summary_recipient_cd_current, prime_award_summary_recipient_cd_original,
        cfda_number, cfda_title, funding_office_name, period_of_performance_start_date,
        period_of_performance_current_end_date, prime_award_base_transaction_description
      FROM cdc_funding.cdc_funding_awards WHERE award_unique_key IN (SELECT auk FROM fr_link)
      ORDER BY award_unique_key, fiscal_year DESC, submission_period DESC""")
    query(session, 'CREATE INDEX ON fr_account_latest (auk)')
    query(session, """CREATE TEMP TABLE fr_taggs_latest ON COMMIT DROP AS
      SELECT DISTINCT ON (award_number) award_number AS fain, legal_entity_name, legal_entity_city,
        legal_entity_state, legal_entity_zip_code, legal_entity_county,
        legal_entity_country, legal_entity_congressional_district, uei, recipient_class,
        recipient_type, metro_non_metro, award_title, award_description, aln,
        assistance_listing_title, program_office, period_of_performance_start_date,
        period_of_performance_end_date
      FROM taggs.raw_awards WHERE award_number IN (SELECT fain FROM fr_link)
      ORDER BY award_number, action_issue_date DESC NULLS LAST, id DESC""")
    query(session, 'CREATE INDEX ON fr_taggs_latest (fain)')
    query(session, """CREATE TEMP TABLE fr_taggs_title ON COMMIT DROP AS
      SELECT DISTINCT ON (award_number) award_number AS fain, trim(award_title) AS title
      FROM taggs.raw_awards WHERE award_number IN (SELECT fain FROM fr_link)
        AND nullif(trim(award_title),'') IS NOT NULL
      GROUP BY award_number, trim(award_title)
      ORDER BY award_number, count(*) DESC, trim(award_title)""")
    query(session, 'CREATE INDEX ON fr_taggs_title (fain)')


def sources(session):
    account = query(session, """SELECT min(fiscal_year), max(fiscal_year), max(submission_period)
      FROM cdc_funding.cdc_funding_awards""").one()
    runs = query(session, """SELECT DISTINCT ON (fiscal_year) fiscal_year, import_status, manifest,
      completed_at FROM cdc_funding.cdc_funding_import_runs ORDER BY fiscal_year, id DESC""").mappings().all()
    prime_date = query(session, "SELECT max(r->>'action_date') FROM fr_prime").scalar()
    sub_date = query(session, "SELECT max(raw_record->>'subaward_action_date') FROM cdc_funding.raw_usaspending_assistance_subawards").scalar()
    taggs_run = query(session, """SELECT finished_at FROM taggs.ingestion_runs
      WHERE status='success' AND finished_at IS NOT NULL
      ORDER BY finished_at DESC, id DESC LIMIT 1""").scalar()
    taggs_years = query(session, "SELECT min(funding_fiscal_year),max(funding_fiscal_year) FROM taggs.raw_awards").one()
    periods = {str(r['fiscal_year']): {'period': max((x for x in (r['manifest'] or {}).get('periods', []) if x), default=None),
                'is_complete': bool((r['manifest'] or {}).get('is_complete', False)),
                'import_status': r['import_status']} for r in runs}
    for fy, period in query(session, 'SELECT fiscal_year, max(submission_period) FROM cdc_funding.cdc_funding_awards GROUP BY 1'):
        periods.setdefault(str(fy), {})['period'] = period
        periods[str(fy)]['is_complete'] = period is not None and period.endswith('P12') and periods[str(fy)].get('import_status') == 'completed'
    meta = {'account_fiscal_years': periods, 'prime_action_date': prime_date,
            'subaward_action_date': sub_date, 'taggs_loaded_at': date(taggs_run)}
    src = [
        {'id':'usaspending_account','publisher':'USAspending.gov','product':'Federal account award data (File C), CDC',
         'coverage':f'FY{account[0]}–FY{account[1]}','data_through':re.sub(r'(FY\d{4})P(\d+)',r'\1 P\2',account[2]) if account[2] else None},
        {'id':'usaspending_award','publisher':'USAspending.gov','product':'CDC assistance prime transactions',
         'coverage':'CDC assistance awards','data_through':prime_date},
        {'id':'taggs','publisher':'HHS TAGGS','product':'HHS award actions',
         'coverage':f'FY{taggs_years[0]}–FY{taggs_years[1]} funding fiscal years','data_through':None,
         'loaded_at':date(taggs_run)},
        {'id':'usaspending_subawards','publisher':'USAspending.gov','product':'Assistance sub-award reports',
         'coverage':'CDC prime-linked sub-awards','data_through':sub_date},
    ]
    for item in src:
        citation_coverage = item['coverage'].removesuffix(' funding fiscal years')
        item['citation'] = (f"Source: {item['publisher']} · {item['product']} · {citation_coverage} · "
                            + (f"loaded {item['loaded_at']}" if item.get('loaded_at') else
                               f"through {item['data_through']}" if item.get('data_through') else 'date not reported'))
    meta['sources'] = src
    return meta


def grouped_amounts(session, table):
    return {r['auk']: {int(x['fy']): money(x['amount']) for x in r['rows'] if x['fy'] is not None}
            for r in query(session, f"SELECT auk, jsonb_agg(jsonb_build_object('fy',fy,'amount',amount)) AS rows FROM {table} GROUP BY auk").mappings()}


def build_data(session, build_id, meta):
    account = grouped_amounts(session, 'fr_account')
    award = grouped_amounts(session, 'fr_award')
    taggs = {(r['fain'],r['nofo_key']): {int(x['fy']): money(x['amount']) for x in r['rows'] if x['fy'] is not None}
             for r in query(session, "SELECT fain,nofo_key,jsonb_agg(jsonb_build_object('fy',fy,'amount',amount)) rows FROM fr_taggs GROUP BY 1,2").mappings()}
    prime_names = {r['auk']: r['names'] or [] for r in query(session, """SELECT auk,
      array_agg(DISTINCT NULLIF(r->>'recipient_name','')) AS names FROM fr_prime
      WHERE auk IN (SELECT auk FROM fr_link) GROUP BY auk""").mappings()}
    account_names = {r['auk']: r['names'] or [] for r in query(session, """SELECT award_unique_key AS auk,
      array_agg(DISTINCT NULLIF(recipient_name,'')) AS names FROM cdc_funding.cdc_funding_awards
      WHERE award_unique_key IN (SELECT auk FROM fr_link) GROUP BY award_unique_key""").mappings()}
    taggs_names = {r['fain']: r['names'] or [] for r in query(session, """SELECT award_number AS fain,
      array_agg(DISTINCT NULLIF(legal_entity_name,'')) AS names FROM taggs.raw_awards
      WHERE award_number IN (SELECT fain FROM fr_link) GROUP BY award_number""").mappings()}
    titles = {r['fain']:r['title'] for r in query(session, 'SELECT fain,title FROM fr_taggs_title').mappings()}
    descriptions = {r['auk']:r['description'] for r in query(session, """SELECT DISTINCT ON (auk) auk,
      nullif(trim(r->>'transaction_description'),'') AS description FROM fr_prime
      WHERE auk IN (SELECT auk FROM fr_link) AND nullif(trim(r->>'transaction_description'),'') IS NOT NULL
      ORDER BY auk,length(trim(r->>'transaction_description')) DESC,id DESC""").mappings()}
    cfda_rows = defaultdict(list)
    for row in query(session, """SELECT auk, r->>'cfda_number' AS number, sum(amount) AS amount,
      (array_agg(nullif(r->>'cfda_title','') ORDER BY length(r->>'cfda_title') DESC NULLS LAST))[1] AS title
      FROM fr_prime WHERE auk IN (SELECT auk FROM fr_link) AND nullif(r->>'cfda_number','') IS NOT NULL
      GROUP BY auk, r->>'cfda_number'""").mappings():
        cfda_rows[row['auk']].append({'number':row['number'],'amount':row['amount'] or 0,'title':row['title']})
    links = query(session, """SELECT l.nofo_key,l.auk AS link_auk,l.fain,p.r AS prime,a.*,t.legal_entity_name,t.legal_entity_city,
      t.legal_entity_state,t.legal_entity_zip_code,t.legal_entity_county,t.legal_entity_country,
      t.legal_entity_congressional_district,t.uei AS taggs_uei,t.recipient_class,t.recipient_type,
      t.metro_non_metro,t.award_title,t.award_description,t.aln,t.assistance_listing_title,
      t.program_office,t.period_of_performance_start_date AS taggs_start,
      t.period_of_performance_end_date AS taggs_end
      FROM fr_link l LEFT JOIN fr_prime_latest p ON p.auk=l.auk
      LEFT JOIN fr_account_latest a ON a.auk=l.auk LEFT JOIN fr_taggs_latest t ON t.fain=l.fain
      ORDER BY l.nofo_key,l.auk""").mappings()
    nofo_rows = defaultdict(list)
    ueis = set()
    for row in links:
        r = row['prime'] or {}
        key, auk, fain = row['nofo_key'], row['link_auk'], row['fain']
        name = first(r.get('recipient_name'), row['recipient_name'], row['legal_entity_name']) or '(unknown recipient)'
        variants = sorted({clean(v) for v in
            [*prime_names.get(auk,[]),*account_names.get(auk,[]),*taggs_names.get(fain,[])] if clean(v)})
        name = max(variants, key=len) if variants else name
        uei = first(r.get('recipient_uei'), row['recipient_uei'], row['taggs_uei'])
        if uei: ueis.add(uei)
        current = first(r.get('prime_award_transaction_recipient_cd_current'), row['prime_award_summary_recipient_cd_current'])
        original = first(r.get('prime_award_transaction_recipient_cd_original'), row['prime_award_summary_recipient_cd_original'])
        cd, cd_source = district(current, original, row['legal_entity_congressional_district'])
        years = sorted(set(account.get(auk,{})) | set(award.get(auk,{})) | set(taggs.get((fain,key),{})))
        fy_rows = [{'fiscal_year':fy,'account_obligation':account.get(auk,{}).get(fy),
                    'award_obligation':award.get(auk,{}).get(fy),
                    'taggs_amount':taggs.get((fain,key),{}).get(fy)} for fy in years]
        account_total = sum(x or 0 for x in account.get(auk,{}).values()) if auk in account else None
        award_total = sum(x or 0 for x in award.get(auk,{}).values()) if auk in award else None
        taggs_total = sum(x or 0 for x in taggs.get((fain,key),{}).values()) if (fain,key) in taggs else None
        best,basis = best_available(account_total,award_total,taggs_total,auk in account,auk in award,(fain,key) in taggs)
        title = first(titles.get(fain), (first(r.get('prime_award_base_transaction_description'),
                      descriptions.get(auk),row['award_description']) or '').split(' - ',1)[0][:200])
        full_abstract = longest(*(abstract_without_title(value,title) for value in
            (descriptions.get(auk),r.get('transaction_description'),row['prime_award_base_transaction_description'])))
        taggs_abstract = clean(row['award_description'])
        cfda_number, cfda_title = preferred_cfda(cfda_rows.get(auk,[]),row['aln'])
        profile = {'award_unique_key':auk,'fain':fain,'uei':uei,'recipient_name':name,'name_variants':variants,
          'parent':{'uei':first(r.get('recipient_parent_uei'),row['recipient_parent_uei']),
                    'name':first(r.get('recipient_parent_name'),row['recipient_parent_name'])},
          'address':{'line1':clean(r.get('recipient_address_line_1')),'line2':clean(r.get('recipient_address_line_2')),
            'city':first(r.get('recipient_city_name'),row['recipient_city'],row['legal_entity_city']),
            'state':first(r.get('recipient_state_code'),row['recipient_state'],row['legal_entity_state']),
            'zip':first(r.get('recipient_zip_code'),row['recipient_zip_code'],row['legal_entity_zip_code']),
            'county':first(r.get('recipient_county_name'),row['recipient_county'],row['legal_entity_county']),
            'country':first(r.get('recipient_country_name'),row['legal_entity_country'])},
          'congressional_district':cd,'congressional_district_source':cd_source,
          'recipient_class':clean(row['recipient_class']),'recipient_type':clean(row['recipient_type']),
          'metro_status':clean(row['metro_non_metro']),
          'business_types':sorted(set(filter(None,[clean(r.get('business_types_description'))]))),
          'project_title':title,
          'abstract':taggs_abstract or full_abstract,
          'abstract_source':'taggs' if taggs_abstract else 'usaspending' if full_abstract else None,
          'abstract_full':full_abstract,
          'cfda':{'number':first(cfda_number,row['cfda_number'],row['aln']),
                  'title':first(cfda_title,row['cfda_title'],row['assistance_listing_title'])},
          'funding_office':first(r.get('funding_office_name'),row['funding_office_name'],row['program_office']),
          'period_of_performance':{'start':date(first(r.get('period_of_performance_start_date'),row['period_of_performance_start_date'],row['taggs_start'])),
                                   'end':date(first(r.get('period_of_performance_current_end_date'),row['period_of_performance_current_end_date'],row['taggs_end']))},
          'totals':{'account_obligation':account_total,'award_obligation':award_total,'taggs_amount':taggs_total,
                    'best_available':best,'best_available_basis':basis},'fiscal_years':fy_rows,
          'usaspending_url':f'https://www.usaspending.gov/award/{auk}/',
          'other_awards':{'count':0,'total':0.0,'top10_total':0.0,'top':[]},'subawards':None}
        nofo_rows[key].append(profile)
    return nofo_rows, ueis


def other_awards(session, build_id, ueis):
    # The join uses a temporary set of all NOFO recipient UEIs, never one query per UEI.
    query(session, 'CREATE TEMP TABLE fr_uei (uei text PRIMARY KEY) ON COMMIT DROP')
    session.execute(text('INSERT INTO fr_uei (uei) VALUES (:uei) ON CONFLICT DO NOTHING'), [{'uei':x} for x in ueis])
    rows = query(session, f"""SELECT t.uei,t.award_number, array_agg(DISTINCT NULLIF({KEY % 't.fon'},'')) FILTER (WHERE t.fon IS NOT NULL) AS nofo_keys,
      sum(t.sum_of_actions) AS amount, max(t.opdiv) AS opdiv,max(t.aln) AS aln,
      max(t.assistance_listing_title) AS aln_title,max(t.fon) AS fon,
      min(t.funding_fiscal_year) AS first_fiscal_year,max(t.funding_fiscal_year) AS last_fiscal_year,
      max(t.award_title) AS award_title
      FROM taggs.raw_awards t JOIN fr_uei u ON u.uei=t.uei
      WHERE t.award_number IS NOT NULL GROUP BY t.uei,t.award_number HAVING sum(t.sum_of_actions)>0""").mappings().all()
    inserts=[]; by_uei=defaultdict(list)
    for r in rows:
        d={k:r[k] for k in ('opdiv','aln','aln_title','fon','first_fiscal_year','last_fiscal_year','award_title')}
        d.update({'award_number':r['award_number'],'amount':money(r['amount'])})
        by_uei[r['uei']].append((r['nofo_keys'] or [],d))
        inserts.append({'build_id':build_id,'uei':r['uei'],'award_number':r['award_number'],
                        'nofo_keys':r['nofo_keys'] or [],'total_amount':r['amount'],'detail':json.dumps(d)})
    if inserts:
        session.execute(text("""INSERT INTO funding_report.uei_award
          (build_id,uei,award_number,nofo_keys,total_amount,detail)
          VALUES (:build_id,:uei,:award_number,:nofo_keys,:total_amount,CAST(:detail AS jsonb))"""),inserts)
    return by_uei


def subawards(session, build_id):
    rows = query(session, """SELECT l.nofo_key, s.raw_record AS r, s.id
      FROM cdc_funding.raw_usaspending_assistance_subawards s
      JOIN fr_link l ON l.fain=s.raw_record->>'prime_award_fain'
        OR l.auk=s.raw_record->>'prime_award_unique_key'
      ORDER BY l.nofo_key,s.id""").mappings()
    grouped=defaultdict(list)
    for row in rows:
        r=row['r']; amount=Decimal(str(first(r.get('subaward_amount')) or '0').replace(',',''))
        semantic=(row['nofo_key'],clean(r.get('prime_award_fain')),clean(r.get('subaward_number')),
                  date(r.get('subaward_action_date')),clean(r.get('subawardee_uei')),amount,
                  clean(r.get('subaward_description')))
        grouped[semantic].append(r)
    by_nofo=defaultdict(list); inserts=[]
    for (key,fain,number,action_date,uei,amount,description), group in grouped.items():
        r=group[-1]; ids=sorted({x.get('subaward_sam_report_id') for x in group if x.get('subaward_sam_report_id')})
        action={'prime_fain':fain,'prime_recipient':clean(r.get('prime_awardee_name')),
          'subaward_number':number,'action_date':action_date,
          'fiscal_year':int(r['subaward_action_date_fiscal_year']) if str(r.get('subaward_action_date_fiscal_year') or '').isdigit() else None,
          'amount':money(amount),'subawardee_uei':uei,'subawardee_name':clean(r.get('subawardee_name')),
          'description':description,'sam_report_ids':ids,'usaspending_url':clean(r.get('usaspending_permalink')),
          'raw_records':len(group),'state':clean(r.get('subawardee_state_code')),
          'address':{'line1':clean(r.get('subawardee_address_line_1')),'line2':None,'city':clean(r.get('subawardee_city_name')),
                     'state':clean(r.get('subawardee_state_code')),'zip':clean(r.get('subawardee_zip_code')),
                     'county':None,'country':clean(r.get('subawardee_country_name'))},
          'dba_name':clean(r.get('subawardee_dba_name')),'business_types':clean(r.get('subawardee_business_types')),
          'congressional_district':first(r.get('subaward_recipient_cd_current'),r.get('subaward_recipient_cd_original'))}
        action_key=hashlib.sha256(json.dumps([key,fain,number,action_date,uei,str(amount),description],
                                             ensure_ascii=False).encode()).hexdigest()
        by_nofo[key].append(action)
        inserts.append({'build_id':build_id,'nofo_key':key,'action_key':action_key,'prime_fain':fain or '',
                        'subawardee_uei':uei,'subawardee_name':action['subawardee_name'],'fiscal_year':action['fiscal_year'],
                        'amount':amount,'action':json.dumps(action)})
    if inserts:
        session.execute(text("""INSERT INTO funding_report.nofo_subaward
          (build_id,nofo_key,action_key,prime_fain,subawardee_uei,subawardee_name,fiscal_year,amount,action)
          VALUES (:build_id,:nofo_key,:action_key,:prime_fain,:subawardee_uei,:subawardee_name,:fiscal_year,:amount,CAST(:action AS jsonb))"""),inserts)
    return by_nofo


def write_model(session, build_id, meta, nofo_rows, by_uei, by_sub):
    fon_rows=query(session,"""SELECT nofo_key, array_agg(fon ORDER BY fon) AS variants,
      (array_agg(fon ORDER BY n DESC, length(fon) DESC, fon))[1] AS display,
      bool_or(cdc) AS supported, max(opdiv) FILTER (WHERE NOT cdc) AS opdiv
      FROM fr_fon GROUP BY nofo_key""").mappings().all()
    awards=[]; nofos=[]
    for fon in fon_rows:
        key=fon['nofo_key']; profiles=nofo_rows.get(key,[])
        if not fon['supported']:
            profiles=[]
        for p in profiles:
            others=[d for keys,d in by_uei.get(p['uei'],[]) if key not in keys]
            others.sort(key=lambda d:(-d['amount'],d['award_number']))
            p['other_awards']={'count':len(others),'total':sum(d['amount'] for d in others),
              'top10_total':sum(d['amount'] for d in others[:10]),
              'top':[dict(d,rank=i) for i,d in enumerate(others[:10],1)]}
            awards.append({'build_id':build_id,'nofo_key':key,'award_unique_key':p['award_unique_key'],
                'fain':p['fain'],'uei':p['uei'],'recipient_name':p['recipient_name'],
                'state':p['address']['state'],'best_available_total':p['totals']['best_available'],
                'profile':json.dumps(p)})
        years={x['fiscal_year'] for p in profiles for x in p['fiscal_years']}
        nofos.append({'build_id':build_id,'nofo_key':key,'fon_display':fon['display'],
          'fon_variants':fon['variants'],'award_count':len(profiles),
          'recipient_count':len({p['uei'] or p['award_unique_key'] for p in profiles}),
          'best_available_total':sum((p['totals']['best_available'] or 0) for p in profiles) if profiles else None,
          'first_fiscal_year':min(years) if years else None,'last_fiscal_year':max(years) if years else None,
          'search_text':' '.join([key]+fon['variants']).lower(),
          'summary':json.dumps({'supported':bool(fon['supported']),'opdiv':fon['opdiv'] if not fon['supported'] else 'CDC'})})
    session.execute(text("""INSERT INTO funding_report.nofo
      (build_id,nofo_key,fon_display,fon_variants,award_count,recipient_count,best_available_total,
       first_fiscal_year,last_fiscal_year,search_text,summary)
      VALUES (:build_id,:nofo_key,:fon_display,:fon_variants,:award_count,:recipient_count,
       :best_available_total,:first_fiscal_year,:last_fiscal_year,:search_text,CAST(:summary AS jsonb))"""),nofos)
    if awards:
        session.execute(text("""INSERT INTO funding_report.nofo_award
          (build_id,nofo_key,award_unique_key,fain,uei,recipient_name,state,best_available_total,profile)
          VALUES (:build_id,:nofo_key,:award_unique_key,:fain,:uei,:recipient_name,:state,
                  :best_available_total,CAST(:profile AS jsonb))"""),awards)
    return {'nofo':len(nofos),'nofo_award':len(awards),'uei_award':sum(map(len,by_uei.values())),
            'nofo_subaward':sum(map(len,by_sub.values()))}


def parse_arguments(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url',default=DATABASE_URL)
    parser.add_argument('--allow-live',action='store_true',
                        help='Allow a build outside places_staging after Gate B approval')
    args=parser.parse_args(argv)
    args.database=make_url(args.database_url).database
    if args.database != 'places_staging' and not args.allow_live:
        raise SystemExit('Refusing to build outside places_staging without --allow-live (Claude runs live builds after Gate B)')
    return args


def build_summary(build_id, database, start, counts):
    return {'build_id':build_id,'database':database,'status':'complete',
            'duration_seconds':round(time.monotonic()-start,2),'counts':counts}


def main():
    args=parse_arguments()
    engine=create_engine(args.database_url,pool_pre_ping=True)
    start=time.monotonic()
    with Session(engine) as s:
        build_id=query(s,"INSERT INTO funding_report.build_run (status,method_version) VALUES ('running','nofo-v1') RETURNING build_id").scalar_one()
        s.commit()
    try:
        with Session(engine) as s:
            stage(s)
            meta=sources(s)
            nofo_rows,ueis=build_data(s,build_id,meta)
            by_uei=other_awards(s,build_id,ueis)
            by_sub=subawards(s,build_id)
            counts=write_model(s,build_id,meta,nofo_rows,by_uei,by_sub)
            query(s,"""UPDATE funding_report.build_run SET status='complete',finished_at=now(),
              sources=CAST(:sources AS jsonb),counts=CAST(:counts AS jsonb) WHERE build_id=:id""",
              {'sources':json.dumps(meta),'counts':json.dumps(counts),'id':build_id})
            query(s,"""INSERT INTO funding_report.active_build (singleton,build_id)
              VALUES (true,:id) ON CONFLICT (singleton) DO UPDATE SET build_id=excluded.build_id,activated_at=now()""",{'id':build_id})
            query(s,"UPDATE funding_report.build_run SET status='superseded' WHERE status='complete' AND build_id<>:id",{'id':build_id})
            query(s,"""DELETE FROM funding_report.build_run WHERE build_id NOT IN
              (SELECT build_id FROM funding_report.build_run ORDER BY build_id DESC LIMIT 2)""")
            s.commit()
        print(json.dumps(build_summary(build_id,args.database,start,counts)))
    except Exception as exc:
        with Session(engine) as s:
            query(s,"UPDATE funding_report.build_run SET status='failed',finished_at=now(),notes=:note WHERE build_id=:id",
                  {'id':build_id,'note':str(exc)[:1000]})
            s.commit()
        raise


if __name__=='__main__':
    main()
