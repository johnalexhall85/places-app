"""Small, testable projections shared by the builder and lookup layer."""
from collections import defaultdict
from decimal import Decimal


def best_available(account, award, taggs, has_account=False, has_award=False, has_taggs=False):
    if has_account:
        return float(account or 0), 'account'
    if has_award:
        return float(award or 0), 'award'
    if has_taggs:
        return float(taggs or 0), 'taggs'
    return None, None


def district(current, original, taggs):
    for value, source in ((current, 'usaspending_current'), (original, 'usaspending_original'),
                          (taggs, 'taggs')):
        if value and str(value).strip():
            return str(value).strip(), source
    return None, None


def dedupe_subawards(rows):
    grouped = defaultdict(list)
    for row in rows:
        key = (row.get('prime_fain'), row.get('subaward_number'), row.get('action_date'),
               row.get('subawardee_uei'), str(Decimal(str(row.get('amount') or 0))),
               row.get('description'))
        grouped[key].append(row)
    result = []
    for group in grouped.values():
        item = dict(group[0])
        item['sam_report_ids'] = sorted({x for row in group for x in row.get('sam_report_ids', []) if x})
        item['raw_records'] = sum(row.get('raw_records', 1) for row in group)
        result.append(item)
    return result


def caveats(sources, incomplete_years=()):
    result = [
        'Sub-award amounts are reported by prime recipients and are not additional federal funding.',
        'Other federal awards are HHS awards in TAGGS only; the top 10 per recipient is shown, not a complete federal portfolio.',
    ]
    result.extend(f"{s['publisher']} {s['product']} data through {s.get('data_through') or 'unknown'}." for s in sources)
    result.extend(f'Fiscal year {year} is not complete.' for year in incomplete_years)
    return result
