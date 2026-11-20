"""Read-only grant history assembled from the two active funding builds."""

from collections import defaultdict

from app.funding_report import lookup as funding_lookup
from .lookup import NEGATIVE_NOTE, build_info, money, run, state_name

NOTES = [
    "Amounts are net CDC obligations from USAspending (File C) for FY2021–FY2026. Earlier years are not included.",
    "A recipient's state is the state USAspending records for the recipient, not where services are delivered.",
    "Sub-award amounts are reported by prime recipients and are not additional federal funding.",
]


class GrantNotFound(ValueError):
    def __init__(self, detail, suggestions=None):
        super().__init__(detail)
        self.suggestions = suggestions or []


def _amount(rows):
    regular = money(sum(r['amount'] for r in rows if not r['is_supplemental']))
    supplemental = money(sum(r['amount'] for r in rows if r['is_supplemental']))
    return {'regular': regular, 'supplemental': supplemental, 'total': money(regular + supplemental)}


def _resolve(db, nofo):
    try:
        return funding_lookup.resolve_nofo(db, nofo)
    except funding_lookup.FundingLookupError as exc:
        message = str(exc)
        suggestions = message.split(' Suggestions: ', 1)[1].split(', ') if ' Suggestions: ' in message else []
        raise GrantNotFound(message.split(' Suggestions: ', 1)[0], suggestions) from exc


