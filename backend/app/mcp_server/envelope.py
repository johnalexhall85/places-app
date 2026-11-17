"""The public envelope and exact published value-row projection."""
import json
from typing import Any
from pydantic import BaseModel, Field
from .config import MAX_BYTES, RULES


class Envelope(BaseModel):
    data: dict[str, Any]
    sources: list[dict[str, Any]] = Field(default_factory=list)
    interpretation_rules: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def source(product, release):
    return {k: product.get(k) for k in ('dataset_id',)} | {
        'product': product['product'], 'product_name': product['name'], 'publisher': product['publisher'],
        'release_id': release.get('release_id'), 'source_release_id': release.get('source_release_id'),
        'published_at': release.get('published_at'), 'landing_page': product.get('landing_page')}


def citation(product, period, release):
    return (f"Source: {product['publisher']} · {product['name']} · {period} · "
            f"release {release.get('source_release_id')}")


def value_row(row, product, release, name=None):
    return {
        'measure_key': f"{row['product']}:{row['measure_id']}", 'label': row['label'],
        'area': {'level': row['level'], 'geoid': row['geoid'], 'name': name},
        'value': row['value'], 'unit': row['unit'], 'storage_scale': row.get('storage_scale'),
        'status': row['status'], 'status_text': row['status_text'], 'uncertainty': row['uncertainty'],
        'period': row['period'], 'population': row['population'], 'value_type': row['value_type'],
        'boundary_vintage': row.get('boundary_vintage'), 'release_id': row['release_id'],
        'notes': row.get('notes') or {}, 'source_credit': row.get('source_credit'),
        'citation': citation(product, row['period'], release),
    }


def compact_value_row(row, name=None, position=None, include_boundary=False,
                      shared_uncertainty_label=None, shared_uncertainty_kind=None):
    """Project one across-areas row; shared measure fields live in data.measure."""
    result = {
        'area': {'level': row['level'], 'geoid': row['geoid'], 'name': name},
        'value': row['value'], 'status': row['status'], 'status_text': row['status_text'],
        'uncertainty': row['uncertainty'].copy() if isinstance(row['uncertainty'], dict) else row['uncertainty'],
    }
    if shared_uncertainty_label is not None and isinstance(result['uncertainty'], dict):
        result['uncertainty'].pop('label', None)
    if shared_uncertainty_kind is not None and isinstance(result['uncertainty'], dict):
        result['uncertainty'].pop('kind', None)
    if row.get('notes'):
        result['notes'] = row['notes']
    if include_boundary:
        result['boundary_vintage'] = row.get('boundary_vintage')
    if position is not None:
        result['position'] = position
    return result


def build(data, products=(), warnings=()):
    used = [p for p in products if p.get('release')]
    rules = list(RULES)
    for product in used:
        rules.extend(rule for rule in product.get('limitations', []) if rule not in rules)
    return Envelope(data=data, sources=[source(p, p['release']) for p in used],
                    interpretation_rules=rules, warnings=list(warnings))


def size_bytes(result):
    structured_content = result.model_dump(mode='json') if isinstance(result, BaseModel) else result
    return len(json.dumps(structured_content, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))


def fit_rows(result, collection, warning='Response size limit reached; narrow the request.'):
    """Trim only the specified value-bearing collection; never remove missing rows."""
    rows = result.data[collection]
    if size_bytes(result) <= MAX_BYTES:
        return result
    result.data['truncated'] = True
    result.warnings.append(warning)
    while rows and size_bytes(result) > MAX_BYTES:
        rows.pop()
    if size_bytes(result) > MAX_BYTES:
        from mcp.server.mcpserver.exceptions import ToolError
        raise ToolError('Response exceeds the size limit even without values; narrow the request')
    return result
