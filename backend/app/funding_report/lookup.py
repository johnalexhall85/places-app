"""Only public read interface to the active funding_report build."""
from collections import Counter, defaultdict
from sqlalchemy import text
from .keys import nofo_key
from .method import caveats


class FundingLookupError(ValueError):
    pass


class UnsupportedNOFOError(FundingLookupError):
    pass


def _one(session, sql, params=None):
    return session.execute(text(sql), params or {}).mappings().first()


def _all(session, sql, params=None):
    return session.execute(text(sql), params or {}).mappings().all()


def active_build(session):
    row=_one(session,"""SELECT b.build_id,b.started_at,b.finished_at,b.method_version,b.sources,b.counts
      FROM funding_report.active_build a JOIN funding_report.build_run b ON b.build_id=a.build_id
      WHERE a.singleton AND b.status='complete'""")
    return dict(row) if row else None


def resolve_nofo(session, value):
    build=active_build(session)
    if build is None:
        raise FundingLookupError('No published funding build is available; retry later.')
    key=nofo_key(value)
    if key is None:
        raise FundingLookupError('Provide a CDC NOFO, such as CDC-RFA-PS21-2102.')
    row=_one(session,"""SELECT nofo_key,fon_display,fon_variants,summary,award_count,recipient_count
      FROM funding_report.nofo WHERE build_id=:id AND nofo_key=:key""",{'id':build['build_id'],'key':key})
    if row:
        result=dict(row)
        if not result['summary'].get('supported',False):
            raise UnsupportedNOFOError(f"{result['fon_display']} belongs to {result['summary'].get('opdiv') or 'another HHS operating division'}; only CDC NOFOs are supported.")
        return result
    suggestions=_all(session,"""SELECT fon_display FROM funding_report.nofo
      WHERE build_id=:id AND (nofo_key LIKE :prefix OR search_text LIKE :part)
      ORDER BY award_count DESC,fon_display LIMIT 5""",
      {'id':build['build_id'],'prefix':key[:4]+'%','part':'%'+str(value).strip().lower()[:40]+'%'})
    suffix=' Suggestions: '+', '.join(r['fon_display'] for r in suggestions) if suggestions else ''
    raise FundingLookupError('Unknown CDC NOFO.'+suffix)


def _rows(session, key):
    build=active_build(session)
    if build is None: raise FundingLookupError('No published funding build is available; retry later.')
    return _all(session,"""SELECT profile FROM funding_report.nofo_award
      WHERE build_id=:id AND nofo_key=:key ORDER BY state NULLS LAST, recipient_name,award_unique_key""",
      {'id':build['build_id'],'key':key})


def award_profiles(session, key):
    """Profiles keyed by the File C award key, in one read."""
    build = active_build(session)
    if not build:
        return {}
    rows = _all(session, """SELECT award_unique_key, profile FROM funding_report.nofo_award
        WHERE build_id=:id AND nofo_key=:key""", {'id': build['build_id'], 'key': key})
    return {row['award_unique_key']: row['profile'] for row in rows}


def award_subaward_summaries(session, key):
    """Use the stored deduplicated actions and the same prime matching as _subaward_block."""
    build = active_build(session)
    if not build:
        return {}
    rows = _all(session, """SELECT p.award_unique_key, s.action FROM funding_report.nofo_award p
        JOIN funding_report.nofo_subaward s ON s.build_id=p.build_id AND s.nofo_key=p.nofo_key
          AND s.prime_fain IN (p.fain,p.award_unique_key)
        WHERE p.build_id=:id AND p.nofo_key=:key""",
        {'id': build['build_id'], 'key': key})
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['award_unique_key']].append(row['action'])
    return {key: {
        'subawardee_count': len({a.get('subawardee_uei') or a.get('subawardee_name') for a in actions}),
        'action_count': len(actions),
        'reported_amount': round(sum(a.get('amount') or 0 for a in actions), 2),
    } for key, actions in grouped.items()}


