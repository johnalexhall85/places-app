"""Read only access to the active CDC state funding build."""
from __future__ import annotations

from sqlalchemy import text
from app.taggs.redo_ingest import STATE_CODE_TO_NAME

NEGATIVE_NOTE = "Supplemental amounts are negative when earlier emergency (for example COVID-19) obligations were reduced in this year."


def run(db, sql, params=None):
    return db.execute(text(sql), params or {})


def money(value):
    return round(float(value or 0), 2)


def build_info(db):
    row = run(db, """SELECT r.build_id,r.finished_at,r.method_version,r.sources
        FROM state_funding.active_build a JOIN state_funding.build_run r USING(build_id)
        WHERE a.singleton""").mappings().first()
    return dict(row) if row else None


def fiscal_years(db):
    build = build_info(db)
    if not build:
        return {"fiscal_years": [], "default": None, "periods": {}, "build": None}
    years = run(db,"SELECT DISTINCT fiscal_year FROM state_funding.obligation WHERE build_id=:id ORDER BY fiscal_year DESC",{"id":build['build_id']}).scalars().all()
    periods = (build['sources'] or {}).get('periods', {})
    return {"fiscal_years": years, "default": years[0] if years else None,
            "periods": periods, "build": {k:build[k] for k in ('build_id','finished_at','method_version')}}


def state_exists(db, code, build_id):
    return bool(run(db,"SELECT 1 FROM state_funding.obligation WHERE build_id=:id AND state=:code LIMIT 1",{'id':build_id,'code':code}).first())


def state_name(code):
    return STATE_CODE_TO_NAME.get(code, code).title().replace(" Of ", " of ")


def citation(fy, period, build_id):
    return f"Source: USAspending · Award financial (File C), CDC · {period or 'FY'+str(fy)} · CHIP build {build_id}"


def where(filters, *, include_account=True):
    sql = "o.build_id=:build_id AND o.state=:code AND o.fiscal_year=:fy"
    if filters['funding_type'] != 'all':
        sql += " AND o.is_supplemental=:supplemental"
    if filters['award_type'] != 'all':
        sql += " AND a.award_type=:award_type"
    if filters['recipient_type'] == 'state_government':
        sql += " AND a.is_state_government IS TRUE"
    if include_account and filters['account']:
        sql += " AND o.federal_account_symbol=:account"
    return sql


def params(code, fy, filters, build_id):
    return dict(build_id=build_id, code=code, fy=fy,
                supplemental=filters['funding_type']=='supplemental',
                award_type=filters['award_type'],account=filters['account'])


def summary(db, code, fy, filters, build):
    p = params(code,fy,filters,build['build_id'])
    clause = where(filters)
    rows = run(db, f"""SELECT o.federal_account_symbol symbol,max(o.federal_account_name) name,
        sum(o.amount) FILTER (WHERE NOT o.is_supplemental) regular,
        sum(o.amount) FILTER (WHERE o.is_supplemental) supplemental,
        sum(o.amount) total,count(DISTINCT o.award_unique_key) award_count,
        count(DISTINCT coalesce(nullif(a.recipient_uei,''),a.recipient_name)) recipient_count
        FROM state_funding.obligation o JOIN state_funding.award a USING(build_id,award_unique_key)
        WHERE {clause} GROUP BY o.federal_account_symbol""",p).mappings().all()
    accounts = run(db,f"""SELECT DISTINCT o.federal_account_symbol symbol,max(o.federal_account_name) name
        FROM state_funding.obligation o JOIN state_funding.award a USING(build_id,award_unique_key)
        WHERE {where(filters,include_account=False)} GROUP BY o.federal_account_symbol ORDER BY symbol""",p).mappings().all()
    overall = run(db,f"""SELECT sum(o.amount) total,
        sum(o.amount) FILTER (WHERE NOT o.is_supplemental) regular,
        sum(o.amount) FILTER (WHERE o.is_supplemental) supplemental,
        count(DISTINCT o.award_unique_key) award_count,
        count(DISTINCT o.award_unique_key) FILTER (WHERE a.award_type='grant') grant_count,
        count(DISTINCT coalesce(nullif(a.recipient_uei,''),a.recipient_name)) recipient_count
        FROM state_funding.obligation o JOIN state_funding.award a USING(build_id,award_unique_key)
        WHERE {clause}""",p).mappings().one()
    period = (build['sources'] or {}).get('periods',{}).get(str(fy),f'FY{fy}')
    return {"state":{"code":code,"name":state_name(code)},"fiscal_year":fy,"period":period,
      "filters":filters,"totals":{k:money(overall[k]) if k in ('total','regular','supplemental') else overall[k] for k in overall.keys()},
      "by_account":sorted([dict(r)|{k:money(r[k]) for k in ('regular','supplemental','total')} for r in rows],key=lambda r:-abs(r['total'])),
      "accounts_available":[dict(r) for r in accounts],"citation":citation(fy,period,build['build_id']),
      "notes":[NEGATIVE_NOTE] if (overall['supplemental'] or 0)<0 else []}


