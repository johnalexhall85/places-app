"""Public catalog, topic filtering, and compact keyword search."""
import json
from pathlib import Path
from .config import PUBLIC_PRODUCTS, WITHHELD_TOPIC_WARNING

TOPICS_PATH = Path(__file__).resolve().parents[1] / 'community' / 'topics.json'
SYNONYMS = {
    'poverty': ('poverty', 'low income'), 'income': ('income', 'poverty'),
    'uninsured': ('uninsured', 'insurance', 'coverage'), 'insurance': ('uninsured', 'insurance', 'coverage'),
    'coverage': ('uninsured', 'insurance'), 'air': ('air', 'aqi'), 'aqi': ('aqi', 'air'),
    'food': ('food', 'snap', 'grocery'), 'snap': ('snap', 'food'), 'grocery': ('grocery', 'food'),
    'medicare': ('medicare', 'beneficiary'), 'diabetes': ('diabetes',),
    'blood pressure': ('blood pressure', 'hypertension'), 'hypertension': ('blood pressure', 'hypertension'),
    'smoking': ('smoking', 'tobacco'), 'tobacco': ('smoking', 'tobacco'),
    'obesity': ('obesity',), 'mental': ('mental', 'depression'), 'depression': ('depression', 'mental'),
    'doctors': ('physicians',), 'doctor': ('physician',),
}


def topics():
    raw = json.loads(TOPICS_PATH.read_text())
    result = []
    for topic in raw:
        keys = [f'{p}:{m}' for p, m in topic['measure_keys'] if p in PUBLIC_PRODUCTS]
        # A topic with only excluded measures should not leak its restricted description.
        if keys:
            result.append({**topic, 'measure_keys': keys, 'measure_count': len(keys)})
    return result


def public_catalog(catalog):
    return ([p for p in catalog['products'] if p['product'] in PUBLIC_PRODUCTS],
            [m for m in catalog['measures'] if m['product'] in PUBLIC_PRODUCTS])


def topic_map():
    mapping = {}
    for topic in topics():
        for key in topic['measure_keys']:
            mapping.setdefault(key, []).append(topic['title'])
    return mapping


def _matches_query(measure, tokens, topic_names):
    key = f"{measure['product']}:{measure['measure_id']}"
    haystack = ' '.join(str(x or '') for x in (
        measure['label'], measure['definition'], measure['measure_id'], measure.get('category'),
        measure['product_name'], *topic_names.get(key, []))).lower()
    return all(any(alt in haystack for alt in SYNONYMS.get(token, (token,))) for token in tokens)


def withheld_query_match(catalog, query, level=None):
    if not query or not query.strip():
        return False
    tokens = _tokens(query)
    return any(m['product'] == 'ahrf' and (not level or level in m['levels'])
               and _matches_query(m, tokens, {}) for m in catalog['measures'])


def _tokens(query):
    if not query:
        return []
    normalized = query.lower().strip()
    return [normalized] if normalized in SYNONYMS else normalized.split()


def search(catalog, query=None, topic=None, level=None, limit=25):
    products, measures = public_catalog(catalog)
    ts = topics()
    if query is None and topic is None and level is None:
        return {'measures': [], 'topics': [{'slug': t['slug'], 'title': t['title'],
                                           'summary': t['summary'], 'measure_count': t['measure_count']} for t in ts]}
    selected = next((t for t in ts if t['slug'] == topic), None) if topic else None
    if topic and selected is None:
        from mcp.server.mcpserver.exceptions import ToolError
        if topic == 'health-care-resources':
            raise ToolError(WITHHELD_TOPIC_WARNING)
        raise ToolError('Unknown topic; call search_measures with no arguments to list topics')
    allowed_keys = set(selected['measure_keys']) if selected else None
    topic_names = topic_map()
    tokens = _tokens(query)
    matches = []
    for m in measures:
        key = f"{m['product']}:{m['measure_id']}"
        if allowed_keys is not None and key not in allowed_keys:
            continue
        if level and level not in m['levels']:
            continue
        if tokens and not _matches_query(m, tokens, topic_names):
            continue
        matches.append({'measure_key': key, 'label': m['label'], 'product_name': m['product_name'],
                        'publisher': m['publisher'], 'unit': m['unit'], 'period': m['period'],
                        'population': m['population'], 'levels': m['levels'], 'topics': topic_names.get(key, [])})
    return {'measures': matches[:limit]}