def list_recipients(session, key, offset=0, limit=50):
    if not isinstance(offset,int) or offset<0 or not isinstance(limit,int) or not 1<=limit<=100:
        raise FundingLookupError('Use offset 0 or greater and limit between 1 and 100.')
    resolved=resolve_nofo(session,key)
    build=active_build(session)
    rows=_all(session,"""SELECT profile FROM funding_report.nofo_award WHERE build_id=:id AND nofo_key=:key
      ORDER BY state NULLS LAST,recipient_name,award_unique_key OFFSET :offset LIMIT :limit""",
      {'id':build['build_id'],'key':resolved['nofo_key'],'offset':offset,'limit':limit})
    return {'nofo_key':resolved['nofo_key'],'fon_display':resolved['fon_display'],
      'total':resolved['recipient_count'],'offset':offset,'limit':limit,
      'recipients':[{'recipient_name':p['recipient_name'],'state':p['address']['state'],
         'congressional_district':p['congressional_district'],'uei':p['uei'],'fain':p['fain'],
         'award_unique_key':p['award_unique_key'],'best_available_total':p['totals']['best_available'],
         'other_award_count':p['other_awards']['count']}
         for row in rows for p in [row['profile']] ]}


def recipient_profile(session,key,recipient):
    resolved=resolve_nofo(session,key)
    if not recipient or not isinstance(recipient,str):
        raise FundingLookupError('Provide a recipient UEI, FAIN, award key, or unique name substring.')
    build=active_build(session)
    params={'id':build['build_id'],'key':resolved['nofo_key'],'recipient':recipient.strip(),
            'substring':'%'+recipient.strip().lower()+'%'}
    exact=_all(session,"""SELECT profile FROM funding_report.nofo_award
      WHERE build_id=:id AND nofo_key=:key AND
      (uei=:recipient OR fain=:recipient OR award_unique_key=:recipient)
      ORDER BY recipient_name""",params)
    rows=exact if exact else _all(session,"""SELECT profile FROM funding_report.nofo_award
      WHERE build_id=:id AND nofo_key=:key AND lower(recipient_name) LIKE :substring
      ORDER BY recipient_name LIMIT 6""",params)
    if not rows: raise FundingLookupError('Recipient not found in this NOFO; use list_nofo_recipients to choose one.')
    if len(rows)>1: raise FundingLookupError('Recipient is ambiguous; use an exact FAIN or award key from list_nofo_recipients.')
    profile = rows[0]['profile']
    subrows = _all(session, """SELECT action FROM funding_report.nofo_subaward
      WHERE build_id=:id AND nofo_key=:key AND prime_fain=:fain""",
      {'id':build['build_id'],'key':resolved['nofo_key'],'fain':profile['fain']})
    _subaward_block(subrows, [profile])
    return profile


def _sum_nullable(values):
    vals=[v for v in values if v is not None]
    return round(sum(vals),2) if vals else None


