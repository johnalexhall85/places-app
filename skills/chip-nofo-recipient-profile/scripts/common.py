"""Formatting and validation shared by the Word and Excel reports."""
from collections import Counter
from datetime import date
from decimal import Decimal
import re

MISSING = '—'
STATES = {
    'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California','CO':'Colorado',
    'CT':'Connecticut','DE':'Delaware','DC':'District of Columbia','FL':'Florida','GA':'Georgia',
    'HI':'Hawaii','ID':'Idaho','IL':'Illinois','IN':'Indiana','IA':'Iowa','KS':'Kansas','KY':'Kentucky',
    'LA':'Louisiana','ME':'Maine','MD':'Maryland','MA':'Massachusetts','MI':'Michigan','MN':'Minnesota',
    'MS':'Mississippi','MO':'Missouri','MT':'Montana','NE':'Nebraska','NV':'Nevada','NH':'New Hampshire',
    'NJ':'New Jersey','NM':'New Mexico','NY':'New York','NC':'North Carolina','ND':'North Dakota',
    'OH':'Ohio','OK':'Oklahoma','OR':'Oregon','PA':'Pennsylvania','RI':'Rhode Island',
    'SC':'South Carolina','SD':'South Dakota','TN':'Tennessee','TX':'Texas','UT':'Utah',
    'VT':'Vermont','VA':'Virginia','WA':'Washington','WV':'West Virginia','WI':'Wisconsin',
    'WY':'Wyoming','AS':'American Samoa','GU':'Guam','MP':'Northern Mariana Islands',
    'PR':'Puerto Rico','VI':'U.S. Virgin Islands'}


def shown(value):
    return MISSING if value is None or value == '' else str(value)


def dollars(value):
    return MISSING if value is None else f'${Decimal(str(value)):,.0f}'


def integer(value):
    return MISSING if value is None else f'{value:,}'


def period(start, end):
    return f'{shown(start)}–{shown(end)}'


def fiscal_range(years):
    ys = sorted(int(y['fiscal_year']) for y in years)
    return f'FY{ys[0]}–FY{ys[-1]}' if ys else MISSING


def title_for(data, override=None):
    if override:
        return override
    titles = Counter()
    for item in data['nofo']['cfda']:
        if item.get('title'):
            titles[item['title']] += item.get('award_count') or 1
    return titles.most_common(1)[0][0] if titles else 'CDC funding opportunity'


def short_abstract(text, limit=900):
    if not text:
        return MISSING
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(' ', 1)[0].rstrip(' ,.;:') + '…'


def short_fon(fon):
    return re.sub(r'^CDC-RFA-', '', fon, flags=re.I)


def validate(data):
    if data.get('schema_version') != 'chip.nofo_recipient_profile.v1':
        raise ValueError('Expected schema_version chip.nofo_recipient_profile.v1')
    for key in ('build', 'sources', 'nofo', 'aggregates', 'recipients', 'subawards', 'caveats'):
        if key not in data:
            raise ValueError(f'Missing required dataset key: {key}')
    for key in ('fon_display', 'recipient_count', 'fiscal_years', 'best_available_total', 'cfda', 'period_of_performance'):
        if key not in data['nofo']:
            raise ValueError(f'Missing required nofo key: {key}')
    for key in ('by_state', 'by_recipient_class', 'by_recipient_type', 'by_metro', 'other_awards_by_opdiv', 'other_awards_by_aln', 'top_recipients_by_other_awards', 'other_awards_top10_total', 'recipients_without_other_awards'):
        if key not in data['aggregates']:
            raise ValueError(f'Missing required aggregates key: {key}')
    for i, p in enumerate(data['recipients']):
        for key in ('recipient_name', 'address', 'fain', 'totals', 'fiscal_years', 'other_awards', 'period_of_performance'):
            if key not in p:
                raise ValueError(f'Missing required recipients[{i}] key: {key}')
    if data['subawards'] is not None:
        for key in ('summary', 'by_fiscal_year', 'by_state', 'subawardees', 'actions'):
            if key not in data['subawards']:
                raise ValueError(f'Missing required subawards key: {key}')
    date.fromisoformat(data.get('_prepared', date.today().isoformat()))