def grant_history(db, nofo):
    resolved = _resolve(db, nofo)
    build = build_info(db)
    if not build:
        raise GrantNotFound('No published state funding build is available.')
    key = resolved['nofo_key']
    rows = [dict(r) for r in run(db, """SELECT o.fiscal_year,o.state,o.award_unique_key,
        o.federal_account_symbol,o.federal_account_name,o.is_supplemental,o.amount,
        a.award_id,a.recipient_name,a.recipient_uei,a.is_state_government,a.project_title,
        a.cfda_number,a.cfda_title,a.usaspending_url,c.category_code,c.category_name,c.basis
        FROM state_funding.award a JOIN state_funding.obligation o USING(build_id,award_unique_key)
        JOIN state_funding.budget_category c USING(federal_account_symbol)
        WHERE a.build_id=:id AND a.award_type='grant' AND a.fon_key=:key
        ORDER BY o.fiscal_year,o.state,a.award_unique_key""",
        {'id': build['build_id'], 'key': key}).mappings()]
    if not rows:
        raise GrantNotFound('No CDC grant awards with obligations were found for this NOFO.')

    title = run(db, """SELECT title,source FROM state_funding.nofo_title WHERE fon_key=:key
        AND source IN ('grants_gov','cdc_funding_profiles')
        ORDER BY CASE source WHEN 'grants_gov' THEN 0 ELSE 1 END LIMIT 1""", {'key': key}).mappings().first()
    fy_rows = defaultdict(list)
    state_rows = defaultdict(list)
    award_rows = defaultdict(list)
    award_state_fy = defaultdict(list)
    category_rows = defaultdict(list)
    for row in rows:
        fy_rows[row['fiscal_year']].append(row)
        state_rows[(row['fiscal_year'], row['state'])].append(row)
        award_rows[row['award_unique_key']].append(row)
        award_state_fy[(row['award_unique_key'], row['fiscal_year'], row['state'])].append(row)
    latest = max((fy for fy, group in fy_rows.items() if _amount(group)['total'] > 0), default=max(fy_rows))
    latest_note = None if _amount(fy_rows[latest])['total'] > 0 else (
        'No fiscal year from FY2021 to FY2026 has a positive net obligation for this grant.')
    profiles = funding_lookup.award_profiles(db, key)
    subawards = funding_lookup.award_subaward_summaries(db, key)
    award_items = []
    for award_key, group in award_rows.items():
        first = group[0]
        profile = profiles.get(award_key) or {}
        years = sorted({r['fiscal_year'] for r in group})
        history = [{'fiscal_year': fy, **_amount([r for r in group if r['fiscal_year'] == fy])} for fy in years]
        current_states = sorted({r['state'] for r in group if r['fiscal_year'] == latest})
        if current_states:
            states = current_states
        else:
            past_year = years[-1]
            candidates = {s: _amount(g)['total'] for (a, fy, s), g in award_state_fy.items()
                          if a == award_key and fy == past_year}
            states = [sorted(candidates, key=lambda s: (-abs(candidates[s]), s))[0]]
        recipient_type = profile.get('recipient_class') or (
            '; '.join(profile.get('business_types') or []) if profile.get('business_types') else None)
        source = ('taggs_recipient_class' if profile.get('recipient_class') else
                  'usaspending_business_types' if recipient_type else 'none')
        for state in states:
            award_items.append({
                'award_unique_key': award_key, 'award_id': first['award_id'], 'state': state,
                'split_state': len(current_states) > 1, 'is_current': bool(current_states),
                'recipient_name': profile.get('recipient_name') or first['recipient_name'],
                'recipient_uei': profile.get('uei') or first['recipient_uei'],
                'city': (profile.get('address') or {}).get('city'),
                'recipient_type': recipient_type or 'Not stated', 'recipient_type_source': source,
                'is_state_government': first['is_state_government'],
                'project_title': profile.get('project_title') or first['project_title'],
                'latest_fy_amount': _amount(award_state_fy[(award_key, latest, state)]) if current_states else None,
                'history': history, 'all_years_total': _amount(group)['total'],
                'first_fy': years[0], 'last_fy': years[-1],
                'subawards': subawards.get(award_key, {'subawardee_count': 0, 'action_count': 0,
                                                      'reported_amount': 0.0}) if profile else None,
                'usaspending_url': first['usaspending_url'],
            })

    by_state = []
    for state in {a['state'] for a in award_items}:
        current = [a for a in award_items if a['state'] == state and a['is_current']]
        past = [a for a in award_items if a['state'] == state and not a['is_current']]
        amount = _amount(state_rows[(latest, state)]) if current else None
        by_state.append({'state': state, 'name': 'State not recorded' if state == '__' else state_name(state),
                         'latest_fy_total': amount['total'] if amount else None,
                         'regular': amount['regular'] if amount else None,
                         'supplemental': amount['supplemental'] if amount else None,
                         'current_count': len(current), 'past_count': len(past)})
    by_state.sort(key=lambda s: (s['state'] == '__', s['latest_fy_total'] is None,
                                 -(s['latest_fy_total'] or 0), s['name']))
    state_order = {s['state']: i for i, s in enumerate(by_state)}
    award_items.sort(key=lambda a: (state_order[a['state']], not a['is_current'],
                                    -(a['latest_fy_amount'] or {}).get('total', 0), a['recipient_name']))

    for row in fy_rows[latest]:
        category_rows[(row['category_code'], row['category_name'], row['basis'])].append(row)
    categories = [{'code': code, 'name': name, 'basis': basis, 'total': _amount(group)['total']}
                  for (code, name, basis), group in category_rows.items()]
    categories.sort(key=lambda c: (-abs(c['total']), c['name']))
    by_fy = []
    periods = (build['sources'] or {}).get('periods', {})
    for fy in range(2021, 2027):
        group = fy_rows[fy]
        by_fy.append({'fiscal_year': fy, **_amount(group),
                      'award_count': len({r['award_unique_key'] for r in group}),
                      'is_complete': 'P12' in periods.get(str(fy), 'FY'+str(fy)+' P12')})
    latest_awards = {a['award_unique_key'] for a in award_items if a['is_current']}
    recipients = lambda items: len({a['recipient_uei'] or a['recipient_name'] for a in items})
    current_items = [a for a in award_items if a['is_current']]
    latest_amount = _amount(fy_rows[latest])
    notes = list(NOTES)
    if latest_amount['supplemental'] < 0:
        notes.append(NEGATIVE_NOTE)
    incomplete = [f"FY{x['fiscal_year']}" for x in by_fy if not x['is_complete']]
    if incomplete:
        notes.append(f"The following fiscal years are not complete: {', '.join(incomplete)}.")
    cfda = defaultdict(set)
    for key_, group in award_rows.items():
        first = group[0]
        if first['cfda_number']:
            cfda[(first['cfda_number'], first['cfda_title'])].add(key_)
    offices = sorted({p['funding_office'] for p in profiles.values() if p.get('funding_office')})
    starts = [p['period_of_performance']['start'] for p in profiles.values()
              if (p.get('period_of_performance') or {}).get('start')]
    ends = [p['period_of_performance']['end'] for p in profiles.values()
            if (p.get('period_of_performance') or {}).get('end')]
    return {
        'nofo': {'nofo_key': key, 'fon_display': resolved['fon_display'],
                 'fon_variants': resolved['fon_variants'],
                 'grant_name': title['title'] if title else resolved['fon_display'],
                 'name_source': ('grants_gov_nofo_title' if title['source'] == 'grants_gov'
                                 else 'cdc_funding_profiles_nofo_title') if title else 'fon',
                 'cfda': [{'number': number, 'title': name, 'award_count': len(keys)}
                          for (number, name), keys in sorted(cfda.items())],
                 'awarding_offices': offices,
                 'period_of_performance': {'start_min': min(starts) if starts else None,
                                           'end_max': max(ends) if ends else None},
                 'categories': categories},
        'latest_fy': latest, 'latest_fy_period': periods.get(str(latest), f'FY{latest}'),
        'latest_fy_note': latest_note, 'fiscal_years': list(range(2026, 2020, -1)),
        'totals': {'latest_fy': {**latest_amount, 'award_count': len(latest_awards),
                                'recipient_count': recipients(current_items),
                                'state_count': len({a['state'] for a in current_items})},
                   'all_years': {'total': _amount(rows)['total'], 'award_count': len(award_rows),
                                 'recipient_count': recipients(award_items)}},
        'by_fiscal_year': by_fy, 'by_state': by_state, 'awards': award_items,
        'citation': (f"Source: USAspending · Award financial (File C), CDC · "
                     f"{periods.get(str(latest), f'FY{latest}')} · CHIP state funding build {build['build_id']}; "
                     'HHS TAGGS; Grants.gov'),
        'notes': notes,
        'build': {'state_funding_build_id': build['build_id'],
                  'funding_report_build_id': (funding_lookup.active_build(db) or {}).get('build_id'),
                  'method_version': 'grant-history-v1'},
    }