def _subaward_block(rows,profiles):
    actions=[dict(r['action']) for r in rows]
    actions.sort(key=lambda x:(x.get('action_date') or '',x.get('prime_fain') or '',x.get('subaward_number') or ''))
    by_uei=defaultdict(list)
    for action in actions:
        by_uei[action.get('subawardee_uei') or action.get('subawardee_name') or '(unknown)'].append(action)
    subawardees=[]
    for uei,group in by_uei.items():
        fy=defaultdict(list)
        for x in group:
            if x['fiscal_year'] is not None: fy[x['fiscal_year']].append(x)
        names=sorted({x['subawardee_name'] for x in group if x['subawardee_name']})
        latest=group[-1]
        subawardees.append({'uei':latest['subawardee_uei'],'name':max(names,key=len) if names else None,
          'name_variants':names,'dba_names':sorted({x['dba_name'] for x in group if x.get('dba_name')}),
          'business_types':sorted({x['business_types'] for x in group if x.get('business_types')}),
          'address':latest['address'],'congressional_district':latest['congressional_district'],
          'prime_fains':sorted({x['prime_fain'] for x in group if x['prime_fain']}),
          'prime_recipients':sorted({x['prime_recipient'] for x in group if x['prime_recipient']}),
          'action_count':len(group),'reported_amount':round(sum(x['amount'] or 0 for x in group),2),
          'first_action_date':min(x['action_date'] for x in group if x['action_date']) if any(x['action_date'] for x in group) else None,
          'last_action_date':max(x['action_date'] for x in group if x['action_date']) if any(x['action_date'] for x in group) else None,
          'fiscal_years':[{'fiscal_year':y,'actions':len(v),'reported_amount':round(sum(x['amount'] or 0 for x in v),2)} for y,v in sorted(fy.items())],
          'description_examples':list(dict.fromkeys(x['description'] for x in group if x['description']))[:3]})
    subawardees.sort(key=lambda x:(-x['reported_amount'],x['name'] or ''))
    fy=defaultdict(list);states=defaultdict(set)
    for x in actions:
        if x['fiscal_year'] is not None: fy[x['fiscal_year']].append(x)
        if x.get('state'): states[x['state']].add(x['subawardee_uei'] or x['subawardee_name'])
    for p in profiles:
        matched=[x for x in actions if x['prime_fain']==p['fain']]
        p['subawards']={'subawardee_count':len({x['subawardee_uei'] or x['subawardee_name'] for x in matched}),
                        'action_count':len(matched),'reported_amount':round(sum(x['amount'] or 0 for x in matched),2)}
    return {'summary':{'distinct_subawardees':len(by_uei),'actions':len(actions),
       'raw_records':sum(x.get('raw_records',1) for x in actions),
       'duplicates_removed':sum(x.get('raw_records',1) for x in actions)-len(actions),
       'reported_amount':round(sum(x['amount'] or 0 for x in actions),2),
       'primes_with_subawards':len({x['prime_fain'] for x in actions})},
       'by_fiscal_year':[{'fiscal_year':y,'actions':len(v),
           'subawardees':len({x['subawardee_uei'] or x['subawardee_name'] for x in v}),
           'reported_amount':round(sum(x['amount'] or 0 for x in v),2)} for y,v in sorted(fy.items())],
       'by_state':[{'state':s,'subawardees':len(v)} for s,v in sorted(states.items())],
       'subawardees':subawardees,'actions':[{k:v for k,v in x.items() if k in
          ('prime_fain','prime_recipient','subaward_number','action_date','fiscal_year','amount','subawardee_uei',
           'subawardee_name','description','sam_report_ids','usaspending_url')} for x in actions]}


