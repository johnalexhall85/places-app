"""Small, testable projections shared by the builder and lookup layer."""
from collections import defaultdict
from decimal import Decimal
from datetime import date
import re


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
    by_id = {s['id']:s for s in sources if 'id' in s}
    for source in sources:
        through = source.get('data_through')
        if source.get('id') == 'taggs':
            result.append(f"HHS TAGGS award actions cover {source['coverage']}; loaded {source['loaded_at']}." if source.get('loaded_at') else
                          f"HHS TAGGS award actions cover {source['coverage']}.")
        elif through:
            through = re.sub(r'(FY\d{4})\s*P(\d+)', r'\1 P\2', through)
            label = 'USAspending federal account award data (File C)' if source.get('id') == 'usaspending_account' else f"{source['publisher']} {source['product']}"
            suffix = '; FY' + through[2:6] + ' is complete' if source.get('id') == 'usaspending_account' and through.endswith('P12') else ''
            result.append(f'{label} runs through {through}{suffix}.')
    account = by_id.get('usaspending_account', {})
    award = by_id.get('usaspending_award', {})
    match = re.search(r'FY(\d{4})\s*P\d+', account.get('data_through') or '')
    through = award.get('data_through')
    if match and through:
        fiscal_year = int(match.group(1))
        # Federal fiscal years end September 30.
        if date.fromisoformat(through[:10]) < date(fiscal_year, 9, 30):
            result.append(f'Award-level USAspending data runs through {through}; CDC awards first made after that date are not yet linked to a funding opportunity, although their obligations appear in the account data.')
    result.extend(f'Fiscal year {year} is not complete.' for year in incomplete_years)
    return result