def grant_award(db, nofo, award_unique_key):
    history = grant_history(db, nofo)
    award = next((a for a in history['awards'] if a['award_unique_key'] == award_unique_key), None)
    if not award:
        raise GrantNotFound('Award not found under this CDC grant.')
    profile = funding_lookup.award_profiles(db, history['nofo']['nofo_key']).get(award_unique_key) or {}
    rows = run(db, """SELECT c.category_code code,c.category_name name,c.basis,
        o.federal_account_symbol symbol,max(o.federal_account_name) account_name,
        coalesce(sum(o.amount) FILTER (WHERE NOT o.is_supplemental),0) regular,
        coalesce(sum(o.amount) FILTER (WHERE o.is_supplemental),0) supplemental,
        sum(o.amount) total FROM state_funding.obligation o
        JOIN state_funding.budget_category c USING(federal_account_symbol)
        WHERE o.build_id=:id AND o.award_unique_key=:award AND o.fiscal_year=:fy
        GROUP BY c.category_code,c.category_name,c.basis,o.federal_account_symbol""",
        {'id': history['build']['state_funding_build_id'], 'award': award_unique_key,
         'fy': history['latest_fy']}).mappings()
    categories = {}
    for row in rows:
        item = categories.setdefault(row['code'], {'code': row['code'], 'name': row['name'],
            'basis': row['basis'], 'regular': 0, 'supplemental': 0, 'total': 0,
            'award_count': 1, 'accounts': []})
        for field in ('regular', 'supplemental', 'total'):
            item[field] = money(item[field] + row[field])
        item['accounts'].append({'symbol': row['symbol'], 'name': row['account_name'],
                                 'regular': money(row['regular']),
                                 'supplemental': money(row['supplemental']), 'total': money(row['total'])})
    return {**award, 'name_variants': profile.get('name_variants', []), 'parent': profile.get('parent'),
            'address': profile.get('address'), 'congressional_district': profile.get('congressional_district'),
            'congressional_district_source': profile.get('congressional_district_source'),
            'organization_type': profile.get('recipient_type'), 'business_types': profile.get('business_types'),
            'metro_status': profile.get('metro_status'),
            'abstract': profile.get('abstract_full') or profile.get('abstract'),
            'abstract_source': profile.get('abstract_source'), 'cfda': profile.get('cfda'),
            'funding_office': profile.get('funding_office'),
            'period_of_performance': profile.get('period_of_performance'),
            'categories': sorted(categories.values(), key=lambda c: -abs(c['total']))}