def nofo_dataset(session,key,include_subawards=False):
    resolved=resolve_nofo(session,key)
    build=active_build(session); id=build['build_id']; key=resolved['nofo_key']
    raw=_one(session,"SELECT * FROM funding_report.nofo WHERE build_id=:id AND nofo_key=:key",{'id':id,'key':key})
    profiles=[r['profile'] for r in _rows(session,key)]
    sub=None
    if include_subawards:
        rows=_all(session,"SELECT action FROM funding_report.nofo_subaward WHERE build_id=:id AND nofo_key=:key",
                  {'id':id,'key':key})
        sub=_subaward_block(rows,profiles)
    fy=defaultdict(list)
    for p in profiles:
        for x in p['fiscal_years']: fy[x['fiscal_year']].append(x)
    periods=[p['period_of_performance'] for p in profiles]
    cfda=defaultdict(list)
    for p in profiles:
        if p['cfda']['number']: cfda[(p['cfda']['number'],p['cfda']['title'])].append(p)
    no={'nofo_key':key,'fon_display':raw['fon_display'],'fon_variants':raw['fon_variants'],
        'awarding_agency':'Centers for Disease Control and Prevention',
        'awarding_offices':sorted({p['funding_office'] for p in profiles if p['funding_office']}),
        'cfda':[{'number':n,'title':t,'award_count':len(v)} for (n,t),v in sorted(cfda.items())],
        'period_of_performance':{'start_min':min((p['start'] for p in periods if p['start']),default=None),
                                 'end_max':max((p['end'] for p in periods if p['end']),default=None)},
        'award_count':raw['award_count'],'recipient_count':raw['recipient_count'],
        'fiscal_years':[{'fiscal_year':y,
          'account_obligation':_sum_nullable(x['account_obligation'] for x in rows),
          'award_obligation':_sum_nullable(x['award_obligation'] for x in rows),
          'taggs_amount':_sum_nullable(x['taggs_amount'] for x in rows),
          'is_complete':bool(build['sources'].get('account_fiscal_years',{}).get(str(y),{}).get('is_complete'))}
          for y,rows in sorted(fy.items())],
        'best_available_total':float(raw['best_available_total']) if raw['best_available_total'] is not None else None}
    def aggregate(field,label,include_total=False,include_other=False):
        groups=defaultdict(list)
        for p in profiles:
            val=p['address']['state'] if field=='state' else p.get(field)
            groups[val or '(unspecified)'].append(p)
        result=[]
        for val,group in groups.items():
            item={label:val,'recipients':len(group)}
            if include_total:
                item['nofo_total']=round(sum(p['totals']['best_available'] or 0 for p in group),2)
            if include_other:
                item['other_awards_top10_total']=round(sum(p['other_awards']['top10_total'] for p in group),2)
            result.append(item)
        return sorted(result,key=lambda x:(-x['recipients'],x[label]))
    tops=[d for p in profiles for d in p['other_awards']['top']]
    opdiv=defaultdict(list);aln=defaultdict(list)
    for d in tops:
        opdiv[d['opdiv'] or '(unspecified)'].append(d)
        aln[(d['aln'] or '(unspecified)',d['aln_title'])].append(d)
    aggregates={'by_state':aggregate('state','state',True,True),
      'by_recipient_class':aggregate('recipient_class','value',True),
      'by_recipient_type':aggregate('recipient_type','value'),
      'by_metro':aggregate('metro_status','value'),
      'other_awards_by_opdiv':sorted([{'opdiv':k,'awards':len(v),'total':round(sum(x['amount'] for x in v),2)}
                                     for k,v in opdiv.items()],key=lambda x:-x['total']),
      'other_awards_by_aln':sorted([{'aln':k[0],'title':k[1],'awards':len(v),
                                  'total':round(sum(x['amount'] for x in v),2)} for k,v in aln.items()],
                                  key=lambda x:-x['total'])[:15],
      'top_recipients_by_other_awards':sorted([{'award_unique_key':p['award_unique_key'],
          'recipient_name':p['recipient_name'],'state':p['address']['state'],
          'other_award_count':p['other_awards']['count'],
          'other_awards_top10_total':p['other_awards']['top10_total']} for p in profiles],
          key=lambda x:-x['other_awards_top10_total'])[:15],
      'other_awards_top10_total':round(sum(p['other_awards']['top10_total'] for p in profiles),2),
      'other_award_rows':len(tops),
      'recipients_without_other_awards':sum(p['other_awards']['count']==0 for p in profiles)}
    sources=build['sources']['sources']
    return {'schema_version':'chip.nofo_recipient_profile.v1',
       'build':{'build_id':id,'built_at':build['finished_at'].isoformat(),
                'method_version':build['method_version']},
       'sources':sources,'nofo':no,'aggregates':aggregates,
       'recipients':profiles,'subawards':sub,
       'caveats':caveats(sources,[x['fiscal_year'] for x in no['fiscal_years'] if not x['is_complete']])}


def nofo_overview(session,key,include_subawards=False):
    dataset=nofo_dataset(session,key,include_subawards)
    return {'nofo':dataset['nofo'],'aggregates':dataset['aggregates'],
       'subawards':dataset['subawards']['summary'] if dataset['subawards'] else None,
       'sources':dataset['sources'],'caveats':dataset['caveats']}
