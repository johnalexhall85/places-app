"""Name and district parsing built solely on approved lookup/search calls."""
import re
from app.area_pilot import lookup
from app.routers.search import search_counties

STATE_ABBR = dict(zip(
    'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR'.split(),
    '01 02 04 05 06 08 09 10 11 12 13 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 44 45 46 47 48 49 50 51 53 54 55 56 72'.split()))


def state_match(query, states):
    q = query.strip().lower()
    return next((s for s in states if q in (s['geoid'], s['name'].lower()) or STATE_ABBR.get(q.upper()) == s['geoid']), None)


def parse_district(query, states):
    """Return (state row, integer district) or None for supported human forms."""
    q = ' '.join(query.strip().split())
    match = re.fullmatch(r'([A-Za-z]{2})-(\d{1,2}|at-large)', q, re.I)
    if match:
        state = state_match(match[1], states)
        return (state, 0 if match[2].lower() == 'at-large' else int(match[2])) if state else None
    match = re.fullmatch(r'(.+?)\s+(?:(?:district|congressional district)\s+)?(\d{1,2})(?:st|nd|rd|th)?', q, re.I)
    if match:
        state = state_match(match[1], states)
        return (state, int(match[2])) if state else None
    match = re.fullmatch(r'(.+?)\s+at-large', q, re.I)
    if match:
        state = state_match(match[1], states)
        return (state, 0) if state else None
    return None


def ordinal(number):
    if number == 0:
        return 'at-large'
    suffix = 'th' if 10 <= number % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
    return f'{number}{suffix}'


def resolve_state(db, query):
    state = state_match(query, lookup.states(db))
    if state is None:
        from mcp.server.mcpserver.exceptions import ToolError
        raise ToolError('Unknown state; use find_places to look up its 2-digit GEOID')
    return state


def find(db, query, levels=None, limit=10):
    states = lookup.states(db)
    levels = levels or ['state', 'county', 'cd']
    matches = []
    if 'state' in levels:
        for state in states:
            if query.strip().lower() in (state['geoid'], state['name'].lower()) or STATE_ABBR.get(query.strip().upper()) == state['geoid'] or query.strip().lower() in state['name'].lower():
                matches.append({'level': 'state', 'geoid': state['geoid'], 'name': state['name'],
                                'state_name': state['name'], 'display_name': state['name']})
    if 'county' in levels:
        for county in search_counties(q=query, limit=limit, db=db):
            state = state_match(county['state_abbr'], states)
            state_name = state['name'] if state else None
            matches.append({'level': 'county', 'geoid': county['county_fips'], 'name': county['name'],
                            'state_name': state_name,
                            'display_name': f"{county['name']}{'' if county['name'].lower().endswith('county') else ' County'}, {state_name or county['state_abbr']}"})
    parsed = parse_district(query, states) if 'cd' in levels else None
    if parsed:
        state, number = parsed
        for district in lookup.state_districts(db, state['geoid']):
            code = str(district['district_code']).strip()
            if code.isdigit() and int(code) == number:
                matches.append({'level': 'cd', 'geoid': district['geoid'], 'name': district['name'],
                                'state_name': state['name'],
                                'display_name': f"{state['name']} {ordinal(number)} congressional district (119th Congress)"})
    return matches[:limit]