def grants(db, code, fy, filters, build, *, q='', sort='amount', direction='desc', page=1, page_size=25, all_rows=False):
    p=params(code,fy,filters,build['build_id'])
    terms=[x.lower() for x in q.split()]
    p.update({f'term{i}':f'%{term}%' for i,term in enumerate(terms)})
    search=''.join(f" AND a.search_text LIKE :term{i}" for i in range(len(terms)))
    order={'amount':'abs(sum(o.amount))','name':'a.grant_name','recipient':'a.recipient_name'}[sort]
    direction_sql='ASC' if direction=='asc' else 'DESC'
    limit='' if all_rows else ' LIMIT :page_size OFFSET :offset'
    p.update(page_size=page_size,offset=(page-1)*page_size)
    base=f"""FROM state_funding.obligation o JOIN state_funding.award a USING(build_id,award_unique_key)
       WHERE {where(filters)}{search}"""
    totals=run(db,f"""SELECT count(*) n,coalesce(sum(total),0) sum_total FROM
         (SELECT o.award_unique_key,sum(o.amount) total {base} GROUP BY o.award_unique_key) x""",p).mappings().one()
    rows=run(db,f"""SELECT a.award_unique_key,a.award_id,a.award_type,a.grant_name,a.name_source,
       a.project_title,a.description,a.recipient_name,a.recipient_uei,a.is_state_government,
       a.fon,a.cfda_number,a.cfda_title,a.usaspending_url,
       coalesce(sum(o.amount) FILTER (WHERE NOT o.is_supplemental),0) regular,
       coalesce(sum(o.amount) FILTER (WHERE o.is_supplemental),0) supplemental,
       sum(o.amount) total
       {base} GROUP BY a.build_id,a.award_unique_key ORDER BY {order} {direction_sql},a.award_unique_key {limit}""",p).mappings().all()
    result=[]
    account_map={}
    if rows:
        keys=[row['award_unique_key'] for row in rows]
        account_rows=run(db,f"""SELECT o.award_unique_key,o.federal_account_symbol symbol,max(o.federal_account_name) name,
           coalesce(sum(o.amount) FILTER (WHERE NOT o.is_supplemental),0) regular,
           coalesce(sum(o.amount) FILTER (WHERE o.is_supplemental),0) supplemental
           FROM state_funding.obligation o WHERE o.build_id=:build_id AND o.state=:code AND o.fiscal_year=:fy
           AND o.award_unique_key=ANY(:keys) {'AND o.is_supplemental=:supplemental' if filters['funding_type']!='all' else ''}
           {'AND o.federal_account_symbol=:account' if filters['account'] else ''}
           GROUP BY o.award_unique_key,o.federal_account_symbol ORDER BY o.award_unique_key,symbol""",p|{'keys':keys}).mappings()
        for a in account_rows:
            account_map.setdefault(a['award_unique_key'],[]).append({'symbol':a['symbol'],'name':a['name'],
              'regular':money(a['regular']),'supplemental':money(a['supplemental'])})
    for row in rows:
        item=dict(row)
        item['accounts']=account_map.get(item['award_unique_key'],[])
        for k in ('regular','supplemental','total'):
            item[k]=money(item[k])
        result.append(item)
    period=(build['sources'] or {}).get('periods',{}).get(str(fy),f'FY{fy}')
    return {'fiscal_year':fy,'filters':filters|{'q':q},'page':page,'page_size':page_size,
            'total_rows':totals['n'],'rows':result,'sum_total':money(totals['sum_total']),
            'citation':citation(fy,period,build['build_id'])}
